"""
Meet/join projection policy for the prover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from subschema.dialects import Dialect
from subschema.ir import LogicalSchemaIR
from subschema.ir.terms import SchemaTerm
from subschema.prover.confirmation import confirm_valid
from subschema.prover.disjointness import irs_are_disjoint
from subschema.prover.finite import (
    finite_values_projection,
    inhabited_finite_values_for_ir,
    schema_is_empty_finite,
)


@dataclass(frozen=True)
class ProjectionDecision:
    kind: str
    schema: Any = None
    source: LogicalSchemaIR | None = None
    lhs: LogicalSchemaIR | None = None
    rhs: LogicalSchemaIR | None = None

    @classmethod
    def schema_value(cls, schema: Any) -> ProjectionDecision:
        return cls("schema", schema=schema)

    @classmethod
    def source_ir(cls, source: LogicalSchemaIR) -> ProjectionDecision:
        return cls("source", source=source)

    @classmethod
    def all_of(cls, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR) -> ProjectionDecision:
        return cls("all_of", lhs=lhs, rhs=rhs)

    @classmethod
    def any_of(cls, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR) -> ProjectionDecision:
        return cls("any_of", lhs=lhs, rhs=rhs)


class ProjectionEngine:
    def __init__(self, context: Any):
        self.context = context
        self.dialect = context.dialect

    def meet_decision_ir(
        self, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
    ) -> ProjectionDecision:
        projection = self.meet_projection_ir(lhs, rhs)
        if projection is not None:
            return projection
        finite_projection = self.finite_meet_projection_ir(lhs, rhs)
        if finite_projection is not None:
            return ProjectionDecision.schema_value(finite_projection)
        return ProjectionDecision.all_of(lhs, rhs)

    def join_decision_ir(
        self, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
    ) -> ProjectionDecision:
        projection = self.join_projection_ir(lhs, rhs)
        if projection is not None:
            return projection
        finite_projection = self.finite_join_projection_ir(lhs, rhs)
        if finite_projection is not None:
            return ProjectionDecision.schema_value(finite_projection)
        return ProjectionDecision.any_of(lhs, rhs)

    def meet_projection_ir(
        self, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
    ) -> ProjectionDecision | None:
        if (
            _irs_share_source(lhs, rhs)
            or _ir_is_boolean(lhs, False)
            or _ir_is_boolean(rhs, True)
        ):
            return ProjectionDecision.source_ir(lhs)
        if _ir_is_boolean(rhs, False) or _ir_is_boolean(lhs, True):
            return ProjectionDecision.source_ir(rhs)
        if schema_is_empty_finite(lhs, self.context) or schema_is_empty_finite(
            rhs, self.context
        ):
            return ProjectionDecision.schema_value(
                _empty_schema_for_dialect(self.dialect)
            )
        resource_disjoint = self._reference_disjointness_projection_ir(lhs, rhs)
        if resource_disjoint is not None:
            return resource_disjoint
        disjoint = irs_are_disjoint(lhs, rhs, self.context)
        if disjoint.status == "proved_true":
            return ProjectionDecision.schema_value(
                _empty_schema_for_dialect(self.dialect)
            )
        lhs_sub_rhs = self.context.subproof_terms(
            lhs.root_term, lhs, rhs.root_term, rhs
        )
        if lhs_sub_rhs.status == "proved_true":
            return ProjectionDecision.source_ir(lhs)
        rhs_sub_lhs = self.context.subproof_terms(
            rhs.root_term, rhs, lhs.root_term, lhs
        )
        if rhs_sub_lhs.status == "proved_true":
            return ProjectionDecision.source_ir(rhs)
        return None

    def join_projection_ir(
        self, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
    ) -> ProjectionDecision | None:
        if (
            _irs_share_source(lhs, rhs)
            or _ir_is_boolean(lhs, True)
            or _ir_is_boolean(rhs, False)
        ):
            return ProjectionDecision.source_ir(lhs)
        if _ir_is_boolean(rhs, True) or _ir_is_boolean(lhs, False):
            return ProjectionDecision.source_ir(rhs)
        if schema_is_empty_finite(lhs, self.context):
            return ProjectionDecision.source_ir(rhs)
        if schema_is_empty_finite(rhs, self.context):
            return ProjectionDecision.source_ir(lhs)
        lhs_sub_rhs = self.context.subproof_terms(
            lhs.root_term, lhs, rhs.root_term, rhs
        )
        if lhs_sub_rhs.status == "proved_true":
            return ProjectionDecision.source_ir(rhs)
        rhs_sub_lhs = self.context.subproof_terms(
            rhs.root_term, rhs, lhs.root_term, lhs
        )
        if rhs_sub_lhs.status == "proved_true":
            return ProjectionDecision.source_ir(lhs)
        return None

    def _reference_disjointness_projection_ir(
        self,
        lhs_ir: LogicalSchemaIR,
        rhs_ir: LogicalSchemaIR,
    ) -> ProjectionDecision | None:
        if not getattr(self.context, "resources", None):
            return None
        if not (
            lhs_ir.semantics.reference.has_static_reference_boundary
            or lhs_ir.semantics.reference.has_dynamic_reference
            or lhs_ir.semantics.reference.has_recursive_reference
            or rhs_ir.semantics.reference.has_static_reference_boundary
            or rhs_ir.semantics.reference.has_dynamic_reference
            or rhs_ir.semantics.reference.has_recursive_reference
        ):
            return None
        disjoint = self.context.subproof_terms(
            lhs_ir.root_term,
            lhs_ir,
            SchemaTerm.not_(rhs_ir.root_term),
            rhs_ir,
        )
        if disjoint.status == "proved_true":
            return ProjectionDecision.schema_value(
                _empty_schema_for_dialect(self.dialect)
            )
        return None

    def finite_meet_projection_ir(
        self, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
    ) -> Any | None:
        lhs_values = inhabited_finite_values_for_ir(lhs, self.context)
        rhs_values = inhabited_finite_values_for_ir(rhs, self.context)
        if lhs_values is None and rhs_values is None:
            return None

        candidates = lhs_values if lhs_values is not None else rhs_values
        if candidates is None:
            return None
        values = []
        lhs_source = lhs.source.to_source()
        rhs_source = rhs.source.to_source()
        for value in candidates:
            lhs_confirmed = confirm_valid(lhs_source, value, self.context)
            rhs_confirmed = confirm_valid(rhs_source, value, self.context)
            if (
                lhs_confirmed.status == "unsupported"
                or rhs_confirmed.status == "unsupported"
            ):
                return None
            if (
                lhs_confirmed.status == "confirmed"
                and rhs_confirmed.status == "confirmed"
            ):
                values.append(value)
        return finite_values_projection(values)

    def finite_join_projection_ir(
        self, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
    ) -> Any | None:
        lhs_values = inhabited_finite_values_for_ir(lhs, self.context)
        rhs_values = inhabited_finite_values_for_ir(rhs, self.context)
        if lhs_values is None or rhs_values is None:
            return None
        return finite_values_projection(lhs_values + rhs_values)


def _irs_share_source(lhs: LogicalSchemaIR, rhs: LogicalSchemaIR) -> bool:
    return lhs.source == rhs.source


def _ir_is_boolean(ir: LogicalSchemaIR, value: bool) -> bool:
    return ir.root.boolean_value is value


def _empty_schema_for_dialect(dialect: Dialect) -> Any:
    if dialect == Dialect.DRAFT4:
        return {"not": {}}
    return False
