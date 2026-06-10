"""
Array length, uniqueness, and contains reasoning for exact subschema proofs.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from typing import Any, Literal

from subschema.compiler.domains.types import (
    type_overapproximation_for_schema,
    type_shape_for_type_keyword,
)
from subschema.compiler.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
    schema_is_false,
    schema_is_true,
    transparent_schema_target,
)
from subschema.dialects import Dialect, KeywordCategory, keyword_category
from subschema.work_protocols import SubproofContext

__all__ = [
    "ARRAY_CONTAINS_RHS_SCHEMA_KEYWORDS",
    "ARRAY_CONTAINS_SCHEMA_KEYWORDS",
    "ARRAY_SCHEMA_KEYWORDS",
    "ARRAY_UNIQUENESS_LHS_SCHEMA_KEYWORDS",
    "ARRAY_UNIQUENESS_RHS_SCHEMA_KEYWORDS",
    "ArrayLengthInterval",
    "ArrayFiniteFragmentShape",
    "ArrayShape",
    "ArrayUniquenessShape",
    "ArrayWitnessShape",
    "array_any_of_item_schemas_for_schema",
    "array_merged_all_of_schema",
    "array_contains_fragment_support_for_schema",
    "array_contains_counts_for_schema",
    "array_cardinality_length_shape_for_schema",
    "array_finite_fragment_shape_for_schema",
    "array_first_required_item_schema",
    "array_guaranteed_contains_matches",
    "array_item_schema_candidate_indexes_for_schema",
    "array_item_schema_at_index_for_schema",
    "array_item_schemas_covering_all_items",
    "array_item_values_fragment_support_for_schema",
    "array_reachable_item_schemas_for_shape",
    "array_requires_unique_items_for_schema",
    "array_shape_for_schema",
    "array_tuple_anyof_distribution_branches_for_schema",
    "array_unevaluated_items_true_fragment_supported",
    "array_unique_items_requirement_for_schema",
    "array_uniqueness_shape_for_schema",
    "array_witness_shape_for_schema",
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
        "uniqueItems",
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
class ArrayFiniteFragmentShape:
    lower: int
    upper: int | None
    prefix_schemas: tuple[Any, ...]
    tail_schema: Any

    def slot_schema(self, index: int) -> Any:
        if index < len(self.prefix_schemas):
            return self.prefix_schemas[index]
        return self.tail_schema


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


def array_requires_unique_items_for_schema(schema: Any) -> bool:
    requirement = array_unique_items_requirement_for_schema(schema)
    return requirement is not None and requirement.requires_unique_items


def array_any_of_item_schemas_for_schema(schema: Any) -> tuple[Any, ...] | None:
    if not isinstance(schema, dict):
        return None
    branches = schema.get("anyOf")
    if not isinstance(branches, list) or not branches:
        return None

    item_schemas: list[Any] = []
    for branch in branches:
        if not isinstance(branch, dict) or branch.get("type") != "array":
            return None
        items = branch.get("items", True)
        if isinstance(items, bool | list):
            return None
        item_schemas.append(items)
    return tuple(item_schemas)


def array_tuple_anyof_distribution_branches_for_schema(
    schema: Any,
) -> tuple[Any, ...] | None:
    if not isinstance(schema, dict):
        return None
    if type_overapproximation_for_schema(schema) != frozenset({"array"}):
        return None

    items = schema.get("items")
    if not isinstance(items, list):
        return None

    item_choices: list[tuple[Any, ...]] = []
    has_choice = False
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("anyOf"), list):
            choices = tuple(item["anyOf"])
            if not choices:
                return None
            item_choices.append(choices)
            has_choice = True
        else:
            item_choices.append((item,))
    if not has_choice:
        return None

    branches = []
    for chosen_items in product(*item_choices):
        branch = deepcopy(schema)
        branch["items"] = [deepcopy(item) for item in chosen_items]
        branches.append(branch)
    return tuple(branches)


def array_item_values_fragment_support_for_schema(
    schema: Any, dialect: Dialect
) -> tuple[bool, bool, bool]:
    return (
        _is_array_item_values_fragment_schema(schema, dialect, allow_contains=True),
        _is_array_item_values_fragment_schema(schema, dialect, allow_contains=False),
        _is_array_item_values_fragment_schema(schema, dialect, allow_contains=True),
    )


def array_contains_fragment_support_for_schema(
    schema: Any, dialect: Dialect
) -> tuple[bool, bool]:
    return (
        _is_array_contains_fragment_schema(schema, dialect, side="lhs"),
        _is_array_contains_fragment_schema(schema, dialect, side="rhs"),
    )


def array_contains_counts_for_schema(schema: Any) -> tuple[int, int | None] | None:
    return _array_contains_counts(schema)


def array_cardinality_length_shape_for_schema(
    schema: Any,
    dialect: Dialect,
) -> ArrayShape | None:
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$dynamicRef", "$recursiveRef"}):
        return None
    allowed_keywords = {
        "additionalItems",
        "contains",
        "items",
        "maxContains",
        "maxItems",
        "minContains",
        "minItems",
        "prefixItems",
        "type",
        "uniqueItems",
    }
    if any(
        key not in allowed_keywords and key not in IGNORED_SCHEMA_METADATA_KEYS
        for key in schema
    ):
        return None

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
        minimum_contains, maximum_contains = contains_counts
        lower = max(lower, minimum_contains)
        if schema["contains"] is True and maximum_contains is not None:
            upper = maximum_contains if upper is None else min(upper, maximum_contains)

    tail_upper = _array_tail_upper_bound(schema, dialect)
    if tail_upper is not None:
        upper = tail_upper if upper is None else min(upper, tail_upper)
    return ArrayShape((ArrayLengthInterval(lower, upper),), accepts_non_array=False)


def array_first_required_item_schema(
    schema: Any,
    dialect: Dialect,
) -> Any | None:
    if not isinstance(schema, dict):
        return None
    minimum = schema.get("minItems", 0)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum <= 0:
        return None

    if dialect is Dialect.DRAFT202012:
        prefix = schema.get("prefixItems")
        if isinstance(prefix, list) and prefix:
            return prefix[0]
        items = schema.get("items", True)
        return items if isinstance(items, bool | dict) else None

    items = schema.get("items", True)
    if isinstance(items, list):
        return items[0] if items else None
    return items if isinstance(items, bool | dict) else None


def array_item_schemas_covering_all_items(
    schema: Any,
    dialect: Dialect,
) -> tuple[Any, ...] | None:
    if not isinstance(schema, dict):
        return None
    if dialect is Dialect.DRAFT202012:
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


def array_item_schema_at_index_for_schema(
    schema: Any,
    dialect: Dialect,
    index: int,
) -> Any | None:
    if not isinstance(schema, dict) or index < 0:
        return None
    prefix = _array_witness_prefix_schemas(schema, dialect)
    if index < len(prefix):
        return prefix[index]
    tail = _array_witness_tail_schema(schema, dialect)
    return tail if isinstance(tail, bool | dict) else None


def array_item_schema_candidate_indexes_for_schema(
    schema: Any,
    dialect: Dialect,
    required_length: int,
) -> tuple[int, ...] | None:
    if not isinstance(schema, dict) or required_length <= 0:
        return ()
    prefix = _array_witness_prefix_schemas(schema, dialect)
    indexes = list(range(min(required_length, len(prefix))))
    if required_length > len(prefix):
        tail = _array_witness_tail_schema(schema, dialect)
        if not isinstance(tail, bool | dict):
            return None
        indexes.append(len(prefix))
    return tuple(indexes)


def array_reachable_item_schemas_for_shape(
    schema: Any,
    shape: ArrayShape,
    dialect: Dialect,
) -> tuple[Any, ...] | None:
    if not isinstance(schema, dict):
        return None
    item_schemas: list[Any] = []
    if dialect is Dialect.DRAFT202012:
        prefix_items = schema.get("prefixItems")
        prefix_schemas = prefix_items if isinstance(prefix_items, list) else []
        for index, item_schema in enumerate(prefix_schemas):
            if _array_length_can_reach_index(shape, index):
                item_schemas.append(item_schema)
        if _array_length_can_reach_index(shape, len(prefix_schemas)):
            items = schema.get("items", True)
            if items is False:
                return tuple(item_schemas)
            if isinstance(items, bool | dict):
                item_schemas.append(items)
                return tuple(item_schemas)
            return None
        return tuple(item_schemas)

    items = schema.get("items", True)
    if isinstance(items, list):
        for index, item_schema in enumerate(items):
            if _array_length_can_reach_index(shape, index):
                item_schemas.append(item_schema)
        if _array_length_can_reach_index(shape, len(items)):
            additional_items = schema.get("additionalItems", True)
            if additional_items is False:
                return tuple(item_schemas)
            if isinstance(additional_items, bool | dict):
                item_schemas.append(additional_items)
                return tuple(item_schemas)
            return None
        return tuple(item_schemas)

    if isinstance(items, bool | dict):
        if _array_length_can_reach_index(shape, 0):
            return (items,)
        return ()
    return None


def array_guaranteed_contains_matches(
    schema: Any,
    contains_schema: Any,
    dialect: Dialect,
    *,
    context: SubproofContext | None = None,
) -> int | None:
    return _minimum_contains_matches_guaranteed(
        schema,
        contains_schema,
        dialect,
        context=context,
    )


@dataclass(frozen=True)
class ArrayWitnessShape:
    minimum_length: int
    maximum_length: int | None
    contains_schema: Any | None
    minimum_contains: int
    prefix_schemas: tuple[Any, ...]
    tail_schema: Any
    requires_unique_items: bool

    @property
    def has_unsatisfiable_length(self) -> bool:
        return (
            self.maximum_length is not None
            and self.minimum_length > self.maximum_length
        )

    def slot_schema(self, index: int) -> Any:
        if self.contains_schema is not None and index < self.minimum_contains:
            return self.contains_schema
        if index < len(self.prefix_schemas):
            return self.prefix_schemas[index]
        return self.tail_schema


def array_witness_shape_for_schema(
    schema: Any,
    dialect: Dialect,
) -> ArrayWitnessShape | None:
    if not isinstance(schema, dict):
        return None
    if "array" not in type_overapproximation_for_schema(schema):
        return None

    minimum = schema.get("minItems", 0)
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        minimum = 0
    contains_schema = schema.get("contains")
    minimum_contains = schema.get(
        "minContains", 1 if contains_schema is not None else 0
    )
    if not isinstance(minimum_contains, int) or isinstance(minimum_contains, bool):
        minimum_contains = 0
    minimum = max(minimum, minimum_contains)
    maximum = schema.get("maxItems")
    if not isinstance(maximum, int) or isinstance(maximum, bool):
        maximum = None

    return ArrayWitnessShape(
        minimum_length=minimum,
        maximum_length=maximum,
        contains_schema=contains_schema,
        minimum_contains=minimum_contains,
        prefix_schemas=_array_witness_prefix_schemas(schema, dialect),
        tail_schema=_array_witness_tail_schema(schema, dialect),
        requires_unique_items=array_requires_unique_items_for_schema(schema),
    )


def array_finite_fragment_shape_for_schema(
    schema: Any,
    dialect: Dialect,
) -> ArrayFiniteFragmentShape | None:
    if not isinstance(schema, dict):
        return None
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None or type_shape.atoms != {"array"}:
        return None
    if not _is_finite_array_value_fragment_schema(schema):
        return None

    prefix = _array_witness_prefix_schemas(schema, dialect)
    tail = _array_witness_tail_schema(schema, dialect)
    implicit_max = len(prefix) if tail is False else None

    lower = schema.get("minItems", 0)
    upper = schema.get("maxItems", implicit_max)
    if not isinstance(lower, int) or isinstance(lower, bool):
        return None
    if upper is not None and (not isinstance(upper, int) or isinstance(upper, bool)):
        return None
    if implicit_max is not None:
        upper = implicit_max if upper is None else min(upper, implicit_max)
    return ArrayFiniteFragmentShape(lower, upper, prefix, tail)


def _array_witness_prefix_schemas(
    schema: dict[str, Any], dialect: Dialect
) -> tuple[Any, ...]:
    prefix = schema.get("prefixItems")
    if (
        prefix is None
        and dialect is not Dialect.DRAFT202012
        and isinstance(schema.get("items"), list)
    ):
        prefix = schema["items"]
    return tuple(prefix) if isinstance(prefix, list) else ()


def _array_witness_tail_schema(schema: dict[str, Any], dialect: Dialect) -> Any:
    if dialect is Dialect.DRAFT202012:
        return schema.get("items", True)
    items = schema.get("items")
    if isinstance(items, dict | bool):
        return items
    if isinstance(items, list):
        return schema.get("additionalItems", True)
    return True


def array_merged_all_of_schema(
    schemas: tuple[Any, ...], dialect: Dialect
) -> dict[str, Any] | None:
    if not schemas or any(not isinstance(schema, dict) for schema in schemas):
        return None
    if any(
        "array" not in type_overapproximation_for_schema(schema) for schema in schemas
    ):
        return None

    merged: dict[str, Any] = {"type": "array"}
    min_items = 0
    max_items = None
    contains_schemas = []
    min_contains = 0
    max_contains = None
    item_schemas = []
    prefix_schemas: list[list[Any]] = []
    unique_items = False

    for schema in schemas:
        minimum = schema.get("minItems", 0)
        if isinstance(minimum, int) and not isinstance(minimum, bool):
            min_items = max(min_items, minimum)
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and not isinstance(maximum, bool):
            max_items = maximum if max_items is None else min(max_items, maximum)
        if schema.get("uniqueItems") is True:
            unique_items = True

        if "contains" in schema:
            contains_schemas.append(schema["contains"])
            minimum_contains = schema.get("minContains", 1)
            if isinstance(minimum_contains, int) and not isinstance(
                minimum_contains, bool
            ):
                min_contains = max(min_contains, minimum_contains)
            maximum_contains = schema.get("maxContains")
            if isinstance(maximum_contains, int) and not isinstance(
                maximum_contains, bool
            ):
                max_contains = (
                    maximum_contains
                    if max_contains is None
                    else min(max_contains, maximum_contains)
                )

        items = schema.get("items")
        prefix = schema.get("prefixItems")
        if isinstance(prefix, list):
            prefix_schemas.append(prefix)
            if items is False:
                max_items = (
                    len(prefix) if max_items is None else min(max_items, len(prefix))
                )
        elif dialect is not Dialect.DRAFT202012 and isinstance(items, list):
            prefix_schemas.append(items)
            if schema.get("additionalItems") is False:
                max_items = (
                    len(items) if max_items is None else min(max_items, len(items))
                )
        if isinstance(items, dict) or isinstance(items, bool):
            item_schemas.append(items)

    if max_items is not None and min_items > max_items:
        return None
    if max_contains is not None and min_contains > max_contains:
        return None

    if min_items:
        merged["minItems"] = min_items
    if max_items is not None:
        merged["maxItems"] = max_items
    if unique_items:
        merged["uniqueItems"] = True
    if contains_schemas:
        merged["contains"] = _all_of_schema(
            tuple(schema for schema in contains_schemas if schema is not True)
        )
        if min_contains != 1:
            merged["minContains"] = min_contains
        if max_contains is not None:
            merged["maxContains"] = max_contains
    if prefix_schemas:
        prefix_items = []
        for index in range(max(len(prefix) for prefix in prefix_schemas)):
            slot_schemas = tuple(
                prefix[index] for prefix in prefix_schemas if index < len(prefix)
            )
            prefix_items.append(
                _all_of_schema(
                    tuple(schema for schema in slot_schemas if schema is not True)
                )
            )
        merged["prefixItems"] = prefix_items
    if item_schemas:
        item_schema = _all_of_schema(
            tuple(schema for schema in item_schemas if schema is not True)
        )
        if item_schema is not True:
            merged["items"] = item_schema
    return merged


def _all_of_schema(schemas: tuple[Any, ...]) -> Any:
    if not schemas:
        return True
    if len(schemas) == 1:
        return schemas[0]
    return {"allOf": list(schemas)}


def array_unevaluated_items_true_fragment_supported(schema: Any) -> bool:
    return _array_unevaluated_items_true_fragment_supported(schema)


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
        schema,
        dialect,
        effective_upper=_array_effective_upper_bound(schema, dialect),
    ):
        return False
    return True


def _is_exact_local_array_length_schema(
    schema: Any, dialect: Dialect, *, effective_upper: int | None = None
) -> bool:
    if schema is True or schema is False:
        return True
    if not isinstance(schema, dict):
        return False
    exact_keywords = {
        "additionalItems",
        "contains",
        "items",
        "maxItems",
        "maxContains",
        "minItems",
        "minContains",
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
        if key in {"minContains", "maxContains"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key == "contains" and not (
            isinstance(value, bool)
            or _contains_constraint_has_exact_length_effect(
                schema,
                effective_upper=effective_upper,
            )
        ):
            return False
        if key == "items" and not _array_items_keyword_is_supported(value, dialect):
            return False
        if key == "prefixItems" and not isinstance(value, list):
            return False
        if key == "additionalItems" and not isinstance(value, bool | dict):
            return False
    return not _array_schema_has_item_value_constraints(
        schema,
        dialect,
        effective_upper=effective_upper,
    )


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
    tail_upper = _array_tail_upper_bound(schema, dialect)
    if tail_upper is not None:
        upper = tail_upper if upper is None else min(upper, tail_upper)
    if "contains" in schema:
        contains_minimum, contains_maximum = contains_counts
        if schema_is_false(schema["contains"]):
            if contains_minimum > 0:
                return ArrayShape(
                    (),
                    accepts_non_array=accepts_non_array,
                    exact=_is_exact_local_array_length_schema(
                        schema,
                        dialect,
                        effective_upper=upper,
                    ),
                )
        else:
            if upper is not None and upper < contains_minimum:
                return ArrayShape(
                    (),
                    accepts_non_array=accepts_non_array,
                    exact=_is_exact_local_array_length_schema(
                        schema,
                        dialect,
                        effective_upper=upper,
                    ),
                )
            lower = max(lower, contains_minimum)
            if schema_is_true(schema["contains"]) and contains_maximum is not None:
                upper = (
                    contains_maximum if upper is None else min(upper, contains_maximum)
                )
    return ArrayShape(
        (ArrayLengthInterval(lower, upper),),
        accepts_non_array=accepts_non_array,
        exact=_is_exact_local_array_length_schema(
            schema,
            dialect,
            effective_upper=upper,
        ),
    )


def _array_items_keyword_is_supported(value: Any, dialect: Dialect) -> bool:
    if dialect is Dialect.DRAFT202012:
        return isinstance(value, bool | dict)
    return isinstance(value, bool | dict | list)


def _array_schema_has_item_value_constraints(
    schema: dict[str, Any],
    dialect: Dialect,
    *,
    effective_upper: int | None = None,
) -> bool:
    prefix_items = schema.get("prefixItems")
    if isinstance(prefix_items, list) and any(
        not schema_is_true(item) for item in prefix_items
    ):
        return True
    if (
        "contains" in schema
        and not isinstance(schema["contains"], bool)
        and not _contains_constraint_has_exact_length_effect(
            schema,
            effective_upper=effective_upper,
        )
    ):
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


def _contains_constraint_has_exact_length_effect(
    schema: dict[str, Any], *, effective_upper: int | None
) -> bool:
    counts = _array_contains_counts(schema)
    if counts is None:
        return False
    minimum, _maximum = counts
    if effective_upper is not None and effective_upper < minimum:
        return True
    return minimum == 0 and effective_upper == 0


def _array_effective_upper_bound(
    schema: dict[str, Any], dialect: Dialect
) -> int | None:
    upper = schema.get("maxItems")
    if upper is not None and (not isinstance(upper, int) or isinstance(upper, bool)):
        return None
    tail_upper = _array_tail_upper_bound(schema, dialect)
    if tail_upper is not None:
        upper = tail_upper if upper is None else min(upper, tail_upper)
    return upper


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


def _array_length_can_reach_index(shape: ArrayShape, index: int) -> bool:
    required_length = index + 1
    return any(
        interval.upper is None or required_length <= interval.upper
        for interval in shape.normalized_intervals()
    )


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
        if key == "uniqueItems" and not isinstance(value, bool):
            return False
    return True


def _is_array_item_values_fragment_schema(
    schema: Any, dialect: Dialect, *, allow_contains: bool = False
) -> bool:
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False

    allowed_keywords = {
        "additionalItems",
        "items",
        "maxItems",
        "minItems",
        "prefixItems",
        "type",
        "uniqueItems",
    }
    if allow_contains:
        allowed_keywords = allowed_keywords | {"contains", "maxContains", "minContains"}
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in allowed_keywords:
            return False
        if key in {"minItems", "maxItems"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key in {"minContains", "maxContains"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key == "contains" and not isinstance(value, bool | dict):
            return False
        if key == "uniqueItems" and not isinstance(value, bool):
            return False
        if key == "prefixItems" and (
            dialect is not Dialect.DRAFT202012 or not isinstance(value, list)
        ):
            return False
        if key == "items":
            if dialect is Dialect.DRAFT202012:
                if not isinstance(value, bool | dict):
                    return False
            elif not isinstance(value, bool | dict | list):
                return False
        if key == "additionalItems" and not isinstance(value, bool | dict):
            return False
    return True


def _array_unevaluated_items_true_fragment_supported(
    schema: Any,
    depth: int = 0,
    *,
    is_root: bool = True,
    allow_length_assertions: bool = False,
) -> bool:
    if schema is True:
        return True
    if schema is False or depth > 16 or not isinstance(schema, dict):
        return False
    if _schema_is_pure_static_ref(schema):
        return True

    allowed_keywords = {
        "$defs",
        "allOf",
        "anyOf",
        "contains",
        "definitions",
        "else",
        "if",
        "items",
        "oneOf",
        "prefixItems",
        "then",
        "type",
    }
    if allow_length_assertions:
        allowed_keywords.update({"maxItems", "minItems"})
    if is_root:
        allowed_keywords.add("unevaluatedItems")
    if not _schema_has_only_keywords(schema, allowed_keywords):
        return False
    if not _schema_type_accepts_arrays(schema.get("type")):
        return False
    if "prefixItems" in schema and not isinstance(schema["prefixItems"], list):
        return False
    if "items" in schema and not isinstance(schema["items"], bool | dict):
        return False
    if "contains" in schema and not isinstance(schema["contains"], bool | dict):
        return False

    return _array_unevaluated_items_children_supported(schema, depth)


def _array_unevaluated_items_children_supported(
    schema: dict[str, Any], depth: int
) -> bool:
    for keyword in ("allOf", "anyOf", "oneOf"):
        subschemas = schema.get(keyword, [])
        if not isinstance(subschemas, list):
            return False
        if not all(
            _array_unevaluated_items_branch_supported(
                keyword,
                subschema,
                depth,
                allow_length_assertions=keyword in {"allOf", "anyOf", "oneOf"},
            )
            for subschema in subschemas
        ):
            return False
    for keyword in ("if", "then", "else"):
        subschema = schema.get(keyword)
        if (
            subschema is not None
            and not _array_unevaluated_items_true_fragment_supported(
                subschema,
                depth + 1,
                is_root=False,
                allow_length_assertions=keyword in {"if", "then", "else"},
            )
        ):
            return False
    return True


def _array_unevaluated_items_branch_supported(
    keyword: str,
    subschema: Any,
    depth: int,
    *,
    allow_length_assertions: bool,
) -> bool:
    if subschema is False and keyword in {"anyOf", "oneOf"}:
        return True
    return _array_unevaluated_items_true_fragment_supported(
        subschema,
        depth + 1,
        is_root=False,
        allow_length_assertions=allow_length_assertions,
    )


def _schema_type_accepts_arrays(type_keyword: Any) -> bool:
    if type_keyword is None:
        return True
    if isinstance(type_keyword, str):
        return type_keyword == "array"
    if isinstance(type_keyword, list):
        return "array" in type_keyword
    return False


def _schema_has_only_keywords(schema: dict[str, Any], keywords: set[str]) -> bool:
    return all(key in keywords or key in IGNORED_SCHEMA_METADATA_KEYS for key in schema)


def _schema_is_pure_static_ref(schema: dict[str, Any]) -> bool:
    return {key for key in schema if key not in IGNORED_SCHEMA_METADATA_KEYS} == {
        "$ref"
    }


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


def _is_finite_array_value_fragment_schema(schema: dict[str, Any]) -> bool:
    allowed = {
        "additionalItems",
        "items",
        "maxItems",
        "minItems",
        "prefixItems",
        "type",
    }
    return all(key in allowed or key in IGNORED_SCHEMA_METADATA_KEYS for key in schema)


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
    _ = lhs, rhs, dialect, context
    return False


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
