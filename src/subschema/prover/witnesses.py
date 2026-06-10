"""
Constructive witnesses from compiled semantic IR facts.
"""

from __future__ import annotations

import copy
from fractions import Fraction
from typing import Any

from subschema.contracts import ProofResult
from subschema.ir import LogicalSchemaIR
from subschema.ir.constraints import (
    ArrayItemModelConstraint,
    ObjectPropertyNamesConstraint,
)
from subschema.ir.terms import SchemaTerm
from subschema.prover.finite import (
    finite_complement_excluded_values_for_ir,
    finite_values_for_ir,
    inhabited_finite_values_for_ir,
)
from subschema.prover.witness_results import WitnessBuildResult
from subschema.values import json_values_equal

_TERM_COMPLEMENT_WITNESS_CANDIDATES: tuple[Any, ...] = (
    None,
    False,
    True,
    0,
    1,
    "",
    [],
    {},
)
_WITNESS_CACHE_MISS = object()


def build_ir_witness(
    ir: LogicalSchemaIR,
    context: Any | None = None,
) -> WitnessBuildResult:
    cache = _context_cache(context)
    cache_key = _ir_witness_cache_key(ir)
    cached = _cached_witness(cache, cache_key)
    if cached is not None:
        return cached
    return _build_ir_witness(ir, context, depth=0)


def build_term_witness(
    term: SchemaTerm,
    parent_ir: LogicalSchemaIR,
    context: Any,
    *,
    lhs_ir: LogicalSchemaIR | None = None,
    rhs_ir: LogicalSchemaIR | None = None,
) -> WitnessBuildResult:
    cache = _context_cache(context)
    cache_key = _term_witness_cache_key(
        term,
        parent_ir,
        lhs_ir=lhs_ir,
        rhs_ir=rhs_ir,
    )
    cached = _cached_witness(cache, cache_key)
    if cached is not None:
        return cached
    return _term_witness(
        term,
        parent_ir,
        context,
        depth=0,
        lhs_ir=lhs_ir,
        rhs_ir=rhs_ir,
    )


def _build_ir_witness(
    ir: LogicalSchemaIR,
    context: Any | None,
    *,
    depth: int,
) -> WitnessBuildResult:
    cache = _context_cache(context)
    cache_key = _ir_witness_cache_key(ir)
    cached = _cached_witness(cache, cache_key)
    if cached is not None:
        return cached
    result = _build_ir_witness_uncached(ir, context, depth=depth)
    _store_witness(cache, cache_key, result)
    return result


def _build_ir_witness_uncached(
    ir: LogicalSchemaIR,
    context: Any | None,
    *,
    depth: int,
) -> WitnessBuildResult:
    if depth > 16:
        return WitnessBuildResult.unsupported(
            "IR witness construction exceeded supported nesting depth"
        )
    if ir.root.boolean_value is True:
        return WitnessBuildResult.concrete(None)
    if ir.root.boolean_value is False:
        return WitnessBuildResult.unsupported("false schema is uninhabited")

    finite = finite_values_for_ir(ir)
    if finite is not None:
        if not finite:
            return WitnessBuildResult.unsupported("finite IR fact is uninhabited")
        if context is None:
            return WitnessBuildResult.unsupported(
                "finite IR witness requires confirmation context"
            )
        inhabited = inhabited_finite_values_for_ir(ir, context)
        if inhabited is None:
            return WitnessBuildResult.unsupported(
                "finite IR witness confirmation failed"
            )
        if inhabited:
            return WitnessBuildResult.concrete(inhabited[0])
        return WitnessBuildResult.unsupported("finite IR fact is uninhabited")

    conditional = _boolean_conditional_witness(ir, context, depth=depth)
    if conditional.status in {"certificate", "resource_exhausted", "witness"}:
        return conditional

    numeric = ir.semantics.scalar.numeric_constraint
    if numeric is not None:
        numeric_atoms = numeric.normalized_atoms()
        for atom in numeric_atoms:
            value = atom.some_fraction()
            if value is not None:
                return WitnessBuildResult.concrete(_json_number(value))
        if numeric_atoms:
            return WitnessBuildResult.unsupported("numeric IR fact is uninhabited")

    string = ir.semantics.scalar.string_language_constraint
    if string is not None and not string.accepts_non_string:
        witness = string.pattern.witness(context)
        if isinstance(witness, ProofResult):
            if witness.status == "resource_exhausted":
                return WitnessBuildResult.resource_exhausted(
                    witness.reason or "regex witness exceeded proof work budget"
                )
            return WitnessBuildResult.unsupported(
                witness.reason or "regex witness could not be constructed"
            )
        if witness is None:
            return WitnessBuildResult.unsupported("string IR fact is uninhabited")
        return WitnessBuildResult.concrete(witness)

    array = _array_witness(ir, context, depth=depth)
    if array.status in {"certificate", "resource_exhausted", "witness"}:
        return array

    object_witness = _object_witness(ir, context, depth=depth)
    if object_witness.status in {"certificate", "resource_exhausted", "witness"}:
        return object_witness

    type_constraint = ir.semantics.scalar.type_constraint
    if type_constraint is not None and type_constraint.atoms:
        return WitnessBuildResult.concrete(
            type_constraint.witness_not_in(type_constraint.complement())
        )

    return WitnessBuildResult.unsupported(
        "IR witness construction requires unsupported semantic facts"
    )


