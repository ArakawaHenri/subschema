import pytest
from math import inf, nan

from jsonschema.exceptions import SchemaError
import jsonschema_rs

from subschema.dialects import Dialect
from subschema.kernel.validation import (
    validate_schema_for_dialect,
    validation_backend_for,
)
from subschema.kernel.values import stable_key


@pytest.mark.parametrize("dialect", list(Dialect))
def test_validation_backend_preserves_integer_valued_float_semantics(dialect):
    backend = validation_backend_for(dialect)

    assert backend.is_valid({"type": "integer"}, 1.0)
    assert not backend.is_valid({"type": "integer"}, True)


@pytest.mark.parametrize(
    "keyword", ["format", "contentEncoding", "contentMediaType", "contentSchema"]
)
def test_validation_backend_preserves_annotation_only_semantics(keyword):
    backend = validation_backend_for(Dialect.DRAFT202012)
    schema = {"type": "string", keyword: "email" if keyword == "format" else "ignored"}

    assert backend.is_valid(schema, "not an email")


def test_validation_backend_uses_jsonschema_rs_for_supported_schema():
    backend = validation_backend_for(Dialect.DRAFT202012)
    validator = backend.validator_for_schema({"type": "string", "minLength": 2})

    assert isinstance(validator, jsonschema_rs.Draft202012Validator)
    assert validator is backend.validator_for_schema({"minLength": 2, "type": "string"})


def test_validation_backend_strips_annotations_before_rs_validation():
    backend = validation_backend_for(Dialect.DRAFT202012)
    validator = backend.validator_for_schema({"type": "string", "format": "email"})

    assert isinstance(validator, jsonschema_rs.Draft202012Validator)
    assert validator is backend.validator_for_schema({"type": "string"})


def test_validation_backend_strips_inactive_keywords_before_rs_validation():
    draft4 = validation_backend_for(Dialect.DRAFT4)
    draft6 = validation_backend_for(Dialect.DRAFT6)
    draft7 = validation_backend_for(Dialect.DRAFT7)

    assert draft4.is_valid({"const": 1}, 2)
    assert draft4.is_valid({"propertyNames": {"pattern": "^a"}}, {"b": 1})
    assert draft6.is_valid({"if": {"type": "integer"}, "then": {"minimum": 5}}, 1)
    assert not draft7.is_valid({"if": {"type": "integer"}, "then": {"minimum": 5}}, 1)
    assert draft7.is_valid({"dependentRequired": {"a": ["b"]}}, {"a": 1})


def test_validation_backend_preserves_embedded_resource_dialect_transition():
    backend = validation_backend_for(Dialect.DRAFT202012)
    draft4_target = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "draft_target": {
                "$schema": "http://json-schema.org/draft-04/schema#",
                "const": 1,
            },
        },
        "$ref": "#/$defs/draft_target",
    }
    draft7_target = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "modern": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "const": 1,
            },
        },
        "$ref": "#/$defs/modern",
    }

    assert backend.is_valid(draft4_target, 1)
    assert backend.is_valid(draft4_target, 2)
    assert backend.is_valid(draft7_target, 1)
    assert not backend.is_valid(draft7_target, 2)


def test_schema_validation_checks_embedded_resources_under_their_own_dialect():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "draft7_tuple": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "items": [{"type": "integer"}],
                "additionalItems": False,
            },
        },
        "$ref": "#/$defs/draft7_tuple",
    }

    validate_schema_for_dialect(schema, Dialect.DRAFT202012)


def test_schema_validation_rejects_invalid_embedded_resources():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "draft7_tuple": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "items": 1,
            },
        },
        "$ref": "#/$defs/draft7_tuple",
    }

    with pytest.raises(SchemaError):
        validate_schema_for_dialect(schema, Dialect.DRAFT202012)


def test_validation_backend_does_not_treat_instance_values_as_embedded_schemas():
    backend = validation_backend_for(Dialect.DRAFT202012)
    schema = {
        "anyOf": [
            {"const": {"$schema": "http://json-schema.org/draft-07/schema#", "x": 1}},
            {"enum": [{"$schema": "http://json-schema.org/draft-07/schema#", "x": 2}]},
        ],
    }

    validator = backend.validator_for_schema(schema)

    assert isinstance(validator, jsonschema_rs.Draft202012Validator)
    assert backend.is_valid(
        schema, {"$schema": "http://json-schema.org/draft-07/schema#", "x": 1}
    )
    assert not backend.is_valid(
        schema, {"$schema": "http://json-schema.org/draft-07/schema#", "x": 3}
    )


@pytest.mark.parametrize("instance", [nan, inf, -inf])
def test_validation_backend_rejects_non_finite_json_instances(instance):
    backend = validation_backend_for(Dialect.DRAFT4)

    assert not backend.is_valid(True, instance)
    assert not backend.is_valid({"type": "number"}, instance)
    assert not backend.is_valid({"type": "integer"}, instance)
    assert not backend.is_valid(
        {"anyOf": [{"type": "number"}, {"type": "string"}]}, instance
    )


@pytest.mark.parametrize(
    "schema", [{"const": nan}, {"enum": [inf]}, {"properties": {"x": {"const": -inf}}}]
)
def test_validation_backend_rejects_non_finite_json_schemas(schema):
    backend = validation_backend_for(Dialect.DRAFT202012)

    with pytest.raises(ValueError):
        backend.validator_for_schema(schema)


def test_stable_key_rejects_non_finite_json_values():
    with pytest.raises(ValueError):
        stable_key({"const": nan})


@pytest.mark.parametrize(
    "value",
    [
        ("not", "json"),
        {1: "non-string-key"},
        {"items": ("tuple",)},
    ],
)
def test_stable_key_rejects_non_json_values(value):
    with pytest.raises(ValueError):
        stable_key(value)
