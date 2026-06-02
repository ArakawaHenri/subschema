import unittest

from subschema import Dialect, is_equivalent, is_subschema


DRAFT6_SCHEMA = "http://json-schema.org/draft-06/schema#"


class TestDraft6NumericBounds(unittest.TestCase):
    def test_number_exclusive_minimum(self):
        exclusive = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "exclusiveMinimum": 0,
        }
        inclusive = {"type": "number", "minimum": 0}

        with self.subTest("exclusive lower bound is stricter"):
            self.assertTrue(is_subschema(exclusive, inclusive))

        with self.subTest("inclusive lower bound admits the boundary"):
            self.assertFalse(is_subschema(inclusive, exclusive, dialect=Dialect.DRAFT6))

    def test_number_exclusive_maximum(self):
        exclusive = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "exclusiveMaximum": 10,
        }
        inclusive = {"type": "number", "maximum": 10}

        with self.subTest("exclusive upper bound is stricter"):
            self.assertTrue(is_subschema(exclusive, inclusive))

        with self.subTest("inclusive upper bound admits the boundary"):
            self.assertFalse(is_subschema(inclusive, exclusive, dialect=Dialect.DRAFT6))

    def test_integer_exclusive_minimum_normalizes_to_next_integer(self):
        exclusive = {
            "$schema": DRAFT6_SCHEMA,
            "type": "integer",
            "exclusiveMinimum": 5,
        }
        next_integer = {"type": "integer", "minimum": 6}

        self.assertTrue(is_equivalent(exclusive, next_integer, dialect=Dialect.DRAFT6))

    def test_integer_inclusive_boundary_is_not_subschema_of_number_exclusive_minimum(
        self,
    ):
        lhs = {"type": "integer", "minimum": 0}
        rhs = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "exclusiveMinimum": 0,
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_integer_exclusive_maximum_normalizes_to_previous_integer(self):
        exclusive = {
            "$schema": DRAFT6_SCHEMA,
            "type": "integer",
            "exclusiveMaximum": 5,
        }
        previous_integer = {"type": "integer", "maximum": 4}

        self.assertTrue(
            is_equivalent(exclusive, previous_integer, dialect=Dialect.DRAFT6)
        )

    def test_integer_inclusive_boundary_is_not_subschema_of_number_exclusive_maximum(
        self,
    ):
        lhs = {"type": "integer", "maximum": 0}
        rhs = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "exclusiveMaximum": 0,
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_weaker_exclusive_minimum_does_not_override_minimum(self):
        schema = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "minimum": 5,
            "exclusiveMinimum": 0,
        }

        self.assertTrue(
            is_equivalent(
                schema, {"type": "number", "minimum": 5}, dialect=Dialect.DRAFT6
            )
        )

    def test_weaker_exclusive_maximum_does_not_override_maximum(self):
        schema = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "maximum": 5,
            "exclusiveMaximum": 10,
        }

        self.assertTrue(
            is_equivalent(
                schema, {"type": "number", "maximum": 5}, dialect=Dialect.DRAFT6
            )
        )

    def test_number_enum_keeps_integer_values(self):
        schema = {"type": "number", "enum": [1]}

        with self.subTest("integer JSON values are numbers"):
            self.assertTrue(is_subschema(schema, {"type": "number"}))

        with self.subTest("integer JSON values remain valid integers"):
            self.assertTrue(is_subschema(schema, {"type": "integer"}))

    def test_draft6_integer_enum_accepts_zero_fraction_number(self):
        schema = {
            "$schema": DRAFT6_SCHEMA,
            "type": "integer",
            "enum": [1.0],
        }

        with self.subTest("Draft 6 integer accepts zero-fraction numbers"):
            self.assertTrue(is_subschema(schema, {"type": "integer"}))

        with self.subTest("the enum is equivalent to the same const value"):
            self.assertTrue(
                is_equivalent(schema, {"const": 1.0}, dialect=Dialect.DRAFT6)
            )
