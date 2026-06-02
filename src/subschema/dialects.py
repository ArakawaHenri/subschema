"""
JSON Schema dialect selection and keyword capability checks.
"""

from collections.abc import Mapping
from enum import StrEnum

from subschema.exceptions import (
    ConflictingDialectError,
    UnknownDialectError,
    UnsupportedKeywordError,
)


class Dialect(StrEnum):
    DRAFT4 = "draft4"
    DRAFT6 = "draft6"
    DRAFT7 = "draft7"
    DRAFT201909 = "draft2019-09"
    DRAFT202012 = "draft2020-12"


class KeywordCategory(StrEnum):
    ANNOTATION = "annotation"
    APPLICATOR = "applicator"
    ASSERTION = "assertion"
    RESOURCE = "resource"
    UNEVALUATED = "unevaluated"
    VOCABULARY = "vocabulary"
    UNKNOWN = "unknown"


DEFAULT_DIALECT = Dialect.DRAFT4

_ALIASES = {
    "draft4": Dialect.DRAFT4,
    "draft-4": Dialect.DRAFT4,
    "draft04": Dialect.DRAFT4,
    "draft-04": Dialect.DRAFT4,
    "http://json-schema.org/draft-04/schema": Dialect.DRAFT4,
    "draft6": Dialect.DRAFT6,
    "draft-6": Dialect.DRAFT6,
    "draft06": Dialect.DRAFT6,
    "draft-06": Dialect.DRAFT6,
    "http://json-schema.org/draft-06/schema": Dialect.DRAFT6,
    "draft7": Dialect.DRAFT7,
    "draft-7": Dialect.DRAFT7,
    "draft07": Dialect.DRAFT7,
    "draft-07": Dialect.DRAFT7,
    "http://json-schema.org/draft-07/schema": Dialect.DRAFT7,
    "2019-09": Dialect.DRAFT201909,
    "draft2019-09": Dialect.DRAFT201909,
    "draft/2019-09": Dialect.DRAFT201909,
    "https://json-schema.org/draft/2019-09/schema": Dialect.DRAFT201909,
    "http://json-schema.org/draft/2019-09/schema": Dialect.DRAFT201909,
    "2020-12": Dialect.DRAFT202012,
    "draft2020-12": Dialect.DRAFT202012,
    "draft/2020-12": Dialect.DRAFT202012,
    "https://json-schema.org/draft/2020-12/schema": Dialect.DRAFT202012,
    "http://json-schema.org/draft/2020-12/schema": Dialect.DRAFT202012,
}

ANNOTATION_KEYWORDS = {
    "$comment",
    "contentEncoding",
    "contentMediaType",
    "contentSchema",
    "default",
    "deprecated",
    "description",
    "examples",
    "format",
    "readOnly",
    "title",
    "writeOnly",
}

CORE_AND_REFERENCE_KEYWORDS = {
    "$defs",
    "$ref",
    "$schema",
    "definitions",
}

RESOURCE_KEYWORDS = CORE_AND_REFERENCE_KEYWORDS | {
    "$anchor",
    "$dynamicAnchor",
    "$dynamicRef",
    "$id",
    "$recursiveAnchor",
    "$recursiveRef",
    "id",
}

VOCABULARY_KEYWORDS = {"$vocabulary"}

IMPLEMENTED_VALIDATION_KEYWORDS = {
    "additionalItems",
    "additionalProperties",
    "allOf",
    "anyOf",
    "enum",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "items",
    "maximum",
    "maxItems",
    "maxLength",
    "maxProperties",
    "minimum",
    "minItems",
    "minLength",
    "minProperties",
    "multipleOf",
    "not",
    "oneOf",
    "pattern",
    "patternProperties",
    "properties",
    "required",
    "type",
    "uniqueItems",
}

DRAFT6_VALIDATION_KEYWORDS = {"const", "contains", "propertyNames"}
DRAFT4_TO_7_VALIDATION_KEYWORDS = {"dependencies"}

DRAFT201909_VALIDATION_KEYWORDS = {
    "dependentRequired",
    "dependentSchemas",
    "maxContains",
    "minContains",
}

