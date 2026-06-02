import pytest

from subschema import Dialect, is_disjoint, is_empty, is_subschema
from subschema.exceptions import UnsupportedProofError


def test_numeric_interval_disjointness_is_default_exact():
    assert is_disjoint(
        {"type": "number", "maximum": 1},
        {"type": "number", "minimum": 2},
    )
    assert not is_disjoint(
        {"type": "number", "maximum": 2},
        {"type": "number", "minimum": 1},
    )


def test_object_property_count_disjointness_is_default_exact():
    assert is_disjoint(
        {"type": "object", "maxProperties": 0},
        {"type": "object", "minProperties": 1},
    )
    assert not is_disjoint(
        {"type": "object", "maxProperties": 2},
        {"type": "object", "minProperties": 1},
    )


def test_array_length_disjointness_is_default_exact():
    assert is_disjoint(
        {"type": "array", "maxItems": 0},
        {"type": "array", "minItems": 1},
    )
    assert not is_disjoint(
        {"type": "array", "maxItems": 2},
        {"type": "array", "minItems": 1},
    )


def test_array_item_disjointness_is_default_exact_for_required_positions():
    assert is_disjoint(
        {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        {"type": "array", "items": {"type": "string"}, "minItems": 1},
    )
    assert is_disjoint(
        {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "minItems": 1,
            "items": False,
        },
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "minItems": 1,
            "items": False,
        },
    )


def test_simple_contains_emptiness_is_default_exact():
    empty_contains = {"type": "array", "contains": False, "minContains": 1}

    assert is_empty(empty_contains)
    assert is_subschema(empty_contains, False)
    assert is_empty(
        {
            "type": "array",
            "items": {"type": "string"},
            "contains": {"type": "integer"},
            "minContains": 1,
        }
    )
    assert is_empty(
        {
            "type": "array",
            "items": {"type": "integer"},
            "contains": {"type": "integer"},
            "maxContains": 0,
            "minItems": 1,
        }
    )


def test_right_side_not_uses_low_cost_disjointness():
    assert is_subschema(
        {"type": "number", "maximum": 1},
        {"not": {"type": "number", "minimum": 2}},
    )


@pytest.mark.parametrize(
    ("lhs", "rhs"),
    [
        (
            {
                "type": "object",
                "minProperties": 1,
                "patternProperties": {"^a": {"type": "integer"}},
                "additionalProperties": False,
            },
            {
                "type": "object",
                "minProperties": 1,
                "patternProperties": {"^a": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
        (
            {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"type": "integer"},
            },
            {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"type": "string"},
            },
        ),
    ],
)
def test_open_or_pattern_object_disjointness_stays_unsupported(lhs, rhs):
    with pytest.raises(UnsupportedProofError):
        is_disjoint(lhs, rhs)


def test_ambiguous_array_branch_item_disjointness_stays_unsupported():
    lhs = {
        "type": "array",
        "minItems": 1,
        "anyOf": [
            {"items": {"type": "integer"}},
            {"items": {"type": "string"}},
        ],
    }
    rhs = {"type": "array", "items": {"type": "boolean"}, "minItems": 1}

    with pytest.raises(UnsupportedProofError):
        is_disjoint(lhs, rhs)


def test_array_contains_draft_specific_tuple_emptiness():
    assert is_empty(
        {
            "type": "array",
            "items": [{"type": "string"}],
            "additionalItems": False,
            "minItems": 1,
            "contains": {"type": "integer"},
            "minContains": 1,
        },
        dialect=Dialect.DRAFT7,
    )
