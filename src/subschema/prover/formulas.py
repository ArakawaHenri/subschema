"""
Formula IR for schema language-difference proof problems.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Literal

from subschema.contracts import UnsupportedDiagnostic, UnsupportedDisposition
from subschema.ir import (
    ApplicatorNode,
    AssertionAtom,
    IRAssertionKind,
    LogicalSchemaIR,
    SchemaNode,
    UnsupportedNode,
)
from subschema.ir.evaluation import EvaluationFrontier
from subschema.ir.terms import SchemaTerm

FormulaPolarity = Literal["negative", "positive"]
FormulaSide = Literal["lhs", "rhs"]
_CONDITIONAL_APPLICATOR_KINDS = frozenset({"else", "if", "then"})
_PURE_APPLICATOR_KINDS = ("allOf", "anyOf", "not", "oneOf")
_PURE_APPLICATOR_KIND_SET = frozenset(_PURE_APPLICATOR_KINDS)

__all__ = [
    "AndFormula",
    "AssertionFormula",
    "BottomFormula",
    "DifferenceFormula",
    "EvaluationEffectFormula",
    "ExactlyOneFormula",
    "FormulaOccurrence",
    "FormulaNode",
    "FormulaPolarity",
    "FormulaSide",
    "GuardedFormula",
    "NotFormula",
    "OrFormula",
    "ReferenceFormula",
    "TopFormula",
    "UnsupportedFormula",
    "lower_schema_formula",
    "lower_schema_term_formula",
    "occurrence_assertion_formula",
]


@dataclass(frozen=True)
class TopFormula:
    """Formula node accepting every JSON instance."""


@dataclass(frozen=True)
class BottomFormula:
    """Formula node accepting no JSON instance."""


@dataclass(frozen=True)
class AndFormula:
    children: tuple[FormulaNode, ...]
    source: SchemaNode | None = None
    applicator_kind: str | None = None
    polarity: FormulaPolarity | None = None
    applicator: ApplicatorNode | None = None


@dataclass(frozen=True)
class OrFormula:
    children: tuple[FormulaNode, ...]
    source: SchemaNode | None = None
    applicator_kind: str | None = None
    polarity: FormulaPolarity | None = None
    applicator: ApplicatorNode | None = None


@dataclass(frozen=True)
class NotFormula:
    child: FormulaNode
    source: SchemaNode | None = None
    applicator_kind: str | None = None
    polarity: FormulaPolarity | None = None
    applicator: ApplicatorNode | None = None


@dataclass(frozen=True)
class ExactlyOneFormula:
    children: tuple[FormulaNode, ...]
    source: SchemaNode | None = None
    applicator_kind: str | None = None
    polarity: FormulaPolarity | None = None
    applicator: ApplicatorNode | None = None


@dataclass(frozen=True)
class GuardedFormula:
    condition: FormulaNode
    then_branch: FormulaNode | None = None
    else_branch: FormulaNode | None = None
    source: SchemaNode | None = None
    applicator_kind: str | None = None
    polarity: FormulaPolarity | None = None
    applicator: ApplicatorNode | None = None
    condition_node: SchemaNode | None = None
    then_node: SchemaNode | None = None
    else_node: SchemaNode | None = None


@dataclass(frozen=True)
class AssertionFormula:
    source: SchemaNode
    assertion: AssertionAtom


@dataclass(frozen=True)
class ReferenceFormula:
    source: SchemaNode
    target: str | None = None
    dynamic: bool = False


@dataclass(frozen=True)
class EvaluationEffectFormula:
    source: SchemaNode
    frontier: EvaluationFrontier


@dataclass(frozen=True)
class UnsupportedFormula:
    diagnostic: UnsupportedDiagnostic


type FormulaNode = (
    AndFormula
    | AssertionFormula
    | BottomFormula
    | EvaluationEffectFormula
    | ExactlyOneFormula
    | GuardedFormula
    | NotFormula
    | OrFormula
    | ReferenceFormula
    | TopFormula
    | UnsupportedFormula
)


@dataclass(frozen=True)
class FormulaOccurrence:
    """A schema occurrence inside L(lhs) intersect complement(L(rhs))."""

    side: FormulaSide
    polarity: FormulaPolarity
    ir: LogicalSchemaIR

    @property
    def root(self) -> SchemaNode:
        return self.ir.root

    @cached_property
    def formula(self) -> FormulaNode:
        return lower_schema_formula(self)

    @property
    def unsupported_diagnostics(self) -> tuple[UnsupportedDiagnostic, ...]:
        return tuple(
            UnsupportedDiagnostic(
                category=node.category,
                reason=node.reason,
                keyword=node.keyword,
                path=node.path,
                side=self.side,
                disposition=_unsupported_node_disposition(node),
            )
            for node in self.ir.root.all_unsupported
        )


@dataclass(frozen=True)
class DifferenceFormula:
    """Formula for satisfiability of L(lhs) intersect complement(L(rhs))."""

    lhs: LogicalSchemaIR
    rhs: LogicalSchemaIR
    formula_override: FormulaNode | None = None
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None

    @cached_property
    def positive_lhs(self) -> FormulaOccurrence:
        return FormulaOccurrence("lhs", "positive", self.lhs)

    @cached_property
    def negative_rhs(self) -> FormulaOccurrence:
        return FormulaOccurrence("rhs", "negative", self.rhs)

    @property
    def occurrences(self) -> tuple[FormulaOccurrence, FormulaOccurrence]:
        return (self.positive_lhs, self.negative_rhs)

    @cached_property
    def formula(self) -> FormulaNode:
        if self.formula_override is not None:
            return self.formula_override
        return _and((self.positive_lhs.formula, self.negative_rhs.formula))

    @property
    def unsupported_diagnostics(self) -> tuple[UnsupportedDiagnostic, ...]:
        return _dedupe_diagnostics(
            self.positive_lhs.unsupported_diagnostics
            + self.negative_rhs.unsupported_diagnostics
            + _unsupported_diagnostics_in_formula(self.formula)
        )

    @property
    def unsupported_reason(self) -> str:
        return "; ".join(
            sorted({diagnostic.format() for diagnostic in self.unsupported_diagnostics})
        )

    def occurrence(self, side: FormulaSide) -> FormulaOccurrence:
        return self.positive_lhs if side == "lhs" else self.negative_rhs


def lower_schema_formula(occurrence: FormulaOccurrence) -> FormulaNode:
    return _formula_for_node(occurrence.root, occurrence.side, occurrence.polarity)


def lower_schema_term_formula(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
    side: FormulaSide,
    polarity: FormulaPolarity,
    *,
    lhs_ir: LogicalSchemaIR | None = None,
    rhs_ir: LogicalSchemaIR | None = None,
) -> FormulaNode:
    match term.kind:
        case "true":
            return TopFormula() if polarity == "positive" else BottomFormula()
        case "false":
            return BottomFormula() if polarity == "positive" else TopFormula()
        case "node":
            if term.ref is None:
                return UnsupportedFormula(
                    UnsupportedDiagnostic(
                        category="semantic-keyword",
                        reason="schema term is missing node ref",
                        side=side,
                    )
                )
            term_ir = _ir_for_term_scope(term, ir, lhs_ir=lhs_ir, rhs_ir=rhs_ir)
            if term_ir is None:
                return UnsupportedFormula(
                    UnsupportedDiagnostic(
                        category="semantic-keyword",
                        reason="schema term requires unavailable scoped IR",
                        side=side,
                    )
                )
            node = term_ir.node_for_ref(term.ref)
            if node is None:
                return UnsupportedFormula(
                    UnsupportedDiagnostic(
                        category="semantic-keyword",
                        reason="schema term requires unavailable IR node",
                        side=side,
                    )
                )
            return _formula_for_node(node, side, polarity)
        case "all_of":
            if polarity == "positive":
                return _and(
                    tuple(
                        lower_schema_term_formula(
                            child,
                            ir,
                            side,
                            "positive",
                            lhs_ir=lhs_ir,
                            rhs_ir=rhs_ir,
                        )
                        for child in term.children
                    )
                )
            return _or(
                tuple(
                    lower_schema_term_formula(
                        child,
                        ir,
                        side,
                        "negative",
                        lhs_ir=lhs_ir,
                        rhs_ir=rhs_ir,
                    )
                    for child in term.children
                )
            )
        case "any_of":
            if polarity == "positive":
                return _or(
                    tuple(
                        lower_schema_term_formula(
                            child,
                            ir,
                            side,
                            "positive",
                            lhs_ir=lhs_ir,
                            rhs_ir=rhs_ir,
                        )
                        for child in term.children
                    )
                )
            return _and(
                tuple(
                    lower_schema_term_formula(
                        child,
                        ir,
                        side,
                        "negative",
                        lhs_ir=lhs_ir,
                        rhs_ir=rhs_ir,
                    )
                    for child in term.children
                )
            )
        case "one_of":
            return ExactlyOneFormula(
                tuple(
                    lower_schema_term_formula(
                        child,
                        ir,
                        side,
                        "positive",
                        lhs_ir=lhs_ir,
                        rhs_ir=rhs_ir,
                    )
                    for child in term.children
                )
            )
        case "not":
            if len(term.children) != 1:
                return UnsupportedFormula(
                    UnsupportedDiagnostic(
                        category="semantic-keyword",
                        reason="not schema term requires exactly one child",
                        side=side,
                    )
                )
            return lower_schema_term_formula(
                term.children[0],
                ir,
                side,
                "negative" if polarity == "positive" else "positive",
                lhs_ir=lhs_ir,
                rhs_ir=rhs_ir,
            )


def _ir_for_term_scope(
    term: SchemaTerm,
    default_ir: LogicalSchemaIR,
    *,
    lhs_ir: LogicalSchemaIR | None,
    rhs_ir: LogicalSchemaIR | None,
) -> LogicalSchemaIR | None:
    match term.scope:
        case "lhs":
            return lhs_ir
        case "rhs":
            return rhs_ir
        case None:
            return default_ir


def occurrence_assertion_formula(
    occurrence: FormulaOccurrence,
    kind: IRAssertionKind,
) -> AssertionFormula | None:
    if (
        occurrence.polarity == "negative"
        and not _negative_occurrence_can_expose_root_assertions(occurrence.root)
    ):
        return None

    assertion = occurrence.ir.semantics.assertion(kind)
    if assertion is None:
        return None
    return AssertionFormula(occurrence.root, assertion)


def _formula_for_node(
    node: SchemaNode,
    side: FormulaSide,
    polarity: FormulaPolarity,
) -> FormulaNode:
    if polarity == "negative":
        return _negative_formula_for_node(node, side)
    return _positive_formula_for_node(node, side)


def _positive_formula_for_node(node: SchemaNode, side: FormulaSide) -> FormulaNode:
    if node.boolean_value is True:
        return TopFormula()
    if node.boolean_value is False:
        return BottomFormula()

    parts: list[FormulaNode] = [
        AssertionFormula(node, assertion) for assertion in node.semantics.assertions()
    ]

    static_reference = _reference_formula(node)
    if static_reference is not None:
        parts.append(static_reference)

    conditional_selection = _positive_conditional_selection_formula(node, side)
    if conditional_selection is not None:
        parts.append(conditional_selection)
    else:
        conditional = _guarded_formula(node, side)
        if conditional is not None:
            parts.append(conditional)

    parts.extend(
        _positive_applicator_formula(applicator, side, source=node)
        for applicator in node.applicators
        if applicator.kind not in {"else", "if", "then"}
    )

    if (
        node.evaluation.has_local_sources
        or node.evaluation.requires_evaluation_tracking
    ):
        parts.append(EvaluationEffectFormula(node, node.evaluation))

    parts.extend(
        _unsupported_formula(side, unsupported) for unsupported in node.all_unsupported
    )

    return _and(tuple(parts))


def _negative_formula_for_node(node: SchemaNode, side: FormulaSide) -> FormulaNode:
    if node.boolean_value is True:
        return BottomFormula()
    if node.boolean_value is False:
        return TopFormula()

    if _node_has_only_applicators(node, {"not"}):
        applicator = _first_applicator_node(node, "not")
        if applicator is not None:
            child = _single_applicator_child(applicator)
            if child is not None:
                return _and(
                    _conjunction_children_for_metadata_wrapper(
                        _positive_formula_for_node(child, side)
                    ),
                    source=node,
                    applicator_kind="not",
                    polarity="negative",
                    applicator=applicator,
                )

    if _node_has_only_applicators(node, {"allOf"}):
        applicator = _first_applicator_node(node, "allOf")
        if applicator is not None:
            return _or(
                tuple(
                    _negative_formula_for_node(child, side)
                    for child in applicator.children
                ),
                source=node,
                applicator_kind="allOf",
                polarity="negative",
                applicator=applicator,
            )

    if _node_has_only_applicators(node, {"anyOf"}):
        applicator = _first_applicator_node(node, "anyOf")
        if applicator is not None:
            return _and(
                tuple(
                    _negative_formula_for_node(child, side)
                    for child in applicator.children
                ),
                source=node,
                applicator_kind="anyOf",
                polarity="negative",
                applicator=applicator,
            )

    if _node_has_only_applicators(node, {"oneOf"}):
        applicator = _first_applicator_node(node, "oneOf")
        if applicator is not None:
            return ExactlyOneFormula(
                tuple(
                    _positive_formula_for_node(child, side)
                    for child in applicator.children
                ),
                source=node,
                applicator_kind="oneOf",
                polarity="negative",
                applicator=applicator,
            )
        return _unsupported_complement(
            side, "oneOf", "negative oneOf requires exact branch-cardinality planning"
        )

    if _node_has_only_applicators(node, {"else", "if", "then"}):
        if _first_applicator_child(node, "if") is None:
            return BottomFormula()
        conditional_selection = _negative_conditional_selection_formula(node, side)
        if conditional_selection is not None:
            return conditional_selection
        conditional = _negative_guarded_formula(node, side)
        if conditional is not None:
            return conditional
        return _unsupported_complement(
            side, "if", "negative conditionals require guarded branch-product planning"
        )

    mixed_applicator = _mixed_negative_applicator_node(node)
    if mixed_applicator is not None:
        return NotFormula(
            _positive_formula_for_node(node, side),
            source=node,
            applicator_kind=mixed_applicator.kind,
            polarity="negative",
            applicator=mixed_applicator,
        )

    mixed_conditional = _mixed_negative_conditional_node(node)
    if mixed_conditional is not None:
        return NotFormula(
            _positive_formula_for_node(node, side),
            source=node,
            applicator_kind="if",
            polarity="negative",
            applicator=mixed_conditional,
        )

    return NotFormula(
        _positive_formula_for_node(node, side), source=node, polarity="negative"
    )


def _positive_applicator_formula(
    applicator: ApplicatorNode,
    side: FormulaSide,
    *,
    source: SchemaNode,
) -> FormulaNode:
    kind = applicator.kind
    children = applicator.children
    if kind == "allOf":
        return _and(
            tuple(_positive_formula_for_node(child, side) for child in children),
            source=source,
            applicator_kind="allOf",
            polarity="positive",
            applicator=applicator,
        )
    if kind == "anyOf":
        return _or(
            tuple(_positive_formula_for_node(child, side) for child in children),
            source=source,
            applicator_kind="anyOf",
            polarity="positive",
            applicator=applicator,
        )
    if kind == "oneOf":
        return ExactlyOneFormula(
            tuple(_positive_formula_for_node(child, side) for child in children),
            source=source,
            applicator_kind="oneOf",
            polarity="positive",
            applicator=applicator,
        )
    if kind == "not" and len(children) == 1:
        return NotFormula(
            _positive_formula_for_node(children[0], side),
            source=source,
            applicator_kind="not",
            polarity="positive",
            applicator=applicator,
        )
    return _unsupported_complement(
        side, str(kind), f"{kind} applicator requires a dedicated formula rule"
    )


def _guarded_formula(node: SchemaNode, side: FormulaSide) -> GuardedFormula | None:
    condition = _first_applicator_child(node, "if")
    if condition is None:
        return None

    then_branch = _first_applicator_child(node, "then")
    else_branch = _first_applicator_child(node, "else")
    return GuardedFormula(
        _positive_formula_for_node(condition, side),
        None if then_branch is None else _positive_formula_for_node(then_branch, side),
        None if else_branch is None else _positive_formula_for_node(else_branch, side),
        source=node,
        applicator_kind="if",
        polarity="positive",
        applicator=_first_applicator_node(node, "if"),
        condition_node=condition,
        then_node=then_branch,
        else_node=else_branch,
    )


def _positive_conditional_selection_formula(
    node: SchemaNode, side: FormulaSide
) -> FormulaNode | None:
    target = _selected_boolean_conditional_branch(node)
    if target is _NO_CONDITIONAL_SELECTION:
        return None
    if target is None:
        return TopFormula()
    if not isinstance(target, SchemaNode):
        return None
    return _positive_formula_for_node(target, side)


def _negative_conditional_selection_formula(
    node: SchemaNode, side: FormulaSide
) -> FormulaNode | None:
    target = _selected_boolean_conditional_branch(node)
    if target is _NO_CONDITIONAL_SELECTION:
        return None
    if target is None:
        return BottomFormula()
    if not isinstance(target, SchemaNode):
        return None
    return _negative_formula_for_node(target, side)


_NO_CONDITIONAL_SELECTION = object()


def _selected_boolean_conditional_branch(
    node: SchemaNode,
) -> SchemaNode | None | object:
    condition = _first_applicator_child(node, "if")
    if condition is None or condition.boolean_value is None:
        return _NO_CONDITIONAL_SELECTION
    if condition.boolean_value:
        return _first_applicator_child(node, "then")
    return _first_applicator_child(node, "else")


def _negative_guarded_formula(
    node: SchemaNode, side: FormulaSide
) -> GuardedFormula | None:
    condition = _first_applicator_child(node, "if")
    if condition is None:
        return None

    then_branch = _first_applicator_child(node, "then")
    else_branch = _first_applicator_child(node, "else")
    return GuardedFormula(
        _positive_formula_for_node(condition, side),
        None if then_branch is None else _negative_formula_for_node(then_branch, side),
        None if else_branch is None else _negative_formula_for_node(else_branch, side),
        source=node,
        applicator_kind="if",
        polarity="negative",
        applicator=_first_applicator_node(node, "if"),
        condition_node=condition,
        then_node=then_branch,
        else_node=else_branch,
    )


def _reference_formula(node: SchemaNode) -> ReferenceFormula | None:
    static_reference = node.semantics.reference.static_reference
    if static_reference.ref is None:
        return None
    return ReferenceFormula(node, target=static_reference.ref)


def _and(
    children: tuple[FormulaNode, ...],
    *,
    source: SchemaNode | None = None,
    applicator_kind: str | None = None,
    polarity: FormulaPolarity | None = None,
    applicator: ApplicatorNode | None = None,
) -> FormulaNode:
    if not children:
        return TopFormula()
    if (
        len(children) == 1
        and source is None
        and applicator_kind is None
        and polarity is None
        and applicator is None
    ):
        return children[0]
    return AndFormula(children, source, applicator_kind, polarity, applicator)


def _or(
    children: tuple[FormulaNode, ...],
    *,
    source: SchemaNode | None = None,
    applicator_kind: str | None = None,
    polarity: FormulaPolarity | None = None,
    applicator: ApplicatorNode | None = None,
) -> FormulaNode:
    if not children:
        return BottomFormula()
    if (
        len(children) == 1
        and source is None
        and applicator_kind is None
        and polarity is None
        and applicator is None
    ):
        return children[0]
    return OrFormula(children, source, applicator_kind, polarity, applicator)


def _conjunction_children_for_metadata_wrapper(
    formula: FormulaNode,
) -> tuple[FormulaNode, ...]:
    if (
        isinstance(formula, AndFormula)
        and formula.source is None
        and formula.applicator_kind is None
        and formula.polarity is None
        and formula.applicator is None
    ):
        return formula.children
    return (formula,)


def _node_has_only_applicators(node: SchemaNode, kinds: set[str]) -> bool:
    semantic_keys = _node_semantic_keys(node)
    return bool(semantic_keys) and semantic_keys <= kinds


def _negative_occurrence_can_expose_root_assertions(node: SchemaNode) -> bool:
    semantic_keys = _node_semantic_keys(node)
    if not semantic_keys:
        return False
    return not semantic_keys <= {"allOf", "anyOf", "else", "if", "not", "oneOf", "then"}


def _mixed_negative_applicator_node(node: SchemaNode) -> ApplicatorNode | None:
    semantic_keys = _node_semantic_keys(node)
    present_kinds = tuple(
        kind for kind in _PURE_APPLICATOR_KINDS if kind in semantic_keys
    )
    if len(present_kinds) != 1 or semantic_keys <= {present_kinds[0]}:
        return None
    if semantic_keys & _CONDITIONAL_APPLICATOR_KINDS:
        return None

    applicator = _first_applicator_node(node, present_kinds[0])
    if applicator is None:
        return None
    if applicator.kind == "not" and _single_applicator_child(applicator) is None:
        return None
    return applicator


def _mixed_negative_conditional_node(node: SchemaNode) -> ApplicatorNode | None:
    semantic_keys = _node_semantic_keys(node)
    if not semantic_keys & _CONDITIONAL_APPLICATOR_KINDS:
        return None
    if semantic_keys <= _CONDITIONAL_APPLICATOR_KINDS:
        return None
    if semantic_keys & _PURE_APPLICATOR_KIND_SET:
        return None
    return _first_applicator_node(node, "if")


def _node_semantic_keys(node: SchemaNode) -> set[str]:
    return set(node.semantics.vocabulary.semantic_keywords)


def _first_applicator_child(node: SchemaNode, kind: str) -> SchemaNode | None:
    applicator = _first_applicator_node(node, kind)
    if applicator is None:
        return None
    return _single_applicator_child(applicator)


def _first_applicator_children(
    node: SchemaNode, kind: str
) -> tuple[SchemaNode, ...] | None:
    applicator = _first_applicator_node(node, kind)
    return None if applicator is None else applicator.children


def _first_applicator_node(node: SchemaNode, kind: str) -> ApplicatorNode | None:
    for applicator in node.applicators:
        if applicator.kind == kind:
            return applicator
    return None


def _single_applicator_child(applicator: ApplicatorNode) -> SchemaNode | None:
    if len(applicator.children) != 1:
        return None
    return applicator.children[0]


def _unsupported_formula(
    side: FormulaSide,
    unsupported: UnsupportedNode,
) -> UnsupportedFormula:
    return UnsupportedFormula(
        UnsupportedDiagnostic(
            category=unsupported.category,
            reason=unsupported.reason,
            keyword=unsupported.keyword,
            path=unsupported.path,
            side=side,
            disposition=_unsupported_node_disposition(unsupported),
        )
    )


def _unsupported_complement(
    side: FormulaSide,
    keyword: str,
    reason: str,
) -> UnsupportedFormula:
    return UnsupportedFormula(
        UnsupportedDiagnostic(
            category="semantic-keyword",
            reason=reason,
            keyword=keyword,
            path=(keyword,),
            side=side,
        )
    )


def _unsupported_node_disposition(
    unsupported: UnsupportedNode,
) -> UnsupportedDisposition:
    if unsupported.category == "evaluation-frontier":
        return "non_terminal"
    return "terminal"


def _unsupported_diagnostics_in_formula(
    formula: FormulaNode,
) -> tuple[UnsupportedDiagnostic, ...]:
    if isinstance(formula, UnsupportedFormula):
        return (formula.diagnostic,)
    if isinstance(formula, AndFormula | OrFormula | ExactlyOneFormula):
        return tuple(
            diagnostic
            for child in formula.children
            for diagnostic in _unsupported_diagnostics_in_formula(child)
        )
    if isinstance(formula, NotFormula):
        return _unsupported_diagnostics_in_formula(formula.child)
    if isinstance(formula, GuardedFormula):
        children = (formula.condition, formula.then_branch, formula.else_branch)
        return tuple(
            diagnostic
            for child in children
            if child is not None
            for diagnostic in _unsupported_diagnostics_in_formula(child)
        )
    return ()


def _dedupe_diagnostics(
    diagnostics: tuple[UnsupportedDiagnostic, ...],
) -> tuple[UnsupportedDiagnostic, ...]:
    seen: set[
        tuple[str, str, str | None, tuple[str, ...], str | None, str]
    ] = set()
    deduped: list[UnsupportedDiagnostic] = []
    for diagnostic in diagnostics:
        key = (
            diagnostic.category,
            diagnostic.reason,
            diagnostic.keyword,
            diagnostic.path,
            diagnostic.side,
            diagnostic.disposition,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(diagnostic)
    return tuple(deduped)
