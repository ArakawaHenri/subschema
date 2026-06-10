import subschema.regex as regex_module

from subschema.dialects import Dialect
from subschema.prover import ProofBudgets, ProofContext, ProofOptions, ProofResult
from subschema.regex import RegexLanguage
from subschema.validator import validation_backend_for


def test_regex_language_uses_json_unanchored_semantics():
    language = RegexLanguage.from_json_regex("abc")

    assert language is not None
    assert language.matches("abc")
    assert language.matches("xabcx")
    assert not language.matches("ab")


def test_regex_language_proves_subset_disjoint_and_equivalent_fragments():
    a_prefix = RegexLanguage.from_json_regex("^a")
    a_plus_prefix = RegexLanguage.from_json_regex("^a+")
    b_prefix = RegexLanguage.from_json_regex("^b")

    assert a_prefix is not None
    assert a_plus_prefix is not None
    assert b_prefix is not None
    assert a_prefix.equivalent_to(a_plus_prefix) is True
    assert a_prefix.is_subset_of(a_plus_prefix) is True
    assert a_prefix.is_disjoint_from(b_prefix) is True


def test_regex_language_difference_witness_is_json_string():
    a_prefix = RegexLanguage.from_json_regex("^a")
    b_prefix = RegexLanguage.from_json_regex("^b")

    assert a_prefix is not None
    assert b_prefix is not None
    difference = a_prefix.difference(b_prefix)
    assert not isinstance(difference, ProofResult)
    witness = difference.witness()

    assert witness == "a"
    assert a_prefix.matches(witness)
    assert not b_prefix.matches(witness)


def test_regex_language_fast_witness_avoids_fsm(monkeypatch):
    def fail_fsm(_pattern):
        raise AssertionError("fast witness should not build an FSM")

    cases = (
        ("abc", "abc"),
        (r"^1\.0$", "1.0"),
        ("[0-9a-f]{64}", "0" * 64),
        ("[1-9a-zA-Z^OIl]{43,44}", "1" * 43),
        ("ab(c|de)f", "abcf"),
        ("ab?c", "ac"),
        ("ab*c", "ac"),
        ("ab+c", "abc"),
        ("a{2,}", "aa"),
    )
    context = ProofContext(
        Dialect.DRAFT7,
        ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)),
    )
    monkeypatch.setattr(regex_module, "_pattern_fsm", fail_fsm)

    for pattern, expected in cases:
        language = RegexLanguage.from_json_regex(pattern)

        assert not isinstance(language, ProofResult)
        assert language.witness(context) == expected
        assert regex_module._fast_json_regex_matches(pattern, expected) is True


def test_regex_language_fast_witness_covers_bigchaindb_representatives(monkeypatch):
    def fail_fsm(_pattern):
        raise AssertionError("BigchainDB representative should not build an FSM")

    backend = validation_backend_for(Dialect.DRAFT4)
    cases = (
        ("[0-9a-f]{64}", "0" * 64),
        ("[1-9a-zA-Z^OIl]{43,44}", "1" * 43),
        ("^[0-9]{1,20}$", "0"),
        (r"^1\.0$", "1.0"),
        (r"^2\.0$", "2.0"),
        ("^ed25519-sha-256$", "ed25519-sha-256"),
        ("^threshold-sha-256$", "threshold-sha-256"),
    )
    monkeypatch.setattr(regex_module, "_pattern_fsm", fail_fsm)

    for pattern, expected in cases:
        language = RegexLanguage.from_json_regex(pattern)

        assert not isinstance(language, ProofResult)
        assert language.witness() == expected
        assert backend.is_valid({"type": "string", "pattern": pattern}, expected)


