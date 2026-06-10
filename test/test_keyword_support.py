from dataclasses import dataclass
from typing import Any

import pytest

from subschema import Dialect
from test.proof_oracle import proof_engine_for_schemas
from subschema.dialects import (
    KeywordCategory,
    keyword_category,
    known_keywords_for_dialect,
    validate_supported_keywords,
)
from subschema.prover import ProofOptions
from test.proof_oracle import (
    assert_concrete_evaluator_matches_validator,
    assert_proved,
    assert_witness_validates,
)


@dataclass(frozen=True)
class KeywordMatrixCase:
    keyword: str
    category: KeywordCategory
    introduced: Dialect
    accepted_from: Dialect
    boundary: str
    test_anchor: str
    proof_class: str = "simple_exact"
    accepted_until: Dialect | None = None


@dataclass(frozen=True)
class KeywordProofCase:
    keyword: str
    dialect: Dialect
    true_lhs: Any
    true_rhs: Any
    false_lhs: Any
    false_rhs: Any


DIALECT_ORDER = (
    Dialect.DRAFT4,
    Dialect.DRAFT6,
    Dialect.DRAFT7,
    Dialect.DRAFT201909,
    Dialect.DRAFT202012,
)


KEYWORD_MATRIX = (
    KeywordMatrixCase(
        "$anchor",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "resource",
        "resource-ref",
    ),
    KeywordMatrixCase(
        "$comment",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT7,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "$defs",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT201909,
        Dialect.DRAFT4,
        "resource",
        "resource-ref",
    ),
    KeywordMatrixCase(
        "$dynamicAnchor",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT202012,
        Dialect.DRAFT202012,
        "resource",
        "dynamic-ref",
    ),
    KeywordMatrixCase(
        "$dynamicRef",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT202012,
        Dialect.DRAFT202012,
        "resource",
        "dynamic-ref",
    ),
    KeywordMatrixCase(
        "$id",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT6,
        Dialect.DRAFT6,
        "resource",
        "resource-ref",
    ),
    KeywordMatrixCase(
        "$recursiveAnchor",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "unsupported",
        "unsupported",
        "unsupported_unreliable",
        accepted_until=Dialect.DRAFT201909,
    ),
    KeywordMatrixCase(
        "$recursiveRef",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "unsupported",
        "unsupported",
        "unsupported_unreliable",
        accepted_until=Dialect.DRAFT201909,
    ),
    KeywordMatrixCase(
        "$ref",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "resource",
        "resource-ref",
    ),
    KeywordMatrixCase(
        "$schema",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "resource",
        "dialect",
    ),
    KeywordMatrixCase(
        "$vocabulary",
        KeywordCategory.VOCABULARY,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "vocabulary",
        "vocabulary",
    ),
    KeywordMatrixCase(
        "additionalItems",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "array",
        "array",
    ),
    KeywordMatrixCase(
        "additionalProperties",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "object",
        "object",
    ),
    KeywordMatrixCase(
        "allOf",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "applicator",
        "applicator",
    ),
    KeywordMatrixCase(
        "anyOf",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "applicator",
        "applicator",
    ),
    KeywordMatrixCase(
        "const",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT6,
        Dialect.DRAFT6,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "contains",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT6,
        Dialect.DRAFT6,
        "array",
        "array",
    ),
    KeywordMatrixCase(
        "contentEncoding",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT7,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "contentMediaType",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT7,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "contentSchema",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT201909,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "default",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "definitions",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "resource",
        "resource-ref",
    ),
    KeywordMatrixCase(
        "dependencies",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "object",
        "object",
        accepted_until=Dialect.DRAFT7,
    ),
    KeywordMatrixCase(
        "dependentRequired",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "object",
        "object",
    ),
    KeywordMatrixCase(
        "dependentSchemas",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "object",
        "object",
    ),
    KeywordMatrixCase(
        "deprecated",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT201909,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "description",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "else",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT7,
        Dialect.DRAFT7,
        "applicator",
        "conditional",
    ),
    KeywordMatrixCase(
        "enum",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "examples",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT6,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "exclusiveMaximum",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "exclusiveMinimum",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "format",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "id",
        KeywordCategory.RESOURCE,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "resource",
        "resource-ref",
        accepted_until=Dialect.DRAFT4,
    ),
    KeywordMatrixCase(
        "if",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT7,
        Dialect.DRAFT7,
        "applicator",
        "conditional",
    ),
    KeywordMatrixCase(
        "items",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "array",
        "array",
    ),
    KeywordMatrixCase(
        "maxContains",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "array",
        "array",
    ),
    KeywordMatrixCase(
        "maxItems",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "array",
        "array",
    ),
    KeywordMatrixCase(
        "maxLength",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "maxProperties",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "object",
        "object",
    ),
    KeywordMatrixCase(
        "maximum",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "minContains",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "array",
        "array",
    ),
    KeywordMatrixCase(
        "minItems",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "array",
        "array",
    ),
    KeywordMatrixCase(
        "minLength",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "minProperties",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "object",
        "object",
    ),
    KeywordMatrixCase(
        "minimum",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "multipleOf",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "not",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "applicator",
        "applicator",
        "endeavor_expensive",
    ),
    KeywordMatrixCase(
        "oneOf",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "applicator",
        "applicator",
        "endeavor_expensive",
    ),
    KeywordMatrixCase(
        "pattern",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "patternProperties",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "object",
        "object",
    ),
    KeywordMatrixCase(
        "prefixItems",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT202012,
        Dialect.DRAFT202012,
        "array",
        "array",
    ),
    KeywordMatrixCase(
        "properties",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "object",
        "object",
    ),
    KeywordMatrixCase(
        "propertyNames",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT6,
        Dialect.DRAFT6,
        "object",
        "object",
    ),
    KeywordMatrixCase(
        "readOnly",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT7,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "required",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "object",
        "object",
    ),
    KeywordMatrixCase(
        "then",
        KeywordCategory.APPLICATOR,
        Dialect.DRAFT7,
        Dialect.DRAFT7,
        "applicator",
        "conditional",
    ),
    KeywordMatrixCase(
        "title",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
    KeywordMatrixCase(
        "type",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "scalar",
        "scalar",
    ),
    KeywordMatrixCase(
        "unevaluatedItems",
        KeywordCategory.UNEVALUATED,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "unevaluated",
        "unevaluated",
        "endeavor_expensive",
    ),
    KeywordMatrixCase(
        "unevaluatedProperties",
        KeywordCategory.UNEVALUATED,
        Dialect.DRAFT201909,
        Dialect.DRAFT201909,
        "unevaluated",
        "unevaluated",
        "endeavor_expensive",
    ),
    KeywordMatrixCase(
        "uniqueItems",
        KeywordCategory.ASSERTION,
        Dialect.DRAFT4,
        Dialect.DRAFT4,
        "array",
        "array",
    ),
    KeywordMatrixCase(
        "writeOnly",
        KeywordCategory.ANNOTATION,
        Dialect.DRAFT7,
        Dialect.DRAFT4,
        "annotation",
        "annotation",
    ),
)

ANNOTATION_VALUES = {
    "$comment": "annotation only",
    "contentEncoding": "base64",
    "contentMediaType": "application/json",
    "contentSchema": {"type": "object"},
    "default": "user@example.com",
    "deprecated": True,
    "description": "annotation",
    "examples": ["user@example.com"],
    "format": "email",
    "readOnly": True,
    "title": "Email",
    "writeOnly": False,
}

EXACT_PROOF_CASES = (
    KeywordProofCase(
        "const",
        Dialect.DRAFT7,
        {"const": 1},
        {"type": "integer"},
        {"const": 1},
        {"const": 2},
    ),
    KeywordProofCase(
        "enum",
        Dialect.DRAFT7,
        {"const": 1},
        {"enum": [1, 2]},
        {"const": 3},
        {"enum": [1, 2]},
    ),
    KeywordProofCase(
        "type",
        Dialect.DRAFT7,
        {"type": "integer"},
        {"type": "number"},
        {"const": "x"},
        {"type": "number"},
    ),
    KeywordProofCase(
        "minimum",
        Dialect.DRAFT7,
        {"type": "number", "minimum": 2},
        {"type": "number", "minimum": 1},
        {"const": 0},
        {"type": "number", "minimum": 1},
    ),
    KeywordProofCase(
        "maximum",
        Dialect.DRAFT7,
        {"type": "number", "maximum": 1},
        {"type": "number", "maximum": 2},
        {"const": 3},
        {"type": "number", "maximum": 2},
    ),
    KeywordProofCase(
        "exclusiveMinimum",
        Dialect.DRAFT6,
        {"type": "number", "exclusiveMinimum": 2},
        {"type": "number", "minimum": 2},
        {"const": 1},
        {"type": "number", "exclusiveMinimum": 1},
    ),
    KeywordProofCase(
        "exclusiveMaximum",
        Dialect.DRAFT6,
        {"type": "number", "exclusiveMaximum": 1},
        {"type": "number", "maximum": 1},
        {"const": 1},
        {"type": "number", "exclusiveMaximum": 1},
    ),
    KeywordProofCase(
        "multipleOf",
        Dialect.DRAFT7,
        {"type": "integer"},
        {"type": "number", "multipleOf": 1},
        {"const": 3},
        {"type": "number", "multipleOf": 2},
    ),
    KeywordProofCase(
        "minLength",
        Dialect.DRAFT7,
        {"type": "string", "minLength": 2},
        {"type": "string", "minLength": 1},
        {"const": "a"},
        {"type": "string", "minLength": 2},
    ),
    KeywordProofCase(
        "maxLength",
        Dialect.DRAFT7,
        {"type": "string", "maxLength": 1},
        {"type": "string", "maxLength": 2},
        {"const": "aa"},
        {"type": "string", "maxLength": 1},
    ),
    KeywordProofCase(
        "pattern",
        Dialect.DRAFT7,
        {"type": "string", "pattern": "^alpha$"},
        {"type": "string", "pattern": "^a"},
        {"const": "beta"},
        {"type": "string", "pattern": "^a"},
    ),
    KeywordProofCase(
        "minItems",
        Dialect.DRAFT7,
        {"type": "array", "minItems": 2},
        {"type": "array", "minItems": 1},
        {"const": []},
        {"type": "array", "minItems": 1},
    ),
    KeywordProofCase(
        "maxItems",
        Dialect.DRAFT7,
        {"type": "array", "maxItems": 1},
        {"type": "array", "maxItems": 2},
        {"const": [1, 2]},
        {"type": "array", "maxItems": 1},
    ),
    KeywordProofCase(
        "uniqueItems",
        Dialect.DRAFT7,
        {"type": "array", "maxItems": 1},
        {"type": "array", "uniqueItems": True},
        {"const": [1, 1]},
        {"type": "array", "uniqueItems": True},
    ),
    KeywordProofCase(
        "items",
        Dialect.DRAFT7,
        {"const": [1]},
        {"type": "array", "items": {"type": "number"}},
        {"const": ["x"]},
        {"type": "array", "items": {"type": "number"}},
    ),
    KeywordProofCase(
        "additionalItems",
        Dialect.DRAFT7,
        {"const": [1, "x"]},
        {
            "type": "array",
            "items": [{"type": "number"}],
            "additionalItems": {"type": "string"},
        },
        {"const": [1, 2]},
        {
            "type": "array",
            "items": [{"type": "number"}],
            "additionalItems": {"type": "string"},
        },
    ),
    KeywordProofCase(
        "prefixItems",
        Dialect.DRAFT202012,
        {"const": [1]},
        {"type": "array", "prefixItems": [{"type": "number"}]},
        {"const": ["x"]},
        {"type": "array", "prefixItems": [{"type": "number"}]},
    ),
    KeywordProofCase(
        "contains",
        Dialect.DRAFT202012,
        {"const": [1]},
        {"type": "array", "contains": {"type": "number"}},
        {"const": ["x"]},
        {"type": "array", "contains": {"type": "number"}},
    ),
    KeywordProofCase(
        "minContains",
        Dialect.DRAFT202012,
        {"const": [1, 2]},
        {"type": "array", "contains": {"type": "number"}, "minContains": 2},
        {"const": [1]},
        {"type": "array", "contains": {"type": "number"}, "minContains": 2},
    ),
    KeywordProofCase(
        "maxContains",
        Dialect.DRAFT202012,
        {"const": [1]},
        {"type": "array", "contains": {"type": "number"}, "maxContains": 1},
        {"const": [1, 2]},
        {"type": "array", "contains": {"type": "number"}, "maxContains": 1},
    ),
    KeywordProofCase(
        "minProperties",
        Dialect.DRAFT7,
        {"type": "object", "required": ["a"]},
        {"type": "object", "minProperties": 1},
        {"const": {}},
        {"type": "object", "minProperties": 1},
    ),
    KeywordProofCase(
        "maxProperties",
        Dialect.DRAFT7,
        {"type": "object", "maxProperties": 1},
        {"type": "object", "maxProperties": 2},
        {"const": {"a": 1, "b": 2}},
        {"type": "object", "maxProperties": 1},
    ),
    KeywordProofCase(
        "required",
        Dialect.DRAFT7,
        {"type": "object", "required": ["a", "b"]},
        {"type": "object", "required": ["a"]},
        {"const": {}},
        {"type": "object", "required": ["a"]},
    ),
    KeywordProofCase(
        "dependencies",
        Dialect.DRAFT7,
        {"const": {"a": 1, "b": 1}},
        {"type": "object", "dependencies": {"a": ["b"]}},
        {"const": {"a": 1}},
        {"type": "object", "dependencies": {"a": ["b"]}},
    ),
    KeywordProofCase(
        "dependentRequired",
        Dialect.DRAFT201909,
        {"const": {"a": 1, "b": 1}},
        {"type": "object", "dependentRequired": {"a": ["b"]}},
        {"const": {"a": 1}},
        {"type": "object", "dependentRequired": {"a": ["b"]}},
    ),
    KeywordProofCase(
        "dependentSchemas",
        Dialect.DRAFT201909,
        {"const": {"a": 1, "b": 1}},
        {"type": "object", "dependentSchemas": {"a": {"required": ["b"]}}},
        {"const": {"a": 1}},
        {"type": "object", "dependentSchemas": {"a": {"required": ["b"]}}},
    ),
    KeywordProofCase(
        "properties",
        Dialect.DRAFT7,
        {"const": {"a": 1}},
        {"type": "object", "properties": {"a": {"type": "number"}}},
        {"const": {"a": "x"}},
        {"type": "object", "properties": {"a": {"type": "number"}}},
    ),
    KeywordProofCase(
        "patternProperties",
        Dialect.DRAFT7,
        {"const": {"abc": 1}},
        {"type": "object", "patternProperties": {"^a": {"type": "number"}}},
        {"const": {"abc": "x"}},
        {"type": "object", "patternProperties": {"^a": {"type": "number"}}},
    ),
    KeywordProofCase(
        "additionalProperties",
        Dialect.DRAFT7,
        {"const": {"a": 1}},
        {"type": "object", "additionalProperties": {"type": "number"}},
        {"const": {"a": "x"}},
        {"type": "object", "additionalProperties": {"type": "number"}},
    ),
    KeywordProofCase(
        "propertyNames",
        Dialect.DRAFT6,
        {"const": {"alpha": 1}},
        {"type": "object", "propertyNames": {"pattern": "^a"}},
        {"const": {"Upper": 1}},
        {"type": "object", "propertyNames": {"pattern": "^[a-z]+$"}},
    ),
    KeywordProofCase(
        "allOf",
        Dialect.DRAFT7,
        {"const": 1},
        {"allOf": [{"type": "number"}]},
        {"const": "x"},
        {"allOf": [{"type": "number"}]},
    ),
    KeywordProofCase(
        "anyOf",
        Dialect.DRAFT7,
        {"const": 1},
        {"anyOf": [{"type": "number"}, {"type": "string"}]},
        {"const": True},
        {"anyOf": [{"type": "number"}, {"type": "string"}]},
    ),
    KeywordProofCase(
        "oneOf",
        Dialect.DRAFT7,
        {"const": 1},
        {"oneOf": [{"type": "number"}, {"type": "string"}]},
        {"const": 1},
        {"oneOf": [{"type": "number"}, {"const": 1}]},
    ),
    KeywordProofCase(
        "not",
        Dialect.DRAFT7,
        {"const": "x"},
        {"not": {"type": "number"}},
        {"const": 1},
        {"not": {"type": "number"}},
    ),
    KeywordProofCase(
        "if/then/else",
        Dialect.DRAFT7,
        {"type": "string", "minLength": 2},
        {"if": {"type": "string"}, "then": {"minLength": 2}, "else": False},
        {"const": "a"},
        {"if": {"type": "string"}, "then": {"minLength": 2}, "else": False},
    ),
)


@pytest.mark.parametrize("case", KEYWORD_MATRIX, ids=lambda case: case.keyword)
def test_keyword_categories_are_stable(case):
    assert keyword_category(case.keyword) is case.category


def test_keyword_inventory_covers_draft_2020_12_known_keywords():
    matrix_keywords = {
        case.keyword
        for case in KEYWORD_MATRIX
        if case.accepted_until is None
        or _dialect_index(Dialect.DRAFT202012) <= _dialect_index(case.accepted_until)
    }

    assert matrix_keywords == known_keywords_for_dialect(Dialect.DRAFT202012)
    assert all(case.category is not KeywordCategory.UNKNOWN for case in KEYWORD_MATRIX)
    assert all(case.test_anchor for case in KEYWORD_MATRIX)
    assert all(
        case.proof_class
        in {"simple_exact", "endeavor_expensive", "unsupported_unreliable"}
        for case in KEYWORD_MATRIX
    )


def test_keyword_inventory_matches_current_dialect_gates():
    for dialect in DIALECT_ORDER:
        expected = {
            case.keyword
            for case in KEYWORD_MATRIX
            if _dialect_index(dialect) >= _dialect_index(case.accepted_from)
            and (
                case.accepted_until is None
                or _dialect_index(dialect) <= _dialect_index(case.accepted_until)
            )
        }
        assert known_keywords_for_dialect(dialect) == expected


def test_inactive_modern_keywords_are_ignored_by_older_dialects():
    assert "contains" not in known_keywords_for_dialect(Dialect.DRAFT4)
    assert "contains" in known_keywords_for_dialect(Dialect.DRAFT6)
    assert "if" not in known_keywords_for_dialect(Dialect.DRAFT6)
    assert "if" in known_keywords_for_dialect(Dialect.DRAFT7)
    assert "dependentRequired" not in known_keywords_for_dialect(Dialect.DRAFT7)
    assert "dependentRequired" in known_keywords_for_dialect(Dialect.DRAFT201909)
    assert "prefixItems" not in known_keywords_for_dialect(Dialect.DRAFT201909)
    assert "prefixItems" in known_keywords_for_dialect(Dialect.DRAFT202012)

    validate_supported_keywords({"contains": {"type": "integer"}}, Dialect.DRAFT4)
    validate_supported_keywords({"minContains": 1}, Dialect.DRAFT7)
    validate_supported_keywords(
        {"prefixItems": [{"type": "integer"}]}, Dialect.DRAFT201909
    )


def test_annotation_and_content_keywords_are_transparent_with_modern_kernel(
    monkeypatch,
):
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": "annotation only",
        "contentEncoding": "base64",
        "contentMediaType": "application/json",
        "contentSchema": {"type": "object"},
        "default": "user@example.com",
        "deprecated": True,
        "description": "annotation",
        "examples": ["user@example.com"],
        "format": "email",
        "readOnly": True,
        "title": "Email",
        "type": "string",
        "writeOnly": False,
    }

    assert_proved({"type": "string"}, rhs, Dialect.DRAFT202012, monkeypatch)
    assert_concrete_evaluator_matches_validator(
        rhs, ("user@example.com", "not-email", 1), Dialect.DRAFT202012
    )


