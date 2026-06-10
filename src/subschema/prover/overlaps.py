"""
Specialized overlap plans for bounded applicator witnesses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from subschema.contracts import ProofResult
from subschema.ir import LogicalSchemaIR, SchemaNode
from subschema.ir.constraints import StringLanguageConstraint
from subschema.work_protocols import RegexWorkContext

RightNotStringOverlapPlanStatus = Literal[
    "proved_true", "resource_exhausted", "unsupported", "witness"
]
RightNotStringOverlapProofChoice = Literal[
    "continue",
    "proved_true",
    "return_resource_exhausted",
    "validate_witness",
]

__all__ = [
    "RightNotStringOverlapPlan",
    "RightNotStringOverlapProofChoice",
    "RightNotStringOverlapPlanStatus",
    "right_not_string_overlap_proof_choice",
    "right_not_string_overlap_plan",
    "right_not_string_overlap_plan_from_constraints",
]


@dataclass(frozen=True)
class RightNotStringOverlapPlan:
    status: RightNotStringOverlapPlanStatus
    reason: str = ""
    witness: Any = None
    rejected_reason: str = ""

    @classmethod
    def true(cls) -> RightNotStringOverlapPlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> RightNotStringOverlapPlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> RightNotStringOverlapPlan:
        return cls("resource_exhausted", reason=reason)

    @classmethod
    def counterexample(cls, witness: Any) -> RightNotStringOverlapPlan:
        return cls(
            "witness",
            witness=witness,
            rejected_reason="SAT right-not string overlap witness was rejected",
        )


def right_not_string_overlap_proof_choice(
    status: RightNotStringOverlapPlanStatus,
) -> RightNotStringOverlapProofChoice:
    if status == "proved_true":
        return "proved_true"
    if status == "resource_exhausted":
        return "return_resource_exhausted"
    if status == "witness":
        return "validate_witness"
    return "continue"


def right_not_string_overlap_plan(
    lhs: LogicalSchemaIR,
    negated_node: SchemaNode,
    context: RegexWorkContext | None = None,
) -> RightNotStringOverlapPlan:
    return right_not_string_overlap_plan_from_constraints(
        lhs.string_language_constraint,
        _string_language_constraint_for_node(negated_node),
        context,
    )


def right_not_string_overlap_plan_from_constraints(
    lhs_constraint: StringLanguageConstraint | None,
    negated_constraint: StringLanguageConstraint | None,
    context: RegexWorkContext | None = None,
) -> RightNotStringOverlapPlan:
    if lhs_constraint is None or negated_constraint is None:
        return RightNotStringOverlapPlan.unsupported(
            "SAT right-not string overlap requires exact language facts"
        )
    lhs_shape = lhs_constraint
    negated_shape = negated_constraint
    if lhs_shape.accepts_non_string or negated_shape.accepts_non_string:
        return RightNotStringOverlapPlan.unsupported(
            "SAT right-not string overlap requires string-only schemas"
        )

    disjoint = lhs_shape.pattern.is_disjoint_from(negated_shape.pattern, context)
    if isinstance(disjoint, ProofResult):
        return RightNotStringOverlapPlan.resource_exhausted(
            disjoint.reason or "regex product exceeded proof work budget"
        )
    if disjoint:
        return RightNotStringOverlapPlan.true()

    overlap = lhs_shape.pattern.intersection(negated_shape.pattern, context)
    if isinstance(overlap, ProofResult):
        return RightNotStringOverlapPlan.resource_exhausted(
            overlap.reason or "regex product exceeded proof work budget"
        )

    witness = overlap.witness(context)
    if isinstance(witness, ProofResult):
        return RightNotStringOverlapPlan.resource_exhausted(
            witness.reason or "regex witness exceeded proof work budget"
        )
    if witness is None:
        return RightNotStringOverlapPlan.unsupported(
            "SAT right-not string overlap witness could not be constructed"
        )
    return RightNotStringOverlapPlan.counterexample(witness)


def _string_language_constraint_for_node(
    node: SchemaNode,
) -> StringLanguageConstraint | None:
    assertion = node.semantics.assertion("string-language")
    if assertion is None or not isinstance(assertion.value, StringLanguageConstraint):
        return None
    return assertion.value
