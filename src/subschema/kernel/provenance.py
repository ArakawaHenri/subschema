from __future__ import annotations

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

    @classmethod
    def root(cls, schema: Any, dialect: Dialect) -> SchemaSource:
        return cls(schema=schema, dialect=dialect)

    @property
    def is_root_schema(self) -> bool:
        return not self.pointer and not self.document_pointer