@pytest.mark.parametrize("keyword", sorted(ANNOTATION_VALUES))
def test_each_keyword_matrix_annotation_keyword_is_transparent(keyword, monkeypatch):
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "string",
        keyword: ANNOTATION_VALUES[keyword],
    }

    assert_proved({"type": "string"}, rhs, Dialect.DRAFT202012, monkeypatch)
    assert_concrete_evaluator_matches_validator(rhs, ("value", 1), Dialect.DRAFT202012)


def test_required_format_assertion_vocabulary_remains_unsupported():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$vocabulary": {
            "https://json-schema.org/draft/2020-12/vocab/format-assertion": True,
        },
        "format": "email",
        "type": "string",
    }
    engine = proof_engine_for_schemas(
        {"type": "string"},
        schema,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(),
    )

    proof = engine.is_subschema({"type": "string"}, schema)

    assert proof.status == "unsupported"
    assert "format-assertion" in proof.reason
    assert proof.diagnostics[0].category == "format-assertion"


def test_required_content_vocabulary_remains_annotation_only(monkeypatch):
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$vocabulary": {
            "https://json-schema.org/draft/2020-12/vocab/content": True,
        },
        "contentEncoding": "base64",
        "contentMediaType": "application/json",
        "contentSchema": {"type": "object", "required": ["x"]},
        "type": "string",
    }

    assert_proved({"type": "string"}, rhs, Dialect.DRAFT202012, monkeypatch)
    assert_concrete_evaluator_matches_validator(
        rhs,
        ("not base64", "eyJ4IjoxfQ==", 1),
        Dialect.DRAFT202012,
    )


