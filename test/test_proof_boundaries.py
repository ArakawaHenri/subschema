from math import inf, nan
import pytest

from subschema.dialects import Dialect
from subschema.kernel import ProofBudgets, ProofContext, ProofEngine, ProofOptions
from subschema.kernel.domains.arrays import (
    ArrayContainsDomainTactic,
    ArrayLengthDomainTactic,
    ArrayUniquenessDomainTactic,
)
from subschema.kernel.domains.numbers import NumericDomainTactic
from subschema.kernel.domains.objects import (
    ObjectClosedPropertiesDomainTactic,
    ObjectPresenceDomainTactic,
    ObjectPropertyCountDomainTactic,
    ObjectPropertyNamesDomainTactic,
    ObjectPropertyValuesDomainTactic,
    ObjectStructureDomainTactic,
)
from subschema.kernel.domains.strings import (
    StringLanguageDomainTactic,
    StringLengthDomainTactic,
)
from subschema.kernel.domains.types import TypeDomainTactic
from subschema.kernel.finite import FiniteDomainTactic, finite_values_for_schema
from subschema.kernel.references import ResourceGraph
from subschema.kernel.semantic import ConcreteEvaluator
from subschema.kernel.formulas import (
    AndFormula,
    AssertionFormula,
    DifferenceFormula,
    ExactlyOneFormula,
    GuardedFormula,
    NotFormula,
    ReferenceFormula,
    TopFormula,
)
from subschema.kernel.sat import EmptinessSolver, difference_rule_specs
from subschema.kernel.schemas import schema_is_false, schema_is_true, schemas_equal
from subschema.kernel.values import dedupe, json_values_equal
from test.proof_oracle import (
    ConcreteEvaluatorCase,
    SMALL_JSON_UNIVERSE,
    assert_concrete_evaluator_case,
    assert_concrete_evaluator_unsupported,
    assert_no_small_counterexample,
    assert_proved_subschema,
    assert_proved,
    assert_witness_validates,
    validator as oracle_validator,
)


CONCRETE_EVALUATOR_REPRESENTATIVE_CASES = (
    ConcreteEvaluatorCase(
        "static-ref-resource",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"name": {"type": "string"}},
            "$ref": "#/$defs/name",
        },
        ("ok", 1),
    ),
    ConcreteEvaluatorCase(
        "static-ref-embedded-dialect-transition",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "draft_target": {
                    "$schema": "http://json-schema.org/draft-04/schema#",
                    "const": 1,
                },
            },
            "$ref": "#/$defs/draft_target",
        },
        (1, 2),
    ),
    ConcreteEvaluatorCase(
        "dynamic-ref-acyclic",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"node": {"$dynamicAnchor": "node", "type": "string"}},
            "$dynamicRef": "#node",
        },
        ("ok", 1),
    ),
    ConcreteEvaluatorCase(
        "scalar-constraints",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "anyOf": [
                {"type": "number", "minimum": 1, "exclusiveMaximum": 5, "multipleOf": 0.5},
                {"type": "string", "minLength": 2, "maxLength": 4, "pattern": "^a"},
            ],
        },
        (1, 1.5, 5, 1.25, "a", "ab", "abcd", "abcde", "ba"),
    ),
    ConcreteEvaluatorCase(
        "decimal-multipleOf-exact",
        {"type": "number", "multipleOf": 0.1},
        (0.2, 0.3, 0.30000000000000004, 0.31),
    ),
    ConcreteEvaluatorCase(
        "integer-valued-floats-follow-json-schema-integer-semantics",
        {"type": "integer"},
        (1, 1.0, 1.5, True),
    ),
    ConcreteEvaluatorCase(
        "unique-items-uses-json-number-equality",
        {"type": "array", "uniqueItems": True},
        ([1, 2], [1, 1.0], [1.0, 2.0], [{"x": 1}, {"x": 1.0}]),
    ),
    ConcreteEvaluatorCase(
        "const-and-enum-use-json-semantic-equality",
        {"anyOf": [{"const": 1}, {"enum": [True]}]},
        (1, 1.0, True, False),
    ),
    ConcreteEvaluatorCase(
        "draft4-modern-keywords-are-inactive",
        {
            "const": 1,
            "propertyNames": {"pattern": "^a"},
        },
        (2, {"b": 1}),
        dialect=Dialect.DRAFT4,
    ),
    ConcreteEvaluatorCase(
        "draft6-conditionals-are-inactive",
        {"if": {"type": "integer"}, "then": {"minimum": 5}},
        (1, 5, "x"),
        dialect=Dialect.DRAFT6,
    ),
    ConcreteEvaluatorCase(
        "draft7-conditionals-are-active",
        {"if": {"type": "integer"}, "then": {"minimum": 5}},
        (1, 5, "x"),
        dialect=Dialect.DRAFT7,
    ),
    ConcreteEvaluatorCase(
        "draft7-minContains-is-annotation",
        {"type": "array", "contains": {"type": "integer"}, "minContains": 2, "maxContains": 2},
        ([1], [1, 2], [1, 2, 3], ["x"]),
        dialect=Dialect.DRAFT7,
    ),
    ConcreteEvaluatorCase(
        "draft2019-minContains-is-assertion",
        {"type": "array", "contains": {"type": "integer"}, "minContains": 2, "maxContains": 2},
        ([1], [1, 2], [1, 2, 3], ["x"]),
        dialect=Dialect.DRAFT201909,
    ),
    ConcreteEvaluatorCase(
        "array-prefix-items",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": {"type": "string"},
            "minItems": 1,
            "uniqueItems": True,
        },
        ([1], [1, "x"], [1, 2], [], [1, "x", "x"]),
    ),
    ConcreteEvaluatorCase(
        "object-dependencies",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "minProperties": 1,
            "maxProperties": 3,
            "propertyNames": {"pattern": "^[a-z_]+$"},
            "properties": {
                "billing_address": {"type": "string"},
                "credit_card": {"type": "number"},
                "zip": {"type": "string"},
            },
            "dependentRequired": {"credit_card": ["billing_address"]},
            "dependentSchemas": {"billing_address": {"properties": {"zip": {"type": "string"}}}},
            "additionalProperties": False,
        },
        (
            {"credit_card": 1, "billing_address": "x"},
            {"credit_card": 1},
            {"Billing": "x"},
            {},
            {"credit_card": 1, "billing_address": "x", "zip": "1", "extra": "x"},
            {"billing_address": "x", "zip": 1},
        ),
    ),
    ConcreteEvaluatorCase(
        "contains-unevaluated-items",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "contains": {"type": "integer"},
            "unevaluatedItems": False,
        },
        ([1], ["x"], [1, "x"], [1, 2]),
    ),
    ConcreteEvaluatorCase(
        "additional-properties-unevaluated-properties",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "properties": {"known": {"type": "string"}},
            "additionalProperties": {"type": "number"},
            "unevaluatedProperties": False,
        },
        (
            {"known": "x"},
            {"known": "x", "extra": 1},
            {"known": "x", "extra": "bad"},
            {"known": 1},
            {"other": 1},
        ),
    ),
)


CONCRETE_EVALUATOR_UNSUPPORTED_CASES = (
    (
        "external-static-ref",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/external",
        },
        "value",
        "could not resolve $ref",
    ),
    (
        "recursive-dynamic-ref",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$dynamicAnchor": "node",
            "allOf": [{"$dynamicRef": "#node"}],
        },
        "value",
        "recursive schema",
    ),
)


MODERN_UNSUPPORTED_LEGACY_DISABLED_CASES = (
    (
        "unknown-required-vocabulary",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$vocabulary": {"https://example.com/custom-assertion-vocabulary": True},
        },
        {},
        "unsupported",
        "required vocabulary",
        "unknown-vocabulary",
    ),
    (
        "format-assertion-vocabulary",
        {},
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$vocabulary": {
                "https://json-schema.org/draft/2020-12/vocab/format-assertion": True,
            },
        },
        "unsupported",
        "format-assertion vocabulary",
        "format-assertion",
    ),
    (
        "recursive-static-ref",
        {},
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"node": {"$ref": "#/$defs/node"}},
            "$ref": "#/$defs/node",
        },
        "unsupported",
        "recursive rhs $ref",
        "recursive-reference",
    ),
    (
        "unresolved-static-ref",
        {},
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.com/external",
        },
        "unsupported",
        "could not resolve rhs $ref",
        "static-reference",
    ),
    (
        "recursive-dynamic-ref",
        {},
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$dynamicAnchor": "node",
            "allOf": [{"$dynamicRef": "#node"}],
        },
        "unsupported",
        "could not resolve rhs $dynamicRef",
        "dynamic-reference",
    ),
    (
        "ambiguous-anyof-evaluation-effect",
        {"type": "object"},
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "anyOf": [
                {"required": ["foo"], "properties": {"foo": {"type": "string"}}},
                {"required": ["bar"], "properties": {"bar": {"type": "number"}}},
            ],
            "unevaluatedProperties": False,
        },
        "unsupported",
        "branch-aware anyOf effects",
        "",
    ),
    (
        "open-schema-valued-unevaluated-properties",
        {"type": "object"},
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "unevaluatedProperties": {"type": "number"},
        },
        "unsupported",
        "finite closed left keyspace",
        "",
    ),
)


