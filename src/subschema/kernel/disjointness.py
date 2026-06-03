"""
Shared schema-language disjointness helpers.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from subschema.dialects import Dialect
from subschema.kernel.contracts import ProofResult
from subschema.kernel.domains.arrays import (
    ArrayShape,
    _minimum_contains_matches_guaranteed,
    array_shape_for_schema,
)
from subschema.kernel.domains.numbers import NumericShape, numeric_shape_for_schema
from subschema.kernel.domains.objects import (
    ObjectPropertyCountShape,
    closed_object_properties_shape_for_schema,
    object_property_count_shape_for_schema,
)
from subschema.kernel.domains.strings import (
    string_language_fragments_are_disjoint,
    string_length_fragments_are_disjoint,
)
from subschema.kernel.domains.types import (
    schema_type_overapproximations_are_disjoint,
    type_overapproximation_for_schema,
)
from subschema.kernel.schemas import IGNORED_SCHEMA_METADATA_KEYS
from subschema.kernel.validation import validation_backend_for
from subschema.kernel.witnesses import build_schema_witness, finite_projection_witness

__all__ = [
    "schema_is_empty_exact",
    "schemas_are_disjoint",
]


class DisjointnessContext(Protocol):
    dialect: Dialect

    def finite_meet_projection(self, lhs: Any, rhs: Any) -> Any | None: ...


def schema_is_empty_exact(schema: Any, context: DisjointnessContext) -> ProofResult:
    if schema is False:
        return ProofResult.true()
    if schema is True:
        return ProofResult.false(None)

    array_empty = _array_contains_emptiness(schema, context)
    if array_empty.status != "unsupported":
        return array_empty

    numeric_empty = _numeric_shape_emptiness(schema, context)
    if numeric_empty.status != "unsupported":
        return numeric_empty

    object_empty = _object_count_emptiness(schema, context)
    if object_empty.status != "unsupported":
        return object_empty

    array_empty = _array_length_emptiness(schema, context)
    if array_empty.status != "unsupported":
        return array_empty

    witness = build_schema_witness(schema, context.dialect, cast(Any, context))
    if witness.status == "resource_exhausted":
        return ProofResult.resource_exhausted(witness.reason)
    if witness.has_witness:
        backend = validation_backend_for(context.dialect)
        if backend.is_valid(schema, witness.witness):
            return ProofResult.false(witness.witness)

    return ProofResult.unsupported("schema emptiness could not be proven exactly")


def schemas_are_disjoint(
    lhs: Any,
    rhs: Any,
    context: DisjointnessContext,
) -> ProofResult:
    return _schemas_are_disjoint(lhs, rhs, context, depth=0)


def _schemas_are_disjoint(
    lhs: Any,
    rhs: Any,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    if depth > 8:
        return ProofResult.unsupported(
            "schema disjointness recursion limit was reached"
        )

    applicator_disjointness = _union_applicator_disjointness(
        lhs, rhs, context, depth=depth
    )
    if applicator_disjointness.status != "unsupported":
        return applicator_disjointness

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
    numeric_disjointness = _numeric_disjointness(lhs, rhs, context)
    if numeric_disjointness.status != "unsupported":
        return numeric_disjointness
    object_count_disjointness = _object_count_disjointness(lhs, rhs, context)
    if object_count_disjointness.status != "unsupported":
        return object_count_disjointness
    array_length_disjointness = _array_length_disjointness(lhs, rhs, context)
    if array_length_disjointness.status != "unsupported":
        return array_length_disjointness
    array_item_disjointness = _array_item_disjointness(
        lhs, rhs, context, depth=depth
    )
    if array_item_disjointness.status != "unsupported":
        return array_item_disjointness
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
        cast(Any, context),
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


def _union_applicator_disjointness(
    lhs: Any,
    rhs: Any,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    lhs_branches = _union_applicator_branch_schemas(lhs)
    if lhs_branches is not None:
        return _branches_are_disjoint_from_schema(
            lhs, lhs_branches, rhs, context, depth=depth
        )

    rhs_branches = _union_applicator_branch_schemas(rhs)
    if rhs_branches is not None:
        return _branches_are_disjoint_from_schema(
            rhs, rhs_branches, lhs, context, depth=depth
        )

    return ProofResult.unsupported(
        "schema disjointness has no supported union applicator fragment"
    )


def _branches_are_disjoint_from_schema(
    union_schema: Any,
    branches: tuple[Any, ...],
    other_schema: Any,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    unsupported: ProofResult | None = None
    backend = validation_backend_for(context.dialect)
    for branch in branches:
        branch_disjoint = _schemas_are_disjoint(
            branch, other_schema, context, depth=depth + 1
        )
        if branch_disjoint.status == "proved_true":
            continue
        if branch_disjoint.status == "resource_exhausted":
            return branch_disjoint
        if branch_disjoint.status == "proved_false":
            witness = branch_disjoint.witness
            if (
                witness is not None
                and backend.is_valid(union_schema, witness)
                and backend.is_valid(other_schema, witness)
            ):
                return ProofResult.false(witness)
            unsupported = ProofResult.unsupported(
                "union branch intersection witness was not valid for the full schema"
            )
            continue
        unsupported = branch_disjoint
    return ProofResult.true() if unsupported is None else unsupported


def _union_applicator_branch_schemas(schema: Any) -> tuple[Any, ...] | None:
    if not isinstance(schema, dict):
        return None

    for keyword in ("anyOf", "oneOf"):
        branches = schema.get(keyword)
        if not isinstance(branches, list) or not branches:
            continue
        base = _schema_without_union_keyword(schema, keyword)
        if base is None:
            return None
        if not base:
            return tuple(branches)
        return tuple({"allOf": [base, branch]} for branch in branches)
    return None


def _schema_without_union_keyword(
    schema: dict[str, Any], keyword: str
) -> dict[str, Any] | None:
    base = {}
    for key, value in schema.items():
        if key == keyword or key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key in {"allOf", "anyOf", "oneOf", "not", "if", "then", "else"}:
            return None
        base[key] = value
    return base


def _numeric_disjointness(
    lhs: Any,
    rhs: Any,
    context: DisjointnessContext,
) -> ProofResult:
    shared_types = type_overapproximation_for_schema(
        lhs
    ) & type_overapproximation_for_schema(rhs)
    if not shared_types <= {"integer", "number"}:
        return ProofResult.unsupported(
            "numeric disjointness requires numeric-only intersection"
        )

    lhs_shape = numeric_shape_for_schema(lhs, context.dialect)
    rhs_shape = numeric_shape_for_schema(rhs, context.dialect)
    if lhs_shape is None or rhs_shape is None:
        return ProofResult.unsupported(
            "numeric disjointness requires exact numeric shapes"
        )

    intersection = lhs_shape.intersect(rhs_shape)
    if not intersection.normalized_atoms() and not intersection.accepts_non_numeric:
        return ProofResult.true()

    witness = intersection.witness_not_in(
        NumericShape((), accepts_non_numeric=False)
    )
    if witness is not None:
        backend = validation_backend_for(context.dialect)
        if backend.is_valid(lhs, witness) and backend.is_valid(rhs, witness):
            return ProofResult.false(witness)

    return ProofResult.unsupported(
        "numeric disjointness could not be proven exactly"
    )


def _numeric_shape_emptiness(schema: Any, context: DisjointnessContext) -> ProofResult:
    if not type_overapproximation_for_schema(schema) <= {"integer", "number"}:
        return ProofResult.unsupported(
            "numeric emptiness requires numeric-only schemas"
        )

    shape = numeric_shape_for_schema(schema, context.dialect)
    if shape is None:
        return ProofResult.unsupported("numeric emptiness requires exact shape")
    if not shape.normalized_atoms() and not shape.accepts_non_numeric:
        return ProofResult.true()
    return ProofResult.unsupported("numeric schema is not empty by shape")


def _object_count_disjointness(
    lhs: Any,
    rhs: Any,
    context: DisjointnessContext,
) -> ProofResult:
    shared_types = type_overapproximation_for_schema(
        lhs
    ) & type_overapproximation_for_schema(rhs)
    if shared_types != {"object"}:
        return ProofResult.unsupported(
            "object count disjointness requires object-only intersection"
        )

    lhs_shape = object_property_count_shape_for_schema(lhs)
    rhs_shape = object_property_count_shape_for_schema(rhs)
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
        ObjectPropertyCountShape((), accepts_non_object=False)
    )
    if witness is not None:
        backend = validation_backend_for(context.dialect)
        if backend.is_valid(lhs, witness) and backend.is_valid(rhs, witness):
            return ProofResult.false(witness)

    return ProofResult.unsupported(
        "object count disjointness could not be proven exactly"
    )


def _object_count_emptiness(schema: Any, context: DisjointnessContext) -> ProofResult:
    if type_overapproximation_for_schema(schema) != {"object"}:
        return ProofResult.unsupported(
            "object count emptiness requires object-only schemas"
        )

    shape = object_property_count_shape_for_schema(schema)
    if shape is None:
        return ProofResult.unsupported(
            "object count emptiness requires exact property-count shape"
        )
    if not shape.normalized_intervals() and not shape.accepts_non_object:
        return ProofResult.true()
    return ProofResult.unsupported("object schema is not empty by property count")


def _array_length_disjointness(
    lhs: Any,
    rhs: Any,
    context: DisjointnessContext,
) -> ProofResult:
    shared_types = type_overapproximation_for_schema(
        lhs
    ) & type_overapproximation_for_schema(rhs)
    if shared_types != {"array"}:
        return ProofResult.unsupported(
            "array length disjointness requires array-only intersection"
        )

    lhs_shape = array_shape_for_schema(
        lhs, context.dialect, allow_item_value_constraints=False
    )
    rhs_shape = array_shape_for_schema(
        rhs, context.dialect, allow_item_value_constraints=False
    )
    if lhs_shape is None or rhs_shape is None:
        return ProofResult.unsupported(
            "array length disjointness requires exact length shapes"
        )

    intersection = lhs_shape.intersect(rhs_shape)
    if not intersection.normalized_intervals() and not intersection.accepts_non_array:
        return ProofResult.true()

    witness = intersection.witness_not_in(ArrayShape((), accepts_non_array=False))
    if witness is not None:
        backend = validation_backend_for(context.dialect)
        if backend.is_valid(lhs, witness) and backend.is_valid(rhs, witness):
            return ProofResult.false(witness)

    return ProofResult.unsupported(
        "array length disjointness could not be proven exactly"
    )


def _array_length_emptiness(schema: Any, context: DisjointnessContext) -> ProofResult:
    if type_overapproximation_for_schema(schema) != {"array"}:
        return ProofResult.unsupported(
            "array length emptiness requires array-only schemas"
        )

    shape = array_shape_for_schema(
        schema, context.dialect, allow_item_value_constraints=False
    )
    if shape is None:
        return ProofResult.unsupported(
            "array length emptiness requires exact length shape"
        )
    if not shape.normalized_intervals() and not shape.accepts_non_array:
        return ProofResult.true()
    return ProofResult.unsupported("array schema is not empty by length")


def _array_item_disjointness(
    lhs: Any,
    rhs: Any,
    context: DisjointnessContext,
    *,
    depth: int,
) -> ProofResult:
    shared_types = type_overapproximation_for_schema(
        lhs
    ) & type_overapproximation_for_schema(rhs)
    if shared_types != {"array"}:
        return ProofResult.unsupported(
            "array item disjointness requires array-only intersection"
        )

    lhs_item = _first_required_array_item_schema(lhs, context)
    rhs_item = _first_required_array_item_schema(rhs, context)
    if lhs_item is None or rhs_item is None:
        return ProofResult.unsupported(
            "array item disjointness requires a shared required item position"
        )

    item_disjoint = _schemas_are_disjoint(
        lhs_item, rhs_item, context, depth=depth + 1
    )
    if item_disjoint.status in {"proved_true", "resource_exhausted"}:
        return item_disjoint
    return ProofResult.unsupported(
        "array item disjointness could not be proven exactly"
    )


def _first_required_array_item_schema(
    schema: Any,
    context: DisjointnessContext,
) -> Any | None:
    if not isinstance(schema, dict):
        return None
    minimum = schema.get("minItems", 0)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum <= 0:
        return None

    if context.dialect is Dialect.DRAFT202012:
        prefix = schema.get("prefixItems")
        if isinstance(prefix, list) and prefix:
            return prefix[0]
        items = schema.get("items", True)
        return items if isinstance(items, bool | dict) else None

    items = schema.get("items", True)
    if isinstance(items, list):
        return items[0] if items else None
    return items if isinstance(items, bool | dict) else None


def _array_contains_emptiness(schema: Any, context: DisjointnessContext) -> ProofResult:
    if (
        not isinstance(schema, dict)
        or "contains" not in schema
        or type_overapproximation_for_schema(schema) != {"array"}
    ):
        return ProofResult.unsupported(
            "array contains emptiness requires array-only contains schema"
        )

    counts = _array_contains_counts(schema)
    if counts is None:
        return ProofResult.unsupported(
            "array contains emptiness requires exact contains counts"
        )
    minimum, maximum = counts
    if maximum is not None and minimum > maximum:
        return ProofResult.true()
    if minimum > 0 and schema["contains"] is False:
        return ProofResult.true()
    if minimum > 0 and _all_array_items_are_disjoint_from_contains(schema, context):
        return ProofResult.true()
    if maximum is not None:
        guaranteed = _guaranteed_contains_matches(schema, context)
        if guaranteed is not None and guaranteed > maximum:
            return ProofResult.true()

    return ProofResult.unsupported(
        "array contains emptiness could not be proven exactly"
    )


def _array_contains_counts(schema: dict[str, Any]) -> tuple[int, int | None] | None:
    minimum = schema.get("minContains", 1)
    maximum = schema.get("maxContains")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None
    return minimum, maximum


def _all_array_items_are_disjoint_from_contains(
    schema: dict[str, Any],
    context: DisjointnessContext,
) -> bool:
    item_schemas = _schemas_covering_all_array_items(schema, context)
    if item_schemas is None:
        return False
    contains_schema = schema["contains"]
    for item_schema in item_schemas:
        disjoint = _schemas_are_disjoint(
            item_schema, contains_schema, context, depth=1
        )
        if disjoint.status != "proved_true":
            return False
    return True


def _schemas_covering_all_array_items(
    schema: dict[str, Any],
    context: DisjointnessContext,
) -> tuple[Any, ...] | None:
    if context.dialect is Dialect.DRAFT202012:
        prefix = schema.get("prefixItems")
        prefix_schemas = tuple(prefix) if isinstance(prefix, list) else ()
        items = schema.get("items", True)
        if items is False:
            return prefix_schemas
        if isinstance(items, dict):
            return prefix_schemas + (items,)
        return None

    items = schema.get("items", True)
    if isinstance(items, dict | bool):
        return (items,)
    if isinstance(items, list):
        prefix_schemas = tuple(items)
        additional = schema.get("additionalItems", True)
        if additional is False:
            return prefix_schemas
        if isinstance(additional, dict):
            return prefix_schemas + (additional,)
    return None


def _guaranteed_contains_matches(
    schema: dict[str, Any],
    context: DisjointnessContext,
) -> int | None:
    return _minimum_contains_matches_guaranteed(
        schema,
        schema["contains"],
        context.dialect,
        context=cast(Any, context),
    )


def _closed_finite_object_disjointness(
    lhs: Any,
    rhs: Any,
    context: DisjointnessContext,
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
    context: DisjointnessContext,
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