APPLICATOR_KEYWORDS = {
    "additionalItems",
    "additionalProperties",
    "allOf",
    "anyOf",
    "contains",
    "dependencies",
    "dependentSchemas",
    "else",
    "if",
    "items",
    "not",
    "oneOf",
    "patternProperties",
    "prefixItems",
    "properties",
    "propertyNames",
    "then",
}

UNEVALUATED_KEYWORDS = {
    "unevaluatedItems",
    "unevaluatedProperties",
}

ASSERTION_KEYWORDS = (
    IMPLEMENTED_VALIDATION_KEYWORDS
    | DRAFT6_VALIDATION_KEYWORDS
    | DRAFT201909_VALIDATION_KEYWORDS
) - APPLICATOR_KEYWORDS

UNIMPLEMENTED_VALIDATION_KEYWORDS = set()

UNIMPLEMENTED_REFERENCE_KEYWORDS = set()

VOCABULARY_DIALECTS = {
    Dialect.DRAFT201909,
    Dialect.DRAFT202012,
}

SUPPORTED_VOCABULARIES = {
    Dialect.DRAFT201909: {
        "https://json-schema.org/draft/2019-09/vocab/applicator",
        "https://json-schema.org/draft/2019-09/vocab/content",
        "https://json-schema.org/draft/2019-09/vocab/core",
        "https://json-schema.org/draft/2019-09/vocab/format",
        "https://json-schema.org/draft/2019-09/vocab/meta-data",
        "https://json-schema.org/draft/2019-09/vocab/unevaluated",
        "https://json-schema.org/draft/2019-09/vocab/validation",
    },
    Dialect.DRAFT202012: {
        "https://json-schema.org/draft/2020-12/vocab/applicator",
        "https://json-schema.org/draft/2020-12/vocab/content",
        "https://json-schema.org/draft/2020-12/vocab/core",
        "https://json-schema.org/draft/2020-12/vocab/format-annotation",
        "https://json-schema.org/draft/2020-12/vocab/meta-data",
        "https://json-schema.org/draft/2020-12/vocab/unevaluated",
        "https://json-schema.org/draft/2020-12/vocab/validation",
    },
}

KNOWN_KEYWORDS_BY_DIALECT = {
    Dialect.DRAFT4: (
        IMPLEMENTED_VALIDATION_KEYWORDS
        | DRAFT4_TO_7_VALIDATION_KEYWORDS
        | ANNOTATION_KEYWORDS
        | CORE_AND_REFERENCE_KEYWORDS
        | {"id"}
    ),
    Dialect.DRAFT6: (
        IMPLEMENTED_VALIDATION_KEYWORDS
        | DRAFT4_TO_7_VALIDATION_KEYWORDS
        | DRAFT6_VALIDATION_KEYWORDS
        | ANNOTATION_KEYWORDS
        | CORE_AND_REFERENCE_KEYWORDS
        | {"$id"}
    ),
    Dialect.DRAFT7: (
        IMPLEMENTED_VALIDATION_KEYWORDS
        | DRAFT4_TO_7_VALIDATION_KEYWORDS
        | DRAFT6_VALIDATION_KEYWORDS
        | ANNOTATION_KEYWORDS
        | CORE_AND_REFERENCE_KEYWORDS
        | {"$id"}
        | {"else", "if", "then"}
    ),
    Dialect.DRAFT201909: (
        IMPLEMENTED_VALIDATION_KEYWORDS
        | DRAFT6_VALIDATION_KEYWORDS
        | ANNOTATION_KEYWORDS
        | CORE_AND_REFERENCE_KEYWORDS
        | {"$anchor", "$id", "$recursiveAnchor", "$recursiveRef", "$vocabulary"}
        | {
            "dependentRequired",
            "dependentSchemas",
            "else",
            "if",
            "maxContains",
            "minContains",
            "then",
            "unevaluatedItems",
            "unevaluatedProperties",
        }
    ),
    Dialect.DRAFT202012: (
        IMPLEMENTED_VALIDATION_KEYWORDS
        | DRAFT6_VALIDATION_KEYWORDS
        | ANNOTATION_KEYWORDS
        | CORE_AND_REFERENCE_KEYWORDS
        | {"$anchor", "$dynamicAnchor", "$dynamicRef", "$id", "$vocabulary"}
        | {
            "dependentRequired",
            "dependentSchemas",
            "else",
            "if",
            "maxContains",
            "minContains",
            "prefixItems",
            "then",
            "unevaluatedItems",
            "unevaluatedProperties",
        }
    ),
}

