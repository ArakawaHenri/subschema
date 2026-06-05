"""
Object-domain reasoning for exact subschema proofs.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from subschema.dialects import Dialect
from subschema.kernel.contracts import ProofResult
from subschema.kernel.domains.strings import (
    string_language_shape_for_schema,
    string_language_witness,
)
from subschema.kernel.domains.types import (
    JSON_TYPE_ATOMS,
    type_shape_for_type_keyword,
    witness_for_type_atom,
)
from subschema.kernel.json_data import strict_json_loads
from subschema.kernel.protocols import SymbolicContext
from subschema.kernel.regex import RegexLanguage
from subschema.kernel.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
    schema_is_true,
    transparent_schema_target,
)
from subschema.kernel.symbolic import SAT, UNSAT, SymbolicSolver
from subschema.kernel.values import stable_key
from subschema.kernel.witnesses import build_schema_witness

_SCHEMA_SHAPE_CACHE_SIZE = 4096

__all__ = [
    "OBJECT_CLOSED_PROPERTIES_SCHEMA_KEYWORDS",
    "OBJECT_PROPERTY_COUNT_SCHEMA_KEYWORDS",
    "OBJECT_PROPERTY_NAMES_SCHEMA_KEYWORDS",
    "OBJECT_PROPERTY_VALUES_SCHEMA_KEYWORDS",
    "OBJECT_PRESENCE_SCHEMA_KEYWORDS",
    "OBJECT_STRUCTURE_SCHEMA_KEYWORDS",
    "ClosedObjectPropertiesShape",
    "ObjectPropertyNamesShape",
    "ObjectPropertyCountInterval",
    "ObjectPropertyCountShape",
    "ObjectPropertyValuesShape",
    "closed_object_properties_shape_for_schema",
    "object_property_names_shape_for_schema",
    "object_property_count_shape_for_schema",
    "object_property_values_shape_for_schema",
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
    value = build_schema_witness(schema, dialect)
    return value.witness if value.status == "witness" else None


def _constructive_value_satisfying_not_schema(
    lhs: Any, rhs: Any, dialect: Dialect
) -> Any:
    value = build_schema_witness({"allOf": [lhs, {"not": rhs}]}, dialect)
    return value.witness if value.status == "witness" else None


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


def _repair_object_witness_for_schema(
    schema: Any, witness: Any, dialect: Dialect
) -> dict[str, Any] | None:
    if not isinstance(witness, dict):
        return None
    repaired = dict(witness)
    for name in repaired:
        value = _constructive_value_for_property(schema, name, dialect)
        if value is None:
            continue
        repaired[name] = value
    return repaired


def _constructive_value_for_property(
    schema: Any, property_name: str, dialect: Dialect
) -> Any | None:
    property_schemas = _property_value_schemas_for_key(schema, property_name)
    if property_schemas is None:
        return None
    if not property_schemas:
        return None

    value = build_schema_witness(_all_of_schema(tuple(property_schemas)), dialect)
    return value.witness if value.status == "witness" else None


def _property_value_schemas_for_key(
    schema: Any, property_name: str, depth: int = 0
) -> list[Any] | None:
    if depth > 16:
        return None
    if isinstance(schema, bool):
        return [] if schema else None
    if not isinstance(schema, dict):
        return None
    if not _is_object_property_names_fragment_schema(schema):
        return None

    schemas = []
    properties = schema.get("properties", {})
    if isinstance(properties, dict) and property_name in properties:
        schemas.append(properties[property_name])
    pattern_properties = schema.get("patternProperties", {})
    if isinstance(pattern_properties, dict):
        for pattern, subschema in pattern_properties.items():
            compiled = RegexLanguage.maybe_from_json_regex(pattern)
            if compiled is None:
                return None
            if compiled.matches(property_name):
                schemas.append(subschema)

    for subschema in schema.get("allOf", []):
        nested = _property_value_schemas_for_key(subschema, property_name, depth + 1)
        if nested is None:
            return None
        schemas.extend(nested)
    return schemas


def _object_property_names_schema_has_value_constraints(
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
        _object_property_names_schema_has_value_constraints(subschema, depth + 1)
        for subschema in schema.get("allOf", [])
    )
