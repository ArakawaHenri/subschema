"""
Evaluation-frontier IR for keywords that feed unevaluated* semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

from subschema.dialects import Dialect
from subschema.kernel.values import stable_key

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext

PropertyEvaluationKind = Literal[
    "additionalProperties",
    "dependencies",
    "dependentSchemas",
    "patternProperties",
    "properties",
]
ItemEvaluationKind = Literal[
    "additionalItems",
    "contains",
    "items",
    "prefixItems",
]
UnevaluatedKeyword = Literal["unevaluatedItems", "unevaluatedProperties"]
EvaluationOriginKind = Literal[
    "allOf",
    "anyOf",
    "conditional",
    "dynamic-ref",
    "local",
    "not",
    "oneOf",
    "static-ref",
]

__all__ = [
    "EvaluatedItemSource",
    "EvaluatedPropertySource",
    "EvaluationExpression",
    "EvaluationExpressionOrigin",
    "EvaluationFrontier",
    "EvaluationOriginKind",
    "EvaluationTraceExpression",
    "EvaluationTracePath",
    "ItemEvaluationKind",
    "PropertyEvaluationKind",
    "UnevaluatedConstraint",
    "UnevaluatedKeyword",
    "evaluation_expression_for_source",
    "evaluation_frontier_for_schema",
    "evaluation_trace_for_source",
]


@dataclass(frozen=True)
class EvaluatedPropertySource:
    kind: PropertyEvaluationKind
    key: str | None = None
    schema: Any = None


@dataclass(frozen=True)
class EvaluatedItemSource:
    kind: ItemEvaluationKind
    index: int | None = None
    start_index: int | None = None
    schema: Any = None
    marks_contains_matches: bool = False


@dataclass(frozen=True)
class UnevaluatedConstraint:
    keyword: UnevaluatedKeyword
    schema: Any

    @property
    def domain(self) -> Literal["items", "properties"]:
        return "items" if self.keyword == "unevaluatedItems" else "properties"


@dataclass(frozen=True)
class EvaluationFrontier:
    """Local evaluated locations and delayed unevaluated* constraints.

    This is intentionally separate from object/array shape facts.  Shape facts
    describe direct assertions.  A frontier describes annotations produced by
    successful applicators, which later unevaluated* rules must consume after
    branch composition has been resolved.
    """

    property_sources: tuple[EvaluatedPropertySource, ...] = ()
    item_sources: tuple[EvaluatedItemSource, ...] = ()
    unevaluated_properties: UnevaluatedConstraint | None = None
    unevaluated_items: UnevaluatedConstraint | None = None

    @property
    def has_local_sources(self) -> bool:
        return bool(self.property_sources or self.item_sources)

    @property
    def requires_evaluation_tracking(self) -> bool:
        return (
            self.unevaluated_properties is not None
            or self.unevaluated_items is not None
        )

    @property
    def constraints(self) -> tuple[UnevaluatedConstraint, ...]:
        return tuple(
            constraint
            for constraint in (self.unevaluated_properties, self.unevaluated_items)
            if constraint is not None
        )


@dataclass(frozen=True)
class EvaluationExpressionOrigin:
    kind: EvaluationOriginKind
    source_resource_uri: str = ""
    source_pointer: tuple[str, ...] = ()
    source_resource_pointer: tuple[str, ...] = ()
    target_resource_uri: str = ""
    target_pointer: tuple[str, ...] = ()
    target_document_pointer: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationExpression:
    property_sources: tuple[EvaluatedPropertySource, ...] = ()
    item_sources: tuple[EvaluatedItemSource, ...] = ()
    unsupported_reason: str = ""
    resource_exhausted_reason: str = ""
    origins: tuple[EvaluationExpressionOrigin, ...] = ()

    @property
    def is_supported(self) -> bool:
        return not self.unsupported_reason and not self.resource_exhausted_reason

    @property
    def is_resource_exhausted(self) -> bool:
        return bool(self.resource_exhausted_reason)

    @classmethod
    def unsupported(cls, reason: str) -> EvaluationExpression:
        return cls(unsupported_reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> EvaluationExpression:
        return cls(resource_exhausted_reason=reason)

    @classmethod
    def from_frontier(
        cls,
        frontier: EvaluationFrontier,
        *,
        origin: EvaluationExpressionOrigin | None = None,
    ) -> EvaluationExpression:
        origins = (origin,) if origin is not None and frontier.has_local_sources else ()
        return cls(
            property_sources=frontier.property_sources,
            item_sources=frontier.item_sources,
            origins=origins,
        )

    def merge(self, other: EvaluationExpression) -> EvaluationExpression:
        if not self.is_supported:
            return self
        if not other.is_supported:
            return other
        return EvaluationExpression(
            property_sources=self.property_sources + other.property_sources,
            item_sources=self.item_sources + other.item_sources,
            origins=self.origins + other.origins,
        )

    def with_origin(self, origin: EvaluationExpressionOrigin) -> EvaluationExpression:
        if self.is_supported and not self.property_sources and not self.item_sources:
            return self
        return EvaluationExpression(
            property_sources=self.property_sources,
            item_sources=self.item_sources,
            unsupported_reason=self.unsupported_reason,
            resource_exhausted_reason=self.resource_exhausted_reason,
            origins=(origin,) + self.origins,
        )


@dataclass(frozen=True)
class EvaluationTracePath:
    property_sources: tuple[EvaluatedPropertySource, ...] = ()
    item_sources: tuple[EvaluatedItemSource, ...] = ()
    origins: tuple[EvaluationExpressionOrigin, ...] = ()
    condition: str = "always"


@dataclass(frozen=True)
class EvaluationTraceExpression:
    paths: tuple[EvaluationTracePath, ...] = ()
    unsupported_reason: str = ""
    resource_exhausted_reason: str = ""

    @property
    def is_supported(self) -> bool:
        return not self.unsupported_reason and not self.resource_exhausted_reason

    @property
    def is_resource_exhausted(self) -> bool:
        return bool(self.resource_exhausted_reason)

    @property
    def evaluated_property_sources(self) -> tuple[EvaluatedPropertySource, ...]:
        return tuple(source for path in self.paths for source in path.property_sources)

    @property
    def evaluated_item_sources(self) -> tuple[EvaluatedItemSource, ...]:
        return tuple(source for path in self.paths for source in path.item_sources)

    @property
    def origins(self) -> tuple[EvaluationExpressionOrigin, ...]:
        return tuple(origin for path in self.paths for origin in path.origins)

    def has_effects(self) -> bool:
        return any(path.property_sources or path.item_sources for path in self.paths)

    @classmethod
    def from_expression(
        cls, expression: EvaluationExpression
    ) -> EvaluationTraceExpression:
        if expression.is_resource_exhausted:
            return cls(resource_exhausted_reason=expression.resource_exhausted_reason)
        if not expression.is_supported:
            return cls(unsupported_reason=expression.unsupported_reason)
        if not expression.property_sources and not expression.item_sources:
            return cls()
        return cls(
            (
                EvaluationTracePath(
                    expression.property_sources,
                    expression.item_sources,
                    expression.origins,
                ),
            )
        )

    def to_expression(self) -> EvaluationExpression:
        if self.is_resource_exhausted:
            return EvaluationExpression.resource_exhausted(
                self.resource_exhausted_reason
            )
        if not self.is_supported:
            return EvaluationExpression.unsupported(self.unsupported_reason)
        expression = EvaluationExpression()
        for path in self.paths:
            expression = expression.merge(
                EvaluationExpression(
                    property_sources=path.property_sources,
                    item_sources=path.item_sources,
                    origins=path.origins,
                )
            )
        return expression


def evaluation_expression_for_source(
    source: Any,
    graph: Any,
    *,
    lhs_schema: Any = None,
    context: ProofContext | None = None,
) -> EvaluationExpression:
    if context is not None:
        cache_key = _evaluation_expression_cache_key(source, lhs_schema, context)
        cached = _cached_evaluation_expression(context, cache_key)
        if cached is not None:
            return cached
    else:
        cache_key = None

    expression = _evaluation_expression_for_source(
        source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=frozenset(),
    )
    if context is not None and cache_key is not None:
        _cache_evaluation_expression(context, cache_key, expression)
    return expression


def evaluation_trace_for_source(
    source: Any,
    graph: Any,
    *,
    lhs_schema: Any = None,
    context: ProofContext | None = None,
) -> EvaluationTraceExpression:
    return EvaluationTraceExpression.from_expression(
        evaluation_expression_for_source(
            source,
            graph,
            lhs_schema=lhs_schema,
            context=context,
        )
    )


def _evaluation_expression_for_source(
    source: Any,
    graph: Any,
    *,
    lhs_schema: Any,
    context: ProofContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression:
    schema = source.schema
    frontier = evaluation_frontier_for_schema(schema, source.dialect)
    expression = EvaluationExpression.from_frontier(
        frontier, origin=_source_origin("local", source)
    )
    if not isinstance(schema, dict):
        return expression

    dynamic_reference_expression = _dynamic_reference_expression(
        source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=seen,
    )
    if dynamic_reference_expression is not None:
        return expression.merge(dynamic_reference_expression)
    if "$recursiveRef" in schema:
        return EvaluationExpression.unsupported(
            "evaluation expression does not support $recursiveRef recursive effects"
        )

    reference_expression = _static_reference_expression(
        source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=seen,
    )
    if reference_expression is not None:
        return expression.merge(reference_expression)

    all_of = schema.get("allOf", [])
    if isinstance(all_of, list):
        for index, subschema in enumerate(all_of):
            child_source = graph.schema_ir_for_pointer(
                source.pointer + ("allOf", str(index)), subschema
            )
            expression = expression.merge(
                _evaluation_expression_for_source(
                    child_source,
                    graph,
                    lhs_schema=lhs_schema,
                    context=context,
                    seen=seen,
                ).with_origin(_source_origin("allOf", child_source))
            )
            if not expression.is_supported:
                return expression
    branch_expression = _branch_applicator_expression(
        source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=seen,
    )
    if branch_expression is not None:
        return expression.merge(branch_expression)
    return expression


def _static_reference_expression(
    source: Any,
    graph: Any,
    *,
    lhs_schema: Any,
    context: ProofContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    from subschema.kernel.references import (
        StaticReferenceUnsupported,
        static_reference_resolution_for_schema,
    )

    resolution = static_reference_resolution_for_schema(
        source.schema,
        graph,
        source_resource_uri=source.resource_uri,
        source_pointer=source.pointer,
        source_resource_pointer=source.resource_pointer,
        source_dialect=source.dialect,
        side="rhs",
    )
    if resolution is None:
        return None
    if isinstance(resolution, StaticReferenceUnsupported):
        return EvaluationExpression.unsupported(resolution.reason)

    location = (resolution.resource_uri, resolution.pointer)
    if location in seen:
        return EvaluationExpression.unsupported(
            f"evaluation expression does not support recursive static $ref {
                resolution.ref!r
            }"
        )
    target_source = replace(
        graph.schema_ir_for_pointer(resolution.document_pointer, resolution.schema),
        dialect=resolution.dialect,
    )
    return _evaluation_expression_for_source(
        target_source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=seen | {location},
    ).with_origin(
        EvaluationExpressionOrigin(
            "static-ref",
            source_resource_uri=source.resource_uri,
            source_pointer=source.pointer,
            source_resource_pointer=source.resource_pointer,
            target_resource_uri=resolution.resource_uri,
            target_pointer=resolution.pointer,
            target_document_pointer=resolution.document_pointer,
        )
    )


def _dynamic_reference_expression(
    source: Any,
    graph: Any,
    *,
    lhs_schema: Any,
    context: ProofContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    from subschema.kernel.references import (
        DynamicReferenceUnsupported,
        DynamicScope,
        dynamic_reference_resolution_for_schema,
    )

    source_frame = graph.reference_frame_for_pointer(source.pointer)
    resolution = dynamic_reference_resolution_for_schema(
        source.schema,
        graph,
        source_frame=source_frame,
        dynamic_scope=DynamicScope().push(source_frame),
        side="rhs",
    )
    if resolution is None:
        return None
    if isinstance(resolution, DynamicReferenceUnsupported):
        return EvaluationExpression.unsupported(resolution.reason)

    location = (resolution.resource_uri, resolution.pointer)
    if location in seen:
        return EvaluationExpression.unsupported(
            f"evaluation expression does not support recursive $dynamicRef {
                resolution.ref!r
            }"
        )
    target_source = replace(
        graph.schema_ir_for_pointer(resolution.document_pointer, resolution.schema),
        dialect=resolution.dialect,
    )
    return _evaluation_expression_for_source(
        target_source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=seen | {location},
    ).with_origin(
        EvaluationExpressionOrigin(
            "dynamic-ref",
            source_resource_uri=source.resource_uri,
            source_pointer=source.pointer,
            source_resource_pointer=source.resource_pointer,
            target_resource_uri=resolution.resource_uri,
            target_pointer=resolution.pointer,
            target_document_pointer=resolution.document_pointer,
        )
    )


def _branch_applicator_expression(
    source: Any,
    graph: Any,
    *,
    lhs_schema: Any,
    context: ProofContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    schema = source.schema
    for keyword in ("anyOf", "oneOf"):
        subschemas = schema.get(keyword)
        if not isinstance(subschemas, list):
            continue
        branch = _branch_collection_expression(
            source,
            graph,
            keyword,
            subschemas,
            lhs_schema=lhs_schema,
            context=context,
            seen=seen,
        )
        if branch is not None:
            return branch

    conditional = _conditional_expression(
        source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=seen,
    )
    if conditional is not None:
        return conditional
    not_expression = _not_expression(
        source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=seen,
    )
    if not_expression is not None:
        return not_expression
    return None


def _branch_collection_expression(
    source: Any,
    graph: Any,
    keyword: Literal["anyOf", "oneOf"],
    subschemas: list[Any],
    *,
    lhs_schema: Any,
    context: ProofContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    merged = EvaluationExpression()
    saw_effects = False
    for index, subschema in enumerate(subschemas):
        child_source = graph.schema_ir_for_pointer(
            source.pointer + (keyword, str(index)), subschema
        )
        child_expression = _evaluation_expression_for_source(
            child_source,
            graph,
            lhs_schema=lhs_schema,
            context=context,
            seen=seen,
        )
        child_has_effects = bool(
            child_expression.property_sources or child_expression.item_sources
        )
        saw_effects = (
            saw_effects or child_has_effects or not child_expression.is_supported
        )
        if context is None or lhs_schema is None:
            continue

        branch_proof = context.subproof(lhs_schema, subschema)
        if branch_proof.status == "resource_exhausted":
            return EvaluationExpression.resource_exhausted(
                branch_proof.reason
                or f"evaluation expression {keyword} branch proof exhausted its budget"
            ).with_origin(_source_origin(keyword, child_source))
        if branch_proof.status != "proved_true":
            continue
        if keyword == "oneOf":
            uniqueness = _branch_uniqueness_proof(
                subschema,
                tuple(
                    other
                    for other_index, other in enumerate(subschemas)
                    if other_index != index
                ),
                source.dialect,
                context,
            )
            if uniqueness.status == "resource_exhausted":
                return EvaluationExpression.resource_exhausted(
                    uniqueness.reason
                    or (
                        "evaluation expression oneOf disjointness proof exhausted its "
                        "budget"
                    )
                ).with_origin(_source_origin(keyword, child_source))
            if uniqueness.status != "proved_true":
                continue
        if not child_expression.is_supported:
            return child_expression
        merged = merged.merge(
            child_expression.with_origin(_source_origin(keyword, child_source))
        )

    if merged.property_sources or merged.item_sources:
        return merged
    if saw_effects:
        return EvaluationExpression.unsupported(
            f"evaluation expression defers branch-aware {keyword} effects"
        )
    return None


def _branch_uniqueness_proof(
    branch: Any,
    others: tuple[Any, ...],
    dialect: Dialect,
    context: ProofContext,
) -> Any:
    from subschema.kernel.disjointness import schemas_are_disjoint

    for other in others:
        proof = schemas_are_disjoint(branch, other, context)
        if proof.status != "proved_true":
            return proof
    from subschema.kernel.contracts import ProofResult

    return ProofResult.true()


def _conditional_expression(
    source: Any,
    graph: Any,
    *,
    lhs_schema: Any,
    context: ProofContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    schema = source.schema
    if_schema = schema.get("if")
    if if_schema is None:
        return None

    then_expression = _conditional_branch_expression(
        source,
        graph,
        "then",
        lhs_schema=lhs_schema,
        context=context,
        seen=seen,
    )
    else_expression = _conditional_branch_expression(
        source,
        graph,
        "else",
        lhs_schema=lhs_schema,
        context=context,
        seen=seen,
    )
    if then_expression is None and else_expression is None:
        return None
    if not _expression_has_effects_or_unsupported(
        then_expression
    ) and not _expression_has_effects_or_unsupported(else_expression):
        return None
    if context is None or lhs_schema is None:
        return EvaluationExpression.unsupported(
            "evaluation expression defers branch-aware conditional effects"
        )

    condition_proof = context.subproof(lhs_schema, if_schema)
    if condition_proof.status == "resource_exhausted":
        return EvaluationExpression.resource_exhausted(
            condition_proof.reason
            or "evaluation expression conditional proof exhausted its budget"
        ).with_origin(_source_origin("conditional", source))
    if condition_proof.status == "proved_true":
        return (then_expression or EvaluationExpression()).with_origin(
            _source_origin("conditional", source)
        )
    disjoint = _schemas_disjoint_proof(lhs_schema, if_schema, context)
    if disjoint.status == "resource_exhausted":
        return EvaluationExpression.resource_exhausted(
            disjoint.reason
            or (
                "evaluation expression conditional disjointness proof "
                "exhausted its budget"
            )
        ).with_origin(_source_origin("conditional", source))
    if disjoint.status == "proved_true":
        return (else_expression or EvaluationExpression()).with_origin(
            _source_origin("conditional", source)
        )
    return EvaluationExpression.unsupported(
        "evaluation expression cannot prove the successful conditional branch"
    )


def _conditional_branch_expression(
    source: Any,
    graph: Any,
    keyword: str,
    *,
    lhs_schema: Any,
    context: ProofContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    subschema = source.schema.get(keyword)
    if subschema is None:
        return None
    child_source = graph.schema_ir_for_pointer(source.pointer + (keyword,), subschema)
    child_expression = _evaluation_expression_for_source(
        child_source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=seen,
    )
    if not child_expression.is_supported:
        return child_expression
    if child_expression.property_sources or child_expression.item_sources:
        return child_expression
    return EvaluationExpression()


def _expression_has_effects_or_unsupported(
    expression: EvaluationExpression | None,
) -> bool:
    return expression is not None and (
        not expression.is_supported
        or bool(expression.property_sources or expression.item_sources)
    )


def _not_expression(
    source: Any,
    graph: Any,
    *,
    lhs_schema: Any,
    context: ProofContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    subschema = source.schema.get("not")
    if subschema is None:
        return None
    child_source = graph.schema_ir_for_pointer(source.pointer + ("not",), subschema)
    child_expression = _evaluation_expression_for_source(
        child_source,
        graph,
        lhs_schema=lhs_schema,
        context=context,
        seen=seen,
    )
    if not child_expression.is_supported:
        return child_expression
    if child_expression.property_sources or child_expression.item_sources:
        return EvaluationExpression.unsupported(
            "evaluation expression defers branch-aware not effects"
        ).with_origin(_source_origin("not", child_source))
    return None


def _schemas_disjoint_proof(
    lhs: Any,
    rhs: Any,
    context: ProofContext,
) -> Any:
    from subschema.kernel.disjointness import schemas_are_disjoint

    return schemas_are_disjoint(lhs, rhs, context)


def _source_origin(
    kind: EvaluationOriginKind, source: Any
) -> EvaluationExpressionOrigin:
    return EvaluationExpressionOrigin(
        kind,
        source_resource_uri=source.resource_uri,
        source_pointer=source.pointer,
        source_resource_pointer=source.resource_pointer,
    )


def _evaluation_expression_cache_key(
    source: Any, lhs_schema: Any, context: ProofContext
) -> tuple[Any, ...]:
    return (
        source.resource_uri,
        source.document_pointer,
        source.resource_pointer,
        stable_key(lhs_schema),
        context.options.endeavor,
        context.options.budgets.max_work,
        context.options.budgets.timeout_ms,
    )


def _cached_evaluation_expression(
    context: ProofContext, cache_key: tuple[Any, ...]
) -> EvaluationExpression | None:
    cached = context.cache_get("evaluation-expression", cache_key)
    return cached if isinstance(cached, EvaluationExpression) else None


def _cache_evaluation_expression(
    context: ProofContext,
    cache_key: tuple[Any, ...],
    expression: EvaluationExpression,
) -> None:
    context.cache_set("evaluation-expression", cache_key, expression)


def evaluation_frontier_for_schema(schema: Any, dialect: Dialect) -> EvaluationFrontier:
    if not isinstance(schema, dict):
        return EvaluationFrontier()

    return EvaluationFrontier(
        property_sources=_property_sources_for_schema(schema),
        item_sources=_item_sources_for_schema(schema, dialect),
        unevaluated_properties=_unevaluated_constraint(schema, "unevaluatedProperties"),
        unevaluated_items=_unevaluated_constraint(schema, "unevaluatedItems"),
    )


def _property_sources_for_schema(
    schema: dict[str, Any],
) -> tuple[EvaluatedPropertySource, ...]:
    sources: list[EvaluatedPropertySource] = []

    properties = schema.get("properties")
    if isinstance(properties, dict):
        sources.extend(
            EvaluatedPropertySource(
                "properties", key=str(property_name), schema=subschema
            )
            for property_name, subschema in sorted(properties.items())
        )

    pattern_properties = schema.get("patternProperties")
    if isinstance(pattern_properties, dict):
        sources.extend(
            EvaluatedPropertySource(
                "patternProperties", key=str(pattern), schema=subschema
            )
            for pattern, subschema in sorted(pattern_properties.items())
        )

    if "additionalProperties" in schema:
        sources.append(
            EvaluatedPropertySource(
                "additionalProperties", schema=schema["additionalProperties"]
            )
        )

    dependencies = schema.get("dependencies")
    if isinstance(dependencies, dict):
        sources.extend(
            EvaluatedPropertySource(
                "dependencies", key=str(property_name), schema=dependency
            )
            for property_name, dependency in sorted(dependencies.items())
            if isinstance(dependency, dict)
        )

    dependent_schemas = schema.get("dependentSchemas")
    if isinstance(dependent_schemas, dict):
        sources.extend(
            EvaluatedPropertySource(
                "dependentSchemas", key=str(property_name), schema=subschema
            )
            for property_name, subschema in sorted(dependent_schemas.items())
        )

    return tuple(sources)


def _item_sources_for_schema(
    schema: dict[str, Any], dialect: Dialect
) -> tuple[EvaluatedItemSource, ...]:
    sources: list[EvaluatedItemSource] = []

    if dialect is Dialect.DRAFT202012:
        prefix_items = schema.get("prefixItems")
        prefix_count = 0
        if isinstance(prefix_items, list):
            prefix_count = len(prefix_items)
            sources.extend(
                EvaluatedItemSource("prefixItems", index=index, schema=subschema)
                for index, subschema in enumerate(prefix_items)
            )

        if "items" in schema and not isinstance(schema["items"], list):
            sources.append(
                EvaluatedItemSource(
                    "items", start_index=prefix_count, schema=schema["items"]
                )
            )
    else:
        items = schema.get("items")
        tuple_count = 0
        if isinstance(items, list):
            tuple_count = len(items)
            sources.extend(
                EvaluatedItemSource("items", index=index, schema=subschema)
                for index, subschema in enumerate(items)
            )
        elif "items" in schema:
            sources.append(EvaluatedItemSource("items", start_index=0, schema=items))

        if "additionalItems" in schema:
            sources.append(
                EvaluatedItemSource(
                    "additionalItems",
                    start_index=tuple_count,
                    schema=schema["additionalItems"],
                )
            )

    if "contains" in schema:
        sources.append(
            EvaluatedItemSource(
                "contains",
                schema=schema["contains"],
                marks_contains_matches=dialect is Dialect.DRAFT202012,
            )
        )

    return tuple(sources)


def _unevaluated_constraint(
    schema: dict[str, Any], keyword: UnevaluatedKeyword
) -> UnevaluatedConstraint | None:
    if keyword not in schema:
        return None
    return UnevaluatedConstraint(keyword, schema[keyword])
