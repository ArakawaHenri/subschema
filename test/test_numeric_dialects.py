import unittest
from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from subschema import Dialect, is_disjoint, is_empty, is_equivalent, is_subschema
from subschema.exceptions import UnsupportedProofError
from subschema.validator import validation_backend_for
from test.proof_oracle import (
    assert_proved_false_result_is_confirmed,
    proof_engine_for_schemas,
    schema_is_empty_exact,
    schemas_are_disjoint,
)


DRAFT6_SCHEMA = "http://json-schema.org/draft-06/schema#"


class TestDraft6NumericBounds(unittest.TestCase):
    def test_number_exclusive_minimum(self):
        exclusive = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "exclusiveMinimum": 0,
        }
        inclusive = {"type": "number", "minimum": 0}

        with self.subTest("exclusive lower bound is stricter"):
            self.assertTrue(is_subschema(exclusive, inclusive))

        with self.subTest("inclusive lower bound admits the boundary"):
            self.assertFalse(is_subschema(inclusive, exclusive, dialect=Dialect.DRAFT6))

    def test_number_exclusive_maximum(self):
        exclusive = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "exclusiveMaximum": 10,
        }
        inclusive = {"type": "number", "maximum": 10}

        with self.subTest("exclusive upper bound is stricter"):
            self.assertTrue(is_subschema(exclusive, inclusive))

        with self.subTest("inclusive upper bound admits the boundary"):
            self.assertFalse(is_subschema(inclusive, exclusive, dialect=Dialect.DRAFT6))

    def test_integer_exclusive_minimum_normalizes_to_next_integer(self):
        exclusive = {
            "$schema": DRAFT6_SCHEMA,
            "type": "integer",
            "exclusiveMinimum": 5,
        }
        next_integer = {"type": "integer", "minimum": 6}

        self.assertTrue(is_equivalent(exclusive, next_integer, dialect=Dialect.DRAFT6))

    def test_integer_inclusive_boundary_is_not_subschema_of_number_exclusive_minimum(
        self,
    ):
        lhs = {"type": "integer", "minimum": 0}
        rhs = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "exclusiveMinimum": 0,
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_integer_exclusive_maximum_normalizes_to_previous_integer(self):
        exclusive = {
            "$schema": DRAFT6_SCHEMA,
            "type": "integer",
            "exclusiveMaximum": 5,
        }
        previous_integer = {"type": "integer", "maximum": 4}

        self.assertTrue(
            is_equivalent(exclusive, previous_integer, dialect=Dialect.DRAFT6)
        )

    def test_integer_inclusive_boundary_is_not_subschema_of_number_exclusive_maximum(
        self,
    ):
        lhs = {"type": "integer", "maximum": 0}
        rhs = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "exclusiveMaximum": 0,
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_weaker_exclusive_minimum_does_not_override_minimum(self):
        schema = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "minimum": 5,
            "exclusiveMinimum": 0,
        }

        self.assertTrue(
            is_equivalent(
                schema, {"type": "number", "minimum": 5}, dialect=Dialect.DRAFT6
            )
        )

    def test_weaker_exclusive_maximum_does_not_override_maximum(self):
        schema = {
            "$schema": DRAFT6_SCHEMA,
            "type": "number",
            "maximum": 5,
            "exclusiveMaximum": 10,
        }

        self.assertTrue(
            is_equivalent(
                schema, {"type": "number", "maximum": 5}, dialect=Dialect.DRAFT6
            )
        )

    def test_number_enum_keeps_integer_values(self):
        schema = {"type": "number", "enum": [1]}

        with self.subTest("integer JSON values are numbers"):
            self.assertTrue(is_subschema(schema, {"type": "number"}))

        with self.subTest("integer JSON values remain valid integers"):
            self.assertTrue(is_subschema(schema, {"type": "integer"}))

    def test_draft6_integer_enum_accepts_zero_fraction_number(self):
        schema = {
            "$schema": DRAFT6_SCHEMA,
            "type": "integer",
            "enum": [1.0],
        }

        with self.subTest("Draft 6 integer accepts zero-fraction numbers"):
            self.assertTrue(is_subschema(schema, {"type": "integer"}))

        with self.subTest("the enum is equivalent to the same const value"):
            self.assertTrue(
                is_equivalent(schema, {"const": 1.0}, dialect=Dialect.DRAFT6)
            )