def test_regex_language_whitespace_fast_witness_avoids_fsm(monkeypatch):
    def fail_fsm(_pattern):
        raise AssertionError("whitespace fast witness should not build an FSM")

    cases = (
        (r"\s", " "),
        (r"\S", "a"),
        (r"[\s]", " "),
        (r"[\S]", "a"),
        (r"[^\s]", "a"),
        (r"[^\S]", " "),
        (r"[\s\S]", "a"),
        (r"^[\s\S]$", "a"),
        (r"foo\sbar", "foo bar"),
        (r"\s+", " "),
        (r"\S{2}", "aa"),
    )
    context = ProofContext(
        Dialect.DRAFT7,
        ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)),
    )
    monkeypatch.setattr(regex_module, "_pattern_fsm", fail_fsm)

    for pattern, expected in cases:
        language = RegexLanguage.from_json_regex(pattern)

        assert not isinstance(language, ProofResult)
        assert language.witness(context) == expected


def test_regex_language_falls_back_to_fsm_for_unhandled_witness_pattern():
    context = ProofContext(
        Dialect.DRAFT7,
        ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)),
    )
    language = RegexLanguage.from_json_regex("a+?")

    assert not isinstance(language, ProofResult)
    proof = language.witness(context)

    assert isinstance(proof, ProofResult)
    assert proof.status == "resource_exhausted"
    assert proof.reason == "regex product exceeded proof work budget"


def test_regex_language_intersection_witness_uses_fsm_product():
    context = ProofContext(Dialect.DRAFT7, ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)))
    left = RegexLanguage.from_json_regex("^(a|b)")
    right = RegexLanguage.from_json_regex("^b")

    assert not isinstance(left, ProofResult)
    assert not isinstance(right, ProofResult)
    witness = left.intersection_witness(right)
    exhausted = left.intersection_witness(right, context)

    assert witness == "b"
    assert left.matches(witness)
    assert right.matches(witness)
    assert isinstance(exhausted, ProofResult)
    assert exhausted.status == "resource_exhausted"
    assert exhausted.reason == "regex product exceeded proof work budget"


def test_regex_language_end_anchor_uses_validation_backend_semantics():
    language = RegexLanguage.from_json_regex("^a$")

    assert not isinstance(language, ProofResult)
    assert language.matches("a")
    assert not language.matches("a\n")
    assert not language.matches("a\r")
    assert not language.matches("a\u2028")
    assert not language.matches("a\nx")


def test_regex_language_dot_matches_validation_backend_semantics():
    language = RegexLanguage.from_json_regex(".")
    backend = validation_backend_for(Dialect.DRAFT202012)
    schema = {"type": "string", "pattern": "."}

    assert not isinstance(language, ProofResult)
    for value in ("\n", "\r", "\u2028", "\u2029", "a"):
        assert language.matches(value) == backend.is_valid(schema, value)


def test_regex_language_ecma_whitespace_escapes_match_validation_backend():
    backend = validation_backend_for(Dialect.DRAFT202012)
    cases = (
        r"\s",
        r"\S",
        r"[\s]",
        r"[\S]",
        r"[^\s]",
        r"[^\S]",
        r"[\s\S]",
        r"[^\s\S]",
        r"^[\s\S]$",
        r"foo\sbar",
    )
    values = (
        " ",
        "\t",
        "\n",
        "\r",
        "\f",
        "\v",
        "\u00a0",
        "\ufeff",
        "\u1680",
        "\u2000",
        "\u2003",
        "\u2028",
        "\u2029",
        "\u202f",
        "\u3000",
        "a",
        "foo bar",
        "fooabar",
    )

    for pattern in cases:
        language = RegexLanguage.from_json_regex(pattern)
        schema = {"type": "string", "pattern": pattern}

        assert not isinstance(language, ProofResult)
        for value in values:
            assert language.matches(value) == backend.is_valid(schema, value)


def test_regex_language_escaped_anchor_literals_match_validation_backend():
    backend = validation_backend_for(Dialect.DRAFT202012)
    cases = (r"\^", r"\$", r"[\^]", r"[\$]")

    for pattern in cases:
        language = RegexLanguage.from_json_regex(pattern)
        schema = {"type": "string", "pattern": pattern}

        assert not isinstance(language, ProofResult)
        for value in ("^", "$", "A", ""):
            assert language.matches(value) == backend.is_valid(schema, value)


