from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from subschema.contracts import ExpensiveProofKind, ProofResult
from subschema.dialects import Dialect
from subschema.prover.formulas import DifferenceFormula
from subschema.work_protocols import SubproofContext, SymbolicContext


class ProofContextProtocol(SymbolicContext, SubproofContext, Protocol):
    resources: Mapping[str, Any]

    @property
    def proof_policy_identity(self) -> tuple[object, ...]: ...

    @property
    def default_search_horizon(self) -> int: ...

    @property
    def endeavor_enabled(self) -> bool: ...

    @property
    def work_is_exhausted(self) -> bool: ...

    def allows_expensive_proof(self, kind: ExpensiveProofKind) -> bool: ...

    def enter_expensive_proof(
        self,
        kind: ExpensiveProofKind,
        *,
        units: int = 0,
        reason: str | None = None,
    ) -> ProofResult | None: ...

    def expensive_proof_required(self, kind: ExpensiveProofKind) -> ProofResult: ...

    def cache_get(self, namespace: str, key: tuple[Any, ...]) -> object | None: ...

    def cache_set(
        self, namespace: str, key: tuple[Any, ...], value: object
    ) -> None: ...


class DifferenceProblemProtocol(Protocol):
    @property
    def formula(self) -> DifferenceFormula: ...

    @property
    def context(self) -> ProofContextProtocol: ...

    @property
    def dialect(self) -> Dialect: ...

    @property
    def applicator_plan_set(self) -> Any: ...

    @property
    def array_model(self) -> Any: ...

    @property
    def object_model(self) -> Any: ...

    def lhs_constraint(self, kind: Any) -> Any | None: ...

    def rhs_constraint(self, kind: Any) -> Any | None: ...

    def lhs_require_exact(self, kind: Any, reason: str) -> ProofResult | None: ...

    def rhs_require_exact(self, kind: Any, reason: str) -> ProofResult | None: ...
