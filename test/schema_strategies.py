from __future__ import annotations

import json
from typing import Any

from hypothesis import strategies as st

from subschema import Dialect

JSON_VALUES: tuple[Any, ...] = (
    None,
    True,
    False,
    -2,
    -1,
    0,
    1,
    2,
    "",
    "a",
    "b",
    " ",
    [],
    [0],
    ["a"],
    {},
    {"a": 0},
    {"b": "a"},
)
JSON_EXAMPLES: tuple[Any, ...] = (None, True, False, -1, 0, 1, "", "a", "b")
JSON_ORACLE_INSTANCES: tuple[Any, ...] = (
    *JSON_EXAMPLES,
    [],
    [0],
    ["a"],
    {},
    {"a": 0},
    {"b": "a"},
    {"a": 0, "b": "a"},
)
TYPE_NAMES = ("null", "boolean", "integer", "number", "string", "array", "object")
PROPERTY_NAMES = ("a", "b", "kind", "name", "age")
SAFE_PATTERNS = ("", "^a$", "^[ab]{0,2}$", r"[\s\S]", r"^\s?$", r"^\S{0,2}$")
SIMPLE_PATTERNS = ("", "^a$", "^[ab]{0,2}$", r"[\s\S]")
INSTANCE_KEYS = (*PROPERTY_NAMES, "extra")
TYPE_SCHEMAS = (
    {"type": "null"},
    {"type": "boolean"},
    {"type": "integer"},
    {"type": "number"},
    {"type": "string"},
    {"type": "array"},
    {"type": "object"},
)


def stable_json_key(value: Any) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def random_json_instance() -> st.SearchStrategy[Any]:
    scalar = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-3, max_value=3),
        st.sampled_from(("", "a", "b", " ", "cat", "dog")),
    )
    return st.recursive(
        scalar,
        lambda children: st.one_of(
            st.lists(children, max_size=3),
            st.dictionaries(
                st.sampled_from(INSTANCE_KEYS),
                children,
                max_size=3,
            ),
        ),
        max_leaves=10,
    )


@st.composite
def random_schema(draw: st.DrawFn) -> Any:
    return draw(
        st.recursive(
            _random_leaf_schema(),
            _random_schema_extension,
            max_leaves=10,
        )
    )


def _random_leaf_schema() -> st.SearchStrategy[Any]:
    return st.one_of(
        st.booleans(),
        _type_schema(),
        _const_schema(JSON_VALUES),
        _enum_schema(JSON_VALUES, max_size=4),
        _numeric_schema(),
        _string_schema(SAFE_PATTERNS, max_length=4),
    )


def _type_schema(max_size: int = 4) -> st.SearchStrategy[dict[str, Any]]:
    single_type = st.sampled_from(TYPE_NAMES).map(lambda name: {"type": name})
    type_array = st.lists(
        st.sampled_from(TYPE_NAMES),
        min_size=1,
        max_size=max_size,
        unique=True,
    ).map(lambda names: {"type": names})
    return st.one_of(single_type, type_array)


def _const_schema(values: tuple[Any, ...]) -> st.SearchStrategy[dict[str, Any]]:
    return st.sampled_from(values).map(lambda value: {"const": value})


def _enum_schema(
    values: tuple[Any, ...],
    *,
    max_size: int,
) -> st.SearchStrategy[dict[str, Any]]:
    return st.lists(
        st.sampled_from(values),
        min_size=1,
        max_size=max_size,
        unique_by=stable_json_key,
    ).map(lambda enum_values: {"enum": enum_values})


@st.composite
def _numeric_schema(
    draw: st.DrawFn,
    *,
    min_bound: int = -4,
    max_bound: int = 4,
    multiples: tuple[int | float, ...] = (1, 2, 0.5),
    include_exclusive_bounds: bool = True,
) -> dict[str, Any]:
    lower = draw(st.integers(min_value=min_bound, max_value=max_bound - 1))
    upper = draw(st.integers(min_value=lower, max_value=max_bound))
    schema: dict[str, Any] = {
        "type": draw(st.sampled_from(("integer", "number"))),
        "minimum": lower,
        "maximum": upper,
    }
    if include_exclusive_bounds and draw(st.booleans()):
        schema["exclusiveMinimum"] = lower - 1
    if include_exclusive_bounds and draw(st.booleans()):
        schema["exclusiveMaximum"] = upper + 1
    if draw(st.booleans()):
        schema["multipleOf"] = draw(st.sampled_from(multiples))
    return schema


