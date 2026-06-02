"""
Public API entrypoints.
"""

from copy import deepcopy

from subschema.dialects import (
    resolve_dialect,
    strip_inactive_keywords_for_dialect,
    validate_supported_keywords,
)
from subschema.kernel.contracts import ProofBudgets, ProofOptions
from subschema.kernel.engine import ProofEngine
from subschema.kernel.json_data import ensure_json_value
from subschema.kernel.normalization import normalize_boolean_schemas
from subschema.kernel.validation import validate_raw_schema_for_dialect


def canonicalize_schema(s, *, dialect=None):
    """Return a modern normalized schema without embedding removed checker objects."""
    ensure_json_value(s, label="schema")
    resolved_dialect = resolve_dialect(s, dialect=dialect)
    _validate_public_schema(s, resolved_dialect)
    schema = strip_inactive_keywords_for_dialect(
        normalize_boolean_schemas(deepcopy(s)), resolved_dialect
    )
    validate_supported_keywords(schema, resolved_dialect)
    return schema


def _validate_public_schema(schema, dialect):
    stripped = strip_inactive_keywords_for_dialect(schema, dialect)
    validate_raw_schema_for_dialect(stripped, dialect)


def _resolve_proof_options(
    proof_options=None,
    *,
    endeavor=False,
    max_work=None,
    timeout_ms=None,
):
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
    s1,
    s2,
    *,
    dialect=None,
    proof_options=None,
    endeavor=False,
    max_work=None,
    timeout_ms=None,
):
    """Entry point for schema subtype checking."""
    ensure_json_value(s1, label="lhs schema")
    ensure_json_value(s2, label="rhs schema")
    resolved_dialect = resolve_dialect(s1, s2, dialect=dialect)
    _validate_public_schema(s1, resolved_dialect)
    _validate_public_schema(s2, resolved_dialect)
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return ProofEngine.for_schemas(
        s1, s2, dialect=resolved_dialect, options=options
    ).is_subschema_bool(s1, s2)


def meet_schemas(
    s1,
    s2,
    *,
    dialect=None,
    proof_options=None,
    endeavor=False,
    max_work=None,
    timeout_ms=None,
):
    """Entry point for schema meet operation."""
    ensure_json_value(s1, label="lhs schema")
    ensure_json_value(s2, label="rhs schema")
    resolved_dialect = resolve_dialect(s1, s2, dialect=dialect)
    _validate_public_schema(s1, resolved_dialect)
    _validate_public_schema(s2, resolved_dialect)
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return ProofEngine.for_schemas(
        s1, s2, dialect=resolved_dialect, options=options
    ).meet(s1, s2)


def join_schemas(
    s1,
    s2,
    *,
    dialect=None,
    proof_options=None,
    endeavor=False,
    max_work=None,
    timeout_ms=None,
):
    """Entry point for schema join operation."""
    ensure_json_value(s1, label="lhs schema")
    ensure_json_value(s2, label="rhs schema")
    resolved_dialect = resolve_dialect(s1, s2, dialect=dialect)
    _validate_public_schema(s1, resolved_dialect)
    _validate_public_schema(s2, resolved_dialect)
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return ProofEngine.for_schemas(
        s1, s2, dialect=resolved_dialect, options=options
    ).join(s1, s2)


def is_equivalent(
    s1,
    s2,
    *,
    dialect=None,
    proof_options=None,
    endeavor=False,
    max_work=None,
    timeout_ms=None,
):
    """Entry point for schema equivalence check operation."""
    options = _resolve_proof_options(
        proof_options,
        endeavor=endeavor,
        max_work=max_work,
        timeout_ms=timeout_ms,
    )
    return is_subschema(
        s1, s2, dialect=dialect, proof_options=options
    ) and is_subschema(
        s2,
        s1,
        dialect=dialect,
        proof_options=options,
    )
