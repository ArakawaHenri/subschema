"""
Compiler-owned extraction of local evaluation frontier facts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from subschema.compiler.schemas import (
    schema_array_keyword_value,
    schema_has_keyword,
    schema_keyword_value,
    schema_mapping_keyword_value,
)
from subschema.dialects import Dialect
from subschema.ir.evaluation import (
    EvaluatedItemSource,
    EvaluatedPropertySource,
    EvaluationFrontier,
    UnevaluatedConstraint,
    UnevaluatedKeyword,
)
from subschema.ir.terms import SchemaTerm

__all__ = ["evaluation_frontier_for_schema"]


def evaluation_frontier_for_schema(
    schema: Any,
    dialect: Dialect,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
) -> EvaluationFrontier:
    if not isinstance(schema, dict):
        return EvaluationFrontier()

    return EvaluationFrontier(
        property_sources=_property_sources_for_schema(schema, child_term),
        item_sources=_item_sources_for_schema(schema, dialect, child_term),
        unevaluated_properties=_unevaluated_constraint(
            schema, "unevaluatedProperties", child_term
        ),
        unevaluated_items=_unevaluated_constraint(
            schema, "unevaluatedItems", child_term
        ),
    )


def _property_sources_for_schema(
    schema: dict[str, Any],
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
) -> tuple[EvaluatedPropertySource, ...]:
    sources: list[EvaluatedPropertySource] = []

    properties = schema_mapping_keyword_value(schema, "properties")
    if properties is not None:
        sources.extend(
            EvaluatedPropertySource(
                "properties",
                key=str(property_name),
                term=_source_term(
                    child_term, subschema, ("properties", str(property_name))
                ),
            )
            for property_name, subschema in sorted(properties.items())
        )

    pattern_properties = schema_mapping_keyword_value(schema, "patternProperties")
    if pattern_properties is not None:
        sources.extend(
            EvaluatedPropertySource(
                "patternProperties",
                key=str(pattern),
                term=_source_term(
                    child_term, subschema, ("patternProperties", str(pattern))
                ),
            )
            for pattern, subschema in sorted(pattern_properties.items())
        )

    if schema_has_keyword(schema, "additionalProperties"):
        sources.append(
            EvaluatedPropertySource(
                "additionalProperties",
                term=_source_term(
                    child_term,
                    schema_keyword_value(schema, "additionalProperties"),
                    ("additionalProperties",),
                ),
            )
        )

    dependencies = schema_mapping_keyword_value(schema, "dependencies")
    if dependencies is not None:
        sources.extend(
            EvaluatedPropertySource(
                "dependencies",
                key=str(property_name),
                term=_source_term(
                    child_term, dependency, ("dependencies", str(property_name))
                ),
            )
            for property_name, dependency in sorted(dependencies.items())
            if isinstance(dependency, dict)
        )

    dependent_schemas = schema_mapping_keyword_value(schema, "dependentSchemas")
    if dependent_schemas is not None:
        sources.extend(
            EvaluatedPropertySource(
                "dependentSchemas",
                key=str(property_name),
                term=_source_term(
                    child_term,
                    subschema,
                    ("dependentSchemas", str(property_name)),
                ),
            )
            for property_name, subschema in sorted(dependent_schemas.items())
        )

    return tuple(sources)


def _item_sources_for_schema(
    schema: dict[str, Any],
    dialect: Dialect,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
) -> tuple[EvaluatedItemSource, ...]:
    sources: list[EvaluatedItemSource] = []

    if dialect is Dialect.DRAFT202012:
        prefix_items = schema_array_keyword_value(schema, "prefixItems")
        prefix_count = 0
        if prefix_items is not None:
            prefix_count = len(prefix_items)
            sources.extend(
                EvaluatedItemSource(
                    "prefixItems",
                    index=index,
                    term=_source_term(
                        child_term, subschema, ("prefixItems", str(index))
                    ),
                )
                for index, subschema in enumerate(prefix_items)
            )

        items = schema_keyword_value(schema, "items")
        if schema_has_keyword(schema, "items") and not isinstance(items, list):
            sources.append(
                EvaluatedItemSource(
                    "items",
                    start_index=prefix_count,
                    term=_source_term(child_term, items, ("items",)),
                )
            )
    else:
        items = schema_keyword_value(schema, "items")
        tuple_count = 0
        if isinstance(items, list):
            tuple_count = len(items)
            sources.extend(
                EvaluatedItemSource(
                    "items",
                    index=index,
                    term=_source_term(child_term, subschema, ("items", str(index))),
                )
                for index, subschema in enumerate(items)
            )
        elif schema_has_keyword(schema, "items"):
            sources.append(
                EvaluatedItemSource(
                    "items",
                    start_index=0,
                    term=_source_term(child_term, items, ("items",)),
                )
            )

        if schema_has_keyword(schema, "additionalItems"):
            sources.append(
                EvaluatedItemSource(
                    "additionalItems",
                    start_index=tuple_count,
                    term=_source_term(
                        child_term,
                        schema_keyword_value(schema, "additionalItems"),
                        ("additionalItems",),
                    ),
                )
            )

    if schema_has_keyword(schema, "contains"):
        sources.append(
            EvaluatedItemSource(
                "contains",
                term=_source_term(
                    child_term, schema_keyword_value(schema, "contains"), ("contains",)
                ),
                marks_contains_matches=dialect is Dialect.DRAFT202012,
            )
        )

    return tuple(sources)


def _unevaluated_constraint(
    schema: dict[str, Any],
    keyword: UnevaluatedKeyword,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
) -> UnevaluatedConstraint | None:
    if not schema_has_keyword(schema, keyword):
        return None
    value = schema_keyword_value(schema, keyword)
    return UnevaluatedConstraint(
        keyword,
        _source_term(child_term, value, (keyword,)),
    )


def _source_term(
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
    schema: Any,
    path: tuple[str, ...],
) -> SchemaTerm:
    if schema is True:
        return SchemaTerm.true()
    if schema is False:
        return SchemaTerm.false()
    if child_term is None or not isinstance(schema, dict):
        return SchemaTerm.true()
    return child_term(schema, path)