def test_required_format_annotation_vocabulary_remains_annotation_only(monkeypatch):
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$vocabulary": {
            "https://json-schema.org/draft/2020-12/vocab/format-annotation": True,
        },
        "format": "email",
        "type": "string",
    }

    assert_proved({"type": "string"}, rhs, Dialect.DRAFT202012, monkeypatch)
    assert_concrete_evaluator_matches_validator(
        rhs,
        ("not an email", "user@example.com", 1),
        Dialect.DRAFT202012,
    )


def test_optional_format_assertion_vocabulary_remains_annotation_only(monkeypatch):
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$vocabulary": {
            "https://json-schema.org/draft/2020-12/vocab/format-assertion": False,
        },
        "format": "email",
        "type": "string",
    }

    assert_proved({"type": "string"}, rhs, Dialect.DRAFT202012, monkeypatch)
    assert_concrete_evaluator_matches_validator(
        rhs,
        ("not an email", "user@example.com", 1),
        Dialect.DRAFT202012,
    )


@pytest.mark.parametrize("case", EXACT_PROOF_CASES, ids=lambda case: case.keyword)
def test_keyword_matrix_exact_true_cases_prove_without_generic_search_path(
    case, monkeypatch
):
    assert_proved(case.true_lhs, case.true_rhs, case.dialect, monkeypatch)


