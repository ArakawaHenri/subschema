"""
Finite enum/const schema reasoning used by proof and projection.
"""

from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from itertools import product
from typing import Any, cast

from subschema.dialects import (
    Dialect,
    resolve_dialect,
    strip_inactive_keywords_for_dialect,
)
from subschema.kernel.json_data import strict_json_loads
from subschema.kernel.references import ResourceGraph
from subschema.kernel.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
    schema_is_true,
)
from subschema.kernel.validation import validation_backend_for
from subschema.kernel.values import dedupe, stable_key

_MAX_NUMERIC_FINITE_VALUES = 64
_MAX_STRING_FINITE_VALUES = 64
_MAX_ARRAY_FINITE_VALUES = 64
_MAX_ARRAY_FINITE_MATERIALIZED_LENGTH = 64
_MAX_OBJECT_FINITE_VALUES = 64
_FINITE_VALUES_CACHE_SIZE = 4096


def finite_values_for_schema(
    schema: Any, graph: ResourceGraph | None = None, depth: int = 0
) -> list[Any] | None:
    if depth > 8:
        return None
    if schema is False:
        return []
    if schema is True or not isinstance(schema, dict):
        return None
    if graph is not None:
        schema = strip_inactive_keywords_for_dialect(schema, graph.dialect)
    cache_key = _cacheable_finite_schema_key(schema, graph)
    if cache_key is not None:
        schema_key, dialect, use_graph = cache_key
        cached = _finite_values_for_schema_cached(schema_key, dialect, use_graph, depth)
        return None if cached is None else list(cached)
    return _finite_values_for_schema_uncached(schema, graph, depth)


@lru_cache(maxsize=_FINITE_VALUES_CACHE_SIZE)
def _finite_values_for_schema_cached(
    schema_key: str,
    dialect: Dialect,
    use_graph: bool,
    depth: int,
) -> tuple[Any, ...] | None:
    schema = strict_json_loads(schema_key)
    graph = ResourceGraph.build(schema, dialect=dialect) if use_graph else None
    values = _finite_values_for_schema_uncached(schema, graph, depth)
    return None if values is None else tuple(values)


def _cacheable_finite_schema_key(
    schema: Any, graph: ResourceGraph | None
) -> tuple[str, Dialect, bool] | None:
    if contains_reference_keyword(schema, {"$ref", "$dynamicRef", "$recursiveRef"}):
        return None
    try:
        schema_key = stable_key(schema)
    except ValueError:
        return None
    dialect = graph.dialect if graph is not None else resolve_dialect(schema)
    return schema_key, dialect, graph is not None


def _finite_values_for_schema_uncached(
    schema: Any, graph: ResourceGraph | None = None, depth: int = 0
) -> list[Any] | None:
    if depth > 8:
        return None
    if schema is False:
        return []
    if schema is True:
        return None
    if not isinstance(schema, dict):
        return None

    schema = resolve_schema_reference(schema, graph) or schema

    double_negated = _double_negated_schema(schema)
    if double_negated is not None:
        return finite_values_for_schema(double_negated, graph, depth + 1)
    if _schema_is_boolean_empty(schema):
        return []

    if "const" in schema:
        return [schema["const"]]
    if "enum" in schema:
        return dedupe(list(schema["enum"]))
    finite_type_values = _finite_values_for_type_keyword(schema.get("type"))
    if finite_type_values is not None:
        return finite_type_values
    numeric_singletons = _finite_numeric_values_for_schema(schema, graph)
    if numeric_singletons is not None:
        return numeric_singletons
    string_values = _finite_string_values_for_schema(schema)
    if string_values is not None:
        return string_values
    if _array_schema_has_uninhabited_required_slot(schema, graph, depth):
        return []
    array_values = _finite_array_values_for_schema(schema, graph, depth)
    if array_values is not None:
        return array_values
    if _object_schema_has_uninhabited_required_property(schema, graph, depth):
        return []
    if _object_schema_has_empty_property_name_keyspace(schema, graph, depth):
        return []
    object_values = _finite_object_values_for_schema(schema, graph, depth)
    if object_values is not None:
        return object_values

    if "allOf" in schema:
        explicit_values = []
        for subschema in schema["allOf"]:
            branch = finite_values_for_schema(subschema, graph, depth + 1)
            if branch == []:
                return []
            if branch is not None:
                explicit_values.extend(branch)
        if explicit_values:
            return _filter_valid_explicit_finite_values(
                schema, graph, explicit_values
            )
        return None

    if "anyOf" in schema:
        values = []
        for subschema in schema["anyOf"]:
            branch = finite_values_for_schema(subschema, graph, depth + 1)
            if branch is None:
                return None
            values.extend(branch)
        return _filter_valid_explicit_finite_values(schema, graph, values)

    if "oneOf" in schema:
        branch_values = []
        for subschema in schema["oneOf"]:
            branch = finite_values_for_schema(subschema, graph, depth + 1)
            if branch is None:
                return None
            branch_values.extend(branch)
        return _filter_valid_explicit_finite_values(schema, graph, branch_values)
    return None


