"""
Array length, uniqueness, and contains reasoning for exact subschema proofs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from subschema.dialects import Dialect, KeywordCategory, keyword_category
from subschema.kernel.domains.types import type_shape_for_type_keyword
from subschema.kernel.protocols import SubproofContext
from subschema.kernel.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
    schema_is_true,
    transparent_schema_target,
)

__all__ = [
    "ARRAY_CONTAINS_RHS_SCHEMA_KEYWORDS",
    "ARRAY_CONTAINS_SCHEMA_KEYWORDS",
    "ARRAY_SCHEMA_KEYWORDS",
    "ARRAY_UNIQUENESS_LHS_SCHEMA_KEYWORDS",
    "ARRAY_UNIQUENESS_RHS_SCHEMA_KEYWORDS",
    "ArrayLengthInterval",
    "ArrayShape",
    "ArrayUniquenessShape",
    "array_shape_for_schema",
    "array_unique_items_requirement_for_schema",
    "array_uniqueness_shape_for_schema",
]

ARRAY_SCHEMA_KEYWORDS = frozenset(
    {
        "additionalItems",
        "allOf",
        "anyOf",
        "contains",
        "items",
        "maxContains",
        "maxItems",
        "minContains",
        "minItems",
        "not",
        "prefixItems",
        "type",
        "uniqueItems",
    }
)

ARRAY_UNIQUENESS_RHS_SCHEMA_KEYWORDS = frozenset({"type", "uniqueItems"})

ARRAY_UNIQUENESS_LHS_SCHEMA_KEYWORDS = frozenset(
    {
        "additionalItems",
        "items",
        "maxItems",
        "minItems",
        "prefixItems",
        "type",
        "uniqueItems",
    }
)

ARRAY_CONTAINS_SCHEMA_KEYWORDS = frozenset(
    {
        "additionalItems",
        "allOf",
        "contains",
        "items",
        "maxContains",
        "maxItems",
        "minContains",
        "minItems",
        "prefixItems",
        "type",
    }
)

ARRAY_CONTAINS_RHS_SCHEMA_KEYWORDS = frozenset(
    {"contains", "maxContains", "minContains", "type"}
)
@dataclass(frozen=True)
class ArrayShape:
    intervals: tuple[ArrayLengthInterval, ...]
    accepts_non_array: bool
    exact: bool = True

    def normalized_intervals(self) -> tuple[ArrayLengthInterval, ...]:
        return _merge_array_intervals(
            tuple(interval for interval in self.intervals if not interval.is_empty())
        )

    def is_subset_of(self, other: ArrayShape) -> bool:
        if self.accepts_non_array and not other.accepts_non_array:
            return False
        return all(
            _array_interval_covered(interval, other.normalized_intervals())
            for interval in self.normalized_intervals()
        )

    def witness_not_in(self, other: ArrayShape) -> list[Any] | None:
        length = self.witness_length_not_in(other)
        if length is None:
            return None
        return [None] * length

    def witness_length_not_in(self, other: ArrayShape) -> int | None:
        for interval in self.normalized_intervals():
            length = _first_uncovered_array_length(
                interval, other.normalized_intervals()
            )
            if length is not None:
                return length
        return None

    def intersect(self, other: ArrayShape) -> ArrayShape:
        intervals = [
            lhs.intersect(rhs)
            for lhs in self.normalized_intervals()
            for rhs in other.normalized_intervals()
        ]
        return ArrayShape(
            _merge_array_intervals(
                tuple(interval for interval in intervals if not interval.is_empty())
            ),
            self.accepts_non_array and other.accepts_non_array,
            self.exact and other.exact,
        )

    def union(self, other: ArrayShape) -> ArrayShape:
        return ArrayShape(
            _merge_array_intervals(
                self.normalized_intervals() + other.normalized_intervals()
            ),
            self.accepts_non_array or other.accepts_non_array,
            self.exact and other.exact,
        )

    def complement(self) -> ArrayShape:
        return ArrayShape(
            _complement_array_intervals(self.normalized_intervals()),
            not self.accepts_non_array,
            self.exact,
        )

    def exact_complement(self) -> ArrayShape | None:
        if not self.exact:
            return None
        return self.complement()


@dataclass(frozen=True)
class ArrayUniquenessShape:
    accepts_array: bool
    accepts_non_array: bool
    requires_unique_items: bool
    guarantees_unique_items: bool
    complete_uniqueness_fragment: bool = True


@dataclass(frozen=True)
class ArrayLengthInterval:
    lower: int = 0
    upper: int | None = None

    def is_empty(self) -> bool:
        return self.upper is not None and self.lower > self.upper

    def intersect(self, other: ArrayLengthInterval) -> ArrayLengthInterval:
        lower = max(self.lower, other.lower)
        if self.upper is None:
            upper = other.upper
        elif other.upper is None:
            upper = self.upper
        else:
            upper = min(self.upper, other.upper)
        return ArrayLengthInterval(lower, upper)


def array_shape_for_schema(
    schema: Any,
    dialect: Dialect,
    *,
    allow_item_value_constraints: bool,
    depth: int = 0,
) -> ArrayShape | None:
    if depth > 16:
        return None
    if schema is True:
        return ArrayShape((ArrayLengthInterval(),), accepts_non_array=True)
    if schema is False:
        return ArrayShape((), accepts_non_array=False)
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    transparent_target = transparent_schema_target(schema)
    if transparent_target is not None:
        return array_shape_for_schema(
            transparent_target,
            dialect,
            allow_item_value_constraints=allow_item_value_constraints,
            depth=depth + 1,
        )
    if not _is_array_length_fragment_schema(
        schema,
        dialect,
        allow_item_value_constraints=allow_item_value_constraints,
    ):
        return None

    shape = _local_array_shape(schema, dialect)
    if shape is None:
        return None

    for subschema in schema.get("allOf", []):
        branch = array_shape_for_schema(
            subschema,
            dialect,
            allow_item_value_constraints=allow_item_value_constraints,
            depth=depth + 1,
        )
        if branch is None:
            return None
        shape = shape.intersect(branch)

    if "anyOf" in schema:
        any_shape = ArrayShape((), accepts_non_array=False)
        for subschema in schema["anyOf"]:
            branch = array_shape_for_schema(
                subschema,
                dialect,
                allow_item_value_constraints=allow_item_value_constraints,
                depth=depth + 1,
            )
            if branch is None:
                return None
            any_shape = any_shape.union(branch)
        shape = shape.intersect(any_shape)

    if "not" in schema:
        negated = array_shape_for_schema(
            schema["not"],
            dialect,
            allow_item_value_constraints=allow_item_value_constraints,
            depth=depth + 1,
        )
        if negated is None:
            return None
        negated_complement = negated.exact_complement()
        if negated_complement is None:
            return None
        shape = shape.intersect(negated_complement)

    return shape


def array_uniqueness_shape_for_schema(
    schema: Any,
    dialect: Dialect,
    *,
    side: Literal["lhs", "rhs"],
    depth: int = 0,
) -> ArrayUniquenessShape | None:
    if depth > 8:
        return None
    if schema is True:
        return ArrayUniquenessShape(
            accepts_array=True,
            accepts_non_array=True,
            requires_unique_items=False,
            guarantees_unique_items=False,
            complete_uniqueness_fragment=True,
        )
    if schema is False:
        return ArrayUniquenessShape(
            accepts_array=False,
            accepts_non_array=False,
            requires_unique_items=True,
            guarantees_unique_items=True,
            complete_uniqueness_fragment=True,
        )
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    transparent_target = transparent_schema_target(schema)
    if transparent_target is not None:
        return array_uniqueness_shape_for_schema(
            transparent_target,
            dialect,
            side=side,
            depth=depth + 1,
        )
    if not _is_array_uniqueness_fragment_schema(schema, dialect, side=side):
        return None

    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    accepts_array = "array" in type_shape.atoms
    accepts_non_array = any(atom != "array" for atom in type_shape.atoms)
    requires_unique_items = schema.get("uniqueItems") is True
    guarantees_unique_items = (
        not accepts_array
        or requires_unique_items
        or _array_schema_max_length_is_at_most_one(schema, dialect)
    )
    return ArrayUniquenessShape(
        accepts_array=accepts_array,
        accepts_non_array=accepts_non_array,
        requires_unique_items=requires_unique_items,
        guarantees_unique_items=guarantees_unique_items,
        complete_uniqueness_fragment=True,
    )


def array_unique_items_requirement_for_schema(
    schema: Any,
    depth: int = 0,
) -> ArrayUniquenessShape | None:
    if depth > 16:
        return None
    if schema is False:
        return ArrayUniquenessShape(
            accepts_array=False,
            accepts_non_array=False,
            requires_unique_items=True,
            guarantees_unique_items=True,
            complete_uniqueness_fragment=True,
        )
    if not isinstance(schema, dict) or schema.get("uniqueItems") is not True:
        if not isinstance(schema, dict):
            return None
        if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
            return None
        transparent_target = transparent_schema_target(schema)
        if transparent_target is None:
            return None
        return array_unique_items_requirement_for_schema(
            transparent_target,
            depth + 1,
        )
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None

    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    accepts_array = "array" in type_shape.atoms
    accepts_non_array = any(atom != "array" for atom in type_shape.atoms)
    return ArrayUniquenessShape(
        accepts_array=accepts_array,
        accepts_non_array=accepts_non_array,
        requires_unique_items=True,
        guarantees_unique_items=True,
        complete_uniqueness_fragment=_is_array_uniqueness_requirement_complete(schema),
    )


def _is_array_length_fragment_schema(
    schema: dict[str, Any],
    dialect: Dialect,
    *,
    allow_item_value_constraints: bool,
) -> bool:
    for key, value in schema.items():
        if (
            key in IGNORED_SCHEMA_METADATA_KEYS
            or keyword_category(key) is KeywordCategory.UNKNOWN
        ):
            continue
        if key in ARRAY_SCHEMA_KEYWORDS:
            if key in {"allOf", "anyOf"} and not isinstance(value, list):
                return False
            if key in {"minItems", "maxItems", "minContains", "maxContains"} and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                return False
            if key == "contains" and not isinstance(value, bool | dict):
                return False
            if key == "items" and not _array_items_keyword_is_supported(value, dialect):
                return False
            if key == "prefixItems" and not isinstance(value, list):
                return False
            if key == "additionalItems" and not isinstance(value, bool | dict):
                return False
            if key == "uniqueItems" and not isinstance(value, bool):
                return False
            continue
        return False
    if not allow_item_value_constraints and _array_schema_has_item_value_constraints(
        schema, dialect
    ):
        return False
    return True


def _is_exact_local_array_length_schema(schema: Any, dialect: Dialect) -> bool:
    if schema is True or schema is False:
        return True
    if not isinstance(schema, dict):
        return False
    exact_keywords = {
        "additionalItems",
        "items",
        "maxItems",
        "minItems",
        "prefixItems",
        "type",
    }
    for key, value in schema.items():
        if (
            key in IGNORED_SCHEMA_METADATA_KEYS
            or keyword_category(key) is KeywordCategory.UNKNOWN
        ):
            continue
        if key in {"allOf", "anyOf", "not"}:
            continue
        if key not in exact_keywords:
            return False
        if key in {"minItems", "maxItems"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key == "items" and not _array_items_keyword_is_supported(value, dialect):
            return False
        if key == "prefixItems" and not isinstance(value, list):
            return False
        if key == "additionalItems" and not isinstance(value, bool | dict):
            return False
    return not _array_schema_has_item_value_constraints(schema, dialect)


def _local_array_shape(schema: dict[str, Any], dialect: Dialect) -> ArrayShape | None:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        types = {schema_type}
        accepts_non_array = schema_type != "array"
    elif isinstance(schema_type, list):
        if not all(isinstance(item, str) for item in schema_type):
            return None
        types = set(schema_type)
        accepts_non_array = any(item != "array" for item in types)
    elif schema_type is None:
        types = {"array"}
        accepts_non_array = True
    else:
        return None

    if "array" not in types:
        return ArrayShape((), accepts_non_array=accepts_non_array)

    lower = schema.get("minItems", 0)
    upper = schema.get("maxItems")
    if not isinstance(lower, int) or isinstance(lower, bool):
        return None
    if upper is not None and (not isinstance(upper, int) or isinstance(upper, bool)):
        return None
    contains_counts = _array_contains_counts(schema)
    if contains_counts is None:
        return None
    if "contains" in schema:
        contains_minimum, contains_maximum = contains_counts
        lower = max(lower, contains_minimum)
        if schema_is_true(schema["contains"]) and contains_maximum is not None:
            upper = contains_maximum if upper is None else min(upper, contains_maximum)
    tail_upper = _array_tail_upper_bound(schema, dialect)
    if tail_upper is not None:
        upper = tail_upper if upper is None else min(upper, tail_upper)
    return ArrayShape(
        (ArrayLengthInterval(lower, upper),),
        accepts_non_array=accepts_non_array,
        exact=_is_exact_local_array_length_schema(schema, dialect),
    )


def _array_items_keyword_is_supported(value: Any, dialect: Dialect) -> bool:
    if dialect is Dialect.DRAFT202012:
        return isinstance(value, bool | dict)
    return isinstance(value, bool | dict | list)


def _array_schema_has_item_value_constraints(
    schema: dict[str, Any], dialect: Dialect
) -> bool:
    prefix_items = schema.get("prefixItems")
    if isinstance(prefix_items, list) and any(
        not schema_is_true(item) for item in prefix_items
    ):
        return True
    if "contains" in schema and not schema_is_true(schema["contains"]):
        return True

    items = schema.get("items")
    if dialect is Dialect.DRAFT202012:
        if items is not None and items is not False and not schema_is_true(items):
            return True
        return False

    if isinstance(items, dict) and not schema_is_true(items):
        return True
    if isinstance(items, list) and any(not schema_is_true(item) for item in items):
        return True
    additional_items = schema.get("additionalItems")
    if isinstance(additional_items, dict) and not schema_is_true(additional_items):
        return True
    return False


def _array_tail_upper_bound(schema: dict[str, Any], dialect: Dialect) -> int | None:
    if dialect is Dialect.DRAFT202012:
        prefix_items = schema.get("prefixItems")
        prefix_count = len(prefix_items) if isinstance(prefix_items, list) else 0
        return prefix_count if schema.get("items") is False else None

    if schema.get("items") is False:
        return 0
    items = schema.get("items")
    if isinstance(items, list) and schema.get("additionalItems") is False:
        return len(items)
    return None


def _is_array_uniqueness_fragment_schema(
    schema: dict[str, Any],
    dialect: Dialect,
    *,
    side: Literal["lhs", "rhs"],
) -> bool:
    allowed_keywords = (
        ARRAY_UNIQUENESS_LHS_SCHEMA_KEYWORDS
        if side == "lhs"
        else ARRAY_UNIQUENESS_RHS_SCHEMA_KEYWORDS
    )
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in allowed_keywords:
            return False
        if key == "uniqueItems" and not isinstance(value, bool):
            return False
        if key in {"minItems", "maxItems"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key == "items" and not _array_items_keyword_is_supported(value, dialect):
            return False
        if key == "prefixItems" and not isinstance(value, list):
            return False
        if key == "additionalItems" and not isinstance(value, bool | dict):
            return False
    return True


def _is_array_uniqueness_requirement_complete(schema: dict[str, Any]) -> bool:
    return all(
        key in ARRAY_UNIQUENESS_RHS_SCHEMA_KEYWORDS
        or key in IGNORED_SCHEMA_METADATA_KEYS
        or keyword_category(key) is KeywordCategory.UNKNOWN
        for key in schema
    )


def _array_schema_max_length_is_at_most_one(
    schema: dict[str, Any], dialect: Dialect
) -> bool:
    upper = schema.get("maxItems")
    if upper is not None and (not isinstance(upper, int) or isinstance(upper, bool)):
        return False

    tail_upper = _array_tail_upper_bound(schema, dialect)
    if tail_upper is not None:
        upper = tail_upper if upper is None else min(upper, tail_upper)
    return upper is not None and upper <= 1


def _is_array_contains_fragment_schema(
    schema: Any,
    dialect: Dialect,
    *,
    side: Literal["lhs", "rhs"],
) -> bool:
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False
    allowed_keywords = (
        ARRAY_CONTAINS_SCHEMA_KEYWORDS
        if side == "lhs"
        else ARRAY_CONTAINS_RHS_SCHEMA_KEYWORDS
    )
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in allowed_keywords:
            return False
        if key == "allOf":
            if not isinstance(value, list):
                return False
            if not all(
                _is_array_contains_fragment_schema(item, dialect, side=side)
                for item in value
            ):
                return False
        if key in {"minItems", "maxItems", "minContains", "maxContains"}:
            if not isinstance(value, int) or isinstance(value, bool):
                return False
        if key == "items" and not _array_items_keyword_is_supported(value, dialect):
            return False
        if key == "prefixItems" and not isinstance(value, list):
            return False
        if key == "additionalItems" and not isinstance(value, bool | dict):
            return False
    return True


def _array_contains_counts(schema: Any) -> tuple[int, int | None] | None:
    if not isinstance(schema, dict) or "contains" not in schema:
        return (0, None)
    minimum = schema.get("minContains", 1)
    maximum = schema.get("maxContains")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None
    return (minimum, maximum)


def _minimum_contains_matches_guaranteed(
    lhs: Any,
    rhs_contains: Any,
    dialect: Dialect,
    *,
    context: SubproofContext | None = None,
) -> int | None:
    if lhs is False:
        return 0
    if lhs is True or not isinstance(lhs, dict):
        return None

    guaranteed = 0
    if "allOf" in lhs:
        branch_bounds = [
            _minimum_contains_matches_guaranteed(
                subschema, rhs_contains, dialect, context=context
            )
            for subschema in lhs["allOf"]
        ]
        if any(bound is None for bound in branch_bounds):
            return None
        concrete_bounds = [bound for bound in branch_bounds if bound is not None]
        guaranteed = max(guaranteed, max(concrete_bounds, default=0))

    lhs_counts = _array_contains_counts(lhs)
    if lhs_counts is None:
        return None
    if "contains" in lhs and _subschema_is_proved(
        lhs["contains"], rhs_contains, dialect, context=context
    ):
        guaranteed = max(guaranteed, lhs_counts[0])

    structural = _minimum_structural_contains_matches(
        lhs, rhs_contains, dialect, context=context
    )
    if structural is not None:
        guaranteed = max(guaranteed, structural)

    return guaranteed


def _minimum_structural_contains_matches(
    lhs: dict[str, Any],
    rhs_contains: Any,
    dialect: Dialect,
    *,
    context: SubproofContext | None = None,
) -> int | None:
    minimum_items = lhs.get("minItems", 0)
    if not isinstance(minimum_items, int) or isinstance(minimum_items, bool):
        return None
    prefix = _array_prefix_schemas(lhs, dialect)
    tail = _array_tail_schema(lhs, dialect)
    guaranteed = 0
    for index, item_schema in enumerate(prefix):
        if index >= minimum_items:
            break
        if _subschema_is_proved(item_schema, rhs_contains, dialect, context=context):
            guaranteed += 1
    if minimum_items > len(prefix):
        if tail is False:
            return guaranteed
        if _subschema_is_proved(tail, rhs_contains, dialect, context=context):
            guaranteed += minimum_items - len(prefix)
    return guaranteed


def _maximum_contains_matches_possible(
    lhs: Any,
    rhs_contains: Any,
    dialect: Dialect,
    *,
    context: SubproofContext | None = None,
) -> int | None:
    if lhs is False:
        return 0
    if lhs is True or not isinstance(lhs, dict):
        return None

    maximum_items = _array_schema_max_items_upper_bound(lhs, dialect)
    upper_bounds = [maximum_items] if maximum_items is not None else []

    lhs_counts = _array_contains_counts(lhs)
    if lhs_counts is None:
        return None
    if (
        "contains" in lhs
        and lhs_counts[1] is not None
        and _subschema_is_proved(
            rhs_contains, lhs["contains"], dialect, context=context
        )
    ):
        upper_bounds.append(lhs_counts[1])

    if "allOf" in lhs:
        for subschema in lhs["allOf"]:
            branch_bound = _maximum_contains_matches_possible(
                subschema,
                rhs_contains,
                dialect,
                context=context,
            )
            if branch_bound is not None:
                upper_bounds.append(branch_bound)

    if not upper_bounds:
        return None
    return min(upper_bounds)


def _array_schema_max_items_upper_bound(
    schema: dict[str, Any], dialect: Dialect
) -> int | None:
    upper = schema.get("maxItems")
    if upper is not None and (not isinstance(upper, int) or isinstance(upper, bool)):
        return None

    tail_upper = _array_tail_upper_bound(schema, dialect)
    if tail_upper is not None:
        upper = tail_upper if upper is None else min(upper, tail_upper)
    return upper


def _array_prefix_schemas(schema: dict[str, Any], dialect: Dialect) -> list[Any]:
    if dialect is Dialect.DRAFT202012:
        prefix = schema.get("prefixItems")
        return prefix if isinstance(prefix, list) else []
    items = schema.get("items")
    return items if isinstance(items, list) else []


def _array_tail_schema(schema: dict[str, Any], dialect: Dialect) -> Any:
    if dialect is Dialect.DRAFT202012:
        return schema.get("items", True)
    items = schema.get("items")
    if isinstance(items, dict | bool):
        return items
    if isinstance(items, list):
        return schema.get("additionalItems", True)
    return True


def _subschema_is_proved(
    lhs: Any,
    rhs: Any,
    dialect: Dialect,
    *,
    context: SubproofContext | None,
) -> bool:
    if context is None:
        return False
    return context.subproof(lhs, rhs).status == "proved_true"


def _merge_array_intervals(
    intervals: tuple[ArrayLengthInterval, ...],
) -> tuple[ArrayLengthInterval, ...]:
    sorted_intervals = sorted(intervals, key=lambda interval: interval.lower)
    merged: list[ArrayLengthInterval] = []
    for interval in sorted_intervals:
        if interval.is_empty():
            continue
        if not merged:
            merged.append(interval)
            continue
        previous = merged[-1]
        if previous.upper is None or interval.lower <= previous.upper + 1:
            upper = (
                None
                if previous.upper is None or interval.upper is None
                else max(previous.upper, interval.upper)
            )
            merged[-1] = ArrayLengthInterval(previous.lower, upper)
        else:
            merged.append(interval)
    return tuple(merged)


def _array_interval_covered(
    interval: ArrayLengthInterval,
    covering_intervals: tuple[ArrayLengthInterval, ...],
) -> bool:
    remaining_start = interval.lower
    interval_end = interval.upper
    for covering in covering_intervals:
        if covering.upper is not None and covering.upper < remaining_start:
            continue
        if covering.lower > remaining_start:
            return False
        if covering.upper is None:
            return True
        remaining_start = covering.upper + 1
        if interval_end is not None and remaining_start > interval_end:
            return True
    return False


def _first_uncovered_array_length(
    interval: ArrayLengthInterval,
    covering_intervals: tuple[ArrayLengthInterval, ...],
) -> int | None:
    current = interval.lower
    for covering in covering_intervals:
        if covering.upper is not None and covering.upper < current:
            continue
        if covering.lower > current:
            return current
        if covering.upper is None:
            return None
        current = covering.upper + 1
        if interval.upper is not None and current > interval.upper:
            return None
    return current if interval.upper is None or current <= interval.upper else None


def _complement_array_intervals(
    intervals: tuple[ArrayLengthInterval, ...],
) -> tuple[ArrayLengthInterval, ...]:
    complements = []
    next_lower = 0
    for interval in intervals:
        if next_lower < interval.lower:
            complements.append(ArrayLengthInterval(next_lower, interval.lower - 1))
        if interval.upper is None:
            return tuple(complements)
        next_lower = interval.upper + 1
    complements.append(ArrayLengthInterval(next_lower, None))
    return tuple(complements)
