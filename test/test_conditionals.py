import unittest

from subschema import Dialect, is_equivalent, is_subschema


class TestConditionals(unittest.TestCase):
    def test_if_then_restricts_matching_branch(self):
        schema = {
            "if": {"type": "string"},
            "then": {"minLength": 2},
        }

        with self.subTest("matching string branch satisfies then"):
            self.assertTrue(
                is_subschema(
                    {"type": "string", "minLength": 2},
                    schema,
                    dialect=Dialect.DRAFT7,
                )
            )

        with self.subTest("matching string branch may violate then"):
            self.assertFalse(
                is_subschema({"type": "string"}, schema, dialect=Dialect.DRAFT7)
            )

        with self.subTest("non-matching branch is unrestricted"):
            self.assertTrue(
                is_subschema({"type": "integer"}, schema, dialect=Dialect.DRAFT7)
            )

    def test_if_else_restricts_non_matching_branch(self):
        schema = {
            "if": {"type": "string"},
            "else": {"minimum": 0},
        }

        with self.subTest("matching branch is unrestricted"):
            self.assertTrue(
                is_subschema({"type": "string"}, schema, dialect=Dialect.DRAFT7)
            )

        with self.subTest("non-matching branch satisfies else"):
            self.assertTrue(
                is_subschema(
                    {"type": "integer", "minimum": 0},
                    schema,
                    dialect=Dialect.DRAFT7,
                )
            )

        with self.subTest("non-matching branch may violate else"):
            self.assertFalse(
                is_subschema({"type": "integer"}, schema, dialect=Dialect.DRAFT7)
            )

    def test_if_then_else_restricts_both_branches(self):
        schema = {
            "if": {"type": "string"},
            "then": {"minLength": 2},
            "else": {"minimum": 0},
        }

        with self.subTest("matching branch satisfies then"):
            self.assertTrue(
                is_subschema(
                    {"type": "string", "minLength": 2},
                    schema,
                    dialect=Dialect.DRAFT7,
                )
            )

        with self.subTest("matching branch may violate then"):
            self.assertFalse(
                is_subschema({"type": "string"}, schema, dialect=Dialect.DRAFT7)
            )

        with self.subTest("non-matching branch satisfies else"):
            self.assertTrue(
                is_subschema(
                    {"type": "integer", "minimum": 0},
                    schema,
                    dialect=Dialect.DRAFT7,
                )
            )

        with self.subTest("non-matching branch may violate else"):
            self.assertFalse(
                is_subschema({"type": "integer"}, schema, dialect=Dialect.DRAFT7)
            )

    def test_then_or_else_without_if_is_annotation_like_noop(self):
        self.assertTrue(
            is_equivalent(
                {"then": {"type": "string"}, "else": {"type": "integer"}},
                {},
                dialect=Dialect.DRAFT7,
            )
        )

    def test_conditionals_are_ignored_before_draft7(self):
        schema = {
            "if": {"type": "string"},
            "then": {"minLength": 2},
        }

        self.assertTrue(is_subschema(schema, True, dialect=Dialect.DRAFT6))
        self.assertTrue(is_subschema(True, schema, dialect=Dialect.DRAFT6))

    def test_negated_conditionals_preserve_else_array_counterexample(self):
        lhs = {
            "not": {
                "if": False,
                "else": {
                    "type": "array",
                    "maxItems": 0,
                    "contains": {"type": "null"},
                    "minContains": 0,
                    "maxContains": 1,
                },
            }
        }
        rhs = {
            "not": {
                "if": False,
                "else": {
                    "type": "array",
                    "items": True,
                    "maxItems": 1,
                },
            }
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012))
