"""
Reference normalization and resource graph helpers for schema compilation.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeGuard
from urllib.parse import urldefrag, urljoin

from referencing import Registry, Resource
from referencing.jsonschema import DRAFT201909, DRAFT202012

from subschema.compiler.normalization import (
    SCHEMA_ARRAY_KEYWORDS,
    SCHEMA_VALUE_KEYWORDS,
)
from subschema.compiler.normalization import (
    SCHEMA_MAP_KEYWORDS as NORMALIZED_SCHEMA_MAP_KEYWORDS,
)
from subschema.compiler.schemas import IGNORED_SCHEMA_METADATA_KEYS
from subschema.contracts import (
    ProofSide,
    UnsupportedCategory,
    UnsupportedDiagnostic,
)
from subschema.dialects import (
    Dialect,
    dialect_from_schema,
    normalize_dialect,
    resolve_dialect,
)
from subschema.provenance import SchemaSource, resource_items

SCHEMA_MAP_KEYWORDS = NORMALIZED_SCHEMA_MAP_KEYWORDS - {"dependencies"}

REF_SIBLING_METADATA_KEYWORDS = {
    "$anchor",
    "$defs",
    "$dynamicAnchor",
    "$id",
    "$recursiveAnchor",
    "$schema",
    "$vocabulary",
    "definitions",
    "id",
}
OBJECT_RECURSION_GUARD_KEYWORDS = {
    "additionalProperties",
    "dependentSchemas",
    "patternProperties",
    "properties",
    "unevaluatedProperties",
}
ARRAY_RECURSION_GUARD_KEYWORDS = {
    "additionalItems",
    "contains",
    "items",
    "prefixItems",
    "unevaluatedItems",
}

__all__ = [
    "REF_SIBLING_METADATA_KEYWORDS",
    "DynamicReferenceUnsupported",
    "DynamicScope",
    "ReferenceFrame",
    "ReferenceResolution",
    "ResourceGraph",
    "ResourceInfo",
    "ResourceLocation",
    "SCHEMA_ARRAY_KEYWORDS",
    "SCHEMA_MAP_KEYWORDS",
    "SCHEMA_VALUE_KEYWORDS",
    "SchemaIR",
    "StaticReferenceUnsupported",
    "dynamic_reference_resolution_for_schema",
    "inline_static_refs_for_proof",
    "normalize_ir_dialect",
    "normalize_modern_refs",
    "resource_graph_for_source",
    "resolve_schema_reference",
    "root_dynamic_reference_resolution",
    "root_static_reference_resolution",
    "recursive_guard_kind_for_path",
    "static_reference_resolution_for_schema",
]


def normalize_modern_refs(schema: Any, dialect: Dialect | str | None = None) -> Any:
    normalized = copy.deepcopy(schema)
    _rewrite_ref_siblings(normalized, dialect)
    resolved_dialect = resolve_dialect(normalized, dialect=dialect)
    anchors: dict[str, str] = {}
    _collect_anchors(normalized, (), anchors, resolved_dialect)
    if anchors:
        _rewrite_anchor_refs(normalized, anchors)
    return normalized


def inline_static_refs_for_proof(
    schema: Any,
    dialect: Dialect | str | None = None,
    *,
    resources: Mapping[str, Any] | None = None,
) -> Any:
    normalized = copy.deepcopy(schema)
    _rewrite_ref_siblings(normalized, dialect)
    graph = ResourceGraph.build(normalized, dialect=dialect, resources=resources)
    if _has_recursive_static_ref(normalized, graph, (), frozenset()):
        return normalized
    return _inline_static_refs_node(normalized, graph, (), frozenset())


def resolve_schema_reference(
    schema: dict[str, Any], graph: ResourceGraph | None
) -> Any | None:
    if graph is None:
        return None
    for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
        ref = schema.get(keyword)
        if isinstance(ref, str):
            return graph.resolve_ref(ref)
    return None


def resource_graph_for_source(source: SchemaSource) -> ResourceGraph:
    root = source.document_root if source.document_root is not None else source.schema
    dialect = source.document_dialect or source.dialect
    return ResourceGraph.build(root, dialect=dialect, resources=dict(source.resources))


def _has_recursive_static_ref(
    schema: Any,
    graph: ResourceGraph,
    pointer: tuple[str, ...],
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> bool:
    if isinstance(schema, list):
        return any(
            _has_recursive_static_ref(item, graph, pointer + (str(index),), seen)
            for index, item in enumerate(schema)
        )
    if not isinstance(schema, dict):
        return False

    ref = schema.get("$ref")
    if isinstance(ref, str):
        location = graph.location_for_pointer(pointer)
        resolution = graph.resolve_ref_info(
            ref,
            base_uri=location.resource_uri,
            source_pointer=pointer,
            source_resource_pointer=location.resource_pointer,
        )
        if resolution is None:
            return False
        target_location = (resolution.resource_uri, resolution.pointer)
        if target_location in seen:
            return True
        return _has_recursive_static_ref(
            resolution.schema,
            graph,
            resolution.document_pointer,
            seen | {target_location},
        )

    return any(
        _has_recursive_static_ref(value, graph, pointer + (str(keyword),), seen)
        for keyword, value in schema.items()
    )


def _inline_static_refs_node(
    schema: Any,
    graph: ResourceGraph,
    pointer: tuple[str, ...],
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> Any:
    if isinstance(schema, list):
        return [
            _inline_static_refs_node(item, graph, pointer + (str(index),), seen)
            for index, item in enumerate(schema)
        ]
    if not isinstance(schema, dict):
        return copy.deepcopy(schema)

    ref = schema.get("$ref")
    if isinstance(ref, str):
        location = graph.location_for_pointer(pointer)
        resolution = graph.resolve_ref_info(
            ref,
            base_uri=location.resource_uri,
            source_pointer=pointer,
            source_resource_pointer=location.resource_pointer,
        )
        if resolution is None or resolution.dialect is not location.dialect:
            return _inline_static_refs_children(schema, graph, pointer, seen)

        target_location = (resolution.resource_uri, resolution.pointer)
        if target_location in seen:
            return _inline_static_refs_children(schema, graph, pointer, seen)

        expanded_target = _inline_static_refs_node(
            resolution.schema,
            graph,
            resolution.document_pointer,
            seen | {target_location},
        )
        if _ref_siblings_apply(location.dialect) and _has_ref_siblings(schema):
            metadata = {
                keyword: copy.deepcopy(value)
                for keyword, value in schema.items()
                if keyword in REF_SIBLING_METADATA_KEYWORDS
            }
            sibling_schema = {
                keyword: value
                for keyword, value in schema.items()
                if keyword != "$ref" and keyword not in REF_SIBLING_METADATA_KEYWORDS
            }
            expanded_sibling = _inline_static_refs_node(
                sibling_schema, graph, pointer, seen
            )
            return {**metadata, "allOf": [expanded_target, expanded_sibling]}
        return expanded_target

    return _inline_static_refs_children(schema, graph, pointer, seen)


def _inline_static_refs_children(
    schema: dict[str, Any],
    graph: ResourceGraph,
    pointer: tuple[str, ...],
    seen: frozenset[tuple[str, tuple[str, ...]]],
) -> dict[str, Any]:
    return {
        keyword: _inline_static_refs_node(value, graph, pointer + (str(keyword),), seen)
        for keyword, value in schema.items()
    }


def _rewrite_ref_siblings(schema: Any, dialect: Dialect | str | None) -> None:
    if isinstance(schema, dict):
        if _ref_siblings_apply(dialect) and _has_ref_siblings(schema):
            _rewrite_current_ref_sibling(schema)
        for keyword, value in list(schema.items()):
            if keyword in SCHEMA_VALUE_KEYWORDS:
                _rewrite_ref_siblings(value, dialect)
            elif keyword in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
                for subschema in value:
                    _rewrite_ref_siblings(subschema, dialect)
            elif keyword in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
                for subschema in value.values():
                    _rewrite_ref_siblings(subschema, dialect)
            elif keyword == "dependencies" and isinstance(value, dict):
                for dependency in value.values():
                    if isinstance(dependency, dict):
                        _rewrite_ref_siblings(dependency, dialect)
    elif isinstance(schema, list):
        for item in schema:
            _rewrite_ref_siblings(item, dialect)


def _ref_siblings_apply(dialect: Dialect | str | None) -> bool:
    return normalize_dialect(dialect) in {
        Dialect.DRAFT201909,
        Dialect.DRAFT202012,
    }


def _has_ref_siblings(schema: dict[str, Any]) -> bool:
    return "$ref" in schema and any(
        keyword != "$ref" and keyword not in REF_SIBLING_METADATA_KEYWORDS
        for keyword in schema
    )


def _rewrite_current_ref_sibling(schema: dict[str, Any]) -> None:
    ref = schema["$ref"]
    metadata = {
        keyword: value
        for keyword, value in schema.items()
        if keyword in REF_SIBLING_METADATA_KEYWORDS
    }
    sibling_schema = {
        keyword: value
        for keyword, value in schema.items()
        if keyword != "$ref" and keyword not in REF_SIBLING_METADATA_KEYWORDS
    }

    schema.clear()
    schema.update(metadata)
    schema["allOf"] = [{"$ref": ref}, sibling_schema]


def _collect_anchors(
    schema: Any, path: tuple[str, ...], anchors: dict[str, str], dialect: Dialect
) -> None:
    if not isinstance(schema, dict):
        return

    anchor = schema.get("$anchor")
    if dialect in {Dialect.DRAFT201909, Dialect.DRAFT202012} and isinstance(
        anchor, str
    ):
        anchors[f"#{anchor}"] = _json_pointer(path)

    schema_id = (
        schema.get("$id")
        if dialect
        in {Dialect.DRAFT6, Dialect.DRAFT7, Dialect.DRAFT201909, Dialect.DRAFT202012}
        else None
    )
    if _is_plain_fragment_id(schema_id):
        anchors[schema_id] = _json_pointer(path)

    for keyword, value in schema.items():
        if keyword in SCHEMA_VALUE_KEYWORDS:
            _collect_schema_value_anchors(value, path + (keyword,), anchors, dialect)
        elif keyword in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
            for index, subschema in enumerate(value):
                _collect_anchors(
                    subschema, path + (keyword, str(index)), anchors, dialect
                )
        elif keyword in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            for property_name, subschema in value.items():
                _collect_anchors(
                    subschema,
                    path + (keyword, property_name),
                    anchors,
                    dialect,
                )
        elif keyword == "dependencies" and isinstance(value, dict):
            for property_name, dependency in value.items():
                if isinstance(dependency, dict):
                    _collect_anchors(
                        dependency,
                        path + (keyword, property_name),
                        anchors,
                        dialect,
                    )


def _collect_schema_value_anchors(
    value: Any, path: tuple[str, ...], anchors: dict[str, str], dialect: Dialect
) -> None:
    if isinstance(value, list):
        for index, subschema in enumerate(value):
            _collect_anchors(subschema, path + (str(index),), anchors, dialect)
    else:
        _collect_anchors(value, path, anchors, dialect)


def _rewrite_anchor_refs(schema: Any, anchors: dict[str, str]) -> None:
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if ref in anchors:
            schema["$ref"] = anchors[ref]
        for value in schema.values():
            _rewrite_anchor_refs(value, anchors)
    elif isinstance(schema, list):
        for item in schema:
            _rewrite_anchor_refs(item, anchors)


def _is_plain_fragment_id(value: Any) -> TypeGuard[str]:
    return (
        isinstance(value, str) and value.startswith("#") and not value.startswith("#/")
    )


def _json_pointer(path: tuple[str, ...]) -> str:
    if not path:
        return "#"
    return "#/" + "/".join(_escape_json_pointer_part(part) for part in path)


def _escape_json_pointer_part(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


@dataclass(frozen=True)
class SchemaIR:
    schema: Any
    dialect: Dialect
    resource_uri: str = ""
    pointer: tuple[str, ...] = ()
    resource_pointer: tuple[str, ...] = ()
    document_pointer: tuple[str, ...] = ()
    document_root: Any | None = None
    document_dialect: Dialect | None = None
    resources: tuple[tuple[str, Any], ...] = ()

    def to_source(self) -> SchemaSource:
        return SchemaSource(
            schema=self.schema,
            dialect=self.dialect,
            resource_uri=self.resource_uri,
            pointer=self.pointer,
            resource_pointer=self.resource_pointer,
            document_pointer=self.document_pointer,
            document_root=self.document_root,
            document_dialect=self.document_dialect,
            resources=self.resources,
        )


@dataclass
class ResourceInfo:
    uri: str
    schema: Any
    dialect: Dialect
    pointer: tuple[str, ...] = ()
    anchors: dict[str, tuple[str, ...]] = field(default_factory=dict)
    dynamic_anchors: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceLocation:
    resource_uri: str
    document_pointer: tuple[str, ...]
    resource_pointer: tuple[str, ...]
    dialect: Dialect


@dataclass(frozen=True)
class ReferenceFrame:
    resource_uri: str
    document_pointer: tuple[str, ...]
    resource_pointer: tuple[str, ...]
    dialect: Dialect


@dataclass(frozen=True)
class DynamicScope:
    frames: tuple[ReferenceFrame, ...] = ()

    def push(self, frame: ReferenceFrame) -> DynamicScope:
        return DynamicScope(self.frames + (frame,))

    def dynamic_anchor_resolution(
        self,
        graph: ResourceGraph,
        anchor: str,
        *,
        ref: str,
        source: ReferenceFrame,
    ) -> ReferenceResolution | None:
        for frame in reversed(self.frames):
            resource = graph.resources.get(frame.resource_uri)
            if resource is None:
                continue
            pointer = resource.dynamic_anchors.get(anchor)
            if pointer is None or pointer != frame.resource_pointer:
                continue
            schema = _resolve_pointer_parts(resource.schema, pointer)
            if schema is None:
                continue
            dialect = dialect_from_schema(schema) or resource.dialect
            return ReferenceResolution(
                ref=ref,
                resource_uri=resource.uri,
                pointer=pointer,
                schema=schema,
                dialect=dialect,
                document_pointer=resource.pointer + pointer,
                source_resource_uri=source.resource_uri,
                source_pointer=source.document_pointer,
                source_resource_pointer=source.resource_pointer,
            )
        return None


@dataclass(frozen=True)
class ReferenceResolution:
    ref: str
    resource_uri: str
    pointer: tuple[str, ...]
    schema: Any
    dialect: Dialect
    document_pointer: tuple[str, ...] = ()
    source_resource_uri: str = ""
    source_pointer: tuple[str, ...] = ()
    source_resource_pointer: tuple[str, ...] = ()


@dataclass(frozen=True)
class StaticReferenceUnsupported:
    reason: str
    side: ProofSide
    path: tuple[str, ...]
    category: UnsupportedCategory = "static-reference"
    keyword: str = "$ref"
    ref: str | None = None
    guard_kind: str | None = None
    target: ReferenceResolution | None = None
    polarity: str = "positive"

    def diagnostic(self) -> UnsupportedDiagnostic:
        return UnsupportedDiagnostic(
            category=self.category,
            reason=self.reason,
            keyword=self.keyword,
            path=self.path,
            side=self.side,
        )


@dataclass(frozen=True)
class DynamicReferenceUnsupported:
    reason: str
    side: ProofSide
    path: tuple[str, ...]
    category: UnsupportedCategory = "dynamic-reference"
    keyword: str = "$dynamicRef"
    ref: str | None = None
    guard_kind: str | None = None
    polarity: str = "positive"

    def diagnostic(self) -> UnsupportedDiagnostic:
        return UnsupportedDiagnostic(
            category=self.category,
            reason=self.reason,
            keyword=self.keyword,
            path=self.path,
            side=self.side,
        )


@dataclass
class ResourceGraph:
    root: Any
    dialect: Dialect
    root_uri: str = ""
    external_resources: tuple[tuple[str, Any], ...] = ()
    resources: dict[str, ResourceInfo] = field(default_factory=dict)
    locations: dict[tuple[str, ...], ResourceLocation] = field(default_factory=dict)
    registry: Registry = field(default_factory=Registry)

    @classmethod
    def build(
        cls,
        schema: Any,
        dialect: Dialect | str | None = None,
        *,
        resources: Mapping[str, Any] | None = None,
    ) -> ResourceGraph:
        resolved_dialect = resolve_dialect(schema, dialect=dialect)
        graph = cls(
            root=schema,
            dialect=resolved_dialect,
            external_resources=resource_items(resources),
        )
        graph._collect_resource(
            schema=schema,
            base_uri="",
            document_pointer=(),
            inherited_dialect=resolved_dialect,
            current_resource_uri=None,
            current_resource_pointer=(),
            record_locations=True,
            update_root_uri=True,
        )
        for uri, resource_schema in sorted((resources or {}).items()):
            resource_dialect = resolve_dialect(
                resource_schema, dialect=resolved_dialect
            )
            if not isinstance(resource_schema, dict):
                graph.resources[uri] = ResourceInfo(
                    uri=uri,
                    schema=resource_schema,
                    dialect=resource_dialect,
                )
                continue
            graph._collect_resource(
                schema=resource_schema,
                base_uri=uri,
                document_pointer=(),
                inherited_dialect=resource_dialect,
                current_resource_uri=uri,
                current_resource_pointer=(),
                record_locations=False,
                update_root_uri=False,
            )
        return graph

    def to_ir(self) -> SchemaIR:
        return self.schema_ir_for_pointer((), self.root)

    def schema_ir_for_pointer(self, pointer: tuple[str, ...], schema: Any) -> SchemaIR:
        location = self.location_for_pointer(pointer)
        return SchemaIR(
            schema,
            location.dialect,
            resource_uri=location.resource_uri,
            pointer=pointer,
            resource_pointer=location.resource_pointer,
            document_pointer=pointer,
            document_root=self.root,
            document_dialect=self.dialect,
            resources=self.external_resources,
        )

    def reference_frame_for_pointer(self, pointer: tuple[str, ...]) -> ReferenceFrame:
        location = self.location_for_pointer(pointer)
        return ReferenceFrame(
            location.resource_uri,
            location.document_pointer,
            location.resource_pointer,
            location.dialect,
        )

    def location_for_pointer(self, pointer: tuple[str, ...]) -> ResourceLocation:
        location = self.locations.get(pointer)
        if location is not None:
            return location

        resource = self._resource_for_document_pointer(pointer)
        return ResourceLocation(
            resource.uri,
            pointer,
            _relative_pointer(pointer, resource.pointer),
            resource.dialect,
        )

    def resolve_ref(self, ref: str, base_uri: str = "") -> Any | None:
        resolution = self.resolve_ref_info(ref, base_uri=base_uri)
        return None if resolution is None else resolution.schema

    def resolve_ref_info(
        self,
        ref: str,
        base_uri: str = "",
        *,
        source_pointer: tuple[str, ...] = (),
        source_resource_pointer: tuple[str, ...] = (),
    ) -> ReferenceResolution | None:
        effective_base_uri = self.root_uri if base_uri == "" else base_uri
        uri, fragment = urldefrag(urljoin(effective_base_uri, ref))
        resource = self.resources.get(uri)
        if resource is None and uri == "":
            resource = self.resources.get("")
        if resource is None:
            return None

        pointer: tuple[str, ...]
        if not fragment:
            pointer = ()
        elif fragment.startswith("/"):
            pointer = tuple(
                _unescape_part(part) for part in fragment.strip("/").split("/")
            )
        else:
            resolved_pointer = (
                resource.anchors[fragment]
                if fragment in resource.anchors
                else resource.dynamic_anchors.get(fragment)
            )
            if resolved_pointer is None:
                return None
            pointer = resolved_pointer

        schema = _resolve_pointer_parts(resource.schema, pointer)
        if schema is None:
            return None
        dialect = dialect_from_schema(schema) or resource.dialect
        document_pointer = resource.pointer + pointer
        return ReferenceResolution(
            ref=ref,
            resource_uri=resource.uri,
            pointer=pointer,
            schema=schema,
            dialect=dialect,
            document_pointer=document_pointer,
            source_resource_uri=effective_base_uri,
            source_pointer=source_pointer,
            source_resource_pointer=source_resource_pointer,
        )

    def resolve_dynamic_ref_info(
        self,
        ref: str,
        source: ReferenceFrame,
        *,
        dynamic_scope: DynamicScope | None = None,
    ) -> ReferenceResolution | None:
        static_resolution = self.resolve_ref_info(
            ref,
            base_uri=source.resource_uri,
            source_pointer=source.document_pointer,
            source_resource_pointer=source.resource_pointer,
        )
        if static_resolution is None:
            return None

        _, fragment = urldefrag(urljoin(source.resource_uri, ref))
        if not fragment or fragment.startswith("/"):
            return static_resolution

        scope = dynamic_scope or DynamicScope()
        return (
            scope.dynamic_anchor_resolution(
                self,
                fragment,
                ref=ref,
                source=source,
            )
            or static_resolution
        )

    def _collect_resource(
        self,
        schema: Any,
        base_uri: str,
        document_pointer: tuple[str, ...],
        inherited_dialect: Dialect,
        current_resource_uri: str | None,
        current_resource_pointer: tuple[str, ...],
        *,
        record_locations: bool,
        update_root_uri: bool,
    ) -> None:
        if not isinstance(schema, dict):
            return

        dialect = resolve_dialect(schema, dialect=inherited_dialect)
        if dialect is Dialect.DRAFT4:
            schema_id = schema.get("id")
        else:
            schema_id = (
                schema.get("$id")
                if dialect
                in {
                    Dialect.DRAFT6,
                    Dialect.DRAFT7,
                    Dialect.DRAFT201909,
                    Dialect.DRAFT202012,
                }
                else None
            )
        starts_resource = current_resource_uri is None or isinstance(schema_id, str)
        resource_uri = (
            urljoin(base_uri, schema_id)
            if isinstance(schema_id, str)
            else current_resource_uri or base_uri
        )
        resource_pointer = (
            document_pointer if starts_resource else current_resource_pointer
        )

        if update_root_uri and document_pointer == ():
            self.root_uri = resource_uri
        if current_resource_uri is not None and _is_plain_fragment_id(schema_id):
            parent = self.resources.get(current_resource_uri)
            if parent is not None:
                parent.anchors[schema_id[1:]] = _relative_pointer(
                    document_pointer, parent.pointer
                )
        resource = self.resources.setdefault(
            resource_uri,
            ResourceInfo(
                uri=resource_uri,
                schema=schema,
                dialect=dialect,
                pointer=resource_pointer,
            ),
        )
        if record_locations:
            self.locations[document_pointer] = ResourceLocation(
                resource_uri,
                document_pointer,
                _relative_pointer(document_pointer, resource.pointer),
                dialect,
            )
        if (
            dialect in {Dialect.DRAFT201909, Dialect.DRAFT202012}
            and "$anchor" in schema
            and isinstance(schema["$anchor"], str)
        ):
            resource.anchors[schema["$anchor"]] = _relative_pointer(
                document_pointer, resource.pointer
            )
        if (
            dialect is Dialect.DRAFT202012
            and "$dynamicAnchor" in schema
            and isinstance(schema["$dynamicAnchor"], str)
        ):
            resource.dynamic_anchors[schema["$dynamicAnchor"]] = _relative_pointer(
                document_pointer, resource.pointer
            )

        specification = DRAFT202012 if dialect is Dialect.DRAFT202012 else DRAFT201909
        try:
            self.registry = self.registry.with_resource(
                resource_uri or "",
                Resource.from_contents(schema, default_specification=specification),
            )
        except Exception:
            pass

        for key, value in schema.items():
            if key in {
                "$defs",
                "definitions",
                "properties",
                "patternProperties",
                "dependentSchemas",
            } and isinstance(value, dict):
                for name, subschema in value.items():
                    self._collect_resource(
                        subschema,
                        resource_uri,
                        document_pointer + (key, str(name)),
                        dialect,
                        resource_uri,
                        resource.pointer,
                        record_locations=record_locations,
                        update_root_uri=False,
                    )
            elif key in {
                "items",
                "additionalItems",
                "additionalProperties",
                "contains",
                "propertyNames",
                "if",
                "then",
                "else",
                "not",
                "unevaluatedItems",
                "unevaluatedProperties",
            }:
                self._collect_resource(
                    value,
                    resource_uri,
                    document_pointer + (key,),
                    dialect,
                    resource_uri,
                    resource.pointer,
                    record_locations=record_locations,
                    update_root_uri=False,
                )
            elif key in {"allOf", "anyOf", "oneOf", "prefixItems"} and isinstance(
                value, list
            ):
                for index, subschema in enumerate(value):
                    self._collect_resource(
                        subschema,
                        resource_uri,
                        document_pointer + (key, str(index)),
                        dialect,
                        resource_uri,
                        resource.pointer,
                        record_locations=record_locations,
                        update_root_uri=False,
                    )
            elif key == "dependencies" and isinstance(value, dict):
                for name, dependency in value.items():
                    if isinstance(dependency, dict):
                        self._collect_resource(
                            dependency,
                            resource_uri,
                            document_pointer + (key, str(name)),
                            dialect,
                            resource_uri,
                            resource.pointer,
                            record_locations=record_locations,
                            update_root_uri=False,
                        )

    def _resource_for_document_pointer(self, pointer: tuple[str, ...]) -> ResourceInfo:
        best = self.resources.get(self.root_uri) or self.resources.get("")
        for resource in self.resources.values():
            if _is_prefix(resource.pointer, pointer) and (
                best is None or len(resource.pointer) > len(best.pointer)
            ):
                best = resource
        if best is None:
            return ResourceInfo(self.root_uri, self.root, self.dialect)
        return best


def root_static_reference_resolution(
    ir: Any,
    *,
    side: ProofSide,
) -> ReferenceResolution | StaticReferenceUnsupported | None:
    graph = resource_graph_for_source(ir.source)
    return static_reference_resolution_for_schema(
        ir.source.schema,
        graph,
        source_resource_uri=ir.source.resource_uri,
        source_pointer=ir.source.pointer,
        source_resource_pointer=ir.source.resource_pointer,
        source_dialect=ir.source.dialect,
        side=side,
    )


def root_dynamic_reference_resolution(
    ir: Any,
    *,
    side: ProofSide,
) -> ReferenceResolution | DynamicReferenceUnsupported | None:
    source = ir.source
    graph = resource_graph_for_source(source)
    source_frame = graph.reference_frame_for_pointer(source.pointer)
    return dynamic_reference_resolution_for_schema(
        source.schema,
        graph,
        source_frame=source_frame,
        dynamic_scope=DynamicScope().push(source_frame),
        side=side,
    )


def static_reference_resolution_for_schema(
    schema: Any,
    graph: ResourceGraph,
    *,
    source_resource_uri: str,
    source_pointer: tuple[str, ...],
    source_resource_pointer: tuple[str, ...],
    source_dialect: Dialect,
    side: ProofSide,
) -> ReferenceResolution | StaticReferenceUnsupported | None:
    if not _is_root_pure_static_reference(schema):
        return None

    seen = {(source_resource_uri, source_resource_pointer)}
    return _resolve_static_reference_chain(
        graph,
        schema["$ref"],
        base_uri=source_resource_uri,
        source_pointer=source_pointer,
        source_resource_pointer=source_resource_pointer,
        source_dialect=source_dialect,
        ref_path=source_pointer + ("$ref",),
        seen=seen,
        side=side,
    )


def dynamic_reference_resolution_for_schema(
    schema: Any,
    graph: ResourceGraph,
    *,
    source_frame: ReferenceFrame,
    dynamic_scope: DynamicScope,
    side: ProofSide,
) -> ReferenceResolution | DynamicReferenceUnsupported | None:
    if not _is_root_pure_dynamic_reference(schema):
        return None

    ref = schema["$dynamicRef"]
    ref_path = source_frame.document_pointer + ("$dynamicRef",)
    resolution = graph.resolve_dynamic_ref_info(
        ref,
        source_frame,
        dynamic_scope=dynamic_scope,
    )
    if resolution is None:
        return DynamicReferenceUnsupported(
            (
                f"SAT dynamic-reference fragment could not resolve {side} "
                f"$dynamicRef {ref!r}"
            ),
            side,
            ref_path,
            ref=ref,
        )

    if resolution.dialect is not source_frame.dialect:
        return DynamicReferenceUnsupported(
            (
                f"SAT dynamic-reference fragment does not support dialect "
                f"transition in {side} target {ref!r}"
            ),
            side,
            ref_path,
            ref=ref,
        )

    nested_ref_path = _first_reference_keyword_path(
        resolution.schema,
        {"$ref", "$dynamicRef", "$recursiveRef"},
    )
    if nested_ref_path is not None:
        category: UnsupportedCategory = "dynamic-reference"
        if nested_ref_path[-1] == "$ref":
            category = "static-reference"
        if nested_ref_path[-1] == "$recursiveRef":
            category = "recursive-reference"
        nested_ref = _resolve_pointer_parts(resolution.schema, nested_ref_path)
        return DynamicReferenceUnsupported(
            (
                f"SAT dynamic-reference fragment does not support nested "
                f"$dynamicRef/$ref in {side} target {ref!r}"
            ),
            side,
            resolution.document_pointer + nested_ref_path,
            category,
            nested_ref_path[-1],
            nested_ref if isinstance(nested_ref, str) else None,
            recursive_guard_kind_for_path(nested_ref_path),
            recursive_reference_polarity_for_path(nested_ref_path),
        )

    return resolution


def _resolve_static_reference_chain(
    graph: ResourceGraph,
    ref: str,
    *,
    base_uri: str,
    source_pointer: tuple[str, ...],
    source_resource_pointer: tuple[str, ...],
    source_dialect: Dialect,
    ref_path: tuple[str, ...],
    seen: set[tuple[str, tuple[str, ...]]],
    side: ProofSide,
) -> ReferenceResolution | StaticReferenceUnsupported:
    resolution = graph.resolve_ref_info(
        ref,
        base_uri=base_uri,
        source_pointer=source_pointer,
        source_resource_pointer=source_resource_pointer,
    )
    if resolution is None:
        return StaticReferenceUnsupported(
            f"SAT static-reference fragment could not resolve {side} $ref {ref!r}",
            side,
            ref_path,
            ref=ref,
        )

    location = (resolution.resource_uri, resolution.pointer)
    if location in seen:
        return StaticReferenceUnsupported(
            (
                f"SAT static-reference fragment does not support recursive "
                f"{side} $ref {ref!r}"
            ),
            side,
            ref_path,
            "recursive-reference",
            ref=ref,
            target=resolution,
        )
    seen.add(location)

    if resolution.dialect is not source_dialect:
        return StaticReferenceUnsupported(
            (
                f"SAT static-reference fragment does not support dialect "
                f"transition in {side} target {ref!r}"
            ),
            side,
            ref_path,
            ref=ref,
        )

    if _is_root_pure_static_reference(resolution.schema):
        return _resolve_static_reference_chain(
            graph,
            resolution.schema["$ref"],
            base_uri=_resolution_base_uri(resolution),
            source_pointer=resolution.document_pointer,
            source_resource_pointer=resolution.pointer,
            source_dialect=source_dialect,
            ref_path=resolution.document_pointer + ("$ref",),
            seen=seen,
            side=side,
        )

    nested_ref_path = _first_reference_keyword_path(
        resolution.schema,
        {"$ref", "$dynamicRef", "$recursiveRef"},
    )
    if nested_ref_path is not None:
        nested_recursive_boundary = _nested_recursive_reference_boundary(
            graph,
            resolution,
            nested_ref_path,
            seen,
            side,
        )
        if nested_recursive_boundary is not None:
            return nested_recursive_boundary
        return StaticReferenceUnsupported(
            (
                f"SAT static-reference fragment does not support nested "
                f"references in {side} target {ref!r}"
            ),
            side,
            resolution.document_pointer + nested_ref_path,
        )

    return resolution


def _nested_recursive_reference_boundary(
    graph: ResourceGraph,
    resolution: ReferenceResolution,
    nested_ref_path: tuple[str, ...],
    seen: set[tuple[str, tuple[str, ...]]],
    side: ProofSide,
) -> StaticReferenceUnsupported | None:
    nested_keyword = nested_ref_path[-1]
    full_path = resolution.document_pointer + nested_ref_path
    if nested_keyword == "$recursiveRef":
        return StaticReferenceUnsupported(
            (
                f"SAT static-reference fragment found $recursiveRef in {side} "
                "target; guarded recursive reference proofs are unsupported"
            ),
            side,
            full_path,
            "recursive-reference",
            "$recursiveRef",
            None,
            recursive_guard_kind_for_path(nested_ref_path),
            resolution,
            recursive_reference_polarity_for_path(nested_ref_path),
        )
    if nested_keyword != "$ref":
        return None

    nested_ref = _resolve_pointer_parts(resolution.schema, nested_ref_path)
    if not isinstance(nested_ref, str):
        return None
    nested_resolution = graph.resolve_ref_info(
        nested_ref,
        base_uri=_resolution_base_uri(resolution),
        source_pointer=full_path,
        source_resource_pointer=resolution.pointer + nested_ref_path,
    )
    if nested_resolution is None:
        return None
    if (nested_resolution.resource_uri, nested_resolution.pointer) not in seen:
        return None

    guard_kind = recursive_guard_kind_for_path(nested_ref_path)
    if guard_kind is None:
        reason = (
            f"SAT static-reference fragment found unguarded recursive {side} "
            f"$ref {nested_ref!r}"
        )
    else:
        reason = (
            f"SAT static-reference fragment found {guard_kind}-guarded recursive "
            f"{side} $ref {nested_ref!r}; guarded recursive reference proofs "
            "are unsupported"
        )
    return StaticReferenceUnsupported(
        reason,
        side,
        full_path,
        "recursive-reference",
        "$ref",
        nested_ref,
        guard_kind,
        resolution,
        recursive_reference_polarity_for_path(nested_ref_path),
    )


def recursive_guard_kind_for_path(path: tuple[str, ...]) -> str | None:
    has_object_guard = any(
        keyword in path for keyword in OBJECT_RECURSION_GUARD_KEYWORDS
    )
    has_array_guard = any(keyword in path for keyword in ARRAY_RECURSION_GUARD_KEYWORDS)
    if has_object_guard and has_array_guard:
        return "object/array"
    if has_object_guard:
        return "object"
    if has_array_guard:
        return "array"
    return None


def recursive_reference_polarity_for_path(path: tuple[str, ...]) -> str:
    negative_edges = sum(1 for part in path if part == "not")
    return "negative" if negative_edges % 2 else "positive"


def _resolution_base_uri(resolution: ReferenceResolution) -> str:
    schema = resolution.schema
    schema_id = schema.get("$id") if isinstance(schema, dict) else None
    if (
        resolution.dialect
        in {Dialect.DRAFT6, Dialect.DRAFT7, Dialect.DRAFT201909, Dialect.DRAFT202012}
        and isinstance(schema_id, str)
    ):
        return urljoin(resolution.resource_uri, schema_id)
    return resolution.resource_uri


def _is_root_pure_static_reference(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    semantic_keys = set(schema) - IGNORED_SCHEMA_METADATA_KEYS
    return semantic_keys == {"$ref"} and isinstance(schema.get("$ref"), str)


def _is_root_pure_dynamic_reference(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    semantic_keys = set(schema) - IGNORED_SCHEMA_METADATA_KEYS
    return semantic_keys == {"$dynamicRef"} and isinstance(
        schema.get("$dynamicRef"), str
    )


def _first_reference_keyword_path(
    schema: Any, keywords: set[str]
) -> tuple[str, ...] | None:
    if isinstance(schema, list):
        for index, item in enumerate(schema):
            path = _first_reference_keyword_path(item, keywords)
            if path is not None:
                return (str(index),) + path
        return None
    if not isinstance(schema, dict):
        return None
    for keyword, value in schema.items():
        if keyword in keywords:
            return (keyword,)
        path = _first_reference_keyword_path(value, keywords)
        if path is not None:
            return (str(keyword),) + path
    return None


def _resolve_pointer_parts(schema: Any, pointer: tuple[str, ...]) -> Any | None:
    current = schema
    for part in pointer:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _unescape_part(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def _is_prefix(prefix: tuple[str, ...], pointer: tuple[str, ...]) -> bool:
    return pointer[: len(prefix)] == prefix


def _relative_pointer(
    pointer: tuple[str, ...], prefix: tuple[str, ...]
) -> tuple[str, ...]:
    if not _is_prefix(prefix, pointer):
        return pointer
    return pointer[len(prefix) :]


def normalize_ir_dialect(dialect: Dialect | str | None) -> Dialect | None:
    return normalize_dialect(dialect)
