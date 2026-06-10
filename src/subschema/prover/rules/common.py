"""
Shared helpers for SAT difference rule implementations.
"""

from __future__ import annotations

from typing import Any, cast

from subschema.contracts import CounterexampleCertificate, ProofResult
from subschema.ir.terms import SchemaTerm
from subschema.prover.confirmation import confirm_difference


def _array_static_reference_unsupported(
    problem: Any, fragment: str
) -> ProofResult | None:
    if _contains_static_reference(problem):
        return ProofResult.unsupported(
            f"SAT {fragment} is deferred for static references"
        )
    return None


def _object_static_reference_unsupported(
    problem: Any, fragment: str
) -> ProofResult | None:
    if _contains_static_reference(problem):
        return ProofResult.unsupported(
            f"SAT {fragment} is deferred for static references"
        )
    return None


def _lhs_static_reference_unsupported(
    problem: Any, fragment: str
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


def _certified_false(
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


def _validated_false(problem: Any, witness: Any, rejected_reason: str) -> ProofResult:
    confirmed = confirm_difference(
        _lhs_confirmation_source(problem),
        _rhs_confirmation_source(problem),
        witness,
    )
    if confirmed.status == "unsupported":
        if confirmed.proof is None:
            return ProofResult.unsupported("counterexample confirmation failed")
        return confirmed.proof
    if confirmed.status == "confirmed":
        return ProofResult.false(witness)
    return ProofResult.unsupported(rejected_reason)


def _validated_any_false(
    problem: Any, witnesses: tuple[Any, ...], missing_reason: str
) -> ProofResult:
    unsupported: ProofResult | None = None
    for witness in witnesses:
        confirmed = confirm_difference(
            _lhs_confirmation_source(problem),
            _rhs_confirmation_source(problem),
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


def _array_witness_horizon(problem: Any) -> int:
    return cast(int, problem.context.default_search_horizon)


def _lhs_confirmation_source(problem: Any) -> Any:
    return problem.formula.lhs.source.to_source()


def _rhs_confirmation_source(problem: Any) -> Any:
    return problem.formula.rhs.source.to_source()


def _contains_static_reference(problem: Any) -> bool:
    return bool(
        _has_blocking_lhs_static_reference_boundary(problem)
        or problem.formula.rhs.has_static_reference_boundary
    )


def _has_blocking_lhs_static_reference_boundary(problem: Any) -> bool:
    lhs_term = problem.formula.lhs_term
    if isinstance(lhs_term, SchemaTerm):
        return _term_has_blocking_static_reference_boundary(
            lhs_term, problem.formula.lhs
        )
    lhs = problem.formula.lhs
    return _ir_has_blocking_static_reference_boundary(lhs)


def _ir_has_blocking_static_reference_boundary(ir: Any) -> bool:
    if not ir.has_static_reference_boundary:
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
    ir: Any,
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


def _node_has_blocking_static_reference_boundary(node: Any) -> bool:
    if not node.semantics.has_static_reference_boundary:
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
