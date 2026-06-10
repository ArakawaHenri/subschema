import unittest
from unittest.mock import patch

from subschema import Dialect, is_disjoint, is_empty, is_subschema
from subschema.exceptions import UnsupportedProofError


class TestSimpleRefs(unittest.TestCase):

    def test_1(self):
        s1 = {'definitions': {'bom': {'type': 'string'},
                              'tak': {'type': 'integer'}},
              'type': 'object', 'properties':
              {'foo': {'$ref': '#/definitions/bom',
                       'type': 'integer'}}}
        s2 = {'type': 'object',
              'properties': {
                  'foo': {'type': 'string'}}}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_2(self):
        s1 = {'definitions': {'bom': {'type': 'string'},
                              'tak': {'type': 'integer'}},
              'type': 'object', 'properties':
              {'foo': {'$ref': '#/definitions/bom',
                       'type': 'integer'}}}
        s2 = {'type': 'object',
              'properties': {
                  'foo': {'type': 'string', 'pattern': 'a'}}}

        with self.subTest():
            self.assertFalse(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))


class TestRefs(unittest.TestCase):

    def test_1(self):
        s1 = {
            "type": "array",
            "items": {"$ref": "#/definitions/positiveInteger"},
            "definitions": {
                "positiveInteger": {
                    "type": "integer",
                    "minimum": 0,
                    "exclusiveMinimum": True
                }
            }
        }
        s2 = {
            "type": "array",
            "items": {"$ref": "#/definitions/positiveInteger"},
            "definitions": {
                "positiveInteger": {
                    "type": "integer",
                    "minimum": -1,
                    "exclusiveMinimum": True
                }
            }
        }
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

        s3 = {"type": "array", "items": {"type": "integer"}}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s3, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s3, dialect=Dialect.DRAFT4))

        s4 = {"type": "array", "items": {"type": "string"}}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s4, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s4, dialect=Dialect.DRAFT4))

        s4 = {"type": "string"}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s4, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s4, dialect=Dialect.DRAFT4))

    def test_finite_value_can_prove_recursive_ref_target_membership(self):
        s1 = {"definitions": {"S": {"anyOf": [{"enum": [None]},
                                              {"allOf": [{"items": [{"$ref": "#/definitions/S"},
                                                                    {"$ref": "#/definitions/S"}],
                                                          "maxItems": 2,
                                                          "minItems": 2,
                                                          "type": "array"},
                                                         {"not": {"type": "array",
                                                                  "uniqueItems": True}}
                                                         ]
                                               }
                                              ]
                                    }
                              },
              "$ref": "#/definitions/S"
              }

        s2 = {"enum": [None]}

        self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))
        self.assertFalse(is_subschema({"enum": ["x"]}, s1, dialect=Dialect.DRAFT4))


