import copy
import unittest

from subschema import Dialect, is_subschema


class TestObjectSubtype(unittest.TestCase):

    def test_identity(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"}
            }
        }
        s2 = copy.deepcopy(s1)
        s2["properties"]["gender"] = {
            "type": "string", "maxLength": 1, "enum": ["M", "F"]}
        self.assertTrue(is_subschema(s1, s2))

    def test_min_property(self):
        s1 = {"type": "object", "minProperties": 1}
        s2 = {"type": "object"}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_max_property(self):
        s1 = {"type": "object", "maxProperties": 3}
        s2 = {"type": "object"}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_optional_property_value_constraint_is_not_presence_only(self):
        lhs = {"type": "object", "maxProperties": 1}
        rhs = {"type": "object", "properties": {"a": {"type": "integer"}}}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_open_object_with_optional_property_can_violate_max_properties(self):
        lhs = {"type": "object", "properties": {"a": {"type": "integer"}}}
        rhs = {"type": "object", "maxProperties": 1}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_closed_single_optional_property_implies_max_properties_one(self):
        lhs = {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "additionalProperties": False,
        }
        rhs = {"type": "object", "maxProperties": 1}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_unconstrained_optional_property_does_not_restrict_open_object(self):
        lhs = {"type": "object", "minProperties": 1}
        rhs = {"type": "object", "properties": {"a": {}}}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_closed_pattern_properties_can_violate_max_properties_one(self):
        lhs = {
            "type": "object",
            "patternProperties": {"^a": {"type": "integer"}},
            "additionalProperties": False,
        }
        rhs = {"type": "object", "maxProperties": 1}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_closed_required_properties_imply_min_properties(self):
        lhs = {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "string"},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        }
        rhs = {"type": "object", "minProperties": 2}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_closed_finite_objects_are_finite_for_applicators(self):
        required_singleton = {
            "type": "object",
            "properties": {"a": {"const": 1}},
            "required": ["a"],
            "additionalProperties": False,
        }
        optional_singleton = {
            "type": "object",
            "properties": {"a": {"const": 1}},
            "additionalProperties": False,
        }
        finite_choice = {
            "type": "object",
            "properties": {"a": {"enum": [1, 2]}},
            "required": ["a"],
            "additionalProperties": False,
        }

        with self.subTest("required singleton object"):
            self.assertTrue(is_subschema(required_singleton, {"enum": [{"a": 1}]}, dialect=Dialect.DRAFT202012))
        with self.subTest("optional singleton property includes absent object"):
            self.assertTrue(is_subschema(optional_singleton, {"enum": [{}, {"a": 1}]}, dialect=Dialect.DRAFT202012))
        with self.subTest("finite property choices are covered by enum"):
            self.assertTrue(
                is_subschema(
                    finite_choice,
                    {"enum": [{"a": 1}, {"a": 2}]},
                    dialect=Dialect.DRAFT202012,
                )
            )
        with self.subTest("finite property choices can refute incomplete enum"):
            self.assertFalse(is_subschema(finite_choice, {"enum": [{"a": 1}]}, dialect=Dialect.DRAFT202012))
        with self.subTest("empty closed object is finite"):
            self.assertTrue(
                is_subschema(
                    {"type": "object", "properties": {}, "additionalProperties": False},
                    {"enum": [{}]},
                    dialect=Dialect.DRAFT202012,
                )
            )
        with self.subTest("optional false property remains absent-only"):
            self.assertTrue(
                is_subschema(
                    {"type": "object", "properties": {"a": False}, "additionalProperties": False},
                    {"enum": [{}]},
                    dialect=Dialect.DRAFT202012,
                )
            )

    def test_property_names_does_not_imply_min_properties(self):
        lhs = {"type": "object", "propertyNames": {"pattern": "^a$"}}
        rhs = {
            "type": "object",
            "minProperties": 1,
            "propertyNames": {"pattern": "^a$"},
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_min_max_property1(self):
        s1 = {"type": "object", "minProperties": 1, "maxProperties": 3}
        s2 = {"type": "object"}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_min_max_property2(self):
        s1 = {"type": "object", "minProperties": 1, "maxProperties": 3}
        s2 = {"type": "object", "maxProperties": 5}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_min_max_property3(self):
        s1 = {"type": "object", "minProperties": 1, "maxProperties": 3}
        s2 = {"type": "object", "minProperties": 5, "maxProperties": 2}

        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_min_max_property4(self):
        s1 = {"type": "object", "minProperties": 1, "maxProperties": 10}
        s2 = {"type": "object", "minProperties": 2, "maxProperties": 5}

        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_required1(self):
        s1 = {"type": "object", "minProperties": 1}
        s2 = {"type": "object", "required": ["p1"]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_require2(self):
        s1 = {"type": "object", "minProperties": 1}
        s2 = {"type": "object", "required": ["p1", "p2"]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_require3(self):
        s1 = {"type": "object", "maxProperties": 1}
        s2 = {"type": "object", "required": ["p1", "p2"]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_require4(self):
        s1 = {"type": "object", "required": ["p2", "p1"]}
        s2 = {"type": "object", "required": ["p1", "p2"]}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_require5(self):
        s1 = {"type": "object", "required": ["p1"]}
        s2 = {"type": "object", "required": ["p2"]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_require6(self):
        s1 = {"type": "object", "required": ["p1", "p2"]}
        s2 = {"type": "object", "required": ["p2"]}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_require7(self):
        s1 = {"type": "object", "required": ["p1", "p2"]}
        s2 = {"type": "object", "required": [
            "p2"], "additionalProperties": {"type": "boolean"}}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_simple_obj1(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
            }
        }
        s2 = copy.deepcopy(s1)
        del s2["properties"]["email"]
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_simple_obj2(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
            }
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
            },
            "patternProperties": {
                "^b.*b$": {"type": "boolean"}
            }
        }
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_simple_obj3(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
            },
            "patternProperties": {
                "b.*b": {"type": "boolean"}
            }
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
            },
            "patternProperties": {
                "^ba+b$": {"type": "boolean"}
            }
        }
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_simple_obj4(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
            },
            "patternProperties": {
                "b.*b": {"type": "integer"}
            }
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
            },
            "patternProperties": {
                "^ba+b$": {"type": "boolean"}
            }
        }
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_simple_obj5(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
            },
            "patternProperties": {
                "b.*b": {"type": "integer"}
            }
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
            },
            "patternProperties": {
                r"^b(\w)+b$": {"type": "integer", "minimum": 10}
            }
        }
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_tricky1(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
                "emaik": {"type": "string", "format": "email"}
            }
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]}
            },
            "patternProperties": {
                "^emai(l|k)$": {"type": "string"}
            },
            "required": ["name"]
        }
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_tricky2(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
                "emaik": {"type": "string", "format": "email"}
            }
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]}
            },
            "patternProperties": {
                "^emai(l|k)$": {"type": "string"}
            }
        }
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_tricky3(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
                "emaik": {"type": "string", "format": "email"}
            }
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]}
            },
            "patternProperties": {
                "emai": {"type": "string"}
            }
        }
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_tricky4(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
                "emaik": {"type": "string", "format": "email"}
            }
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]}
            },
            "patternProperties": {
                "emai": {"type": "string", "minLength": 10}
            }
        }
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_tricky5(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
                "emaik": {"type": "string", "format": "email"}
            },
            "additionalProperties": {"type": "boolean"}
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]}
            },
            "patternProperties": {
                "emai": {"type": "string", "minLength": 10}
            }
        }
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_tricky6(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
                "emaik": {"type": "string", "format": "email"}
            },
            "additionalProperties": {"type": "boolean"}
        }
        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]}
            },
            "patternProperties": {
                "emai": {"type": "string", "minLength": 10}
            },
            "additionalProperties": {"type": "boolean"}
        }
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_tricky7(self):
        s1 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]},
                "email": {"type": "string", "format": "email"},
                "emaik": {"type": "string", "format": "email"}
            },
            "additionalProperties": {"type": "string"}
        }

        s2 = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "gender": {"type": "string", "maxLength": 1, "enum": ["F", "M"]}
            },
            "patternProperties": {
                "emai": {"type": "string"}
            }

        }
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_required_with_real_schema(self):
        s1 = {'additionalProperties': False,
              'properties': {'X': {'$schema': 'http://json-schema.org/draft-04/schema#',
                                   'items': {'items': {'type': 'number'},
                                             'maxItems': 4,
                                             'minItems': 4,
                                             'type': 'array'},
                                   'maxItems': 150,
                                   'minItems': 150,
                                   'type': 'array'},
                             'y': {'$schema': 'http://json-schema.org/draft-04/schema#',
                                   'items': {'type': 'integer'},
                                   'maxItems': 150,
                                   'minItems': 150,
                                   'type': 'array'}},
              'required': ['X', 'y'],
              'type': 'object'}

        s2 = {'$schema': 'http://json-schema.org/draft-04/schema#',
              'additionalProperties': False,
              'description': 'Input data schema for training.',
              'properties': {'X': {'description': 'Features; the outer array is '
                                   'over samples.',
                                   'items': {'items': {'type': 'number'},
                                             'type': 'array'},
                                   'type': 'array'},
                             'y': {'description': 'Target class labels; the array '
                                   'is over samples.',
                                   'items': {'type': 'number'},
                                   'type': 'array'}},
              'required': ['X', 'y'],
              'type': 'object'}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_real_object_schema(self):
        s1 = {'additionalProperties': False,
              'properties': {'X': {'$schema': 'http://json-schema.org/draft-04/schema#',
                                   'items': {'items': [
                                                        {'description': 'sepal length (cm)',
                                                        'type': 'number'},
                                                       {'description': 'sepal width (cm)',
                                                        'type': 'number'},
                                                       {'description': 'petal length (cm)',
                                                        'type': 'number'},
                                                       {'description': 'petal width (cm)',
                                                        'type': 'number'}
                                                        ],
                                             'maxItems': 4,
                                             'minItems': 4,
                                             'type': 'array'},
                                   'maxItems': 120,
                                   'minItems': 120,
                                   'type': 'array'},
                             'y': {'$schema': 'http://json-schema.org/draft-04/schema#',
                                   'items': {'description': 'target',
                                             'type': 'integer'},
                                   'maxItems': 120,
                                   'minItems': 120,
                                   'type': 'array'}},
              'required': ['X', 'y'],
              'type': 'object'}

        s2 = {'$schema': 'http://json-schema.org/draft-04/schema#',
              'additionalProperties': False,
              'description': 'Input data schema for training.',
              'properties': {'X': {'description': 'Features; the outer array is over samples.',
                                   'items': {'items': {'type': 'number'},
                                             'type': 'array'},
                                   'type': 'array'},
                             'y': {'description': 'Target class labels; the array is over samples.',
                                   'items': {'type': 'number'},
                                   'type': 'array'}},
              'required': ['X', 'y'],
              'type': 'object'}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_property_top1(self):
        s1 = {"type":"object",
              "properties": {"name":{},
                             "age": {"type": "integer"}}}
        s2 = {"type":"object",
              "properties": {"age": {"type": "integer"}}}
        
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))

        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_property_top2(self):
        s1 = {"type":"object",
              "properties": {"name":{"type": ["number","integer", "string", "boolean","object","array", "null"]},
                             "age": {"type": "integer"}}}
        s2 = {"type":"object",
              "properties": {"age": {"type": "integer"},
                             "name": {}}}
        
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))

        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

class TestDependency(unittest.TestCase):

    def test_1(self):
        s1 = {'type': 'object', 'dependencies': {'foo': {'type':'string'}}}
        s2 = {'type': 'object'}

        with self.subTest('LHS < RHS'):
            self.assertTrue(is_subschema(s1, s2))
        # with self.subTest('"dependencies" not yet supported.'):
        #     self.assertFalse(is_subschema(s2, s2))