def _json_number(value: Fraction) -> int | float:
    if value.denominator == 1:
        return int(value)
    return float(value)


def _array_witness(
    ir: LogicalSchemaIR,
    context: Any | None,
    *,
    depth: int,
) -> WitnessBuildResult:
    if not _type_allows(ir, "array"):
        return WitnessBuildResult.unsupported("IR facts do not require array witness")

    return _array_witness_from_irs((ir,) + _all_of_child_irs(ir), context, depth=depth)


def _array_witness_from_irs(
    array_irs: tuple[LogicalSchemaIR, ...],
    context: Any | None,
    *,
    depth: int,
) -> WitnessBuildResult:
    if not any(_type_allows(array_ir, "array") for array_ir in array_irs):
        return WitnessBuildResult.unsupported("IR facts do not require array witness")

    primary_ir = array_irs[0]
    length = max(_array_min_length(array_ir) for array_ir in array_irs)
    contains_term, contains_ir = _preferred_contains_term(array_irs, context)
    min_contains = _contains_minimum(array_irs)
    if contains_term is not None:
        length = max(length, min_contains or 1)
    if length > 1024:
        return WitnessBuildResult.unsupported("array IR witness is too large")

    values: list[Any] = [None] * length
    if contains_term is not None and length > 0:
        contains_witness = _child_witness(
            contains_term, contains_ir or primary_ir, context, depth=depth
        )
        if contains_witness.status != "witness":
            return contains_witness
        values[0] = contains_witness.witness

    item_model_entry = _first_constrained_item_model(array_irs)
    item_model = None if item_model_entry is None else item_model_entry[0]
    item_model_ir = primary_ir if item_model_entry is None else item_model_entry[1]
    if item_model is not None:
        for index in range(length):
            if values[index] is not None:
                continue
            item_term = item_model.term_at_index(index)
            if item_term is None:
                continue
            item_witness = _child_witness(
                item_term, item_model_ir, context, depth=depth
            )
            if item_witness.status != "witness":
                return item_witness
            values[index] = item_witness.witness
    return WitnessBuildResult.concrete(values)


