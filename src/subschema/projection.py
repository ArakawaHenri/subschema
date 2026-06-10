"""
Public JSON Schema emission for prover projection decisions.
"""

from __future__ import annotations

from typing import Any

from subschema.prover.projection import ProjectionDecision

__all__ = ["projection_decision_schema"]


def projection_decision_schema(decision: ProjectionDecision) -> Any:
    if decision.kind == "schema":
        return decision.schema
    if decision.kind == "source":
        if decision.source is None:
            raise ValueError("source projection decision requires source IR")
        return decision.source.source.schema
    if decision.kind == "all_of":
        if decision.lhs is None or decision.rhs is None:
            raise ValueError("allOf projection decision requires both input IRs")
        return {"allOf": [decision.lhs.source.schema, decision.rhs.source.schema]}
    if decision.kind == "any_of":
        if decision.lhs is None or decision.rhs is None:
            raise ValueError("anyOf projection decision requires both input IRs")
        return {"anyOf": [decision.lhs.source.schema, decision.rhs.source.schema]}
    raise ValueError(f"unknown projection decision kind: {decision.kind!r}")
