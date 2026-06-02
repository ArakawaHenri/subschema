import unittest

from subschema import Dialect, is_subschema


class TestContains(unittest.TestCase):
    def test_contains_restricts_arrays(self):
        contains_integer = {"type": "array", "contains": {"type": "integer"}}

        with self.subTest("array with contains is still an array"):
            self.assertTrue(
                is_subschema(contains_integer, {"type": "array"}, dialect=Dialect.DRAFT6)
            )

        with self.subTest("arbitrary array may not contain an integer"):
            self.assertFalse(
                is_subschema({"type": "array"}, contains_integer, dialect=Dialect.DRAFT6)
            )

    def test_homogeneous_items_can_imply_contains(self):
        integer_items = {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 1,
        }
        contains_integer = {"type": "array", "contains": {"type": "integer"}}

        self.assertTrue(
            is_subschema(integer_items, contains_integer, dialect=Dialect.DRAFT6)
        )

    def test_empty_homogeneous_array_does_not_imply_contains(self):
        integer_items = {
            "type": "array",
            "items": {"type": "integer"},
        }
        contains_integer = {"type": "array", "contains": {"type": "integer"}}

        self.assertFalse(
            is_subschema(integer_items, contains_integer, dialect=Dialect.DRAFT6)
        )

    def test_tuple_item_can_imply_contains_when_guaranteed_present(self):
        tuple_array = {
            "type": "array",
            "items": [{"type": "integer"}, {"type": "string"}],
            "minItems": 1,
        }
        contains_integer = {"type": "array", "contains": {"type": "integer"}}

        self.assertTrue(
            is_subschema(tuple_array, contains_integer, dialect=Dialect.DRAFT6)
        )

    def test_optional_tuple_item_does_not_imply_contains(self):
        tuple_array = {
            "type": "array",
            "items": [{"type": "integer"}],
            "minItems": 0,
        }
        contains_integer = {"type": "array", "contains": {"type": "integer"}}

        self.assertFalse(
            is_subschema(tuple_array, contains_integer, dialect=Dialect.DRAFT6)
        )

    def test_contains_schema_subtype_implies_contains_schema(self):
        contains_integer = {"type": "array", "contains": {"type": "integer"}}
        contains_number = {"type": "array", "contains": {"type": "number"}}

        with self.subTest("integer contains implies number contains"):
            self.assertTrue(
                is_subschema(contains_integer, contains_number, dialect=Dialect.DRAFT6)
            )

        with self.subTest("number contains does not imply integer contains"):
            self.assertFalse(
                is_subschema(contains_number, contains_integer, dialect=Dialect.DRAFT6)
            )

    def test_all_of_preserves_multiple_contains_constraints(self):
        both = {
            "allOf": [
                {"type": "array", "contains": {"type": "integer"}},
                {"type": "array", "contains": {"type": "string"}},
            ]
        }

        self.assertTrue(
            is_subschema(
                both,
                {"type": "array", "contains": {"type": "number"}},
                dialect=Dialect.DRAFT6,
            )
        )
        self.assertTrue(
            is_subschema(
                both,
                {"type": "array", "contains": {"type": "string"}},
                dialect=Dialect.DRAFT6,
            )
        )


