"""
IR-native proof-engine orchestration for the prover.
"""

from __future__ import annotations

import subschema.prover.driver as proof_driver
from subschema.contracts import ProofOptions, ProofResult
from subschema.dialects import Dialect
from subschema.ir import LogicalSchemaIR
from subschema.ir.terms import SchemaTerm
from subschema.prover.context import ProofContext


class ProofEngine:
    def __init__(
        self,
        dialect: Dialect,
        *,
        context: ProofContext | None = None,
        options: ProofOptions | None = None,
    ):
        self.context = context or ProofContext(
            dialect,
            ProofOptions() if options is None else options,
        )
        self.dialect = self.context.dialect

    def is_ir_subschema(
        self,
        lhs: LogicalSchemaIR,
        rhs: LogicalSchemaIR,
    ) -> ProofResult:
        return proof_driver.prove_ir_subschema_with_context(self.context, lhs, rhs)

    def is_ir_subschema_bool(
        self,
        lhs: LogicalSchemaIR,
        rhs: LogicalSchemaIR,
    ) -> bool:
        return self.is_ir_subschema(lhs, rhs).as_bool(self.dialect)

    def is_term_subschema(
        self,
        lhs: SchemaTerm,
        lhs_ir: LogicalSchemaIR,
        rhs: SchemaTerm,
        rhs_ir: LogicalSchemaIR,
    ) -> ProofResult:
        return proof_driver.prove_terms_subschema_with_context(
            self.context,
            lhs,
            lhs_ir,
            rhs,
            rhs_ir,
        )
