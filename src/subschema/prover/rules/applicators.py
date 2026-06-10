"""
Applicator SAT difference rules.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from subschema.contracts import ProofResult
from subschema.ir import ReferenceUnsupportedFact, SchemaNode, TaggedBranch
from subschema.ir.constraints import StringLanguageConstraint
from subschema.ir.terms import SchemaTerm
from subschema.prover.applicators import (
    ApplicatorBaseProduct,
    ApplicatorBranchPlan,
    ApplicatorBranchProduct,
    ApplicatorConditionalPlan,
    ApplicatorConditionalProduct,
    ApplicatorExpansionBudget,
    ApplicatorNnfBranchProduct,
    ApplicatorNnfFragment,
    ApplicatorNnfSchemaProduct,
    ApplicatorOneOfBranchProduct,
    ApplicatorOneOfCardinalityPlan,
    ApplicatorOneOfDisjointnessProduct,
    applicator_base_pre_branch_choice,
    applicator_base_product,
    applicator_branch_expansion_budget,
    applicator_branch_products,
    applicator_nnf_schema_product,
    conditional_branch_products,
    conditional_branch_proof_choice,
    conditional_covering_product_proof_choice,
    conditional_covering_subproof_choice,
    conditional_final_proof_choice,
    left_all_of_branch_proof_choice,
    left_any_of_branch_proof_choice,
    left_one_of_branch_proof_choice,
    one_of_cardinality_products,
    one_of_coverage_branch_proof_choice,
    one_of_coverage_expansion_budget,
    one_of_covering_selection,
    one_of_disjointness_direct_proof_choice,
    one_of_disjointness_expansion_budget,
    one_of_disjointness_products,
    one_of_disjointness_proof_choice,
    one_of_overlap_witness_plan,
    right_negative_all_of_branch_product_plan,
    right_negative_all_of_branch_proof_choice,
    right_negative_any_of_branch_product_plan,
    right_negative_any_of_branch_proof_choice,
    right_not_intersection_witness_plan,
    right_not_witness_plan,
)
from subschema.prover.disjointness import terms_are_disjoint
from subschema.prover.overlaps import (
    right_not_string_overlap_plan_from_constraints,
    right_not_string_overlap_proof_choice,
)
from subschema.prover.protocols import DifferenceProblemProtocol
from subschema.prover.rules.common import (
    _certified_false,
    _validated_false,
)
from subschema.prover.witness_results import WitnessBuildResult
from subschema.values import json_values_equal


def _string_language_constraint(value: Any) -> StringLanguageConstraint | None:
    return value if isinstance(value, StringLanguageConstraint) else None


type ApplicatorPlanWithBase = (
    ApplicatorBranchPlan | ApplicatorConditionalPlan | ApplicatorOneOfCardinalityPlan
)
RightNotWitnessKind = Literal["concrete", "intersection", "product"]

RIGHT_NOT_DIFFERENCE_UNPROVEN = (
    "SAT right-not difference could not prove left implies negated schema"
)
RIGHT_NOT_REGEX_EXHAUSTED = "regex proof exceeded proof work budget"
RIGHT_NOT_SUBPROOF_EXHAUSTED = "SAT right-not subproof exhausted its budget"


@dataclass(frozen=True)
class RightNotWitnessObligation:
    kind: RightNotWitnessKind
    product: ApplicatorNnfSchemaProduct
    rejected_reason: str
    missing_reason: str
    witness: Any = None


@dataclass(frozen=True)
class RightNotDecision:
    proof: ProofResult | None = None
    witness_obligation: RightNotWitnessObligation | None = None

    @classmethod
    def from_proof(cls, proof: ProofResult) -> RightNotDecision:
        return cls(proof=proof)

    @classmethod
    def from_witness(
        cls,
        obligation: RightNotWitnessObligation,
    ) -> RightNotDecision:
        return cls(witness_obligation=obligation)


@dataclass(frozen=True)
class ApplicatorProofFlow:
    plan: ApplicatorPlanWithBase
    prove_branch: Callable[[], ProofResult]
    branch_first: bool = False


def _prove_left_any_of_applicator_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("left-anyof-exact")
    if plan is None:
        return ProofResult.unsupported(
            "SAT left-anyOf applicator fragment requires a pure left anyOf"
        )
    return _prove_left_any_of_difference(problem, plan)


def _prove_left_one_of_applicator_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("left-oneof-exact")
    if plan is None:
        return ProofResult.unsupported(
            "SAT left-oneOf applicator fragment requires a pure left oneOf"
        )
    return _prove_left_one_of_difference(problem, plan)


def _prove_left_all_of_applicator_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("left-allof-exact")
    if plan is None:
        return ProofResult.unsupported(
            "SAT left-allOf applicator fragment requires a pure left allOf"
        )
    return _prove_left_all_of_difference(problem, plan)


def _prove_right_not_applicator_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
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
    problem: DifferenceProblemProtocol,
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
    problem: DifferenceProblemProtocol,
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
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    matching_branch = _matching_tagged_rhs_one_of_branch(problem)
    if matching_branch is None:
        return ProofResult.unsupported(
            "SAT right-oneOf tagged fragment requires unique required tags"
        )

    proof = _tagged_branch_subproof(problem, matching_branch)
    if proof.status == "proved_true":
        if _rhs_has_evaluation_frontier_constraint(problem):
            return ProofResult.unsupported(
                "SAT tagged right-oneOf evaluation sibling requires "
                "evaluation-aware proof"
            )
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


def _rhs_has_evaluation_frontier_constraint(problem: DifferenceProblemProtocol) -> bool:
    return (
        problem.formula.rhs.evaluation.unevaluated_properties is not None
        or problem.formula.rhs.evaluation.unevaluated_items is not None
    )


def _matching_tagged_rhs_one_of_branch(
    problem: DifferenceProblemProtocol,
) -> TaggedBranch | None:
    tagged = problem.formula.rhs.tagged_one_of
    if tagged is None:
        return None
    lhs_tag = problem.formula.lhs.required_singleton_tag(tagged.tag_name)
    if lhs_tag is None:
        return None
    for branch in tagged.branches:
        if json_values_equal(lhs_tag, branch.tag_value):
            return cast(TaggedBranch, branch)
    return None


def _tagged_branch_subproof(
    problem: DifferenceProblemProtocol,
    branch: TaggedBranch,
) -> ProofResult:
    if branch.term is None:
        return ProofResult.unsupported("SAT tagged branch proof requires schema terms")
    return problem.context.subproof_terms(
        problem.formula.lhs.root_term,
        problem.formula.lhs,
        branch.term,
        problem.formula.rhs,
    )


def _prove_right_all_of_applicator_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    plan = problem.applicator_plan_set.branch_with_strategy("right-allof-nnf-exact")
    if plan is None:
        return ProofResult.unsupported(
            "SAT right-allOf applicator fragment requires a supported right allOf"
        )
    if not _applicator_base_is_standalone(plan):
        return _prove_rhs_all_of_evaluation_sibling_refutation(problem, plan)

    return _run_right_applicator_flow(
        problem,
        ApplicatorProofFlow(
            plan=plan,
            prove_branch=lambda: _prove_rhs_negative_all_of_difference(
                problem, plan.nnf
            ),
        ),
    )


def _prove_rhs_all_of_evaluation_sibling_refutation(
    problem: DifferenceProblemProtocol, plan: ApplicatorBranchPlan
) -> ProofResult:
    unsupported: ProofResult | None = None
    for child in plan.children:
        rhs_reference = _rhs_term_for_node_static_reference(child)
        if isinstance(rhs_reference, ReferenceUnsupportedFact):
            return ProofResult.unsupported(
                rhs_reference.reason, diagnostics=rhs_reference.diagnostic("rhs")
            )
        proof = problem.context.subproof_terms(
            problem.formula.lhs.root_term,
            problem.formula.lhs,
            rhs_reference or SchemaTerm.node(child.ref),
            problem.formula.rhs,
        )
        if proof.status == "resource_exhausted":
            return proof
        if proof.status == "unsupported":
            unsupported = proof
            continue
        if proof.status == "proved_true":
            continue
        if proof.certificate is not None:
            return _certified_false(
                "applicator-right-allof",
                "right allOf child subproof has a certified counterexample",
                child=proof,
            )
        if proof.witness is None:
            unsupported = ProofResult.unsupported(
                "SAT right-allOf branch witness could not be constructed"
            )
            continue
        validated = _validated_false(
            problem, proof.witness, "SAT right-allOf branch witness was rejected"
        )
        if validated.status != "unsupported":
            return validated
        unsupported = ProofResult.unsupported(
            validated.reason or "SAT right-allOf branch witness was rejected"
        )
    return unsupported or ProofResult.unsupported(
        "SAT right-allOf evaluation sibling base requires evaluation-aware proof"
    )


def _run_right_applicator_flow(
    problem: DifferenceProblemProtocol, flow: ApplicatorProofFlow
) -> ProofResult:
    if flow.branch_first:
        return _run_right_applicator_branch_first_flow(problem, flow)
    return _run_right_applicator_base_first_flow(problem, flow)


def _run_right_applicator_base_first_flow(
    problem: DifferenceProblemProtocol, flow: ApplicatorProofFlow
) -> ProofResult:
    base_proof = ProofResult.unsupported(
        "SAT applicator sibling base requires evaluation-aware proof"
    )
    if _applicator_base_is_standalone(flow.plan):
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
    problem: DifferenceProblemProtocol, flow: ApplicatorProofFlow
) -> ProofResult:
    branch_proof = flow.prove_branch()
    if branch_proof.status in {"proved_false", "resource_exhausted"}:
        return branch_proof

    base_proof = ProofResult.unsupported(
        "SAT applicator sibling base requires evaluation-aware proof"
    )
    if _applicator_base_is_standalone(flow.plan):
        base_proof = _prove_applicator_base_difference(problem, flow.plan)
        if applicator_base_pre_branch_choice(base_proof.status) == "base_false":
            return _validated_applicator_base_false(problem, flow.plan, base_proof)
    if base_proof.status in {"unsupported", "resource_exhausted"}:
        return base_proof
    if branch_proof.status == "proved_true":
        return ProofResult.true()
    return branch_proof


def _applicator_base_is_standalone(plan: ApplicatorPlanWithBase) -> bool:
    if isinstance(plan, ApplicatorBranchPlan | ApplicatorConditionalPlan):
        return plan.base_is_standalone
    return True


def _prove_conditional_applicator_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    plan = problem.applicator_plan_set.conditional()
    if plan is None:
        return ProofResult.unsupported(
            "SAT conditional applicator fragment requires supported if/then/else"
        )
    return _prove_conditional_difference(problem, plan)


def _prove_applicator_base_difference(
    problem: DifferenceProblemProtocol,
    plan: ApplicatorPlanWithBase,
) -> ProofResult:
    product = applicator_base_product(
        plan,
        lhs_term=problem.formula.lhs.root_term,
    )
    if product is None:
        return ProofResult.true()
    return _applicator_base_subproof(problem, product)


def _applicator_base_subproof(
    problem: DifferenceProblemProtocol, product: ApplicatorBaseProduct
) -> ProofResult:
    if product.lhs_term is not None and product.rhs_term is not None:
        return problem.context.subproof_terms(
            product.lhs_term,
            problem.formula.lhs,
            product.rhs_term,
            problem.formula.rhs,
        )
    return ProofResult.unsupported("SAT applicator base proof requires schema terms")


def _validated_applicator_base_false(
    problem: DifferenceProblemProtocol,
    plan: ApplicatorPlanWithBase,
    proof: ProofResult,
) -> ProofResult:
    product = applicator_base_product(
        plan,
        lhs_term=problem.formula.lhs.root_term,
    )
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
    problem: DifferenceProblemProtocol, plan: ApplicatorConditionalPlan
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, applicator_branch_expansion_budget(plan)
    ):
        return proof
    base_proof = ProofResult.unsupported(
        "SAT conditional sibling base requires evaluation-aware proof"
    )
    if plan.base_is_standalone:
        base_proof = _prove_applicator_base_difference(problem, plan)
        if applicator_base_pre_branch_choice(base_proof.status) == "base_false":
            return _validated_applicator_base_false(problem, plan, base_proof)

    products = conditional_branch_products(
        plan,
        lhs_term=problem.formula.lhs.root_term,
        rhs_term=problem.formula.rhs.root_term,
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

        proof = _conditional_branch_subproof(problem, product)
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


def _conditional_branch_subproof(
    problem: DifferenceProblemProtocol,
    product: ApplicatorConditionalProduct,
) -> ProofResult:
    if product.lhs_term is None or product.rhs_term is None:
        return ProofResult.unsupported(
            "conditional branch proof requires schema terms"
        )
    return problem.context.subproof_terms(
        product.lhs_term,
        problem.formula.lhs,
        product.rhs_term,
        problem.formula.rhs,
    )


def _prove_rhs_conditional_product_empty(
    problem: DifferenceProblemProtocol,
    product: ApplicatorConditionalProduct,
) -> ProofResult | None:
    if product.covering_lhs_term is None or product.covering_term is None:
        return None

    proof = problem.context.subproof_terms(
        product.covering_lhs_term,
        problem.formula.lhs,
        product.covering_term,
        problem.formula.rhs,
    )
    choice = conditional_covering_subproof_choice(proof.status)
    if choice == "proved_true":
        return ProofResult.true()
    if choice == "return_proof":
        return proof
    return None


def _applicator_expansion_budget_exhausted(
    problem: DifferenceProblemProtocol,
    expansion_budget: ApplicatorExpansionBudget,
) -> ProofResult | None:
    return problem.context.spend_work(
        expansion_budget.product_count,
        "branch expansion",
        "branch expansion exceeded proof work budget",
    )


def _prove_left_any_of_difference(
    problem: DifferenceProblemProtocol, plan: ApplicatorBranchPlan
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
    problem: DifferenceProblemProtocol, plan: ApplicatorBranchPlan
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
    problem: DifferenceProblemProtocol, plan: ApplicatorBranchPlan
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
    problem: DifferenceProblemProtocol,
    plan: ApplicatorBranchPlan,
) -> tuple[ApplicatorBranchProduct, ...]:
    return applicator_branch_products(
        plan,
        lhs_term=problem.formula.lhs.root_term,
        rhs_term=problem.formula.rhs.root_term,
    )


def _left_branch_subproof(
    problem: DifferenceProblemProtocol, product: ApplicatorBranchProduct
) -> ProofResult:
    lhs_reference = _static_reference_term_for_node(product.child, "lhs")
    if isinstance(lhs_reference, ReferenceUnsupportedFact):
        return ProofResult.unsupported(
            lhs_reference.reason, diagnostics=lhs_reference.diagnostic("lhs")
        )
    if (
        isinstance(lhs_reference, SchemaTerm)
        and product.rhs_term is not None
        and product.lhs_term is not None
    ):
        proof = problem.context.subproof_terms(
            lhs_reference,
            problem.formula.lhs,
            product.rhs_term,
            problem.formula.rhs,
        )
        if proof.status != "unsupported":
            return proof
    if product.lhs_term is None or product.rhs_term is None:
        return ProofResult.unsupported("SAT left branch proof requires schema terms")
    proof = problem.context.subproof_terms(
        product.lhs_term,
        problem.formula.lhs,
        product.rhs_term,
        problem.formula.rhs,
    )
    if proof.status != "unsupported":
        return proof
    return ProofResult.unsupported(
        proof.reason or "SAT left branch proof requires term-supported schemas"
    )


def _static_reference_term_for_node(
    node: SchemaNode,
    side: Literal["lhs", "rhs"],
) -> SchemaTerm | ReferenceUnsupportedFact | None:
    reference = node.semantics.reference.static_reference
    unsupported = reference.unsupported(side)
    if unsupported is not None:
        return unsupported
    return reference.target


def _prove_rhs_negative_any_of_difference(
    problem: DifferenceProblemProtocol, nnf: ApplicatorNnfFragment
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, applicator_branch_expansion_budget(nnf)
    ):
        return proof
    product_plan = right_negative_any_of_branch_product_plan(
        nnf, lhs_term=problem.formula.lhs.root_term
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
    problem: DifferenceProblemProtocol,
) -> ProofResult | None:
    constraint = (
        problem.formula.lhs.semantics.array_tuple_anyof_distribution_constraint
    )
    if constraint is None:
        return None
    if proof := problem.context.spend_work(
        len(constraint.branch_terms),
        "array product",
        "array tuple anyOf distribution exceeded proof work budget",
    ):
        return proof

    unsupported: ProofResult | None = None
    branch_terms = constraint.branch_terms
    if not branch_terms:
        return ProofResult.unsupported(
            "tuple anyOf distribution proof requires branch terms"
        )
    for branch_term in branch_terms:
        branch_proof = problem.context.subproof_terms(
            branch_term,
            problem.formula.lhs,
            problem.formula.rhs.root_term,
            problem.formula.rhs,
        )
        if branch_proof.status == "proved_true":
            continue
        if branch_proof.status == "proved_false":
            if branch_proof.certificate is not None:
                return _certified_false(
                    "array-item-anyof",
                    "tuple anyOf distribution branch has a certified counterexample",
                    child=branch_proof,
                )
            if branch_proof.witness is None:
                return ProofResult.unsupported(
                    "tuple anyOf distribution counterexample is missing"
                )
            return _validated_false(
                problem,
                branch_proof.witness,
                "tuple anyOf distribution witness was rejected",
            )
        if branch_proof.status == "resource_exhausted":
            return branch_proof
        unsupported = branch_proof
    return ProofResult.true() if unsupported is None else unsupported


def _prove_rhs_one_of_cardinality_difference(
    problem: DifferenceProblemProtocol,
    plan: ApplicatorOneOfCardinalityPlan,
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, one_of_coverage_expansion_budget(plan)
    ):
        return proof
    products = one_of_cardinality_products(
        plan,
        lhs_term=problem.formula.lhs.root_term,
    )
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
        lhs_term=problem.formula.lhs.root_term,
        covering_indexes=tuple(covering_indexes),
    )
    if covering.overlap_product is not None:
        witness_plan = one_of_overlap_witness_plan(
            covering.overlap_product,
            problem.context,
            problem.formula.lhs,
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
    problem: DifferenceProblemProtocol,
    product: ApplicatorOneOfDisjointnessProduct,
) -> ProofResult:
    branch_reference = _rhs_term_for_node_static_reference(product.child)
    if isinstance(branch_reference, ReferenceUnsupportedFact):
        return ProofResult.unsupported(
            branch_reference.reason, diagnostics=branch_reference.diagnostic("rhs")
        )
    if product.lhs_term is not None and product.branch_term is not None:
        term_disjoint = terms_are_disjoint(
            product.lhs_term,
            problem.formula.lhs,
            product.branch_term,
            problem.formula.rhs,
            problem.context,
        )
        if (
            one_of_disjointness_direct_proof_choice(term_disjoint.status)
            == "return_proof"
        ):
            return term_disjoint
        return ProofResult.unsupported(
            term_disjoint.reason
            or "SAT right-oneOf disjointness proof requires term-supported schemas"
        )
    return ProofResult.unsupported(
        "SAT right-oneOf disjointness proof requires schema terms"
    )


def _one_of_disjointness_products(
    problem: DifferenceProblemProtocol,
    plan: ApplicatorOneOfCardinalityPlan,
    covered_index: int,
) -> tuple[ApplicatorOneOfDisjointnessProduct, ...]:
    return one_of_disjointness_products(
        plan,
        lhs_term=problem.formula.lhs.root_term,
        covered_index=covered_index,
    )


def _prove_rhs_negative_all_of_difference(
    problem: DifferenceProblemProtocol, nnf: ApplicatorNnfFragment
) -> ProofResult:
    if proof := _applicator_expansion_budget_exhausted(
        problem, applicator_branch_expansion_budget(nnf)
    ):
        return proof
    product_plan = right_negative_all_of_branch_product_plan(
        nnf, lhs_term=problem.formula.lhs.root_term
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
    problem: DifferenceProblemProtocol, product: ApplicatorNnfBranchProduct
) -> ProofResult:
    rhs_reference = _rhs_term_for_node_static_reference(product.child.node)
    if isinstance(rhs_reference, ReferenceUnsupportedFact):
        return ProofResult.unsupported(
            rhs_reference.reason, diagnostics=rhs_reference.diagnostic("rhs")
        )
    if (
        isinstance(rhs_reference, SchemaTerm)
        and product.lhs_term is not None
        and product.rhs_term is not None
    ):
        proof = problem.context.subproof_terms(
            product.lhs_term,
            problem.formula.lhs,
            rhs_reference,
            problem.formula.rhs,
        )
        if proof.status != "unsupported":
            return proof
    if product.lhs_term is not None and product.rhs_term is not None:
        proof = problem.context.subproof_terms(
            product.lhs_term,
            problem.formula.lhs,
            product.rhs_term,
            problem.formula.rhs,
        )
        if proof.status != "unsupported":
            return proof
        return ProofResult.unsupported(
            proof.reason or "SAT right NNF branch proof requires term-supported schemas"
        )
    return ProofResult.unsupported("SAT right NNF branch proof requires schema terms")


def _certified_array_item_against_rhs_anyof(
    problem: DifferenceProblemProtocol,
) -> ProofResult | None:
    if not problem.formula.lhs.array_item_values_fragment_constraint.lhs_supported:
        return None
    rhs_item_constraint = (
        problem.formula.rhs.semantics.array_any_of_item_schemas_constraint
    )
    if rhs_item_constraint is None:
        return None

    model = problem.array_model
    if model.first_lhs_length_reaching(0) is None:
        return None

    lhs_item_term = model.lhs_item_term_at(0)
    rhs_item_term = SchemaTerm.any_of(rhs_item_constraint.item_terms)
    if lhs_item_term is not None and rhs_item_term.kind != "false":
        proof = problem.context.subproof_terms(
            lhs_item_term,
            problem.formula.lhs,
            rhs_item_term,
            problem.formula.rhs,
        )
        if proof.status == "unsupported":
            return None
    else:
        return None
    if not proof.has_counterexample:
        return None
    return _certified_false(
        "array-item-anyof",
        "a reachable array item violates every RHS anyOf array item schema",
        path=("0",),
        child=proof,
    )


def _rhs_one_of_branch_subproof(
    problem: DifferenceProblemProtocol, product: ApplicatorOneOfBranchProduct
) -> ProofResult:
    branch_reference = _rhs_term_for_node_static_reference(product.child)
    if isinstance(branch_reference, ReferenceUnsupportedFact):
        return ProofResult.unsupported(
            branch_reference.reason, diagnostics=branch_reference.diagnostic("rhs")
        )
    if product.lhs_term is not None and product.branch_term is not None:
        proof = problem.context.subproof_terms(
            product.lhs_term,
            problem.formula.lhs,
            product.branch_term,
            problem.formula.rhs,
        )
        if proof.status != "unsupported":
            return proof
        return ProofResult.unsupported(
            proof.reason
            or "SAT right oneOf branch proof requires term-supported schemas"
        )
    return ProofResult.unsupported("SAT right oneOf branch proof requires schema terms")


def _rhs_term_for_node_static_reference(
    node: SchemaNode,
) -> SchemaTerm | ReferenceUnsupportedFact | None:
    return _static_reference_term_for_node(node, "rhs")


def _prove_rhs_not_difference(
    problem: DifferenceProblemProtocol, nnf: ApplicatorNnfFragment
) -> ProofResult:
    return _realize_right_not_decision(problem, _plan_rhs_not_difference(problem, nnf))


def _plan_rhs_not_difference(
    problem: DifferenceProblemProtocol, nnf: ApplicatorNnfFragment
) -> RightNotDecision:
    product = _rhs_nnf_schema_product(problem, nnf)
    if product is None:
        return RightNotDecision.from_proof(ProofResult.unsupported(nnf.reason))

    rhs_term = _rhs_not_product_term(product)
    if isinstance(rhs_term, ReferenceUnsupportedFact):
        return RightNotDecision.from_proof(
            ProofResult.unsupported(
                rhs_term.reason, diagnostics=rhs_term.diagnostic("rhs")
            )
        )

    if product.lhs_term is not None and rhs_term is not None:
        lhs_negated = _pure_not_child_term(product.lhs_term, problem.formula.lhs)
        if lhs_negated is not None:
            proof = problem.context.subproof_terms(
                rhs_term.with_scope("lhs"),
                problem.formula.rhs,
                lhs_negated.with_scope("rhs"),
                problem.formula.lhs,
            )
            if proof.status == "proved_true":
                return RightNotDecision.from_proof(ProofResult.true())
            if proof.status == "resource_exhausted":
                return RightNotDecision.from_proof(
                    ProofResult.resource_exhausted(
                        proof.reason or RIGHT_NOT_SUBPROOF_EXHAUSTED
                    )
                )
            if proof.status == "proved_false" and proof.witness is not None:
                return RightNotDecision.from_witness(
                    RightNotWitnessObligation(
                        "concrete",
                        product,
                        product.complement_witness_rejected_reason,
                        product.complement_witness_missing_reason,
                        witness=proof.witness,
                    )
                )

        double_negated_rhs = _pure_not_child_term(rhs_term, problem.formula.rhs)
        if double_negated_rhs is not None:
            proof = problem.context.subproof_terms(
                product.lhs_term,
                problem.formula.lhs,
                double_negated_rhs,
                problem.formula.rhs,
            )
            if proof.status in {"proved_true", "resource_exhausted", "unsupported"}:
                return RightNotDecision.from_proof(proof)
            if proof.witness is None:
                return RightNotDecision.from_proof(
                    ProofResult.unsupported(product.complement_witness_missing_reason)
                )
            return RightNotDecision.from_witness(
                RightNotWitnessObligation(
                    "concrete",
                    product,
                    product.complement_witness_rejected_reason,
                    product.complement_witness_missing_reason,
                    witness=proof.witness,
                )
            )

    if product.lhs_term is not None and rhs_term is not None:
        disjoint = terms_are_disjoint(
            product.lhs_term,
            problem.formula.lhs,
            rhs_term,
            problem.formula.rhs,
            problem.context,
        )
        if disjoint.status == "proved_true":
            return RightNotDecision.from_proof(ProofResult.true())
        if disjoint.status == "proved_false" and disjoint.witness is not None:
            return RightNotDecision.from_witness(
                RightNotWitnessObligation(
                    "concrete",
                    product,
                    product.witness_rejected_reason,
                    product.witness_missing_reason,
                    witness=disjoint.witness,
                )
            )
        if disjoint.status == "resource_exhausted":
            return RightNotDecision.from_proof(disjoint)

    string_overlap = right_not_string_overlap_plan_from_constraints(
        _string_language_constraint(problem.lhs_constraint("string-language")),
        product.rhs_string_language_constraint,
        problem.context,
    )
    choice = right_not_string_overlap_proof_choice(string_overlap.status)
    if choice == "proved_true":
        return RightNotDecision.from_proof(ProofResult.true())
    if choice == "validate_witness":
        return RightNotDecision.from_witness(
            RightNotWitnessObligation(
                "concrete",
                product,
                string_overlap.rejected_reason,
                product.witness_missing_reason,
                witness=string_overlap.witness,
            )
        )
    if choice == "return_resource_exhausted":
        return RightNotDecision.from_proof(
            ProofResult.resource_exhausted(
                string_overlap.reason or RIGHT_NOT_REGEX_EXHAUSTED
            )
        )

    if product.lhs_term is not None and rhs_term is not None:
        proof = problem.context.subproof_terms(
            product.lhs_term,
            problem.formula.lhs,
            rhs_term,
            problem.formula.rhs,
        )
        if proof.status == "proved_true":
            return RightNotDecision.from_witness(
                RightNotWitnessObligation(
                    "product",
                    product,
                    product.witness_rejected_reason,
                    product.witness_missing_reason,
                )
            )
        if proof.status == "resource_exhausted":
            return RightNotDecision.from_proof(
                ProofResult.resource_exhausted(
                    proof.reason or RIGHT_NOT_SUBPROOF_EXHAUSTED
                )
            )
    return RightNotDecision.from_witness(
        RightNotWitnessObligation(
            "intersection",
            product,
            product.complement_witness_rejected_reason,
            product.complement_witness_missing_reason,
        )
    )


def _realize_right_not_decision(
    problem: DifferenceProblemProtocol,
    decision: RightNotDecision,
) -> ProofResult:
    if decision.proof is not None:
        return decision.proof
    if decision.witness_obligation is None:
        return ProofResult.unsupported(RIGHT_NOT_DIFFERENCE_UNPROVEN)
    return _realize_right_not_witness_obligation(
        problem,
        decision.witness_obligation,
    )


def _realize_right_not_witness_obligation(
    problem: DifferenceProblemProtocol,
    obligation: RightNotWitnessObligation,
) -> ProofResult:
    if obligation.kind == "concrete":
        if obligation.witness is None:
            return ProofResult.unsupported(obligation.missing_reason)
        return _validated_false(problem, obligation.witness, obligation.rejected_reason)
    if obligation.kind == "product":
        return _realize_right_not_witness_plan(
            problem,
            right_not_witness_plan(
                obligation.product,
                problem.context,
                problem.formula.lhs,
            ),
            obligation.rejected_reason,
        )
    rhs_term = _rhs_not_product_term(obligation.product)
    rhs_term_arg = None if isinstance(rhs_term, ReferenceUnsupportedFact) else rhs_term
    return _realize_right_not_witness_plan(
        problem,
        right_not_intersection_witness_plan(
            obligation.product,
            problem.context,
            problem.formula.lhs,
            rhs_term_arg,
            problem.formula.rhs,
        ),
        obligation.rejected_reason,
    )


def _realize_right_not_witness_plan(
    problem: DifferenceProblemProtocol,
    witness_plan: WitnessBuildResult,
    rejected_reason: str,
) -> ProofResult:
    if witness_plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(witness_plan.reason)
    if witness_plan.status == "certificate" and witness_plan.certificate is not None:
        return ProofResult.certified_false(witness_plan.certificate)
    if witness_plan.has_witness:
        return _validated_false(problem, witness_plan.witness, rejected_reason)
    return ProofResult.unsupported(witness_plan.reason or RIGHT_NOT_DIFFERENCE_UNPROVEN)


def _rhs_not_product_term(
    product: ApplicatorNnfSchemaProduct,
) -> SchemaTerm | ReferenceUnsupportedFact | None:
    rhs_reference = _rhs_term_for_node_static_reference(product.child.node)
    if isinstance(rhs_reference, ReferenceUnsupportedFact):
        return rhs_reference
    return rhs_reference or product.rhs_term


def _pure_not_child_term(
    term: SchemaTerm,
    ir: Any,
) -> SchemaTerm | None:
    if term.kind != "node" or term.ref is None:
        return None
    node = ir.node_for_ref(term.ref)
    if node is None:
        return None
    not_applicators = tuple(
        applicator
        for applicator in node.applicators
        if applicator.kind == "not"
        and len(applicator.children) == 1
        and not applicator.base_semantic_keywords
    )
    if len(not_applicators) != 1:
        return None
    return SchemaTerm.node(not_applicators[0].children[0].ref, scope=term.scope)


def _rhs_nnf_schema_product(
    problem: DifferenceProblemProtocol,
    nnf: ApplicatorNnfFragment,
) -> ApplicatorNnfSchemaProduct | None:
    return applicator_nnf_schema_product(
        nnf,
        lhs_term=problem.formula.lhs.root_term,
    )
