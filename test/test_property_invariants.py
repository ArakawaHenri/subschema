from __future__ import annotations

import json
from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from subschema import (
    UnsupportedProofError,
    is_disjoint,
    is_empty,
    is_subschema,
    join_schemas,
    meet_schemas,
)


JSON_EXAMPLES: tuple[Any, ...] = (None, True, False, -1, 0, 1, "", "a", "b")
TYPE_SCHEMAS = (
    {"type": "null"},
    {"type": "boolean"},
    {"type": "integer"},
    {"type": "number"},
    {"type": "string"},
    {"type": "array"},
    {"type": "object"},
)
STRING_PATTERNS = ("", "^a$", "^[ab]{0,2}$", r"[\s\S]")


def stable_json_key(value: Any) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


@st.composite
def simple_schema(draw: st.DrawFn) -> Any:
    return draw(
        st.one_of(
            st.booleans(),
            st.sampled_from(TYPE_SCHEMAS).map(dict),
            _const_schema(),
            _enum_schema(),
            _numeric_schema(),
            _string_schema(),
            _closed_object_schema(),
            _fixed_tuple_schema(),
        )
    )


def _const_schema() -> st.SearchStrategy[dict[str, Any]]:
    return st.sampled_from(JSON_EXAMPLES).map(lambda value: {"const": value})


def _enum_schema() -> st.SearchStrategy[dict[str, Any]]:
    return st.lists(
        st.sampled_from(JSON_EXAMPLES),
        min_size=1,
        max_size=3,
        unique_by=stable_json_key,
    ).map(lambda values: {"enum": values})


@st.composite
def _numeric_schema(draw: st.DrawFn) -> dict[str, Any]:
    lower = draw(st.integers(min_value=-3, max_value=3))
    upper = draw(st.integers(min_value=lower, max_value=4))
    schema: dict[str, Any] = {
        "type": draw(st.sampled_from(("integer", "number"))),
        "minimum": lower,
        "maximum": upper,
    }
    if draw(st.booleans()):
        schema["multipleOf"] = draw(st.sampled_from((1, 2)))
    return schema


@st.composite
def _string_schema(draw: st.DrawFn) -> dict[str, Any]:
    min_length = draw(st.integers(min_value=0, max_value=2))
    max_length = draw(st.integers(min_value=min_length, max_value=3))
    schema: dict[str, Any] = {
        "type": "string",
        "minLength": min_length,
        "maxLength": max_length,
    }
    if draw(st.booleans()):
        schema["pattern"] = draw(st.sampled_from(STRING_PATTERNS))
    return schema


@st.composite
def _closed_object_schema(draw: st.DrawFn) -> dict[str, Any]:
    property_names = draw(
        st.lists(st.sampled_from(("a", "b")), unique=True, max_size=2)
    )
    properties = {
        name: draw(st.sampled_from(TYPE_SCHEMAS).map(dict))
        for name in property_names
    }
    required_strategy = (
        st.lists(st.sampled_from(property_names), unique=True)
        if property_names
        else st.just([])
    )
    required = draw(required_strategy)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


@st.composite
def _fixed_tuple_schema(draw: st.DrawFn) -> dict[str, Any]:
    item_schemas = draw(
        st.lists(st.sampled_from(TYPE_SCHEMAS).map(dict), min_size=0, max_size=3)
    )
    length = len(item_schemas)
    if length == 0:
        return {
            "type": "array",
            "items": False,
            "minItems": 0,
            "maxItems": 0,
        }
    return {
        "type": "array",
        "prefixItems": item_schemas,
        "items": False,
        "minItems": length,
        "maxItems": length,
    }


@given(simple_schema())
@settings(max_examples=100, deadline=None)
def test_schema_reflexivity(schema: Any) -> None:
    assert is_subschema(schema, schema)


@given(simple_schema(), simple_schema())
@settings(max_examples=100, deadline=None)
def test_meet_is_lower_bound(lhs: Any, rhs: Any) -> None:
    meet = meet_schemas(lhs, rhs)

    assert is_subschema(meet, lhs)
    assert is_subschema(meet, rhs)


@given(simple_schema(), simple_schema())
@settings(max_examples=100, deadline=None)
def test_join_is_upper_bound(lhs: Any, rhs: Any) -> None:
    join = join_schemas(lhs, rhs)

    assert is_subschema(lhs, join)
    assert is_subschema(rhs, join)


@given(simple_schema(), simple_schema())
@settings(max_examples=100, deadline=None)
def test_disjointness_matches_all_of_emptiness(lhs: Any, rhs: Any) -> None:
    try:
        disjoint = is_disjoint(lhs, rhs)
        empty = is_empty({"allOf": [lhs, rhs]})
    except UnsupportedProofError:
        assume(False)

    assert disjoint == empty