def _object_witness(
    ir: LogicalSchemaIR,
    context: Any | None,
    *,
    depth: int,
) -> WitnessBuildResult:
    if not _type_allows(ir, "object"):
        return WitnessBuildResult.unsupported("IR facts do not require object witness")

    names = set[str]()
    value_terms: dict[str, SchemaTerm] = {}
    object_irs = (ir,) + _all_of_child_irs(ir)
    property_names = None
    for object_ir in object_irs:
        values = object_ir.semantics.object.object_property_values_constraint
        if values is not None:
            names.update(values.required)
            for name in values.property_names:
                _add_value_term(value_terms, name, values.property_term_for(name))

        closed = object_ir.semantics.object.object_closed_properties_constraint
        if closed is not None:
            names.update(closed.required)
            for name in closed.property_terms:
                _add_value_term(value_terms, name, closed.property_term_for(name))

        key_value = object_ir.semantics.object.object_key_value_constraint
        if key_value is not None:
            names.update(key_value.required)
            for name in key_value.properties:
                _add_value_term(value_terms, name, key_value.value_term_for(name))

        if object_ir.semantics.object.object_property_names_constraint is not None:
            property_names = object_ir.semantics.object.object_property_names_constraint
            names.update(property_names.required)

    target_count = max(
        len(names),
        *(_object_min_properties(item) for item in object_irs),
    )
    while len(names) < target_count:
        extra_name = _object_extra_name(property_names, names, context)
        if extra_name is None:
            return WitnessBuildResult.unsupported(
                "object IR witness requires unsupported property name"
            )
        names.add(extra_name)

    if len(names) > 512:
        return WitnessBuildResult.unsupported("object IR witness is too large")

    witness: dict[str, Any] = {}
    for name in sorted(names):
        term = value_terms.get(name)
        if term is None:
            witness[name] = None
            continue
        value = _child_witness(term, ir, context, depth=depth)
        if value.status != "witness":
            return value
        witness[name] = value.witness
    return WitnessBuildResult.concrete(witness)


def _child_witness(
    term: SchemaTerm,
    parent_ir: LogicalSchemaIR,
    context: Any | None,
    *,
    depth: int,
    lhs_ir: LogicalSchemaIR | None = None,
    rhs_ir: LogicalSchemaIR | None = None,
) -> WitnessBuildResult:
    if context is None:
        return WitnessBuildResult.unsupported(
            "IR witness construction requires proof context"
        )
    return _term_witness(
        term,
        parent_ir,
        context,
        depth=depth + 1,
        lhs_ir=lhs_ir,
        rhs_ir=rhs_ir,
    )


def _term_witness(
    term: SchemaTerm,
    parent_ir: LogicalSchemaIR,
    context: Any,
    *,
    depth: int,
    lhs_ir: LogicalSchemaIR | None = None,
    rhs_ir: LogicalSchemaIR | None = None,
) -> WitnessBuildResult:
    cache = _context_cache(context)
    cache_key = _term_witness_cache_key(
        term,
        parent_ir,
        lhs_ir=lhs_ir,
        rhs_ir=rhs_ir,
    )
    cached = _cached_witness(cache, cache_key)
    if cached is not None:
        return cached
    result = _term_witness_uncached(
        term,
        parent_ir,
        context,
        depth=depth,
        lhs_ir=lhs_ir,
        rhs_ir=rhs_ir,
    )
    _store_witness(cache, cache_key, result)
    return result


