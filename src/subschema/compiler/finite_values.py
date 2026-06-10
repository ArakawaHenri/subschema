"""
Raw-schema finite-value extraction for the IR compiler boundary.
"""

from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from itertools import product
from typing import Any, cast

from subschema.compiler.domains.arrays import array_finite_fragment_shape_for_schema
from subschema.compiler.domains.numbers import numeric_shape_for_schema
from subschema.compiler.domains.object_facts import (
    object_additional_properties_schema_for_schema,
    object_finite_value_shape_for_schema,
    object_is_exact_object_only_schema,
    object_pattern_property_schemas_for_schema,
    object_property_count_bounds_for_schema,
    object_property_names_schema_for_schema,
    object_property_schemas_for_schema,
    object_required_names_for_schema,
)
from subschema.compiler.domains.strings import (
    string_language_shape_for_schema,
    string_schema_has_finite_language_for_values,
)
from subschema.compiler.domains.types import finite_values_for_type_schema
from subschema.compiler.literals import explicit_finite_values_for_schema
from subschema.compiler.resources import ResourceGraph, resolve_schema_reference
from subschema.compiler.schemas import (
    contains_reference_keyword,
    pure_not_target,
    schema_array_keyword_value,
    schema_is_true,
)
from subschema.dialects import (
    Dialect,
    resolve_dialect,
    strip_inactive_keywords_for_dialect,
)
from subschema.json_data import strict_json_loads
from subschema.regex import RegexLanguage
from subschema.values import dedupe, json_semantic_key, stable_key

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

    resolved = resolve_schema_reference(schema, graph)
    if resolved is not None:
        schema = resolved
    if schema is False:
        return []
    if schema is True:
        return None
    if not isinstance(schema, dict):
        return None

    double_negated = _double_negated_schema(schema)
    if double_negated is not None:
        return finite_values_for_schema(double_negated, graph, depth + 1)
    if _schema_is_boolean_empty(schema):
        return []

    explicit_values = explicit_finite_values_for_schema(schema)
    if explicit_values is not None:
        return explicit_values
    finite_type_values = finite_values_for_type_schema(schema)
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

    all_of = schema_array_keyword_value(schema, "allOf")
    if all_of is not None:
        finite_branches = []
        for subschema in all_of:
            branch = finite_values_for_schema(subschema, graph, depth + 1)
            if branch == []:
                return []
            if branch is not None:
                finite_branches.append(branch)
        return _all_of_finite_candidates(finite_branches)

    any_of = schema_array_keyword_value(schema, "anyOf")
    if any_of is not None:
        values = []
        for subschema in any_of:
            branch = finite_values_for_schema(subschema, graph, depth + 1)
            if branch is None:
                return None
            values.extend(branch)
        return dedupe(values)

    one_of = schema_array_keyword_value(schema, "oneOf")
    if one_of is not None:
        branch_values = []
        for subschema in one_of:
            branch = finite_values_for_schema(subschema, graph, depth + 1)
            if branch is None:
                return None
            branch_values.extend(branch)
        return dedupe(branch_values)
    return None


def _all_of_finite_candidates(branches: list[list[Any]]) -> list[Any] | None:
    if not branches:
        return None
    values = branches[0]
    for branch in branches[1:]:
        branch_keys = {json_semantic_key(value) for value in branch}
        values = [
            value for value in values if json_semantic_key(value) in branch_keys
        ]
    return dedupe(values)


def _finite_numeric_values_for_schema(
    schema: dict[str, Any], graph: ResourceGraph | None
) -> list[Any] | None:
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
    if not string_schema_has_finite_language_for_values(schema):
        return None
    shape = string_language_shape_for_schema(schema)
    if shape is None or shape.accepts_non_string:
        return None
    values = shape.pattern.finite_strings(max_values=_MAX_STRING_FINITE_VALUES)
    return None if values is None else list(values)


