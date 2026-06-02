import pytest

from subschema import Dialect, UnsupportedProofError, is_disjoint, is_subschema
from subschema.kernel import ProofEngine
from test.proof_oracle import assert_witness_validates


def test_closed_finite_objects_with_disjoint_required_keyspaces_are_disjoint():
    lhs = {
        "type": "object",
        "properties": {"a": {}},
        "required": ["a"],
        "additionalProperties": False,
    }
    rhs = {
        "type": "object",
        "properties": {"b": {}},
        "required": ["b"],
        "additionalProperties": False,
    }

    assert is_disjoint(lhs, rhs)


def test_closed_finite_objects_with_disjoint_property_values_are_disjoint():
    lhs = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    rhs = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
    }

    assert is_disjoint(lhs, rhs)


def test_closed_finite_objects_with_shared_instance_are_not_disjoint():
    lhs = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    rhs = {
        "type": "object",
        "properties": {"a": {"type": "number"}},
        "required": ["a"],
        "additionalProperties": False,
    }

    assert not is_disjoint(lhs, rhs)


def test_closed_finite_object_subproofs_cover_common_fields_and_forbidden_keys():
    true_lhs = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    true_rhs = {
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "integer"},
        },
        "additionalProperties": False,
    }
    false_lhs = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    }
    false_rhs = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
        "additionalProperties": False,
    }

    assert is_subschema(true_lhs, true_rhs)
    proof = ProofEngine.for_schemas(false_lhs, false_rhs).is_subschema(
        false_lhs, false_rhs
    )

    assert proof.status == "proved_false", proof
    assert_witness_validates(false_lhs, false_rhs, Dialect.DRAFT202012, proof.witness)


def test_fixed_finite_arrays_prove_per_index_item_obligations():
    true_lhs = {
        "type": "array",
        "prefixItems": [{"type": "integer"}, {"type": "integer"}],
        "items": False,
    }
    true_rhs = {"type": "array", "items": {"type": "number"}}
    false_lhs = {
        "type": "array",
        "prefixItems": [{"type": "number"}],
        "items": False,
    }
    false_rhs = {"type": "array", "items": {"type": "integer"}}

    assert is_subschema(true_lhs, true_rhs)
    proof = ProofEngine.for_schemas(false_lhs, false_rhs).is_subschema(
        false_lhs, false_rhs
    )

    assert proof.status == "proved_false", proof
    assert_witness_validates(false_lhs, false_rhs, Dialect.DRAFT202012, proof.witness)


def test_vacuous_dependencies_and_finite_property_names_are_default_exact():
    closed_object = {
        "type": "object",
        "properties": {"name": {}, "abc": {}},
        "additionalProperties": False,
    }
    dependent_required = {
        "type": "object",
        "dependentRequired": {"credit_card": ["billing_address"]},
    }
    dependent_schemas = {
        "type": "object",
        "dependentSchemas": {
            "credit_card": {"required": ["billing_address"]},
        },
    }
    property_names = {"type": "object", "propertyNames": {"pattern": "^[an]"}}

    assert is_subschema(closed_object, dependent_required)
    assert is_subschema(closed_object, dependent_schemas)
    assert is_subschema(closed_object, property_names)


def test_simple_finite_applicator_wrappers_are_default_exact():
    assert is_subschema({"type": "integer"}, {"allOf": [{"type": "number"}]})
    assert is_subschema({"type": "integer"}, {"anyOf": [{"type": "number"}]})
    assert is_subschema({"enum": [1, "a"]}, {"oneOf": [{"type": "integer"}, {"type": "string"}]})
    assert is_subschema({"enum": [1, 2]}, {"not": {"enum": [3]}})


@pytest.mark.parametrize(
    "rhs",
    [
        {
            "$dynamicAnchor": "node",
            "allOf": [{"$dynamicRef": "#node"}],
        },
        {
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"a": {"$ref": "#/$defs/node"}},
                    "additionalProperties": False,
                }
            },
            "$ref": "#/$defs/node",
        },
    ],
)
def test_recursive_and_dynamic_reference_boundaries_remain_unsupported(rhs):
    with pytest.raises(UnsupportedProofError):
        is_subschema({"type": "object"}, rhs)
