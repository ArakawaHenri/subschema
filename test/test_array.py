import unittest

from subschema import Dialect, is_subschema


class TestArraySubtype(unittest.TestCase):

    def test_identity(self):
        s1 = {"type": "array",
              "minItems": 5, "maxItems:": 10}
        s2 = s1
        self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))

    def test_min_max(self):
        s1 = {"type": "array",
              "minItems": 5, "maxItems:": 10}
        s2 = {"type": "array",
              "minItems": 1, "maxItems:": 20}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_unique(self):
        s1 = {"type": "array", "uniqueItems": True}
        s2 = {"type": "array", "uniqueItems": False}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_unique_items_does_not_block_length_counterexamples(self):
        exact_two_unique = {"type": "array", "uniqueItems": True, "minItems": 2, "maxItems": 2}

        with self.subTest("unconstrained arrays can be too short"):
            self.assertFalse(is_subschema({"type": "array"}, exact_two_unique, dialect=Dialect.DRAFT4))
        with self.subTest("one-item arrays can be too short"):
            self.assertFalse(is_subschema({"type": "array", "minItems": 1, "maxItems": 1}, exact_two_unique, dialect=Dialect.DRAFT4))
        with self.subTest("two-item unique arrays violate maxItems one"):
            self.assertFalse(is_subschema(exact_two_unique, {"type": "array", "minItems": 1, "maxItems": 1}, dialect=Dialect.DRAFT4))

    def test_empty_items1(self):
        s1 = {"type": "array"}
        s2 = {"type": "array", "items": {}}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_empty_items2(self):
        s1 = {"type": "array", "additionalItems": False}
        s2 = {"type": "array", "items": {}}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_empty_items3(self):
        s1 = {"type": "array", "items": [{}, {}], "additionalItems": False}
        s2 = {"type": "array", "items": {}}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_empty_items4(self):
        s1 = {"type": "array", "items": [{}, {}], "additionalItems": True}
        s2 = {"type": "array", "items": {}}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_empty_items5(self):
        s1 = {"type": "array", "items": [{}, {}], "additionalItems": False}
        s2 = {"type": "array", "items": [{}], "additionalItems": False}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_dictItems_listItems1(self):
        s1 = {"type": "array", "items": {"type": "string"}}
        s2 = {"type": "array", "items": [{"type": "string"}]}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_dictItems_listItems2(self):
        s1 = {"type": "array", "items": {"type": "string"}}
        s2 = {"type": "array", "items": [
            {"type": "string"}, {"type": "string"}]}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_dictItems_listItems3(self):
        s1 = {"type": "array", "items": [{"type": "string"}]}
        s2 = {"type": "array", "items": [
            {"type": "string"}, {"type": "number"}]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_dictItems_listItems4(self):
        s1 = {"type": "array", "items": [
            {"type": "string"}], "additionalItems": False}
        s2 = {"type": "array", "items": [
            {"type": "string"}, {"type": "number"}]}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_dictItems_listItems5(self):
        s1 = {"type": "array", "items": [
            {"type": "string"}], "additionalItems": True}
        s2 = {"type": "array", "items": [
            {"type": "string"}, {"type": "number"}]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))

    def test_dictItems_listItems6(self):
        s1 = {"type": "array", "items": [
            {"type": "string"}], "additionalItems": {}}
        s2 = {"type": "array", "items": [
            {"type": "string"}, {"type": "number"}]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1, dialect=Dialect.DRAFT4))


class TestNestedArray(unittest.TestCase):

    def test_1(self):
        s1 = {
            '$schema': 'http://json-schema.org/draft-04/schema#',
            'type': 'array',
            'minItems': 150,
            'maxItems': 150,
            'items': {
                    'type': 'array',
                    'minItems': 4,
                    'maxItems': 4,
                    'items': {
                        'type': 'number'}}}

        s2 = {
            'description': 'Features; the outer array is over samples.',
            'anyOf': [{
                'type': 'array',
                'items': {
                        'type': 'string'}}, {
                'type': 'array',
                'items': {
                        'type': 'array',
                        'minItems': 1,
                        'maxItems': 1,
                        'items': {
                            'type': 'string'}}}]}

        self.assertFalse(is_subschema(s1, s2, dialect=Dialect.DRAFT4))
