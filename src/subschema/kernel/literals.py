"""
Explicit literal facts shared by finite and type reasoning.
"""

from __future__ import annotations

from typing import Any

from subschema.kernel.values import dedupe


def explicit_finite_values_for_schema(schema: Any) -> list[Any] | None:
    if schema is False:
        return []
    if schema is True or not isinstance(schema, dict):
        return None
    if "const" in schema:
        return [schema["const"]]
    enum = schema.get("enum")
    if isinstance(enum, list):
        return dedupe(list(enum))
    return None
