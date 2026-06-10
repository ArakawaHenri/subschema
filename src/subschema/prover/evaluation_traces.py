"""
Evaluation trace resolution for branch-aware unevaluated* proofs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol, cast

from subschema.contracts import ProofResult
from subschema.dialects import Dialect
from subschema.ir import ApplicatorNode, LogicalSchemaIR, SchemaNode
from subschema.ir.evaluation import (
    EvaluationExpression,
    EvaluationExpressionOrigin,
    EvaluationOriginKind,
    EvaluationTraceExpression,
    EvaluationTracePath,
)
from subschema.ir.terms import SchemaTerm
from subschema.prover.disjointness import irs_are_disjoint


class EvaluationTraceContext(Protocol):
    dialect: Dialect
    resources: Mapping[str, Any]

    @property
    def proof_policy_identity(self) -> tuple[object, ...]: ...

    def subproof_terms(
        self,
        lhs: SchemaTerm,
        lhs_ir: LogicalSchemaIR,
        rhs: SchemaTerm,
        rhs_ir: LogicalSchemaIR,
    ) -> ProofResult: ...

    def cache_get(self, namespace: str, key: tuple[Any, ...]) -> object | None: ...
    def cache_set(
        self, namespace: str, key: tuple[Any, ...], value: object
    ) -> None: ...


def evaluation_expression_for_node(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm | None = None,
    lhs_ir: LogicalSchemaIR | None = None,
    context: EvaluationTraceContext | None = None,
) -> EvaluationExpression:
    if lhs_term is None and lhs_ir is not None:
        lhs_term = lhs_ir.root_term
    if context is not None:
        cache_key = _evaluation_expression_cache_key(node, ir, lhs_term, context)
        cached = _cached_evaluation_expression(context, cache_key)
        if cached is not None:
            return cached
    else:
        cache_key = None

    expression = _evaluation_expression_for_node(
        node,
        ir,
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=frozenset(),
    )
    if context is not None and cache_key is not None:
        _cache_evaluation_expression(context, cache_key, expression)
    return expression


def evaluation_trace_for_node(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm | None = None,
    lhs_ir: LogicalSchemaIR | None = None,
    context: EvaluationTraceContext | None = None,
) -> EvaluationTraceExpression:
    expression = evaluation_expression_for_node(
        node,
        ir,
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
    )
    if not expression.is_supported and not expression.is_resource_exhausted:
        conditioned = _conditioned_trace_for_node(node, ir, seen=frozenset())
        if conditioned is not None:
            return conditioned
    return EvaluationTraceExpression.from_expression(
        expression
    )


def _evaluation_expression_for_node(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR | None,
    context: EvaluationTraceContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression:
    expression = EvaluationExpression.from_frontier(
        node.evaluation, origin=_node_origin("local", node)
    )

    reference_expression = _reference_expression(
        node,
        ir,
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=seen,
    )
    if reference_expression is not None:
        return expression.merge(reference_expression)

    for applicator in _applicators(node, "allOf"):
        for child in applicator.children:
            child_expression = _evaluation_expression_for_node(
                child,
                ir,
                lhs_term=lhs_term,
                lhs_ir=lhs_ir,
                context=context,
                seen=seen,
            )
            if (
                context is not None
                and lhs_term is not None
                and lhs_ir is not None
                and _expression_has_effects_or_unsupported(child_expression)
            ):
                proof = context.subproof_terms(
                    lhs_term,
                    lhs_ir,
                    SchemaTerm.node(child.ref),
                    ir,
                )
                if proof.status == "resource_exhausted":
                    return EvaluationExpression.resource_exhausted(
                        proof.reason
                        or "evaluation expression allOf proof exhausted its budget"
                    ).with_origin(_node_origin("allOf", child))
                if proof.status != "proved_true":
                    return EvaluationExpression.unsupported(
                        "evaluation expression cannot prove selected allOf effects"
                    ).with_origin(_node_origin("allOf", child))
            expression = expression.merge(
                child_expression.with_origin(_node_origin("allOf", child))
            )
            if not expression.is_supported:
                return expression

    branch_expression = _branch_applicator_expression(
        node,
        ir,
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=seen,
    )
    if branch_expression is not None:
        return expression.merge(branch_expression)
    return expression


def _conditioned_trace_for_node(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationTraceExpression | None:
    base_expression = _unconditional_expression_prefix(node, ir, seen=seen)
    if base_expression is None or not base_expression.is_supported:
        return None

    branch_paths = _conditioned_branch_paths(node, ir, seen=seen)
    if not branch_paths:
        return None

    base_path = EvaluationTracePath(
        base_expression.property_sources,
        base_expression.item_sources,
        base_expression.origins,
    )
    return EvaluationTraceExpression(
        tuple(_merge_trace_path(base_path, path) for path in branch_paths)
    )


def _unconditional_expression_prefix(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    expression = EvaluationExpression.from_frontier(
        node.evaluation, origin=_node_origin("local", node)
    )
    reference_expression = _reference_expression(
        node,
        ir,
        lhs_term=None,
        lhs_ir=None,
        context=None,
        seen=seen,
    )
    if reference_expression is not None:
        expression = expression.merge(reference_expression)
        if not expression.is_supported:
            return expression

    for applicator in _applicators(node, "allOf"):
        for child in applicator.children:
            child_expression = _evaluation_expression_for_node(
                child,
                ir,
                lhs_term=None,
                lhs_ir=None,
                context=None,
                seen=seen,
            )
            expression = expression.merge(
                child_expression.with_origin(_node_origin("allOf", child))
            )
            if not expression.is_supported:
                return expression
    return expression


def _conditioned_branch_paths(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> tuple[EvaluationTracePath, ...]:
    for keyword in ("anyOf", "oneOf"):
        for applicator in _applicators(node, keyword):
            paths = _conditioned_branch_collection_paths(keyword, applicator, ir, seen)
            if paths:
                return paths

    conditional_paths = _conditioned_conditional_paths(node, ir, seen)
    if conditional_paths:
        return conditional_paths
    return ()


def _conditioned_branch_collection_paths(
    keyword: Literal["anyOf", "oneOf"],
    applicator: ApplicatorNode,
    ir: LogicalSchemaIR,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> tuple[EvaluationTracePath, ...]:
    paths = []
    for child in applicator.children:
        expression = _evaluation_expression_for_node(
            child,
            ir,
            lhs_term=None,
            lhs_ir=None,
            context=None,
            seen=seen,
        )
        if not expression.is_supported:
            return ()
        if not expression.property_sources and not expression.item_sources:
            continue
        paths.append(
            EvaluationTracePath(
                expression.property_sources,
                expression.item_sources,
                (_node_origin(keyword, child),) + expression.origins,
                SchemaTerm.node(child.ref),
            )
        )
    return tuple(paths)


def _conditioned_conditional_paths(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> tuple[EvaluationTracePath, ...]:
    if_applicator = _first_applicator(node, "if")
    if if_applicator is None or not if_applicator.children:
        return ()
    if_term = SchemaTerm.node(if_applicator.children[0].ref)

    return tuple(
        path
        for path in (
            _conditioned_conditional_path(node, ir, "then", if_term, seen),
            _conditioned_conditional_path(
                node, ir, "else", SchemaTerm.not_(if_term), seen
            ),
        )
        if path is not None
    )


def _conditioned_conditional_path(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    keyword: Literal["then", "else"],
    condition: SchemaTerm,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationTracePath | None:
    applicator = _first_applicator(node, keyword)
    if applicator is None or not applicator.children:
        return None
    expression = _evaluation_expression_for_node(
        applicator.children[0],
        ir,
        lhs_term=None,
        lhs_ir=None,
        context=None,
        seen=seen,
    )
    if not expression.is_supported:
        return None
    if not expression.property_sources and not expression.item_sources:
        return None
    return EvaluationTracePath(
        expression.property_sources,
        expression.item_sources,
        (_node_origin("conditional", applicator.children[0]),) + expression.origins,
        condition,
    )


def _merge_trace_path(
    base: EvaluationTracePath, branch: EvaluationTracePath
) -> EvaluationTracePath:
    return EvaluationTracePath(
        base.property_sources + branch.property_sources,
        base.item_sources + branch.item_sources,
        base.origins + branch.origins,
        branch.condition,
    )


def _reference_expression(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR | None,
    context: EvaluationTraceContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    static_reference = node.semantics.reference.static_reference
    if static_reference.rhs_unsupported is not None:
        return EvaluationExpression.unsupported(static_reference.rhs_unsupported.reason)
    if static_reference.target is not None:
        return _referenced_expression(
            "static-ref",
            node,
            static_reference.target,
            ir,
            lhs_term=lhs_term,
            lhs_ir=lhs_ir,
            context=context,
            seen=seen,
        )

    dynamic_reference = node.semantics.reference.dynamic_reference
    if dynamic_reference.rhs_unsupported is not None:
        return EvaluationExpression.unsupported(
            dynamic_reference.rhs_unsupported.reason
        )
    if dynamic_reference.target is not None:
        return _referenced_expression(
            "dynamic-ref",
            node,
            dynamic_reference.target,
            ir,
            lhs_term=lhs_term,
            lhs_ir=lhs_ir,
            context=context,
            seen=seen,
        )

    if node.semantics.reference.has_recursive_reference:
        return EvaluationExpression.unsupported(
            "evaluation expression does not support $recursiveRef recursive effects"
        )
    return None


def _referenced_expression(
    kind: Literal["static-ref", "dynamic-ref"],
    source: SchemaNode,
    target: SchemaTerm,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR | None,
    context: EvaluationTraceContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    if target.ref is None:
        return None
    target_node = ir.node_for_ref(target.ref)
    if target_node is None:
        return EvaluationExpression.unsupported(
            "evaluation expression reference target is not present in schema IR"
        )
    location = (
        target_node.source.resource_uri,
        target_node.source.resource_pointer,
    )
    if location in seen:
        return EvaluationExpression.unsupported(
            f"evaluation expression does not support recursive {kind} effects"
        )
    return _evaluation_expression_for_node(
        target_node,
        ir,
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=seen | {location},
    ).with_origin(_reference_origin(kind, source, target_node))


def _branch_applicator_expression(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR | None,
    context: EvaluationTraceContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    for keyword in ("anyOf", "oneOf"):
        for applicator in _applicators(node, keyword):
            branch = _branch_collection_expression(
                keyword,
                applicator,
                ir,
                lhs_term=lhs_term,
                lhs_ir=lhs_ir,
                context=context,
                seen=seen,
            )
            if branch is not None:
                return branch

    conditional = _conditional_expression(
        node,
        ir,
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=seen,
    )
    if conditional is not None:
        return conditional
    not_expression = _not_expression(
        node,
        ir,
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=seen,
    )
    if not_expression is not None:
        return not_expression
    return None


def _branch_collection_expression(
    keyword: Literal["anyOf", "oneOf"],
    applicator: ApplicatorNode,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR | None,
    context: EvaluationTraceContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    merged = EvaluationExpression()
    saw_effects = False
    for index, child in enumerate(applicator.children):
        child_expression = _evaluation_expression_for_node(
            child,
            ir,
            lhs_term=lhs_term,
            lhs_ir=lhs_ir,
            context=context,
            seen=seen,
        )
        child_has_effects = bool(
            child_expression.property_sources or child_expression.item_sources
        )
        saw_effects = (
            saw_effects or child_has_effects or not child_expression.is_supported
        )
        if context is None or lhs_term is None or lhs_ir is None:
            continue

        child_term = SchemaTerm.node(child.ref)
        branch_proof = context.subproof_terms(lhs_term, lhs_ir, child_term, ir)
        if branch_proof.status == "resource_exhausted":
            return EvaluationExpression.resource_exhausted(
                branch_proof.reason
                or f"evaluation expression {keyword} branch proof exhausted its budget"
            ).with_origin(_node_origin(keyword, child))
        if branch_proof.status != "proved_true":
            continue
        if keyword == "oneOf":
            uniqueness = _selected_branch_uniqueness_proof(
                lhs_term,
                lhs_ir,
                tuple(
                    SchemaTerm.node(other.ref)
                    for other_index, other in enumerate(applicator.children)
                    if other_index != index
                ),
                ir,
                context,
            )
            if uniqueness.status == "resource_exhausted":
                return EvaluationExpression.resource_exhausted(
                    uniqueness.reason
                    or (
                        "evaluation expression oneOf disjointness proof exhausted its "
                        "budget"
                    )
                ).with_origin(_node_origin(keyword, child))
            if uniqueness.status != "proved_true":
                continue
        if not child_expression.is_supported:
            return child_expression
        merged = merged.merge(
            child_expression.with_origin(_node_origin(keyword, child))
        )

    if merged.property_sources or merged.item_sources:
        return merged
    if saw_effects:
        return EvaluationExpression.unsupported(
            f"evaluation expression defers branch-aware {keyword} effects"
        )
    return None


def _selected_branch_uniqueness_proof(
    lhs_term: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    others: tuple[SchemaTerm, ...],
    rhs_ir: LogicalSchemaIR,
    context: EvaluationTraceContext,
) -> ProofResult:
    for other in others:
        proof = _lhs_disjoint_from_term(lhs_term, lhs_ir, other, rhs_ir, context)
        if proof.status != "proved_true":
            return proof
    return ProofResult.true()


def _conditional_expression(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR | None,
    context: EvaluationTraceContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    if_applicator = _first_applicator(node, "if")
    if if_applicator is None or not if_applicator.children:
        return None
    if_child = if_applicator.children[0]

    then_expression = _conditional_branch_expression(
        node,
        ir,
        "then",
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=seen,
    )
    else_expression = _conditional_branch_expression(
        node,
        ir,
        "else",
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=seen,
    )
    if then_expression is None and else_expression is None:
        return None
    if not _expression_has_effects_or_unsupported(
        then_expression
    ) and not _expression_has_effects_or_unsupported(else_expression):
        return None
    if context is None or lhs_term is None or lhs_ir is None:
        return EvaluationExpression.unsupported(
            "evaluation expression defers branch-aware conditional effects"
        )

    if_term = SchemaTerm.node(if_child.ref)
    condition_proof = context.subproof_terms(lhs_term, lhs_ir, if_term, ir)
    if condition_proof.status == "resource_exhausted":
        return EvaluationExpression.resource_exhausted(
            condition_proof.reason
            or "evaluation expression conditional proof exhausted its budget"
        ).with_origin(_node_origin("conditional", node))
    if condition_proof.status == "proved_true":
        return _selected_conditional_branch_expression(
            node,
            "then",
            then_expression,
            ir,
            lhs_term=lhs_term,
            lhs_ir=lhs_ir,
            context=context,
        )
    disjoint = _lhs_disjoint_from_term(lhs_term, lhs_ir, if_term, ir, context)
    if disjoint.status == "resource_exhausted":
        return EvaluationExpression.resource_exhausted(
            disjoint.reason
            or (
                "evaluation expression conditional disjointness proof "
                "exhausted its budget"
            )
        ).with_origin(_node_origin("conditional", node))
    if disjoint.status == "proved_true":
        return _selected_conditional_branch_expression(
            node,
            "else",
            else_expression,
            ir,
            lhs_term=lhs_term,
            lhs_ir=lhs_ir,
            context=context,
        )
    return EvaluationExpression.unsupported(
        "evaluation expression cannot prove the successful conditional branch"
    )


def _selected_conditional_branch_expression(
    node: SchemaNode,
    keyword: Literal["then", "else"],
    expression: EvaluationExpression | None,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    context: EvaluationTraceContext,
) -> EvaluationExpression:
    selected = expression or EvaluationExpression()
    origin = _node_origin("conditional", node)
    if not _expression_has_effects_or_unsupported(selected):
        return selected.with_origin(origin)

    branch = _first_applicator(node, keyword)
    if branch is None or not branch.children:
        return selected.with_origin(origin)

    branch_proof = context.subproof_terms(
        lhs_term,
        lhs_ir,
        SchemaTerm.node(branch.children[0].ref),
        ir,
    )
    if branch_proof.status == "resource_exhausted":
        return EvaluationExpression.resource_exhausted(
            branch_proof.reason
            or (
                f"evaluation expression conditional {keyword} proof "
                "exhausted its budget"
            )
        ).with_origin(origin)
    if branch_proof.status not in {"proved_true", "proved_false"}:
        return EvaluationExpression.unsupported(
            f"evaluation expression cannot prove selected conditional {keyword} "
            "branch effects"
        ).with_origin(origin)
    return selected.with_origin(origin)


def _conditional_branch_expression(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    keyword: Literal["then", "else"],
    *,
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR | None,
    context: EvaluationTraceContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    applicator = _first_applicator(node, keyword)
    if applicator is None or not applicator.children:
        return None
    child_expression = _evaluation_expression_for_node(
        applicator.children[0],
        ir,
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=seen,
    )
    if not child_expression.is_supported:
        return child_expression
    if child_expression.property_sources or child_expression.item_sources:
        return child_expression
    return EvaluationExpression()


def _not_expression(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    *,
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR | None,
    context: EvaluationTraceContext | None,
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> EvaluationExpression | None:
    applicator = _first_applicator(node, "not")
    if applicator is None or not applicator.children:
        return None
    child = applicator.children[0]
    child_expression = _evaluation_expression_for_node(
        child,
        ir,
        lhs_term=lhs_term,
        lhs_ir=lhs_ir,
        context=context,
        seen=seen,
    )
    if not child_expression.is_supported:
        return child_expression
    if child_expression.property_sources or child_expression.item_sources:
        return EvaluationExpression.unsupported(
            "evaluation expression defers branch-aware not effects",
            unsupported_priority=10,
        ).with_origin(_node_origin("not", child))
    return None


def _expression_has_effects_or_unsupported(
    expression: EvaluationExpression | None,
) -> bool:
    return expression is not None and (
        not expression.is_supported
        or bool(expression.property_sources or expression.item_sources)
    )


def _lhs_disjoint_from_term(
    lhs_term: SchemaTerm,
    lhs_ir: LogicalSchemaIR,
    rhs_term: SchemaTerm,
    rhs_ir: LogicalSchemaIR,
    context: EvaluationTraceContext,
) -> ProofResult:
    if (
        lhs_term.kind == "node"
        and lhs_term.ref is not None
        and rhs_term.kind == "node"
        and rhs_term.ref is not None
    ):
        return irs_are_disjoint(
            lhs_ir.with_root_ref(lhs_term.ref),
            rhs_ir.with_root_ref(rhs_term.ref),
            cast(Any, context),
        )
    return context.subproof_terms(
        lhs_term,
        lhs_ir,
        SchemaTerm.not_(rhs_term),
        rhs_ir,
    )


def _applicators(
    node: SchemaNode, kind: Literal["allOf", "anyOf", "oneOf"]
) -> tuple[ApplicatorNode, ...]:
    return tuple(
        applicator for applicator in node.applicators if applicator.kind == kind
    )


def _first_applicator(
    node: SchemaNode,
    kind: Literal["if", "then", "else", "not"],
) -> ApplicatorNode | None:
    for applicator in node.applicators:
        if applicator.kind == kind:
            return applicator
    return None


def _node_origin(
    kind: EvaluationOriginKind, node: SchemaNode
) -> EvaluationExpressionOrigin:
    source = node.source
    return EvaluationExpressionOrigin(
        kind,
        source_resource_uri=source.resource_uri,
        source_pointer=source.pointer,
        source_resource_pointer=source.resource_pointer,
    )


def _reference_origin(
    kind: Literal["static-ref", "dynamic-ref"],
    source: SchemaNode,
    target: SchemaNode,
) -> EvaluationExpressionOrigin:
    source_ref = source.source
    target_ref = target.source
    return EvaluationExpressionOrigin(
        kind,
        source_resource_uri=source_ref.resource_uri,
        source_pointer=source_ref.pointer,
        source_resource_pointer=source_ref.resource_pointer,
        target_resource_uri=target_ref.resource_uri,
        target_pointer=target_ref.resource_pointer,
        target_document_pointer=target_ref.document_pointer,
    )


def _evaluation_expression_cache_key(
    node: SchemaNode,
    ir: LogicalSchemaIR,
    lhs_term: SchemaTerm | None,
    context: EvaluationTraceContext,
) -> tuple[Any, ...]:
    return (
        ir.document.cache_identity,
        node.ref,
        lhs_term,
        *context.proof_policy_identity,
    )


def _cached_evaluation_expression(
    context: EvaluationTraceContext, cache_key: tuple[Any, ...]
) -> EvaluationExpression | None:
    cached = context.cache_get("evaluation-expression", cache_key)
    return cached if isinstance(cached, EvaluationExpression) else None


def _cache_evaluation_expression(
    context: EvaluationTraceContext,
    cache_key: tuple[Any, ...],
    expression: EvaluationExpression,
) -> None:
    context.cache_set("evaluation-expression", cache_key, expression)