def _term_witness_uncached(
    term: SchemaTerm,
    parent_ir: LogicalSchemaIR,
    context: Any,
    *,
    depth: int,
    lhs_ir: LogicalSchemaIR | None = None,
    rhs_ir: LogicalSchemaIR | None = None,
) -> WitnessBuildResult:
    match term.kind:
        case "true":
            return WitnessBuildResult.concrete(None)
        case "false":
            return WitnessBuildResult.unsupported("false schema is uninhabited")
        case "node":
            if term.ref is None:
                return WitnessBuildResult.unsupported("schema term is missing node ref")
            term_ir = _ir_for_term_scope(term, parent_ir, lhs_ir=lhs_ir, rhs_ir=rhs_ir)
            if term_ir is None:
                return WitnessBuildResult.unsupported(
                    "schema term requires unavailable scoped IR"
                )
            node = term_ir.node_for_ref(term.ref)
            if node is None:
                return WitnessBuildResult.unsupported(
                    "schema term requires unavailable IR node"
                )
            return _build_ir_witness(term_ir.with_root(node), context, depth=depth)
        case "all_of":
            if not term.children:
                return WitnessBuildResult.concrete(None)
            if len(term.children) == 1:
                return _term_witness(
                    term.children[0],
                    parent_ir,
                    context,
                    depth=depth,
                    lhs_ir=lhs_ir,
                    rhs_ir=rhs_ir,
                )
            child_irs = _node_child_irs_for_all_of_term(
                term,
                parent_ir,
                lhs_ir=lhs_ir,
                rhs_ir=rhs_ir,
            )
            if child_irs is not None:
                numeric_witness = _numeric_finite_complement_all_of_witness(
                    child_irs, context
                )
                if numeric_witness is not None:
                    return WitnessBuildResult.concrete(numeric_witness)
                array_witness = _array_witness_from_irs(
                    child_irs, context, depth=depth
                )
                if array_witness.status in {"witness", "resource_exhausted"}:
                    return array_witness
            for child in term.children:
                witness = _term_witness(
                    child,
                    parent_ir,
                    context,
                    depth=depth,
                    lhs_ir=lhs_ir,
                    rhs_ir=rhs_ir,
                )
                if witness.status == "witness":
                    return witness
                if witness.status == "resource_exhausted":
                    return witness
            return WitnessBuildResult.unsupported(
                "allOf schema term witness requires combined term inhabitation"
            )
        case "any_of" | "one_of":
            for child in term.children:
                witness = _term_witness(
                    child,
                    parent_ir,
                    context,
                    depth=depth,
                    lhs_ir=lhs_ir,
                    rhs_ir=rhs_ir,
                )
                if witness.status == "witness":
                    return witness
                if witness.status == "resource_exhausted":
                    return witness
            return WitnessBuildResult.unsupported(
                "applicator schema term witness is uninhabited or unsupported"
            )
        case "not":
            excluded = _finite_values_for_term_complement_child(term, parent_ir)
            if excluded is None:
                return WitnessBuildResult.unsupported(
                    "not schema term witness requires complement construction"
                )
            for candidate in _TERM_COMPLEMENT_WITNESS_CANDIDATES:
                if _value_not_in(candidate, excluded):
                    return WitnessBuildResult.concrete(candidate)
            return WitnessBuildResult.unsupported(
                "not schema term finite complement witness could not be constructed"
            )


def _finite_values_for_term_complement_child(
    term: SchemaTerm,
    parent_ir: LogicalSchemaIR,
) -> tuple[Any, ...] | None:
    if len(term.children) != 1:
        return None
    child = term.children[0]
    match child.kind:
        case "false":
            return ()
        case "node":
            if child.ref is None:
                return None
            node = parent_ir.node_for_ref(child.ref)
            if node is None:
                return None
            values = finite_values_for_ir(parent_ir.with_root(node))
            return None if values is None else tuple(values)
        case _:
            return None


def _node_child_irs_for_all_of_term(
    term: SchemaTerm,
    parent_ir: LogicalSchemaIR,
    *,
    lhs_ir: LogicalSchemaIR | None,
    rhs_ir: LogicalSchemaIR | None,
) -> tuple[LogicalSchemaIR, ...] | None:
    child_irs: list[LogicalSchemaIR] = []
    for child in term.children:
        if child.kind != "node" or child.ref is None:
            return None
        child_parent_ir = _ir_for_term_scope(
            child,
            parent_ir,
            lhs_ir=lhs_ir,
            rhs_ir=rhs_ir,
        )
        if child_parent_ir is None:
            return None
        node = child_parent_ir.node_for_ref(child.ref)
        if node is None:
            return None
        child_irs.append(child_parent_ir.with_root(node))
    return tuple(child_irs)


