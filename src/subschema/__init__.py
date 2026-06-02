from subschema import api, exceptions
from subschema.dialects import Dialect
from subschema.exceptions import SchemaError, SubschemaError, UnsupportedProofError

is_subschema = api.is_subschema
is_empty = api.is_empty
is_disjoint = api.is_disjoint
covers = api.covers
meet_schemas = api.meet_schemas
join_schemas = api.join_schemas
is_equivalent = api.is_equivalent

canonicalize_schema = api.canonicalize_schema

__all__ = [
    "Dialect",
    "SchemaError",
    "SubschemaError",
    "UnsupportedProofError",
    "canonicalize_schema",
    "covers",
    "exceptions",
    "is_equivalent",
    "is_empty",
    "is_disjoint",
    "is_subschema",
    "join_schemas",
    "meet_schemas",
]
