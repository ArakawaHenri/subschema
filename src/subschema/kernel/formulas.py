"""
Formula IR for schema language-difference proof problems.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any, Literal

from subschema.dialects import Dialect
from subschema.kernel.contracts import UnsupportedDiagnostic
from subschema.kernel.evaluation import EvaluationFrontier
from subschema.kernel.ir import (
    ApplicatorNode,
    AssertionAtom,
    IRAssertionKind,
    LogicalSchemaIR,
    SchemaIRCompiler,
    SchemaNode,
    UnsupportedNode,
)
from subschema.kernel.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    schema_is_false,
    schema_is_true,
)

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
    def schema(self) -> Any:
        return self.ir.schema

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
            )
            for node in self.ir.unsupported
        )


@dataclass(frozen=True)
class DifferenceFormula:
    """Formula for satisfiability of L(lhs) intersect complement(L(rhs))."""

    lhs: LogicalSchemaIR
    rhs: LogicalSchemaIR

    @classmethod
    def from_schemas(cls, lhs: Any, rhs: Any, dialect: Dialect) -> DifferenceFormula:
        compiler = SchemaIRCompiler(dialect)
        return cls(compiler.compile(lhs), compiler.compile(rhs))

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
        return _and((self.positive_lhs.formula, self.negative_rhs.formula))

    @property
    def unsupported_diagnostics(self) -> tuple[UnsupportedDiagnostic, ...]:
        return (
            self.positive_lhs.unsupported_diagnostics
            + self.negative_rhs.unsupported_diagnostics
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


def occurrence_assertion_formula(
    occurrence: FormulaOccurrence,
    kind: IRAssertionKind,
) -> AssertionFormula | None:
    if (
        occurrence.polarity == "negative"
        and not _negative_occurrence_can_expose_root_assertions(occurrence.root)
    ):
        return None

    assertion = occurrence.ir.assertion(kind)
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
    schema = node.source.schema
    if schema_is_true(schema):
        return TopFormula()
    if schema_is_false(schema):
        return BottomFormula()

    parts: list[FormulaNode] = [
        AssertionFormula(node, assertion) for assertion in node.facts.assertions()
    ]

    static_reference = _reference_formula(node)
    if static_reference is not None:
        parts.append(static_reference)

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
        _unsupported_formula(side, unsupported) for unsupported in node.unsupported
    )

    return _and(tuple(parts))


def _negative_formula_for_node(node: SchemaNode, side: FormulaSide) -> FormulaNode:
    schema = node.source.schema
    if schema_is_true(schema):
        return BottomFormula()
    if schema_is_false(schema):
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
    schema = node.source.schema
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    return ReferenceFormula(node, target=ref) if isinstance(ref, str) else None


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
    schema = node.source.schema
    if not isinstance(schema, dict):
        return False
    semantic_keys = set(schema) - IGNORED_SCHEMA_METADATA_KEYS
    return bool(semantic_keys) and semantic_keys <= kinds


def _negative_occurrence_can_expose_root_assertions(node: SchemaNode) -> bool:
    schema = node.source.schema
    if not isinstance(schema, dict):
        return False
    semantic_keys = set(schema) - IGNORED_SCHEMA_METADATA_KEYS
    if not semantic_keys:
        return False
    return not semantic_keys <= {"allOf", "anyOf", "else", "if", "not", "oneOf", "then"}


def _mixed_negative_applicator_node(node: SchemaNode) -> ApplicatorNode | None:
    schema = node.source.schema
    if not isinstance(schema, dict):
        return None

    semantic_keys = set(schema) - IGNORED_SCHEMA_METADATA_KEYS
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
    schema = node.source.schema
    if not isinstance(schema, dict):
        return None

    semantic_keys = set(schema) - IGNORED_SCHEMA_METADATA_KEYS
    if not semantic_keys & _CONDITIONAL_APPLICATOR_KINDS:
        return None
    if semantic_keys <= _CONDITIONAL_APPLICATOR_KINDS:
        return None
    if semantic_keys & _PURE_APPLICATOR_KIND_SET:
        return None
    return _first_applicator_node(node, "if")


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