def _numeric_finite_complement_all_of_witness(
    child_irs: tuple[LogicalSchemaIR, ...],
    context: Any,
) -> int | float | None:
    excluded = tuple(
        value
        for child_ir in child_irs
        for values in (finite_complement_excluded_values_for_ir(child_ir, context),)
        if values is not None
        for value in values
    )
    if not excluded:
        return None
    numeric_constraints = tuple(
        child_ir.semantics.scalar.numeric_constraint
        for child_ir in child_irs
        if child_ir.semantics.scalar.numeric_constraint is not None
    )
    if not numeric_constraints:
        return None
    candidates: list[Fraction] = []
    for constraint in numeric_constraints:
        for atom in constraint.normalized_atoms():
            value = atom.some_fraction()
            if value is not None:
                candidates.append(value)
    for value in excluded:
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        fraction = Fraction(value)
        candidates.extend((fraction - 1, fraction + 1))
    for candidate in candidates:
        if all(constraint.contains(candidate) for constraint in numeric_constraints):
            json_value = _json_number(candidate)
            if _value_not_in(json_value, excluded):
                return json_value
    return None


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


def _boolean_conditional_witness(
    ir: LogicalSchemaIR,
    context: Any | None,
    *,
    depth: int,
) -> WitnessBuildResult:
    if context is None:
        return WitnessBuildResult.unsupported(
            "IR witness construction requires proof context"
        )
    if depth > 16:
        return WitnessBuildResult.unsupported(
            "IR witness construction exceeded supported nesting depth"
        )
    condition = next(
        (
            applicator.children[0]
            for applicator in ir.root.applicators
            if applicator.kind == "if" and applicator.children
        ),
        None,
    )
    if condition is None or condition.boolean_value is None:
        return WitnessBuildResult.unsupported(
            "IR conditional witness requires boolean condition"
        )
    target_kind = "then" if condition.boolean_value else "else"
    target = next(
        (
            applicator.children[0]
            for applicator in ir.root.applicators
            if applicator.kind == target_kind and applicator.children
        ),
        None,
    )
    if target is not None:
        terms = [
            SchemaTerm.node(target.ref),
            ir.semantics.applicator.conditional_base_term,
        ]
    else:
        terms = [ir.semantics.applicator.conditional_base_term]
    term = SchemaTerm.all_of(tuple(term for term in terms if term is not None))
    return _term_witness(term, ir, context, depth=depth + 1)


def _value_not_in(value: Any, values: tuple[Any, ...]) -> bool:
    return all(not json_values_equal(value, existing) for existing in values)


def _add_value_term(
    target: dict[str, SchemaTerm],
    name: str,
    term: SchemaTerm | None,
) -> None:
    if term is None:
        return
    existing = target.get(name)
    if existing is None:
        target[name] = term
    else:
        target[name] = SchemaTerm.all_of((existing, term))


def _array_min_length(ir: LogicalSchemaIR) -> int:
    candidates = (
        ir.semantics.array.array_length_lhs_constraint,
        ir.semantics.array.array_length_rhs_constraint,
        ir.semantics.array.array_cardinality_length_constraint,
    )
    lower = 0
    for constraint in candidates:
        if constraint is None:
            continue
        intervals = constraint.normalized_intervals()
        if intervals:
            lower = max(lower, intervals[0].lower)
    return lower


def _object_min_properties(ir: LogicalSchemaIR) -> int:
    bounds = ir.semantics.object.object_property_count_bounds_constraint
    lower = bounds.minimum if bounds is not None else 0
    constraint = ir.semantics.object.object_property_count_constraint
    if constraint is not None:
        intervals = constraint.normalized_intervals()
        if intervals:
            lower = max(lower, intervals[0].lower)
    return lower


def _object_extra_name(
    constraint: ObjectPropertyNamesConstraint | None,
    existing: set[str],
    context: Any | None,
) -> str | None:
    preferred = ("a", "b", "c", "x", "y", "z")
    if constraint is None:
        return next((name for name in preferred if name not in existing), None)
    for name in sorted(constraint.required) + list(preferred):
        if name not in existing and constraint.keyspace_pattern.matches(name):
            return name
    pattern_witness = constraint.keyspace_pattern.witness(context)
    if isinstance(pattern_witness, str) and pattern_witness not in existing:
        return pattern_witness
    return None


def _type_allows(ir: LogicalSchemaIR, atom: str) -> bool:
    constraint = ir.semantics.scalar.type_constraint
    return constraint is not None and constraint.atoms == frozenset({atom})


