import unittest

from jsonschema.exceptions import SchemaError

from subschema import Dialect, is_equivalent, is_subschema


class TestBooleanSchemas(unittest.TestCase):
    def test_true_schema_is_top(self):
        with self.subTest("true is equivalent to empty schema"):
            self.assertTrue(is_equivalent(True, {}, dialect=Dialect.DRAFT6))

        with self.subTest("integer is a subtype of true"):
            self.assertTrue(is_subschema({"type": "integer"}, True, dialect=Dialect.DRAFT6))

    def test_false_schema_is_bottom(self):
        with self.subTest("false is a subtype of any schema"):
            self.assertTrue(is_subschema(False, {"type": "integer"}, dialect=Dialect.DRAFT6))

        with self.subTest("non-empty schema is not a subtype of false"):
            self.assertFalse(is_subschema({"type": "integer"}, False, dialect=Dialect.DRAFT6))

        with self.subTest("false schemas are equivalent"):
            self.assertTrue(is_equivalent(False, {"not": {}}, dialect=Dialect.DRAFT6))

    def test_boolean_schema_in_properties(self):
        impossible_property = {
            "type": "object",
            "properties": {"blocked": False},
        }

        with self.subTest("object forbidding a property is still an object"):
            self.assertTrue(is_subschema(impossible_property, {"type": "object"}, dialect=Dialect.DRAFT6))

        with self.subTest("arbitrary object may contain the forbidden property"):
            self.assertFalse(is_subschema({"type": "object"}, impossible_property, dialect=Dialect.DRAFT6))

    def test_boolean_schema_in_array_items(self):
        empty_only_array = {"type": "array", "items": False}

        with self.subTest("array with false items is still an array"):
            self.assertTrue(is_subschema(empty_only_array, {"type": "array"}, dialect=Dialect.DRAFT6))

        with self.subTest("arbitrary array may contain rejected items"):
            self.assertFalse(is_subschema({"type": "array"}, empty_only_array, dialect=Dialect.DRAFT6))

        with self.subTest("true items does not restrict arrays"):
            self.assertTrue(is_equivalent({"type": "array", "items": True}, {"type": "array"}, dialect=Dialect.DRAFT6))

    def test_boolean_schemas_are_rejected_in_draft4(self):
        for schema in (
            True,
            False,
            {"type": "array", "items": False},
            {"type": "object", "properties": {"blocked": False}},
        ):
            with self.subTest(schema=schema):
                with self.assertRaises(SchemaError):
                    is_subschema(schema, {}, dialect=Dialect.DRAFT4)

    def test_boolean_schemas_with_modern_dialects(self):
        for dialect in [
            Dialect.DRAFT6,
            Dialect.DRAFT7,
            Dialect.DRAFT201909,
            Dialect.DRAFT202012,
        ]:
            with self.subTest(dialect=dialect):
                self.assertTrue(is_subschema(False, True, dialect=dialect))
                self.assertTrue(
                    is_subschema(
                        {"type": "object", "properties": {"flag": True}},
                        {"type": "object"},
                        dialect=dialect,
                    )
                )


class TestAnnotationOnlySchemas(unittest.TestCase):
    def test_annotation_only_schema_is_top(self):
        annotation_schema = {
            "$comment": "not a validation assertion",
            "default": 0,
            "deprecated": True,
            "description": "annotation only",
            "examples": [1, "two"],
            "readOnly": True,
            "title": "Anything",
            "writeOnly": False,
        }

        self.assertTrue(is_equivalent(annotation_schema, {}))

    def test_annotations_do_not_restrict_typed_schema(self):
        annotated_string = {
            "$comment": "annotation only",
            "examples": ["abc"],
            "readOnly": True,
            "type": "string",
            "writeOnly": False,
        }

        self.assertTrue(is_equivalent(annotated_string, {"type": "string"}))
