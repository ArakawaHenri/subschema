"""
Language-difference emptiness solver for the proof kernel.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import cached_property
from itertools import product
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from subschema.dialects import Dialect
from subschema.kernel.applicators import (
    ApplicatorBaseProduct,
    ApplicatorBranchPlan,
    ApplicatorBranchProduct,
    ApplicatorConditionalPlan,
    ApplicatorConditionalProduct,
    ApplicatorDifferencePlan,
    ApplicatorExpansionBudget,
    ApplicatorNnfBranchProduct,
    ApplicatorNnfFragment,
    ApplicatorNnfSchemaProduct,
    ApplicatorOneOfBranchProduct,
    ApplicatorOneOfCardinalityPlan,
    ApplicatorOneOfDisjointnessProduct,
    ApplicatorPlanSet,
    applicator_base_pre_branch_choice,
    applicator_base_product,
    applicator_branch_expansion_budget,
    applicator_branch_products,
    applicator_nnf_schema_product,
    applicator_plan_set,
    conditional_branch_products,
    conditional_branch_proof_choice,
    conditional_covering_product_proof_choice,
    conditional_covering_subproof_choice,
    conditional_final_proof_choice,
    left_all_of_branch_proof_choice,
    left_any_of_branch_proof_choice,
    left_branch_resolved_lhs_schema,
    left_one_of_branch_proof_choice,
    one_of_branch_resolved_schema,
    one_of_cardinality_products,
    one_of_coverage_branch_proof_choice,
    one_of_coverage_expansion_budget,
    one_of_covering_selection,
    one_of_disjointness_complement_schema,
    one_of_disjointness_direct_proof_choice,
    one_of_disjointness_expansion_budget,
    one_of_disjointness_products,
    one_of_disjointness_proof_choice,
    one_of_disjointness_resolved_branch_schema,
    one_of_overlap_witness_plan,
    right_negative_all_of_branch_product_plan,
    right_negative_all_of_branch_proof_choice,
    right_negative_any_of_branch_product_plan,
    right_negative_any_of_branch_proof_choice,
    right_nnf_branch_resolved_rhs_schema,
    right_not_complement_needs_subproof,
    right_not_complement_proof_choice,
    right_not_complement_schema,
    right_not_intersection_witness_plan,
    right_not_resolved_rhs_schema,
    right_not_subproof_choice,
    right_not_witness_plan,
)
from subschema.kernel.confirmation import confirm_difference, confirm_valid
from subschema.kernel.constraints import (
    FiniteConstraint,
    NumericConstraint,
    StringLanguageConstraint,
    StringLengthConstraint,
    TypeConstraint,
)
from subschema.kernel.contracts import (
    CounterexampleCertificate,
    ProofClass,
    ProofResult,
    UnsupportedDiagnostic,
)
from subschema.kernel.difference import (
    ArrayDifferenceModel,
    ObjectDifferenceModel,
    materialize_array_duplicate_witness_plan,
    materialize_array_witness_plan,
    materialize_array_witness_skeleton,
    materialize_closed_object_witness_skeleton,
    materialize_object_key_value_witness_skeleton,
    materialize_object_property_names_repair_skeleton,
    materialize_object_property_value_witness_skeleton,
)
from subschema.kernel.disjointness import schema_is_empty_exact, schemas_are_disjoint
from subschema.kernel.domains.numbers import NumericAtom, NumericShape
from subschema.kernel.domains.types import (
    schema_covers_type_atom,
    type_overapproximation_for_schema,
    witness_for_type_atom,
)
from subschema.kernel.finite import finite_complement_excluded_values
from subschema.kernel.formulas import (
    AndFormula,
    BottomFormula,
    DifferenceFormula,
    FormulaNode,
    NotFormula,
    OrFormula,
    TopFormula,
    occurrence_assertion_formula,
)
from subschema.kernel.ir import IRAssertionKind, SchemaNode
from subschema.kernel.overlaps import (
    right_not_string_overlap_plan_from_constraints,
    right_not_string_overlap_proof_choice,
)
from subschema.kernel.references import (
    DynamicReferenceUnsupported,
    ReferenceResolution,
    StaticReferenceUnsupported,
    root_dynamic_reference_resolution,
    root_static_reference_resolution,
    static_reference_resolution_for_schema,
)
from subschema.kernel.scalars import (
    finite_rhs_difference_plan_from_constraints,
    numeric_difference_plan_from_constraints,
    string_language_difference_plan_from_constraints,
    string_length_difference_plan_from_constraints,
    type_difference_plan_from_constraints,
    typed_scalar_difference_plan_from_constraints,
)
from subschema.kernel.schemas import (
    contains_reference_keyword,
    schema_is_false,
    schema_is_true,
    schemas_equal,
)
from subschema.kernel.values import json_semantic_key, json_values_equal
from subschema.kernel.witnesses import build_schema_witness

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext

RuleBudgetUse = Literal["branch", "domain", "none"]
RuleCompleteness = Literal["bounded_witness", "exact", "unsupported_boundary"]
RuleWitnessMode = Literal["none", "validated"]
type ApplicatorPlanWithBase = (
    ApplicatorBranchPlan | ApplicatorConditionalPlan | ApplicatorOneOfCardinalityPlan
)


@dataclass(frozen=True)
class DifferenceRuleSpec:
    name: str
    fragment: str
    completeness: RuleCompleteness
    witness_mode: RuleWitnessMode
    proof_class: ProofClass
    budget_use: RuleBudgetUse = "none"


@dataclass(frozen=True)
class DifferenceProblem:
    formula: DifferenceFormula
    context: ProofContext

    @property
    def dialect(self) -> Dialect:
        return self.context.dialect

    @property
    def lhs_schema(self) -> Any:
        return self.formula.lhs.schema

    @property
    def rhs_schema(self) -> Any:
        return self.formula.rhs.schema

    def lhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        formula = occurrence_assertion_formula(self.formula.positive_lhs, kind)
        assertion = (
            self.formula.lhs.assertion(kind) if formula is None else formula.assertion
        )
        return None if assertion is None else assertion.value

    def rhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        formula = occurrence_assertion_formula(self.formula.negative_rhs, kind)
        assertion = (
            self.formula.rhs.assertion(kind) if formula is None else formula.assertion
        )
        return None if assertion is None else assertion.value

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


@dataclass(frozen=True)
class ApplicatorProofFlow:
    plan: ApplicatorPlanWithBase
    prove_branch: Callable[[], ProofResult]
    branch_first: bool = False


class EmptinessSolver:
    """Prove or refute schema inclusion by solving language-difference emptiness."""

    def __init__(self, context: ProofContext):
        self.context = context
        self.dialect = context.dialect
        self.rules = difference_rules()

    def prove_difference_empty(self, lhs: Any, rhs: Any) -> ProofResult:
        return self.prove_formula_difference_empty(
            DifferenceFormula.from_schemas(lhs, rhs, self.dialect)
        )

    def prove_formula_difference_empty(self, formula: DifferenceFormula) -> ProofResult:
        problem = DifferenceProblem(formula, self.context)
        unsupported: ProofResult | None = None
        for rule in self.rules:
            proof = rule.prove(problem)
            proof = _proof_after_rule_class_guard(problem, rule, proof)
            if proof.status != "unsupported":
                return proof
            if _should_stop_after_rule_unsupported(rule, proof):
                return _with_formula_diagnostics(formula, proof)
            unsupported = proof
        return (
            _semantic_unsupported(formula)
            or unsupported
            or ProofResult.unsupported(
                "SAT emptiness solver does not support this schema pair"
            )
        )


def _proof_after_rule_class_guard(
    problem: DifferenceProblem,
    rule: DifferenceRule,
    proof: ProofResult,
) -> ProofResult:
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
            "finite-domain-ir",
            _prove_finite_lhs_difference,
            fragment="finite left language",
            completeness="exact",
            witness_mode="validated",
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
) -> FunctionDifferenceRule:
    return FunctionDifferenceRule(
        DifferenceRuleSpec(
            name=name,
            fragment=fragment,
            completeness=completeness,
            witness_mode=witness_mode,
            proof_class=_default_proof_class(completeness, budget_use)
            if proof_class is None
            else proof_class,
            budget_use=budget_use,
        ),
        fn,
    )


def _default_proof_class(
    completeness: RuleCompleteness, budget_use: RuleBudgetUse
) -> ProofClass:
    if completeness == "unsupported_boundary":
        return "unsupported_unreliable"
    return "simple_exact"


def _should_stop_after_rule_unsupported(
    rule: DifferenceRule, proof: ProofResult
) -> bool:
    if proof.diagnostics:
        return True
    if rule.name == "array-unevaluated-items-ir":
        return proof.reason not in {
            "SAT unevaluatedItems difference requires unevaluatedItems",
            (
                "SAT array unevaluatedItems difference is deferred for "
                "left-side static references"
            ),
        }
    if rule.name == "object-unevaluated-properties-ir":
        return proof.reason not in {
            "SAT unevaluatedProperties difference requires unevaluatedProperties",
            (
                "SAT object unevaluatedProperties difference is deferred for "
                "left-side static references"
            ),
        }
    if rule.name != "static-reference-ir":
        return False
    return (
        proof.reason != "SAT static-reference fragment requires a root pure static $ref"
    )


def _prove_trivial_difference(problem: DifferenceProblem) -> ProofResult:
    if _formula_is_syntactically_empty(problem.formula.formula):
        return ProofResult.true()
    if (
        schema_is_false(problem.lhs_schema)
        or schema_is_true(problem.rhs_schema)
        or schemas_equal(problem.lhs_schema, problem.rhs_schema)
    ):
        return ProofResult.true()
    if schema_is_false(problem.rhs_schema):
        empty = schema_is_empty_exact(problem.lhs_schema, problem.context)
        if empty.status == "proved_true":
            return empty
        if empty.status == "resource_exhausted":
            return empty
    return ProofResult.unsupported(
        "schemas are outside the trivial difference fragment"
    )


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
    )


def _dedupe_diagnostics(
    diagnostics: tuple[UnsupportedDiagnostic, ...]
) -> tuple[UnsupportedDiagnostic, ...]:
    seen: set[
        tuple[str, str, str | None, tuple[str, ...], str | None]
    ] = set()
    deduped: list[UnsupportedDiagnostic] = []
    for diagnostic in diagnostics:
        key = (
            diagnostic.category,
            diagnostic.reason,
            diagnostic.keyword,
            diagnostic.path,
            diagnostic.side,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(diagnostic)
    return tuple(deduped)


def _prove_finite_lhs_difference(problem: DifferenceProblem) -> ProofResult:
    finite_constraint = _finite_constraint(problem.lhs_constraint("finite"))
    if finite_constraint is None:
        return ProofResult.unsupported(
            "SAT finite fragment requires finite left language"
        )

    for value in finite_constraint.values:
        confirmed = confirm_difference(
            _lhs_confirmation_source(problem),
            _rhs_confirmation_source(problem),
            value,
        )
        if confirmed.status == "unsupported":
            if confirmed.proof is None:
                return ProofResult.unsupported("finite witness confirmation failed")
            return confirmed.proof
        if confirmed.status == "confirmed":
            return ProofResult.false(value)
    return ProofResult.true()


def _prove_static_reference_difference(problem: DifferenceProblem) -> ProofResult:
    lhs_resolution = root_static_reference_resolution(problem.formula.lhs, side="lhs")
    rhs_resolution = root_static_reference_resolution(problem.formula.rhs, side="rhs")

    if lhs_resolution is None and rhs_resolution is None:
        return ProofResult.unsupported(
            "SAT static-reference fragment requires a root pure static $ref"
        )
    if isinstance(lhs_resolution, StaticReferenceUnsupported):
        if _static_reference_supports_constructive_false(lhs_resolution):
            false_proof = _constructive_static_reference_false(problem)
            if false_proof.status == "proved_false":
                return false_proof
        return ProofResult.unsupported(
            lhs_resolution.reason, diagnostics=lhs_resolution.diagnostic()
        )
    if isinstance(rhs_resolution, StaticReferenceUnsupported):
        if _static_reference_supports_constructive_false(rhs_resolution):
            false_proof = _constructive_static_reference_false(problem)
            if false_proof.status == "proved_false":
                return false_proof
        return ProofResult.unsupported(
            rhs_resolution.reason, diagnostics=rhs_resolution.diagnostic()
        )

    lhs_schema = problem.lhs_schema if lhs_resolution is None else lhs_resolution.schema
    rhs_schema = problem.rhs_schema if rhs_resolution is None else rhs_resolution.schema

    proof = problem.context.subproof(lhs_schema, rhs_schema)
    if proof.status in {"proved_true", "resource_exhausted", "unsupported"}:
        return proof
    if proof.witness is None:
        return ProofResult.unsupported(
            "SAT static-reference witness could not be constructed"
        )
    return _validated_false(
        problem, proof.witness, "SAT static-reference witness was rejected"
    )


def _constructive_static_reference_false(problem: DifferenceProblem) -> ProofResult:
    witness = build_schema_witness(problem.lhs_schema, problem.dialect, problem.context)
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
    unsupported: StaticReferenceUnsupported,
) -> bool:
    return (
        unsupported.category == "static-reference"
        and "dialect transition" in unsupported.reason
    )


def _prove_dynamic_reference_difference(problem: DifferenceProblem) -> ProofResult:
    lhs_resolution = root_dynamic_reference_resolution(problem.formula.lhs, side="lhs")
    rhs_resolution = root_dynamic_reference_resolution(problem.formula.rhs, side="rhs")

    if lhs_resolution is None and rhs_resolution is None:
        return ProofResult.unsupported(
            "SAT dynamic-reference fragment requires a root pure $dynamicRef"
        )
    if isinstance(lhs_resolution, DynamicReferenceUnsupported):
        return ProofResult.unsupported(
            lhs_resolution.reason, diagnostics=lhs_resolution.diagnostic()
        )
    if isinstance(rhs_resolution, DynamicReferenceUnsupported):
        return ProofResult.unsupported(
            rhs_resolution.reason, diagnostics=rhs_resolution.diagnostic()
        )

    lhs_schema = problem.lhs_schema if lhs_resolution is None else lhs_resolution.schema
    rhs_schema = problem.rhs_schema if rhs_resolution is None else rhs_resolution.schema

    proof = problem.context.subproof(lhs_schema, rhs_schema)
    if proof.status in {"proved_true", "resource_exhausted", "unsupported"}:
        return proof
    if proof.witness is None:
        return ProofResult.unsupported(
            "SAT dynamic-reference witness could not be constructed"
        )
    return _validated_false(
        problem, proof.witness, "SAT dynamic-reference witness was rejected"
    )


def _prove_finite_rhs_difference(problem: DifferenceProblem) -> ProofResult:
    if _contains_static_reference(problem):
        return ProofResult.unsupported(
            "SAT finite-rhs fragment is deferred for static references"
        )

    plan = finite_rhs_difference_plan_from_constraints(
        _type_constraint(problem.lhs_constraint("type")),
        _finite_constraint(problem.lhs_constraint("finite")),
        _finite_constraint(problem.rhs_constraint("finite")),
        _numeric_constraint(problem.lhs_constraint("numeric")),
    )
    if plan.status == "unsupported":
        if plan.reason == "SAT finite-rhs witness could not be constructed":
            return _constructive_finite_rhs_false(problem)
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    proof = _validated_any_false(
        problem, plan.witnesses, "SAT finite-rhs witness could not be constructed"
    )
    if proof.status != "unsupported":
        return proof
    return _constructive_finite_rhs_false(problem)


def _constructive_finite_rhs_false(problem: DifferenceProblem) -> ProofResult:
    witness = build_schema_witness(problem.lhs_schema, problem.dialect, problem.context)
    if witness.status == "resource_exhausted":
        return ProofResult.resource_exhausted(witness.reason)
    if witness.status != "witness":
        return ProofResult.unsupported(
            witness.reason or "SAT finite-rhs witness could not be constructed"
        )
    return _validated_false(
        problem, witness.witness, "SAT finite-rhs constructive witness was rejected"
    )


def _prove_finite_complement_difference(problem: DifferenceProblem) -> ProofResult:
    lhs_excluded = _finite_complement_excluded_values(
        problem.lhs_schema, problem.dialect
    )
    rhs_excluded = _finite_complement_excluded_values(
        problem.rhs_schema, problem.dialect
    )
    if rhs_excluded is None:
        return ProofResult.unsupported(
            "SAT finite-complement fragment requires finite negated schemas"
        )
    if lhs_excluded is None:
        return _validated_any_false(
            problem,
            rhs_excluded,
            "SAT finite-complement witness could not be constructed",
        )

    if all(_json_value_in(value, lhs_excluded) for value in rhs_excluded):
        return ProofResult.true()

    for value in rhs_excluded:
        if not _json_value_in(value, lhs_excluded):
            return _validated_false(
                problem, value, "SAT finite-complement witness was rejected"
            )
    return ProofResult.unsupported(
        "SAT finite-complement witness could not be constructed"
    )


def _prove_left_any_of_applicator_difference(problem: DifferenceProblem) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("left-anyof-exact")
    if plan is None:
        return ProofResult.unsupported(
            "SAT left-anyOf applicator fragment requires a pure left anyOf"
        )
    return _prove_left_any_of_difference(problem, plan)


def _prove_left_one_of_applicator_difference(problem: DifferenceProblem) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("left-oneof-exact")
    if plan is None:
        return ProofResult.unsupported(
            "SAT left-oneOf applicator fragment requires a pure left oneOf"
        )
    return _prove_left_one_of_difference(problem, plan)


def _prove_left_all_of_applicator_difference(problem: DifferenceProblem) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("left-allof-exact")
    if plan is None:
        return ProofResult.unsupported(
            "SAT left-allOf applicator fragment requires a pure left allOf"
        )
    return _prove_left_all_of_difference(problem, plan)


def _prove_right_not_applicator_difference(problem: DifferenceProblem) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("right-not-nnf")
    if plan is None:
        return ProofResult.unsupported(
            "SAT right-not applicator fragment requires a supported right not"
        )
    return _run_right_applicator_flow(
        problem,
        ApplicatorProofFlow(
            plan=plan,
            prove_branch=lambda: _prove_rhs_not_difference(problem, plan.nnf),
        ),
    )


def _prove_right_any_of_applicator_difference(
    problem: DifferenceProblem,
) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("right-anyof-nnf-bounded")
    if plan is None:
        return ProofResult.unsupported(
            "SAT right-anyOf applicator fragment requires a supported right anyOf"
        )
    return _run_right_applicator_flow(
        problem,
        ApplicatorProofFlow(
            plan=plan,
            prove_branch=lambda: _prove_rhs_negative_any_of_difference(
                problem, plan.nnf
            ),
            branch_first=True,
        ),
    )


def _prove_right_one_of_applicator_difference(
    problem: DifferenceProblem,
) -> ProofResult:
    tagged_proof = _prove_tagged_right_one_of_difference(problem)
    if tagged_proof.status != "unsupported":
        return tagged_proof

    plan = problem.applicator_plan_set.one_of_cardinality()
    if plan is None:
        return ProofResult.unsupported(
            "SAT right-oneOf applicator fragment requires a supported right oneOf"
        )
    return _run_right_applicator_flow(
        problem,
        ApplicatorProofFlow(
            plan=plan,
            prove_branch=lambda: _prove_rhs_one_of_cardinality_difference(
                problem, plan
            ),
        ),
    )


def _prove_tagged_right_one_of_difference(
    problem: DifferenceProblem,
) -> ProofResult:
    matching_branch = _matching_tagged_rhs_one_of_branch(problem)
    if matching_branch is None:
        return ProofResult.unsupported(
            "SAT right-oneOf tagged fragment requires unique required tags"
        )

    proof = problem.context.subproof(problem.lhs_schema, matching_branch)
    if proof.status == "proved_true":
        return ProofResult.true()
    if proof.status == "resource_exhausted":
        return proof
    if proof.status == "proved_false":
        if proof.certificate is not None:
            return _certified_false(
                "applicator-right-oneof",
                "tagged right oneOf branch has a certified counterexample",
                child=proof,
            )
        if proof.witness is not None:
            return _validated_false(
                problem,
                proof.witness,
                "SAT tagged right-oneOf matching-tag witness was rejected",
            )

    return ProofResult.unsupported(
        "SAT right-oneOf tagged branch proof was inconclusive"
    )


def _matching_tagged_rhs_one_of_branch(problem: DifferenceProblem) -> Any | None:
    tagged = problem.formula.rhs.tagged_one_of
    if tagged is None:
        return None
    lhs_tag = problem.formula.lhs.required_singleton_tag(tagged.tag_name)
    if lhs_tag is None:
        return None
    for branch in tagged.branches:
        if json_values_equal(lhs_tag, branch.tag_value):
            return branch.schema
    return None


def _prove_right_all_of_applicator_difference(
    problem: DifferenceProblem,
) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("right-allof-nnf-exact")
    if plan is None:
        return ProofResult.unsupported(
            "SAT right-allOf applicator fragment requires a supported right allOf"
        )

    return _run_right_applicator_flow(
        problem,
        ApplicatorProofFlow(
            plan=plan,
            prove_branch=lambda: _prove_rhs_negative_all_of_difference(
                problem, plan.nnf
            ),
        ),
    )


def _run_right_applicator_flow(
    problem: DifferenceProblem, flow: ApplicatorProofFlow
) -> ProofResult:
    if flow.branch_first:
        return _run_right_applicator_branch_first_flow(problem, flow)
    return _run_right_applicator_base_first_flow(problem, flow)


def _run_right_applicator_base_first_flow(
    problem: DifferenceProblem, flow: ApplicatorProofFlow
) -> ProofResult:
    base_proof = _prove_applicator_base_difference(problem, flow.plan)
    if applicator_base_pre_branch_choice(base_proof.status) == "base_false":
        return _validated_applicator_base_false(problem, flow.plan, base_proof)

    branch_proof = flow.prove_branch()
    if branch_proof.status == "proved_false":
        return branch_proof
    if base_proof.status == "resource_exhausted":
        return base_proof
    if branch_proof.status == "proved_true" and base_proof.status == "proved_true":
        return ProofResult.true()
    if branch_proof.status == "proved_true":
        return base_proof
    return branch_proof


def _run_right_applicator_branch_first_flow(
    problem: DifferenceProblem, flow: ApplicatorProofFlow
) -> ProofResult:
    branch_proof = flow.prove_branch()
    if branch_proof.status in {"proved_false", "resource_exhausted"}:
        return branch_proof

    base_proof = _prove_applicator_base_difference(problem, flow.plan)
    if applicator_base_pre_branch_choice(base_proof.status) == "base_false":
        return _validated_applicator_base_false(problem, flow.plan, base_proof)
    if base_proof.status in {"unsupported", "resource_exhausted"}:
        return base_proof
    if branch_proof.status == "proved_true":
        return ProofResult.true()
    return branch_proof


def _prove_conditional_applicator_difference(problem: DifferenceProblem) -> ProofResult:
    plan = problem.applicator_plan_set.conditional()
    if plan is None:
        return ProofResult.unsupported(
            "SAT conditional applicator fragment requires pure if/then/else"
        )
    return _prove_conditional_difference(problem, plan)


def _prove_applicator_base_difference(
    problem: DifferenceProblem,
    plan: ApplicatorPlanWithBase,
) -> ProofResult:
    product = applicator_base_product(plan, lhs_schema=problem.lhs_schema)
    if product is None:
        return ProofResult.true()
    return _applicator_base_subproof(problem, product)


def _applicator_base_subproof(
    problem: DifferenceProblem, product: ApplicatorBaseProduct
) -> ProofResult:
    return problem.context.subproof(product.lhs_schema, product.rhs_schema)


def _validated_applicator_base_false(
    problem: DifferenceProblem,
    plan: ApplicatorPlanWithBase,
    proof: ProofResult,
) -> ProofResult:
    product = applicator_base_product(plan, lhs_schema=problem.lhs_schema)
    if product is None:
        return ProofResult.unsupported(
            "SAT applicator base product could not be recovered"
        )
    if proof.certificate is not None:
        return _certified_false(
            "applicator-base",
            "applicator base subproof has a certified counterexample",
            child=proof,
        )
    if proof.witness is None:
        return ProofResult.unsupported(product.witness_missing_reason)
    return _validated_false(problem, proof.witness, product.witness_rejected_reason)


def _prove_conditional_difference(
    problem: DifferenceProblem, plan: ApplicatorConditionalPlan
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, applicator_branch_expansion_budget(plan)
    ):
        return proof
    base_proof = _prove_applicator_base_difference(problem, plan)
    if applicator_base_pre_branch_choice(base_proof.status) == "base_false":
        return _validated_applicator_base_false(problem, plan, base_proof)

    products = conditional_branch_products(
        plan,
        lhs_schema=problem.lhs_schema,
        rhs_schema=problem.rhs_schema,
    )
    if not products:
        return ProofResult.unsupported(plan.reason)

    unsupported: ProofResult | None = None
    for product in products:
        if product.is_trivially_empty_difference:
            continue

        empty = _prove_rhs_conditional_product_empty(problem, product)
        if empty is not None:
            choice = conditional_covering_product_proof_choice(empty.status)
            if choice == "continue":
                continue
            return empty

        proof = problem.context.subproof(product.lhs_schema, product.rhs_schema)
        choice = conditional_branch_proof_choice(proof.status)
        if choice == "continue":
            continue
        if choice == "return_proof":
            return proof
        if choice == "record_unsupported":
            unsupported = proof
            continue
        if proof.witness is None:
            return ProofResult.unsupported(product.witness_missing_reason)
        validated = _validated_false(
            problem, proof.witness, product.witness_rejected_reason
        )
        if validated.status != "unsupported":
            return validated
        unsupported = ProofResult.unsupported(
            validated.reason or product.witness_rejected_reason
        )

    final_choice = conditional_final_proof_choice(
        base_proof.status, has_unsupported_branch=unsupported is not None
    )
    if final_choice == "proved_true":
        return ProofResult.true()
    if final_choice == "base":
        return base_proof
    return unsupported or ProofResult.unsupported(
        "SAT conditional proof had no supported branch result"
    )


def _prove_rhs_conditional_product_empty(
    problem: DifferenceProblem,
    product: ApplicatorConditionalProduct,
) -> ProofResult | None:
    if product.covering_lhs_schema is None or product.covering_schema is None:
        return None

    proof = problem.context.subproof(
        product.covering_lhs_schema, product.covering_schema
    )
    choice = conditional_covering_subproof_choice(proof.status)
    if choice == "proved_true":
        return ProofResult.true()
    if choice == "return_proof":
        return proof
    return None


def _applicator_expansion_budget_exhausted(
    problem: DifferenceProblem,
    expansion_budget: ApplicatorExpansionBudget,
) -> ProofResult | None:
    return problem.context.spend_work(
        expansion_budget.product_count,
        "branch expansion",
        "branch expansion exceeded proof work budget",
    )


def _prove_left_any_of_difference(
    problem: DifferenceProblem, plan: ApplicatorBranchPlan
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, applicator_branch_expansion_budget(plan)
    ):
        return proof
    for product in _left_branch_products(problem, plan):
        proof = _left_branch_subproof(problem, product)
        choice = left_any_of_branch_proof_choice(proof.status)
        if choice == "continue":
            continue
        if choice == "return_proof":
            return proof
        if proof.witness is None:
            return ProofResult.unsupported(product.witness_missing_reason)
        validated = _validated_false(
            problem, proof.witness, product.witness_rejected_reason
        )
        if validated.status != "unsupported":
            return validated
        return ProofResult.unsupported(
            validated.reason or product.witness_rejected_reason
        )
    return ProofResult.true()


def _prove_left_one_of_difference(
    problem: DifferenceProblem, plan: ApplicatorBranchPlan
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, applicator_branch_expansion_budget(plan)
    ):
        return proof
    unsupported: ProofResult | None = None
    for product in _left_branch_products(problem, plan):
        proof = _left_branch_subproof(problem, product)
        choice = left_one_of_branch_proof_choice(proof.status)
        if choice == "continue":
            continue
        if choice == "return_proof":
            return proof
        if choice == "record_unsupported":
            unsupported = proof
            continue
        if choice == "validate_witness" and proof.certificate is not None:
            return _certified_false(
                "applicator-right-anyof",
                "negative anyOf branch product has a certified counterexample",
                child=proof,
            )
        if choice == "validate_witness":
            validated = _validated_false(
                problem, proof.witness, product.witness_rejected_reason
            )
            if validated.status != "unsupported":
                return validated
            unsupported = ProofResult.unsupported(
                product.witness_unsupported_reason or product.witness_rejected_reason
            )
            continue
        unsupported = ProofResult.unsupported(product.witness_missing_reason)
    return ProofResult.true() if unsupported is None else unsupported


def _prove_left_all_of_difference(
    problem: DifferenceProblem, plan: ApplicatorBranchPlan
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, applicator_branch_expansion_budget(plan)
    ):
        return proof
    unsupported: ProofResult | None = None
    for product in _left_branch_products(problem, plan):
        proof = _left_branch_subproof(problem, product)
        choice = left_all_of_branch_proof_choice(proof.status)
        if choice == "proved_true":
            return ProofResult.true()
        if choice == "return_proof":
            return proof
        if choice == "record_unsupported":
            unsupported = proof
            continue
        if choice == "validate_witness" and proof.certificate is not None:
            return _certified_false(
                "applicator-right-oneof",
                "right oneOf branch product has a certified counterexample",
                child=proof,
            )
        if choice == "validate_witness":
            validated = _validated_false(
                problem, proof.witness, product.witness_rejected_reason
            )
            if validated.status != "unsupported":
                return validated
    return unsupported or ProofResult.unsupported(
        "SAT left-allOf proof could not establish a covering conjunct"
    )


def _left_branch_products(
    problem: DifferenceProblem,
    plan: ApplicatorBranchPlan,
) -> tuple[ApplicatorBranchProduct, ...]:
    return applicator_branch_products(
        plan,
        lhs_schema=problem.lhs_schema,
        rhs_schema=problem.rhs_schema,
    )


def _left_branch_subproof(
    problem: DifferenceProblem, product: ApplicatorBranchProduct
) -> ProofResult:
    lhs_schema = _subproof_schema_for_node_static_reference(
        problem, product.child, "lhs"
    )
    if isinstance(lhs_schema, StaticReferenceUnsupported):
        return ProofResult.unsupported(
            lhs_schema.reason, diagnostics=lhs_schema.diagnostic()
        )
    if isinstance(lhs_schema, ReferenceResolution):
        return problem.context.subproof(
            left_branch_resolved_lhs_schema(product, lhs_schema.schema),
            product.rhs_schema,
        )
    return problem.context.subproof(product.lhs_schema, product.rhs_schema)


def _subproof_schema_for_node_static_reference(
    problem: DifferenceProblem,
    node: SchemaNode,
    side: Literal["lhs", "rhs"],
) -> ReferenceResolution | StaticReferenceUnsupported | None:
    return static_reference_resolution_for_schema(
        node.source.schema,
        problem.formula.occurrence(side).ir.graph,
        source_resource_uri=node.source.resource_uri,
        source_pointer=node.source.pointer,
        source_resource_pointer=node.source.resource_pointer,
        source_dialect=node.source.dialect,
        side=side,
    )


def _prove_rhs_negative_any_of_difference(
    problem: DifferenceProblem, nnf: ApplicatorNnfFragment
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, applicator_branch_expansion_budget(nnf)
    ):
        return proof
    product_plan = right_negative_any_of_branch_product_plan(
        nnf, lhs_schema=problem.lhs_schema
    )
    if not product_plan.is_supported:
        return ProofResult.unsupported(product_plan.unsupported_reason)

    unsupported: ProofResult | None = None
    for product in product_plan.products:
        proof = _rhs_nnf_branch_subproof(problem, product)
        choice = right_negative_any_of_branch_proof_choice(proof.status)
        if choice == "proved_true":
            return ProofResult.true()
        if choice == "return_proof":
            return proof
        if choice == "record_unsupported":
            unsupported = proof
            continue
        if choice == "validate_witness" and proof.certificate is not None:
            return _certified_false(
                "applicator-right-anyof",
                "negative anyOf branch product has a certified counterexample",
                child=proof,
            )
        if choice == "validate_witness":
            validated = _validated_false(
                problem, proof.witness, product.witness_rejected_reason
            )
            if validated.status != "unsupported":
                return validated
    certified = _certified_array_item_against_rhs_anyof(problem)
    if certified is not None:
        return certified
    tuple_distribution = _prove_lhs_tuple_anyof_distribution(problem)
    if tuple_distribution is not None and tuple_distribution.status != "unsupported":
        return tuple_distribution
    return unsupported or ProofResult.unsupported(
        "SAT negative anyOf proof could not establish a covering branch"
    )


def _prove_lhs_tuple_anyof_distribution(
    problem: DifferenceProblem,
) -> ProofResult | None:
    branches = _lhs_tuple_anyof_distribution_branches(problem.lhs_schema)
    if branches is None:
        return None

    if proof := problem.context.spend_work(
        len(branches),
        "array product",
        "array tuple anyOf distribution exceeded proof work budget",
    ):
        return proof

    unsupported: ProofResult | None = None
    for branch in branches:
        proof = problem.context.subproof(branch, problem.rhs_schema)
        if proof.status == "proved_true":
            continue
        if proof.status == "proved_false":
            if proof.certificate is not None:
                return _certified_false(
                    "array-item-anyof",
                    "tuple anyOf distribution branch has a certified counterexample",
                    child=proof,
                )
            if proof.witness is None:
                return ProofResult.unsupported(
                    "tuple anyOf distribution counterexample is missing"
                )
            return _validated_false(
                problem, proof.witness, "tuple anyOf distribution witness was rejected"
            )
        if proof.status == "resource_exhausted":
            return proof
        unsupported = proof
    return ProofResult.true() if unsupported is None else unsupported


def _lhs_tuple_anyof_distribution_branches(schema: Any) -> tuple[Any, ...] | None:
    if not isinstance(schema, dict):
        return None
    if type_overapproximation_for_schema(schema) != frozenset({"array"}):
        return None

    items = schema.get("items")
    if not isinstance(items, list):
        return None

    item_choices: list[tuple[Any, ...]] = []
    has_choice = False
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("anyOf"), list):
            choices = tuple(item["anyOf"])
            if not choices:
                return None
            item_choices.append(choices)
            has_choice = True
        else:
            item_choices.append((item,))
    if not has_choice:
        return None

    branches = []
    for chosen_items in product(*item_choices):
        branch = deepcopy(schema)
        branch["items"] = [deepcopy(item) for item in chosen_items]
        branches.append(branch)
    return tuple(branches)


def _prove_rhs_one_of_cardinality_difference(
    problem: DifferenceProblem,
    plan: ApplicatorOneOfCardinalityPlan,
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, one_of_coverage_expansion_budget(plan)
    ):
        return proof
    products = one_of_cardinality_products(plan, lhs_schema=problem.lhs_schema)
    covering_indexes = []
    unsupported: ProofResult | None = None
    for product in products:
        proof = _rhs_one_of_branch_subproof(problem, product)
        choice = one_of_coverage_branch_proof_choice(proof.status)
        if choice == "record_covering":
            covering_indexes.append(product.index)
            continue
        if choice == "return_proof":
            return proof
        if choice == "record_unsupported":
            unsupported = proof
            continue
        if choice == "validate_witness" and proof.certificate is not None:
            return _certified_false(
                "applicator-right-oneof",
                "right oneOf branch product has a certified counterexample",
                child=proof,
            )
        if choice == "validate_witness":
            validated = _validated_false(
                problem, proof.witness, product.witness_rejected_reason
            )
            if validated.status != "unsupported":
                return validated

    covering = one_of_covering_selection(
        plan,
        lhs_schema=problem.lhs_schema,
        covering_indexes=tuple(covering_indexes),
    )
    if covering.overlap_product is not None:
        witness_plan = one_of_overlap_witness_plan(
            covering.overlap_product, problem.dialect
        )
        if witness_plan.status == "resource_exhausted":
            return ProofResult.resource_exhausted(witness_plan.reason)
        if (
            witness_plan.status == "certificate"
            and witness_plan.certificate is not None
        ):
            return ProofResult.certified_false(witness_plan.certificate)
        if not witness_plan.has_witness:
            return ProofResult.unsupported(witness_plan.reason)
        return _validated_false(
            problem,
            witness_plan.witness,
            covering.overlap_product.witness_rejected_reason,
        )
    covered_index = covering.covered_index
    if covered_index is None:
        return unsupported or ProofResult.unsupported(covering.unsupported_reason)

    if proof := _applicator_expansion_budget_exhausted(
        problem, one_of_disjointness_expansion_budget(plan)
    ):
        return proof
    for disjoint_product in _one_of_disjointness_products(problem, plan, covered_index):
        disjoint = _prove_rhs_one_of_disjointness_product(problem, disjoint_product)
        choice = one_of_disjointness_proof_choice(disjoint.status)
        if choice == "proved_true":
            continue
        if choice == "validate_witness" and disjoint.witness is not None:
            return _validated_false(
                problem,
                disjoint.witness,
                disjoint_product.witness_rejected_reason,
            )
        return disjoint
    return ProofResult.true()


def _prove_rhs_one_of_disjointness_product(
    problem: DifferenceProblem,
    product: ApplicatorOneOfDisjointnessProduct,
) -> ProofResult:
    branch_schema = _rhs_schema_for_node_static_reference(problem, product.child)
    if isinstance(branch_schema, StaticReferenceUnsupported):
        return ProofResult.unsupported(
            branch_schema.reason, diagnostics=branch_schema.diagnostic()
        )
    resolved_branch_schema = one_of_disjointness_resolved_branch_schema(
        product,
        branch_schema.schema
        if isinstance(branch_schema, ReferenceResolution)
        else None,
    )
    disjoint = schemas_are_disjoint(
        product.lhs_schema,
        resolved_branch_schema,
        problem.context,
    )
    if one_of_disjointness_direct_proof_choice(disjoint.status) == "return_proof":
        return disjoint

    complement_schema = one_of_disjointness_complement_schema(
        product, resolved_branch_schema
    )
    complement = problem.context.subproof(product.lhs_schema, complement_schema)
    choice = one_of_disjointness_proof_choice(complement.status)
    if choice == "proved_true":
        return ProofResult.true()
    if choice == "validate_witness":
        if complement.witness is None:
            return ProofResult.unsupported(product.witness_missing_reason)
        return ProofResult.false(complement.witness)
    return complement


def _one_of_disjointness_products(
    problem: DifferenceProblem,
    plan: ApplicatorOneOfCardinalityPlan,
    covered_index: int,
) -> tuple[ApplicatorOneOfDisjointnessProduct, ...]:
    return one_of_disjointness_products(
        plan,
        lhs_schema=problem.lhs_schema,
        covered_index=covered_index,
    )


def _prove_rhs_negative_all_of_difference(
    problem: DifferenceProblem, nnf: ApplicatorNnfFragment
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, applicator_branch_expansion_budget(nnf)
    ):
        return proof
    product_plan = right_negative_all_of_branch_product_plan(
        nnf, lhs_schema=problem.lhs_schema
    )
    if not product_plan.is_supported:
        return ProofResult.unsupported(product_plan.unsupported_reason)

    for product in product_plan.products:
        proof = _rhs_nnf_branch_subproof(problem, product)
        choice = right_negative_all_of_branch_proof_choice(proof.status)
        if choice == "continue":
            continue
        if choice == "return_proof":
            return proof
        if proof.certificate is not None:
            return _certified_false(
                "applicator-right-allof",
                "negative allOf branch product has a certified counterexample",
                child=proof,
            )
        if proof.witness is None:
            return ProofResult.unsupported(product.witness_missing_reason)
        validated = _validated_false(
            problem, proof.witness, product.witness_rejected_reason
        )
        if validated.status != "unsupported":
            return validated
        return ProofResult.unsupported(
            validated.reason or product.witness_rejected_reason
        )
    return ProofResult.true()


def _rhs_nnf_branch_subproof(
    problem: DifferenceProblem, product: ApplicatorNnfBranchProduct
) -> ProofResult:
    rhs_schema = _rhs_schema_for_node_static_reference(problem, product.child.node)
    if isinstance(rhs_schema, StaticReferenceUnsupported):
        return ProofResult.unsupported(
            rhs_schema.reason, diagnostics=rhs_schema.diagnostic()
        )
    if isinstance(rhs_schema, ReferenceResolution):
        return problem.context.subproof(
            product.lhs_schema,
            right_nnf_branch_resolved_rhs_schema(product, rhs_schema.schema),
        )
    return problem.context.subproof(
        product.lhs_schema,
        right_nnf_branch_resolved_rhs_schema(product, None),
    )


def _certified_array_item_against_rhs_anyof(
    problem: DifferenceProblem,
) -> ProofResult | None:
    rhs_schema = problem.rhs_schema
    if not isinstance(rhs_schema, dict):
        return None
    branches = rhs_schema.get("anyOf")
    if not isinstance(branches, list) or not branches:
        return None

    rhs_item_schemas = []
    for branch in branches:
        if not isinstance(branch, dict) or branch.get("type") != "array":
            return None
        items = branch.get("items", True)
        if isinstance(items, bool | list):
            return None
        rhs_item_schemas.append(items)

    model = problem.array_model
    if model.first_lhs_length_reaching(0) is None:
        return None

    proof = problem.context.subproof(
        model.lhs_item_schema_at(0),
        {"anyOf": rhs_item_schemas},
    )
    if not proof.has_counterexample:
        return None
    return _certified_false(
        "array-item-anyof",
        "a reachable array item violates every RHS anyOf array item schema",
        path=("0",),
        child=proof,
    )


def _rhs_one_of_branch_subproof(
    problem: DifferenceProblem, product: ApplicatorOneOfBranchProduct
) -> ProofResult:
    branch_schema = _rhs_schema_for_node_static_reference(problem, product.child)
    if isinstance(branch_schema, StaticReferenceUnsupported):
        return ProofResult.unsupported(
            branch_schema.reason, diagnostics=branch_schema.diagnostic()
        )
    if isinstance(branch_schema, ReferenceResolution):
        return problem.context.subproof(
            product.lhs_schema,
            one_of_branch_resolved_schema(product, branch_schema.schema),
        )
    return problem.context.subproof(
        product.lhs_schema,
        one_of_branch_resolved_schema(product, None),
    )


def _rhs_schema_for_node_static_reference(
    problem: DifferenceProblem,
    node: SchemaNode,
) -> ReferenceResolution | StaticReferenceUnsupported | None:
    return _subproof_schema_for_node_static_reference(problem, node, "rhs")


def _prove_rhs_not_difference(
    problem: DifferenceProblem, nnf: ApplicatorNnfFragment
) -> ProofResult:
    product = _rhs_nnf_schema_product(problem, nnf)
    if product is None:
        return ProofResult.unsupported(nnf.reason)

    rhs_schema = _rhs_not_product_schema(problem, product)
    if isinstance(rhs_schema, StaticReferenceUnsupported):
        return ProofResult.unsupported(
            rhs_schema.reason, diagnostics=rhs_schema.diagnostic()
        )

    lhs_negated = _pure_not_subschema(product.lhs_schema)
    if lhs_negated is not None:
        proof = problem.context.subproof(rhs_schema, lhs_negated)
        choice = right_not_complement_proof_choice(proof.status)
        if choice == "proved_true":
            return ProofResult.true()
        if choice == "return_resource_exhausted":
            return ProofResult.resource_exhausted(
                proof.reason
                or "SAT right-not lhs complement subproof exhausted its budget"
            )
        if choice == "validate_witness":
            if proof.certificate is not None:
                return _certified_false(
                    "applicator-right-not",
                    "left and right pure-not product has a certified counterexample",
                    child=proof,
                )
            if proof.witness is None:
                return ProofResult.unsupported(
                    product.complement_witness_missing_reason
                )
            return _validated_false(
                problem, proof.witness, product.complement_witness_rejected_reason
            )

    double_negated_rhs = _pure_not_subschema(rhs_schema)
    if double_negated_rhs is not None:
        proof = problem.context.subproof(product.lhs_schema, double_negated_rhs)
        if proof.status in {"proved_true", "resource_exhausted", "unsupported"}:
            return proof
        if proof.certificate is not None:
            return _certified_false(
                "applicator-right-not",
                "double negated right-not product has a certified counterexample",
                child=proof,
            )
        if proof.witness is None:
            return ProofResult.unsupported(product.complement_witness_missing_reason)
        return _validated_false(
            problem, proof.witness, product.complement_witness_rejected_reason
        )

    disjoint = schemas_are_disjoint(product.lhs_schema, rhs_schema, problem.context)
    if disjoint.status == "proved_true":
        return ProofResult.true()
    if disjoint.status == "proved_false" and disjoint.witness is not None:
        return _validated_false(
            problem, disjoint.witness, product.witness_rejected_reason
        )
    if disjoint.status == "resource_exhausted":
        return disjoint

    string_overlap = right_not_string_overlap_plan_from_constraints(
        _string_language_constraint(problem.lhs_constraint("string-language")),
        product.rhs_string_language_constraint,
        product.lhs_schema,
        rhs_schema,
        problem.dialect,
        problem.context,
    )
    choice = right_not_string_overlap_proof_choice(string_overlap.status)
    if choice == "proved_true":
        return ProofResult.true()
    if choice == "validate_witness":
        return _validated_false(
            problem, string_overlap.witness, string_overlap.rejected_reason
        )
    if choice == "return_resource_exhausted":
        return ProofResult.resource_exhausted(
            string_overlap.reason or "regex proof exceeded proof work budget"
        )

    proof = problem.context.subproof(product.lhs_schema, rhs_schema)
    choice = right_not_subproof_choice(proof.status)
    if choice == "materialize_witness":
        witness_plan = right_not_witness_plan(product, problem.dialect)
        if witness_plan.status == "resource_exhausted":
            return ProofResult.resource_exhausted(witness_plan.reason)
        if (
            witness_plan.status == "certificate"
            and witness_plan.certificate is not None
        ):
            return ProofResult.certified_false(witness_plan.certificate)
        if not witness_plan.has_witness:
            return ProofResult.unsupported(witness_plan.reason)
        return _validated_false(
            problem, witness_plan.witness, product.witness_rejected_reason
        )
    if choice == "return_resource_exhausted":
        return ProofResult.resource_exhausted(
            proof.reason or "SAT right-not subproof exhausted its budget"
        )
    if choice == "return_unsupported":
        return ProofResult.unsupported(
            proof.reason or "SAT right-not subproof is unsupported"
        )

    complement_schema = right_not_complement_schema(product, rhs_schema)
    if right_not_complement_needs_subproof(
        product,
        complement_schema,
        original_lhs_schema=problem.lhs_schema,
        original_rhs_schema=problem.rhs_schema,
    ):
        complement = problem.context.subproof(product.lhs_schema, complement_schema)
        choice = right_not_complement_proof_choice(complement.status)
        if choice == "proved_true":
            return ProofResult.true()
        if choice == "validate_witness":
            if complement.witness is None:
                return ProofResult.unsupported(
                    product.complement_witness_missing_reason
                )
            return _validated_false(
                problem, complement.witness, product.complement_witness_rejected_reason
            )
        if choice == "return_resource_exhausted":
            return ProofResult.resource_exhausted(
                complement.reason
                or "SAT right-not complement subproof exhausted its budget"
            )
    intersection_witness = right_not_intersection_witness_plan(
        product, rhs_schema, problem.dialect
    )
    if intersection_witness.status == "resource_exhausted":
        return ProofResult.resource_exhausted(intersection_witness.reason)
    if (
        intersection_witness.status == "certificate"
        and intersection_witness.certificate is not None
    ):
        return ProofResult.certified_false(intersection_witness.certificate)
    if intersection_witness.has_witness:
        return _validated_false(
            problem,
            intersection_witness.witness,
            product.complement_witness_rejected_reason,
        )
    return ProofResult.unsupported(
        "SAT right-not difference could not prove left implies negated schema"
    )


def _pure_not_subschema(schema: Any) -> Any | None:
    if not isinstance(schema, dict):
        return None
    semantic_keys = tuple(
        key
        for key in schema
        if key not in {"$comment", "$id", "$schema", "description", "title"}
    )
    if semantic_keys != ("not",):
        return None
    return schema["not"]


def _rhs_not_product_schema(
    problem: DifferenceProblem,
    product: ApplicatorNnfSchemaProduct,
) -> Any | StaticReferenceUnsupported:
    rhs_schema = _rhs_schema_for_node_static_reference(problem, product.child.node)
    if isinstance(rhs_schema, StaticReferenceUnsupported):
        return rhs_schema
    return right_not_resolved_rhs_schema(
        product,
        rhs_schema.schema if isinstance(rhs_schema, ReferenceResolution) else None,
    )


def _rhs_nnf_schema_product(
    problem: DifferenceProblem,
    nnf: ApplicatorNnfFragment,
) -> ApplicatorNnfSchemaProduct | None:
    return applicator_nnf_schema_product(nnf, lhs_schema=problem.lhs_schema)


def _prove_type_difference(problem: DifferenceProblem) -> ProofResult:
    lhs_constraint = _type_constraint(problem.lhs_constraint("type"))
    rhs_constraint = _type_constraint(problem.rhs_constraint("type"))
    plan = type_difference_plan_from_constraints(
        lhs_constraint,
        rhs_constraint,
    )
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    if lhs_constraint is None or rhs_constraint is None:
        return _validated_false(problem, plan.witness, plan.rejected_reason)
    extra_atoms = lhs_constraint.shape.atoms - rhs_constraint.shape.atoms
    lhs_witness = build_schema_witness(
        problem.lhs_schema, problem.dialect, problem.context
    )
    witnesses = tuple(witness_for_type_atom(atom) for atom in sorted(extra_atoms)) + (
        (lhs_witness.witness,) if lhs_witness.has_witness else ()
    )
    return _validated_any_false(problem, witnesses, plan.rejected_reason)


def _prove_numeric_difference(problem: DifferenceProblem) -> ProofResult:
    lhs_numeric = _numeric_constraint(problem.lhs_constraint("numeric"))
    rhs_type = _type_constraint(problem.rhs_constraint("type"))
    if (
        lhs_numeric is not None
        and lhs_numeric.shape.accepts_non_numeric
        and rhs_type is not None
        and not rhs_type.language_complete
        and _schema_has_non_numeric_assertions(problem.rhs_schema)
    ):
        return ProofResult.unsupported(
            "SAT numeric fragment cannot prove unmodeled non-numeric right semantics"
        )
    plan = numeric_difference_plan_from_constraints(
        lhs_numeric,
        _numeric_constraint(problem.rhs_constraint("numeric")),
        context=problem.context,
        lhs_type=_type_constraint(problem.lhs_constraint("type")),
        rhs_type=rhs_type,
    )
    if isinstance(plan, ProofResult):
        return plan
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _prove_string_length_difference(problem: DifferenceProblem) -> ProofResult:
    plan = string_length_difference_plan_from_constraints(
        _string_length_constraint(problem.lhs_constraint("string-length")),
        _string_length_constraint(problem.rhs_constraint("string-length")),
    )
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _prove_string_language_difference(problem: DifferenceProblem) -> ProofResult:
    plan = string_language_difference_plan_from_constraints(
        _string_language_constraint(problem.lhs_constraint("string-language")),
        _string_language_constraint(problem.rhs_constraint("string-language")),
        context=problem.context,
    )
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _prove_typed_scalar_difference(problem: DifferenceProblem) -> ProofResult:
    if _contains_static_reference(problem):
        return ProofResult.unsupported(
            "SAT typed-scalar fragment is deferred for static references"
        )
    if _schema_has_object_or_array_assertions(
        problem.lhs_schema
    ) or _schema_has_object_or_array_assertions(problem.rhs_schema):
        return ProofResult.unsupported(
            "SAT typed-scalar fragment excludes object and array assertions"
        )

    lhs_type = _type_constraint(problem.lhs_constraint("type"))
    rhs_type = _type_constraint(problem.rhs_constraint("type"))
    lhs_numeric = _numeric_constraint_for_typed_scalar(
        problem.lhs_schema,
        lhs_type,
        _numeric_constraint(problem.lhs_constraint("numeric")),
    )
    rhs_numeric = _numeric_constraint_for_typed_scalar(
        problem.rhs_schema,
        rhs_type,
        _numeric_constraint(problem.rhs_constraint("numeric")),
    )
    lhs_string = _string_language_constraint(problem.lhs_constraint("string-language"))
    rhs_string = _string_language_constraint(problem.rhs_constraint("string-language"))
    plan = typed_scalar_difference_plan_from_constraints(
        lhs_type,
        rhs_type,
        lhs_numeric,
        rhs_numeric,
        lhs_string,
        rhs_string,
        context=problem.context,
    )
    if isinstance(plan, ProofResult):
        return plan
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        if (
            lhs_type is not None
            and rhs_type is not None
            and not rhs_type.language_complete
            and not all(
                _typed_scalar_rhs_atom_is_modeled(
                    problem,
                    atom,
                    lhs_numeric=problem.lhs_constraint("numeric"),
                    rhs_numeric=problem.rhs_constraint("numeric"),
                    lhs_string=problem.lhs_constraint("string-language"),
                    rhs_string=problem.rhs_constraint("string-language"),
                )
                for atom in lhs_type.atoms
            )
        ):
            return ProofResult.unsupported(
                "SAT typed-scalar fragment requires modeled right scalar semantics"
            )
        return ProofResult.true()
    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _typed_scalar_rhs_atom_is_modeled(
    problem: DifferenceProblem,
    atom: str,
    *,
    lhs_numeric: NumericConstraint | None,
    rhs_numeric: NumericConstraint | None,
    lhs_string: StringLanguageConstraint | None,
    rhs_string: StringLanguageConstraint | None,
) -> bool:
    if schema_covers_type_atom(problem.rhs_schema, atom):
        return True
    if atom in {"integer", "number"}:
        return lhs_numeric is not None and rhs_numeric is not None
    if atom == "string":
        return lhs_string is not None and rhs_string is not None
    return False


def _finite_constraint(value: Any) -> FiniteConstraint | None:
    return value if isinstance(value, FiniteConstraint) else None


def _type_constraint(value: Any) -> TypeConstraint | None:
    return value if isinstance(value, TypeConstraint) else None


def _numeric_constraint(value: Any) -> NumericConstraint | None:
    return value if isinstance(value, NumericConstraint) else None


def _string_length_constraint(value: Any) -> StringLengthConstraint | None:
    return value if isinstance(value, StringLengthConstraint) else None


def _string_language_constraint(value: Any) -> StringLanguageConstraint | None:
    return value if isinstance(value, StringLanguageConstraint) else None


def _array_static_reference_unsupported(
    problem: DifferenceProblem, fragment: str
) -> ProofResult | None:
    if _contains_static_reference(problem):
        return ProofResult.unsupported(
            f"SAT {fragment} is deferred for static references"
        )
    return None


def _object_static_reference_unsupported(
    problem: DifferenceProblem, fragment: str
) -> ProofResult | None:
    if _contains_static_reference(problem):
        return ProofResult.unsupported(
            f"SAT {fragment} is deferred for static references"
        )
    return None


def _lhs_static_reference_unsupported(
    problem: DifferenceProblem, fragment: str
) -> ProofResult | None:
    if contains_reference_keyword(problem.lhs_schema, {"$ref", "$recursiveRef"}):
        return ProofResult.unsupported(
            f"SAT {fragment} is deferred for left-side static references"
        )
    return None


def _prove_array_unevaluated_items_difference(
    problem: DifferenceProblem,
) -> ProofResult:
    if proof := _lhs_static_reference_unsupported(
        problem, "array unevaluatedItems difference"
    ):
        return proof
    model = problem.array_model
    plan = model.unevaluated_items_difference_plan(
        budget=_array_witness_horizon(problem),
        expanded=problem.context.allows_expensive_proof("evaluation_trace"),
    )
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        witness = materialize_array_witness_skeleton(
            plan.witness_skeleton, problem.dialect
        )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason or "SAT unevaluatedItems witness could not be constructed"
            )
        return _validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = problem.context.subproof(obligation.lhs_schema, obligation.rhs_schema)
        if proof.status == "resource_exhausted":
            return ProofResult.resource_exhausted(
                proof.reason
                or "SAT unevaluatedItems finite-left item proof exhausted its budget"
            )
        if proof.status == "unsupported":
            return ProofResult.unsupported(
                proof.reason
                or "SAT unevaluatedItems finite-left item proof is unsupported"
            )
        if proof.status == "proved_false":
            if proof.witness is None:
                return ProofResult.unsupported(
                    "SAT unevaluatedItems finite-left item witness is missing"
                )
            budget = _array_witness_horizon(problem)
            skeleton = model.array_witness_skeleton_reaching(
                obligation.index, budget=budget
            )
            witness = materialize_array_witness_skeleton(
                skeleton,
                problem.dialect,
                override=(obligation.index, proof.witness),
            )
            if witness is None:
                if model.array_witness_skeleton_reaching_budget_exhausted(
                    obligation.index, budget=budget
                ):
                    return ProofResult.resource_exhausted(
                        "array witness exceeded proof work budget"
                    )
                return ProofResult.unsupported(
                    "SAT unevaluatedItems finite-left item witness could not be "
                    "constructed"
                )
            return _validated_false(
                problem,
                witness,
                "SAT unevaluatedItems finite-left item witness was rejected",
            )

    return ProofResult.true()


def _prove_array_length_difference(problem: DifferenceProblem) -> ProofResult:
    if proof := _array_static_reference_unsupported(problem, "array length difference"):
        return proof
    model = problem.array_model
    plan = model.length_difference_plan(budget=_array_witness_horizon(problem))
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    witness = plan.witness
    if plan.witness_plan is not None:
        witness = materialize_array_witness_plan(plan.witness_plan, problem.dialect)
    if plan.witness_skeleton is not None:
        witness = materialize_array_witness_skeleton(
            plan.witness_skeleton, problem.dialect
        )
    if witness is None:
        return ProofResult.unsupported(
            plan.reason or "SAT array length witness could not be constructed"
        )
    return _validated_false(problem, witness, plan.rejected_reason)


def _prove_array_uniqueness_difference(problem: DifferenceProblem) -> ProofResult:
    if proof := _array_static_reference_unsupported(
        problem, "array uniqueness difference"
    ):
        return proof
    model = problem.array_model
    plan = model.uniqueness_difference_plan(budget=_array_witness_horizon(problem))
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        witness = plan.witness
        if plan.witness_skeleton is not None:
            witness = materialize_array_witness_skeleton(
                plan.witness_skeleton, problem.dialect
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason
                or "SAT array uniqueness array witness could not be constructed"
            )
        return _validated_false(problem, witness, plan.rejected_reason)

    duplicate_witness = materialize_array_duplicate_witness_plan(
        plan.duplicate_plan, problem.dialect
    )
    if duplicate_witness is None:
        return ProofResult.unsupported(
            plan.reason
            or "SAT array uniqueness difference could not construct a duplicate witness"
        )
    return _validated_false(problem, duplicate_witness, plan.rejected_reason)


def _prove_array_contains_difference(problem: DifferenceProblem) -> ProofResult:
    if proof := _array_static_reference_unsupported(
        problem, "array contains difference"
    ):
        return proof
    model = problem.array_model
    plan = model.contains_difference_plan(
        problem.context, budget=_array_witness_horizon(problem)
    )
    if plan.status == "unsupported" and plan.reason in {
        "SAT array contains count bounds could not be proven exactly",
        "SAT array contains max violation witness needs a lower length bound",
    }:
        gate = problem.context.enter_expensive_proof("array_product")
        if gate is not None:
            return gate
        plan = model.contains_difference_plan(
            problem.context,
            budget=_array_witness_horizon(problem),
            expanded=True,
        )
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        if model.has_rhs_item_value_constraints():
            rhs_item_value_proof = _array_contains_rhs_item_value_witness(
                problem, model
            )
            if rhs_item_value_proof is not None:
                return rhs_item_value_proof
            return ProofResult.unsupported(
                "SAT array contains difference cannot prove RHS item value constraints"
            )
        return ProofResult.true()

    contains_witness = plan.witness
    if plan.witness_plan is not None:
        contains_witness = materialize_array_witness_plan(
            plan.witness_plan, problem.dialect
        )
    if contains_witness is None:
        return ProofResult.unsupported(
            plan.reason or "SAT array contains witness could not be constructed"
        )
    return _validated_false(problem, contains_witness, plan.rejected_reason)


def _array_contains_rhs_item_value_witness(
    problem: DifferenceProblem,
    model: ArrayDifferenceModel,
) -> ProofResult | None:
    lhs_contains = model.lhs_contains
    if lhs_contains is None:
        return None
    contains_witness = build_schema_witness(lhs_contains.schema, problem.dialect)
    if not contains_witness.has_witness:
        return None

    for slot in model.rhs_slots:
        if slot.schema is True:
            continue
        slot_violation = problem.context.subproof(True, slot.schema)
        if slot_violation.status == "resource_exhausted":
            return ProofResult.resource_exhausted(
                slot_violation.reason
                or "SAT array contains slot subproof exhausted its budget"
            )
        if slot_violation.status != "proved_false" or slot_violation.witness is None:
            continue

        overrides = {slot.index: slot_violation.witness}
        contains_confirmed = confirm_valid(
            lhs_contains.schema,
            slot_violation.witness,
            problem.context,
        )
        if contains_confirmed.status == "unsupported":
            if contains_confirmed.proof is None:
                return ProofResult.unsupported("contains witness confirmation failed")
            return contains_confirmed.proof
        if contains_confirmed.status == "confirmed":
            contains_index = slot.index
        else:
            contains_index = 0 if slot.index != 0 else slot.index + 1
            overrides[contains_index] = contains_witness.witness

        length = max(overrides) + 1
        skeleton = model.array_witness_skeleton(
            length, budget=_array_witness_horizon(problem)
        )
        witness = materialize_array_witness_skeleton(
            skeleton, problem.dialect, override=overrides
        )
        if witness is None:
            continue
        proof = _validated_false(
            problem,
            witness,
            "SAT array contains RHS item-value witness was rejected",
        )
        if proof.status != "unsupported":
            return proof
    return None


def _prove_array_item_values_difference(problem: DifferenceProblem) -> ProofResult:
    if proof := _array_static_reference_unsupported(
        problem, "array item-values difference"
    ):
        return proof
    model = problem.array_model
    plan = model.item_values_difference_plan(
        problem.dialect, budget=_array_witness_horizon(problem)
    )
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        witness = plan.witness
        if plan.witness_plan is not None:
            witness = materialize_array_witness_plan(plan.witness_plan, problem.dialect)
        elif plan.witness_skeleton is not None:
            witness = materialize_array_witness_skeleton(
                plan.witness_skeleton, problem.dialect
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason or "SAT array item-values witness could not be constructed"
            )
        return _validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = problem.context.subproof(obligation.lhs_schema, obligation.rhs_schema)
        if proof.status == "resource_exhausted":
            return ProofResult.resource_exhausted(
                proof.reason or "SAT array item-values proof exhausted its budget"
            )
        if proof.status == "unsupported":
            return ProofResult.unsupported(
                proof.reason or "SAT array item-values proof is unsupported"
            )
        if proof.status == "proved_false":
            if not proof.has_counterexample:
                return ProofResult.unsupported(
                    "SAT array item-values counterexample is missing"
                )
            budget = _array_witness_horizon(problem)
            witness_plan = (
                None
                if proof.certificate is not None
                else model.array_witness_plan_with_override(
                    obligation.index, proof.witness, budget=budget
                )
            )
            skeleton = model.array_witness_skeleton_reaching(
                obligation.index, budget=budget
            )
            if proof.certificate is not None:
                return _certified_false(
                    "array-item-value",
                    (
                        "array item-value subproof has a certified counterexample at "
                        "a reachable index"
                    ),
                    path=(str(obligation.index),),
                    child=proof,
                )
            witness = materialize_array_witness_plan(witness_plan, problem.dialect)
            if witness is None:
                witness = materialize_array_witness_skeleton(
                    skeleton,
                    problem.dialect,
                    override=(obligation.index, proof.witness),
                )
            if witness is None:
                if model.array_witness_skeleton_reaching_budget_exhausted(
                    obligation.index, budget=budget
                ):
                    return _certified_false(
                        "array-item-value",
                        (
                            "array item-value concrete counterexample is reachable "
                            "without materializing the full array"
                        ),
                        path=(str(obligation.index),),
                        child=proof,
                    )
                return ProofResult.unsupported(
                    "SAT array item-values witness could not be constructed"
                )
            return _validated_false(
                problem, witness, "SAT array item-values witness was rejected"
            )

    if (
        plan.post_obligation_witness_plan is not None
        or plan.post_obligation_witness_skeleton is not None
    ):
        witness = (
            materialize_array_witness_plan(
                plan.post_obligation_witness_plan, problem.dialect
            )
            if plan.post_obligation_witness_plan is not None
            else materialize_array_witness_skeleton(
                plan.post_obligation_witness_skeleton, problem.dialect
            )
        )
        if witness is not None:
            return _validated_false(
                problem, witness, plan.post_obligation_rejected_reason
            )

    return ProofResult.true()


def _prove_object_unevaluated_properties_difference(
    problem: DifferenceProblem,
) -> ProofResult:
    if proof := _lhs_static_reference_unsupported(
        problem, "object unevaluatedProperties difference"
    ):
        return proof
    model = problem.object_model
    plan = model.unevaluated_properties_difference_plan()
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        if plan.witness is not None:
            return _validated_false(problem, plan.witness, plan.rejected_reason)
        for skeleton in plan.witness_skeletons:
            witness = materialize_object_key_value_witness_skeleton(
                skeleton, problem.dialect
            )
            if witness is None:
                continue
            proof = _validated_false(problem, witness, plan.rejected_reason)
            if proof.status != "unsupported":
                return proof
        return ProofResult.unsupported(
            plan.reason or "SAT unevaluatedProperties witness could not be constructed"
        )

    for obligation in plan.obligations:
        proof = problem.context.subproof(obligation.lhs_schema, obligation.rhs_schema)
        if proof.status == "resource_exhausted":
            return ProofResult.resource_exhausted(
                proof.reason
                or (
                    "SAT unevaluatedProperties closed-left value proof exhausted "
                    "its budget"
                )
            )
        if proof.status == "unsupported":
            return ProofResult.unsupported(
                proof.reason
                or "SAT unevaluatedProperties closed-left value proof is unsupported"
            )
        if proof.status == "proved_false":
            if proof.witness is None:
                return ProofResult.unsupported(
                    "SAT unevaluatedProperties closed-left value witness could "
                    "not be constructed"
                )
            witness = materialize_object_key_value_witness_skeleton(
                obligation.witness_skeleton,
                problem.dialect,
                override=(obligation.name, proof.witness),
            )
            if witness is None:
                return ProofResult.unsupported(
                    "SAT unevaluatedProperties closed-left value witness could "
                    "not be constructed"
                )
            return _validated_false(
                problem,
                witness,
                "SAT unevaluatedProperties closed-left value witness was rejected",
            )

    return ProofResult.true()


def _prove_object_property_count_difference(problem: DifferenceProblem) -> ProofResult:
    if proof := _object_static_reference_unsupported(
        problem, "object property-count difference"
    ):
        return proof
    if _rhs_requires_nonempty_object(problem.rhs_schema):
        empty_object = _validated_false(
            problem, {}, "SAT object property-count empty-object witness was rejected"
        )
        if empty_object.status != "unsupported":
            return empty_object
    model = problem.object_model
    plan = model.property_count_difference_plan()
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        if _object_property_count_lhs_has_unmodeled_negated_constraints(
            problem.lhs_schema
        ):
            return ProofResult.unsupported(
                "SAT object property-count true proof requires count-complete "
                "left complement semantics"
            )
        if _object_property_count_rhs_has_unmodeled_constraints(problem.rhs_schema):
            return ProofResult.unsupported(
                "SAT object property-count true proof requires count-complete "
                "right object semantics"
            )
        return ProofResult.true()

    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _rhs_requires_nonempty_object(schema: Any) -> bool:
    return (
        isinstance(schema, dict)
        and isinstance(schema.get("minProperties"), int)
        and not isinstance(schema.get("minProperties"), bool)
        and schema["minProperties"] > 0
    )


def _rhs_has_property_count_constraint(schema: Any) -> bool:
    return isinstance(schema, dict) and (
        "minProperties" in schema or "maxProperties" in schema
    )


def _object_property_count_rhs_has_unmodeled_constraints(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 16:
        return True
    if not isinstance(schema, dict):
        return False
    if any(
        keyword in schema
        for keyword in (
            "additionalProperties",
            "dependencies",
            "dependentRequired",
            "dependentSchemas",
            "patternProperties",
            "properties",
            "propertyNames",
            "required",
            "unevaluatedProperties",
        )
    ):
        return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            _object_property_count_rhs_has_unmodeled_constraints(subschema, depth + 1)
            for subschema in value
        ):
            return True
    return "not" in schema and _object_property_count_rhs_has_unmodeled_constraints(
        schema["not"], depth + 1
    )


def _object_property_count_lhs_has_unmodeled_negated_constraints(
    schema: Any,
    depth: int = 0,
    *,
    negated: bool = False,
) -> bool:
    if depth > 16:
        return True
    if not isinstance(schema, dict):
        return False
    if negated and _object_property_count_rhs_has_unmodeled_constraints(schema, depth):
        return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            _object_property_count_lhs_has_unmodeled_negated_constraints(
                subschema,
                depth + 1,
                negated=negated,
            )
            for subschema in value
        ):
            return True
    return (
        "not" in schema
        and _object_property_count_lhs_has_unmodeled_negated_constraints(
            schema["not"],
            depth + 1,
            negated=not negated,
        )
    )


def _rhs_property_count_is_directly_satisfied(lhs_schema: Any, rhs_schema: Any) -> bool:
    if not isinstance(lhs_schema, dict) or not isinstance(rhs_schema, dict):
        return False
    rhs_min = rhs_schema.get("minProperties", 0)
    rhs_max = rhs_schema.get("maxProperties")
    lhs_min = lhs_schema.get("minProperties", 0)
    lhs_max = lhs_schema.get("maxProperties")
    if not isinstance(rhs_min, int) or isinstance(rhs_min, bool):
        return False
    if not isinstance(lhs_min, int) or isinstance(lhs_min, bool):
        return False
    if lhs_min < rhs_min:
        return False
    if rhs_max is None:
        return True
    if not isinstance(rhs_max, int) or isinstance(rhs_max, bool):
        return False
    return (
        isinstance(lhs_max, int)
        and not isinstance(lhs_max, bool)
        and lhs_max <= rhs_max
    )


def _prove_object_presence_product_difference(
    problem: DifferenceProblem,
) -> ProofResult:
    if proof := _object_static_reference_unsupported(
        problem, "object presence-product difference"
    ):
        return proof
    model = problem.object_model
    dependent_value = _rhs_dependent_schema_property_value_witness(problem, model)
    if dependent_value is not None:
        return dependent_value
    dependency_keyspace = _prove_object_presence_witness_plans(
        problem,
        model,
        model.dependency_keyspace_witness_plan().witness_plans,
    )
    if dependency_keyspace is not None:
        return dependency_keyspace
    plan = model.presence_product_plan(problem.context.default_search_horizon)
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)

    witness_proof = _prove_object_presence_witness_plans(
        problem, model, plan.witness_plans
    )
    if witness_proof is not None:
        return witness_proof

    if plan.can_prove_true:
        return ProofResult.true()
    return ProofResult.unsupported(
        "SAT object presence product cannot prove open-world upper-bound completeness"
    )


def _prove_object_presence_witness_plans(
    problem: DifferenceProblem,
    model: ObjectDifferenceModel,
    witness_plans: tuple[Any, ...],
) -> ProofResult | None:
    for witness_plan in witness_plans:
        witness = witness_plan.witness()
        if witness_plan.atom is None and model.lhs_key_values is not None:
            materialized = materialize_object_key_value_witness_skeleton(
                model.lhs_key_values.witness_skeleton_for_names(witness_plan.present),
                problem.dialect,
            )
            if materialized is not None:
                witness = materialized
        proof = _validated_false(
            problem,
            witness,
            f"SAT object presence {witness_plan.source} witness was rejected",
        )
        if proof.status != "unsupported":
            return proof
        return ProofResult.unsupported(
            proof.reason or "SAT object presence witness was rejected"
        )
    return None


def _rhs_dependent_schema_property_value_witness(
    problem: DifferenceProblem,
    model: ObjectDifferenceModel,
) -> ProofResult | None:
    if not isinstance(problem.rhs_schema, dict) or model.lhs_key_values is None:
        return None
    dependent_schemas = problem.rhs_schema.get("dependentSchemas")
    if not isinstance(dependent_schemas, dict):
        return None
    for trigger, dependent_schema in dependent_schemas.items():
        if not isinstance(trigger, str) or not isinstance(dependent_schema, dict):
            continue
        properties = dependent_schema.get("properties")
        if not isinstance(properties, dict):
            continue
        for name, rhs_schema in properties.items():
            if not isinstance(name, str) or rhs_schema is True:
                continue
            if not model.lhs_key_values.allows_key(
                trigger
            ) or not model.lhs_key_values.allows_key(name):
                continue
            proof = problem.context.subproof(
                model.lhs_key_values.value_schema_for(name), rhs_schema
            )
            if proof.status == "resource_exhausted":
                return ProofResult.resource_exhausted(
                    proof.reason
                    or "SAT object dependentSchemas subproof exhausted its budget"
                )
            if proof.status == "unsupported":
                continue
            if proof.status != "proved_false" or proof.witness is None:
                continue
            skeleton = model.lhs_key_values.witness_skeleton_for_names(
                frozenset({trigger, name})
            )
            witness = materialize_object_key_value_witness_skeleton(
                skeleton,
                problem.dialect,
                override=(name, proof.witness),
            )
            if witness is None:
                return _certified_false(
                    "object-dependent-schema",
                    (
                        "object dependentSchemas counterexample could not be "
                        "materialized without expanding child data"
                    ),
                    path=(name,),
                    child=proof,
                )
            validated = _validated_false(
                problem,
                witness,
                "SAT object dependentSchemas witness was rejected",
            )
            if validated.status != "unsupported":
                return validated
    return None


def _prove_object_property_values_difference(problem: DifferenceProblem) -> ProofResult:
    if proof := _object_static_reference_unsupported(
        problem, "object property-values difference"
    ):
        return proof
    model = problem.object_model
    plan = model.property_values_difference_plan()
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        witness = plan.witness
        if plan.witness_skeleton is not None:
            witness = materialize_object_property_value_witness_skeleton(
                plan.witness_skeleton, problem.dialect
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason
                or "SAT object property-values witness could not be constructed"
            )
        return _validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = problem.context.subproof(obligation.lhs_schema, obligation.rhs_schema)
        if proof.status == "resource_exhausted":
            return proof
        if proof.status == "unsupported":
            return ProofResult.unsupported(
                proof.reason or "SAT object property value proof is unsupported"
            )
        if proof.status == "proved_false":
            if not proof.has_counterexample:
                return ProofResult.unsupported(
                    "SAT object property-values counterexample is missing"
                )
            if proof.certificate is not None:
                return _certified_false(
                    "object-property-value",
                    "object property-value subproof has a certified counterexample",
                    path=(obligation.name,),
                    child=proof,
                )
            witness = materialize_object_property_value_witness_skeleton(
                model.property_values_witness_skeleton(obligation.name),
                problem.dialect,
                override=(obligation.name, proof.witness),
            )
            if witness is None:
                return _certified_false(
                    "object-property-value",
                    (
                        "object property-value counterexample could not be "
                        "materialized without expanding child data"
                    ),
                    path=(obligation.name,),
                    child=proof,
                )
            return _validated_false(
                problem,
                witness,
                "SAT object property-values value witness was rejected",
            )

    return ProofResult.true()


def _prove_object_key_value_difference(problem: DifferenceProblem) -> ProofResult:
    if proof := _object_static_reference_unsupported(
        problem, "object key-value difference"
    ):
        return proof
    model = problem.object_model
    budget = problem.context.default_search_horizon
    plan = model.key_value_difference_plan(budget, context=problem.context)
    if plan.status == "unsupported" and plan.reason in {
        (
            "SAT object key-value product defers complex "
            "explicit-property/pattern combinations"
        ),
        "SAT object key-value fragment requires matching pattern/additional classes",
    }:
        gate = problem.context.enter_expensive_proof("object_product")
        if gate is not None:
            return gate
        plan = model.key_value_difference_plan(
            budget, expanded=True, context=problem.context
        )
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        witness = plan.witness
        if plan.witness_skeleton is not None:
            witness = materialize_object_key_value_witness_skeleton(
                plan.witness_skeleton, problem.dialect
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason or "SAT object key-value witness could not be constructed"
            )
        return _validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = problem.context.subproof(obligation.lhs_schema, obligation.rhs_schema)
        if proof.status == "resource_exhausted":
            return ProofResult.resource_exhausted(
                proof.reason or "SAT object key-value subproof exhausted its budget"
            )
        if proof.status == "unsupported":
            return ProofResult.unsupported(
                proof.reason or "SAT object key-value subproof is unsupported"
            )
        if proof.status == "proved_false":
            if not proof.has_counterexample:
                return ProofResult.unsupported(
                    "SAT object key-value counterexample is missing"
                )
            if proof.certificate is not None:
                return _certified_false(
                    "object-key-value",
                    "object key-value subproof has a certified counterexample",
                    path=(obligation.name,),
                    child=proof,
                )
            witness = materialize_object_key_value_witness_skeleton(
                model.key_value_witness_skeleton(obligation.name),
                problem.dialect,
                override=(obligation.name, proof.witness),
            )
            if witness is None:
                return _certified_false(
                    "object-key-value",
                    (
                        "object key-value counterexample could not be materialized "
                        "without expanding child data"
                    ),
                    path=(obligation.name,),
                    child=proof,
                )
            return _validated_false(
                problem, witness, "SAT object key-value witness was rejected"
            )

    if _rhs_has_property_count_constraint(
        problem.rhs_schema
    ) and not _rhs_property_count_is_directly_satisfied(
        problem.lhs_schema,
        problem.rhs_schema,
    ):
        return ProofResult.unsupported(
            "SAT object key-value difference cannot prove property-count constraints"
        )
    return ProofResult.true()


def _prove_object_property_names_difference(problem: DifferenceProblem) -> ProofResult:
    if proof := _object_static_reference_unsupported(
        problem, "object propertyNames difference"
    ):
        return proof
    model = problem.object_model
    plan = model.property_names_difference_plan()
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    proof = _validated_false(
        problem,
        plan.witness,
        "SAT object propertyNames witness was rejected by concrete validation",
    )
    if proof.status != "unsupported":
        return proof

    repaired = materialize_object_property_names_repair_skeleton(
        plan.repair_skeleton, problem.dialect
    )
    if repaired is None:
        return proof
    return _validated_false(
        problem,
        repaired,
        "SAT object propertyNames repaired witness was rejected by concrete validation",
    )


def _prove_closed_object_properties_difference(
    problem: DifferenceProblem,
) -> ProofResult:
    model = problem.object_model
    plan = model.closed_object_difference_plan()
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        witness = plan.witness
        if plan.witness_skeleton is not None:
            witness = materialize_closed_object_witness_skeleton(
                plan.witness_skeleton, problem.dialect
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason or "SAT closed-object witness could not be constructed"
            )
        return _validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = problem.context.subproof(obligation.lhs_schema, obligation.rhs_schema)
        if proof.status == "resource_exhausted":
            return proof
        if proof.status == "unsupported":
            return ProofResult.unsupported(
                proof.reason or "SAT closed-object property value proof is unsupported"
            )
        if proof.status == "proved_false":
            if not proof.has_counterexample:
                return ProofResult.unsupported(
                    "SAT closed-object counterexample is missing"
                )
            if proof.certificate is not None:
                return _certified_false(
                    "closed-object-property",
                    "closed-object property subproof has a certified counterexample",
                    path=(obligation.name,),
                    child=proof,
                )
            witness = materialize_closed_object_witness_skeleton(
                model.closed_object_witness_skeleton(obligation.name),
                problem.dialect,
                override=(obligation.name, proof.witness),
            )
            if witness is None:
                return _certified_false(
                    "closed-object-property",
                    (
                        "closed-object counterexample could not be materialized "
                        "without expanding child data"
                    ),
                    path=(obligation.name,),
                    child=proof,
                )
            validated = _validated_false(
                problem, witness, "SAT closed-object value witness was rejected"
            )
            if validated.status != "unsupported":
                return validated
            return _certified_false(
                "closed-object-property",
                (
                    "closed-object property counterexample could not be "
                    "concretely validated after sibling materialization"
                ),
                path=(obligation.name,),
                child=proof,
            )

    return ProofResult.true()


_OBJECT_ARRAY_ASSERTION_KEYWORDS = frozenset(
    {
        "additionalItems",
        "additionalProperties",
        "contains",
        "dependentRequired",
        "dependentSchemas",
        "dependencies",
        "items",
        "maxContains",
        "maxItems",
        "maxProperties",
        "minContains",
        "minItems",
        "minProperties",
        "patternProperties",
        "prefixItems",
        "properties",
        "propertyNames",
        "required",
        "uniqueItems",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
_NUMERIC_ASSERTION_KEYWORDS = frozenset(
    {"exclusiveMaximum", "exclusiveMinimum", "maximum", "minimum", "multipleOf"}
)
_STRING_ASSERTION_KEYWORDS = frozenset({"maxLength", "minLength", "pattern"})


def _schema_has_object_or_array_assertions(schema: Any) -> bool:
    if isinstance(schema, list):
        return any(_schema_has_object_or_array_assertions(item) for item in schema)
    if not isinstance(schema, dict):
        return False
    if any(key in _OBJECT_ARRAY_ASSERTION_KEYWORDS for key in schema):
        return True
    return any(
        _schema_has_object_or_array_assertions(value)
        for key, value in schema.items()
        if key in {"allOf", "anyOf", "oneOf", "not", "if", "then", "else"}
    )


def _schema_has_non_numeric_assertions(schema: Any) -> bool:
    return _schema_has_object_or_array_assertions(
        schema
    ) or _schema_has_string_assertions(schema)


def _schema_has_string_assertions(schema: Any) -> bool:
    if isinstance(schema, list):
        return any(_schema_has_string_assertions(item) for item in schema)
    if not isinstance(schema, dict):
        return False
    if any(key in _STRING_ASSERTION_KEYWORDS for key in schema):
        return True
    return any(
        _schema_has_string_assertions(value)
        for key, value in schema.items()
        if key in {"allOf", "anyOf", "oneOf", "not", "if", "then", "else"}
    )


def _schema_has_numeric_assertions(schema: Any) -> bool:
    if isinstance(schema, list):
        return any(_schema_has_numeric_assertions(item) for item in schema)
    if not isinstance(schema, dict):
        return False
    if any(key in _NUMERIC_ASSERTION_KEYWORDS for key in schema):
        return True
    return any(
        _schema_has_numeric_assertions(value)
        for key, value in schema.items()
        if key in {"allOf", "anyOf", "oneOf", "not", "if", "then", "else"}
    )


def _numeric_constraint_for_typed_scalar(
    schema: Any,
    type_constraint: TypeConstraint | None,
    numeric_constraint: NumericConstraint | None,
) -> NumericConstraint | None:
    if (
        numeric_constraint is not None
        or type_constraint is None
        or _schema_has_numeric_assertions(schema)
    ):
        return numeric_constraint

    numeric_atoms = type_constraint.atoms & {"integer", "number"}
    accepts_non_numeric = bool(type_constraint.atoms - {"integer", "number"})
    if not numeric_atoms:
        return NumericConstraint(
            NumericShape((), accepts_non_numeric=accepts_non_numeric)
        )
    return NumericConstraint(
        NumericShape(
            (NumericAtom(integer_only="number" not in numeric_atoms),),
            accepts_non_numeric=accepts_non_numeric,
        )
    )


def _finite_complement_excluded_values(
    schema: Any, dialect: Dialect
) -> tuple[Any, ...] | None:
    return finite_complement_excluded_values(schema, dialect)


def _json_value_in(value: Any, values: tuple[Any, ...]) -> bool:
    key = json_semantic_key(value)
    return any(key == json_semantic_key(existing) for existing in values)


def _child_certificate(kind: str, proof: ProofResult) -> CounterexampleCertificate:
    if proof.certificate is not None:
        return proof.certificate
    return CounterexampleCertificate(kind, "validated concrete child witness")


def _certified_false(
    kind: str,
    reason: str,
    *,
    path: tuple[str, ...] = (),
    child: ProofResult | None = None,
) -> ProofResult:
    children = () if child is None else (_child_certificate("concrete-witness", child),)
    return ProofResult.certified_false(
        CounterexampleCertificate(
            kind,
            reason,
            path,
            children,
        )
    )


def _validated_false(
    problem: DifferenceProblem, witness: Any, rejected_reason: str
) -> ProofResult:
    confirmed = confirm_difference(
        _lhs_confirmation_source(problem),
        _rhs_confirmation_source(problem),
        witness,
    )
    if confirmed.status == "unsupported":
        if confirmed.proof is None:
            return ProofResult.unsupported("counterexample confirmation failed")
        return confirmed.proof
    if confirmed.status == "confirmed":
        return ProofResult.false(witness)
    return ProofResult.unsupported(rejected_reason)


def _validated_any_false(
    problem: DifferenceProblem, witnesses: tuple[Any, ...], missing_reason: str
) -> ProofResult:
    unsupported: ProofResult | None = None
    for witness in witnesses:
        confirmed = confirm_difference(
            _lhs_confirmation_source(problem),
            _rhs_confirmation_source(problem),
            witness,
        )
        if confirmed.status == "unsupported":
            unsupported = confirmed.proof or ProofResult.unsupported(
                "counterexample confirmation failed"
            )
            continue
        if confirmed.status == "confirmed":
            return ProofResult.false(witness)
    return unsupported or ProofResult.unsupported(missing_reason)


def _array_witness_horizon(problem: DifferenceProblem) -> int:
    return problem.context.default_search_horizon


def _lhs_confirmation_source(problem: DifferenceProblem) -> Any:
    return problem.formula.lhs.source.to_source()


def _rhs_confirmation_source(problem: DifferenceProblem) -> Any:
    return problem.formula.rhs.source.to_source()


def _all_of_schema(schemas: tuple[Any, ...]) -> Any:
    if not schemas:
        return True
    if len(schemas) == 1:
        return schemas[0]
    return {"allOf": list(schemas)}


def _semantic_unsupported(formula: DifferenceFormula) -> ProofResult | None:
    diagnostics = formula.unsupported_diagnostics
    if not diagnostics:
        return None

    return ProofResult.unsupported(formula.unsupported_reason, diagnostics=diagnostics)


def _contains_static_reference(problem: DifferenceProblem) -> bool:
    return contains_reference_keyword(
        problem.lhs_schema, {"$ref", "$recursiveRef"}
    ) or contains_reference_keyword(
        problem.rhs_schema,
        {"$ref", "$recursiveRef"},
    )
