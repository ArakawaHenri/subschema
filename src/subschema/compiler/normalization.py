"""
Compiler-owned raw schema normalization helpers.
"""

from __future__ import annotations

from typing import Any

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

_IGNORED_PROOF_KEYS = frozenset(
    {
        "$anchor",
        "$comment",
        "$defs",
        "$dynamicAnchor",
        "$id",
        "$schema",
        "$vocabulary",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "default",
        "definitions",
        "deprecated",
        "description",
        "discriminator",
        "examples",
        "format",
        "readOnly",
        "title",
        "writeOnly",
    }
)
_SIMPLE_UNEVALUATED_OBJECT_KEYS = frozenset(
    {
        "allOf",
        "maxProperties",
        "minProperties",
        "properties",
        "required",
        "type",
        "unevaluatedProperties",
    }
)
_SIMPLE_UNEVALUATED_OBJECT_CHILD_KEYS = frozenset(
    {"maxProperties", "minProperties", "properties", "required", "type"}
)
_SIMPLE_UNEVALUATED_ARRAY_KEYS = frozenset(
    {
        "allOf",
        "maxItems",
        "minItems",
        "prefixItems",
        "type",
        "unevaluatedItems",
    }
)
_SIMPLE_UNEVALUATED_ARRAY_CHILD_KEYS = frozenset(
    {"maxItems", "minItems", "prefixItems", "type"}
)


def normalize_simple_lhs_unevaluated_for_proof(schema: Any) -> Any:
    """Project narrow positive unevaluated fragments to equivalent closed shapes."""
    if not isinstance(schema, dict):
        return schema
    normalized_object = _normalize_simple_unevaluated_properties(schema)
    if normalized_object is not None:
        return normalized_object
    normalized_array = _normalize_simple_unevaluated_items(schema)
    if normalized_array is not None:
        return normalized_array
    return schema


def _normalize_simple_unevaluated_properties(schema: dict[str, Any]) -> Any | None:
    unevaluated = schema.get("unevaluatedProperties")
    if not isinstance(unevaluated, bool | dict):
        return None
    if not _schema_keys_are_allowed(schema, _SIMPLE_UNEVALUATED_OBJECT_KEYS):
        return None

    sources = _simple_all_of_sources(schema, _SIMPLE_UNEVALUATED_OBJECT_CHILD_KEYS)
    if sources is None or any(_object_type_is_not_exact(source) for source in sources):
        return None

    property_schemas: dict[str, list[Any]] = {}
    required: set[str] = set()
    min_properties = 0
    max_properties: int | None = None
    for source in sources:
        properties = source.get("properties")
        if isinstance(properties, dict):
            for name, subschema in properties.items():
                if isinstance(name, str):
                    property_schemas.setdefault(name, []).append(subschema)
        source_required = source.get("required")
        if isinstance(source_required, list):
            required.update(name for name in source_required if isinstance(name, str))

        minimum = _nonnegative_int(source.get("minProperties"))
        if minimum is not None:
            min_properties = max(min_properties, minimum)
        maximum = _nonnegative_int(source.get("maxProperties"))
        if maximum is not None:
            max_properties = (
                maximum if max_properties is None else min(max_properties, maximum)
            )

    normalized: dict[str, Any] = {
        "type": "object",
        "properties": {
            name: _combine_schema_obligations(obligations)
            for name, obligations in sorted(property_schemas.items())
        },
        "additionalProperties": unevaluated,
    }
    if required:
        normalized["required"] = sorted(required)
    if min_properties:
        normalized["minProperties"] = min_properties
    if max_properties is not None:
        normalized["maxProperties"] = max_properties
    return normalized


def _normalize_simple_unevaluated_items(schema: dict[str, Any]) -> Any | None:
    unevaluated = schema.get("unevaluatedItems")
    if not isinstance(unevaluated, bool | dict):
        return None
    if not _schema_keys_are_allowed(schema, _SIMPLE_UNEVALUATED_ARRAY_KEYS):
        return None

    sources = _simple_all_of_sources(schema, _SIMPLE_UNEVALUATED_ARRAY_CHILD_KEYS)
    if sources is None or any(_array_type_is_not_exact(source) for source in sources):
        return None

    prefix_obligations: list[list[Any]] = []
    min_items = 0
    max_items: int | None = None
    for source in sources:
        prefix_items = source.get("prefixItems")
        if isinstance(prefix_items, list):
            while len(prefix_obligations) < len(prefix_items):
                prefix_obligations.append([])
            for index, subschema in enumerate(prefix_items):
                prefix_obligations[index].append(subschema)

        minimum = _nonnegative_int(source.get("minItems"))
        if minimum is not None:
            min_items = max(min_items, minimum)
        maximum = _nonnegative_int(source.get("maxItems"))
        if maximum is not None:
            max_items = maximum if max_items is None else min(max_items, maximum)

    if unevaluated is False:
        closed_length = len(prefix_obligations)
        max_items = (
            closed_length if max_items is None else min(max_items, closed_length)
        )
    if max_items is not None and min_items > max_items:
        return False

    normalized: dict[str, Any] = {
        "type": "array",
        "prefixItems": [
            _combine_schema_obligations(obligations)
            for obligations in prefix_obligations
        ],
        "items": unevaluated,
    }
    if min_items:
        normalized["minItems"] = min_items
    if max_items is not None:
        normalized["maxItems"] = max_items
    return normalized


def _simple_all_of_sources(
    schema: dict[str, Any],
    child_allowed_keys: frozenset[str],
) -> tuple[dict[str, Any], ...] | None:
    sources = [schema]
    all_of = schema.get("allOf")
    if all_of is not None:
        if not isinstance(all_of, list):
            return None
        for child in all_of:
            if not isinstance(child, dict):
                return None
            if not _schema_keys_are_allowed(child, child_allowed_keys):
                return None
            sources.append(child)
    return tuple(sources)


def _schema_keys_are_allowed(
    schema: dict[str, Any], semantic_keys: frozenset[str]
) -> bool:
    return all(key in semantic_keys or key in _IGNORED_PROOF_KEYS for key in schema)


def _object_type_is_not_exact(schema: dict[str, Any]) -> bool:
    return schema.get("type") not in (None, "object")


def _array_type_is_not_exact(schema: dict[str, Any]) -> bool:
    return schema.get("type") not in (None, "array")


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _combine_schema_obligations(obligations: list[Any]) -> Any:
    if not obligations:
        return True
    if len(obligations) == 1:
        return obligations[0]
    return {"allOf": obligations}
