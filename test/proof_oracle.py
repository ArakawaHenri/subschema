from dataclasses import dataclass
from itertools import product
from typing import Any

from subschema.dialects import Dialect
from subschema.kernel import ProofEngine
from subschema.kernel.semantic import ConcreteEvaluator
from subschema.kernel.validation import validation_backend_for
from subschema.kernel.values import dedupe


@dataclass(frozen=True)
class ConcreteEvaluatorCase:
    name: str
    schema: Any
    instances: tuple[Any, ...]
    dialect: Dialect = Dialect.DRAFT202012


def small_json_universe(max_depth: int = 2) -> tuple[Any, ...]:
    scalars = (
        None,
        False,
        True,
        -1,
        0,
        1,
        2,
        0.5,
        "",
        "a",
        "aa",
        "b",
        "foo",
    )
    levels = [list(scalars)]
    values = list(scalars)
    keys = ("a", "b", "foo", "bar")

    for _depth in range(max_depth):
        representatives = levels[-1][:8]
        arrays = [[]]
        arrays.extend([value] for value in representatives)
        arrays.extend([left, right] for left, right in product(representatives[:4], repeat=2))

        objects = [{}]
        objects.extend({key: value} for key in keys for value in representatives)
        objects.extend({"a": left, "b": right} for left, right in product(representatives[:4], repeat=2))
        objects.extend({"foo": left, "bar": right} for left, right in product(representatives[:3], repeat=2))

        level = dedupe(arrays + objects)
        levels.append(level)
        values.extend(level)

    return tuple(dedupe(values))


SMALL_JSON_UNIVERSE = small_json_universe()


def validator(schema: Any, dialect: Dialect):
    return _BackendOracleValidator(schema, dialect)


@dataclass(frozen=True)
class _BackendOracleValidator:
    schema: Any
    dialect: Dialect

    def is_valid(self, instance: Any) -> bool:
        return validation_backend_for(self.dialect).is_valid(self.schema, instance)


def assert_concrete_evaluator_matches_validator(
    schema: Any,
    instances: tuple[Any, ...] | list[Any],
    dialect: Dialect = Dialect.DRAFT202012,
) -> None:
    evaluator = ConcreteEvaluator.for_schema(schema, dialect)
    schema_validator = validator(schema, dialect)
    for instance in instances:
        result = evaluator.validate(instance)
        assert result.is_supported, (instance, result.unsupported)
        assert result.valid == schema_validator.is_valid(instance), instance


def assert_concrete_evaluator_case(case: ConcreteEvaluatorCase) -> None:
    assert_concrete_evaluator_matches_validator(case.schema, case.instances, case.dialect)


def assert_concrete_evaluator_unsupported(
    schema: Any,
    instance: Any,
    dialect: Dialect = Dialect.DRAFT202012,
    reason_contains: str = "",
) -> None:
    result = ConcreteEvaluator.for_schema(schema, dialect).validate(instance)
    assert not result.is_supported, result
    if reason_contains:
        assert any(reason_contains in reason for reason in result.unsupported), result.unsupported


def assert_no_small_counterexample(lhs: Any, rhs: Any, dialect: Dialect) -> None:
    lhs_validator = validator(lhs, dialect)
    rhs_validator = validator(rhs, dialect)
    for instance in SMALL_JSON_UNIVERSE:
        assert not (
            lhs_validator.is_valid(instance) and not rhs_validator.is_valid(instance)
        ), instance


def assert_witness_validates(lhs: Any, rhs: Any, dialect: Dialect, witness: Any) -> None:
    assert validator(lhs, dialect).is_valid(witness)
    assert not validator(rhs, dialect).is_valid(witness)


def assert_proved_subschema(lhs: Any, rhs: Any, dialect: Dialect) -> None:
    proof = ProofEngine.for_schemas(lhs, rhs, dialect=dialect).is_subschema(
        lhs,
        rhs,
    )
    assert proof.status == "proved_true", proof


def assert_proved(
    lhs: Any,
    rhs: Any,
    dialect: Dialect,
    monkeypatch: Any | None = None,
) -> None:
    _ = monkeypatch
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=dialect)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "proved_true", proof
