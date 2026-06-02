from __future__ import annotations

from subschema.dialects import Dialect

type JSONScalar = None | bool | int | float | str
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type JSONArray = list[JSONValue]
type JSONObject = dict[str, JSONValue]
type JSONSchema = JSONValue
type DialectInput = Dialect | str | None
type SchemaPath = tuple[str, ...]
