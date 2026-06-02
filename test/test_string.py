import unittest

from subschema import is_subschema, is_equivalent


class TestStringSubtype(unittest.TestCase):

    def test_min_min(self):
        s1 = {"type": "string", "minLength": 5}
        s2 = {"type": "integer", "maxLength": 1}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_empty_pattern(self):
        s1 = {"type": "string", "pattern": ""}
        s2 = {"type": "string"}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_regx_range1(self):
        s1 = {"type": "string", "maxLength": 5, "pattern": "(ab)*"}
        s2 = {"type": "string", "pattern": "(ab){3}"}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_regx_range2(self):
        s1 = {"type": "string", "maxLength": 5, "pattern": "^(ab)*$"}
        s2 = {"type": "string", "pattern": "^(ab){0,3}$"}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_finite_regex_languages_are_finite_for_applicators(self):
        finite_regex = {"type": "string", "pattern": "^[ab]$"}
        exact_a = {"type": "string", "pattern": "^a$"}

        with self.subTest("small anchored character class is covered by enum"):
            self.assertTrue(is_subschema(finite_regex, {"enum": ["a", "b"]}))
        with self.subTest("small anchored character class can refute incomplete enum"):
            self.assertFalse(is_subschema(finite_regex, {"enum": ["a"]}))
        with self.subTest("oneOf overlap is filtered by concrete finite validation"):
            self.assertTrue(is_subschema({"oneOf": [finite_regex, {"enum": ["b"]}]}, exact_a))


