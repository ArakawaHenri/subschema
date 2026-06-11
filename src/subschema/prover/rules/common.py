"""
Shared helpers for SAT difference rule implementations.
"""

from __future__ import annotations

from typing import Any

from subschema.contracts import CounterexampleCertificate, ProofResult
from subschema.ir import LogicalSchemaIR, SchemaNode
from subschema.ir.terms import SchemaTerm
from subschema.provenance import SchemaSource
from subschema.prover.confirmation import confirm_difference
from subschema.prover.protocols import DifferenceProblemProtocol


def array_static_reference_unsupported(
    problem: DifferenceProblemProtocol, fragment: str
) -> ProofResult | None:
    if contains_static_reference(problem):
        return ProofResult.unsupported(
            f"SAT {fragment} is deferred for static references"
        )
    return None


def object_static_reference_unsupported(
    problem: DifferenceProblemProtocol, fragment: str
) -> ProofResult | None:
    if contains_static_reference(problem):
        return ProofResult.unsupported(
            f"SAT {fragment} is deferred for static references"
        )
    return None


def lhs_static_reference_unsupported(
    problem: DifferenceProblemProtocol, fragment: str
) -> ProofResult | None:
    if _has_blocking_lhs_static_reference_boundary(problem):
        return ProofResult.unsupported(
            f"SAT {fragment} is deferred for left-side static references"
        )
    return None


def _child_certificate(kind: str, proof: ProofResult) -> CounterexampleCertificate:
    if proof.certificate is not None:
        return proof.certificate
    return CounterexampleCertificate(kind, "validated concrete child witness")


def certified_false(
    kind: str,
    reason: str,
    *,
    path: tuple[str, ...] = (),
    child: ProofResult | None = None,
) -> ProofResult:
    children = () if child is None else (_child_certificate("concrete-witness", child),)
    return ProofResult.certified_false(
        CounterexampleCertificate(
            kind,
            reason,
            path,
            children,
        )
    )


def validated_false(
    problem: DifferenceProblemProtocol, witness: Any, rejected_reason: str
) -> ProofResult:
    confirmed = confirm_difference(
        lhs_confirmation_source(problem),
        rhs_confirmation_source(problem),
        witness,
    )
    if confirmed.status == "unsupported":
        if confirmed.proof is None:
            return ProofResult.unsupported("counterexample confirmation failed")
        return confirmed.proof
    if confirmed.status == "confirmed":
        return ProofResult.false(witness)
    return ProofResult.unsupported(rejected_reason)


def validated_any_false(
    problem: DifferenceProblemProtocol, witnesses: tuple[Any, ...], missing_reason: str
) -> ProofResult:
    unsupported: ProofResult | None = None
    for witness in witnesses:
        confirmed = confirm_difference(
            lhs_confirmation_source(problem),
            rhs_confirmation_source(problem),
            witness,
        )
        if confirmed.status == "unsupported":
            unsupported = confirmed.proof or ProofResult.unsupported(
                "counterexample confirmation failed"
            )
            continue
        if confirmed.status == "confirmed":
            return ProofResult.false(witness)
    return unsupported or ProofResult.unsupported(missing_reason)


def array_witness_horizon(problem: DifferenceProblemProtocol) -> int:
    return problem.context.default_search_horizon


def lhs_confirmation_source(problem: DifferenceProblemProtocol) -> SchemaSource:
    return problem.formula.lhs.source.to_source()


def rhs_confirmation_source(problem: DifferenceProblemProtocol) -> SchemaSource:
    return problem.formula.rhs.source.to_source()


def contains_static_reference(problem: DifferenceProblemProtocol) -> bool:
    return bool(
        _has_blocking_lhs_static_reference_boundary(problem)
        or problem.formula.rhs.semantics.reference.has_static_reference_boundary
    )


def _has_blocking_lhs_static_reference_boundary(
    problem: DifferenceProblemProtocol,
) -> bool:
    lhs_term = problem.formula.lhs_term
    if isinstance(lhs_term, SchemaTerm):
        return _term_has_blocking_static_reference_boundary(
            lhs_term, problem.formula.lhs
        )
    lhs = problem.formula.lhs
    return _ir_has_blocking_static_reference_boundary(lhs)


def _ir_has_blocking_static_reference_boundary(ir: LogicalSchemaIR) -> bool:
    if not ir.semantics.reference.has_static_reference_boundary:
        return False
    reference = ir.semantics.reference
    if reference.has_non_recursive_static_reference_boundary:
        return True
    recursive = reference.recursive_references
    if not recursive:
        return True
    return not all(
        fact.polarity == "positive"
        and fact.guard_kind in {"array", "object", "object/array"}
        for fact in recursive
    )


def _term_has_blocking_static_reference_boundary(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
) -> bool:
    match term.kind:
        case "true" | "false":
            return False
        case "node":
            if term.ref is None:
                return True
            node = ir.node_for_ref(term.ref)
            if node is None:
                return True
            return _node_has_blocking_static_reference_boundary(node)
        case "not":
            return True
        case "all_of" | "any_of" | "one_of":
            return any(
                _term_has_blocking_static_reference_boundary(child, ir)
                for child in term.children
            )


def _node_has_blocking_static_reference_boundary(node: SchemaNode) -> bool:
    if not node.semantics.reference.has_static_reference_boundary:
        return False
    reference = node.semantics.reference
    if reference.has_non_recursive_static_reference_boundary:
        return True
    recursive = reference.recursive_references
    if not recursive:
        return True
    return not all(
        fact.polarity == "positive"
        and fact.guard_kind in {"array", "object", "object/array"}
        for fact in recursive
    )
