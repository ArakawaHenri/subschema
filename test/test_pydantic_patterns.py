import pytest

from subschema import Dialect, covers, is_disjoint, is_subschema
from subschema.exceptions import UnsupportedProofError


CAT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "meows"],
    "properties": {
        "kind": {"const": "cat"},
        "meows": {"type": "integer", "minimum": 0},
    },
}
DOG_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "barks"],
    "properties": {
        "kind": {"const": "dog"},
        "barks": {"type": "integer", "minimum": 0},
    },
}
PET_UNION_SCHEMA = {
    "oneOf": [CAT_SCHEMA, DOG_SCHEMA],
    "discriminator": {"propertyName": "kind"},
}


def test_pydantic_strict_models_with_defs_and_nullable_fields():
    address = {
        "type": "object",
        "additionalProperties": False,
        "required": ["city"],
        "properties": {"city": {"type": "string", "minLength": 1}},
    }
    lhs = {
        "$defs": {"Address": address},
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "name", "address"],
        "properties": {
            "id": {"type": "integer", "minimum": 0},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "address": {"$ref": "#/$defs/Address"},
        },
    }
    rhs = {
        "type": "object",
        "required": ["id", "address"],
        "properties": {
            "id": {"type": "number"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "address": address,
        },
    }

    assert is_subschema(lhs, rhs)


def test_simple_all_of_unevaluated_properties_closes_strict_model():
    lhs = {
        "type": "object",
        "allOf": [
            {
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
            {
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ],
        "unevaluatedProperties": False,
    }
    rhs = {
        "type": "object",
        "properties": {
            "id": {"type": "number"},
            "name": {"type": "string"},
        },
        "required": ["id", "name"],
        "additionalProperties": False,
    }

    assert is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012)


def test_simple_all_of_unevaluated_items_closes_tuple_model():
    lhs = {
        "type": "array",
        "allOf": [
            {"prefixItems": [{"type": "integer"}], "minItems": 1},
            {"prefixItems": [True, {"type": "string"}], "minItems": 2},
        ],
        "unevaluatedItems": False,
    }
    rhs = {
        "type": "array",
        "prefixItems": [{"type": "number"}, {"type": "string"}],
        "minItems": 2,
        "items": False,
    }

    assert is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012)


def test_unevaluated_boundaries_remain_unsupported():
    object_with_pattern = {
        "type": "object",
        "patternProperties": {"^a": {"type": "integer"}},
        "unevaluatedProperties": False,
    }
    object_rhs = {
        "type": "object",
        "patternProperties": {"^a": {"type": "number"}},
        "additionalProperties": False,
    }
    object_with_schema_valued_unevaluated = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "unevaluatedProperties": {"type": "integer"},
    }
    array_with_schema_valued_unevaluated = {
        "type": "array",
        "prefixItems": [{"type": "integer"}],
        "unevaluatedItems": {"type": "integer"},
    }

    with pytest.raises(UnsupportedProofError):
        is_subschema(object_with_pattern, object_rhs, dialect=Dialect.DRAFT202012)
    with pytest.raises(UnsupportedProofError):
        is_subschema(
            object_with_schema_valued_unevaluated,
            {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "additionalProperties": False,
            },
            dialect=Dialect.DRAFT202012,
        )
    with pytest.raises(UnsupportedProofError):
        is_subschema(
            array_with_schema_valued_unevaluated,
            {
                "type": "array",
                "prefixItems": [{"type": "integer"}],
                "items": False,
            },
            dialect=Dialect.DRAFT202012,
        )


def test_const_tagged_pydantic_one_of_is_covered_by_matching_branch():
    assert is_subschema(CAT_SCHEMA, PET_UNION_SCHEMA)
    assert covers(CAT_SCHEMA, [PET_UNION_SCHEMA])


def test_const_tagged_pydantic_one_of_disjointness_splits_branches():
    bird = {
        "type": "object",
        "required": ["kind"],
        "properties": {"kind": {"const": "bird"}},
    }

    assert is_disjoint(PET_UNION_SCHEMA, bird)


def test_overlapping_tagged_one_of_does_not_become_true_from_discriminator_hint():
    broad_cat = {
        "type": "object",
        "required": ["kind"],
        "properties": {"kind": {"const": "cat"}},
    }
    overlapping = {
        "oneOf": [broad_cat, broad_cat],
        "discriminator": {"propertyName": "kind"},
    }

    assert not is_subschema(broad_cat, overlapping)
