from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from subschema.dialects import Dialect
from subschema.kernel.contracts import ProofResult
from subschema.kernel.provenance import SchemaSource
from subschema.kernel.validation import (
    ValidationOutcome,
    validate_source_difference,
    validate_source_instance,
)

ConfirmationStatus = Literal["confirmed", "rejected", "unsupported"]


class ConfirmationContext(Protocol):
    dialect: Dialect


@dataclass(frozen=True)
class ConfirmationResult:
    status: ConfirmationStatus
    proof: ProofResult | None = None

    @classmethod
    def confirmed(cls) -> ConfirmationResult:
        return cls(status="confirmed")

    @classmethod
    def rejected(cls) -> ConfirmationResult:
        return cls(status="rejected")

    @classmethod
    def unsupported(cls, reason: str) -> ConfirmationResult:
        return cls(
            status="unsupported",
            proof=ProofResult.unsupported(reason),
        )


def confirm_valid(
    schema_or_source: Any,
    instance: Any,
    context: ConfirmationContext | None = None,
) -> ConfirmationResult:
    source_or_result = _source_for(schema_or_source, context)
    if isinstance(source_or_result, ConfirmationResult):
        return source_or_result
    source = source_or_result
    if not _is_root_confirmation_source(source):
        return _unsupported_non_root_source(source, "schema confirmation")
    return _confirmation_from_validation_outcome(
        validate_source_instance(source, instance)
    )


def confirm_difference(
    lhs_or_source: Any,
    rhs_or_source: Any,
    witness: Any,
    context: ConfirmationContext | None = None,
) -> ConfirmationResult:
    lhs_or_result = _source_for(lhs_or_source, context)
    if isinstance(lhs_or_result, ConfirmationResult):
        return lhs_or_result
    rhs_or_result = _source_for(rhs_or_source, context)
    if isinstance(rhs_or_result, ConfirmationResult):
        return rhs_or_result
    lhs_source = lhs_or_result
    rhs_source = rhs_or_result
    if lhs_source.dialect is not rhs_source.dialect:
        return ConfirmationResult.unsupported(
            "schema difference confirmation requires matching dialects"
        )
    if not _is_root_confirmation_source(lhs_source) or not _is_root_confirmation_source(
        rhs_source
    ):
        if not _is_root_confirmation_source(lhs_source):
            return _unsupported_non_root_source(
                lhs_source,
                "schema difference confirmation",
            )
        return _unsupported_non_root_source(
            rhs_source,
            "schema difference confirmation",
        )
    return _confirmation_from_validation_outcome(
        validate_source_difference(lhs_source, rhs_source, witness)
    )


def _confirmation_from_validation_outcome(
    outcome: ValidationOutcome,
) -> ConfirmationResult:
    if outcome.status == "valid":
        return ConfirmationResult.confirmed()
    if outcome.status == "invalid":
        return ConfirmationResult.rejected()
    return ConfirmationResult.unsupported(
        f"schema validation is unsupported: {outcome.reason}"
    )


def _source_for(
    schema_or_source: Any,
    context: ConfirmationContext | None,
) -> SchemaSource | ConfirmationResult:
    if isinstance(schema_or_source, SchemaSource):
        return schema_or_source
    if context is None:
        return ConfirmationResult.unsupported(
            "schema confirmation requires a proof context"
        )
    return SchemaSource.root(schema_or_source, context.dialect)


def _is_root_confirmation_source(source: SchemaSource) -> bool:
    return source.is_root_schema


def _unsupported_non_root_source(
    source: SchemaSource,
    operation: str,
) -> ConfirmationResult:
    if not source.has_document_context:
        return ConfirmationResult.unsupported(f"{operation} requires source document")
    return ConfirmationResult.unsupported(
        f"{operation} requires source validator backend"
    )