def _filter_valid_explicit_finite_values(
    schema: dict[str, Any],
    graph: ResourceGraph | None,
    values: list[Any],
) -> list[Any] | None:
    dialect = graph.dialect if graph is not None else resolve_dialect(schema)
    backend = validation_backend_for(dialect)
    try:
        return dedupe([value for value in values if backend.is_valid(schema, value)])
    except Exception:
        return None


def _finite_values_for_type_keyword(type_keyword: Any) -> list[Any] | None:
    if isinstance(type_keyword, str):
        atoms = {type_keyword}
    elif isinstance(type_keyword, list) and all(
        isinstance(item, str) for item in type_keyword
    ):
        atoms = set(type_keyword)
    else:
        return None
    if not atoms <= {"boolean", "null"}:
        return None
    values: list[Any] = []
    if "boolean" in atoms:
        values.extend((False, True))
    if "null" in atoms:
        values.append(None)
    return values


def _finite_numeric_values_for_schema(
    schema: dict[str, Any], graph: ResourceGraph | None
) -> list[Any] | None:
    from subschema.kernel.domains.numbers import numeric_shape_for_schema

    dialect = graph.dialect if graph is not None else resolve_dialect(schema)
    shape = numeric_shape_for_schema(schema, dialect)
    if shape is None or shape.accepts_non_numeric:
        return None

    values: list[Fraction] = []
    for atom in shape.normalized_atoms():
        atom_values = _numeric_atom_finite_values(
            atom,
            max_values=_MAX_NUMERIC_FINITE_VALUES - len(values),
        )
        if atom_values is None:
            return None
        values.extend(atom_values)
        if len(set(values)) > _MAX_NUMERIC_FINITE_VALUES:
            return None
    return dedupe([_json_number(value) for value in values])


def _finite_string_values_for_schema(schema: dict[str, Any]) -> list[str] | None:
    from subschema.kernel.domains.strings import string_language_shape_for_schema

    if not _is_string_only_schema(schema):
        return None
    if not _string_schema_has_finite_length_horizon(schema):
        return None
    shape = string_language_shape_for_schema(schema)
    if shape is None or shape.accepts_non_string:
        return None
    values = shape.pattern.finite_strings(max_values=_MAX_STRING_FINITE_VALUES)
    return None if values is None else list(values)


def _is_string_only_schema(schema: dict[str, Any]) -> bool:
    type_keyword = schema.get("type")
    if type_keyword == "string":
        return True
    return isinstance(type_keyword, list) and set(type_keyword) == {"string"}


def _string_schema_has_finite_length_horizon(schema: dict[str, Any]) -> bool:
    upper = schema.get("maxLength")
    if isinstance(upper, int) and not isinstance(upper, bool):
        return True
    return _is_small_anchored_finite_pattern(schema.get("pattern"))


