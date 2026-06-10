"""
Kernel-native schema terms used by proof services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SchemaTermKind = Literal["node", "true", "false", "all_of", "any_of", "one_of", "not"]
SchemaTermScope = Literal["lhs", "rhs"]


@dataclass(frozen=True)
class SchemaNodeRef:
    resource_uri: str
    document_pointer: tuple[str, ...]
    resource_pointer: tuple[str, ...]


@dataclass(frozen=True)
class SchemaTerm:
    kind: SchemaTermKind
    ref: SchemaNodeRef | None = None
    children: tuple[SchemaTerm, ...] = ()
    scope: SchemaTermScope | None = None

    @classmethod
    def node(
        cls,
        ref: SchemaNodeRef,
        *,
        scope: SchemaTermScope | None = None,
    ) -> SchemaTerm:
        return cls("node", ref=ref, scope=scope)

    @classmethod
    def true(cls) -> SchemaTerm:
        return cls("true")

    @classmethod
    def false(cls) -> SchemaTerm:
        return cls("false")

    @classmethod
    def all_of(cls, children: tuple[SchemaTerm, ...]) -> SchemaTerm:
        return _fold_composite("all_of", children)

    @classmethod
    def any_of(cls, children: tuple[SchemaTerm, ...]) -> SchemaTerm:
        return _fold_composite("any_of", children)

    @classmethod
    def one_of(cls, children: tuple[SchemaTerm, ...]) -> SchemaTerm:
        return _fold_composite("one_of", children)

    @classmethod
    def not_(cls, child: SchemaTerm) -> SchemaTerm:
        match child.kind:
            case "true":
                return cls.false()
            case "false":
                return cls.true()
            case _:
                return cls("not", children=(child,))

    def with_scope(self, scope: SchemaTermScope) -> SchemaTerm:
        match self.kind:
            case "node":
                if self.scope == scope:
                    return self
                return SchemaTerm.node(_expect_ref(self.ref), scope=scope)
            case "true" | "false":
                return self
            case "all_of":
                return SchemaTerm.all_of(
                    tuple(child.with_scope(scope) for child in self.children)
                )
            case "any_of":
                return SchemaTerm.any_of(
                    tuple(child.with_scope(scope) for child in self.children)
                )
            case "one_of":
                return SchemaTerm.one_of(
                    tuple(child.with_scope(scope) for child in self.children)
                )
            case "not":
                if len(self.children) != 1:
                    return self
                return SchemaTerm.not_(self.children[0].with_scope(scope))


def _fold_composite(
    kind: Literal["all_of", "any_of", "one_of"],
    children: tuple[SchemaTerm, ...],
) -> SchemaTerm:
    children = _deduplicate_children(children)
    match (kind, children):
        case ("all_of", ()):
            return SchemaTerm.true()
        case ("any_of" | "one_of", ()):
            return SchemaTerm.false()
        case (_, (single,)):
            return single
        case _:
            return SchemaTerm(kind, children=children)


def _deduplicate_children(children: tuple[SchemaTerm, ...]) -> tuple[SchemaTerm, ...]:
    deduplicated: list[SchemaTerm] = []
    seen: set[SchemaTerm] = set()
    for child in children:
        if child in seen:
            continue
        seen.add(child)
        deduplicated.append(child)
    return tuple(deduplicated)


def _expect_ref(ref: SchemaNodeRef | None) -> SchemaNodeRef:
    if ref is None:
        raise ValueError("node schema term requires a ref")
    return ref
