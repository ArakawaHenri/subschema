"""
Stable JSON value helpers shared by proof-kernel search and projection.
"""

from __future__ import annotations

from typing import Any

from subschema.kernel.json_data import strict_json_dumps


def dedupe(values: list[Any] | tuple[Any, ...]) -> list[Any]:
    seen = set()
    deduped = []
    for value in values:
        key = json_semantic_key(value)
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    return deduped


def dependency_names(schema: dict[str, Any]) -> list[str]:
    names = []
    for key in ("dependentRequired", "dependentSchemas", "dependencies"):
        value = schema.get(key)
        if isinstance(value, dict):
            names.extend(str(name) for name in value)
            for dependency in value.values():
                if isinstance(dependency, list):
                    names.extend(str(name) for name in dependency)
    return names


def stable_key(value: Any) -> str:
    return strict_json_dumps(value, sort_keys=True, separators=(",", ":"))


def json_semantic_key(value: Any) -> str:
    return stable_key(normalize_json_number_value(value))


def json_values_equal(lhs: Any, rhs: Any) -> bool:
    return json_semantic_key(lhs) == json_semantic_key(rhs)


def normalize_json_number_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: normalize_json_number_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json_number_value(item) for item in value]
    return value
