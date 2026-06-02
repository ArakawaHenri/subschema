"""
Small tagged-union helpers for object oneOf fragments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from subschema.kernel.values import json_semantic_key, json_values_equal

__all__ = [
    "TaggedBranch",
    "TaggedOneOf",
    "matching_tagged_one_of_branch",
    "schema_required_singleton_tag",
    "tagged_one_of",
]


@dataclass(frozen=True)
class TaggedBranch:
    schema: Any
    tag_name: str
    tag_value: Any


@dataclass(frozen=True)
class TaggedOneOf:
    tag_name: str
    branches: tuple[TaggedBranch, ...]


def matching_tagged_one_of_branch(lhs: Any, rhs: Any) -> Any | None:
    tagged = tagged_one_of(rhs)
    if tagged is None:
        return None
    lhs_tag = schema_required_singleton_tag(lhs, tagged.tag_name)
    if lhs_tag is None:
        return None
    for branch in tagged.branches:
        if json_values_equal(lhs_tag, branch.tag_value):
            return branch.schema
    return None


def tagged_one_of(schema: Any) -> TaggedOneOf | None:
    if not isinstance(schema, dict):
        return None
    branches = schema.get("oneOf")
    if not isinstance(branches, list) or not branches:
        return None

    candidate_names = _candidate_discriminator_names(schema, branches)
    for tag_name in candidate_names:
        tagged_branches = _tagged_branches_for_name(branches, tag_name)
        if tagged_branches is not None:
            return TaggedOneOf(tag_name, tagged_branches)
    return None


def schema_required_singleton_tag(schema: Any, tag_name: str) -> Any | None:
    if not isinstance(schema, dict):
        return None
    required = schema.get("required")
    if not isinstance(required, list) or tag_name not in required:
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    return _singleton_schema_value(properties.get(tag_name))


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
    if not isinstance(branch, dict):
        return {}
    required = branch.get("required")
    properties = branch.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        return {}
    required_names = {name for name in required if isinstance(name, str)}
    tags = {}
    for name in required_names:
        value = _singleton_schema_value(properties.get(name))
        if value is not None:
            tags[name] = value
    return tags


def _tagged_branches_for_name(
    branches: list[Any], tag_name: str
) -> tuple[TaggedBranch, ...] | None:
    tagged_branches: list[TaggedBranch] = []
    seen_values: set[str] = set()
    for branch in branches:
        value = schema_required_singleton_tag(branch, tag_name)
        if value is None:
            return None
        key = json_semantic_key(value)
        if key in seen_values:
            return None
        seen_values.add(key)
        tagged_branches.append(TaggedBranch(branch, tag_name, value))
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