def _all_of_child_irs(ir: LogicalSchemaIR) -> tuple[LogicalSchemaIR, ...]:
    return tuple(
        ir.with_root(child)
        for applicator in ir.root.applicators
        if applicator.kind == "allOf"
        for child in applicator.children
    )


def _preferred_contains_term(
    irs: tuple[LogicalSchemaIR, ...],
    context: Any | None,
) -> tuple[SchemaTerm | None, LogicalSchemaIR | None]:
    entries = tuple(
        (constraint.term, item)
        for item in irs
        for constraint in (item.semantics.array.array_contains_constraint,)
        if constraint is not None and constraint.term is not None
    )
    if context is not None:
        for term, item in entries:
            if _term_has_finite_values(term, item):
                return term, item
    return entries[0] if entries else (None, None)


def _term_has_finite_values(term: SchemaTerm, parent_ir: LogicalSchemaIR) -> bool:
    if term.kind == "node" and term.ref is not None:
        node = parent_ir.node_for_ref(term.ref)
        return node is not None and bool(
            finite_values_for_ir(parent_ir.with_root(node))
        )
    if term.kind == "false":
        return True
    return False


def _contains_minimum(irs: tuple[LogicalSchemaIR, ...]) -> int | None:
    minimums = tuple(
        constraint.minimum
        for item in irs
        for constraint in (item.semantics.array.array_contains_constraint,)
        if constraint is not None
    )
    if minimums:
        return max(minimums)
    counts = tuple(
        item.semantics.array.array_contains_counts[0]
        for item in irs
        if item.semantics.array.array_contains_counts is not None
    )
    return max(counts) if counts else None


def _term_is_true(term: SchemaTerm | None) -> bool:
    return term is None or term.kind == "true"


def _first_constrained_item_model(
    irs: tuple[LogicalSchemaIR, ...],
) -> tuple[ArrayItemModelConstraint, LogicalSchemaIR] | None:
    return next(
        (
            (item.semantics.array.array_item_model_constraint, item)
            for item in irs
            if item.semantics.array.array_item_model_constraint is not None
            and (
                item.semantics.array.array_item_model_constraint.prefix_terms
                or not _term_is_true(
                    item.semantics.array.array_item_model_constraint.tail_term
                )
            )
        ),
        None,
    )


def _context_cache(context: Any | None) -> dict[tuple[object, ...], object] | None:
    cache = getattr(context, "cache", None)
    if isinstance(cache, dict):
        return cache
    return None


def _cached_witness(
    cache: dict[tuple[object, ...], object] | None,
    key: tuple[object, ...],
) -> WitnessBuildResult | None:
    if cache is None:
        return None
    cached = cache.get(key, _WITNESS_CACHE_MISS)
    if cached is _WITNESS_CACHE_MISS:
        return None
    return WitnessBuildResult.concrete(copy.deepcopy(cached))


def _store_witness(
    cache: dict[tuple[object, ...], object] | None,
    key: tuple[object, ...],
    result: WitnessBuildResult,
) -> None:
    if cache is not None and result.status == "witness":
        cache[key] = copy.deepcopy(result.witness)


def _ir_witness_cache_key(ir: LogicalSchemaIR) -> tuple[object, ...]:
    return (
        "ir-witness",
        id(ir.document),
        ir.root_ref,
    )


def _term_witness_cache_key(
    term: SchemaTerm,
    parent_ir: LogicalSchemaIR,
    *,
    lhs_ir: LogicalSchemaIR | None,
    rhs_ir: LogicalSchemaIR | None,
) -> tuple[object, ...]:
    return (
        "term-witness",
        term,
        id(parent_ir.document),
        parent_ir.root_ref,
        None if lhs_ir is None else id(lhs_ir.document),
        None if lhs_ir is None else lhs_ir.root_ref,
        None if rhs_ir is None else id(rhs_ir.document),
        None if rhs_ir is None else rhs_ir.root_ref,
    )
