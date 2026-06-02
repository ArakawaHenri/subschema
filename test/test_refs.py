import unittest

from subschema import Dialect, is_subschema
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

    def test_finite_value_can_be_proved_against_recursive_ref(self):
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

        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))


class TestModernRefs(unittest.TestCase):
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
