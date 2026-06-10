from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from subschema.contracts import ProofResult
from subschema.dialects import Dialect
from subschema.ir import LogicalSchemaIR
from subschema.ir.terms import SchemaTerm
from subschema.provenance import SchemaSource
from subschema.validator import (
    ValidationOutcome,
    validate_source_difference,
    validate_source_instance,
)

ConfirmationStatus = Literal["confirmed", "rejected", "unsupported"]


class ConfirmationContext(Protocol):
    dialect: Dialect
    resources: Mapping[str, Any]


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
    return _confirmation_from_validation_outcome(
        validate_source_difference(lhs_source, rhs_source, witness)
    )


def confirm_term_valid(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
    instance: Any,
    context: ConfirmationContext,
    *,
    lhs_ir: LogicalSchemaIR | None = None,
    rhs_ir: LogicalSchemaIR | None = None,
) -> ConfirmationResult:
    return _confirm_term_valid(
        term,
        ir,
        instance,
        context,
        lhs_ir=lhs_ir,
        rhs_ir=rhs_ir,
        depth=0,
    )


def confirm_term_difference(
    lhs_term: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    rhs_term: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
    witness: Any,
    context: ConfirmationContext,
) -> ConfirmationResult:
    lhs = confirm_term_valid(
        lhs_term,
        lhs_ir,
        witness,
        context,
        lhs_ir=lhs_ir,
        rhs_ir=rhs_ir,
    )
    if lhs.status != "confirmed":
        return lhs if lhs.status == "unsupported" else ConfirmationResult.rejected()
    rhs = confirm_term_valid(
        rhs_term,
        rhs_ir,
        witness,
        context,
        lhs_ir=lhs_ir,
        rhs_ir=rhs_ir,
    )
    if rhs.status == "confirmed":
        return ConfirmationResult.rejected()
    return rhs if rhs.status == "unsupported" else ConfirmationResult.confirmed()


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
    return SchemaSource.root(
        schema_or_source,
        context.dialect,
        resources=context.resources,
    )


def _confirm_term_valid(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
    instance: Any,
    context: ConfirmationContext,
    *,
    lhs_ir: LogicalSchemaIR | None,
    rhs_ir: LogicalSchemaIR | None,
    depth: int,
) -> ConfirmationResult:
    if depth > 32:
        return ConfirmationResult.unsupported(
            "schema term confirmation exceeded supported nesting depth"
        )
    match term.kind:
        case "true":
            return ConfirmationResult.confirmed()
        case "false":
            return ConfirmationResult.rejected()
        case "node":
            term_ir = _ir_for_term_scope(term, ir, lhs_ir=lhs_ir, rhs_ir=rhs_ir)
            if term_ir is None or term.ref is None:
                return ConfirmationResult.unsupported(
                    "schema term confirmation requires available IR node"
                )
            node = term_ir.node_for_ref(term.ref)
            if node is None:
                return ConfirmationResult.unsupported(
                    "schema term confirmation requires available IR node"
                )
            return confirm_valid(node.source.to_source(), instance, context)
        case "all_of":
            unsupported: ConfirmationResult | None = None
            for child in term.children:
                result = _confirm_term_valid(
                    child,
                    ir,
                    instance,
                    context,
                    lhs_ir=lhs_ir,
                    rhs_ir=rhs_ir,
                    depth=depth + 1,
                )
                if result.status == "rejected":
                    return ConfirmationResult.rejected()
                if result.status == "unsupported":
                    unsupported = result
            return unsupported or ConfirmationResult.confirmed()
        case "any_of":
            any_of_unsupported: ConfirmationResult | None = None
            for child in term.children:
                result = _confirm_term_valid(
                    child,
                    ir,
                    instance,
                    context,
                    lhs_ir=lhs_ir,
                    rhs_ir=rhs_ir,
                    depth=depth + 1,
                )
                if result.status == "confirmed":
                    return ConfirmationResult.confirmed()
                if result.status == "unsupported":
                    any_of_unsupported = result
            return any_of_unsupported or ConfirmationResult.rejected()
        case "one_of":
            confirmed_count = 0
            one_of_unsupported: ConfirmationResult | None = None
            for child in term.children:
                result = _confirm_term_valid(
                    child,
                    ir,
                    instance,
                    context,
                    lhs_ir=lhs_ir,
                    rhs_ir=rhs_ir,
                    depth=depth + 1,
                )
                if result.status == "confirmed":
                    confirmed_count += 1
                    if confirmed_count > 1:
                        return ConfirmationResult.rejected()
                elif result.status == "unsupported":
                    one_of_unsupported = result
            if confirmed_count == 1 and one_of_unsupported is None:
                return ConfirmationResult.confirmed()
            if confirmed_count == 0 and one_of_unsupported is None:
                return ConfirmationResult.rejected()
            return one_of_unsupported or ConfirmationResult.rejected()
        case "not":
            if len(term.children) != 1:
                return ConfirmationResult.unsupported(
                    "not schema term confirmation requires exactly one child"
                )
            result = _confirm_term_valid(
                term.children[0],
                ir,
                instance,
                context,
                lhs_ir=lhs_ir,
                rhs_ir=rhs_ir,
                depth=depth + 1,
            )
            if result.status == "confirmed":
                return ConfirmationResult.rejected()
            if result.status == "rejected":
                return ConfirmationResult.confirmed()
            return result


def _ir_for_term_scope(
    term: SchemaTerm,
    default_ir: LogicalSchemaIR,
    *,
    lhs_ir: LogicalSchemaIR | None,
    rhs_ir: LogicalSchemaIR | None,
) -> LogicalSchemaIR | None:
    match term.scope:
        case "lhs":
            return lhs_ir
        case "rhs":
            return rhs_ir
        case None:
            return default_ir