EXACT_RULE_ORACLE_CASES = (
    ("trivial-difference", {"type": "string"}, {"type": "string"}, Dialect.DRAFT7),
    ("finite-domain-ir", {"enum": [1, 2]}, {"type": "number"}, Dialect.DRAFT7),
    (
        "finite-complement-ir",
        {"not": {"oneOf": [{"enum": [1, 2, 3]}, {"enum": [1, 2]}]}},
        {"not": {"enum": [3]}},
        Dialect.DRAFT7,
    ),
    (
        "static-reference-ir",
        {"definitions": {"name": {"type": "string"}}, "$ref": "#/definitions/name"},
        {"type": "string"},
        Dialect.DRAFT7,
    ),
    (
        "dynamic-reference-ir",
        {"type": "string"},
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"node": {"$dynamicAnchor": "node", "type": "string"}},
            "$dynamicRef": "#node",
        },
        Dialect.DRAFT202012,
    ),
    (
        "applicator-left-anyof-ir",
        {"anyOf": [{"type": "integer"}, {"type": "number", "minimum": 0}]},
        {"type": "number"},
        Dialect.DRAFT7,
    ),
    (
        "applicator-left-oneof-ir",
        {"oneOf": [{"type": "integer"}, {"const": "a"}]},
        {"type": ["number", "string"]},
        Dialect.DRAFT7,
    ),
    (
        "applicator-left-allof-ir",
        {"allOf": [{"type": "integer"}, {"minimum": 0}]},
        {"type": "number"},
        Dialect.DRAFT7,
    ),
    (
        "applicator-right-oneof-ir",
        {"type": "integer"},
        {"oneOf": [{"type": "number"}, {"type": "string"}]},
        Dialect.DRAFT7,
    ),
    (
        "applicator-right-allof-ir",
        {"type": "integer"},
        {"allOf": [{"type": "number"}, {}]},
        Dialect.DRAFT7,
    ),
    (
        "applicator-conditional-ir",
        {"type": "string", "minLength": 1},
        {"if": {"type": "string"}, "then": {"minLength": 1}, "else": True},
        Dialect.DRAFT7,
    ),
    (
        "numeric-domain-ir",
        {"type": "number", "minimum": 2, "maximum": 4},
        {"type": "number", "minimum": 1},
        Dialect.DRAFT7,
    ),
    (
        "type-domain-ir",
        {"type": "string"},
        {"type": ["string", "number"]},
        Dialect.DRAFT7,
    ),
    (
        "string-length-domain-ir",
        {"type": "string", "minLength": 2, "maxLength": 3},
        {"type": "string", "minLength": 1},
        Dialect.DRAFT7,
    ),
    (
        "string-language-domain-ir",
        {"type": "string", "pattern": "^ab", "maxLength": 4},
        {"type": "string", "pattern": "^a", "minLength": 2},
        Dialect.DRAFT7,
    ),
    (
        "typed-scalar-domain-ir",
        {"type": ["integer", "boolean"], "minimum": 10, "maximum": 20},
        {"anyOf": [{"type": "integer"}, {"type": "boolean"}], "allOf": [{"minimum": 10}, {"maximum": 20}]},
        Dialect.DRAFT7,
    ),
    (
        "array-length-ir",
        {"type": "array", "items": [{}, {}], "additionalItems": False},
        {"type": "array", "maxItems": 2},
        Dialect.DRAFT7,
    ),
    (
        "object-property-count-ir",
        {"type": "object", "required": ["a", "b"]},
        {"type": "object", "minProperties": 2},
        Dialect.DRAFT7,
    ),
)


EXTENDED_TRUE_ORACLE_CASES = (
    (
        "boolean-schema",
        False,
        {"type": "string"},
        Dialect.DRAFT7,
    ),
    (
        "integer-multipleOf",
        {"type": "integer", "multipleOf": 6},
        {"type": "integer", "multipleOf": 3},
        Dialect.DRAFT7,
    ),
    (
        "array-local-uniqueItems",
        {"type": "array", "maxItems": 1},
        {"type": "array", "uniqueItems": True},
        Dialect.DRAFT7,
    ),
    (
        "array-local-contains",
        {"type": "array", "minItems": 2, "items": {"type": "integer"}},
        {"type": "array", "contains": {"type": "integer"}, "minContains": 2},
        Dialect.DRAFT201909,
    ),
    (
        "array-item-value-subproof",
        {"type": "array", "items": {"type": "integer"}, "maxItems": 2},
        {"type": "array", "items": {"type": "number"}},
        Dialect.DRAFT7,
    ),
    (
        "object-dependentRequired-presence",
        {
            "type": "object",
            "required": ["credit_card"],
            "dependentRequired": {"credit_card": ["billing_address"]},
        },
        {"type": "object", "minProperties": 2},
        Dialect.DRAFT201909,
    ),
    (
        "object-closed-property-values",
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "required": ["a"],
            "additionalProperties": False,
        },
        {"type": "object", "properties": {"a": {"type": "number"}}},
        Dialect.DRAFT7,
    ),
    (
        "object-propertyNames-language",
        {"type": "object", "propertyNames": {"pattern": "^alpha"}},
        {"type": "object", "propertyNames": {"pattern": "^a"}},
        Dialect.DRAFT7,
    ),
)


GROUPED_FALSE_WITNESS_CASES = (
    (
        "symbolic-object-witness",
        {"type": "object", "additionalProperties": {"type": "number"}, "minProperties": 1},
        {"type": "object", "additionalProperties": {"not": {"type": "number"}}},
        Dialect.DRAFT7,
        ProofOptions(endeavor=True),
    ),
    (
        "array-uniqueItems",
        {"type": "array", "minItems": 2},
        {"type": "array", "uniqueItems": True},
        Dialect.DRAFT7,
        ProofOptions(),
    ),
    (
        "array-contains",
        {"type": "array", "minItems": 1, "items": {"type": "number"}},
        {"type": "array", "contains": {"type": "integer"}},
        Dialect.DRAFT6,
        ProofOptions(),
    ),
    (
        "array-item-values",
        {"type": "array", "items": [{"type": "string"}]},
        {"type": "array", "items": {"type": "string"}},
        Dialect.DRAFT7,
        ProofOptions(),
    ),
    (
        "object-key-value",
        {"type": "object", "patternProperties": {"^a": {"type": "number"}}},
        {"type": "object", "patternProperties": {"^a": {"type": "integer"}}},
        Dialect.DRAFT7,
        ProofOptions(),
    ),
    (
        "applicator-oneOf-overlap",
        {"const": 1},
        {"oneOf": [{"type": "number"}, {"enum": [1, 2]}]},
        Dialect.DRAFT7,
        ProofOptions(),
    ),
)


def test_small_json_universe_is_generated_and_nested():
    assert None in SMALL_JSON_UNIVERSE
    assert [] in SMALL_JSON_UNIVERSE
    assert [[]] in SMALL_JSON_UNIVERSE
    assert {"a": []} in SMALL_JSON_UNIVERSE
    assert len(SMALL_JSON_UNIVERSE) == len(dedupe(SMALL_JSON_UNIVERSE))


def test_difference_rule_specs_have_proof_class_metadata():
    proof_classes = {spec.proof_class for spec in difference_rule_specs()}

    assert proof_classes
    assert proof_classes <= {
        "simple_exact",
        "endeavor_expensive",
        "unsupported_unreliable",
    }


