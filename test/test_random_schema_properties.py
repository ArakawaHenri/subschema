from __future__ import annotations

import json
from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from subschema import (
    Dialect,
    UnsupportedProofError,
    canonicalize_schema,
    is_disjoint,
    is_empty,
    is_subschema,
    join_schemas,
    meet_schemas,
)
from subschema.kernel.validation import validation_backend_for


JSON_VALUES: tuple[Any, ...] = (
    None,
    True,
    False,
    -2,
    -1,
    0,
    1,
    2,
    "",
    "a",
    "b",
    " ",
    [],
    [0],
    ["a"],
    {},
    {"a": 0},
    {"b": "a"},
)
JSON_INSTANCES: tuple[Any, ...] = (
    *JSON_VALUES,
    [0, "a"],
    {"a": 0, "b": "a"},
    {"kind": "cat", "name": "a"},
    {"kind": "dog", "age": 1},
)
PROPERTY_NAMES = ("a", "b", "kind", "name", "age")
TYPE_NAMES = ("null", "boolean", "integer", "number", "string", "array", "object")
SAFE_PATTERNS = ("", "^a$", "^[ab]{0,2}$", r"[\s\S]", r"^\s?$", r"^\S{0,2}$")


def _stable_json_key(value: Any) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


@st.composite
def random_schema(draw: st.DrawFn) -> Any:
    return draw(
        st.recursive(
            _random_leaf_schema(),
            _random_schema_extension,
            max_leaves=10,
        )
    )


def _random_leaf_schema() -> st.SearchStrategy[Any]:
    return st.one_of(
        st.booleans(),
        _type_schema(),
        _const_schema(),
        _enum_schema(),
        _numeric_schema(),
        _string_schema(),
    )


def _type_schema() -> st.SearchStrategy[dict[str, Any]]:
    single_type = st.sampled_from(TYPE_NAMES).map(lambda name: {"type": name})
    type_array = st.lists(
        st.sampled_from(TYPE_NAMES),
        min_size=1,
        max_size=4,
        unique=True,
    ).map(lambda names: {"type": names})
    return st.one_of(single_type, type_array)


def _const_schema() -> st.SearchStrategy[dict[str, Any]]:
    return st.sampled_from(JSON_VALUES).map(lambda value: {"const": value})


def _enum_schema() -> st.SearchStrategy[dict[str, Any]]:
    return st.lists(
        st.sampled_from(JSON_VALUES),
        min_size=1,
        max_size=4,
        unique_by=_stable_json_key,
    ).map(lambda values: {"enum": values})


@st.composite
def _numeric_schema(draw: st.DrawFn) -> dict[str, Any]:
    lower = draw(st.integers(min_value=-4, max_value=3))
    upper = draw(st.integers(min_value=lower, max_value=4))
    schema: dict[str, Any] = {
        "type": draw(st.sampled_from(("integer", "number"))),
        "minimum": lower,
        "maximum": upper,
    }
    if draw(st.booleans()):
        schema["exclusiveMinimum"] = lower - 1
    if draw(st.booleans()):
        schema["exclusiveMaximum"] = upper + 1
    if draw(st.booleans()):
        schema["multipleOf"] = draw(st.sampled_from((1, 2, 0.5)))
    return schema


@st.composite
def _string_schema(draw: st.DrawFn) -> dict[str, Any]:
    min_length = draw(st.integers(min_value=0, max_value=2))
    max_length = draw(st.integers(min_value=min_length, max_value=4))
    schema: dict[str, Any] = {
        "type": "string",
        "minLength": min_length,
        "maxLength": max_length,
    }
    if draw(st.booleans()):
        schema["pattern"] = draw(st.sampled_from(SAFE_PATTERNS))
    return schema


def _random_schema_extension(
    children: st.SearchStrategy[Any],
) -> st.SearchStrategy[Any]:
    return st.one_of(
        _applicator_schema(children),
        _conditional_schema(children),
        _object_schema(children),
        _array_schema(children),
        _annotation_schema(children),
    )


