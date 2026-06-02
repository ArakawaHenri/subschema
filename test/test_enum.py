import unittest

from subschema import is_subschema


class TestEnum(unittest.TestCase):

    def test_enum_simple1(self):
        s1 = {'enum': [1]}
        s2 = {'enum': [1, 2]}

        with self.subTest('LHS < RHS'):
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest('LHS > RHS'):
            self.assertFalse(is_subschema(s2, s1))

    def test_enum_simple2(self):
        s1 = {'enum': [True]}
        s2 = {'enum': [1, 2]}

        with self.subTest('LHS < RHS'):
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest('LHS > RHS'):
            self.assertFalse(is_subschema(s2, s1))

    def test_enum_simple3(self):
        s1 = {'type': 'integer', 'enum': [1, 2]}
        s2 = {'type': 'boolean', 'enum': [True]}

        with self.subTest('LHS < RHS'):
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest('LHS > RHS'):
            self.assertFalse(is_subschema(s2, s1))

    def test_enum_simple4(self):
        s1 = {'enum': ['1', 2]}
        s2 = {'enum': [1, '2']}

        with self.subTest('LHS < RHS'):
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest('LHS > RHS'):
            self.assertFalse(is_subschema(s2, s1))

    def test_enum_uninhabited1(self):
        s1 = {'type': 'string', 'enum': [1, 2]}
        s2 = {'type': 'string'}

        with self.subTest('LHS < RHS'):
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest('LHS > RHS'):
            self.assertFalse(is_subschema(s2, s1))

    def test_enum_uninhabited2(self):
        s1 = {'type': 'string', 'enum': [0, 1]}
        s2 = {'type': 'boolean', 'enum': [0]}

        with self.subTest('LHS < RHS'):
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest('LHS > RHS'):
            self.assertTrue(is_subschema(s2, s1))

    def test_enum_uninhabited3(self):
        s1 = {'enum': []}
        s2 = {'type': 'boolean'}

        with self.subTest('LHS < RHS'):
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest('LHS > RHS'):
            self.assertFalse(is_subschema(s2, s1))

    def test_enum_uninhabited4(self):
        s1 = {'enum': []}
        s2 = {'not': {}}

        with self.subTest('LHS < RHS'):
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest('LHS > RHS'):
            self.assertTrue(is_subschema(s2, s1))

    def test_enum_regex_string(self):
        s1 = {'enum': ['^*']}
        s2 = {'enum': ['^^']}

        with self.subTest('LHS < RHS'):
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest('LHS > RHS'):
            self.assertFalse(is_subschema(s2, s1))


class TestComplexEnum(unittest.TestCase):

    def test_array(self):
        s1 = {'enum': [[]]}
        s2 = {'type': 'array'}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))

        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_object(self):
        s1 = {'enum': [{'foo': 1}]}
        s2 = {'type': 'object'}

        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))

        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))