def test_exact_difference_rule_specs_have_step_d_oracle_coverage():
    exact_rule_names = {
        spec.name
        for spec in difference_rule_specs()
        if spec.completeness == "exact"
    }
    covered_rule_names = {case[0] for case in EXACT_RULE_ORACLE_CASES}

    assert exact_rule_names <= covered_rule_names
    assert covered_rule_names <= {spec.name for spec in difference_rule_specs()}


@pytest.mark.parametrize(
    "case",
    CONCRETE_EVALUATOR_REPRESENTATIVE_CASES,
    ids=lambda case: case.name,
)
def test_concrete_evaluator_oracle_representative_cases_match_jsonschema(case):
    assert_concrete_evaluator_case(case)


@pytest.mark.parametrize(
    ("name", "schema", "instance", "reason_contains"),
    CONCRETE_EVALUATOR_UNSUPPORTED_CASES,
)
def test_concrete_evaluator_oracle_unsupported_cases_stay_diagnostic(
    name,
    schema,
    instance,
    reason_contains,
):
    assert name
    assert_concrete_evaluator_unsupported(schema, instance, reason_contains=reason_contains)


@pytest.mark.parametrize(
    "schema",
    (
        {"const": nan},
        {"enum": [inf]},
        {"properties": {"x": {"const": -inf}}},
    ),
)
def test_concrete_evaluator_rejects_non_json_schemas(schema):
    with pytest.raises(ValueError):
        ConcreteEvaluator.for_schema(schema)


@pytest.mark.parametrize("instance", (nan, inf, -inf, [1, nan]))
def test_concrete_evaluator_rejects_non_json_instances(instance):
    evaluator = ConcreteEvaluator.for_schema(True)

    with pytest.raises(ValueError):
        evaluator.validate(instance)


@pytest.mark.parametrize(("rule_name", "lhs", "rhs", "dialect"), EXACT_RULE_ORACLE_CASES)
def test_exact_difference_rule_oracle_matrix(rule_name, lhs, rhs, dialect, monkeypatch):
    assert rule_name
    assert_proved(lhs, rhs, dialect, monkeypatch)
    assert_no_small_counterexample(lhs, rhs, dialect)


@pytest.mark.parametrize(("fragment", "lhs", "rhs", "dialect"), EXTENDED_TRUE_ORACLE_CASES)
def test_extended_default_fragment_oracle_matrix(fragment, lhs, rhs, dialect, monkeypatch):
    assert fragment
    assert_proved(lhs, rhs, dialect, monkeypatch)
    assert_no_small_counterexample(lhs, rhs, dialect)


@pytest.mark.parametrize(
    ("name", "lhs", "rhs", "expected_status", "reason_contains", "diagnostic_category"),
    MODERN_UNSUPPORTED_LEGACY_DISABLED_CASES,
)
def test_keyword_modern_unsupported_cases_return_solver_boundary(
    name,
    lhs,
    rhs,
    expected_status,
    reason_contains,
    diagnostic_category,
):
    assert name

    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(),
    )

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == expected_status
    assert proof.status != "proved_true"
    assert reason_contains in proof.reason
    if diagnostic_category:
        assert diagnostic_category in {diagnostic.category for diagnostic in proof.diagnostics}


def test_proof_contract_types_live_in_kernel_package():
    assert ProofEngine.__module__ == "subschema.kernel.engine"
    assert ProofContext.__module__ == "subschema.kernel.context"
    assert ArrayLengthDomainTactic.__module__ == "subschema.kernel.domains.arrays"
    assert ArrayUniquenessDomainTactic.__module__ == "subschema.kernel.domains.arrays"
    assert ArrayContainsDomainTactic.__module__ == "subschema.kernel.domains.arrays"
    assert FiniteDomainTactic.__module__ == "subschema.kernel.finite"
    assert NumericDomainTactic.__module__ == "subschema.kernel.domains.numbers"
    assert ObjectPropertyCountDomainTactic.__module__ == "subschema.kernel.domains.objects"
    assert ObjectPresenceDomainTactic.__module__ == "subschema.kernel.domains.objects"
    assert ObjectStructureDomainTactic.__module__ == "subschema.kernel.domains.objects"
    assert ObjectClosedPropertiesDomainTactic.__module__ == "subschema.kernel.domains.objects"
    assert ObjectPropertyNamesDomainTactic.__module__ == "subschema.kernel.domains.objects"
    assert ObjectPropertyValuesDomainTactic.__module__ == "subschema.kernel.domains.objects"
    assert TypeDomainTactic.__module__ == "subschema.kernel.domains.types"
    assert StringLengthDomainTactic.__module__ == "subschema.kernel.domains.strings"
    assert StringLanguageDomainTactic.__module__ == "subschema.kernel.domains.strings"


def test_kernel_value_and_validation_helpers_live_in_kernel_modules():
    assert dedupe([1, 1.0, True, 2]) == [1, True, 2]
    assert json_values_equal({"x": [1]}, {"x": [1.0]})
    assert not json_values_equal(True, 1)
    assert oracle_validator({"type": "integer"}, Dialect.DRAFT7).is_valid(1)


def test_schema_predicates_and_finite_values_live_in_kernel_package():
    draft4_graph = ResourceGraph.build(True, dialect=Dialect.DRAFT4)
    draft7_graph = ResourceGraph.build(True, dialect=Dialect.DRAFT7)
    assert schema_is_true(True)
    assert schema_is_true({})
    assert schema_is_false(False)
    assert schemas_equal({"enum": [1, 2]}, {"enum": [1, 2]})
    assert finite_values_for_schema({"const": 1}) == [1]
    assert finite_values_for_schema({"const": 1}, draft4_graph) is None
    assert finite_values_for_schema({"anyOf": [{"const": 1}, {"const": 2}]}, draft7_graph) == [1, 2]
    assert finite_values_for_schema({"enum": [1, 1.0, True]}) == [1, True]
    assert finite_values_for_schema({"not": {"not": {"const": "a"}}}, draft7_graph) == ["a"]
    assert finite_values_for_schema({"not": True}) == []
    assert finite_values_for_schema({"not": {}}) == []
    assert finite_values_for_schema({"allOf": [{"enum": []}, True]}) == []
    assert finite_values_for_schema(
        {"allOf": [{"enum": [1, 2]}, {"const": 1}]},
        draft7_graph,
    ) == [1]
    assert finite_values_for_schema(
        {"allOf": [{"const": 1}, {"const": 2}]},
        draft7_graph,
    ) == []
    assert finite_values_for_schema(
        {"oneOf": [{"enum": [1, 2]}, {"enum": [2, 3]}]},
        draft7_graph,
    ) == [1, 3]
    assert finite_values_for_schema({"type": "string", "pattern": "[0-9a-f]{64}"}) is None
    assert finite_values_for_schema({"type": "string", "pattern": "^[ab]$"}) == ["a", "b"]
    assert (
        finite_values_for_schema(
            {
                "type": "array",
                "prefixItems": [{"const": index} for index in range(2)],
                "items": False,
                "minItems": 2,
            },
            ResourceGraph.build(True, dialect=Dialect.DRAFT202012),
        )
        == [[0, 1]]
    )
    assert finite_values_for_schema(
        {
            "type": "array",
            "prefixItems": [{"const": index} for index in range(65)],
            "items": False,
            "minItems": 65,
        },
        ResourceGraph.build(True, dialect=Dialect.DRAFT202012),
    ) is None


def test_double_negated_finite_schema_is_proved_by_default():
    lhs = {"not": {"not": {"const": "a"}}}
    rhs = {"anyOf": [{"type": "string"}, {"type": "number"}]}

    proof = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012).is_subschema(lhs, rhs)

    assert proof.status == "proved_true"


def test_json_number_semantic_equality_is_used_by_finite_proof():
    equal_number_lhs = {"enum": [1]}
    equal_number_rhs = {"enum": [1.0]}
    unique_items_rhs = {"type": "array", "uniqueItems": True}
    duplicate_number_lhs = {"enum": [[1, 1.0]]}

    forward = ProofEngine.for_schemas(equal_number_lhs, equal_number_rhs, dialect=Dialect.DRAFT7).is_subschema(
        equal_number_lhs,
        equal_number_rhs,
    )
    reverse = ProofEngine.for_schemas(equal_number_rhs, equal_number_lhs, dialect=Dialect.DRAFT7).is_subschema(
        equal_number_rhs,
        equal_number_lhs,
    )
    duplicate = ProofEngine.for_schemas(duplicate_number_lhs, unique_items_rhs, dialect=Dialect.DRAFT7).is_subschema(
        duplicate_number_lhs,
        unique_items_rhs,
    )

    assert forward.status == "proved_true"
    assert reverse.status == "proved_true"
    assert duplicate.status == "proved_false"


