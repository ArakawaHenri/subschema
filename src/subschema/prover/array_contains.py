"""
Shared IR helpers for array contains cardinality reasoning.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from subschema.contracts import ProofResult
from subschema.dialects import Dialect
from subschema.ir import LogicalSchemaIR
from subschema.ir.constraints import (
    ArrayContainsConstraint,
    ArrayItemModelConstraint,
    ArrayLengthConstraint,
)
from subschema.ir.terms import SchemaTerm


class ArrayContainsContext(Protocol):
    dialect: Dialect
    resources: Mapping[str, Any]

    def subproof_terms(
        self,
        lhs: SchemaTerm,
        lhs_ir: LogicalSchemaIR,
        rhs: SchemaTerm,
        rhs_ir: LogicalSchemaIR,
    ) -> ProofResult: ...


def guaranteed_contains_matches(
    ir: LogicalSchemaIR,
    contains: ArrayContainsConstraint,
    context: ArrayContainsContext,
    *,
    contains_ir: LogicalSchemaIR | None = None,
    length_constraint: ArrayLengthConstraint | None = None,
    term_at_index: Callable[[int], SchemaTerm | None] | None = None,
    tail_start_index: int | None = None,
    tail_term: SchemaTerm | None = None,
) -> int:
    """Return a proven lower bound for contains matches in every array instance."""

    guaranteed = 0
    rhs_ir = ir if contains_ir is None else contains_ir
    own_contains = ir.semantics.array.array_contains_constraint
    if own_contains is not None and _term_is_subschema(
        own_contains.term, ir, contains.term, rhs_ir, context
    ):
        guaranteed = max(guaranteed, own_contains.minimum)

    structural = _structural_guaranteed_contains_matches(
        ir,
        contains,
        context,
        contains_ir=rhs_ir,
        length_constraint=length_constraint,
        term_at_index=term_at_index,
        tail_start_index=tail_start_index,
        tail_term=tail_term,
    )
    return max(guaranteed, structural)


def _structural_guaranteed_contains_matches(
    ir: LogicalSchemaIR,
    contains: ArrayContainsConstraint,
    context: ArrayContainsContext,
    *,
    contains_ir: LogicalSchemaIR,
    length_constraint: ArrayLengthConstraint | None,
    term_at_index: Callable[[int], SchemaTerm | None] | None,
    tail_start_index: int | None,
    tail_term: SchemaTerm | None,
) -> int:
    item_model = ir.semantics.array.array_item_model_constraint
    if item_model is None and term_at_index is None:
        return 0

    required_length = _array_length_lower_bound(
        length_constraint or ir.semantics.array.array_length_lhs_constraint
    )
    if required_length is None or required_length <= 0:
        return 0

    guaranteed = 0
    bulk_tail_start = tail_start_index
    bulk_tail_term = tail_term
    if term_at_index is None and item_model is not None:
        bulk_tail_start = len(item_model.prefix_terms)
        bulk_tail_term = item_model.tail_term

    prefix_limit = required_length
    if bulk_tail_start is not None:
        prefix_limit = min(prefix_limit, bulk_tail_start)

    for index in range(prefix_limit):
        item_term = _term_at_index(index, item_model, term_at_index)
        if _term_is_subschema(item_term, ir, contains.term, contains_ir, context):
            guaranteed += 1

    if (
        bulk_tail_start is not None
        and required_length > bulk_tail_start
        and _term_is_subschema(bulk_tail_term, ir, contains.term, contains_ir, context)
    ):
        guaranteed += required_length - bulk_tail_start

    return guaranteed


def _term_at_index(
    index: int,
    item_model: ArrayItemModelConstraint | None,
    term_at_index: Callable[[int], SchemaTerm | None] | None,
) -> SchemaTerm | None:
    if term_at_index is not None:
        return term_at_index(index)
    if item_model is None:
        return None
    return item_model.term_at_index(index)


def _array_length_lower_bound(
    constraint: ArrayLengthConstraint | None,
) -> int | None:
    if constraint is None:
        return None
    intervals = constraint.normalized_intervals()
    if not intervals:
        return 0
    return min(interval.lower for interval in intervals)


def _term_is_subschema(
    lhs: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR,
    rhs: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
    context: ArrayContainsContext,
) -> bool:
    if lhs is None:
        return False
    proof = context.subproof_terms(lhs, lhs_ir, rhs, rhs_ir)
    return proof.status == "proved_true"
