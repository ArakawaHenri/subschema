"""
Test-only proof facade and validation oracles.

This module intentionally mirrors selected internal proof entrypoints so tests can
exercise IR/SAT behavior without importing underscore-prefixed production
helpers. It is not a public API compatibility layer.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product
from typing import Any, cast

import subschema.prover.driver as proof_driver
from subschema.compiler.ir import SchemaIRCompiler
from subschema.compiler.proof_pipeline import prepare_for_proof
from subschema.contracts import ProofOptions, ProofResult, certificate_is_verifiable
from subschema.dialects import Dialect, resolve_dialect
from subschema.ir import LogicalSchemaIR
from subschema.projection import projection_decision_schema
from subschema.prover.confirmation import confirm_valid
from subschema.prover.context import ProofContext
from subschema.prover.disjointness import (
    SharedWitnessConfirmation,
    ir_is_empty_exact,
    irs_are_disjoint,
)
from subschema.prover.formulas import DifferenceFormula
from subschema.prover.projection import ProjectionEngine
from subschema.prover.sat import EmptinessSolver
from subschema.prover.witnesses import build_ir_witness
from subschema.validator import validation_backend_for
from subschema.values import dedupe
from test.semantic_oracle import ConcreteEvaluator


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


class ProofOracleEngine:
    def __init__(
        self,
        dialect: Dialect,
        *,
        options: ProofOptions | None = None,
        resources: dict[str, Any] | None = None,
    ) -> None:
        self.context = ProofContext(
            dialect,
            ProofOptions() if options is None else options,
            resources={} if resources is None else resources,
        )
        self.dialect = self.context.dialect

    def is_subschema(self, lhs: Any, rhs: Any) -> ProofResult:
        lhs_validation = proof_driver.schema_validation_result(self.context, lhs, "lhs")
        if lhs_validation is not None:
            return lhs_validation
        rhs_validation = proof_driver.schema_validation_result(self.context, rhs, "rhs")
        if rhs_validation is not None:
            return rhs_validation
        return self.prepared_ir_proof(lhs, rhs)

    def is_subschema_bool(self, lhs: Any, rhs: Any) -> bool:
        return self.is_subschema(lhs, rhs).as_bool(self.dialect)

    def meet(self, lhs: Any, rhs: Any) -> Any:
        return projection_decision_schema(
            ProjectionEngine(self.context).meet_decision_ir(
                compile_schema_with_context(self.context, lhs),
                compile_schema_with_context(self.context, rhs),
            )
        )

    def join(self, lhs: Any, rhs: Any) -> Any:
        return projection_decision_schema(
            ProjectionEngine(self.context).join_decision_ir(
                compile_schema_with_context(self.context, lhs),
                compile_schema_with_context(self.context, rhs),
            )
        )

    def bounded_ir_proof(self, lhs: Any, rhs: Any) -> ProofResult:
        return bounded_ir_proof(self.context, lhs, rhs)

    def prepared_ir_proof(self, lhs: Any, rhs: Any) -> ProofResult:
        proof_lhs, proof_rhs = prepare_for_proof(
            lhs,
            rhs,
            dialect=self.context.dialect,
            resources=self.context.resources,
        )
        return bounded_ir_proof(self.context, proof_lhs, proof_rhs)


def proof_engine(
    dialect: Dialect,
    *,
    options: ProofOptions | None = None,
    resources: dict[str, Any] | None = None,
) -> ProofOracleEngine:
    return ProofOracleEngine(dialect, options=options, resources=resources)


def proof_engine_for_schemas(
    *schemas: Any,
    dialect: Dialect | str | None = None,
    options: ProofOptions | None = None,
    resources: dict[str, Any] | None = None,
) -> ProofOracleEngine:
    return proof_engine(
        resolve_dialect(*schemas, dialect=dialect),
        options=options,
        resources=resources,
    )


def compile_schema_with_context(context: ProofContext, schema: Any) -> LogicalSchemaIR:
    return SchemaIRCompiler(context.dialect).compile(
        schema,
        resources=context.resources,
    )


def difference_formula_from_schemas(
    lhs: Any,
    rhs: Any,
    dialect: Dialect,
    *,
    resources: dict[str, Any] | None = None,
) -> DifferenceFormula:
    compiler = SchemaIRCompiler(dialect)
    return DifferenceFormula(
        compiler.compile(lhs, resources=resources),
        compiler.compile(rhs, resources=resources),
    )


def bounded_ir_proof(context: ProofContext, lhs: Any, rhs: Any) -> ProofResult:
    return EmptinessSolver(context).prove_formula_difference_empty(
        difference_formula_from_schemas(
            lhs,
            rhs,
            context.dialect,
            resources=context.resources,
        )
    )


def schema_is_empty_exact(schema: Any, context: ProofContext) -> ProofResult:
    return ir_is_empty_exact(compile_schema_with_context(context, schema), context)


def schemas_are_disjoint(lhs: Any, rhs: Any, context: ProofContext) -> ProofResult:
    return schemas_are_disjoint_at_depth(lhs, rhs, context, depth=0)


def schemas_are_disjoint_at_depth(
    lhs: Any,
    rhs: Any,
    context: ProofContext,
    *,
    depth: int,
) -> ProofResult:
    if depth > 8:
        return ProofResult.unsupported("schema disjointness recursion limit was reached")

    lhs_ir = compile_schema_with_context(context, lhs)
    rhs_ir = compile_schema_with_context(context, rhs)

    finite_intersection = ProjectionEngine(context).finite_meet_projection_ir(
        lhs_ir, rhs_ir
    )
    if finite_intersection is False:
        return ProofResult.true()
    if finite_intersection is not None:
        finite_witness = build_ir_witness(
            compile_schema_with_context(context, finite_intersection),
            cast(Any, context),
        )
        if finite_witness.has_witness:
            proof = _proof_from_shared_witness(
                _confirmed_shared_witness_ir(
                    lhs_ir, rhs_ir, finite_witness.witness, context
                )
            )
            if proof is not None:
                return proof

    ir_disjointness = irs_are_disjoint(lhs_ir, rhs_ir, context)
    if ir_disjointness.status != "unsupported":
        return ir_disjointness

    intersection_witness = build_ir_witness(
        compile_schema_with_context(context, {"allOf": [lhs, rhs]}),
        cast(Any, context),
    )
    if intersection_witness.status == "resource_exhausted":
        return ProofResult.resource_exhausted(intersection_witness.reason)
    if intersection_witness.has_witness:
        proof = _proof_from_shared_witness(
            _confirmed_shared_witness_ir(
                lhs_ir, rhs_ir, intersection_witness.witness, context
            )
        )
        if proof is not None:
            return proof

    return ProofResult.unsupported("schema disjointness could not be proven exactly")


def _confirmed_shared_witness_ir(
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
    witness: Any,
    context: ProofContext,
) -> SharedWitnessConfirmation:
    lhs_confirmed = confirm_valid(lhs.source.to_source(), witness, context)
    if lhs_confirmed.status == "unsupported":
        return SharedWitnessConfirmation("unsupported", lhs_confirmed.proof)
    if lhs_confirmed.status == "rejected":
        return SharedWitnessConfirmation("rejected")
    rhs_confirmed = confirm_valid(rhs.source.to_source(), witness, context)
    if rhs_confirmed.status == "unsupported":
        return SharedWitnessConfirmation("unsupported", rhs_confirmed.proof)
    if rhs_confirmed.status == "confirmed":
        return SharedWitnessConfirmation("confirmed_false", ProofResult.false(witness))
    return SharedWitnessConfirmation("rejected")


def _proof_from_shared_witness(
    shared: SharedWitnessConfirmation,
) -> ProofResult | None:
    if shared.status == "confirmed_false" and shared.proof is not None:
        return shared.proof
    if shared.status == "unsupported" and shared.proof is not None:
        return shared.proof
    return None


def validator(schema: Any, dialect: Dialect):
    return _BackendOracleValidator(schema, dialect)


@dataclass(frozen=True)
class _BackendOracleValidator:
    schema: Any
    dialect: Dialect

    def is_valid(self, instance: Any) -> bool:
        return validation_backend_for(self.dialect).is_valid(self.schema, instance)


def backend_is_valid(
    schema: Any,
    instance: Any,
    dialect: Dialect = Dialect.DRAFT202012,
) -> bool:
    return validation_backend_for(dialect).is_valid(schema, instance)


def finite_universe_counterexample(
    lhs: Any,
    rhs: Any,
    dialect: Dialect = Dialect.DRAFT202012,
    universe: Iterable[Any] | None = None,
) -> Any | None:
    for instance in SMALL_JSON_UNIVERSE if universe is None else universe:
        if backend_is_valid(lhs, instance, dialect) and not backend_is_valid(
            rhs, instance, dialect
        ):
            return instance
    return None


def finite_universe_shared_instance(
    lhs: Any,
    rhs: Any,
    dialect: Dialect = Dialect.DRAFT202012,
    universe: Iterable[Any] | None = None,
) -> Any | None:
    for instance in SMALL_JSON_UNIVERSE if universe is None else universe:
        if backend_is_valid(lhs, instance, dialect) and backend_is_valid(
            rhs, instance, dialect
        ):
            return instance
    return None


def finite_universe_schema_instance(
    schema: Any,
    dialect: Dialect = Dialect.DRAFT202012,
    universe: Iterable[Any] | None = None,
) -> Any | None:
    for instance in SMALL_JSON_UNIVERSE if universe is None else universe:
        if backend_is_valid(schema, instance, dialect):
            return instance
    return None


def finite_universe_coverage_counterexample(
    lhs: Any,
    rhs_alternatives: Iterable[Any],
    dialect: Dialect = Dialect.DRAFT202012,
    universe: Iterable[Any] | None = None,
) -> Any | None:
    alternatives = tuple(rhs_alternatives)
    for instance in SMALL_JSON_UNIVERSE if universe is None else universe:
        if backend_is_valid(lhs, instance, dialect) and not any(
            backend_is_valid(rhs, instance, dialect) for rhs in alternatives
        ):
            return instance
    return None


def assert_proved_false_result_is_confirmed(
    lhs: Any,
    rhs: Any,
    proof: ProofResult,
    dialect: Dialect = Dialect.DRAFT202012,
) -> None:
    if proof.certificate is not None:
        assert certificate_is_verifiable(proof.certificate), proof
        return
    if backend_is_valid(lhs, proof.witness, dialect) and not backend_is_valid(
        rhs,
        proof.witness,
        dialect,
    ):
        return
    raise AssertionError(f"proved_false result is not confirmed: {proof!r}")


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
    proof = proof_engine_for_schemas(lhs, rhs, dialect=dialect).is_subschema(
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
    engine = proof_engine_for_schemas(lhs, rhs, dialect=dialect)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "proved_true", proof
