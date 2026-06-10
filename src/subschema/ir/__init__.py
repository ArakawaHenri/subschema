"""
Logical schema IR compiled from resource-aware schema inputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from subschema.contracts import (
    ProofSide,
    UnsupportedCategory,
    UnsupportedDiagnostic,
)
from subschema.dialects import Dialect
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
    ObjectDependentSchemaProperty,
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
from subschema.ir.evaluation import (
    EvaluationFrontier,
)
from subschema.ir.terms import SchemaNodeRef, SchemaTerm
from subschema.provenance import SchemaSource

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
DomainFactStatus = Literal["exact", "overapprox", "unsupported"]
RecursiveReferenceGuard = Literal["array", "object", "object/array", "unguarded"]
RecursiveReferencePolarity = Literal["positive", "negative"]

__all__ = [
    "AssertionAtom",
    "ApplicatorKind",
    "ApplicatorNode",
    "ArraySelectorCandidate",
    "ArrayAnyOfItemSchemasConstraint",
    "ArrayContainsConstraint",
    "ArrayContainsFragmentConstraint",
    "ArrayItemValuesFragmentConstraint",
    "ArrayLengthConstraint",
    "ArrayTupleAnyOfDistributionConstraint",
    "ArrayUniquenessConstraint",
    "DomainFactInfo",
    "DomainFactStatus",
    "DynamicReferenceSemantics",
    "EvaluationFrontier",
    "FiniteConstraint",
    "IRAssertionKind",
    "LogicalSchemaIR",
    "NumericConstraint",
    "ObjectClosedPropertiesConstraint",
    "ObjectDependentSchemaPropertiesConstraint",
    "ObjectDependentSchemaProperty",
    "ObjectPropertyCountBoundsConstraint",
    "ObjectPropertyCountConstraint",
    "ObjectPropertyNamesConstraint",
    "ObjectPropertyValuesConstraint",
    "ObjectSelectorCandidate",
    "RecursiveReferenceFact",
    "RecursiveReferenceGuard",
    "RecursiveReferenceObligation",
    "RecursiveReferencePolarity",
    "ReferenceSemantics",
    "ReferenceUnsupportedFact",
    "SchemaDocumentIR",
    "SchemaSemantics",
    "SchemaNodeRef",
    "SchemaNode",
    "SchemaTerm",
    "StaticReferenceSemantics",
    "StringLanguageConstraint",
    "StringLengthConstraint",
    "TaggedBranch",
    "TaggedOneOf",
    "TypeConstraint",
    "UnsupportedNode",
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
    schema: Any
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
class RecursiveReferenceFact:
    keyword: str
    path: tuple[str, ...]
    ref: str | None = None
    guard_kind: RecursiveReferenceGuard = "unguarded"
    polarity: RecursiveReferencePolarity = "positive"
    target_ref: SchemaNodeRef | None = None


@dataclass(frozen=True)
class RecursiveReferenceObligation:
    side: ProofSide
    keyword: str
    path: tuple[str, ...]
    ref: str | None
    guard_kind: RecursiveReferenceGuard
    polarity: RecursiveReferencePolarity
    target_ref: SchemaNodeRef | None = None

    @property
    def can_defer(self) -> bool:
        return (
            self.keyword == "$ref"
            and self.polarity == "positive"
            and self.guard_kind in {"array", "object", "object/array"}
        )

    def diagnostic(self) -> UnsupportedDiagnostic:
        return UnsupportedDiagnostic(
            "recursive-reference",
            _recursive_reference_obligation_reason(self),
            keyword=self.keyword,
            path=self.path,
            side=self.side,
            disposition="deferable" if self.can_defer else "terminal",
        )


def _recursive_reference_obligation_reason(
    obligation: RecursiveReferenceObligation,
) -> str:
    if obligation.keyword == "$recursiveRef":
        if obligation.polarity == "negative":
            return (
                "negative-polarity $recursiveRef requires guarded recursive "
                "reference proof support"
            )
        return "$recursiveRef requires guarded recursive reference proof support"
    ref = repr(obligation.ref) if obligation.ref is not None else "<unknown>"
    polarity = "negative-polarity " if obligation.polarity == "negative" else ""
    if obligation.guard_kind == "unguarded":
        return (
            "SAT static-reference fragment found "
            f"{polarity}unguarded recursive {obligation.side} $ref {ref}"
        )
    return (
        "SAT static-reference fragment found "
        f"{polarity}{obligation.guard_kind}-guarded recursive "
        f"{obligation.side} $ref {ref}; guarded recursive reference proofs are "
        "unsupported"
    )


@dataclass(frozen=True)
class ReferenceUnsupportedFact:
    reason: str
    path: tuple[str, ...]
    category: UnsupportedCategory = "static-reference"
    keyword: str = "$ref"
    ref: str | None = None
    guard_kind: RecursiveReferenceGuard | None = None
    polarity: RecursiveReferencePolarity = "positive"

    def diagnostic(self, side: ProofSide) -> UnsupportedDiagnostic:
        return UnsupportedDiagnostic(
            category=self.category,
            reason=self.reason,
            keyword=self.keyword,
            path=self.path,
            side=side,
        )


@dataclass(frozen=True)
class StaticReferenceSemantics:
    ref: str | None = None
    target: SchemaTerm | None = None
    lhs_unsupported: ReferenceUnsupportedFact | None = None
    rhs_unsupported: ReferenceUnsupportedFact | None = None

    def unsupported(self, side: ProofSide) -> ReferenceUnsupportedFact | None:
        return self.lhs_unsupported if side == "lhs" else self.rhs_unsupported


@dataclass(frozen=True)
class DynamicReferenceSemantics:
    target: SchemaTerm | None = None
    lhs_unsupported: ReferenceUnsupportedFact | None = None
    rhs_unsupported: ReferenceUnsupportedFact | None = None

    def unsupported(self, side: ProofSide) -> ReferenceUnsupportedFact | None:
        return self.lhs_unsupported if side == "lhs" else self.rhs_unsupported


@dataclass(frozen=True)
class ReferenceSemantics:
    has_static_reference_boundary: bool = False
    has_non_recursive_static_reference_boundary: bool = False
    static_reference_paths: tuple[tuple[str, ...], ...] = ()
    has_dynamic_reference: bool = False
    has_recursive_reference: bool = False
    recursive_references: tuple[RecursiveReferenceFact, ...] = ()
    recursive_obligations: tuple[RecursiveReferenceObligation, ...] = ()
    static_reference: StaticReferenceSemantics = field(
        default_factory=StaticReferenceSemantics
    )
    dynamic_reference: DynamicReferenceSemantics = field(
        default_factory=DynamicReferenceSemantics
    )


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



    @property
    def finite_constraint(self) -> FiniteConstraint | None:
        return self.scalar.finite_constraint

    @property
    def type_constraint(self) -> TypeConstraint | None:
        return self.scalar.type_constraint

    @property
    def numeric_constraint(self) -> NumericConstraint | None:
        return self.scalar.numeric_constraint

    @property
    def string_length_constraint(self) -> StringLengthConstraint | None:
        return self.scalar.string_length_constraint

    @property
    def string_language_constraint(self) -> StringLanguageConstraint | None:
        return self.scalar.string_language_constraint

    @property
    def array_length_lhs_constraint(self) -> ArrayLengthConstraint | None:
        return self.array.array_length_lhs_constraint

    @property
    def array_length_rhs_constraint(self) -> ArrayLengthConstraint | None:
        return self.array.array_length_rhs_constraint

    @property
    def array_any_of_item_schemas_constraint(
        self,
    ) -> ArrayAnyOfItemSchemasConstraint | None:
        return self.array.array_any_of_item_schemas_constraint

    @property
    def array_tuple_anyof_distribution_constraint(
        self,
    ) -> ArrayTupleAnyOfDistributionConstraint | None:
        return self.array.array_tuple_anyof_distribution_constraint

    @property
    def array_contains_constraint(self) -> ArrayContainsConstraint | None:
        return self.array.array_contains_constraint

    @property
    def array_contains_counts(self) -> tuple[int, int | None] | None:
        return self.array.array_contains_counts

    @property
    def array_cardinality_length_constraint(self) -> ArrayLengthConstraint | None:
        return self.array.array_cardinality_length_constraint

    @property
    def array_item_model_constraint(self) -> ArrayItemModelConstraint | None:
        return self.array.array_item_model_constraint

    @property
    def array_contains_fragment_constraint(
        self,
    ) -> ArrayContainsFragmentConstraint:
        return self.array.array_contains_fragment_constraint

    @property
    def array_item_values_fragment_constraint(
        self,
    ) -> ArrayItemValuesFragmentConstraint:
        return self.array.array_item_values_fragment_constraint

    @property
    def array_unevaluated_items_true_fragment_supported(self) -> bool:
        return self.array.array_unevaluated_items_true_fragment_supported

    @property
    def array_uniqueness_lhs_constraint(self) -> ArrayUniquenessConstraint | None:
        return self.array.array_uniqueness_lhs_constraint

    @property
    def array_uniqueness_rhs_constraint(self) -> ArrayUniquenessConstraint | None:
        return self.array.array_uniqueness_rhs_constraint

    @property
    def array_selector_candidates(self) -> tuple[ArraySelectorCandidate, ...]:
        return self.array.selector_candidates

    @property
    def object_property_count_constraint(self) -> ObjectPropertyCountConstraint | None:
        return self.object.object_property_count_constraint

    @property
    def object_property_count_bounds_constraint(
        self,
    ) -> ObjectPropertyCountBoundsConstraint | None:
        return self.object.object_property_count_bounds_constraint

    @property
    def object_dependent_schema_properties_constraint(
        self,
    ) -> ObjectDependentSchemaPropertiesConstraint | None:
        return self.object.object_dependent_schema_properties_constraint

    @property
    def object_dependent_schema_required_constraint(
        self,
    ) -> ObjectDependentRequiredConstraint | None:
        return self.object.object_dependent_schema_required_constraint

    @property
    def object_dependent_required_constraint(
        self,
    ) -> ObjectDependentRequiredConstraint | None:
        return self.object.object_dependent_required_constraint

    @property
    def object_property_values_constraint(
        self,
    ) -> ObjectPropertyValuesConstraint | None:
        return self.object.object_property_values_constraint

    @property
    def object_closed_properties_constraint(
        self,
    ) -> ObjectClosedPropertiesConstraint | None:
        return self.object.object_closed_properties_constraint

    @property
    def object_property_names_constraint(self) -> ObjectPropertyNamesConstraint | None:
        return self.object.object_property_names_constraint

    @property
    def object_key_value_constraint(self) -> ObjectKeyValueConstraint | None:
        return self.object.object_key_value_constraint

    @property
    def object_presence_product_constraint(
        self,
    ) -> ObjectPresenceProductConstraint | None:
        return self.object.object_presence_product_constraint

    @property
    def object_property_names_has_value_constraints(self) -> bool:
        return self.object.object_property_names_has_value_constraints

    @property
    def object_unevaluated_properties_true_fragment_supported(self) -> bool:
        return (
            self.object
            .object_unevaluated_properties_true_fragment_supported
        )

    @property
    def object_selector_candidates(self) -> tuple[ObjectSelectorCandidate, ...]:
        return self.object.selector_candidates

    @property
    def tagged_one_of(self) -> TaggedOneOf | None:
        return self.applicator.tagged_one_of

    @property
    def required_singleton_tags(self) -> tuple[tuple[str, Any], ...]:
        return self.applicator.required_singleton_tags

    @property
    def covered_type_atoms(self) -> frozenset[str]:
        return self.scalar.covered_type_atoms

    @property
    def has_object_or_array_assertions(self) -> bool:
        return self.object.has_object_or_array_assertions

    @property
    def has_string_assertions(self) -> bool:
        return self.scalar.has_string_assertions

    @property
    def has_numeric_assertions(self) -> bool:
        return self.scalar.has_numeric_assertions

    @property
    def has_static_reference_boundary(self) -> bool:
        return self.reference.has_static_reference_boundary

    @property
    def has_dynamic_reference(self) -> bool:
        return self.reference.has_dynamic_reference

    @property
    def has_recursive_reference(self) -> bool:
        return self.reference.has_recursive_reference

    @property
    def finite_values(self) -> tuple[Any, ...] | None:
        constraint = self.finite_constraint
        return None if constraint is None else constraint.values

    @property
    def type_shape(self) -> TypeConstraint | None:
        return self.type_constraint

    @property
    def numeric_shape(self) -> NumericConstraint | None:
        return self.numeric_constraint

    @property
    def string_length_shape(self) -> StringLengthConstraint | None:
        return self.string_length_constraint

    @property
    def string_language_shape(self) -> StringLanguageConstraint | None:
        return self.string_language_constraint

    @property
    def array_length_lhs_shape(self) -> ArrayLengthConstraint | None:
        return self.array_length_lhs_constraint

    @property
    def array_length_rhs_shape(self) -> ArrayLengthConstraint | None:
        return self.array_length_rhs_constraint

    @property
    def array_uniqueness_lhs_shape(self) -> ArrayUniquenessConstraint | None:
        return self.array_uniqueness_lhs_constraint

    @property
    def array_uniqueness_rhs_shape(self) -> ArrayUniquenessConstraint | None:
        return self.array_uniqueness_rhs_constraint

    @property
    def object_property_count_shape(self) -> ObjectPropertyCountConstraint | None:
        return self.object_property_count_constraint

    @property
    def object_property_values_shape(self) -> ObjectPropertyValuesConstraint | None:
        return self.object_property_values_constraint

    @property
    def object_closed_properties_shape(
        self,
    ) -> ObjectClosedPropertiesConstraint | None:
        return self.object_closed_properties_constraint

    @property
    def object_property_names_shape(self) -> ObjectPropertyNamesConstraint | None:
        return self.object_property_names_constraint

    @property
    def has_non_numeric_assertions(self) -> bool:
        return self.has_object_or_array_assertions or self.has_string_assertions

    def required_singleton_tag(self, tag_name: str) -> Any | None:
        for name, value in self.required_singleton_tags:
            if name == tag_name:
                return value
        return None

    def accepts_only_type(self, atom: str) -> bool:
        constraint = self.type_constraint
        return constraint is not None and constraint.atoms == frozenset({atom})

    def covers_type_atom(self, atom: str) -> bool:
        return atom in self.covered_type_atoms

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
    base_term: SchemaTerm = field(default_factory=SchemaTerm.true)
    base_semantic_keywords: frozenset[str] = frozenset()


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
    ref: SchemaNodeRef
    source: SchemaSource
    semantics: SchemaSemantics
    boolean_value: bool | None = None
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
class SchemaDocumentIR:
    source: SchemaSource
    root_ref: SchemaNodeRef
    nodes: Mapping[SchemaNodeRef, SchemaNode] = field(default_factory=dict)

    @property
    def root(self) -> SchemaNode:
        root = self.node_for_ref(self.root_ref)
        if root is None:
            raise KeyError("schema document root ref is not registered")
        return root

    def node_for_ref(self, ref: SchemaNodeRef) -> SchemaNode | None:
        found = self.nodes.get(ref)
        if found is not None:
            return found
        return _find_node_for_ref(self.root, ref)


@dataclass(frozen=True)
class LogicalSchemaIR:
    document: SchemaDocumentIR
    root_ref: SchemaNodeRef

    @property
    def root(self) -> SchemaNode:
        root = self.node_for_ref(self.root_ref)
        if root is None:
            raise KeyError("schema IR root ref is not registered")
        return root

    @property
    def nodes(self) -> Mapping[SchemaNodeRef, SchemaNode]:
        return self.document.nodes

    @property
    def source(self) -> SchemaSource:
        return self.root.source

    @property
    def root_term(self) -> SchemaTerm:
        return SchemaTerm.node(self.root_ref)

    def term_for_node(self, node: SchemaNode) -> SchemaTerm:
        return SchemaTerm.node(node.ref)

    def node_for_ref(self, ref: SchemaNodeRef) -> SchemaNode | None:
        return self.document.node_for_ref(ref)

    def with_root(self, root: SchemaNode) -> LogicalSchemaIR:
        return self.with_root_ref(root.ref)

    def with_root_ref(self, ref: SchemaNodeRef) -> LogicalSchemaIR:
        if self.node_for_ref(ref) is None:
            raise KeyError("schema IR root ref is not registered")
        return LogicalSchemaIR(self.document, ref)

    @property
    def dialect(self) -> Dialect:
        return self.source.dialect

    @property
    def semantics(self) -> SchemaSemantics:
        return self.root.semantics

    @property
    def evaluation(self) -> EvaluationFrontier:
        return self.root.evaluation

    @property
    def assertions(self) -> tuple[AssertionAtom, ...]:
        return self.semantics.assertions()

    @property
    def applicators(self) -> tuple[ApplicatorNode, ...]:
        return self.root.applicators

    @property
    def unsupported(self) -> tuple[UnsupportedNode, ...]:
        return self.root.all_unsupported

    def assertion(self, kind: IRAssertionKind) -> AssertionAtom | None:
        return self.semantics.assertion(kind)

    @property
    def finite_values(self) -> tuple[Any, ...] | None:
        return self.semantics.finite_values

    @property
    def finite_constraint(self) -> FiniteConstraint | None:
        return self.semantics.finite_constraint

    @property
    def type_shape(self) -> TypeConstraint | None:
        return self.semantics.type_shape

    @property
    def type_constraint(self) -> TypeConstraint | None:
        return self.semantics.type_constraint

    @property
    def numeric_shape(self) -> NumericConstraint | None:
        return self.semantics.numeric_shape

    @property
    def numeric_constraint(self) -> NumericConstraint | None:
        return self.semantics.numeric_constraint

    @property
    def string_length_shape(self) -> StringLengthConstraint | None:
        return self.semantics.string_length_shape

    @property
    def string_length_constraint(self) -> StringLengthConstraint | None:
        return self.semantics.string_length_constraint

    @property
    def string_language_shape(self) -> StringLanguageConstraint | None:
        return self.semantics.string_language_shape

    @property
    def string_language_constraint(self) -> StringLanguageConstraint | None:
        return self.semantics.string_language_constraint

    @property
    def array_length_lhs_constraint(self) -> ArrayLengthConstraint | None:
        return self.semantics.array_length_lhs_constraint

    @property
    def array_length_rhs_constraint(self) -> ArrayLengthConstraint | None:
        return self.semantics.array_length_rhs_constraint

    @property
    def array_any_of_item_schemas_constraint(
        self,
    ) -> ArrayAnyOfItemSchemasConstraint | None:
        return self.semantics.array_any_of_item_schemas_constraint

    @property
    def array_tuple_anyof_distribution_constraint(
        self,
    ) -> ArrayTupleAnyOfDistributionConstraint | None:
        return self.semantics.array_tuple_anyof_distribution_constraint

    @property
    def array_contains_constraint(self) -> ArrayContainsConstraint | None:
        return self.semantics.array_contains_constraint

    @property
    def array_contains_counts(self) -> tuple[int, int | None] | None:
        return self.semantics.array_contains_counts

    @property
    def array_cardinality_length_constraint(self) -> ArrayLengthConstraint | None:
        return self.semantics.array_cardinality_length_constraint

    @property
    def array_item_model_constraint(self) -> ArrayItemModelConstraint | None:
        return self.semantics.array_item_model_constraint

    @property
    def array_contains_fragment_constraint(
        self,
    ) -> ArrayContainsFragmentConstraint:
        return self.semantics.array_contains_fragment_constraint

    @property
    def array_item_values_fragment_constraint(
        self,
    ) -> ArrayItemValuesFragmentConstraint:
        return self.semantics.array_item_values_fragment_constraint

    @property
    def array_unevaluated_items_true_fragment_supported(self) -> bool:
        return self.semantics.array_unevaluated_items_true_fragment_supported

    @property
    def array_uniqueness_lhs_constraint(self) -> ArrayUniquenessConstraint | None:
        return self.semantics.array_uniqueness_lhs_constraint

    @property
    def array_uniqueness_rhs_constraint(self) -> ArrayUniquenessConstraint | None:
        return self.semantics.array_uniqueness_rhs_constraint

    @property
    def object_property_count_constraint(self) -> ObjectPropertyCountConstraint | None:
        return self.semantics.object_property_count_constraint

    @property
    def object_property_count_bounds_constraint(
        self,
    ) -> ObjectPropertyCountBoundsConstraint | None:
        return self.semantics.object_property_count_bounds_constraint

    @property
    def object_dependent_schema_properties_constraint(
        self,
    ) -> ObjectDependentSchemaPropertiesConstraint | None:
        return self.semantics.object_dependent_schema_properties_constraint

    @property
    def object_dependent_schema_required_constraint(
        self,
    ) -> ObjectDependentRequiredConstraint | None:
        return self.semantics.object_dependent_schema_required_constraint

    @property
    def object_property_names_constraint(self) -> ObjectPropertyNamesConstraint | None:
        return self.semantics.object_property_names_constraint

    @property
    def object_property_values_constraint(
        self,
    ) -> ObjectPropertyValuesConstraint | None:
        return self.semantics.object_property_values_constraint

    @property
    def object_closed_properties_constraint(
        self,
    ) -> ObjectClosedPropertiesConstraint | None:
        return self.semantics.object_closed_properties_constraint

    @property
    def object_key_value_constraint(self) -> ObjectKeyValueConstraint | None:
        return self.semantics.object_key_value_constraint

    @property
    def object_presence_product_constraint(
        self,
    ) -> ObjectPresenceProductConstraint | None:
        return self.semantics.object_presence_product_constraint

    @property
    def object_property_names_has_value_constraints(self) -> bool:
        return self.semantics.object_property_names_has_value_constraints

    @property
    def object_unevaluated_properties_true_fragment_supported(self) -> bool:
        return self.semantics.object_unevaluated_properties_true_fragment_supported

    @property
    def tagged_one_of(self) -> TaggedOneOf | None:
        return self.semantics.tagged_one_of

    def required_singleton_tag(self, tag_name: str) -> Any | None:
        return self.semantics.required_singleton_tag(tag_name)

    def accepts_only_type(self, atom: str) -> bool:
        return self.semantics.accepts_only_type(atom)

    def covers_type_atom(self, atom: str) -> bool:
        return self.semantics.covers_type_atom(atom)

    @property
    def has_static_reference_boundary(self) -> bool:
        return self.semantics.has_static_reference_boundary

    @property
    def has_dynamic_reference(self) -> bool:
        return self.semantics.has_dynamic_reference

    @property
    def has_recursive_reference(self) -> bool:
        return self.semantics.has_recursive_reference




def _find_node_for_ref(node: SchemaNode, ref: SchemaNodeRef) -> SchemaNode | None:
    if node.ref == ref:
        return node
    for applicator in node.applicators:
        for child in applicator.children:
            found = _find_node_for_ref(child, ref)
            if found is not None:
                return found
    return None


def _escape_pointer_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")
