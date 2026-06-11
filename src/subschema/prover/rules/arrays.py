"""
Array SAT difference rules.
"""

from __future__ import annotations

from subschema.contracts import ProofResult
from subschema.ir import LogicalSchemaIR
from subschema.ir.terms import SchemaTerm
from subschema.prover.confirmation import confirm_term_valid
from subschema.prover.difference import (
    ArrayDifferenceModel,
    materialize_array_duplicate_witness_plan,
    materialize_array_witness_plan,
    materialize_array_witness_skeleton,
)
from subschema.prover.protocols import DifferenceProblemProtocol
from subschema.prover.rules.common import (
    array_static_reference_unsupported,
    array_witness_horizon,
    certified_false,
    lhs_static_reference_unsupported,
    validated_false,
)
from subschema.prover.witness_results import WitnessBuildResult
from subschema.prover.witnesses import build_term_witness


def prove_array_unevaluated_items_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    if proof := lhs_static_reference_unsupported(
        problem, "array unevaluatedItems difference"
    ):
        return proof
    model = problem.array_model
    plan = model.unevaluated_items_difference_plan(
        budget=array_witness_horizon(problem),
        expanded=problem.context.allows_expensive_proof("evaluation_trace"),
    )
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(
            plan.reason,
            unsupported_priority=plan.unsupported_priority,
        )
    if plan.status == "conditioned_obligations":
        return ProofResult.unsupported(
            plan.reason,
            unsupported_priority=plan.unsupported_priority,
        )
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        witness = materialize_array_witness_skeleton(
            plan.witness_skeleton, problem.dialect, context=problem.context
        )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason or "SAT unevaluatedItems witness could not be constructed"
            )
        return validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = _array_child_subproof(
            problem,
            obligation.lhs_term,
            obligation.rhs_term,
        )
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
            budget = array_witness_horizon(problem)
            skeleton = model.array_witness_skeleton_reaching(
                obligation.index, budget=budget
            )
            witness = materialize_array_witness_skeleton(
                skeleton,
                problem.dialect,
                override=(obligation.index, proof.witness),
                context=problem.context,
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
            return validated_false(
                problem,
                witness,
                "SAT unevaluatedItems finite-left item witness was rejected",
            )

    return ProofResult.true()


def prove_array_length_difference(problem: DifferenceProblemProtocol) -> ProofResult:
    if proof := array_static_reference_unsupported(problem, "array length difference"):
        return proof
    model = problem.array_model
    plan = model.length_difference_plan(budget=array_witness_horizon(problem))
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    witness = plan.witness
    if plan.witness_plan is not None:
        witness = materialize_array_witness_plan(
            plan.witness_plan, problem.dialect, context=problem.context
        )
    if plan.witness_skeleton is not None:
        witness = materialize_array_witness_skeleton(
            plan.witness_skeleton, problem.dialect, context=problem.context
        )
    if witness is None:
        return ProofResult.unsupported(
            plan.reason or "SAT array length witness could not be constructed"
        )
    return validated_false(problem, witness, plan.rejected_reason)


def prove_array_uniqueness_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    if proof := array_static_reference_unsupported(
        problem, "array uniqueness difference"
    ):
        return proof
    model = problem.array_model
    plan = model.uniqueness_difference_plan(budget=array_witness_horizon(problem))
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
                plan.witness_skeleton, problem.dialect, context=problem.context
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason
                or "SAT array uniqueness array witness could not be constructed"
            )
        return validated_false(problem, witness, plan.rejected_reason)

    duplicate_witness = materialize_array_duplicate_witness_plan(
        plan.duplicate_plan, problem.dialect, context=problem.context
    )
    if duplicate_witness is None:
        return ProofResult.unsupported(
            plan.reason
            or "SAT array uniqueness difference could not construct a duplicate witness"
        )
    return validated_false(problem, duplicate_witness, plan.rejected_reason)


def prove_array_contains_difference(problem: DifferenceProblemProtocol) -> ProofResult:
    if proof := array_static_reference_unsupported(
        problem, "array contains difference"
    ):
        return proof
    model = problem.array_model
    plan = model.contains_difference_plan(
        problem.context, budget=array_witness_horizon(problem)
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
            budget=array_witness_horizon(problem),
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
            plan.witness_plan, problem.dialect, context=problem.context
        )
    if contains_witness is None:
        return ProofResult.unsupported(
            plan.reason or "SAT array contains witness could not be constructed"
        )
    return validated_false(problem, contains_witness, plan.rejected_reason)


