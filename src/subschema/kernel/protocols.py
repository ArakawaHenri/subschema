from __future__ import annotations

from typing import Any, Protocol

from subschema.dialects import Dialect
from subschema.kernel.contracts import ProofResult


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

    def subproof(self, lhs: Any, rhs: Any) -> ProofResult: ...