class TestJSONNumberEdgeCases(unittest.TestCase):
    def test_negative_zero_matches_zero(self):
        self.assertTrue(is_equivalent({"const": -0.0}, {"const": 0.0}))

    def test_negative_zero_disjointness_uses_json_number_semantics(self):
        with self.subTest("negative zero is the same singleton as zero"):
            self.assertFalse(is_disjoint({"const": -0.0}, {"const": 0}))

        with self.subTest("zero is excluded by a positive exclusive lower bound"):
            self.assertTrue(
                is_disjoint(
                    {"const": -0.0},
                    {"type": "number", "exclusiveMinimum": 0},
                )
            )

    def test_zero_fraction_numbers_are_integers(self):
        with self.subTest("negative zero is an integer-valued JSON number"):
            self.assertTrue(is_subschema({"const": -0.0}, {"type": "integer"}))

        with self.subTest("positive zero-fraction value is integer-valued"):
            self.assertTrue(is_subschema({"const": 2.0}, {"type": "integer"}))

        with self.subTest("fractional value is not an integer"):
            self.assertFalse(is_subschema({"const": 2.5}, {"type": "integer"}))

    def test_integer_float_bounds_use_integer_valued_number_semantics(self):
        with self.subTest("fractional singleton interval has no integer value"):
            self.assertTrue(
                is_empty({"type": "integer", "minimum": 0.5, "maximum": 0.5})
            )

        with self.subTest("zero-fraction singleton interval has an integer value"):
            self.assertFalse(
                is_empty({"type": "integer", "minimum": 1.0, "maximum": 1.0})
            )

    def test_rational_multiple_of_subtyping(self):
        with self.subTest("quarter multiples are eighth multiples"):
            self.assertTrue(
                is_subschema(
                    {"type": "number", "multipleOf": 0.25},
                    {"type": "number", "multipleOf": 0.125},
                )
            )

        with self.subTest("quarter multiples are not half multiples"):
            self.assertFalse(
                is_subschema(
                    {"type": "number", "multipleOf": 0.25},
                    {"type": "number", "multipleOf": 0.5},
                )
            )

    def test_rational_multiple_of_disjointness_with_singleton_interval(self):
        multiples = {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "multipleOf": 0.5,
        }
        singleton = {"type": "number", "minimum": 0.25, "maximum": 0.25}

        self.assertTrue(is_disjoint(multiples, singleton))

    def test_decimal_multiple_of_uses_json_decimal_value_not_binary_float_noise(self):
        with self.subTest("0.3 is a JSON decimal multiple of 0.1"):
            self.assertTrue(
                is_subschema({"const": 0.3}, {"type": "number", "multipleOf": 0.1})
            )

        with self.subTest("0.3 is not a JSON decimal multiple of 0.2"):
            self.assertFalse(
                is_subschema({"const": 0.3}, {"type": "number", "multipleOf": 0.2})
            )

        with self.subTest("0.6 is a JSON decimal multiple of 0.2"):
            self.assertTrue(
                is_subschema({"const": 0.6}, {"type": "number", "multipleOf": 0.2})
            )


NUMERIC_EDGE_VALUES: tuple[int | float, ...] = (
    -2,
    -1,
    -0.0,
    0,
    0.0,
    0.1,
    0.2,
    0.25,
    0.3,
    0.5,
    0.6,
    1,
    1.0,
    1.5,
    2,
    2.0,
    2.5,
    3,
)
NUMERIC_EDGE_BOUNDS: tuple[int | float, ...] = (
    -2,
    -1,
    -0.0,
    0.0,
    0.1,
    0.2,
    0.25,
    0.3,
    0.5,
    1.0,
    2.0,
)
NUMERIC_MULTIPLES: tuple[int | float, ...] = (0.1, 0.2, 0.25, 0.5, 1, 2)