@pytest.mark.parametrize("case", EXACT_PROOF_CASES, ids=lambda case: case.keyword)
def test_keyword_matrix_exact_false_cases_return_validated_witness(case, monkeypatch):
    proof = _proof_without_generic_search_path(
        case.false_lhs, case.false_rhs, case.dialect, monkeypatch
    )

    assert proof.status == "proved_false", proof
    assert_witness_validates(
        case.false_lhs, case.false_rhs, case.dialect, proof.witness
    )


@pytest.mark.parametrize(
    ("lhs", "rhs", "dialect"),
    (
        ({"const": 1}, {"type": "integer"}, Dialect.DRAFT7),
        (
            {"type": "number", "exclusiveMinimum": 1},
            {"type": "number", "minimum": 1},
            Dialect.DRAFT6,
        ),
        (
            {
                "type": "array",
                "prefixItems": [{"type": "integer"}],
                "minItems": 1,
                "maxItems": 1,
            },
            {"type": "array", "contains": {"type": "number"}},
            Dialect.DRAFT202012,
        ),
        (
            {"type": "object", "propertyNames": {"pattern": "^alpha"}},
            {"type": "object", "propertyNames": {"pattern": "^a"}},
            Dialect.DRAFT6,
        ),
        (
            {"type": "string", "minLength": 2},
            {"if": {"type": "string"}, "then": {"minLength": 2}, "else": False},
            Dialect.DRAFT7,
        ),
        (
            {"type": "object", "required": ["credit_card", "billing_address"]},
            {
                "type": "object",
                "dependentRequired": {"credit_card": ["billing_address"]},
            },
            Dialect.DRAFT201909,
        ),
        (
            {"type": "object", "required": ["credit_card", "billing_address"]},
            {
                "type": "object",
                "dependentSchemas": {"credit_card": {"required": ["billing_address"]}},
            },
            Dialect.DRAFT201909,
        ),
    ),
)
def test_keyword_local_keyword_true_fragments_prove_without_generic_search_path(
    lhs, rhs, dialect, monkeypatch
):
    assert_proved(lhs, rhs, dialect, monkeypatch)