def _is_small_anchored_finite_pattern(pattern: Any) -> bool:
    if (
        not isinstance(pattern, str)
        or not pattern.startswith("^")
        or not pattern.endswith("$")
    ):
        return False
    body = pattern[1:-1]
    escaped = False
    in_class = False
    for char in body:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "[":
            if in_class:
                return False
            in_class = True
            continue
        if char == "]":
            if not in_class:
                return False
            in_class = False
            continue
        if char in "*+?{|}" and not in_class:
            return False
    return not escaped and not in_class


def _finite_array_values_for_schema(
    schema: dict[str, Any], graph: ResourceGraph | None, depth: int
) -> list[Any] | None:
    if not _is_array_only_schema(schema) or not _is_finite_array_fragment_schema(
        schema
    ):
        return None

    dialect = graph.dialect if graph is not None else resolve_dialect(schema)
    prefix = _array_prefix_schemas(schema, dialect)
    tail = _array_tail_schema(schema, dialect)
    implicit_max = len(prefix) if tail is False else None

    lower = schema.get("minItems", 0)
    upper = schema.get("maxItems", implicit_max)
    if not isinstance(lower, int) or isinstance(lower, bool):
        return None
    if upper is None or not isinstance(upper, int) or isinstance(upper, bool):
        return None
    if implicit_max is not None:
        upper = min(upper, implicit_max)
    if lower > upper:
        return []
    if upper > _MAX_ARRAY_FINITE_MATERIALIZED_LENGTH:
        return None

    arrays: list[list[Any]] = []
    for length in range(lower, upper + 1):
        choices = []
        for index in range(length):
            slot_schema = _array_slot_schema(prefix, tail, index)
            slot_values = finite_values_for_schema(slot_schema, graph, depth + 1)
            if slot_values is None:
                return None
            choices.append(slot_values)
        if not choices:
            arrays.append([])
            continue
        for values in product(*choices):
            arrays.append(list(values))
            if len(arrays) > _MAX_ARRAY_FINITE_VALUES:
                return None
    return dedupe(arrays)


def _array_schema_has_uninhabited_required_slot(
    schema: dict[str, Any],
    graph: ResourceGraph | None,
    depth: int,
) -> bool:
    if not _is_array_only_schema(schema) or not _is_finite_array_fragment_schema(
        schema
    ):
        return False

    lower = schema.get("minItems", 0)
    if not isinstance(lower, int) or isinstance(lower, bool) or lower <= 0:
        return False

    dialect = graph.dialect if graph is not None else resolve_dialect(schema)
    prefix = _array_prefix_schemas(schema, dialect)
    tail = _array_tail_schema(schema, dialect)
    scan_prefix_slots = min(lower, len(prefix), _MAX_ARRAY_FINITE_MATERIALIZED_LENGTH)
    for index in range(scan_prefix_slots):
        slot_schema = _array_slot_schema(prefix, tail, index)
        values = finite_values_for_schema(slot_schema, graph, depth + 1)
        if values == []:
            return True
    if lower > len(prefix):
        values = finite_values_for_schema(tail, graph, depth + 1)
        if values == []:
            return True
    return False


def _finite_object_values_for_schema(
    schema: dict[str, Any], graph: ResourceGraph | None, depth: int
) -> list[Any] | None:
    if not _is_object_only_schema(schema) or not _is_finite_object_fragment_schema(
        schema
    ):
        return None

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return None
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(
        isinstance(name, str) for name in required
    ):
        return None
    required_names = frozenset(required)
    if not required_names <= properties.keys():
        return []

    lower = schema.get("minProperties", 0)
    upper = schema.get("maxProperties", len(properties))
    if not isinstance(lower, int) or isinstance(lower, bool):
        return None
    if not isinstance(upper, int) or isinstance(upper, bool):
        return None

    objects: list[dict[str, Any]] = [{}]
    for name, subschema in sorted(properties.items()):
        present_values = finite_values_for_schema(subschema, graph, depth + 1)
        if present_values is None:
            if subschema is False and name not in required_names:
                continue
            return None
        if not present_values and name in required_names:
            return []

        next_objects = []
        if name not in required_names:
            next_objects.extend(objects)
        for base in objects:
            for value in present_values:
                next_objects.append({**base, name: value})
                if len(next_objects) > _MAX_OBJECT_FINITE_VALUES:
                    return None
        objects = next_objects

    return dedupe([value for value in objects if lower <= len(value) <= upper])


