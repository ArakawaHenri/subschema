"""
Object-domain reasoning for exact subschema proofs.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from subschema.compiler.domains.numbers import numeric_shape_for_schema
from subschema.compiler.domains.object_facts import (
    object_property_count_bounds_for_schema,
    object_property_schemas_for_schema,
    object_required_names_for_schema,
)
from subschema.compiler.domains.strings import (
    string_language_shape_for_schema,
    string_language_witness,
)
from subschema.compiler.domains.types import (
    JSON_TYPE_ATOMS,
    type_shape_for_type_keyword,
    witness_for_type_atom,
)
from subschema.compiler.literals import explicit_finite_values_for_schema
from subschema.compiler.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
    schema_array_keyword_value,
    schema_is_true,
    transparent_schema_target,
)
from subschema.contracts import ProofResult
from subschema.dialects import Dialect
from subschema.json_data import strict_json_loads
from subschema.regex import RegexLanguage
from subschema.symbolic import SAT, UNSAT, SymbolicSolver
from subschema.values import stable_key
from subschema.work_protocols import SymbolicContext

_SCHEMA_SHAPE_CACHE_SIZE = 4096

__all__ = [
    "OBJECT_CLOSED_PROPERTIES_SCHEMA_KEYWORDS",
    "OBJECT_PROPERTY_COUNT_SCHEMA_KEYWORDS",
    "OBJECT_PROPERTY_NAMES_SCHEMA_KEYWORDS",
    "OBJECT_PROPERTY_VALUES_SCHEMA_KEYWORDS",
    "OBJECT_PRESENCE_SCHEMA_KEYWORDS",
    "OBJECT_PRESENCE_PRODUCT_KEYWORDS",
    "OBJECT_STRUCTURE_SCHEMA_KEYWORDS",
    "OBJECT_KEY_VALUE_LHS_KEYSPACE_PARTITION",
    "OBJECT_KEY_VALUE_RHS_KEYSPACE_PARTITION",
    "ClosedObjectPropertiesShape",
    "ObjectPropertyNamesShape",
    "ObjectKeyValuePattern",
    "ObjectKeyValueShape",
    "ObjectKeyValueWitnessSkeleton",
    "ObjectKeyValueWitnessSlot",
    "ObjectPropertyCountInterval",
    "ObjectPropertyCountShape",
    "ObjectPropertyValuesShape",
    "closed_object_properties_shape_for_schema",
    "object_key_value_mixed_product_budget_exhausted",
    "object_key_value_mixed_product_supported",
    "object_key_value_obligations_budget_exhausted",
    "object_key_value_partition_patterns",
    "object_key_value_shape_allows_unrestricted_keys",
    "object_key_value_shape_for_schema",
    "object_dependent_required_entries_for_schema",
    "object_dependency_closed_present_names",
    "object_dependent_schema_required_entries_for_schema",
    "object_dependent_schema_properties_for_schema",
    "object_property_count_bounds_for_schema",
    "object_schema_has_property_count_constraint",
    "object_presence_lhs_has_negative_value_constraints",
    "object_presence_product_has_one_of",
    "object_presence_product_has_upper_count_constraint",
    "object_presence_product_accepts",
    "object_presence_product_names_for_schemas",
    "object_presence_product_symbolic_expr",
    "object_presence_schema_has_unmodeled_value_constraints",
    "object_max_properties_bound_for_schema",
    "object_min_properties_lower_bound_for_schema",
    "object_property_names_shape_for_schema",
    "object_property_names_schema_has_value_constraints",
    "object_property_count_shape_for_schema",
    "object_property_schemas_for_schema",
    "object_property_values_shape_for_schema",
    "object_required_names_for_schema",
    "object_required_names_in_presence_schema",
    "object_unevaluated_properties_true_fragment_supported",
]

OBJECT_PROPERTY_COUNT_SCHEMA_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "allOf",
        "anyOf",
        "maxProperties",
        "minProperties",
        "not",
        "patternProperties",
        "properties",
        "propertyNames",
        "required",
        "type",
    }
)

OBJECT_PRESENCE_SCHEMA_KEYWORDS = frozenset(
    {
        "allOf",
        "anyOf",
        "dependencies",
        "dependentRequired",
        "dependentSchemas",
        "not",
        "oneOf",
        "required",
        "type",
    }
)

OBJECT_PRESENCE_PRODUCT_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "allOf",
        "anyOf",
        "dependencies",
        "dependentRequired",
        "dependentSchemas",
        "maxProperties",
        "minProperties",
        "not",
        "oneOf",
        "properties",
        "required",
        "type",
    }
)

OBJECT_STRUCTURE_SCHEMA_KEYWORDS = frozenset(
    {
        "allOf",
        "anyOf",
        "dependencies",
        "dependentRequired",
        "maxProperties",
        "minProperties",
        "not",
        "required",
        "type",
    }
)

OBJECT_PROPERTY_NAMES_SCHEMA_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "allOf",
        "patternProperties",
        "properties",
        "propertyNames",
        "required",
        "type",
    }
)

OBJECT_CLOSED_PROPERTIES_SCHEMA_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "allOf",
        "maxProperties",
        "minProperties",
        "patternProperties",
        "properties",
        "required",
        "type",
    }
)

OBJECT_PROPERTY_VALUES_SCHEMA_KEYWORDS = frozenset(
    {"allOf", "properties", "required", "type"}
)

OBJECT_KEY_VALUE_LHS_KEYSPACE_PARTITION = ("keyspace", "lhs")
OBJECT_KEY_VALUE_RHS_KEYSPACE_PARTITION = ("keyspace", "rhs")


@dataclass(frozen=True)
class ObjectPropertyCountShape:
    intervals: tuple[ObjectPropertyCountInterval, ...]
    accepts_non_object: bool
    exact: bool = True

    def normalized_intervals(self) -> tuple[ObjectPropertyCountInterval, ...]:
        return _merge_object_property_count_intervals(
            tuple(interval for interval in self.intervals if not interval.is_empty())
        )

    def is_subset_of(self, other: ObjectPropertyCountShape) -> bool:
        if self.accepts_non_object and not other.accepts_non_object:
            return False
        return all(
            _object_property_count_interval_covered(
                interval, other.normalized_intervals()
            )
            for interval in self.normalized_intervals()
        )

    def witness_not_in(self, other: ObjectPropertyCountShape) -> dict[str, None] | None:
        for interval in self.normalized_intervals():
            count = _first_uncovered_object_property_count(
                interval, other.normalized_intervals()
            )
            if count is not None:
                return {f"k{i}": None for i in range(count)}
        return None

    def intersect(self, other: ObjectPropertyCountShape) -> ObjectPropertyCountShape:
        intervals = [
            lhs.intersect(rhs)
            for lhs in self.normalized_intervals()
            for rhs in other.normalized_intervals()
        ]
        return ObjectPropertyCountShape(
            _merge_object_property_count_intervals(
                tuple(interval for interval in intervals if not interval.is_empty())
            ),
            self.accepts_non_object and other.accepts_non_object,
            self.exact and other.exact,
        )

    def union(self, other: ObjectPropertyCountShape) -> ObjectPropertyCountShape:
        return ObjectPropertyCountShape(
            _merge_object_property_count_intervals(
                self.normalized_intervals() + other.normalized_intervals()
            ),
            self.accepts_non_object or other.accepts_non_object,
            self.exact and other.exact,
        )

    def complement(self) -> ObjectPropertyCountShape:
        return ObjectPropertyCountShape(
            _complement_object_property_count_intervals(self.normalized_intervals()),
            not self.accepts_non_object,
            self.exact,
        )

    def exact_complement(self) -> ObjectPropertyCountShape | None:
        if not self.exact:
            return None
        return self.complement()


@dataclass(frozen=True)
class ObjectPropertyCountInterval:
    lower: int = 0
    upper: int | None = None

    def is_empty(self) -> bool:
        return self.upper is not None and self.lower > self.upper

    def intersect(
        self, other: ObjectPropertyCountInterval
    ) -> ObjectPropertyCountInterval:
        lower = max(self.lower, other.lower)
        if self.upper is None:
            upper = other.upper
        elif other.upper is None:
            upper = self.upper
        else:
            upper = min(self.upper, other.upper)
        return ObjectPropertyCountInterval(lower, upper)


@dataclass(frozen=True)
class ObjectKeyValuePattern:
    text: str
    pattern: Any
    schema: Any


@dataclass(frozen=True)
class ObjectKeyValueWitnessSlot:
    name: str
    schema: Any


@dataclass(frozen=True)
class ObjectKeyValueWitnessSkeleton:
    slots: tuple[ObjectKeyValueWitnessSlot, ...]


@dataclass(frozen=True)
class ObjectKeyValueShape:
    properties: dict[str, Any]
    patterns: tuple[ObjectKeyValuePattern, ...]
    additional_schema: Any
    keyspace_pattern: Any | None
    required: frozenset[str]
    accepts_object: bool
    accepts_non_object: bool

    @property
    def has_value_constraints(self) -> bool:
        return (
            any(schema is not True for schema in self.properties.values())
            or any(pattern.schema is not True for pattern in self.patterns)
            or self.additional_schema is not True
        )

    def pattern_texts(self) -> frozenset[str]:
        return frozenset(pattern.text for pattern in self.patterns)

    def pattern_by_text(self, text: str) -> ObjectKeyValuePattern | None:
        for pattern in self.patterns:
            if pattern.text == text:
                return pattern
        return None

    def key_matches_pattern(self, name: str) -> bool:
        return any(pattern.pattern.matches(name) for pattern in self.patterns)

    def keyspace_allows(self, name: str) -> bool:
        return self.keyspace_pattern is None or self.keyspace_pattern.matches(name)

    def allows_key(self, name: str) -> bool:
        return self.keyspace_allows(name) and (
            name in self.properties
            or self.key_matches_pattern(name)
            or self.additional_schema is not False
        )

    def value_schema_for(self, name: str) -> Any:
        if not self.allows_key(name):
            return False
        schemas = []
        if name in self.properties:
            schemas.append(self.properties[name])
        schemas.extend(
            pattern.schema for pattern in self.patterns if pattern.pattern.matches(name)
        )
        if name not in self.properties and not self.key_matches_pattern(name):
            schemas.append(self.additional_schema)
        return _all_of_schema(tuple(schema for schema in schemas if schema is not True))

    def object_is_inhabited(self) -> bool:
        return self.accepts_object and all(
            self.allows_key(name) for name in self.required
        )

    def witness_skeleton(
        self, override_name: str | None = None
    ) -> ObjectKeyValueWitnessSkeleton | None:
        names = set(self.required)
        if override_name is not None:
            names.add(override_name)
        return self.witness_skeleton_for_names(names)

    def witness_skeleton_for_names(
        self, names: set[str] | frozenset[str]
    ) -> ObjectKeyValueWitnessSkeleton | None:
        if not all(self.allows_key(name) for name in names):
            return None
        return ObjectKeyValueWitnessSkeleton(
            tuple(
                ObjectKeyValueWitnessSlot(name, self.value_schema_for(name))
                for name in sorted(names)
            )
        )


def object_property_count_shape_for_schema(
    schema: Any, depth: int = 0
) -> ObjectPropertyCountShape | None:
    if depth > 16:
        return None
    if schema is True:
        return ObjectPropertyCountShape(
            (ObjectPropertyCountInterval(),), accepts_non_object=True
        )
    if schema is False:
        return ObjectPropertyCountShape((), accepts_non_object=False)
    if not isinstance(schema, dict):
        return None
    if {"$ref", "$recursiveRef", "$dynamicRef"} & schema.keys():
        return None
    transparent_target = transparent_schema_target(schema)
    if transparent_target is not None:
        return object_property_count_shape_for_schema(transparent_target, depth + 1)
    if not _is_object_property_count_fragment_schema(schema):
        return None

    shape = _local_object_property_count_shape(schema)
    if shape is None:
        return None

    for subschema in schema.get("allOf", []):
        branch = object_property_count_shape_for_schema(subschema, depth + 1)
        if branch is None:
            return None
        shape = shape.intersect(branch)

    if "anyOf" in schema:
        any_shape = ObjectPropertyCountShape((), accepts_non_object=False)
        for subschema in schema["anyOf"]:
            branch = object_property_count_shape_for_schema(subschema, depth + 1)
            if branch is None:
                return None
            any_shape = any_shape.union(branch)
        shape = shape.intersect(any_shape)

    if "not" in schema:
        negated = object_property_count_shape_for_schema(schema["not"], depth + 1)
        if negated is None:
            return None
        negated_complement = negated.exact_complement()
        if negated_complement is None:
            return None
        shape = shape.intersect(negated_complement)

    return shape


def object_dependent_schema_properties_for_schema(
    schema: Any,
) -> tuple[tuple[str, str, Any], ...] | None:
    if not isinstance(schema, dict):
        return None
    dependent_schemas = schema.get("dependentSchemas")
    if not isinstance(dependent_schemas, dict):
        return None

    entries: list[tuple[str, str, Any]] = []
    for trigger, dependent_schema in dependent_schemas.items():
        if not isinstance(trigger, str) or not isinstance(dependent_schema, dict):
            continue
        properties = dependent_schema.get("properties")
        if not isinstance(properties, dict):
            continue
        for name, property_schema in properties.items():
            if isinstance(name, str) and property_schema is not True:
                entries.append((trigger, name, property_schema))
    return tuple(entries) or None


def _is_object_property_count_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key in OBJECT_PROPERTY_COUNT_SCHEMA_KEYWORDS:
            if key in {"allOf", "anyOf"} and not isinstance(value, list):
                return False
            if key in {"minProperties", "maxProperties"} and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                return False
            if key == "properties" and not isinstance(value, dict):
                return False
            if key == "patternProperties" and not isinstance(value, dict):
                return False
            if (
                key == "propertyNames"
                and string_language_shape_for_schema(value) is None
            ):
                return False
            if key == "required" and not _is_string_array(value):
                return False
            if key == "additionalProperties" and not isinstance(value, bool | dict):
                return False
            continue
        return False
    return True


def _is_exact_local_object_property_count_schema(schema: Any) -> bool:
    if schema is True or schema is False:
        return True
    if not isinstance(schema, dict):
        return False
    exact_keywords = {
        "maxProperties",
        "minProperties",
        "type",
    }
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key in {"allOf", "anyOf", "not"}:
            continue
        if key not in exact_keywords:
            return False
        if key in {"minProperties", "maxProperties"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
    return True


def _local_object_property_count_shape(
    schema: dict[str, Any],
) -> ObjectPropertyCountShape | None:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        types = {schema_type}
        accepts_non_object = schema_type != "object"
    elif isinstance(schema_type, list):
        if not all(isinstance(item, str) for item in schema_type):
            return None
        types = set(schema_type)
        accepts_non_object = any(item != "object" for item in types)
    elif schema_type is None:
        types = {"object"}
        accepts_non_object = True
    else:
        return None

    if "object" not in types:
        return ObjectPropertyCountShape((), accepts_non_object=accepts_non_object)

    required = schema.get("required", ())
    lower = max(
        schema.get("minProperties", 0),
        len(required) if isinstance(required, list) else 0,
    )
    upper = schema.get("maxProperties")
    if not isinstance(lower, int) or isinstance(lower, bool):
        return None
    if upper is not None and (not isinstance(upper, int) or isinstance(upper, bool)):
        return None
    if schema.get("additionalProperties") is False and not schema.get(
        "patternProperties"
    ):
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return None
        upper = len(properties) if upper is None else min(upper, len(properties))
    return ObjectPropertyCountShape(
        (ObjectPropertyCountInterval(lower, upper),),
        accepts_non_object=accepts_non_object,
        exact=_is_exact_local_object_property_count_schema(schema),
    )


def _merge_object_property_count_intervals(
    intervals: tuple[ObjectPropertyCountInterval, ...],
) -> tuple[ObjectPropertyCountInterval, ...]:
    sorted_intervals = sorted(intervals, key=lambda interval: interval.lower)
    merged: list[ObjectPropertyCountInterval] = []
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
            merged[-1] = ObjectPropertyCountInterval(previous.lower, upper)
        else:
            merged.append(interval)
    return tuple(merged)


def _object_property_count_interval_covered(
    interval: ObjectPropertyCountInterval,
    covering_intervals: tuple[ObjectPropertyCountInterval, ...],
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


def _first_uncovered_object_property_count(
    interval: ObjectPropertyCountInterval,
    covering_intervals: tuple[ObjectPropertyCountInterval, ...],
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


def _complement_object_property_count_intervals(
    intervals: tuple[ObjectPropertyCountInterval, ...],
) -> tuple[ObjectPropertyCountInterval, ...]:
    complements = []
    next_lower = 0
    for interval in intervals:
        if next_lower < interval.lower:
            complements.append(
                ObjectPropertyCountInterval(next_lower, interval.lower - 1)
            )
        if interval.upper is None:
            return tuple(complements)
        next_lower = interval.upper + 1
    complements.append(ObjectPropertyCountInterval(next_lower, None))
    return tuple(complements)


def _object_presence_names_for_schemas(*schemas: Any) -> tuple[str, ...] | None:
    names: set[str] = set()
    for schema in schemas:
        if not _collect_object_presence_names(schema, names):
            return None
    return tuple(sorted(names))


def _collect_object_presence_names(
    schema: Any, names: set[str], depth: int = 0
) -> bool:
    if depth > 16:
        return False
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False
    if {"$ref", "$recursiveRef", "$dynamicRef"} & schema.keys():
        return False
    if not _is_object_presence_fragment_schema(schema):
        return False

    for name in schema.get("required", []):
        names.add(name)
    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        names.add(trigger)
        names.update(dependencies)
    for trigger, dependency in schema.get("dependencies", {}).items():
        names.add(trigger)
        names.update(dependency)
    for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
        names.add(trigger)
        if not _collect_object_presence_names(dependent_schema, names, depth + 1):
            return False

    for keyword in ("allOf", "anyOf", "oneOf"):
        for subschema in schema.get(keyword, []):
            if not _collect_object_presence_names(subschema, names, depth + 1):
                return False
    if "not" in schema and not _collect_object_presence_names(
        schema["not"], names, depth + 1
    ):
        return False
    return True


def _is_object_presence_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in OBJECT_PRESENCE_SCHEMA_KEYWORDS:
            return False
        if key in {"allOf", "anyOf", "oneOf"} and not isinstance(value, list):
            return False
        if key == "required" and not _is_string_array(value):
            return False
        if key == "dependentRequired" and not _is_string_array_map(value):
            return False
        if key == "dependentSchemas" and not _is_object_presence_schema_map(value):
            return False
        if key == "dependencies" and not _is_array_dependency_map(value):
            return False
    return True


def _is_string_array(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_string_array_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(name, str) and _is_string_array(dependencies)
        for name, dependencies in value.items()
    )


def _is_array_dependency_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(name, str) and _is_string_array(dependency)
        for name, dependency in value.items()
    )


def _is_object_presence_schema_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(name, str)
        and isinstance(dependent_schema, bool | dict)
        and _collect_object_presence_names(dependent_schema, set())
        for name, dependent_schema in value.items()
    )


def _object_presence_symbolic_difference(
    lhs: Any,
    rhs: Any,
    names: tuple[str, ...],
    context: SymbolicContext,
) -> frozenset[str] | bool | ProofResult | None:
    solver = SymbolicSolver(
        context, "object product", "object product exceeded proof work budget"
    )
    variables = solver.bool_vars(names)
    lhs_expr = _object_presence_symbolic_expr(lhs, variables, solver)
    rhs_expr = _object_presence_symbolic_expr(rhs, variables, solver)
    if lhs_expr is None or rhs_expr is None:
        return None
    solver.add(lhs_expr, solver.not_(rhs_expr))
    check = solver.check_with_work(units=max(len(names), 1))
    if isinstance(check, ProofResult):
        return check
    if check == SAT:
        return solver.model_bool_set(solver.model(), names)
    if check == UNSAT:
        return False
    return None


def _object_presence_symbolic_expr(
    schema: Any,
    variables: dict[str, Any],
    solver: SymbolicSolver,
    depth: int = 0,
) -> Any | None:
    if depth > 16:
        return None
    if schema is True:
        return solver.and_()
    if schema is False:
        return solver.or_()
    if not isinstance(schema, dict):
        return None
    if not _is_object_presence_fragment_schema(schema):
        return None

    local = _local_object_presence_symbolic_expr(schema, variables, solver)
    if local is None:
        return None
    constraints = [local]

    for subschema in schema.get("allOf", []):
        branch = _object_presence_symbolic_expr(subschema, variables, solver, depth + 1)
        if branch is None:
            return None
        constraints.append(branch)

    if "anyOf" in schema:
        branches = []
        for subschema in schema["anyOf"]:
            branch = _object_presence_symbolic_expr(
                subschema, variables, solver, depth + 1
            )
            if branch is None:
                return None
            branches.append(branch)
        constraints.append(solver.or_(*branches))

    if "oneOf" in schema:
        branches = []
        for subschema in schema["oneOf"]:
            branch = _object_presence_symbolic_expr(
                subschema, variables, solver, depth + 1
            )
            if branch is None:
                return None
            branches.append(branch)
        constraints.append(solver.exactly_one(branches))

    for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
        if not isinstance(trigger, str):
            return None
        branch = _object_presence_symbolic_expr(
            dependent_schema, variables, solver, depth + 1
        )
        if branch is None:
            return None
        constraints.append(
            solver.implies(variables.get(trigger, solver.bool_var(trigger)), branch)
        )

    if "not" in schema:
        negated = _object_presence_symbolic_expr(
            schema["not"], variables, solver, depth + 1
        )
        if negated is None:
            return None
        constraints.append(solver.not_(negated))

    return solver.and_(*constraints)


def _local_object_presence_symbolic_expr(
    schema: dict[str, Any],
    variables: dict[str, Any],
    solver: SymbolicSolver,
) -> Any | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if "object" not in type_shape.atoms:
        return solver.or_()

    constraints = []
    for name in schema.get("required", []):
        if not isinstance(name, str):
            return None
        constraints.append(variables.get(name, solver.bool_var(name)))

    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        if not isinstance(trigger, str):
            return None
        dependency_vars = [
            variables.get(name, solver.bool_var(name)) for name in dependencies
        ]
        constraints.append(
            solver.implies(
                variables.get(trigger, solver.bool_var(trigger)),
                solver.and_(*dependency_vars),
            )
        )

    for trigger, dependencies in schema.get("dependencies", {}).items():
        if not isinstance(trigger, str):
            return None
        dependency_vars = [
            variables.get(name, solver.bool_var(name)) for name in dependencies
        ]
        constraints.append(
            solver.implies(
                variables.get(trigger, solver.bool_var(trigger)),
                solver.and_(*dependency_vars),
            )
        )

    return solver.and_(*constraints)


def _object_presence_schema_accepts(
    schema: Any, atom: str, present: frozenset[str], depth: int = 0
) -> bool | None:
    if depth > 16:
        return None
    if schema is True:
        return True
    if schema is False:
        return False
    if not isinstance(schema, dict):
        return None
    if not _is_object_presence_fragment_schema(schema):
        return None

    local = _local_object_presence_accepts(schema, atom, present)
    if local is None or not local:
        return local

    for subschema in schema.get("allOf", []):
        branch = _object_presence_schema_accepts(subschema, atom, present, depth + 1)
        if branch is None:
            return None
        if not branch:
            return False

    if "anyOf" in schema:
        branch_results = []
        for subschema in schema["anyOf"]:
            branch = _object_presence_schema_accepts(
                subschema, atom, present, depth + 1
            )
            if branch is None:
                return None
            branch_results.append(branch)
        if not any(branch_results):
            return False

    if "oneOf" in schema:
        branch_results = []
        for subschema in schema["oneOf"]:
            branch = _object_presence_schema_accepts(
                subschema, atom, present, depth + 1
            )
            if branch is None:
                return None
            branch_results.append(branch)
        if sum(branch_results) != 1:
            return False

    if atom == "object":
        for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
            if trigger not in present:
                continue
            branch = _object_presence_schema_accepts(
                dependent_schema, atom, present, depth + 1
            )
            if branch is None:
                return None
            if not branch:
                return False

    if "not" in schema:
        negated = _object_presence_schema_accepts(
            schema["not"], atom, present, depth + 1
        )
        if negated is None:
            return None
        if negated:
            return False

    return True


def _local_object_presence_accepts(
    schema: dict[str, Any], atom: str, present: frozenset[str]
) -> bool | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if atom not in type_shape.atoms:
        return False
    if atom != "object":
        return True

    required = frozenset(schema.get("required", []))
    if not required <= present:
        return False

    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        if trigger in present and not frozenset(dependencies) <= present:
            return False

    for trigger, dependency in schema.get("dependencies", {}).items():
        if trigger in present and not frozenset(dependency) <= present:
            return False

    return True


def _object_structure_names_for_schemas(*schemas: Any) -> tuple[str, ...] | None:
    names: set[str] = set()
    for schema in schemas:
        if not _collect_object_structure_names(schema, names):
            return None
    return tuple(sorted(names))


def _collect_object_structure_names(
    schema: Any, names: set[str], depth: int = 0
) -> bool:
    if depth > 16:
        return False
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return False
    if not _is_object_structure_fragment_schema(schema):
        return False

    for name in schema.get("required", []):
        names.add(name)
    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        names.add(trigger)
        names.update(dependencies)
    for trigger, dependency in schema.get("dependencies", {}).items():
        names.add(trigger)
        names.update(dependency)

    for keyword in ("allOf", "anyOf"):
        for subschema in schema.get(keyword, []):
            if not _collect_object_structure_names(subschema, names, depth + 1):
                return False
    if "not" in schema and not _collect_object_structure_names(
        schema["not"], names, depth + 1
    ):
        return False
    return True


def _is_object_structure_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in OBJECT_STRUCTURE_SCHEMA_KEYWORDS:
            return False
        if key in {"allOf", "anyOf"} and not isinstance(value, list):
            return False
        if key in {"minProperties", "maxProperties"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key == "required" and not _is_string_array(value):
            return False
        if key == "dependentRequired" and not _is_string_array_map(value):
            return False
        if key == "dependencies" and not _is_array_dependency_map(value):
            return False
    return True


def _object_structure_accepts_non_object(
    schema: Any, atom: str, depth: int = 0
) -> bool | None:
    if depth > 16:
        return None
    if schema is True:
        return True
    if schema is False:
        return False
    if not isinstance(schema, dict):
        return None
    if not _is_object_structure_fragment_schema(schema):
        return None

    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if atom not in type_shape.atoms:
        return False

    for subschema in schema.get("allOf", []):
        branch = _object_structure_accepts_non_object(subschema, atom, depth + 1)
        if branch is None:
            return None
        if not branch:
            return False

    if "anyOf" in schema:
        branch_results = []
        for subschema in schema["anyOf"]:
            branch = _object_structure_accepts_non_object(subschema, atom, depth + 1)
            if branch is None:
                return None
            branch_results.append(branch)
        if not any(branch_results):
            return False

    if "not" in schema:
        negated = _object_structure_accepts_non_object(schema["not"], atom, depth + 1)
        if negated is None:
            return None
        if negated:
            return False

    return True


def _object_structure_symbolic_difference(
    lhs: Any,
    rhs: Any,
    names: tuple[str, ...],
    context: SymbolicContext,
) -> tuple[frozenset[str], int] | bool | ProofResult | None:
    solver = SymbolicSolver(
        context, "object product", "object product exceeded proof work budget"
    )
    variables = solver.bool_vars(names)
    count = solver.int_var("property_count")
    present_count = solver.sum_bools(variables.values())
    solver.add(solver.ge(count, present_count), solver.ge(count, 0))
    lhs_expr = _object_structure_symbolic_expr(lhs, variables, count, solver)
    rhs_expr = _object_structure_symbolic_expr(rhs, variables, count, solver)
    if lhs_expr is None or rhs_expr is None:
        return None
    solver.add(lhs_expr, solver.not_(rhs_expr))
    check = solver.check_with_work(units=max(len(names) + 1, 1))
    if isinstance(check, ProofResult):
        return check
    if check == SAT:
        model = solver.model()
        return solver.model_bool_set(model, names), solver.model_int(
            model, "property_count"
        )
    if check == UNSAT:
        return False
    return None


def _object_structure_symbolic_expr(
    schema: Any,
    variables: dict[str, Any],
    count: Any,
    solver: SymbolicSolver,
    depth: int = 0,
) -> Any | None:
    if depth > 16:
        return None
    if schema is True:
        return solver.and_()
    if schema is False:
        return solver.or_()
    if not isinstance(schema, dict):
        return None
    if not _is_object_structure_fragment_schema(schema):
        return None

    local = _local_object_structure_symbolic_expr(schema, variables, count, solver)
    if local is None:
        return None
    constraints = [local]

    for subschema in schema.get("allOf", []):
        branch = _object_structure_symbolic_expr(
            subschema, variables, count, solver, depth + 1
        )
        if branch is None:
            return None
        constraints.append(branch)

    if "anyOf" in schema:
        branches = []
        for subschema in schema["anyOf"]:
            branch = _object_structure_symbolic_expr(
                subschema, variables, count, solver, depth + 1
            )
            if branch is None:
                return None
            branches.append(branch)
        constraints.append(solver.or_(*branches))

    if "not" in schema:
        negated = _object_structure_symbolic_expr(
            schema["not"], variables, count, solver, depth + 1
        )
        if negated is None:
            return None
        constraints.append(solver.not_(negated))

    return solver.and_(*constraints)


def _local_object_structure_symbolic_expr(
    schema: dict[str, Any],
    variables: dict[str, Any],
    count: Any,
    solver: SymbolicSolver,
) -> Any | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if "object" not in type_shape.atoms:
        return solver.or_()

    presence = _local_object_presence_symbolic_expr(schema, variables, solver)
    if presence is None:
        return None

    minimum = schema.get("minProperties", 0)
    maximum = schema.get("maxProperties")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None

    constraints = [presence, solver.ge(count, minimum)]
    if maximum is not None:
        constraints.append(solver.le(count, maximum))
    return solver.and_(*constraints)


def _object_structure_intervals_for_schema(
    schema: Any,
    present: frozenset[str],
    depth: int = 0,
) -> tuple[ObjectPropertyCountInterval, ...] | None:
    if depth > 16:
        return None
    lower_bound = len(present)
    if schema is True:
        return (ObjectPropertyCountInterval(lower_bound),)
    if schema is False:
        return ()
    if not isinstance(schema, dict):
        return None
    if not _is_object_structure_fragment_schema(schema):
        return None

    intervals = _local_object_structure_intervals(schema, present)
    if intervals is None:
        return None

    for subschema in schema.get("allOf", []):
        branch = _object_structure_intervals_for_schema(subschema, present, depth + 1)
        if branch is None:
            return None
        intervals = _intersect_object_property_count_interval_sets(intervals, branch)

    if "anyOf" in schema:
        any_intervals: tuple[ObjectPropertyCountInterval, ...] = ()
        for subschema in schema["anyOf"]:
            branch = _object_structure_intervals_for_schema(
                subschema, present, depth + 1
            )
            if branch is None:
                return None
            any_intervals = _merge_object_property_count_intervals(
                any_intervals + branch
            )
        intervals = _intersect_object_property_count_interval_sets(
            intervals, any_intervals
        )

    if "not" in schema:
        negated = _object_structure_intervals_for_schema(
            schema["not"], present, depth + 1
        )
        if negated is None:
            return None
        complement = _complement_object_property_count_intervals_from(
            lower_bound, negated
        )
        intervals = _intersect_object_property_count_interval_sets(
            intervals, complement
        )

    return _merge_object_property_count_intervals(intervals)


def _local_object_structure_intervals(
    schema: dict[str, Any],
    present: frozenset[str],
) -> tuple[ObjectPropertyCountInterval, ...] | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if "object" not in type_shape.atoms:
        return ()
    local_presence = _local_object_presence_accepts(schema, "object", present)
    if local_presence is None:
        return None
    if not local_presence:
        return ()

    minimum = schema.get("minProperties", 0)
    maximum = schema.get("maxProperties")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None
    lower = max(minimum, len(present))
    upper = maximum
    return _merge_object_property_count_intervals(
        (ObjectPropertyCountInterval(lower, upper),)
    )


def _intersect_object_property_count_interval_sets(
    lhs: tuple[ObjectPropertyCountInterval, ...],
    rhs: tuple[ObjectPropertyCountInterval, ...],
) -> tuple[ObjectPropertyCountInterval, ...]:
    intervals = [left.intersect(right) for left in lhs for right in rhs]
    return _merge_object_property_count_intervals(
        tuple(interval for interval in intervals if not interval.is_empty())
    )


def _complement_object_property_count_intervals_from(
    lower_bound: int,
    intervals: tuple[ObjectPropertyCountInterval, ...],
) -> tuple[ObjectPropertyCountInterval, ...]:
    complements = []
    next_lower = lower_bound
    for interval in _merge_object_property_count_intervals(intervals):
        if interval.upper is not None and interval.upper < next_lower:
            continue
        if next_lower < interval.lower:
            complements.append(
                ObjectPropertyCountInterval(next_lower, interval.lower - 1)
            )
        if interval.upper is None:
            return tuple(complements)
        next_lower = max(next_lower, interval.upper + 1)
    complements.append(ObjectPropertyCountInterval(next_lower, None))
    return tuple(complements)


def _object_structure_witness(
    present: frozenset[str],
    universe: tuple[str, ...],
    count: int,
) -> dict[str, None]:
    witness = dict.fromkeys(sorted(present))
    extra_index = 0
    while len(witness) < count:
        name = f"__extra_{extra_index}"
        extra_index += 1
        if name not in universe:
            witness[name] = None
    return witness


@dataclass(frozen=True)
class ObjectPropertyValuesShape:
    property_schemas: dict[str, tuple[Any, ...]]
    required: frozenset[str]
    accepts_object: bool
    accepts_non_object: bool

    @property
    def property_names(self) -> frozenset[str]:
        return frozenset(self.property_schemas)

    def property_schema_for(self, name: str) -> Any:
        return _all_of_schema(self.property_schemas.get(name, ()))

    def intersect(self, other: ObjectPropertyValuesShape) -> ObjectPropertyValuesShape:
        names = self.property_names | other.property_names
        property_schemas = {}
        for name in names:
            constraints = self.property_schemas.get(
                name, ()
            ) + other.property_schemas.get(name, ())
            if constraints:
                property_schemas[name] = constraints
        return ObjectPropertyValuesShape(
            property_schemas,
            self.required | other.required,
            self.accepts_object and other.accepts_object,
            self.accepts_non_object and other.accepts_non_object,
        )

    def object_witness(
        self,
        dialect: Dialect,
        override: tuple[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        names = set(self.required)
        if override is not None:
            names.add(override[0])

        witness = {}
        for name in sorted(names):
            if override is not None and name == override[0]:
                value = override[1]
            else:
                value = _constructive_value_for_schema(
                    self.property_schema_for(name), dialect
                )
            witness[name] = value
        return witness


def object_property_values_shape_for_schema(
    schema: Any, depth: int = 0
) -> ObjectPropertyValuesShape | None:
    if depth > 16:
        return None
    if schema is True:
        return ObjectPropertyValuesShape(
            {}, frozenset(), accepts_object=True, accepts_non_object=True
        )
    if schema is False:
        return ObjectPropertyValuesShape(
            {}, frozenset(), accepts_object=False, accepts_non_object=False
        )
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    transparent_target = transparent_schema_target(schema)
    if transparent_target is not None:
        return object_property_values_shape_for_schema(transparent_target, depth + 1)
    if not _is_object_property_values_fragment_schema(schema):
        return None

    shape = _local_object_property_values_shape(schema)
    if shape is None:
        return None

    for subschema in schema.get("allOf", []):
        branch = object_property_values_shape_for_schema(subschema, depth + 1)
        if branch is None:
            return None
        shape = shape.intersect(branch)
    return shape


def object_key_value_shape_for_schema(schema: Any) -> ObjectKeyValueShape | None:
    if schema is True:
        return ObjectKeyValueShape(
            {},
            (),
            True,
            None,
            frozenset(),
            accepts_object=True,
            accepts_non_object=True,
        )
    if schema is False:
        return ObjectKeyValueShape(
            {},
            (),
            False,
            None,
            frozenset(),
            accepts_object=False,
            accepts_non_object=False,
        )
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    if not _is_object_key_value_fragment_schema(schema):
        return None

    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    keyspace_pattern = _object_key_value_property_names_pattern(schema)
    patterns = []
    pattern_properties = schema.get("patternProperties", {})
    for text, subschema in sorted(pattern_properties.items()):
        pattern = RegexLanguage.maybe_from_json_regex(text)
        if pattern is None:
            return None
        patterns.append(ObjectKeyValuePattern(text, pattern, subschema))
    properties = schema.get("properties", {})
    return ObjectKeyValueShape(
        dict(sorted(properties.items())),
        tuple(patterns),
        schema.get("additionalProperties", True),
        keyspace_pattern,
        object_required_names_for_schema(schema),
        accepts_object="object" in type_shape.atoms,
        accepts_non_object=any(atom != "object" for atom in type_shape.atoms),
    )


def object_key_value_mixed_product_supported(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    budget: int,
    *,
    expanded: bool = False,
) -> bool:
    has_explicit = bool(lhs.properties or rhs.properties)
    has_pattern = bool(lhs.patterns or rhs.patterns)
    if not (has_explicit and has_pattern):
        return True

    explicit_names = (
        set(lhs.properties)
        | set(rhs.properties)
        | set(lhs.required)
        | set(rhs.required)
    )
    partition_patterns = object_key_value_partition_patterns(lhs, rhs)
    class_count = 1 << len(partition_patterns)
    if not expanded and budget >= 0 and len(explicit_names) + class_count > budget:
        return False

    value_schemas = [
        *lhs.properties.values(),
        *rhs.properties.values(),
        *(pattern.schema for pattern in lhs.patterns),
        *(pattern.schema for pattern in rhs.patterns),
        lhs.additional_schema,
        rhs.additional_schema,
    ]
    value_schema_supported = (
        _object_key_value_value_schema_is_expanded_product_safe
        if expanded
        else _object_key_value_value_schema_is_solver_local
    )
    return all(value_schema_supported(schema) for schema in value_schemas)


def object_key_value_mixed_product_budget_exhausted(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    budget: int,
) -> bool:
    has_explicit = bool(lhs.properties or rhs.properties)
    has_pattern = bool(lhs.patterns or rhs.patterns)
    if budget < 0 or not (has_explicit and has_pattern):
        return False

    explicit_names = (
        set(lhs.properties)
        | set(rhs.properties)
        | set(lhs.required)
        | set(rhs.required)
    )
    class_count = 1 << len(object_key_value_partition_patterns(lhs, rhs))
    return len(explicit_names) + class_count > budget


def object_key_value_obligations_budget_exhausted(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    budget: int,
) -> bool:
    if budget < 0:
        return False

    names = (
        set(lhs.properties)
        | set(rhs.properties)
        | set(lhs.required)
        | set(rhs.required)
    )
    class_count = 1 << len(object_key_value_partition_patterns(lhs, rhs))
    return class_count + len(names) > budget


def object_key_value_partition_patterns(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
) -> dict[tuple[str, str], RegexLanguage]:
    patterns = {
        ("pattern", pattern.text): pattern.pattern for pattern in lhs.patterns
    }
    patterns.update(
        {("pattern", pattern.text): pattern.pattern for pattern in rhs.patterns}
    )
    if lhs.keyspace_pattern is not None:
        patterns[OBJECT_KEY_VALUE_LHS_KEYSPACE_PARTITION] = lhs.keyspace_pattern
    if rhs.keyspace_pattern is not None:
        patterns[OBJECT_KEY_VALUE_RHS_KEYSPACE_PARTITION] = rhs.keyspace_pattern
    return patterns


def object_key_value_shape_allows_unrestricted_keys(
    shape: ObjectKeyValueShape,
) -> bool:
    return (
        not shape.properties
        and not shape.patterns
        and shape.additional_schema is True
        and shape.keyspace_pattern is None
        and not shape.required
    )


def _is_object_key_value_fragment_schema(schema: dict[str, Any]) -> bool:
    allowed_keywords = {
        "additionalProperties",
        "maxProperties",
        "minProperties",
        "patternProperties",
        "properties",
        "propertyNames",
        "required",
        "type",
    }
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in allowed_keywords:
            return False
        if key == "properties" and not isinstance(value, dict):
            return False
        if key == "patternProperties":
            if not isinstance(value, dict):
                return False
            if any(
                not isinstance(pattern, str)
                or RegexLanguage.maybe_from_json_regex(pattern) is None
                for pattern in value
            ):
                return False
        if key == "additionalProperties" and not isinstance(value, bool | dict):
            return False
        if key == "propertyNames" and not _is_object_key_value_property_names_schema(
            value
        ):
            return False
        if key in {"maxProperties", "minProperties"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key == "required" and (
            not isinstance(value, list)
            or not all(isinstance(name, str) for name in value)
        ):
            return False
    return True


def _is_object_key_value_property_names_schema(schema: Any) -> bool:
    if schema is True:
        return True
    if not isinstance(schema, dict):
        return False

    allowed_keywords = IGNORED_SCHEMA_METADATA_KEYS | {"pattern", "type"}
    if any(key not in allowed_keywords for key in schema):
        return False
    if "type" in schema and schema["type"] != "string":
        return False
    pattern = schema.get("pattern")
    return pattern is None or (
        isinstance(pattern, str)
        and RegexLanguage.maybe_from_json_regex(pattern) is not None
    )


def _object_key_value_property_names_pattern(
    schema: dict[str, Any],
) -> RegexLanguage | None:
    property_names = schema.get("propertyNames", True)
    if property_names is True:
        return None
    pattern = property_names.get("pattern")
    if pattern is None:
        return None
    return RegexLanguage.maybe_from_json_regex(pattern)


def _object_key_value_value_schema_is_solver_local(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 8:
        return False
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return False

    allowed_keywords = IGNORED_SCHEMA_METADATA_KEYS | {
        "allOf",
        "anyOf",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maximum",
        "maxLength",
        "minimum",
        "minLength",
        "multipleOf",
        "not",
        "pattern",
        "type",
    }
    if any(key not in allowed_keywords for key in schema):
        return False

    schema_type = schema.get("type")
    if isinstance(schema_type, str) and schema_type in {"array", "object"}:
        return False
    if isinstance(schema_type, list) and any(
        item in {"array", "object"} for item in schema_type
    ):
        return False

    for key in ("allOf", "anyOf"):
        subschemas = schema.get(key, [])
        if not isinstance(subschemas, list):
            return False
        if not all(
            _object_key_value_value_schema_is_solver_local(subschema, depth + 1)
            for subschema in subschemas
        ):
            return False
    if "not" in schema and not _object_key_value_value_schema_is_solver_local(
        schema["not"], depth + 1
    ):
        return False
    return True


def _object_key_value_value_schema_is_expanded_product_safe(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 8:
        return False
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return False

    allowed_keywords = IGNORED_SCHEMA_METADATA_KEYS | {
        "allOf",
        "anyOf",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maximum",
        "maxLength",
        "minimum",
        "minLength",
        "multipleOf",
        "not",
        "pattern",
        "type",
    }
    if any(key not in allowed_keywords for key in schema):
        return False

    for key in ("allOf", "anyOf"):
        subschemas = schema.get(key, [])
        if not isinstance(subschemas, list):
            return False
        if not all(
            _object_key_value_value_schema_is_expanded_product_safe(
                subschema, depth + 1
            )
            for subschema in subschemas
        ):
            return False
    if "not" in schema and not _object_key_value_value_schema_is_expanded_product_safe(
        schema["not"], depth + 1
    ):
        return False
    return True


def object_required_names_in_presence_schema(
    schema: Any, depth: int = 0
) -> frozenset[str]:
    if depth > 16 or not isinstance(schema, dict):
        return frozenset()
    names = set(object_required_names_for_schema(schema))
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for subschema in all_of:
            names.update(object_required_names_in_presence_schema(subschema, depth + 1))
    return frozenset(names)


def object_dependent_required_entries_for_schema(
    schema: Any,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(schema, dict):
        return ()
    entries = []
    for keyword in ("dependentRequired", "dependencies"):
        value = schema.get(keyword)
        if not isinstance(value, dict):
            continue
        for trigger, dependencies in value.items():
            if not isinstance(trigger, str):
                continue
            if not isinstance(dependencies, list) or not all(
                isinstance(name, str) for name in dependencies
            ):
                continue
            entries.append((trigger, tuple(dependencies)))
    return tuple(entries)


def object_dependent_schema_required_entries_for_schema(
    schema: Any,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(schema, dict):
        return ()
    entries = []
    dependent_schemas = schema.get("dependentSchemas")
    if not isinstance(dependent_schemas, dict):
        return ()
    for trigger, dependent_schema in dependent_schemas.items():
        if not isinstance(trigger, str):
            continue
        dependencies = tuple(
            sorted(object_required_names_in_presence_schema(dependent_schema))
        )
        if dependencies:
            entries.append((trigger, dependencies))
    return tuple(entries)


def object_dependency_closed_present_names(
    schema: Any,
    seed: frozenset[str],
) -> frozenset[str] | None:
    if not isinstance(schema, dict):
        return seed
    names = set(seed)
    names.update(object_required_names_for_schema(schema))
    changed = True
    while changed:
        changed = False
        for trigger, dependencies in object_dependent_required_entries_for_schema(
            schema
        ):
            if trigger not in names:
                continue
            for dependency in dependencies:
                if dependency not in names:
                    names.add(dependency)
                    changed = True
        dependent_schemas = schema.get("dependentSchemas", {})
        if isinstance(dependent_schemas, dict):
            for trigger, dependent_schema in dependent_schemas.items():
                if trigger not in names:
                    continue
                for dependency in object_required_names_in_presence_schema(
                    dependent_schema
                ):
                    if dependency not in names:
                        names.add(dependency)
                        changed = True
    return frozenset(names)


def object_schema_has_property_count_constraint(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 16 or not isinstance(schema, dict):
        return False
    if "minProperties" in schema or "maxProperties" in schema:
        return True
    if (
        "not" in schema
        and isinstance(schema["not"], dict)
        and object_schema_has_property_count_constraint(schema["not"], depth + 1)
    ):
        return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            object_schema_has_property_count_constraint(subschema, depth + 1)
            for subschema in value
        ):
            return True
    for dependent_schema in schema.get("dependentSchemas", {}).values():
        if object_schema_has_property_count_constraint(dependent_schema, depth + 1):
            return True
    return False


def object_presence_schema_has_unmodeled_value_constraints(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 16 or not isinstance(schema, dict):
        return False
    properties = schema.get("properties")
    if isinstance(properties, dict) and any(
        subschema is not True for subschema in properties.values()
    ):
        return True
    for dependent_schema in schema.get("dependentSchemas", {}).values():
        if object_presence_schema_has_unmodeled_value_constraints(
            dependent_schema, depth + 1
        ):
            return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            object_presence_schema_has_unmodeled_value_constraints(
                subschema, depth + 1
            )
            for subschema in value
        ):
            return True
    if "not" in schema and object_presence_schema_has_unmodeled_value_constraints(
        schema["not"], depth + 1
    ):
        return True
    return False


def object_presence_lhs_has_negative_value_constraints(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 16 or not isinstance(schema, dict):
        return False
    if "not" in schema and object_presence_schema_has_unmodeled_value_constraints(
        schema["not"], depth + 1
    ):
        return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            object_presence_lhs_has_negative_value_constraints(subschema, depth + 1)
            for subschema in value
        ):
            return True
    return False


def object_presence_product_has_upper_count_constraint(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 16 or not isinstance(schema, dict):
        return False
    if "maxProperties" in schema:
        return True
    if (
        "not" in schema
        and isinstance(schema["not"], dict)
        and "minProperties" in schema["not"]
    ):
        return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            object_presence_product_has_upper_count_constraint(subschema, depth + 1)
            for subschema in value
        ):
            return True
    for dependent_schema in schema.get("dependentSchemas", {}).values():
        if object_presence_product_has_upper_count_constraint(
            dependent_schema, depth + 1
        ):
            return True
    return False


def object_presence_product_has_one_of(schema: Any, depth: int = 0) -> bool:
    if depth > 16:
        return False
    if isinstance(schema, list):
        return any(
            object_presence_product_has_one_of(item, depth + 1) for item in schema
        )
    if not isinstance(schema, dict):
        return False
    if "oneOf" in schema:
        return True
    return any(
        object_presence_product_has_one_of(value, depth + 1)
        for key, value in schema.items()
        if key in {"allOf", "anyOf", "not", "if", "then", "else", "dependentSchemas"}
    )


def object_presence_product_names_for_schemas(
    *schemas: Any,
    seed: frozenset[str] = frozenset(),
) -> tuple[str, ...] | None:
    names = set(seed)
    for schema in schemas:
        if not _collect_object_presence_product_names(schema, names):
            return None
    return tuple(sorted(names))


def object_presence_product_accepts(
    schema: Any,
    atom: str,
    present: frozenset[str],
    depth: int = 0,
) -> bool | None:
    if depth > 16:
        return None
    if schema is True:
        return True
    if schema is False:
        return False
    if not isinstance(schema, dict):
        return None
    if not _is_object_presence_product_schema(schema):
        return None

    local = _local_object_presence_product_accepts(schema, atom, present)
    if local is None or not local:
        return local

    for subschema in schema.get("allOf", []):
        branch = object_presence_product_accepts(subschema, atom, present, depth + 1)
        if branch is None:
            return None
        if not branch:
            return False

    if "anyOf" in schema:
        branch_results = []
        for subschema in schema["anyOf"]:
            branch = object_presence_product_accepts(
                subschema, atom, present, depth + 1
            )
            if branch is None:
                return None
            branch_results.append(branch)
        if not any(branch_results):
            return False

    if "oneOf" in schema:
        branch_results = []
        for subschema in schema["oneOf"]:
            branch = object_presence_product_accepts(
                subschema, atom, present, depth + 1
            )
            if branch is None:
                return None
            branch_results.append(branch)
        if sum(branch_results) != 1:
            return False

    if atom == "object":
        for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
            if trigger not in present:
                continue
            branch = object_presence_product_accepts(
                dependent_schema, atom, present, depth + 1
            )
            if branch is None:
                return None
            if not branch:
                return False

    if "not" in schema:
        negated = object_presence_product_accepts(
            schema["not"], atom, present, depth + 1
        )
        if negated is None:
            return None
        if negated:
            return False

    return True


def object_presence_product_symbolic_expr(
    schema: Any,
    variables: dict[str, Any],
    solver: SymbolicSolver,
    depth: int = 0,
) -> Any | None:
    if depth > 16:
        return None
    if schema is True:
        return solver.and_()
    if schema is False:
        return solver.or_()
    if not isinstance(schema, dict):
        return None
    if not _is_object_presence_product_schema(schema):
        return None

    local = _local_object_presence_product_symbolic_expr(schema, variables, solver)
    if local is None:
        return None
    constraints = [local]

    for subschema in schema.get("allOf", []):
        branch = object_presence_product_symbolic_expr(
            subschema, variables, solver, depth + 1
        )
        if branch is None:
            return None
        constraints.append(branch)

    if "anyOf" in schema:
        branches = []
        for subschema in schema["anyOf"]:
            branch = object_presence_product_symbolic_expr(
                subschema, variables, solver, depth + 1
            )
            if branch is None:
                return None
            branches.append(branch)
        constraints.append(solver.or_(*branches))

    if "oneOf" in schema:
        branches = []
        for subschema in schema["oneOf"]:
            branch = object_presence_product_symbolic_expr(
                subschema, variables, solver, depth + 1
            )
            if branch is None:
                return None
            branches.append(branch)
        constraints.append(solver.exactly_one(branches))

    for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
        if not isinstance(trigger, str):
            return None
        branch = object_presence_product_symbolic_expr(
            dependent_schema, variables, solver, depth + 1
        )
        if branch is None:
            return None
        constraints.append(
            solver.implies(variables.get(trigger, solver.bool_var(trigger)), branch)
        )

    if "not" in schema:
        negated = object_presence_product_symbolic_expr(
            schema["not"], variables, solver, depth + 1
        )
        if negated is None:
            return None
        constraints.append(solver.not_(negated))

    return solver.and_(*constraints)


def object_max_properties_bound_for_schema(
    schema: Any, depth: int = 0
) -> int | None:
    if depth > 16 or not isinstance(schema, dict):
        return None

    bounds = []
    maximum = schema.get("maxProperties")
    if isinstance(maximum, int) and not isinstance(maximum, bool):
        bounds.append(maximum)

    negated = schema.get("not")
    if isinstance(negated, dict):
        minimum = negated.get("minProperties")
        if isinstance(minimum, int) and not isinstance(minimum, bool) and minimum > 0:
            bounds.append(minimum - 1)

    for subschema in schema.get("allOf", []):
        bound = object_max_properties_bound_for_schema(subschema, depth + 1)
        if bound is not None:
            bounds.append(bound)

    for keyword in ("anyOf", "oneOf"):
        value = schema.get(keyword)
        if not isinstance(value, list):
            continue
        branch_bounds: list[int] = []
        for subschema in value:
            bound = object_max_properties_bound_for_schema(subschema, depth + 1)
            if bound is None:
                branch_bounds = []
                break
            branch_bounds.append(bound)
        if branch_bounds:
            bounds.append(max(branch_bounds))

    return min(bounds) if bounds else None


def object_min_properties_lower_bound_for_schema(
    schema: Any, depth: int = 0
) -> int:
    if depth > 16 or not isinstance(schema, dict):
        return 0
    bounds = []
    minimum = schema.get("minProperties")
    if isinstance(minimum, int) and not isinstance(minimum, bool):
        bounds.append(minimum)
    bounds.extend(
        object_min_properties_lower_bound_for_schema(subschema, depth + 1)
        for subschema in schema.get("allOf", [])
    )
    return max(bounds, default=0)


def _collect_object_presence_product_names(
    schema: Any, names: set[str], depth: int = 0
) -> bool:
    if depth > 16:
        return False
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return False
    if not _is_object_presence_product_schema(schema):
        return False

    for name in schema.get("required", []):
        names.add(name)
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        names.update(name for name in properties if isinstance(name, str))
    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        names.add(trigger)
        names.update(dependencies)
    for trigger, dependencies in schema.get("dependencies", {}).items():
        names.add(trigger)
        names.update(dependencies)
    for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
        names.add(trigger)
        if not _collect_object_presence_product_names(
            dependent_schema, names, depth + 1
        ):
            return False

    for keyword in ("allOf", "anyOf", "oneOf"):
        for subschema in schema.get(keyword, []):
            if not _collect_object_presence_product_names(subschema, names, depth + 1):
                return False
    if "not" in schema and not _collect_object_presence_product_names(
        schema["not"], names, depth + 1
    ):
        return False
    return True


def _local_object_presence_product_symbolic_expr(
    schema: dict[str, Any],
    variables: dict[str, Any],
    solver: SymbolicSolver,
) -> Any | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if "object" not in type_shape.atoms:
        return solver.or_()

    constraints = []
    for name in schema.get("required", []):
        if not isinstance(name, str):
            return None
        constraints.append(variables.get(name, solver.bool_var(name)))

    if schema.get("additionalProperties") is False:
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return None
        allowed = frozenset(name for name in properties if isinstance(name, str))
        constraints.extend(
            solver.not_(variable)
            for name, variable in variables.items()
            if name not in allowed
        )

    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        if not isinstance(trigger, str):
            return None
        dependency_vars = [
            variables.get(name, solver.bool_var(name)) for name in dependencies
        ]
        constraints.append(
            solver.implies(
                variables.get(trigger, solver.bool_var(trigger)),
                solver.and_(*dependency_vars),
            )
        )

    for trigger, dependencies in schema.get("dependencies", {}).items():
        if not isinstance(trigger, str):
            return None
        dependency_vars = [
            variables.get(name, solver.bool_var(name)) for name in dependencies
        ]
        constraints.append(
            solver.implies(
                variables.get(trigger, solver.bool_var(trigger)),
                solver.and_(*dependency_vars),
            )
        )

    minimum = schema.get("minProperties", 0)
    maximum = schema.get("maxProperties")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None
    values = tuple(variables.values())
    constraints.append(solver.cardinality_ge(values, minimum))
    if maximum is not None:
        constraints.append(solver.cardinality_le(values, maximum))
    return solver.and_(*constraints)


def _local_object_presence_product_accepts(
    schema: dict[str, Any],
    atom: str,
    present: frozenset[str],
) -> bool | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if atom not in type_shape.atoms:
        return False
    if atom != "object":
        return True

    required = frozenset(schema.get("required", []))
    if not required <= present:
        return False

    if schema.get("additionalProperties") is False:
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return None
        allowed = frozenset(name for name in properties if isinstance(name, str))
        if not present <= allowed:
            return False

    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        if trigger in present and not frozenset(dependencies) <= present:
            return False

    for trigger, dependencies in schema.get("dependencies", {}).items():
        if trigger in present and not frozenset(dependencies) <= present:
            return False

    minimum = schema.get("minProperties", 0)
    maximum = schema.get("maxProperties")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None
    if len(present) < minimum:
        return False
    if maximum is not None and len(present) > maximum:
        return False
    return True


def _is_object_presence_product_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in OBJECT_PRESENCE_PRODUCT_KEYWORDS:
            return False
        if key in {"allOf", "anyOf", "oneOf"} and not isinstance(value, list):
            return False
        if key == "not" and not isinstance(value, bool | dict):
            return False
        if key == "properties" and not isinstance(value, dict):
            return False
        if key == "additionalProperties" and value is not False:
            return False
        if key == "required" and not _is_string_array(value):
            return False
        if key == "dependentRequired" and not _is_string_array_map(value):
            return False
        if key == "dependencies" and not _is_string_array_map(value):
            return False
        if key == "dependentSchemas" and not _is_presence_product_schema_map(value):
            return False
        if key in {"minProperties", "maxProperties"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
    return True


def _is_presence_product_schema_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(name, str)
        and isinstance(dependent_schema, bool | dict)
        and _collect_object_presence_product_names(dependent_schema, set())
        for name, dependent_schema in value.items()
    )


def object_unevaluated_properties_true_fragment_supported(schema: Any) -> bool:
    return _object_unevaluated_properties_true_fragment_supported(schema)


def _object_unevaluated_properties_true_fragment_supported(
    schema: Any,
    depth: int = 0,
    *,
    is_root: bool = True,
    allow_required: bool = False,
) -> bool:
    if schema is True:
        return True
    if schema is False or depth > 16 or not isinstance(schema, dict):
        return False
    if _schema_is_pure_static_ref(schema):
        return True

    allowed_keywords = {
        "$defs",
        "additionalProperties",
        "allOf",
        "anyOf",
        "definitions",
        "else",
        "if",
        "oneOf",
        "patternProperties",
        "properties",
        "then",
        "type",
    }
    if allow_required:
        allowed_keywords.add("required")
    if is_root:
        allowed_keywords.add("unevaluatedProperties")
    if not _schema_has_only_keywords(schema, allowed_keywords):
        return False
    if (
        "additionalProperties" in schema
        and schema.get("additionalProperties") is not False
    ):
        return False
    if not _schema_type_accepts_objects(schema.get("type")):
        return False

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return False
    pattern_properties = schema.get("patternProperties", {})
    if not isinstance(pattern_properties, dict):
        return False
    if any(
        RegexLanguage.maybe_from_json_regex(str(pattern)) is None
        for pattern in pattern_properties
    ):
        return False

    return _object_unevaluated_properties_children_supported(
        schema, depth, allow_required=allow_required
    )


def _object_unevaluated_properties_children_supported(
    schema: dict[str, Any], depth: int, *, allow_required: bool
) -> bool:
    for keyword in ("allOf", "anyOf", "oneOf"):
        subschemas = schema.get(keyword, [])
        if not isinstance(subschemas, list):
            return False
        if not all(
            _object_unevaluated_properties_branch_supported(
                keyword,
                subschema,
                depth,
                allow_required=allow_required
                or keyword in {"allOf", "anyOf", "oneOf"},
            )
            for subschema in subschemas
        ):
            return False
    for keyword in ("if", "then", "else"):
        subschema = schema.get(keyword)
        if (
            subschema is not None
            and not _object_unevaluated_properties_true_fragment_supported(
                subschema,
                depth + 1,
                is_root=False,
                allow_required=allow_required or keyword in {"if", "then", "else"},
            )
        ):
            return False
    return True


def _object_unevaluated_properties_branch_supported(
    keyword: str, subschema: Any, depth: int, *, allow_required: bool
) -> bool:
    if subschema is False and keyword in {"anyOf", "oneOf"}:
        return True
    return _object_unevaluated_properties_true_fragment_supported(
        subschema,
        depth + 1,
        is_root=False,
        allow_required=allow_required,
    )


def _schema_type_accepts_objects(type_keyword: Any) -> bool:
    if type_keyword is None:
        return True
    if isinstance(type_keyword, str):
        return type_keyword == "object"
    if isinstance(type_keyword, list):
        return "object" in type_keyword
    return False


def _schema_has_only_keywords(schema: dict[str, Any], keywords: set[str]) -> bool:
    return all(key in keywords or key in IGNORED_SCHEMA_METADATA_KEYS for key in schema)


def _schema_is_pure_static_ref(schema: dict[str, Any]) -> bool:
    return {key for key in schema if key not in IGNORED_SCHEMA_METADATA_KEYS} == {
        "$ref"
    }


def _is_object_property_values_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in OBJECT_PROPERTY_VALUES_SCHEMA_KEYWORDS:
            return False
        if key == "allOf" and not isinstance(value, list):
            return False
        if key == "properties" and not isinstance(value, dict):
            return False
        if key == "required" and not _is_string_array(value):
            return False
    return True


def _local_object_property_values_shape(
    schema: dict[str, Any],
) -> ObjectPropertyValuesShape | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    properties = schema.get("properties", {})
    property_schemas = {
        name: (property_schema,)
        for name, property_schema in properties.items()
        if not schema_is_true(property_schema)
    }
    return ObjectPropertyValuesShape(
        property_schemas,
        frozenset(schema.get("required", [])),
        accepts_object="object" in type_shape.atoms,
        accepts_non_object=any(atom != "object" for atom in type_shape.atoms),
    )


@dataclass(frozen=True)
class ClosedObjectPropertiesShape:
    allowed_names: frozenset[str]
    keyspace_pattern: RegexLanguage | None
    required: frozenset[str]
    property_schemas: dict[str, tuple[Any, ...]]
    pattern_property_schemas: tuple[tuple[Any, Any], ...]
    accepts_object: bool
    accepts_non_object: bool
    has_finite_keyspace: bool

    def object_is_inhabited(self) -> bool:
        return self.accepts_object and all(
            self.keyspace_accepts(name) for name in self.required
        )

    def keyspace_satisfies(self, other: ClosedObjectPropertiesShape) -> bool:
        if not other.required <= self.required:
            return False
        if self.has_finite_keyspace:
            return all(other.keyspace_accepts(name) for name in self.allowed_names)
        if other.has_finite_keyspace:
            return False
        if self.keyspace_pattern is None or other.keyspace_pattern is None:
            return False
        subset = self.keyspace_pattern.is_subset_of(other.keyspace_pattern)
        return subset is True

    def keyspace_witness_not_in(
        self,
        other: ClosedObjectPropertiesShape,
        dialect: Dialect,
    ) -> dict[str, Any] | None:
        if not other.required <= self.required:
            return self.object_witness(dialect)
        for name in sorted(self.allowed_names):
            if not other.keyspace_accepts(name):
                value = _constructive_value_for_schema(
                    self.property_schema_for(name), dialect
                )
                return self.object_witness(dialect, override=(name, value))
        return None

    def property_schema_for(self, name: str) -> Any:
        return _all_of_schema(
            self.property_schemas.get(name, ())
            + self._matching_pattern_property_schemas(name)
        )

    def intersect(
        self, other: ClosedObjectPropertiesShape
    ) -> ClosedObjectPropertiesShape:
        finite_keyspace = self.has_finite_keyspace or other.has_finite_keyspace
        explicit_names = self.allowed_names | other.allowed_names
        names = frozenset(
            name
            for name in explicit_names
            if self.keyspace_accepts(name) and other.keyspace_accepts(name)
        )
        property_schemas = {}
        for name in names:
            constraints = self.property_schemas.get(
                name, ()
            ) + other.property_schemas.get(name, ())
            if constraints:
                property_schemas[name] = constraints
        return ClosedObjectPropertiesShape(
            names,
            _intersect_closed_keyspace_patterns(self, other, finite_keyspace),
            self.required | other.required,
            property_schemas,
            self.pattern_property_schemas + other.pattern_property_schemas,
            self.accepts_object and other.accepts_object,
            self.accepts_non_object and other.accepts_non_object,
            finite_keyspace,
        )

    def object_witness(
        self,
        dialect: Dialect,
        override: tuple[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        names = set(self.required)
        if override is not None:
            names.add(override[0])
        if not all(self.keyspace_accepts(name) for name in names):
            return None

        witness = {}
        for name in sorted(names):
            if override is not None and name == override[0]:
                value = override[1]
            else:
                value = _constructive_value_for_schema(
                    self.property_schema_for(name), dialect
                )
            if value is None:
                value = None
            witness[name] = value
        return witness

    def keyspace_accepts(self, name: str) -> bool:
        if self.has_finite_keyspace:
            return name in self.allowed_names
        if self.keyspace_pattern is None:
            return False
        return self.keyspace_pattern.matches(name)

    def _matching_pattern_property_schemas(self, name: str) -> tuple[Any, ...]:
        return tuple(
            property_schema
            for pattern, property_schema in self.pattern_property_schemas
            if pattern.matches(name)
        )


def closed_object_properties_shape_for_schema(
    schema: Any, depth: int = 0
) -> ClosedObjectPropertiesShape | None:
    if depth > 16:
        return None
    if schema is True:
        return _top_closed_object_properties_shape()
    if schema is False:
        return ClosedObjectPropertiesShape(
            frozenset(),
            None,
            frozenset(),
            {},
            (),
            accepts_object=False,
            accepts_non_object=False,
            has_finite_keyspace=True,
        )
    if not isinstance(schema, dict):
        return None
    if {"$ref", "$recursiveRef", "$dynamicRef"} & schema.keys():
        return None
    transparent_target = transparent_schema_target(schema)
    if transparent_target is not None:
        return closed_object_properties_shape_for_schema(transparent_target, depth + 1)
    if _is_closed_object_properties_all_of_wrapper_schema(schema):
        shape = _top_closed_object_properties_shape()
    elif _is_closed_object_properties_fragment_schema(schema):
        local_shape = _local_closed_object_properties_shape(schema)
        if local_shape is None:
            return None
        shape = local_shape
    else:
        return None

    for subschema in schema.get("allOf", []):
        branch = closed_object_properties_shape_for_schema(subschema, depth + 1)
        if branch is None:
            return None
        shape = shape.intersect(branch)
    return shape


def _top_closed_object_properties_shape() -> ClosedObjectPropertiesShape:
    return ClosedObjectPropertiesShape(
        frozenset(),
        RegexLanguage.all(),
        frozenset(),
        {},
        (),
        accepts_object=True,
        accepts_non_object=True,
        has_finite_keyspace=False,
    )


def _is_closed_object_properties_all_of_wrapper_schema(schema: dict[str, Any]) -> bool:
    saw_all_of = False
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key != "allOf":
            return False
        if not isinstance(value, list):
            return False
        saw_all_of = True
    return saw_all_of


def _is_closed_object_properties_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in OBJECT_CLOSED_PROPERTIES_SCHEMA_KEYWORDS:
            return False
        if (
            key == "additionalProperties"
            and value is not False
            and not schema_is_true(value)
        ):
            return False
        if key == "allOf" and not isinstance(value, list):
            return False
        if key == "properties" and not isinstance(value, dict):
            return False
        if key == "patternProperties" and not _is_pattern_properties_map(value):
            return False
        if key == "required" and not _is_string_array(value):
            return False
    return True


def _local_closed_object_properties_shape(
    schema: dict[str, Any],
) -> ClosedObjectPropertiesShape | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if "object" not in type_shape.atoms:
        return ClosedObjectPropertiesShape(
            frozenset(),
            None,
            frozenset(),
            {},
            (),
            accepts_object=False,
            accepts_non_object=bool(type_shape.atoms),
            has_finite_keyspace=True,
        )

    properties = schema.get("properties", {})
    property_schemas = {
        name: (property_schema,)
        for name, property_schema in properties.items()
        if not schema_is_true(property_schema)
    }
    pattern_property_schemas = []
    for pattern, property_schema in schema.get("patternProperties", {}).items():
        compiled = RegexLanguage.maybe_from_json_regex(pattern)
        if compiled is None:
            return None
        if not schema_is_true(property_schema):
            pattern_property_schemas.append((compiled, property_schema))
    additional_properties = schema.get("additionalProperties", True)
    has_finite_keyspace = additional_properties is False and not schema.get(
        "patternProperties"
    )
    keyspace_pattern = None
    if not has_finite_keyspace:
        if additional_properties is False:
            keyspace_pattern = _closed_object_allowed_name_pattern(schema)
            if keyspace_pattern is None:
                return None
        else:
            keyspace_pattern = RegexLanguage.all()
    return ClosedObjectPropertiesShape(
        frozenset(properties),
        keyspace_pattern,
        frozenset(schema.get("required", [])),
        property_schemas,
        tuple(pattern_property_schemas),
        accepts_object=True,
        accepts_non_object=any(atom != "object" for atom in type_shape.atoms),
        has_finite_keyspace=has_finite_keyspace,
    )


def _intersect_closed_keyspace_patterns(
    lhs: ClosedObjectPropertiesShape,
    rhs: ClosedObjectPropertiesShape,
    finite_keyspace: bool,
) -> Any | None:
    if finite_keyspace:
        return None
    if lhs.keyspace_pattern is None or rhs.keyspace_pattern is None:
        return None
    return lhs.keyspace_pattern.intersection(rhs.keyspace_pattern)


def _all_of_schema(schemas: tuple[Any, ...]) -> Any:
    if not schemas:
        return True
    if len(schemas) == 1:
        return schemas[0]
    return {"allOf": list(schemas)}


def _constructive_value_for_schema(schema: Any, dialect: Dialect) -> Any:
    if schema is True:
        return None
    if schema is False:
        return None

    explicit = explicit_finite_values_for_schema(schema)
    if explicit:
        return explicit[0]
    if not isinstance(schema, dict):
        return None

    all_of = schema_array_keyword_value(schema, "allOf")
    if all_of is not None:
        for subschema in all_of:
            if isinstance(subschema, dict) and "not" in subschema:
                continue
            value = _constructive_value_for_schema(subschema, dialect)
            if value is not None:
                return value
        return None

    numeric = numeric_shape_for_schema(schema, dialect)
    if numeric is not None and not numeric.accepts_non_numeric:
        for atom in numeric.normalized_atoms():
            value = atom.some_fraction()
            if value is not None:
                return int(value) if value.denominator == 1 else float(value)

    string = string_language_shape_for_schema(schema)
    if string is not None and not string.accepts_non_string:
        value = string_language_witness(string.pattern)
        if isinstance(value, str):
            return value

    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is not None and type_shape.atoms:
        return witness_for_type_atom(next(iter(sorted(type_shape.atoms))))
    return None


def _closed_property_value_schema_is_supported(schema: Any, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False

    allowed_keywords = IGNORED_SCHEMA_METADATA_KEYS | {
        "allOf",
        "anyOf",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maximum",
        "maxLength",
        "minimum",
        "minLength",
        "multipleOf",
        "not",
        "pattern",
        "type",
    }
    if any(key not in allowed_keywords for key in schema):
        return False

    schema_type = schema.get("type")
    if isinstance(schema_type, str) and schema_type in {"array", "object"}:
        return False
    if isinstance(schema_type, list) and any(
        item in {"array", "object"} for item in schema_type
    ):
        return False

    for key in ("allOf", "anyOf"):
        subschemas = schema.get(key, [])
        if not isinstance(subschemas, list):
            return False
        if not all(
            _closed_property_value_schema_is_supported(subschema, depth + 1)
            for subschema in subschemas
        ):
            return False
    if "not" in schema and not _closed_property_value_schema_is_supported(
        schema["not"], depth + 1
    ):
        return False
    return True


@dataclass(frozen=True)
class ObjectPropertyNamesShape:
    keyspace_pattern: Any
    required: frozenset[str]
    accepts_object: bool
    accepts_non_object: bool

    def object_is_inhabited(self) -> bool:
        return self.accepts_object and all(
            self.keyspace_pattern.matches(name) for name in self.required
        )

    def is_subset_of(self, other: ObjectPropertyNamesShape) -> bool:
        if self.accepts_non_object and not other.accepts_non_object:
            return False
        if not self.object_is_inhabited():
            return True
        if not other.accepts_object:
            return False
        if not other.required <= self.required:
            return False
        result = self.keyspace_pattern.is_subset_of(other.keyspace_pattern)
        return False if isinstance(result, ProofResult) else result

    def witness_not_in(self, other: ObjectPropertyNamesShape) -> Any | None:
        if self.accepts_non_object and not other.accepts_non_object:
            return witness_for_type_atom(
                next(iter(sorted(JSON_TYPE_ATOMS - {"object"})))
            )
        if not self.object_is_inhabited():
            return None
        if not other.accepts_object:
            return self._object_witness()
        if not other.required <= self.required:
            return self._object_witness()

        difference = self.keyspace_pattern.difference(other.keyspace_pattern)
        if isinstance(difference, ProofResult):
            return None
        bad_name = string_language_witness(difference)
        if not isinstance(bad_name, str):
            return None
        return self._object_witness(extra_name=bad_name)

    def intersect(self, other: ObjectPropertyNamesShape) -> ObjectPropertyNamesShape:
        return ObjectPropertyNamesShape(
            _expect_regex_language(
                self.keyspace_pattern.intersection(other.keyspace_pattern)
            ),
            self.required | other.required,
            self.accepts_object and other.accepts_object,
            self.accepts_non_object and other.accepts_non_object,
        )

    def _object_witness(self, extra_name: str | None = None) -> dict[str, None]:
        witness = dict.fromkeys(sorted(self.required))
        if extra_name is not None:
            witness[extra_name] = None
        return witness


def object_property_names_shape_for_schema(
    schema: Any, depth: int = 0
) -> ObjectPropertyNamesShape | None:
    cache_key = _cacheable_schema_key(schema)
    if cache_key is None:
        return _object_property_names_shape_for_schema_uncached(schema, depth)
    return _object_property_names_shape_for_schema_cached(cache_key, depth)


@lru_cache(maxsize=_SCHEMA_SHAPE_CACHE_SIZE)
def _object_property_names_shape_for_schema_cached(
    schema_key: str, depth: int
) -> ObjectPropertyNamesShape | None:
    return _object_property_names_shape_for_schema_uncached(
        strict_json_loads(schema_key), depth
    )


def _object_property_names_shape_for_schema_uncached(
    schema: Any, depth: int = 0
) -> ObjectPropertyNamesShape | None:
    if depth > 16:
        return None
    if schema is True:
        return ObjectPropertyNamesShape(
            RegexLanguage.all(),
            frozenset(),
            accepts_object=True,
            accepts_non_object=True,
        )
    if schema is False:
        return ObjectPropertyNamesShape(
            RegexLanguage.empty(),
            frozenset(),
            accepts_object=False,
            accepts_non_object=False,
        )
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    transparent_target = transparent_schema_target(schema)
    if transparent_target is not None:
        return object_property_names_shape_for_schema(transparent_target, depth + 1)
    if not _is_object_property_names_fragment_schema(schema):
        return None

    shape = _local_object_property_names_shape(schema)
    if shape is None:
        return None

    for subschema in schema.get("allOf", []):
        branch = object_property_names_shape_for_schema(subschema, depth + 1)
        if branch is None:
            return None
        shape = shape.intersect(branch)

    return shape


def _cacheable_schema_key(schema: Any) -> str | None:
    key = stable_key(schema)
    try:
        strict_json_loads(key)
    except (TypeError, ValueError):
        return None
    return key


def _is_object_property_names_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in OBJECT_PROPERTY_NAMES_SCHEMA_KEYWORDS:
            return False
        if key == "allOf" and not isinstance(value, list):
            return False
        if key == "required" and not _is_string_array(value):
            return False
        if key == "propertyNames" and string_language_shape_for_schema(value) is None:
            return False
        if key == "properties" and not isinstance(value, dict):
            return False
        if key == "patternProperties" and not _is_pattern_properties_map(value):
            return False
        if key == "additionalProperties" and not isinstance(value, bool):
            return False
    return True


def _local_object_property_names_shape(
    schema: dict[str, Any],
) -> ObjectPropertyNamesShape | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None

    name_pattern = RegexLanguage.all()
    if "propertyNames" in schema:
        name_shape = string_language_shape_for_schema(schema["propertyNames"])
        if name_shape is None:
            return None
        name_pattern = name_shape.pattern
    keyspace_pattern = name_pattern
    if schema.get("additionalProperties") is False:
        allowed_pattern = _closed_object_allowed_name_pattern(schema)
        if allowed_pattern is None:
            return None
        keyspace_pattern = _expect_regex_language(
            name_pattern.intersection(allowed_pattern)
        )

    return ObjectPropertyNamesShape(
        keyspace_pattern,
        frozenset(schema.get("required", [])),
        accepts_object="object" in type_shape.atoms,
        accepts_non_object=any(atom != "object" for atom in type_shape.atoms),
    )


def _is_pattern_properties_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(pattern, str)
        and RegexLanguage.maybe_from_json_regex(pattern) is not None
        for pattern in value
    )


def _closed_object_allowed_name_pattern(
    schema: dict[str, Any],
) -> RegexLanguage | None:
    patterns = [RegexLanguage.exact(name) for name in schema.get("properties", {})]
    for pattern in schema.get("patternProperties", {}):
        compiled = RegexLanguage.maybe_from_json_regex(pattern)
        if compiled is None:
            return None
        patterns.append(compiled)
    union = RegexLanguage.empty()
    for pattern in patterns:
        union = _expect_regex_language(union.union(pattern))
    return union


def _expect_regex_language(value: RegexLanguage | ProofResult) -> RegexLanguage:
    if isinstance(value, ProofResult):
        raise TypeError("unexpected regex proof result in unbudgeted object operation")
    return value




def object_property_names_schema_has_value_constraints(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 16:
        return True
    if not isinstance(schema, dict):
        return False

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return True
    if any(property_schema is not True for property_schema in properties.values()):
        return True

    pattern_properties = schema.get("patternProperties", {})
    if not isinstance(pattern_properties, dict):
        return True
    if any(
        property_schema is not True for property_schema in pattern_properties.values()
    ):
        return True

    additional_properties = schema.get("additionalProperties", True)
    if not isinstance(additional_properties, bool):
        return True

    return any(
        object_property_names_schema_has_value_constraints(subschema, depth + 1)
        for subschema in schema.get("allOf", [])
    )