@pytest.mark.parametrize(
    ("lhs", "rhs", "dialect"),
    (
        ({"const": 1}, {"const": 2}, Dialect.DRAFT7),
        (
            {"type": "number", "minimum": 1, "maximum": 1},
            {"type": "number", "exclusiveMinimum": 1},
            Dialect.DRAFT6,
        ),
        (
            {"const": [0.5]},
            {"type": "array", "contains": {"type": "integer"}},
            Dialect.DRAFT202012,
        ),
        (
            {"const": {"Upper": 1}},
            {"type": "object", "propertyNames": {"pattern": "^[a-z]+$"}},
            Dialect.DRAFT6,
        ),
        (
            {"const": "a"},
            {"if": {"type": "string"}, "then": {"minLength": 2}, "else": False},
            Dialect.DRAFT7,
        ),
        (
            {"const": {"credit_card": 1}},
            {
                "type": "object",
                "dependentRequired": {"credit_card": ["billing_address"]},
            },
            Dialect.DRAFT201909,
        ),
        (
            {"const": {"credit_card": 1}},
            {
                "type": "object",
                "dependentSchemas": {"credit_card": {"required": ["billing_address"]}},
            },
            Dialect.DRAFT201909,
        ),
    ),
)
def test_keyword_local_keyword_false_fragments_return_validated_witness(
    lhs, rhs, dialect, monkeypatch
):
    proof = _proof_without_generic_search_path(lhs, rhs, dialect, monkeypatch)

    assert proof.status == "proved_false", proof
    assert_witness_validates(lhs, rhs, dialect, proof.witness)


