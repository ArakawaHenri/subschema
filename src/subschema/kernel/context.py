"""
Proof context, policy, and budget state for the kernel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import subschema.kernel.driver as proof_driver
from subschema.dialects import Dialect
from subschema.kernel.contracts import (
    ExpensiveProofKind,
    ProofOptions,
    ProofResult,
    ProofWorkMeter,
)
from subschema.kernel.values import stable_key

_EXPENSIVE_PROOF_WORK_LABELS: dict[ExpensiveProofKind, str] = {
    "array_product": "array product",
    "branch_product": "branch expansion",
    "evaluation_trace": "evaluation trace",
    "object_product": "object product",
    "regex_product": "regex product",
}

_DEFAULT_CONSTRUCTIVE_WITNESS_HORIZON = 4096


@dataclass
class ProofContext:
    dialect: Dialect
    options: ProofOptions = field(default_factory=ProofOptions)
    subproof_cache: dict[tuple[Any, ...], ProofResult] = field(default_factory=dict)
    evaluation_expression_cache: dict[tuple[Any, ...], Any] = field(
        default_factory=dict
    )
    work_meter: ProofWorkMeter = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.options, ProofOptions):
            raise TypeError("options must be a ProofOptions instance")
        limit = self.options.budgets.max_work if self.options.endeavor else -1
        self.work_meter = ProofWorkMeter(limit)

    def subproof(self, lhs: Any, rhs: Any) -> ProofResult:
        key = self._subproof_cache_key(lhs, rhs)
        if key not in self.subproof_cache:
            exhausted = self.consume_branch_expansion(
                "branch expansion exceeded proof work budget"
            )
            if exhausted is not None:
                return exhausted
            self.subproof_cache[key] = proof_driver.prove_subschema_with_context(
                self,
                lhs,
                rhs,
            )
        return self.subproof_cache[key]

    def _subproof_cache_key(self, lhs: Any, rhs: Any) -> tuple[Any, ...]:
        return (
            self.dialect,
            self.options.endeavor,
            self.options.budgets.max_work,
            self.options.budgets.timeout_ms,
            stable_key(lhs),
            stable_key(rhs),
        )

    def consume_branch_expansion(self, reason: str) -> ProofResult | None:
        return self.spend_work(1, "branch expansion", reason)

    def spend_work(
        self, units: int, kind: str, reason: str | None = None
    ) -> ProofResult | None:
        return self.work_meter.spend(units, kind, reason)

    def allows_expensive_proof(self, kind: ExpensiveProofKind) -> bool:
        self.proof_work_label(kind)
        return self.options.endeavor

    def enter_expensive_proof(
        self,
        kind: ExpensiveProofKind,
        *,
        units: int = 0,
        reason: str | None = None,
    ) -> ProofResult | None:
        if not self.allows_expensive_proof(kind):
            return self.expensive_proof_required(kind)
        return self.spend_work(units, self.proof_work_label(kind), reason)

    def expensive_proof_required(self, kind: ExpensiveProofKind) -> ProofResult:
        return ProofResult.unsupported(
            f"{self.proof_work_label(kind)} requires endeavor proof"
        )

    def proof_work_label(self, kind: ExpensiveProofKind) -> str:
        return _EXPENSIVE_PROOF_WORK_LABELS[kind]

    @property
    def default_search_horizon(self) -> int:
        if self.options.endeavor:
            return self.options.budgets.max_work
        return _DEFAULT_CONSTRUCTIVE_WITNESS_HORIZON

    @property
    def work_is_exhausted(self) -> bool:
        return self.work_meter.exhausted

    def meet(self, lhs: Any, rhs: Any) -> Any:
        from subschema.kernel.projection import ProjectionEngine

        return ProjectionEngine(self).meet(lhs, rhs)

    def join(self, lhs: Any, rhs: Any) -> Any:
        from subschema.kernel.projection import ProjectionEngine

        return ProjectionEngine(self).join(lhs, rhs)

    def finite_meet_projection(self, lhs: Any, rhs: Any) -> Any | None:
        from subschema.kernel.projection import ProjectionEngine

        return ProjectionEngine(self).finite_meet_projection(lhs, rhs)

    def finite_join_projection(self, lhs: Any, rhs: Any) -> Any | None:
        from subschema.kernel.projection import ProjectionEngine

        return ProjectionEngine(self).finite_join_projection(lhs, rhs)