def _finite_array_values_for_schema(
    schema: dict[str, Any], graph: ResourceGraph | None, depth: int
) -> list[Any] | None:
    dialect = graph.dialect if graph is not None else resolve_dialect(schema)
    shape = array_finite_fragment_shape_for_schema(schema, dialect)
    if shape is None or shape.upper is None:
        return None
    if shape.lower > shape.upper:
        return []
    if shape.upper > _MAX_ARRAY_FINITE_MATERIALIZED_LENGTH:
        return None

    arrays: list[list[Any]] = []
    for length in range(shape.lower, shape.upper + 1):
        choices = []
        for index in range(length):
            slot_schema = shape.slot_schema(index)
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
    dialect = graph.dialect if graph is not None else resolve_dialect(schema)
    shape = array_finite_fragment_shape_for_schema(schema, dialect)
    if shape is None or shape.lower <= 0:
        return False

    scan_prefix_slots = min(
        shape.lower, len(shape.prefix_schemas), _MAX_ARRAY_FINITE_MATERIALIZED_LENGTH
    )
    for index in range(scan_prefix_slots):
        slot_schema = shape.slot_schema(index)
        values = finite_values_for_schema(slot_schema, graph, depth + 1)
        if values == []:
            return True
    if shape.lower > len(shape.prefix_schemas):
        values = finite_values_for_schema(shape.tail_schema, graph, depth + 1)
        if values == []:
            return True
    return False


def _finite_object_values_for_schema(
    schema: dict[str, Any], graph: ResourceGraph | None, depth: int
) -> list[Any] | None:
    shape = object_finite_value_shape_for_schema(schema)
    if shape is None:
        return None

    properties = shape.properties
    required_names = shape.required_names
    if shape.lower > shape.upper:
        return []

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

    return dedupe(
        [value for value in objects if shape.lower <= len(value) <= shape.upper]
    )


def _object_schema_has_uninhabited_required_property(
    schema: dict[str, Any],
    graph: ResourceGraph | None,
    depth: int,
) -> bool:
    if not object_is_exact_object_only_schema(schema):
        return False

    required = object_required_names_for_schema(schema)
    if not required:
        return False

    properties = object_property_schemas_for_schema(schema)
    pattern_properties = object_pattern_property_schemas_for_schema(schema)

    for name in required:
        if _object_property_name_is_rejected(schema, graph, name):
            return True

        matched_pattern = False
        if name in properties and _schema_is_known_empty(
            properties[name], graph, depth + 1
        ):
            return True

        for pattern_text, subschema in pattern_properties:
            pattern = _regex_language_for_json_pattern(pattern_text)
            if pattern is None or not pattern.matches(name):
                continue
            matched_pattern = True
            if _schema_is_known_empty(subschema, graph, depth + 1):
                return True

        if name not in properties and not matched_pattern:
            additional = object_additional_properties_schema_for_schema(schema)
            if _schema_is_known_empty(additional, graph, depth + 1):
                return True
    return False


def _object_schema_has_empty_property_name_keyspace(
    schema: dict[str, Any],
    graph: ResourceGraph | None,
    depth: int,
) -> bool:
    if not object_is_exact_object_only_schema(schema):
        return False
    bounds = object_property_count_bounds_for_schema(schema)
    if bounds is None:
        return False
    lower, _, _ = bounds
    if lower <= 0:
        return False
    return _property_names_schema_rejects_all_strings(
        object_property_names_schema_for_schema(schema), graph, depth + 1
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

    shape = string_language_shape_for_schema(schema)
    return shape is not None and shape.pattern.is_empty()


def _object_property_name_is_rejected(
    schema: dict[str, Any], graph: ResourceGraph | None, name: str
) -> bool:
    property_names = object_property_names_schema_for_schema(schema)
    if property_names is True:
        return False
    if property_names is False:
        return True
    if contains_reference_keyword(
        property_names, {"$ref", "$dynamicRef", "$recursiveRef"}
    ):
        return False
    shape = string_language_shape_for_schema(property_names)
    if shape is None or not shape.exact:
        return False
    return not shape.pattern.matches(name)


def _schema_is_known_empty(
    schema: Any, graph: ResourceGraph | None, depth: int
) -> bool:
    if schema is False:
        return True
    return finite_values_for_schema(schema, graph, depth) == []


def _regex_language_for_json_pattern(pattern: str) -> Any | None:
    language = RegexLanguage.from_json_regex(pattern)
    return language if isinstance(language, RegexLanguage) else None


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


def _double_negated_schema(schema: dict[str, Any]) -> Any | None:
    inner = pure_not_target(schema)
    if not isinstance(inner, dict):
        return None
    return pure_not_target(inner)


def _schema_is_boolean_empty(schema: dict[str, Any]) -> bool:
    negated = pure_not_target(schema)
    return negated is not None and schema_is_true(negated)
