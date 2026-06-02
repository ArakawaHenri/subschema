"""
Concrete validation/evaluation oracle built on ResourceGraph.

This is an internal harness for checking that resource and evaluation semantics
match JSON Schema behavior on representative instances.  It is intentionally
small and conservative: unsupported keywords are reported instead of guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, TypeGuard

from subschema.dialects import (
    Dialect,
    dialect_from_schema,
    strip_inactive_keywords_for_dialect,
)
from subschema.kernel.json_data import ensure_json_value
from subschema.kernel.references import DynamicScope, ReferenceFrame, ResourceGraph
from subschema.kernel.values import json_semantic_key, json_values_equal

__all__ = [
    "ConcreteEvaluationResult",
    "ConcreteEvaluator",
]


@dataclass(frozen=True)
class ConcreteEvaluationResult:
    valid: bool
    evaluated_properties: frozenset[str] = frozenset()
    evaluated_items: frozenset[int] = frozenset()
    unsupported: tuple[str, ...] = ()

    @property
    def is_supported(self) -> bool:
        return not self.unsupported


@dataclass
class ConcreteEvaluator:
    graph: ResourceGraph
    _seen: set[tuple[str, tuple[str, ...], Dialect, int]] = field(
        default_factory=set
    )

    @classmethod
    def for_schema(
        cls, schema: Any, dialect: Dialect | str | None = None
    ) -> ConcreteEvaluator:
        ensure_json_value(schema, label="schema")
        return cls(ResourceGraph.build(schema, dialect=dialect))

    def validate(self, instance: Any) -> ConcreteEvaluationResult:
        ensure_json_value(instance, label="instance")
        return self._validate_at(
            self.graph.root,
            instance,
            pointer=(),
            scope=DynamicScope().push(self.graph.reference_frame_for_pointer(())),
        )

    def _validate_at(
        self,
        schema: Any,
        instance: Any,
        *,
        pointer: tuple[str, ...],
        scope: DynamicScope,
        dialect: Dialect | None = None,
    ) -> ConcreteEvaluationResult:
        if schema is True:
            return _valid()
        if schema is False:
            return _invalid()
        if not isinstance(schema, dict):
            return _valid()

        frame = self._frame_for_schema(pointer, schema, dialect)
        schema = strip_inactive_keywords_for_dialect(schema, frame.dialect)
        if isinstance(schema.get("$dynamicAnchor"), str):
            scope = scope.push(frame)

        key = (frame.resource_uri, frame.resource_pointer, frame.dialect, id(instance))
        if key in self._seen:
            return _unsupported(
                f"concrete evaluator does not support recursive schema at {pointer!r}"
            )
        self._seen.add(key)
        try:
            result = self._validate_references(
                schema, instance, pointer=pointer, scope=scope, frame=frame
            )
            if not result.valid or not result.is_supported:
                return result

            if not _type_accepts(schema.get("type"), instance):
                return _invalid()
            if "const" in schema and not json_values_equal(instance, schema["const"]):
                return _invalid()
            enum = schema.get("enum")
            if isinstance(enum, list) and not any(
                json_values_equal(instance, value) for value in enum
            ):
                return _invalid()

            result = _merge(
                result,
                self._validate_scalar_keywords(schema, instance, dialect=frame.dialect),
            )
            if not result.valid or not result.is_supported:
                return result

            result = _merge(
                result,
                self._validate_applicators(
                    schema,
                    instance,
                    pointer=pointer,
                    scope=scope,
                    dialect=frame.dialect,
                ),
            )
            if not result.valid or not result.is_supported:
                return result
            result = _merge(
                result,
                self._validate_object_keywords(
                    schema,
                    instance,
                    pointer=pointer,
                    scope=scope,
                    dialect=frame.dialect,
                ),
            )
            if not result.valid or not result.is_supported:
                return result
            return _merge(
                result,
                self._validate_array_keywords(
                    schema,
                    instance,
                    pointer=pointer,
                    scope=scope,
                    dialect=frame.dialect,
                ),
            )
        finally:
            self._seen.discard(key)

    def _frame_for_schema(
        self,
        pointer: tuple[str, ...],
        schema: dict[str, Any],
        inherited_dialect: Dialect | None,
    ) -> ReferenceFrame:
        frame = self.graph.reference_frame_for_pointer(pointer)
        dialect = dialect_from_schema(schema) or inherited_dialect or frame.dialect
        return ReferenceFrame(
            frame.resource_uri,
            frame.document_pointer,
            frame.resource_pointer,
            dialect,
        )

    def _validate_references(
        self,
        schema: dict[str, Any],
        instance: Any,
        *,
        pointer: tuple[str, ...],
        scope: DynamicScope,
        frame: ReferenceFrame,
    ) -> ConcreteEvaluationResult:
        result = _valid()
        if isinstance(schema.get("$ref"), str):
            resolution = self.graph.resolve_ref_info(
                schema["$ref"],
                base_uri=frame.resource_uri,
                source_pointer=frame.document_pointer,
                source_resource_pointer=frame.resource_pointer,
            )
            if resolution is None:
                return _unsupported(
                    f"concrete evaluator could not resolve $ref {schema['$ref']!r}"
                )
            result = _merge(
                result,
                self._validate_at(
                    resolution.schema,
                    instance,
                    pointer=resolution.document_pointer,
                    scope=scope.push(
                        self._frame_for_schema(
                            resolution.document_pointer,
                            resolution.schema,
                            resolution.dialect,
                        )
                    ),
                    dialect=resolution.dialect,
                ),
            )
        if isinstance(schema.get("$dynamicRef"), str):
            resolution = self.graph.resolve_dynamic_ref_info(
                schema["$dynamicRef"], frame, dynamic_scope=scope
            )
            if resolution is None:
                return _unsupported(
                    f"concrete evaluator could not resolve $dynamicRef {
                        schema['$dynamicRef']!r
                    }"
                )
            result = _merge(
                result,
                self._validate_at(
                    resolution.schema,
                    instance,
                    pointer=resolution.document_pointer,
                    scope=scope.push(
                        self._frame_for_schema(
                            resolution.document_pointer,
                            resolution.schema,
                            resolution.dialect,
                        )
                    ),
                    dialect=resolution.dialect,
                ),
            )
        return result

    def _validate_applicators(
        self,
        schema: dict[str, Any],
        instance: Any,
        *,
        pointer: tuple[str, ...],
        scope: DynamicScope,
        dialect: Dialect,
    ) -> ConcreteEvaluationResult:
        result = _valid()
        for index, subschema in enumerate(
            schema.get("allOf", []) if isinstance(schema.get("allOf"), list) else []
        ):
            result = _merge(
                result,
                self._validate_at(
                    subschema,
                    instance,
                    pointer=pointer + ("allOf", str(index)),
                    scope=scope,
                    dialect=dialect,
                ),
            )
            if not result.valid or not result.is_supported:
                return result

        any_of = schema.get("anyOf")
        if isinstance(any_of, list):
            branch_results = [
                self._validate_at(
                    subschema,
                    instance,
                    pointer=pointer + ("anyOf", str(index)),
                    scope=scope,
                    dialect=dialect,
                )
                for index, subschema in enumerate(any_of)
            ]
            result = _merge(
                result, _merge_valid_branches(branch_results, require_one=True)
            )
            if not result.valid or not result.is_supported:
                return result

        one_of = schema.get("oneOf")
        if isinstance(one_of, list):
            branch_results = [
                self._validate_at(
                    subschema,
                    instance,
                    pointer=pointer + ("oneOf", str(index)),
                    scope=scope,
                    dialect=dialect,
                )
                for index, subschema in enumerate(one_of)
            ]
            result = _merge(
                result, _merge_valid_branches(branch_results, require_exactly_one=True)
            )
            if not result.valid or not result.is_supported:
                return result

        if "not" in schema:
            not_result = self._validate_at(
                schema["not"],
                instance,
                pointer=pointer + ("not",),
                scope=scope,
                dialect=dialect,
            )
            if not not_result.is_supported:
                return not_result
            if not_result.valid:
                return _invalid()

        if_schema = schema.get("if")
        if if_schema is not None:
            if_result = self._validate_at(
                if_schema,
                instance,
                pointer=pointer + ("if",),
                scope=scope,
                dialect=dialect,
            )
            if not if_result.is_supported:
                return if_result
            branch = "then" if if_result.valid else "else"
            if branch in schema:
                result = _merge(
                    result,
                    self._validate_at(
                        schema[branch],
                        instance,
                        pointer=pointer + (branch,),
                        scope=scope,
                        dialect=dialect,
                    ),
                )
        return result

    def _validate_scalar_keywords(
        self,
        schema: dict[str, Any],
        instance: Any,
        *,
        dialect: Dialect,
    ) -> ConcreteEvaluationResult:
        result = _validate_numeric_keywords(schema, instance, dialect)
        if not result.valid or not result.is_supported:
            return result
        return _validate_string_keywords(schema, instance)

    def _validate_object_keywords(
        self,
        schema: dict[str, Any],
        instance: Any,
        *,
        pointer: tuple[str, ...],
        scope: DynamicScope,
        dialect: Dialect,
    ) -> ConcreteEvaluationResult:
        if not isinstance(instance, dict):
            return _valid()
        result = _valid()
        required = schema.get("required")
        if isinstance(required, list) and any(
            name not in instance for name in required
        ):
            return _invalid()
        min_properties = schema.get("minProperties")
        if (
            isinstance(min_properties, int)
            and not isinstance(min_properties, bool)
            and len(instance) < min_properties
        ):
            return _invalid()
        max_properties = schema.get("maxProperties")
        if (
            isinstance(max_properties, int)
            and not isinstance(max_properties, bool)
            and len(instance) > max_properties
        ):
            return _invalid()

        if "propertyNames" in schema:
            for name in instance:
                child = self._validate_at(
                    schema["propertyNames"],
                    name,
                    pointer=pointer + ("propertyNames",),
                    scope=scope,
                    dialect=dialect,
                )
                if not child.valid or not child.is_supported:
                    return child

        property_names = set()
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, subschema in properties.items():
                if name not in instance:
                    continue
                child = self._validate_at(
                    subschema,
                    instance[name],
                    pointer=pointer + ("properties", str(name)),
                    scope=scope,
                    dialect=dialect,
                )
                if not child.valid or not child.is_supported:
                    return child
                property_names.add(str(name))

        patterns = schema.get("patternProperties")
        if isinstance(patterns, dict):
            for pattern, subschema in patterns.items():
                for name, value in instance.items():
                    if re.search(str(pattern), name) is None:
                        continue
                    child = self._validate_at(
                        subschema,
                        value,
                        pointer=pointer + ("patternProperties", str(pattern)),
                        scope=scope,
                        dialect=dialect,
                    )
                    if not child.valid or not child.is_supported:
                        return child
                    property_names.add(name)

        dependencies = schema.get("dependencies")
        if isinstance(dependencies, dict):
            for trigger, dependency in dependencies.items():
                if trigger not in instance:
                    continue
                if isinstance(dependency, list):
                    if any(name not in instance for name in dependency):
                        return _invalid()
                    continue
                if isinstance(dependency, dict) or isinstance(dependency, bool):
                    child = self._validate_at(
                        dependency,
                        instance,
                        pointer=pointer + ("dependencies", str(trigger)),
                        scope=scope,
                        dialect=dialect,
                    )
                    if not child.valid or not child.is_supported:
                        return child
                    result = _merge(result, child)

        dependent_required = schema.get("dependentRequired")
        if isinstance(dependent_required, dict):
            for trigger, dependencies in dependent_required.items():
                if trigger in instance and isinstance(dependencies, list):
                    if any(name not in instance for name in dependencies):
                        return _invalid()

        dependent_schemas = schema.get("dependentSchemas")
        if isinstance(dependent_schemas, dict):
            for trigger, subschema in dependent_schemas.items():
                if trigger not in instance:
                    continue
                child = self._validate_at(
                    subschema,
                    instance,
                    pointer=pointer + ("dependentSchemas", str(trigger)),
                    scope=scope,
                    dialect=dialect,
                )
                if not child.valid or not child.is_supported:
                    return child
                result = _merge(result, child)

        if "additionalProperties" in schema:
            for name, value in instance.items():
                if name in property_names or (
                    isinstance(properties, dict) and name in properties
                ):
                    continue
                child = self._validate_at(
                    schema["additionalProperties"],
                    value,
                    pointer=pointer + ("additionalProperties",),
                    scope=scope,
                    dialect=dialect,
                )
                if not child.valid or not child.is_supported:
                    return child
                property_names.add(name)

        result = ConcreteEvaluationResult(
            True,
            result.evaluated_properties | frozenset(property_names),
            result.evaluated_items,
        )
        if "unevaluatedProperties" in schema:
            for name, value in instance.items():
                if name in result.evaluated_properties:
                    continue
                child = self._validate_at(
                    schema["unevaluatedProperties"],
                    value,
                    pointer=pointer + ("unevaluatedProperties",),
                    scope=scope,
                    dialect=dialect,
                )
                if not child.valid or not child.is_supported:
                    return child
        return result

    def _validate_array_keywords(
        self,
        schema: dict[str, Any],
        instance: Any,
        *,
        pointer: tuple[str, ...],
        scope: DynamicScope,
        dialect: Dialect,
    ) -> ConcreteEvaluationResult:
        if not isinstance(instance, list):
            return _valid()
        evaluated = set()
        min_items = schema.get("minItems")
        if (
            isinstance(min_items, int)
            and not isinstance(min_items, bool)
            and len(instance) < min_items
        ):
            return _invalid()
        max_items = schema.get("maxItems")
        if (
            isinstance(max_items, int)
            and not isinstance(max_items, bool)
            and len(instance) > max_items
        ):
            return _invalid()
        if schema.get("uniqueItems") is True and not _has_unique_items(instance):
            return _invalid()

        if dialect is Dialect.DRAFT202012:
            prefix_items = schema.get("prefixItems")
            prefix_count = 0
            if isinstance(prefix_items, list):
                prefix_count = len(prefix_items)
                for index, subschema in enumerate(prefix_items):
                    if index >= len(instance):
                        continue
                    child = self._validate_at(
                        subschema,
                        instance[index],
                        pointer=pointer + ("prefixItems", str(index)),
                        scope=scope,
                        dialect=dialect,
                    )
                    if not child.valid or not child.is_supported:
                        return child
                    evaluated.add(index)
            if "items" in schema and not isinstance(schema["items"], list):
                for index in range(prefix_count, len(instance)):
                    child = self._validate_at(
                        schema["items"],
                        instance[index],
                        pointer=pointer + ("items",),
                        scope=scope,
                        dialect=dialect,
                    )
                    if not child.valid or not child.is_supported:
                        return child
                    evaluated.add(index)
        else:
            items = schema.get("items")
            tuple_count = 0
            if isinstance(items, list):
                tuple_count = len(items)
                for index, subschema in enumerate(items):
                    if index >= len(instance):
                        continue
                    child = self._validate_at(
                        subschema,
                        instance[index],
                        pointer=pointer + ("items", str(index)),
                        scope=scope,
                        dialect=dialect,
                    )
                    if not child.valid or not child.is_supported:
                        return child
                    evaluated.add(index)
                if "additionalItems" in schema:
                    for index in range(tuple_count, len(instance)):
                        child = self._validate_at(
                            schema["additionalItems"],
                            instance[index],
                            pointer=pointer + ("additionalItems",),
                            scope=scope,
                            dialect=dialect,
                        )
                        if not child.valid or not child.is_supported:
                            return child
                        evaluated.add(index)
            elif "items" in schema:
                for index, value in enumerate(instance):
                    child = self._validate_at(
                        items,
                        value,
                        pointer=pointer + ("items",),
                        scope=scope,
                        dialect=dialect,
                    )
                    if not child.valid or not child.is_supported:
                        return child
                    evaluated.add(index)

        if "contains" in schema:
            matches = []
            for index, value in enumerate(instance):
                child = self._validate_at(
                    schema["contains"],
                    value,
                    pointer=pointer + ("contains",),
                    scope=scope,
                    dialect=dialect,
                )
                if not child.is_supported:
                    return child
                if child.valid:
                    matches.append(index)
            if dialect in {Dialect.DRAFT201909, Dialect.DRAFT202012}:
                raw_minimum = schema.get("minContains", 1)
                if not isinstance(raw_minimum, int) or isinstance(raw_minimum, bool):
                    return _unsupported(
                        "concrete evaluator requires integer minContains"
                    )
                minimum = raw_minimum
                maximum = schema.get("maxContains")
                if isinstance(maximum, bool) or (
                    maximum is not None and not isinstance(maximum, int)
                ):
                    return _unsupported(
                        "concrete evaluator requires integer maxContains"
                    )
            else:
                minimum = 1
                maximum = None
            if len(matches) < minimum or (
                isinstance(maximum, int) and len(matches) > maximum
            ):
                return _invalid()
            if dialect is Dialect.DRAFT202012:
                evaluated.update(matches)

        if "unevaluatedItems" in schema:
            for index, value in enumerate(instance):
                if index in evaluated:
                    continue
                child = self._validate_at(
                    schema["unevaluatedItems"],
                    value,
                    pointer=pointer + ("unevaluatedItems",),
                    scope=scope,
                    dialect=dialect,
                )
                if not child.valid or not child.is_supported:
                    return child
        return ConcreteEvaluationResult(True, frozenset(), frozenset(evaluated))


def _validate_numeric_keywords(
    schema: dict[str, Any],
    instance: Any,
    dialect: Dialect,
) -> ConcreteEvaluationResult:
    if not _is_json_number(instance):
        return _valid()

    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if _is_json_number(minimum):
        exclusive_minimum = schema.get("exclusiveMinimum")
        if isinstance(exclusive_minimum, bool) and dialect is Dialect.DRAFT4:
            if exclusive_minimum and instance <= minimum:
                return _invalid()
        elif instance < minimum:
            return _invalid()

    if _is_json_number(maximum):
        exclusive_maximum = schema.get("exclusiveMaximum")
        if isinstance(exclusive_maximum, bool) and dialect is Dialect.DRAFT4:
            if exclusive_maximum and instance >= maximum:
                return _invalid()
        elif instance > maximum:
            return _invalid()

    exclusive_minimum = schema.get("exclusiveMinimum")
    if _is_json_number(exclusive_minimum) and instance <= exclusive_minimum:
        return _invalid()

    exclusive_maximum = schema.get("exclusiveMaximum")
    if _is_json_number(exclusive_maximum) and instance >= exclusive_maximum:
        return _invalid()

    multiple_of = schema.get("multipleOf")
    if _is_json_number(multiple_of):
        if multiple_of <= 0:
            return _unsupported("concrete evaluator requires positive multipleOf")
        if not _is_multiple_of(instance, multiple_of):
            return _invalid()

    return _valid()


def _validate_string_keywords(
    schema: dict[str, Any], instance: Any
) -> ConcreteEvaluationResult:
    if not isinstance(instance, str):
        return _valid()

    min_length = schema.get("minLength")
    if (
        isinstance(min_length, int)
        and not isinstance(min_length, bool)
        and len(instance) < min_length
    ):
        return _invalid()

    max_length = schema.get("maxLength")
    if (
        isinstance(max_length, int)
        and not isinstance(max_length, bool)
        and len(instance) > max_length
    ):
        return _invalid()

    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            matches = re.search(pattern, instance) is not None
        except re.error:
            return _unsupported(
                "concrete evaluator does not support invalid regex patterns"
            )
        if not matches:
            return _invalid()

    return _valid()


def _is_json_number(value: Any) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, int | float)


def _is_json_integer(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value.is_integer()


def _is_multiple_of(instance: int | float, divisor: int | float) -> bool:
    return (Fraction(str(instance)) / Fraction(str(divisor))).denominator == 1


def _has_unique_items(instance: list[Any]) -> bool:
    seen = set()
    for value in instance:
        key = json_semantic_key(value)
        if key in seen:
            return False
        seen.add(key)
    return True


def _merge(
    lhs: ConcreteEvaluationResult, rhs: ConcreteEvaluationResult
) -> ConcreteEvaluationResult:
    return ConcreteEvaluationResult(
        lhs.valid and rhs.valid,
        lhs.evaluated_properties | rhs.evaluated_properties,
        lhs.evaluated_items | rhs.evaluated_items,
        lhs.unsupported + rhs.unsupported,
    )


def _merge_valid_branches(
    branches: list[ConcreteEvaluationResult],
    *,
    require_one: bool = False,
    require_exactly_one: bool = False,
) -> ConcreteEvaluationResult:
    unsupported = tuple(reason for branch in branches for reason in branch.unsupported)
    if unsupported:
        return ConcreteEvaluationResult(False, unsupported=unsupported)
    valid_branches = [branch for branch in branches if branch.valid]
    if require_one and not valid_branches:
        return _invalid()
    if require_exactly_one and len(valid_branches) != 1:
        return _invalid()
    result = _valid()
    for branch in valid_branches:
        result = _merge(result, branch)
    return result


def _valid() -> ConcreteEvaluationResult:
    return ConcreteEvaluationResult(True)


def _invalid() -> ConcreteEvaluationResult:
    return ConcreteEvaluationResult(False)


def _unsupported(reason: str) -> ConcreteEvaluationResult:
    return ConcreteEvaluationResult(False, unsupported=(reason,))


def _type_accepts(type_keyword: Any, instance: Any) -> bool:
    if type_keyword is None:
        return True
    if isinstance(type_keyword, str):
        return _single_type_accepts(type_keyword, instance)
    if isinstance(type_keyword, list):
        return any(_single_type_accepts(str(item), instance) for item in type_keyword)
    return True


def _single_type_accepts(type_name: str, instance: Any) -> bool:
    if type_name == "null":
        return instance is None
    if type_name == "boolean":
        return isinstance(instance, bool)
    if type_name == "integer":
        return _is_json_integer(instance)
    if type_name == "number":
        return not isinstance(instance, bool) and isinstance(instance, int | float)
    if type_name == "string":
        return isinstance(instance, str)
    if type_name == "array":
        return isinstance(instance, list)
    if type_name == "object":
        return isinstance(instance, dict)
    return True
