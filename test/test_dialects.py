import unittest

from subschema import Dialect, canonicalize_schema, is_equivalent, is_subschema
from subschema.dialects import (
    dialect_from_schema,
    resolve_dialect,
    strip_inactive_keywords_for_dialect,
    validate_supported_keywords,
)
from subschema.exceptions import (
    ConflictingDialectError,
    UnknownDialectError,
    UnsupportedKeywordError,
)


class TestDialectResolution(unittest.TestCase):
    def test_default_dialect_uses_draft202012_behavior(self):
        self.assertEqual(resolve_dialect({}, {}), Dialect.DRAFT202012)
        self.assertTrue(is_subschema({"type": "integer"}, {"type": "number"}))
        self.assertEqual(
            canonicalize_schema({"prefixItems": [{"type": "integer"}]}),
            {"prefixItems": [{"type": "integer"}]},
        )

    def test_explicit_dialect_alias(self):
        self.assertEqual(resolve_dialect(dialect="2020-12"), Dialect.DRAFT202012)
        self.assertEqual(resolve_dialect(dialect="draft/2020-12"), Dialect.DRAFT202012)

    def test_schema_declared_dialect(self):
        schema = {"$schema": "http://json-schema.org/draft-07/schema#"}

        self.assertEqual(dialect_from_schema(schema), Dialect.DRAFT7)
        self.assertEqual(resolve_dialect(schema), Dialect.DRAFT7)

    def test_unknown_dialect(self):
        with self.assertRaises(UnknownDialectError):
            resolve_dialect(dialect="draft-next")

    def test_conflicting_declared_dialects(self):
        lhs = {"$schema": "http://json-schema.org/draft-07/schema#"}
        rhs = {"$schema": "https://json-schema.org/draft/2020-12/schema"}

        with self.assertRaises(ConflictingDialectError):
            is_subschema(lhs, rhs)

    def test_explicit_dialect_overrides_declared_conflict(self):
        lhs = {"$schema": "http://json-schema.org/draft-07/schema#", "const": 1}
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "integer",
        }

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT7))


