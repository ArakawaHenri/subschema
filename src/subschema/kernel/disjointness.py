"""
Shared schema-language disjointness helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from subschema.kernel.contracts import ProofResult
from subschema.kernel.domains.strings import (
    string_language_fragments_are_disjoint,
    string_length_fragments_are_disjoint,
)
from subschema.kernel.domains.types import (
    schema_type_overapproximations_are_disjoint,
    type_overapproximation_for_schema,
)
from subschema.kernel.validation import validation_backend_for
from subschema.kernel.witnesses import build_schema_witness, finite_projection_witness

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext

__all__ = [
    "schemas_are_disjoint",
]


def schemas_are_disjoint(
    lhs: Any,
    rhs: Any,
    context: ProofContext,
) -> ProofResult:
    return _schemas_are_disjoint(lhs, rhs, context, depth=0)


def _schemas_are_disjoint(
    lhs: Any,
    rhs: Any,
    context: ProofContext,
    *,
    depth: int,
) -> ProofResult:
    if depth > 8:
        return ProofResult.unsupported(
            "schema disjointness recursion limit was reached"
        )

    finite_intersection = context.finite_meet_projection(lhs, rhs)
    if finite_intersection is False:
        return ProofResult.true()
    finite_witness = finite_projection_witness(finite_intersection, context.dialect)
    if finite_witness.has_witness:
        return ProofResult.false(finite_witness.witness)

    if schema_type_overapproximations_are_disjoint(lhs, rhs):
        return ProofResult.true()
    if string_length_fragments_are_disjoint(lhs, rhs):
        return ProofResult.true()
    if string_language_fragments_are_disjoint(lhs, rhs):
        return ProofResult.true()
    closed_object_disjointness = _closed_finite_object_disjointness(
        lhs, rhs, context, depth=depth
    )
    if closed_object_disjointness.status != "unsupported":
        return closed_object_disjointness
    object_property_conflict = _object_required_property_conflict(
        lhs, rhs, context, depth=depth
    )
    if object_property_conflict.status != "unsupported":
        return object_property_conflict
    intersection_witness = build_schema_witness(
        {"allOf": [lhs, rhs]},
        context.dialect,
        context,
    )
    if intersection_witness.status == "resource_exhausted":
        return ProofResult.resource_exhausted(intersection_witness.reason)
    if intersection_witness.has_witness:
        backend = validation_backend_for(context.dialect)
        if backend.is_valid(lhs, intersection_witness.witness) and backend.is_valid(
            rhs, intersection_witness.witness
        ):
            return ProofResult.false(intersection_witness.witness)

    return ProofResult.unsupported("schema disjointness could not be proven exactly")


def _closed_finite_object_disjointness(
    lhs: Any,
    rhs: Any,
    context: ProofContext,
    *,
    depth: int,
) -> ProofResult:
    if not isinstance(lhs, dict) or not isinstance(rhs, dict):
        return ProofResult.unsupported(
            "closed object disjointness requires object schemas"
        )

    shared_types = type_overapproximation_for_schema(
        lhs
    ) & type_overapproximation_for_schema(rhs)
    if shared_types != {"object"}:
        return ProofResult.unsupported(
            "closed object disjointness requires object-only intersection"
        )

    from subschema.kernel.domains.objects import (
        closed_object_properties_shape_for_schema,
    )

    lhs_shape = closed_object_properties_shape_for_schema(lhs)
    rhs_shape = closed_object_properties_shape_for_schema(rhs)
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
        value_disjoint = _schemas_are_disjoint(
            lhs_shape.property_schema_for(name),
            rhs_shape.property_schema_for(name),
            context,
            depth=depth + 1,
        )
        if value_disjoint.status == "proved_true":
            return ProofResult.true()
        if value_disjoint.status == "resource_exhausted":
            return value_disjoint

    witness = intersection.object_witness(context.dialect)
    if witness is not None:
        backend = validation_backend_for(context.dialect)
        if backend.is_valid(lhs, witness) and backend.is_valid(rhs, witness):
            return ProofResult.false(witness)

    return ProofResult.unsupported(
        "closed object disjointness could not be proven exactly"
    )


def _is_finite_closed_object_shape(shape: Any) -> bool:
    return (
        shape.has_finite_keyspace
        and not shape.accepts_non_object
        and not shape.pattern_property_schemas
    )


def _object_required_property_conflict(
    lhs: Any,
    rhs: Any,
    context: ProofContext,
    *,
    depth: int,
) -> ProofResult:
    if not isinstance(lhs, dict) or not isinstance(rhs, dict):
        return ProofResult.unsupported(
            "object property disjointness requires object schemas"
        )

    shared_types = type_overapproximation_for_schema(
        lhs
    ) & type_overapproximation_for_schema(rhs)
    if shared_types != {"object"}:
        return ProofResult.unsupported(
            "object property disjointness requires object-only intersection"
        )

    lhs_required = _required_names(lhs)
    rhs_required = _required_names(rhs)
    if not lhs_required or not rhs_required:
        return ProofResult.unsupported(
            "object property disjointness requires shared required properties"
        )

    lhs_properties = _property_schemas(lhs)
    rhs_properties = _property_schemas(rhs)
    for name in sorted(
        lhs_required & rhs_required & lhs_properties.keys() & rhs_properties.keys()
    ):
        value_disjoint = _schemas_are_disjoint(
            lhs_properties[name],
            rhs_properties[name],
            context,
            depth=depth + 1,
        )
        if value_disjoint.status == "proved_true":
            return ProofResult.true()
        if value_disjoint.status == "resource_exhausted":
            return value_disjoint

    return ProofResult.unsupported(
        "object required property values could not be proven disjoint"
    )


def _required_names(schema: dict[str, Any]) -> frozenset[str]:
    required = schema.get("required")
    if not isinstance(required, list):
        return frozenset()
    return frozenset(name for name in required if isinstance(name, str))


def _property_schemas(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    return {
        name: subschema
        for name, subschema in properties.items()
        if isinstance(name, str)
    }
