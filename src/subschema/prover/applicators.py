"""
Applicator proof plans compiled from logical schema IR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from subschema.contracts import ProofStatus
from subschema.ir import (
    ApplicatorKind,
    ApplicatorNode,
    LogicalSchemaIR,
    SchemaNode,
)
from subschema.ir.constraints import StringLanguageConstraint
from subschema.ir.terms import SchemaTerm
from subschema.prover.confirmation import confirm_term_valid
from subschema.prover.formulas import (
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
from subschema.prover.witness_results import WitnessBuildResult
from subschema.prover.witnesses import build_term_witness

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
type ApplicatorDifferencePlan = (
    ApplicatorBranchPlan | ApplicatorConditionalPlan | ApplicatorOneOfCardinalityPlan
)
type ApplicatorFormulaMetadata = tuple[FormulaNode, ApplicatorNode]
type ConditionalFormulaMetadata = tuple[
    FormulaNode, SchemaNode, SchemaNode | None, SchemaNode | None
]

_EVALUATION_SIBLING_KEYWORDS = frozenset(
    {"unevaluatedItems", "unevaluatedProperties"}
)
_DEDICATED_BASE_KEYWORDS = frozenset(
    {"$dynamicRef", "$recursiveRef", "unevaluatedItems", "unevaluatedProperties"}
)

@dataclass(frozen=True)
class ApplicatorFormulaFragment:
    side: ApplicatorPlanSide
    polarity: ApplicatorFormulaPolarity
    kind: ApplicatorKind
    children: tuple[SchemaNode, ...]
    source: ApplicatorNode
    base_term: SchemaTerm = SchemaTerm.true()
    base_semantic_keywords: frozenset[str] = frozenset()
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
    child: ApplicatorNnfChild
    witness_missing_reason: str = (
        "SAT applicator NNF branch witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT applicator NNF branch witness was rejected"
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


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
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


@dataclass(frozen=True)
class ApplicatorBranchPlan:
    formula: ApplicatorFormulaFragment
    proof_class: ApplicatorProofClass
    strategy: ApplicatorProofStrategy
    reason: str
    nnf: ApplicatorNnfFragment
    base_is_standalone: bool = True

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
    child: SchemaNode
    witness_missing_reason: str = (
        "SAT applicator branch witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT applicator branch witness was rejected"
    witness_unsupported_reason: str | None = None
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


@dataclass(frozen=True)
class ApplicatorBaseProduct:
    witness_missing_reason: str
    witness_rejected_reason: str
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


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
    base_term: SchemaTerm = SchemaTerm.true()
    base_semantic_keywords: frozenset[str] = frozenset()
    base_is_standalone: bool = True
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
    branch: ApplicatorConditionalBranch
    witness_missing_reason: str = (
        "SAT conditional branch witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT conditional branch witness was rejected"
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None
    covering_term: SchemaTerm | None = None
    covering_lhs_term: SchemaTerm | None = None

    @property
    def is_trivially_empty_difference(self) -> bool:
        return self.lhs_term == SchemaTerm.false() or self.rhs_term == SchemaTerm.true()


@dataclass(frozen=True)
class ApplicatorOneOfBranchProduct:
    index: int
    child: SchemaNode
    witness_rejected_reason: str = "SAT right-oneOf branch witness was rejected"
    lhs_term: SchemaTerm | None = None
    branch_term: SchemaTerm | None = None


@dataclass(frozen=True)
class ApplicatorOneOfOverlapProduct:
    covering_indexes: tuple[int, ...]
    witness_missing_reason: str = (
        "SAT right-oneOf overlap witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT right-oneOf overlap witness was rejected"
    lhs_term: SchemaTerm | None = None


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
    child: SchemaNode
    witness_missing_reason: str = (
        "SAT right-oneOf disjointness witness could not be constructed"
    )
    witness_rejected_reason: str = "SAT right-oneOf overlap witness was rejected"
    lhs_term: SchemaTerm | None = None
    branch_term: SchemaTerm | None = None


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

    positive_kinds: tuple[ApplicatorKind, ...] = ("anyOf", "oneOf", "allOf")
    for kind in positive_kinds:
        fragment = _pure_applicator_formula(formula.positive_lhs, kind)
        if fragment is not None:
            fragments.append(fragment)

    rhs_not = _pure_applicator_formula(formula.negative_rhs, "not")
    if rhs_not is not None:
        fragments.append(rhs_not)

    for kind in positive_kinds:
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
    lhs_term: SchemaTerm | None = None,
) -> tuple[ApplicatorNnfBranchProduct, ...]:
    if nnf.operator in {"allOf", "anyOf"} and all(
        child.polarity == "negative" for child in nnf.children
    ):
        return tuple(
            ApplicatorNnfBranchProduct(
                index,
                child,
                _nnf_branch_witness_missing_reason_for_fragment(nnf),
                _nnf_branch_witness_rejected_reason_for_fragment(nnf),
                lhs_term,
                _node_term_for_side(child.node, nnf.source.side),
            )
            for index, child in enumerate(nnf.children)
        )

    return ()


def right_negative_any_of_branch_product_plan(
    nnf: ApplicatorNnfFragment,
    *,
    lhs_term: SchemaTerm | None = None,
) -> ApplicatorNnfBranchProductPlan:
    return _right_negative_nnf_branch_product_plan(
        nnf, lhs_term=lhs_term, expected_operator="allOf"
    )


def right_negative_all_of_branch_product_plan(
    nnf: ApplicatorNnfFragment,
    *,
    lhs_term: SchemaTerm | None = None,
) -> ApplicatorNnfBranchProductPlan:
    return _right_negative_nnf_branch_product_plan(
        nnf, lhs_term=lhs_term, expected_operator="anyOf"
    )


def _right_negative_nnf_branch_product_plan(
    nnf: ApplicatorNnfFragment,
    *,
    lhs_term: SchemaTerm | None,
    expected_operator: ApplicatorNnfOperator,
) -> ApplicatorNnfBranchProductPlan:
    products = applicator_nnf_branch_products(nnf, lhs_term=lhs_term)
    if nnf.operator != expected_operator or (not products and nnf.children):
        return ApplicatorNnfBranchProductPlan.unsupported(nnf.reason)
    return ApplicatorNnfBranchProductPlan(products)


def applicator_nnf_schema_product(
    nnf: ApplicatorNnfFragment,
    *,
    lhs_term: SchemaTerm | None = None,
) -> ApplicatorNnfSchemaProduct | None:
    if nnf.operator != "schema" or len(nnf.children) != 1:
        return None

    child = nnf.children[0]
    if child.polarity != "positive":
        return None

    return ApplicatorNnfSchemaProduct(
        child,
        _string_language_constraint_for_node(child.node),
        lhs_term=_all_of_terms(
            (lhs_term, _scoped_term(nnf.source.base_term, nnf.source.side))
        ),
        rhs_term=_node_term_for_side(child.node, nnf.source.side),
    )


def right_not_witness_plan(
    product: ApplicatorNnfSchemaProduct,
    context: Any | None = None,
    lhs_ir: LogicalSchemaIR | None = None,
) -> WitnessBuildResult:
    if context is None:
        return WitnessBuildResult.unsupported(product.witness_missing_reason)
    if product.lhs_term is not None and lhs_ir is not None:
        witness = build_term_witness(product.lhs_term, lhs_ir, context)
        if witness.status == "unsupported" and not witness.reason:
            return WitnessBuildResult.unsupported(product.witness_missing_reason)
        return witness
    return WitnessBuildResult.unsupported(product.witness_missing_reason)


def right_not_intersection_witness_plan(
    product: ApplicatorNnfSchemaProduct,
    context: Any | None = None,
    lhs_ir: LogicalSchemaIR | None = None,
    rhs_term: SchemaTerm | None = None,
    rhs_ir: LogicalSchemaIR | None = None,
) -> WitnessBuildResult:
    if context is None:
        return WitnessBuildResult.unsupported(product.complement_witness_missing_reason)
    if (
        product.lhs_term is not None
        and lhs_ir is not None
        and rhs_term is not None
        and rhs_ir is not None
    ):
        intersection_term = SchemaTerm.all_of((product.lhs_term, rhs_term))
        for witness_term, parent_ir in (
            (intersection_term, lhs_ir),
            (rhs_term, rhs_ir),
            (product.lhs_term, lhs_ir),
        ):
            witness = build_term_witness(
                witness_term,
                parent_ir,
                context,
                lhs_ir=lhs_ir,
                rhs_ir=rhs_ir,
            )
            if witness.status == "witness":
                confirmed = confirm_term_valid(
                    intersection_term,
                    lhs_ir,
                    witness.witness,
                    context,
                    lhs_ir=lhs_ir,
                    rhs_ir=rhs_ir,
                )
                if confirmed.status == "confirmed":
                    return witness
            elif witness.status == "resource_exhausted":
                return witness
    return WitnessBuildResult.unsupported(product.complement_witness_missing_reason)


def applicator_branch_products(
    plan: ApplicatorBranchPlan,
    *,
    lhs_term: SchemaTerm | None = None,
    rhs_term: SchemaTerm | None = None,
) -> tuple[ApplicatorBranchProduct, ...]:
    if plan.side == "lhs" and plan.kind in {"allOf", "anyOf", "oneOf"}:
        return tuple(
            ApplicatorBranchProduct(
                index,
                child,
                _branch_witness_missing_reason_for_plan(plan),
                _branch_witness_rejected_reason_for_plan(plan),
                _branch_witness_unsupported_reason_for_plan(plan),
                _all_of_terms(
                    (
                        _scoped_term(plan.formula.base_term, plan.side),
                        _node_term_for_side(child, plan.side),
                    )
                ),
                rhs_term,
            )
            for index, child in enumerate(plan.children)
        )

    return ()


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
    lhs_term: SchemaTerm | None = None,
) -> ApplicatorBaseProduct | None:
    if not _plan_has_rhs_negative_base(plan):
        return None

    base_term = _base_term_for_plan(plan)
    if base_term.kind == "true":
        return None
    return ApplicatorBaseProduct(
        _base_witness_missing_reason_for_plan(plan),
        _base_witness_rejected_reason_for_plan(plan),
        lhs_term,
        _scoped_term(base_term, plan.side),
    )


def applicator_base_pre_branch_choice(
    base_status: ProofStatus,
) -> ApplicatorProofChoice:
    if base_status == "proved_false":
        return "base_false"
    return "continue"


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
    formula_metadata = _applicator_formula_from_metadata(occurrence, kind)
    if formula_metadata is None:
        return None
    formula_node, applicator = formula_metadata
    if not _supports_sibling_base_applicator(occurrence, kind, applicator):
        return None
    return ApplicatorFormulaFragment(
        side=occurrence.side,
        polarity=occurrence.polarity,
        kind=kind,
        children=applicator.children,
        source=applicator,
        base_term=applicator.base_term,
        base_semantic_keywords=applicator.base_semantic_keywords,
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
    applicator: ApplicatorNode,
) -> bool:
    base_keywords = applicator.base_semantic_keywords
    if (
        occurrence.side == "lhs"
        and occurrence.polarity == "positive"
        and kind in {"allOf", "anyOf", "oneOf"}
    ):
        return not base_keywords & _DEDICATED_BASE_KEYWORDS

    if (
        occurrence.side != "rhs"
        or occurrence.polarity != "negative"
        or kind not in {"allOf", "anyOf", "not", "oneOf"}
    ):
        return False
    if not base_keywords & _DEDICATED_BASE_KEYWORDS:
        return True
    return kind == "allOf" and bool(base_keywords) and (
        base_keywords <= _EVALUATION_SIBLING_KEYWORDS
    )


def _conditional_sibling_base(
    occurrence: FormulaOccurrence,
) -> tuple[SchemaTerm, frozenset[str], bool] | None:
    semantics = occurrence.ir.semantics.applicator
    base_term = semantics.conditional_base_term
    if base_term is None:
        return None
    base_keywords = semantics.conditional_base_semantic_keywords
    return (
        base_term,
        base_keywords,
        not bool(base_keywords & _EVALUATION_SIBLING_KEYWORDS),
    )


def _branch_plan(fragment: ApplicatorFormulaFragment) -> ApplicatorDifferencePlan:
    if fragment.side == "rhs" and fragment.kind == "oneOf":
        return ApplicatorOneOfCardinalityPlan(fragment)

    return ApplicatorBranchPlan(
        formula=fragment,
        proof_class=_proof_class_for_pure_applicator(fragment),
        strategy=_strategy_for_pure_applicator(fragment),
        reason=_reason_for_pure_applicator(fragment),
        nnf=applicator_nnf_fragment(fragment),
        base_is_standalone=_applicator_base_is_standalone(fragment),
    )


def _applicator_base_is_standalone(fragment: ApplicatorFormulaFragment) -> bool:
    if not (
        fragment.side == "rhs"
        and fragment.polarity == "negative"
        and fragment.kind == "allOf"
        and fragment.base_semantic_keywords
    ):
        return True
    return not bool(fragment.base_semantic_keywords & _EVALUATION_SIBLING_KEYWORDS)


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
    lhs_term: SchemaTerm | None = None,
    rhs_term: SchemaTerm | None = None,
) -> tuple[ApplicatorConditionalProduct, ...]:
    if plan.side == "lhs" and plan.polarity == "positive":
        return tuple(
            ApplicatorConditionalProduct(
                branch.kind,
                branch,
                lhs_term=_all_of_terms(
                    (
                        _scoped_term(plan.base_term, plan.side),
                        _term_for_nnf_child(branch.condition, plan.side),
                        _term_for_optional_nnf_child(branch.consequence, plan.side),
                    )
                ),
                rhs_term=rhs_term,
            )
            for branch in plan.branches
        )

    if plan.side == "rhs" and plan.polarity == "negative":
        return tuple(
            ApplicatorConditionalProduct(
                branch.kind,
                branch,
                lhs_term=_all_of_terms(
                    (lhs_term, _term_for_nnf_child(branch.condition, plan.side))
                ),
                rhs_term=_positive_term_for_optional_child(
                    branch.consequence, plan.side
                ),
                covering_term=_inverted_term_for_nnf_child(branch.condition, plan.side),
                covering_lhs_term=lhs_term,
            )
            for branch in plan.branches
        )

    return ()


def one_of_cardinality_products(
    plan: ApplicatorOneOfCardinalityPlan,
    *,
    lhs_term: SchemaTerm | None = None,
) -> tuple[ApplicatorOneOfBranchProduct, ...]:
    product_lhs_term = _all_of_terms(
        (lhs_term, _scoped_term(plan.formula.base_term, plan.side))
    )
    return tuple(
        ApplicatorOneOfBranchProduct(
            index,
            child,
            lhs_term=product_lhs_term,
            branch_term=_node_term_for_side(child, plan.side),
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
    lhs_term: SchemaTerm | None = None,
    covering_indexes: tuple[int, ...],
) -> ApplicatorOneOfOverlapProduct | None:
    if any(index < 0 or index >= len(plan.children) for index in covering_indexes):
        return None
    product_lhs_term = _all_of_terms(
        (lhs_term, _scoped_term(plan.formula.base_term, plan.side))
    )
    return (
        None
        if len(covering_indexes) <= 1
        else ApplicatorOneOfOverlapProduct(
            covering_indexes,
            lhs_term=product_lhs_term,
        )
    )


def one_of_covering_selection(
    plan: ApplicatorOneOfCardinalityPlan,
    *,
    lhs_term: SchemaTerm | None = None,
    covering_indexes: tuple[int, ...],
) -> ApplicatorOneOfCoveringSelection:
    overlap_product = one_of_overlap_product(
        plan,
        lhs_term=lhs_term,
        covering_indexes=covering_indexes,
    )
    if overlap_product is not None:
        return ApplicatorOneOfCoveringSelection(None, overlap_product)
    if len(covering_indexes) == 1:
        return ApplicatorOneOfCoveringSelection(covering_indexes[0])
    return ApplicatorOneOfCoveringSelection(None)


def one_of_overlap_witness_plan(
    product: ApplicatorOneOfOverlapProduct,
    context: Any | None = None,
    lhs_ir: LogicalSchemaIR | None = None,
) -> WitnessBuildResult:
    if context is None:
        return WitnessBuildResult.unsupported(product.witness_missing_reason)
    if product.lhs_term is not None and lhs_ir is not None:
        witness = build_term_witness(product.lhs_term, lhs_ir, context)
        if witness.status == "unsupported" and not witness.reason:
            return WitnessBuildResult.unsupported(product.witness_missing_reason)
        return witness
    return WitnessBuildResult.unsupported(product.witness_missing_reason)


def one_of_disjointness_products(
    plan: ApplicatorOneOfCardinalityPlan,
    *,
    lhs_term: SchemaTerm | None = None,
    covered_index: int,
) -> tuple[ApplicatorOneOfDisjointnessProduct, ...]:
    product_lhs_term = _all_of_terms(
        (lhs_term, _scoped_term(plan.formula.base_term, plan.side))
    )
    return tuple(
        ApplicatorOneOfDisjointnessProduct(
            covered_index,
            index,
            child,
            lhs_term=product_lhs_term,
            branch_term=_node_term_for_side(child, plan.side),
        )
        for index, child in enumerate(plan.children)
        if index != covered_index
    )


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


def _conditional_applicator_plan_for_occurrence(
    occurrence: FormulaOccurrence,
) -> ApplicatorConditionalPlan | None:
    base_term = SchemaTerm.true()
    base_keywords: frozenset[str] = frozenset()
    base_is_standalone = True
    if (sibling_base := _conditional_sibling_base(occurrence)) is not None:
        base_term, base_keywords, base_is_standalone = sibling_base
        if occurrence.side == "lhs" and not base_is_standalone:
            return None
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
        base_term=base_term,
        base_semantic_keywords=base_keywords,
        base_is_standalone=base_is_standalone,
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


def _base_term_for_plan(plan: ApplicatorDifferencePlan) -> SchemaTerm:
    if isinstance(plan, ApplicatorConditionalPlan):
        return plan.base_term
    return plan.formula.base_term


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
    if kind == "allOf":
        return "allOf"
    if kind == "anyOf":
        return "anyOf"
    if kind == "oneOf":
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


def _positive_term_for_optional_child(
    child: ApplicatorNnfChild | None,
    side: ApplicatorPlanSide,
) -> SchemaTerm:
    return SchemaTerm.true() if child is None else _node_term_for_side(child.node, side)


def _term_for_optional_nnf_child(
    child: ApplicatorNnfChild | None,
    side: ApplicatorPlanSide,
) -> SchemaTerm:
    return SchemaTerm.true() if child is None else _term_for_nnf_child(child, side)


def _term_for_nnf_child(
    child: ApplicatorNnfChild,
    side: ApplicatorPlanSide,
) -> SchemaTerm:
    term = _node_term_for_side(child.node, side)
    return term if child.polarity == "positive" else SchemaTerm.not_(term)


def _string_language_constraint_for_node(
    node: SchemaNode,
) -> StringLanguageConstraint | None:
    assertion = node.semantics.assertion("string-language")
    if assertion is None or not isinstance(assertion.value, StringLanguageConstraint):
        return None
    return assertion.value


def _inverted_term_for_nnf_child(
    child: ApplicatorNnfChild,
    side: ApplicatorPlanSide,
) -> SchemaTerm:
    term = _node_term_for_side(child.node, side)
    return SchemaTerm.not_(term) if child.polarity == "positive" else term


def _all_of_terms(parts: tuple[SchemaTerm | None, ...]) -> SchemaTerm | None:
    if any(part is None for part in parts):
        return None
    simplified = []
    for part in parts:
        if part is None:
            return None
        if part.kind == "true":
            continue
        if part.kind == "false":
            return SchemaTerm.false()
        simplified.append(part)
    return SchemaTerm.all_of(tuple(simplified))


def _node_term_for_side(node: SchemaNode, side: ApplicatorPlanSide) -> SchemaTerm:
    return SchemaTerm.node(node.ref, scope=side)


def _scoped_term(term: SchemaTerm, side: ApplicatorPlanSide) -> SchemaTerm:
    return term.with_scope(side)