class TestNotStringSubtype(unittest.TestCase):

    def test_str_not_str(self):
        s1 = {"type": "string"}
        s2 = {"not": s1}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_str_not_str_with_range(self):
        s1 = {"type": "string"}
        s2 = {"allOf": [{"type": "string"}, {
            "not": {"type": "string", "minLength": 2}}]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_str_not_str_with_range2(self):
        s1 = {"type": "string", "maxLength": 1}
        s2 = {"allOf": [{"type": "string"}, {
            "not": {"type": "string", "minLength": 2}}]}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_str_not_str_with_range3(self):
        s1 = {"type": "string", "minLength": 1, "maxLength": 5}
        s2 = {"allOf": [{"type": "string"}, {
            "not": {"type": "string", "minLength": 2}}]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_str_not_str_with_range4(self):
        s1 = {"type": "string", "minLength": 1, "maxLength": 5}
        s2 = {"allOf": [{"type": "string"}, {
            "not": {"type": "string", "minLength": 2}}]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_not_str_not_str1(self):
        s1 = {"not": {"type": "string"}}
        s2 = {"not": {"not": {"not": {"type": "string"}}}}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_not_str_not_str2(self):
        s1 = {"not": {"type": "string"}}
        s2 = {"not": {"not": {"type": "string"}}}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_all_str_not_str1(self):
        s1 = {"allOf": [{"type": "string"}, {
            "not": {"type": "string", "minLength": 2}}]}
        s2 = {"type": "string"}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_all_str_not_str2(self):
        s1 = {"allOf": [{"type": "string"}, {
            "not": {"type": "string", "minLength": 2}}]}
        s2 = {"type": "string", "maxLength": 1}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_all_str_not_str3(self):
        s1 = {"allOf": [{"type": "string"}, {
            "not": {"type": "string", "minLength": 2, "pattern": "ab"}}]}
        s2 = {"type": "string", "maxLength": 1}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_not_str_and_join_string(self):
        s1 = {"allOf": [{"type": "string"}, {
            "not": {"type": "string", "minLength": 5, "pattern": "a"}}]}
        s2 = {"anyOf": [{"type": "string", "maxLength": 4},
                        {"type": "string", "pattern": "[^a]"}]}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_equiv_multiple_case(self):
        s1 = {"type": ["string", "null"], "minLength": 1}
        s2 = {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]}
        s3 = {"anyOf": [{"type": "string", "pattern": ".+"}, {"enum": [None]}]}
        s4 = {"type": ["string", "null"], "pattern": ".{1,}"}
        s5 = {"type": ["string", "null"], "not": {"enum": [""]}}

        with self.subTest():
            self.assertTrue(is_equivalent(s1, s2))
        with self.subTest():
            self.assertFalse(is_equivalent(s1, s3))
        with self.subTest():
            self.assertFalse(is_equivalent(s1, s4))
        with self.subTest():
            self.assertTrue(is_equivalent(s1, s5))
        with self.subTest():
            self.assertFalse(is_equivalent(s2, s3))
        with self.subTest():
            self.assertFalse(is_equivalent(s2, s4))
        with self.subTest():
            self.assertTrue(is_equivalent(s2, s5))
        with self.subTest():
            self.assertTrue(is_equivalent(s3, s4))
        with self.subTest():
            self.assertFalse(is_equivalent(s3, s5))
        with self.subTest():
            self.assertFalse(is_equivalent(s4, s5))

        s6 = {"type": ["string", "null"], "pattern": ".{2,}"}
        s7 = {"type": ["string", "null"], "minLength": 2}

        with self.subTest():
            self.assertFalse(is_equivalent(s6, s7))
        with self.subTest():
            self.assertTrue(is_subschema(s6, s1))
        with self.subTest():
            self.assertFalse(is_subschema(s1, s7))

    def test_dot_pattern_does_not_match_line_terminator(self):
        min_one = {"type": "string", "minLength": 1}
        dot_one = {"type": "string", "pattern": ".+"}

        self.assertFalse(is_subschema(min_one, dot_one))
        self.assertTrue(is_subschema(dot_one, min_one))

    def test_dot_pattern_keeps_carriage_return_counterexample(self):
        dot = {"type": "string", "pattern": "."}
        no_carriage_return = {"type": "string", "pattern": "[^\r]"}

        self.assertFalse(is_subschema(dot, no_carriage_return))

    def test_ecma_unicode_escape_pattern_is_supported(self):
        escaped_a = {"type": "string", "pattern": r"^\u0041$"}
        literal_a = {"type": "string", "pattern": "^A$"}

        self.assertTrue(is_equivalent(escaped_a, literal_a))

    def test_ecma_control_escape_pattern_is_supported(self):
        control_a = {"type": "string", "pattern": r"^\cA$"}
        unicode_control_a = {"type": "string", "pattern": r"^\u0001$"}

        self.assertTrue(is_equivalent(control_a, unicode_control_a))

    def test_negated_pattern_is_not_a_length_complement(self):
        lhs = {"type": "string", "not": {"type": "string", "pattern": "^a$"}}
        rhs = {"not": {"type": "string", "minLength": 1}}
        typed_rhs = {"type": "string", "not": {"type": "string", "minLength": 1}}

        self.assertFalse(is_subschema(lhs, rhs))
        self.assertFalse(is_subschema(lhs, typed_rhs))


class TestStringEnumSubtype(unittest.TestCase):

    def test_enum1(self):
        s1 = {"type": "string", "enum": ["a"]}
        s2 = {"enum": ["a"]}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

    def test_enum2(self):
        s1 = {"type": "string", "enum": ["a"]}
        s2 = {"enum": ["a", "b"]}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_enum3(self):
        s1 = {"type": "string", "enum": ["a", ""]}
        s2 = {"enum": ["a", "b"]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_enum4(self):
        s1 = {"anyOf": [{"enum": ["a", "b", "c"]}, {"type": "string"}]}
        s2 = {"type": "string"}
        self.assertTrue(is_equivalent(s1, s2))

    def test_not_enum1(self):
        s1 = {"type": "string", "not": {"enum": ["a"]}}
        s2 = {"type": "string"}
        with self.subTest():
            self.assertTrue(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))

    def test_not_enum2(self):
        s1 = {"type": "string", "not": {"enum": ["a", "b"]}}
        s2 = {"type": "string", "enum": ["a", "b"]}
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))
        with self.subTest():
            self.assertFalse(is_subschema(s2, s1))