def test_uninhabited_required_array_slot_is_finite_empty():
    lhs = {"type": "array", "minItems": 1, "items": {"enum": []}}
    rhs = {"type": "integer", "minimum": 1}

    assert finite_values_for_schema(lhs) == []
    proof = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012).is_subschema(lhs, rhs)

    assert proof.status == "proved_true"


def test_202012_closed_tail_required_array_slot_is_finite_empty():
    lhs = {"type": "array", "prefixItems": [{"type": "string"}], "items": False, "minItems": 2}

    assert finite_values_for_schema(lhs) == []


def test_finite_rhs_uses_constructive_lhs_object_witness():
    lhs = {"type": "object", "required": ["b"], "propertyNames": {"pattern": "^b"}}
    rhs = {"enum": [[], 0, [0], {"a": {"b": 1}}]}

    proof = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012).is_subschema(lhs, rhs)

    assert proof.status == "proved_false"
    assert proof.witness == {"b": None}


@pytest.mark.parametrize(
    "lhs",
    [
        {"type": "object", "required": ["a"], "properties": {"a": False}},
        {"type": "object", "required": ["a"], "properties": {"a": {"not": True}}},
        {"type": "object", "required": ["a"], "patternProperties": {"^a": False}},
        {"type": "object", "required": ["a"], "additionalProperties": False},
        {"type": "object", "required": ["a"], "propertyNames": {"pattern": "^b"}},
    ],
)
def test_uninhabited_required_object_property_is_finite_empty(lhs):
    rhs = {"type": "string"}

    assert finite_values_for_schema(lhs) == []
    proof = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012).is_subschema(lhs, rhs)

    assert proof.status == "proved_true"


@pytest.mark.parametrize(
    "property_names",
    [
        False,
        {"enum": []},
        {"const": 1},
        {"type": "integer"},
        {"not": {"type": "string"}},
    ],
)
def test_empty_property_name_keyspace_with_min_properties_is_finite_empty(property_names):
    lhs = {"type": "object", "propertyNames": property_names, "minProperties": 1}
    rhs = {"type": "string"}

    assert finite_values_for_schema(lhs) == []
    proof = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012).is_subschema(lhs, rhs)

    assert proof.status == "proved_true"


@pytest.mark.parametrize(
    ("lhs", "rhs", "dialect"),
    [
        ({"type": "integer"}, {"type": "number"}, Dialect.DRAFT7),
        (
            {"type": "integer", "minimum": 2, "maximum": 4},
            {"type": "number", "minimum": 1},
            Dialect.DRAFT7,
        ),
        (
            {"type": "string", "minLength": 2, "maxLength": 3},
            {"type": "string", "minLength": 1},
            Dialect.DRAFT7,
        ),
        (
            {"type": "array", "items": [{}, {}], "additionalItems": False},
            {"type": "array", "maxItems": 2},
            Dialect.DRAFT7,
        ),
        (
            {"type": "array", "maxItems": 1},
            {"type": "array", "uniqueItems": True},
            Dialect.DRAFT7,
        ),
        (
            {"type": "array", "minItems": 2, "items": {"type": "integer"}},
            {"type": "array", "contains": {"type": "integer"}, "minContains": 2},
            Dialect.DRAFT201909,
        ),
        (
            {"type": "object", "required": ["a", "b"]},
            {"type": "object", "minProperties": 2},
            Dialect.DRAFT7,
        ),
        ({"const": 1}, {"enum": [0, 1, 2]}, Dialect.DRAFT7),
        (
            {"type": "string", "pattern": "^ab", "maxLength": 4},
            {"type": "string", "pattern": "^a", "minLength": 2},
            Dialect.DRAFT7,
        ),
        (
            {"type": "object", "propertyNames": {"pattern": "^alpha"}},
            {"type": "object", "propertyNames": {"pattern": "^a"}},
            Dialect.DRAFT7,
        ),
        (
            {
                "type": "object",
                "properties": {"a": {"type": "integer"}},
                "required": ["a"],
                "additionalProperties": False,
            },
            {"type": "object", "properties": {"a": {"type": "number"}}},
            Dialect.DRAFT7,
        ),
        (
            {"anyOf": [{"type": "integer"}, {"const": 1}]},
            {"type": "number"},
            Dialect.DRAFT7,
        ),
        (
            {"oneOf": [{"type": "integer"}, {"const": "a"}]},
            {"type": ["number", "string"]},
            Dialect.DRAFT7,
        ),
        (
            {"allOf": [{"type": "integer"}, {"minimum": 0}]},
            {"type": "number"},
            Dialect.DRAFT7,
        ),
        (
            {"type": "integer"},
            {"allOf": [{"type": "number"}, {}]},
            Dialect.DRAFT7,
        ),
        (
            {"type": "integer"},
            {"oneOf": [{"type": "number"}, {"type": "string"}]},
            Dialect.DRAFT7,
        ),
        (
            {"type": "string", "minLength": 1},
            {"if": {"type": "string"}, "then": {"minLength": 1}, "else": True},
            Dialect.DRAFT7,
        ),
        (
            {"if": {"type": "string"}, "then": {"minLength": 1}, "else": False},
            {"type": "string"},
            Dialect.DRAFT7,
        ),
    ],
)
def test_finite_model_oracle_for_representative_exact_fragments(lhs, rhs, dialect):
    proof = ProofEngine.for_schemas(lhs, rhs, dialect=dialect).is_subschema(
        lhs,
        rhs,
    )

    assert proof.status == "proved_true"
    assert_no_small_counterexample(lhs, rhs, dialect)


@pytest.mark.parametrize(
    ("lhs", "rhs", "dialect"),
    [
        (
            {"anyOf": [{"type": "integer"}, {"const": 1}]},
            {"type": "number"},
            Dialect.DRAFT7,
        ),
        (
            {"oneOf": [{"type": "integer"}, {"const": "a"}]},
            {"type": ["number", "string"]},
            Dialect.DRAFT7,
        ),
        (
            {"allOf": [{"type": "integer"}, {"minimum": 0}]},
            {"type": "number"},
            Dialect.DRAFT7,
        ),
        (
            {"type": "integer"},
            {"anyOf": [{"type": "number"}, {"type": "string"}]},
            Dialect.DRAFT7,
        ),
        (
            {"type": "integer"},
            {"oneOf": [{"type": "number"}, {"type": "string"}]},
            Dialect.DRAFT7,
        ),
        (
            {"type": "integer"},
            {"allOf": [{"type": "number"}, {}]},
            Dialect.DRAFT7,
        ),
        (
            {"type": "string", "pattern": "^b"},
            {"not": {"pattern": "^a"}},
            Dialect.DRAFT7,
        ),
        (
            {"type": "string", "minLength": 1},
            {"if": {"type": "string"}, "then": {"minLength": 1}, "else": True},
            Dialect.DRAFT7,
        ),
        (
            {"if": {"type": "string"}, "then": {"minLength": 1}, "else": False},
            {"type": "string"},
            Dialect.DRAFT7,
        ),
    ],
)
def test_applicator_exact_fragments_have_finite_model_oracle_without_candidates(lhs, rhs, dialect, monkeypatch):
    assert_proved(lhs, rhs, dialect, monkeypatch)
    assert_no_small_counterexample(lhs, rhs, dialect)


