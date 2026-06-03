"""
JSON type-set reasoning for exact subschema proofs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from subschema.kernel.literals import explicit_finite_values_for_schema
from subschema.kernel.regex import RegexLanguage
from subschema.kernel.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
    schema_is_true,
)
from subschema.kernel.values import dedupe, json_semantic_key

JSON_TYPE_ATOMS = frozenset(
    {"null", "boolean", "integer", "number", "string", "array", "object"}
)

TYPE_SCHEMA_KEYWORDS = frozenset({"allOf", "anyOf", "not", "oneOf", "type"})
TYPE_TRANSPARENT_ASSERTION_KEYWORDS = frozenset(
    {
        "additionalItems",
        "additionalProperties",
        "contains",
        "dependentRequired",
        "dependentSchemas",
        "dependencies",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "items",
        "maxContains",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minContains",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "multipleOf",
        "pattern",
        "patternProperties",
        "prefixItems",
        "properties",
        "propertyNames",
        "required",
        "uniqueItems",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)

_ATOM_RESTRICTIVE_KEYWORDS = {
    "array": frozenset(
        {
            "additionalItems",
            "contains",
            "items",
            "maxContains",
            "maxItems",
            "minContains",
            "minItems",
            "prefixItems",
            "unevaluatedItems",
            "uniqueItems",
        }
    ),
    "boolean": frozenset(),
    "integer": frozenset(
        {"exclusiveMaximum", "exclusiveMinimum", "maximum", "minimum", "multipleOf"}
    ),
    "null": frozenset(),
    "number": frozenset(
        {"exclusiveMaximum", "exclusiveMinimum", "maximum", "minimum", "multipleOf"}
    ),
    "object": frozenset(
        {
            "additionalProperties",
            "dependencies",
            "dependentRequired",
            "dependentSchemas",
            "maxProperties",
            "minProperties",
            "patternProperties",
            "properties",
            "propertyNames",
            "required",
            "unevaluatedProperties",
        }
    ),
    "string": frozenset({"maxLength", "minLength", "pattern"}),
}

__all__ = [
    "JSON_TYPE_ATOMS",
    "TYPE_SCHEMA_KEYWORDS",
    "TypeShape",
    "schema_covers_type_atom",
    "schema_type_overapproximations_are_disjoint",
    "type_language_complete_for_schema",
    "type_overapproximation_for_schema",
    "type_shape_for_type_keyword",
    "type_shape_for_schema",
    "witness_for_type_atom",
]

@dataclass(frozen=True)
class TypeShape:
    atoms: frozenset[str]

    def is_subset_of(self, other: TypeShape) -> bool:
        return self.atoms <= other.atoms

    def witness_not_in(self, other: TypeShape) -> Any | None:
        for atom in sorted(self.atoms - other.atoms):
            return witness_for_type_atom(atom)
        return None

    def intersect(self, other: TypeShape) -> TypeShape:
        return TypeShape(self.atoms & other.atoms)

    def union(self, other: TypeShape) -> TypeShape:
        return TypeShape(self.atoms | other.atoms)

    def complement(self) -> TypeShape:
        return TypeShape(JSON_TYPE_ATOMS - self.atoms)


def schema_type_overapproximations_are_disjoint(lhs: Any, rhs: Any) -> bool:
    return not type_overapproximation_for_schema(lhs).intersection(
        type_overapproximation_for_schema(rhs)
    )


def schema_covers_type_atom(schema: Any, atom: str, depth: int = 0) -> bool:
    if depth > 16 or atom not in JSON_TYPE_ATOMS:
        return False
    if schema is True:
        return True
    if schema is False or not isinstance(schema, dict):
        return False
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return False

    finite_values = _finite_values_for_type_reasoning(schema)
    if finite_values is not None:
        if atom == "boolean":
            return any(value is False for value in finite_values) and any(
                value is True for value in finite_values
            )
        if atom == "null":
            return any(value is None for value in finite_values)
        return False

    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None or atom not in type_shape.atoms:
        return False

    for subschema in schema.get("allOf", []):
        if not schema_covers_type_atom(subschema, atom, depth + 1):
            return False

    if "anyOf" in schema and not any(
        schema_covers_type_atom(subschema, atom, depth + 1)
        for subschema in schema["anyOf"]
    ):
        return False

    if "oneOf" in schema:
        covering = [
            index
            for index, subschema in enumerate(schema["oneOf"])
            if schema_covers_type_atom(subschema, atom, depth + 1)
        ]
        if len(covering) != 1:
            return False
        for index, subschema in enumerate(schema["oneOf"]):
            if index != covering[0] and atom in type_overapproximation_for_schema(
                subschema, depth + 1
            ):
                return False

    if "not" in schema and atom in type_overapproximation_for_schema(
        schema["not"], depth + 1
    ):
        return False

    applicator_keys = {"allOf", "anyOf", "oneOf", "not"}
    for key in schema:
        if (
            key in IGNORED_SCHEMA_METADATA_KEYS
            or key == "type"
            or key in applicator_keys
        ):
            continue
        if key in _ATOM_RESTRICTIVE_KEYWORDS[atom]:
            return False
        if key in TYPE_TRANSPARENT_ASSERTION_KEYWORDS:
            continue
        return False
    return True


def type_overapproximation_for_schema(schema: Any, depth: int = 0) -> frozenset[str]:
    if depth > 16:
        return JSON_TYPE_ATOMS
    if schema is False:
        return frozenset()
    if schema is True:
        return JSON_TYPE_ATOMS
    if not isinstance(schema, dict):
        return JSON_TYPE_ATOMS
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return JSON_TYPE_ATOMS
    finite_shape = _finite_value_type_shape(schema)
    if finite_shape is not None:
        return finite_shape.atoms

    type_shape = type_shape_for_type_keyword(schema.get("type"))
    atoms = type_shape.atoms if type_shape is not None else JSON_TYPE_ATOMS

    for subschema in schema.get("allOf", []):
        atoms &= type_overapproximation_for_schema(subschema, depth + 1)

    if "anyOf" in schema:
        any_atoms: frozenset[str] = frozenset()
        for subschema in schema["anyOf"]:
            any_atoms |= type_overapproximation_for_schema(subschema, depth + 1)
        atoms &= any_atoms

    if "oneOf" in schema:
        one_of_atoms: frozenset[str] = frozenset()
        for subschema in schema["oneOf"]:
            one_of_atoms |= type_overapproximation_for_schema(subschema, depth + 1)
        atoms &= one_of_atoms

    return atoms


def type_shape_for_schema(schema: Any, depth: int = 0) -> TypeShape | None:
    if depth > 16:
        return None
    if schema is True:
        return TypeShape(JSON_TYPE_ATOMS)
    if schema is False:
        return TypeShape(frozenset())
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    if _contains_unsupported_regex(schema):
        return None
    finite_shape = _finite_value_type_shape(schema)
    if finite_shape is not None:
        return finite_shape
    if not _is_type_fragment_schema(schema):
        return None

    shape = type_shape_for_type_keyword(schema.get("type"))
    if shape is None:
        return None

    for subschema in schema.get("allOf", []):
        branch = type_shape_for_schema(subschema, depth + 1)
        if branch is None:
            return None
        shape = shape.intersect(branch)

    if "anyOf" in schema:
        any_shape = TypeShape(frozenset())
        for subschema in schema["anyOf"]:
            branch = type_shape_for_schema(subschema, depth + 1)
            if branch is None:
                return None
            any_shape = any_shape.union(branch)
        shape = shape.intersect(any_shape)

    if "oneOf" in schema:
        one_of_shape = _one_of_true_complement_type_shape(schema["oneOf"], depth)
        if one_of_shape is None:
            one_of_shape = TypeShape(frozenset())
            for subschema in schema["oneOf"]:
                branch = type_shape_for_schema(subschema, depth + 1)
                if branch is None:
                    return None
                one_of_shape = one_of_shape.union(branch)
        shape = shape.intersect(one_of_shape)

    if "not" in schema:
        negated = _finite_exhausted_type_shape(schema["not"])
        if negated is None:
            negated = type_shape_for_schema(schema["not"], depth + 1)
            if negated is not None and not type_language_complete_for_schema(
                schema["not"], depth + 1
            ):
                negated = TypeShape(frozenset())
        if negated is None:
            return None
        shape = shape.intersect(negated.complement())

    return shape


def witness_for_type_atom(atom: str) -> Any:
    return {
        "array": [],
        "boolean": True,
        "integer": 0,
        "null": None,
        "number": 0.5,
        "object": {},
        "string": "",
    }[atom]


def _is_type_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key in TYPE_SCHEMA_KEYWORDS:
            if key in {"allOf", "anyOf", "oneOf"} and not isinstance(value, list):
                return False
            continue
        if key in TYPE_TRANSPARENT_ASSERTION_KEYWORDS:
            continue
        return False
    return True


def type_language_complete_for_schema(schema: Any, depth: int = 0) -> bool:
    if schema is True or schema is False:
        return True
    if depth > 16 or not isinstance(schema, dict):
        return False
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return False
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS or key == "type":
            continue
        if key in {"allOf", "anyOf"} and isinstance(value, list):
            if not all(
                type_language_complete_for_schema(subschema, depth + 1)
                for subschema in value
            ):
                return False
            continue
        if key == "oneOf" and isinstance(value, list):
            if not _one_of_type_language_complete(value, depth):
                return False
            continue
        if key == "not":
            exhausted = _finite_exhausted_type_shape(value)
            if exhausted is not None:
                if exhausted.atoms:
                    continue
                return False
            negated = type_shape_for_schema(value, depth + 1)
            if negated is not None and type_language_complete_for_schema(
                value, depth + 1
            ):
                continue
        return False
    return True


def _one_of_type_language_complete(subschemas: list[Any], depth: int) -> bool:
    if _one_of_true_complement_type_shape(subschemas, depth) is not None:
        return True
    shapes = []
    for subschema in subschemas:
        if not type_language_complete_for_schema(subschema, depth + 1):
            return False
        shape = type_shape_for_schema(subschema, depth + 1)
        if shape is None:
            return False
        shapes.append(shape)
    return all(
        lhs.atoms.isdisjoint(rhs.atoms)
        for index, lhs in enumerate(shapes)
        for rhs in shapes[index + 1 :]
    )


def _one_of_true_complement_type_shape(
    subschemas: list[Any], depth: int
) -> TypeShape | None:
    if len(subschemas) != 2:
        return None
    if schema_is_true(subschemas[0]):
        complement = subschemas[1]
    elif schema_is_true(subschemas[1]):
        complement = subschemas[0]
    else:
        return None
    if not type_language_complete_for_schema(complement, depth + 1):
        return None
    complement_shape = type_shape_for_schema(complement, depth + 1)
    if complement_shape is None:
        return None
    return complement_shape.complement()


def _contains_unsupported_regex(schema: Any) -> bool:
    if isinstance(schema, list):
        return any(_contains_unsupported_regex(item) for item in schema)
    if not isinstance(schema, dict):
        return False
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and not isinstance(
        RegexLanguage.from_json_regex(pattern), RegexLanguage
    ):
        return True
    property_names = schema.get("propertyNames")
    if isinstance(property_names, dict) and _contains_unsupported_regex(property_names):
        return True
    pattern_properties = schema.get("patternProperties")
    if isinstance(pattern_properties, dict):
        for property_pattern, subschema in pattern_properties.items():
            if (
                isinstance(property_pattern, str)
                and not isinstance(
                    RegexLanguage.from_json_regex(property_pattern), RegexLanguage
                )
            ) or _contains_unsupported_regex(subschema):
                return True
    return any(
        _contains_unsupported_regex(value)
        for key, value in schema.items()
        if key in {"allOf", "anyOf", "oneOf", "not", "if", "then", "else"}
    )


def _finite_exhausted_type_shape(schema: Any) -> TypeShape | None:
    values = _finite_values_for_type_reasoning(schema)
    if values is None:
        return None
    removed_atoms = set()
    if any(value is None for value in values):
        removed_atoms.add("null")
    if any(value is False for value in values) and any(
        value is True for value in values
    ):
        removed_atoms.add("boolean")
    return TypeShape(frozenset(removed_atoms))


def _finite_value_type_shape(schema: Any) -> TypeShape | None:
    values = _finite_values_for_type_reasoning(schema)
    if values is None:
        return None
    atoms = {_json_type_atom(value) for value in values}
    return TypeShape(frozenset(atoms))


def _json_type_atom(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "integer" if value.is_integer() else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "object"


def _finite_values_for_type_reasoning(
    schema: Any, depth: int = 0
) -> list[Any] | None:
    if depth > 8:
        return None
    explicit_values = explicit_finite_values_for_schema(schema)
    if explicit_values is not None:
        return explicit_values
    if not isinstance(schema, dict):
        return None

    double_negated = _double_negated_schema(schema)
    if double_negated is not None:
        return _finite_values_for_type_reasoning(double_negated, depth + 1)
    if "not" in schema and schema_is_true(schema["not"]):
        return []

    type_values = _finite_values_for_type_keyword(schema.get("type"))
    if type_values is not None:
        return type_values

    if "allOf" in schema and isinstance(schema["allOf"], list):
        return _all_of_finite_values_for_type_reasoning(schema["allOf"], depth)
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        values: list[Any] = []
        for subschema in schema["anyOf"]:
            branch = _finite_values_for_type_reasoning(subschema, depth + 1)
            if branch is None:
                return None
            values.extend(branch)
        return dedupe(values)
    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        branches = []
        for subschema in schema["oneOf"]:
            branch = _finite_values_for_type_reasoning(subschema, depth + 1)
            if branch is None:
                return None
            branches.append(branch)
        return _one_of_finite_values(branches)
    return None


def _finite_values_for_type_keyword(type_keyword: Any) -> list[Any] | None:
    if isinstance(type_keyword, str):
        atoms = {type_keyword}
    elif isinstance(type_keyword, list) and all(
        isinstance(item, str) for item in type_keyword
    ):
        atoms = set(type_keyword)
    else:
        return None
    if not atoms <= {"boolean", "null"}:
        return None
    values: list[Any] = []
    if "boolean" in atoms:
        values.extend((False, True))
    if "null" in atoms:
        values.append(None)
    return values


def _all_of_finite_values_for_type_reasoning(
    subschemas: list[Any], depth: int
) -> list[Any] | None:
    finite_branches = []
    for subschema in subschemas:
        branch = _finite_values_for_type_reasoning(subschema, depth + 1)
        if branch == []:
            return []
        if branch is not None:
            finite_branches.append(branch)
    if not finite_branches:
        return None

    values = finite_branches[0]
    for branch in finite_branches[1:]:
        branch_keys = {json_semantic_key(value) for value in branch}
        values = [
            value for value in values if json_semantic_key(value) in branch_keys
        ]
    return dedupe(values)


def _one_of_finite_values(branches: list[list[Any]]) -> list[Any]:
    counts: dict[str, tuple[Any, int]] = {}
    for branch in branches:
        for value in dedupe(branch):
            key = json_semantic_key(value)
            representative, count = counts.get(key, (value, 0))
            counts[key] = (representative, count + 1)
    return dedupe(
        [representative for representative, count in counts.values() if count == 1]
    )


def _double_negated_schema(schema: dict[str, Any]) -> Any | None:
    negated = schema.get("not")
    if not isinstance(negated, dict):
        return None
    inner = negated.get("not")
    return inner if isinstance(inner, bool | dict) else None


def type_shape_for_type_keyword(schema_type: Any) -> TypeShape | None:
    if schema_type is None:
        return TypeShape(JSON_TYPE_ATOMS)
    if isinstance(schema_type, str):
        return _type_shape_for_names({schema_type})
    if isinstance(schema_type, list):
        if not all(isinstance(name, str) for name in schema_type):
            return None
        return _type_shape_for_names(set(schema_type))
    return None


def _type_shape_for_names(names: set[str]) -> TypeShape | None:
    atoms = set()
    for name in names:
        if name == "number":
            atoms.update({"integer", "number"})
        elif name in JSON_TYPE_ATOMS:
            atoms.add(name)
        else:
            return None
    return TypeShape(frozenset(atoms))
