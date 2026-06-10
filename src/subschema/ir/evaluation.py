"""
Evaluation-frontier IR for keywords that feed unevaluated* semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from subschema.ir.terms import SchemaTerm

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
]


@dataclass(frozen=True)
class EvaluatedPropertySource:
    kind: PropertyEvaluationKind
    key: str | None = None
    term: SchemaTerm = SchemaTerm.true()


@dataclass(frozen=True)
class EvaluatedItemSource:
    kind: ItemEvaluationKind
    index: int | None = None
    start_index: int | None = None
    term: SchemaTerm = SchemaTerm.true()
    marks_contains_matches: bool = False


@dataclass(frozen=True)
class UnevaluatedConstraint:
    keyword: UnevaluatedKeyword
    term: SchemaTerm

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
    unsupported_priority: int = 0
    resource_exhausted_reason: str = ""
    origins: tuple[EvaluationExpressionOrigin, ...] = ()

    @property
    def is_supported(self) -> bool:
        return not self.unsupported_reason and not self.resource_exhausted_reason

    @property
    def is_resource_exhausted(self) -> bool:
        return bool(self.resource_exhausted_reason)

    @classmethod
    def unsupported(
        cls, reason: str, *, unsupported_priority: int = 0
    ) -> EvaluationExpression:
        return cls(
            unsupported_reason=reason,
            unsupported_priority=unsupported_priority,
        )

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
            unsupported_priority=self.unsupported_priority,
            resource_exhausted_reason=self.resource_exhausted_reason,
            origins=(origin,) + self.origins,
        )


@dataclass(frozen=True)
class EvaluationTracePath:
    property_sources: tuple[EvaluatedPropertySource, ...] = ()
    item_sources: tuple[EvaluatedItemSource, ...] = ()
    origins: tuple[EvaluationExpressionOrigin, ...] = ()
    condition: SchemaTerm = field(default_factory=SchemaTerm.true)

    @property
    def is_unconditional(self) -> bool:
        return self.condition.kind == "true"


@dataclass(frozen=True)
class EvaluationTraceExpression:
    paths: tuple[EvaluationTracePath, ...] = ()
    unsupported_reason: str = ""
    unsupported_priority: int = 0
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

    @property
    def has_conditioned_paths(self) -> bool:
        return any(not path.is_unconditional for path in self.paths)

    def has_effects(self) -> bool:
        return any(path.property_sources or path.item_sources for path in self.paths)

    @classmethod
    def from_expression(
        cls,
        expression: EvaluationExpression,
        *,
        condition: SchemaTerm | None = None,
    ) -> EvaluationTraceExpression:
        if expression.is_resource_exhausted:
            return cls(resource_exhausted_reason=expression.resource_exhausted_reason)
        if not expression.is_supported:
            return cls(
                unsupported_reason=expression.unsupported_reason,
                unsupported_priority=expression.unsupported_priority,
            )
        if not expression.property_sources and not expression.item_sources:
            return cls()
        return cls(
            (
                EvaluationTracePath(
                    expression.property_sources,
                    expression.item_sources,
                    expression.origins,
                    SchemaTerm.true() if condition is None else condition,
                ),
            )
        )

    def to_expression(self) -> EvaluationExpression:
        if self.is_resource_exhausted:
            return EvaluationExpression.resource_exhausted(
                self.resource_exhausted_reason
            )
        if not self.is_supported:
            return EvaluationExpression.unsupported(
                self.unsupported_reason,
                unsupported_priority=self.unsupported_priority,
            )
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
