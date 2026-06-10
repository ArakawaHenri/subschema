"""
Finite-value reasoning over compiled schema IR.
"""

from __future__ import annotations

from typing import Any

from subschema.ir import LogicalSchemaIR, SchemaNode
from subschema.ir.terms import SchemaTerm
from subschema.prover.confirmation import confirm_term_valid, confirm_valid
from subschema.values import dedupe

_FINITE_INHABITANTS_CACHE_MISS = object()
_FINITE_TERM_INHABITANTS_CACHE_MISS = object()


def finite_values_for_ir(ir: LogicalSchemaIR) -> list[Any] | None:
    """Return compiled finite candidates, not proof-confirmed inhabitants."""
    constraint = ir.finite_constraint
    if constraint is None:
        return None
    return list(constraint.values)


def inhabited_finite_values_for_ir(
    ir: LogicalSchemaIR,
    context: Any,
) -> list[Any] | None:
    cache = _context_cache(context)
    cache_key = _finite_inhabitants_cache_key(ir)
    if cache is not None:
        cached = cache.get(cache_key, _FINITE_INHABITANTS_CACHE_MISS)
        if isinstance(cached, tuple):
            return list(cached)

    values = finite_values_for_ir(ir)
    if values is None:
        return None
    constraint = ir.finite_constraint
    if constraint is not None and not constraint.requires_confirmation:
        result = dedupe(values)
        _store_finite_inhabitants(cache, cache_key, result)
        return result
    inhabited = []
    source = ir.source.to_source()
    for value in values:
        confirmed = confirm_valid(source, value, context)
        if confirmed.status == "unsupported":
            return None
        if confirmed.status == "confirmed":
            inhabited.append(value)
    result = dedupe(inhabited)
    _store_finite_inhabitants(cache, cache_key, result)
    return result


def inhabited_finite_values_for_term(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
    context: Any,
) -> list[Any] | None:
    cache = _context_cache(context)
    cache_key = _finite_term_inhabitants_cache_key(term, ir)
    if cache is not None:
        cached = cache.get(cache_key, _FINITE_TERM_INHABITANTS_CACHE_MISS)
        if isinstance(cached, tuple):
            return list(cached)

    values = _candidate_finite_values_for_term(term, ir, context)
    if values is None:
        return None
    confirmed = []
    for value in values:
        result = confirm_term_valid(term, ir, value, context)
        if result.status == "unsupported":
            return None
        if result.status == "confirmed":
            confirmed.append(value)
    deduped = dedupe(confirmed)
    if cache is not None:
        cache[cache_key] = tuple(deduped)
    return deduped


def schema_is_empty_finite(ir: LogicalSchemaIR, context: Any) -> bool:
    values = inhabited_finite_values_for_ir(ir, context)
    return values == []


def finite_values_projection(values: list[Any]) -> Any:
    values = dedupe(values)
    if not values:
        return False
    if len(values) == 1:
        return {"const": values[0]}
    return {"enum": values}


def finite_complement_excluded_values_for_ir(
    ir: LogicalSchemaIR,
    context: Any,
) -> tuple[Any, ...] | None:
    negated = _single_not_child(ir)
    if negated is None:
        return None
    values = inhabited_finite_values_for_ir(
        ir.with_root(negated),
        context,
    )
    return None if values is None else tuple(values)


def _single_not_child(ir: LogicalSchemaIR) -> SchemaNode | None:
    children = tuple(
        applicator.children[0]
        for applicator in ir.applicators
        if applicator.kind == "not" and len(applicator.children) == 1
    )
    return children[0] if len(children) == 1 else None


def _candidate_finite_values_for_term(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
    context: Any,
) -> list[Any] | None:
    match term.kind:
        case "false":
            return []
        case "true":
            return None
        case "node":
            if term.ref is None:
                return None
            node = ir.node_for_ref(term.ref)
            if node is None:
                return None
            return inhabited_finite_values_for_ir(ir.with_root(node), context)
        case "all_of":
            return _candidate_finite_values_for_all_of_term(term, ir, context)
        case "any_of" | "one_of":
            values = []
            for child in term.children:
                child_values = _candidate_finite_values_for_term(child, ir, context)
                if child_values is None:
                    return None
                values.extend(child_values)
            return dedupe(values)
        case "not":
            return None


def _candidate_finite_values_for_all_of_term(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
    context: Any,
) -> list[Any] | None:
    finite_child_values = []
    for child in term.children:
        values = _candidate_finite_values_for_term(child, ir, context)
        if values is not None:
            finite_child_values.append(values)
    if not finite_child_values:
        return None
    return min(finite_child_values, key=len)


def _context_cache(context: Any) -> dict[tuple[object, ...], object] | None:
    cache = getattr(context, "cache", None)
    if isinstance(cache, dict):
        return cache
    return None


def _finite_inhabitants_cache_key(ir: LogicalSchemaIR) -> tuple[object, ...]:
    return (
        "inhabited-finite-values",
        id(ir.document),
        ir.root_ref,
    )


def _finite_term_inhabitants_cache_key(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
) -> tuple[object, ...]:
    return (
        "inhabited-finite-term-values",
        id(ir.document),
        term,
    )


def _store_finite_inhabitants(
    cache: dict[tuple[object, ...], object] | None,
    key: tuple[object, ...],
    values: list[Any],
) -> None:
    if cache is not None:
        cache[key] = tuple(values)
