from subschema import api, exceptions
from subschema.dialects import Dialect

is_subschema = api.is_subschema
meet_schemas = api.meet_schemas
join_schemas = api.join_schemas
is_equivalent = api.is_equivalent

canonicalize_schema = api.canonicalize_schema

__all__ = [
    "Dialect",
    "canonicalize_schema",
    "exceptions",
    "is_equivalent",
    "is_subschema",
    "join_schemas",
    "meet_schemas",
]
