"""
Logical schema IR compiled from resource-aware schema inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Literal

from subschema.dialects import Dialect
from subschema.kernel.constraints import (
    ArrayLengthConstraint,
    ArrayUniquenessConstraint,
    FiniteConstraint,
    NumericConstraint,
    ObjectClosedPropertiesConstraint,
    ObjectPropertyCountConstraint,
    ObjectPropertyNamesConstraint,
    ObjectPropertyValuesConstraint,
    StringLanguageConstraint,
    StringLengthConstraint,
    TypeConstraint,
)
from subschema.kernel.contracts import ProofResult, UnsupportedCategory
from subschema.kernel.domains.arrays import (
    ArrayShape,
    ArrayUniquenessShape,
    array_shape_for_schema,
    array_uniqueness_shape_for_schema,
)
from subschema.kernel.domains.numbers import NumericShape, numeric_shape_for_schema
from subschema.kernel.domains.objects import (
    ClosedObjectPropertiesShape,
    ObjectPropertyCountShape,
    ObjectPropertyNamesShape,
    ObjectPropertyValuesShape,
    closed_object_properties_shape_for_schema,
    object_property_count_shape_for_schema,
    object_property_names_shape_for_schema,
    object_property_values_shape_for_schema,
)
from subschema.kernel.domains.strings import (
    StringLanguageShape,
    StringShape,
    string_language_shape_for_schema,
    string_shape_for_schema,
)
from subschema.kernel.domains.types import (
    TypeShape,
    type_language_complete_for_schema,
    type_shape_for_schema,
)
from subschema.kernel.evaluation import (
    EvaluationFrontier,
    evaluation_frontier_for_schema,
)
from subschema.kernel.finite import finite_values_for_schema
from subschema.kernel.references import ResourceGraph
from subschema.kernel.references import SchemaIR as ResourceSchemaIR
from subschema.kernel.regex import RegexLanguage
from subschema.kernel.schemas import (
    HARD_KEYWORDS,
    SCHEMA_ARRAY_KEYWORDS,
    SCHEMA_MAP_KEYWORDS,
    SCHEMA_VALUE_KEYWORDS,
)

IRAssertionKind = Literal[
    "array-length-lhs",
    "array-length-rhs",
    "array-uniqueness-lhs",
    "array-uniqueness-rhs",
    "finite",
    "numeric",
    "object-closed-properties",
    "object-property-count",
    "object-property-names",
    "object-property-values",
    "string-language",
    "string-length",
    "type",
]
ApplicatorKind = Literal["allOf", "anyOf", "else", "if", "not", "oneOf", "then"]

__all__ = [
    "AssertionAtom",
    "ApplicatorKind",
    "ApplicatorNode",
    "ArrayLengthConstraint",
    "ArrayUniquenessConstraint",
    "DomainFacts",
    "EvaluationFrontier",
    "FiniteConstraint",
    "IRAssertionKind",
    "LogicalSchemaIR",
    "NumericConstraint",
    "ObjectClosedPropertiesConstraint",
    "ObjectPropertyCountConstraint",
    "ObjectPropertyNamesConstraint",
    "ObjectPropertyValuesConstraint",
    "SchemaIRCompiler",
    "SchemaNode",
    "StringLanguageConstraint",
    "StringLengthConstraint",
    "TypeConstraint",
    "UnsupportedNode",
]


@dataclass(frozen=True)
class AssertionAtom:
    kind: IRAssertionKind
    value: Any


@dataclass(frozen=True)
class DomainFacts:
    schema: Any
    graph: ResourceGraph
    dialect: Dialect

    @cached_property
    def finite_constraint(self) -> FiniteConstraint | None:
        values = finite_values_for_schema(self.schema, self.graph)
        return None if values is None else FiniteConstraint(tuple(values))

    @property
    def finite_values(self) -> tuple[Any, ...] | None:
        constraint = self.finite_constraint
        return None if constraint is None else constraint.values

    @cached_property
    def type_constraint(self) -> TypeConstraint | None:
        shape = type_shape_for_schema(self.schema)
        return (
            None
            if shape is None
            else TypeConstraint(shape, type_language_complete_for_schema(self.schema))
        )

    @property
    def type_shape(self) -> TypeShape | None:
        constraint = self.type_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def numeric_constraint(self) -> NumericConstraint | None:
        shape = numeric_shape_for_schema(self.schema, self.dialect)
        return None if shape is None else NumericConstraint(shape)

    @property
    def numeric_shape(self) -> NumericShape | None:
        constraint = self.numeric_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def string_length_constraint(self) -> StringLengthConstraint | None:
        shape = string_shape_for_schema(self.schema)
        return None if shape is None else StringLengthConstraint(shape)

    @property
    def string_length_shape(self) -> StringShape | None:
        constraint = self.string_length_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def string_language_constraint(self) -> StringLanguageConstraint | None:
        shape = string_language_shape_for_schema(self.schema)
        return None if shape is None else StringLanguageConstraint(shape)

    @property
    def string_language_shape(self) -> StringLanguageShape | None:
        constraint = self.string_language_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def array_length_lhs_constraint(self) -> ArrayLengthConstraint | None:
        shape = array_shape_for_schema(
            self.schema,
            self.dialect,
            allow_item_value_constraints=True,
        )
        return None if shape is None else ArrayLengthConstraint(shape)

    @property
    def array_length_lhs_shape(self) -> ArrayShape | None:
        constraint = self.array_length_lhs_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def array_length_rhs_constraint(self) -> ArrayLengthConstraint | None:
        shape = array_shape_for_schema(
            self.schema,
            self.dialect,
            allow_item_value_constraints=False,
        )
        return None if shape is None else ArrayLengthConstraint(shape)

    @property
    def array_length_rhs_shape(self) -> ArrayShape | None:
        constraint = self.array_length_rhs_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def array_uniqueness_lhs_constraint(self) -> ArrayUniquenessConstraint | None:
        shape = array_uniqueness_shape_for_schema(
            self.schema,
            self.dialect,
            side="lhs",
        )
        return None if shape is None else ArrayUniquenessConstraint(shape)

    @property
    def array_uniqueness_lhs_shape(self) -> ArrayUniquenessShape | None:
        constraint = self.array_uniqueness_lhs_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def array_uniqueness_rhs_constraint(self) -> ArrayUniquenessConstraint | None:
        shape = array_uniqueness_shape_for_schema(
            self.schema,
            self.dialect,
            side="rhs",
        )
        return None if shape is None else ArrayUniquenessConstraint(shape)

    @property
    def array_uniqueness_rhs_shape(self) -> ArrayUniquenessShape | None:
        constraint = self.array_uniqueness_rhs_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def object_property_count_constraint(self) -> ObjectPropertyCountConstraint | None:
        shape = object_property_count_shape_for_schema(self.schema)
        return None if shape is None else ObjectPropertyCountConstraint(shape)

    @property
    def object_property_count_shape(self) -> ObjectPropertyCountShape | None:
        constraint = self.object_property_count_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def object_property_values_constraint(
        self,
    ) -> ObjectPropertyValuesConstraint | None:
        shape = object_property_values_shape_for_schema(self.schema)
        return None if shape is None else ObjectPropertyValuesConstraint(shape)

    @property
    def object_property_values_shape(self) -> ObjectPropertyValuesShape | None:
        constraint = self.object_property_values_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def object_closed_properties_constraint(
        self,
    ) -> ObjectClosedPropertiesConstraint | None:
        shape = closed_object_properties_shape_for_schema(self.schema)
        return None if shape is None else ObjectClosedPropertiesConstraint(shape)

    @property
    def object_closed_properties_shape(self) -> ClosedObjectPropertiesShape | None:
        constraint = self.object_closed_properties_constraint
        return None if constraint is None else constraint.shape

    @cached_property
    def object_property_names_constraint(self) -> ObjectPropertyNamesConstraint | None:
        shape = object_property_names_shape_for_schema(self.schema)
        return None if shape is None else ObjectPropertyNamesConstraint(shape)

    @property
    def object_property_names_shape(self) -> ObjectPropertyNamesShape | None:
        constraint = self.object_property_names_constraint
        return None if constraint is None else constraint.shape

    def assertions(self) -> tuple[AssertionAtom, ...]:
        return tuple(
            AssertionAtom(kind, value)
            for kind, value in (
                ("finite", self.finite_constraint),
                ("type", self.type_constraint),
                ("numeric", self.numeric_constraint),
                ("string-length", self.string_length_constraint),
                ("string-language", self.string_language_constraint),
                ("array-length-lhs", self.array_length_lhs_constraint),
                ("array-length-rhs", self.array_length_rhs_constraint),
                ("array-uniqueness-lhs", self.array_uniqueness_lhs_constraint),
                ("array-uniqueness-rhs", self.array_uniqueness_rhs_constraint),
                ("object-property-count", self.object_property_count_constraint),
                ("object-property-values", self.object_property_values_constraint),
                ("object-closed-properties", self.object_closed_properties_constraint),
                ("object-property-names", self.object_property_names_constraint),
            )
            if value is not None
        )

    def assertion(self, kind: IRAssertionKind) -> AssertionAtom | None:
        value = self._assertion_value(kind)
        if value is None:
            return None
        return AssertionAtom(kind, value)

    def _assertion_value(self, kind: IRAssertionKind) -> Any | None:
        match kind:
            case "array-length-lhs":
                return self.array_length_lhs_constraint
            case "array-length-rhs":
                return self.array_length_rhs_constraint
            case "array-uniqueness-lhs":
                return self.array_uniqueness_lhs_constraint
            case "array-uniqueness-rhs":
                return self.array_uniqueness_rhs_constraint
            case "finite":
                return self.finite_constraint
            case "numeric":
                return self.numeric_constraint
            case "object-closed-properties":
                return self.object_closed_properties_constraint
            case "object-property-count":
                return self.object_property_count_constraint
            case "object-property-names":
                return self.object_property_names_constraint
            case "object-property-values":
                return self.object_property_values_constraint
            case "string-language":
                return self.string_language_constraint
            case "string-length":
                return self.string_length_constraint
            case "type":
                return self.type_constraint


@dataclass(frozen=True)
class ApplicatorNode:
    kind: ApplicatorKind
    children: tuple[SchemaNode, ...]


@dataclass(frozen=True)
class UnsupportedNode:
    keyword: str
    reason: str
    path: tuple[str, ...] = ()
    category: UnsupportedCategory = "semantic-keyword"

    @property
    def pointer(self) -> str:
        if not self.path:
            return "#"
        return "#/" + "/".join(
            _escape_pointer_segment(segment) for segment in self.path
        )


@dataclass(frozen=True)
class SchemaNode:
    source: ResourceSchemaIR
    facts: DomainFacts
    evaluation: EvaluationFrontier = field(default_factory=EvaluationFrontier)
    applicators: tuple[ApplicatorNode, ...] = ()
    unsupported: tuple[UnsupportedNode, ...] = ()

    @property
    def all_unsupported(self) -> tuple[UnsupportedNode, ...]:
        return self.unsupported + tuple(
            unsupported
            for applicator in self.applicators
            for child in applicator.children
            for unsupported in child.all_unsupported
        )


@dataclass(frozen=True)
class LogicalSchemaIR:
    graph: ResourceGraph
    root: SchemaNode

    @property
    def source(self) -> ResourceSchemaIR:
        return self.root.source

    @property
    def schema(self) -> Any:
        return self.source.schema

    @property
    def dialect(self) -> Dialect:
        return self.source.dialect

    @property
    def facts(self) -> DomainFacts:
        return self.root.facts

    @property
    def evaluation(self) -> EvaluationFrontier:
        return self.root.evaluation

    @property
    def assertions(self) -> tuple[AssertionAtom, ...]:
        return self.facts.assertions()

    @property
    def applicators(self) -> tuple[ApplicatorNode, ...]:
        return self.root.applicators

    @property
    def unsupported(self) -> tuple[UnsupportedNode, ...]:
        return self.root.all_unsupported

    def assertion(self, kind: IRAssertionKind) -> AssertionAtom | None:
        return self.facts.assertion(kind)

    @property
    def finite_values(self) -> tuple[Any, ...] | None:
        return self.facts.finite_values

    @property
    def finite_constraint(self) -> FiniteConstraint | None:
        return self.facts.finite_constraint

    @property
    def type_shape(self) -> TypeShape | None:
        return self.facts.type_shape

    @property
    def type_constraint(self) -> TypeConstraint | None:
        return self.facts.type_constraint

    @property
    def numeric_shape(self) -> NumericShape | None:
        return self.facts.numeric_shape

    @property
    def numeric_constraint(self) -> NumericConstraint | None:
        return self.facts.numeric_constraint

    @property
    def string_length_shape(self) -> StringShape | None:
        return self.facts.string_length_shape

    @property
    def string_length_constraint(self) -> StringLengthConstraint | None:
        return self.facts.string_length_constraint

    @property
    def string_language_shape(self) -> StringLanguageShape | None:
        return self.facts.string_language_shape

    @property
    def string_language_constraint(self) -> StringLanguageConstraint | None:
        return self.facts.string_language_constraint

    @property
    def array_length_lhs_constraint(self) -> ArrayLengthConstraint | None:
        return self.facts.array_length_lhs_constraint

    @property
    def array_length_rhs_constraint(self) -> ArrayLengthConstraint | None:
        return self.facts.array_length_rhs_constraint

    @property
    def array_uniqueness_lhs_constraint(self) -> ArrayUniquenessConstraint | None:
        return self.facts.array_uniqueness_lhs_constraint

    @property
    def array_uniqueness_rhs_constraint(self) -> ArrayUniquenessConstraint | None:
        return self.facts.array_uniqueness_rhs_constraint

    @property
    def object_property_count_constraint(self) -> ObjectPropertyCountConstraint | None:
        return self.facts.object_property_count_constraint

    @property
    def object_property_names_constraint(self) -> ObjectPropertyNamesConstraint | None:
        return self.facts.object_property_names_constraint

    @property
    def object_property_values_constraint(
        self,
    ) -> ObjectPropertyValuesConstraint | None:
        return self.facts.object_property_values_constraint

    @property
    def object_closed_properties_constraint(
        self,
    ) -> ObjectClosedPropertiesConstraint | None:
        return self.facts.object_closed_properties_constraint


class SchemaIRCompiler:
    def __init__(self, dialect: Dialect):
        self.dialect = dialect

    def compile(self, schema: Any) -> LogicalSchemaIR:
        return self.compile_graph(ResourceGraph.build(schema, dialect=self.dialect))

    def compile_graph(self, graph: ResourceGraph) -> LogicalSchemaIR:
        return LogicalSchemaIR(
            graph, self._compile_node(graph.to_ir(), graph, depth=0, path=())
        )

    def _compile_node(
        self,
        source: ResourceSchemaIR,
        graph: ResourceGraph,
        *,
        depth: int,
        path: tuple[str, ...],
    ) -> SchemaNode:
        schema = source.schema
        evaluation = self._compile_evaluation(schema, source.dialect)
        return SchemaNode(
            source=source,
            facts=self._compile_facts(source, graph),
            evaluation=evaluation,
            applicators=self._compile_applicators(
                schema, graph, depth=depth, path=path
            ),
            unsupported=self._compile_unsupported(schema, evaluation, path),
        )

    def _compile_facts(
        self, source: ResourceSchemaIR, graph: ResourceGraph
    ) -> DomainFacts:
        return DomainFacts(source.schema, graph, source.dialect)

    def _compile_evaluation(
        self, schema: Any, dialect: Dialect | None = None
    ) -> EvaluationFrontier:
        return evaluation_frontier_for_schema(schema, dialect or self.dialect)

    def _compile_applicators(
        self,
        schema: Any,
        graph: ResourceGraph,
        *,
        depth: int,
        path: tuple[str, ...],
    ) -> tuple[ApplicatorNode, ...]:
        if depth > 16 or not isinstance(schema, dict):
            return ()

        applicators = []
        for keyword in ("allOf", "anyOf", "oneOf"):
            value = schema.get(keyword)
            if isinstance(value, list):
                applicators.append(
                    ApplicatorNode(
                        keyword,
                        tuple(
                            self._compile_child(
                                subschema,
                                graph,
                                depth=depth + 1,
                                path=path + (keyword, str(index)),
                            )
                            for index, subschema in enumerate(value)
                        ),
                    )
                )

        for keyword in ("not", "if", "then", "else"):
            value = schema.get(keyword)
            if isinstance(value, bool | dict):
                applicators.append(
                    ApplicatorNode(
                        keyword,
                        (
                            self._compile_child(
                                value, graph, depth=depth + 1, path=path + (keyword,)
                            ),
                        ),
                    )
                )
        return tuple(applicators)

    def _compile_child(
        self,
        schema: Any,
        graph: ResourceGraph,
        *,
        depth: int,
        path: tuple[str, ...],
    ) -> SchemaNode:
        return self._compile_node(
            graph.schema_ir_for_pointer(path, schema),
            graph,
            depth=depth,
            path=path,
        )

    def _compile_unsupported(
        self,
        schema: Any,
        evaluation: EvaluationFrontier,
        path: tuple[str, ...],
    ) -> tuple[UnsupportedNode, ...]:
        if not isinstance(schema, dict):
            return ()

        nodes = [
            _unsupported_node(keyword, evaluation, path + (keyword,))
            for keyword in sorted(HARD_KEYWORDS.intersection(schema))
        ]
        nodes.extend(_regex_unsupported_nodes(schema, path))
        nodes.extend(self._nested_unsupported(schema, path))
        return tuple(nodes)

    def _nested_unsupported(
        self, schema: dict[str, Any], path: tuple[str, ...]
    ) -> tuple[UnsupportedNode, ...]:
        nodes: list[UnsupportedNode] = []
        for keyword, value in schema.items():
            if keyword in {"allOf", "anyOf", "oneOf", "not", "if", "then", "else"}:
                continue
            if keyword in SCHEMA_VALUE_KEYWORDS:
                nodes.extend(
                    self._compile_unsupported_for_inline_schema(
                        value, path + (keyword,)
                    )
                )
                continue
            if keyword in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
                for index, item in enumerate(value):
                    nodes.extend(
                        self._compile_unsupported_for_inline_schema(
                            item, path + (keyword, str(index))
                        )
                    )
                continue
            if keyword in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
                for property_name, subschema in value.items():
                    nodes.extend(
                        self._compile_unsupported_for_inline_schema(
                            subschema,
                            path + (keyword, str(property_name)),
                        )
                    )
        return tuple(nodes)

    def _compile_unsupported_for_inline_schema(
        self,
        schema: Any,
        path: tuple[str, ...],
    ) -> tuple[UnsupportedNode, ...]:
        return self._compile_unsupported(
            schema, self._compile_evaluation(schema, self.dialect), path
        )


def _unsupported_node(
    keyword: str, evaluation: EvaluationFrontier, path: tuple[str, ...]
) -> UnsupportedNode:
    category, reason = _unsupported_category_and_reason(keyword, evaluation)
    return UnsupportedNode(keyword, reason, path, category)


def _unsupported_category_and_reason(
    keyword: str,
    evaluation: EvaluationFrontier,
) -> tuple[UnsupportedCategory, str]:
    if (
        keyword == "unevaluatedProperties"
        and evaluation.unevaluated_properties is not None
    ):
        return (
            "evaluation-frontier",
            "unevaluatedProperties requires evaluated-property frontier proof support",
        )
    if keyword == "unevaluatedItems" and evaluation.unevaluated_items is not None:
        return (
            "evaluation-frontier",
            "unevaluatedItems requires evaluated-item frontier proof support",
        )
    if keyword == "$dynamicRef":
        return (
            "dynamic-reference",
            "$dynamicRef requires dynamic-scope reference proof support",
        )
    if keyword == "$recursiveRef":
        return (
            "recursive-reference",
            "$recursiveRef requires guarded recursive reference proof support",
        )
    return (
        "semantic-keyword",
        "modern semantic keyword requires a dedicated IR proof rule",
    )


def _regex_unsupported_nodes(
    schema: dict[str, Any], path: tuple[str, ...]
) -> tuple[UnsupportedNode, ...]:
    nodes = []
    pattern = schema.get("pattern")
    compiled_pattern = (
        RegexLanguage.from_json_regex(pattern) if isinstance(pattern, str) else None
    )
    if isinstance(compiled_pattern, ProofResult):
        nodes.append(
            UnsupportedNode(
                "pattern",
                compiled_pattern.reason
                or (
                    "pattern uses regex syntax outside the supported "
                    "regular-language fragment"
                ),
                path + ("pattern",),
                "non-regular-regex",
            )
        )

    pattern_properties = schema.get("patternProperties")
    if isinstance(pattern_properties, dict):
        for pattern in sorted(pattern_properties):
            compiled = RegexLanguage.from_json_regex(str(pattern))
            if isinstance(compiled, ProofResult):
                nodes.append(
                    UnsupportedNode(
                        "patternProperties",
                        compiled.reason
                        or (
                            "patternProperties key uses regex syntax outside the "
                            "supported regular-language fragment"
                        ),
                        path + ("patternProperties", str(pattern)),
                        "non-regular-regex",
                    )
                )
    return tuple(nodes)


def _escape_pointer_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")
