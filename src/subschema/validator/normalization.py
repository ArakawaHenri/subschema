"""
Schema normalization helpers shared by the prover.
"""

from __future__ import annotations

from typing import Any

TOP: dict[str, Any] = {}
BOT: dict[str, Any] = {"not": {}}

SCHEMA_VALUE_KEYWORDS = {
    "additionalItems",
    "additionalProperties",
    "contains",
    "else",
    "if",
    "items",
    "not",
    "propertyNames",
    "then",
    "unevaluatedItems",
    "unevaluatedProperties",
}

SCHEMA_ARRAY_KEYWORDS = {"allOf", "anyOf", "oneOf", "prefixItems"}

SCHEMA_MAP_KEYWORDS = {
    "$defs",
    "definitions",
    "dependencies",
    "dependentSchemas",
    "patternProperties",
    "properties",
}

__all__ = [
    "BOT",
    "SCHEMA_ARRAY_KEYWORDS",
    "SCHEMA_MAP_KEYWORDS",
    "SCHEMA_VALUE_KEYWORDS",
    "TOP",
    "normalize_boolean_schemas",
]


def normalize_boolean_schemas(obj: Any, keyword: str | None = None) -> Any:
    if isinstance(obj, bool) and _is_schema_position(keyword):
        return TOP if obj else BOT
    if isinstance(obj, dict):
        if keyword in SCHEMA_MAP_KEYWORDS:
            return {key: normalize_boolean_schemas(value) for key, value in obj.items()}
        return {
            key: normalize_boolean_schemas(value, keyword=key)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        if keyword in SCHEMA_ARRAY_KEYWORDS or keyword == "items":
            return [normalize_boolean_schemas(item, keyword=keyword) for item in obj]
        return obj
    return obj


def _is_schema_position(keyword: str | None) -> bool:
    return keyword is None or keyword in SCHEMA_VALUE_KEYWORDS