class TestModernRefs(unittest.TestCase):
    def test_absolute_id_ref_within_same_document(self):
        s1 = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/schemas/root.json",
            "$defs": {
                "positiveInteger": {
                    "type": "integer",
                    "minimum": 0,
                }
            },
            "type": "array",
            "items": {
                "$ref": "https://example.com/schemas/root.json#/$defs/positiveInteger"
            },
        }
        s2 = {"type": "array", "items": {"type": "integer"}}

        with self.subTest("absolute same-document ref resolves"):
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT202012))

        with self.subTest("resolved absolute ref preserves constraints"):
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT202012))

    def test_embedded_resource_relative_ref(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/schemas/root.json",
            "$defs": {
                "embedded": {
                    "$id": "embedded.json",
                    "type": "string",
                    "pattern": "^a$",
                }
            },
            "$ref": "embedded.json",
        }

        with self.subTest("relative ref resolves to embedded resource"):
            self.assertTrue(
                is_subschema({"const": "a"}, schema, dialect=Dialect.DRAFT202012)
            )

        with self.subTest("embedded resource constraints are preserved"):
            self.assertFalse(
                is_subschema({"const": "b"}, schema, dialect=Dialect.DRAFT202012)
            )

    def test_unregistered_external_ref_is_unsupported(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/missing.json",
        }

        with self.assertRaises(UnsupportedProofError) as raised:
            is_empty(schema, dialect=Dialect.DRAFT202012)

        self.assertIn("could not resolve", raised.exception.reason)

    def test_unregistered_external_ref_does_not_fetch_network(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/missing.json",
        }

        with patch("socket.create_connection") as create_connection:
            with self.assertRaises(UnsupportedProofError):
                is_empty(schema, dialect=Dialect.DRAFT202012)

        create_connection.assert_not_called()

    def test_registered_external_resource_id_can_be_canonical(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/canonical.json",
        }
        resources = {
            "https://example.com/schemas/loader.json": {
                "$id": "https://example.com/schemas/canonical.json",
                "type": "string",
                "pattern": "^a$",
            }
        }

        self.assertTrue(
            is_subschema(
                {"const": "a"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )
        self.assertFalse(
            is_subschema(
                {"const": "b"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )

    def test_registered_external_resource_relative_ref_uses_root_base_uri(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/schemas/root.json",
            "$ref": "defs/name.json",
        }
        resources = {
            "https://example.com/schemas/defs/name.json": {
                "type": "string",
                "pattern": "^a$",
            }
        }

        self.assertTrue(
            is_subschema(
                {"const": "a"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )
        self.assertFalse(
            is_subschema(
                {"const": "b"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )

    def test_registered_external_resource_embedded_relative_ref(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/root.json",
        }
        resources = {
            "https://example.com/schemas/root.json": {
                "$id": "https://example.com/schemas/root.json",
                "$defs": {
                    "name": {
                        "$id": "defs/name.json",
                        "type": "string",
                        "pattern": "^a$",
                    }
                },
                "$ref": "defs/name.json",
            }
        }

        self.assertTrue(
            is_subschema(
                {"const": "a"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )
        self.assertFalse(
            is_subschema(
                {"const": "b"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )

    def test_registered_external_resource_can_reference_registered_sibling(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/root.json",
        }
        resources = {
            "https://example.com/schemas/root.json": {
                "$id": "https://example.com/schemas/root.json",
                "$ref": "defs/name.json",
            },
            "https://example.com/schemas/defs/name.json": {
                "type": "string",
                "pattern": "^a$",
            },
        }

        self.assertTrue(
            is_subschema(
                {"const": "a"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )
        self.assertFalse(
            is_subschema(
                {"const": "b"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )

    def test_registered_external_resource_confirmation_does_not_fetch_network(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/root.json",
        }
        resources = {
            "https://example.com/schemas/root.json": {
                "$id": "https://example.com/schemas/root.json",
                "$ref": "defs/name.json",
            },
            "https://example.com/schemas/defs/name.json": {
                "type": "string",
                "pattern": "^a$",
            },
        }

        with patch("socket.create_connection") as create_connection:
            self.assertFalse(
                is_subschema(
                    {"const": "b"},
                    schema,
                    dialect=Dialect.DRAFT202012,
                    resources=resources,
                )
            )

        create_connection.assert_not_called()

    def test_registered_external_resource_cycle_has_stable_diagnostic(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/a.json",
        }
        resources = {
            "https://example.com/schemas/a.json": {
                "$id": "https://example.com/schemas/a.json",
                "$ref": "b.json",
            },
            "https://example.com/schemas/b.json": {
                "$id": "https://example.com/schemas/b.json",
                "$ref": "a.json",
            },
        }

        with patch("socket.create_connection") as create_connection:
            with self.subTest("emptiness"):
                with self.assertRaises(UnsupportedProofError) as raised:
                    is_empty(
                        schema,
                        dialect=Dialect.DRAFT202012,
                        resources=resources,
                    )
                self.assertIn("recursive", raised.exception.reason)
                self.assertIn("a.json", raised.exception.reason)

            with self.subTest("subschema"):
                with self.assertRaises(UnsupportedProofError) as raised:
                    is_subschema(
                        {"const": 1},
                        schema,
                        dialect=Dialect.DRAFT202012,
                        resources=resources,
                    )
                self.assertIn("recursive", raised.exception.reason)
                self.assertIn("a.json", raised.exception.reason)

        create_connection.assert_not_called()

    def test_registered_external_resource_dialect_transition_is_unsupported(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/draft7.json",
        }
        resources = {
            "https://example.com/schemas/draft7.json": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "const": 1,
            },
        }

        with self.assertRaises(UnsupportedProofError) as raised:
            is_subschema(
                {"const": 2},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )

        self.assertIn("dialect transition", raised.exception.reason)

    def test_registered_external_boolean_resource_resolves(self):
        false_schema = {"$ref": "https://example.com/schemas/false"}
        true_schema = {"$ref": "https://example.com/schemas/true"}
        resources = {
            "https://example.com/schemas/false": False,
            "https://example.com/schemas/true": True,
        }

        self.assertTrue(
            is_empty(
                false_schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )
        self.assertTrue(
            is_subschema(
                {"const": 1},
                true_schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )
        self.assertFalse(
            is_subschema(
                {"const": 1},
                false_schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )

    def test_registered_external_resource_anchor_ref(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/root.json#name",
        }
        resources = {
            "https://example.com/schemas/root.json": {
                "$id": "https://example.com/schemas/root.json",
                "$defs": {
                    "name": {
                        "$anchor": "name",
                        "type": "string",
                        "pattern": "^a$",
                    }
                },
            }
        }

        self.assertTrue(
            is_subschema(
                {"const": "a"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )
        self.assertFalse(
            is_subschema(
                {"const": "b"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )

    def test_registered_external_resource_root_anchor_ref(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/root.json#name",
        }
        resources = {
            "https://example.com/schemas/root.json": {
                "$id": "https://example.com/schemas/root.json",
                "$anchor": "name",
                "type": "string",
                "pattern": "^a$",
            }
        }

        self.assertTrue(
            is_subschema(
                {"const": "a"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )
        self.assertFalse(
            is_subschema(
                {"const": "b"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )

    def test_registered_external_embedded_resource_root_anchor_ref(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/schemas/defs/name.json#name",
        }
        resources = {
            "https://example.com/schemas/root.json": {
                "$id": "https://example.com/schemas/root.json",
                "$defs": {
                    "name": {
                        "$id": "defs/name.json",
                        "$anchor": "name",
                        "type": "string",
                        "pattern": "^a$",
                    }
                },
            }
        }

        self.assertTrue(
            is_subschema(
                {"const": "a"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )
        self.assertFalse(
            is_subschema(
                {"const": "b"},
                schema,
                dialect=Dialect.DRAFT202012,
                resources=resources,
            )
        )

    def test_registered_external_missing_relative_ref_has_stable_diagnostic(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/schemas/root.json",
            "$ref": "defs/missing.json",
        }

        with self.assertRaises(UnsupportedProofError) as raised:
            is_empty(schema, dialect=Dialect.DRAFT202012, resources={})

        self.assertIn("could not resolve", raised.exception.reason)
        self.assertIn("defs/missing.json", raised.exception.reason)

    def test_guarded_recursive_object_ref_can_prove_shallow_type_boundary(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/$defs/node"}},
                }
            },
            "$ref": "#/$defs/node",
        }

        self.assertTrue(
            is_subschema(schema, {"type": "object"}, dialect=Dialect.DRAFT202012)
        )
        self.assertFalse(
            is_subschema(
                schema,
                {"type": "object", "required": ["child"]},
                dialect=Dialect.DRAFT202012,
            )
        )

    def test_guarded_recursive_array_ref_can_prove_shallow_type_boundary(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "node": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/node"},
                }
            },
            "$ref": "#/$defs/node",
        }

        self.assertTrue(
            is_subschema(schema, {"type": "array"}, dialect=Dialect.DRAFT202012)
        )

    def test_guarded_recursive_refs_can_prove_shallow_type_disjointness(self):
        object_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/$defs/node"}},
                }
            },
            "$ref": "#/$defs/node",
        }
        array_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "node": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/node"},
                }
            },
            "$ref": "#/$defs/node",
        }

        self.assertTrue(
            is_disjoint(object_schema, {"type": "string"}, dialect=Dialect.DRAFT202012)
        )
        self.assertTrue(
            is_disjoint(array_schema, {"type": "string"}, dialect=Dialect.DRAFT202012)
        )
        self.assertTrue(
            is_disjoint(object_schema, array_schema, dialect=Dialect.DRAFT202012)
        )

    def test_guarded_recursive_object_ref_can_prove_child_type_boundary(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/$defs/node"}},
                }
            },
            "$ref": "#/$defs/node",
        }

        self.assertTrue(
            is_subschema(
                schema,
                {"type": "object", "properties": {"child": {"type": "object"}}},
                dialect=Dialect.DRAFT202012,
            )
        )
        self.assertFalse(
            is_subschema(
                schema,
                {"type": "object", "properties": {"child": {"type": "string"}}},
                dialect=Dialect.DRAFT202012,
            )
        )

    def test_guarded_recursive_array_ref_can_prove_item_type_boundary(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "node": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/node"},
                }
            },
            "$ref": "#/$defs/node",
        }

        self.assertTrue(
            is_subschema(
                schema,
                {"type": "array", "items": {"type": "array"}},
                dialect=Dialect.DRAFT202012,
            )
        )
        self.assertFalse(
            is_subschema(
                schema,
                {"type": "array", "items": {"type": "string"}},
                dialect=Dialect.DRAFT202012,
            )
        )

    def test_defs_pointer_ref(self):
        s1 = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "positiveInteger": {
                    "type": "integer",
                    "minimum": 0,
                }
            },
            "type": "array",
            "items": {"$ref": "#/$defs/positiveInteger"},
        }
        s2 = {"type": "array", "items": {"type": "integer"}}

        with self.subTest("defs pointer ref resolves"):
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT202012))

        with self.subTest("resolved constraint is preserved"):
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT202012))

    def test_anchor_ref(self):
        s1 = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "positiveInteger": {
                    "$anchor": "positiveInteger",
                    "type": "integer",
                    "minimum": 0,
                }
            },
            "type": "array",
            "items": {"$ref": "#positiveInteger"},
        }
        s2 = {"type": "array", "items": {"type": "integer"}}

        with self.subTest("anchor ref resolves"):
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT202012))

        with self.subTest("resolved anchor constraint is preserved"):
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT202012))

    def test_anchor_ref_is_inactive_before_2019_09(self):
        schema = {
            "$defs": {
                "positiveInteger": {
                    "$anchor": "positiveInteger",
                    "type": "integer",
                    "minimum": 0,
                }
            },
            "$ref": "#positiveInteger",
        }

        with self.assertRaises(UnsupportedProofError):
            is_subschema({"const": 1}, schema, dialect=Dialect.DRAFT4)

    def test_plain_fragment_id_ref(self):
        s1 = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": {
                "positiveInteger": {
                    "$id": "#positiveInteger",
                    "type": "integer",
                    "minimum": 0,
                }
            },
            "type": "array",
            "items": {"$ref": "#positiveInteger"},
        }
        s2 = {"type": "array", "items": {"type": "integer"}}

        with self.subTest("plain fragment id ref resolves"):
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT7))

        with self.subTest("resolved id constraint is preserved"):
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT7))

    def test_dollar_id_ref_is_inactive_in_draft4(self):
        schema = {
            "definitions": {
                "positiveInteger": {
                    "$id": "#positiveInteger",
                    "type": "integer",
                    "minimum": 0,
                }
            },
            "$ref": "#positiveInteger",
        }

        with self.assertRaises(UnsupportedProofError):
            is_subschema({"const": 1}, schema, dialect=Dialect.DRAFT4)

    def test_draft4_id_ref_is_inactive_after_draft4(self):
        schema = {
            "definitions": {
                "positiveInteger": {
                    "id": "#positiveInteger",
                    "type": "integer",
                    "minimum": 0,
                }
            },
            "$ref": "#positiveInteger",
        }

        with self.assertRaises(UnsupportedProofError):
            is_subschema({"const": 1}, schema, dialect=Dialect.DRAFT6)

    def test_nested_ref_confirmation_reports_public_unsupported(self):
        ref_schema = {
            "$defs": {
                "target": {
                    "$defs": {"target": False},
                    "$ref": "#/$defs/target",
                }
            },
            "$ref": "#/$defs/target",
        }

        with self.assertRaises(UnsupportedProofError):
            is_empty(
                {"allOf": [{"type": "null"}, ref_schema]},
                dialect=Dialect.DRAFT202012,
            )

        try:
            is_disjoint({"type": "null"}, ref_schema, dialect=Dialect.DRAFT202012)
        except UnsupportedProofError:
            pass

    def test_dynamic_ref_is_resolved_by_ir_engine(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "stringNode": {
                    "$dynamicAnchor": "node",
                    "type": "string",
                }
            },
            "$dynamicRef": "#node",
        }

        with self.subTest("matching finite value is accepted"):
            self.assertTrue(is_subschema({"const": "x"}, schema, dialect=Dialect.DRAFT202012))

        with self.subTest("non-matching finite value is rejected"):
            self.assertFalse(is_subschema({"const": 1}, schema, dialect=Dialect.DRAFT202012))

    def test_recursive_ref_is_handled_by_ir_engine(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2019-09/schema",
            "$recursiveAnchor": True,
            "$recursiveRef": "#",
        }

        self.assertTrue(is_subschema(schema, {}, dialect=Dialect.DRAFT201909))

    def test_modern_ref_sibling_keywords_apply(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "number": {"type": "number"},
            },
            "$ref": "#/$defs/number",
            "minimum": 0,
        }
        expected = {"type": "number", "minimum": 0}

        with self.subTest("modern ref siblings are applied"):
            self.assertTrue(is_subschema(schema, expected, dialect=Dialect.DRAFT202012))
            self.assertTrue(is_subschema(expected, schema, dialect=Dialect.DRAFT202012))

        with self.subTest("the sibling constraint is not discarded"):
            self.assertFalse(
                is_subschema({"type": "number"}, schema, dialect=Dialect.DRAFT202012)
            )

    def test_draft7_ref_sibling_keywords_keep_sibling_ignored_behavior(self):
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": {
                "number": {"type": "number"},
            },
            "$ref": "#/definitions/number",
            "minimum": 0,
        }

        with self.subTest("Draft 7 ref siblings are ignored"):
            self.assertTrue(is_subschema(schema, {"type": "number"}, dialect=Dialect.DRAFT7))
            self.assertTrue(is_subschema({"type": "number"}, schema, dialect=Dialect.DRAFT7))

    def test_3(self):
        s1 = {
            "definitions": {
                "person": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/definitions/person"},
                            "default": []
                        }
                    }
                }
            },
            "type": "object",
            "properties": {
                "person": {"$ref": "#/definitions/person"}
            }
        }

        s2 = {"enum": [None]}

        with self.subTest():
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT4))
