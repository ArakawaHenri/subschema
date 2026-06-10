"""
Object SAT difference rules.
"""

from __future__ import annotations

from typing import Any

from subschema.contracts import ProofResult
from subschema.ir.constraints import ObjectPropertyCountBoundsConstraint
from subschema.ir.terms import SchemaTerm
from subschema.prover.difference import (
    ObjectDifferenceModel,
    materialize_closed_object_witness_skeleton,
    materialize_object_key_value_witness_skeleton,
    materialize_object_property_names_repair_skeleton,
    materialize_object_property_value_witness_skeleton,
)
from subschema.prover.protocols import DifferenceProblemProtocol
from subschema.prover.rules.common import (
    _certified_false,
    _lhs_static_reference_unsupported,
    _object_static_reference_unsupported,
    _validated_false,
)


def _prove_object_unevaluated_properties_difference(
    problem: DifferenceProblemProtocol,
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
        if plan.witness is not None:
            return _validated_false(problem, plan.witness, plan.rejected_reason)
        for skeleton in plan.witness_skeletons:
            witness = materialize_object_key_value_witness_skeleton(
                skeleton,
                problem.dialect,
                context=problem.context,
                ir=problem.formula.lhs,
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
        proof = _object_child_subproof(
            problem,
            obligation.lhs_term,
            obligation.rhs_term,
        )
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
                context=problem.context,
                ir=problem.formula.lhs,
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


def _prove_object_property_count_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    if proof := _object_static_reference_unsupported(
        problem, "object property-count difference"
    ):
        return proof
    if _rhs_rejects_empty_object(problem):
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
        return ProofResult.true()

    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _rhs_rejects_empty_object(problem: DifferenceProblemProtocol) -> bool:
    rhs_bounds = problem.formula.rhs.semantics.object_property_count_bounds_constraint
    return rhs_bounds is not None and rhs_bounds.minimum > 0


def _rhs_has_property_count_constraint(problem: DifferenceProblemProtocol) -> bool:
    rhs_bounds = problem.formula.rhs.semantics.object_property_count_bounds_constraint
    return rhs_bounds is not None and rhs_bounds.has_explicit_bound


def _rhs_property_count_is_directly_satisfied(
    problem: DifferenceProblemProtocol,
) -> bool:
    lhs_bounds: ObjectPropertyCountBoundsConstraint | None
    rhs_bounds: ObjectPropertyCountBoundsConstraint | None
    lhs_bounds = problem.formula.lhs.semantics.object_property_count_bounds_constraint
    rhs_bounds = problem.formula.rhs.semantics.object_property_count_bounds_constraint
    if lhs_bounds is None or rhs_bounds is None:
        return False

    if lhs_bounds.minimum < rhs_bounds.minimum:
        return False
    if rhs_bounds.maximum is None:
        return True
    return lhs_bounds.maximum is not None and lhs_bounds.maximum <= rhs_bounds.maximum


def _prove_object_presence_product_difference(
    problem: DifferenceProblemProtocol,
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
    problem: DifferenceProblemProtocol,
    model: ObjectDifferenceModel,
    witness_plans: tuple[Any, ...],
) -> ProofResult | None:
    for witness_plan in witness_plans:
        witness = witness_plan.witness()
        if witness_plan.atom is None and model.lhs_key_values is not None:
            materialized = materialize_object_key_value_witness_skeleton(
                model.lhs_key_values.witness_skeleton_for_names(witness_plan.present),
                problem.dialect,
                context=problem.context,
                ir=problem.formula.lhs,
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
    problem: DifferenceProblemProtocol,
    model: ObjectDifferenceModel,
) -> ProofResult | None:
    if model.lhs_key_values is None:
        return None
    constraint = (
        problem.formula.rhs.semantics
        .object_dependent_schema_properties_constraint
    )
    if constraint is None:
        return None

    for dependent_property in constraint.properties:
        trigger = dependent_property.trigger
        name = dependent_property.name
        if not model.lhs_key_values.allows_key(
            trigger
        ) or not model.lhs_key_values.allows_key(name):
            continue
        proof = _object_child_subproof(
            problem,
            model.lhs_key_values.value_term_for(name),
            dependent_property.term,
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
            context=problem.context,
            ir=problem.formula.lhs,
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


def _prove_object_property_values_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
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
                plan.witness_skeleton, problem.dialect, context=problem.context
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason
                or "SAT object property-values witness could not be constructed"
            )
        return _validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = _object_child_subproof(
            problem,
            obligation.lhs_term,
            obligation.rhs_term,
        )
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
                context=problem.context,
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


def _prove_object_key_value_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
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
                plan.witness_skeleton,
                problem.dialect,
                context=problem.context,
                ir=problem.formula.lhs,
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason or "SAT object key-value witness could not be constructed"
            )
        return _validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = _object_child_subproof(
            problem,
            obligation.lhs_term,
            obligation.rhs_term,
        )
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
                context=problem.context,
                ir=problem.formula.lhs,
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
        problem
    ) and not _rhs_property_count_is_directly_satisfied(problem):
        return ProofResult.unsupported(
            "SAT object key-value difference cannot prove property-count constraints"
        )
    return ProofResult.true()


def _prove_object_property_names_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
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
        plan.repair_skeleton, problem.dialect, context=problem.context
    )
    if repaired is None:
        return proof
    return _validated_false(
        problem,
        repaired,
        "SAT object propertyNames repaired witness was rejected by concrete validation",
    )


def _prove_closed_object_properties_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    model = problem.object_model
    plan = model.closed_object_difference_plan(problem.context)
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()

    if plan.status == "witness":
        witness = plan.witness
        if plan.witness_skeleton is not None:
            witness = materialize_closed_object_witness_skeleton(
                plan.witness_skeleton, problem.dialect, context=problem.context
            )
        if witness is None:
            return ProofResult.unsupported(
                plan.reason or "SAT closed-object witness could not be constructed"
            )
        return _validated_false(problem, witness, plan.rejected_reason)

    for obligation in plan.obligations:
        proof = _object_child_subproof(
            problem,
            obligation.lhs_term,
            obligation.rhs_term,
        )
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
                context=problem.context,
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


def _object_child_subproof(
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
            proof.reason or "SAT object child proof requires term-supported schemas"
        )
    return ProofResult.unsupported("SAT object child proof requires schema terms")
