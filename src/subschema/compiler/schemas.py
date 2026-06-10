"""
Raw JSON Schema syntax helpers owned by the compiler.
"""

from __future__ import annotations

from typing import Any

from subschema.compiler.normalization import (
    SCHEMA_ARRAY_KEYWORDS,
    SCHEMA_MAP_KEYWORDS,
    SCHEMA_VALUE_KEYWORDS,
)
from subschema.dialects import Dialect
from subschema.values import stable_key

DEDICATED_IR_KEYWORDS = {
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


def schema_array_keyword_value(schema: Any, keyword: str) -> list[Any] | None:
    if not isinstance(schema, dict):
        return None
    value = schema.get(keyword)
    return value if isinstance(value, list) else None


def schema_has_keyword(schema: Any, keyword: str) -> bool:
    return isinstance(schema, dict) and keyword in schema


def schema_keyword_value(schema: Any, keyword: str, default: Any = None) -> Any:
    if not isinstance(schema, dict):
        return default
    return schema.get(keyword, default)


def schema_mapping_keyword_value(schema: Any, keyword: str) -> dict[Any, Any] | None:
    if not isinstance(schema, dict):
        return None
    value = schema.get(keyword)
    return value if isinstance(value, dict) else None


def schema_semantic_key_set(schema: Any) -> frozenset[str]:
    if not isinstance(schema, dict):
        return frozenset()
    return frozenset(key for key in schema if key not in IGNORED_SCHEMA_METADATA_KEYS)


def schema_without_keyword(schema: Any, keyword: str) -> Any | None:
    return schema_without_keywords(schema, {keyword})


def schema_without_keywords(schema: Any, keywords: set[str]) -> Any | None:
    if not isinstance(schema, dict):
        return None
    base = {key: value for key, value in schema.items() if key not in keywords}
    return base if schema_semantic_key_set(base) else True


def transparent_schema_target(schema: Any) -> Any | None:
    if not isinstance(schema, dict):
        return None
    semantic_keys = _semantic_keys(schema)
    if semantic_keys == ("not",):
        inner = pure_not_target(schema)
        if not isinstance(inner, dict) or _semantic_keys(inner) != ("not",):
            return None
        target = pure_not_target(inner)
        return _transparent_target_if_supported(target)
    if len(semantic_keys) != 1 or semantic_keys[0] not in {"allOf", "anyOf", "oneOf"}:
        return None
    value = schema[semantic_keys[0]]
    if not isinstance(value, list) or len(value) != 1:
        return None
    return _transparent_target_if_supported(value[0])


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


def _transparent_target_if_supported(target: Any) -> Any | None:
    if not isinstance(target, bool | dict):
        return None
    if contains_reference_keyword(target, {"$ref", "$dynamicRef", "$recursiveRef"}):
        return None
    return target


def pure_not_target(schema: Any) -> Any | None:
    if not isinstance(schema, dict):
        return None
    if _semantic_keys(schema) != ("not",):
        return None
    return schema["not"]


def _semantic_keys(schema: dict[str, Any]) -> tuple[str, ...]:
    return tuple(key for key in schema if key not in IGNORED_SCHEMA_METADATA_KEYS)


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
