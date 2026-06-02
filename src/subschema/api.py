"""
Public API entrypoints.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any, cast

from subschema.dialects import (
    Dialect,
    resolve_dialect,
    strip_inactive_keywords_for_dialect,
    validate_supported_keywords,
)
from subschema.kernel.contracts import ProofBudgets, ProofOptions
from subschema.kernel.disjointness import schemas_are_disjoint
from subschema.kernel.engine import ProofEngine
from subschema.kernel.json_data import ensure_json_value
from subschema.kernel.normalization import normalize_boolean_schemas
from subschema.kernel.schemas import empty_schema_for_dialect
from subschema.kernel.validation import validate_raw_schema_for_dialect
from subschema.types import DialectInput, JSONSchema, JSONValue


def canonicalize_schema(
    schema: JSONSchema, *, dialect: DialectInput = None
) -> JSONSchema:
    """Return a modern normalized schema without embedding removed checker objects."""
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


def _resolve_proof_options(
    proof_options: ProofOptions | None = None,
    *,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
) -> ProofOptions | None:
    if not isinstance(endeavor, bool):
        raise TypeError("endeavor must be a boolean")
    if proof_options is not None:
        if not isinstance(proof_options, ProofOptions):
            raise TypeError("proof_options must be a ProofOptions instance")
        if endeavor or max_work is not None or timeout_ms is not None:
            raise ValueError(
                "proof_options cannot be combined with endeavor, max_work, or "
                "timeout_ms"
            )
        return proof_options
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
    return None


def is_subschema(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    proof_options: ProofOptions | None = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
) -> bool:
    """Entry point for schema subtype checking."""
    ensure_json_value(lhs, label="lhs schema")
    ensure_json_value(rhs, label="rhs schema")
    resolved_dialect = resolve_dialect(lhs, rhs, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    _validate_public_schema(rhs, resolved_dialect)
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return ProofEngine.for_schemas(
        lhs, rhs, dialect=resolved_dialect, options=options
    ).is_subschema_bool(lhs, rhs)


def meet_schemas(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    proof_options: ProofOptions | None = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
) -> JSONSchema:
    """Entry point for schema meet operation."""
    ensure_json_value(lhs, label="lhs schema")
    ensure_json_value(rhs, label="rhs schema")
    resolved_dialect = resolve_dialect(lhs, rhs, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    _validate_public_schema(rhs, resolved_dialect)
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return cast(JSONSchema, ProofEngine.for_schemas(
        lhs, rhs, dialect=resolved_dialect, options=options
    ).meet(lhs, rhs))


def join_schemas(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    proof_options: ProofOptions | None = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
) -> JSONSchema:
    """Entry point for schema join operation."""
    ensure_json_value(lhs, label="lhs schema")
    ensure_json_value(rhs, label="rhs schema")
    resolved_dialect = resolve_dialect(lhs, rhs, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    _validate_public_schema(rhs, resolved_dialect)
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return cast(JSONSchema, ProofEngine.for_schemas(
        lhs, rhs, dialect=resolved_dialect, options=options
    ).join(lhs, rhs))


def is_equivalent(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    proof_options: ProofOptions | None = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
) -> bool:
    """Entry point for schema equivalence check operation."""
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return is_subschema(
        lhs, rhs, dialect=dialect, proof_options=options
    ) and is_subschema(
        rhs,
        lhs,
        dialect=dialect,
        proof_options=options,
    )


def is_empty(
    schema: JSONSchema,
    *,
    dialect: DialectInput = None,
    proof_options: ProofOptions | None = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
) -> bool:
    """Return whether a schema accepts no JSON instances."""
    ensure_json_value(schema, label="schema")
    resolved_dialect = resolve_dialect(schema, dialect=dialect)
    _validate_public_schema(schema, resolved_dialect)
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    empty_schema = empty_schema_for_dialect(resolved_dialect)
    return ProofEngine.for_schemas(
        schema,
        empty_schema,
        dialect=resolved_dialect,
        options=options,
    ).is_subschema_bool(schema, empty_schema)


def is_disjoint(
    lhs: JSONSchema,
    rhs: JSONSchema,
    *,
    dialect: DialectInput = None,
    proof_options: ProofOptions | None = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
) -> bool:
    """Return whether two schemas accept no common JSON instance."""
    ensure_json_value(lhs, label="lhs schema")
    ensure_json_value(rhs, label="rhs schema")
    resolved_dialect = resolve_dialect(lhs, rhs, dialect=dialect)
    _validate_public_schema(lhs, resolved_dialect)
    _validate_public_schema(rhs, resolved_dialect)
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=resolved_dialect,
        options=options,
    )
    return schemas_are_disjoint(lhs, rhs, engine.context).as_bool(resolved_dialect)


def covers(
    lhs: JSONSchema,
    rhs_alternatives: Iterable[JSONSchema],
    *,
    dialect: DialectInput = None,
    proof_options: ProofOptions | None = None,
    endeavor: bool = False,
    max_work: int | None = None,
    timeout_ms: int | None = None,
) -> bool:
    """Return whether lhs is covered by any of the RHS alternative schemas."""
    rhs_schemas = _materialize_rhs_alternatives(rhs_alternatives)
    if not rhs_schemas:
        return is_empty(
            lhs,
            dialect=dialect,
            proof_options=proof_options,
            endeavor=endeavor,
            max_work=max_work,
            timeout_ms=timeout_ms,
        )
    rhs: JSONSchema = {"anyOf": cast(JSONValue, rhs_schemas)}
    return is_subschema(
        lhs,
        rhs,
        dialect=dialect,
        proof_options=proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
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
