import unittest

from subschema import Dialect, is_subschema


class TestArray202012(unittest.TestCase):
    def test_prefix_items_with_false_items_closes_tuple_tail(self):
        closed_tuple = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": False,
        }

        with self.subTest("closed tuple has at most one item"):
            self.assertTrue(
                is_subschema(
                    closed_tuple,
                    {"type": "array", "maxItems": 1},
                    dialect=Dialect.DRAFT202012,
                )
            )

        with self.subTest("arbitrary one-item array may violate prefix item schema"):
            self.assertFalse(
                is_subschema(
                    {"type": "array", "maxItems": 1},
                    closed_tuple,
                    dialect=Dialect.DRAFT202012,
                )
            )

    def test_prefix_items_with_tail_items_schema(self):
        tuple_with_string_tail = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": {"type": "string"},
            "minItems": 2,
        }
        contains_string = {
            "type": "array",
            "contains": {"type": "string"},
            "minContains": 1,
        }

        self.assertTrue(
            is_subschema(
                tuple_with_string_tail,
                contains_string,
                dialect=Dialect.DRAFT202012,
            )
        )

    def test_prefix_items_with_open_tail_does_not_imply_unique_items(self):
        tuple_with_string_tail = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": {"type": "string"},
        }

        self.assertFalse(
            is_subschema(
                tuple_with_string_tail,
                {"type": "array", "uniqueItems": True},
                dialect=Dialect.DRAFT202012,
            )
        )

    def test_unique_items_does_not_cover_prefix_item_constraints(self):
        lhs = {"type": "array", "uniqueItems": True}
        rhs = {
            "not": {
                "not": {
                    "type": "array",
                    "prefixItems": [False],
                    "uniqueItems": True,
                }
            }
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012))

    def test_items_false_without_prefix_items_allows_only_empty_arrays(self):
        empty_only = {
            "type": "array",
            "items": False,
        }

        with self.subTest("false homogeneous items implies maxItems zero"):
            self.assertTrue(
                is_subschema(
                    empty_only,
                    {"type": "array", "maxItems": 0},
                    dialect=Dialect.DRAFT202012,
                )
            )

        with self.subTest("empty array constraint is not equivalent to arbitrary array"):
            self.assertFalse(
                is_subschema(
                    {"type": "array"},
                    empty_only,
                    dialect=Dialect.DRAFT202012,
                )
            )

        with self.subTest("empty-only arrays are a finite singleton language"):
            self.assertTrue(
                is_subschema(
                    empty_only,
                    {"enum": [[]]},
                    dialect=Dialect.DRAFT202012,
                )
            )

    def test_closed_finite_tuple_arrays_are_finite_for_applicators(self):
        closed_tuple = {
            "type": "array",
            "prefixItems": [{"const": 1}, {"const": 2}],
            "items": False,
            "minItems": 2,
        }
        finite_choice_tuple = {
            "type": "array",
            "prefixItems": [{"enum": [1, 2]}],
            "items": False,
            "minItems": 1,
        }

        with self.subTest("fixed tuple is covered by enum"):
            self.assertTrue(
                is_subschema(
                    closed_tuple,
                    {"enum": [[1, 2]]},
                    dialect=Dialect.DRAFT202012,
                )
            )

        with self.subTest("finite slot choices are covered by enum"):
            self.assertTrue(
                is_subschema(
                    finite_choice_tuple,
                    {"enum": [[1], [2]]},
                    dialect=Dialect.DRAFT202012,
                )
            )

        with self.subTest("finite slot choices can refute incomplete enum"):
            self.assertFalse(
                is_subschema(
                    finite_choice_tuple,
                    {"enum": [[1]]},
                    dialect=Dialect.DRAFT202012,
                )
            )

    def test_additional_items_is_ignored_in_2020_12(self):
        draft7_tail_keyword = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "additionalItems": False,
        }

        self.assertFalse(
            is_subschema(
                draft7_tail_keyword,
                {"type": "array", "maxItems": 1},
                dialect=Dialect.DRAFT202012,
            )
        )

    def test_homogeneous_items_constrains_prefix_slots(self):
        closed_two_item_tuple = {
            "type": "array",
            "prefixItems": [True, True],
            "items": False,
        }

        self.assertFalse(
            is_subschema(
                closed_two_item_tuple,
                {"type": "array", "items": {"type": "integer"}},
                dialect=Dialect.DRAFT202012,
            )
        )

    def test_prefix_items_is_ignored_before_2020_12(self):
        schema = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
        }

        self.assertTrue(is_subschema(schema, {"type": "array"}, dialect=Dialect.DRAFT201909))
        self.assertTrue(is_subschema({"type": "array"}, schema, dialect=Dialect.DRAFT201909))