def test_keyword_static_ref_anchor_and_embedded_id_prove_with_modern_kernel(
    monkeypatch,
):
    lhs = {
        "$id": "https://example.com/root",
        "$defs": {
            "child": {
                "$id": "child",
                "$defs": {
                    "name": {
                        "$anchor": "name",
                        "type": "string",
                    }
                },
                "$ref": "#name",
            }
        },
        "$ref": "child",
    }

    assert_proved(lhs, {"type": "string"}, Dialect.DRAFT202012, monkeypatch)


def test_keyword_acyclic_dynamic_ref_proves_and_recursive_dynamic_ref_stays_unsupported(
    monkeypatch,
):
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "node": {
                "$dynamicAnchor": "node",
                "type": "string",
            }
        },
        "$dynamicRef": "#node",
    }
    assert_proved({"type": "string"}, rhs, Dialect.DRAFT202012, monkeypatch)

    recursive = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$dynamicAnchor": "node",
        "allOf": [{"$dynamicRef": "#node"}],
    }
    proof = proof_engine_for_schemas(
        {"type": "object"},
        recursive,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(),
    ).is_subschema({"type": "object"}, recursive)

    assert proof.status == "unsupported"
    assert "$dynamicRef" in proof.reason


def test_keyword_array_tuple_prefix_and_unevaluated_items_boundaries(monkeypatch):
    draft7_tuple = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "array",
        "items": [{"type": "integer"}],
        "additionalItems": {"type": "string"},
    }
    draft202012_prefix = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "array",
        "prefixItems": [{"type": "integer"}],
        "items": {"type": "string"},
    }

    assert_concrete_evaluator_matches_validator(
        draft7_tuple, ([1], [1, "x"], [1, 2]), Dialect.DRAFT7
    )
    assert_concrete_evaluator_matches_validator(
        draft202012_prefix, ([1], [1, "x"], [1, 2]), Dialect.DRAFT202012
    )
    assert_proved({"const": [1, "x"]}, draft7_tuple, Dialect.DRAFT7, monkeypatch)
    assert_proved(
        {"const": [1, "x"]}, draft202012_prefix, Dialect.DRAFT202012, monkeypatch
    )

    unevaluated = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "contains": {"type": "integer"},
        "unevaluatedItems": False,
    }
    assert_proved({"const": [1]}, unevaluated, Dialect.DRAFT202012, monkeypatch)
    proof = _proof_without_generic_search_path(
        {"const": [1, "x"]}, unevaluated, Dialect.DRAFT202012, monkeypatch
    )

    assert proof.status == "proved_false", proof
    assert_witness_validates(
        {"const": [1, "x"]}, unevaluated, Dialect.DRAFT202012, proof.witness
    )