def _applicator_schema(children: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    all_of = st.lists(children, min_size=1, max_size=3).map(
        lambda schemas: {"allOf": schemas}
    )
    any_of = st.lists(children, min_size=1, max_size=3).map(
        lambda schemas: {"anyOf": schemas}
    )
    one_of = st.lists(children, min_size=1, max_size=3).map(
        lambda schemas: {"oneOf": schemas}
    )
    not_schema = children.map(lambda schema: {"not": schema})
    return st.one_of(all_of, any_of, one_of, not_schema)


@st.composite
def _conditional_schema(draw: st.DrawFn, children: st.SearchStrategy[Any]) -> dict[str, Any]:
    schema: dict[str, Any] = {"if": draw(children)}
    if draw(st.booleans()):
        schema["then"] = draw(children)
    if draw(st.booleans()):
        schema["else"] = draw(children)
    return schema


@st.composite
def _object_schema(draw: st.DrawFn, children: st.SearchStrategy[Any]) -> dict[str, Any]:
    property_names = draw(
        st.lists(st.sampled_from(PROPERTY_NAMES), unique=True, max_size=3)
    )
    properties = {name: draw(children) for name in property_names}
    required_strategy = (
        st.lists(st.sampled_from(property_names), unique=True)
        if property_names
        else st.just([])
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": draw(required_strategy),
    }
    if draw(st.booleans()):
        schema["additionalProperties"] = draw(st.one_of(st.booleans(), children))
    if draw(st.booleans()):
        schema["minProperties"] = draw(st.integers(min_value=0, max_value=2))
    if draw(st.booleans()):
        schema["maxProperties"] = draw(st.integers(min_value=2, max_value=4))
    if draw(st.booleans()):
        schema["propertyNames"] = draw(_string_schema())
    if draw(st.booleans()) and property_names:
        schema["dependentRequired"] = {
            property_names[0]: draw(
                st.lists(st.sampled_from(PROPERTY_NAMES), unique=True, max_size=2)
            )
        }
    if draw(st.booleans()) and property_names:
        schema["dependentSchemas"] = {property_names[0]: draw(children)}
    return schema


@st.composite
def _array_schema(draw: st.DrawFn, children: st.SearchStrategy[Any]) -> dict[str, Any]:
    prefix_items = draw(st.lists(children, min_size=0, max_size=3))
    schema: dict[str, Any] = {"type": "array"}
    if prefix_items:
        schema["prefixItems"] = prefix_items
    if draw(st.booleans()):
        schema["items"] = draw(st.one_of(st.booleans(), children))
    min_items = draw(st.integers(min_value=0, max_value=3))
    max_items = draw(st.integers(min_value=min_items, max_value=4))
    if draw(st.booleans()):
        schema["minItems"] = min_items
    if draw(st.booleans()):
        schema["maxItems"] = max_items
    if draw(st.booleans()):
        schema["uniqueItems"] = True
    if draw(st.booleans()):
        schema["contains"] = draw(children)
        min_contains = draw(st.integers(min_value=0, max_value=2))
        max_contains = draw(st.integers(min_value=min_contains, max_value=3))
        schema["minContains"] = min_contains
        schema["maxContains"] = max_contains
    return schema


@st.composite
def _annotation_schema(draw: st.DrawFn, children: st.SearchStrategy[Any]) -> dict[str, Any]:
    schema = draw(children)
    if not isinstance(schema, dict):
        schema = {"const": schema}
    annotated = dict(schema)
    annotated["title"] = draw(st.sampled_from(("Generated", "Random", "")))
    annotated["description"] = draw(st.sampled_from(("schema", "property test", "")))
    if draw(st.booleans()):
        annotated["default"] = draw(st.sampled_from(JSON_VALUES))
    if draw(st.booleans()):
        annotated["examples"] = draw(
            st.lists(st.sampled_from(JSON_VALUES), max_size=3)
        )
    return annotated


def _small_instance_counterexample(lhs: Any, rhs: Any) -> Any | None:
    backend = validation_backend_for(Dialect.DRAFT202012)
    for instance in JSON_INSTANCES:
        if backend.is_valid(lhs, instance) and not backend.is_valid(rhs, instance):
            return instance
    return None


@given(random_schema())
@settings(max_examples=150, deadline=None)
def test_random_schema_is_valid_and_reflexive_when_provable(schema: Any) -> None:
    canonicalize_schema(schema)

    try:
        assert is_subschema(schema, schema)
    except UnsupportedProofError:
        assume(False)


@given(random_schema(), random_schema())
@settings(max_examples=150, deadline=None)
def test_random_true_subschema_has_no_small_counterexample(lhs: Any, rhs: Any) -> None:
    try:
        result = is_subschema(lhs, rhs)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert _small_instance_counterexample(lhs, rhs) is None


@given(random_schema(), random_schema())
@settings(max_examples=120, deadline=None)
def test_random_disjointness_matches_all_of_emptiness(lhs: Any, rhs: Any) -> None:
    try:
        disjoint = is_disjoint(lhs, rhs)
        empty = is_empty({"allOf": [lhs, rhs]})
    except UnsupportedProofError:
        assume(False)

    assert disjoint == empty


@given(random_schema(), random_schema())
@settings(max_examples=120, deadline=None)
def test_random_meet_join_bounds_when_provable(lhs: Any, rhs: Any) -> None:
    meet = meet_schemas(lhs, rhs)
    join = join_schemas(lhs, rhs)

    try:
        assert is_subschema(meet, lhs)
        assert is_subschema(meet, rhs)
        assert is_subschema(lhs, join)
        assert is_subschema(rhs, join)
    except UnsupportedProofError:
        assume(False)
