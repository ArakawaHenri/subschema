"""
Applicator proof plans compiled from logical schema IR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from subschema.dialects import Dialect
from subschema.kernel.constraints import StringLanguageConstraint
from subschema.kernel.contracts import ProofStatus
from subschema.kernel.formulas import (
    AndFormula,
    DifferenceFormula,
    ExactlyOneFormula,
    FormulaNode,
    FormulaOccurrence,
    FormulaPolarity,
    FormulaSide,
    GuardedFormula,
    NotFormula,
    OrFormula,
)
from subschema.kernel.ir import (
    ApplicatorKind,
    ApplicatorNode,
    LogicalSchemaIR,
    SchemaNode,
)
from subschema.kernel.schemas import (
    HARD_KEYWORDS,
    IGNORED_SCHEMA_METADATA_KEYS,
    schema_is_false,
    schema_is_true,
    schemas_equal,
)
from subschema.kernel.witnesses import WitnessBuildResult, build_schema_witness

ApplicatorPlanSide = FormulaSide
ApplicatorFormulaPolarity = FormulaPolarity
ApplicatorNnfOperator = Literal["allOf", "anyOf", "oneOf", "schema", "unsupported"]
ApplicatorProofClass = Literal["bounded_witness", "exact", "unsupported"]
ApplicatorProofStrategy = Literal[
    "left-allof-exact",
    "left-anyof-exact",
    "left-oneof-exact",
    "right-allof-nnf-exact",
    "right-anyof-nnf-bounded",
    "right-not-nnf",
    "right-oneof-cardinality-exact",
    "conditional-guarded-exact",
    "unsupported-applicator",
]
ApplicatorProofChoice = Literal[
    "base", "base_false", "branch", "continue", "proved_true"
]
ApplicatorBranchProofChoice = Literal[
    "continue",
    "proved_true",
    "record_covering",
    "record_unsupported",
    "return_proof",
    "validate_witness",
]
ConditionalFinalProofChoice = Literal["base", "proved_true", "unsupported"]
ConditionalApplicatorKind = Literal["else", "if", "then"]
ConditionalBranchKind = Literal["if-false", "if-true"]
RightNotProofChoice = Literal[
    "continue",
    "materialize_witness",
    "proved_true",
    "return_resource_exhausted",
    "return_unsupported",
    "validate_witness",
]

type ApplicatorDifferencePlan = (
    ApplicatorBranchPlan | ApplicatorConditionalPlan | ApplicatorOneOfCardinalityPlan
)
type ApplicatorFormulaMetadata = tuple[FormulaNode, ApplicatorNode]
type ConditionalFormulaMetadata = tuple[
    FormulaNode, SchemaNode, SchemaNode | None, SchemaNode | None
]

__all__ = [
    "ApplicatorBranchPlan",
    "ApplicatorBranchProduct",
    "ApplicatorBaseProduct",
    "ApplicatorConditionalBranch",
    "ApplicatorConditionalPlan",
    "ApplicatorDifferencePlan",
    "ApplicatorFormulaFragment",
    "ApplicatorFormulaPolarity",
    "ApplicatorNnfChild",
    "ApplicatorNnfBranchProductPlan",
    "ApplicatorNnfBranchProduct",
    "ApplicatorNnfFragment",
    "ApplicatorNnfOperator",
    "ApplicatorNnfSchemaProduct",
    "ApplicatorOneOfBranchProduct",
    "ApplicatorOneOfCardinalityPlan",
    "ApplicatorOneOfCoveringSelection",
    "ApplicatorOneOfDisjointnessProduct",
    "ApplicatorOneOfOverlapProduct",
    "ApplicatorExpansionBudget",
    "ApplicatorPlanSet",
    "ApplicatorPlanSide",
    "ApplicatorProofChoice",
    "ApplicatorProofClass",
    "ApplicatorProofStrategy",
    "ConditionalBranchKind",
    "ConditionalFinalProofChoice",
    "RightNotProofChoice",
    "ApplicatorConditionalProduct",
    "ApplicatorBranchProofChoice",
    "applicator_difference_plans",
    "applicator_base_product",
    "applicator_base_pre_branch_choice",
    "applicator_branch_products",
    "applicator_branch_expansion_budget",
    "applicator_formula_fragments",
    "applicator_plan_set",
    "applicator_nnf_fragment",
    "applicator_nnf_branch_products",
    "applicator_nnf_fragments",
    "applicator_nnf_schema_product",
    "conditional_branch_proof_choice",
    "conditional_branch_products",
    "conditional_covering_product_proof_choice",
    "conditional_covering_subproof_choice",
    "conditional_final_proof_choice",
    "left_all_of_branch_proof_choice",
    "left_any_of_branch_proof_choice",
    "left_branch_resolved_lhs_schema",
    "left_one_of_branch_proof_choice",
    "one_of_cardinality_products",
    "one_of_coverage_expansion_budget",
    "one_of_coverage_branch_proof_choice",
    "one_of_covering_selection",
    "one_of_disjointness_complement_schema",
    "one_of_disjointness_expansion_budget",
    "one_of_disjointness_direct_proof_choice",
    "one_of_disjointness_proof_choice",
    "one_of_disjointness_products",
    "one_of_disjointness_resolved_branch_schema",
    "one_of_branch_resolved_schema",
    "one_of_overlap_product",
    "one_of_overlap_witness_plan",
    "right_not_complement_needs_subproof",
    "right_not_complement_proof_choice",
    "right_not_complement_schema",
    "right_not_intersection_witness_plan",
    "right_not_resolved_rhs_schema",
    "right_not_subproof_choice",
    "right_applicator_base_first_result_choice",
    "right_applicator_branch_first_pre_base_choice",
    "right_applicator_branch_first_result_choice",
    "right_negative_all_of_branch_product_plan",
    "right_negative_all_of_branch_proof_choice",
    "right_negative_any_of_branch_product_plan",
    "right_negative_any_of_branch_proof_choice",
    "right_nnf_branch_resolved_rhs_schema",
    "right_not_witness_plan",
    "conditional_applicator_plan",
    "pure_applicator_plan",
]


@dataclass(frozen=True)
class ApplicatorFormulaFragment:
    side: ApplicatorPlanSide
    polarity: ApplicatorFormulaPolarity
    kind: ApplicatorKind
    children: tuple[SchemaNode, ...]
    source: ApplicatorNode
    base_schema: Any = True
    formula_node: FormulaNode | None = None


@dataclass(frozen=True)
class ApplicatorNnfChild:
    polarity: ApplicatorFormulaPolarity
    node: SchemaNode


@dataclass(frozen=True)
class ApplicatorNnfFragment:
    source: ApplicatorFormulaFragment
    operator: ApplicatorNnfOperator
    children: tuple[ApplicatorNnfChild, ...]
    proof_class: ApplicatorProofClass
    reason: str

    @property
    def branch_product_count(self) -> int:
        return len(self.children)

    @property
    def branch_budget_exhausted_reason(self) -> str:
        return "branch expansion exceeded proof work budget"


@dataclass(frozen=True)
class ApplicatorNnfBranchProduct:
    index: int
    lhs_schema: Any
    rhs_schema: Any
    child: ApplicatorNnfChild
    witness_missing_reason: str = (
        "SAT applicator NNF branch witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT applicator NNF branch witness was rejected"


@dataclass(frozen=True)
class ApplicatorNnfBranchProductPlan:
    products: tuple[ApplicatorNnfBranchProduct, ...] = ()
    unsupported_reason: str = ""

    @property
    def is_supported(self) -> bool:
        return not self.unsupported_reason

    @classmethod
    def unsupported(cls, reason: str) -> ApplicatorNnfBranchProductPlan:
        return cls(unsupported_reason=reason)


@dataclass(frozen=True)
class ApplicatorNnfSchemaProduct:
    lhs_schema: Any
    rhs_schema: Any
    child: ApplicatorNnfChild
    rhs_string_language_constraint: StringLanguageConstraint | None
    witness_missing_reason: str = "SAT right-not witness could not be constructed"
    witness_rejected_reason: str = "SAT right-not witness was rejected"
    complement_witness_missing_reason: str = (
        "SAT right-not complement witness could not be constructed"
    )
    complement_witness_rejected_reason: str = (
        "SAT right-not complement witness was rejected"
    )


@dataclass(frozen=True)
class ApplicatorBranchPlan:
    formula: ApplicatorFormulaFragment
    proof_class: ApplicatorProofClass
    strategy: ApplicatorProofStrategy
    reason: str
    nnf: ApplicatorNnfFragment

    @property
    def side(self) -> ApplicatorPlanSide:
        return self.formula.side

    @property
    def polarity(self) -> ApplicatorFormulaPolarity:
        return self.formula.polarity

    @property
    def kind(self) -> ApplicatorKind:
        return self.formula.kind

    @property
    def children(self) -> tuple[SchemaNode, ...]:
        return self.formula.children

    @property
    def source(self) -> ApplicatorNode:
        return self.formula.source

    @property
    def branch_product_count(self) -> int:
        return len(self.children)

    @property
    def branch_budget_exhausted_reason(self) -> str:
        return "branch expansion exceeded proof work budget"


@dataclass(frozen=True)
class ApplicatorBranchProduct:
    index: int
    lhs_schema: Any
    rhs_schema: Any
    child: SchemaNode
    base_schema: Any = True
    witness_missing_reason: str = (
        "SAT applicator branch witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT applicator branch witness was rejected"
    witness_unsupported_reason: str | None = None


@dataclass(frozen=True)
class ApplicatorBaseProduct:
    lhs_schema: Any
    rhs_schema: Any
    witness_missing_reason: str
    witness_rejected_reason: str


@dataclass(frozen=True)
class ApplicatorConditionalBranch:
    kind: ConditionalBranchKind
    condition: ApplicatorNnfChild
    consequence: ApplicatorNnfChild | None
    proof_class: ApplicatorProofClass = "exact"
    reason: str = "conditional branch lowers to a guarded branch product"


@dataclass(frozen=True)
class ApplicatorConditionalPlan:
    side: ApplicatorPlanSide
    polarity: ApplicatorFormulaPolarity
    if_child: SchemaNode
    then_child: SchemaNode | None
    else_child: SchemaNode | None
    branches: tuple[ApplicatorConditionalBranch, ...]
    base_schema: Any = True
    formula_node: FormulaNode | None = None
    proof_class: ApplicatorProofClass = "exact"
    strategy: ApplicatorProofStrategy = "conditional-guarded-exact"
    reason: str = "conditional applicator lowers to guarded branch products"

    @property
    def branch_product_count(self) -> int:
        return len(self.branches)

    @property
    def branch_budget_exhausted_reason(self) -> str:
        return "branch expansion exceeded proof work budget"


@dataclass(frozen=True)
class ApplicatorConditionalProduct:
    kind: ConditionalBranchKind
    lhs_schema: Any
    rhs_schema: Any
    branch: ApplicatorConditionalBranch
    covering_schema: Any | None = None
    covering_lhs_schema: Any | None = None
    witness_missing_reason: str = (
        "SAT conditional branch witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT conditional branch witness was rejected"

    @property
    def is_trivially_empty_difference(self) -> bool:
        return schema_is_false(self.lhs_schema) or schema_is_true(self.rhs_schema)


@dataclass(frozen=True)
class ApplicatorOneOfBranchProduct:
    index: int
    lhs_schema: Any
    branch_schema: Any
    child: SchemaNode
    witness_rejected_reason: str = "SAT right-oneOf branch witness was rejected"


@dataclass(frozen=True)
class ApplicatorOneOfOverlapProduct:
    lhs_schema: Any
    covering_indexes: tuple[int, ...]
    witness_missing_reason: str = (
        "SAT right-oneOf overlap witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT right-oneOf overlap witness was rejected"


@dataclass(frozen=True)
class ApplicatorOneOfCoveringSelection:
    covered_index: int | None
    overlap_product: ApplicatorOneOfOverlapProduct | None = None
    unsupported_reason: str = (
        "SAT right-oneOf proof could not establish exactly one covering branch"
    )

    @property
    def is_selected(self) -> bool:
        return self.covered_index is not None


@dataclass(frozen=True)
class ApplicatorOneOfDisjointnessProduct:
    covered_index: int
    index: int
    lhs_schema: Any
    branch_schema: Any
    child: SchemaNode
    witness_missing_reason: str = (
        "SAT right-oneOf disjointness witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT right-oneOf overlap witness was rejected"


@dataclass(frozen=True)
class ApplicatorOneOfCardinalityPlan:
    formula: ApplicatorFormulaFragment
    proof_class: ApplicatorProofClass = "exact"
    strategy: ApplicatorProofStrategy = "right-oneof-cardinality-exact"
    reason: str = (
        "right-side oneOf uses branch coverage and disjointness cardinality products"
    )

    @property
    def side(self) -> ApplicatorPlanSide:
        return self.formula.side

    @property
    def polarity(self) -> ApplicatorFormulaPolarity:
        return self.formula.polarity

    @property
    def kind(self) -> ApplicatorKind:
        return self.formula.kind

    @property
    def children(self) -> tuple[SchemaNode, ...]:
        return self.formula.children

    @property
    def source(self) -> ApplicatorNode:
        return self.formula.source

    @property
    def coverage_product_count(self) -> int:
        return len(self.children)

    @property
    def disjointness_product_count(self) -> int:
        return max(len(self.children) - 1, 0)

    @property
    def coverage_budget_exhausted_reason(self) -> str:
        return "branch expansion exceeded proof work budget"

    @property
    def disjointness_budget_exhausted_reason(self) -> str:
        return "branch expansion exceeded proof work budget"


@dataclass(frozen=True)
class ApplicatorExpansionBudget:
    product_count: int
    exhausted_reason: str

    def exhausted_reason_for(
        self,
        *,
        current_expansions: int,
        max_work: int,
    ) -> str | None:
        if max_work >= 0 and current_expansions + self.product_count > max_work:
            return self.exhausted_reason
        return None


@dataclass(frozen=True)
class ApplicatorPlanSet:
    plans: tuple[ApplicatorDifferencePlan, ...]

    def branch_with_strategy(
        self, strategy: ApplicatorProofStrategy
    ) -> ApplicatorBranchPlan | None:
        for plan in self.plans:
            if isinstance(plan, ApplicatorBranchPlan) and plan.strategy == strategy:
                return plan
        return None

    def one_of_cardinality(self) -> ApplicatorOneOfCardinalityPlan | None:
        for plan in self.plans:
            if isinstance(plan, ApplicatorOneOfCardinalityPlan):
                return plan
        return None

    def conditional(self) -> ApplicatorConditionalPlan | None:
        for plan in self.plans:
            if isinstance(plan, ApplicatorConditionalPlan):
                return plan
        return None


def applicator_difference_plans(
    formula: DifferenceFormula,
) -> tuple[ApplicatorDifferencePlan, ...]:
    return applicator_plan_set(formula).plans


def applicator_plan_set(
    formula: DifferenceFormula,
) -> ApplicatorPlanSet:
    plans: list[ApplicatorDifferencePlan] = []

    plans.extend(
        _branch_plan(fragment) for fragment in applicator_formula_fragments(formula)
    )

    lhs_conditional = _conditional_applicator_plan_for_occurrence(formula.positive_lhs)
    if lhs_conditional is not None:
        plans.append(lhs_conditional)

    rhs_conditional = _conditional_applicator_plan_for_occurrence(formula.negative_rhs)
    if rhs_conditional is not None:
        plans.append(rhs_conditional)

    return ApplicatorPlanSet(tuple(plans))


def applicator_branch_expansion_budget(
    source: ApplicatorBranchPlan | ApplicatorConditionalPlan | ApplicatorNnfFragment,
) -> ApplicatorExpansionBudget:
    return ApplicatorExpansionBudget(
        source.branch_product_count, source.branch_budget_exhausted_reason
    )


def one_of_coverage_expansion_budget(
    plan: ApplicatorOneOfCardinalityPlan,
) -> ApplicatorExpansionBudget:
    return ApplicatorExpansionBudget(
        plan.coverage_product_count, plan.coverage_budget_exhausted_reason
    )


def one_of_disjointness_expansion_budget(
    plan: ApplicatorOneOfCardinalityPlan,
) -> ApplicatorExpansionBudget:
    return ApplicatorExpansionBudget(
        plan.disjointness_product_count, plan.disjointness_budget_exhausted_reason
    )


def applicator_formula_fragments(
    formula: DifferenceFormula,
) -> tuple[ApplicatorFormulaFragment, ...]:
    fragments: list[ApplicatorFormulaFragment] = []

    for kind in ("anyOf", "oneOf", "allOf"):
        fragment = _pure_applicator_formula(formula.positive_lhs, kind)
        if fragment is not None:
            fragments.append(fragment)

    rhs_not = _pure_applicator_formula(formula.negative_rhs, "not")
    if rhs_not is not None:
        fragments.append(rhs_not)

    for kind in ("anyOf", "oneOf", "allOf"):
        fragment = _pure_applicator_formula(formula.negative_rhs, kind)
        if fragment is not None:
            fragments.append(fragment)

    return tuple(fragments)


def applicator_nnf_fragments(
    formula: DifferenceFormula,
) -> tuple[ApplicatorNnfFragment, ...]:
    return tuple(
        applicator_nnf_fragment(fragment)
        for fragment in applicator_formula_fragments(formula)
    )


def applicator_nnf_branch_products(
    nnf: ApplicatorNnfFragment,
    *,
    lhs_schema: Any,
) -> tuple[ApplicatorNnfBranchProduct, ...]:
    if nnf.operator in {"allOf", "anyOf"} and all(
        child.polarity == "negative" for child in nnf.children
    ):
        return tuple(
            ApplicatorNnfBranchProduct(
                index,
                lhs_schema,
                child.node.source.schema,
                child,
                _nnf_branch_witness_missing_reason_for_fragment(nnf),
                _nnf_branch_witness_rejected_reason_for_fragment(nnf),
            )
            for index, child in enumerate(nnf.children)
        )

    return ()


def right_negative_any_of_branch_product_plan(
    nnf: ApplicatorNnfFragment,
    *,
    lhs_schema: Any,
) -> ApplicatorNnfBranchProductPlan:
    return _right_negative_nnf_branch_product_plan(
        nnf, lhs_schema=lhs_schema, expected_operator="allOf"
    )


def right_negative_all_of_branch_product_plan(
    nnf: ApplicatorNnfFragment,
    *,
    lhs_schema: Any,
) -> ApplicatorNnfBranchProductPlan:
    return _right_negative_nnf_branch_product_plan(
        nnf, lhs_schema=lhs_schema, expected_operator="anyOf"
    )


def _right_negative_nnf_branch_product_plan(
    nnf: ApplicatorNnfFragment,
    *,
    lhs_schema: Any,
    expected_operator: ApplicatorNnfOperator,
) -> ApplicatorNnfBranchProductPlan:
    products = applicator_nnf_branch_products(nnf, lhs_schema=lhs_schema)
    if nnf.operator != expected_operator or (not products and nnf.children):
        return ApplicatorNnfBranchProductPlan.unsupported(nnf.reason)
    return ApplicatorNnfBranchProductPlan(products)


def applicator_nnf_schema_product(
    nnf: ApplicatorNnfFragment,
    *,
    lhs_schema: Any,
) -> ApplicatorNnfSchemaProduct | None:
    if nnf.operator != "schema" or len(nnf.children) != 1:
        return None

    child = nnf.children[0]
    if child.polarity != "positive":
        return None

    return ApplicatorNnfSchemaProduct(
        _all_of_schema_parts((lhs_schema, nnf.source.base_schema)),
        child.node.source.schema,
        child,
        _string_language_constraint_for_node(child.node),
    )


def right_not_witness_plan(
    product: ApplicatorNnfSchemaProduct,
    dialect: Dialect,
) -> WitnessBuildResult:
    witness = build_schema_witness(product.lhs_schema, dialect)
    if witness.status == "unsupported" and not witness.reason:
        return WitnessBuildResult.unsupported(product.witness_missing_reason)
    return witness


def right_not_intersection_witness_plan(
    product: ApplicatorNnfSchemaProduct,
    rhs_schema: Any,
    dialect: Dialect,
) -> WitnessBuildResult:
    witness = build_schema_witness(
        _all_of_schema_parts((product.lhs_schema, rhs_schema)), dialect
    )
    if witness.status == "unsupported" and not witness.reason:
        return WitnessBuildResult.unsupported(product.complement_witness_missing_reason)
    return witness


def right_not_complement_schema(
    product: ApplicatorNnfSchemaProduct,
    rhs_schema: Any,
) -> Any:
    return {"not": rhs_schema}


def right_not_complement_needs_subproof(
    product: ApplicatorNnfSchemaProduct,
    complement_schema: Any,
    *,
    original_lhs_schema: Any,
    original_rhs_schema: Any,
) -> bool:
    return not schemas_equal(
        product.lhs_schema, original_lhs_schema
    ) or not schemas_equal(
        complement_schema,
        original_rhs_schema,
    )


def right_not_subproof_choice(status: ProofStatus) -> RightNotProofChoice:
    if status == "proved_true":
        return "materialize_witness"
    if status == "resource_exhausted":
        return "return_resource_exhausted"
    return "continue"


def right_not_complement_proof_choice(status: ProofStatus) -> RightNotProofChoice:
    if status == "proved_true":
        return "proved_true"
    if status == "proved_false":
        return "validate_witness"
    if status == "resource_exhausted":
        return "return_resource_exhausted"
    return "continue"


def right_not_resolved_rhs_schema(
    product: ApplicatorNnfSchemaProduct,
    resolved_schema: Any | None,
) -> Any:
    return product.rhs_schema if resolved_schema is None else resolved_schema


def applicator_branch_products(
    plan: ApplicatorBranchPlan,
    *,
    lhs_schema: Any,
    rhs_schema: Any,
) -> tuple[ApplicatorBranchProduct, ...]:
    if plan.side == "lhs" and plan.kind in {"allOf", "anyOf", "oneOf"}:
        return tuple(
            ApplicatorBranchProduct(
                index,
                _all_of_schema_parts((plan.formula.base_schema, child.source.schema)),
                rhs_schema,
                child,
                plan.formula.base_schema,
                _branch_witness_missing_reason_for_plan(plan),
                _branch_witness_rejected_reason_for_plan(plan),
                _branch_witness_unsupported_reason_for_plan(plan),
            )
            for index, child in enumerate(plan.children)
        )

    return ()


def left_branch_resolved_lhs_schema(
    product: ApplicatorBranchProduct,
    resolved_schema: Any,
) -> Any:
    if schema_is_true(product.base_schema):
        return resolved_schema
    if schema_is_false(product.base_schema) or schema_is_false(resolved_schema):
        return False
    return {"allOf": [product.base_schema, resolved_schema]}


def left_any_of_branch_proof_choice(status: ProofStatus) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "continue"
    if status in {"unsupported", "resource_exhausted"}:
        return "return_proof"
    return "validate_witness"


def left_one_of_branch_proof_choice(status: ProofStatus) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "continue"
    if status == "resource_exhausted":
        return "return_proof"
    if status == "unsupported":
        return "record_unsupported"
    return "validate_witness"


def left_all_of_branch_proof_choice(status: ProofStatus) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "proved_true"
    if status == "resource_exhausted":
        return "return_proof"
    if status == "unsupported":
        return "record_unsupported"
    return "validate_witness"


def applicator_base_product(
    plan: ApplicatorDifferencePlan,
    *,
    lhs_schema: Any,
) -> ApplicatorBaseProduct | None:
    if not _plan_has_rhs_negative_base(plan):
        return None

    base_schema = _base_schema_for_plan(plan)
    if schema_is_true(base_schema):
        return None
    return ApplicatorBaseProduct(
        lhs_schema,
        base_schema,
        _base_witness_missing_reason_for_plan(plan),
        _base_witness_rejected_reason_for_plan(plan),
    )


def applicator_base_pre_branch_choice(
    base_status: ProofStatus,
) -> ApplicatorProofChoice:
    if base_status == "proved_false":
        return "base_false"
    return "continue"


def right_applicator_base_first_result_choice(
    base_status: ProofStatus,
    branch_status: ProofStatus,
) -> ApplicatorProofChoice:
    if base_status == "proved_false":
        return "base_false"
    if branch_status == "proved_false":
        return "branch"
    if base_status == "resource_exhausted":
        return "base"
    if branch_status == "proved_true" and base_status == "proved_true":
        return "proved_true"
    if branch_status == "proved_true":
        return "base"
    return "branch"


def right_applicator_branch_first_pre_base_choice(
    branch_status: ProofStatus,
) -> ApplicatorProofChoice:
    if branch_status in {"proved_false", "resource_exhausted"}:
        return "branch"
    return "continue"


def right_applicator_branch_first_result_choice(
    base_status: ProofStatus,
    branch_status: ProofStatus,
) -> ApplicatorProofChoice:
    if base_status == "proved_false":
        return "base_false"
    if base_status in {"unsupported", "resource_exhausted"}:
        return "base"
    if branch_status == "proved_true":
        return "proved_true"
    return "branch"


def right_negative_any_of_branch_proof_choice(
    status: ProofStatus,
) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "proved_true"
    if status == "resource_exhausted":
        return "return_proof"
    if status == "unsupported":
        return "record_unsupported"
    return "validate_witness"


def right_negative_all_of_branch_proof_choice(
    status: ProofStatus,
) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "continue"
    if status in {"unsupported", "resource_exhausted"}:
        return "return_proof"
    return "validate_witness"


def conditional_covering_subproof_choice(
    status: ProofStatus,
) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "proved_true"
    if status == "resource_exhausted":
        return "return_proof"
    return "continue"


def conditional_covering_product_proof_choice(
    status: ProofStatus,
) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "continue"
    return "return_proof"


def conditional_branch_proof_choice(status: ProofStatus) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "continue"
    if status == "resource_exhausted":
        return "return_proof"
    if status == "unsupported":
        return "record_unsupported"
    return "validate_witness"


def conditional_final_proof_choice(
    base_status: ProofStatus,
    *,
    has_unsupported_branch: bool,
) -> ConditionalFinalProofChoice:
    if has_unsupported_branch:
        return "unsupported"
    if base_status == "proved_true":
        return "proved_true"
    return "base"


def applicator_nnf_fragment(
    fragment: ApplicatorFormulaFragment,
) -> ApplicatorNnfFragment:
    if fragment.polarity == "positive":
        return ApplicatorNnfFragment(
            fragment,
            _positive_nnf_operator(fragment.kind),
            _nnf_children(fragment.children, "positive"),
            _proof_class_for_pure_applicator(fragment),
            _reason_for_pure_applicator(fragment),
        )

    if fragment.kind == "not":
        return ApplicatorNnfFragment(
            fragment,
            "schema",
            _nnf_children(fragment.children, "positive"),
            "exact",
            "negative not normalizes exactly to its positive child schema",
        )

    if fragment.kind == "allOf":
        return ApplicatorNnfFragment(
            fragment,
            "anyOf",
            _nnf_children(fragment.children, "negative"),
            "exact",
            "negative allOf normalizes exactly to disjunctive complement branches",
        )
    if fragment.kind == "anyOf":
        return ApplicatorNnfFragment(
            fragment,
            "allOf",
            _nnf_children(fragment.children, "negative"),
            "bounded_witness",
            (
                "negative anyOf normalizes to conjunctive complement "
                "branches; default proof supports covering branches and "
                "validated witnesses"
            ),
        )
    if fragment.kind == "oneOf":
        return _unsupported_negative_applicator_nnf(
            fragment,
            "unsupported",
            "negative oneOf requires exact branch-cardinality complement planning",
        )

    return _unsupported_negative_applicator_nnf(
        fragment,
        "unsupported",
        "negative applicator requires a dedicated NNF rule",
    )


def pure_applicator_plan(
    ir: LogicalSchemaIR,
    kind: ApplicatorKind,
    *,
    side: ApplicatorPlanSide,
) -> ApplicatorDifferencePlan | None:
    fragment = _pure_applicator_formula(
        FormulaOccurrence(side, _polarity_for_side(side), ir), kind
    )
    return None if fragment is None else _branch_plan(fragment)


def _pure_applicator_formula(
    occurrence: FormulaOccurrence,
    kind: ApplicatorKind,
) -> ApplicatorFormulaFragment | None:
    ir = occurrence.ir
    if not isinstance(ir.schema, dict):
        return None

    if _schema_has_only_keywords(ir.schema, {kind}):
        base_schema = True
    elif _supports_sibling_base_applicator(occurrence, kind):
        base_schema = _schema_without_keyword(ir.schema, kind)
    else:
        return None

    formula_metadata = _applicator_formula_from_metadata(occurrence, kind)
    if formula_metadata is None:
        return None
    formula_node, applicator = formula_metadata
    return ApplicatorFormulaFragment(
        side=occurrence.side,
        polarity=occurrence.polarity,
        kind=kind,
        children=applicator.children,
        source=applicator,
        base_schema=base_schema,
        formula_node=formula_node,
    )


def _applicator_formula_from_metadata(
    occurrence: FormulaOccurrence,
    kind: ApplicatorKind,
) -> ApplicatorFormulaMetadata | None:
    return _find_applicator_formula(
        occurrence.formula,
        root=occurrence.root,
        kind=kind,
        polarity=occurrence.polarity,
    )


def _find_applicator_formula(
    formula: FormulaNode,
    *,
    root: SchemaNode,
    kind: ApplicatorKind,
    polarity: ApplicatorFormulaPolarity,
) -> ApplicatorFormulaMetadata | None:
    if (
        isinstance(
            formula,
            AndFormula | OrFormula | NotFormula | ExactlyOneFormula | GuardedFormula,
        )
        and formula.source is root
        and formula.applicator_kind == kind
        and formula.polarity == polarity
        and formula.applicator is not None
    ):
        return formula, formula.applicator

    for child in _formula_children(formula):
        metadata = _find_applicator_formula(
            child, root=root, kind=kind, polarity=polarity
        )
        if metadata is not None:
            return metadata
    return None


def _formula_children(formula: FormulaNode) -> tuple[FormulaNode, ...]:
    if isinstance(formula, AndFormula | OrFormula | ExactlyOneFormula):
        return formula.children
    if isinstance(formula, NotFormula):
        return (formula.child,)
    if isinstance(formula, GuardedFormula):
        return tuple(
            child
            for child in (formula.condition, formula.then_branch, formula.else_branch)
            if child is not None
        )
    return ()


def _supports_sibling_base_applicator(
    occurrence: FormulaOccurrence,
    kind: ApplicatorKind,
) -> bool:
    if (
        occurrence.side == "lhs"
        and occurrence.polarity == "positive"
        and kind in {"allOf", "anyOf", "oneOf"}
    ):
        base = _schema_without_keyword(occurrence.ir.schema, kind)
        if not isinstance(base, dict):
            return True
        return not (set(base) - IGNORED_SCHEMA_METADATA_KEYS) & HARD_KEYWORDS

    if (
        occurrence.side != "rhs"
        or occurrence.polarity != "negative"
        or kind not in {"allOf", "anyOf", "not", "oneOf"}
    ):
        return False
    base = _schema_without_keyword(occurrence.ir.schema, kind)
    if not isinstance(base, dict):
        return True
    return not (set(base) - IGNORED_SCHEMA_METADATA_KEYS) & HARD_KEYWORDS


def _schema_without_keyword(schema: dict[str, Any], keyword: str) -> Any:
    return _schema_without_keywords(schema, {keyword})


def _schema_without_keywords(schema: dict[str, Any], keywords: set[str]) -> Any:
    base = {key: value for key, value in schema.items() if key not in keywords}
    semantic_keys = set(base) - IGNORED_SCHEMA_METADATA_KEYS
    return base if semantic_keys else True


def _supports_sibling_base_conditional(occurrence: FormulaOccurrence) -> bool:
    base = _schema_without_keywords(occurrence.ir.schema, {"else", "if", "then"})
    if not isinstance(base, dict):
        return True
    return not (set(base) - IGNORED_SCHEMA_METADATA_KEYS) & HARD_KEYWORDS


def _branch_plan(fragment: ApplicatorFormulaFragment) -> ApplicatorDifferencePlan:
    if fragment.side == "rhs" and fragment.kind == "oneOf":
        return ApplicatorOneOfCardinalityPlan(fragment)

    return ApplicatorBranchPlan(
        formula=fragment,
        proof_class=_proof_class_for_pure_applicator(fragment),
        strategy=_strategy_for_pure_applicator(fragment),
        reason=_reason_for_pure_applicator(fragment),
        nnf=applicator_nnf_fragment(fragment),
    )


def conditional_applicator_plan(
    ir: LogicalSchemaIR,
    *,
    side: ApplicatorPlanSide,
) -> ApplicatorConditionalPlan | None:
    return _conditional_applicator_plan_for_occurrence(
        FormulaOccurrence(side, _polarity_for_side(side), ir)
    )


def conditional_branch_products(
    plan: ApplicatorConditionalPlan,
    *,
    lhs_schema: Any,
    rhs_schema: Any,
) -> tuple[ApplicatorConditionalProduct, ...]:
    if plan.side == "lhs" and plan.polarity == "positive":
        return tuple(
            ApplicatorConditionalProduct(
                branch.kind,
                _all_of_schema_parts(
                    (
                        plan.base_schema,
                        _schema_for_nnf_child(branch.condition),
                        _schema_for_optional_nnf_child(branch.consequence),
                    )
                ),
                rhs_schema,
                branch,
            )
            for branch in plan.branches
        )

    if plan.side == "rhs" and plan.polarity == "negative":
        return tuple(
            ApplicatorConditionalProduct(
                branch.kind,
                _all_of_schema_parts(
                    (lhs_schema, _schema_for_nnf_child(branch.condition))
                ),
                _positive_schema_for_optional_child(branch.consequence),
                branch,
                _inverted_schema_for_nnf_child(branch.condition),
                lhs_schema,
            )
            for branch in plan.branches
        )

    return ()


def one_of_cardinality_products(
    plan: ApplicatorOneOfCardinalityPlan,
    *,
    lhs_schema: Any,
) -> tuple[ApplicatorOneOfBranchProduct, ...]:
    product_lhs_schema = _all_of_schema_parts((lhs_schema, plan.formula.base_schema))
    return tuple(
        ApplicatorOneOfBranchProduct(
            index,
            product_lhs_schema,
            child.source.schema,
            child,
        )
        for index, child in enumerate(plan.children)
    )


def one_of_coverage_branch_proof_choice(
    status: ProofStatus,
) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "record_covering"
    if status == "resource_exhausted":
        return "return_proof"
    if status == "unsupported":
        return "record_unsupported"
    return "validate_witness"


def one_of_overlap_product(
    plan: ApplicatorOneOfCardinalityPlan,
    *,
    lhs_schema: Any,
    covering_indexes: tuple[int, ...],
) -> ApplicatorOneOfOverlapProduct | None:
    if any(index < 0 or index >= len(plan.children) for index in covering_indexes):
        return None
    product_lhs_schema = _all_of_schema_parts((lhs_schema, plan.formula.base_schema))
    return (
        None
        if len(covering_indexes) <= 1
        else ApplicatorOneOfOverlapProduct(product_lhs_schema, covering_indexes)
    )


def one_of_covering_selection(
    plan: ApplicatorOneOfCardinalityPlan,
    *,
    lhs_schema: Any,
    covering_indexes: tuple[int, ...],
) -> ApplicatorOneOfCoveringSelection:
    overlap_product = one_of_overlap_product(
        plan, lhs_schema=lhs_schema, covering_indexes=covering_indexes
    )
    if overlap_product is not None:
        return ApplicatorOneOfCoveringSelection(None, overlap_product)
    if len(covering_indexes) == 1:
        return ApplicatorOneOfCoveringSelection(covering_indexes[0])
    return ApplicatorOneOfCoveringSelection(None)


def one_of_overlap_witness_plan(
    product: ApplicatorOneOfOverlapProduct,
    dialect: Dialect,
) -> WitnessBuildResult:
    witness = build_schema_witness(product.lhs_schema, dialect)
    if witness.status == "unsupported" and not witness.reason:
        return WitnessBuildResult.unsupported(product.witness_missing_reason)
    return witness


def one_of_disjointness_products(
    plan: ApplicatorOneOfCardinalityPlan,
    *,
    lhs_schema: Any,
    covered_index: int,
) -> tuple[ApplicatorOneOfDisjointnessProduct, ...]:
    product_lhs_schema = _all_of_schema_parts((lhs_schema, plan.formula.base_schema))
    return tuple(
        ApplicatorOneOfDisjointnessProduct(
            covered_index,
            index,
            product_lhs_schema,
            child.source.schema,
            child,
        )
        for index, child in enumerate(plan.children)
        if index != covered_index
    )


def one_of_disjointness_complement_schema(
    product: ApplicatorOneOfDisjointnessProduct,
    branch_schema: Any,
) -> Any:
    return {"not": branch_schema}


def one_of_disjointness_direct_proof_choice(
    status: ProofStatus,
) -> ApplicatorBranchProofChoice:
    if status == "unsupported":
        return "continue"
    return "return_proof"


def one_of_disjointness_proof_choice(
    status: ProofStatus,
) -> ApplicatorBranchProofChoice:
    if status == "proved_true":
        return "proved_true"
    if status == "proved_false":
        return "validate_witness"
    return "return_proof"


def right_nnf_branch_resolved_rhs_schema(
    product: ApplicatorNnfBranchProduct,
    resolved_schema: Any | None,
) -> Any:
    return product.rhs_schema if resolved_schema is None else resolved_schema


def one_of_branch_resolved_schema(
    product: ApplicatorOneOfBranchProduct,
    resolved_schema: Any | None,
) -> Any:
    return product.branch_schema if resolved_schema is None else resolved_schema


def one_of_disjointness_resolved_branch_schema(
    product: ApplicatorOneOfDisjointnessProduct,
    resolved_schema: Any | None,
) -> Any:
    return product.branch_schema if resolved_schema is None else resolved_schema


def _conditional_applicator_plan_for_occurrence(
    occurrence: FormulaOccurrence,
) -> ApplicatorConditionalPlan | None:
    ir = occurrence.ir
    if not isinstance(ir.schema, dict):
        return None
    if _schema_has_only_keywords(ir.schema, {"if", "then", "else"}):
        base_schema = True
    elif _supports_sibling_base_conditional(occurrence):
        base_schema = _schema_without_keywords(ir.schema, {"else", "if", "then"})
    else:
        return None

    formula_node = None
    conditional_metadata = _conditional_formula_from_metadata(occurrence)
    if conditional_metadata is None:
        return None
    formula_node, if_node, then_node, else_node = conditional_metadata
    return ApplicatorConditionalPlan(
        side=occurrence.side,
        polarity=occurrence.polarity,
        if_child=if_node,
        then_child=then_node,
        else_child=else_node,
        branches=_conditional_branches(
            occurrence.polarity,
            if_node=if_node,
            then_node=then_node,
            else_node=else_node,
        ),
        base_schema=base_schema,
        formula_node=formula_node,
    )


def _conditional_nodes_from_formula_metadata(
    occurrence: FormulaOccurrence,
) -> tuple[SchemaNode, SchemaNode | None, SchemaNode | None] | None:
    metadata = _conditional_formula_from_metadata(occurrence)
    return None if metadata is None else metadata[1:]


def _conditional_formula_from_metadata(
    occurrence: FormulaOccurrence,
) -> ConditionalFormulaMetadata | None:
    formula = _find_conditional_formula(
        occurrence.formula,
        root=occurrence.root,
        polarity=occurrence.polarity,
    )
    if formula is None:
        return None
    if isinstance(formula, GuardedFormula):
        if formula.condition_node is None:
            return None
        return formula, formula.condition_node, formula.then_node, formula.else_node

    conditional_nodes = _conditional_nodes_from_not_formula(formula, occurrence.root)
    if conditional_nodes is None:
        return None
    return formula, *conditional_nodes


def _find_conditional_formula(
    formula: FormulaNode,
    *,
    root: SchemaNode,
    polarity: ApplicatorFormulaPolarity,
) -> FormulaNode | None:
    if (
        isinstance(formula, GuardedFormula | NotFormula)
        and formula.source is root
        and formula.applicator_kind == "if"
        and formula.polarity == polarity
    ):
        return formula

    for child in _formula_children(formula):
        conditional = _find_conditional_formula(child, root=root, polarity=polarity)
        if conditional is not None:
            return conditional
    return None


def _conditional_nodes_from_not_formula(
    formula: FormulaNode,
    root: SchemaNode,
) -> tuple[SchemaNode, SchemaNode | None, SchemaNode | None] | None:
    if not isinstance(formula, NotFormula):
        return None

    guarded = _find_conditional_formula(formula.child, root=root, polarity="positive")
    if not isinstance(guarded, GuardedFormula) or guarded.condition_node is None:
        return None
    return guarded.condition_node, guarded.then_node, guarded.else_node


def _proof_class_for_pure_applicator(
    fragment: ApplicatorFormulaFragment,
) -> ApplicatorProofClass:
    if fragment.polarity == "negative" and fragment.kind == "not":
        return "bounded_witness"
    if fragment.polarity == "negative" and fragment.kind == "anyOf":
        return "bounded_witness"
    return "exact"


def _strategy_for_pure_applicator(
    fragment: ApplicatorFormulaFragment,
) -> ApplicatorProofStrategy:
    match fragment.side, fragment.kind:
        case "lhs", "allOf":
            return "left-allof-exact"
        case "lhs", "anyOf":
            return "left-anyof-exact"
        case "lhs", "oneOf":
            return "left-oneof-exact"
        case "rhs", "allOf":
            return "right-allof-nnf-exact"
        case "rhs", "anyOf":
            return "right-anyof-nnf-bounded"
        case "rhs", "not":
            return "right-not-nnf"
        case "rhs", "oneOf":
            return "right-oneof-cardinality-exact"
    return "unsupported-applicator"


def _plan_has_rhs_negative_base(plan: ApplicatorDifferencePlan) -> bool:
    return plan.side == "rhs" and plan.polarity == "negative"


def _base_schema_for_plan(plan: ApplicatorDifferencePlan) -> Any:
    if isinstance(plan, ApplicatorConditionalPlan):
        return plan.base_schema
    return plan.formula.base_schema


def _base_witness_missing_reason_for_plan(plan: ApplicatorDifferencePlan) -> str:
    return f"SAT {
        _base_witness_label_for_plan(plan)
    } base witness could not be constructed"


def _base_witness_rejected_reason_for_plan(plan: ApplicatorDifferencePlan) -> str:
    return f"SAT {_base_witness_label_for_plan(plan)} base witness was rejected"


def _base_witness_label_for_plan(plan: ApplicatorDifferencePlan) -> str:
    match plan.strategy:
        case "right-not-nnf":
            return "right-not"
        case "right-anyof-nnf-bounded":
            return "right-anyOf"
        case "right-oneof-cardinality-exact":
            return "right-oneOf"
        case "right-allof-nnf-exact":
            return "right-allOf"
        case "conditional-guarded-exact":
            return "conditional"
    return "applicator"


def _branch_witness_missing_reason_for_plan(plan: ApplicatorBranchPlan) -> str:
    return f"SAT {
        _branch_witness_label_for_plan(plan)
    } branch witness could not be constructed"


def _branch_witness_rejected_reason_for_plan(plan: ApplicatorBranchPlan) -> str:
    return f"SAT {_branch_witness_label_for_plan(plan)} branch witness was rejected"


def _branch_witness_unsupported_reason_for_plan(
    plan: ApplicatorBranchPlan,
) -> str | None:
    if plan.strategy == "left-oneof-exact":
        return (
            "SAT left-oneOf branch counterexample is not necessarily in "
            "the oneOf result"
        )
    return None


def _branch_witness_label_for_plan(plan: ApplicatorBranchPlan) -> str:
    match plan.strategy:
        case "left-anyof-exact":
            return "left-anyOf"
        case "left-oneof-exact":
            return "left-oneOf"
        case "left-allof-exact":
            return "left-allOf"
    return "applicator"


def _nnf_branch_witness_missing_reason_for_fragment(nnf: ApplicatorNnfFragment) -> str:
    return f"SAT {
        _nnf_branch_witness_label_for_fragment(nnf)
    } witness could not be constructed"


def _nnf_branch_witness_rejected_reason_for_fragment(nnf: ApplicatorNnfFragment) -> str:
    return f"SAT {_nnf_branch_witness_label_for_fragment(nnf)} witness was rejected"


def _nnf_branch_witness_label_for_fragment(nnf: ApplicatorNnfFragment) -> str:
    match nnf.source.kind:
        case "allOf":
            return "right-allOf conjunct"
        case "anyOf":
            return "right-anyOf branch"
    return "applicator NNF branch"


def _nnf_branch_budget_label_for_fragment(nnf: ApplicatorNnfFragment) -> str:
    match nnf.source.kind:
        case "allOf":
            return "right-allOf branch"
        case "anyOf":
            return "right-anyOf branch"
    return "applicator NNF branch"


def _reason_for_pure_applicator(fragment: ApplicatorFormulaFragment) -> str:
    if fragment.polarity == "negative" and fragment.kind == "not":
        return "right-side not uses specialized overlap and validated witness checks"
    if fragment.polarity == "negative" and fragment.kind == "allOf":
        return "right-side allOf lowers to exact disjunctive complement branches"
    if fragment.polarity == "negative" and fragment.kind == "anyOf":
        return (
            "right-side anyOf lowers to conjunctive complement branches "
            "with bounded validated witnesses"
        )
    if fragment.polarity == "negative" and fragment.kind == "oneOf":
        return (
            "right-side oneOf uses branch coverage and disjointness "
            "cardinality products"
        )
    return "pure applicator wrapper reduces to exact branch subproofs"


def _positive_nnf_operator(kind: ApplicatorKind) -> ApplicatorNnfOperator:
    if kind in {"allOf", "anyOf", "oneOf"}:
        return kind
    return "unsupported"


def _unsupported_negative_applicator_nnf(
    fragment: ApplicatorFormulaFragment,
    operator: ApplicatorNnfOperator,
    reason: str,
) -> ApplicatorNnfFragment:
    return ApplicatorNnfFragment(
        fragment,
        operator,
        _nnf_children(fragment.children, "negative"),
        "unsupported",
        reason,
    )


def _nnf_children(
    children: tuple[SchemaNode, ...],
    polarity: ApplicatorFormulaPolarity,
) -> tuple[ApplicatorNnfChild, ...]:
    return tuple(ApplicatorNnfChild(polarity, child) for child in children)


def _conditional_branches(
    polarity: ApplicatorFormulaPolarity,
    *,
    if_node: SchemaNode,
    then_node: SchemaNode | None,
    else_node: SchemaNode | None,
) -> tuple[ApplicatorConditionalBranch, ...]:
    return (
        ApplicatorConditionalBranch(
            "if-true",
            ApplicatorNnfChild("positive", if_node),
            _conditional_consequence(then_node, polarity),
        ),
        ApplicatorConditionalBranch(
            "if-false",
            ApplicatorNnfChild("negative", if_node),
            _conditional_consequence(else_node, polarity),
        ),
    )


def _conditional_consequence(
    node: SchemaNode | None,
    polarity: ApplicatorFormulaPolarity,
) -> ApplicatorNnfChild | None:
    if node is None:
        return None
    return ApplicatorNnfChild(polarity, node)


def _polarity_for_side(side: ApplicatorPlanSide) -> ApplicatorFormulaPolarity:
    return "positive" if side == "lhs" else "negative"


def _schema_has_only_keywords(schema: dict[str, object], keywords: set[str]) -> bool:
    return all(key in keywords or key in IGNORED_SCHEMA_METADATA_KEYS for key in schema)


def _schema_for_optional_nnf_child(child: ApplicatorNnfChild | None) -> Any:
    return True if child is None else _schema_for_nnf_child(child)


def _positive_schema_for_optional_child(child: ApplicatorNnfChild | None) -> Any:
    return True if child is None else child.node.source.schema


def _schema_for_nnf_child(child: ApplicatorNnfChild) -> Any:
    schema = child.node.source.schema
    return schema if child.polarity == "positive" else {"not": schema}


def _string_language_constraint_for_node(
    node: SchemaNode,
) -> StringLanguageConstraint | None:
    assertion = node.facts.assertion("string-language")
    if assertion is None or not isinstance(assertion.value, StringLanguageConstraint):
        return None
    return assertion.value


def _inverted_schema_for_nnf_child(child: ApplicatorNnfChild) -> Any:
    schema = child.node.source.schema
    return {"not": schema} if child.polarity == "positive" else schema


def _all_of_schema_parts(parts: tuple[Any, ...]) -> Any:
    simplified = []
    for part in parts:
        if schema_is_true(part):
            continue
        if schema_is_false(part):
            return False
        simplified.append(part)

    if not simplified:
        return True
    if len(simplified) == 1:
        return simplified[0]
    return {"allOf": simplified}