@pytest.mark.parametrize(
    ("lhs", "rhs", "dialect"),
    [
        ({"type": "string"}, {"type": "number"}, Dialect.DRAFT7),
        (
            {"type": "integer", "multipleOf": 5},
            {"type": "integer", "multipleOf": 7},
            Dialect.DRAFT7,
        ),
        (
            {"type": "string", "minLength": 2},
            {"type": "string", "maxLength": 1},
            Dialect.DRAFT7,
        ),
        (
            {"type": "array", "minItems": 2},
            {"type": "array", "uniqueItems": True},
            Dialect.DRAFT7,
        ),
        (
            {"type": "array", "minItems": 1, "items": {"type": "number"}},
            {"type": "array", "contains": {"type": "integer"}},
            Dialect.DRAFT6,
        ),
        (
            {"type": "object", "minProperties": 2},
            {"type": "object", "maxProperties": 1},
            Dialect.DRAFT7,
        ),
        ({"enum": [1, "a"]}, {"type": "number"}, Dialect.DRAFT7),
        (
            {"type": "object", "propertyNames": {"pattern": "^b"}},
            {"type": "object", "propertyNames": {"pattern": "^a"}},
            Dialect.DRAFT7,
        ),
        (
            {
                "type": "object",
                "properties": {"email": {"type": "integer"}},
                "required": ["email"],
                "additionalProperties": False,
            },
            {"type": "object", "patternProperties": {"^emai": {"type": "string"}}},
            Dialect.DRAFT7,
        ),
        (
            {"const": 1},
            {"oneOf": [{"type": "number"}, {"const": 1}]},
            Dialect.DRAFT7,
        ),
        (
            {"type": "string", "pattern": "^ab"},
            {"not": {"pattern": "^a"}},
            Dialect.DRAFT7,
        ),
        (
            {"anyOf": [{"const": 1}, {"const": "a"}]},
            {"type": "number"},
            Dialect.DRAFT7,
        ),
        (
            {"if": {"type": "string"}, "then": {"minLength": 1}, "else": False},
            {"type": "string", "minLength": 2},
            Dialect.DRAFT7,
        ),
    ],
)
def test_false_witnesses_validate_for_representative_fragments(lhs, rhs, dialect):
    proof = ProofEngine.for_schemas(lhs, rhs, dialect=dialect).is_subschema(
        lhs,
        rhs,
    )

    assert proof.status == "proved_false"
    assert_witness_validates(lhs, rhs, dialect, proof.witness)


@pytest.mark.parametrize(("fragment", "lhs", "rhs", "dialect", "options"), GROUPED_FALSE_WITNESS_CASES)
def test_grouped_false_witnesses_validate_by_generator_family(fragment, lhs, rhs, dialect, options):
    assert fragment
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=dialect, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_false"
    assert_witness_validates(lhs, rhs, dialect, proof.witness)


@pytest.mark.parametrize(
    ("schema", "dialect"),
    [
        (True, Dialect.DRAFT7),
        (False, Dialect.DRAFT7),
        ({"type": "integer", "minimum": 1}, Dialect.DRAFT7),
        ({"type": "string", "pattern": "^a", "maxLength": 3}, Dialect.DRAFT7),
        ({"enum": [1, "a", None]}, Dialect.DRAFT7),
        ({"type": "array", "items": {"type": "integer"}, "maxItems": 2}, Dialect.DRAFT7),
        ({"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}, Dialect.DRAFT7),
        ({"type": "array", "prefixItems": [{"type": "integer"}]}, Dialect.DRAFT202012),
    ],
)
def test_reflexivity_invariant_for_representative_fragments(schema, dialect):
    assert_proved_subschema(schema, schema, dialect)


@pytest.mark.parametrize(
    ("narrow", "middle", "wide", "dialect"),
    [
        (
            {"type": "integer", "minimum": 2, "maximum": 4},
            {"type": "number", "minimum": 1},
            {"type": "number"},
            Dialect.DRAFT7,
        ),
        (
            {"type": "string", "pattern": "^alpha", "maxLength": 8},
            {"type": "string", "pattern": "^a"},
            {"type": "string"},
            Dialect.DRAFT7,
        ),
        (
            {"const": 1},
            {"enum": [1, 2]},
            {"type": "number"},
            Dialect.DRAFT7,
        ),
        (
            {"type": "object", "required": ["a", "b"]},
            {"type": "object", "minProperties": 2},
            {"type": "object"},
            Dialect.DRAFT7,
        ),
        (
            {"type": "array", "items": [{}, {}], "additionalItems": False},
            {"type": "array", "maxItems": 2},
            {"type": "array"},
            Dialect.DRAFT7,
        ),
    ],
)
def test_transitivity_smoke_invariant_for_representative_fragments(narrow, middle, wide, dialect):
    assert_proved_subschema(narrow, middle, dialect)
    assert_proved_subschema(middle, wide, dialect)
    assert_proved_subschema(narrow, wide, dialect)
    assert_no_small_counterexample(narrow, wide, dialect)


@pytest.mark.parametrize(
    ("lhs", "rhs", "dialect"),
    [
        ({"type": "integer"}, {"type": "number"}, Dialect.DRAFT7),
        ({"enum": [1, 2]}, {"enum": [2, 3]}, Dialect.DRAFT7),
        (False, {"type": "string"}, Dialect.DRAFT7),
        ({"const": {"a": 1}}, {"type": "object"}, Dialect.DRAFT7),
        (
            {
                "type": "object",
                "properties": {"a": {"type": "integer"}},
                "required": ["a"],
                "additionalProperties": False,
            },
            {"type": "object", "properties": {"a": {"type": "number"}}},
            Dialect.DRAFT7,
        ),
    ],
)
def test_meet_and_join_projection_invariants(lhs, rhs, dialect):
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=dialect,
        options=ProofOptions(),
    )

    meet = engine.meet(lhs, rhs)
    join = engine.join(lhs, rhs)

    assert_proved_subschema(meet, lhs, dialect)
    assert_proved_subschema(meet, rhs, dialect)
    assert_proved_subschema(lhs, join, dialect)
    assert_proved_subschema(rhs, join, dialect)


def test_default_proof_options_preserve_existing_behavior():
    lhs = {"type": "integer"}
    rhs = {"type": "number"}
    engine = ProofEngine.for_schemas(lhs, rhs, options=ProofOptions())

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "proved_true"


@pytest.mark.parametrize(
    ("rhs", "reason"),
    (
        (
            {"type": "string", "pattern": "(?=a)"},
            "non-regular-regex: lookaround/zero-width assertions are unsupported",
        ),
        (
            {"type": "object", "patternProperties": {r"(a)\1": {"type": "number"}}},
            "non-regular-regex: backreferences are unsupported",
        ),
        (
            {"type": "string", "pattern": r"\s"},
            "unsupported-regex-syntax: ECMA whitespace escapes are outside the supported regex frontend",
        ),
    ),
)
def test_non_regular_regex_fragments_are_structured_unsupported(rhs, reason):
    lhs = {"type": "object"} if "patternProperties" in rhs else {"type": "string"}
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(),
    )

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "unsupported"
    assert reason in proof.reason
    assert proof.diagnostics
    assert proof.diagnostics[0].category == "non-regular-regex"


@pytest.mark.parametrize(
    "invalid_budget_kwargs",
    [
        {"max_candidates": 0},
        {"max_array_length": 2},
        {"max_branch_expansions": 0},
        {"max_object_universe": 1},
        {"max_regex_states": 1},
    ],
)
def test_invalid_budget_fields_are_rejected(invalid_budget_kwargs):
    with pytest.raises(TypeError):
        ProofBudgets(**invalid_budget_kwargs)


def test_meet_and_join_use_modern_projection():
    lhs = {"type": "object", "minProperties": 1, "patternProperties": {"^a": {"type": "integer"}}}
    rhs = {"type": "object", "minProperties": 1, "patternProperties": {"^a+": {"type": "number"}}}
    engine = ProofEngine.for_schemas(lhs, rhs, options=ProofOptions())

    assert engine.meet(lhs, rhs) == lhs
    assert engine.join(lhs, rhs) == rhs


def test_bounded_search_reports_resource_exhausted_when_candidate_budget_is_exceeded():
    lhs = {"type": "object", "minProperties": 1, "patternProperties": {"^a": {"type": "number"}}}
    rhs = {"type": "object", "minProperties": 1, "patternProperties": {"^a+": {"type": "integer"}}}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "object product exceeded proof work budget"


def test_array_length_witness_reports_resource_exhausted_when_array_budget_is_exceeded():
    lhs = {"type": "array", "minItems": 3}
    rhs = {"type": "array", "maxItems": 2}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=2))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "array witness exceeded proof work budget"


def test_array_uniqueness_witness_reports_resource_exhausted_when_array_budget_is_exceeded():
    lhs = {"type": "array", "minItems": 2}
    rhs = {"type": "array", "uniqueItems": True}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "array witness exceeded proof work budget"


def test_array_contains_witness_reports_resource_exhausted_when_array_budget_is_exceeded():
    lhs = {"type": "array", "items": True, "minItems": 3}
    rhs = {"type": "array", "contains": True, "minContains": 0, "maxContains": 2}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=2))
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT201909, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "array witness exceeded proof work budget"