def _object_schema_has_uninhabited_required_property(
    schema: dict[str, Any],
    graph: ResourceGraph | None,
    depth: int,
) -> bool:
    if not _is_object_only_schema(schema):
        return False

    required = schema.get("required", [])
    if not isinstance(required, list) or not all(
        isinstance(name, str) for name in required
    ):
        return False
    if not required:
        return False

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    pattern_properties = schema.get("patternProperties", {})
    if not isinstance(pattern_properties, dict):
        pattern_properties = {}

    for name in required:
        if _object_property_name_is_rejected(schema, graph, name):
            return True

        matched_pattern = False
        if name in properties and _schema_is_known_empty(
            properties[name], graph, depth + 1
        ):
            return True

        for pattern_text, subschema in pattern_properties.items():
            if not isinstance(pattern_text, str):
                continue
            pattern = _regex_language_for_json_pattern(pattern_text)
            if pattern is None or not pattern.matches(name):
                continue
            matched_pattern = True
            if _schema_is_known_empty(subschema, graph, depth + 1):
                return True

        if name not in properties and not matched_pattern:
            additional = schema.get("additionalProperties", True)
            if _schema_is_known_empty(additional, graph, depth + 1):
                return True
    return False


def _object_schema_has_empty_property_name_keyspace(
    schema: dict[str, Any],
    graph: ResourceGraph | None,
    depth: int,
) -> bool:
    if not _is_object_only_schema(schema):
        return False
    lower = schema.get("minProperties", 0)
    if not isinstance(lower, int) or isinstance(lower, bool) or lower <= 0:
        return False
    return _property_names_schema_rejects_all_strings(
        schema.get("propertyNames", True), graph, depth + 1
    )


def _property_names_schema_rejects_all_strings(
    schema: Any,
    graph: ResourceGraph | None,
    depth: int,
) -> bool:
    if contains_reference_keyword(schema, {"$ref", "$dynamicRef", "$recursiveRef"}):
        return False
    finite = finite_values_for_schema(schema, graph, depth)
    if finite is not None:
        return not any(isinstance(value, str) for value in finite)

    from subschema.kernel.domains.strings import string_language_shape_for_schema

    shape = string_language_shape_for_schema(schema)
    return shape is not None and shape.pattern.is_empty()


def _object_property_name_is_rejected(
    schema: dict[str, Any], graph: ResourceGraph | None, name: str
) -> bool:
    property_names = schema.get("propertyNames", True)
    if property_names is True:
        return False
    if property_names is False:
        return True
    dialect = graph.dialect if graph is not None else resolve_dialect(schema)
    try:
        return not validation_backend_for(dialect).is_valid(property_names, name)
    except Exception:
        return False


def _schema_is_known_empty(
    schema: Any, graph: ResourceGraph | None, depth: int
) -> bool:
    if schema is False:
        return True
    return finite_values_for_schema(schema, graph, depth) == []


def _regex_language_for_json_pattern(pattern: str) -> Any | None:
    from subschema.kernel.regex import RegexLanguage

    language = RegexLanguage.from_json_regex(pattern)
    return language if isinstance(language, RegexLanguage) else None


def _is_object_only_schema(schema: dict[str, Any]) -> bool:
    type_keyword = schema.get("type")
    if type_keyword == "object":
        return True
    return isinstance(type_keyword, list) and set(type_keyword) == {"object"}


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


