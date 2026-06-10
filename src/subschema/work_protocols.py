from __future__ import annotations

from typing import Any, Protocol

from subschema.contracts import ProofResult
from subschema.dialects import Dialect


class RegexWorkContext(Protocol):
    def spend_work(
        self,
        units: int,
        kind: str,
        reason: str | None = None,
    ) -> ProofResult | None: ...


class SymbolicContext(RegexWorkContext, Protocol):
    @property
    def solver_timeout_ms(self) -> int: ...


class SubproofContext(Protocol):
    dialect: Dialect

    def subproof_ir(self, lhs: Any, rhs: Any) -> ProofResult: ...

    def subproof_term(self, lhs: Any, rhs: Any, ir: Any) -> ProofResult: ...

    def subproof_terms(
        self,
        lhs: Any,
        lhs_ir: Any,
        rhs: Any,
        rhs_ir: Any,
    ) -> ProofResult: ...