def test_array_contains_structural_max_violation_reports_resource_exhausted_when_array_budget_is_exceeded():
    lhs = {
        "type": "array",
        "prefixItems": [{"type": "integer"}, {"type": "integer"}],
        "maxItems": 2,
    }
    rhs = {
        "type": "array",
        "contains": {"type": "integer"},
        "minContains": 0,
        "maxContains": 1,
    }
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1))
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "array witness exceeded proof work budget"


def test_array_contains_min_violation_reports_resource_exhausted_when_array_budget_is_exceeded():
    lhs = {"type": "array", "items": {"type": "string"}, "minItems": 3}
    rhs = {"type": "array", "contains": {"type": "integer"}, "minContains": 1}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=2))
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT201909, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "array witness exceeded proof work budget"


def test_array_item_values_preserve_resource_exhausted_from_subproofs():
    lhs = {"type": "array", "items": {"anyOf": [{"type": "integer"}]}, "minItems": 1}
    rhs = {"type": "array", "items": {"type": "number"}}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_array_item_values_reports_resource_exhausted_when_length_witness_exceeds_array_budget():
    lhs = {
        "type": "array",
        "prefixItems": [{"type": "integer"}],
        "items": {"type": "string"},
        "minItems": 3,
    }
    rhs = {
        "type": "array",
        "prefixItems": [{"type": "integer"}, {"type": "string"}],
        "items": False,
    }
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=2))
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "array witness exceeded proof work budget"


def test_array_item_values_reports_resource_exhausted_when_obligation_witness_exceeds_array_budget():
    lhs = {"type": "array", "items": [{"type": "string"}]}
    rhs = {"type": "array", "items": {"type": "string"}}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1))
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT4,
        options=options,
    )

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_unevaluated_items_reports_resource_exhausted_when_extra_item_witness_exceeds_array_budget():
    lhs = {
        "type": "array",
        "prefixItems": [{"type": "integer"}, {"type": "integer"}],
        "minItems": 2,
        "maxItems": 2,
    }
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [{"prefixItems": [{"type": "integer"}]}],
        "unevaluatedItems": False,
    }
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1))
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "array witness exceeded proof work budget"


def test_unevaluated_items_reports_resource_exhausted_when_value_witness_exceeds_array_budget():
    lhs = {
        "type": "array",
        "prefixItems": [{"type": "number"}],
        "maxItems": 1,
    }
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [{"prefixItems": [{"type": "string"}]}],
        "unevaluatedItems": False,
    }
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_unevaluated_properties_branch_effect_budget_exhaustion_returns_resource_exhausted():
    lhs = {
        "type": "object",
        "properties": {"foo": {"type": "string"}},
        "additionalProperties": False,
    }
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "anyOf": [{"properties": {"foo": {"type": "string"}}}, False],
        "unevaluatedProperties": False,
    }
    options = ProofOptions(
        endeavor=True,
        budgets=ProofBudgets(max_work=0),
    )
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012, options=options)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_unevaluated_items_branch_effect_budget_exhaustion_returns_resource_exhausted():
    lhs = {
        "type": "array",
        "prefixItems": [{"type": "integer"}],
        "maxItems": 1,
    }
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "if": {"type": "array"},
        "then": {"prefixItems": [{"type": "number"}]},
        "unevaluatedItems": False,
    }
    options = ProofOptions(
        endeavor=True,
        budgets=ProofBudgets(max_work=0),
    )
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012, options=options)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_ambiguous_any_of_evaluation_effects_stay_unsupported_with_modern_kernel():
    lhs = {"type": "object"}
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "anyOf": [
            {"required": ["foo"], "properties": {"foo": {"type": "string"}}},
            {"required": ["bar"], "properties": {"bar": {"type": "number"}}},
        ],
        "unevaluatedProperties": False,
    }
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(),
    )

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "unsupported"
    assert "branch-aware anyOf effects" in proof.reason


def test_not_evaluation_effects_stay_unsupported_with_modern_kernel():
    lhs = {"type": "object"}
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "not": {"properties": {"foo": {"type": "string"}}},
        "unevaluatedProperties": False,
    }
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(),
    )

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "unsupported"
    assert "not effects" in proof.reason


def test_schema_valued_unevaluated_properties_unbounded_case_stays_unsupported():
    lhs = {"type": "object"}
    rhs = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "unevaluatedProperties": {"type": "number"},
    }
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(),
    )

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "unsupported"
    assert proof.reason == "SAT schema-valued unevaluatedProperties witness requires a finite closed left keyspace"


def test_object_presence_product_reports_resource_exhausted_when_universe_budget_is_exceeded():
    lhs = {"type": "object", "required": ["a", "b"]}
    rhs = {"type": "object", "required": ["a"]}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "object product exceeded proof work budget"


def test_object_key_value_reports_resource_exhausted_for_mixed_product_budget():
    lhs = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "patternProperties": {"^b": {"type": "integer"}},
    }
    rhs = {
        "type": "object",
        "properties": {"a": {"type": "number"}},
        "patternProperties": {"^b": {"type": "number"}},
    }
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "object product exceeded proof work budget"


def test_object_key_value_reports_resource_exhausted_for_pattern_obligation_budget():
    lhs = {
        "type": "object",
        "patternProperties": {
            "^a": {"type": "integer"},
            "^b": {"type": "integer"},
        },
    }
    rhs = {
        "type": "object",
        "patternProperties": {
            "^a": {"type": "number"},
            "^b": {"type": "number"},
        },
    }
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "object product exceeded proof work budget"


def test_object_presence_domain_tactic_reports_resource_exhausted_when_universe_budget_is_exceeded():
    lhs = {"type": "object", "required": ["a", "b"]}
    rhs = {"type": "object"}
    context = ProofContext(Dialect.DRAFT7, ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1)))

    proof = ObjectPresenceDomainTactic(context).is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "object product exceeded proof work budget"


def test_object_structure_domain_tactic_reports_resource_exhausted_when_universe_budget_is_exceeded():
    lhs = {"type": "object", "required": ["a", "b"], "minProperties": 2}
    rhs = {"type": "object", "minProperties": 1}
    context = ProofContext(Dialect.DRAFT7, ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1)))

    proof = ObjectStructureDomainTactic(context).is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "object product exceeded proof work budget"


def test_public_subschema_keeps_solver_resource_exhaustion_with_solver_path():
    lhs = {"type": "array", "items": {"anyOf": [{"type": "integer"}]}, "minItems": 1}
    rhs = {"type": "array", "items": {"type": "number"}}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012, options=options)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_bounded_ir_uses_sat_emptiness_solver_before_generic_search_path(monkeypatch):
    lhs = {"const": {"a": 1}}
    rhs = {"type": "array"}
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

    def fail_blocked_search_path(*_args, **_kwargs):
        raise AssertionError("SAT solver should prove this difference inside the solver path")

    monkeypatch.setattr(engine.context, "blocked_search_path", fail_blocked_search_path, raising=False)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_false"
    assert proof.witness == {"a": 1}
    assert_witness_validates(lhs, rhs, Dialect.DRAFT7, proof.witness)


def test_bounded_ir_sat_solver_can_prove_finite_empty_difference(monkeypatch):
    lhs = {"enum": [1, 2]}
    rhs = {"type": "number"}
    engine = ProofEngine.for_schemas(lhs, rhs)

    def fail_blocked_search_path(*_args, **_kwargs):
        raise AssertionError("SAT solver should prove the finite difference is empty")

    monkeypatch.setattr(engine.context, "blocked_search_path", fail_blocked_search_path, raising=False)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_true"


def test_object_pattern_obligations_with_property_counts_prove(monkeypatch):
    lhs = {"type": "object", "minProperties": 1, "patternProperties": {"^a": {"type": "number"}}}
    rhs = {"type": "object", "minProperties": 1, "patternProperties": {"^a+": {"type": "integer"}}}
    engine = ProofEngine.for_schemas(lhs, rhs)

    def fail_blocked_search_path(*_args, **_kwargs):
        raise AssertionError("default proof policy must not use constructive proof path")

    monkeypatch.setattr(engine.context, "blocked_search_path", fail_blocked_search_path, raising=False)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_false"
    assert set(proof.witness) == {"a"}
    assert isinstance(proof.witness["a"], int | float)
    assert not float(proof.witness["a"]).is_integer()
    assert_witness_validates(lhs, rhs, Dialect.DRAFT7, proof.witness)