def _array_contains_rhs_item_value_witness(
    problem: DifferenceProblemProtocol,
    model: ArrayDifferenceModel,
) -> ProofResult | None:
    lhs_contains = model.lhs_contains
    if lhs_contains is None:
        return None
    contains_witness = _array_term_witness(
        lhs_contains.term, problem.formula.lhs, problem
    )
    if contains_witness is None:
        return None
    if not contains_witness.has_witness:
        return None

    for slot in model.rhs_slots:
        if slot.term is not None and slot.term.kind == "true":
            continue
        if slot.term is None:
            continue
        slot_violation = problem.context.subproof_terms(
            SchemaTerm.true(),
            problem.formula.rhs,
            slot.term,
            problem.formula.rhs,
        )
        if slot_violation.status == "resource_exhausted":
            return ProofResult.resource_exhausted(
                slot_violation.reason
                or "SAT array contains slot subproof exhausted its budget"
            )
        if slot_violation.status != "proved_false" or slot_violation.witness is None:
            continue

        overrides = {slot.index: slot_violation.witness}
        contains_confirmed = confirm_term_valid(
            lhs_contains.term,
            problem.formula.lhs,
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
            length, budget=array_witness_horizon(problem)
        )
        witness = materialize_array_witness_skeleton(
            skeleton,
            problem.dialect,
            override=overrides,
            context=problem.context,
        )
        if witness is None:
            continue
        proof = validated_false(
            problem,
            witness,
            "SAT array contains RHS item-value witness was rejected",
        )
        if proof.status != "unsupported":
            return proof
    return None


def _array_term_witness(
    term: object | None,
    ir: LogicalSchemaIR,
    problem: DifferenceProblemProtocol,
) -> WitnessBuildResult | None:
    if not isinstance(term, SchemaTerm):
        return None
    witness = build_term_witness(term, ir, problem.context)
    return None if witness.status == "unsupported" else witness


def prove_array_item_values_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    if proof := array_static_reference_unsupported(
        problem, "array item-values difference"
    ):
        return proof
    model = problem.array_model
    plan = model.item_values_difference_plan(budget=array_witness_horizon(problem))
    if plan.status == "resource_exhausted":
        return ProofResult.resource_exhausted(plan.reason)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        witness = plan.witness
        if plan.witness_plan is not None:
            witness = materialize_array_witness_plan(
                plan.witness_plan, problem.dialect, context=problem.context
            )
        elif plan.witness_skeleton is not None:
            witness = materialize_array_witness_skeleton(
                plan.witness_skeleton, problem.dialect, context=problem.context
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason or "SAT array item-values witness could not be constructed"
            )
        return validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = _array_child_subproof(
            problem,
            obligation.lhs_term,
            obligation.rhs_term,
        )
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
            budget = array_witness_horizon(problem)
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
                return certified_false(
                    "array-item-value",
                    (
                        "array item-value subproof has a certified counterexample at "
                        "a reachable index"
                    ),
                    path=(str(obligation.index),),
                    child=proof,
                )
            witness = materialize_array_witness_plan(
                witness_plan, problem.dialect, context=problem.context
            )
            if witness is None:
                witness = materialize_array_witness_skeleton(
                    skeleton,
                    problem.dialect,
                    override=(obligation.index, proof.witness),
                    context=problem.context,
                )
            if witness is None:
                if model.array_witness_skeleton_reaching_budget_exhausted(
                    obligation.index, budget=budget
                ):
                    return certified_false(
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
            return validated_false(
                problem, witness, "SAT array item-values witness was rejected"
            )

    if (
        plan.post_obligation_witness_plan is not None
        or plan.post_obligation_witness_skeleton is not None
    ):
        witness = (
            materialize_array_witness_plan(
                plan.post_obligation_witness_plan,
                problem.dialect,
                context=problem.context,
            )
            if plan.post_obligation_witness_plan is not None
            else materialize_array_witness_skeleton(
                plan.post_obligation_witness_skeleton,
                problem.dialect,
                context=problem.context,
            )
        )
        if witness is not None:
            return validated_false(
                problem, witness, plan.post_obligation_rejected_reason
            )

    return ProofResult.true()


def _array_child_subproof(
    problem: DifferenceProblemProtocol,
    lhs_term: SchemaTerm | None,
    rhs_term: SchemaTerm | None,
) -> ProofResult:
    if lhs_term is not None and rhs_term is not None:
        proof = problem.context.subproof_terms(
            lhs_term,
            problem.formula.lhs,
            rhs_term,
            problem.formula.rhs,
        )
        if proof.status != "unsupported":
            return proof
        return ProofResult.unsupported(
            proof.reason or "SAT array child proof requires term-supported schemas"
        )
    return ProofResult.unsupported("SAT array child proof requires schema terms")
