"""
Schema-level predicates and routing heuristics for the proof kernel.
"""

from __future__ import annotations

from typing import Any

from subschema.dialects import Dialect
from subschema.kernel.normalization import (
    SCHEMA_ARRAY_KEYWORDS,
    SCHEMA_MAP_KEYWORDS,
    SCHEMA_VALUE_KEYWORDS,
)
from subschema.kernel.values import stable_key

HARD_KEYWORDS = {
    "$dynamicRef",
    "$recursiveRef",
    "unevaluatedItems",
    "unevaluatedProperties",
}

IGNORED_SCHEMA_METADATA_KEYS = frozenset(
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
        "documentation_url",
        "examples",
        "format",
        "id",
        "exclusiveMaximumForOptimizer",
        "exclusiveMinimumForOptimizer",
        "forOptimizer",
        "maximumForOptimizer",
        "minimumForOptimizer",
        "readOnly",
        "title",
        "value",
        "writeOnly",
    }
)


def schema_is_false(schema: Any) -> bool:
    return schema is False or schema == {"not": {}}


def empty_schema_for_dialect(dialect: Dialect) -> Any:
    if dialect == Dialect.DRAFT4:
        return {"not": {}}
    return False


def schema_is_true(schema: Any) -> bool:
    return schema is True or schema == {}


def schemas_equal(lhs: Any, rhs: Any) -> bool:
    return stable_key(lhs) == stable_key(rhs)


def contains_reference_keyword(schema: Any, keywords: set[str]) -> bool:
    return _contains_reference_keyword(schema, keywords)


def _contains_reference_keyword(schema: Any, keywords: set[str]) -> bool:
    if isinstance(schema, list):
        return any(_contains_reference_keyword(item, keywords) for item in schema)
    if not isinstance(schema, dict):
        return False
    if any(keyword in schema for keyword in keywords):
        return True
    for key, value in schema.items():
        if key in SCHEMA_VALUE_KEYWORDS:
            if _contains_reference_keyword(value, keywords):
                return True
        elif key in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
            if any(_contains_reference_keyword(item, keywords) for item in value):
                return True
        elif key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            if any(
                _contains_reference_keyword(item, keywords) for item in value.values()
            ):
                return True
    return False


def should_use_ir_engine(*schemas: Any) -> bool:
    return any(schema_needs_ir_engine(schema) for schema in schemas)


def should_prefer_ir_tactic(*schemas: Any) -> bool:
    return any(schema_requires_ir_first(schema) for schema in schemas)


def schema_needs_ir_engine(schema: Any) -> bool:
    if isinstance(schema, bool):
        return True
    if isinstance(schema, list):
        return any(schema_needs_ir_engine(item) for item in schema)
    if not isinstance(schema, dict):
        return False

    if HARD_KEYWORDS.intersection(schema):
        return True
    if has_complex_finite_value(schema):
        return True
    if has_negated_container_schema(schema):
        return True

    for key, value in schema.items():
        if key in SCHEMA_VALUE_KEYWORDS and schema_needs_ir_engine(value):
            return True
        if key in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
            if any(schema_needs_ir_engine(item) for item in value):
                return True
        if key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            if any(schema_needs_ir_engine(item) for item in value.values()):
                return True
    return False


def schema_requires_ir_first(schema: Any) -> bool:
    if isinstance(schema, bool):
        return False
    if isinstance(schema, list):
        return any(schema_requires_ir_first(item) for item in schema)
    if not isinstance(schema, dict):
        return False

    if HARD_KEYWORDS.intersection(schema):
        return True
    if has_complex_finite_value(schema):
        return True
    if has_negated_container_schema(schema):
        return True

    for key, value in schema.items():
        if key in SCHEMA_VALUE_KEYWORDS and schema_requires_ir_first(value):
            return True
        if key in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
            if any(schema_requires_ir_first(item) for item in value):
                return True
        if key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            if any(schema_requires_ir_first(item) for item in value.values()):
                return True
    return False


def has_complex_finite_value(schema: dict[str, Any]) -> bool:
    values = []
    if "const" in schema:
        values.append(schema["const"])
    values.extend(schema.get("enum", []))
    return any(isinstance(value, list | dict) for value in values)


def has_negated_container_schema(schema: dict[str, Any]) -> bool:
    negated = schema.get("not")
    if not isinstance(negated, dict):
        return False
    schema_type = negated.get("type")
    return schema_type in {"array", "object"} or any(
        keyword in negated
        for keyword in {
            "items",
            "prefixItems",
            "properties",
            "required",
            "additionalProperties",
        }
    )


def is_pure_schema_array_applicator(schema: Any, keyword: str) -> bool:
    if not isinstance(schema, dict):
        return False
    saw_keyword = False
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key != keyword:
            return False
        if not isinstance(value, list):
            return False
        saw_keyword = True
    return saw_keyword


def is_pure_schema_value_applicator(schema: Any, keyword: str) -> bool:
    if not isinstance(schema, dict):
        return False
    saw_keyword = False
    for key in schema:
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key != keyword:
            return False
        saw_keyword = True
    return saw_keyword
