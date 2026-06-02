"""
Meet/join projection policy for the proof kernel.
"""

from __future__ import annotations

from typing import Any

from subschema.kernel.finite import (
    finite_values_projection,
    inhabited_finite_values_for_schema,
    schema_is_empty_finite,
)
from subschema.kernel.schemas import (
    schema_is_false,
    schema_is_true,
    schemas_equal,
)
from subschema.kernel.validation import validation_backend_for


class ProjectionEngine:
    def __init__(self, context: Any):
        self.context = context
        self.dialect = context.dialect

    def meet(self, lhs: Any, rhs: Any) -> Any:
        projection = self.meet_projection(lhs, rhs)
        if projection is not None:
            return projection
        finite_projection = self.finite_meet_projection(lhs, rhs)
        if finite_projection is not None:
            return finite_projection
        return {"allOf": [lhs, rhs]}

    def join(self, lhs: Any, rhs: Any) -> Any:
        projection = self.join_projection(lhs, rhs)
        if projection is not None:
            return projection
        finite_projection = self.finite_join_projection(lhs, rhs)
        if finite_projection is not None:
            return finite_projection
        return {"anyOf": [lhs, rhs]}

    def meet_projection(self, lhs: Any, rhs: Any) -> Any | None:
        if schemas_equal(lhs, rhs) or schema_is_false(lhs) or schema_is_true(rhs):
            return lhs
        if schema_is_false(rhs) or schema_is_true(lhs):
            return rhs
        if schema_is_empty_finite(lhs, self.dialect) or schema_is_empty_finite(
            rhs, self.dialect
        ):
            return False
        lhs_sub_rhs = self.context.subproof(lhs, rhs)
        if lhs_sub_rhs.status == "proved_true":
            return lhs
        rhs_sub_lhs = self.context.subproof(rhs, lhs)
        if rhs_sub_lhs.status == "proved_true":
            return rhs
        return None

    def join_projection(self, lhs: Any, rhs: Any) -> Any | None:
        if schemas_equal(lhs, rhs) or schema_is_true(lhs) or schema_is_false(rhs):
            return lhs
        if schema_is_true(rhs) or schema_is_false(lhs):
            return rhs
        if schema_is_empty_finite(lhs, self.dialect):
            return rhs
        if schema_is_empty_finite(rhs, self.dialect):
            return lhs
        lhs_sub_rhs = self.context.subproof(lhs, rhs)
        if lhs_sub_rhs.status == "proved_true":
            return rhs
        rhs_sub_lhs = self.context.subproof(rhs, lhs)
        if rhs_sub_lhs.status == "proved_true":
            return lhs
        return None

    def finite_meet_projection(self, lhs: Any, rhs: Any) -> Any | None:
        lhs_values = inhabited_finite_values_for_schema(lhs, self.dialect)
        rhs_values = inhabited_finite_values_for_schema(rhs, self.dialect)
        if lhs_values is None and rhs_values is None:
            return None

        candidates = lhs_values if lhs_values is not None else rhs_values
        backend = validation_backend_for(self.dialect)
        values = [
            value
            for value in candidates
            if backend.is_valid(lhs, value) and backend.is_valid(rhs, value)
        ]
        return finite_values_projection(values)

    def finite_join_projection(self, lhs: Any, rhs: Any) -> Any | None:
        lhs_values = inhabited_finite_values_for_schema(lhs, self.dialect)
        rhs_values = inhabited_finite_values_for_schema(rhs, self.dialect)
        if lhs_values is None or rhs_values is None:
            return None
        return finite_values_projection(lhs_values + rhs_values)