class TestDialectKeywordSupport(unittest.TestCase):
    def test_canonicalize_schema_accepts_declared_supported_dialect(self):
        schema = {"$schema": "http://json-schema.org/draft-07/schema#", "const": 1}

        self.assertTrue(is_equivalent(canonicalize_schema(schema), {"const": 1}))

    def test_annotation_keywords_do_not_restrict_schema(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$comment": "annotation only",
            "examples": [1],
            "title": "Anything",
        }

        self.assertTrue(is_subschema({"type": "integer"}, schema))

    def test_unevaluated_items_is_handled_by_ir_engine(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "prefixItems": [{"type": "integer"}],
            "unevaluatedItems": False,
        }

        with self.subTest("finite matching array is accepted"):
            self.assertTrue(is_subschema({"const": [1]}, schema))

        with self.subTest("arbitrary arrays may contain unevaluated items"):
            self.assertFalse(is_subschema({"type": "array"}, schema))

    def test_inactive_modern_keyword_is_ignored_without_declared_schema_too(self):
        validate_supported_keywords({"if": {"type": "integer"}}, Dialect.DRAFT4)

    def test_min_contains_is_ignored_before_modern_dialect(self):
        no_contains_schema = {"type": "array", "minContains": 1}
        self.assertTrue(is_subschema(no_contains_schema, {"type": "array"}, dialect=Dialect.DRAFT7))
        self.assertTrue(is_subschema({"type": "array"}, no_contains_schema, dialect=Dialect.DRAFT7))

        schema = {
            "type": "array",
            "contains": {"const": 1},
            "minContains": 2,
        }
        contains_only = {"type": "array", "contains": {"const": 1}}

        self.assertTrue(is_subschema(schema, contains_only, dialect=Dialect.DRAFT7))
        self.assertTrue(is_subschema(contains_only, schema, dialect=Dialect.DRAFT7))

    def test_contains_is_ignored_before_draft6(self):
        schema = {"type": "array", "contains": {"type": "integer"}}

        self.assertTrue(is_subschema(schema, {"type": "array"}, dialect=Dialect.DRAFT4))
        self.assertTrue(is_subschema({"type": "array"}, schema, dialect=Dialect.DRAFT4))

    def test_inactive_keyword_subschemas_are_not_validated_or_resolved(self):
        schema = {"type": "array", "contains": {"$ref": "#/$defs/missing"}}

        self.assertTrue(is_subschema(schema, {"type": "array"}, dialect=Dialect.DRAFT4))
        self.assertTrue(is_subschema({"type": "array"}, schema, dialect=Dialect.DRAFT4))

    def test_inactive_keyword_stripping_respects_embedded_resource_dialect(self):
        schema = {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "definitions": {
                "target": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "const": 1,
                },
            },
            "$ref": "#/definitions/target",
        }

        stripped = strip_inactive_keywords_for_dialect(schema, Dialect.DRAFT4)

        self.assertEqual(stripped["definitions"]["target"]["const"], 1)
        self.assertFalse(is_subschema({"enum": [2]}, schema, dialect=Dialect.DRAFT4))

    def test_supported_keyword_validation_respects_embedded_resource_dialect(self):
        schema = {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "definitions": {
                "target": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$vocabulary": {
                        "https://json-schema.org/draft/2020-12/vocab/format-assertion": True,
                    },
                },
            },
            "$ref": "#/definitions/target",
        }

        with self.assertRaises(UnsupportedKeywordError):
            validate_supported_keywords(schema, Dialect.DRAFT4)

    def test_property_names_is_ignored_before_draft6(self):
        schema = {"type": "object", "propertyNames": {"pattern": "^a"}}

        self.assertTrue(is_subschema(schema, {"type": "object"}, dialect=Dialect.DRAFT4))
        self.assertTrue(is_subschema({"type": "object"}, schema, dialect=Dialect.DRAFT4))

    def test_const_is_ignored_before_draft6(self):
        schema = {"const": 1}

        self.assertTrue(is_subschema({"const": 2}, schema, dialect=Dialect.DRAFT4))
        self.assertFalse(is_subschema({"const": 2}, schema, dialect=Dialect.DRAFT6))

    def test_dependent_required_is_ignored_before_modern_dialect(self):
        schema = {
            "type": "object",
            "dependentRequired": {"credit_card": ["billing_address"]},
        }

        self.assertTrue(is_subschema(schema, {"type": "object"}, dialect=Dialect.DRAFT7))
        self.assertTrue(is_subschema({"type": "object"}, schema, dialect=Dialect.DRAFT7))

    def test_prefix_items_is_ignored_before_2020_12(self):
        schema = {"type": "array", "prefixItems": [{"type": "integer"}]}

        self.assertTrue(is_subschema(schema, {"type": "array"}, dialect=Dialect.DRAFT201909))
        self.assertTrue(is_subschema({"type": "array"}, schema, dialect=Dialect.DRAFT201909))

    def test_additional_items_is_ignored_in_2020_12(self):
        schema = {"type": "array", "prefixItems": [{"type": "integer"}], "additionalItems": False}
        without_additional_items = {"type": "array", "prefixItems": [{"type": "integer"}]}

        self.assertTrue(is_subschema(schema, without_additional_items, dialect=Dialect.DRAFT202012))
        self.assertTrue(is_subschema(without_additional_items, schema, dialect=Dialect.DRAFT202012))

    def test_dynamic_keywords_are_ignored_before_2020_12(self):
        schema = {"type": "integer", "$dynamicRef": "#node", "$dynamicAnchor": "node"}

        self.assertTrue(is_subschema(schema, {"type": "number"}, dialect=Dialect.DRAFT7))

    def test_recursive_keywords_are_ignored_outside_2019_09(self):
        schema = {"type": "integer", "$recursiveRef": "#", "$recursiveAnchor": True}

        self.assertTrue(is_subschema(schema, {"type": "number"}, dialect=Dialect.DRAFT202012))

    def test_numeric_exclusive_bounds_are_supported_for_modern_dialects(self):
        schema = {
            "$schema": "http://json-schema.org/draft-06/schema#",
            "type": "number",
            "exclusiveMinimum": 0,
        }

        self.assertTrue(is_subschema(schema, {"type": "number"}))

    def test_vocabulary_is_ignored_before_modern_dialect(self):
        schema = {
            "$vocabulary": {
                "https://json-schema.org/draft/2020-12/vocab/validation": True,
            },
        }

        self.assertTrue(is_subschema(schema, {}, dialect=Dialect.DRAFT7))
        self.assertTrue(is_subschema({}, schema, dialect=Dialect.DRAFT7))

    def test_supported_required_vocabulary_is_accepted(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$vocabulary": {
                "https://json-schema.org/draft/2020-12/vocab/core": True,
                "https://json-schema.org/draft/2020-12/vocab/validation": True,
                "https://json-schema.org/draft/2020-12/vocab/format-annotation": True,
            },
            "type": "integer",
        }

        self.assertTrue(is_subschema(schema, {"type": "number"}))

    def test_optional_unknown_vocabulary_is_ignored(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$vocabulary": {
                "https://example.com/custom-annotation-vocabulary": False,
            },
            "type": "integer",
        }

        self.assertTrue(is_subschema(schema, {"type": "number"}))

    def test_required_unknown_vocabulary_fails_clearly(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$vocabulary": {
                "https://example.com/custom-assertion-vocabulary": True,
            },
        }

        with self.assertRaises(UnsupportedKeywordError):
            is_subschema(schema, {})

    def test_canonicalize_preserves_vocabulary_uri_names_for_validation(self):
        schema = {"$vocabulary": {"prefixItems": True}}

        with self.assertRaises(UnsupportedKeywordError):
            canonicalize_schema(schema, dialect=Dialect.DRAFT202012)

    def test_required_unevaluated_vocabulary_is_accepted(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$vocabulary": {
                "https://json-schema.org/draft/2020-12/vocab/unevaluated": True,
            },
        }

        self.assertTrue(is_subschema({"type": "integer"}, schema))
