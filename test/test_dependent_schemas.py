import unittest

from subschema import Dialect, is_equivalent, is_subschema


class TestDependentSchemas(unittest.TestCase):
    def test_dependent_schema_restricts_objects(self):
        dependency = {
            "type": "object",
            "dependentSchemas": {
                "credit_card": {"required": ["billing_address"]},
            },
        }

        with self.subTest("dependent schema is still an object"):
            self.assertTrue(
                is_subschema(dependency, {"type": "object"}, dialect=Dialect.DRAFT201909)
            )

        with self.subTest("arbitrary object may violate the dependent schema"):
            self.assertFalse(
                is_subschema({"type": "object"}, dependency, dialect=Dialect.DRAFT201909)
            )

    def test_dependent_schema_is_ignored_before_modern_dialect(self):
        dependency = {
            "type": "object",
            "dependentSchemas": {
                "credit_card": {"required": ["billing_address"]},
            },
        }

        self.assertTrue(is_subschema(dependency, {"type": "object"}, dialect=Dialect.DRAFT7))
        self.assertTrue(is_subschema({"type": "object"}, dependency, dialect=Dialect.DRAFT7))

    def test_closed_object_without_trigger_satisfies_dependent_schema(self):
        closed_object = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": False,
        }
        dependency = {
            "type": "object",
            "dependentSchemas": {
                "credit_card": {"required": ["billing_address"]},
            },
        }

        self.assertTrue(
            is_subschema(closed_object, dependency, dialect=Dialect.DRAFT201909)
        )

    def test_global_subtype_can_satisfy_dependent_schema(self):
        always_has_billing_address = {
            "type": "object",
            "required": ["billing_address"],
        }
        dependency = {
            "type": "object",
            "dependentSchemas": {
                "credit_card": {"required": ["billing_address"]},
            },
        }

        self.assertTrue(
            is_subschema(
                always_has_billing_address,
                dependency,
                dialect=Dialect.DRAFT201909,
            )
        )

    def test_stronger_dependent_schema_implies_weaker_dependent_schema(self):
        stronger = {
            "type": "object",
            "dependentSchemas": {
                "credit_card": {"required": ["billing_address", "zip"]},
            },
        }
        weaker = {
            "type": "object",
            "dependentSchemas": {
                "credit_card": {"required": ["billing_address"]},
            },
        }

        with self.subTest("stronger dependent schema implies weaker one"):
            self.assertTrue(is_subschema(stronger, weaker, dialect=Dialect.DRAFT201909))

        with self.subTest("weaker dependent schema does not imply stronger one"):
            self.assertFalse(is_subschema(weaker, stronger, dialect=Dialect.DRAFT201909))

    def test_dependent_schema_property_values_are_not_presence_only(self):
        dependency = {
            "type": "object",
            "dependentSchemas": {
                "a": {"properties": {"b": {"type": "integer"}}},
            },
        }

        self.assertFalse(is_subschema({"type": "object"}, dependency, dialect=Dialect.DRAFT201909))

    def test_all_of_merges_dependent_schemas_for_same_trigger(self):
        combined = {
            "allOf": [
                {
                    "type": "object",
                    "dependentSchemas": {
                        "credit_card": {"required": ["billing_address"]},
                    },
                },
                {
                    "type": "object",
                    "dependentSchemas": {
                        "credit_card": {"required": ["zip"]},
                    },
                },
            ]
        }
        expected = {
            "type": "object",
            "dependentSchemas": {
                "credit_card": {"required": ["billing_address", "zip"]},
            },
        }

        self.assertTrue(is_equivalent(combined, expected, dialect=Dialect.DRAFT201909))