def test_keyword_ambiguous_unevaluated_branch_effect_stays_unsupported_with_modern_kernel():
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "anyOf": [
            {"properties": {"foo": {"type": "string"}}},
            {"properties": {"bar": {"type": "string"}}},
        ],
        "unevaluatedProperties": False,
    }
    engine = proof_engine_for_schemas(
        {"type": "object"},
        rhs,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(),
    )

    proof = engine.is_subschema({"type": "object"}, rhs)

    assert proof.status == "unsupported"
    assert "branch-conditioned evaluation trace paths" in proof.reason


def test_annotation_transparency_does_not_force_complex_object_product_into_default_exact_solver():
    lhs = {
        "type": "object",
        "properties": {
            "email": {"type": "string", "format": "email"},
            "emaik": {"type": "string", "contentEncoding": "base64"},
        },
        "additionalProperties": {"type": "boolean"},
    }
    rhs = {
        "type": "object",
        "patternProperties": {
            "emai": {"type": "string", "minLength": 10},
        },
        "additionalProperties": {"type": "boolean"},
    }

    proof = proof_engine_for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT7,
        options=ProofOptions(),
    ).is_subschema(lhs, rhs)

    assert proof.status == "proved_false"
    assert_witness_validates(lhs, rhs, Dialect.DRAFT7, proof.witness)
    assert proof.status != "proved_true"


def _proof_without_generic_search_path(lhs, rhs, dialect, monkeypatch):
    engine = proof_engine_for_schemas(
        lhs,
        rhs,
        dialect=dialect,
        options=ProofOptions(),
    )

    def fail_unexpected_proof_path(*_args, **_kwargs):
        raise AssertionError(
            "keyword exact fragment must not use constructive proof path"
        )

    monkeypatch.setattr(
        engine.context,
        "unexpected_proof_path",
        fail_unexpected_proof_path,
        raising=False,
    )
    return engine.is_subschema(lhs, rhs)


def _dialect_index(dialect):
    return DIALECT_ORDER.index(dialect)