class TestMinMaxContains(unittest.TestCase):
    def test_positive_min_contains_implies_min_items(self):
        contains_integer = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 1,
        }

        self.assertTrue(
            is_subschema(
                contains_integer,
                {"type": "array", "minItems": 1},
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_positive_min_contains_does_not_imply_small_max_items(self):
        contains_integer = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 1,
        }

        self.assertFalse(
            is_subschema(
                contains_integer,
                {"type": "array", "minItems": 1, "maxItems": 2},
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_min_contains_zero_is_not_restrictive_without_max_contains(self):
        optional_contains = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
        }

        self.assertTrue(
            is_subschema(
                {"type": "array"},
                optional_contains,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_homogeneous_items_can_imply_min_contains(self):
        integer_items = {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 2,
        }
        min_two_integers = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 2,
        }

        self.assertTrue(
            is_subschema(
                integer_items,
                min_two_integers,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_homogeneous_items_do_not_imply_larger_min_contains(self):
        integer_items = {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 1,
        }
        min_two_integers = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 2,
        }

        self.assertFalse(
            is_subschema(
                integer_items,
                min_two_integers,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_tuple_items_can_imply_min_contains(self):
        tuple_array = {
            "type": "array",
            "items": [{"type": "integer"}, {"type": "integer"}],
            "minItems": 2,
        }
        min_two_numbers = {
            "type": "array",
            "contains": {"type": "number"},
            "minContains": 2,
        }

        self.assertTrue(
            is_subschema(
                tuple_array,
                min_two_numbers,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_max_contains_uses_structural_upper_bound(self):
        at_most_one_item = {
            "type": "array",
            "items": {"type": "integer"},
            "maxItems": 1,
        }
        at_most_one_integer = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
            "maxContains": 1,
        }

        self.assertTrue(
            is_subschema(
                at_most_one_item,
                at_most_one_integer,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_max_contains_rejects_possible_larger_count(self):
        two_items_allowed = {
            "type": "array",
            "items": {"type": "integer"},
            "maxItems": 2,
        }
        at_most_one_integer = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
            "maxContains": 1,
        }

        self.assertFalse(
            is_subschema(
                two_items_allowed,
                at_most_one_integer,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_unconstrained_array_can_violate_max_contains(self):
        at_most_one_integer = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
            "maxContains": 1,
        }

        self.assertFalse(
            is_subschema(
                {"type": "array"},
                at_most_one_integer,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_unique_array_can_violate_max_contains_with_distinct_matches(self):
        at_most_one_integer = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
            "maxContains": 1,
        }

        self.assertFalse(
            is_subschema(
                {"type": "array", "uniqueItems": True},
                at_most_one_integer,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_contains_constraint_can_imply_min_and_max_contains(self):
        exactly_one_number = {
            "type": "array",
            "contains": {"type": "number"},
            "minContains": 1,
            "maxContains": 1,
        }
        at_least_one_number_at_most_two_numbers = {
            "type": "array",
            "contains": {"type": "number"},
            "minContains": 1,
            "maxContains": 2,
        }

        self.assertTrue(
            is_subschema(
                exactly_one_number,
                at_least_one_number_at_most_two_numbers,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_contains_true_max_contains_implies_max_items(self):
        contains_anything_at_most_one = {
            "type": "array",
            "contains": True,
            "minContains": 0,
            "maxContains": 1,
        }

        self.assertTrue(
            is_subschema(
                contains_anything_at_most_one,
                {"type": "array", "maxItems": 1},
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_finite_prefix_with_nonmatching_tail_implies_max_contains(self):
        prefix_integer_string_tail = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": {"type": "string"},
        }
        at_most_one_integer = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
            "maxContains": 1,
        }

        self.assertTrue(
            is_subschema(
                prefix_integer_string_tail,
                at_most_one_integer,
                dialect=Dialect.DRAFT202012,
            )
        )

    def test_nontrivial_max_contains_does_not_imply_max_items(self):
        contains_integer_at_most_one = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
            "maxContains": 1,
        }

        self.assertFalse(
            is_subschema(
                contains_integer_at_most_one,
                {"type": "array", "maxItems": 1},
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_contains_proof_does_not_ignore_tuple_item_constraints(self):
        contains_integer = {"type": "array", "contains": {"type": "integer"}}
        tuple_with_closed_second_slot = {
            "type": "array",
            "prefixItems": [True, False],
            "contains": {"type": "integer"},
        }

        self.assertFalse(
            is_subschema(
                contains_integer,
                tuple_with_closed_second_slot,
                dialect=Dialect.DRAFT202012,
            )
        )
