from __future__ import annotations

from typing import Any

from hypothesis import assume, given, settings

from subschema import Dialect, UnsupportedProofError, canonicalize_schema, is_subschema
from test.proof_oracle import proof_engine_for_schemas
from subschema.validator import ValidationUnsupportedError
from test.proof_oracle import (
    assert_proved_false_result_is_confirmed,
    finite_universe_counterexample,
)
from test.schema_strategies import (
    JSON_ORACLE_INSTANCES,
    dialect_schema,
    dialect_schema_pair,
)


def _assert_no_backend_exception(call: Any) -> None:
    try:
        call()
    except UnsupportedProofError:
        return
    except ValidationUnsupportedError as err:
        raise AssertionError("public helper leaked ValidationUnsupportedError") from err
    except Exception as err:
        if type(err).__module__.partition(".")[0] in {
            "jsonschema",
            "jsonschema_rs",
            "referencing",
        }:
            raise AssertionError("public helper leaked validation backend error") from err
        raise


@given(dialect_schema())
@settings(max_examples=100, deadline=None)
def test_dialect_random_schema_is_valid_and_reflexive_when_provable(
    case: tuple[Dialect, Any],
) -> None:
    dialect, schema = case

    canonicalize_schema(schema, dialect=dialect)
    _assert_no_backend_exception(lambda: is_subschema(schema, schema, dialect=dialect))


@given(dialect_schema_pair())
@settings(max_examples=100, deadline=None)
def test_dialect_random_true_subschema_has_no_small_counterexample(
    case: tuple[Dialect, Any, Any],
) -> None:
    dialect, lhs, rhs = case

    try:
        result = is_subschema(lhs, rhs, dialect=dialect)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert (
            finite_universe_counterexample(
                lhs,
                rhs,
                dialect=dialect,
                universe=JSON_ORACLE_INSTANCES,
            )
            is None
        )


@given(dialect_schema_pair())
@settings(max_examples=80, deadline=None)
def test_dialect_random_generated_false_subschema_results_are_confirmed(
    case: tuple[Dialect, Any, Any],
) -> None:
    dialect, lhs, rhs = case
    proof = proof_engine_for_schemas(lhs, rhs, dialect=dialect).is_subschema(lhs, rhs)

    if proof.status == "proved_false":
        assert_proved_false_result_is_confirmed(lhs, rhs, proof, dialect)
