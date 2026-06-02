"""
Applicator composition and shared proof-composition helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from subschema.kernel.contracts import ProofResult
from subschema.kernel.disjointness import schemas_are_disjoint
from subschema.kernel.schemas import is_pure_schema_array_applicator
from subschema.kernel.validation import validation_backend_for
from subschema.kernel.witnesses import finite_projection_witness

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext

__all__ = [
    "ApplicatorCompositionTactic",
    "finite_projection_witness",
    "proof_is_inconclusive",
    "schemas_are_disjoint",
]


class ApplicatorCompositionTactic:
    def __init__(self, context: ProofContext):
        self.context = context
        self.dialect = self.context.dialect

    def is_subschema(self, lhs: Any, rhs: Any) -> ProofResult:
        if is_pure_schema_array_applicator(lhs, "anyOf"):
            return self._prove_left_any_of(lhs["anyOf"], lhs, rhs)
        if is_pure_schema_array_applicator(lhs, "oneOf"):
            return self._prove_left_one_of(lhs["oneOf"], lhs, rhs)
        if is_pure_schema_array_applicator(lhs, "allOf"):
            return self._prove_left_all_of(lhs["allOf"], lhs, rhs)
        if is_pure_schema_array_applicator(rhs, "anyOf"):
            return self._prove_right_any_of(rhs["anyOf"], lhs, rhs)
        if is_pure_schema_array_applicator(rhs, "oneOf"):
            return self._prove_right_one_of(rhs["oneOf"], lhs, rhs)
        if is_pure_schema_array_applicator(rhs, "allOf"):
            return self._prove_right_all_of(rhs["allOf"], lhs, rhs)
        return ProofResult.unsupported(
            "schema is outside the exact applicator composition fragment"
        )

    def _prove_left_any_of(
        self, branches: list[Any], lhs: Any, rhs: Any
    ) -> ProofResult:
        backend = validation_backend_for(self.dialect)
        for branch in branches:
            proof = self.context.subproof(branch, rhs)
            if proof.status == "proved_true":
                continue
            if proof_is_inconclusive(proof):
                return proof
            if proof.witness is None:
                return ProofResult.unsupported(
                    "applicator branch counterexample could not be constructed"
                )
            if backend.validates_difference(lhs, rhs, proof.witness):
                return proof
            return ProofResult.unsupported(
                "applicator branch counterexample was rejected by concrete validation"
            )
        return ProofResult.true()

    def _prove_left_one_of(
        self, branches: list[Any], lhs: Any, rhs: Any
    ) -> ProofResult:
        unsupported: ProofResult | None = None
        backend = validation_backend_for(self.dialect)
        for branch in branches:
            proof = self.context.subproof(branch, rhs)
            if proof.status == "proved_true":
                continue
            if proof_is_inconclusive(proof):
                unsupported = proof
                continue
            if proof.witness is not None and backend.validates_difference(
                lhs, rhs, proof.witness
            ):
                return proof
            unsupported = ProofResult.unsupported(
                "left oneOf branch counterexample is not necessarily in the "
                "oneOf result"
            )
        return ProofResult.true() if unsupported is None else unsupported

    def _prove_left_all_of(
        self, branches: list[Any], lhs: Any, rhs: Any
    ) -> ProofResult:
        backend = validation_backend_for(self.dialect)
        unsupported: ProofResult | None = None
        for branch in branches:
            proof = self.context.subproof(branch, rhs)
            if proof.status == "proved_true":
                return ProofResult.true()
            if proof_is_inconclusive(proof):
                unsupported = proof
                continue
            if proof.witness is not None and backend.validates_difference(
                lhs, rhs, proof.witness
            ):
                return proof
        return unsupported or ProofResult.unsupported(
            "left allOf proof could not establish a covering conjunct"
        )

    def _prove_right_any_of(
        self, branches: list[Any], lhs: Any, rhs: Any
    ) -> ProofResult:
        backend = validation_backend_for(self.dialect)
        unsupported: ProofResult | None = None
        for branch in branches:
            proof = self.context.subproof(lhs, branch)
            if proof.status == "proved_true":
                return ProofResult.true()
            if proof_is_inconclusive(proof):
                unsupported = proof
                continue
            if proof.witness is not None and backend.validates_difference(
                lhs, rhs, proof.witness
            ):
                return proof
        return unsupported or ProofResult.unsupported(
            "right anyOf proof could not establish a covering branch"
        )

    def _prove_right_one_of(
        self, branches: list[Any], lhs: Any, rhs: Any
    ) -> ProofResult:
        covering_indexes = []
        unsupported: ProofResult | None = None
        for index, branch in enumerate(branches):
            proof = self.context.subproof(lhs, branch)
            if proof.status == "proved_true":
                covering_indexes.append(index)
            elif proof_is_inconclusive(proof):
                unsupported = proof

        if len(covering_indexes) != 1:
            return unsupported or ProofResult.unsupported(
                "right oneOf proof could not establish exactly one covering branch"
            )

        covered_index = covering_indexes[0]
        for index, branch in enumerate(branches):
            if index == covered_index:
                continue
            disjoint = schemas_are_disjoint(lhs, branch, self.context)
            if disjoint.status == "proved_true":
                continue
            if disjoint.status == "proved_false" and disjoint.witness is not None:
                backend = validation_backend_for(self.dialect)
                if backend.validates_difference(lhs, rhs, disjoint.witness):
                    return disjoint
                return ProofResult.unsupported(
                    "right oneOf overlap witness was rejected by concrete validation"
                )
            return disjoint
        return ProofResult.true()

    def _prove_right_all_of(
        self, branches: list[Any], lhs: Any, rhs: Any
    ) -> ProofResult:
        backend = validation_backend_for(self.dialect)
        for branch in branches:
            proof = self.context.subproof(lhs, branch)
            if proof.status == "proved_true":
                continue
            if proof_is_inconclusive(proof):
                return proof
            if proof.witness is None:
                return ProofResult.unsupported(
                    "applicator conjunct counterexample could not be constructed"
                )
            if backend.validates_difference(lhs, rhs, proof.witness):
                return proof
            return ProofResult.unsupported(
                "applicator conjunct counterexample was rejected by concrete validation"
            )
        return ProofResult.true()


def proof_is_inconclusive(result: ProofResult) -> bool:
    return result.status in {"unsupported", "resource_exhausted"}