@st.composite
def _string_schema(
    draw: st.DrawFn,
    patterns: tuple[str, ...] = SAFE_PATTERNS,
    *,
    max_length: int = 4,
) -> dict[str, Any]:
    min_length = draw(st.integers(min_value=0, max_value=2))
    upper_length = draw(st.integers(min_value=min_length, max_value=max_length))
    schema: dict[str, Any] = {
        "type": "string",
        "minLength": min_length,
        "maxLength": upper_length,
    }
    if draw(st.booleans()):
        schema["pattern"] = draw(st.sampled_from(patterns))
    return schema


def _random_schema_extension(
    children: st.SearchStrategy[Any],
) -> st.SearchStrategy[Any]:
    return st.one_of(
        _applicator_schema(children),
        _conditional_schema(children),
        _object_schema(children),
        _array_schema(children),
        _annotation_schema(children),
    )


def _applicator_schema(children: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    all_of = st.lists(children, min_size=1, max_size=3).map(
        lambda schemas: {"allOf": schemas}
    )
    any_of = st.lists(children, min_size=1, max_size=3).map(
        lambda schemas: {"anyOf": schemas}
    )
    one_of = st.lists(children, min_size=1, max_size=3).map(
        lambda schemas: {"oneOf": schemas}
    )
    not_schema = children.map(lambda schema: {"not": schema})
    return st.one_of(all_of, any_of, one_of, not_schema)


@st.composite
def _conditional_schema(draw: st.DrawFn, children: st.SearchStrategy[Any]) -> dict[str, Any]:
    schema: dict[str, Any] = {"if": draw(children)}
    if draw(st.booleans()):
        schema["then"] = draw(children)
    if draw(st.booleans()):
        schema["else"] = draw(children)
    return schema


@st.composite
def _object_schema(draw: st.DrawFn, children: st.SearchStrategy[Any]) -> dict[str, Any]:
    property_names = draw(
        st.lists(st.sampled_from(PROPERTY_NAMES), unique=True, max_size=3)
    )
    properties = {name: draw(children) for name in property_names}
    required_strategy = (
        st.lists(st.sampled_from(property_names), unique=True)
        if property_names
        else st.just([])
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": draw(required_strategy),
    }
    if draw(st.booleans()):
        schema["additionalProperties"] = draw(st.one_of(st.booleans(), children))
    if draw(st.booleans()):
        schema["minProperties"] = draw(st.integers(min_value=0, max_value=2))
    if draw(st.booleans()):
        schema["maxProperties"] = draw(st.integers(min_value=2, max_value=4))
    if draw(st.booleans()):
        schema["propertyNames"] = draw(_string_schema())
    if draw(st.booleans()) and property_names:
        schema["dependentRequired"] = {
            property_names[0]: draw(
                st.lists(st.sampled_from(PROPERTY_NAMES), unique=True, max_size=2)
            )
        }
    if draw(st.booleans()) and property_names:
        schema["dependentSchemas"] = {property_names[0]: draw(children)}
    return schema


@st.composite
def _array_schema(draw: st.DrawFn, children: st.SearchStrategy[Any]) -> dict[str, Any]:
    prefix_items = draw(st.lists(children, min_size=0, max_size=3))
    schema: dict[str, Any] = {"type": "array"}
    if prefix_items:
        schema["prefixItems"] = prefix_items
    if draw(st.booleans()):
        schema["items"] = draw(st.one_of(st.booleans(), children))
    min_items = draw(st.integers(min_value=0, max_value=3))
    max_items = draw(st.integers(min_value=min_items, max_value=4))
    if draw(st.booleans()):
        schema["minItems"] = min_items
    if draw(st.booleans()):
        schema["maxItems"] = max_items
    if draw(st.booleans()):
        schema["uniqueItems"] = True
    if draw(st.booleans()):
        schema["contains"] = draw(children)
        min_contains = draw(st.integers(min_value=0, max_value=2))
        max_contains = draw(st.integers(min_value=min_contains, max_value=3))
        schema["minContains"] = min_contains
        schema["maxContains"] = max_contains
    return schema


@st.composite
def _annotation_schema(draw: st.DrawFn, children: st.SearchStrategy[Any]) -> dict[str, Any]:
    schema = draw(children)
    if not isinstance(schema, dict):
        schema = {"const": schema}
    annotated = dict(schema)
    annotated["title"] = draw(st.sampled_from(("Generated", "Random", "")))
    annotated["description"] = draw(st.sampled_from(("schema", "property test", "")))
    if draw(st.booleans()):
        annotated["default"] = draw(st.sampled_from(JSON_VALUES))
    if draw(st.booleans()):
        annotated["examples"] = draw(
            st.lists(st.sampled_from(JSON_VALUES), max_size=3)
        )
    return annotated


@st.composite
def random_resource_schema(draw: st.DrawFn) -> dict[str, Any]:
    target = draw(
        st.one_of(
            st.booleans(),
            _type_schema(),
            _const_schema(JSON_VALUES),
            _enum_schema(JSON_VALUES, max_size=4),
            _numeric_schema(),
            _string_schema(SAFE_PATTERNS, max_length=4),
        )
    )
    kind = draw(st.sampled_from(("defs-ref", "allof-ref", "nested-defs", "anchor")))
    if kind == "defs-ref":
        return {"$defs": {"target": target}, "$ref": "#/$defs/target"}
    if kind == "allof-ref":
        return {
            "$defs": {"target": target},
            "allOf": [{"$ref": "#/$defs/target"}],
        }
    if kind == "nested-defs":
        return {
            "$defs": {
                "outer": {
                    "$defs": {"inner": target},
                    "$ref": "#/$defs/outer/$defs/inner",
                }
            },
            "$ref": "#/$defs/outer",
        }
    return {
        "$defs": {"target": _anchored_target(target)},
        "$ref": "#target",
    }


def _anchored_target(target: Any) -> dict[str, Any]:
    if isinstance(target, dict):
        return {"$anchor": "target", **target}
    return {"$anchor": "target", "allOf": [target]}


@st.composite
def random_external_resource_case(
    draw: st.DrawFn,
) -> tuple[Any, dict[str, Any]]:
    uri = "https://example.com/generated/root.json"
    target = draw(
        st.one_of(
            st.booleans(),
            _type_schema(),
            _const_schema(JSON_VALUES),
            _enum_schema(JSON_VALUES, max_size=4),
            _numeric_schema(),
            _string_schema(SAFE_PATTERNS, max_length=4),
        )
    )
    kind = draw(
        st.sampled_from(
            (
                "direct",
                "canonical-id",
                "root-anchor",
                "embedded-canonical-anchor",
                "registered-sibling",
                "dialect-transition",
            )
        )
    )
    if kind == "canonical-id":
        return (
            {"$ref": uri},
            {
                "https://example.com/generated/loader.json": (
                    _resource_document(target, uri)
                )
            },
        )
    if kind == "root-anchor":
        return (
            {"$ref": f"{uri}#target"},
            {uri: _resource_anchor_document(target, uri)},
        )
    if kind == "embedded-canonical-anchor":
        embedded_uri = "https://example.com/generated/defs/target.json"
        return (
            {"$ref": f"{embedded_uri}#target"},
            {
                uri: {
                    "$id": uri,
                    "$defs": {
                        "target": _resource_anchor_document(
                            target,
                            "defs/target.json",
                        )
                    },
                }
            },
        )
    if kind == "registered-sibling":
        return (
            {"$ref": uri},
            {
                uri: {
                    "$id": uri,
                    "$ref": "defs/target.json",
                },
                "https://example.com/generated/defs/target.json": (
                    _resource_document(target)
                ),
            },
        )
    if kind == "dialect-transition":
        return (
            {"$ref": uri},
            {
                uri: _resource_document(
                    target,
                    uri,
                    schema_uri="http://json-schema.org/draft-07/schema#",
                )
            },
        )
    return {"$ref": uri}, {uri: _resource_document(target)}


def _resource_document(
    target: Any,
    uri: str | None = None,
    *,
    schema_uri: str | None = None,
) -> dict[str, Any]:
    document = dict(target) if isinstance(target, dict) else {"allOf": [target]}
    if schema_uri is not None:
        document["$schema"] = schema_uri
    if uri is not None:
        document["$id"] = uri
    return document


def _resource_anchor_document(target: Any, uri: str | None = None) -> dict[str, Any]:
    document = _resource_document(target, uri)
    document["$anchor"] = "target"
    return document


@st.composite
def dialect_schema(draw: st.DrawFn) -> tuple[Dialect, Any]:
    dialect = draw(st.sampled_from(tuple(Dialect)))
    return dialect, draw(_schema_for_dialect(dialect))


@st.composite
def dialect_schema_pair(draw: st.DrawFn) -> tuple[Dialect, Any, Any]:
    dialect = draw(st.sampled_from(tuple(Dialect)))
    schema = _schema_for_dialect(dialect)
    return dialect, draw(schema), draw(schema)


def _schema_for_dialect(dialect: Dialect) -> st.SearchStrategy[Any]:
    return st.recursive(
        _leaf_schema_for_dialect(dialect),
        lambda children: _extension_schema_for_dialect(dialect, children),
        max_leaves=8,
    )


def _leaf_schema_for_dialect(dialect: Dialect) -> st.SearchStrategy[Any]:
    leaves = [
        _type_schema(max_size=3),
        _enum_schema(JSON_EXAMPLES, max_size=3),
        _numeric_schema(
            min_bound=-3,
            max_bound=3,
            multiples=(1, 2),
            include_exclusive_bounds=False,
        ),
        _string_schema(SIMPLE_PATTERNS, max_length=3),
    ]
    if dialect is not Dialect.DRAFT4:
        leaves.extend(
            (
                st.booleans(),
                _const_schema(JSON_EXAMPLES),
            )
        )
    return st.one_of(*leaves)


def _extension_schema_for_dialect(
    dialect: Dialect,
    children: st.SearchStrategy[Any],
) -> st.SearchStrategy[Any]:
    extensions = [
        _applicator_schema(children),
        _object_schema_for_dialect(dialect, children),
        _array_schema_for_dialect(dialect, children),
    ]
    if dialect in {Dialect.DRAFT7, Dialect.DRAFT201909, Dialect.DRAFT202012}:
        extensions.append(_conditional_schema(children))
    return st.one_of(*extensions)


@st.composite
def _object_schema_for_dialect(
    draw: st.DrawFn,
    dialect: Dialect,
    children: st.SearchStrategy[Any],
) -> dict[str, Any]:
    property_names = draw(
        st.lists(st.sampled_from(("a", "b")), unique=True, max_size=2)
    )
    properties = {name: draw(children) for name in property_names}
    required = draw(
        st.lists(st.sampled_from(property_names), unique=True)
        if property_names
        else st.just([])
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required or dialect is not Dialect.DRAFT4:
        schema["required"] = required
    if draw(st.booleans()):
        schema["additionalProperties"] = draw(st.one_of(st.booleans(), children))
    if dialect in {
        Dialect.DRAFT6,
        Dialect.DRAFT7,
        Dialect.DRAFT201909,
        Dialect.DRAFT202012,
    } and draw(st.booleans()):
        schema["propertyNames"] = draw(_string_schema(SIMPLE_PATTERNS, max_length=3))
    if dialect in {Dialect.DRAFT201909, Dialect.DRAFT202012} and draw(st.booleans()):
        schema["dependentRequired"] = {
            "a": draw(st.lists(st.sampled_from(("a", "b")), unique=True))
        }
    return schema


@st.composite
def _array_schema_for_dialect(
    draw: st.DrawFn,
    dialect: Dialect,
    children: st.SearchStrategy[Any],
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array"}
    prefix_items = draw(st.lists(children, max_size=2))
    if dialect is Dialect.DRAFT202012:
        if prefix_items:
            schema["prefixItems"] = prefix_items
        if draw(st.booleans()):
            schema["items"] = draw(st.one_of(st.booleans(), children))
    else:
        if prefix_items and draw(st.booleans()):
            schema["items"] = prefix_items
            if draw(st.booleans()):
                schema["additionalItems"] = draw(st.one_of(st.booleans(), children))
        elif draw(st.booleans()):
            schema["items"] = draw(children)
    min_items = draw(st.integers(min_value=0, max_value=2))
    max_items = draw(st.integers(min_value=min_items, max_value=3))
    if draw(st.booleans()):
        schema["minItems"] = min_items
    if draw(st.booleans()):
        schema["maxItems"] = max_items
    if draw(st.booleans()):
        schema["uniqueItems"] = True
    if dialect is not Dialect.DRAFT4 and draw(st.booleans()):
        schema["contains"] = draw(children)
    if dialect in {Dialect.DRAFT201909, Dialect.DRAFT202012} and "contains" in schema:
        min_contains = draw(st.integers(min_value=0, max_value=2))
        max_contains = draw(st.integers(min_value=min_contains, max_value=3))
        schema["minContains"] = min_contains
        schema["maxContains"] = max_contains
    return schema


@st.composite
def simple_schema(draw: st.DrawFn) -> Any:
    return draw(
        st.one_of(
            st.booleans(),
            st.sampled_from(TYPE_SCHEMAS).map(dict),
            _const_schema(JSON_EXAMPLES),
            _enum_schema(JSON_EXAMPLES, max_size=3),
            _numeric_schema(
                min_bound=-3,
                max_bound=4,
                multiples=(1, 2),
                include_exclusive_bounds=False,
            ),
            _string_schema(SIMPLE_PATTERNS, max_length=3),
            _closed_object_schema(),
            _fixed_tuple_schema(),
        )
    )


def covered_schema() -> st.SearchStrategy[Any]:
    return st.recursive(
        simple_schema(),
        lambda children: st.one_of(
            _all_of_schema(children),
            _any_of_schema(children),
            _finite_one_of_schema(),
            _nested_closed_object_schema(children),
            _nested_fixed_tuple_schema(children),
        ),
        max_leaves=8,
    )


@st.composite
def _closed_object_schema(draw: st.DrawFn) -> dict[str, Any]:
    property_names = draw(
        st.lists(st.sampled_from(("a", "b")), unique=True, max_size=2)
    )
    properties = {
        name: draw(st.sampled_from(TYPE_SCHEMAS).map(dict))
        for name in property_names
    }
    required_strategy = (
        st.lists(st.sampled_from(property_names), unique=True)
        if property_names
        else st.just([])
    )
    required = draw(required_strategy)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


@st.composite
def _fixed_tuple_schema(draw: st.DrawFn) -> dict[str, Any]:
    item_schemas = draw(
        st.lists(st.sampled_from(TYPE_SCHEMAS).map(dict), min_size=0, max_size=3)
    )
    length = len(item_schemas)
    if length == 0:
        return {
            "type": "array",
            "items": False,
            "minItems": 0,
            "maxItems": 0,
        }
    return {
        "type": "array",
        "prefixItems": item_schemas,
        "items": False,
        "minItems": length,
        "maxItems": length,
    }


def _all_of_schema(
    children: st.SearchStrategy[Any],
) -> st.SearchStrategy[dict[str, Any]]:
    return st.lists(children, min_size=1, max_size=3).map(
        lambda schemas: {"allOf": schemas}
    )


def _any_of_schema(
    children: st.SearchStrategy[Any],
) -> st.SearchStrategy[dict[str, Any]]:
    return st.lists(children, min_size=1, max_size=3).map(
        lambda schemas: {"anyOf": schemas}
    )


def _finite_one_of_schema() -> st.SearchStrategy[dict[str, Any]]:
    return st.lists(
        st.sampled_from(JSON_EXAMPLES),
        min_size=1,
        max_size=3,
        unique_by=stable_json_key,
    ).map(lambda values: {"oneOf": [{"const": value} for value in values]})


@st.composite
def _nested_closed_object_schema(
    draw: st.DrawFn, children: st.SearchStrategy[Any]
) -> dict[str, Any]:
    property_names = draw(
        st.lists(st.sampled_from(("a", "b")), unique=True, max_size=2)
    )
    properties = {name: draw(children) for name in property_names}
    required_strategy = (
        st.lists(st.sampled_from(property_names), unique=True)
        if property_names
        else st.just([])
    )
    required = draw(required_strategy)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


@st.composite
def _nested_fixed_tuple_schema(
    draw: st.DrawFn, children: st.SearchStrategy[Any]
) -> dict[str, Any]:
    item_schemas = draw(st.lists(children, min_size=0, max_size=3))
    length = len(item_schemas)
    if length == 0:
        return {
            "type": "array",
            "items": False,
            "minItems": 0,
            "maxItems": 0,
        }
    return {
        "type": "array",
        "prefixItems": item_schemas,
        "items": False,
        "minItems": length,
        "maxItems": length,
    }
