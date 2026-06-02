import unittest

from subschema import Dialect, is_equivalent, is_subschema


class TestDependentRequired(unittest.TestCase):
    def test_dependent_required_restricts_objects(self):
        dependency = {
            "type": "object",
            "dependentRequired": {"credit_card": ["billing_address"]},
        }

        with self.subTest("dependency schema is still an object"):
            self.assertTrue(
                is_subschema(dependency, {"type": "object"}, dialect=Dialect.DRAFT201909)
            )

        with self.subTest("arbitrary object may violate the dependency"):
            self.assertFalse(
                is_subschema({"type": "object"}, dependency, dialect=Dialect.DRAFT201909)
            )

    def test_required_trigger_closes_required_dependencies(self):
        dependency = {
            "type": "object",
            "required": ["credit_card"],
            "dependentRequired": {"credit_card": ["billing_address"]},
        }
        explicit_required = {
            "type": "object",
            "required": ["credit_card", "billing_address"],
        }

        self.assertTrue(
            is_equivalent(dependency, explicit_required, dialect=Dialect.DRAFT201909)
        )

    def test_stronger_dependency_is_subtype_of_weaker_dependency(self):
        stronger = {
            "type": "object",
            "dependentRequired": {"credit_card": ["billing_address", "zip"]},
        }
        weaker = {
            "type": "object",
            "dependentRequired": {"credit_card": ["billing_address"]},
        }

        with self.subTest("stronger dependency implies weaker dependency"):
            self.assertTrue(is_subschema(stronger, weaker, dialect=Dialect.DRAFT201909))

        with self.subTest("weaker dependency does not imply stronger dependency"):
            self.assertFalse(is_subschema(weaker, stronger, dialect=Dialect.DRAFT201909))

    def test_closed_object_without_trigger_satisfies_dependency(self):
        closed_object = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": False,
        }
        dependency = {
            "type": "object",
            "dependentRequired": {"credit_card": ["billing_address"]},
        }

        self.assertTrue(
            is_subschema(closed_object, dependency, dialect=Dialect.DRAFT201909)
        )

    def test_all_of_merges_dependent_required(self):
        combined = {
            "allOf": [
                {
                    "type": "object",
                    "dependentRequired": {"credit_card": ["billing_address"]},
                },
                {
                    "type": "object",
                    "dependentRequired": {"credit_card": ["zip"]},
                },
            ]
        }
        expected = {
            "type": "object",
            "dependentRequired": {"credit_card": ["billing_address", "zip"]},
        }

        self.assertTrue(is_equivalent(combined, expected, dialect=Dialect.DRAFT201909))

    def test_array_valued_dependencies_restrict_draft7_objects(self):
        draft_behavior = {
            "type": "object",
            "dependencies": {"credit_card": ["billing_address"]},
        }
        explicit_required = {
            "type": "object",
            "required": ["credit_card", "billing_address"],
        }

        self.assertTrue(is_subschema(explicit_required, draft_behavior, dialect=Dialect.DRAFT7))
        self.assertFalse(is_subschema({"type": "object", "required": ["credit_card"]}, draft_behavior, dialect=Dialect.DRAFT7))

    def test_dependencies_is_ignored_in_2019_09_and_later(self):
        dependency = {
            "type": "object",
            "dependencies": {"credit_card": ["billing_address"]},
        }
        object_schema = {"type": "object"}

        self.assertTrue(is_subschema(dependency, object_schema, dialect=Dialect.DRAFT201909))
        self.assertTrue(is_subschema(object_schema, dependency, dialect=Dialect.DRAFT201909))
        self.assertTrue(is_subschema(dependency, object_schema, dialect=Dialect.DRAFT202012))
        self.assertTrue(is_subschema(object_schema, dependency, dialect=Dialect.DRAFT202012))

    def test_dependencies_preserve_property_names_that_look_like_inactive_keywords(self):
        lhs = {"type": "object", "required": ["prefixItems"]}
        rhs = {
            "type": "object",
            "dependencies": {"prefixItems": ["billing_address"]},
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT4))

    def test_dependencies_preserve_property_names_that_look_like_reference_keywords(self):
        lhs = {"type": "object", "dependencies": {"a": ["b"]}}
        rhs = {
            "type": "object",
            "dependencies": {"$dynamicRef": ["b"]},
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT4))

    def test_dependent_required_preserves_property_names_that_look_like_inactive_keywords(self):
        lhs = {"type": "object", "required": ["prefixItems"]}
        rhs = {
            "type": "object",
            "dependentRequired": {"prefixItems": ["billing_address"]},
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT201909))

    def test_dependent_required_can_violate_property_names_keyspace(self):
        dependency = {
            "type": "object",
            "dependentRequired": {"a": ["b"]},
        }
        restricted_names = {
            "type": "object",
            "propertyNames": {"pattern": "^a$"},
        }

        self.assertFalse(
            is_subschema(dependency, restricted_names, dialect=Dialect.DRAFT201909)
        )

    def test_property_names_keyspace_can_violate_dependent_required(self):
        restricted_names = {
            "type": "object",
            "propertyNames": {"pattern": "^a$"},
        }
        dependency = {
            "type": "object",
            "dependentRequired": {"a": ["b"]},
        }

        self.assertFalse(
            is_subschema(restricted_names, dependency, dialect=Dialect.DRAFT201909)
        )

    def test_dependent_required_can_violate_closed_pattern_keyspace(self):
        dependency = {
            "type": "object",
            "dependentRequired": {"a": ["b"]},
        }
        closed_pattern = {
            "type": "object",
            "patternProperties": {"^a": {"enum": [1, 2]}},
            "additionalProperties": False,
        }

        self.assertFalse(
            is_subschema(dependency, closed_pattern, dialect=Dialect.DRAFT201909)
        )

    def test_closed_pattern_keyspace_can_violate_dependent_required(self):
        closed_pattern = {
            "type": "object",
            "patternProperties": {"^a": {"enum": [1, 2]}},
            "additionalProperties": False,
        }
        dependency = {
            "type": "object",
            "dependentRequired": {"a": ["b"]},
        }

        self.assertFalse(
            is_subschema(closed_pattern, dependency, dialect=Dialect.DRAFT201909)
        )
