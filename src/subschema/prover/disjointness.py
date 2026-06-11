"""
Shared schema-language disjointness helpers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from subschema.contracts import ProofResult
from subschema.dialects import Dialect
from subschema.ir import LogicalSchemaIR
from subschema.ir.constraints import (
    JSON_TYPE_ATOMS,
    ArrayLengthConstraint,
    NumericConstraint,
    ObjectPropertyCountConstraint,
    StringLanguageConstraint,
    StringLengthConstraint,
)
from subschema.ir.terms import SchemaTerm
from subschema.prover.array_contains import guaranteed_contains_matches
from subschema.prover.confirmation import confirm_valid
from subschema.prover.finite import (
    finite_complement_excluded_values_for_ir,
    finite_values_for_ir,
)
from subschema.prover.witnesses import build_ir_witness
from subschema.values import json_semantic_key
from subschema.work_protocols import RegexWorkContext

__all__ = [
    "ir_is_empty_exact",
    "irs_are_disjoint",
    "terms_are_disjoint",
]


class DisjointnessContext(Protocol):
    dialect: Dialect
    resources: Mapping[str, Any]

    def subproof_terms(
        self,
        lhs: SchemaTerm,
        lhs_ir: LogicalSchemaIR,
        rhs: SchemaTerm,
        rhs_ir: LogicalSchemaIR,
    ) -> ProofResult: ...


SharedWitnessStatus = Literal["confirmed_false", "rejected", "unsupported"]


@dataclass(frozen=True)
class SharedWitnessConfirmation:
    status: SharedWitnessStatus
    proof: ProofResult | None = None


def _type_atoms(ir: LogicalSchemaIR) -> frozenset[str]:
    constraint = ir.semantics.scalar.type_constraint
    if constraint is None:
        return JSON_TYPE_ATOMS
    return constraint.atoms


def _string_length_constraint(value: Any) -> StringLengthConstraint | None:
    return value if isinstance(value, StringLengthConstraint) else None


def _string_language_constraint(value: Any) -> StringLanguageConstraint | None:
    return value if isinstance(value, StringLanguageConstraint) else None


def ir_is_empty_exact(
    ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    if ir.root.boolean_value is False:
        return ProofResult.true()
    if ir.root.boolean_value is True:
        return ProofResult.false(None)

    array_empty = _array_contains_emptiness_ir(ir, context)
    if array_empty.status != "unsupported":
        return array_empty

    numeric_empty = _numeric_shape_emptiness_ir(ir)
    if numeric_empty.status != "unsupported":
        return numeric_empty

    object_empty = _object_count_emptiness_ir(ir)
    if object_empty.status != "unsupported":
        return object_empty

    array_empty = _array_length_emptiness_ir(ir)
    if array_empty.status != "unsupported":
        return array_empty

    array_empty = _array_unique_items_cardinality_emptiness_ir(ir, context)
    if array_empty.status != "unsupported":
        return array_empty

    witness = build_ir_witness(ir, cast(Any, context))
    if witness.status == "resource_exhausted":
        return ProofResult.resource_exhausted(witness.reason)
    if witness.has_witness:
        confirmed = confirm_valid(ir.source.to_source(), witness.witness, context)
        if confirmed.status == "unsupported":
            if confirmed.proof is None:
                return ProofResult.unsupported("schema witness confirmation failed")
            return confirmed.proof
        if confirmed.status == "confirmed":
            return ProofResult.false(witness.witness)

    return ProofResult.unsupported("schema emptiness could not be proven exactly")


def irs_are_disjoint(
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    return _irs_are_disjoint(lhs, rhs, context, depth=0)


def _irs_are_disjoint(
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    if depth > 8:
        return ProofResult.unsupported(
            "schema disjointness recursion limit was reached"
        )

    reference_disjointness = _static_reference_target_disjointness_ir(
        lhs, rhs, context
    )
    if reference_disjointness.status != "unsupported":
        return reference_disjointness

    applicator_disjointness = _union_applicator_disjointness_ir(
        lhs, rhs, context, depth=depth
    )
    if applicator_disjointness.status != "unsupported":
        return applicator_disjointness

    if not (_type_atoms(lhs) & _type_atoms(rhs)):
        return ProofResult.true()
    string_length_disjointness = _string_length_disjointness_ir(lhs, rhs)
    if string_length_disjointness.status != "unsupported":
        return string_length_disjointness
    string_language_disjointness = _string_language_disjointness_ir(
        lhs, rhs, context
    )
    if string_language_disjointness.status != "unsupported":
        return string_language_disjointness
    numeric_disjointness = _numeric_disjointness_ir(lhs, rhs, context)
    if numeric_disjointness.status != "unsupported":
        return numeric_disjointness
    object_count_disjointness = _object_count_disjointness_ir(lhs, rhs, context)
    if object_count_disjointness.status != "unsupported":
        return object_count_disjointness
    array_length_disjointness = _array_length_disjointness_ir(lhs, rhs, context)
    if array_length_disjointness.status != "unsupported":
        return array_length_disjointness
    array_item_disjointness = _array_item_disjointness_ir(
        lhs, rhs, context, depth=depth
    )
    if array_item_disjointness.status != "unsupported":
        return array_item_disjointness
    closed_object_disjointness = _closed_finite_object_disjointness_ir(
        lhs, rhs, context, depth=depth
    )
    if closed_object_disjointness.status != "unsupported":
        return closed_object_disjointness
    object_property_conflict = _object_required_property_conflict_ir(
        lhs, rhs, context, depth=depth
    )
    if object_property_conflict.status != "unsupported":
        return object_property_conflict

    return ProofResult.unsupported("IR disjointness could not be proven exactly")


def _static_reference_target_disjointness_ir(
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    lhs_target = lhs.root.semantics.reference.static_reference.target
    rhs_target = rhs.root.semantics.reference.static_reference.target
    if lhs_target is None and rhs_target is None:
        return ProofResult.unsupported(
            "static-reference disjointness requires target terms"
        )
    return terms_are_disjoint(
        lhs_target or lhs.root_term,
        lhs,
        rhs_target or rhs.root_term,
        rhs,
        context,
    )


def _union_applicator_disjointness_ir(
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    lhs_branches = _union_applicator_branch_terms(lhs)
    if lhs_branches is not None:
        return _branch_terms_are_disjoint_from_ir(
            lhs,
            lhs_branches,
            rhs,
            context,
            depth=depth,
        )

    rhs_branches = _union_applicator_branch_terms(rhs)
    if rhs_branches is not None:
        return _branch_terms_are_disjoint_from_ir(
            rhs,
            rhs_branches,
            lhs,
            context,
            depth=depth,
        )

    return ProofResult.unsupported(
        "schema disjointness has no supported union applicator fragment"
    )


def _branch_terms_are_disjoint_from_ir(
    union_ir: LogicalSchemaIR,
    branches: tuple[SchemaTerm, ...],
    other_ir: LogicalSchemaIR,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    unsupported: ProofResult | None = None
    for branch in branches:
        branch_disjoint = terms_are_disjoint(
            branch,
            union_ir,
            other_ir.root_term,
            other_ir,
            context,
        )
        if branch_disjoint.status == "proved_true":
            continue
        if branch_disjoint.status == "resource_exhausted":
            return branch_disjoint
        if branch_disjoint.status == "proved_false":
            witness = branch_disjoint.witness
            if witness is not None:
                shared = _confirmed_shared_witness_ir(
                    union_ir, other_ir, witness, context
                )
                if shared.status == "confirmed_false" and shared.proof is not None:
                    return shared.proof
                if shared.status == "unsupported":
                    unsupported = shared.proof
                    continue
            unsupported = (
                unsupported
                or ProofResult.unsupported(
                    "union branch intersection witness was not valid for the "
                    "full schema"
                )
            )
            continue
        unsupported = branch_disjoint
    return ProofResult.true() if unsupported is None else unsupported


def _union_applicator_branch_terms(
    ir: LogicalSchemaIR,
) -> tuple[SchemaTerm, ...] | None:
    for applicator in ir.root.applicators:
        if applicator.kind not in {"anyOf", "oneOf"}:
            continue
        if not applicator.children:
            continue
        if not _union_applicator_base_is_supported(applicator.base_semantic_keywords):
            return None
        if applicator.kind == "anyOf" and _any_of_has_object_or_array_effects(
            ir, applicator.children
        ):
            return None
        return tuple(
            _all_of_terms((applicator.base_term, SchemaTerm.node(child.ref)))
            for child in applicator.children
        )
    return None


def _union_applicator_base_is_supported(base_keywords: frozenset[str]) -> bool:
    applicator_keys = {"allOf", "anyOf", "oneOf", "not", "if", "then", "else"}
    return not bool(base_keywords & applicator_keys)


def _any_of_has_object_or_array_effects(
    ir: LogicalSchemaIR,
    children: tuple[Any, ...],
) -> bool:
    if ir.root.semantics.object.has_object_or_array_assertions:
        return True
    return any(
        child.semantics.object.has_object_or_array_assertions for child in children
    )


def _all_of_terms(children: tuple[SchemaTerm, ...]) -> SchemaTerm:
    return SchemaTerm.all_of(tuple(child for child in children if child.kind != "true"))


def _numeric_disjointness_ir(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    shared_types = _type_atoms(lhs_ir) & _type_atoms(rhs_ir)
    if not shared_types <= {"integer", "number"}:
        return ProofResult.unsupported(
            "numeric disjointness requires numeric-only intersection"
        )

    lhs_shape = lhs_ir.semantics.scalar.numeric_constraint
    rhs_shape = rhs_ir.semantics.scalar.numeric_constraint
    if lhs_shape is None or rhs_shape is None:
        return ProofResult.unsupported(
            "numeric disjointness requires exact numeric shapes"
        )

    intersection = lhs_shape.intersect(rhs_shape)
    if not intersection.normalized_atoms() and not intersection.accepts_non_numeric:
        return ProofResult.true()

    witness = intersection.witness_not_in(
        NumericConstraint((), accepts_non_numeric=False)
    )
    if witness is not None:
        shared = _confirmed_shared_witness_ir(lhs_ir, rhs_ir, witness, context)
        proof = _proof_from_shared_witness(shared)
        if proof is not None:
            return proof

    return ProofResult.unsupported(
        "numeric disjointness could not be proven exactly"
    )


def _string_length_disjointness_ir(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
) -> ProofResult:
    shared_types = _type_atoms(lhs_ir) & _type_atoms(rhs_ir)
    if shared_types != {"string"}:
        return ProofResult.unsupported(
            "string length disjointness requires string-only intersection"
        )

    lhs_shape = _string_length_constraint(
        lhs_ir.semantics.scalar.string_length_constraint
    )
    rhs_shape = _string_length_constraint(
        rhs_ir.semantics.scalar.string_length_constraint
    )
    if lhs_shape is None or rhs_shape is None:
        return ProofResult.unsupported(
            "string length disjointness requires exact string length facts"
        )

    intersection = lhs_shape.intersect(rhs_shape)
    if not intersection.normalized_intervals() and not intersection.accepts_non_string:
        return ProofResult.true()
    return ProofResult.unsupported(
        "string length disjointness could not be proven exactly"
    )


def _string_language_disjointness_ir(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    shared_types = _type_atoms(lhs_ir) & _type_atoms(rhs_ir)
    if shared_types != {"string"}:
        return ProofResult.unsupported(
            "string language disjointness requires string-only intersection"
        )

    lhs_shape = _string_language_constraint(
        lhs_ir.semantics.scalar.string_language_constraint
    )
    rhs_shape = _string_language_constraint(
        rhs_ir.semantics.scalar.string_language_constraint
    )
    if lhs_shape is None or rhs_shape is None:
        return ProofResult.unsupported(
            "string language disjointness requires exact string language facts"
        )

    disjoint = lhs_shape.pattern.is_disjoint_from(
        rhs_shape.pattern, cast(RegexWorkContext, context)
    )
    if isinstance(disjoint, ProofResult):
        return disjoint
    if disjoint:
        return ProofResult.true()
    return ProofResult.unsupported(
        "string language disjointness could not be proven exactly"
    )


def _numeric_shape_emptiness_ir(ir: LogicalSchemaIR) -> ProofResult:
    if not _type_atoms(ir) <= {"integer", "number"}:
        return ProofResult.unsupported(
            "numeric emptiness requires numeric-only schemas"
        )

    shape = ir.semantics.scalar.numeric_constraint
    if shape is None:
        return ProofResult.unsupported("numeric emptiness requires exact shape")
    if not shape.normalized_atoms() and not shape.accepts_non_numeric:
        return ProofResult.true()
    return ProofResult.unsupported("numeric schema is not empty by shape")


def _object_count_disjointness_ir(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    shared_types = _type_atoms(lhs_ir) & _type_atoms(rhs_ir)
    if shared_types != {"object"}:
        return ProofResult.unsupported(
            "object count disjointness requires object-only intersection"
        )

    lhs_shape = lhs_ir.semantics.object.object_property_count_constraint
    rhs_shape = rhs_ir.semantics.object.object_property_count_constraint
    if lhs_shape is None or rhs_shape is None:
        return ProofResult.unsupported(
            "object count disjointness requires exact property-count shapes"
        )

    intersection = lhs_shape.intersect(rhs_shape)
    if (
        not intersection.normalized_intervals()
        and not intersection.accepts_non_object
    ):
        return ProofResult.true()

    witness = intersection.witness_not_in(
        ObjectPropertyCountConstraint((), accepts_non_object=False)
    )
    if witness is not None:
        shared = _confirmed_shared_witness_ir(lhs_ir, rhs_ir, witness, context)
        proof = _proof_from_shared_witness(shared)
        if proof is not None:
            return proof

    return ProofResult.unsupported(
        "object count disjointness could not be proven exactly"
    )


def _object_count_emptiness_ir(ir: LogicalSchemaIR) -> ProofResult:
    if _type_atoms(ir) != {"object"}:
        return ProofResult.unsupported(
            "object count emptiness requires object-only schemas"
        )

    shape = ir.semantics.object.object_property_count_constraint
    if shape is None:
        return ProofResult.unsupported(
            "object count emptiness requires exact property-count shape"
        )
    if not shape.normalized_intervals() and not shape.accepts_non_object:
        return ProofResult.true()
    return ProofResult.unsupported("object schema is not empty by property count")


def _array_length_disjointness_ir(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    shared_types = _type_atoms(lhs_ir) & _type_atoms(rhs_ir)
    if shared_types != {"array"}:
        return ProofResult.unsupported(
            "array length disjointness requires array-only intersection"
        )

    lhs_shape = lhs_ir.semantics.array.array_length_rhs_constraint
    rhs_shape = rhs_ir.semantics.array.array_length_rhs_constraint
    if lhs_shape is None or rhs_shape is None:
        return ProofResult.unsupported(
            "array length disjointness requires exact length shapes"
        )

    intersection = lhs_shape.intersect(rhs_shape)
    if not intersection.normalized_intervals() and not intersection.accepts_non_array:
        return ProofResult.true()

    witness = intersection.witness_not_in(
        ArrayLengthConstraint((), accepts_non_array=False)
    )
    if witness is not None:
        shared = _confirmed_shared_witness_ir(lhs_ir, rhs_ir, witness, context)
        proof = _proof_from_shared_witness(shared)
        if proof is not None:
            return proof

    return ProofResult.unsupported(
        "array length disjointness could not be proven exactly"
    )


def _array_length_emptiness_ir(ir: LogicalSchemaIR) -> ProofResult:
    if _type_atoms(ir) != {"array"}:
        return ProofResult.unsupported(
            "array length emptiness requires array-only schemas"
        )

    shape = ir.semantics.array.array_length_rhs_constraint
    if shape is None:
        return ProofResult.unsupported(
            "array length emptiness requires exact length shape"
        )
    if not shape.normalized_intervals() and not shape.accepts_non_array:
        return ProofResult.true()
    return ProofResult.unsupported("array schema is not empty by length")


def _array_unique_items_cardinality_emptiness_ir(
    ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    if _type_atoms(ir) != {"array"}:
        return ProofResult.unsupported(
            "array uniqueItems cardinality emptiness requires array-only schemas"
        )
    uniqueness = ir.semantics.array.array_uniqueness_rhs_constraint
    if uniqueness is None or not uniqueness.requires_unique_items:
        return ProofResult.unsupported(
            "array uniqueItems cardinality emptiness requires uniqueItems"
        )

    shape = ir.semantics.array.array_cardinality_length_constraint
    if shape is None:
        return ProofResult.unsupported(
            "array uniqueItems cardinality emptiness requires exact length shape"
        )
    intervals = shape.normalized_intervals()
    if not intervals and not shape.accepts_non_array:
        return ProofResult.true()

    lower_bound = min((interval.lower for interval in intervals), default=0)
    value_bound = _array_unique_items_value_bound(ir, context)
    if value_bound is None:
        return ProofResult.unsupported(
            "array uniqueItems cardinality emptiness requires finite item values"
        )
    if lower_bound > value_bound:
        return ProofResult.true()
    return ProofResult.unsupported(
        "array schema is not empty by uniqueItems cardinality"
    )


def _array_unique_items_value_bound(
    ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> int | None:
    item_model = ir.semantics.array.array_item_model_constraint
    if item_model is None or item_model.covering_all_item_terms is None:
        return None

    value_keys: set[str] = set()
    for item_term in item_model.covering_all_item_terms:
        values = _finite_values_for_reachable_item_term(item_term, ir)
        if values is None:
            return None
        value_keys.update(json_semantic_key(value) for value in values)
    return len(value_keys)


def _finite_values_for_reachable_item_term(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
) -> list[Any] | None:
    item_ir = _term_node_ir(term, ir)
    if item_ir is None:
        return None
    if (
        item_ir.semantics.reference.has_static_reference_boundary
        or item_ir.semantics.reference.has_dynamic_reference
        or item_ir.semantics.reference.has_recursive_reference
    ):
        return None
    return finite_values_for_ir(item_ir)


def _array_item_disjointness_ir(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    shared_types = _type_atoms(lhs_ir) & _type_atoms(rhs_ir)
    if shared_types != {"array"}:
        return ProofResult.unsupported(
            "array item disjointness requires array-only intersection"
        )

    lhs_item = _first_required_array_item_term(lhs_ir)
    rhs_item = _first_required_array_item_term(rhs_ir)
    if lhs_item is None or rhs_item is None:
        required_slot_disjoint = _required_array_slot_disjointness_ir(
            lhs_ir,
            rhs_ir,
            context,
            depth=depth,
        )
        if required_slot_disjoint.status != "unsupported":
            return required_slot_disjoint
        return ProofResult.unsupported(
            "array item disjointness requires a shared required item position"
        )

    item_disjoint = terms_are_disjoint(
        lhs_item, lhs_ir, rhs_item, rhs_ir, context
    )
    if item_disjoint.status in {"proved_true", "resource_exhausted"}:
        return item_disjoint
    required_slot_disjoint = _required_array_slot_disjointness_ir(
        lhs_ir,
        rhs_ir,
        context,
        depth=depth,
    )
    if required_slot_disjoint.status != "unsupported":
        return required_slot_disjoint
    return ProofResult.unsupported(
        "array item disjointness could not be proven exactly"
    )


def _first_required_array_item_term(ir: LogicalSchemaIR) -> SchemaTerm | None:
    item_model = ir.semantics.array.array_item_model_constraint
    return None if item_model is None else item_model.first_required_item_term


def _required_array_slot_disjointness_ir(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    lhs_shape = lhs_ir.semantics.array.array_cardinality_length_constraint
    rhs_shape = rhs_ir.semantics.array.array_cardinality_length_constraint
    if lhs_shape is None or rhs_shape is None:
        return ProofResult.unsupported(
            "array item disjointness requires exact shared length facts"
        )

    shared_shape = lhs_shape.intersect(rhs_shape)
    intervals = shared_shape.normalized_intervals()
    if not intervals and not shared_shape.accepts_non_array:
        return ProofResult.true()

    required_length = min((interval.lower for interval in intervals), default=0)
    lhs_item_model = lhs_ir.semantics.array.array_item_model_constraint
    rhs_item_model = rhs_ir.semantics.array.array_item_model_constraint
    lhs_indexes = (
        None
        if lhs_item_model is None
        else lhs_item_model.candidate_indexes(required_length)
    )
    rhs_indexes = (
        None
        if rhs_item_model is None
        else rhs_item_model.candidate_indexes(required_length)
    )
    if lhs_indexes is None or rhs_indexes is None:
        return ProofResult.unsupported(
            "array item disjointness requires supported item schema indexes"
        )
    assert lhs_item_model is not None
    assert rhs_item_model is not None

    unsupported: ProofResult | None = None
    for index in sorted(set(lhs_indexes) | set(rhs_indexes)):
        if index >= required_length:
            continue
        lhs_item = lhs_item_model.term_at_index(index)
        rhs_item = rhs_item_model.term_at_index(index)
        if lhs_item is None or rhs_item is None:
            continue
        item_disjoint = terms_are_disjoint(
            lhs_item,
            lhs_ir,
            rhs_item,
            rhs_ir,
            context,
        )
        if item_disjoint.status == "proved_true":
            return item_disjoint
        if item_disjoint.status == "resource_exhausted":
            return item_disjoint
        if item_disjoint.status == "unsupported":
            unsupported = item_disjoint

    return unsupported or ProofResult.unsupported(
        "array item disjointness found no required conflicting item position"
    )


def _array_contains_emptiness_ir(
    ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    contains = ir.semantics.array.array_contains_constraint
    contains_term = None if contains is None else contains.term
    if contains is None or contains_term is None or _type_atoms(ir) != {"array"}:
        return ProofResult.unsupported(
            "array contains emptiness requires array-only contains schema"
        )

    minimum = contains.minimum
    maximum = contains.maximum
    if maximum is not None and minimum > maximum:
        return ProofResult.true()
    if minimum > 0 and contains_term.kind == "false":
        return ProofResult.true()
    if minimum > 0 and _all_array_items_are_disjoint_from_contains_term(
        ir, contains_term, context
    ):
        return ProofResult.true()
    if maximum is not None:
        guaranteed = guaranteed_contains_matches(ir, contains, context)
        if guaranteed > maximum:
            return ProofResult.true()

    return ProofResult.unsupported(
        "array contains emptiness could not be proven exactly"
    )


def _all_array_items_are_disjoint_from_contains_term(
    ir: LogicalSchemaIR,
    contains_term: SchemaTerm,
    context: DisjointnessContext,
) -> bool:
    item_model = ir.semantics.array.array_item_model_constraint
    if item_model is None or item_model.covering_all_item_terms is None:
        return False
    for item_term in item_model.covering_all_item_terms:
        disjoint = terms_are_disjoint(
            item_term, ir, contains_term, ir, context
        )
        if disjoint.status != "proved_true":
            return False
    return True


def _closed_finite_object_disjointness_ir(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    shared_types = _type_atoms(lhs_ir) & _type_atoms(rhs_ir)
    if shared_types != {"object"}:
        return ProofResult.unsupported(
            "closed object disjointness requires object-only intersection"
        )

    lhs_shape = lhs_ir.semantics.object.object_closed_properties_constraint
    rhs_shape = rhs_ir.semantics.object.object_closed_properties_constraint
    if (
        lhs_shape is None
        or rhs_shape is None
        or not _is_finite_closed_object_shape(lhs_shape)
        or not _is_finite_closed_object_shape(rhs_shape)
    ):
        return ProofResult.unsupported(
            "closed object disjointness requires finite closed-property shapes"
        )

    intersection = lhs_shape.intersect(rhs_shape)
    if not intersection.object_is_inhabited():
        return ProofResult.true()

    for name in sorted(intersection.required):
        lhs_term = lhs_shape.property_term_for(name)
        rhs_term = rhs_shape.property_term_for(name)
        if lhs_term is None or rhs_term is None:
            return ProofResult.unsupported(
                "closed object disjointness requires property schema terms"
            )
        value_disjoint = terms_are_disjoint(
            lhs_term,
            lhs_ir,
            rhs_term,
            rhs_ir,
            context,
        )
        if value_disjoint.status == "proved_true":
            return ProofResult.true()
        if value_disjoint.status == "resource_exhausted":
            return value_disjoint

    witness = intersection.object_witness(context.dialect)
    if witness is not None:
        shared = _confirmed_shared_witness_ir(lhs_ir, rhs_ir, witness, context)
        proof = _proof_from_shared_witness(shared)
        if proof is not None:
            return proof

    return ProofResult.unsupported(
        "closed object disjointness could not be proven exactly"
    )


def _is_finite_closed_object_shape(shape: Any) -> bool:
    return (
        shape.has_finite_keyspace
        and not shape.accepts_non_object
        and not shape.pattern_property_terms
    )


def _confirmed_shared_witness_ir(
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
    witness: Any,
    context: DisjointnessContext,
) -> SharedWitnessConfirmation:
    lhs_confirmed = confirm_valid(lhs.source.to_source(), witness, context)
    if lhs_confirmed.status == "unsupported":
        return SharedWitnessConfirmation("unsupported", lhs_confirmed.proof)
    if lhs_confirmed.status == "rejected":
        return SharedWitnessConfirmation("rejected")
    rhs_confirmed = confirm_valid(rhs.source.to_source(), witness, context)
    if rhs_confirmed.status == "unsupported":
        return SharedWitnessConfirmation("unsupported", rhs_confirmed.proof)
    if rhs_confirmed.status == "confirmed":
        return SharedWitnessConfirmation(
            "confirmed_false", ProofResult.false(witness)
        )
    return SharedWitnessConfirmation("rejected")


def _proof_from_shared_witness(
    shared: SharedWitnessConfirmation,
) -> ProofResult | None:
    if shared.status == "confirmed_false" and shared.proof is not None:
        return shared.proof
    if shared.status == "unsupported" and shared.proof is not None:
        return shared.proof
    return None


def _object_required_property_conflict_ir(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    shared_types = _type_atoms(lhs_ir) & _type_atoms(rhs_ir)
    if shared_types != {"object"}:
        return ProofResult.unsupported(
            "object property disjointness requires object-only intersection"
        )

    lhs_constraint = lhs_ir.semantics.object.object_key_value_constraint
    rhs_constraint = rhs_ir.semantics.object.object_key_value_constraint
    if lhs_constraint is None or rhs_constraint is None:
        return ProofResult.unsupported(
            "object property disjointness requires object key-value facts"
        )

    lhs_required = lhs_constraint.required
    rhs_required = rhs_constraint.required
    if not lhs_required or not rhs_required:
        return ProofResult.unsupported(
            "object property disjointness requires shared required properties"
        )

    for name in sorted(
        lhs_required
        & rhs_required
        & lhs_constraint.properties
        & rhs_constraint.properties
    ):
        lhs_term = lhs_constraint.value_term_for(name)
        rhs_term = rhs_constraint.value_term_for(name)
        if lhs_term is None or rhs_term is None:
            return ProofResult.unsupported(
                "object property disjointness requires property schema terms"
            )
        value_disjoint = terms_are_disjoint(
            lhs_term,
            lhs_ir,
            rhs_term,
            rhs_ir,
            context,
        )
        if value_disjoint.status == "proved_true":
            return ProofResult.true()
        if value_disjoint.status == "resource_exhausted":
            return value_disjoint

    return ProofResult.unsupported(
        "object required property values could not be proven disjoint"
    )


def terms_are_disjoint(
    lhs: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    rhs: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    if lhs.kind == "false" or rhs.kind == "false":
        return ProofResult.true()
    if lhs.kind == "true" or rhs.kind == "true":
        return ProofResult.unsupported(
            "schema term disjointness cannot prove unconstrained terms disjoint"
        )
    conjunct_disjointness = _all_of_conjunct_disjointness(
        lhs, lhs_ir, rhs, rhs_ir, context
    )
    if conjunct_disjointness.status != "unsupported":
        return conjunct_disjointness
    lhs_node_ir = _term_node_ir(lhs, lhs_ir)
    rhs_node_ir = _term_node_ir(rhs, rhs_ir)
    if lhs_node_ir is not None and rhs_node_ir is not None:
        lhs_values = finite_values_for_ir(lhs_node_ir)
        rhs_values = finite_values_for_ir(rhs_node_ir)
        if lhs_values is not None and rhs_values is not None:
            finite_proof = _finite_candidate_disjointness(
                lhs_node_ir, rhs_node_ir, lhs_values, rhs_values, context
            )
            if finite_proof.status != "unsupported":
                return finite_proof
        finite_complement = _finite_complement_term_intersection(
            lhs_node_ir, rhs_node_ir, context
        )
        if finite_complement is not None:
            return finite_complement
        if not (_type_atoms(lhs_node_ir) & _type_atoms(rhs_node_ir)):
            return ProofResult.true()
        node_disjointness = _irs_are_disjoint(
            lhs_node_ir, rhs_node_ir, context, depth=0
        )
        if node_disjointness.status != "unsupported":
            return node_disjointness
    return context.subproof_terms(lhs, lhs_ir, SchemaTerm.not_(rhs), rhs_ir)


def _all_of_conjunct_disjointness(
    lhs: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    rhs: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    if lhs.kind == "all_of":
        return _any_conjunct_disjoint_from_term(
            lhs.children, lhs_ir, rhs, rhs_ir, context
        )
    if rhs.kind == "all_of":
        return _any_conjunct_disjoint_from_term(
            rhs.children, rhs_ir, lhs, lhs_ir, context
        )
    return ProofResult.unsupported(
        "schema term disjointness has no allOf conjunct proof"
    )


def _any_conjunct_disjoint_from_term(
    conjuncts: tuple[SchemaTerm, ...],
    conjunct_ir: LogicalSchemaIR,
    other: SchemaTerm,
    other_ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult:
    if other.kind != "node":
        return ProofResult.unsupported(
            "schema term allOf conjunct disjointness requires node terms"
        )
    unsupported: ProofResult | None = None
    for conjunct in conjuncts:
        if conjunct.kind != "node":
            unsupported = (
                unsupported
                or ProofResult.unsupported(
                    "schema term allOf conjunct disjointness requires node terms"
                )
            )
            continue
        proof = terms_are_disjoint(conjunct, conjunct_ir, other, other_ir, context)
        if proof.status == "proved_true":
            return ProofResult.true()
        if proof.status == "resource_exhausted":
            unsupported = proof
            continue
        if proof.status == "unsupported":
            unsupported = proof
            continue
    if unsupported is not None:
        return unsupported
    return ProofResult.unsupported(
        "schema term allOf conjunct disjointness could not be proven exactly"
    )


def _finite_complement_term_intersection(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: DisjointnessContext,
) -> ProofResult | None:
    rhs_excluded = finite_complement_excluded_values_for_ir(rhs_ir, context)
    if rhs_excluded is not None:
        proof = _term_intersection_against_excluded_values(
            lhs_ir, rhs_ir, rhs_excluded, context
        )
        if proof is not None:
            return proof

    lhs_excluded = finite_complement_excluded_values_for_ir(lhs_ir, context)
    if lhs_excluded is not None:
        proof = _term_intersection_against_excluded_values(
            rhs_ir, lhs_ir, lhs_excluded, context
        )
        if proof is not None:
            return proof
    return None


def _term_intersection_against_excluded_values(
    candidate_ir: LogicalSchemaIR,
    complement_ir: LogicalSchemaIR,
    excluded_values: tuple[Any, ...],
    context: DisjointnessContext,
) -> ProofResult | None:
    excluded_keys = {json_semantic_key(value) for value in excluded_values}
    candidate_values = finite_values_for_ir(candidate_ir)
    if candidate_values is not None:
        allowed = tuple(
            value
            for value in candidate_values
            if json_semantic_key(value) not in excluded_keys
        )
        if not allowed:
            return ProofResult.true()
        unsupported: ProofResult | None = None
        for value in allowed:
            shared = _confirmed_shared_witness_ir(
                candidate_ir, complement_ir, value, context
            )
            proof = _proof_from_shared_witness(shared)
            if proof is not None:
                return proof
            if shared.status == "unsupported":
                unsupported = shared.proof or ProofResult.unsupported(
                    "finite candidate witness confirmation failed"
                )
        if unsupported is not None:
            return unsupported
        return ProofResult.true()

    witness = build_ir_witness(candidate_ir, context)
    if not witness.has_witness:
        return None
    if json_semantic_key(witness.witness) in excluded_keys:
        return None
    shared = _confirmed_shared_witness_ir(
        candidate_ir, complement_ir, witness.witness, context
    )
    return _proof_from_shared_witness(shared)


def _finite_candidate_disjointness(
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    lhs_values: list[Any],
    rhs_values: list[Any],
    context: DisjointnessContext,
) -> ProofResult:
    lhs_keys = {json_semantic_key(value) for value in lhs_values}
    rhs_keys = {json_semantic_key(value) for value in rhs_values}
    shared_keys = lhs_keys & rhs_keys
    if not shared_keys:
        return ProofResult.true()

    unsupported: ProofResult | None = None
    for value in lhs_values:
        if json_semantic_key(value) not in shared_keys:
            continue
        shared = _confirmed_shared_witness_ir(lhs_ir, rhs_ir, value, context)
        proof = _proof_from_shared_witness(shared)
        if proof is not None:
            return proof
        if shared.status == "unsupported":
            unsupported = shared.proof or ProofResult.unsupported(
                "finite candidate witness confirmation failed"
            )
    if unsupported is not None:
        return unsupported
    return ProofResult.true()


def _term_node_ir(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
) -> LogicalSchemaIR | None:
    if term.kind != "node" or term.ref is None:
        return None
    node = ir.node_for_ref(term.ref)
    return None if node is None else ir.with_root_ref(node.ref)