SUPPORTED_KEYWORDS = {
    dialect: frozenset(keywords)
    for dialect, keywords in KNOWN_KEYWORDS_BY_DIALECT.items()
}

_SCHEMA_ARRAY_KEYWORDS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_SCHEMA_MAP_KEYWORDS = {
    "$defs",
    "definitions",
    "dependentSchemas",
    "patternProperties",
    "properties",
}
_SCHEMA_VALUE_KEYWORDS = {
    "additionalItems",
    "additionalProperties",
    "contains",
    "else",
    "if",
    "items",
    "not",
    "propertyNames",
    "then",
    "unevaluatedItems",
    "unevaluatedProperties",
}


def normalize_dialect(dialect):
    if dialect is None:
        return None
    if isinstance(dialect, Dialect):
        return dialect

    normalized = str(dialect).strip().removesuffix("#").lower()
    try:
        return _ALIASES[normalized]
    except KeyError as err:
        raise UnknownDialectError(dialect) from err


def dialect_from_schema(schema):
    if isinstance(schema, Mapping) and "$schema" in schema:
        return normalize_dialect(schema["$schema"])
    return None


def resolve_dialect(*schemas, dialect=None):
    explicit_dialect = normalize_dialect(dialect)
    if explicit_dialect is not None:
        return explicit_dialect

    declared = {
        detected
        for detected in (dialect_from_schema(schema) for schema in schemas)
        if detected is not None
    }
    if len(declared) > 1:
        raise ConflictingDialectError(sorted(declared))
    return next(iter(declared), DEFAULT_DIALECT)


def known_keywords_for_dialect(dialect):
    return SUPPORTED_KEYWORDS[normalize_dialect(dialect) or DEFAULT_DIALECT]


def keyword_category(keyword):
    if keyword in ANNOTATION_KEYWORDS:
        return KeywordCategory.ANNOTATION
    if keyword in VOCABULARY_KEYWORDS:
        return KeywordCategory.VOCABULARY
    if keyword in UNEVALUATED_KEYWORDS:
        return KeywordCategory.UNEVALUATED
    if keyword in RESOURCE_KEYWORDS:
        return KeywordCategory.RESOURCE
    if keyword in APPLICATOR_KEYWORDS:
        return KeywordCategory.APPLICATOR
    if keyword in ASSERTION_KEYWORDS:
        return KeywordCategory.ASSERTION
    return KeywordCategory.UNKNOWN


def validate_supported_keywords(schema, dialect):
    dialect = normalize_dialect(dialect) or DEFAULT_DIALECT
    _validate_supported_keywords(schema, dialect, ())


def strip_inactive_keywords_for_dialect(schema, dialect):
    dialect = normalize_dialect(dialect) or DEFAULT_DIALECT
    return _strip_inactive_keywords(schema, dialect, None)


def _validate_supported_keywords(schema, dialect, path):
    if not isinstance(schema, Mapping):
        return

    dialect = dialect_from_schema(schema) or dialect
    for keyword, value in schema.items():
        if not _keyword_is_active_for_dialect(keyword, dialect):
            continue
        _raise_if_unsupported(keyword, value, dialect, path)
        _visit_subschemas(keyword, value, dialect, path + (keyword,))


def _raise_if_unsupported(keyword, value, dialect, path):
    if keyword_category(keyword) is KeywordCategory.VOCABULARY:
        _raise_if_unsupported_vocabulary(value, dialect, path)
        return

    if keyword in UNIMPLEMENTED_REFERENCE_KEYWORDS:
        raise UnsupportedKeywordError(keyword, dialect, path)

    if keyword in UNIMPLEMENTED_VALIDATION_KEYWORDS:
        raise UnsupportedKeywordError(keyword, dialect, path)


