"""
Proof-driver orchestration for the kernel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from subschema.dialects import (
    strip_inactive_keywords_for_dialect,
    validate_supported_keywords,
)
from subschema.exceptions import UnsupportedKeywordError
from subschema.kernel.contracts import (
    ProofResult,
    ProofSide,
    UnsupportedCategory,
    UnsupportedDiagnostic,
)
from subschema.kernel.json_data import ensure_json_value
from subschema.kernel.references import inline_static_refs_for_proof
from subschema.kernel.validation import validate_schema_for_dialect

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext


def prove_subschema_with_context(
    context: ProofContext,
    lhs: Any,
    rhs: Any,
) -> ProofResult:
    lhs_validation = schema_validation_result(context, lhs, "lhs")
    if lhs_validation is not None:
        return lhs_validation
    rhs_validation = schema_validation_result(context, rhs, "rhs")
    if rhs_validation is not None:
        return rhs_validation

    prepared_lhs = strip_inactive_keywords_for_dialect(lhs, context.dialect)
    prepared_rhs = strip_inactive_keywords_for_dialect(rhs, context.dialect)
    proof_lhs = inline_static_refs_for_proof(prepared_lhs, context.dialect)
    proof_rhs = inline_static_refs_for_proof(prepared_rhs, context.dialect)
    return bounded_ir_proof(context, proof_lhs, proof_rhs)


def validate_schema(context: ProofContext, schema: Any) -> None:
    ensure_json_value(schema, label="schema")
    validate_supported_keywords(schema, context.dialect)
    validation_schema = strip_inactive_keywords_for_dialect(schema, context.dialect)
    validate_schema_for_dialect(validation_schema, context.dialect)


def schema_validation_result(
    context: ProofContext, schema: Any, side: ProofSide
) -> ProofResult | None:
    try:
        validate_schema(context, schema)
    except UnsupportedKeywordError as err:
        diagnostic = _diagnostic_from_unsupported_keyword(err, side)
        return ProofResult.unsupported(diagnostic.format(), err, diagnostic)
    return None


def bounded_ir_proof(context: ProofContext, lhs: Any, rhs: Any) -> ProofResult:
    from subschema.kernel.sat import EmptinessSolver

    return EmptinessSolver(context).prove_difference_empty(lhs, rhs)


def _diagnostic_from_unsupported_keyword(
    err: UnsupportedKeywordError, side: ProofSide
) -> UnsupportedDiagnostic:
    keyword = str(err.keyword)
    path = _unsupported_keyword_path(err)
    category: UnsupportedCategory = "dialect-keyword"
    reason = str(err)

    if keyword == "$vocabulary":
        vocabulary_uri = err.path[-1] if err.path else None
        if vocabulary_uri is not None and "format-assertion" in vocabulary_uri:
            category = "format-assertion"
            reason = f"required format-assertion vocabulary {
                vocabulary_uri!r
            } is unsupported"
        elif vocabulary_uri is not None:
            category = "unknown-vocabulary"
            reason = f"required vocabulary {vocabulary_uri!r} is unsupported"
        else:
            category = "unknown-vocabulary"
            reason = (
                "$vocabulary is supported only for dialects with vocabulary "
                "declarations"
            )

    return UnsupportedDiagnostic(
        category=category,
        reason=reason,
        keyword=keyword,
        path=path,
        side=side,
    )


def _unsupported_keyword_path(err: UnsupportedKeywordError) -> tuple[str, ...]:
    keyword = str(err.keyword)
    if keyword == "$vocabulary":
        return ("$vocabulary",) + tuple(str(segment) for segment in err.path)
    return tuple(str(segment) for segment in err.path) + (keyword,)
