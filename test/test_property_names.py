import unittest

from subschema import Dialect, is_equivalent, is_subschema


class TestPropertyNames(unittest.TestCase):
    def test_property_names_restricts_objects(self):
        restricted_names = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
        }

        with self.subTest("restricted object is still an object"):
            self.assertTrue(
                is_subschema(restricted_names, {"type": "object"}, dialect=Dialect.DRAFT6)
            )

        with self.subTest("arbitrary object may have rejected names"):
            self.assertFalse(
                is_subschema({"type": "object"}, restricted_names, dialect=Dialect.DRAFT6)
            )

    def test_closed_explicit_properties_can_satisfy_property_names(self):
        closed_object = {
            "type": "object",
            "properties": {"alpha": {"type": "number"}},
            "additionalProperties": False,
        }
        restricted_names = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
        }

        self.assertTrue(
            is_subschema(closed_object, restricted_names, dialect=Dialect.DRAFT6)
        )

    def test_closed_explicit_properties_can_violate_property_names(self):
        closed_object = {
            "type": "object",
            "properties": {"beta": {"type": "number"}},
            "additionalProperties": False,
        }
        restricted_names = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
        }

        self.assertFalse(
            is_subschema(closed_object, restricted_names, dialect=Dialect.DRAFT6)
        )

    def test_pattern_properties_can_satisfy_property_names(self):
        closed_object = {
            "type": "object",
            "patternProperties": {"^a": {"type": "number"}},
            "additionalProperties": False,
        }
        restricted_names = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
        }

        self.assertTrue(
            is_subschema(closed_object, restricted_names, dialect=Dialect.DRAFT6)
        )

    def test_property_names_does_not_imply_max_properties_one(self):
        lhs = {"type": "object", "propertyNames": {"pattern": "^a+$"}}
        rhs = {"type": "object", "maxProperties": 1}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_meet_combines_property_names(self):
        lhs = {"type": "object", "propertyNames": {"pattern": "^a"}}
        rhs = {"type": "object", "propertyNames": {"minLength": 3}}
        equivalent = {
            "type": "object",
            "propertyNames": {"pattern": "^a", "minLength": 3},
        }

        self.assertTrue(
            is_equivalent(
                {"allOf": [lhs, rhs]},
                equivalent,
                dialect=Dialect.DRAFT6,
            )
        )

    def test_required_key_rejected_by_property_names_is_uninhabited(self):
        schema = {
            "type": "object",
            "required": ["beta"],
            "propertyNames": {"pattern": "^a"},
        }

        self.assertTrue(is_subschema(schema, False, dialect=Dialect.DRAFT6))

    def test_whitespace_pattern_restricts_property_names(self):
        closed_whitespace_key = {
            "type": "object",
            "properties": {" ": {"type": "number"}},
            "additionalProperties": False,
        }
        closed_letter_key = {
            "type": "object",
            "properties": {"a": {"type": "number"}},
            "additionalProperties": False,
        }
        whitespace_names = {
            "type": "object",
            "propertyNames": {"pattern": r"^\s$"},
        }

        self.assertTrue(
            is_subschema(
                closed_whitespace_key,
                whitespace_names,
                dialect=Dialect.DRAFT202012,
            )
        )
        self.assertFalse(
            is_subschema(
                closed_letter_key,
                whitespace_names,
                dialect=Dialect.DRAFT202012,
            )
        )

    def test_whitespace_pattern_properties_participate_in_value_proofs(self):
        lhs = {
            "type": "object",
            "minProperties": 1,
            "patternProperties": {r"^\s$": {"type": "number"}},
        }
        rhs = {
            "type": "object",
            "minProperties": 1,
            "patternProperties": {r"^\s$": {"type": "integer"}},
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012))

    def test_dotall_idiom_restricts_property_names_like_validation_backend(self):
        nonempty_key = {
            "type": "object",
            "properties": {"a": {"type": "number"}},
            "additionalProperties": False,
        }
        empty_key = {
            "type": "object",
            "properties": {"": {"type": "number"}},
            "additionalProperties": False,
        }
        dotall_names = {
            "type": "object",
            "propertyNames": {"pattern": r"[\s\S]"},
        }

        self.assertTrue(
            is_subschema(nonempty_key, dotall_names, dialect=Dialect.DRAFT202012)
        )
        self.assertFalse(
            is_subschema(empty_key, dotall_names, dialect=Dialect.DRAFT202012)
        )