def test_regex_language_ecma_hex_unicode_literals_match_validation_backend():
    backend = validation_backend_for(Dialect.DRAFT202012)
    cases = (
        r"\x41",
        r"[\x41]",
        r"\u0041",
        r"[\u0041]",
        r"\u005E",
        r"[\u005E]",
        r"\x24",
        r"[\x24]",
        r"\u0028",
        r"\cA",
        r"[\cA]",
    )

    for pattern in cases:
        language = RegexLanguage.from_json_regex(pattern)
        schema = {"type": "string", "pattern": pattern}

        assert not isinstance(language, ProofResult)
        for value in ("A", "^", "$", "(", "\x01", "u0041", "x41", ""):
            assert language.matches(value) == backend.is_valid(schema, value)


def test_regex_language_spends_proof_work_units():
    context = ProofContext(Dialect.DRAFT7, ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)))
    a_prefix = RegexLanguage.from_json_regex("^(a|aa)")
    b_prefix = RegexLanguage.from_json_regex("^b")

    assert a_prefix is not None
    assert b_prefix is not None
    proof = a_prefix.is_disjoint_from(b_prefix, context)

    assert isinstance(proof, ProofResult)
    assert proof.status == "resource_exhausted"
    assert proof.reason == "regex product exceeded proof work budget"


def test_regex_language_short_circuits_identity_operations_without_budget():
    context = ProofContext(Dialect.DRAFT7, ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)))
    a_prefix = RegexLanguage.from_json_regex("^a")

    assert not isinstance(a_prefix, ProofResult)
    assert RegexLanguage.all().intersection(a_prefix, context) is a_prefix
    assert a_prefix.intersection(RegexLanguage.all(), context) is a_prefix
    assert RegexLanguage.empty().union(a_prefix, context) is a_prefix
    assert a_prefix.union(RegexLanguage.empty(), context) is a_prefix
    assert a_prefix.difference(RegexLanguage.empty(), context) is a_prefix
    assert RegexLanguage.empty().intersection(a_prefix, context).is_empty()
    assert a_prefix.difference(RegexLanguage.all(), context).is_empty()


def test_regex_language_short_circuits_equal_patterns_without_fsm(monkeypatch):
    def fail_fsm(_pattern):
        raise AssertionError("equal regex language checks should not build an FSM")

    pattern = (
        r"^ni:///sha-256;([a-zA-Z0-9_-]{0,86})[?]"
        r"(fpt=ed25519-sha-256(&)?|cost=[0-9]+(&)?|"
        r"subtypes=ed25519-sha-256(&)?){2,3}$"
    )
    lhs = RegexLanguage.from_json_regex(pattern)
    rhs = RegexLanguage.from_json_regex(pattern)
    context = ProofContext(
        Dialect.DRAFT7,
        ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)),
    )
    monkeypatch.setattr(regex_module, "_pattern_fsm", fail_fsm)

    assert not isinstance(lhs, ProofResult)
    assert not isinstance(rhs, ProofResult)
    assert lhs.is_subset_of(rhs, context) is True
    assert lhs.equivalent_to(rhs, context) is True
    assert lhs.is_disjoint_from(rhs, context) is False


def test_regex_language_short_circuits_literal_relations_without_fsm(monkeypatch):
    def fail_fsm(_pattern):
        raise AssertionError("literal regex relation fast path should not build an FSM")

    context = ProofContext(
        Dialect.DRAFT7,
        ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)),
    )
    exact = RegexLanguage.from_json_regex(r"^ed25519\x2dsha\x2d256$")
    exact_equivalent = RegexLanguage.from_json_regex("^ed25519-sha-256$")
    prefix = RegexLanguage.from_json_regex("^ed25519")
    other_prefix = RegexLanguage.from_json_regex("^threshold")

    assert not isinstance(exact, ProofResult)
    assert not isinstance(exact_equivalent, ProofResult)
    assert not isinstance(prefix, ProofResult)
    assert not isinstance(other_prefix, ProofResult)
    monkeypatch.setattr(regex_module, "_pattern_fsm", fail_fsm)

    assert exact.equivalent_to(exact_equivalent, context) is True
    assert exact.is_subset_of(prefix, context) is True
    assert prefix.is_subset_of(exact, context) is False
    assert prefix.is_disjoint_from(other_prefix, context) is True


