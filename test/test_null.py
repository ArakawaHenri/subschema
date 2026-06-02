import unittest

from subschema import is_subschema


class TestNull(unittest.TestCase):

    def test_null1(self):
        s1 = {'enum': [None]}
        s2 = {'type': 'null'}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_null2(self):
        s1 = {'type': 'null'}
        s2 = {}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_null3(self):
        s1 = {'enum': [None]}
        s2 = {'enum': [0]}

        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))