@st.composite
def numeric_edge_schema(draw: st.DrawFn) -> dict[str, Any]:
    lower_index = draw(st.integers(min_value=0, max_value=len(NUMERIC_EDGE_BOUNDS) - 1))
    upper_index = draw(
        st.integers(min_value=lower_index, max_value=len(NUMERIC_EDGE_BOUNDS) - 1)
    )
    schema: dict[str, Any] = {
        "type": draw(st.sampled_from(("integer", "number"))),
        "minimum": NUMERIC_EDGE_BOUNDS[lower_index],
        "maximum": NUMERIC_EDGE_BOUNDS[upper_index],
    }
    if draw(st.booleans()):
        schema["exclusiveMinimum"] = schema["minimum"]
    if draw(st.booleans()):
        schema["exclusiveMaximum"] = schema["maximum"]
    if draw(st.booleans()):
        schema["multipleOf"] = draw(st.sampled_from(NUMERIC_MULTIPLES))
    return schema


def _numeric_edge_counterexample(lhs: Any, rhs: Any) -> Any | None:
    backend = validation_backend_for(Dialect.DRAFT202012)
    for instance in NUMERIC_EDGE_VALUES:
        if backend.is_valid(lhs, instance) and not backend.is_valid(rhs, instance):
            return instance
    return None


def _numeric_edge_shared_instance(lhs: Any, rhs: Any) -> Any | None:
    backend = validation_backend_for(Dialect.DRAFT202012)
    for instance in NUMERIC_EDGE_VALUES:
        if backend.is_valid(lhs, instance) and backend.is_valid(rhs, instance):
            return instance
    return None


def _assert_numeric_shared_witness_is_confirmed(lhs: Any, rhs: Any, witness: Any) -> None:
    backend = validation_backend_for(Dialect.DRAFT202012)
    assert backend.is_valid(lhs, witness), witness
    assert backend.is_valid(rhs, witness), witness


@given(numeric_edge_schema(), numeric_edge_schema())
@settings(max_examples=160, deadline=None)
def test_numeric_edge_true_subschema_has_no_small_counterexample(
    lhs: Any, rhs: Any
) -> None:
    try:
        result = is_subschema(lhs, rhs)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert _numeric_edge_counterexample(lhs, rhs) is None


@given(numeric_edge_schema(), numeric_edge_schema())
@settings(max_examples=160, deadline=None)
def test_numeric_edge_true_disjointness_has_no_small_shared_instance(
    lhs: Any, rhs: Any
) -> None:
    try:
        result = is_disjoint(lhs, rhs)
    except UnsupportedProofError:
        assume(False)

    if result:
        assert _numeric_edge_shared_instance(lhs, rhs) is None


@given(numeric_edge_schema(), numeric_edge_schema())
@settings(max_examples=160, deadline=None)
def test_numeric_edge_false_subschema_witnesses_are_confirmed(
    lhs: Any, rhs: Any
) -> None:
    proof = proof_engine_for_schemas(
        lhs, rhs, dialect=Dialect.DRAFT202012
    ).is_subschema(lhs, rhs)

    if proof.status == "proved_false":
        assert_proved_false_result_is_confirmed(lhs, rhs, proof)


@given(numeric_edge_schema(), numeric_edge_schema())
@settings(max_examples=160, deadline=None)
def test_numeric_edge_false_disjointness_witnesses_are_confirmed(
    lhs: Any, rhs: Any
) -> None:
    engine = proof_engine_for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)
    proof = schemas_are_disjoint(lhs, rhs, engine.context)

    if proof.status == "proved_false":
        _assert_numeric_shared_witness_is_confirmed(lhs, rhs, proof.witness)


@given(numeric_edge_schema())
@settings(max_examples=160, deadline=None)
def test_numeric_edge_false_emptiness_witnesses_are_confirmed(schema: Any) -> None:
    engine = proof_engine_for_schemas(schema, dialect=Dialect.DRAFT202012)
    proof = schema_is_empty_exact(schema, engine.context)

    if proof.status == "proved_false":
        assert validation_backend_for(Dialect.DRAFT202012).is_valid(
            schema,
            proof.witness,
        )
