"""
Proof-engine orchestration for the kernel.
"""

from __future__ import annotations

from typing import Any

import subschema.kernel.driver as proof_driver
from subschema.dialects import Dialect, resolve_dialect
from subschema.kernel.context import ProofContext
from subschema.kernel.contracts import ProofOptions, ProofResult, ProofSide


class ProofEngine:
    def __init__(
        self,
        dialect: Dialect,
        *,
        context: ProofContext | None = None,
        options: ProofOptions | None = None,
    ):
        self.context = context or ProofContext(
            dialect, ProofOptions() if options is None else options
        )
        self.dialect = self.context.dialect

    @classmethod
    def for_schemas(
        cls,
        *schemas: Any,
        dialect: Dialect | str | None = None,
        options: ProofOptions | None = None,
    ) -> ProofEngine:
        return cls(resolve_dialect(*schemas, dialect=dialect), options=options)

    def is_subschema(self, lhs: Any, rhs: Any) -> ProofResult:
        return proof_driver.prove_subschema_with_context(
            self.context,
            lhs,
            rhs,
        )

    def is_subschema_bool(self, lhs: Any, rhs: Any) -> bool:
        return self.is_subschema(lhs, rhs).as_bool(self.dialect)

    def meet(self, lhs: Any, rhs: Any) -> Any:
        return self.context.meet(lhs, rhs)

    def join(self, lhs: Any, rhs: Any) -> Any:
        return self.context.join(lhs, rhs)

    def _validate_schema(self, schema: Any) -> None:
        proof_driver.validate_schema(self.context, schema)

    def _schema_validation_result(
        self, schema: Any, side: ProofSide
    ) -> ProofResult | None:
        return proof_driver.schema_validation_result(self.context, schema, side)

    def _bounded_ir_proof(self, lhs: Any, rhs: Any) -> ProofResult:
        return proof_driver.bounded_ir_proof(self.context, lhs, rhs)