def _raise_if_unsupported_vocabulary(value, dialect, path):
    if not isinstance(value, Mapping):
        return

    supported = SUPPORTED_VOCABULARIES[dialect]
    for uri, required in value.items():
        if required is True and uri not in supported:
            raise UnsupportedKeywordError("$vocabulary", dialect, path + (str(uri),))


def _visit_subschemas(keyword, value, dialect, path):
    if not _keyword_is_active_for_dialect(keyword, dialect):
        return
    if keyword in _SCHEMA_VALUE_KEYWORDS:
        _validate_supported_keywords(value, dialect, path)
        return

    if keyword in _SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
        for index, item in enumerate(value):
            _validate_supported_keywords(item, dialect, path + (str(index),))
        return

    if keyword in _SCHEMA_MAP_KEYWORDS and isinstance(value, Mapping):
        for property_name, subschema in value.items():
            _validate_supported_keywords(
                subschema,
                dialect,
                path + (str(property_name),),
            )
        return

    if keyword == "dependencies" and isinstance(value, Mapping):
        for property_name, dependency in value.items():
            if isinstance(dependency, Mapping):
                _validate_supported_keywords(
                    dependency,
                    dialect,
                    path + (str(property_name),),
                )


def _strip_inactive_keywords(schema, dialect, keyword):
    if isinstance(schema, Mapping):
        dialect = dialect_from_schema(schema) or dialect
        if keyword in _SCHEMA_MAP_KEYWORDS:
            return {
                key: _strip_inactive_keywords(value, dialect, None)
                for key, value in schema.items()
            }
        if keyword == "dependencies":
            return {
                key: _strip_inactive_keywords(value, dialect, None)
                if isinstance(value, Mapping)
                else value
                for key, value in schema.items()
            }
        if keyword in {"$vocabulary", "dependentRequired"}:
            return dict(schema)
        stripped = {}
        for key, value in schema.items():
            if not _keyword_is_active_for_dialect(key, dialect):
                continue
            stripped[key] = _strip_inactive_keywords(value, dialect, key)
        return stripped
    if isinstance(schema, list):
        if keyword in _SCHEMA_ARRAY_KEYWORDS or keyword == "items":
            return [_strip_inactive_keywords(item, dialect, keyword) for item in schema]
        return schema
    return schema


def _keyword_is_active_for_dialect(keyword, dialect):
    if keyword in DRAFT4_TO_7_VALIDATION_KEYWORDS:
        return dialect in {Dialect.DRAFT4, Dialect.DRAFT6, Dialect.DRAFT7}
    if keyword == "id":
        return dialect is Dialect.DRAFT4
    if keyword == "$id":
        return dialect in {
            Dialect.DRAFT6,
            Dialect.DRAFT7,
            Dialect.DRAFT201909,
            Dialect.DRAFT202012,
        }
    if keyword in DRAFT6_VALIDATION_KEYWORDS:
        return dialect in {
            Dialect.DRAFT6,
            Dialect.DRAFT7,
            Dialect.DRAFT201909,
            Dialect.DRAFT202012,
        }
    if keyword in DRAFT201909_VALIDATION_KEYWORDS:
        return dialect in {Dialect.DRAFT201909, Dialect.DRAFT202012}
    if keyword in {"else", "if", "then"}:
        return dialect in {Dialect.DRAFT7, Dialect.DRAFT201909, Dialect.DRAFT202012}
    if keyword in UNEVALUATED_KEYWORDS:
        return dialect in {Dialect.DRAFT201909, Dialect.DRAFT202012}
    if keyword == "prefixItems":
        return dialect is Dialect.DRAFT202012
    if keyword == "additionalItems":
        return dialect is not Dialect.DRAFT202012
    if keyword in {"$dynamicAnchor", "$dynamicRef"}:
        return dialect is Dialect.DRAFT202012
    if keyword == "$anchor":
        return dialect in {Dialect.DRAFT201909, Dialect.DRAFT202012}
    if keyword in {"$recursiveAnchor", "$recursiveRef"}:
        return dialect is Dialect.DRAFT201909
    if keyword == "$vocabulary":
        return dialect in VOCABULARY_DIALECTS
    return True
