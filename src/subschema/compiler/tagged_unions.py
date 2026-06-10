"""
Small tagged-union helpers for object oneOf fragments.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from subschema.ir import TaggedBranch, TaggedOneOf
from subschema.ir.terms import SchemaTerm
from subschema.values import json_semantic_key

__all__ = [
    "TaggedBranch",
    "TaggedOneOf",
    "schema_required_singleton_tags",
    "schema_required_singleton_tag",
    "tagged_one_of",
]


def tagged_one_of(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
) -> TaggedOneOf | None:
    if not isinstance(schema, dict):
        return None
    branches = schema.get("oneOf")
    if not isinstance(branches, list) or not branches:
        return None

    candidate_names = _candidate_discriminator_names(schema, branches)
    for tag_name in candidate_names:
        tagged_branches = _tagged_branches_for_name(branches, tag_name, child_term)
        if tagged_branches is not None:
            return TaggedOneOf(tag_name, tagged_branches)
    return None


def schema_required_singleton_tag(schema: Any, tag_name: str) -> Any | None:
    for name, value in schema_required_singleton_tags(schema):
        if name == tag_name:
            return value
    return None


def schema_required_singleton_tags(schema: Any) -> tuple[tuple[str, Any], ...]:
    if not isinstance(schema, dict):
        return ()
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        return ()
    required_names = sorted({name for name in required if isinstance(name, str)})
    tags: list[tuple[str, Any]] = []
    for name in required_names:
        value = _singleton_schema_value(properties.get(name))
        if value is not None:
            tags.append((name, value))
    return tuple(tags)


def _candidate_discriminator_names(
    schema: dict[str, Any], branches: list[Any]
) -> tuple[str, ...]:
    discriminator = schema.get("discriminator")
    property_name = (
        discriminator.get("propertyName")
        if isinstance(discriminator, dict)
        else None
    )
    if isinstance(property_name, str):
        return (property_name,)

    candidates: set[str] | None = None
    for branch in branches:
        branch_candidates = set(_branch_singleton_required_tags(branch))
        candidates = (
            branch_candidates
            if candidates is None
            else candidates & branch_candidates
        )
    return tuple(sorted(candidates or ()))


def _branch_singleton_required_tags(branch: Any) -> dict[str, Any]:
    return dict(schema_required_singleton_tags(branch))


def _tagged_branches_for_name(
    branches: list[Any],
    tag_name: str,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
) -> tuple[TaggedBranch, ...] | None:
    tagged_branches: list[TaggedBranch] = []
    seen_values: set[str] = set()
    for index, branch in enumerate(branches):
        value = schema_required_singleton_tag(branch, tag_name)
        if value is None:
            return None
        key = json_semantic_key(value)
        if key in seen_values:
            return None
        seen_values.add(key)
        branch_term = (
            None
            if child_term is None or not isinstance(branch, bool | dict)
            else child_term(branch, ("oneOf", str(index)))
        )
        tagged_branches.append(TaggedBranch(branch, tag_name, value, branch_term))
    return tuple(tagged_branches)


def _singleton_schema_value(schema: Any) -> Any | None:
    if not isinstance(schema, dict):
        return None
    if "const" in schema:
        return schema["const"]
    enum = schema.get("enum")
    if isinstance(enum, list) and len(enum) == 1:
        return enum[0]
    return None
