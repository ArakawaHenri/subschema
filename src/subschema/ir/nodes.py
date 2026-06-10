"""
Typed schema IR nodes and document views.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from subschema.contracts import UnsupportedCategory
from subschema.dialects import Dialect
from subschema.ir.evaluation import EvaluationFrontier
from subschema.ir.semantics import SchemaSemantics
from subschema.ir.terms import SchemaNodeRef, SchemaTerm
from subschema.provenance import SchemaSource

ApplicatorKind = Literal["allOf", "anyOf", "else", "if", "not", "oneOf", "then"]

__all__ = [
    "ApplicatorKind",
    "ApplicatorNode",
    "LogicalSchemaIR",
    "SchemaDocumentIR",
    "SchemaNode",
    "UnsupportedNode",
]


@dataclass(frozen=True)
class ApplicatorNode:
    kind: ApplicatorKind
    children: tuple[SchemaNode, ...]
    base_term: SchemaTerm = field(default_factory=SchemaTerm.true)
    base_semantic_keywords: frozenset[str] = frozenset()


@dataclass(frozen=True)
class UnsupportedNode:
    keyword: str
    reason: str
    path: tuple[str, ...] = ()
    category: UnsupportedCategory = "semantic-keyword"

    @property
    def pointer(self) -> str:
        if not self.path:
            return "#"
        return "#/" + "/".join(
            _escape_pointer_segment(segment) for segment in self.path
        )


@dataclass(frozen=True)
class SchemaNode:
    ref: SchemaNodeRef
    source: SchemaSource
    semantics: SchemaSemantics
    boolean_value: bool | None = None
    evaluation: EvaluationFrontier = field(default_factory=EvaluationFrontier)
    applicators: tuple[ApplicatorNode, ...] = ()
    unsupported: tuple[UnsupportedNode, ...] = ()

    @property
    def all_unsupported(self) -> tuple[UnsupportedNode, ...]:
        return self.unsupported + tuple(
            unsupported
            for applicator in self.applicators
            for child in applicator.children
            for unsupported in child.all_unsupported
        )


@dataclass(frozen=True)
class SchemaDocumentIR:
    source: SchemaSource
    root_ref: SchemaNodeRef
    nodes: Mapping[SchemaNodeRef, SchemaNode] = field(default_factory=dict)

    @property
    def root(self) -> SchemaNode:
        root = self.node_for_ref(self.root_ref)
        if root is None:
            raise KeyError("schema document root ref is not registered")
        return root

    def node_for_ref(self, ref: SchemaNodeRef) -> SchemaNode | None:
        found = self.nodes.get(ref)
        if found is not None:
            return found
        return _find_node_for_ref(self.root, ref)


@dataclass(frozen=True)
class LogicalSchemaIR:
    document: SchemaDocumentIR
    root_ref: SchemaNodeRef

    @property
    def root(self) -> SchemaNode:
        root = self.node_for_ref(self.root_ref)
        if root is None:
            raise KeyError("schema IR root ref is not registered")
        return root

    @property
    def nodes(self) -> Mapping[SchemaNodeRef, SchemaNode]:
        return self.document.nodes

    @property
    def source(self) -> SchemaSource:
        return self.root.source

    @property
    def root_term(self) -> SchemaTerm:
        return SchemaTerm.node(self.root_ref)

    def term_for_node(self, node: SchemaNode) -> SchemaTerm:
        return SchemaTerm.node(node.ref)

    def node_for_ref(self, ref: SchemaNodeRef) -> SchemaNode | None:
        return self.document.node_for_ref(ref)

    def with_root(self, root: SchemaNode) -> LogicalSchemaIR:
        return self.with_root_ref(root.ref)

    def with_root_ref(self, ref: SchemaNodeRef) -> LogicalSchemaIR:
        if self.node_for_ref(ref) is None:
            raise KeyError("schema IR root ref is not registered")
        return LogicalSchemaIR(self.document, ref)

    @property
    def dialect(self) -> Dialect:
        return self.source.dialect

    @property
    def semantics(self) -> SchemaSemantics:
        return self.root.semantics


def _find_node_for_ref(node: SchemaNode, ref: SchemaNodeRef) -> SchemaNode | None:
    if node.ref == ref:
        return node
    for applicator in node.applicators:
        for child in applicator.children:
            found = _find_node_for_ref(child, ref)
            if found is not None:
                return found
    return None


def _escape_pointer_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")