def test_regex_language_short_circuits_charclass_repeat_relations_without_fsm(
    monkeypatch,
):
    def fail_fsm(_pattern):
        raise AssertionError(
            "charclass repeat regex relation fast path should not build an FSM"
        )

    context = ProofContext(
        Dialect.DRAFT7,
        ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)),
    )
    hex_64 = RegexLanguage.from_json_regex(r"^[0-9a-f]{64}$")
    hex_bounded = RegexLanguage.from_json_regex(r"^[0-9a-f]{1,128}$")
    digits_range = RegexLanguage.from_json_regex(r"^[0-9]{1,20}$")
    digits_escape_range = RegexLanguage.from_json_regex(r"^\d{1,20}$")
    letters = RegexLanguage.from_json_regex(r"^[g-z]{64}$")

    assert not isinstance(hex_64, ProofResult)
    assert not isinstance(hex_bounded, ProofResult)
    assert not isinstance(digits_range, ProofResult)
    assert not isinstance(digits_escape_range, ProofResult)
    assert not isinstance(letters, ProofResult)
    monkeypatch.setattr(regex_module, "_pattern_fsm", fail_fsm)

    assert hex_64.is_subset_of(hex_bounded, context) is True
    assert hex_bounded.is_subset_of(hex_64, context) is False
    assert digits_range.equivalent_to(digits_escape_range, context) is True
    assert hex_64.is_disjoint_from(letters, context) is True


def test_regex_language_large_regular_product_uses_work_budget():
    context = ProofContext(Dialect.DRAFT7, ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=10)))
    left = RegexLanguage.from_json_regex("^(a|b|c|d|e).*(x|y|z)$")
    right = RegexLanguage.from_json_regex("^(a|b|c|d|e).*(q|r|s)$")

    assert left is not None
    assert right is not None
    proof = left.is_disjoint_from(right, context)

    assert isinstance(proof, ProofResult)
    assert proof.status == "resource_exhausted"
    assert proof.reason == "regex product exceeded proof work budget"


def test_regex_language_keeps_non_regular_regex_unsupported():
    proof = RegexLanguage.from_json_regex("(?=a)")

    assert isinstance(proof, ProofResult)
    assert proof.status == "unsupported"
    assert proof.reason == "non-regular-regex: lookaround/zero-width assertions are unsupported"
    assert proof.diagnostics
    assert proof.diagnostics[0].category == "non-regular-regex"


def test_regex_language_reports_backreference_and_recursive_constructs_as_unreliable():
    for pattern, reason in (
        (r"(a)\1", "non-regular-regex: backreferences are unsupported"),
        (r"\b", "non-regular-regex: lookaround/zero-width assertions are unsupported"),
        (r"\B", "non-regular-regex: lookaround/zero-width assertions are unsupported"),
        (r"\0", "unsupported-regex-syntax: NUL/octal escapes are outside the supported validation backend"),
        (r"[\0]", "unsupported-regex-syntax: NUL/octal escapes are outside the supported validation backend"),
        ("(?R)", "non-regular-regex: recursive or conditional regex constructs are unsupported"),
        ("[", "unsupported-regex-syntax: regex syntax is outside the supported regular-language fragment"),
        ("a^", "unsupported-regex-syntax: anchors are only supported at the start/end of a pattern"),
        ("$a", "unsupported-regex-syntax: anchors are only supported at the start/end of a pattern"),
    ):
        proof = RegexLanguage.from_json_regex(pattern)

        assert isinstance(proof, ProofResult)
        assert proof.status == "unsupported"
        assert proof.reason == reason


def test_regex_language_does_not_treat_word_boundary_escape_inside_charclass_as_assertion():
    proof = RegexLanguage.from_json_regex(r"[\b]")

    assert isinstance(proof, ProofResult)
    assert proof.reason == "unsupported-regex-syntax: regex syntax is outside the supported regular-language fragment"
