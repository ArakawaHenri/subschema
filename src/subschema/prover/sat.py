"""
Language-difference emptiness solver for the prover.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Literal, Protocol, cast

from subschema.contracts import (
    ProofClass,
    ProofResult,
    UnsupportedDiagnostic,
    UnsupportedDisposition,
)
from subschema.dialects import Dialect
from subschema.ir import (
    AssertionAtom,
    DomainFactInfo,
    IRAssertionKind,
    LogicalSchemaIR,
    RecursiveReferenceFact,
    RecursiveReferenceObligation,
    ReferenceUnsupportedFact,
    SchemaNode,
)
from subschema.ir.constraints import TypeConstraint
from subschema.ir.terms import SchemaTerm
from subschema.prover.applicators import (
    ApplicatorDifferencePlan,
    ApplicatorPlanSet,
    applicator_plan_set,
)
from subschema.prover.confirmation import confirm_term_difference
from subschema.prover.difference import (
    ArrayDifferenceModel,
    ObjectDifferenceModel,
)
from subschema.prover.disjointness import ir_is_empty_exact
from subschema.prover.formulas import (
    AndFormula,
    AssertionFormula,
    BottomFormula,
    DifferenceFormula,
    ExactlyOneFormula,
    FormulaNode,
    GuardedFormula,
    NotFormula,
    OrFormula,
    TopFormula,
    lower_schema_term_formula,
    occurrence_assertion_formula,
)
from subschema.prover.protocols import ProofContextProtocol
from subschema.prover.rules.applicators import (
    _prove_conditional_applicator_difference,
    _prove_left_all_of_applicator_difference,
    _prove_left_any_of_applicator_difference,
    _prove_left_one_of_applicator_difference,
    _prove_right_all_of_applicator_difference,
    _prove_right_any_of_applicator_difference,
    _prove_right_not_applicator_difference,
    _prove_right_one_of_applicator_difference,
)
from subschema.prover.rules.arrays import (
    _prove_array_contains_difference,
    _prove_array_item_values_difference,
    _prove_array_length_difference,
    _prove_array_unevaluated_items_difference,
    _prove_array_uniqueness_difference,
)
from subschema.prover.rules.common import (
    _validated_false,
)
from subschema.prover.rules.objects import (
    _prove_closed_object_properties_difference,
    _prove_object_key_value_difference,
    _prove_object_presence_product_difference,
    _prove_object_property_count_difference,
    _prove_object_property_names_difference,
    _prove_object_property_values_difference,
    _prove_object_unevaluated_properties_difference,
)
from subschema.prover.rules.scalars import (
    _prove_finite_complement_difference,
    _prove_finite_lhs_difference,
    _prove_finite_rhs_difference,
    _prove_numeric_difference,
    _prove_string_language_difference,
    _prove_string_length_difference,
    _prove_type_difference,
    _prove_typed_scalar_difference,
)
from subschema.prover.witnesses import build_ir_witness, build_term_witness

RuleBudgetUse = Literal["branch", "domain", "none"]
RuleCompleteness = Literal["bounded_witness", "exact", "unsupported_boundary"]
RuleDomain = Literal[
    "applicator",
    "array",
    "finite",
    "object",
    "reference",
    "scalar",
    "trivial",
]
RuleUnsupportedDisposition = Literal["diagnostic", "non_terminal", "terminal"]
RuleWitnessMode = Literal["none", "validated"]


@dataclass(frozen=True)
class DifferenceRuleSpec:
    name: str
    fragment: str
    completeness: RuleCompleteness
    witness_mode: RuleWitnessMode
    proof_class: ProofClass
    domain: RuleDomain = "scalar"
    budget_use: RuleBudgetUse = "none"
    unsupported_disposition: RuleUnsupportedDisposition = "diagnostic"
    formula_diagnostic_guard: bool = False
    unsupported_priority: int = 0


@dataclass(frozen=True)
class DifferenceProblem:
    formula: DifferenceFormula
    context: ProofContextProtocol

    @property
    def dialect(self) -> Dialect:
        return self.context.dialect

    def lhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        formula = _side_formula_assertion(self.formula, "lhs", kind)
        if formula is None and self.formula.lhs_term is not None:
            return None
        assertion = (
            self.formula.lhs.assertion(kind) if formula is None else formula.assertion
        )
        return None if assertion is None else assertion.value

    def rhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        formula = _side_formula_assertion(self.formula, "rhs", kind)
        if formula is None and self.formula.rhs_term is not None:
            return None
        assertion = (
            self.formula.rhs.assertion(kind) if formula is None else formula.assertion
        )
        return None if assertion is None else assertion.value

    def lhs_fact_info(self, kind: IRAssertionKind) -> DomainFactInfo:
        formula = _side_formula_assertion(self.formula, "lhs", kind)
        if formula is None and self.formula.lhs_term is not None:
            return DomainFactInfo("unsupported", "schema term has no matching fact")
        if formula is None:
            return self.formula.lhs.semantics.fact_info(kind)
        assertion = formula.assertion
        return formula.source.semantics.constraint_info(
            kind, None if assertion is None else assertion.value
        )

    def rhs_fact_info(self, kind: IRAssertionKind) -> DomainFactInfo:
        formula = _side_formula_assertion(self.formula, "rhs", kind)
        if formula is None and self.formula.rhs_term is not None:
            return DomainFactInfo("unsupported", "schema term has no matching fact")
        if formula is None:
            return self.formula.rhs.semantics.fact_info(kind)
        assertion = formula.assertion
        return formula.source.semantics.constraint_info(
            kind, None if assertion is None else assertion.value
        )

    def lhs_require_exact(
        self, kind: IRAssertionKind, reason: str
    ) -> ProofResult | None:
        if self.lhs_fact_info(kind).status == "exact":
            return None
        return ProofResult.unsupported(reason)

    def rhs_require_exact(
        self, kind: IRAssertionKind, reason: str
    ) -> ProofResult | None:
        if self.rhs_fact_info(kind).status == "exact":
            return None
        return ProofResult.unsupported(reason)

    @cached_property
    def array_model(self) -> ArrayDifferenceModel:
        return ArrayDifferenceModel.from_problem(self)

    @cached_property
    def object_model(self) -> ObjectDifferenceModel:
        return ObjectDifferenceModel.from_problem(self)

    @cached_property
    def applicator_plans(self) -> tuple[ApplicatorDifferencePlan, ...]:
        return self.applicator_plan_set.plans

    @cached_property
    def applicator_plan_set(self) -> ApplicatorPlanSet:
        if self.formula.lhs_term is not None or self.formula.rhs_term is not None:
            return ApplicatorPlanSet(())
        return applicator_plan_set(self.formula)


class DifferenceRule(Protocol):
    spec: DifferenceRuleSpec

    @property
    def name(self) -> str: ...

    def prove(self, problem: DifferenceProblem) -> ProofResult: ...


@dataclass(frozen=True)
class FunctionDifferenceRule:
    spec: DifferenceRuleSpec
    fn: Callable[[DifferenceProblem], ProofResult]

    @property
    def name(self) -> str:
        return self.spec.name

    def prove(self, problem: DifferenceProblem) -> ProofResult:
        return self.fn(problem)


class EmptinessSolver:
    """Prove or refute schema inclusion by solving language-difference emptiness."""

    def __init__(self, context: ProofContextProtocol):
        self.context = context
        self.dialect = context.dialect
        self.rules = difference_rules()

    def prove_ir_difference_empty(
        self,
        lhs: LogicalSchemaIR,
        rhs: LogicalSchemaIR,
    ) -> ProofResult:
        return self.prove_formula_difference_empty(DifferenceFormula(lhs, rhs))

    def prove_term_difference_empty(
        self,
        lhs: SchemaTerm,
        rhs: SchemaTerm,
        ir: LogicalSchemaIR,
    ) -> ProofResult:
        return self.prove_terms_difference_empty(lhs, ir, rhs, ir)

    def prove_terms_difference_empty(
        self,
        lhs: SchemaTerm,
        lhs_ir: LogicalSchemaIR,
        rhs: SchemaTerm,
        rhs_ir: LogicalSchemaIR,
    ) -> ProofResult:
        if lhs.kind == "false" or rhs.kind == "true":
            return ProofResult.true()
        if rhs.kind == "false":
            witness = build_term_witness(lhs, lhs_ir, self.context)
            if witness.status == "resource_exhausted":
                return ProofResult.resource_exhausted(witness.reason)
            if witness.has_witness:
                return ProofResult.false(witness.witness)
            return ProofResult.unsupported(
                witness.reason or "schema term false proof requires confirmation source"
            )
        if lhs.kind == "node" and rhs.kind == "node":
            lhs_node_ir = _ir_for_node_term(lhs, lhs_ir, lhs_ir=lhs_ir, rhs_ir=rhs_ir)
            rhs_node_ir = _ir_for_node_term(rhs, rhs_ir, lhs_ir=lhs_ir, rhs_ir=rhs_ir)
            if lhs_node_ir is None or rhs_node_ir is None:
                return ProofResult.unsupported(
                    "schema term proof requires available IR nodes"
                )
            return self.prove_ir_difference_empty(lhs_node_ir, rhs_node_ir)
        lhs_formula = lower_schema_term_formula(
            lhs,
            lhs_ir,
            "lhs",
            "positive",
            lhs_ir=lhs_ir,
            rhs_ir=rhs_ir,
        )
        rhs_formula = lower_schema_term_formula(
            rhs,
            rhs_ir,
            "rhs",
            "negative",
            lhs_ir=lhs_ir,
            rhs_ir=rhs_ir,
        )
        formula = DifferenceFormula(
            lhs_ir,
            rhs_ir,
            AndFormula((lhs_formula, rhs_formula)),
            lhs,
            rhs,
        )
        if _formula_is_syntactically_empty(formula.formula):
            return ProofResult.true()
        return self.prove_formula_difference_empty(formula)

    def prove_formula_difference_empty(self, formula: DifferenceFormula) -> ProofResult:
        problem = DifferenceProblem(formula, self.context)
        unsupported_rule: DifferenceRule | None = None
        unsupported: ProofResult | None = None
        for rule in self.rules:
            proof = rule.prove(problem)
            proof = _proof_after_rule_class_guard(problem, rule, proof)
            proof = _proof_after_term_confirmation_guard(problem, proof)
            if proof.status != "unsupported":
                return proof
            if _should_stop_after_rule_unsupported(rule, proof):
                return _with_formula_diagnostics(formula, proof)
            unsupported_rule, unsupported = _preferred_unsupported_result(
                problem,
                unsupported_rule,
                unsupported,
                rule,
                proof,
            )
        return (
            _formula_capability_boundary_unsupported(formula)
            or unsupported
            or ProofResult.unsupported(
                "SAT emptiness solver does not support this schema pair"
            )
        )


def _ir_for_node_term(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
    *,
    lhs_ir: LogicalSchemaIR | None = None,
    rhs_ir: LogicalSchemaIR | None = None,
) -> LogicalSchemaIR | None:
    ir = _ir_for_scoped_term(term, ir, lhs_ir=lhs_ir, rhs_ir=rhs_ir) or ir
    if term.ref is None:
        return None
    node = ir.node_for_ref(term.ref)
    if node is None:
        return None
    return ir.with_root_ref(node.ref)


def _side_formula_assertion(
    formula: DifferenceFormula,
    side: Literal["lhs", "rhs"],
    kind: IRAssertionKind,
) -> AssertionFormula | None:
    override = formula.formula_override
    term = formula.lhs_term if side == "lhs" else formula.rhs_term
    term_assertion = _term_assertion(
        term,
        formula.lhs if side == "lhs" else formula.rhs,
        side=side,
        lhs_ir=formula.lhs,
        rhs_ir=formula.rhs,
        kind=kind,
    )
    if term_assertion is not None:
        return term_assertion
    if (
        side == "lhs"
        and isinstance(override, AndFormula)
        and len(override.children) == 2
    ):
        branch = override.children[0]
        found = _combined_assertion_formula(branch, kind)
        if found is not None:
            return found
    if side == "rhs" and term is not None:
        return None
    occurrence = formula.positive_lhs if side == "lhs" else formula.negative_rhs
    root_assertion = occurrence_assertion_formula(occurrence, kind)
    if root_assertion is not None:
        return root_assertion
    if side == "rhs":
        return _selected_boolean_conditional_assertion(formula.rhs.root, kind)
    return _combined_assertion_formula(occurrence.formula, kind)


def _term_assertion(
    term: SchemaTerm | None,
    ir: LogicalSchemaIR,
    *,
    side: Literal["lhs", "rhs"],
    lhs_ir: LogicalSchemaIR | None = None,
    rhs_ir: LogicalSchemaIR | None = None,
    kind: IRAssertionKind,
) -> AssertionFormula | None:
    if term is None:
        return None
    if (
        side == "lhs"
        and term.kind == "not"
        and len(term.children) == 1
        and kind == "type"
    ):
        child_assertion = _term_assertion(
            term.children[0],
            ir,
            side=side,
            lhs_ir=lhs_ir,
            rhs_ir=rhs_ir,
            kind=kind,
        )
        if not isinstance(child_assertion, AssertionFormula) or not isinstance(
            child_assertion.assertion.value, TypeConstraint
        ):
            return None
        if not child_assertion.assertion.value.language_complete:
            return None
        return AssertionFormula(
            child_assertion.source,
            AssertionAtom(kind, child_assertion.assertion.value.complement()),
        )
    if term.kind != "node" or term.ref is None:
        return None
    term_ir = _ir_for_scoped_term(term, ir, lhs_ir=lhs_ir, rhs_ir=rhs_ir)
    if term_ir is None:
        return None
    node = term_ir.node_for_ref(term.ref)
    if node is None:
        return None
    assertion = node.semantics.assertion(kind)
    if assertion is None:
        return None
    return AssertionFormula(node, assertion)


def _ir_for_scoped_term(
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


def _combined_assertion_formula(
    formula: FormulaNode,
    kind: IRAssertionKind,
) -> AssertionFormula | None:
    formulas = _assertion_formulas_in_conjunction(formula, kind)
    if not formulas:
        return None
    value = formulas[0].assertion.value
    for next_formula in formulas[1:]:
        intersect = getattr(value, "intersect", None)
        if not callable(intersect):
            return formulas[0]
        value = intersect(next_formula.assertion.value)
    return AssertionFormula(formulas[0].source, AssertionAtom(kind, value))


def _selected_boolean_conditional_assertion(
    node: SchemaNode,
    kind: IRAssertionKind,
) -> AssertionFormula | None:
    selected = _selected_boolean_conditional_branch(node)
    if selected is None:
        return None
    assertion = selected.semantics.assertion(kind)
    if assertion is None:
        return None
    return AssertionFormula(selected, assertion)


def _selected_boolean_conditional_branch(node: SchemaNode) -> SchemaNode | None:
    condition = _first_applicator_child(node, "if")
    if condition is None or condition.boolean_value is None:
        return None
    target_kind = "then" if condition.boolean_value else "else"
    return _first_applicator_child(node, target_kind)


def _first_applicator_child(node: SchemaNode, kind: str) -> SchemaNode | None:
    for applicator in node.applicators:
        if applicator.kind == kind and applicator.children:
            return applicator.children[0]
    return None


def _assertion_formulas_in_conjunction(
    formula: FormulaNode,
    kind: IRAssertionKind,
) -> tuple[AssertionFormula, ...]:
    if isinstance(formula, AssertionFormula) and formula.assertion.kind == kind:
        return (formula,)
    if isinstance(formula, AndFormula):
        return tuple(
            assertion
            for child in formula.children
            for assertion in _assertion_formulas_in_conjunction(child, kind)
        )
    return ()


def _first_assertion_formula(
    formula: FormulaNode,
    kind: IRAssertionKind,
) -> AssertionFormula | None:
    if isinstance(formula, AssertionFormula) and formula.assertion.kind == kind:
        return formula
    children: tuple[FormulaNode, ...]
    if isinstance(formula, AndFormula | OrFormula | ExactlyOneFormula):
        children = formula.children
    elif isinstance(formula, GuardedFormula):
        children = tuple(
            child
            for child in (formula.condition, formula.then_branch, formula.else_branch)
            if child is not None
        )
    else:
        children = ()
    for child in children:
        found = _first_assertion_formula(child, kind)
        if found is not None:
            return found
    return None


def _preferred_unsupported_result(
    problem: DifferenceProblem,
    current_rule: DifferenceRule | None,
    current: ProofResult | None,
    candidate_rule: DifferenceRule,
    candidate: ProofResult,
) -> tuple[DifferenceRule, ProofResult]:
    if current is None or current_rule is None:
        return candidate_rule, candidate

    if _lhs_is_exact_array_schema(problem):
        current_is_array = current_rule.spec.domain == "array"
        candidate_is_array = candidate_rule.spec.domain == "array"
        candidate_is_object = candidate_rule.spec.domain == "object"
        if candidate_is_array and not current_is_array:
            return candidate_rule, candidate
        if current_is_array and candidate_is_object:
            return current_rule, current

    current_priority = _effective_unsupported_priority(current_rule, current)
    candidate_priority = _effective_unsupported_priority(candidate_rule, candidate)
    if candidate_priority != current_priority:
        if candidate_priority > current_priority:
            return candidate_rule, candidate
        return current_rule, current
    if current_priority > 0:
        return current_rule, current

    return candidate_rule, candidate


def _effective_unsupported_priority(
    rule: DifferenceRule, proof: ProofResult
) -> int:
    return max(rule.spec.unsupported_priority, proof.unsupported_priority)


def _lhs_is_exact_array_schema(problem: DifferenceProblem) -> bool:
    constraint = problem.formula.lhs.type_constraint
    return (
        constraint is not None
        and constraint.language_complete
        and constraint.atoms == frozenset({"array"})
    )


def _proof_after_rule_class_guard(
    problem: DifferenceProblem,
    rule: DifferenceRule,
    proof: ProofResult,
) -> ProofResult:
    if (
        proof.status == "proved_false"
        and rule.spec.formula_diagnostic_guard
        and _formula_has_non_deferable_formula_diagnostic(problem.formula)
    ):
        return ProofResult.unsupported(
            "SAT proof defers terminal formula diagnostics",
            diagnostics=problem.formula.unsupported_diagnostics,
        )
    if proof.status == "unsupported":
        return proof
    if rule.spec.proof_class == "unsupported_unreliable":
        return ProofResult.unsupported(
            f"{rule.name} is outside the reliable proof fragment"
        )
    if (
        rule.spec.proof_class == "endeavor_expensive"
        and not problem.context.allows_expensive_proof("branch_product")
    ):
        return ProofResult.unsupported(f"{rule.name} requires endeavor proof")
    return proof


def _formula_has_non_deferable_formula_diagnostic(
    formula: DifferenceFormula,
) -> bool:
    return any(
        diagnostic.disposition != "deferable"
        for diagnostic in formula.unsupported_diagnostics
    )


def _proof_after_term_confirmation_guard(
    problem: DifferenceProblem,
    proof: ProofResult,
) -> ProofResult:
    if proof.status == "unsupported":
        return proof
    lhs_term = problem.formula.lhs_term
    rhs_term = problem.formula.rhs_term
    if (
        proof.status == "proved_true"
        and rhs_term is not None
        and rhs_term.kind not in {"false", "node", "true"}
    ):
        return ProofResult.unsupported(
            "RHS composite schema term proof requires term-aware exactness"
        )
    if (
        proof.status == "proved_false"
        and lhs_term is not None
        and rhs_term is not None
        and proof.certificate is None
    ):
        if proof.witness is None:
            return ProofResult.unsupported(
                "schema term counterexample is missing a concrete witness"
            )
        confirmed = confirm_term_difference(
            lhs_term,
            problem.formula.lhs,
            rhs_term,
            problem.formula.rhs,
            proof.witness,
            problem.context,
        )
        if confirmed.status == "confirmed":
            return proof
        if confirmed.status == "unsupported":
            return confirmed.proof or ProofResult.unsupported(
                "schema term counterexample confirmation failed"
            )
        return ProofResult.unsupported("schema term counterexample was rejected")
    return proof


def difference_rules() -> tuple[DifferenceRule, ...]:
    rules = (
        _rule(
            "trivial-difference",
            _prove_trivial_difference,
            fragment="boolean and syntactically equal schemas",
            completeness="exact",
            witness_mode="none",
        ),
        _rule(
            "static-reference-ir",
            _prove_static_reference_difference,
            fragment="root pure acyclic static $ref targets",
            completeness="exact",
            witness_mode="validated",
            budget_use="branch",
        ),
        _rule(
            "dynamic-reference-ir",
            _prove_dynamic_reference_difference,
            fragment=(
                "root pure acyclic $dynamicRef targets with dynamic-scope resolution"
            ),
            completeness="exact",
            witness_mode="validated",
            budget_use="branch",
        ),
        _rule(
            "recursive-reference-boundary",
            _prove_recursive_reference_boundary,
            fragment="recursive reference unsupported boundary",
            completeness="unsupported_boundary",
            witness_mode="none",
            unsupported_disposition="diagnostic",
        ),
        _rule(
            "finite-domain-ir",
            _prove_finite_lhs_difference,
            fragment="finite left language",
            completeness="exact",
            witness_mode="validated",
        ),
        _rule(
            "finite-rhs-domain-ir",
            _prove_finite_rhs_difference,
            fragment="finite right language with generated non-member witnesses",
            completeness="bounded_witness",
            witness_mode="validated",
        ),
        _rule(
            "finite-complement-ir",
            _prove_finite_complement_difference,
            fragment="complements of finite enum/const/applicator languages",
            completeness="exact",
            witness_mode="validated",
        ),
        _rule(
            "applicator-left-anyof-ir",
            _prove_left_any_of_applicator_difference,
            fragment="left-side anyOf branch coverage products",
            completeness="exact",
            witness_mode="validated",
            budget_use="branch",
        ),
        _rule(
            "applicator-left-oneof-ir",
            _prove_left_one_of_applicator_difference,
            fragment="left-side oneOf branch coverage products",
            completeness="exact",
            witness_mode="validated",
            budget_use="branch",
        ),
        _rule(
            "applicator-left-allof-ir",
            _prove_left_all_of_applicator_difference,
            fragment="left-side allOf covering-conjunct products",
            completeness="exact",
            witness_mode="validated",
            budget_use="branch",
        ),
        _rule(
            "applicator-right-not-ir",
            _prove_right_not_applicator_difference,
            fragment="right-side not base, NNF schema product, and specialized overlap",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="branch",
            unsupported_priority=5,
        ),
        _rule(
            "applicator-right-anyof-ir",
            _prove_right_any_of_applicator_difference,
            fragment="right-side anyOf negative NNF branch products",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="branch",
        ),
        _rule(
            "applicator-right-oneof-ir",
            _prove_right_one_of_applicator_difference,
            fragment=(
                "right-side oneOf base, coverage, overlap, and disjointness products"
            ),
            completeness="exact",
            witness_mode="validated",
            budget_use="branch",
        ),
        _rule(
            "applicator-right-allof-ir",
            _prove_right_all_of_applicator_difference,
            fragment="right-side allOf negative NNF branch products",
            completeness="exact",
            witness_mode="validated",
            budget_use="branch",
        ),
        _rule(
            "applicator-conditional-ir",
            _prove_conditional_applicator_difference,
            fragment="if/then/else base and guarded branch products",
            completeness="exact",
            witness_mode="validated",
            budget_use="branch",
            formula_diagnostic_guard=True,
        ),
        _rule(
            "numeric-domain-ir",
            _prove_numeric_difference,
            fragment="numeric interval and multipleOf constraints",
            completeness="exact",
            witness_mode="validated",
        ),
        _rule(
            "type-domain-ir",
            _prove_type_difference,
            fragment="JSON type-set constraints",
            completeness="exact",
            witness_mode="validated",
        ),
        _rule(
            "string-length-domain-ir",
            _prove_string_length_difference,
            fragment="string length interval constraints",
            completeness="exact",
            witness_mode="validated",
        ),
        _rule(
            "string-language-domain-ir",
            _prove_string_language_difference,
            fragment="supported regular string-language constraints",
            completeness="exact",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "typed-scalar-domain-ir",
            _prove_typed_scalar_difference,
            fragment="type-partitioned numeric and string scalar constraints",
            completeness="exact",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "array-unevaluated-items-ir",
            _prove_array_unevaluated_items_difference,
            fragment="evaluation-expression unevaluatedItems frontier constraints",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "array-length-ir",
            _prove_array_length_difference,
            fragment="array length and closed-tail constraints",
            completeness="exact",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "array-uniqueness-ir",
            _prove_array_uniqueness_difference,
            fragment="local uniqueItems constraints and duplicate witness plans",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "array-contains-ir",
            _prove_array_contains_difference,
            fragment="local contains cardinality and witness plans",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "array-item-values-ir",
            _prove_array_item_values_difference,
            fragment="array prefix/tail item-value obligations",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "object-unevaluated-properties-ir",
            _prove_object_unevaluated_properties_difference,
            fragment="evaluation-expression unevaluatedProperties frontier constraints",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "object-property-count-ir",
            _prove_object_property_count_difference,
            fragment="object property-count constraints",
            completeness="exact",
            witness_mode="validated",
        ),
        _rule(
            "object-presence-product-ir",
            _prove_object_presence_product_difference,
            fragment=(
                "required and dependency presence products over finite key universes"
            ),
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "object-property-values-ir",
            _prove_object_property_values_difference,
            fragment="object property-value obligations",
            completeness="bounded_witness",
            witness_mode="validated",
        ),
        _rule(
            "object-key-value-ir",
            _prove_object_key_value_difference,
            fragment="object explicit, pattern, and fresh key/value products",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "object-property-names-ir",
            _prove_object_property_names_difference,
            fragment="object propertyNames keyspace and repair witness plans",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="domain",
        ),
        _rule(
            "object-closed-properties-ir",
            _prove_closed_object_properties_difference,
            fragment="closed object keyspace and property-value obligations",
            completeness="bounded_witness",
            witness_mode="validated",
            budget_use="domain",
        ),
    )
    return cast(tuple[DifferenceRule, ...], rules)


def difference_rule_specs() -> tuple[DifferenceRuleSpec, ...]:
    return tuple(rule.spec for rule in difference_rules())


def _rule(
    name: str,
    fn: Callable[[DifferenceProblem], ProofResult],
    *,
    fragment: str,
    completeness: RuleCompleteness,
    witness_mode: RuleWitnessMode,
    budget_use: RuleBudgetUse = "none",
    proof_class: ProofClass | None = None,
    unsupported_disposition: RuleUnsupportedDisposition | None = None,
    formula_diagnostic_guard: bool = False,
    unsupported_priority: int = 0,
) -> FunctionDifferenceRule:
    resolved_proof_class = (
        _default_proof_class(completeness, budget_use)
        if proof_class is None
        else proof_class
    )
    return FunctionDifferenceRule(
        DifferenceRuleSpec(
            name=name,
            domain=_rule_domain(name),
            fragment=fragment,
            completeness=completeness,
            witness_mode=witness_mode,
            proof_class=resolved_proof_class,
            budget_use=budget_use,
            unsupported_disposition=_default_unsupported_disposition(
                completeness, resolved_proof_class
            )
            if unsupported_disposition is None
            else unsupported_disposition,
            formula_diagnostic_guard=formula_diagnostic_guard,
            unsupported_priority=unsupported_priority,
        ),
        fn,
    )


def _rule_domain(name: str) -> RuleDomain:
    if name == "trivial-difference":
        return "trivial"
    if name.endswith("reference-ir") or name == "recursive-reference-boundary":
        return "reference"
    if name.startswith("finite-"):
        return "finite"
    if name.startswith("applicator-"):
        return "applicator"
    if name.startswith("array-"):
        return "array"
    if name.startswith("object-"):
        return "object"
    return "scalar"


def _default_proof_class(
    completeness: RuleCompleteness, budget_use: RuleBudgetUse
) -> ProofClass:
    if completeness == "unsupported_boundary":
        return "unsupported_unreliable"
    return "simple_exact"


def _default_unsupported_disposition(
    completeness: RuleCompleteness, proof_class: ProofClass
) -> RuleUnsupportedDisposition:
    if (
        completeness == "unsupported_boundary"
        or proof_class == "unsupported_unreliable"
    ):
        return "terminal"
    return "diagnostic"


def _should_stop_after_rule_unsupported(
    rule: DifferenceRule, proof: ProofResult
) -> bool:
    disposition = _rule_unsupported_disposition(rule, proof)
    return disposition == "terminal"


def _rule_unsupported_disposition(
    rule: DifferenceRule, proof: ProofResult
) -> UnsupportedDisposition:
    if proof.diagnostics:
        return _diagnostics_disposition(proof.diagnostics)
    if rule.spec.unsupported_disposition == "terminal":
        return "terminal"
    if rule.spec.unsupported_disposition == "non_terminal":
        return "non_terminal"
    return "non_terminal"


def _diagnostics_disposition(
    diagnostics: tuple[UnsupportedDiagnostic, ...],
) -> UnsupportedDisposition:
    dispositions = frozenset(diagnostic.disposition for diagnostic in diagnostics)
    if dispositions <= {"deferable", "non_terminal"}:
        return "deferable" if "deferable" in dispositions else "non_terminal"
    if dispositions == {"non_terminal"}:
        return "non_terminal"
    return "terminal"


def _prove_trivial_difference(problem: DifferenceProblem) -> ProofResult:
    if _formula_is_syntactically_empty(problem.formula.formula):
        return ProofResult.true()
    if problem.formula.lhs_term is not None or problem.formula.rhs_term is not None:
        lhs_term = problem.formula.lhs_term or problem.formula.lhs.root_term
        rhs_term = problem.formula.rhs_term or problem.formula.rhs.root_term
        if lhs_term.kind == "false" or rhs_term.kind == "true" or lhs_term == rhs_term:
            return ProofResult.true()
        return ProofResult.unsupported(
            "schemas are outside the trivial difference fragment"
        )
    if (
        problem.formula.lhs.root.boolean_value is False
        or _ir_accepts_everything(problem.formula.rhs)
        or problem.formula.lhs.source == problem.formula.rhs.source
    ):
        return ProofResult.true()
    lhs_empty = ir_is_empty_exact(problem.formula.lhs, problem.context)
    if lhs_empty.status == "proved_true":
        return lhs_empty
    if problem.formula.rhs.root.boolean_value is False:
        if lhs_empty.status == "resource_exhausted":
            return lhs_empty
    return ProofResult.unsupported(
        "schemas are outside the trivial difference fragment"
    )


def _ir_accepts_everything(ir: LogicalSchemaIR) -> bool:
    root = ir.root
    if root.boolean_value is not None:
        return root.boolean_value is True
    if root.unsupported:
        return False
    reference = root.semantics.reference
    if (
        reference.has_static_reference_boundary
        or reference.has_dynamic_reference
        or reference.has_recursive_reference
    ):
        return False
    return not root.semantics.vocabulary.semantic_keywords


def _formula_is_syntactically_empty(formula: FormulaNode) -> bool:
    if isinstance(formula, BottomFormula):
        return True
    if isinstance(formula, TopFormula):
        return False
    if isinstance(formula, AndFormula):
        return any(_formula_is_syntactically_empty(child) for child in formula.children)
    if isinstance(formula, OrFormula):
        return all(_formula_is_syntactically_empty(child) for child in formula.children)
    if isinstance(formula, NotFormula):
        return isinstance(formula.child, TopFormula)
    return False


def _with_formula_diagnostics(
    formula: DifferenceFormula, proof: ProofResult
) -> ProofResult:
    diagnostics = _dedupe_diagnostics(
        proof.diagnostics + formula.unsupported_diagnostics
    )
    if diagnostics == proof.diagnostics:
        return proof
    return ProofResult.unsupported(
        proof.reason or formula.unsupported_reason,
        proof.error,
        diagnostics=diagnostics,
        unsupported_priority=proof.unsupported_priority,
    )


def _dedupe_diagnostics(
    diagnostics: tuple[UnsupportedDiagnostic, ...],
) -> tuple[UnsupportedDiagnostic, ...]:
    seen: set[tuple[str, str, str | None, tuple[str, ...], str | None, str]] = set()
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


def _prove_static_reference_difference(problem: DifferenceProblem) -> ProofResult:
    if problem.formula.lhs_term is not None or problem.formula.rhs_term is not None:
        return ProofResult.unsupported(
            "SAT static-reference fragment requires a root pure static $ref"
        )

    lhs_reference = problem.formula.lhs.root.semantics.reference.static_reference
    rhs_reference = problem.formula.rhs.root.semantics.reference.static_reference

    if (
        lhs_reference.target is None
        and rhs_reference.target is None
        and lhs_reference.lhs_unsupported is None
        and rhs_reference.rhs_unsupported is None
    ):
        return ProofResult.unsupported(
            "SAT static-reference fragment requires a root pure static $ref"
        )
    if lhs_reference.lhs_unsupported is not None:
        target_proof = _try_static_reference_target_subproof(problem)
        if target_proof is not None:
            return target_proof
        if _static_reference_supports_constructive_false(lhs_reference.lhs_unsupported):
            false_proof = _constructive_static_reference_false(problem)
            if false_proof.status == "proved_false":
                return false_proof
        return ProofResult.unsupported(
            lhs_reference.lhs_unsupported.reason,
            diagnostics=lhs_reference.lhs_unsupported.diagnostic("lhs"),
        )
    if rhs_reference.rhs_unsupported is not None:
        target_proof = _try_static_reference_target_subproof(problem)
        if target_proof is not None:
            return target_proof
        if _static_reference_supports_constructive_false(rhs_reference.rhs_unsupported):
            false_proof = _constructive_static_reference_false(problem)
            if false_proof.status == "proved_false":
                return false_proof
        return ProofResult.unsupported(
            rhs_reference.rhs_unsupported.reason,
            diagnostics=rhs_reference.rhs_unsupported.diagnostic("rhs"),
        )

    lhs_term = lhs_reference.target or problem.formula.lhs.root_term
    rhs_term = rhs_reference.target or problem.formula.rhs.root_term

    proof = problem.context.subproof_terms(
        lhs_term,
        problem.formula.lhs,
        rhs_term,
        problem.formula.rhs,
    )
    if proof.status in {"proved_true", "resource_exhausted", "unsupported"}:
        return proof
    if proof.witness is None:
        return ProofResult.unsupported(
            "SAT static-reference witness could not be constructed"
        )
    return _validated_false(
        problem, proof.witness, "SAT static-reference witness was rejected"
    )


def _try_static_reference_target_subproof(
    problem: DifferenceProblem,
) -> ProofResult | None:
    lhs_reference = problem.formula.lhs.root.semantics.reference.static_reference
    rhs_reference = problem.formula.rhs.root.semantics.reference.static_reference
    if lhs_reference.target is None and rhs_reference.target is None:
        return None

    proof = problem.context.subproof_terms(
        lhs_reference.target or problem.formula.lhs.root_term,
        problem.formula.lhs,
        rhs_reference.target or problem.formula.rhs.root_term,
        problem.formula.rhs,
    )
    if proof.status in {"proved_true", "resource_exhausted"}:
        return proof
    if proof.status == "proved_false" and proof.witness is not None:
        confirmed = _validated_false(
            problem,
            proof.witness,
            "SAT static-reference target witness was rejected",
        )
        if confirmed.status == "proved_false":
            return confirmed
    return None


def _constructive_static_reference_false(problem: DifferenceProblem) -> ProofResult:
    witness = build_ir_witness(
        problem.formula.lhs,
        problem.context,
    )
    if witness.status == "resource_exhausted":
        return ProofResult.resource_exhausted(witness.reason)
    if witness.status != "witness":
        return ProofResult.unsupported(
            witness.reason
            or "SAT static-reference constructive witness could not be built"
        )
    return _validated_false(
        problem,
        witness.witness,
        "SAT static-reference constructive witness was rejected",
    )


def _static_reference_supports_constructive_false(
    unsupported: ReferenceUnsupportedFact,
) -> bool:
    return (
        unsupported.category == "static-reference"
        and "dialect transition" in unsupported.reason
    )


def _prove_dynamic_reference_difference(problem: DifferenceProblem) -> ProofResult:
    if problem.formula.lhs_term is not None or problem.formula.rhs_term is not None:
        return ProofResult.unsupported(
            "SAT dynamic-reference fragment requires a root pure $dynamicRef"
        )

    lhs_reference = problem.formula.lhs.root.semantics.reference.dynamic_reference
    rhs_reference = problem.formula.rhs.root.semantics.reference.dynamic_reference

    if (
        lhs_reference.target is None
        and rhs_reference.target is None
        and lhs_reference.lhs_unsupported is None
        and rhs_reference.rhs_unsupported is None
    ):
        return ProofResult.unsupported(
            "SAT dynamic-reference fragment requires a root pure $dynamicRef"
        )
    if lhs_reference.lhs_unsupported is not None:
        return ProofResult.unsupported(
            lhs_reference.lhs_unsupported.reason,
            diagnostics=lhs_reference.lhs_unsupported.diagnostic("lhs"),
        )
    if rhs_reference.rhs_unsupported is not None:
        return ProofResult.unsupported(
            rhs_reference.rhs_unsupported.reason,
            diagnostics=rhs_reference.rhs_unsupported.diagnostic("rhs"),
        )

    lhs_term = lhs_reference.target or problem.formula.lhs.root_term
    rhs_term = rhs_reference.target or problem.formula.rhs.root_term

    proof = problem.context.subproof_terms(
        lhs_term,
        problem.formula.lhs,
        rhs_term,
        problem.formula.rhs,
    )
    if proof.status in {"proved_true", "resource_exhausted", "unsupported"}:
        return proof
    if proof.witness is None:
        return ProofResult.unsupported(
            "SAT dynamic-reference witness could not be constructed"
        )
    return _validated_false(
        problem, proof.witness, "SAT dynamic-reference witness was rejected"
    )


def _prove_recursive_reference_boundary(problem: DifferenceProblem) -> ProofResult:
    diagnostics = _recursive_reference_diagnostics(problem.formula)
    if not diagnostics:
        return ProofResult.unsupported(
            "SAT recursive-reference boundary requires recursive reference facts"
        )
    reason = "; ".join(sorted({diagnostic.format() for diagnostic in diagnostics}))
    return ProofResult.unsupported(reason, diagnostics=diagnostics)


def _formula_capability_boundary_unsupported(
    formula: DifferenceFormula,
) -> ProofResult | None:
    diagnostics = _dedupe_diagnostics(
        _terminal_diagnostics(formula.unsupported_diagnostics)
        + _recursive_reference_diagnostics(formula)
    )
    if not diagnostics:
        return None

    reason = "; ".join(sorted({diagnostic.format() for diagnostic in diagnostics}))
    return ProofResult.unsupported(reason, diagnostics=diagnostics)


def _terminal_diagnostics(
    diagnostics: tuple[UnsupportedDiagnostic, ...],
) -> tuple[UnsupportedDiagnostic, ...]:
    return tuple(
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.disposition == "terminal"
    )


def _recursive_reference_diagnostics(
    formula: DifferenceFormula,
) -> tuple[UnsupportedDiagnostic, ...]:
    diagnostics = tuple(
        diagnostic
        for diagnostic in formula.unsupported_diagnostics
        if diagnostic.category == "recursive-reference"
    )
    return _dedupe_diagnostics(
        diagnostics
        + tuple(
            obligation.diagnostic()
            for obligation in _recursive_reference_obligations(formula)
        )
    )


def _recursive_reference_obligations(
    formula: DifferenceFormula,
) -> tuple[RecursiveReferenceObligation, ...]:
    return tuple(
        _recursive_reference_obligation("lhs", fact)
        for fact in formula.lhs.semantics.reference.recursive_references
    ) + tuple(
        _recursive_reference_obligation("rhs", fact)
        for fact in formula.rhs.semantics.reference.recursive_references
    )


def _recursive_reference_obligation(
    side: Literal["lhs", "rhs"],
    fact: RecursiveReferenceFact,
) -> RecursiveReferenceObligation:
    return RecursiveReferenceObligation(
        side=side,
        keyword=fact.keyword,
        path=fact.path,
        ref=fact.ref,
        guard_kind=fact.guard_kind,
        polarity=fact.polarity,
        target_ref=fact.target_ref,
    )
