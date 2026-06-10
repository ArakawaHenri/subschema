from __future__ import annotations

from typing import Any

from hypothesis import assume, given, settings

from subschema import (
    Dialect,
    UnsupportedProofError,
    is_disjoint,
    is_empty,
    is_subschema,
    join_schemas,
    meet_schemas,
)
from test.proof_oracle import proof_engine_for_schemas
from test.proof_oracle import (
    assert_proved_false_result_is_confirmed,
    finite_universe_counterexample,
    finite_universe_shared_instance,
)
from test.schema_strategies import covered_schema, simple_schema


@given(simple_schema())
@settings(max_examples=100, deadline=None)
def test_schema_reflexivity(schema: Any) -> None:
    assert is_subschema(schema, schema)


@given(simple_schema(), simple_schema())
@settings(max_examples=100, deadline=None)
def test_meet_is_lower_bound(lhs: Any, rhs: Any) -> None:
    meet = meet_schemas(lhs, rhs)

    assert is_subschema(meet, lhs)
    assert is_subschema(meet, rhs)


@given(simple_schema(), simple_schema())
@settings(max_examples=100, deadline=None)
def test_join_is_upper_bound(lhs: Any, rhs: Any) -> None:
    join = join_schemas(lhs, rhs)

    assert is_subschema(lhs, join)
    assert is_subschema(rhs, join)


@given(simple_schema(), simple_schema())
@settings(max_examples=100, deadline=None)
def test_disjointness_matches_all_of_emptiness(lhs: Any, rhs: Any) -> None:
    try:
        disjoint = is_disjoint(lhs, rhs)
        empty = is_empty({"allOf": [lhs, rhs]})
    except UnsupportedProofError:
        assume(False)

    assert disjoint == empty


@given(covered_schema())
@settings(max_examples=200, deadline=None)
def test_covered_schema_reflexivity(schema: Any) -> None:
    assert is_subschema(schema, schema)


@given(simple_schema(), simple_schema())
@settings(max_examples=150, deadline=None)
def test_all_of_strengthening_is_monotone(base: Any, restriction: Any) -> None:
    assert is_subschema({"allOf": [base, restriction]}, base)


@given(simple_schema(), simple_schema())
@settings(max_examples=150, deadline=None)
def test_any_of_weakening_is_monotone(base: Any, alternative: Any) -> None:
    assert is_subschema(base, {"anyOf": [base, alternative]})


@given(covered_schema(), covered_schema())
@settings(max_examples=120, deadline=None)
def test_proved_subschema_has_no_small_counterexample(lhs: Any, rhs: Any) -> None:
    try:
        result = is_subschema(lhs, rhs)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert finite_universe_counterexample(lhs, rhs) is None


@given(covered_schema(), covered_schema())
@settings(max_examples=180, deadline=None)
def test_generated_proved_false_results_are_confirmed(
    lhs: Any, rhs: Any
) -> None:
    proof = proof_engine_for_schemas(
        lhs, rhs, dialect=Dialect.DRAFT202012
    ).is_subschema(lhs, rhs)

    if proof.status == "proved_false":
        assert_proved_false_result_is_confirmed(lhs, rhs, proof)


def test_large_array_false_certificate_is_verifiable() -> None:
    lhs = {
        "type": "array",
        "minItems": 10_000,
        "items": {"type": "string"},
    }
    rhs = {"type": "array", "items": {"type": "integer"}}

    proof = proof_engine_for_schemas(
        lhs, rhs, dialect=Dialect.DRAFT202012
    ).is_subschema(lhs, rhs)

    assert proof.status == "proved_false"
    assert proof.witness is None
    assert proof.certificate is not None
    assert_proved_false_result_is_confirmed(lhs, rhs, proof)


@given(covered_schema(), covered_schema())
@settings(max_examples=120, deadline=None)
def test_proved_disjointness_has_no_small_shared_instance(lhs: Any, rhs: Any) -> None:
    try:
        result = is_disjoint(lhs, rhs)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert finite_universe_shared_instance(lhs, rhs) is None


@given(covered_schema(), covered_schema())
@settings(max_examples=150, deadline=None)
def test_covered_meet_is_lower_bound(lhs: Any, rhs: Any) -> None:
    meet = meet_schemas(lhs, rhs)

    assert is_subschema(meet, lhs)
    assert is_subschema(meet, rhs)


@given(covered_schema(), covered_schema())
@settings(max_examples=150, deadline=None)
def test_covered_join_is_upper_bound(lhs: Any, rhs: Any) -> None:
    join = join_schemas(lhs, rhs)

    assert is_subschema(lhs, join)
    assert is_subschema(rhs, join)


@given(covered_schema(), covered_schema())
@settings(max_examples=150, deadline=None)
def test_covered_disjointness_matches_all_of_emptiness(
    lhs: Any, rhs: Any
) -> None:
    try:
        disjoint = is_disjoint(lhs, rhs)
        empty = is_empty({"allOf": [lhs, rhs]})
    except UnsupportedProofError:
        assume(False)

    assert disjoint == empty