def _is_array_only_schema(schema: dict[str, Any]) -> bool:
    type_keyword = schema.get("type")
    if type_keyword == "array":
        return True
    return isinstance(type_keyword, list) and set(type_keyword) == {"array"}


def _is_finite_array_fragment_schema(schema: dict[str, Any]) -> bool:
    allowed = {
        "additionalItems",
        "items",
        "maxItems",
        "minItems",
        "prefixItems",
        "type",
    }
    return all(key in allowed or key in IGNORED_SCHEMA_METADATA_KEYS for key in schema)


def _array_prefix_schemas(schema: dict[str, Any], dialect: Dialect) -> tuple[Any, ...]:
    if dialect is Dialect.DRAFT202012:
        prefix = schema.get("prefixItems", ())
        return tuple(prefix) if isinstance(prefix, list) else ()
    items = schema.get("items", ())
    return tuple(items) if isinstance(items, list) else ()


def _array_tail_schema(schema: dict[str, Any], dialect: Dialect) -> Any:
    if dialect is Dialect.DRAFT202012:
        return schema.get("items", True)
    items = schema.get("items", True)
    if isinstance(items, list):
        return schema.get("additionalItems", True)
    return items


def _array_slot_schema(prefix: tuple[Any, ...], tail: Any, index: int) -> Any:
    if index < len(prefix):
        return prefix[index]
    return tail


def _numeric_atom_finite_values(
    atom: Any, *, max_values: int
) -> tuple[Fraction, ...] | None:
    if max_values < 1:
        return None
    normalized = atom.normalized()
    if normalized.is_empty():
        return ()
    finite_values = normalized.finite_values(max_values=max_values)
    if finite_values is not None:
        return cast(tuple[Fraction, ...], finite_values)
    if (
        normalized.lower is not None
        and normalized.upper is not None
        and normalized.lower == normalized.upper
        and normalized.lower_inclusive
        and normalized.upper_inclusive
        and normalized.contains(normalized.lower)
    ):
        return (normalized.lower,)
    return None


def _json_number(value: Fraction) -> int | float:
    if value.denominator == 1:
        return int(value)
    return float(value)


def inhabited_finite_values_for_schema(
    schema: Any, dialect: Dialect
) -> list[Any] | None:
    values = finite_values_for_schema(
        schema, ResourceGraph.build(schema, dialect=dialect)
    )
    if values is None:
        return None
    backend = validation_backend_for(dialect)
    return [value for value in values if backend.is_valid(schema, value)]


def schema_is_empty_finite(schema: Any, dialect: Dialect) -> bool:
    values = inhabited_finite_values_for_schema(schema, dialect)
    return values == []


def finite_complement_excluded_values(
    schema: Any, dialect: Dialect
) -> tuple[Any, ...] | None:
    if not isinstance(schema, dict):
        return None
    if _semantic_keys(schema) != ("not",):
        return None
    values = inhabited_finite_values_for_schema(schema["not"], dialect)
    return None if values is None else tuple(values)


def _double_negated_schema(schema: dict[str, Any]) -> Any | None:
    if _semantic_keys(schema) != ("not",):
        return None
    inner = schema["not"]
    if not isinstance(inner, dict) or _semantic_keys(inner) != ("not",):
        return None
    return inner["not"]


def _schema_is_boolean_empty(schema: dict[str, Any]) -> bool:
    return _semantic_keys(schema) == ("not",) and schema_is_true(schema["not"])


def _semantic_keys(schema: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        key
        for key in schema
        if key not in {"$comment", "$id", "$schema", "description", "title"}
    )


def finite_values_projection(values: list[Any]) -> Any:
    values = dedupe(values)
    if not values:
        return False
    if len(values) == 1:
        return {"const": values[0]}
    return {"enum": values}


def resolve_schema_reference(
    schema: dict[str, Any], graph: ResourceGraph | None
) -> Any | None:
    if graph is None:
        return None
    for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
        ref = schema.get(keyword)
        if isinstance(ref, str):
            return graph.resolve_ref(ref)
    return None
