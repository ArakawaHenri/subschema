from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from subschema.dialects import Dialect


@dataclass(frozen=True)
class SchemaSource:
    schema: Any
    dialect: Dialect
    resource_uri: str = ""
    pointer: tuple[str, ...] = ()
    resource_pointer: tuple[str, ...] = ()
    document_pointer: tuple[str, ...] = ()
    document_root: Any | None = None
    document_dialect: Dialect | None = None
    resources: tuple[tuple[str, Any], ...] = ()

    @classmethod
    def root(
        cls,
        schema: Any,
        dialect: Dialect,
        resources: Mapping[str, Any] | None = None,
    ) -> SchemaSource:
        return cls(
            schema=schema,
            dialect=dialect,
            document_root=schema,
            document_dialect=dialect,
            resources=resource_items(resources),
        )

    @property
    def is_root_schema(self) -> bool:
        return not self.pointer and not self.document_pointer

    @property
    def has_document_context(self) -> bool:
        return self.document_root is not None and self.document_dialect is not None

    def to_source(self) -> SchemaSource:
        return self


def resource_items(resources: Mapping[str, Any] | None) -> tuple[tuple[str, Any], ...]:
    if not resources:
        return ()
    return tuple(sorted(resources.items()))
