"""
Compiler-owned semantic assembly for raw JSON Schema syntax.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from subschema.compiler.domains.arrays import (
    array_any_of_item_schemas_for_schema,
    array_cardinality_length_shape_for_schema,
    array_contains_counts_for_schema,
    array_contains_fragment_support_for_schema,
    array_item_values_fragment_support_for_schema,
    array_shape_for_schema,
    array_tuple_anyof_distribution_branches_for_schema,
    array_unevaluated_items_true_fragment_supported,
    array_unique_items_requirement_for_schema,
    array_uniqueness_shape_for_schema,
)
from subschema.compiler.domains.numbers import numeric_shape_for_schema
from subschema.compiler.domains.objects import (
    closed_object_properties_shape_for_schema,
    object_dependent_required_entries_for_schema,
    object_dependent_schema_properties_for_schema,
    object_dependent_schema_required_entries_for_schema,
    object_key_value_shape_for_schema,
    object_property_count_bounds_for_schema,
    object_property_count_shape_for_schema,
    object_property_names_schema_has_value_constraints,
    object_property_names_shape_for_schema,
    object_property_values_shape_for_schema,
    object_unevaluated_properties_true_fragment_supported,
)
from subschema.compiler.domains.strings import (
    string_language_shape_for_schema,
    string_shape_for_schema,
)
from subschema.compiler.domains.types import (
    schema_covers_type_atom,
    type_language_complete_for_schema,
    type_shape_for_schema,
    type_shape_for_type_keyword,
)
from subschema.compiler.evaluation import evaluation_frontier_for_schema
from subschema.compiler.finite_values import finite_values_for_schema
from subschema.compiler.normalization import (
    SCHEMA_ARRAY_KEYWORDS,
    SCHEMA_MAP_KEYWORDS,
    SCHEMA_VALUE_KEYWORDS,
)
from subschema.compiler.resources import (
    ResourceGraph,
    recursive_guard_kind_for_path,
    recursive_reference_polarity_for_path,
)
from subschema.compiler.schemas import (
    DEDICATED_IR_KEYWORDS,
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
)
from subschema.compiler.tagged_unions import (
    schema_required_singleton_tags,
    tagged_one_of,
)
from subschema.contracts import ProofResult, UnsupportedCategory
from subschema.dialects import Dialect
from subschema.ir import (
    ApplicatorSemantics,
    ArraySelectorCandidate,
    ArraySemantics,
    EvaluationSemantics,
    ObjectSelectorCandidate,
    ObjectSemantics,
    RecursiveReferenceFact,
    RecursiveReferenceGuard,
    RecursiveReferencePolarity,
    ReferenceSemantics,
    ScalarSemantics,
    SchemaSemantics,
    UnsupportedNode,
    VocabularySemantics,
)
from subschema.ir.constraints import (
    JSON_TYPE_ATOMS,
    ArrayAnyOfItemSchemasConstraint,
    ArrayContainsConstraint,
    ArrayContainsFragmentConstraint,
    ArrayItemModelConstraint,
    ArrayItemValuesFragmentConstraint,
    ArrayLengthConstraint,
    ArrayLengthIntervalFact,
    ArrayTupleAnyOfDistributionConstraint,
    ArrayUniquenessConstraint,
    FiniteConstraint,
    NumericAtomFact,
    NumericConstraint,
    ObjectClosedPropertiesConstraint,
    ObjectDependentRequiredConstraint,
    ObjectDependentRequiredEntry,
    ObjectDependentSchemaPropertiesConstraint,
    ObjectDependentSchemaProperty,
    ObjectKeyValueConstraint,
    ObjectKeyValuePattern,
    ObjectPresenceLocalConstraint,
    ObjectPresenceProductConstraint,
    ObjectPropertyCountBoundsConstraint,
    ObjectPropertyCountConstraint,
    ObjectPropertyCountIntervalFact,
    ObjectPropertyNamesConstraint,
    ObjectPropertyValuesConstraint,
    StringLanguageConstraint,
    StringLengthConstraint,
    StringLengthIntervalFact,
    TypeConstraint,
)
from subschema.ir.evaluation import EvaluationFrontier
from subschema.ir.terms import SchemaTerm
from subschema.regex import RegexLanguage

__all__ = [
    "build_schema_semantics",
    "compile_schema_unsupported_nodes",
]

_APPLICATOR_ASSERTION_SCAN_KEYS = frozenset(
    {"allOf", "anyOf", "else", "if", "not", "oneOf", "then"}
)
_OBJECT_ARRAY_ASSERTION_KEYWORDS = frozenset(
    {
        "additionalItems",
        "additionalProperties",
        "contains",
        "dependentRequired",
        "dependentSchemas",
        "dependencies",
        "items",
        "maxContains",
        "maxItems",
        "maxProperties",
        "minContains",
        "minItems",
        "minProperties",
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
_OBJECT_PRESENCE_PRODUCT_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "allOf",
        "anyOf",
        "dependentRequired",
        "dependentSchemas",
        "dependencies",
        "maxProperties",
        "minProperties",
        "not",
        "oneOf",
        "properties",
        "required",
        "type",
    }
)
_NUMERIC_ASSERTION_KEYWORDS = frozenset(
    {"exclusiveMaximum", "exclusiveMinimum", "maximum", "minimum", "multipleOf"}
)
_STRING_ASSERTION_KEYWORDS = frozenset(
    {"const", "enum", "maxLength", "minLength", "pattern"}
)
_SCALAR_SEMANTIC_KEYWORDS = frozenset(
    {
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maximum",
        "maxLength",
        "minimum",
        "minLength",
        "multipleOf",
        "pattern",
        "type",
    }
)
_ARRAY_SEMANTIC_KEYWORDS = frozenset(
    {
        "additionalItems",
        "contains",
        "items",
        "maxContains",
        "maxItems",
        "minContains",
        "minItems",
        "prefixItems",
        "uniqueItems",
    }
)
_OBJECT_SEMANTIC_KEYWORDS = frozenset(
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
    }
)
_APPLICATOR_SEMANTIC_KEYWORDS = frozenset(
    {"allOf", "anyOf", "else", "if", "not", "oneOf", "then"}
)
_REFERENCE_SEMANTIC_KEYWORDS = frozenset(
    {
        "$anchor",
        "$defs",
        "$dynamicAnchor",
        "$dynamicRef",
        "$id",
        "$recursiveAnchor",
        "$recursiveRef",
        "$ref",
        "definitions",
        "id",
    }
)
_EVALUATION_SEMANTIC_KEYWORDS = frozenset(
    {"unevaluatedItems", "unevaluatedProperties"}
)
_ANNOTATION_SEMANTIC_KEYWORDS = frozenset(
    {
        "$comment",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "default",
        "deprecated",
        "description",
        "discriminator",
        "examples",
        "format",
        "readOnly",
        "title",
        "writeOnly",
    }
)
_VOCABULARY_SEMANTIC_KEYWORDS = frozenset({"$schema", "$vocabulary"})


def compile_schema_unsupported_nodes(
    schema: Any,
    evaluation: EvaluationFrontier,
    dialect: Dialect,
    path: tuple[str, ...],
) -> tuple[UnsupportedNode, ...]:
    if not isinstance(schema, dict):
        return ()

    nodes = [
        _unsupported_node(keyword, evaluation, path + (keyword,))
        for keyword in sorted(DEDICATED_IR_KEYWORDS.intersection(schema))
    ]
    nodes.extend(_regex_unsupported_nodes(schema, path))
    nodes.extend(_nested_unsupported(schema, dialect, path))
    return tuple(nodes)


def _array_contains_constraint_for_schema(
    schema: Any,
    evaluation: EvaluationFrontier,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
) -> ArrayContainsConstraint | None:
    if not isinstance(schema, dict) or "contains" not in schema:
        return None

    minimum = schema.get("minContains", 1)
    maximum = schema.get("maxContains")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None

    contains_sources = tuple(
        source for source in evaluation.item_sources if source.kind == "contains"
    )
    return ArrayContainsConstraint(
        minimum,
        maximum,
        any(source.marks_contains_matches for source in contains_sources),
        SchemaTerm.true()
        if child_term is None
        else child_term(schema["contains"], ("contains",)),
    )


def _array_any_of_item_terms_for_schema(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
) -> tuple[SchemaTerm, ...] | None:
    if child_term is None or not isinstance(schema, dict):
        return None
    branches = schema.get("anyOf")
    if not isinstance(branches, list) or not branches:
        return None

    terms: list[SchemaTerm] = []
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict) or branch.get("type") != "array":
            return None
        items = branch.get("items", True)
        if not isinstance(items, dict):
            return None
        terms.append(child_term(items, ("anyOf", str(index), "items")))
    return tuple(terms)


def _array_tuple_anyof_distribution_terms_for_branches(
    branches: tuple[Any, ...] | None,
    synthetic_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
) -> tuple[SchemaTerm, ...] | None:
    if branches is None or synthetic_term is None:
        return None
    return tuple(
        synthetic_term(
            branch,
            ("$synthetic", "arrayTupleAnyOfDistribution", str(index)),
        )
        for index, branch in enumerate(branches)
    )


def _numeric_constraint_from_shape(shape: Any | None) -> NumericConstraint | None:
    if shape is None:
        return None
    return NumericConstraint(
        tuple(
            NumericAtomFact(
                integer_only=atom.integer_only,
                lower=atom.lower,
                lower_inclusive=atom.lower_inclusive,
                upper=atom.upper,
                upper_inclusive=atom.upper_inclusive,
                multiple_of=atom.multiple_of,
            )
            for atom in shape.atoms
        ),
        accepts_non_numeric=shape.accepts_non_numeric,
        exact=shape.exact,
    )


def _string_length_constraint_from_shape(shape: Any) -> StringLengthConstraint:
    return StringLengthConstraint(
        tuple(
            StringLengthIntervalFact(interval.lower, interval.upper)
            for interval in shape.intervals
        ),
        accepts_non_string=shape.accepts_non_string,
        exact=shape.exact,
    )


def _string_language_constraint_from_shape(shape: Any) -> StringLanguageConstraint:
    return StringLanguageConstraint(
        shape.pattern,
        accepts_non_string=shape.accepts_non_string,
        exact=shape.exact,
    )


def _array_length_constraint_from_shape(
    shape: Any | None,
) -> ArrayLengthConstraint | None:
    if shape is None:
        return None
    return ArrayLengthConstraint(
        tuple(
            ArrayLengthIntervalFact(interval.lower, interval.upper)
            for interval in shape.intervals
        ),
        accepts_non_array=shape.accepts_non_array,
        exact=shape.exact,
    )


def _array_length_constraint_for_schema(
    shape: Any | None,
    type_shape: Any | None,
) -> ArrayLengthConstraint | None:
    constraint = _array_length_constraint_from_shape(shape)
    if constraint is not None:
        return constraint
    if type_shape is None or "array" not in type_shape.atoms:
        return None
    return ArrayLengthConstraint(
        (ArrayLengthIntervalFact(0, None),),
        accepts_non_array=_type_shape_accepts_any_atom_except(type_shape, "array"),
        exact=False,
    )


def _array_uniqueness_constraint_from_shape(
    shape: Any | None,
) -> ArrayUniquenessConstraint | None:
    if shape is None:
        return None
    return ArrayUniquenessConstraint(
        accepts_array=shape.accepts_array,
        accepts_non_array=shape.accepts_non_array,
        requires_unique_items=shape.requires_unique_items,
        guarantees_unique_items=shape.guarantees_unique_items,
        complete_uniqueness_fragment=shape.complete_uniqueness_fragment,
    )


def _array_item_model_constraint_for_schema(
    schema: Any,
    dialect: Dialect,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
) -> ArrayItemModelConstraint | None:
    if not isinstance(schema, dict):
        return None
    if dialect is Dialect.DRAFT202012:
        prefix = schema.get("prefixItems")
        prefix_terms = (
            ()
            if child_term is None or not isinstance(prefix, list)
            else tuple(
                child_term(item, ("prefixItems", str(index)))
                for index, item in enumerate(prefix)
            )
        )
        tail = schema.get("items", True)
        tail_path = ("items",)
    else:
        items = schema.get("items", True)
        if isinstance(items, list):
            prefix_terms = (
                ()
                if child_term is None
                else tuple(
                    child_term(item, ("items", str(index)))
                    for index, item in enumerate(items)
                )
            )
            tail = schema.get("additionalItems", True)
            tail_path = ("additionalItems",)
        else:
            prefix_terms = ()
            tail = items
            tail_path = ("items",)
    if not isinstance(tail, bool | dict):
        tail = None
    tail_term = (
        _schema_term_for_boolean_or_child(tail, child_term, tail_path)
        if tail is not None
        else None
    )
    first_required_item_term = _array_first_required_item_term_for_schema(
        schema, dialect, prefix_terms, tail_term
    )
    covering_all_item_terms = _array_item_terms_covering_all_items_for_schema(
        schema, dialect, prefix_terms, tail_term
    )
    return ArrayItemModelConstraint(
        prefix_terms=prefix_terms,
        tail_term=tail_term,
        first_required_item_term=first_required_item_term,
        covering_all_item_terms=covering_all_item_terms,
    )


def _array_first_required_item_term_for_schema(
    schema: Any,
    dialect: Dialect,
    prefix_terms: tuple[SchemaTerm, ...],
    tail_term: SchemaTerm | None,
) -> SchemaTerm | None:
    if not isinstance(schema, dict):
        return None
    minimum = schema.get("minItems", 0)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum <= 0:
        return None
    if dialect is Dialect.DRAFT202012:
        return prefix_terms[0] if prefix_terms else tail_term
    items = schema.get("items", True)
    if isinstance(items, list):
        return prefix_terms[0] if prefix_terms else None
    return tail_term


def _array_item_terms_covering_all_items_for_schema(
    schema: Any,
    dialect: Dialect,
    prefix_terms: tuple[SchemaTerm, ...],
    tail_term: SchemaTerm | None,
) -> tuple[SchemaTerm, ...] | None:
    if not isinstance(schema, dict):
        return None
    if dialect is Dialect.DRAFT202012:
        items = schema.get("items", True)
        if items is False:
            return prefix_terms
        if isinstance(items, dict) and tail_term is not None:
            return prefix_terms + (tail_term,)
        return None

    items = schema.get("items", True)
    if isinstance(items, bool | dict):
        return () if tail_term is None else (tail_term,)
    if isinstance(items, list):
        additional = schema.get("additionalItems", True)
        if additional is False:
            return prefix_terms
        if isinstance(additional, dict) and tail_term is not None:
            return prefix_terms + (tail_term,)
    return None


def _object_property_count_constraint_from_shape(
    shape: Any | None,
) -> ObjectPropertyCountConstraint | None:
    if shape is None:
        return None
    return ObjectPropertyCountConstraint(
        tuple(
            ObjectPropertyCountIntervalFact(interval.lower, interval.upper)
            for interval in shape.intervals
        ),
        accepts_non_object=shape.accepts_non_object,
        exact=shape.exact,
    )


def _object_property_values_constraint_for_schema(
    shape: Any | None,
    schema: Any,
    type_shape: Any | None,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
    recursive_static_reference_child: (
        Callable[[SchemaTerm, tuple[str, ...]], bool] | None
    ) = None,
) -> ObjectPropertyValuesConstraint | None:
    property_terms = _all_of_property_terms_for_schema(schema, child_term)
    if shape is None:
        property_terms = {
            name: terms
            for name, terms in property_terms.items()
            if any(
                recursive_static_reference_child is not None
                and recursive_static_reference_child(term, ())
                for term in terms
            )
        }
        if not property_terms:
            return None
        return ObjectPropertyValuesConstraint(
            _all_of_required_names_for_schema(schema),
            accepts_object=_type_shape_accepts_atom(type_shape, "object"),
            accepts_non_object=_type_shape_accepts_any_atom_except(
                type_shape, "object"
            ),
            property_terms=property_terms,
        )
    return ObjectPropertyValuesConstraint(
        frozenset(shape.required),
        accepts_object=shape.accepts_object,
        accepts_non_object=shape.accepts_non_object,
        property_terms=property_terms,
    )


def _object_closed_properties_constraint_from_shape(
    shape: Any | None,
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
) -> ObjectClosedPropertiesConstraint | None:
    if shape is None:
        return None
    property_terms = _all_of_property_terms_for_schema(schema, child_term)
    pattern_property_terms = _all_of_pattern_property_terms_for_schema(
        schema, child_term
    )
    return ObjectClosedPropertiesConstraint(
        frozenset(shape.allowed_names),
        shape.keyspace_pattern,
        frozenset(shape.required),
        accepts_object=shape.accepts_object,
        accepts_non_object=shape.accepts_non_object,
        has_finite_keyspace=shape.has_finite_keyspace,
        property_terms=property_terms,
        pattern_property_terms=pattern_property_terms,
    )


def _object_property_names_constraint_from_shape(
    shape: Any | None,
) -> ObjectPropertyNamesConstraint | None:
    if shape is None:
        return None
    return ObjectPropertyNamesConstraint(
        shape.keyspace_pattern,
        frozenset(shape.required),
        accepts_object=shape.accepts_object,
        accepts_non_object=shape.accepts_non_object,
    )


def _object_key_value_constraint_from_shape(
    shape: Any | None,
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
) -> ObjectKeyValueConstraint | None:
    if shape is None:
        return None
    property_terms = {
        name: term
        for name, terms in _property_terms_for_schema(schema, child_term).items()
        for term in (SchemaTerm.all_of(terms),)
    }
    pattern_terms_by_text = _pattern_property_term_by_text(schema, child_term)
    additional_term = _additional_properties_term_for_schema(schema, child_term)
    return ObjectKeyValueConstraint(
        frozenset(shape.properties),
        tuple(
            ObjectKeyValuePattern(
                pattern.text,
                pattern.pattern,
                pattern_terms_by_text.get(pattern.text, SchemaTerm.true()),
            )
            for pattern in shape.patterns
        ),
        shape.keyspace_pattern,
        frozenset(shape.required),
        accepts_object=shape.accepts_object,
        accepts_non_object=shape.accepts_non_object,
        property_terms=property_terms,
        additional_term=additional_term,
    )


def _array_selector_candidates_from_model(
    model: ArrayItemModelConstraint | None,
) -> tuple[ArraySelectorCandidate, ...]:
    if model is None:
        return ()
    return tuple(
        ArraySelectorCandidate(index, term)
        for index, term in enumerate(model.prefix_terms)
    )


def _object_selector_candidates_from_key_values(
    key_values: ObjectKeyValueConstraint | None,
) -> tuple[ObjectSelectorCandidate, ...]:
    if key_values is None:
        return ()
    return tuple(
        ObjectSelectorCandidate(name, term)
        for name in sorted(key_values.required & key_values.properties)
        for term in (key_values.value_term_for(name),)
        if term is not None
    )


def _property_terms_for_schema(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
) -> dict[str, tuple[SchemaTerm, ...]]:
    if child_term is None or not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    return {
        str(name): (child_term(property_schema, ("properties", str(name))),)
        for name, property_schema in properties.items()
        if isinstance(name, str) and isinstance(property_schema, bool | dict)
    }


def _all_of_property_terms_for_schema(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
    path: tuple[str, ...] = (),
) -> dict[str, tuple[SchemaTerm, ...]]:
    if child_term is None or not isinstance(schema, dict):
        return {}
    terms: dict[str, tuple[SchemaTerm, ...]] = {}
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, property_schema in properties.items():
            if not isinstance(name, str) or not isinstance(
                property_schema, bool | dict
            ):
                continue
            terms[name] = terms.get(name, ()) + (
                child_term(property_schema, path + ("properties", name)),
            )

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for index, subschema in enumerate(all_of):
            if not isinstance(subschema, dict):
                continue
            child_terms = _all_of_property_terms_for_schema(
                subschema, child_term, path + ("allOf", str(index))
            )
            for name, name_terms in child_terms.items():
                terms[name] = terms.get(name, ()) + name_terms
    return terms


def _all_of_required_names_for_schema(schema: Any) -> frozenset[str]:
    if not isinstance(schema, dict):
        return frozenset()
    required = schema.get("required")
    names = {item for item in required if isinstance(item, str)} if isinstance(
        required, list
    ) else set()
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for subschema in all_of:
            names.update(_all_of_required_names_for_schema(subschema))
    return frozenset(names)


def _type_shape_accepts_atom(type_shape: Any | None, atom: str) -> bool:
    return type_shape is None or atom in type_shape.atoms


def _type_shape_accepts_any_atom_except(type_shape: Any | None, atom: str) -> bool:
    return type_shape is None or any(item != atom for item in type_shape.atoms)


def _pattern_property_terms_for_schema(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
) -> tuple[tuple[RegexLanguage, SchemaTerm], ...]:
    if child_term is None:
        return ()
    return tuple(
        (pattern, term)
        for _text, pattern, term in _pattern_property_term_entries(schema, child_term)
    )


def _all_of_pattern_property_terms_for_schema(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
    path: tuple[str, ...] = (),
) -> tuple[tuple[RegexLanguage, SchemaTerm], ...]:
    if child_term is None or not isinstance(schema, dict):
        return ()

    entries = [
        (pattern, term)
        for _text, pattern, term in _pattern_property_term_entries(
            schema, child_term, path
        )
    ]
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for index, subschema in enumerate(all_of):
            entries.extend(
                _all_of_pattern_property_terms_for_schema(
                    subschema, child_term, path + ("allOf", str(index))
                )
            )
    return tuple(entries)


def _pattern_property_term_by_text(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
) -> dict[str, SchemaTerm]:
    if child_term is None:
        return {}
    return {
        text: term
        for text, _pattern, term in _pattern_property_term_entries(schema, child_term)
    }


def _pattern_property_term_entries(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm],
    path: tuple[str, ...] = (),
) -> tuple[tuple[str, RegexLanguage, SchemaTerm], ...]:
    if not isinstance(schema, dict):
        return ()
    pattern_properties = schema.get("patternProperties")
    if not isinstance(pattern_properties, dict):
        return ()

    entries = []
    for text, property_schema in pattern_properties.items():
        if not isinstance(text, str) or not isinstance(property_schema, bool | dict):
            continue
        pattern = RegexLanguage.from_json_regex(text)
        if not isinstance(pattern, RegexLanguage):
            continue
        entries.append(
            (
                text,
                pattern,
                child_term(property_schema, path + ("patternProperties", text)),
            )
        )
    return tuple(entries)


def _additional_properties_term_for_schema(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
) -> SchemaTerm | None:
    if child_term is None or not isinstance(schema, dict):
        return None
    value = schema.get("additionalProperties", True)
    if not isinstance(value, bool | dict):
        return None
    return _schema_term_for_boolean_or_child(
        value, child_term, ("additionalProperties",)
    )


def _schema_term_for_boolean_or_child(
    schema: Any,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None,
    path: tuple[str, ...],
) -> SchemaTerm | None:
    if schema is True:
        return SchemaTerm.true()
    if schema is False:
        return SchemaTerm.false()
    if child_term is None or not isinstance(schema, dict):
        return None
    return child_term(schema, path)


def _object_presence_product_constraint_for_schema(
    schema: Any, depth: int = 0
) -> ObjectPresenceProductConstraint | None:
    if depth > 16:
        return None
    if schema is True:
        return ObjectPresenceProductConstraint.true()
    if schema is False:
        return ObjectPresenceProductConstraint.false()
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    if not _is_object_presence_product_schema(schema):
        return None

    local = _local_object_presence_product_constraint(schema)
    if local is None:
        return None

    all_of = _presence_product_children(schema.get("allOf", ()), depth)
    any_of = _presence_product_children(schema.get("anyOf", ()), depth)
    one_of = _presence_product_children(schema.get("oneOf", ()), depth)
    if all_of is None or any_of is None or one_of is None:
        return None

    not_schema = None
    if "not" in schema:
        not_schema = _object_presence_product_constraint_for_schema(
            schema["not"], depth + 1
        )
        if not_schema is None:
            return None

    dependent_schemas = []
    for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
        if not isinstance(trigger, str):
            return None
        child = _object_presence_product_constraint_for_schema(
            dependent_schema, depth + 1
        )
        if child is None:
            return None
        dependent_schemas.append((trigger, child))

    return ObjectPresenceProductConstraint.schema(
        local,
        all_of=all_of,
        any_of=any_of,
        one_of=one_of,
        not_schema=not_schema,
        dependent_schemas=tuple(dependent_schemas),
    )


def _presence_product_children(
    value: Any, depth: int
) -> tuple[ObjectPresenceProductConstraint, ...] | None:
    if not isinstance(value, list | tuple):
        return None
    children = []
    for child_schema in value:
        child = _object_presence_product_constraint_for_schema(child_schema, depth + 1)
        if child is None:
            return None
        children.append(child)
    return tuple(children)


def _local_object_presence_product_constraint(
    schema: dict[str, Any],
) -> ObjectPresenceLocalConstraint | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return None
    property_names = frozenset(name for name in properties if isinstance(name, str))

    required = schema.get("required", [])
    if not _is_string_array(required):
        return None

    dependent_required = []
    for keyword in ("dependentRequired", "dependencies"):
        entries = schema.get(keyword, {})
        if not isinstance(entries, dict):
            return None
        for trigger, dependencies in entries.items():
            if not isinstance(trigger, str) or not _is_string_array(dependencies):
                return None
            dependent_required.append((trigger, frozenset(dependencies)))

    minimum = schema.get("minProperties", 0)
    maximum = schema.get("maxProperties")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None

    return ObjectPresenceLocalConstraint(
        type_shape.atoms,
        property_names,
        frozenset(required),
        schema.get("additionalProperties") is False,
        tuple(dependent_required),
        minimum,
        maximum,
        any(value is not True for value in properties.values()),
    )


def _is_object_presence_product_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in _OBJECT_PRESENCE_PRODUCT_KEYWORDS:
            return False
        if key in {"allOf", "anyOf", "oneOf"} and not isinstance(value, list):
            return False
        if key == "not" and not isinstance(value, bool | dict):
            return False
        if key == "properties" and not isinstance(value, dict):
            return False
        if key == "additionalProperties" and value is not False:
            return False
        if key == "required" and not _is_string_array(value):
            return False
        if key == "dependentRequired" and not _is_string_array_map(value):
            return False
        if key == "dependencies" and not _is_string_array_map(value):
            return False
        if key == "dependentSchemas" and not _is_presence_product_schema_map(value):
            return False
        if key in {"minProperties", "maxProperties"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
    return True


def _is_presence_product_schema_map(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        isinstance(trigger, str)
        and isinstance(dependent_schema, bool | dict)
        and _object_presence_product_constraint_for_schema(dependent_schema) is not None
        for trigger, dependent_schema in value.items()
    )


def _is_string_array(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_string_array_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and _is_string_array(item)
        for key, item in value.items()
    )


def build_schema_semantics(
    schema: Any,
    graph: ResourceGraph,
    dialect: Dialect,
    evaluation: EvaluationFrontier,
    child_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
    synthetic_term: Callable[[Any, tuple[str, ...]], SchemaTerm] | None = None,
    recursive_static_reference_child: (
        Callable[[SchemaTerm, tuple[str, ...]], bool] | None
    ) = None,
) -> SchemaSemantics:
    finite_values = finite_values_for_schema(schema, graph)
    type_shape = type_shape_for_schema(schema)
    numeric_shape = numeric_shape_for_schema(schema, dialect)
    string_length_shape = string_shape_for_schema(schema)
    string_language_shape = string_language_shape_for_schema(schema)
    array_length_lhs_shape = array_shape_for_schema(
        schema,
        dialect,
        allow_item_value_constraints=True,
    )
    array_length_rhs_shape = array_shape_for_schema(
        schema,
        dialect,
        allow_item_value_constraints=False,
    )
    array_uniqueness_lhs_shape = array_uniqueness_shape_for_schema(
        schema,
        dialect,
        side="lhs",
    )
    array_uniqueness_rhs_shape = array_uniqueness_shape_for_schema(
        schema,
        dialect,
        side="rhs",
    ) or array_unique_items_requirement_for_schema(schema)
    array_cardinality_length_shape = array_cardinality_length_shape_for_schema(
        schema,
        dialect,
    )
    object_property_count_shape = object_property_count_shape_for_schema(schema)
    object_property_count_bounds = object_property_count_bounds_for_schema(schema)
    dependent_required_entries = object_dependent_required_entries_for_schema(
        schema
    )
    dependent_schema_properties = object_dependent_schema_properties_for_schema(
        schema
    )
    dependent_schema_required_entries = (
        object_dependent_schema_required_entries_for_schema(schema)
    )
    object_property_values_shape = object_property_values_shape_for_schema(schema)
    object_closed_properties_shape = closed_object_properties_shape_for_schema(
        schema
    )
    object_property_names_shape = object_property_names_shape_for_schema(schema)
    object_key_value_shape = object_key_value_shape_for_schema(schema)
    object_presence_product_constraint = (
        _object_presence_product_constraint_for_schema(schema)
    )
    array_any_of_item_schemas = array_any_of_item_schemas_for_schema(schema)
    array_any_of_item_terms = _array_any_of_item_terms_for_schema(
        schema, child_term
    )
    array_tuple_anyof_distribution = (
        array_tuple_anyof_distribution_branches_for_schema(schema)
    )
    array_tuple_anyof_distribution_terms = (
        _array_tuple_anyof_distribution_terms_for_branches(
            array_tuple_anyof_distribution,
            synthetic_term,
        )
    )
    (
        array_item_values_lhs_supported,
        array_item_values_rhs_supported,
        array_item_values_rhs_witness_supported,
    ) = array_item_values_fragment_support_for_schema(schema, dialect)
    array_contains_lhs_supported, array_contains_rhs_supported = (
        array_contains_fragment_support_for_schema(schema, dialect)
    )
    array_item_model_constraint = _array_item_model_constraint_for_schema(
        schema, dialect, child_term
    )
    object_key_value_constraint = _object_key_value_constraint_from_shape(
        object_key_value_shape, schema, child_term
    )
    return SchemaSemantics(
        scalar=ScalarSemantics(
            finite_constraint=None
            if finite_values is None
            else FiniteConstraint(tuple(finite_values)),
            type_constraint=None
            if type_shape is None
            else TypeConstraint(
                type_shape.atoms, type_language_complete_for_schema(schema)
            ),
            numeric_constraint=_numeric_constraint_from_shape(numeric_shape),
            string_length_constraint=None
            if string_length_shape is None
            else _string_length_constraint_from_shape(string_length_shape),
            string_language_constraint=None
            if string_language_shape is None
            else _string_language_constraint_from_shape(string_language_shape),
            covered_type_atoms=frozenset(
                atom
                for atom in JSON_TYPE_ATOMS
                if schema_covers_type_atom(schema, atom)
            ),
            has_string_assertions=_schema_has_assertions(
                schema, _STRING_ASSERTION_KEYWORDS
            ),
            has_numeric_assertions=_schema_has_assertions(
                schema, _NUMERIC_ASSERTION_KEYWORDS
            ),
        ),
        array=ArraySemantics(
            array_length_lhs_constraint=_array_length_constraint_for_schema(
                array_length_lhs_shape, type_shape
            ),
            array_length_rhs_constraint=_array_length_constraint_from_shape(
                array_length_rhs_shape
            ),
            array_any_of_item_schemas_constraint=None
            if array_any_of_item_schemas is None
            else ArrayAnyOfItemSchemasConstraint(
                () if array_any_of_item_terms is None else array_any_of_item_terms,
            ),
            array_tuple_anyof_distribution_constraint=None
            if array_tuple_anyof_distribution is None
            else ArrayTupleAnyOfDistributionConstraint(
                ()
                if array_tuple_anyof_distribution_terms is None
                else array_tuple_anyof_distribution_terms,
            ),
            array_contains_constraint=_array_contains_constraint_for_schema(
                schema, evaluation, child_term
            ),
            array_contains_counts=array_contains_counts_for_schema(schema),
            array_cardinality_length_constraint=(
                _array_length_constraint_from_shape(
                    array_cardinality_length_shape
                )
            ),
            array_item_model_constraint=(
                array_item_model_constraint
            ),
            array_contains_fragment_constraint=ArrayContainsFragmentConstraint(
                array_contains_lhs_supported,
                array_contains_rhs_supported,
            ),
            array_item_values_fragment_constraint=ArrayItemValuesFragmentConstraint(
                array_item_values_lhs_supported,
                array_item_values_rhs_supported,
                array_item_values_rhs_witness_supported,
            ),
            array_unevaluated_items_true_fragment_supported=(
                array_unevaluated_items_true_fragment_supported(schema)
            ),
            array_uniqueness_lhs_constraint=(
                _array_uniqueness_constraint_from_shape(array_uniqueness_lhs_shape)
            ),
            array_uniqueness_rhs_constraint=(
                _array_uniqueness_constraint_from_shape(array_uniqueness_rhs_shape)
            ),
            selector_candidates=_array_selector_candidates_from_model(
                array_item_model_constraint
            ),
        ),
        object=ObjectSemantics(
            object_property_count_constraint=(
                _object_property_count_constraint_from_shape(
                    object_property_count_shape
                )
            ),
            object_property_count_bounds_constraint=None
            if object_property_count_bounds is None
            else ObjectPropertyCountBoundsConstraint(*object_property_count_bounds),
            object_dependent_required_constraint=None
            if not dependent_required_entries
            else ObjectDependentRequiredConstraint(
                tuple(
                    ObjectDependentRequiredEntry(trigger, frozenset(dependencies))
                    for trigger, dependencies in dependent_required_entries
                )
            ),
            object_dependent_schema_properties_constraint=None
            if dependent_schema_properties is None
            else ObjectDependentSchemaPropertiesConstraint(
                tuple(
                    ObjectDependentSchemaProperty(
                        trigger,
                        name,
                        SchemaTerm.true()
                        if child_term is None
                        else child_term(
                            property_schema,
                            ("dependentSchemas", trigger, "properties", name),
                        ),
                    )
                    for trigger, name, property_schema in (
                        dependent_schema_properties
                    )
                )
            ),
            object_dependent_schema_required_constraint=None
            if not dependent_schema_required_entries
            else ObjectDependentRequiredConstraint(
                tuple(
                    ObjectDependentRequiredEntry(trigger, frozenset(dependencies))
                    for trigger, dependencies in dependent_schema_required_entries
                )
            ),
            object_property_values_constraint=(
                _object_property_values_constraint_for_schema(
                    object_property_values_shape,
                    schema,
                    type_shape,
                    child_term,
                    recursive_static_reference_child,
                )
            ),
            object_closed_properties_constraint=(
                _object_closed_properties_constraint_from_shape(
                    object_closed_properties_shape, schema, child_term
                )
            ),
            object_property_names_constraint=(
                _object_property_names_constraint_from_shape(
                    object_property_names_shape
                )
            ),
            object_key_value_constraint=object_key_value_constraint,
            object_presence_product_constraint=object_presence_product_constraint,
            object_property_names_has_value_constraints=(
                object_property_names_schema_has_value_constraints(schema)
            ),
            object_unevaluated_properties_true_fragment_supported=(
                object_unevaluated_properties_true_fragment_supported(schema)
            ),
            has_object_or_array_assertions=_schema_has_assertions(
                schema, _OBJECT_ARRAY_ASSERTION_KEYWORDS
            ),
            selector_candidates=_object_selector_candidates_from_key_values(
                object_key_value_constraint
            ),
        ),
        applicator=ApplicatorSemantics(
            tagged_one_of=tagged_one_of(schema, child_term),
            required_singleton_tags=schema_required_singleton_tags(schema),
        ),
        reference=ReferenceSemantics(
            has_static_reference_boundary=contains_reference_keyword(
                schema, {"$ref", "$recursiveRef"}
            ),
            has_non_recursive_static_reference_boundary=contains_reference_keyword(
                schema, {"$ref", "$recursiveRef"}
            ),
            static_reference_paths=_reference_keyword_paths(
                schema, frozenset({"$ref", "$recursiveRef"})
            ),
            has_dynamic_reference=contains_reference_keyword(
                schema, {"$dynamicRef"}
            ),
            has_recursive_reference=contains_reference_keyword(
                schema, {"$recursiveRef"}
            ),
            recursive_references=_recursive_reference_facts_for_schema(schema),
        ),
        evaluation=EvaluationSemantics(evaluation),
        vocabulary=_vocabulary_semantics_for_schema(schema),
    )


def _reference_keyword_paths(
    schema: Any,
    keywords: frozenset[str],
    path: tuple[str, ...] = (),
) -> tuple[tuple[str, ...], ...]:
    if isinstance(schema, list):
        return tuple(
            keyword_path
            for index, item in enumerate(schema)
            for keyword_path in _reference_keyword_paths(
                item, keywords, path + (str(index),)
            )
        )
    if not isinstance(schema, dict):
        return ()
    paths = tuple(
        path + (keyword,)
        for keyword in sorted(keywords)
        if keyword in schema and isinstance(schema.get(keyword), str)
    )
    return paths + tuple(
        keyword_path
        for key, value in schema.items()
        if key not in keywords
        for keyword_path in _reference_keyword_paths(
            value, keywords, path + (str(key),)
        )
    )


def _recursive_reference_facts_for_schema(
    schema: Any,
    path: tuple[str, ...] = (),
    polarity: str = "positive",
) -> tuple[RecursiveReferenceFact, ...]:
    if isinstance(schema, list):
        return tuple(
            fact
            for index, item in enumerate(schema)
            for fact in _recursive_reference_facts_for_schema(
                item, path + (str(index),), polarity
            )
        )
    if not isinstance(schema, dict):
        return ()

    facts: list[RecursiveReferenceFact] = []
    recursive_ref = schema.get("$recursiveRef")
    if isinstance(recursive_ref, str):
        ref_path = path + ("$recursiveRef",)
        facts.append(
            RecursiveReferenceFact(
                keyword="$recursiveRef",
                path=ref_path,
                ref=recursive_ref,
                guard_kind=_ir_recursive_guard_kind(
                    recursive_guard_kind_for_path(ref_path)
                ),
                polarity=_ir_recursive_reference_polarity(polarity),
            )
        )

    for key, value in schema.items():
        if key == "$recursiveRef":
            continue
        facts.extend(
            _recursive_reference_facts_for_schema(
                value,
                path + (str(key),),
                _child_recursive_reference_polarity(key, polarity),
            )
        )
    return tuple(facts)


def _ir_recursive_guard_kind(value: str | None) -> RecursiveReferenceGuard:
    if value == "array":
        return "array"
    if value == "object":
        return "object"
    if value == "object/array":
        return "object/array"
    return "unguarded"


def _child_recursive_reference_polarity(key: str, polarity: str) -> str:
    if key == "not":
        return "negative" if polarity == "positive" else "positive"
    return polarity


def _ir_recursive_reference_polarity(polarity: str) -> RecursiveReferencePolarity:
    return "negative" if polarity == "negative" else "positive"


def _schema_has_assertions(schema: Any, keywords: frozenset[str]) -> bool:
    if isinstance(schema, list):
        return any(_schema_has_assertions(item, keywords) for item in schema)
    if not isinstance(schema, dict):
        return False
    if any(key in keywords for key in schema):
        return True
    return any(
        _schema_has_assertions(value, keywords)
        for key, value in schema.items()
        if key in _APPLICATOR_ASSERTION_SCAN_KEYS
    )


def _present_schema_keywords(schema: Any) -> frozenset[str]:
    if not isinstance(schema, dict):
        return frozenset()
    return frozenset(str(keyword) for keyword in schema)


def _vocabulary_semantics_for_schema(schema: Any) -> VocabularySemantics:
    present = _present_schema_keywords(schema)
    semantic = present - IGNORED_SCHEMA_METADATA_KEYS
    if "if" not in present or not (present & {"else", "then"}):
        semantic -= {"else", "if", "then"}
    return VocabularySemantics(
        present_keywords=present,
        semantic_keywords=semantic,
        scalar_keywords=present & _SCALAR_SEMANTIC_KEYWORDS,
        array_keywords=present & _ARRAY_SEMANTIC_KEYWORDS,
        object_keywords=present & _OBJECT_SEMANTIC_KEYWORDS,
        applicator_keywords=present & _APPLICATOR_SEMANTIC_KEYWORDS,
        reference_keywords=present & _REFERENCE_SEMANTIC_KEYWORDS,
        evaluation_keywords=present & _EVALUATION_SEMANTIC_KEYWORDS,
        annotation_keywords=present & _ANNOTATION_SEMANTIC_KEYWORDS,
        vocabulary_keywords=present & _VOCABULARY_SEMANTIC_KEYWORDS,
    )


def _nested_unsupported(
    schema: dict[str, Any], dialect: Dialect, path: tuple[str, ...]
) -> tuple[UnsupportedNode, ...]:
    nodes: list[UnsupportedNode] = []
    for keyword, value in schema.items():
        if keyword in {"allOf", "anyOf", "oneOf", "not", "if", "then", "else"}:
            continue
        if keyword in SCHEMA_VALUE_KEYWORDS:
            nodes.extend(
                compile_schema_unsupported_nodes(
                    value,
                    _inline_evaluation(value, dialect),
                    dialect,
                    path + (keyword,),
                )
            )
            continue
        if keyword in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
            for index, item in enumerate(value):
                nodes.extend(
                    compile_schema_unsupported_nodes(
                        item,
                        _inline_evaluation(item, dialect),
                        dialect,
                        path + (keyword, str(index)),
                    )
                )
            continue
        if keyword in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            for property_name, subschema in value.items():
                nodes.extend(
                    compile_schema_unsupported_nodes(
                        subschema,
                        _inline_evaluation(subschema, dialect),
                        dialect,
                        path + (keyword, str(property_name)),
                    )
                )
    return tuple(nodes)


def _inline_evaluation(schema: Any, dialect: Dialect) -> EvaluationFrontier:
    return evaluation_frontier_for_schema(schema, dialect)


def _unsupported_node(
    keyword: str, evaluation: EvaluationFrontier, path: tuple[str, ...]
) -> UnsupportedNode:
    category, reason = _unsupported_category_and_reason(keyword, evaluation, path)
    return UnsupportedNode(keyword, reason, path, category)


def _unsupported_category_and_reason(
    keyword: str,
    evaluation: EvaluationFrontier,
    path: tuple[str, ...],
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
        if recursive_reference_polarity_for_path(path) == "negative":
            return (
                "recursive-reference",
                (
                    "negative-polarity $recursiveRef requires guarded recursive "
                    "reference proof support"
                ),
            )
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
