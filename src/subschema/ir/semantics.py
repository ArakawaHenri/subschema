"""
Typed semantic facts for compiled schema IR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from subschema.ir.constraints import (
    ArrayAnyOfItemSchemasConstraint,
    ArrayContainsConstraint,
    ArrayContainsFragmentConstraint,
    ArrayItemModelConstraint,
    ArrayItemValuesFragmentConstraint,
    ArrayLengthConstraint,
    ArrayTupleAnyOfDistributionConstraint,
    ArrayUniquenessConstraint,
    FiniteConstraint,
    NumericConstraint,
    ObjectClosedPropertiesConstraint,
    ObjectDependentRequiredConstraint,
    ObjectDependentSchemaPropertiesConstraint,
    ObjectKeyValueConstraint,
    ObjectPresenceProductConstraint,
    ObjectPropertyCountBoundsConstraint,
    ObjectPropertyCountConstraint,
    ObjectPropertyNamesConstraint,
    ObjectPropertyValuesConstraint,
    StringLanguageConstraint,
    StringLengthConstraint,
    TypeConstraint,
)
from subschema.ir.evaluation import EvaluationFrontier
from subschema.ir.references import ReferenceSemantics
from subschema.ir.terms import SchemaTerm

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
DomainFactStatus = Literal["exact", "overapprox", "unsupported"]

__all__ = [
    "AssertionAtom",
    "ArraySelectorCandidate",
    "ArraySemantics",
    "ApplicatorSemantics",
    "DomainFactInfo",
    "DomainFactStatus",
    "EvaluationSemantics",
    "IRAssertionKind",
    "ObjectSelectorCandidate",
    "ObjectSemantics",
    "ScalarSemantics",
    "SchemaSemantics",
    "TaggedBranch",
    "TaggedOneOf",
    "VocabularySemantics",
]


@dataclass(frozen=True)
class AssertionAtom:
    kind: IRAssertionKind
    value: Any


@dataclass(frozen=True)
class DomainFactInfo:
    status: DomainFactStatus
    reason: str | None = None


@dataclass(frozen=True)
class TaggedBranch:
    tag_name: str
    tag_value: Any
    term: SchemaTerm | None = None


@dataclass(frozen=True)
class TaggedOneOf:
    tag_name: str
    branches: tuple[TaggedBranch, ...]


@dataclass(frozen=True)
class ArraySelectorCandidate:
    index: int
    term: SchemaTerm


@dataclass(frozen=True)
class ObjectSelectorCandidate:
    name: str
    term: SchemaTerm


@dataclass(frozen=True)
class ScalarSemantics:
    finite_constraint: FiniteConstraint | None = None
    type_constraint: TypeConstraint | None = None
    numeric_constraint: NumericConstraint | None = None
    string_length_constraint: StringLengthConstraint | None = None
    string_language_constraint: StringLanguageConstraint | None = None
    covered_type_atoms: frozenset[str] = frozenset()
    has_string_assertions: bool = False
    has_numeric_assertions: bool = False


@dataclass(frozen=True)
class ArraySemantics:
    array_length_lhs_constraint: ArrayLengthConstraint | None = None
    array_length_rhs_constraint: ArrayLengthConstraint | None = None
    array_any_of_item_schemas_constraint: ArrayAnyOfItemSchemasConstraint | None = None
    array_tuple_anyof_distribution_constraint: (
        ArrayTupleAnyOfDistributionConstraint | None
    ) = None
    array_contains_constraint: ArrayContainsConstraint | None = None
    array_contains_counts: tuple[int, int | None] | None = None
    array_cardinality_length_constraint: ArrayLengthConstraint | None = None
    array_item_model_constraint: ArrayItemModelConstraint | None = None
    array_contains_fragment_constraint: ArrayContainsFragmentConstraint = (
        ArrayContainsFragmentConstraint(False, False)
    )
    array_item_values_fragment_constraint: ArrayItemValuesFragmentConstraint = (
        ArrayItemValuesFragmentConstraint(False, False, False)
    )
    array_unevaluated_items_true_fragment_supported: bool = False
    array_uniqueness_lhs_constraint: ArrayUniquenessConstraint | None = None
    array_uniqueness_rhs_constraint: ArrayUniquenessConstraint | None = None
    selector_candidates: tuple[ArraySelectorCandidate, ...] = ()


@dataclass(frozen=True)
class ObjectSemantics:
    object_property_count_constraint: ObjectPropertyCountConstraint | None = None
    object_property_count_bounds_constraint: (
        ObjectPropertyCountBoundsConstraint | None
    ) = None
    object_dependent_required_constraint: (
        ObjectDependentRequiredConstraint | None
    ) = None
    object_dependent_schema_properties_constraint: (
        ObjectDependentSchemaPropertiesConstraint | None
    ) = None
    object_dependent_schema_required_constraint: (
        ObjectDependentRequiredConstraint | None
    ) = None
    object_property_values_constraint: ObjectPropertyValuesConstraint | None = None
    object_closed_properties_constraint: ObjectClosedPropertiesConstraint | None = None
    object_property_names_constraint: ObjectPropertyNamesConstraint | None = None
    object_key_value_constraint: ObjectKeyValueConstraint | None = None
    object_presence_product_constraint: ObjectPresenceProductConstraint | None = None
    object_property_names_has_value_constraints: bool = False
    object_unevaluated_properties_true_fragment_supported: bool = False
    has_object_or_array_assertions: bool = False
    selector_candidates: tuple[ObjectSelectorCandidate, ...] = ()


@dataclass(frozen=True)
class ApplicatorSemantics:
    tagged_one_of: TaggedOneOf | None = None
    required_singleton_tags: tuple[tuple[str, Any], ...] = ()
    conditional_base_term: SchemaTerm | None = None
    conditional_base_semantic_keywords: frozenset[str] = frozenset()


@dataclass(frozen=True)
class EvaluationSemantics:
    frontier: EvaluationFrontier = field(default_factory=EvaluationFrontier)


@dataclass(frozen=True)
class VocabularySemantics:
    present_keywords: frozenset[str] = frozenset()
    semantic_keywords: frozenset[str] = frozenset()
    scalar_keywords: frozenset[str] = frozenset()
    array_keywords: frozenset[str] = frozenset()
    object_keywords: frozenset[str] = frozenset()
    applicator_keywords: frozenset[str] = frozenset()
    reference_keywords: frozenset[str] = frozenset()
    evaluation_keywords: frozenset[str] = frozenset()
    annotation_keywords: frozenset[str] = frozenset()
    vocabulary_keywords: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SchemaSemantics:
    scalar: ScalarSemantics = field(default_factory=ScalarSemantics)
    array: ArraySemantics = field(default_factory=ArraySemantics)
    object: ObjectSemantics = field(default_factory=ObjectSemantics)
    applicator: ApplicatorSemantics = field(default_factory=ApplicatorSemantics)
    reference: ReferenceSemantics = field(default_factory=ReferenceSemantics)
    evaluation: EvaluationSemantics = field(default_factory=EvaluationSemantics)
    vocabulary: VocabularySemantics = field(default_factory=VocabularySemantics)

    def finite_values(self) -> tuple[Any, ...] | None:
        constraint = self.scalar.finite_constraint
        return None if constraint is None else constraint.values

    def required_singleton_tag(self, tag_name: str) -> Any | None:
        for name, value in self.applicator.required_singleton_tags:
            if name == tag_name:
                return value
        return None

    def accepts_only_type(self, atom: str) -> bool:
        constraint = self.scalar.type_constraint
        return constraint is not None and constraint.atoms == frozenset({atom})

    def covers_type_atom(self, atom: str) -> bool:
        return atom in self.scalar.covered_type_atoms

    def has_non_numeric_assertions(self) -> bool:
        return (
            self.object.has_object_or_array_assertions
            or self.scalar.has_string_assertions
        )

    def fact_info(self, kind: IRAssertionKind) -> DomainFactInfo:
        return self.constraint_info(kind, self._assertion_value(kind))

    @staticmethod
    def constraint_info(
        kind: IRAssertionKind,
        constraint: Any | None,
    ) -> DomainFactInfo:
        if constraint is None:
            return DomainFactInfo("unsupported", f"{kind} fact is unavailable")
        if isinstance(constraint, TypeConstraint) and not constraint.language_complete:
            return DomainFactInfo("overapprox")
        if not bool(getattr(constraint, "exact", True)):
            return DomainFactInfo("overapprox")
        if not bool(getattr(constraint, "complete_uniqueness_fragment", True)):
            return DomainFactInfo("overapprox")
        return DomainFactInfo("exact")

    def assertions(self) -> tuple[AssertionAtom, ...]:
        assertion_values: tuple[tuple[IRAssertionKind, Any | None], ...] = (
            ("finite", self.scalar.finite_constraint),
            ("type", self.scalar.type_constraint),
            ("numeric", self.scalar.numeric_constraint),
            ("string-length", self.scalar.string_length_constraint),
            ("string-language", self.scalar.string_language_constraint),
            ("array-length-lhs", self.array.array_length_lhs_constraint),
            ("array-length-rhs", self.array.array_length_rhs_constraint),
            ("array-uniqueness-lhs", self.array.array_uniqueness_lhs_constraint),
            ("array-uniqueness-rhs", self.array.array_uniqueness_rhs_constraint),
            ("object-property-count", self.object.object_property_count_constraint),
            ("object-property-values", self.object.object_property_values_constraint),
            (
                "object-closed-properties",
                self.object.object_closed_properties_constraint,
            ),
            ("object-property-names", self.object.object_property_names_constraint),
        )
        return tuple(
            AssertionAtom(kind, value)
            for kind, value in assertion_values
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
                return self.array.array_length_lhs_constraint
            case "array-length-rhs":
                return self.array.array_length_rhs_constraint
            case "array-uniqueness-lhs":
                return self.array.array_uniqueness_lhs_constraint
            case "array-uniqueness-rhs":
                return self.array.array_uniqueness_rhs_constraint
            case "finite":
                return self.scalar.finite_constraint
            case "numeric":
                return self.scalar.numeric_constraint
            case "object-closed-properties":
                return self.object.object_closed_properties_constraint
            case "object-property-count":
                return self.object.object_property_count_constraint
            case "object-property-names":
                return self.object.object_property_names_constraint
            case "object-property-values":
                return self.object.object_property_values_constraint
            case "string-language":
                return self.scalar.string_language_constraint
            case "string-length":
                return self.scalar.string_length_constraint
            case "type":
                return self.scalar.type_constraint
