"""
Constructive schema-inhabitant helpers for proof-kernel SAT rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from subschema.dialects import Dialect
from subschema.kernel.contracts import CounterexampleCertificate, ProofResult
from subschema.kernel.domains.numbers import numeric_shape_for_schema
from subschema.kernel.domains.strings import (
    string_language_shape_for_schema,
    string_language_witness,
)
from subschema.kernel.domains.types import (
    type_overapproximation_for_schema,
    witness_for_type_atom,
)
from subschema.kernel.finite import finite_values_for_schema
from subschema.kernel.references import ResourceGraph
from subschema.kernel.regex import RegexLanguage
from subschema.kernel.values import json_semantic_key

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext

WitnessBuildStatus = Literal[
    "certificate", "resource_exhausted", "unsupported", "witness"
]

_MAX_MATERIALIZED_ARRAY_LENGTH = 1024
_MAX_MATERIALIZED_OBJECT_PROPERTIES = 512

__all__ = [
    "WitnessBuildResult",
    "WitnessBuilder",
    "build_schema_witness",
    "finite_projection_witness",
]


@dataclass(frozen=True)
class WitnessBuildResult:
    status: WitnessBuildStatus
    witness: Any = None
    certificate: CounterexampleCertificate | None = None
    reason: str = ""

    @classmethod
    def concrete(cls, witness: Any) -> WitnessBuildResult:
        return cls("witness", witness=witness)

    @classmethod
    def certified(cls, certificate: CounterexampleCertificate) -> WitnessBuildResult:
        return cls("certificate", certificate=certificate, reason=certificate.reason)

    @classmethod
    def unsupported(cls, reason: str) -> WitnessBuildResult:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> WitnessBuildResult:
        return cls("resource_exhausted", reason=reason)

    @property
    def has_witness(self) -> bool:
        return self.status == "witness"

    def as_proof_result(self) -> ProofResult:
        if self.status == "witness":
            return ProofResult.false(self.witness)
        if self.status == "certificate" and self.certificate is not None:
            return ProofResult.certified_false(self.certificate)
        if self.status == "resource_exhausted":
            return ProofResult.resource_exhausted(self.reason)
        return ProofResult.unsupported(self.reason)


@dataclass(frozen=True)
class WitnessBuilder:
    dialect: Dialect
    context: ProofContext | None = None

    def build(self, schema: Any) -> WitnessBuildResult:
        return self._build(schema, depth=0)

    def _build(self, schema: Any, *, depth: int) -> WitnessBuildResult:
        if depth > 16:
            return WitnessBuildResult.unsupported(
                "schema witness construction exceeded supported nesting depth"
            )
        if schema is True:
            return WitnessBuildResult.concrete(None)
        if schema is False:
            return WitnessBuildResult.unsupported("false schema is uninhabited")

        finite = finite_projection_witness(schema, self.dialect)
        if finite.has_witness:
            return finite
        if not isinstance(schema, dict):
            return WitnessBuildResult.unsupported(
                "schema witness construction requires a schema object"
            )

        all_of = self._all_of_witness(schema, depth=depth)
        if all_of.has_witness or all_of.status in {"certificate", "resource_exhausted"}:
            return all_of

        finite_values = _finite_values_for_schema(schema, self.dialect)
        if finite_values:
            return WitnessBuildResult.concrete(finite_values[0])

        branch = self._applicator_witness(schema, depth=depth)
        if branch.has_witness or branch.status in {"certificate", "resource_exhausted"}:
            return branch

        numeric = self._numeric_witness(schema)
        if numeric.has_witness or numeric.status == "resource_exhausted":
            return numeric

        string = self._string_witness(schema)
        if string.has_witness or string.status == "resource_exhausted":
            return string

        array = self._array_witness(schema, depth=depth)
        if array.has_witness or array.status in {"certificate", "resource_exhausted"}:
            return array

        obj = self._object_witness(schema, depth=depth)
        if obj.has_witness or obj.status in {"certificate", "resource_exhausted"}:
            return obj

        return self._type_witness(schema)

    def _numeric_witness(self, schema: dict[str, Any]) -> WitnessBuildResult:
        shape = numeric_shape_for_schema(schema, self.dialect)
        if shape is None:
            return WitnessBuildResult.unsupported(
                "schema witness construction has no exact numeric shape"
            )
        for atom in shape.normalized_atoms():
            value = atom.some_fraction()
            if value is not None:
                return WitnessBuildResult.concrete(
                    int(value) if value.denominator == 1 else float(value)
                )
        return WitnessBuildResult.unsupported("numeric schema is uninhabited")

    def _string_witness(self, schema: dict[str, Any]) -> WitnessBuildResult:
        shape = string_language_shape_for_schema(schema)
        if shape is None:
            return WitnessBuildResult.unsupported(
                "schema witness construction has no exact string language"
            )
        if shape.accepts_non_string:
            return WitnessBuildResult.unsupported(
                "string language shape is not string-only"
            )
        witness = string_language_witness(shape.pattern, self.context)
        if isinstance(witness, ProofResult):
            if witness.status == "resource_exhausted":
                return WitnessBuildResult.resource_exhausted(
                    witness.reason or "regex witness exceeded proof work budget"
                )
            return WitnessBuildResult.unsupported(
                witness.reason or "regex witness could not be constructed"
            )
        if witness is None:
            return WitnessBuildResult.unsupported("string schema is uninhabited")
        return WitnessBuildResult.concrete(witness)

    def _array_witness(
        self, schema: dict[str, Any], *, depth: int
    ) -> WitnessBuildResult:
        if "allOf" in schema:
            return WitnessBuildResult.unsupported(
                "array allOf witness requires mergeable array constraints"
            )
        if not _schema_allows_array_witness(schema):
            return WitnessBuildResult.unsupported(
                "schema does not require an array witness"
            )
        minimum = schema.get("minItems", 0)
        if not isinstance(minimum, int) or isinstance(minimum, bool):
            minimum = 0
        contains = schema.get("contains")
        min_contains = schema.get("minContains", 1 if contains is not None else 0)
        if not isinstance(min_contains, int) or isinstance(min_contains, bool):
            min_contains = 0
        minimum = max(minimum, min_contains)
        maximum = schema.get("maxItems")
        if (
            isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and minimum > maximum
        ):
            return WitnessBuildResult.unsupported(
                "array length constraints are unsatisfiable"
            )
        if minimum > _MAX_MATERIALIZED_ARRAY_LENGTH:
            return WitnessBuildResult.certified(
                CounterexampleCertificate(
                    "array-inhabitant",
                    "array witness construction requires materializing a large array",
                )
            )

        prefix = schema.get("prefixItems")
        if (
            prefix is None
            and self.dialect is not Dialect.DRAFT202012
            and isinstance(schema.get("items"), list)
        ):
            prefix = schema["items"]
        if not isinstance(prefix, list):
            prefix = []

        values = []
        for index in range(minimum):
            item_schema = (
                contains
                if contains is not None and index < min_contains
                else _array_item_schema_for_witness(
                    schema,
                    self.dialect,
                    index,
                    prefix,
                )
            )
            if item_schema is False:
                return WitnessBuildResult.unsupported(
                    "array witness slot is closed by false schema"
                )
            item = (
                self._build_distinct(item_schema, values, depth=depth + 1)
                if schema.get("uniqueItems") is True
                else self._build(
                    item_schema,
                    depth=depth + 1,
                )
            )
            if item.status == "witness":
                values.append(item.witness)
                continue
            return item
        return WitnessBuildResult.concrete(values)

    def _object_witness(
        self, schema: dict[str, Any], *, depth: int
    ) -> WitnessBuildResult:
        if "allOf" in schema:
            return WitnessBuildResult.unsupported(
                "object allOf witness requires mergeable object constraints"
            )
        if "object" not in type_overapproximation_for_schema(schema):
            return WitnessBuildResult.unsupported(
                "schema does not require an object witness"
            )
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        required = schema.get("required", [])
        if not isinstance(required, list):
            required = []
        required_names = tuple(name for name in required if isinstance(name, str))
        minimum = schema.get("minProperties", 0)
        if not isinstance(minimum, int) or isinstance(minimum, bool):
            minimum = 0
        maximum = schema.get("maxProperties")
        if (
            isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and len(required_names) > maximum
        ):
            return WitnessBuildResult.unsupported(
                "object property count constraints are unsatisfiable"
            )
        if len(required_names) > _MAX_MATERIALIZED_OBJECT_PROPERTIES:
            return WitnessBuildResult.certified(
                CounterexampleCertificate(
                    "object-inhabitant",
                    "object witness construction requires materializing a large object",
                )
            )

        witness = {}
        for name in required_names:
            value = self._build(properties.get(name, True), depth=depth + 1)
            if value.status == "witness":
                witness[name] = value.witness
                continue
            return value
        target_size = max(len(witness), minimum)
        if (
            isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and target_size > maximum
        ):
            return WitnessBuildResult.unsupported(
                "object property count constraints are unsatisfiable"
            )
        if target_size > _MAX_MATERIALIZED_OBJECT_PROPERTIES:
            return WitnessBuildResult.certified(
                CounterexampleCertificate(
                    "object-inhabitant",
                    "object witness construction requires materializing a large object",
                )
            )
        while len(witness) < target_size:
            name = self._next_object_witness_name(
                schema, properties, frozenset(witness)
            )
            if name is None:
                return WitnessBuildResult.unsupported(
                    "object witness could not satisfy keyspace constraints"
                )
            value = self._build(
                _object_property_schema_for_witness(schema, properties, name),
                depth=depth + 1,
            )
            if value.status != "witness":
                return value
            witness[name] = value.witness
        return WitnessBuildResult.concrete(witness)

    def _next_object_witness_name(
        self,
        schema: dict[str, Any],
        properties: dict[str, Any],
        used_names: frozenset[str],
    ) -> str | None:
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for name in sorted(properties):
                if name not in used_names:
                    return name
            return None
        property_names = schema.get("propertyNames", True)
        if isinstance(property_names, dict):
            name = self._property_names_witness(property_names)
            if name is not None and name not in used_names:
                return name
        index = 0
        while True:
            name = f"k{index}"
            if name not in used_names:
                return name
            index += 1

    def _property_names_witness(self, schema: dict[str, Any]) -> str | None:
        shape = string_language_shape_for_schema(schema)
        if shape is None:
            return None
        witness = string_language_witness(shape.pattern, self.context)
        return witness if isinstance(witness, str) else None

    def _type_witness(self, schema: dict[str, Any]) -> WitnessBuildResult:
        atoms = sorted(type_overapproximation_for_schema(schema))
        if not atoms:
            return WitnessBuildResult.unsupported("schema type approximation is empty")
        return WitnessBuildResult.concrete(witness_for_type_atom(atoms[0]))

    def _build_distinct(
        self, schema: Any, used_values: list[Any], *, depth: int
    ) -> WitnessBuildResult:
        used = {json_semantic_key(value) for value in used_values}
        finite = _finite_values_for_schema(schema, self.dialect)
        if finite is not None:
            for value in finite:
                if json_semantic_key(value) not in used:
                    return WitnessBuildResult.concrete(value)
            return WitnessBuildResult.unsupported(
                "distinct array witness could not satisfy finite item schema"
            )

        witness = self._build(schema, depth=depth)
        if witness.has_witness and json_semantic_key(witness.witness) not in used:
            return witness

        for atom in sorted(type_overapproximation_for_schema(schema)):
            candidate = witness_for_type_atom(atom)
            if json_semantic_key(candidate) not in used:
                return WitnessBuildResult.concrete(candidate)
        return witness

    def _applicator_witness(
        self, schema: dict[str, Any], *, depth: int
    ) -> WitnessBuildResult:
        for keyword in ("anyOf", "oneOf"):
            subschemas = schema.get(keyword)
            if not isinstance(subschemas, list):
                continue
            for subschema in subschemas:
                witness = self._build(subschema, depth=depth + 1)
                if witness.has_witness or witness.status in {
                    "certificate",
                    "resource_exhausted",
                }:
                    return witness

        subschemas = schema.get("allOf")
        if isinstance(subschemas, list) and subschemas:
            return WitnessBuildResult.unsupported(
                "schema witness construction requires unsupported applicator "
                "intersection"
            )
        return WitnessBuildResult.unsupported(
            "schema has no constructive applicator witness"
        )

    def _all_of_witness(
        self, schema: dict[str, Any], *, depth: int
    ) -> WitnessBuildResult:
        subschemas = schema.get("allOf")
        if not isinstance(subschemas, list) or not subschemas:
            return WitnessBuildResult.unsupported("schema has no allOf witness")

        positive = []
        excluded = []
        negated = []
        for subschema in subschemas:
            if isinstance(subschema, dict) and set(subschema) == {"not"}:
                finite = _finite_values_for_schema(subschema["not"], self.dialect)
                if finite is not None:
                    excluded.extend(finite)
                    continue
                negated.append(subschema["not"])
                continue
            positive.append(subschema)

        merged_array = _merged_array_all_of_schema(tuple(positive), self.dialect)
        if merged_array is not None:
            array_witness = self._build(merged_array, depth=depth + 1)
            if (
                array_witness.has_witness
                and not _value_is_excluded(array_witness.witness, excluded)
                and all(
                    _schema_definitely_rejects_witness(
                        schema, array_witness.witness, self.dialect
                    )
                    for schema in negated
                )
            ):
                return array_witness
            if array_witness.status in {"certificate", "resource_exhausted"}:
                return array_witness

        merged_object = _merged_object_all_of_schema(tuple(positive))
        if merged_object is not None:
            object_witness = self._build(merged_object, depth=depth + 1)
            if (
                object_witness.has_witness
                and not _value_is_excluded(object_witness.witness, excluded)
                and all(
                    _schema_definitely_rejects_witness(
                        schema, object_witness.witness, self.dialect
                    )
                    for schema in negated
                )
            ):
                return object_witness
            if object_witness.status in {"certificate", "resource_exhausted"}:
                return object_witness

        if not excluded and not negated:
            return WitnessBuildResult.unsupported(
                "schema witness construction requires unsupported applicator "
                "intersection"
            )

        base_schema = positive[0] if len(positive) == 1 else {"allOf": positive}
        base_witness = self._build(base_schema, depth=depth + 1)
        if (
            base_witness.has_witness
            and not _value_is_excluded(base_witness.witness, excluded)
            and all(
                _schema_definitely_rejects_witness(
                    schema, base_witness.witness, self.dialect
                )
                for schema in negated
            )
        ):
            return base_witness

        numeric = numeric_shape_for_schema(base_schema, self.dialect)
        if numeric is not None:
            for atom in numeric.normalized_atoms():
                for fraction in atom.candidate_fractions():
                    value = (
                        int(fraction) if fraction.denominator == 1 else float(fraction)
                    )
                    if not _value_is_excluded(value, excluded):
                        return WitnessBuildResult.concrete(value)

        string = string_language_shape_for_schema(base_schema)
        if string is not None and not string.accepts_non_string:
            witness = string_language_witness(string.pattern, self.context)
            if isinstance(witness, ProofResult):
                if witness.status == "resource_exhausted":
                    return WitnessBuildResult.resource_exhausted(
                        witness.reason or "regex witness exceeded proof work budget"
                    )
            elif witness is not None and not _value_is_excluded(witness, excluded):
                return WitnessBuildResult.concrete(witness)

        return WitnessBuildResult.unsupported(
            "schema witness construction requires unsupported allOf complement"
        )


def build_schema_witness(
    schema: Any,
    dialect: Dialect,
    context: ProofContext | None = None,
) -> WitnessBuildResult:
    return WitnessBuilder(dialect, context).build(schema)


def finite_projection_witness(schema: Any, dialect: Dialect) -> WitnessBuildResult:
    if isinstance(schema, dict):
        finite_values = _finite_values_for_schema(schema, dialect)
        if finite_values:
            return WitnessBuildResult.concrete(finite_values[0])
    return WitnessBuildResult.unsupported("schema has no explicit finite witness")


def _array_item_schema_for_witness(
    schema: dict[str, Any],
    dialect: Dialect,
    index: int,
    prefix: list[Any],
) -> Any:
    if index < len(prefix):
        return prefix[index]
    if dialect is Dialect.DRAFT202012:
        return schema.get("items", True)
    items = schema.get("items")
    if isinstance(items, dict) or isinstance(items, bool):
        return items
    if isinstance(items, list):
        return schema.get("additionalItems", True)
    return True


def _schema_allows_array_witness(schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "array":
        return True
    if isinstance(schema_type, list):
        return "array" in schema_type
    if schema_type is None:
        return "array" in type_overapproximation_for_schema(schema)
    return False


def _object_property_schema_for_witness(
    schema: dict[str, Any],
    properties: dict[str, Any],
    name: str,
) -> Any:
    schemas = []
    if name in properties:
        schemas.append(properties[name])
    pattern_properties = schema.get("patternProperties")
    if isinstance(pattern_properties, dict):
        for pattern, subschema in sorted(pattern_properties.items()):
            if not isinstance(pattern, str):
                continue
            language = RegexLanguage.maybe_from_json_regex(pattern)
            if language is not None and language.matches(name):
                schemas.append(subschema)
    if name not in properties and not schemas:
        schemas.append(schema.get("additionalProperties", True))
    return _all_of_schema(tuple(item for item in schemas if item is not True))


def _all_of_schema(schemas: tuple[Any, ...]) -> Any:
    if not schemas:
        return True
    if len(schemas) == 1:
        return schemas[0]
    return {"allOf": list(schemas)}


def _merged_array_all_of_schema(
    schemas: tuple[Any, ...], dialect: Dialect
) -> dict[str, Any] | None:
    if not schemas or any(not isinstance(schema, dict) for schema in schemas):
        return None
    if any(
        "array" not in type_overapproximation_for_schema(schema) for schema in schemas
    ):
        return None

    merged: dict[str, Any] = {"type": "array"}
    min_items = 0
    max_items = None
    contains_schemas = []
    min_contains = 0
    max_contains = None
    item_schemas = []
    prefix_schemas: list[list[Any]] = []
    unique_items = False

    for schema in schemas:
        minimum = schema.get("minItems", 0)
        if isinstance(minimum, int) and not isinstance(minimum, bool):
            min_items = max(min_items, minimum)
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and not isinstance(maximum, bool):
            max_items = maximum if max_items is None else min(max_items, maximum)
        if schema.get("uniqueItems") is True:
            unique_items = True

        if "contains" in schema:
            contains_schemas.append(schema["contains"])
            minimum_contains = schema.get("minContains", 1)
            if isinstance(minimum_contains, int) and not isinstance(
                minimum_contains, bool
            ):
                min_contains = max(min_contains, minimum_contains)
            maximum_contains = schema.get("maxContains")
            if isinstance(maximum_contains, int) and not isinstance(
                maximum_contains, bool
            ):
                max_contains = (
                    maximum_contains
                    if max_contains is None
                    else min(max_contains, maximum_contains)
                )

        items = schema.get("items")
        prefix = schema.get("prefixItems")
        if isinstance(prefix, list):
            prefix_schemas.append(prefix)
            if items is False:
                max_items = (
                    len(prefix) if max_items is None else min(max_items, len(prefix))
                )
        elif dialect is not Dialect.DRAFT202012 and isinstance(items, list):
            prefix_schemas.append(items)
            if schema.get("additionalItems") is False:
                max_items = (
                    len(items) if max_items is None else min(max_items, len(items))
                )
        if isinstance(items, dict) or isinstance(items, bool):
            item_schemas.append(items)

    if max_items is not None and min_items > max_items:
        return None
    if max_contains is not None and min_contains > max_contains:
        return None

    if min_items:
        merged["minItems"] = min_items
    if max_items is not None:
        merged["maxItems"] = max_items
    if unique_items:
        merged["uniqueItems"] = True
    if contains_schemas:
        merged["contains"] = _all_of_schema(
            tuple(schema for schema in contains_schemas if schema is not True)
        )
        if min_contains != 1:
            merged["minContains"] = min_contains
        if max_contains is not None:
            merged["maxContains"] = max_contains
    if prefix_schemas:
        prefix_items = []
        for index in range(max(len(prefix) for prefix in prefix_schemas)):
            slot_schemas = tuple(
                prefix[index] for prefix in prefix_schemas if index < len(prefix)
            )
            prefix_items.append(
                _all_of_schema(
                    tuple(schema for schema in slot_schemas if schema is not True)
                )
            )
        merged["prefixItems"] = prefix_items
    if item_schemas:
        item_schema = _all_of_schema(
            tuple(schema for schema in item_schemas if schema is not True)
        )
        if item_schema is not True:
            merged["items"] = item_schema
    return merged


def _merged_object_all_of_schema(schemas: tuple[Any, ...]) -> dict[str, Any] | None:
    if not schemas or any(not isinstance(schema, dict) for schema in schemas):
        return None
    if any(
        "object" not in type_overapproximation_for_schema(schema) for schema in schemas
    ):
        return None

    merged: dict[str, Any] = {"type": "object"}
    min_properties = 0
    max_properties = None
    required: set[str] = set()
    property_schemas: dict[str, list[Any]] = {}
    pattern_schemas: dict[str, list[Any]] = {}
    property_names: list[Any] = []
    additional_schemas: list[Any] = []
    closes_additional = False

    for schema in schemas:
        minimum = schema.get("minProperties", 0)
        if isinstance(minimum, int) and not isinstance(minimum, bool):
            min_properties = max(min_properties, minimum)
        maximum = schema.get("maxProperties")
        if isinstance(maximum, int) and not isinstance(maximum, bool):
            max_properties = (
                maximum if max_properties is None else min(max_properties, maximum)
            )

        schema_required = schema.get("required")
        if isinstance(schema_required, list):
            required.update(name for name in schema_required if isinstance(name, str))

        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, subschema in properties.items():
                if isinstance(name, str):
                    property_schemas.setdefault(name, []).append(subschema)

        patterns = schema.get("patternProperties")
        if isinstance(patterns, dict):
            for pattern, subschema in patterns.items():
                if isinstance(pattern, str):
                    pattern_schemas.setdefault(pattern, []).append(subschema)

        names_schema = schema.get("propertyNames")
        if names_schema not in (None, True):
            property_names.append(names_schema)

        additional = schema.get("additionalProperties", True)
        if additional is False:
            closes_additional = True
        elif additional is not True:
            additional_schemas.append(additional)

    if (
        max_properties is not None
        and max(min_properties, len(required)) > max_properties
    ):
        return None

    if min_properties:
        merged["minProperties"] = min_properties
    if max_properties is not None:
        merged["maxProperties"] = max_properties
    if required:
        merged["required"] = sorted(required)
    if property_schemas:
        merged["properties"] = {
            name: _all_of_schema(
                tuple(schema for schema in schemas_for_name if schema is not True)
            )
            for name, schemas_for_name in sorted(property_schemas.items())
        }
    if pattern_schemas:
        merged["patternProperties"] = {
            pattern: _all_of_schema(
                tuple(schema for schema in schemas_for_pattern if schema is not True)
            )
            for pattern, schemas_for_pattern in sorted(pattern_schemas.items())
        }
    if property_names:
        merged["propertyNames"] = _all_of_schema(
            tuple(schema for schema in property_names if schema is not True)
        )
    if closes_additional:
        merged["additionalProperties"] = False
    elif additional_schemas:
        merged["additionalProperties"] = _all_of_schema(
            tuple(schema for schema in additional_schemas if schema is not True)
        )
    return merged


def _finite_values_for_schema(schema: Any, dialect: Dialect) -> list[Any] | None:
    return finite_values_for_schema(
        schema, ResourceGraph.build(schema, dialect=dialect)
    )


def _schema_definitely_rejects_witness(
    schema: Any, witness: Any, dialect: Dialect
) -> bool:
    finite = _finite_values_for_schema(schema, dialect)
    if finite is not None:
        return json_semantic_key(witness) not in {
            json_semantic_key(value) for value in finite
        }
    if not isinstance(schema, dict):
        return False
    atoms = type_overapproximation_for_schema(schema)
    return _type_atom_for_value(witness) not in atoms


def _value_is_excluded(value: Any, excluded: list[Any]) -> bool:
    value_key = json_semantic_key(value)
    return any(
        value_key == json_semantic_key(excluded_value) for excluded_value in excluded
    )


def _type_atom_for_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"