@pytest.mark.parametrize(
    ("lhs", "rhs", "dialect", "reason_fragment"),
    [
        (
            True,
            {"$dynamicRef": "#node"},
            Dialect.DRAFT202012,
            "could not resolve rhs $dynamicRef",
        ),
        (
            {"definitions": {"x": {"$ref": "#/definitions/x"}}, "$ref": "#/definitions/x"},
            {"type": "string"},
            Dialect.DRAFT7,
            "recursive lhs $ref",
        ),
    ],
)
def test_modern_unsupported_cases_do_not_return_success(lhs, rhs, dialect, reason_fragment):
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=dialect,
        options=ProofOptions(),
    )

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status in {"unsupported", "resource_exhausted"}
    assert proof.status != "proved_true"
    assert reason_fragment in proof.reason


def test_rhs_not_uses_required_property_disjointness_for_object_values():
    lhs = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
    rhs = {"not": {"required": ["a"], "properties": {"a": {"type": "string"}}}}
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7, options=ProofOptions())

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "proved_true"


def test_endeavor_object_product_expands_complex_value_obligations(monkeypatch):
    lhs = {"type": "object", "patternProperties": {"^a": {"type": "array", "contains": {"type": "integer"}, "minContains": 1}}}
    rhs = {"type": "object", "patternProperties": {"^a": {"type": "array", "contains": {"type": "integer"}, "minContains": 2}}}
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT201909,
        options=ProofOptions(endeavor=True),
    )

    def fail_blocked_search_path(*_args, **_kwargs):
        raise AssertionError("endeavor object product should prove this inside the solver path")

    monkeypatch.setattr(engine.context, "blocked_search_path", fail_blocked_search_path, raising=False)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_false"
    assert_witness_validates(lhs, rhs, Dialect.DRAFT201909, proof.witness)


def test_endeavor_object_product_expands_property_names_additional_obligations(monkeypatch):
    lhs = {
        "type": "object",
        "minProperties": 1,
        "propertyNames": {"pattern": "^a"},
        "additionalProperties": {"type": "array", "contains": {"type": "integer"}, "minContains": 1},
    }
    rhs = {
        "type": "object",
        "minProperties": 1,
        "propertyNames": {"pattern": "^a"},
        "additionalProperties": {"type": "array", "contains": {"type": "integer"}, "minContains": 2},
    }
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT201909,
        options=ProofOptions(endeavor=True),
    )

    def fail_blocked_search_path(*_args, **_kwargs):
        raise AssertionError("endeavor propertyNames/additionalProperties product should prove inside the solver path")

    monkeypatch.setattr(engine.context, "blocked_search_path", fail_blocked_search_path, raising=False)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_false"
    assert_witness_validates(lhs, rhs, Dialect.DRAFT201909, proof.witness)


def test_endeavor_object_product_expands_pattern_properties_to_additional_obligations(monkeypatch):
    lhs = {
        "type": "object",
        "minProperties": 1,
        "propertyNames": {"pattern": "^a"},
        "patternProperties": {"^a": {"type": "array", "contains": {"type": "integer"}, "minContains": 1}},
    }
    rhs = {
        "type": "object",
        "minProperties": 1,
        "propertyNames": {"pattern": "^a"},
        "additionalProperties": {"type": "array", "contains": {"type": "integer"}, "minContains": 2},
    }
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT201909,
        options=ProofOptions(endeavor=True),
    )

    def fail_blocked_search_path(*_args, **_kwargs):
        raise AssertionError("endeavor patternProperties/additionalProperties product should prove inside the solver path")

    monkeypatch.setattr(engine.context, "blocked_search_path", fail_blocked_search_path, raising=False)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_false"
    assert_witness_validates(lhs, rhs, Dialect.DRAFT201909, proof.witness)


def test_default_mode_does_not_enter_endeavor_object_product():
    lhs = {"type": "object", "patternProperties": {"^a": {"type": "array", "contains": {"type": "integer"}, "minContains": 1}}}
    rhs = {"type": "object", "patternProperties": {"^a": {"type": "array", "contains": {"type": "integer"}, "minContains": 2}}}
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT201909,
        options=ProofOptions(),
    )

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "unsupported"


def test_endeavor_array_contains_product_proves_min_violation(monkeypatch):
    lhs = {"type": "array", "contains": {"type": "integer"}, "minContains": 1}
    rhs = {"type": "array", "contains": {"type": "integer"}, "minContains": 2}
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT201909,
        options=ProofOptions(endeavor=True),
    )

    def fail_blocked_search_path(*_args, **_kwargs):
        raise AssertionError("endeavor array product should prove this inside the solver path")

    monkeypatch.setattr(engine.context, "blocked_search_path", fail_blocked_search_path, raising=False)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_false"
    assert_witness_validates(lhs, rhs, Dialect.DRAFT201909, proof.witness)


def test_endeavor_array_contains_product_proves_max_violation(monkeypatch):
    lhs = {"type": "array", "contains": {"type": "integer"}, "minContains": 2}
    rhs = {"type": "array", "contains": {"type": "integer"}, "maxContains": 1}
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT201909,
        options=ProofOptions(endeavor=True),
    )

    def fail_blocked_search_path(*_args, **_kwargs):
        raise AssertionError("endeavor array max product should prove this inside the solver path")

    monkeypatch.setattr(engine.context, "blocked_search_path", fail_blocked_search_path, raising=False)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_false"
    assert_witness_validates(lhs, rhs, Dialect.DRAFT201909, proof.witness)


def test_endeavor_evaluation_trace_expands_contains_unevaluated_items(monkeypatch):
    lhs = {"type": "array", "minItems": 1, "maxItems": 1, "items": {"type": "number"}}
    rhs = {"type": "array", "contains": {"type": "integer"}, "unevaluatedItems": False}
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(endeavor=True),
    )

    def fail_blocked_search_path(*_args, **_kwargs):
        raise AssertionError("endeavor evaluation trace should prove this inside the solver path")

    monkeypatch.setattr(engine.context, "blocked_search_path", fail_blocked_search_path, raising=False)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "proved_false"
    assert len(proof.witness) == 1
    assert isinstance(proof.witness[0], int | float)
    assert not float(proof.witness[0]).is_integer()
    assert_witness_validates(lhs, rhs, Dialect.DRAFT202012, proof.witness)


@pytest.mark.parametrize(
    ("lhs", "rhs", "dialect", "reason"),
    (
        (
            {"type": "object", "patternProperties": {"^a": {"type": "array", "contains": {"type": "integer"}, "minContains": 1}}},
            {"type": "object", "patternProperties": {"^a": {"type": "array", "contains": {"type": "integer"}, "minContains": 2}}},
            Dialect.DRAFT201909,
            "object product exceeded proof work budget",
        ),
        (
            {"type": "array", "contains": {"type": "integer"}, "minContains": 1},
            {"type": "array", "contains": {"type": "integer"}, "minContains": 2},
            Dialect.DRAFT201909,
            "array product exceeded proof work budget",
        ),
        (
            {"type": "array", "minItems": 1, "maxItems": 1, "items": {"type": "number"}},
            {"type": "array", "contains": {"type": "integer"}, "unevaluatedItems": False},
            Dialect.DRAFT202012,
            "evaluation trace exceeded proof work budget",
        ),
    ),
)
def test_endeavor_expanded_products_exhaust_first_work_unit(lhs, rhs, dialect, reason):
    engine = ProofEngine.for_schemas(
        lhs,
        rhs,
        dialect=dialect,
        options=ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)),
    )

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == reason


