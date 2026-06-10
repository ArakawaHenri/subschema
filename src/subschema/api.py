"""
Public API entrypoints.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any, cast
from urllib.parse import urldefrag, urlparse

import subschema.prover.driver as proof_driver
from subschema.compiler.ir import SchemaIRCompiler
from subschema.compiler.proof_pipeline import prepare_for_proof
from subschema.compiler.schemas import empty_schema_for_dialect
from subschema.contracts import ProofBudgets, ProofOptions, ProofResult
from subschema.dialects import (
    Dialect,
    resolve_dialect,
    strip_inactive_keywords_for_dialect,
    validate_supported_keywords,
)
from subschema.ir import LogicalSchemaIR
from subschema.json_data import ensure_json_value
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
from subschema.prover.protocols import ProofContextProtocol
from subschema.prover.sat import EmptinessSolver
from subschema.prover.witnesses import build_ir_witness
from subschema.types import DialectInput, JSONResourceRegistry, JSONSchema, JSONValue
from subschema.validator import validate_raw_schema_for_dialect
from subschema.validator.normalization import normalize_boolean_schemas


class _SchemaProofEngine:
    def __init__(
        self,
        dialect: Dialect,
        *,
        options: ProofOptions | None = None,
        resources: Mapping[str, Any] | None = None,
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
        return self._prepared_ir_proof(lhs, rhs)

    def is_subschema_bool(self, lhs: Any, rhs: Any) -> bool:
        return self.is_subschema(lhs, rhs).as_bool(self.dialect)

    def meet(self, lhs: Any, rhs: Any) -> Any:
        return _meet_projection_with_context(self.context, lhs, rhs)

    def join(self, lhs: Any, rhs: Any) -> Any:
        return _join_projection_with_context(self.context, lhs, rhs)

    def _bounded_ir_proof(self, lhs: Any, rhs: Any) -> ProofResult:
        return _bounded_ir_proof(self.context, lhs, rhs)

    def _prepared_ir_proof(self, lhs: Any, rhs: Any) -> ProofResult:
        return _prepared_bounded_ir_proof(self.context, lhs, rhs)


def canonicalize_schema(
    schema: JSONSchema, *, dialect: DialectInput = None
) -> JSONSchema:
    """Return a normalized schema without embedding internal proof objects."""
    ensure_json_value(schema, label="schema")
    resolved_dialect = resolve_dialect(schema, dialect=dialect)
    _validate_public_schema(schema, resolved_dialect)
    schema = strip_inactive_keywords_for_dialect(
        normalize_boolean_schemas(deepcopy(schema)), resolved_dialect
    )
    validate_supported_keywords(schema, resolved_dialect)
    return cast(JSONSchema, schema)


def _validate_public_schema(schema: Any, dialect: Dialect) -> None:
    stripped = strip_inactive_keywords_for_dialect(schema, dialect)
    validate_raw_schema_for_dialect(stripped, dialect)


def _prepare_public_resources(
    resources: Mapping[str, JSONSchema] | None,
    dialect: Dialect,
) -> JSONResourceRegistry:
    if resources is None:
        return {}
    if not isinstance(resources, Mapping):
        raise TypeError("resources must be a mapping from URI to schema")
    prepared: JSONResourceRegistry = {}
    for uri, schema in resources.items():
        if not isinstance(uri, str):
            raise TypeError("resource registry keys must be strings")
        _validate_resource_registry_uri(uri)
        ensure_json_value(schema, label=f"resource {uri!r}")
        resource_dialect = resolve_dialect(schema, dialect=dialect)
        _validate_public_schema(schema, resource_dialect)
        prepared[uri] = schema
    return prepared


def _validate_resource_registry_uri(uri: str) -> None:
    if not uri:
        raise ValueError("resource registry keys must be absolute document URIs")
    parsed = urlparse(uri)
    if not parsed.scheme:
        raise ValueError("resource registry keys must be absolute document URIs")
    _, fragment = urldefrag(uri)
    if fragment:
        raise ValueError("resource registry keys must not include fragments")


def _proof_options_from_public_controls(
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
) -> ProofOptions:
    if not isinstance(endeavor, bool):
        raise TypeError("endeavor must be a boolean")
    if (max_work is not None or timeout_ms is not None) and not endeavor:
        raise ValueError("max_work and timeout_ms require endeavor=True")
    if endeavor:
        return ProofOptions(
            endeavor=endeavor,
            budgets=ProofBudgets(
                max_work=4096 if max_work is None else max_work,
                timeout_ms=1000 if timeout_ms is None else timeout_ms,
            ),
        )
    return ProofOptions()


def _is_subschema_resolved(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: Dialect,
    options: ProofOptions,
    resources: JSONResourceRegistry,
) -> bool:
    return _proof_engine_for_schemas(
        lhs, rhs, dialect=dialect, options=options, resources=resources
    ).is_subschema_bool(lhs, rhs)


def _is_empty_resolved(
    schema: JSONSchema,
    *,
    dialect: Dialect,
    options: ProofOptions,
    resources: JSONResourceRegistry,
) -> bool:
    empty_schema = empty_schema_for_dialect(dialect)
    engine = _proof_engine_for_schemas(
        schema,
        empty_schema,
        dialect=dialect,
        options=options,
        resources=resources,
    )
    exact_empty = _schema_is_empty_exact(schema, engine.context)
    if exact_empty.status != "unsupported":
        return exact_empty.as_bool(dialect)
    return engine.is_subschema_bool(schema, empty_schema)


def _proof_engine(
    dialect: Dialect,
    *,
    options: ProofOptions | None = None,
    resources: dict[str, Any] | None = None,
) -> _SchemaProofEngine:
    return _SchemaProofEngine(
        dialect,
        options=options,
        resources=resources,
    )


def _proof_engine_for_schemas(
    *schemas: Any,
    dialect: Dialect | str | None = None,
    options: ProofOptions | None = None,
    resources: dict[str, Any] | None = None,
) -> _SchemaProofEngine:
    return _proof_engine(
        resolve_dialect(*schemas, dialect=dialect),
        options=options,
        resources=resources,
    )


def _compile_schema_with_context(
    context: ProofContextProtocol,
    schema: Any,
) -> LogicalSchemaIR:
    return SchemaIRCompiler(context.dialect).compile(
        schema,
        resources=context.resources,
    )


def _bounded_ir_proof(
    context: ProofContextProtocol,
    lhs: Any,
    rhs: Any,
) -> ProofResult:
    formula = _difference_formula_from_schemas(
        lhs,
        rhs,
        context.dialect,
        resources=context.resources,
    )
    return EmptinessSolver(context).prove_formula_difference_empty(formula)


def _difference_formula_from_schemas(
    lhs: Any,
    rhs: Any,
    dialect: Dialect,
    *,
    resources: Mapping[str, Any] | None = None,
) -> DifferenceFormula:
    compiler = SchemaIRCompiler(dialect)
    return DifferenceFormula(
        compiler.compile(lhs, resources=resources),
        compiler.compile(rhs, resources=resources),
    )


def _prepared_bounded_ir_proof(
    context: ProofContextProtocol,
    lhs: Any,
    rhs: Any,
) -> ProofResult:
    proof_lhs, proof_rhs = _prepared_proof_schemas(context, lhs, rhs)
    return _bounded_ir_proof(context, proof_lhs, proof_rhs)


def _prepared_proof_schemas(
    context: ProofContextProtocol,
    lhs: Any,
    rhs: Any,
) -> tuple[Any, Any]:
    return prepare_for_proof(
        lhs,
        rhs,
        dialect=context.dialect,
        resources=context.resources,
    )


def _meet_projection_with_context(
    context: ProofContextProtocol,
    lhs: Any,
    rhs: Any,
) -> Any:
    return projection_decision_schema(
        ProjectionEngine(context).meet_decision_ir(
            _compile_schema_with_context(context, lhs),
            _compile_schema_with_context(context, rhs),
        )
    )


def _join_projection_with_context(
    context: ProofContextProtocol,
    lhs: Any,
    rhs: Any,
) -> Any:
    return projection_decision_schema(
        ProjectionEngine(context).join_decision_ir(
            _compile_schema_with_context(context, lhs),
            _compile_schema_with_context(context, rhs),
        )
    )


def _schema_is_empty_exact(
    schema: Any,
    context: ProofContextProtocol,
) -> ProofResult:
    return ir_is_empty_exact(_compile_schema_with_context(context, schema), context)


def _schemas_are_disjoint(
    lhs: Any,
    rhs: Any,
    context: ProofContextProtocol,
) -> ProofResult:
    return _schemas_are_disjoint_at_depth(lhs, rhs, context, depth=0)


def _schemas_are_disjoint_at_depth(
    lhs: Any,
    rhs: Any,
    context: ProofContextProtocol,
    *,
    depth: int,
) -> ProofResult:
    if depth > 8:
        return ProofResult.unsupported(
            "schema disjointness recursion limit was reached"
        )

    lhs_ir = _compile_schema_with_context(context, lhs)
    rhs_ir = _compile_schema_with_context(context, rhs)

    finite_intersection = ProjectionEngine(context).finite_meet_projection_ir(
        lhs_ir, rhs_ir
    )
    if finite_intersection is False:
        return ProofResult.true()
    if finite_intersection is not None:
        finite_witness = build_ir_witness(
            _compile_schema_with_context(context, finite_intersection),
            cast(Any, context),
        )
        if finite_witness.has_witness:
            shared = _confirmed_shared_witness_ir(
                lhs_ir, rhs_ir, finite_witness.witness, context
            )
            proof = _proof_from_shared_witness(shared)
            if proof is not None:
                return proof

    ir_disjointness = irs_are_disjoint(lhs_ir, rhs_ir, context)
    if ir_disjointness.status != "unsupported":
        return ir_disjointness

    intersection_witness = build_ir_witness(
        _compile_schema_with_context(context, {"allOf": [lhs, rhs]}),
        cast(Any, context),
    )
    if intersection_witness.status == "resource_exhausted":
        return ProofResult.resource_exhausted(intersection_witness.reason)
    if intersection_witness.has_witness:
        shared = _confirmed_shared_witness_ir(
            lhs_ir, rhs_ir, intersection_witness.witness, context
        )
        proof = _proof_from_shared_witness(shared)
        if proof is not None:
            return proof

    return ProofResult.unsupported("schema disjointness could not be proven exactly")


def _confirmed_shared_witness_ir(
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
    witness: Any,
    context: ProofContextProtocol,
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


def is_subschema(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
    resources: Mapping[str, JSONSchema] | None = None,
) -> bool:
    """Entry point for schema subtype checking."""
    ensure_json_value(lhs, label="lhs schema")
    ensure_json_value(rhs, label="rhs schema")
    resolved_dialect = resolve_dialect(lhs, rhs, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    _validate_public_schema(rhs, resolved_dialect)
    prepared_resources = _prepare_public_resources(resources, resolved_dialect)
    options = _proof_options_from_public_controls(
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return _is_subschema_resolved(
        lhs,
        rhs,
        dialect=resolved_dialect,
        options=options,
        resources=prepared_resources,
    )


def meet_schemas(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
    resources: Mapping[str, JSONSchema] | None = None,
) -> JSONSchema:
    """Entry point for schema meet operation."""
    ensure_json_value(lhs, label="lhs schema")
    ensure_json_value(rhs, label="rhs schema")
    resolved_dialect = resolve_dialect(lhs, rhs, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    _validate_public_schema(rhs, resolved_dialect)
    prepared_resources = _prepare_public_resources(resources, resolved_dialect)
    options = _proof_options_from_public_controls(
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return cast(
        JSONSchema,
        _proof_engine_for_schemas(
            lhs,
            rhs,
            dialect=resolved_dialect,
            options=options,
            resources=prepared_resources,
        ).meet(lhs, rhs),
    )


def join_schemas(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
    resources: Mapping[str, JSONSchema] | None = None,
) -> JSONSchema:
    """Entry point for schema join operation."""
    ensure_json_value(lhs, label="lhs schema")
    ensure_json_value(rhs, label="rhs schema")
    resolved_dialect = resolve_dialect(lhs, rhs, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    _validate_public_schema(rhs, resolved_dialect)
    prepared_resources = _prepare_public_resources(resources, resolved_dialect)
    options = _proof_options_from_public_controls(
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return cast(
        JSONSchema,
        _proof_engine_for_schemas(
            lhs,
            rhs,
            dialect=resolved_dialect,
            options=options,
            resources=prepared_resources,
        ).join(lhs, rhs),
    )


def is_equivalent(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
    resources: Mapping[str, JSONSchema] | None = None,
) -> bool:
    """Entry point for schema equivalence check operation."""
    ensure_json_value(lhs, label="lhs schema")
    ensure_json_value(rhs, label="rhs schema")
    resolved_dialect = resolve_dialect(lhs, rhs, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    _validate_public_schema(rhs, resolved_dialect)
    prepared_resources = _prepare_public_resources(resources, resolved_dialect)
    options = _proof_options_from_public_controls(
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return _is_subschema_resolved(
        lhs,
        rhs,
        dialect=resolved_dialect,
        options=options,
        resources=prepared_resources,
    ) and _is_subschema_resolved(
        rhs,
        lhs,
        dialect=resolved_dialect,
        options=options,
        resources=prepared_resources,
    )


def is_empty(
    schema: JSONSchema,
    *,
    dialect: DialectInput = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
    resources: Mapping[str, JSONSchema] | None = None,
) -> bool:
    """Return whether a schema accepts no JSON instances."""
    ensure_json_value(schema, label="schema")
    resolved_dialect = resolve_dialect(schema, dialect=dialect)
    _validate_public_schema(schema, resolved_dialect)
    prepared_resources = _prepare_public_resources(resources, resolved_dialect)
    options = _proof_options_from_public_controls(
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    if prepared_resources:
        return _is_subschema_resolved(
            schema,
            empty_schema_for_dialect(resolved_dialect),
            dialect=resolved_dialect,
            options=options,
            resources=prepared_resources,
        )
    return _is_empty_resolved(
        schema,
        dialect=resolved_dialect,
        options=options,
        resources=prepared_resources,
    )


def is_disjoint(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
    resources: Mapping[str, JSONSchema] | None = None,
) -> bool:
    """Return whether two schemas accept no common JSON instance."""
    ensure_json_value(lhs, label="lhs schema")
    ensure_json_value(rhs, label="rhs schema")
    resolved_dialect = resolve_dialect(lhs, rhs, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    _validate_public_schema(rhs, resolved_dialect)
    prepared_resources = _prepare_public_resources(resources, resolved_dialect)
    options = _proof_options_from_public_controls(
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    if prepared_resources:
        return _is_subschema_resolved(
            lhs,
            {"not": rhs},
            dialect=resolved_dialect,
            options=options,
            resources=prepared_resources,
        )
    engine = _proof_engine_for_schemas(
        lhs,
        rhs,
        dialect=resolved_dialect,
        options=options,
        resources=prepared_resources,
    )
    return _schemas_are_disjoint(lhs, rhs, engine.context).as_bool(resolved_dialect)


def covers(
    lhs: JSONSchema,
    rhs_alternatives: Iterable[JSONSchema],
    *,
    dialect: DialectInput = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
    resources: Mapping[str, JSONSchema] | None = None,
) -> bool:
    """Return whether lhs is covered by any of the RHS alternative schemas."""
    rhs_schemas = _materialize_rhs_alternatives(rhs_alternatives)
    ensure_json_value(lhs, label="lhs schema")
    resolved_dialect = resolve_dialect(lhs, *rhs_schemas, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    for rhs_schema in rhs_schemas:
        _validate_public_schema(rhs_schema, resolved_dialect)
    prepared_resources = _prepare_public_resources(resources, resolved_dialect)
    options = _proof_options_from_public_controls(
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    if not rhs_schemas:
        return _is_empty_resolved(
            lhs,
            dialect=resolved_dialect,
            options=options,
            resources=prepared_resources,
        )
    rhs: JSONSchema = {"anyOf": cast(JSONValue, rhs_schemas)}
    _validate_public_schema(rhs, resolved_dialect)
    return _is_subschema_resolved(
        lhs,
        rhs,
        dialect=resolved_dialect,
        options=options,
        resources=prepared_resources,
    )


def _materialize_rhs_alternatives(
    rhs_alternatives: Iterable[JSONSchema],
) -> list[JSONSchema]:
    if isinstance(rhs_alternatives, dict | str | bytes):
        raise TypeError("rhs_alternatives must be an iterable of schemas")
    try:
        return list(rhs_alternatives)
    except TypeError as err:
        raise TypeError("rhs_alternatives must be an iterable of schemas") from err
