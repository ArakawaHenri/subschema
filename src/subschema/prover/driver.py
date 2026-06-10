"""
Proof-driver orchestration for the prover.
"""

from __future__ import annotations

from typing import Any

from subschema.contracts import (
    ProofResult,
    ProofSide,
    UnsupportedCategory,
    UnsupportedDiagnostic,
)
from subschema.dialects import (
    strip_inactive_keywords_for_dialect,
    validate_supported_keywords,
)
from subschema.exceptions import UnsupportedKeywordError
from subschema.ir import LogicalSchemaIR
from subschema.ir.constraints import JSON_TYPE_ATOMS, TypeConstraint
from subschema.ir.terms import SchemaTerm
from subschema.json_data import ensure_json_value
from subschema.prover.disjointness import terms_are_disjoint
from subschema.prover.finite import finite_complement_excluded_values_for_ir
from subschema.prover.protocols import ProofContextProtocol
from subschema.prover.sat import EmptinessSolver
from subschema.validator import validate_schema_for_dialect


def validate_schema(context: ProofContextProtocol, schema: Any) -> None:
    ensure_json_value(schema, label="schema")
    validate_supported_keywords(schema, context.dialect)
    validation_schema = strip_inactive_keywords_for_dialect(schema, context.dialect)
    validate_schema_for_dialect(validation_schema, context.dialect)


def schema_validation_result(
    context: ProofContextProtocol, schema: Any, side: ProofSide
) -> ProofResult | None:
    try:
        validate_schema(context, schema)
    except UnsupportedKeywordError as err:
        diagnostic = _diagnostic_from_unsupported_keyword(err, side)
        return ProofResult.unsupported(diagnostic.format(), err, diagnostic)
    return None


def prove_ir_subschema_with_context(
    context: ProofContextProtocol,
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
) -> ProofResult:
    return EmptinessSolver(context).prove_ir_difference_empty(lhs, rhs)


def prove_term_subschema_with_context(
    context: ProofContextProtocol,
    lhs: SchemaTerm,
    rhs: SchemaTerm,
    ir: LogicalSchemaIR,
) -> ProofResult:
    return EmptinessSolver(context).prove_term_difference_empty(lhs, rhs, ir)


def prove_terms_subschema_with_context(
    context: ProofContextProtocol,
    lhs: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    rhs: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
) -> ProofResult:
    term_proof = _prove_terms_by_decomposition(context, lhs, lhs_ir, rhs, rhs_ir)
    if term_proof is not None:
        return term_proof
    return EmptinessSolver(context).prove_terms_difference_empty(
        lhs, lhs_ir, rhs, rhs_ir
    )


def _prove_terms_by_decomposition(
    context: ProofContextProtocol,
    lhs: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    rhs: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
) -> ProofResult | None:
    if lhs.kind == "true" and rhs.kind == "node":
        proof = _prove_true_term_subset_of_node(context, rhs, rhs_ir)
        if proof is not None:
            return proof
    if rhs.kind == "not" and len(rhs.children) == 1:
        return terms_are_disjoint(lhs, lhs_ir, rhs.children[0], rhs_ir, context)
    if rhs.kind == "all_of":
        return _prove_lhs_subset_of_all_terms(
            context, lhs, lhs_ir, rhs.children, rhs_ir
        )
    if lhs.kind == "any_of":
        return _prove_any_term_subset_of_rhs(context, lhs.children, lhs_ir, rhs, rhs_ir)
    if lhs.kind == "all_of":
        return _prove_all_term_subset_of_rhs(context, lhs.children, lhs_ir, rhs, rhs_ir)
    if rhs.kind == "any_of":
        return _prove_lhs_subset_of_any_term(context, lhs, lhs_ir, rhs.children, rhs_ir)
    return None


def _prove_true_term_subset_of_node(
    context: ProofContextProtocol,
    rhs: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
) -> ProofResult | None:
    if rhs.ref is None:
        return None
    node = rhs_ir.node_for_ref(rhs.ref)
    if node is None:
        return None
    node_ir = rhs_ir.with_root_ref(node.ref)
    excluded_values = finite_complement_excluded_values_for_ir(node_ir, context)
    if excluded_values:
        return ProofResult.false(excluded_values[0])
    type_constraint = node.semantics.scalar.type_constraint
    if type_constraint is None or not type_constraint.language_complete:
        return None
    witness = TypeConstraint(JSON_TYPE_ATOMS).witness_not_in(type_constraint)
    return None if witness is None else ProofResult.false(witness)


def _prove_lhs_subset_of_all_terms(
    context: ProofContextProtocol,
    lhs: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    rhs_children: tuple[SchemaTerm, ...],
    rhs_ir: LogicalSchemaIR,
) -> ProofResult:
    unsupported: ProofResult | None = None
    for child in rhs_children:
        proof = context.subproof_terms(lhs, lhs_ir, child, rhs_ir)
        if proof.status == "proved_false" or proof.status == "resource_exhausted":
            return proof
        if proof.status == "unsupported":
            unsupported = proof if unsupported is None else unsupported
    if unsupported is not None:
        return unsupported
    return ProofResult.true()


def _prove_any_term_subset_of_rhs(
    context: ProofContextProtocol,
    lhs_children: tuple[SchemaTerm, ...],
    lhs_ir: LogicalSchemaIR,
    rhs: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
) -> ProofResult:
    unsupported: ProofResult | None = None
    for child in lhs_children:
        proof = context.subproof_terms(child, lhs_ir, rhs, rhs_ir)
        if proof.status == "proved_false" or proof.status == "resource_exhausted":
            return proof
        if proof.status == "unsupported":
            unsupported = proof if unsupported is None else unsupported
    if unsupported is not None:
        return unsupported
    return ProofResult.true()


def _prove_all_term_subset_of_rhs(
    context: ProofContextProtocol,
    lhs_children: tuple[SchemaTerm, ...],
    lhs_ir: LogicalSchemaIR,
    rhs: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
) -> ProofResult | None:
    unsupported: ProofResult | None = None
    for child in lhs_children:
        proof = context.subproof_terms(child, lhs_ir, rhs, rhs_ir)
        if proof.status == "proved_true":
            return ProofResult.true()
        if proof.status == "resource_exhausted":
            return proof
        if proof.status == "unsupported":
            unsupported = proof if unsupported is None else unsupported
    return unsupported


def _prove_lhs_subset_of_any_term(
    context: ProofContextProtocol,
    lhs: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    rhs_children: tuple[SchemaTerm, ...],
    rhs_ir: LogicalSchemaIR,
) -> ProofResult | None:
    unsupported: ProofResult | None = None
    for child in rhs_children:
        proof = context.subproof_terms(lhs, lhs_ir, child, rhs_ir)
        if proof.status == "proved_true":
            return ProofResult.true()
        if proof.status == "resource_exhausted":
            return proof
        if proof.status == "unsupported":
            unsupported = proof if unsupported is None else unsupported
    return unsupported


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
