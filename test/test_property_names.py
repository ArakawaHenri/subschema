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
