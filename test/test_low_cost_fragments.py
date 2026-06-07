import pytest

from subschema import Dialect, covers, is_disjoint, is_empty, is_subschema
from subschema.exceptions import UnsupportedProofError
from subschema.kernel.schemas import transparent_schema_target


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


def test_unique_items_with_finite_items_can_be_empty_by_cardinality():
    boolean_items = {
        "type": "array",
        "minItems": 3,
        "uniqueItems": True,
        "items": {"type": "boolean"},
    }
    enum_items = {
        "type": "array",
        "minItems": 3,
        "uniqueItems": True,
        "items": {"enum": [1, 2]},
    }

    assert is_empty(boolean_items)
    assert is_empty(enum_items)
    assert is_subschema(
        boolean_items,
        {"type": "array", "minItems": 2, "uniqueItems": True},
    )
    assert not is_empty(
        {
            "type": "array",
            "minItems": 2,
            "uniqueItems": True,
            "items": {"type": "boolean"},
        }
    )


def test_unique_items_cardinality_handles_finite_tuple_items():
    assert is_empty(
        {
            "type": "array",
            "minItems": 3,
            "uniqueItems": True,
            "prefixItems": [{"const": 1}, {"const": 2}],
            "items": False,
        }
    )


def test_array_only_unsupported_diagnostic_is_not_closed_object_reason():
    schema = {
        "type": "array",
        "minItems": 1,
        "items": {"type": "string", "pattern": "(?=a)"},
    }

    with pytest.raises(UnsupportedProofError) as exc_info:
        is_subschema(schema, False)

    assert "closed-object" not in exc_info.value.reason


def test_right_side_not_uses_low_cost_disjointness():
    assert is_subschema(
        {"type": "number", "maximum": 1},
        {"not": {"type": "number", "minimum": 2}},
    )


def test_transparent_double_not_recovers_closed_object_counterexample():
    lhs = {
        "not": {
            "not": {
                "type": "object",
                "properties": {"a": {"type": "integer"}},
                "required": [],
                "additionalProperties": False,
            }
        }
    }
    rhs = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
        "additionalProperties": True,
    }

    assert not is_subschema(lhs, rhs)


def test_transparent_double_not_recovers_empty_and_disjointness_proofs():
    assert is_empty({"not": {"not": False}})
    assert is_disjoint(
        {"not": {"not": {"type": "number", "maximum": 1}}},
        {"type": "number", "exclusiveMinimum": 2},
    )
    assert covers({"not": {"not": {"type": "integer"}}}, [{"type": "number"}])


@pytest.mark.parametrize("wrapper", ["allOf", "anyOf", "oneOf"])
def test_singleton_applicator_wrappers_preserve_low_cost_shapes(wrapper):
    def wrapped(schema):
        return {wrapper: [schema]}

    assert is_subschema(wrapped({"type": "integer"}), {"type": "number"})
    assert is_subschema(
        wrapped(
            {
                "type": "array",
                "prefixItems": [{"type": "integer"}],
                "items": False,
                "minItems": 1,
                "maxItems": 1,
            }
        ),
        {
            "type": "array",
            "prefixItems": [{"type": "number"}],
            "items": False,
            "minItems": 1,
            "maxItems": 1,
        },
    )
    assert is_subschema(
        wrapped(
            {
                "type": "object",
                "properties": {"a": {"type": "integer"}},
                "required": ["a"],
                "additionalProperties": False,
            }
        ),
        {
            "type": "object",
            "properties": {"a": {"type": "number"}},
            "required": ["a"],
            "additionalProperties": False,
        },
    )


def test_transparent_target_is_intentionally_narrow():
    assert transparent_schema_target({"not": {"type": "integer"}}) is None
    assert transparent_schema_target(
        {"anyOf": [{"type": "integer"}, {"type": "string"}]}
    ) is None
    assert (
        transparent_schema_target(
            {
                "allOf": [{"$ref": "#/$defs/A"}],
                "$defs": {"A": {"type": "integer"}},
            }
        )
        is None
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
