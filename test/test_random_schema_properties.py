from __future__ import annotations

from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from subschema import (
    UnsupportedProofError,
    canonicalize_schema,
    covers,
    is_disjoint,
    is_empty,
    is_subschema,
    join_schemas,
    meet_schemas,
)
from test.proof_oracle import proof_engine_for_schemas
from subschema.validator import ValidationUnsupportedError
from test.proof_oracle import (
    assert_proved_false_result_is_confirmed,
    backend_is_valid,
    finite_universe_counterexample,
    finite_universe_coverage_counterexample,
    finite_universe_schema_instance,
    finite_universe_shared_instance,
)
from test.schema_strategies import (
    random_external_resource_case,
    random_json_instance,
    random_resource_schema,
    random_schema,
)


def _assert_public_helper_has_no_backend_exception(call: Any) -> None:
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


@given(random_schema())
@settings(max_examples=150, deadline=None)
def test_random_schema_is_valid_and_reflexive_when_provable(schema: Any) -> None:
    canonicalize_schema(schema)

    try:
        assert is_subschema(schema, schema)
    except UnsupportedProofError:
        assume(False)


@given(random_schema(), random_schema())
@settings(max_examples=100, deadline=None)
def test_random_true_subschema_has_no_finite_universe_counterexample(
    lhs: Any, rhs: Any
) -> None:
    try:
        result = is_subschema(lhs, rhs)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert finite_universe_counterexample(lhs, rhs) is None


@given(random_schema(), random_schema())
@settings(max_examples=80, deadline=None)
def test_random_generated_false_subschema_results_are_confirmed(
    lhs: Any, rhs: Any
) -> None:
    proof = proof_engine_for_schemas(lhs, rhs).is_subschema(lhs, rhs)

    if proof.status == "proved_false":
        assert_proved_false_result_is_confirmed(lhs, rhs, proof)


@given(random_schema(), random_schema(), random_json_instance())
@settings(max_examples=80, deadline=None)
def test_random_true_subschema_accepts_random_lhs_instances(
    lhs: Any,
    rhs: Any,
    instance: Any,
) -> None:
    try:
        result = is_subschema(lhs, rhs)
    except UnsupportedProofError:
        assume(False)

    if result and backend_is_valid(lhs, instance):
        assert backend_is_valid(rhs, instance)


@given(random_schema(), random_schema())
@settings(max_examples=80, deadline=None)
def test_random_true_disjointness_has_no_finite_universe_shared_instance(
    lhs: Any, rhs: Any
) -> None:
    try:
        result = is_disjoint(lhs, rhs)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert finite_universe_shared_instance(lhs, rhs) is None


@given(random_schema())
@settings(max_examples=80, deadline=None)
def test_random_true_emptiness_rejects_finite_universe_instances(
    schema: Any,
) -> None:
    try:
        result = is_empty(schema)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert finite_universe_schema_instance(schema) is None


@given(random_schema(), st.lists(random_schema(), max_size=3))
@settings(max_examples=60, deadline=None)
def test_random_true_coverage_accepts_finite_universe_lhs_instances(
    lhs: Any,
    rhs_alternatives: list[Any],
) -> None:
    try:
        result = covers(lhs, rhs_alternatives)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert (
            finite_universe_coverage_counterexample(lhs, rhs_alternatives) is None
        )


@given(random_schema(), random_schema(), random_json_instance())
@settings(max_examples=60, deadline=None)
def test_random_meet_join_match_random_instance_semantics(
    lhs: Any,
    rhs: Any,
    instance: Any,
) -> None:
    meet = meet_schemas(lhs, rhs)
    join = join_schemas(lhs, rhs)

    if backend_is_valid(meet, instance):
        assert backend_is_valid(lhs, instance)
        assert backend_is_valid(rhs, instance)
    if backend_is_valid(lhs, instance) or backend_is_valid(rhs, instance):
        assert backend_is_valid(join, instance)


def test_count_shape_complement_does_not_ignore_property_names() -> None:
    lhs = {
        "not": {
            "type": "object",
            "properties": {},
            "required": [],
            "propertyNames": {"type": "string", "minLength": 0, "maxLength": 0},
        },
    }
    rhs = {
        "not": {
            "type": "object",
            "properties": {},
            "required": [],
            "maxProperties": 2,
        },
    }

    try:
        result = is_subschema(lhs, rhs)
    except UnsupportedProofError:
        return
    assert not result


def test_overapprox_scalar_fact_does_not_prove_negative_one_of() -> None:
    lhs = {
        "not": {
            "not": {
                "oneOf": [
                    {"type": ["string"]},
                    {"enum": [None, ""]},
                ]
            }
        }
    }
    rhs = {"not": {"if": False, "else": {"type": "string"}}}

    try:
        result = is_subschema(lhs, rhs)
    except UnsupportedProofError:
        return
    assert not result


@given(random_schema(), random_schema())
@settings(max_examples=120, deadline=None)
def test_random_disjointness_matches_all_of_emptiness(lhs: Any, rhs: Any) -> None:
    try:
        disjoint = is_disjoint(lhs, rhs)
        empty = is_empty({"allOf": [lhs, rhs]})
    except UnsupportedProofError:
        assume(False)

    assert disjoint == empty


@given(random_schema(), random_schema())
@settings(max_examples=120, deadline=None)
def test_random_meet_join_bounds_when_provable(lhs: Any, rhs: Any) -> None:
    meet = meet_schemas(lhs, rhs)
    join = join_schemas(lhs, rhs)

    try:
        assert is_subschema(meet, lhs)
        assert is_subschema(meet, rhs)
        assert is_subschema(lhs, join)
        assert is_subschema(rhs, join)
    except UnsupportedProofError:
        assume(False)


@given(random_resource_schema())
@settings(max_examples=80, deadline=None)
def test_random_resource_schemas_do_not_leak_backend_exceptions(
    schema: Any,
) -> None:
    _assert_public_helper_has_no_backend_exception(lambda: is_subschema(schema, schema))
    _assert_public_helper_has_no_backend_exception(
        lambda: is_empty({"allOf": [{"type": "null"}, schema]})
    )
    _assert_public_helper_has_no_backend_exception(
        lambda: is_disjoint({"type": "null"}, schema)
    )


@given(random_external_resource_case())
@settings(max_examples=25, deadline=None)
def test_random_external_resources_do_not_leak_backend_exceptions(
    case: tuple[Any, dict[str, Any]],
) -> None:
    schema, resources = case

    _assert_public_helper_has_no_backend_exception(
        lambda: is_subschema(schema, schema, resources=resources)
    )
    _assert_public_helper_has_no_backend_exception(
        lambda: is_empty(
            {"allOf": [{"type": "null"}, schema]},
            resources=resources,
        )
    )
    _assert_public_helper_has_no_backend_exception(
        lambda: is_disjoint({"type": "null"}, schema, resources=resources)
    )
