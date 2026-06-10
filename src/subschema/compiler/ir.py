"""
Compiler from raw JSON Schema syntax into typed semantic IR.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from subschema.compiler.evaluation import evaluation_frontier_for_schema
from subschema.compiler.resources import (
    DynamicReferenceUnsupported,
    DynamicScope,
    ReferenceResolution,
    ResourceGraph,
    StaticReferenceUnsupported,
    dynamic_reference_resolution_for_schema,
    recursive_guard_kind_for_path,
    recursive_reference_polarity_for_path,
    static_reference_resolution_for_schema,
)
from subschema.compiler.resources import SchemaIR as ResourceSchemaIR
from subschema.compiler.schemas import (
    schema_semantic_key_set,
    schema_without_keyword,
    schema_without_keywords,
)
from subschema.compiler.semantics import (
    build_schema_semantics,
    compile_schema_unsupported_nodes,
)
from subschema.dialects import Dialect
from subschema.ir import (
    ApplicatorKind,
    ApplicatorNode,
    DynamicReferenceSemantics,
    LogicalSchemaIR,
    RecursiveReferenceFact,
    RecursiveReferenceGuard,
    RecursiveReferencePolarity,
    ReferenceUnsupportedFact,
    SchemaDocumentIR,
    SchemaNode,
    SchemaNodeRef,
    SchemaSemantics,
    StaticReferenceSemantics,
)
from subschema.ir.evaluation import EvaluationFrontier
from subschema.ir.terms import SchemaTerm
from subschema.values import stable_key


class SchemaIRCompiler:
    def __init__(self, dialect: Dialect):
        self.dialect = dialect
        self._nodes: dict[SchemaNodeRef, SchemaNode] = {}
        self._synthetic_terms: dict[tuple[object, ...], SchemaTerm] = {}

    def compile(
        self,
        schema: Any,
        *,
        resources: Mapping[str, Any] | None = None,
    ) -> LogicalSchemaIR:
        return self.compile_graph(
            ResourceGraph.build(schema, dialect=self.dialect, resources=resources)
        )

    def compile_graph(self, graph: ResourceGraph) -> LogicalSchemaIR:
        self._nodes = {}
        self._synthetic_terms = {}
        root = self._compile_node(graph.to_ir(), graph, depth=0, path=())
        document = SchemaDocumentIR(root.source, root.ref, dict(self._nodes))
        return LogicalSchemaIR(document, root.ref)

    def _compile_node(
        self,
        source: ResourceSchemaIR,
        graph: ResourceGraph,
        *,
        depth: int,
        path: tuple[str, ...],
        ref_prefix: tuple[str, ...] = (),
    ) -> SchemaNode:
        ref = _node_ref_for_source(source, ref_prefix=ref_prefix)
        existing = self._nodes.get(ref)
        if existing is not None:
            return existing

        schema = source.schema
        evaluation = self._compile_evaluation(
            schema,
            source.dialect,
            graph=graph,
            depth=depth,
            path=path,
            ref_prefix=ref_prefix,
        )
        semantics = self._compile_semantics(
            source,
            graph,
            evaluation,
            depth=depth,
            path=path,
            ref_prefix=ref_prefix,
        )
        node = SchemaNode(
            ref=ref,
            source=source.to_source(),
            semantics=semantics,
            boolean_value=schema if isinstance(schema, bool) else None,
            evaluation=evaluation,
            applicators=self._compile_applicators(
                schema,
                graph,
                dialect=source.dialect,
                depth=depth,
                path=path,
                ref_prefix=ref_prefix,
            ),
            unsupported=compile_schema_unsupported_nodes(
                schema, evaluation, source.dialect, path
            ),
        )
        self._nodes[node.ref] = node
        self._compile_static_reference_target(
            schema,
            source,
            graph,
            depth=depth,
            ref_prefix=ref_prefix,
        )
        return node

    def _compile_static_reference_target(
        self,
        schema: Any,
        source: ResourceSchemaIR,
        graph: ResourceGraph,
        *,
        depth: int,
        ref_prefix: tuple[str, ...],
    ) -> None:
        if depth > 16 or not isinstance(schema, dict):
            return
        resolution = static_reference_resolution_for_schema(
            schema,
            graph,
            source_resource_uri=source.resource_uri,
            source_pointer=source.pointer,
            source_resource_pointer=source.resource_pointer,
            source_dialect=source.dialect,
            side="rhs",
        )
        if not isinstance(resolution, ReferenceResolution):
            return
        target_source = graph.schema_ir_for_pointer(
            resolution.document_pointer, resolution.schema
        )
        target_source = replace(target_source, dialect=resolution.dialect)
        target_ref = _node_ref_for_source(target_source, ref_prefix=ref_prefix)
        if target_ref in self._nodes:
            return
        self._compile_node(
            target_source,
            graph,
            depth=depth + 1,
            path=resolution.document_pointer,
            ref_prefix=ref_prefix,
        )

    def _compile_semantics(
        self,
        source: ResourceSchemaIR,
        graph: ResourceGraph,
        evaluation: EvaluationFrontier,
        *,
        depth: int,
        path: tuple[str, ...],
        ref_prefix: tuple[str, ...],
    ) -> SchemaSemantics:
        semantics = build_schema_semantics(
            source.schema,
            graph,
            source.dialect,
            evaluation,
            child_term=lambda schema, child_path: self._compile_child_term(
                schema,
                graph,
                depth=depth + 1,
                path=path + child_path,
                ref_prefix=ref_prefix,
            ),
            recursive_static_reference_child=lambda term, _child_path: (
                _term_contains_graph_resolved_recursive_static_reference(
                    term,
                    source,
                    graph,
                    ref_prefix=ref_prefix,
                )
            ),
            synthetic_term=lambda schema, synthetic_path: self._compile_synthetic_term(
                schema,
                graph,
                source.dialect,
                depth=depth + 1,
                path=path + synthetic_path,
                ref_prefix=ref_prefix,
            ),
        )
        conditional_base = self._compile_conditional_base(
            source.schema,
            graph,
            source.dialect,
            depth=depth,
            path=path,
            ref_prefix=ref_prefix,
        )
        if conditional_base is not None:
            base_term, base_keywords = conditional_base
            semantics = replace(
                semantics,
                applicator=replace(
                    semantics.applicator,
                    conditional_base_term=base_term,
                    conditional_base_semantic_keywords=base_keywords,
                ),
            )
        static_reference = self._compile_static_reference_semantics(
            source,
            graph,
            depth=depth,
            ref_prefix=ref_prefix,
        )
        dynamic_reference = self._compile_dynamic_reference_semantics(
            source,
            graph,
            depth=depth,
            ref_prefix=ref_prefix,
        )
        nested_recursive_static_references = _nested_recursive_static_reference_facts(
            source,
            graph,
            ref_prefix=ref_prefix,
        )
        if (
            static_reference == StaticReferenceSemantics()
            and dynamic_reference == DynamicReferenceSemantics()
            and not semantics.reference.recursive_references
            and not nested_recursive_static_references
        ):
            return semantics
        recursive_references = _merge_recursive_reference_facts(
            semantics.reference.recursive_references,
            nested_recursive_static_references,
            _recursive_reference_fact_from_unsupported(
                static_reference.lhs_unsupported
            ),
            _recursive_reference_fact_from_unsupported(
                static_reference.rhs_unsupported
            ),
            _recursive_reference_fact_from_unsupported(
                dynamic_reference.lhs_unsupported
            ),
            _recursive_reference_fact_from_unsupported(
                dynamic_reference.rhs_unsupported
            ),
        )
        return replace(
            semantics,
            reference=replace(
                semantics.reference,
                has_non_recursive_static_reference_boundary=(
                    _has_non_recursive_static_reference_boundary(
                        semantics.reference.static_reference_paths,
                        recursive_references,
                    )
                ),
                has_recursive_reference=(
                    semantics.reference.has_recursive_reference
                    or bool(recursive_references)
                ),
                recursive_references=recursive_references,
                static_reference=static_reference,
                dynamic_reference=dynamic_reference,
            ),
        )

    def _compile_static_reference_semantics(
        self,
        source: ResourceSchemaIR,
        graph: ResourceGraph,
        *,
        depth: int,
        ref_prefix: tuple[str, ...],
    ) -> StaticReferenceSemantics:
        ref = _static_reference_value(source.schema)
        lhs_resolution = static_reference_resolution_for_schema(
            source.schema,
            graph,
            source_resource_uri=source.resource_uri,
            source_pointer=source.pointer,
            source_resource_pointer=source.resource_pointer,
            source_dialect=source.dialect,
            side="lhs",
        )
        if isinstance(lhs_resolution, ReferenceResolution):
            target_source = _source_for_reference_resolution(lhs_resolution, graph)
            target_ref = _node_ref_for_source(target_source, ref_prefix=ref_prefix)
            if target_ref not in self._nodes and depth <= 16:
                self._compile_node(
                    target_source,
                    graph,
                    depth=depth + 1,
                    path=lhs_resolution.document_pointer,
                    ref_prefix=ref_prefix,
                )
            return StaticReferenceSemantics(ref=ref, target=SchemaTerm.node(target_ref))
        if not isinstance(lhs_resolution, StaticReferenceUnsupported):
            return StaticReferenceSemantics(ref=ref)

        rhs_resolution = static_reference_resolution_for_schema(
            source.schema,
            graph,
            source_resource_uri=source.resource_uri,
            source_pointer=source.pointer,
            source_resource_pointer=source.resource_pointer,
            source_dialect=source.dialect,
            side="rhs",
        )
        rhs_unsupported = (
            rhs_resolution
            if isinstance(rhs_resolution, StaticReferenceUnsupported)
            else lhs_resolution
        )
        target = self._compile_unsupported_static_reference_target(
            lhs_resolution,
            graph,
            depth=depth,
            ref_prefix=ref_prefix,
        ) or self._compile_unsupported_static_reference_target(
            rhs_unsupported,
            graph,
            depth=depth,
            ref_prefix=ref_prefix,
        )
        return StaticReferenceSemantics(
            ref=ref,
            target=target,
            lhs_unsupported=_reference_unsupported_fact(lhs_resolution),
            rhs_unsupported=_reference_unsupported_fact(rhs_unsupported),
        )

    def _compile_unsupported_static_reference_target(
        self,
        unsupported: StaticReferenceUnsupported,
        graph: ResourceGraph,
        *,
        depth: int,
        ref_prefix: tuple[str, ...],
    ) -> SchemaTerm | None:
        if unsupported.target is None:
            return None
        target_source = _source_for_reference_resolution(unsupported.target, graph)
        target_ref = _node_ref_for_source(target_source, ref_prefix=ref_prefix)
        if target_ref not in self._nodes and depth <= 16:
            self._compile_node(
                target_source,
                graph,
                depth=depth + 1,
                path=unsupported.target.document_pointer,
                ref_prefix=ref_prefix,
            )
        return SchemaTerm.node(target_ref)

    def _compile_dynamic_reference_semantics(
        self,
        source: ResourceSchemaIR,
        graph: ResourceGraph,
        *,
        depth: int,
        ref_prefix: tuple[str, ...],
    ) -> DynamicReferenceSemantics:
        source_frame = graph.reference_frame_for_pointer(source.pointer)
        lhs_resolution = dynamic_reference_resolution_for_schema(
            source.schema,
            graph,
            source_frame=source_frame,
            dynamic_scope=DynamicScope().push(source_frame),
            side="lhs",
        )
        if isinstance(lhs_resolution, ReferenceResolution):
            target_source = _source_for_reference_resolution(lhs_resolution, graph)
            target_ref = _node_ref_for_source(target_source, ref_prefix=ref_prefix)
            if target_ref not in self._nodes and depth <= 16:
                self._compile_node(
                    target_source,
                    graph,
                    depth=depth + 1,
                    path=lhs_resolution.document_pointer,
                    ref_prefix=ref_prefix,
                )
            return DynamicReferenceSemantics(target=SchemaTerm.node(target_ref))
        if not isinstance(lhs_resolution, DynamicReferenceUnsupported):
            return DynamicReferenceSemantics()

        rhs_resolution = dynamic_reference_resolution_for_schema(
            source.schema,
            graph,
            source_frame=source_frame,
            dynamic_scope=DynamicScope().push(source_frame),
            side="rhs",
        )
        rhs_unsupported = (
            rhs_resolution
            if isinstance(rhs_resolution, DynamicReferenceUnsupported)
            else lhs_resolution
        )
        return DynamicReferenceSemantics(
            lhs_unsupported=_reference_unsupported_fact(lhs_resolution),
            rhs_unsupported=_reference_unsupported_fact(rhs_unsupported),
        )

    def _compile_evaluation(
        self,
        schema: Any,
        dialect: Dialect | None = None,
        *,
        graph: ResourceGraph,
        depth: int,
        path: tuple[str, ...],
        ref_prefix: tuple[str, ...],
    ) -> EvaluationFrontier:
        return evaluation_frontier_for_schema(
            schema,
            dialect or self.dialect,
            child_term=lambda child_schema, child_path: self._compile_child_term(
                child_schema,
                graph,
                depth=depth + 1,
                path=path + child_path,
                ref_prefix=ref_prefix,
            ),
        )

    def _compile_applicators(
        self,
        schema: Any,
        graph: ResourceGraph,
        *,
        dialect: Dialect,
        depth: int,
        path: tuple[str, ...],
        ref_prefix: tuple[str, ...],
    ) -> tuple[ApplicatorNode, ...]:
        if depth > 16 or not isinstance(schema, dict):
            return ()

        applicators: list[ApplicatorNode] = []
        schema_array_applicators: tuple[ApplicatorKind, ...] = (
            "allOf",
            "anyOf",
            "oneOf",
        )
        for keyword in schema_array_applicators:
            value = schema.get(keyword)
            if isinstance(value, list):
                base_term, base_keywords = self._compile_applicator_base(
                    schema,
                    keyword,
                    graph,
                    dialect,
                    depth=depth,
                    path=path,
                    ref_prefix=ref_prefix,
                )
                applicators.append(
                    ApplicatorNode(
                        keyword,
                        tuple(
                            self._compile_child(
                                subschema,
                                graph,
                                depth=depth + 1,
                                path=path + (keyword, str(index)),
                                ref_prefix=ref_prefix,
                            )
                            for index, subschema in enumerate(value)
                        ),
                        base_term,
                        base_keywords,
                    )
                )

        schema_value_applicators: tuple[ApplicatorKind, ...] = (
            "not",
            "if",
            "then",
            "else",
        )
        for keyword in schema_value_applicators:
            value = schema.get(keyword)
            if isinstance(value, bool | dict):
                base_term, base_keywords = self._compile_applicator_base(
                    schema,
                    keyword,
                    graph,
                    dialect,
                    depth=depth,
                    path=path,
                    ref_prefix=ref_prefix,
                )
                applicators.append(
                    ApplicatorNode(
                        keyword,
                        (
                            self._compile_child(
                                value,
                                graph,
                                depth=depth + 1,
                                path=path + (keyword,),
                                ref_prefix=ref_prefix,
                            ),
                        ),
                        base_term,
                        base_keywords,
                    )
                )
        return tuple(applicators)

    def _compile_applicator_base(
        self,
        schema: dict[str, Any],
        keyword: str,
        graph: ResourceGraph,
        dialect: Dialect,
        *,
        depth: int,
        path: tuple[str, ...],
        ref_prefix: tuple[str, ...],
    ) -> tuple[SchemaTerm, frozenset[str]]:
        base_schema = schema_without_keyword(schema, keyword)
        if base_schema is None:
            return SchemaTerm.true(), frozenset()
        return (
            self._compile_synthetic_term(
                base_schema,
                graph,
                dialect,
                depth=depth + 1,
                path=path + ("$base", keyword),
                ref_prefix=ref_prefix,
            ),
            schema_semantic_key_set(base_schema),
        )

    def _compile_conditional_base(
        self,
        schema: Any,
        graph: ResourceGraph,
        dialect: Dialect,
        *,
        depth: int,
        path: tuple[str, ...],
        ref_prefix: tuple[str, ...],
    ) -> tuple[SchemaTerm, frozenset[str]] | None:
        if not isinstance(schema, dict) or not (schema.keys() & {"else", "if", "then"}):
            return None
        base_schema = schema_without_keywords(schema, {"else", "if", "then"})
        if base_schema is None:
            return None
        return (
            self._compile_synthetic_term(
                base_schema,
                graph,
                dialect,
                depth=depth + 1,
                path=path + ("$base", "conditional"),
                ref_prefix=ref_prefix,
            ),
            schema_semantic_key_set(base_schema),
        )

    def _compile_child(
        self,
        schema: Any,
        graph: ResourceGraph,
        *,
        depth: int,
        path: tuple[str, ...],
        ref_prefix: tuple[str, ...],
    ) -> SchemaNode:
        return self._compile_node(
            graph.schema_ir_for_pointer(path, schema),
            graph,
            depth=depth,
            path=path,
            ref_prefix=ref_prefix,
        )

    def _compile_child_term(
        self,
        schema: Any,
        graph: ResourceGraph,
        *,
        depth: int,
        path: tuple[str, ...],
        ref_prefix: tuple[str, ...],
    ) -> SchemaTerm:
        if schema is True:
            return SchemaTerm.true()
        if schema is False:
            return SchemaTerm.false()
        child = self._compile_child(
            schema, graph, depth=depth, path=path, ref_prefix=ref_prefix
        )
        return SchemaTerm.node(child.ref)

    def _compile_synthetic_term(
        self,
        schema: Any,
        graph: ResourceGraph,
        dialect: Dialect,
        *,
        depth: int,
        path: tuple[str, ...],
        ref_prefix: tuple[str, ...],
    ) -> SchemaTerm:
        if schema is True:
            return SchemaTerm.true()
        if schema is False:
            return SchemaTerm.false()
        cache_key = _synthetic_term_cache_key(
            schema,
            graph,
            dialect,
            ref_prefix=ref_prefix,
        )
        if cache_key is not None:
            cached = self._synthetic_terms.get(cache_key)
            if cached is not None:
                return cached
        synthetic_graph = ResourceGraph.build(
            schema, dialect=dialect, resources=dict(graph.external_resources)
        )
        child = self._compile_node(
            synthetic_graph.to_ir(),
            synthetic_graph,
            depth=depth,
            path=(),
            ref_prefix=ref_prefix + path,
        )
        term = SchemaTerm.node(child.ref)
        if cache_key is not None:
            self._synthetic_terms[cache_key] = term
        return term


def _node_ref_for_source(
    source: ResourceSchemaIR,
    *,
    ref_prefix: tuple[str, ...] = (),
) -> SchemaNodeRef:
    return SchemaNodeRef(
        resource_uri=source.resource_uri,
        document_pointer=ref_prefix + source.document_pointer,
        resource_pointer=ref_prefix + source.resource_pointer,
    )


def _synthetic_term_cache_key(
    schema: Any,
    graph: ResourceGraph,
    dialect: Dialect,
    *,
    ref_prefix: tuple[str, ...],
) -> tuple[object, ...] | None:
    resources_key = _resources_cache_key(graph.external_resources)
    if resources_key is None:
        return None
    try:
        schema_key = stable_key(schema)
    except (TypeError, ValueError):
        return None
    return (
        "synthetic-term",
        dialect,
        ref_prefix,
        resources_key,
        schema_key,
    )


def _resources_cache_key(
    resources: tuple[tuple[str, Any], ...],
) -> tuple[tuple[str, str], ...] | None:
    items: list[tuple[str, str]] = []
    for uri, schema in resources:
        try:
            items.append((uri, stable_key(schema)))
        except (TypeError, ValueError):
            return None
    return tuple(items)


def _static_reference_value(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    return ref if isinstance(ref, str) else None


def _source_for_reference_resolution(
    resolution: ReferenceResolution,
    graph: ResourceGraph,
) -> ResourceSchemaIR:
    resource = _document_resource_for_reference_resolution(resolution, graph)
    document_root = graph.root if resource is None else resource.schema
    document_dialect = resolution.dialect if resource is None else resource.dialect
    return ResourceSchemaIR(
        resolution.schema,
        resolution.dialect,
        resource_uri=resolution.resource_uri,
        pointer=resolution.document_pointer,
        resource_pointer=resolution.pointer,
        document_pointer=resolution.document_pointer,
        document_root=document_root,
        document_dialect=document_dialect,
        resources=graph.external_resources,
    )


def _document_resource_for_reference_resolution(
    resolution: ReferenceResolution,
    graph: ResourceGraph,
) -> Any:
    source_resource = graph.resources.get(resolution.source_resource_uri)
    if source_resource is not None and _pointer_exists(
        source_resource.schema, resolution.document_pointer
    ):
        return source_resource
    return graph.resources.get(resolution.resource_uri)


def _pointer_exists(schema: Any, pointer: tuple[str, ...]) -> bool:
    current = schema
    for part in pointer:
        if isinstance(current, dict):
            if part not in current:
                return False
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return False
            if index < 0 or index >= len(current):
                return False
            current = current[index]
            continue
        return False
    return True


def _reference_unsupported_fact(
    unsupported: StaticReferenceUnsupported | DynamicReferenceUnsupported,
) -> ReferenceUnsupportedFact:
    return ReferenceUnsupportedFact(
        reason=unsupported.reason,
        path=unsupported.path,
        category=unsupported.category,
        keyword=unsupported.keyword,
        ref=unsupported.ref,
        guard_kind=_ir_recursive_guard_kind(unsupported.guard_kind),
        polarity=_ir_recursive_reference_polarity(unsupported.polarity),
    )


def _nested_recursive_static_reference_facts(
    source: ResourceSchemaIR,
    graph: ResourceGraph,
    *,
    ref_prefix: tuple[str, ...],
) -> tuple[RecursiveReferenceFact, ...]:
    return tuple(
        fact
        for path, ref in _static_reference_values(source.schema)
        if (
            fact := _nested_recursive_static_reference_fact(
                source,
                graph,
                path,
                ref,
                ref_prefix=ref_prefix,
            )
        )
        is not None
    )


def _term_contains_graph_resolved_recursive_static_reference(
    term: SchemaTerm,
    source: ResourceSchemaIR,
    graph: ResourceGraph,
    *,
    ref_prefix: tuple[str, ...],
) -> bool:
    if term.kind != "node" or term.ref is None:
        return False
    facts = _nested_recursive_static_reference_facts(
        source,
        graph,
        ref_prefix=ref_prefix,
    )
    return any(
        term.ref.resource_uri == source.resource_uri
        and term.ref.document_pointer
        == ref_prefix + source.document_pointer + fact.path[:-1]
        and term.ref.resource_pointer
        == ref_prefix + source.resource_pointer + fact.path[:-1]
        for fact in facts
    )


def _nested_recursive_static_reference_fact(
    source: ResourceSchemaIR,
    graph: ResourceGraph,
    path: tuple[str, ...],
    ref: str,
    *,
    ref_prefix: tuple[str, ...],
) -> RecursiveReferenceFact | None:
    resolution = graph.resolve_ref_info(
        ref,
        base_uri=source.resource_uri,
        source_pointer=source.pointer + path,
        source_resource_pointer=source.resource_pointer + path,
    )
    if resolution is None:
        return None
    if (
        resolution.resource_uri != source.resource_uri
        or resolution.pointer != source.resource_pointer
    ):
        return None
    target_source = _source_for_reference_resolution(resolution, graph)
    return RecursiveReferenceFact(
        keyword="$ref",
        path=path,
        ref=ref,
        guard_kind=_ir_recursive_guard_kind(
            recursive_guard_kind_for_path(path)
        )
        or "unguarded",
        polarity=_ir_recursive_reference_polarity(
            recursive_reference_polarity_for_path(path)
        ),
        target_ref=_node_ref_for_source(target_source, ref_prefix=ref_prefix),
    )


def _static_reference_values(
    schema: Any,
    path: tuple[str, ...] = (),
) -> tuple[tuple[tuple[str, ...], str], ...]:
    if isinstance(schema, list):
        return tuple(
            item
            for index, child in enumerate(schema)
            for item in _static_reference_values(child, path + (str(index),))
        )
    if not isinstance(schema, dict):
        return ()
    values: tuple[tuple[tuple[str, ...], str], ...] = ()
    ref = schema.get("$ref")
    if isinstance(ref, str):
        values = ((path + ("$ref",), ref),)
    return values + tuple(
        item
        for key, value in schema.items()
        if key != "$ref"
        for item in _static_reference_values(value, path + (str(key),))
    )


def _recursive_reference_fact_from_unsupported(
    fact: ReferenceUnsupportedFact | None,
) -> RecursiveReferenceFact | None:
    if fact is None or fact.category != "recursive-reference":
        return None
    return RecursiveReferenceFact(
        keyword=fact.keyword,
        path=fact.path,
        ref=fact.ref,
        guard_kind=fact.guard_kind or "unguarded",
        polarity=fact.polarity,
    )


def _merge_recursive_reference_facts(
    *facts: RecursiveReferenceFact | tuple[RecursiveReferenceFact, ...] | None,
) -> tuple[RecursiveReferenceFact, ...]:
    merged: dict[
        tuple[str, tuple[str, ...], str | None, RecursiveReferenceGuard, str],
        RecursiveReferenceFact,
    ] = {}
    for item in facts:
        if item is None:
            continue
        if isinstance(item, tuple):
            for fact in item:
                merged[
                    (fact.keyword, fact.path, fact.ref, fact.guard_kind, fact.polarity)
                ] = fact
            continue
        merged[(item.keyword, item.path, item.ref, item.guard_kind, item.polarity)] = (
            item
        )
    return tuple(merged.values())


def _has_non_recursive_static_reference_boundary(
    static_reference_paths: tuple[tuple[str, ...], ...],
    recursive_references: tuple[RecursiveReferenceFact, ...],
) -> bool:
    recursive_paths = frozenset(fact.path for fact in recursive_references)
    return any(path not in recursive_paths for path in static_reference_paths)


def _ir_recursive_guard_kind(value: str | None) -> RecursiveReferenceGuard | None:
    if value == "array":
        return "array"
    if value == "object":
        return "object"
    if value == "object/array":
        return "object/array"
    return None


def _ir_recursive_reference_polarity(value: str) -> RecursiveReferencePolarity:
    return "negative" if value == "negative" else "positive"
