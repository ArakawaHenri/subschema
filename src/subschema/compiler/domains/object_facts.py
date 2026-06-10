"""
Low-level object schema facts shared by object-domain and finite reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from subschema.compiler.domains.types import type_shape_for_type_keyword
from subschema.compiler.schemas import IGNORED_SCHEMA_METADATA_KEYS

__all__ = [
    "ObjectFiniteValueShape",
    "object_additional_properties_schema_for_schema",
    "object_finite_value_shape_for_schema",
    "object_is_exact_object_only_schema",
    "object_pattern_property_schemas_for_schema",
    "object_property_count_bounds_for_schema",
    "object_property_names_schema_for_schema",
    "object_property_schemas_for_schema",
    "object_required_names_for_schema",
]


@dataclass(frozen=True)
class ObjectFiniteValueShape:
    properties: dict[str, Any]
    required_names: frozenset[str]
    lower: int
    upper: int


def object_required_names_for_schema(schema: Any) -> frozenset[str]:
    if not isinstance(schema, dict):
        return frozenset()
    required = schema.get("required")
    if not isinstance(required, list):
        return frozenset()
    return frozenset(name for name in required if isinstance(name, str))


def object_property_schemas_for_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    return {
        name: subschema
        for name, subschema in properties.items()
        if isinstance(name, str)
    }


def object_pattern_property_schemas_for_schema(
    schema: Any,
) -> tuple[tuple[str, Any], ...]:
    if not isinstance(schema, dict):
        return ()
    patterns = schema.get("patternProperties")
    if not isinstance(patterns, dict):
        return ()
    return tuple(
        (pattern, subschema)
        for pattern, subschema in sorted(patterns.items())
        if isinstance(pattern, str)
    )


def object_additional_properties_schema_for_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return True
    return schema.get("additionalProperties", True)


def object_property_names_schema_for_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return True
    return schema.get("propertyNames", True)


def object_property_count_bounds_for_schema(
    schema: Any,
) -> tuple[int, int | None, bool] | None:
    if not isinstance(schema, dict):
        return None
    minimum = schema.get("minProperties", 0)
    maximum = schema.get("maxProperties")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None
    return minimum, maximum, "minProperties" in schema or "maxProperties" in schema


def object_is_exact_object_only_schema(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    return type_shape is not None and type_shape.atoms == {"object"}


def object_finite_value_shape_for_schema(
    schema: Any,
) -> ObjectFiniteValueShape | None:
    if not isinstance(schema, dict) or not object_is_exact_object_only_schema(schema):
        return None
    if not _is_finite_object_fragment_schema(schema):
        return None

    properties = object_property_schemas_for_schema(schema)
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(
        isinstance(name, str) for name in required
    ):
        return None
    required_names = frozenset(required)

    if not required_names <= properties.keys():
        return ObjectFiniteValueShape(properties, required_names, 1, 0)

    minimum = schema.get("minProperties", 0)
    maximum = schema.get("maxProperties", len(properties))
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if not isinstance(maximum, int) or isinstance(maximum, bool):
        return None
    return ObjectFiniteValueShape(properties, required_names, minimum, maximum)


def _is_finite_object_fragment_schema(schema: dict[str, Any]) -> bool:
    allowed = {
        "additionalProperties",
        "maxProperties",
        "minProperties",
        "properties",
        "required",
        "type",
    }
    if not all(key in allowed or key in IGNORED_SCHEMA_METADATA_KEYS for key in schema):
        return False
    return schema.get("additionalProperties") is False
