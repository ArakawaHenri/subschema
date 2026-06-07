import pytest
from math import inf, nan

from jsonschema.exceptions import SchemaError
import jsonschema_rs

import subschema.kernel.validation as validation_module
from subschema.dialects import Dialect
from subschema.kernel.confirmation import confirm_difference, confirm_valid
from subschema.kernel.provenance import SchemaSource
from subschema.kernel.validation import (
    ValidationUnsupportedError,
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
    plan = validation_module._build_instance_plan(
        SchemaSource.root({"type": "string", "minLength": 2}, Dialect.DRAFT202012),
    )

    assert isinstance(plan, validation_module.InstanceValidationPlan)
    assert plan.schema.backend_kind == "jsonschema_rs"
    assert plan.schema.backend_schema_key is not None
    assert isinstance(validator, jsonschema_rs.Draft202012Validator)
    assert validator is backend.validator_for_schema({"minLength": 2, "type": "string"})


def test_validation_backend_wraps_jsonschema_rs_compile_errors(monkeypatch):
    backend = validation_backend_for(Dialect.DRAFT202012)

    def raise_compile_error(dialect, schema):
        raise RuntimeError("compile failed")

    monkeypatch.setattr(
        validation_module,
        "_compile_jsonschema_rs_validator",
        raise_compile_error,
    )

    with pytest.raises(ValidationUnsupportedError):
        backend.is_valid({"type": "string", "pattern": "^compile-error$"}, "x")


def test_validation_state_machine_reports_backend_compile_unsupported(monkeypatch):
    def raise_compile_error(dialect, schema):
        raise RuntimeError("compile failed")

    monkeypatch.setattr(
        validation_module,
        "_compile_jsonschema_rs_validator",
        raise_compile_error,
    )

    outcome = validation_module.validate_source_instance(
        SchemaSource.root(
            {"type": "string", "pattern": "^compile-error$"},
            Dialect.DRAFT202012,
        ),
        "x",
    )

    assert outcome.status == "unsupported"
    assert "compile failed" in outcome.reason


def test_validation_state_machine_prefers_unsupported_source_over_invalid_instance():
    source = SchemaSource(
        schema={"type": "integer"},
        dialect=Dialect.DRAFT202012,
        pointer=("$defs", "value"),
        document_root={"$defs": {"value": {"type": "integer"}}},
        document_dialect=Dialect.DRAFT202012,
    )

    outcome = validation_module.validate_source_instance(source, float("nan"))

    assert outcome.status == "unsupported"
    assert outcome.reason == "validation requires root schema source"


def test_confirmation_uses_validation_outcomes_for_root_sources():
    integer = SchemaSource.root({"type": "integer"}, Dialect.DRAFT202012)
    number = SchemaSource.root({"type": "number"}, Dialect.DRAFT202012)

    assert confirm_valid(integer, 1).status == "confirmed"
    assert confirm_valid(integer, "x").status == "rejected"
    assert confirm_difference(integer, number, "x").status == "rejected"


def test_confirmation_rejects_non_root_source_without_source_backend():
    source = SchemaSource(
        schema={"type": "integer"},
        dialect=Dialect.DRAFT202012,
        pointer=("$defs", "value"),
        document_root={"$defs": {"value": {"type": "integer"}}},
        document_dialect=Dialect.DRAFT202012,
    )

    result = confirm_valid(source, 1)

    assert result.status == "unsupported"
    assert result.proof is not None
    assert result.proof.reason == "schema confirmation requires source validator backend"


def test_validation_backend_wraps_jsonschema_rs_runtime_errors(monkeypatch):
    backend = validation_backend_for(Dialect.DRAFT202012)

    class BrokenValidator:
        def is_valid(self, instance):
            raise RuntimeError("runtime failed")

    def broken_validator(dialect, schema):
        return BrokenValidator()

    monkeypatch.setattr(
        validation_module,
        "_compile_jsonschema_rs_validator",
        broken_validator,
    )

    with pytest.raises(ValidationUnsupportedError):
        backend.is_valid({"type": "string", "pattern": "^runtime-error$"}, "x")


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
    draft4_plan = validation_module._build_instance_plan(
        SchemaSource.root(draft4_target, Dialect.DRAFT202012),
    )

    assert isinstance(draft4_plan, validation_module.InstanceValidationPlan)
    assert draft4_plan.schema.backend_kind == "python_jsonschema"
    assert backend.is_valid(draft4_target, 1)
    assert backend.is_valid(draft4_target, 2)
    assert backend.is_valid(draft7_target, 1)
    assert not backend.is_valid(draft7_target, 2)


def test_validation_difference_plan_allows_mixed_backends():
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "target": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "const": 1,
            },
        },
        "$ref": "#/$defs/target",
    }

    plan = validation_module._build_difference_plan(
        SchemaSource.root(True, Dialect.DRAFT202012),
        SchemaSource.root(rhs, Dialect.DRAFT202012),
    )
    outcome = validation_module.validate_source_difference(
        SchemaSource.root(True, Dialect.DRAFT202012),
        SchemaSource.root(rhs, Dialect.DRAFT202012),
        2,
    )

    assert isinstance(plan, validation_module.DifferenceConfirmationPlan)
    assert plan.lhs.backend_kind == "jsonschema_rs"
    assert plan.rhs.backend_kind == "python_jsonschema"
    assert outcome.status == "valid"


def test_validation_difference_prefers_unsupported_rhs_over_invalid_witness():
    rhs_source = SchemaSource(
        schema={"type": "integer"},
        dialect=Dialect.DRAFT202012,
        pointer=("$defs", "value"),
        document_root={"$defs": {"value": {"type": "integer"}}},
        document_dialect=Dialect.DRAFT202012,
    )

    outcome = validation_module.validate_source_difference(
        SchemaSource.root(True, Dialect.DRAFT202012),
        rhs_source,
        float("nan"),
    )

    assert outcome.status == "unsupported"
    assert outcome.reason == "validation requires root schema source"


def test_validation_difference_plan_reports_dialect_mismatch():
    plan = validation_module._build_difference_plan(
        SchemaSource.root(True, Dialect.DRAFT202012),
        SchemaSource.root(True, Dialect.DRAFT7),
    )

    assert isinstance(plan, validation_module.UnsupportedValidationPlan)
    assert plan.reason == "validation requires matching dialects"


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