def test_endeavor_expanded_product_small_positive_budgets_track_frontiers():
    object_lhs = {
        "type": "object",
        "patternProperties": {"^a": {"type": "array", "contains": {"type": "integer"}, "minContains": 1}},
    }
    object_rhs = {
        "type": "object",
        "patternProperties": {"^a": {"type": "array", "contains": {"type": "integer"}, "minContains": 2}},
    }
    object_engine = ProofEngine.for_schemas(
        object_lhs,
        object_rhs,
        dialect=Dialect.DRAFT201909,
        options=ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1)),
    )

    object_proof = object_engine._bounded_ir_proof(object_lhs, object_rhs)

    assert object_proof.status == "resource_exhausted"
    assert object_proof.reason == "object product exceeded proof work budget"

    array_lhs = {"type": "array", "contains": {"type": "integer"}, "minContains": 1}
    array_rhs = {"type": "array", "contains": {"type": "integer"}, "minContains": 2}
    array_engine = ProofEngine.for_schemas(
        array_lhs,
        array_rhs,
        dialect=Dialect.DRAFT201909,
        options=ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=2)),
    )

    array_proof = array_engine._bounded_ir_proof(array_lhs, array_rhs)

    assert array_proof.status == "proved_false"
    assert_witness_validates(array_lhs, array_rhs, Dialect.DRAFT201909, array_proof.witness)

    evaluation_lhs = {"type": "array", "minItems": 1, "maxItems": 1, "items": {"type": "number"}}
    evaluation_rhs = {"type": "array", "contains": {"type": "integer"}, "unevaluatedItems": False}
    evaluation_engine = ProofEngine.for_schemas(
        evaluation_lhs,
        evaluation_rhs,
        dialect=Dialect.DRAFT202012,
        options=ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=2)),
    )

    evaluation_proof = evaluation_engine._bounded_ir_proof(evaluation_lhs, evaluation_rhs)

    assert evaluation_proof.status == "proved_false"
    assert_witness_validates(evaluation_lhs, evaluation_rhs, Dialect.DRAFT202012, evaluation_proof.witness)

    max_lhs = {"type": "array", "contains": {"type": "integer"}, "minContains": 2}
    max_rhs = {"type": "array", "contains": {"type": "integer"}, "maxContains": 1}
    max_budget_engine = ProofEngine.for_schemas(
        max_lhs,
        max_rhs,
        dialect=Dialect.DRAFT201909,
        options=ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=1)),
    )

    max_budget_proof = max_budget_engine._bounded_ir_proof(max_lhs, max_rhs)

    assert max_budget_proof.status == "resource_exhausted"
    assert max_budget_proof.reason == "array product exceeded proof work budget"


def test_candidate_budget_applies_only_to_final_witness_search():
    lhs = {"type": "object", "minProperties": 1, "patternProperties": {"^a": {"type": "array", "minItems": 1}}}
    rhs = {"type": "object", "minProperties": 1, "patternProperties": {"^a": {"type": "array", "minItems": 2}}}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine._bounded_ir_proof(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "object product exceeded proof work budget"


def test_sat_solver_exposes_language_difference_formula():
    formula = DifferenceFormula.from_schemas({"type": "integer"}, {"type": "number"}, Dialect.DRAFT7)
    solver = EmptinessSolver(ProofContext(Dialect.DRAFT7))

    proof = solver.prove_formula_difference_empty(formula)

    assert DifferenceFormula.__module__ == "subschema.kernel.formulas"
    assert EmptinessSolver.__module__ == "subschema.kernel.sat"
    assert formula.lhs.__class__.__module__ == "subschema.kernel.ir"
    assert formula.lhs.source.__class__.__module__ == "subschema.kernel.references"
    assert formula.lhs.type_shape is not None
    assert formula.rhs.type_shape is not None
    assert formula.rhs.numeric_shape is not None
    assert proof.status == "proved_true"


def test_difference_formula_lowers_to_typed_formula_nodes():
    formula = DifferenceFormula.from_schemas(
        {"allOf": [{"type": "integer"}, {"minimum": 1}]},
        {"anyOf": [{"type": "number"}, {"const": "x"}]},
        Dialect.DRAFT7,
    )

    root = formula.formula
    lhs_formula = formula.positive_lhs.formula
    rhs_formula = formula.negative_rhs.formula

    assert isinstance(root, AndFormula)
    assert root.children == (lhs_formula, rhs_formula)
    assert isinstance(lhs_formula, AndFormula)
    assert len(lhs_formula.children) == 3
    assert isinstance(rhs_formula, AndFormula)
    assert all(isinstance(child, NotFormula) for child in rhs_formula.children)


def test_formula_lowering_handles_booleans_not_oneof_and_conditionals():
    boolean_formula = DifferenceFormula.from_schemas(True, False, Dialect.DRAFT7)
    assert isinstance(boolean_formula.positive_lhs.formula, TopFormula)
    assert isinstance(boolean_formula.negative_rhs.formula, TopFormula)

    not_formula = DifferenceFormula.from_schemas(
        {"type": "string"},
        {"not": {"type": "string"}},
        Dialect.DRAFT7,
    )
    assert isinstance(not_formula.negative_rhs.formula, AndFormula)
    assert any(isinstance(child, AssertionFormula) for child in not_formula.negative_rhs.formula.children)

    positive_not_formula = DifferenceFormula.from_schemas(
        {"not": {"type": "string"}},
        {},
        Dialect.DRAFT7,
    )
    assert isinstance(positive_not_formula.positive_lhs.formula, AndFormula)
    positive_not_wrapper = next(
        child
        for child in positive_not_formula.positive_lhs.formula.children
        if isinstance(child, NotFormula) and child.applicator_kind == "not"
    )
    assert positive_not_wrapper.polarity == "positive"

    one_of_formula = DifferenceFormula.from_schemas(
        {},
        {"oneOf": [{"type": "string"}, {"type": "number"}]},
        Dialect.DRAFT7,
    )
    assert isinstance(one_of_formula.negative_rhs.formula, ExactlyOneFormula)
    assert one_of_formula.negative_rhs.formula.polarity == "negative"
    assert len(one_of_formula.negative_rhs.formula.children) == 2

    conditional_formula = DifferenceFormula.from_schemas(
        {
            "if": {"type": "string"},
            "then": {"minLength": 1},
            "else": {"type": "number"},
        },
        {},
        Dialect.DRAFT7,
    )
    assert isinstance(conditional_formula.positive_lhs.formula, GuardedFormula)
    assert conditional_formula.positive_lhs.formula.then_branch is not None
    assert conditional_formula.positive_lhs.formula.else_branch is not None

    negative_conditional_formula = DifferenceFormula.from_schemas(
        {},
        {
            "if": {"type": "string"},
            "then": {"minLength": 1},
            "else": {"type": "number"},
        },
        Dialect.DRAFT7,
    )
    assert isinstance(negative_conditional_formula.negative_rhs.formula, GuardedFormula)
    assert negative_conditional_formula.negative_rhs.formula.polarity == "negative"
    assert negative_conditional_formula.negative_rhs.formula.then_branch is not None
    assert negative_conditional_formula.negative_rhs.formula.else_branch is not None


def test_formula_lowering_records_static_references_as_reference_nodes():
    formula = DifferenceFormula.from_schemas(
        {
            "definitions": {"name": {"type": "string"}},
            "$ref": "#/definitions/name",
        },
        {"type": "string"},
        Dialect.DRAFT7,
    )

    lhs_formula = formula.positive_lhs.formula

    assert isinstance(lhs_formula, ReferenceFormula)
    assert lhs_formula.target == "#/definitions/name"
    assert lhs_formula.dynamic is False
    assert formula.unsupported_diagnostics == ()


def test_applicator_subproofs_share_the_engine_context():
    lhs = {"anyOf": [{"type": "integer"}]}
    rhs = {"type": "number"}
    engine = ProofEngine.for_schemas(lhs, rhs)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "proved_true"
    assert engine.context.subproof_cache
    cache_key = next(iter(engine.context.subproof_cache))
    assert cache_key[:4] == (
        engine.context.dialect,
        engine.context.options.endeavor,
        engine.context.options.budgets.max_work,
        engine.context.options.budgets.timeout_ms,
    )


def test_applicator_subproofs_use_branch_expansion_budget():
    lhs = {"anyOf": [{"type": "integer"}]}
    rhs = {"type": "number"}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_conditional_branch_products_use_branch_expansion_budget():
    lhs = {"type": "string", "minLength": 2}
    rhs = {"if": {"type": "string"}, "then": {"minLength": 2}}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7, options=options)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_one_of_cardinality_products_use_branch_expansion_budget():
    lhs = {"type": "object"}
    rhs = {"oneOf": [{"type": "object"}, {"type": "array"}]}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_one_of_disjointness_products_use_branch_expansion_budget():
    lhs = {"type": "object"}
    rhs = {"oneOf": [{"type": "object"}, {"type": "array"}]}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=2))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_left_applicator_branch_products_use_branch_expansion_budget():
    lhs = {"anyOf": [{"type": "integer"}]}
    rhs = {"type": "number"}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"


def test_right_nnf_branch_products_use_branch_expansion_budget():
    lhs = {"type": "string"}
    rhs = {"allOf": [{"type": "string"}]}
    options = ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0))
    engine = ProofEngine.for_schemas(lhs, rhs, options=options)

    proof = engine.is_subschema(lhs, rhs)

    assert proof.status == "resource_exhausted"
    assert proof.reason == "branch expansion exceeded proof work budget"
