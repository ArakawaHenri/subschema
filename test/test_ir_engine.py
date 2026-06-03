import inspect
import unittest
from functools import cached_property
from unittest.mock import patch

import subschema.api as public_api
import subschema.kernel.applicators as applicators_module
import subschema.kernel.composition as composition_module
import subschema.kernel.constraints as constraints_module
import subschema.kernel.context as context_module
import subschema.kernel.contracts as contracts_module
import subschema.kernel.difference as difference_module
import subschema.kernel.disjointness as disjointness_module
import subschema.kernel.driver as driver_module
import subschema.kernel.engine as engine_module
import subschema.kernel.evaluation as evaluation_module
import subschema.kernel.formulas as formulas_module
import subschema.kernel.ir as ir_module
import subschema.kernel.normalization as normalization_module
import subschema.kernel.overlaps as overlaps_module
import subschema.kernel.references as references_module
import subschema.kernel.regex as regex_module
import subschema.kernel.scalars as scalars_module
import subschema.kernel.sat as sat_module
import subschema.kernel.symbolic as symbolic_module
import subschema.kernel.validation as validation_module
import subschema.kernel.witnesses as witnesses_module
import subschema.kernel.domains.arrays as arrays_module
import subschema.kernel.domains.numbers as numbers_module
import subschema.kernel.domains.objects as objects_module
import subschema.kernel.domains.strings as strings_module
import subschema.kernel.domains.types as types_module
from subschema.exceptions import UnsupportedKeywordError
from subschema.kernel.values import json_semantic_key
from subschema.kernel.applicators import (
    ApplicatorBaseProduct,
    ApplicatorBranchPlan,
    ApplicatorBranchProduct,
    ApplicatorConditionalBranch,
    ApplicatorConditionalPlan,
    ApplicatorConditionalProduct,
    ApplicatorExpansionBudget,
    ApplicatorFormulaFragment,
    ApplicatorNnfChild,
    ApplicatorNnfBranchProduct,
    ApplicatorNnfBranchProductPlan,
    ApplicatorNnfFragment,
    ApplicatorNnfSchemaProduct,
    ApplicatorOneOfBranchProduct,
    ApplicatorOneOfCardinalityPlan,
    ApplicatorOneOfCoveringSelection,
    ApplicatorOneOfDisjointnessProduct,
    ApplicatorOneOfOverlapProduct,
    ApplicatorPlanSet,
    applicator_base_product,
    applicator_base_pre_branch_choice,
    applicator_branch_expansion_budget,
    applicator_branch_products,
    applicator_difference_plans,
    applicator_formula_fragments,
    applicator_nnf_fragments,
    applicator_nnf_branch_products,
    applicator_nnf_schema_product,
    applicator_plan_set,
    conditional_branch_proof_choice,
    conditional_branch_products,
    conditional_covering_product_proof_choice,
    conditional_covering_subproof_choice,
    conditional_final_proof_choice,
    left_all_of_branch_proof_choice,
    left_any_of_branch_proof_choice,
    left_branch_resolved_lhs_schema,
    left_one_of_branch_proof_choice,
    one_of_branch_resolved_schema,
    one_of_cardinality_products,
    one_of_coverage_expansion_budget,
    one_of_coverage_branch_proof_choice,
    one_of_covering_selection,
    one_of_disjointness_complement_schema,
    one_of_disjointness_expansion_budget,
    one_of_disjointness_direct_proof_choice,
    one_of_disjointness_proof_choice,
    one_of_disjointness_products,
    one_of_disjointness_resolved_branch_schema,
    one_of_overlap_product,
    one_of_overlap_witness_plan,
    right_not_complement_needs_subproof,
    right_not_complement_proof_choice,
    right_not_complement_schema,
    right_not_resolved_rhs_schema,
    right_not_subproof_choice,
    right_negative_all_of_branch_product_plan,
    right_negative_all_of_branch_proof_choice,
    right_negative_any_of_branch_product_plan,
    right_negative_any_of_branch_proof_choice,
    right_not_witness_plan,
    right_nnf_branch_resolved_rhs_schema,
)
from subschema.kernel.certificates import verify_counterexample_certificate
from subschema.kernel.contracts import (
    CounterexampleCertificate,
    ProofBudgets,
    ProofOptions,
    ProofResult,
    UnsupportedDiagnostic,
)
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
from subschema.kernel.context import ProofContext
from subschema.kernel.engine import ProofEngine
from subschema.kernel.formulas import (
    AndFormula,
    AssertionFormula,
    BottomFormula,
    DifferenceFormula,
    EvaluationEffectFormula,
    ExactlyOneFormula,
    FormulaOccurrence,
    GuardedFormula,
    NotFormula,
    OrFormula,
    ReferenceFormula,
    TopFormula,
    UnsupportedFormula,
)
from subschema.kernel.evaluation import (
    EvaluatedItemSource,
    EvaluatedPropertySource,
    EvaluationExpression,
    EvaluationExpressionOrigin,
    EvaluationFrontier,
    EvaluationTraceExpression,
    evaluation_trace_for_source,
)
from subschema.kernel.difference import (
    ArrayContainsConstraint,
    ArrayContainsDifferencePlan,
    ArrayContainsItemProof,
    ArrayContainsMaxViolationPlan,
    ArrayContainsMinViolationPlan,
    ArrayDifferenceModel,
    ArrayDuplicateWitnessPlan,
    ArrayItemValueObligation,
    ArrayItemValuesDifferencePlan,
    ArrayLengthDifferencePlan,
    ArrayUnevaluatedItemObligation,
    ArrayUnevaluatedItemsDifferencePlan,
    ArrayWitnessOverride,
    ArrayWitnessPlan,
    ArrayWitnessSkeleton,
    ArrayWitnessSlot,
    ArrayUniquenessDifferencePlan,
    ClosedObjectDifferencePlan,
    ClosedObjectValueObligation,
    ClosedObjectWitnessSkeleton,
    ClosedObjectWitnessSlot,
    ObjectDifferenceModel,
    ObjectKeyValueDifferencePlan,
    ObjectKeyValueObligation,
    ObjectKeyValueShape,
    ObjectKeyValueWitnessSkeleton,
    ObjectKeyValueWitnessSlot,
    ObjectPropertyCountDifferencePlan,
    ObjectPropertyValueObligation,
    ObjectPropertyValuesDifferencePlan,
    ObjectPropertyValueWitnessSkeleton,
    ObjectPropertyValueWitnessSlot,
    ObjectPropertyNamesDifferencePlan,
    ObjectPropertyNamesRepairSkeleton,
    ObjectPropertyNamesRepairSlot,
    ObjectUnevaluatedPropertiesDifferencePlan,
    ObjectUnevaluatedPropertyObligation,
    ObjectPresenceProductPlan,
    ObjectPresenceWitnessPlan,
    materialize_closed_object_witness_skeleton,
    materialize_array_duplicate_witness_plan,
    materialize_array_witness_plan,
    materialize_array_witness_skeleton,
    materialize_object_key_value_witness_skeleton,
    materialize_object_property_names_repair_skeleton,
    materialize_object_property_value_witness_skeleton,
)
from subschema.kernel.ir import (
    ApplicatorNode,
    AssertionAtom,
    DomainFacts,
    LogicalSchemaIR,
    SchemaIRCompiler,
    SchemaNode,
    TaggedOneOf,
    UnsupportedNode,
)
from subschema.kernel.overlaps import (
    RightNotStringOverlapPlan,
    right_not_string_overlap_plan,
    right_not_string_overlap_plan_from_constraints,
    right_not_string_overlap_proof_choice,
)
from subschema.kernel.projection import ProjectionEngine
from subschema.kernel.scalars import (
    FiniteRhsDifferencePlan,
    ScalarDifferencePlan,
    finite_rhs_difference_plan,
    finite_rhs_difference_plan_from_constraints,
    numeric_difference_plan,
    numeric_difference_plan_from_constraints,
    string_language_difference_plan,
    string_language_difference_plan_from_constraints,
    string_length_difference_plan,
    string_length_difference_plan_from_constraints,
    type_difference_plan,
    type_difference_plan_from_constraints,
)
from subschema.kernel.semantic import ConcreteEvaluator
from subschema.kernel.sat import (
    DifferenceProblem,
    DifferenceRuleSpec,
    EmptinessSolver,
    difference_rule_specs,
    difference_rules,
)
from subschema.kernel.symbolic import SymbolicSolver
from subschema.kernel.witnesses import (
    WitnessBuildResult,
    build_schema_witness,
    finite_projection_witness,
)
from subschema import Dialect, is_subschema, join_schemas, meet_schemas
from test.proof_oracle import (
    assert_concrete_evaluator_matches_validator,
    assert_concrete_evaluator_unsupported,
    assert_witness_validates,
)


class TestProofEngineRouting(unittest.TestCase):
    def test_public_api_routes_through_proof_engine(self):
        lhs = {"type": "integer"}
        rhs = {"type": "number"}

        self.assertTrue(public_api.is_subschema(lhs, rhs))
        self.assertEqual(public_api.meet_schemas(lhs, rhs), lhs)
        self.assertEqual(public_api.join_schemas(lhs, rhs), rhs)

    def test_public_api_module_uses_modern_normalization(self):
        self.assertEqual(
            public_api.canonicalize_schema(True, dialect=Dialect.DRAFT6), {}
        )
        self.assertEqual(
            public_api.canonicalize_schema(False, dialect=Dialect.DRAFT6), {"not": {}}
        )

    def test_proof_engine_is_the_only_public_subschema_runtime(self):
        lhs = {"type": "object", "properties": {"a": {"type": "integer"}}}
        rhs = {"type": "object", "properties": {"a": {"type": "number"}}}

        proof = ProofEngine.for_schemas(lhs, rhs).is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")
        self.assertTrue(is_subschema(lhs, rhs))
        self.assertEqual(ProofEngine.__module__, "subschema.kernel.engine")

    def test_kernel_returns_solver_result_directly(self):
        lhs = {
            "type": "object",
            "minProperties": 1,
            "patternProperties": {"^a": {"type": "integer"}},
        }
        rhs = {
            "type": "object",
            "minProperties": 1,
            "patternProperties": {"^a+": {"type": "number"}},
        }
        engine = ProofEngine.for_schemas(lhs, rhs, options=ProofOptions())

        proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_runtime_budget_consumers_use_unified_work_meter(self):
        self.assertIn("max_work", inspect.getsource(contracts_module.ProofBudgets))
        self.assertIn("ProofWorkMeter", inspect.getsource(context_module))
        self.assertIn("ExpensiveProofKind", inspect.getsource(contracts_module))
        self.assertIn("enter_expensive_proof", inspect.getsource(context_module))

    def test_expensive_proof_gate_uses_typed_policy_and_work_meter(self):
        default_context = ProofContext(Dialect.DRAFT7)
        endeavor_context = ProofContext(
            Dialect.DRAFT7,
            ProofOptions(endeavor=True, budgets=ProofBudgets(max_work=0)),
        )

        default_result = default_context.enter_expensive_proof("object_product")
        exhausted_result = endeavor_context.enter_expensive_proof(
            "object_product", units=1
        )

        self.assertEqual(default_context.work_meter.limit, -1)
        self.assertEqual(endeavor_context.work_meter.limit, 0)
        self.assertEqual(default_result.status, "unsupported")
        self.assertEqual(
            default_result.reason, "object product requires endeavor proof"
        )
        self.assertEqual(exhausted_result.status, "resource_exhausted")
        self.assertEqual(
            exhausted_result.reason, "object product exceeded proof work budget"
        )

    def test_proof_budget_configuration_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            ProofBudgets(max_work=-2)
        with self.assertRaises(ValueError):
            ProofBudgets(timeout_ms=-2)
        with self.assertRaises(TypeError):
            ProofBudgets(max_work=True)
        with self.assertRaises(TypeError):
            ProofBudgets(timeout_ms=1.5)

        unlimited = ProofBudgets(max_work=-1, timeout_ms=-1)
        self.assertEqual(unlimited.max_work, -1)
        self.assertEqual(unlimited.timeout_ms, -1)

    def test_proof_work_meter_rejects_invalid_spend_units(self):
        meter = contracts_module.ProofWorkMeter(1)

        with self.assertRaises(TypeError):
            meter.spend(True, "object product")
        with self.assertRaises(ValueError):
            meter.spend(-1, "object product")
        self.assertIsNone(meter.spend(0, "object product"))

    def test_proof_options_reject_invalid_runtime_configuration(self):
        with self.assertRaises(TypeError):
            ProofOptions(endeavor="yes")
        with self.assertRaises(TypeError):
            ProofOptions(**{"mode": "endeavor"})
        with self.assertRaises(TypeError):
            ProofOptions(budgets={"max_work": 1})
        with self.assertRaises(ValueError):
            ProofOptions(budgets=ProofBudgets(max_work=1))
        with self.assertRaises(TypeError):
            ProofContext(Dialect.DRAFT7, options={})
        with self.assertRaises(TypeError):
            ProofEngine(Dialect.DRAFT7, options={})

    def test_symbolic_solver_timeout_is_resource_exhausted(self):
        class FakeTimeoutSolver:
            def __init__(self):
                self.timeout_was_set = False

            def set(self, **_kwargs):
                self.timeout_was_set = True

            def check(self):
                return symbolic_module.z3.unknown

            def reason_unknown(self):
                return "timeout"

        context = ProofContext(
            Dialect.DRAFT7,
            ProofOptions(endeavor=True, budgets=ProofBudgets(timeout_ms=10)),
        )
        solver = symbolic_module.SymbolicSolver(
            context,
            "object product",
            "object product exceeded proof work budget",
            solver=FakeTimeoutSolver(),
        )

        proof = solver.check()

        self.assertEqual(proof.status, "resource_exhausted")
        self.assertEqual(proof.reason, "object product exceeded timeout")

    def test_default_symbolic_solver_does_not_set_timeout(self):
        class FakeSatSolver:
            def __init__(self):
                self.timeout_was_set = False

            def set(self, **_kwargs):
                self.timeout_was_set = True

            def check(self):
                return symbolic_module.z3.sat

        fake_solver = FakeSatSolver()
        solver = symbolic_module.SymbolicSolver(
            ProofContext(Dialect.DRAFT7),
            "object product",
            "object product exceeded proof work budget",
            solver=fake_solver,
        )

        self.assertEqual(solver.context.solver_timeout_ms, -1)
        self.assertEqual(solver.check(), symbolic_module.z3.sat)
        self.assertFalse(fake_solver.timeout_was_set)

    def test_symbolic_solver_unknown_is_unsupported(self):
        class FakeUnknownSolver:
            def set(self, **_kwargs):
                pass

            def check(self):
                return symbolic_module.z3.unknown

            def reason_unknown(self):
                return "incomplete"

        solver = symbolic_module.SymbolicSolver(
            ProofContext(Dialect.DRAFT7),
            "array product",
            "array product exceeded proof work budget",
            solver=FakeUnknownSolver(),
        )

        proof = solver.check()

        self.assertEqual(proof.status, "unsupported")
        self.assertEqual(
            proof.reason, "array product solver returned unknown: incomplete"
        )

    def test_symbolic_solver_rejects_boolean_numeric_inputs(self):
        solver = symbolic_module.SymbolicSolver(
            ProofContext(Dialect.DRAFT7),
            "numeric product",
            "numeric product exceeded proof work budget",
        )

        with self.assertRaisesRegex(ValueError, "not booleans"):
            solver.real_value(True)
        with self.assertRaisesRegex(ValueError, "not booleans"):
            solver.finite_choice("choice", [False, 1])

        self.assertIsNotNone(solver.finite_choice("integer_choice", [0, 1]))

    def test_expensive_proof_mode_checks_are_centralized(self):
        sat_source = inspect.getsource(sat_module)

        self.assertIn("options.endeavor", inspect.getsource(context_module))
        self.assertNotIn("options.endeavor", inspect.getsource(driver_module))
        self.assertNotIn("options.endeavor", sat_source)
        self.assertNotIn("not options.endeavor", sat_source)
        self.assertIn('enter_expensive_proof("object_product")', sat_source)
        self.assertIn('enter_expensive_proof("array_product")', sat_source)

    def test_regular_language_operations_are_routed_through_regex_backend(self):
        for module in (
            difference_module,
            objects_module,
            overlaps_module,
            strings_module,
        ):
            source = inspect.getsource(module)
            self.assertNotIn("from greenery", source)
            self.assertNotIn("import greenery", source)
            self.assertNotIn(".everythingbut()", source)
        self.assertIn("from greenery import parse", inspect.getsource(regex_module))

    def test_domain_math_helpers_do_not_import_proof_engine(self):
        for module in (
            arrays_module,
            numbers_module,
            objects_module,
            strings_module,
            types_module,
            difference_module,
            evaluation_module,
        ):
            source = inspect.getsource(module)
            self.assertNotIn("from subschema.kernel.engine", source)
            self.assertNotIn("import subschema.kernel.engine", source)
            self.assertNotIn("ProofEngine(", source)

    def test_meet_and_join_delegate_to_context_projection_policy(self):
        projection_sources = inspect.getsource(ProofEngine.meet) + inspect.getsource(
            ProofEngine.join
        )

        self.assertIn("self.context.meet", projection_sources)
        self.assertIn("self.context.join", projection_sources)
        self.assertNotIn("finite_", projection_sources)
        self.assertEqual(ProjectionEngine.__module__, "subschema.kernel.projection")

    def test_symbolic_solver_lives_in_kernel_package(self):
        self.assertEqual(SymbolicSolver.__module__, "subschema.kernel.symbolic")

    def test_difference_formula_lowering_golden_cases(self):
        boolean_formula = DifferenceFormula.from_schemas(True, False, Dialect.DRAFT7)

        self.assertEqual(boolean_formula.positive_lhs.schema, True)
        self.assertEqual(boolean_formula.negative_rhs.schema, False)
        self.assertEqual(applicator_formula_fragments(boolean_formula), ())
        self.assertEqual(applicator_nnf_fragments(boolean_formula), ())

        rhs_all_of_formula = DifferenceFormula.from_schemas(
            {"type": "string"},
            {"allOf": [{"type": "string"}, {"minLength": 1}]},
            Dialect.DRAFT7,
        )
        rhs_all_of_formula_node = rhs_all_of_formula.negative_rhs.formula
        self.assertIsInstance(rhs_all_of_formula_node, OrFormula)
        self.assertIs(rhs_all_of_formula_node.source, rhs_all_of_formula.rhs.root)
        self.assertEqual(rhs_all_of_formula_node.applicator_kind, "allOf")
        self.assertEqual(rhs_all_of_formula_node.polarity, "negative")
        self.assertIs(
            rhs_all_of_formula_node.applicator,
            rhs_all_of_formula.rhs.root.applicators[0],
        )
        rhs_all_of_nnf = applicator_nnf_fragments(rhs_all_of_formula)[0]
        self.assertIs(rhs_all_of_nnf.source.formula_node, rhs_all_of_formula_node)
        self.assertEqual(rhs_all_of_nnf.operator, "anyOf")
        self.assertEqual(rhs_all_of_nnf.proof_class, "exact")
        self.assertEqual(rhs_all_of_nnf.branch_product_count, 2)
        self.assertEqual(
            rhs_all_of_nnf.branch_budget_exhausted_reason,
            "branch expansion exceeded proof work budget",
        )
        rhs_all_of_budget = applicator_branch_expansion_budget(rhs_all_of_nnf)
        self.assertIsInstance(rhs_all_of_budget, ApplicatorExpansionBudget)
        self.assertEqual(rhs_all_of_budget.product_count, 2)
        self.assertIsNone(
            rhs_all_of_budget.exhausted_reason_for(current_expansions=0, max_work=2)
        )
        self.assertEqual(
            rhs_all_of_budget.exhausted_reason_for(current_expansions=0, max_work=1),
            rhs_all_of_nnf.branch_budget_exhausted_reason,
        )
        self.assertTrue(
            all(child.polarity == "negative" for child in rhs_all_of_nnf.children)
        )
        self.assertIn("negative allOf normalizes", rhs_all_of_nnf.reason)
        rhs_all_of_products = applicator_nnf_branch_products(
            rhs_all_of_nnf,
            lhs_schema=rhs_all_of_formula.lhs.schema,
        )
        rhs_all_of_product_plan = right_negative_all_of_branch_product_plan(
            rhs_all_of_nnf,
            lhs_schema=rhs_all_of_formula.lhs.schema,
        )
        self.assertIsInstance(rhs_all_of_product_plan, ApplicatorNnfBranchProductPlan)
        self.assertTrue(rhs_all_of_product_plan.is_supported)
        self.assertEqual(rhs_all_of_product_plan.products, rhs_all_of_products)
        self.assertEqual(
            rhs_all_of_products[0].witness_missing_reason,
            "SAT right-allOf conjunct witness could not be constructed",
        )
        self.assertEqual(
            rhs_all_of_products[0].witness_rejected_reason,
            "SAT right-allOf conjunct witness was rejected",
        )

        rhs_any_of_formula = DifferenceFormula.from_schemas(
            {"type": "string"},
            {"anyOf": [{"type": "number"}, {"type": "string"}]},
            Dialect.DRAFT7,
        )
        rhs_any_of_formula_node = rhs_any_of_formula.negative_rhs.formula
        self.assertIsInstance(rhs_any_of_formula_node, AndFormula)
        self.assertIs(rhs_any_of_formula_node.source, rhs_any_of_formula.rhs.root)
        self.assertEqual(rhs_any_of_formula_node.applicator_kind, "anyOf")
        self.assertEqual(rhs_any_of_formula_node.polarity, "negative")
        self.assertIs(
            rhs_any_of_formula_node.applicator,
            rhs_any_of_formula.rhs.root.applicators[0],
        )
        rhs_any_of_nnf = applicator_nnf_fragments(rhs_any_of_formula)[0]
        self.assertIs(rhs_any_of_nnf.source.formula_node, rhs_any_of_formula_node)
        self.assertEqual(rhs_any_of_nnf.operator, "allOf")
        self.assertEqual(rhs_any_of_nnf.proof_class, "bounded_witness")
        self.assertEqual(rhs_any_of_nnf.branch_product_count, 2)
        self.assertEqual(
            rhs_any_of_nnf.branch_budget_exhausted_reason,
            "branch expansion exceeded proof work budget",
        )
        self.assertEqual(
            applicator_branch_expansion_budget(rhs_any_of_nnf).product_count, 2
        )
        self.assertTrue(
            all(child.polarity == "negative" for child in rhs_any_of_nnf.children)
        )
        self.assertIn("negative anyOf normalizes", rhs_any_of_nnf.reason)
        rhs_any_of_product_plan = right_negative_any_of_branch_product_plan(
            rhs_any_of_nnf,
            lhs_schema=rhs_any_of_formula.lhs.schema,
        )
        self.assertTrue(rhs_any_of_product_plan.is_supported)
        self.assertEqual(len(rhs_any_of_product_plan.products), 2)

        rhs_one_of_formula = DifferenceFormula.from_schemas(
            {"type": "string"},
            {"oneOf": [{"type": "number"}, {"type": "string"}]},
            Dialect.DRAFT7,
        )
        rhs_one_of_formula_node = rhs_one_of_formula.negative_rhs.formula
        self.assertIsInstance(rhs_one_of_formula_node, ExactlyOneFormula)
        self.assertIs(rhs_one_of_formula_node.source, rhs_one_of_formula.rhs.root)
        self.assertEqual(rhs_one_of_formula_node.applicator_kind, "oneOf")
        self.assertEqual(rhs_one_of_formula_node.polarity, "negative")
        self.assertIs(
            rhs_one_of_formula_node.applicator,
            rhs_one_of_formula.rhs.root.applicators[0],
        )
        rhs_one_of_nnf = applicator_nnf_fragments(rhs_one_of_formula)[0]
        self.assertEqual(rhs_one_of_nnf.operator, "unsupported")
        self.assertEqual(rhs_one_of_nnf.proof_class, "unsupported")
        self.assertIn("branch-cardinality", rhs_one_of_nnf.reason)
        unsupported_nnf_product_plan = right_negative_any_of_branch_product_plan(
            rhs_one_of_nnf,
            lhs_schema=rhs_one_of_formula.lhs.schema,
        )
        self.assertFalse(unsupported_nnf_product_plan.is_supported)
        self.assertEqual(
            unsupported_nnf_product_plan.unsupported_reason, rhs_one_of_nnf.reason
        )
        rhs_one_of_plan = applicator_difference_plans(rhs_one_of_formula)[0]
        self.assertIsInstance(rhs_one_of_plan, ApplicatorOneOfCardinalityPlan)
        self.assertIs(rhs_one_of_plan.formula.formula_node, rhs_one_of_formula_node)
        self.assertEqual(rhs_one_of_plan.strategy, "right-oneof-cardinality-exact")
        self.assertEqual(rhs_one_of_plan.proof_class, "exact")
        self.assertEqual(rhs_one_of_plan.coverage_product_count, 2)
        self.assertEqual(rhs_one_of_plan.disjointness_product_count, 1)
        self.assertEqual(
            rhs_one_of_plan.coverage_budget_exhausted_reason,
            "branch expansion exceeded proof work budget",
        )
        self.assertEqual(
            rhs_one_of_plan.disjointness_budget_exhausted_reason,
            "branch expansion exceeded proof work budget",
        )
        self.assertEqual(
            one_of_coverage_expansion_budget(rhs_one_of_plan).product_count, 2
        )
        self.assertEqual(
            one_of_disjointness_expansion_budget(rhs_one_of_plan).product_count, 1
        )
        self.assertEqual(
            one_of_coverage_expansion_budget(rhs_one_of_plan).exhausted_reason_for(
                current_expansions=1,
                max_work=2,
            ),
            rhs_one_of_plan.coverage_budget_exhausted_reason,
        )
        rhs_one_of_products = one_of_cardinality_products(
            rhs_one_of_plan,
            lhs_schema=rhs_one_of_formula.lhs.schema,
        )
        self.assertEqual([product.index for product in rhs_one_of_products], [0, 1])
        self.assertEqual(rhs_one_of_products[0].lhs_schema, {"type": "string"})
        self.assertEqual(rhs_one_of_products[0].branch_schema, {"type": "number"})
        self.assertEqual(
            rhs_one_of_products[0].witness_rejected_reason,
            "SAT right-oneOf branch witness was rejected",
        )
        rhs_one_of_overlap_selection = one_of_covering_selection(
            rhs_one_of_plan,
            lhs_schema=rhs_one_of_formula.lhs.schema,
            covering_indexes=(0, 1),
        )
        self.assertIsInstance(
            rhs_one_of_overlap_selection, ApplicatorOneOfCoveringSelection
        )
        self.assertFalse(rhs_one_of_overlap_selection.is_selected)
        self.assertIsInstance(
            rhs_one_of_overlap_selection.overlap_product, ApplicatorOneOfOverlapProduct
        )
        self.assertEqual(
            rhs_one_of_overlap_selection.unsupported_reason,
            "SAT right-oneOf proof could not establish exactly one covering branch",
        )
        rhs_one_of_selected = one_of_covering_selection(
            rhs_one_of_plan,
            lhs_schema=rhs_one_of_formula.lhs.schema,
            covering_indexes=(0,),
        )
        self.assertTrue(rhs_one_of_selected.is_selected)
        self.assertEqual(rhs_one_of_selected.covered_index, 0)
        self.assertIsNone(rhs_one_of_selected.overlap_product)
        rhs_one_of_incomplete = one_of_covering_selection(
            rhs_one_of_plan,
            lhs_schema=rhs_one_of_formula.lhs.schema,
            covering_indexes=(),
        )
        self.assertFalse(rhs_one_of_incomplete.is_selected)
        self.assertIsNone(rhs_one_of_incomplete.overlap_product)

        lhs_not_formula = DifferenceFormula.from_schemas(
            {"not": {"type": "string"}},
            {"type": "number"},
            Dialect.DRAFT7,
        )
        lhs_not_formula_node = lhs_not_formula.positive_lhs.formula
        self.assertIsInstance(lhs_not_formula_node, AndFormula)
        lhs_not_wrapper = next(
            child
            for child in lhs_not_formula_node.children
            if isinstance(child, NotFormula) and child.applicator_kind == "not"
        )
        self.assertIs(lhs_not_wrapper.source, lhs_not_formula.lhs.root)
        self.assertEqual(lhs_not_wrapper.polarity, "positive")
        self.assertIs(
            lhs_not_wrapper.applicator, lhs_not_formula.lhs.root.applicators[0]
        )
        self.assertIsInstance(lhs_not_wrapper.child, AndFormula)
        self.assertEqual(applicator_difference_plans(lhs_not_formula), ())

        lhs_conditional_formula = DifferenceFormula.from_schemas(
            {"if": {"type": "string"}, "then": {"minLength": 1}, "else": False},
            {"type": "string"},
            Dialect.DRAFT7,
        )
        lhs_conditional_formula_node = lhs_conditional_formula.positive_lhs.formula
        self.assertIsInstance(lhs_conditional_formula_node, GuardedFormula)
        self.assertIs(
            lhs_conditional_formula_node.source, lhs_conditional_formula.lhs.root
        )
        self.assertEqual(lhs_conditional_formula_node.applicator_kind, "if")
        self.assertEqual(lhs_conditional_formula_node.polarity, "positive")
        self.assertIs(
            lhs_conditional_formula_node.applicator,
            lhs_conditional_formula.lhs.root.applicators[0],
        )
        self.assertIs(
            lhs_conditional_formula_node.condition_node,
            lhs_conditional_formula.lhs.root.applicators[0].children[0],
        )
        self.assertIs(
            lhs_conditional_formula_node.then_node,
            lhs_conditional_formula.lhs.root.applicators[1].children[0],
        )
        self.assertIs(
            lhs_conditional_formula_node.else_node,
            lhs_conditional_formula.lhs.root.applicators[2].children[0],
        )
        lhs_conditional_plan = applicator_difference_plans(lhs_conditional_formula)[0]
        self.assertIsInstance(lhs_conditional_plan, ApplicatorConditionalPlan)
        self.assertIs(lhs_conditional_plan.formula_node, lhs_conditional_formula_node)
        self.assertEqual(lhs_conditional_plan.side, "lhs")
        self.assertEqual(lhs_conditional_plan.polarity, "positive")
        self.assertEqual(lhs_conditional_plan.proof_class, "exact")
        self.assertEqual(lhs_conditional_plan.strategy, "conditional-guarded-exact")
        self.assertEqual(lhs_conditional_plan.branch_product_count, 2)
        self.assertEqual(
            [branch.kind for branch in lhs_conditional_plan.branches],
            ["if-true", "if-false"],
        )
        self.assertEqual(
            lhs_conditional_plan.branches[0].condition.polarity, "positive"
        )
        self.assertEqual(
            lhs_conditional_plan.branches[0].consequence.polarity, "positive"
        )
        self.assertEqual(
            lhs_conditional_plan.branches[1].condition.polarity, "negative"
        )
        self.assertEqual(
            lhs_conditional_plan.branches[1].consequence.polarity, "positive"
        )
        lhs_conditional_products = conditional_branch_products(
            lhs_conditional_plan,
            lhs_schema=lhs_conditional_formula.lhs.schema,
            rhs_schema=lhs_conditional_formula.rhs.schema,
        )
        self.assertEqual(
            lhs_conditional_products[0].lhs_schema,
            {"allOf": [{"type": "string"}, {"minLength": 1}]},
        )
        self.assertEqual(lhs_conditional_products[0].rhs_schema, {"type": "string"})
        self.assertIsNone(lhs_conditional_products[0].covering_schema)
        self.assertEqual(lhs_conditional_products[1].lhs_schema, False)
        self.assertIsNone(lhs_conditional_products[1].covering_schema)

    def test_difference_formula_owns_unsupported_diagnostics(self):
        formula = DifferenceFormula.from_schemas(
            {"type": "object", "unevaluatedProperties": False},
            {"$dynamicRef": "#node"},
            Dialect.DRAFT202012,
        )

        diagnostics = formula.unsupported_diagnostics

        self.assertEqual(len(diagnostics), 2)
        self.assertEqual(diagnostics[0].side, "lhs")
        self.assertEqual(diagnostics[0].keyword, "unevaluatedProperties")
        self.assertEqual(diagnostics[0].pointer, "#/unevaluatedProperties")
        self.assertEqual(diagnostics[0].category, "evaluation-frontier")
        self.assertEqual(diagnostics[1].side, "rhs")
        self.assertEqual(diagnostics[1].keyword, "$dynamicRef")
        self.assertEqual(diagnostics[1].pointer, "#/$dynamicRef")
        self.assertEqual(diagnostics[1].category, "dynamic-reference")
        self.assertIn("lhs #/unevaluatedProperties", formula.unsupported_reason)
        self.assertIn("rhs #/$dynamicRef", formula.unsupported_reason)

        proof = EmptinessSolver(
            ProofContext(Dialect.DRAFT202012)
        ).prove_formula_difference_empty(formula)
        self.assertEqual(proof.status, "unsupported")
        self.assertEqual(proof.diagnostics[0].side, "rhs")
        self.assertEqual(proof.diagnostics[0].keyword, "$dynamicRef")
        self.assertEqual(proof.diagnostics[0].category, "dynamic-reference")

    def test_sat_emptiness_solver_lives_in_kernel_package(self):
        formula = DifferenceFormula.from_schemas(
            {"type": "integer"}, {"type": "number"}, Dialect.DRAFT7
        )

        self.assertEqual(DifferenceFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(FormulaOccurrence.__module__, "subschema.kernel.formulas")
        self.assertEqual(DifferenceProblem.__module__, "subschema.kernel.sat")
        self.assertEqual(EmptinessSolver.__module__, "subschema.kernel.sat")
        self.assertEqual(SymbolicSolver.__module__, "subschema.kernel.symbolic")
        self.assertEqual(WitnessBuildResult.__module__, "subschema.kernel.witnesses")
        self.assertEqual(build_schema_witness.__module__, "subschema.kernel.witnesses")
        self.assertEqual(formula.positive_lhs.side, "lhs")
        self.assertEqual(formula.positive_lhs.polarity, "positive")
        self.assertIs(formula.positive_lhs.ir, formula.lhs)
        self.assertEqual(formula.negative_rhs.side, "rhs")
        self.assertEqual(formula.negative_rhs.polarity, "negative")
        self.assertIs(formula.negative_rhs.ir, formula.rhs)
        self.assertEqual(
            formula.occurrences, (formula.positive_lhs, formula.negative_rhs)
        )
        self.assertEqual(
            ApplicatorBranchPlan.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(
            ApplicatorBranchProduct.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(
            ApplicatorConditionalBranch.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(
            ApplicatorConditionalPlan.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(
            ApplicatorConditionalProduct.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(
            ApplicatorFormulaFragment.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(ApplicatorNnfChild.__module__, "subschema.kernel.applicators")
        self.assertEqual(
            ApplicatorNnfBranchProduct.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(
            ApplicatorNnfFragment.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(
            ApplicatorOneOfBranchProduct.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(
            ApplicatorOneOfCardinalityPlan.__module__, "subschema.kernel.applicators"
        )
        self.assertEqual(UnsupportedDiagnostic.__module__, "subschema.kernel.contracts")
        self.assertEqual(ArrayDifferenceModel.__module__, "subschema.kernel.difference")
        self.assertEqual(
            ArrayContainsConstraint.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayContainsDifferencePlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayContainsItemProof.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayContainsMaxViolationPlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayContainsMinViolationPlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayDuplicateWitnessPlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayItemValueObligation.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayItemValuesDifferencePlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayLengthDifferencePlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayUnevaluatedItemObligation.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ArrayUnevaluatedItemsDifferencePlan.__module__,
            "subschema.kernel.difference",
        )
        self.assertEqual(
            ArrayUniquenessDifferencePlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(ArrayWitnessOverride.__module__, "subschema.kernel.difference")
        self.assertEqual(ArrayWitnessPlan.__module__, "subschema.kernel.difference")
        self.assertEqual(ArrayWitnessSkeleton.__module__, "subschema.kernel.difference")
        self.assertEqual(ArrayWitnessSlot.__module__, "subschema.kernel.difference")
        self.assertEqual(
            materialize_array_duplicate_witness_plan.__module__,
            "subschema.kernel.difference",
        )
        self.assertEqual(
            materialize_array_witness_plan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            materialize_array_witness_skeleton.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            materialize_object_key_value_witness_skeleton.__module__,
            "subschema.kernel.difference",
        )
        self.assertEqual(
            materialize_object_property_value_witness_skeleton.__module__,
            "subschema.kernel.difference",
        )
        self.assertEqual(
            ClosedObjectDifferencePlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ClosedObjectValueObligation.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ClosedObjectWitnessSkeleton.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ClosedObjectWitnessSlot.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectDifferenceModel.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectKeyValueDifferencePlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectKeyValueObligation.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(ObjectKeyValueShape.__module__, "subschema.kernel.difference")
        self.assertEqual(
            ObjectKeyValueWitnessSkeleton.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectKeyValueWitnessSlot.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectPropertyCountDifferencePlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectPropertyValueObligation.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectPropertyValuesDifferencePlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectPropertyValueWitnessSkeleton.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectPropertyValueWitnessSlot.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectPropertyNamesDifferencePlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectPropertyNamesRepairSkeleton.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectPropertyNamesRepairSlot.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectUnevaluatedPropertiesDifferencePlan.__module__,
            "subschema.kernel.difference",
        )
        self.assertEqual(
            ObjectUnevaluatedPropertyObligation.__module__,
            "subschema.kernel.difference",
        )
        self.assertEqual(
            ObjectPresenceProductPlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            ObjectPresenceWitnessPlan.__module__, "subschema.kernel.difference"
        )
        self.assertEqual(
            materialize_closed_object_witness_skeleton.__module__,
            "subschema.kernel.difference",
        )
        self.assertEqual(
            materialize_object_property_names_repair_skeleton.__module__,
            "subschema.kernel.difference",
        )
        self.assertEqual(AndFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(AssertionFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(BottomFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(
            EvaluationEffectFormula.__module__, "subschema.kernel.formulas"
        )
        self.assertEqual(ExactlyOneFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(GuardedFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(NotFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(OrFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(ReferenceFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(TopFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(UnsupportedFormula.__module__, "subschema.kernel.formulas")
        self.assertEqual(AssertionAtom.__module__, "subschema.kernel.ir")
        self.assertEqual(ApplicatorNode.__module__, "subschema.kernel.ir")
        self.assertEqual(DifferenceRuleSpec.__module__, "subschema.kernel.sat")
        self.assertEqual(DomainFacts.__module__, "subschema.kernel.ir")
        self.assertEqual(FiniteConstraint.__module__, "subschema.kernel.constraints")
        self.assertEqual(TypeConstraint.__module__, "subschema.kernel.constraints")
        self.assertEqual(NumericConstraint.__module__, "subschema.kernel.constraints")
        self.assertEqual(
            StringLengthConstraint.__module__, "subschema.kernel.constraints"
        )
        self.assertEqual(
            StringLanguageConstraint.__module__, "subschema.kernel.constraints"
        )
        self.assertEqual(
            ArrayLengthConstraint.__module__, "subschema.kernel.constraints"
        )
        self.assertEqual(
            ArrayUniquenessConstraint.__module__, "subschema.kernel.constraints"
        )
        self.assertEqual(
            ObjectPropertyCountConstraint.__module__, "subschema.kernel.constraints"
        )
        self.assertEqual(
            ObjectPropertyNamesConstraint.__module__, "subschema.kernel.constraints"
        )
        self.assertEqual(
            ObjectPropertyValuesConstraint.__module__, "subschema.kernel.constraints"
        )
        self.assertEqual(
            ObjectClosedPropertiesConstraint.__module__, "subschema.kernel.constraints"
        )
        self.assertEqual(EvaluationFrontier.__module__, "subschema.kernel.evaluation")
        self.assertEqual(EvaluationExpression.__module__, "subschema.kernel.evaluation")
        self.assertEqual(
            EvaluationExpressionOrigin.__module__, "subschema.kernel.evaluation"
        )
        self.assertEqual(
            EvaluationTraceExpression.__module__, "subschema.kernel.evaluation"
        )
        self.assertEqual(ConcreteEvaluator.__module__, "subschema.kernel.semantic")
        self.assertEqual(
            references_module.ReferenceFrame.__module__, "subschema.kernel.references"
        )
        self.assertEqual(
            references_module.DynamicScope.__module__, "subschema.kernel.references"
        )
        self.assertIn(
            "origins", inspect.getsource(evaluation_module.EvaluationExpression)
        )
        self.assertIn("cache_get", inspect.getsource(context_module.ProofContext))
        self.assertNotIn(
            "EvaluationExpression",
            inspect.getsource(context_module.ProofContext),
        )
        self.assertEqual(LogicalSchemaIR.__module__, "subschema.kernel.ir")
        self.assertEqual(SchemaIRCompiler.__module__, "subschema.kernel.ir")
        self.assertEqual(SchemaNode.__module__, "subschema.kernel.ir")
        self.assertEqual(UnsupportedNode.__module__, "subschema.kernel.ir")
        self.assertEqual(formula.lhs.__class__.__module__, "subschema.kernel.ir")
        self.assertEqual(
            formula.lhs.source.__class__.__module__, "subschema.kernel.references"
        )
        self.assertIsInstance(formula.lhs.type_constraint, TypeConstraint)
        self.assertIsInstance(formula.lhs.numeric_constraint, NumericConstraint)
        self.assertIsInstance(formula.lhs.assertion("type").value, TypeConstraint)
        self.assertIsInstance(formula.lhs.assertion("numeric").value, NumericConstraint)
        self.assertIsNotNone(formula.lhs.type_shape)
        self.assertIsNotNone(formula.lhs.numeric_shape)
        self.assertTrue(formula.lhs.assertions)
        array_length_formula = DifferenceFormula.from_schemas(
            {"type": "array", "minItems": 1},
            {"type": "array"},
            Dialect.DRAFT7,
        )
        self.assertIsInstance(
            array_length_formula.lhs.array_length_lhs_constraint, ArrayLengthConstraint
        )
        array_uniqueness_formula = DifferenceFormula.from_schemas(
            {"type": "array", "uniqueItems": True},
            {"type": "array"},
            Dialect.DRAFT7,
        )
        self.assertIsInstance(
            array_uniqueness_formula.lhs.array_uniqueness_lhs_constraint,
            ArrayUniquenessConstraint,
        )
        object_count_formula = DifferenceFormula.from_schemas(
            {"type": "object", "minProperties": 1},
            {"type": "object"},
            Dialect.DRAFT7,
        )
        self.assertIsInstance(
            object_count_formula.lhs.object_property_count_constraint,
            ObjectPropertyCountConstraint,
        )
        object_names_formula = DifferenceFormula.from_schemas(
            {"type": "object", "propertyNames": {"pattern": "^a"}},
            {"type": "object"},
            Dialect.DRAFT7,
        )
        self.assertIsInstance(
            object_names_formula.lhs.object_property_names_constraint,
            ObjectPropertyNamesConstraint,
        )
        object_values_formula = DifferenceFormula.from_schemas(
            {"type": "object", "properties": {"a": {"type": "integer"}}},
            {"type": "object"},
            Dialect.DRAFT7,
        )
        self.assertIsInstance(
            object_values_formula.lhs.object_property_values_constraint,
            ObjectPropertyValuesConstraint,
        )
        object_closed_formula = DifferenceFormula.from_schemas(
            {"type": "object", "additionalProperties": False},
            {"type": "object"},
            Dialect.DRAFT7,
        )
        self.assertIsInstance(
            object_closed_formula.lhs.object_closed_properties_constraint,
            ObjectClosedPropertiesConstraint,
        )
        tagged_formula = DifferenceFormula.from_schemas(
            {
                "type": "object",
                "required": ["kind"],
                "properties": {"kind": {"const": "cat"}},
            },
            {
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["kind"],
                        "properties": {"kind": {"const": "cat"}},
                    },
                    {
                        "type": "object",
                        "required": ["kind"],
                        "properties": {"kind": {"const": "dog"}},
                    },
                ]
            },
            Dialect.DRAFT202012,
        )
        self.assertIsInstance(tagged_formula.rhs.tagged_one_of, TaggedOneOf)
        self.assertEqual(tagged_formula.lhs.required_singleton_tag("kind"), "cat")
        rule_names = [rule.name for rule in difference_rules()]
        self.assertIn("numeric-domain-ir", rule_names)
        self.assertNotIn("applicator-domain-ir", rule_names)
        self.assertLess(
            rule_names.index("finite-domain-ir"),
            rule_names.index("static-reference-ir"),
        )
        self.assertLess(
            rule_names.index("static-reference-ir"),
            rule_names.index("dynamic-reference-ir"),
        )
        self.assertLess(
            rule_names.index("dynamic-reference-ir"),
            rule_names.index("finite-rhs-domain-ir"),
        )
        self.assertLess(
            rule_names.index("applicator-left-anyof-ir"),
            rule_names.index("applicator-left-oneof-ir"),
        )
        self.assertLess(
            rule_names.index("applicator-left-oneof-ir"),
            rule_names.index("applicator-left-allof-ir"),
        )
        self.assertLess(
            rule_names.index("applicator-left-allof-ir"),
            rule_names.index("applicator-right-not-ir"),
        )
        self.assertLess(
            rule_names.index("applicator-right-not-ir"),
            rule_names.index("applicator-right-anyof-ir"),
        )
        self.assertLess(
            rule_names.index("applicator-right-anyof-ir"),
            rule_names.index("applicator-right-oneof-ir"),
        )
        self.assertLess(
            rule_names.index("applicator-right-oneof-ir"),
            rule_names.index("applicator-right-allof-ir"),
        )
        self.assertLess(
            rule_names.index("applicator-right-allof-ir"),
            rule_names.index("applicator-conditional-ir"),
        )
        self.assertNotIn("array-difference-ir", rule_names)
        self.assertNotIn("object-difference-ir", rule_names)
        self.assertLess(
            rule_names.index("array-unevaluated-items-ir"),
            rule_names.index("array-length-ir"),
        )
        self.assertLess(
            rule_names.index("array-length-ir"), rule_names.index("array-uniqueness-ir")
        )
        self.assertLess(
            rule_names.index("array-uniqueness-ir"),
            rule_names.index("array-contains-ir"),
        )
        self.assertLess(
            rule_names.index("array-contains-ir"),
            rule_names.index("array-item-values-ir"),
        )
        self.assertLess(
            rule_names.index("object-unevaluated-properties-ir"),
            rule_names.index("object-property-count-ir"),
        )
        self.assertLess(
            rule_names.index("object-property-count-ir"),
            rule_names.index("object-presence-product-ir"),
        )
        self.assertLess(
            rule_names.index("object-presence-product-ir"),
            rule_names.index("object-property-values-ir"),
        )
        self.assertLess(
            rule_names.index("object-property-values-ir"),
            rule_names.index("object-key-value-ir"),
        )
        self.assertLess(
            rule_names.index("object-key-value-ir"),
            rule_names.index("object-property-names-ir"),
        )
        self.assertLess(
            rule_names.index("object-property-names-ir"),
            rule_names.index("object-closed-properties-ir"),
        )
        self.assertEqual(difference_rules()[-1].name, "object-closed-properties-ir")
        self.assertEqual(
            tuple(rule.spec for rule in difference_rules()), difference_rule_specs()
        )
        expected_domain_specs = {
            "static-reference-ir": (
                "static $ref",
                "exact",
                "validated",
                "simple_exact",
                "branch",
            ),
            "dynamic-reference-ir": (
                "$dynamicRef",
                "exact",
                "validated",
                "simple_exact",
                "branch",
            ),
            "array-unevaluated-items-ir": (
                "unevaluatedItems",
                "bounded_witness",
                "validated",
                "simple_exact",
                "domain",
            ),
            "array-length-ir": (
                "array length",
                "exact",
                "validated",
                "simple_exact",
                "domain",
            ),
            "array-uniqueness-ir": (
                "uniqueItems",
                "bounded_witness",
                "validated",
                "simple_exact",
                "domain",
            ),
            "array-contains-ir": (
                "contains",
                "bounded_witness",
                "validated",
                "simple_exact",
                "domain",
            ),
            "array-item-values-ir": (
                "item-value",
                "bounded_witness",
                "validated",
                "simple_exact",
                "domain",
            ),
            "object-unevaluated-properties-ir": (
                "unevaluatedProperties",
                "bounded_witness",
                "validated",
                "simple_exact",
                "domain",
            ),
            "object-property-count-ir": (
                "property-count",
                "exact",
                "validated",
                "simple_exact",
                "none",
            ),
            "object-presence-product-ir": (
                "presence products",
                "bounded_witness",
                "validated",
                "simple_exact",
                "domain",
            ),
            "object-property-values-ir": (
                "property-value",
                "bounded_witness",
                "validated",
                "simple_exact",
                "none",
            ),
            "object-key-value-ir": (
                "key/value",
                "bounded_witness",
                "validated",
                "simple_exact",
                "domain",
            ),
            "object-property-names-ir": (
                "propertyNames",
                "bounded_witness",
                "validated",
                "simple_exact",
                "domain",
            ),
            "object-closed-properties-ir": (
                "closed object",
                "bounded_witness",
                "validated",
                "simple_exact",
                "domain",
            ),
        }
        specs_by_name = {spec.name: spec for spec in difference_rule_specs()}
        for name, (
            fragment,
            completeness,
            witness_mode,
            proof_class,
            budget_use,
        ) in expected_domain_specs.items():
            with self.subTest(rule=name):
                spec = specs_by_name[name]
                self.assertIn(fragment, spec.fragment)
                self.assertEqual(spec.completeness, completeness)
                self.assertEqual(spec.witness_mode, witness_mode)
                self.assertEqual(spec.proof_class, proof_class)
                self.assertEqual(spec.budget_use, budget_use)
        for spec in difference_rule_specs():
            self.assertTrue(spec.fragment)
            self.assertIn(
                spec.completeness, {"bounded_witness", "exact", "unsupported_boundary"}
            )
            self.assertIn(spec.witness_mode, {"none", "validated"})
            self.assertIn(
                spec.proof_class,
                {"simple_exact", "endeavor_expensive", "unsupported_unreliable"},
            )
            self.assertIn(spec.budget_use, {"branch", "domain", "none"})
        self.assertNotIn("bounded-witness-search", specs_by_name)
        self.assertEqual(
            {spec.name: spec.completeness for spec in difference_rule_specs()}[
                "type-domain-ir"
            ],
            "exact",
        )
        self.assertEqual(
            {spec.name: spec.completeness for spec in difference_rule_specs()}[
                "applicator-left-anyof-ir"
            ],
            "exact",
        )
        self.assertEqual(
            {spec.name: spec.completeness for spec in difference_rule_specs()}[
                "applicator-right-anyof-ir"
            ],
            "bounded_witness",
        )
        self.assertEqual(
            {spec.name: spec.completeness for spec in difference_rule_specs()}[
                "applicator-right-oneof-ir"
            ],
            "exact",
        )
        self.assertEqual(
            {spec.name: spec.budget_use for spec in difference_rule_specs()}[
                "applicator-conditional-ir"
            ],
            "branch",
        )
        self.assertLessEqual(
            {spec.witness_mode for spec in difference_rule_specs()},
            {"none", "validated"},
        )
        self.assertEqual(
            {spec.name: spec.budget_use for spec in difference_rule_specs()}[
                "array-contains-ir"
            ],
            "domain",
        )
        self.assertEqual(
            {spec.name: spec.completeness for spec in difference_rule_specs()}[
                "object-property-count-ir"
            ],
            "exact",
        )
        applicator_formula = DifferenceFormula.from_schemas(
            {"anyOf": [{"type": "string"}]},
            {"type": "string"},
            Dialect.DRAFT7,
        )
        applicator_plan_index = applicator_plan_set(applicator_formula)
        self.assertIsInstance(applicator_plan_index, ApplicatorPlanSet)

        applicator_plans = applicator_difference_plans(applicator_formula)
        self.assertEqual(applicator_plan_index.plans, applicator_plans)
        applicator_fragments = applicator_formula_fragments(applicator_formula)
        self.assertEqual(len(applicator_fragments), 1)
        self.assertEqual(applicator_fragments[0].side, "lhs")
        self.assertEqual(applicator_fragments[0].polarity, "positive")
        self.assertEqual(applicator_fragments[0].kind, "anyOf")
        applicator_root_formula = applicator_formula.positive_lhs.formula
        self.assertIsInstance(applicator_root_formula, AndFormula)
        applicator_formula_node = next(
            child
            for child in applicator_root_formula.children
            if isinstance(child, OrFormula) and child.applicator_kind == "anyOf"
        )
        self.assertIs(applicator_formula_node.source, applicator_formula.lhs.root)
        self.assertEqual(applicator_formula_node.applicator_kind, "anyOf")
        self.assertEqual(applicator_formula_node.polarity, "positive")
        self.assertIs(
            applicator_formula_node.applicator, applicator_fragments[0].source
        )
        self.assertIs(applicator_fragments[0].formula_node, applicator_formula_node)
        applicator_nnf = applicator_nnf_fragments(applicator_formula)
        self.assertEqual(applicator_nnf[0].operator, "anyOf")
        self.assertEqual(applicator_nnf[0].proof_class, "exact")
        self.assertEqual(applicator_nnf[0].children[0].polarity, "positive")
        self.assertEqual(len(applicator_plans), 1)
        self.assertEqual(applicator_plans[0].formula, applicator_fragments[0])
        self.assertEqual(applicator_plans[0].nnf, applicator_nnf[0])
        self.assertEqual(applicator_plans[0].side, "lhs")
        self.assertEqual(applicator_plans[0].polarity, "positive")
        self.assertEqual(applicator_plans[0].kind, "anyOf")
        self.assertEqual(applicator_plans[0].proof_class, "exact")
        self.assertEqual(applicator_plans[0].strategy, "left-anyof-exact")
        self.assertIs(
            applicator_plan_index.branch_with_strategy("left-anyof-exact"),
            applicator_plan_index.plans[0],
        )
        self.assertEqual(
            applicator_plan_index.branch_with_strategy("left-anyof-exact"),
            applicator_plans[0],
        )
        self.assertIsNone(applicator_plan_index.one_of_cardinality())
        self.assertIsNone(applicator_plan_index.conditional())
        self.assertEqual(applicator_plans[0].branch_product_count, 1)
        self.assertEqual(
            applicator_plans[0].children[0].source.schema, {"type": "string"}
        )
        self.assertTrue(applicator_plans[0].formula.base_schema)
        applicator_products = applicator_branch_products(
            applicator_plans[0],
            lhs_schema=applicator_formula.lhs.schema,
            rhs_schema=applicator_formula.rhs.schema,
        )
        self.assertEqual(len(applicator_products), 1)
        self.assertIsInstance(applicator_products[0], ApplicatorBranchProduct)
        self.assertEqual(applicator_products[0].lhs_schema, {"type": "string"})
        self.assertEqual(applicator_products[0].rhs_schema, {"type": "string"})
        self.assertEqual(
            applicator_products[0].witness_missing_reason,
            "SAT left-anyOf branch witness could not be constructed",
        )
        self.assertEqual(
            applicator_products[0].witness_rejected_reason,
            "SAT left-anyOf branch witness was rejected",
        )
        self.assertIsNone(applicator_products[0].witness_unsupported_reason)
        mixed_lhs_any_of_formula = DifferenceFormula.from_schemas(
            {"type": "string", "anyOf": [{"maxLength": 3}, {"pattern": "^a"}]},
            {"type": "string"},
            Dialect.DRAFT7,
        )
        mixed_lhs_any_of_fragments = applicator_formula_fragments(
            mixed_lhs_any_of_formula
        )
        self.assertEqual(len(mixed_lhs_any_of_fragments), 1)
        self.assertEqual(mixed_lhs_any_of_fragments[0].side, "lhs")
        self.assertEqual(mixed_lhs_any_of_fragments[0].polarity, "positive")
        self.assertEqual(mixed_lhs_any_of_fragments[0].kind, "anyOf")
        self.assertEqual(mixed_lhs_any_of_fragments[0].base_schema, {"type": "string"})
        mixed_lhs_any_of_products = applicator_branch_products(
            applicator_difference_plans(mixed_lhs_any_of_formula)[0],
            lhs_schema=mixed_lhs_any_of_formula.lhs.schema,
            rhs_schema=mixed_lhs_any_of_formula.rhs.schema,
        )
        self.assertEqual(
            mixed_lhs_any_of_products[0].lhs_schema,
            {"allOf": [{"type": "string"}, {"maxLength": 3}]},
        )
        self.assertEqual(mixed_lhs_any_of_products[0].base_schema, {"type": "string"})
        self.assertEqual(
            left_branch_resolved_lhs_schema(
                mixed_lhs_any_of_products[0], {"pattern": "^a"}
            ),
            {"allOf": [{"type": "string"}, {"pattern": "^a"}]},
        )
        self.assertEqual(
            left_branch_resolved_lhs_schema(mixed_lhs_any_of_products[0], False), False
        )
        self.assertEqual(
            left_branch_resolved_lhs_schema(applicator_products[0], {"type": "number"}),
            {"type": "number"},
        )
        lhs_one_of_products = applicator_branch_products(
            applicator_difference_plans(
                DifferenceFormula.from_schemas(
                    {"oneOf": [{"type": "string"}, {"type": "number"}]},
                    {"type": "string"},
                    Dialect.DRAFT7,
                )
            )[0],
            lhs_schema={"oneOf": [{"type": "string"}, {"type": "number"}]},
            rhs_schema={"type": "string"},
        )
        self.assertEqual(
            lhs_one_of_products[0].witness_missing_reason,
            "SAT left-oneOf branch witness could not be constructed",
        )
        self.assertEqual(
            lhs_one_of_products[0].witness_rejected_reason,
            "SAT left-oneOf branch witness was rejected",
        )
        self.assertEqual(
            lhs_one_of_products[0].witness_unsupported_reason,
            "SAT left-oneOf branch counterexample is not necessarily in the oneOf result",
        )
        lhs_all_of_products = applicator_branch_products(
            applicator_difference_plans(
                DifferenceFormula.from_schemas(
                    {"allOf": [{"type": "string"}, {"minLength": 1}]},
                    {"type": "string"},
                    Dialect.DRAFT7,
                )
            )[0],
            lhs_schema={"allOf": [{"type": "string"}, {"minLength": 1}]},
            rhs_schema={"type": "string"},
        )
        self.assertEqual(
            lhs_all_of_products[0].witness_missing_reason,
            "SAT left-allOf branch witness could not be constructed",
        )
        self.assertEqual(
            lhs_all_of_products[0].witness_rejected_reason,
            "SAT left-allOf branch witness was rejected",
        )
        mixed_rhs_any_of_formula = DifferenceFormula.from_schemas(
            {"type": "string", "maxLength": 3},
            {"type": "string", "anyOf": [{"maxLength": 5}, {"pattern": "^a"}]},
            Dialect.DRAFT7,
        )
        mixed_rhs_any_of_fragments = applicator_formula_fragments(
            mixed_rhs_any_of_formula
        )
        self.assertEqual(len(mixed_rhs_any_of_fragments), 1)
        self.assertEqual(mixed_rhs_any_of_fragments[0].side, "rhs")
        self.assertEqual(mixed_rhs_any_of_fragments[0].polarity, "negative")
        self.assertEqual(mixed_rhs_any_of_fragments[0].kind, "anyOf")
        self.assertEqual(mixed_rhs_any_of_fragments[0].base_schema, {"type": "string"})
        mixed_rhs_any_of_formula_node = mixed_rhs_any_of_formula.negative_rhs.formula
        self.assertIsInstance(mixed_rhs_any_of_formula_node, NotFormula)
        self.assertIs(
            mixed_rhs_any_of_formula_node.source, mixed_rhs_any_of_formula.rhs.root
        )
        self.assertEqual(mixed_rhs_any_of_formula_node.applicator_kind, "anyOf")
        self.assertEqual(mixed_rhs_any_of_formula_node.polarity, "negative")
        self.assertIs(
            mixed_rhs_any_of_formula_node.applicator,
            mixed_rhs_any_of_fragments[0].source,
        )
        self.assertIs(
            mixed_rhs_any_of_fragments[0].formula_node, mixed_rhs_any_of_formula_node
        )
        self.assertEqual(
            applicator_difference_plans(mixed_rhs_any_of_formula)[0].strategy,
            "right-anyof-nnf-bounded",
        )
        mixed_rhs_any_of_base = applicator_base_product(
            applicator_difference_plans(mixed_rhs_any_of_formula)[0],
            lhs_schema=mixed_rhs_any_of_formula.lhs.schema,
        )
        self.assertIsInstance(mixed_rhs_any_of_base, ApplicatorBaseProduct)
        self.assertEqual(
            mixed_rhs_any_of_base.witness_missing_reason,
            "SAT right-anyOf base witness could not be constructed",
        )
        self.assertEqual(
            mixed_rhs_any_of_base.witness_rejected_reason,
            "SAT right-anyOf base witness was rejected",
        )
        mixed_rhs_all_of_formula = DifferenceFormula.from_schemas(
            {"type": "string"},
            {
                "type": "string",
                "definitions": {"name": {"type": "string"}},
                "allOf": [{"$ref": "#/definitions/name"}],
            },
            Dialect.DRAFT7,
        )
        mixed_rhs_all_of_fragments = applicator_formula_fragments(
            mixed_rhs_all_of_formula
        )
        self.assertEqual(len(mixed_rhs_all_of_fragments), 1)
        self.assertEqual(mixed_rhs_all_of_fragments[0].side, "rhs")
        self.assertEqual(mixed_rhs_all_of_fragments[0].polarity, "negative")
        self.assertEqual(mixed_rhs_all_of_fragments[0].kind, "allOf")
        self.assertEqual(
            mixed_rhs_all_of_fragments[0].base_schema,
            {"type": "string", "definitions": {"name": {"type": "string"}}},
        )
        mixed_rhs_all_of_formula_node = mixed_rhs_all_of_formula.negative_rhs.formula
        self.assertIsInstance(mixed_rhs_all_of_formula_node, NotFormula)
        self.assertEqual(mixed_rhs_all_of_formula_node.applicator_kind, "allOf")
        self.assertIs(
            mixed_rhs_all_of_formula_node.applicator,
            mixed_rhs_all_of_fragments[0].source,
        )
        self.assertIs(
            mixed_rhs_all_of_fragments[0].formula_node, mixed_rhs_all_of_formula_node
        )
        self.assertEqual(
            applicator_difference_plans(mixed_rhs_all_of_formula)[0].strategy,
            "right-allof-nnf-exact",
        )
        mixed_rhs_all_of_base = applicator_base_product(
            applicator_difference_plans(mixed_rhs_all_of_formula)[0],
            lhs_schema=mixed_rhs_all_of_formula.lhs.schema,
        )
        self.assertIsInstance(mixed_rhs_all_of_base, ApplicatorBaseProduct)
        self.assertEqual(
            mixed_rhs_all_of_base.witness_missing_reason,
            "SAT right-allOf base witness could not be constructed",
        )
        self.assertEqual(
            mixed_rhs_all_of_base.witness_rejected_reason,
            "SAT right-allOf base witness was rejected",
        )
        hard_keyword_formula = DifferenceFormula.from_schemas(
            {"type": "array"},
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "allOf": [{"prefixItems": [{"type": "integer"}]}],
                "unevaluatedItems": False,
            },
            Dialect.DRAFT202012,
        )
        self.assertEqual(applicator_formula_fragments(hard_keyword_formula), ())
        lhs_hard_keyword_formula = DifferenceFormula.from_schemas(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "anyOf": [{"type": "array"}],
                "unevaluatedItems": False,
            },
            {"type": "array"},
            Dialect.DRAFT202012,
        )
        self.assertEqual(applicator_formula_fragments(lhs_hard_keyword_formula), ())
        rhs_not_formula = DifferenceFormula.from_schemas(
            {"type": "string"},
            {"not": {"type": "number"}},
            Dialect.DRAFT7,
        )
        rhs_not_plans = applicator_difference_plans(rhs_not_formula)
        rhs_not_fragments = applicator_formula_fragments(rhs_not_formula)
        rhs_not_formula_node = rhs_not_formula.negative_rhs.formula
        self.assertIsInstance(rhs_not_formula_node, AndFormula)
        self.assertEqual(rhs_not_formula_node.applicator_kind, "not")
        self.assertIs(rhs_not_formula_node.applicator, rhs_not_fragments[0].source)
        self.assertIs(rhs_not_fragments[0].formula_node, rhs_not_formula_node)
        self.assertEqual(rhs_not_fragments[0].polarity, "negative")
        rhs_not_nnf = applicator_nnf_fragments(rhs_not_formula)
        self.assertEqual(rhs_not_nnf[0].operator, "schema")
        self.assertEqual(rhs_not_nnf[0].proof_class, "exact")
        self.assertEqual(rhs_not_nnf[0].branch_product_count, 1)
        self.assertEqual(rhs_not_nnf[0].children[0].polarity, "positive")
        self.assertEqual(
            rhs_not_nnf[0].children[0].node.source.schema, {"type": "number"}
        )
        rhs_not_product = applicator_nnf_schema_product(
            rhs_not_nnf[0],
            lhs_schema=rhs_not_formula.lhs.schema,
        )
        self.assertIsInstance(rhs_not_product, ApplicatorNnfSchemaProduct)
        self.assertEqual(rhs_not_product.lhs_schema, {"type": "string"})
        self.assertEqual(rhs_not_product.rhs_schema, {"type": "number"})
        self.assertIsInstance(
            rhs_not_product.rhs_string_language_constraint, StringLanguageConstraint
        )
        self.assertEqual(
            rhs_not_product.witness_missing_reason,
            "SAT right-not witness could not be constructed",
        )
        self.assertEqual(
            rhs_not_product.witness_rejected_reason,
            "SAT right-not witness was rejected",
        )
        self.assertEqual(
            rhs_not_product.complement_witness_missing_reason,
            "SAT right-not complement witness could not be constructed",
        )
        self.assertEqual(
            rhs_not_product.complement_witness_rejected_reason,
            "SAT right-not complement witness was rejected",
        )
        rhs_not_witness = right_not_witness_plan(rhs_not_product, Dialect.DRAFT7)
        self.assertTrue(rhs_not_witness.has_witness)
        self.assertEqual(rhs_not_witness.witness, "")
        rhs_not_complement = right_not_complement_schema(
            rhs_not_product, rhs_not_product.rhs_schema
        )
        self.assertEqual(rhs_not_complement, {"not": {"type": "number"}})
        self.assertFalse(
            right_not_complement_needs_subproof(
                rhs_not_product,
                rhs_not_complement,
                original_lhs_schema=rhs_not_formula.lhs.schema,
                original_rhs_schema=rhs_not_formula.rhs.schema,
            )
        )
        self.assertEqual(rhs_not_plans[0].side, "rhs")
        self.assertEqual(rhs_not_plans[0].polarity, "negative")
        self.assertEqual(rhs_not_plans[0].kind, "not")
        self.assertEqual(rhs_not_plans[0].proof_class, "bounded_witness")
        self.assertEqual(rhs_not_plans[0].strategy, "right-not-nnf")
        self.assertEqual(rhs_not_plans[0].nnf, rhs_not_nnf[0])
        rhs_not_overlap_plan = right_not_string_overlap_plan(
            rhs_not_formula.lhs,
            rhs_not_nnf[0].children[0].node,
            Dialect.DRAFT7,
        )
        self.assertIsInstance(rhs_not_overlap_plan, RightNotStringOverlapPlan)
        self.assertEqual(rhs_not_overlap_plan.status, "unsupported")
        mixed_rhs_not_formula = DifferenceFormula.from_schemas(
            {"const": "b"},
            {
                "type": "string",
                "definitions": {"bad": {"const": "a"}},
                "not": {"$ref": "#/definitions/bad"},
            },
            Dialect.DRAFT7,
        )
        mixed_rhs_not_plan = applicator_difference_plans(mixed_rhs_not_formula)[0]
        self.assertEqual(
            mixed_rhs_not_plan.formula.base_schema,
            {"type": "string", "definitions": {"bad": {"const": "a"}}},
        )
        self.assertIsInstance(mixed_rhs_not_plan.formula.formula_node, NotFormula)
        self.assertEqual(mixed_rhs_not_plan.formula.formula_node.applicator_kind, "not")
        self.assertIs(
            mixed_rhs_not_plan.formula.formula_node.applicator,
            mixed_rhs_not_plan.source,
        )
        mixed_rhs_not_base = applicator_base_product(
            mixed_rhs_not_plan,
            lhs_schema=mixed_rhs_not_formula.lhs.schema,
        )
        self.assertIsInstance(mixed_rhs_not_base, ApplicatorBaseProduct)
        self.assertEqual(mixed_rhs_not_base.lhs_schema, {"const": "b"})
        self.assertEqual(
            mixed_rhs_not_base.rhs_schema,
            {"type": "string", "definitions": {"bad": {"const": "a"}}},
        )
        self.assertEqual(
            mixed_rhs_not_base.witness_missing_reason,
            "SAT right-not base witness could not be constructed",
        )
        self.assertEqual(
            mixed_rhs_not_base.witness_rejected_reason,
            "SAT right-not base witness was rejected",
        )
        mixed_rhs_not_product = applicator_nnf_schema_product(
            mixed_rhs_not_plan.nnf,
            lhs_schema=mixed_rhs_not_formula.lhs.schema,
        )
        self.assertEqual(
            mixed_rhs_not_product.lhs_schema,
            {
                "allOf": [
                    {"const": "b"},
                    {"type": "string", "definitions": {"bad": {"const": "a"}}},
                ]
            },
        )
        self.assertEqual(
            mixed_rhs_not_product.rhs_schema, {"$ref": "#/definitions/bad"}
        )
        self.assertEqual(
            right_not_resolved_rhs_schema(mixed_rhs_not_product, {"const": "a"}),
            {"const": "a"},
        )
        self.assertEqual(
            right_not_resolved_rhs_schema(mixed_rhs_not_product, None),
            {"$ref": "#/definitions/bad"},
        )
        mixed_rhs_not_complement = right_not_complement_schema(
            mixed_rhs_not_product, {"const": "a"}
        )
        self.assertTrue(
            right_not_complement_needs_subproof(
                mixed_rhs_not_product,
                mixed_rhs_not_complement,
                original_lhs_schema=mixed_rhs_not_formula.lhs.schema,
                original_rhs_schema=mixed_rhs_not_formula.rhs.schema,
            )
        )
        hard_keyword_not_formula = DifferenceFormula.from_schemas(
            {"type": "object"},
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "not": {"required": ["blocked"]},
                "unevaluatedProperties": False,
            },
            Dialect.DRAFT202012,
        )
        self.assertEqual(applicator_difference_plans(hard_keyword_not_formula), ())
        rhs_any_of_formula = DifferenceFormula.from_schemas(
            {"type": "string"},
            {"anyOf": [{"type": "number"}, {"type": "string"}]},
            Dialect.DRAFT7,
        )
        rhs_any_of_nnf = applicator_nnf_fragments(rhs_any_of_formula)
        self.assertEqual(rhs_any_of_nnf[0].operator, "allOf")
        self.assertEqual(rhs_any_of_nnf[0].proof_class, "bounded_witness")
        self.assertTrue(
            all(child.polarity == "negative" for child in rhs_any_of_nnf[0].children)
        )
        rhs_any_of_products = applicator_nnf_branch_products(
            rhs_any_of_nnf[0],
            lhs_schema=rhs_any_of_formula.lhs.schema,
        )
        self.assertEqual(len(rhs_any_of_products), 2)
        self.assertIsInstance(rhs_any_of_products[0], ApplicatorNnfBranchProduct)
        self.assertEqual(rhs_any_of_products[0].lhs_schema, {"type": "string"})
        self.assertEqual(rhs_any_of_products[0].rhs_schema, {"type": "number"})
        self.assertEqual(
            rhs_any_of_products[0].witness_missing_reason,
            "SAT right-anyOf branch witness could not be constructed",
        )
        self.assertEqual(
            rhs_any_of_products[0].witness_rejected_reason,
            "SAT right-anyOf branch witness was rejected",
        )
        self.assertEqual(
            right_nnf_branch_resolved_rhs_schema(rhs_any_of_products[0], {"const": 1}),
            {"const": 1},
        )
        self.assertEqual(
            right_nnf_branch_resolved_rhs_schema(rhs_any_of_products[0], None),
            {"type": "number"},
        )
        rhs_one_of_formula = DifferenceFormula.from_schemas(
            {"type": "object"},
            {"oneOf": [{"type": "object"}, {"type": "array"}]},
            Dialect.DRAFT7,
        )
        rhs_one_of_plan = applicator_difference_plans(rhs_one_of_formula)[0]
        self.assertIsInstance(rhs_one_of_plan, ApplicatorOneOfCardinalityPlan)
        self.assertEqual(rhs_one_of_plan.side, "rhs")
        self.assertEqual(rhs_one_of_plan.polarity, "negative")
        self.assertEqual(rhs_one_of_plan.kind, "oneOf")
        self.assertIs(
            rhs_one_of_formula.negative_rhs.formula.applicator, rhs_one_of_plan.source
        )
        self.assertEqual(rhs_one_of_plan.strategy, "right-oneof-cardinality-exact")
        rhs_one_of_products = one_of_cardinality_products(
            rhs_one_of_plan,
            lhs_schema=rhs_one_of_formula.lhs.schema,
        )
        self.assertTrue(
            all(
                isinstance(product, ApplicatorOneOfBranchProduct)
                for product in rhs_one_of_products
            )
        )
        self.assertEqual(rhs_one_of_products[1].branch_schema, {"type": "array"})
        self.assertEqual(
            one_of_branch_resolved_schema(rhs_one_of_products[1], {"type": "integer"}),
            {"type": "integer"},
        )
        self.assertEqual(
            one_of_branch_resolved_schema(rhs_one_of_products[1], None),
            {"type": "array"},
        )
        rhs_one_of_overlap_product = one_of_overlap_product(
            rhs_one_of_plan,
            lhs_schema=rhs_one_of_formula.lhs.schema,
            covering_indexes=(0, 1),
        )
        self.assertIsInstance(rhs_one_of_overlap_product, ApplicatorOneOfOverlapProduct)
        self.assertEqual(rhs_one_of_overlap_product.lhs_schema, {"type": "object"})
        self.assertEqual(rhs_one_of_overlap_product.covering_indexes, (0, 1))
        self.assertEqual(
            rhs_one_of_overlap_product.witness_missing_reason,
            "SAT right-oneOf overlap witness could not be constructed",
        )
        self.assertEqual(
            rhs_one_of_overlap_product.witness_rejected_reason,
            "SAT right-oneOf overlap witness was rejected",
        )
        rhs_one_of_overlap_witness = one_of_overlap_witness_plan(
            rhs_one_of_overlap_product, Dialect.DRAFT7
        )
        self.assertTrue(rhs_one_of_overlap_witness.has_witness)
        self.assertEqual(rhs_one_of_overlap_witness.witness, {})
        rhs_one_of_disjointness_products = one_of_disjointness_products(
            rhs_one_of_plan,
            lhs_schema=rhs_one_of_formula.lhs.schema,
            covered_index=0,
        )
        self.assertEqual(len(rhs_one_of_disjointness_products), 1)
        self.assertIsInstance(
            rhs_one_of_disjointness_products[0], ApplicatorOneOfDisjointnessProduct
        )
        self.assertEqual(rhs_one_of_disjointness_products[0].covered_index, 0)
        self.assertEqual(rhs_one_of_disjointness_products[0].index, 1)
        self.assertEqual(
            rhs_one_of_disjointness_products[0].lhs_schema, {"type": "object"}
        )
        self.assertEqual(
            rhs_one_of_disjointness_products[0].branch_schema, {"type": "array"}
        )
        self.assertEqual(
            rhs_one_of_disjointness_products[0].witness_missing_reason,
            "SAT right-oneOf disjointness witness could not be constructed",
        )
        self.assertEqual(
            rhs_one_of_disjointness_products[0].witness_rejected_reason,
            "SAT right-oneOf overlap witness was rejected",
        )
        self.assertEqual(
            one_of_disjointness_complement_schema(
                rhs_one_of_disjointness_products[0],
                rhs_one_of_disjointness_products[0].branch_schema,
            ),
            {"not": {"type": "array"}},
        )
        self.assertEqual(
            one_of_disjointness_resolved_branch_schema(
                rhs_one_of_disjointness_products[0],
                {"type": "integer"},
            ),
            {"type": "integer"},
        )
        self.assertEqual(
            one_of_disjointness_resolved_branch_schema(
                rhs_one_of_disjointness_products[0], None
            ),
            {"type": "array"},
        )
        mixed_rhs_one_of_formula = DifferenceFormula.from_schemas(
            {"type": "string", "minLength": 1},
            {"type": "string", "oneOf": [{"minLength": 1}, {"maxLength": 0}]},
            Dialect.DRAFT7,
        )
        mixed_rhs_one_of_plan = applicator_difference_plans(mixed_rhs_one_of_formula)[0]
        self.assertIsInstance(mixed_rhs_one_of_plan, ApplicatorOneOfCardinalityPlan)
        self.assertEqual(mixed_rhs_one_of_plan.formula.base_schema, {"type": "string"})
        self.assertIsInstance(mixed_rhs_one_of_plan.formula.formula_node, NotFormula)
        self.assertEqual(
            mixed_rhs_one_of_plan.formula.formula_node.applicator_kind, "oneOf"
        )
        self.assertIs(
            mixed_rhs_one_of_plan.formula.formula_node.applicator,
            mixed_rhs_one_of_plan.source,
        )
        mixed_rhs_one_of_base = applicator_base_product(
            mixed_rhs_one_of_plan,
            lhs_schema=mixed_rhs_one_of_formula.lhs.schema,
        )
        self.assertIsInstance(mixed_rhs_one_of_base, ApplicatorBaseProduct)
        self.assertEqual(
            mixed_rhs_one_of_base.lhs_schema, {"type": "string", "minLength": 1}
        )
        self.assertEqual(mixed_rhs_one_of_base.rhs_schema, {"type": "string"})
        self.assertEqual(
            mixed_rhs_one_of_base.witness_missing_reason,
            "SAT right-oneOf base witness could not be constructed",
        )
        self.assertEqual(
            mixed_rhs_one_of_base.witness_rejected_reason,
            "SAT right-oneOf base witness was rejected",
        )
        mixed_rhs_one_of_products = one_of_cardinality_products(
            mixed_rhs_one_of_plan,
            lhs_schema=mixed_rhs_one_of_formula.lhs.schema,
        )
        self.assertEqual(
            mixed_rhs_one_of_products[0].lhs_schema,
            {"allOf": [{"type": "string", "minLength": 1}, {"type": "string"}]},
        )
        mixed_rhs_one_of_overlap = one_of_overlap_product(
            mixed_rhs_one_of_plan,
            lhs_schema=mixed_rhs_one_of_formula.lhs.schema,
            covering_indexes=(0, 1),
        )
        self.assertEqual(
            mixed_rhs_one_of_overlap.lhs_schema,
            {"allOf": [{"type": "string", "minLength": 1}, {"type": "string"}]},
        )
        mixed_rhs_one_of_disjointness = one_of_disjointness_products(
            mixed_rhs_one_of_plan,
            lhs_schema=mixed_rhs_one_of_formula.lhs.schema,
            covered_index=0,
        )
        self.assertEqual(
            mixed_rhs_one_of_disjointness[0].lhs_schema,
            {"allOf": [{"type": "string", "minLength": 1}, {"type": "string"}]},
        )
        hard_keyword_one_of_formula = DifferenceFormula.from_schemas(
            {"type": "array"},
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "oneOf": [{"type": "array"}, {"type": "object"}],
                "unevaluatedItems": False,
            },
            Dialect.DRAFT202012,
        )
        self.assertEqual(applicator_difference_plans(hard_keyword_one_of_formula), ())
        conditional_formula = DifferenceFormula.from_schemas(
            {"type": "string"},
            {"if": {"type": "string"}, "then": {"minLength": 1}, "else": False},
            Dialect.DRAFT7,
        )
        conditional_formula_node = conditional_formula.negative_rhs.formula
        self.assertIsInstance(conditional_formula_node, GuardedFormula)
        self.assertIs(conditional_formula_node.source, conditional_formula.rhs.root)
        self.assertEqual(conditional_formula_node.applicator_kind, "if")
        self.assertEqual(conditional_formula_node.polarity, "negative")
        self.assertIs(
            conditional_formula_node.applicator,
            conditional_formula.rhs.root.applicators[0],
        )
        conditional_plans = applicator_difference_plans(conditional_formula)
        self.assertIsInstance(conditional_plans[0], ApplicatorConditionalPlan)
        self.assertIs(conditional_plans[0].formula_node, conditional_formula_node)
        self.assertEqual(conditional_plans[0].side, "rhs")
        self.assertEqual(conditional_plans[0].polarity, "negative")
        self.assertEqual(conditional_plans[0].proof_class, "exact")
        self.assertEqual(conditional_plans[0].strategy, "conditional-guarded-exact")
        self.assertEqual(conditional_plans[0].branch_product_count, 2)
        self.assertEqual(
            conditional_plans[0].branch_budget_exhausted_reason,
            "branch expansion exceeded proof work budget",
        )
        self.assertEqual(
            applicator_branch_expansion_budget(conditional_plans[0]).product_count, 2
        )
        self.assertEqual(
            conditional_plans[0].if_child.source.schema, {"type": "string"}
        )
        self.assertEqual(
            conditional_plans[0].then_child.source.schema, {"minLength": 1}
        )
        self.assertEqual(conditional_plans[0].else_child.source.schema, False)
        self.assertIs(
            conditional_formula_node.condition_node, conditional_plans[0].if_child
        )
        self.assertIs(
            conditional_formula_node.then_node, conditional_plans[0].then_child
        )
        self.assertIs(
            conditional_formula_node.else_node, conditional_plans[0].else_child
        )
        self.assertEqual(
            [branch.kind for branch in conditional_plans[0].branches],
            ["if-true", "if-false"],
        )
        self.assertTrue(
            all(
                branch.proof_class == "exact"
                for branch in conditional_plans[0].branches
            )
        )
        self.assertEqual(
            conditional_plans[0].branches[0].condition.polarity, "positive"
        )
        self.assertEqual(
            conditional_plans[0].branches[0].consequence.polarity, "negative"
        )
        self.assertEqual(
            conditional_plans[0].branches[1].condition.polarity, "negative"
        )
        self.assertEqual(
            conditional_plans[0].branches[1].consequence.polarity, "negative"
        )
        conditional_products = conditional_branch_products(
            conditional_plans[0],
            lhs_schema=conditional_formula.lhs.schema,
            rhs_schema=conditional_formula.rhs.schema,
        )
        self.assertEqual(len(conditional_products), 2)
        self.assertEqual(
            conditional_products[0].lhs_schema,
            {"allOf": [{"type": "string"}, {"type": "string"}]},
        )
        self.assertEqual(conditional_products[0].rhs_schema, {"minLength": 1})
        self.assertEqual(
            conditional_products[0].covering_schema, {"not": {"type": "string"}}
        )
        self.assertEqual(
            conditional_products[0].covering_lhs_schema, {"type": "string"}
        )
        self.assertFalse(conditional_products[0].is_trivially_empty_difference)
        self.assertEqual(
            conditional_products[0].witness_missing_reason,
            "SAT conditional branch witness could not be constructed",
        )
        self.assertEqual(
            conditional_products[0].witness_rejected_reason,
            "SAT conditional branch witness was rejected",
        )
        self.assertEqual(
            conditional_products[1].lhs_schema,
            {"allOf": [{"type": "string"}, {"not": {"type": "string"}}]},
        )
        self.assertEqual(conditional_products[1].rhs_schema, False)
        self.assertEqual(conditional_products[1].covering_schema, {"type": "string"})
        self.assertEqual(
            conditional_products[1].covering_lhs_schema, {"type": "string"}
        )
        self.assertFalse(conditional_products[1].is_trivially_empty_difference)
        self.assertTrue(
            ApplicatorConditionalProduct(
                "if-true",
                False,
                {"type": "string"},
                conditional_products[0].branch,
            ).is_trivially_empty_difference
        )
        self.assertTrue(
            ApplicatorConditionalProduct(
                "if-true",
                {"type": "string"},
                True,
                conditional_products[0].branch,
            ).is_trivially_empty_difference
        )
        mixed_lhs_conditional_formula = DifferenceFormula.from_schemas(
            {"type": "string", "if": {"type": "string"}, "then": {"minLength": 1}},
            {"type": "string"},
            Dialect.DRAFT7,
        )
        mixed_lhs_conditional_plan = applicator_difference_plans(
            mixed_lhs_conditional_formula
        )[0]
        self.assertIsInstance(mixed_lhs_conditional_plan, ApplicatorConditionalPlan)
        self.assertEqual(mixed_lhs_conditional_plan.base_schema, {"type": "string"})
        mixed_lhs_conditional_root = mixed_lhs_conditional_formula.positive_lhs.formula
        if isinstance(mixed_lhs_conditional_root, GuardedFormula):
            mixed_lhs_guarded = mixed_lhs_conditional_root
        else:
            self.assertIsInstance(mixed_lhs_conditional_root, AndFormula)
            mixed_lhs_guarded = next(
                child
                for child in mixed_lhs_conditional_root.children
                if isinstance(child, GuardedFormula)
            )
        self.assertIs(
            mixed_lhs_guarded.condition_node, mixed_lhs_conditional_plan.if_child
        )
        self.assertIs(
            mixed_lhs_guarded.then_node, mixed_lhs_conditional_plan.then_child
        )
        self.assertIs(mixed_lhs_conditional_plan.formula_node, mixed_lhs_guarded)
        mixed_lhs_conditional_products = conditional_branch_products(
            mixed_lhs_conditional_plan,
            lhs_schema=mixed_lhs_conditional_formula.lhs.schema,
            rhs_schema=mixed_lhs_conditional_formula.rhs.schema,
        )
        self.assertEqual(
            mixed_lhs_conditional_products[0].lhs_schema,
            {"allOf": [{"type": "string"}, {"type": "string"}, {"minLength": 1}]},
        )
        mixed_rhs_conditional_formula = DifferenceFormula.from_schemas(
            {"type": "string", "minLength": 2},
            {"type": "string", "if": {"type": "string"}, "then": {"minLength": 1}},
            Dialect.DRAFT7,
        )
        mixed_rhs_conditional_plan = applicator_difference_plans(
            mixed_rhs_conditional_formula
        )[0]
        self.assertIsInstance(mixed_rhs_conditional_plan, ApplicatorConditionalPlan)
        self.assertEqual(mixed_rhs_conditional_plan.base_schema, {"type": "string"})
        mixed_rhs_conditional_base = applicator_base_product(
            mixed_rhs_conditional_plan,
            lhs_schema=mixed_rhs_conditional_formula.lhs.schema,
        )
        self.assertIsInstance(mixed_rhs_conditional_base, ApplicatorBaseProduct)
        self.assertEqual(
            mixed_rhs_conditional_base.lhs_schema, {"type": "string", "minLength": 2}
        )
        self.assertEqual(mixed_rhs_conditional_base.rhs_schema, {"type": "string"})
        self.assertEqual(
            mixed_rhs_conditional_base.witness_missing_reason,
            "SAT conditional base witness could not be constructed",
        )
        self.assertEqual(
            mixed_rhs_conditional_base.witness_rejected_reason,
            "SAT conditional base witness was rejected",
        )
        self.assertIsInstance(mixed_rhs_conditional_plan.formula_node, NotFormula)
        self.assertEqual(mixed_rhs_conditional_plan.formula_node.applicator_kind, "if")
        self.assertIs(
            mixed_rhs_conditional_plan.formula_node.applicator,
            mixed_rhs_conditional_formula.rhs.root.applicators[0],
        )
        self.assertEqual(
            applicators_module._conditional_nodes_from_formula_metadata(
                mixed_rhs_conditional_formula.negative_rhs
            ),
            (
                mixed_rhs_conditional_plan.if_child,
                mixed_rhs_conditional_plan.then_child,
                mixed_rhs_conditional_plan.else_child,
            ),
        )
        hard_keyword_conditional_formula = DifferenceFormula.from_schemas(
            {"type": "array"},
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "if": {"type": "array"},
                "then": {"minItems": 1},
                "unevaluatedItems": False,
            },
            Dialect.DRAFT202012,
        )
        self.assertEqual(
            applicator_difference_plans(hard_keyword_conditional_formula), ()
        )
        self.assertFalse(hasattr(sat_module, "ExactTacticRule"))
        self.assertFalse(hasattr(sat_module, "_pure_applicator"))
        self.assertNotIn("exact_subschema_tactics", inspect.getsource(sat_module))
        self.assertNotIn("class DifferenceFormula", inspect.getsource(sat_module))
        self.assertIn("class DifferenceFormula", inspect.getsource(formulas_module))
        self.assertIn(
            "positive_lhs", inspect.getsource(formulas_module.DifferenceFormula)
        )
        self.assertIn(
            "negative_rhs", inspect.getsource(formulas_module.DifferenceFormula)
        )
        self.assertIn(
            "_reference_formula",
            inspect.getsource(formulas_module._positive_formula_for_node),
        )
        self.assertIn(
            "unsupported_diagnostics",
            inspect.getsource(formulas_module.FormulaOccurrence),
        )
        self.assertIn(
            "formula.unsupported_diagnostics",
            inspect.getsource(sat_module._semantic_unsupported),
        )
        self.assertFalse(hasattr(sat_module, "_unsupported_diagnostics"))
        self.assertIn(
            "def applicator_plan_set", inspect.getsource(sat_module.DifferenceProblem)
        )
        self.assertIn(
            "applicator_plan_set(self.formula)",
            inspect.getsource(sat_module.DifferenceProblem),
        )
        self.assertIn(
            "def applicator_plans", inspect.getsource(sat_module.DifferenceProblem)
        )
        self.assertIn(
            "return self.applicator_plan_set.plans",
            inspect.getsource(sat_module.DifferenceProblem),
        )
        self.assertNotIn(
            "for plan in problem.applicator_plans", inspect.getsource(sat_module)
        )
        self.assertIn("branch_with_strategy", inspect.getsource(sat_module))
        self.assertIn("one_of_cardinality()", inspect.getsource(sat_module))
        self.assertIn("conditional()", inspect.getsource(sat_module))
        self.assertNotIn(
            "applicator_difference_plans(problem.formula)",
            inspect.getsource(sat_module),
        )
        self.assertNotIn(
            "applicator_difference_plans(problem.formula.lhs",
            inspect.getsource(sat_module),
        )
        self.assertIn("FormulaOccurrence", inspect.getsource(applicators_module))
        self.assertIn(
            "_applicator_formula_from_metadata", inspect.getsource(applicators_module)
        )
        self.assertIn("_find_applicator_formula", inspect.getsource(applicators_module))
        self.assertFalse(hasattr(applicators_module, "_applicator_node_from_ir"))
        self.assertFalse(
            hasattr(applicators_module, "_applicator_node_from_formula_metadata")
        )
        self.assertIn(
            "_applicator_formula_from_metadata(occurrence, kind)",
            inspect.getsource(applicators_module._pure_applicator_formula),
        )
        self.assertNotIn(
            "_applicator_node_from_ir",
            inspect.getsource(applicators_module._pure_applicator_formula),
        )
        self.assertIn(
            "_conditional_formula_from_metadata(occurrence)",
            inspect.getsource(
                applicators_module._conditional_applicator_plan_for_occurrence
            ),
        )
        self.assertIn(
            "_conditional_nodes_from_formula_metadata",
            inspect.getsource(applicators_module),
        )
        self.assertIn(
            "_conditional_nodes_from_not_formula", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "_conditional_formula_from_metadata", inspect.getsource(applicators_module)
        )
        self.assertFalse(hasattr(applicators_module, "_conditional_nodes_from_ir"))
        self.assertFalse(hasattr(applicators_module, "_single_conditional_child"))
        self.assertNotIn(
            'occurrence.polarity != "positive"',
            inspect.getsource(
                applicators_module._conditional_nodes_from_formula_metadata
            ),
        )
        self.assertNotIn(
            "occurrence.ir",
            inspect.getsource(applicators_module._conditional_formula_from_metadata),
        )
        self.assertNotIn("match plan.side, plan.kind", inspect.getsource(sat_module))
        self.assertNotIn("match plan.strategy", inspect.getsource(sat_module))
        self.assertFalse(hasattr(sat_module, "_prove_applicator_difference"))
        self.assertFalse(hasattr(sat_module, "_applicator_plan_with_strategy"))
        self.assertFalse(hasattr(sat_module, "_one_of_cardinality_plan"))
        self.assertFalse(hasattr(sat_module, "_conditional_plan"))
        self.assertIn("plan.nnf", inspect.getsource(sat_module))
        self.assertNotIn(
            "applicator_nnf_fragment(plan.formula)", inspect.getsource(sat_module)
        )
        self.assertNotIn(
            "_prove_rhs_not_difference(problem, plan.children[0])",
            inspect.getsource(sat_module),
        )
        self.assertFalse(hasattr(sat_module, "_prove_right_any_of_difference"))
        self.assertFalse(hasattr(sat_module, "_prove_right_all_of_difference"))
        self.assertIn("right-anyof-nnf-bounded", inspect.getsource(applicators_module))
        self.assertIn("right-allof-nnf-exact", inspect.getsource(applicators_module))
        self.assertIn(
            "right-oneof-cardinality-exact", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "conditional-guarded-exact", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "applicator_branch_products",
            inspect.getsource(sat_module._left_branch_products),
        )
        self.assertIn(
            "witness_unsupported_reason",
            inspect.getsource(applicators_module.ApplicatorBranchProduct),
        )
        self.assertIn(
            "product.witness_missing_reason",
            inspect.getsource(sat_module._prove_left_any_of_difference),
        )
        self.assertIn(
            "product.witness_rejected_reason",
            inspect.getsource(sat_module._prove_left_any_of_difference),
        )
        self.assertIn(
            "product.witness_unsupported_reason",
            inspect.getsource(sat_module._prove_left_one_of_difference),
        )
        self.assertEqual(left_any_of_branch_proof_choice("proved_true"), "continue")
        self.assertEqual(left_any_of_branch_proof_choice("unsupported"), "return_proof")
        self.assertEqual(
            left_any_of_branch_proof_choice("proved_false"), "validate_witness"
        )
        self.assertEqual(left_one_of_branch_proof_choice("proved_true"), "continue")
        self.assertEqual(
            left_one_of_branch_proof_choice("unsupported"), "record_unsupported"
        )
        self.assertEqual(
            left_one_of_branch_proof_choice("resource_exhausted"), "return_proof"
        )
        self.assertEqual(
            left_one_of_branch_proof_choice("proved_false"), "validate_witness"
        )
        self.assertEqual(left_all_of_branch_proof_choice("proved_true"), "proved_true")
        self.assertEqual(
            left_all_of_branch_proof_choice("unsupported"), "record_unsupported"
        )
        self.assertEqual(
            left_all_of_branch_proof_choice("resource_exhausted"), "return_proof"
        )
        self.assertEqual(
            left_all_of_branch_proof_choice("proved_false"), "validate_witness"
        )
        self.assertIn(
            "left_any_of_branch_proof_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "left_one_of_branch_proof_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "left_all_of_branch_proof_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "left_any_of_branch_proof_choice",
            inspect.getsource(sat_module._prove_left_any_of_difference),
        )
        self.assertIn(
            "left_one_of_branch_proof_choice",
            inspect.getsource(sat_module._prove_left_one_of_difference),
        )
        self.assertIn(
            "left_all_of_branch_proof_choice",
            inspect.getsource(sat_module._prove_left_all_of_difference),
        )
        self.assertNotIn(
            'proof.status == "proved_true"',
            inspect.getsource(sat_module._prove_left_any_of_difference),
        )
        self.assertNotIn(
            'proof.status == "unsupported"',
            inspect.getsource(sat_module._prove_left_one_of_difference),
        )
        self.assertNotIn(
            'proof.status == "resource_exhausted"',
            inspect.getsource(sat_module._prove_left_all_of_difference),
        )
        self.assertNotIn("left-anyOf branch witness", inspect.getsource(sat_module))
        self.assertNotIn("left-oneOf branch witness", inspect.getsource(sat_module))
        self.assertNotIn("left-allOf branch witness", inspect.getsource(sat_module))
        self.assertNotIn(
            "left-oneOf branch counterexample", inspect.getsource(sat_module)
        )
        self.assertNotIn(
            "child.source.schema",
            inspect.getsource(sat_module._prove_left_any_of_difference),
        )
        self.assertNotIn(
            "child.source.schema",
            inspect.getsource(sat_module._prove_left_one_of_difference),
        )
        self.assertNotIn(
            "child.source.schema",
            inspect.getsource(sat_module._prove_left_all_of_difference),
        )
        self.assertIn(
            "left_branch_resolved_lhs_schema", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "left_branch_resolved_lhs_schema",
            inspect.getsource(sat_module._left_branch_subproof),
        )
        self.assertFalse(hasattr(sat_module, "_left_branch_resolved_schema"))
        self.assertNotIn(
            '{"allOf": [product.base_schema, resolution.schema]}',
            inspect.getsource(sat_module),
        )
        self.assertIn(
            "conditional_branch_products",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertIn(
            "covering_lhs_schema",
            inspect.getsource(applicators_module.ApplicatorConditionalProduct),
        )
        self.assertIn(
            "product.covering_lhs_schema",
            inspect.getsource(sat_module._prove_rhs_conditional_product_empty),
        )
        self.assertIn(
            "is_trivially_empty_difference",
            inspect.getsource(applicators_module.ApplicatorConditionalProduct),
        )
        self.assertIn(
            "product.is_trivially_empty_difference",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertNotIn(
            "schema_is_false",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertNotIn(
            "schema_is_true",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertIn(
            "witness_missing_reason",
            inspect.getsource(applicators_module.ApplicatorConditionalProduct),
        )
        self.assertIn(
            "product.witness_missing_reason",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertIn(
            "product.witness_rejected_reason",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertNotIn("conditional branch witness", inspect.getsource(sat_module))
        self.assertEqual(
            conditional_covering_subproof_choice("proved_true"), "proved_true"
        )
        self.assertEqual(
            conditional_covering_subproof_choice("resource_exhausted"), "return_proof"
        )
        self.assertEqual(
            conditional_covering_subproof_choice("unsupported"), "continue"
        )
        self.assertEqual(
            conditional_covering_product_proof_choice("proved_true"), "continue"
        )
        self.assertEqual(
            conditional_covering_product_proof_choice("resource_exhausted"),
            "return_proof",
        )
        self.assertEqual(conditional_branch_proof_choice("proved_true"), "continue")
        self.assertEqual(
            conditional_branch_proof_choice("resource_exhausted"), "return_proof"
        )
        self.assertEqual(
            conditional_branch_proof_choice("unsupported"), "record_unsupported"
        )
        self.assertEqual(
            conditional_branch_proof_choice("proved_false"), "validate_witness"
        )
        self.assertEqual(
            conditional_final_proof_choice("proved_true", has_unsupported_branch=False),
            "proved_true",
        )
        self.assertEqual(
            conditional_final_proof_choice("unsupported", has_unsupported_branch=False),
            "base",
        )
        self.assertEqual(
            conditional_final_proof_choice("proved_true", has_unsupported_branch=True),
            "unsupported",
        )
        self.assertIn(
            "conditional_covering_subproof_choice",
            inspect.getsource(applicators_module),
        )
        self.assertIn(
            "conditional_covering_product_proof_choice",
            inspect.getsource(applicators_module),
        )
        self.assertIn(
            "conditional_branch_proof_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "conditional_final_proof_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "conditional_covering_product_proof_choice",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertIn(
            "conditional_branch_proof_choice",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertIn(
            "conditional_final_proof_choice",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertIn(
            "conditional_covering_subproof_choice",
            inspect.getsource(sat_module._prove_rhs_conditional_product_empty),
        )
        self.assertNotIn(
            'empty.status == "proved_true"',
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertNotIn(
            'proof.status == "proved_true"',
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertNotIn(
            'proof.status == "resource_exhausted"',
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertNotIn(
            'proof.status == "unsupported"',
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertNotIn(
            'base_proof.status == "proved_true"',
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertNotIn(
            'proof.status == "proved_true"',
            inspect.getsource(sat_module._prove_rhs_conditional_product_empty),
        )
        self.assertNotIn(
            'proof.status == "resource_exhausted"',
            inspect.getsource(sat_module._prove_rhs_conditional_product_empty),
        )
        self.assertIn(
            "_applicator_expansion_budget_exhausted",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertIn(
            "applicator_branch_expansion_budget(plan)",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertIn(
            "_prove_applicator_base_difference",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertIn(
            "applicator_base_product",
            inspect.getsource(sat_module._prove_applicator_base_difference),
        )
        self.assertIn("ApplicatorBaseProduct", inspect.getsource(applicators_module))
        self.assertIn(
            "witness_missing_reason",
            inspect.getsource(applicators_module.ApplicatorBaseProduct),
        )
        self.assertIn("_validated_applicator_base_false", inspect.getsource(sat_module))
        self.assertIn(
            "product.witness_missing_reason",
            inspect.getsource(sat_module._validated_applicator_base_false),
        )
        self.assertIn(
            "product.witness_rejected_reason",
            inspect.getsource(sat_module._validated_applicator_base_false),
        )
        self.assertEqual(
            applicator_base_pre_branch_choice("proved_false"), "base_false"
        )
        self.assertEqual(applicator_base_pre_branch_choice("proved_true"), "continue")
        self.assertIn(
            "applicator_base_pre_branch_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "applicator_base_pre_branch_choice",
            inspect.getsource(sat_module._run_right_applicator_base_first_flow),
        )
        self.assertIn(
            "applicator_base_pre_branch_choice",
            inspect.getsource(sat_module._prove_conditional_difference),
        )
        self.assertNotIn(
            'base_proof.status == "proved_false"', inspect.getsource(sat_module)
        )
        self.assertTrue(hasattr(sat_module, "ApplicatorProofFlow"))
        self.assertIn(
            "_run_right_applicator_base_first_flow",
            inspect.getsource(sat_module._run_right_applicator_flow),
        )
        self.assertIn(
            "_run_right_applicator_branch_first_flow",
            inspect.getsource(sat_module._run_right_applicator_flow),
        )
        self.assertIn(
            'branch_proof.status in {"proved_false", "resource_exhausted"}',
            inspect.getsource(sat_module._run_right_applicator_branch_first_flow),
        )
        self.assertIn(
            'branch_proof.status == "proved_true" and base_proof.status == "proved_true"',
            inspect.getsource(sat_module._run_right_applicator_base_first_flow),
        )
        self.assertNotIn("right_applicator_base_first_result_choice", inspect.getsource(applicators_module))
        self.assertNotIn(
            "right_applicator_branch_first_result_choice",
            inspect.getsource(applicators_module),
        )
        self.assertNotIn(
            "right_applicator_base_first_result_choice",
            inspect.getsource(sat_module._prove_right_not_applicator_difference),
        )
        self.assertNotIn(
            "right_applicator_branch_first_pre_base_choice",
            inspect.getsource(sat_module._prove_right_any_of_applicator_difference),
        )
        self.assertNotIn(
            "right_applicator_branch_first_result_choice",
            inspect.getsource(sat_module._prove_right_any_of_applicator_difference),
        )
        self.assertNotIn(
            'branch_proof.status == "proved_true" and base_proof.status == "proved_true"',
            inspect.getsource(sat_module._prove_right_not_applicator_difference),
        )
        self.assertNotIn("right-not base witness", inspect.getsource(sat_module))
        self.assertNotIn("right-anyOf base witness", inspect.getsource(sat_module))
        self.assertNotIn("right-oneOf base witness", inspect.getsource(sat_module))
        self.assertNotIn("right-allOf base witness", inspect.getsource(sat_module))
        self.assertNotIn("conditional base witness", inspect.getsource(sat_module))
        self.assertFalse(hasattr(sat_module, "_prove_rhs_applicator_base_difference"))
        self.assertFalse(hasattr(sat_module, "_prove_rhs_one_of_base_difference"))
        self.assertFalse(hasattr(sat_module, "_prove_rhs_conditional_base_difference"))
        self.assertNotIn("plan.formula.base_schema", inspect.getsource(sat_module))
        self.assertNotIn("plan.base_schema", inspect.getsource(sat_module))
        self.assertIn(
            "_applicator_expansion_budget_exhausted",
            inspect.getsource(sat_module._prove_left_any_of_difference),
        )
        self.assertIn(
            "applicator_branch_expansion_budget(plan)",
            inspect.getsource(sat_module._prove_left_any_of_difference),
        )
        self.assertIn(
            "branch_budget_exhausted_reason",
            inspect.getsource(applicators_module.ApplicatorBranchPlan),
        )
        self.assertNotIn(
            "plan.branch_product_count",
            inspect.getsource(sat_module._prove_left_any_of_difference),
        )
        self.assertNotIn(
            "plan.branch_budget_exhausted_reason",
            inspect.getsource(sat_module._prove_left_any_of_difference),
        )
        self.assertIn(
            "_applicator_expansion_budget_exhausted",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertIn(
            "applicator_branch_expansion_budget(nnf)",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertNotIn(
            "nnf.branch_product_count",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertNotIn(
            "nnf.branch_budget_exhausted_reason",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertIn(
            "coverage_budget_exhausted_reason",
            inspect.getsource(applicators_module.ApplicatorOneOfCardinalityPlan),
        )
        self.assertIn(
            "one_of_coverage_expansion_budget(plan)",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertIn(
            "one_of_disjointness_expansion_budget(plan)",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertNotIn(
            "plan.coverage_product_count",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertNotIn(
            "plan.disjointness_product_count",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertIn(
            "witness_missing_reason",
            inspect.getsource(applicators_module.ApplicatorNnfBranchProduct),
        )
        self.assertIn(
            "product.witness_rejected_reason",
            inspect.getsource(sat_module._prove_rhs_negative_any_of_difference),
        )
        self.assertIn(
            "product.witness_missing_reason",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertIn(
            "product.witness_rejected_reason",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertEqual(
            right_negative_any_of_branch_proof_choice("proved_true"), "proved_true"
        )
        self.assertEqual(
            right_negative_any_of_branch_proof_choice("unsupported"),
            "record_unsupported",
        )
        self.assertEqual(
            right_negative_any_of_branch_proof_choice("resource_exhausted"),
            "return_proof",
        )
        self.assertEqual(
            right_negative_any_of_branch_proof_choice("proved_false"),
            "validate_witness",
        )
        self.assertEqual(
            right_negative_all_of_branch_proof_choice("proved_true"), "continue"
        )
        self.assertEqual(
            right_negative_all_of_branch_proof_choice("unsupported"), "return_proof"
        )
        self.assertEqual(
            right_negative_all_of_branch_proof_choice("resource_exhausted"),
            "return_proof",
        )
        self.assertEqual(
            right_negative_all_of_branch_proof_choice("proved_false"),
            "validate_witness",
        )
        self.assertIn(
            "right_negative_any_of_branch_proof_choice",
            inspect.getsource(applicators_module),
        )
        self.assertIn(
            "right_negative_all_of_branch_proof_choice",
            inspect.getsource(applicators_module),
        )
        self.assertIn(
            "right_negative_any_of_branch_product_plan",
            inspect.getsource(applicators_module),
        )
        self.assertIn(
            "right_negative_all_of_branch_product_plan",
            inspect.getsource(applicators_module),
        )
        self.assertIn(
            "ApplicatorNnfBranchProductPlan", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "right_negative_any_of_branch_product_plan",
            inspect.getsource(sat_module._prove_rhs_negative_any_of_difference),
        )
        self.assertIn(
            "right_negative_all_of_branch_product_plan",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertIn(
            "right_negative_any_of_branch_proof_choice",
            inspect.getsource(sat_module._prove_rhs_negative_any_of_difference),
        )
        self.assertIn(
            "right_negative_all_of_branch_proof_choice",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertNotIn(
            'proof.status == "proved_true"',
            inspect.getsource(sat_module._prove_rhs_negative_any_of_difference),
        )
        self.assertNotIn(
            'proof.status in {"unsupported", "resource_exhausted"}',
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertNotIn("right-anyOf branch witness", inspect.getsource(sat_module))
        self.assertNotIn("right-allOf conjunct witness", inspect.getsource(sat_module))
        self.assertNotIn("max_branch_expansions", inspect.getsource(sat_module))
        self.assertNotIn("len(plan.children)", inspect.getsource(sat_module))
        self.assertNotIn("len(plan.branches)", inspect.getsource(sat_module))
        self.assertNotIn("len(nnf.children)", inspect.getsource(sat_module))
        self.assertNotIn("nnf.operator", inspect.getsource(sat_module))
        self.assertNotIn("nnf.children", inspect.getsource(sat_module))
        self.assertIn(
            "product.covering_schema",
            inspect.getsource(sat_module._prove_rhs_conditional_product_empty),
        )
        self.assertNotIn(
            "plan.side",
            inspect.getsource(sat_module._prove_rhs_conditional_product_empty),
        )
        self.assertNotIn(
            "plan.polarity",
            inspect.getsource(sat_module._prove_rhs_conditional_product_empty),
        )
        self.assertNotIn(
            "problem.lhs_schema",
            inspect.getsource(sat_module._prove_rhs_conditional_product_empty),
        )
        self.assertNotIn(
            "condition.node.source.schema",
            inspect.getsource(sat_module._prove_rhs_conditional_product_empty),
        )
        self.assertEqual(
            one_of_coverage_branch_proof_choice("proved_true"), "record_covering"
        )
        self.assertEqual(
            one_of_coverage_branch_proof_choice("unsupported"), "record_unsupported"
        )
        self.assertEqual(
            one_of_coverage_branch_proof_choice("resource_exhausted"), "return_proof"
        )
        self.assertEqual(
            one_of_coverage_branch_proof_choice("proved_false"), "validate_witness"
        )
        self.assertIn(
            "one_of_coverage_branch_proof_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "one_of_cardinality_products",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertIn(
            "one_of_coverage_branch_proof_choice",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertIn(
            "one_of_covering_selection",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertNotIn(
            'proof.status == "proved_true"',
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertNotIn(
            'proof.status == "unsupported"',
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertNotIn("one_of_overlap_product", inspect.getsource(sat_module))
        self.assertNotIn(
            "len(covering_indexes)",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertIn(
            "one_of_overlap_witness_plan",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertNotIn(
            "schema_witness_plan",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertIn(
            "one_of_disjointness_products",
            inspect.getsource(sat_module._one_of_disjointness_products),
        )
        self.assertIn(
            "one_of_disjointness_complement_schema",
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertEqual(
            one_of_disjointness_direct_proof_choice("proved_true"), "return_proof"
        )
        self.assertEqual(
            one_of_disjointness_direct_proof_choice("proved_false"), "return_proof"
        )
        self.assertEqual(
            one_of_disjointness_direct_proof_choice("resource_exhausted"),
            "return_proof",
        )
        self.assertEqual(
            one_of_disjointness_direct_proof_choice("unsupported"), "continue"
        )
        self.assertEqual(one_of_disjointness_proof_choice("proved_true"), "proved_true")
        self.assertEqual(
            one_of_disjointness_proof_choice("proved_false"), "validate_witness"
        )
        self.assertEqual(
            one_of_disjointness_proof_choice("unsupported"), "return_proof"
        )
        self.assertEqual(
            one_of_disjointness_proof_choice("resource_exhausted"), "return_proof"
        )
        self.assertIn(
            "one_of_disjointness_direct_proof_choice",
            inspect.getsource(applicators_module),
        )
        self.assertIn(
            "one_of_disjointness_direct_proof_choice",
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertIn(
            "one_of_disjointness_proof_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "one_of_disjointness_proof_choice",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertIn(
            "one_of_disjointness_proof_choice",
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertNotIn(
            'disjoint.status == "proved_true"',
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertNotIn(
            'disjoint.status == "proved_false"',
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertNotIn(
            'complement.status == "proved_true"',
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertNotIn(
            'complement.status == "proved_false"',
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertNotIn(
            'disjoint.status != "unsupported"',
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertIn(
            "one_of_disjointness_resolved_branch_schema",
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertNotIn(
            "product.branch_schema",
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertIn(
            "product.witness_missing_reason",
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertIn(
            "product.witness_rejected_reason",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertNotIn("right-oneOf branch witness", inspect.getsource(sat_module))
        self.assertNotIn("right-oneOf overlap witness", inspect.getsource(sat_module))
        self.assertNotIn(
            '{"not": resolved_branch_schema}',
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertIn(
            "_prove_applicator_base_difference",
            inspect.getsource(sat_module._run_right_applicator_base_first_flow),
        )
        self.assertIn(
            "ApplicatorProofFlow",
            inspect.getsource(sat_module._prove_right_one_of_applicator_difference),
        )
        self.assertIn(
            "problem.formula.rhs.tagged_one_of",
            inspect.getsource(sat_module._matching_tagged_rhs_one_of_branch),
        )
        self.assertNotIn(
            "problem.rhs_schema",
            inspect.getsource(sat_module._matching_tagged_rhs_one_of_branch),
        )
        self.assertNotIn(
            "problem.lhs_schema",
            inspect.getsource(sat_module._matching_tagged_rhs_one_of_branch),
        )
        self.assertIn(
            "subproof(product.lhs_schema",
            inspect.getsource(sat_module._prove_rhs_one_of_disjointness_product),
        )
        self.assertNotIn(
            "if product.index == covered_index",
            inspect.getsource(sat_module._prove_rhs_one_of_cardinality_difference),
        )
        self.assertFalse(hasattr(sat_module, "_rhs_nnf_branch_products"))
        self.assertIn(
            "right_nnf_branch_resolved_rhs_schema",
            inspect.getsource(sat_module._rhs_nnf_branch_subproof),
        )
        self.assertNotIn(
            "product.rhs_schema", inspect.getsource(sat_module._rhs_nnf_branch_subproof)
        )
        self.assertIn(
            "one_of_branch_resolved_schema",
            inspect.getsource(sat_module._rhs_one_of_branch_subproof),
        )
        self.assertNotIn(
            "product.branch_schema",
            inspect.getsource(sat_module._rhs_one_of_branch_subproof),
        )
        self.assertNotIn(
            "child.node.source.schema",
            inspect.getsource(sat_module._prove_rhs_negative_any_of_difference),
        )
        self.assertNotIn(
            "child.node.source.schema",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertFalse(hasattr(sat_module, "_prove_right_one_of_difference"))
        self.assertFalse(hasattr(sat_module, "_prove_rhs_one_of_overlap_difference"))
        self.assertIn(
            "ApplicatorNnfFragment",
            inspect.getsource(sat_module._prove_rhs_negative_any_of_difference),
        )
        self.assertIn(
            "ApplicatorNnfFragment",
            inspect.getsource(sat_module._prove_rhs_negative_all_of_difference),
        )
        self.assertIn("ApplicatorBranchPlan", inspect.getsource(applicators_module))
        self.assertEqual(
            right_not_string_overlap_plan.__module__, "subschema.kernel.overlaps"
        )
        self.assertEqual(
            right_not_string_overlap_plan_from_constraints.__module__,
            "subschema.kernel.overlaps",
        )
        self.assertEqual(
            right_not_string_overlap_proof_choice.__module__,
            "subschema.kernel.overlaps",
        )
        self.assertIn("RightNotStringOverlapPlan", inspect.getsource(overlaps_module))
        self.assertEqual(
            right_not_string_overlap_proof_choice("proved_true"), "proved_true"
        )
        self.assertEqual(
            right_not_string_overlap_proof_choice("witness"), "validate_witness"
        )
        self.assertEqual(
            right_not_string_overlap_proof_choice("unsupported"), "continue"
        )
        self.assertFalse(hasattr(sat_module, "_prove_rhs_not_string_overlap"))
        self.assertIn(
            "right_not_string_overlap_plan_from_constraints",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertIn(
            "right_not_string_overlap_proof_choice",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertIn(
            "lhs_constraint", inspect.getsource(sat_module._prove_rhs_not_difference)
        )
        self.assertIn(
            "applicator_nnf_schema_product",
            inspect.getsource(sat_module._rhs_nnf_schema_product),
        )
        self.assertIn(
            "_rhs_not_product_schema",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertIn(
            "product.rhs_string_language_constraint",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertIn(
            "right_not_witness_plan",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertIn(
            "right_not_complement_schema",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertIn(
            "right_not_complement_needs_subproof", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "right_not_complement_needs_subproof",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertEqual(
            right_not_subproof_choice("proved_true"), "materialize_witness"
        )
        self.assertEqual(right_not_subproof_choice("proved_false"), "continue")
        self.assertEqual(
            right_not_subproof_choice("resource_exhausted"), "return_resource_exhausted"
        )
        self.assertEqual(right_not_subproof_choice("unsupported"), "continue")
        self.assertEqual(
            right_not_complement_proof_choice("proved_true"), "proved_true"
        )
        self.assertEqual(
            right_not_complement_proof_choice("proved_false"), "validate_witness"
        )
        self.assertEqual(
            right_not_complement_proof_choice("resource_exhausted"),
            "return_resource_exhausted",
        )
        self.assertEqual(right_not_complement_proof_choice("unsupported"), "continue")
        self.assertIn(
            "right_not_subproof_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "right_not_complement_proof_choice", inspect.getsource(applicators_module)
        )
        self.assertIn(
            "right_not_subproof_choice",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertIn(
            "right_not_complement_proof_choice",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            'string_overlap.status == "proved_true"',
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            'string_overlap.status == "witness"',
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            'proof.status == "proved_true"',
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            'proof.status == "resource_exhausted"',
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            'proof.status == "unsupported"',
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            'complement.status == "proved_true"',
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            'complement.status == "proved_false"',
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            'complement.status == "resource_exhausted"',
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            "schemas_equal", inspect.getsource(sat_module._prove_rhs_not_difference)
        )
        self.assertIn(
            "right_not_resolved_rhs_schema",
            inspect.getsource(sat_module._rhs_not_product_schema),
        )
        self.assertNotIn(
            "product.rhs_schema", inspect.getsource(sat_module._rhs_not_product_schema)
        )
        self.assertIn(
            "product.witness_rejected_reason",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertIn(
            "product.complement_witness_missing_reason",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertIn(
            "product.complement_witness_rejected_reason",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            "positive_node.source.schema",
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn(
            '{"not": rhs_schema}',
            inspect.getsource(sat_module._prove_rhs_not_difference),
        )
        self.assertNotIn("_schema_node_constraint", inspect.getsource(sat_module))
        self.assertIs(
            composition_module.schemas_are_disjoint,
            disjointness_module.schemas_are_disjoint,
        )
        self.assertEqual(
            disjointness_module.schemas_are_disjoint.__module__,
            "subschema.kernel.disjointness",
        )
        self.assertFalse(hasattr(sat_module, "_prove_schema_disjoint"))
        self.assertNotIn(
            "schema_type_overapproximations_are_disjoint", inspect.getsource(sat_module)
        )
        self.assertNotIn(
            "string_language_fragments_are_disjoint", inspect.getsource(sat_module)
        )
        self.assertFalse(hasattr(sat_module, "WitnessSearchRule"))
        self.assertFalse(hasattr(sat_module, "_first_valid_value_for_schema"))
        self.assertFalse(hasattr(sat_module, "_finite_projection_witness"))
        self.assertNotIn("NO_WITNESS", inspect.getsource(sat_module))
        self.assertNotIn("first_valid_value_for_schema", inspect.getsource(sat_module))
        self.assertNotIn("schema_witness_plan", inspect.getsource(sat_module))
        self.assertNotIn(
            "first_valid_value_for_schema", inspect.getsource(witnesses_module)
        )
        self.assertIn(
            "finite_values_for_schema", inspect.getsource(ir_module.DomainFacts)
        )
        self.assertIn("cached_property", inspect.getsource(ir_module.DomainFacts))
        self.assertIn("def assertion", inspect.getsource(ir_module.DomainFacts))
        self.assertIn(
            "return self.facts.assertion(kind)",
            inspect.getsource(ir_module.LogicalSchemaIR.assertion),
        )
        self.assertNotIn(
            "for assertion in self.assertions",
            inspect.getsource(ir_module.LogicalSchemaIR.assertion),
        )
        self.assertIn("FiniteConstraint", inspect.getsource(constraints_module))
        self.assertIn("finite_constraint", inspect.getsource(ir_module.DomainFacts))
        self.assertIn("type_constraint", inspect.getsource(ir_module.DomainFacts))
        self.assertIn("numeric_constraint", inspect.getsource(ir_module.DomainFacts))
        self.assertIn(
            "string_length_constraint", inspect.getsource(ir_module.DomainFacts)
        )
        self.assertIn(
            "string_language_constraint", inspect.getsource(ir_module.DomainFacts)
        )
        self.assertIn(
            "array_length_lhs_constraint", inspect.getsource(ir_module.DomainFacts)
        )
        self.assertIn(
            "array_uniqueness_lhs_constraint", inspect.getsource(ir_module.DomainFacts)
        )
        self.assertIn(
            "object_property_count_constraint", inspect.getsource(ir_module.DomainFacts)
        )
        self.assertIn(
            "object_property_names_constraint", inspect.getsource(ir_module.DomainFacts)
        )
        self.assertIn(
            "object_property_values_constraint",
            inspect.getsource(ir_module.DomainFacts),
        )
        self.assertIn(
            "object_closed_properties_constraint",
            inspect.getsource(ir_module.DomainFacts),
        )
        self.assertIn(
            "array_length_lhs_constraint",
            inspect.getsource(difference_module.ArrayDifferenceModel),
        )
        self.assertIn(
            "array_uniqueness_lhs_constraint",
            inspect.getsource(difference_module.ArrayDifferenceModel),
        )
        self.assertIn(
            "object_property_count_constraint",
            inspect.getsource(difference_module.ObjectDifferenceModel),
        )
        self.assertIn(
            "object_property_names_constraint",
            inspect.getsource(difference_module.ObjectDifferenceModel),
        )
        self.assertIn(
            "object_property_values_constraint",
            inspect.getsource(difference_module.ObjectDifferenceModel),
        )
        self.assertIn(
            "object_closed_properties_constraint",
            inspect.getsource(difference_module.ObjectDifferenceModel),
        )
        self.assertIn(
            "from_problem", inspect.getsource(difference_module.ArrayDifferenceModel)
        )
        self.assertIn(
            "from_problem", inspect.getsource(difference_module.ObjectDifferenceModel)
        )
        self.assertNotIn(
            "lhs_constraint(",
            inspect.getsource(difference_module.ArrayDifferenceModel.from_problem),
        )
        self.assertNotIn(
            "rhs_constraint(",
            inspect.getsource(difference_module.ArrayDifferenceModel.from_problem),
        )
        self.assertNotIn(
            "lhs_constraint(",
            inspect.getsource(difference_module.ObjectDifferenceModel.from_problem),
        )
        self.assertNotIn(
            "rhs_constraint(",
            inspect.getsource(difference_module.ObjectDifferenceModel.from_problem),
        )
        self.assertNotIn(
            "unevaluatedProperties", inspect.getsource(ir_module.DomainFacts)
        )
        self.assertNotIn("unevaluatedItems", inspect.getsource(ir_module.DomainFacts))
        self.assertNotIn(
            "finite_values_for_schema", inspect.getsource(sat_module.EmptinessSolver)
        )
        self.assertNotIn(
            "type_shape_for_schema", inspect.getsource(sat_module.EmptinessSolver)
        )
        self.assertNotIn(
            "numeric_shape_for_schema", inspect.getsource(sat_module.EmptinessSolver)
        )
        self.assertNotIn(
            "string_shape_for_schema", inspect.getsource(sat_module.EmptinessSolver)
        )
        self.assertNotIn(
            "array_shape_for_schema", inspect.getsource(sat_module.EmptinessSolver)
        )
        for extractor_name in (
            "finite_values_for_schema",
            "type_shape_for_schema",
            "numeric_shape_for_schema",
            "string_shape_for_schema",
            "string_language_shape_for_schema",
            "array_shape_for_schema",
            "array_uniqueness_shape_for_schema",
            "object_property_count_shape_for_schema",
            "object_property_names_shape_for_schema",
            "object_property_values_shape_for_schema",
            "closed_object_properties_shape_for_schema",
        ):
            with self.subTest(extractor=extractor_name):
                self.assertNotIn(extractor_name, inspect.getsource(sat_module))
        self.assertFalse(hasattr(sat_module, "_prove_array_difference"))
        self.assertFalse(hasattr(sat_module, "_prove_object_difference"))
        self.assertIn(
            "def array_model", inspect.getsource(sat_module.DifferenceProblem)
        )
        self.assertIn(
            "ArrayDifferenceModel.from_problem(self)",
            inspect.getsource(sat_module.DifferenceProblem),
        )
        self.assertIn(
            "def object_model", inspect.getsource(sat_module.DifferenceProblem)
        )
        self.assertIn(
            "ObjectDifferenceModel.from_problem(self)",
            inspect.getsource(sat_module.DifferenceProblem),
        )
        self.assertIn(
            "def applicator_plan_set", inspect.getsource(sat_module.DifferenceProblem)
        )
        self.assertIn(
            "def applicator_plans", inspect.getsource(sat_module.DifferenceProblem)
        )
        self.assertIsInstance(
            sat_module.DifferenceProblem.__dict__["array_model"], cached_property
        )
        self.assertIsInstance(
            sat_module.DifferenceProblem.__dict__["object_model"], cached_property
        )
        self.assertIsInstance(
            sat_module.DifferenceProblem.__dict__["applicator_plan_set"],
            cached_property,
        )
        self.assertIsInstance(
            sat_module.DifferenceProblem.__dict__["applicator_plans"], cached_property
        )
        self.assertIn(
            "problem.array_model",
            inspect.getsource(sat_module._prove_array_length_difference),
        )
        self.assertIn(
            "finite_constraint",
            inspect.getsource(sat_module._prove_finite_lhs_difference),
        )
        self.assertIn(
            "lhs_constraint", inspect.getsource(sat_module._prove_finite_lhs_difference)
        )
        self.assertNotIn(
            "formula.lhs.finite_values",
            inspect.getsource(sat_module._prove_finite_lhs_difference),
        )
        self.assertIn(
            "occurrence_assertion_formula",
            inspect.getsource(sat_module.DifferenceProblem),
        )
        self.assertFalse(hasattr(sat_module, "_FINITE_RHS_WITNESS_VALUES"))
        self.assertFalse(hasattr(sat_module, "_finite_rhs_atom_witnesses"))
        self.assertFalse(hasattr(sat_module, "_finite_rhs_generic_witnesses"))
        self.assertFalse(hasattr(sat_module, "_json_values_equal"))
        self.assertIn(
            "finite_rhs_difference_plan",
            inspect.getsource(sat_module._prove_finite_rhs_difference),
        )
        self.assertIn(
            "lhs_constraint", inspect.getsource(sat_module._prove_finite_rhs_difference)
        )
        self.assertIn(
            "rhs_constraint", inspect.getsource(sat_module._prove_finite_rhs_difference)
        )
        self.assertNotIn(
            "witness_not_in", inspect.getsource(sat_module._prove_type_difference)
        )
        self.assertNotIn(
            "witness_not_in", inspect.getsource(sat_module._prove_numeric_difference)
        )
        self.assertNotIn(
            "witness_not_in",
            inspect.getsource(sat_module._prove_string_length_difference),
        )
        self.assertNotIn(
            "witness_not_in",
            inspect.getsource(sat_module._prove_string_language_difference),
        )
        self.assertIn(
            "type_difference_plan", inspect.getsource(sat_module._prove_type_difference)
        )
        self.assertIn(
            "numeric_difference_plan",
            inspect.getsource(sat_module._prove_numeric_difference),
        )
        self.assertIn(
            "string_length_difference_plan",
            inspect.getsource(sat_module._prove_string_length_difference),
        )
        self.assertIn(
            "string_language_difference_plan",
            inspect.getsource(sat_module._prove_string_language_difference),
        )
        self.assertIn(
            "lhs_constraint", inspect.getsource(sat_module._prove_type_difference)
        )
        self.assertIn(
            "rhs_constraint", inspect.getsource(sat_module._prove_type_difference)
        )
        self.assertIn(
            "lhs_constraint", inspect.getsource(sat_module._prove_numeric_difference)
        )
        self.assertIn(
            "rhs_constraint", inspect.getsource(sat_module._prove_numeric_difference)
        )
        self.assertIn("ScalarDifferencePlan", inspect.getsource(scalars_module))
        self.assertIn("FiniteRhsDifferencePlan", inspect.getsource(scalars_module))
        self.assertNotIn(
            "lhs_length", inspect.getsource(sat_module._prove_array_length_difference)
        )
        self.assertNotIn(
            "rhs_length", inspect.getsource(sat_module._prove_array_length_difference)
        )
        self.assertNotIn(
            "witness_not_in",
            inspect.getsource(sat_module._prove_array_length_difference),
        )
        self.assertNotIn("_schema_type_is_array_only", inspect.getsource(sat_module))
        self.assertNotIn(
            "contains_empty_min_violation_possible(",
            inspect.getsource(sat_module._prove_array_contains_difference),
        )
        self.assertNotIn(
            "minimum_contains_matches_guaranteed(",
            inspect.getsource(sat_module._prove_array_contains_difference),
        )
        self.assertNotIn(
            "contains_min_violation_witness_plan(",
            inspect.getsource(sat_module._prove_array_contains_difference),
        )
        self.assertNotIn(
            "maximum_contains_matches_possible(",
            inspect.getsource(sat_module._prove_array_contains_difference),
        )
        self.assertNotIn(
            "_rhs_all_of_evaluated_item_sources", inspect.getsource(sat_module)
        )
        self.assertNotIn(
            "_rhs_evaluated_item_schema_for_index", inspect.getsource(sat_module)
        )
        self.assertNotIn(
            "_first_rhs_unevaluated_item_index_reachable", inspect.getsource(sat_module)
        )
        self.assertNotIn(
            "lhs_length",
            inspect.getsource(sat_module._prove_array_unevaluated_items_difference),
        )
        self.assertNotIn(
            "_array_static_reference_unsupported",
            inspect.getsource(sat_module._prove_array_unevaluated_items_difference),
        )
        self.assertIn(
            "_lhs_static_reference_unsupported",
            inspect.getsource(sat_module._prove_array_unevaluated_items_difference),
        )
        self.assertNotIn(
            "_rhs_all_of_evaluated_property_sources", inspect.getsource(sat_module)
        )
        self.assertNotIn(
            "_rhs_evaluated_property_schema_for_name", inspect.getsource(sat_module)
        )
        self.assertNotIn("_rhs_evaluates_property_name", inspect.getsource(sat_module))
        self.assertNotIn(
            "lhs_key_values",
            inspect.getsource(
                sat_module._prove_object_unevaluated_properties_difference
            ),
        )
        self.assertNotIn(
            "_object_static_reference_unsupported",
            inspect.getsource(
                sat_module._prove_object_unevaluated_properties_difference
            ),
        )
        self.assertIn(
            "_lhs_static_reference_unsupported",
            inspect.getsource(
                sat_module._prove_object_unevaluated_properties_difference
            ),
        )
        self.assertIn(
            "evaluation_trace_for_source", inspect.getsource(difference_module)
        )
        self.assertNotIn(".to_expression(", inspect.getsource(difference_module))
        self.assertNotIn("EvaluationExpression", inspect.getsource(difference_module))
        self.assertIn("evaluated_item_sources", inspect.getsource(difference_module))
        self.assertIn(
            "evaluated_property_sources", inspect.getsource(difference_module)
        )
        self.assertNotIn(
            "def _all_of_evaluated_item_sources", inspect.getsource(difference_module)
        )
        self.assertNotIn(
            "def _all_of_evaluated_property_sources",
            inspect.getsource(difference_module),
        )
        self.assertNotIn(
            "lhs_uniqueness",
            inspect.getsource(sat_module._prove_array_uniqueness_difference),
        )
        self.assertNotIn(
            "rhs_uniqueness",
            inspect.getsource(sat_module._prove_array_uniqueness_difference),
        )
        self.assertNotIn(
            "uniqueness_duplicate_witness_plan(",
            inspect.getsource(sat_module._prove_array_uniqueness_difference),
        )
        self.assertNotIn(
            "_is_array_item_values_fragment_schema", inspect.getsource(sat_module)
        )
        self.assertNotIn(
            "has_rhs_item_value_constraints(",
            inspect.getsource(sat_module._prove_array_item_values_difference),
        )
        self.assertNotIn(
            "item_value_obligations(",
            inspect.getsource(sat_module._prove_array_item_values_difference),
        )
        self.assertNotIn(
            "object_property_count_shape_for_schema",
            inspect.getsource(sat_module.EmptinessSolver),
        )
        self.assertIn(
            "problem.object_model",
            inspect.getsource(sat_module._prove_object_property_count_difference),
        )
        self.assertNotIn(
            "lhs_property_count",
            inspect.getsource(sat_module._prove_object_property_count_difference),
        )
        self.assertNotIn(
            "rhs_property_count",
            inspect.getsource(sat_module._prove_object_property_count_difference),
        )
        self.assertNotIn(
            "witness_not_in",
            inspect.getsource(sat_module._prove_object_property_count_difference),
        )
        self.assertFalse(hasattr(sat_module, "object_key_value_shape_for_schema"))
        self.assertFalse(hasattr(sat_module, "_object_key_value_shape_for_schema"))
        self.assertFalse(hasattr(sat_module, "_object_key_value_obligations"))
        self.assertFalse(hasattr(sat_module, "_object_key_value_witness"))
        self.assertFalse(
            hasattr(sat_module, "_object_key_value_mixed_product_supported")
        )
        self.assertFalse(hasattr(sat_module, "_object_presence_product_can_prove_true"))
        self.assertFalse(hasattr(sat_module, "_object_property_count_upper_bound"))
        self.assertFalse(hasattr(sat_module, "_object_schema_max_properties_bound"))
        self.assertFalse(hasattr(sat_module, "_repair_object_property_names_witness"))
        self.assertNotIn(
            "lhs_key_values",
            inspect.getsource(sat_module._prove_object_key_value_difference),
        )
        self.assertNotIn(
            "rhs_key_values",
            inspect.getsource(sat_module._prove_object_key_value_difference),
        )
        self.assertNotIn(
            "key_value_product_supported(",
            inspect.getsource(sat_module._prove_object_key_value_difference),
        )
        self.assertNotIn(
            "key_value_obligations(",
            inspect.getsource(sat_module._prove_object_key_value_difference),
        )
        self.assertIn(
            "materialize_object_key_value_witness_skeleton",
            inspect.getsource(sat_module._prove_object_key_value_difference),
        )
        self.assertNotIn(
            "lhs_property_values",
            inspect.getsource(sat_module._prove_object_property_values_difference),
        )
        self.assertNotIn(
            "rhs_property_values",
            inspect.getsource(sat_module._prove_object_property_values_difference),
        )
        self.assertNotIn(
            "property_value_obligations(",
            inspect.getsource(sat_module._prove_object_property_values_difference),
        )
        self.assertFalse(hasattr(sat_module, "_object_property_values_witness"))
        self.assertIn(
            "materialize_object_property_value_witness_skeleton",
            inspect.getsource(sat_module._prove_object_property_values_difference),
        )
        self.assertNotIn(
            "lhs_closed_properties",
            inspect.getsource(sat_module._prove_closed_object_properties_difference),
        )
        self.assertNotIn(
            "rhs_closed_properties",
            inspect.getsource(sat_module._prove_closed_object_properties_difference),
        )
        self.assertNotIn(
            "closed_object_value_obligations(",
            inspect.getsource(sat_module._prove_closed_object_properties_difference),
        )
        self.assertFalse(hasattr(sat_module, "_closed_object_witness"))
        self.assertFalse(hasattr(sat_module, "_closed_object_witness_from_skeleton"))
        self.assertIn(
            "materialize_closed_object_witness_skeleton",
            inspect.getsource(sat_module._prove_closed_object_properties_difference),
        )
        self.assertNotIn(
            "_rhs_object_property_names_has_value_constraints",
            inspect.getsource(sat_module),
        )
        self.assertNotIn(
            "lhs_property_names.is_subset_of", inspect.getsource(sat_module)
        )
        self.assertNotIn("finite_closed_lhs_names(", inspect.getsource(sat_module))
        self.assertNotIn("keyspace_witness_not_in(", inspect.getsource(sat_module))
        self.assertNotIn("lhs_shape.object_witness(", inspect.getsource(sat_module))
        self.assertFalse(hasattr(sat_module, "_object_property_names_repair_witness"))
        self.assertIn(
            "materialize_object_property_names_repair_skeleton",
            inspect.getsource(sat_module._prove_object_property_names_difference),
        )
        self.assertFalse(hasattr(sat_module, "_rhs_has_array_item_value_constraints"))
        self.assertFalse(
            hasattr(sat_module, "_first_lhs_unconstrained_index_under_rhs_tail")
        )
        self.assertFalse(hasattr(sat_module, "_array_contains_min_violation_witness"))
        self.assertFalse(hasattr(sat_module, "_array_contains_max_violation_witness"))
        self.assertFalse(
            hasattr(sat_module, "_array_contains_min_violation_witness_from_plan")
        )
        self.assertFalse(
            hasattr(sat_module, "_array_contains_max_violation_witness_from_plan")
        )
        self.assertFalse(hasattr(sat_module, "_first_lhs_array_length"))
        self.assertFalse(hasattr(sat_module, "_array_witness_from_skeleton"))
        self.assertFalse(hasattr(sat_module, "_array_witness_from_plan"))
        self.assertFalse(hasattr(sat_module, "_array_duplicate_witness"))
        self.assertIn(
            "materialize_array_witness_skeleton", inspect.getsource(difference_module)
        )
        self.assertIn(
            "materialize_array_witness_plan",
            inspect.getsource(sat_module._prove_array_contains_difference),
        )
        self.assertFalse(hasattr(sat_module, "_array_length_shape_allows"))
        self.assertNotIn(
            "[None, None]",
            inspect.getsource(sat_module._prove_array_uniqueness_difference),
        )
        self.assertNotIn("presence_property_sets(", inspect.getsource(sat_module))
        self.assertNotIn(
            "multi_fresh_presence_property_sets(", inspect.getsource(sat_module)
        )
        self.assertNotIn("presence_accepts(", inspect.getsource(sat_module))
        self.assertIn(
            "bounded_ir_proof",
            inspect.getsource(engine_module.ProofEngine._bounded_ir_proof),
        )
        self.assertIn(
            "EmptinessSolver", inspect.getsource(driver_module.bounded_ir_proof)
        )
        self.assertNotIn("find_counterexample(", inspect.getsource(sat_module))
        self.assertNotIn(
            "find_counterexample(", inspect.getsource(sat_module.EmptinessSolver)
        )
        disjoint_proof = disjointness_module.schemas_are_disjoint(
            {"type": "string"},
            {"type": "number"},
            ProofContext(Dialect.DRAFT7),
        )
        self.assertEqual(disjoint_proof.status, "proved_true")
        object_value_disjoint = disjointness_module.schemas_are_disjoint(
            {
                "type": "object",
                "properties": {"a": {"type": "integer"}},
                "required": ["a"],
            },
            {"required": ["a"], "properties": {"a": {"type": "string"}}},
            ProofContext(Dialect.DRAFT7),
        )
        self.assertEqual(object_value_disjoint.status, "proved_true")

        rhs_not_witness_formula = DifferenceFormula.from_schemas(
            {"type": "string", "pattern": "^ab$"},
            {"not": {"type": "string", "pattern": "^a"}},
            Dialect.DRAFT7,
        )
        rhs_not_witness_nnf = applicator_nnf_fragments(rhs_not_witness_formula)[0]
        rhs_not_witness_plan = right_not_string_overlap_plan(
            rhs_not_witness_formula.lhs,
            rhs_not_witness_nnf.children[0].node,
            Dialect.DRAFT7,
        )
        rhs_not_witness_constraint_plan = (
            right_not_string_overlap_plan_from_constraints(
                rhs_not_witness_formula.lhs.string_language_constraint,
                rhs_not_witness_nnf.children[0]
                .node.facts.assertion("string-language")
                .value,
                rhs_not_witness_formula.lhs.schema,
                rhs_not_witness_nnf.children[0].node.source.schema,
                Dialect.DRAFT7,
            )
        )
        self.assertEqual(rhs_not_witness_plan.status, "witness")
        self.assertEqual(rhs_not_witness_plan.witness, "ab")
        self.assertEqual(rhs_not_witness_constraint_plan, rhs_not_witness_plan)

    def test_rule_proof_class_guards_runtime_results(self):
        class FakeRule:
            def __init__(self, spec, proof):
                self.spec = spec
                self.name = spec.name
                self._proof = proof

            def prove(self, _problem):
                return self._proof

        endeavor_spec = DifferenceRuleSpec(
            name="fake-endeavor",
            fragment="test",
            completeness="bounded_witness",
            witness_mode="validated",
            proof_class="endeavor_expensive",
            budget_use="domain",
        )
        unreliable_spec = DifferenceRuleSpec(
            name="fake-unreliable",
            fragment="test",
            completeness="unsupported_boundary",
            witness_mode="none",
            proof_class="unsupported_unreliable",
            budget_use="none",
        )

        default_solver = EmptinessSolver(ProofContext(Dialect.DRAFT7))
        default_solver.rules = (FakeRule(endeavor_spec, ProofResult.true()),)
        unreliable_solver = EmptinessSolver(ProofContext(Dialect.DRAFT7))
        unreliable_solver.rules = (FakeRule(unreliable_spec, ProofResult.false("x")),)

        endeavor_proof = default_solver.prove_difference_empty(
            {"type": "string"}, {"type": "number"}
        )
        unreliable_proof = unreliable_solver.prove_difference_empty(
            {"type": "string"}, {"type": "number"}
        )

        self.assertEqual(endeavor_proof.status, "unsupported")
        self.assertEqual(endeavor_proof.reason, "fake-endeavor requires endeavor proof")
        self.assertEqual(unreliable_proof.status, "unsupported")
        self.assertEqual(
            unreliable_proof.reason,
            "fake-unreliable is outside the reliable proof fragment",
        )

        endeavor_solver = EmptinessSolver(
            ProofContext(Dialect.DRAFT7, ProofOptions(endeavor=True)),
        )
        endeavor_solver.rules = (FakeRule(endeavor_spec, ProofResult.true()),)
        endeavor_allowed = endeavor_solver.prove_difference_empty(
            {"type": "string"}, {"type": "number"}
        )
        self.assertEqual(endeavor_allowed.status, "proved_true")

    def test_counterexample_certificates_are_verified_before_proved_false(self):
        valid = CounterexampleCertificate(
            "closed-object-property",
            "closed-object property subproof has a certified counterexample",
            path=("x",),
            children=(
                CounterexampleCertificate(
                    "concrete-witness", "validated concrete child witness"
                ),
            ),
        )
        invalid = CounterexampleCertificate(
            "unknown-certificate", "not a supported certificate"
        )
        invalid_child = CounterexampleCertificate(
            "array-inhabitant",
            "array witness construction requires materializing a large array",
            children=(
                CounterexampleCertificate(
                    "concrete-witness", "validated concrete child witness"
                ),
            ),
        )

        self.assertTrue(verify_counterexample_certificate(valid))
        self.assertEqual(ProofResult.certified_false(valid).status, "proved_false")
        self.assertFalse(verify_counterexample_certificate(invalid))
        rejected = ProofResult.certified_false(invalid)
        self.assertEqual(rejected.status, "unsupported")
        self.assertIn("not verifiable", rejected.reason)
        self.assertFalse(verify_counterexample_certificate(invalid_child))

    def test_finite_rhs_witnesses_are_constructed_by_witness_builder(self):
        engine = ProofEngine.for_schemas(
            {"type": "array"}, {"const": []}, dialect=Dialect.DRAFT7
        )

        proof = engine._bounded_ir_proof({"type": "array"}, {"const": []})

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(proof.witness, [None])

    def test_finite_rhs_numeric_witness_uses_numeric_shape(self):
        lhs = {"type": "integer", "minimum": 1}
        rhs = {"enum": [1, 2]}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "finite RHS numeric witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIsInstance(proof.witness, int)
        assert_witness_validates(lhs, rhs, Dialect.DRAFT202012, proof.witness)

    def test_scalar_difference_plans_capture_sat_domain_decisions(self):
        type_formula = DifferenceFormula.from_schemas(
            {"type": "null"}, {"type": "string"}, Dialect.DRAFT7
        )
        self.assertIsInstance(type_formula.lhs.type_constraint, TypeConstraint)
        self.assertEqual(type_formula.lhs.finite_constraint.values, (None,))
        type_plan = type_difference_plan(type_formula.lhs, type_formula.rhs)
        self.assertIsInstance(type_plan, ScalarDifferencePlan)
        self.assertEqual(type_plan.status, "witness")
        self.assertIsNone(type_plan.witness)
        type_problem = DifferenceProblem(type_formula, ProofContext(Dialect.DRAFT7))
        type_constraint_plan = type_difference_plan_from_constraints(
            type_problem.lhs_constraint("type"),
            type_problem.rhs_constraint("type"),
        )
        self.assertEqual(type_constraint_plan, type_plan)
        type_engine = ProofEngine.for_schemas({"type": "null"}, {"type": "string"})
        type_proof = type_engine._bounded_ir_proof({"type": "null"}, {"type": "string"})
        self.assertEqual(type_proof.status, "proved_false")
        self.assertIsNone(type_proof.witness)

        numeric_formula = DifferenceFormula.from_schemas(
            {"type": "integer"}, {"type": "number"}, Dialect.DRAFT7
        )
        self.assertIsInstance(numeric_formula.lhs.numeric_constraint, NumericConstraint)
        self.assertEqual(
            numeric_difference_plan(numeric_formula.lhs, numeric_formula.rhs).status,
            "proved_true",
        )
        self.assertEqual(
            numeric_difference_plan_from_constraints(
                numeric_formula.lhs.numeric_constraint,
                numeric_formula.rhs.numeric_constraint,
            ).status,
            "proved_true",
        )
        numeric_witness_formula = DifferenceFormula.from_schemas(
            {"type": "number", "minimum": 5},
            {"type": "number", "minimum": 6},
            Dialect.DRAFT7,
        )
        with patch.object(
            scalars_module.SymbolicSolver,
            "check_with_work",
            return_value=ProofResult.unsupported(
                "numeric symbolic solver returned unknown"
            ),
        ):
            numeric_plan = numeric_difference_plan_from_constraints(
                numeric_witness_formula.lhs.numeric_constraint,
                numeric_witness_formula.rhs.numeric_constraint,
                context=ProofContext(Dialect.DRAFT7),
            )
        self.assertEqual(numeric_plan.status, "witness")
        self.assertEqual(
            numeric_plan.rejected_reason,
            "SAT numeric witness was rejected by concrete validation",
        )
        self.assertGreaterEqual(numeric_plan.witness, 5)
        self.assertLess(numeric_plan.witness, 6)

        constructive_numeric_formula = DifferenceFormula.from_schemas(
            {"type": "number", "multipleOf": 10},
            {"type": "integer", "minimum": 5},
            Dialect.DRAFT7,
        )

        with patch.object(
            scalars_module.SymbolicSolver,
            "check_with_work",
            side_effect=AssertionError(
                "constructive numeric witness should not require Z3"
            ),
        ):
            constructive_numeric_plan = numeric_difference_plan_from_constraints(
                constructive_numeric_formula.lhs.numeric_constraint,
                constructive_numeric_formula.rhs.numeric_constraint,
                context=ProofContext(Dialect.DRAFT7),
            )

        self.assertEqual(constructive_numeric_plan.status, "witness")
        assert_witness_validates(
            {"type": "number", "multipleOf": 10},
            {"type": "integer", "minimum": 5},
            Dialect.DRAFT7,
            constructive_numeric_plan.witness,
        )

        symbolic_context = ProofContext(Dialect.DRAFT7)
        symbolic_solver = scalars_module.SymbolicSolver(
            symbolic_context,
            "numeric product",
            "numeric product exceeded proof work budget",
        )
        symbolic_value = symbolic_solver.real_var("number")
        symbolic_solver.add(
            symbolic_solver.integer_real(symbolic_value, "lhs_integer"),
            symbolic_solver.le(symbolic_value, symbolic_solver.real_value(5)),
            symbolic_solver.not_(
                symbolic_solver.and_(
                    symbolic_solver.integer_real(symbolic_value, "rhs_integer"),
                    symbolic_solver.le(symbolic_value, symbolic_solver.real_value(10)),
                )
            ),
        )
        self.assertEqual(symbolic_solver.check_with_work(), scalars_module.UNSAT)

        length_formula = DifferenceFormula.from_schemas(
            {"type": "string", "minLength": 2},
            {"type": "string", "minLength": 3},
            Dialect.DRAFT7,
        )
        self.assertIsInstance(
            length_formula.lhs.string_length_constraint, StringLengthConstraint
        )
        self.assertEqual(
            string_length_difference_plan(
                length_formula.lhs, length_formula.rhs
            ).witness,
            "aa",
        )
        self.assertEqual(
            string_length_difference_plan_from_constraints(
                length_formula.lhs.string_length_constraint,
                length_formula.rhs.string_length_constraint,
            ).witness,
            "aa",
        )

        language_formula = DifferenceFormula.from_schemas(
            {"type": "string", "pattern": "^a$"},
            {"type": "string", "pattern": "^b$"},
            Dialect.DRAFT7,
        )
        self.assertIsInstance(
            language_formula.lhs.string_language_constraint, StringLanguageConstraint
        )
        self.assertEqual(
            string_language_difference_plan(
                language_formula.lhs, language_formula.rhs
            ).status,
            "witness",
        )
        self.assertEqual(
            string_language_difference_plan_from_constraints(
                language_formula.lhs.string_language_constraint,
                language_formula.rhs.string_language_constraint,
            ).status,
            "witness",
        )

        finite_formula = DifferenceFormula.from_schemas(
            {"type": "array"}, {"const": []}, Dialect.DRAFT7
        )
        self.assertIsInstance(finite_formula.rhs.finite_constraint, FiniteConstraint)
        finite_plan = finite_rhs_difference_plan(finite_formula.lhs, finite_formula.rhs)
        self.assertIsInstance(finite_plan, FiniteRhsDifferencePlan)
        self.assertEqual(finite_plan.status, "witnesses")
        self.assertIn([None], finite_plan.witnesses)
        self.assertEqual(
            finite_rhs_difference_plan_from_constraints(
                finite_formula.lhs.type_constraint,
                finite_formula.lhs.finite_constraint,
                finite_formula.rhs.finite_constraint,
            ),
            finite_plan,
        )

        self.assertIn(
            "finite_constraint",
            inspect.getsource(scalars_module.finite_rhs_difference_plan),
        )
        self.assertIn(
            "finite_rhs_difference_plan_from_constraints",
            inspect.getsource(scalars_module.finite_rhs_difference_plan),
        )
        self.assertIn(
            "type_constraint", inspect.getsource(scalars_module.type_difference_plan)
        )
        self.assertIn(
            "type_difference_plan_from_constraints",
            inspect.getsource(scalars_module.type_difference_plan),
        )
        self.assertIn(
            "numeric_constraint",
            inspect.getsource(scalars_module.numeric_difference_plan),
        )
        self.assertIn(
            "numeric_difference_plan_from_constraints",
            inspect.getsource(scalars_module.numeric_difference_plan),
        )
        self.assertIn(
            "string_length_constraint",
            inspect.getsource(scalars_module.string_length_difference_plan),
        )
        self.assertIn(
            "string_length_difference_plan_from_constraints",
            inspect.getsource(scalars_module.string_length_difference_plan),
        )
        self.assertIn(
            "string_language_constraint",
            inspect.getsource(scalars_module.string_language_difference_plan),
        )
        self.assertIn(
            "string_language_difference_plan_from_constraints",
            inspect.getsource(scalars_module.string_language_difference_plan),
        )
        self.assertNotIn(
            ".type_shape", inspect.getsource(scalars_module.type_difference_plan)
        )
        self.assertNotIn(
            ".numeric_shape", inspect.getsource(scalars_module.numeric_difference_plan)
        )
        self.assertNotIn(
            ".string_length_shape",
            inspect.getsource(scalars_module.string_length_difference_plan),
        )
        self.assertNotIn(
            ".string_language_shape",
            inspect.getsource(scalars_module.string_language_difference_plan),
        )

    def test_schema_inhabitant_witness_helpers_live_outside_sat(self):
        self.assertEqual(build_schema_witness.__module__, "subschema.kernel.witnesses")
        self.assertEqual(
            finite_projection_witness.__module__, "subschema.kernel.witnesses"
        )
        false_witness = build_schema_witness(False, Dialect.DRAFT7)
        self.assertEqual(false_witness.status, "unsupported")
        string_witness = build_schema_witness({"type": "string"}, Dialect.DRAFT7)
        self.assertTrue(string_witness.has_witness)
        self.assertEqual(string_witness.witness, "")
        const_witness = finite_projection_witness({"const": None}, Dialect.DRAFT7)
        self.assertTrue(const_witness.has_witness)
        self.assertIsNone(const_witness.witness)
        self.assertEqual(
            finite_projection_witness({"const": None}, Dialect.DRAFT4).status,
            "unsupported",
        )
        self.assertEqual(
            finite_projection_witness({"type": "string"}, Dialect.DRAFT7).status,
            "unsupported",
        )

    def test_domain_fragments_reject_boolean_integer_keywords(self):
        self.assertIsNone(
            strings_module.string_shape_for_schema(
                {"type": "string", "minLength": True}
            )
        )
        self.assertIsNone(
            strings_module.string_shape_for_schema(
                {"type": "string", "maxLength": False}
            )
        )
        self.assertIsNone(
            objects_module.object_property_count_shape_for_schema(
                {"minProperties": True}
            )
        )
        self.assertIsNone(
            objects_module.object_property_count_shape_for_schema(
                {"maxProperties": False}
            )
        )

    def test_schema_inhabitant_exclusions_use_json_semantics(self):
        true_not_number = build_schema_witness(
            {"allOf": [{"const": True}, {"not": {"const": 1}}]},
            Dialect.DRAFT7,
        )
        self.assertTrue(true_not_number.has_witness)
        self.assertIs(true_not_number.witness, True)

        object_not_numeric_object = build_schema_witness(
            {
                "allOf": [
                    {
                        "type": "object",
                        "properties": {"x": {"const": True}},
                        "required": ["x"],
                    },
                    {"not": {"enum": [{"x": 1}]}},
                ]
            },
            Dialect.DRAFT7,
        )
        self.assertTrue(object_not_numeric_object.has_witness)
        self.assertEqual(object_not_numeric_object.witness, {"x": True})

    def test_schema_inhabitant_negated_object_branch_keeps_dialect(self):
        object_not_array = build_schema_witness(
            {
                "allOf": [
                    {
                        "type": "object",
                        "properties": {"x": {"const": True}},
                        "required": ["x"],
                    },
                    {"not": {"type": "array"}},
                ]
            },
            Dialect.DRAFT7,
        )
        self.assertTrue(object_not_array.has_witness)
        self.assertEqual(object_not_array.witness, {"x": True})

    def test_composite_difference_models_capture_object_and_array_search_space(self):
        lhs_array = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": {"type": "string"},
            "contains": {"type": "string"},
            "minItems": 3,
            "minContains": 1,
            "maxContains": 3,
        }
        rhs_array = {
            "type": "array",
            "prefixItems": [{"type": "integer"}, {"type": "string"}],
            "items": False,
        }
        array_formula = DifferenceFormula.from_schemas(
            lhs_array, rhs_array, Dialect.DRAFT202012
        )
        array_problem = DifferenceProblem(
            array_formula, ProofEngine(Dialect.DRAFT202012).context
        )
        array_model = ArrayDifferenceModel.from_problem(array_problem)

        self.assertEqual(
            [(slot.index, slot.source) for slot in array_model.lhs_slots],
            [(0, "prefixItems")],
        )
        self.assertEqual(array_model.lhs_tail.start_index, 1)
        self.assertEqual(array_model.lhs_tail.source, "items")
        self.assertEqual(array_model.rhs_tail.start_index, 2)
        self.assertTrue(array_model.rhs_tail.closed)
        self.assertEqual(array_model.lhs_contains.minimum, 1)
        self.assertEqual(array_model.lhs_contains.maximum, 3)
        self.assertTrue(array_model.lhs_contains.marks_evaluated)
        tail_lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": {"type": "string"},
            "minItems": 3,
        }
        tail_rhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}, {"type": "string"}],
            "items": False,
        }
        tail_formula = DifferenceFormula.from_schemas(
            tail_lhs, tail_rhs, Dialect.DRAFT202012
        )
        tail_model = ArrayDifferenceModel.from_irs(tail_formula.lhs, tail_formula.rhs)
        length_formula = DifferenceFormula.from_schemas(
            {"type": "array", "minItems": 3},
            {"type": "array", "maxItems": 2},
            Dialect.DRAFT202012,
        )
        length_problem = DifferenceProblem(
            length_formula, ProofEngine(Dialect.DRAFT202012).context
        )
        length_model = ArrayDifferenceModel.from_problem(length_problem)
        self.assertIs(length_model.problem, length_problem)
        self.assertIsNotNone(length_model.lhs_length)
        self.assertIsNotNone(length_model.rhs_length)
        self.assertIsNotNone(length_model.rhs_length_with_item_values)
        length_plan = length_model.length_difference_plan()
        self.assertIsInstance(length_plan, ArrayLengthDifferencePlan)
        self.assertEqual(length_plan.status, "witness")
        self.assertEqual(
            materialize_array_witness_skeleton(
                length_plan.witness_skeleton, Dialect.DRAFT202012
            ),
            [None, None, None],
        )
        with patch.object(
            difference_module.SymbolicSolver,
            "check_with_work",
            return_value=ProofResult.unsupported(
                "array symbolic solver returned unknown"
            ),
        ):
            length_plan = length_model.length_difference_plan()
        self.assertEqual(length_plan.status, "witness")
        contains_constraint = ArrayContainsConstraint(
            {"type": "string"}, 1, 3, marks_evaluated=True
        )
        contains_min_plan = tail_model.contains_min_violation_plan(contains_constraint)
        contains_max_plan = tail_model.contains_max_violation_plan(contains_constraint)
        self.assertIsInstance(contains_min_plan, ArrayContainsMinViolationPlan)
        self.assertIsInstance(contains_max_plan, ArrayContainsMaxViolationPlan)
        self.assertTrue(
            all(
                isinstance(item, ArrayContainsItemProof)
                for item in contains_min_plan.item_proofs
            )
        )
        self.assertEqual(contains_min_plan.length, 3)
        self.assertEqual(contains_max_plan.target_matches, 4)
        contains_min_witness_plan = tail_model.contains_min_violation_witness_plan(
            ArrayContainsConstraint({"type": "number"}, 2, 3, marks_evaluated=True),
            ProofEngine(Dialect.DRAFT202012).context,
        )
        self.assertIsInstance(contains_min_witness_plan, ArrayWitnessPlan)
        self.assertIsInstance(contains_min_witness_plan.skeleton, ArrayWitnessSkeleton)
        self.assertTrue(
            all(
                isinstance(override, ArrayWitnessOverride)
                for override in contains_min_witness_plan.overrides
            )
        )
        contains_max_witness_plan = tail_model.contains_max_violation_witness_plan(
            ArrayContainsConstraint(True, 0, 1, marks_evaluated=True),
            ProofEngine(Dialect.DRAFT202012).context,
        )
        self.assertIsInstance(contains_max_witness_plan, ArrayWitnessPlan)
        self.assertIsInstance(contains_max_witness_plan.skeleton, ArrayWitnessSkeleton)
        contains_difference_formula = DifferenceFormula.from_schemas(
            {"type": "array", "maxItems": 0},
            {"type": "array", "contains": True, "minContains": 1},
            Dialect.DRAFT202012,
        )
        contains_difference_model = ArrayDifferenceModel.from_irs(
            contains_difference_formula.lhs,
            contains_difference_formula.rhs,
        )
        contains_difference_plan = contains_difference_model.contains_difference_plan(
            ProofEngine(Dialect.DRAFT202012).context,
        )
        self.assertIsInstance(contains_difference_plan, ArrayContainsDifferencePlan)
        self.assertEqual(contains_difference_plan.status, "witness")
        self.assertEqual(contains_difference_plan.witness, [])
        unevaluated_witness_formula = DifferenceFormula.from_schemas(
            {"type": "array", "minItems": 1},
            {"type": "array", "unevaluatedItems": False},
            Dialect.DRAFT202012,
        )
        unevaluated_witness_model = ArrayDifferenceModel.from_irs(
            unevaluated_witness_formula.lhs,
            unevaluated_witness_formula.rhs,
        )
        unevaluated_witness_plan = (
            unevaluated_witness_model.unevaluated_items_difference_plan()
        )
        self.assertIsInstance(
            unevaluated_witness_plan, ArrayUnevaluatedItemsDifferencePlan
        )
        self.assertEqual(unevaluated_witness_plan.status, "witness")
        self.assertIsInstance(
            unevaluated_witness_plan.witness_skeleton, ArrayWitnessSkeleton
        )
        unevaluated_obligation_formula = DifferenceFormula.from_schemas(
            {"type": "array", "prefixItems": [{"type": "integer"}], "maxItems": 1},
            {
                "type": "array",
                "prefixItems": [{"type": "number"}],
                "unevaluatedItems": False,
            },
            Dialect.DRAFT202012,
        )
        unevaluated_obligation_model = ArrayDifferenceModel.from_irs(
            unevaluated_obligation_formula.lhs,
            unevaluated_obligation_formula.rhs,
        )
        unevaluated_obligation_plan = (
            unevaluated_obligation_model.unevaluated_items_difference_plan()
        )
        self.assertEqual(unevaluated_obligation_plan.status, "obligations")
        self.assertTrue(
            all(
                isinstance(obligation, ArrayUnevaluatedItemObligation)
                for obligation in unevaluated_obligation_plan.obligations
            )
        )
        array_skeleton = tail_model.array_witness_skeleton(3)
        self.assertIsInstance(array_skeleton, ArrayWitnessSkeleton)
        self.assertTrue(
            all(isinstance(slot, ArrayWitnessSlot) for slot in array_skeleton.slots)
        )
        self.assertEqual(
            [(slot.index, slot.schema) for slot in array_skeleton.slots],
            [
                (0, {"type": "integer"}),
                (1, {"type": "string"}),
                (2, {"type": "string"}),
            ],
        )
        materialized_array = materialize_array_witness_skeleton(
            array_skeleton, Dialect.DRAFT202012
        )
        self.assertEqual(len(materialized_array), 3)
        self.assertIs(type(materialized_array[0]), int)
        self.assertIsInstance(materialized_array[1], str)
        materialized_plan = materialize_array_witness_plan(
            ArrayWitnessPlan(array_skeleton, (ArrayWitnessOverride(1, "override"),)),
            Dialect.DRAFT202012,
        )
        self.assertEqual(materialized_plan[1], "override")
        materialized_duplicate = materialize_array_duplicate_witness_plan(
            ArrayDuplicateWitnessPlan(
                ArrayWitnessSkeleton(
                    2,
                    (
                        ArrayWitnessSlot(0, True),
                        ArrayWitnessSlot(1, True),
                    ),
                ),
                0,
                1,
                {"const": "duplicate"},
            ),
            Dialect.DRAFT202012,
        )
        self.assertEqual(materialized_duplicate, ["duplicate", "duplicate"])
        self.assertEqual(tail_model.first_lhs_array_length(), 3)
        self.assertTrue(tail_model.lhs_allows_length(3))
        self.assertFalse(tail_model.lhs_allows_length(2))
        self.assertIsInstance(
            tail_model.first_lhs_array_witness_skeleton(), ArrayWitnessSkeleton
        )
        self.assertIsInstance(
            tail_model.array_witness_skeleton_reaching(2), ArrayWitnessSkeleton
        )
        self.assertIsInstance(
            tail_model.array_witness_skeleton_for_length_witness([None, None, None]),
            ArrayWitnessSkeleton,
        )
        duplicate_plan = tail_model.uniqueness_duplicate_witness_plan()
        self.assertIsInstance(duplicate_plan, ArrayDuplicateWitnessPlan)
        self.assertIsInstance(duplicate_plan.skeleton, ArrayWitnessSkeleton)
        self.assertEqual(
            (duplicate_plan.first_index, duplicate_plan.second_index), (1, 2)
        )
        self.assertEqual(
            duplicate_plan.duplicate_schema,
            {"type": "string"},
        )
        uniqueness_formula = DifferenceFormula.from_schemas(
            {"type": "array", "minItems": 2},
            {"type": "array", "uniqueItems": True},
            Dialect.DRAFT202012,
        )
        uniqueness_model = ArrayDifferenceModel.from_irs(
            uniqueness_formula.lhs,
            uniqueness_formula.rhs,
        )
        uniqueness_plan = uniqueness_model.uniqueness_difference_plan()
        self.assertIsInstance(uniqueness_plan, ArrayUniquenessDifferencePlan)
        self.assertEqual(uniqueness_plan.status, "duplicate_witness")
        self.assertIsInstance(uniqueness_plan.duplicate_plan, ArrayDuplicateWitnessPlan)
        array_obligations = tail_model.item_value_obligations()
        self.assertTrue(tail_model.has_rhs_item_value_constraints())
        self.assertEqual(tail_model.rhs_closed_tail_violation_length(), 3)
        self.assertIsInstance(
            tail_model.rhs_closed_tail_violation_skeleton(), ArrayWitnessSkeleton
        )
        self.assertTrue(
            all(
                isinstance(obligation, ArrayItemValueObligation)
                for obligation in array_obligations
            )
        )
        self.assertEqual(
            [(obligation.index, obligation.source) for obligation in array_obligations],
            [(0, "rhs-slot"), (1, "rhs-slot")],
        )
        item_values_plan = tail_model.item_values_difference_plan(Dialect.DRAFT202012)
        self.assertIsInstance(item_values_plan, ArrayItemValuesDifferencePlan)
        self.assertEqual(item_values_plan.status, "witness")
        self.assertIsInstance(item_values_plan.witness_skeleton, ArrayWitnessSkeleton)

        item_values_formula = DifferenceFormula.from_schemas(
            {"type": "array", "items": {"type": "integer"}},
            {"type": "array", "items": {"type": "number"}},
            Dialect.DRAFT202012,
        )
        item_values_model = ArrayDifferenceModel.from_irs(
            item_values_formula.lhs,
            item_values_formula.rhs,
        )
        item_values_plan = item_values_model.item_values_difference_plan(
            Dialect.DRAFT202012
        )
        self.assertEqual(item_values_plan.status, "obligations")
        self.assertTrue(
            all(
                isinstance(obligation, ArrayItemValueObligation)
                for obligation in item_values_plan.obligations
            )
        )

        lhs_object = {
            "type": "object",
            "properties": {"alpha": {"type": "integer"}},
            "required": ["alpha"],
            "additionalProperties": False,
        }
        rhs_object = {
            "type": "object",
            "properties": {"beta": True},
            "patternProperties": {"^x": {"type": "string"}},
            "dependentSchemas": {"gamma": {"required": ["delta"]}},
        }
        object_formula = DifferenceFormula.from_schemas(
            lhs_object, rhs_object, Dialect.DRAFT202012
        )
        object_problem = DifferenceProblem(
            object_formula, ProofEngine(Dialect.DRAFT202012).context
        )
        object_model = ObjectDifferenceModel.from_problem(object_problem)

        self.assertEqual(
            object_model.universe.explicit_names,
            frozenset({"alpha", "beta", "gamma"}),
        )
        self.assertEqual(object_model.universe.pattern_names, frozenset({"^x"}))
        self.assertTrue(object_model.universe.lhs_closed_world)
        self.assertFalse(object_model.universe.rhs_closed_world)
        self.assertTrue(object_model.universe.has_fresh_class)
        self.assertNotIn(
            object_model.universe.fresh.representative,
            object_model.universe.explicit_names,
        )
        self.assertIsInstance(object_model.lhs_key_values, ObjectKeyValueShape)
        self.assertEqual(
            object_model.lhs_key_values.properties["alpha"], {"type": "integer"}
        )
        self.assertFalse(object_model.lhs_key_values.additional_schema)
        object_skeleton = object_model.lhs_key_values.witness_skeleton("alpha")
        self.assertIsInstance(object_skeleton, ObjectKeyValueWitnessSkeleton)
        self.assertTrue(
            all(
                isinstance(slot, ObjectKeyValueWitnessSlot)
                for slot in object_skeleton.slots
            )
        )
        self.assertEqual(
            [(slot.name, slot.schema) for slot in object_skeleton.slots],
            [
                ("alpha", {"type": "integer"}),
            ],
        )
        materialized_object = materialize_object_key_value_witness_skeleton(
            object_skeleton, Dialect.DRAFT202012
        )
        self.assertEqual(set(materialized_object), {"alpha"})
        self.assertIs(type(materialized_object["alpha"]), int)
        materialized_object_override = materialize_object_key_value_witness_skeleton(
            object_skeleton,
            Dialect.DRAFT202012,
            override=("alpha", 42),
        )
        self.assertEqual(materialized_object_override, {"alpha": 42})
        count_formula = DifferenceFormula.from_schemas(
            {"type": "object", "minProperties": 3},
            {"type": "object", "maxProperties": 2},
            Dialect.DRAFT202012,
        )
        count_problem = DifferenceProblem(
            count_formula, ProofEngine(Dialect.DRAFT202012).context
        )
        count_model = ObjectDifferenceModel.from_problem(count_problem)
        self.assertIs(count_model.problem, count_problem)
        self.assertIsNotNone(count_model.lhs_property_count)
        self.assertIsNotNone(count_model.rhs_property_count)
        count_plan = count_model.property_count_difference_plan()
        self.assertIsInstance(count_plan, ObjectPropertyCountDifferencePlan)
        self.assertEqual(count_plan.status, "witness")
        self.assertEqual(count_plan.witness, {"k0": None, "k1": None, "k2": None})
        with patch.object(
            difference_module.SymbolicSolver,
            "check_with_work",
            return_value=ProofResult.unsupported(
                "object symbolic solver returned unknown"
            ),
        ):
            count_plan = count_model.property_count_difference_plan()
        self.assertEqual(count_plan.status, "witness")
        self.assertEqual(count_plan.witness, {"k0": None, "k1": None, "k2": None})
        unevaluated_property_witness_formula = DifferenceFormula.from_schemas(
            {"type": "object"},
            {"type": "object", "unevaluatedProperties": False},
            Dialect.DRAFT202012,
        )
        unevaluated_property_witness_model = ObjectDifferenceModel.from_irs(
            unevaluated_property_witness_formula.lhs,
            unevaluated_property_witness_formula.rhs,
        )
        unevaluated_property_witness_plan = (
            unevaluated_property_witness_model.unevaluated_properties_difference_plan()
        )
        self.assertIsInstance(
            unevaluated_property_witness_plan, ObjectUnevaluatedPropertiesDifferencePlan
        )
        self.assertEqual(unevaluated_property_witness_plan.status, "witness")
        self.assertTrue(unevaluated_property_witness_plan.witness_skeletons)
        unevaluated_property_obligation_formula = DifferenceFormula.from_schemas(
            {
                "type": "object",
                "properties": {"foo": {"type": "number"}},
                "additionalProperties": False,
            },
            {
                "type": "object",
                "allOf": [{"properties": {"foo": {"type": "string"}}}],
                "unevaluatedProperties": False,
            },
            Dialect.DRAFT202012,
        )
        unevaluated_property_obligation_model = ObjectDifferenceModel.from_irs(
            unevaluated_property_obligation_formula.lhs,
            unevaluated_property_obligation_formula.rhs,
        )
        unevaluated_property_obligation_plan = unevaluated_property_obligation_model.unevaluated_properties_difference_plan()
        self.assertEqual(unevaluated_property_obligation_plan.status, "obligations")
        self.assertTrue(
            all(
                isinstance(obligation, ObjectUnevaluatedPropertyObligation)
                for obligation in unevaluated_property_obligation_plan.obligations
            )
        )
        kv_lhs = {
            "type": "object",
            "patternProperties": {"^x": {"type": "number"}},
        }
        kv_rhs = {
            "type": "object",
            "patternProperties": {"^x": {"type": "string"}},
        }
        kv_formula = DifferenceFormula.from_schemas(kv_lhs, kv_rhs, Dialect.DRAFT202012)
        kv_model = ObjectDifferenceModel.from_irs(kv_formula.lhs, kv_formula.rhs)
        self.assertIsInstance(kv_model.lhs_key_values, ObjectKeyValueShape)
        self.assertIsInstance(kv_model.rhs_key_values, ObjectKeyValueShape)
        self.assertEqual(kv_model.rhs_key_values.pattern_texts(), frozenset({"^x"}))
        self.assertTrue(
            kv_model.rhs_key_values.allows_key(kv_model.universe.fresh.representative)
        )
        obligations = kv_model.key_value_obligations(budget=12)
        self.assertTrue(obligations)
        self.assertTrue(
            all(
                isinstance(obligation, ObjectKeyValueObligation)
                for obligation in obligations
            )
        )
        self.assertTrue(
            any(obligation.name.startswith("x") for obligation in obligations)
        )
        kv_plan = kv_model.key_value_difference_plan(budget=12)
        self.assertIsInstance(kv_plan, ObjectKeyValueDifferencePlan)
        self.assertEqual(kv_plan.status, "obligations")
        self.assertEqual(kv_plan.obligations, obligations)

        kv_witness_formula = DifferenceFormula.from_schemas(
            {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
            {"type": "string", "additionalProperties": False},
            Dialect.DRAFT202012,
        )
        kv_witness_model = ObjectDifferenceModel.from_irs(
            kv_witness_formula.lhs,
            kv_witness_formula.rhs,
        )
        kv_witness_plan = kv_witness_model.key_value_difference_plan(budget=12)
        self.assertEqual(kv_witness_plan.status, "witness")
        self.assertIsInstance(
            kv_witness_plan.witness_skeleton, ObjectKeyValueWitnessSkeleton
        )

        presence_lhs = {"type": "object", "required": ["alpha"], "maxProperties": 1}
        presence_rhs = {
            "type": "object",
            "dependentRequired": {"alpha": ["beta"]},
            "maxProperties": 2,
        }
        presence_formula = DifferenceFormula.from_schemas(
            presence_lhs, presence_rhs, Dialect.DRAFT202012
        )
        presence_problem = DifferenceProblem(
            presence_formula, ProofEngine(Dialect.DRAFT202012).context
        )
        presence_model = ObjectDifferenceModel.from_problem(presence_problem)
        presence_plan = presence_model.presence_product_plan(budget=12)
        self.assertIsInstance(presence_plan, ObjectPresenceProductPlan)
        self.assertEqual(presence_plan.status, "ready")
        self.assertTrue(
            all(
                isinstance(plan, ObjectPresenceWitnessPlan)
                for plan in presence_plan.witness_plans
            )
        )
        self.assertTrue(
            any(
                plan.present == frozenset({"alpha"})
                for plan in presence_plan.witness_plans
            )
        )

        value_lhs = {
            "type": "object",
            "properties": {"foo": {"type": "integer"}},
            "required": ["foo"],
        }
        value_rhs = {
            "type": "object",
            "properties": {"foo": {"type": "number"}, "bar": True},
        }
        value_formula = DifferenceFormula.from_schemas(
            value_lhs, value_rhs, Dialect.DRAFT202012
        )
        value_problem = DifferenceProblem(
            value_formula, ProofEngine(Dialect.DRAFT202012).context
        )
        value_model = ObjectDifferenceModel.from_problem(value_problem)
        self.assertIsNotNone(value_model.lhs_property_values)
        self.assertIsNotNone(value_model.rhs_property_values)
        value_obligations = value_model.property_value_obligations()
        self.assertTrue(
            all(
                isinstance(obligation, ObjectPropertyValueObligation)
                for obligation in value_obligations
            )
        )
        self.assertEqual(
            [
                (obligation.name, obligation.lhs_schema, obligation.rhs_schema)
                for obligation in value_obligations
            ],
            [("foo", {"type": "integer"}, {"type": "number"})],
        )
        value_skeleton = value_model.property_values_witness_skeleton("foo")
        self.assertIsInstance(value_skeleton, ObjectPropertyValueWitnessSkeleton)
        self.assertTrue(
            all(
                isinstance(slot, ObjectPropertyValueWitnessSlot)
                for slot in value_skeleton.slots
            )
        )
        self.assertEqual(
            [(slot.name, slot.schema) for slot in value_skeleton.slots],
            [("foo", {"type": "integer"})],
        )
        materialized_value = materialize_object_property_value_witness_skeleton(
            value_skeleton,
            Dialect.DRAFT202012,
        )
        self.assertEqual(set(materialized_value), {"foo"})
        self.assertIs(type(materialized_value["foo"]), int)
        materialized_value_override = (
            materialize_object_property_value_witness_skeleton(
                value_skeleton,
                Dialect.DRAFT202012,
                override=("foo", 7),
            )
        )
        self.assertEqual(materialized_value_override, {"foo": 7})
        value_plan = value_model.property_values_difference_plan()
        self.assertIsInstance(value_plan, ObjectPropertyValuesDifferencePlan)
        self.assertEqual(value_plan.status, "obligations")
        self.assertEqual(value_plan.obligations, value_obligations)

        value_witness_formula = DifferenceFormula.from_schemas(
            value_lhs,
            {"type": "string"},
            Dialect.DRAFT202012,
        )
        value_witness_model = ObjectDifferenceModel.from_irs(
            value_witness_formula.lhs,
            value_witness_formula.rhs,
        )
        value_witness_plan = value_witness_model.property_values_difference_plan()
        self.assertEqual(value_witness_plan.status, "witness")
        self.assertIsInstance(
            value_witness_plan.witness_skeleton, ObjectPropertyValueWitnessSkeleton
        )

        closed_lhs = {
            "type": "object",
            "properties": {
                "foo": {"type": "integer"},
                "bar": {"type": "string"},
            },
            "required": ["foo"],
            "additionalProperties": False,
        }
        closed_rhs = {
            "type": "object",
            "properties": {"foo": {"type": "number"}},
            "additionalProperties": False,
        }
        closed_formula = DifferenceFormula.from_schemas(
            closed_lhs, closed_rhs, Dialect.DRAFT202012
        )
        closed_problem = DifferenceProblem(
            closed_formula, ProofEngine(Dialect.DRAFT202012).context
        )
        closed_model = ObjectDifferenceModel.from_problem(closed_problem)
        self.assertIsNotNone(closed_model.lhs_closed_properties)
        self.assertIsNotNone(closed_model.rhs_closed_properties)
        closed_obligations = closed_model.closed_object_value_obligations()
        self.assertTrue(
            all(
                isinstance(obligation, ClosedObjectValueObligation)
                for obligation in closed_obligations
            )
        )
        self.assertEqual(
            [
                (obligation.name, obligation.lhs_schema, obligation.rhs_schema)
                for obligation in closed_obligations
            ],
            [("foo", {"type": "integer"}, {"type": "number"})],
        )
        closed_skeleton = closed_model.closed_object_witness_skeleton("foo")
        self.assertIsInstance(closed_skeleton, ClosedObjectWitnessSkeleton)
        self.assertTrue(
            all(
                isinstance(slot, ClosedObjectWitnessSlot)
                for slot in closed_skeleton.slots
            )
        )
        self.assertEqual(
            [(slot.name, slot.schema) for slot in closed_skeleton.slots],
            [("foo", {"type": "integer"})],
        )
        materialized_closed = materialize_closed_object_witness_skeleton(
            closed_skeleton, Dialect.DRAFT202012
        )
        self.assertEqual(set(materialized_closed), {"foo"})
        self.assertIs(type(materialized_closed["foo"]), int)
        materialized_closed_override = materialize_closed_object_witness_skeleton(
            closed_skeleton,
            Dialect.DRAFT202012,
            override=("foo", 11),
        )
        self.assertEqual(materialized_closed_override, {"foo": 11})
        keyspace_skeleton = closed_model.closed_object_keyspace_witness_skeleton()
        self.assertIsInstance(keyspace_skeleton, ClosedObjectWitnessSkeleton)
        self.assertEqual(
            [(slot.name, slot.schema) for slot in keyspace_skeleton.slots],
            [
                ("bar", {"type": "string"}),
                ("foo", {"type": "integer"}),
            ],
        )
        closed_plan = closed_model.closed_object_difference_plan()
        self.assertIsInstance(closed_plan, ClosedObjectDifferencePlan)
        self.assertEqual(closed_plan.status, "witness")
        self.assertIsInstance(closed_plan.witness_skeleton, ClosedObjectWitnessSkeleton)

        closed_obligation_formula = DifferenceFormula.from_schemas(
            {
                "type": "object",
                "properties": {"foo": {"type": "integer"}},
                "required": ["foo"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"foo": {"type": "number"}},
                "required": ["foo"],
                "additionalProperties": False,
            },
            Dialect.DRAFT202012,
        )
        closed_obligation_model = ObjectDifferenceModel.from_irs(
            closed_obligation_formula.lhs,
            closed_obligation_formula.rhs,
        )
        closed_obligation_plan = closed_obligation_model.closed_object_difference_plan()
        self.assertEqual(closed_obligation_plan.status, "obligations")
        self.assertTrue(
            all(
                isinstance(obligation, ClosedObjectValueObligation)
                for obligation in closed_obligation_plan.obligations
            )
        )

        names_repair_lhs = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
            "properties": {"a": {"type": "integer"}},
        }
        names_repair_rhs = {
            "type": "object",
            "propertyNames": {"pattern": "^b"},
        }
        names_repair_formula = DifferenceFormula.from_schemas(
            names_repair_lhs,
            names_repair_rhs,
            Dialect.DRAFT202012,
        )
        names_repair_model = ObjectDifferenceModel.from_irs(
            names_repair_formula.lhs,
            names_repair_formula.rhs,
        )
        repair_skeleton = names_repair_model.property_names_repair_skeleton({"a": None})
        self.assertIsInstance(repair_skeleton, ObjectPropertyNamesRepairSkeleton)
        self.assertTrue(
            all(
                isinstance(slot, ObjectPropertyNamesRepairSlot)
                for slot in repair_skeleton.slots
            )
        )
        self.assertEqual(
            [
                (slot.name, slot.schema, slot.original_value)
                for slot in repair_skeleton.slots
            ],
            [("a", {"type": "integer"}, None)],
        )
        names_plan = names_repair_model.property_names_difference_plan()
        self.assertIsInstance(names_plan, ObjectPropertyNamesDifferencePlan)
        self.assertEqual(names_plan.status, "witness")
        self.assertEqual(names_plan.witness, {"a": None})
        self.assertIsInstance(
            names_plan.repair_skeleton, ObjectPropertyNamesRepairSkeleton
        )
        materialized_repair = materialize_object_property_names_repair_skeleton(
            names_plan.repair_skeleton,
            Dialect.DRAFT202012,
        )
        self.assertEqual(set(materialized_repair), {"a"})
        self.assertIs(type(materialized_repair["a"]), int)

        names_true_formula = DifferenceFormula.from_schemas(
            {"type": "object", "propertyNames": {"pattern": "^a"}},
            {"type": "object", "propertyNames": {"pattern": "^a"}},
            Dialect.DRAFT202012,
        )
        names_true_problem = DifferenceProblem(
            names_true_formula, ProofEngine(Dialect.DRAFT202012).context
        )
        names_true_model = ObjectDifferenceModel.from_problem(names_true_problem)
        self.assertIsNotNone(names_true_model.lhs_property_names)
        self.assertIsNotNone(names_true_model.rhs_property_names)
        self.assertEqual(
            names_true_model.property_names_difference_plan().status, "proved_true"
        )

    def test_array_difference_rule_runs_before_array_exact_tactics_and_generic_search_path(
        self,
    ):
        lhs = {"type": "array", "minItems": 2}
        rhs = {"type": "array", "minItems": 1}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "array difference rule should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_static_reference_rule_proves_root_lhs_ref_with_modern_kernel_or_generic_search_path(
        self,
    ):
        lhs = {
            "definitions": {"name": {"type": "string"}},
            "$ref": "#/definitions/name",
        }
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "static reference rule should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_static_reference_rule_validates_rhs_ref_counterexample_with_modern_kernel(
        self,
    ):
        lhs = {"const": -1}
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"positive": {"type": "integer", "minimum": 0}},
            "$ref": "#/$defs/positive",
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(proof.witness, -1)

    def test_static_reference_rule_follows_acyclic_pure_ref_chains_with_modern_kernel(
        self,
    ):
        lhs = {
            "definitions": {
                "alias": {"$ref": "#/definitions/name"},
                "name": {"type": "string"},
            },
            "$ref": "#/definitions/alias",
        }
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "static reference chain rule should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

        formula = DifferenceFormula.from_schemas(lhs, rhs, Dialect.DRAFT7)
        resolution = references_module.root_static_reference_resolution(
            formula.lhs, side="lhs"
        )
        self.assertIsInstance(resolution, references_module.ReferenceResolution)
        self.assertEqual(resolution.ref, "#/definitions/name")
        self.assertEqual(resolution.pointer, ("definitions", "name"))
        self.assertEqual(resolution.schema, {"type": "string"})

    def test_static_reference_chain_reports_recursive_boundary_in_reference_layer(self):
        lhs = {
            "definitions": {
                "alias": {"$ref": "#/definitions/alias"},
            },
            "$ref": "#/definitions/alias",
        }
        formula = DifferenceFormula.from_schemas(
            lhs, {"type": "string"}, Dialect.DRAFT7
        )

        resolution = references_module.root_static_reference_resolution(
            formula.lhs, side="lhs"
        )

        self.assertIsInstance(resolution, references_module.StaticReferenceUnsupported)
        self.assertIn("recursive lhs $ref", resolution.reason)
        self.assertEqual(resolution.category, "recursive-reference")
        self.assertEqual(resolution.path, ("definitions", "alias", "$ref"))

    def test_static_reference_rule_rejects_dialect_transition_before_subproof(self):
        lhs = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": {
                "target": {
                    "$schema": "http://json-schema.org/draft-04/schema#",
                    "type": "string",
                },
            },
            "$ref": "#/definitions/target",
        }
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "unsupported")
        self.assertIn("dialect transition in lhs target", proof.reason)
        self.assertEqual(proof.diagnostics[0].category, "static-reference")
        self.assertEqual(proof.diagnostics[0].path, ("$ref",))

    def test_static_reference_validation_accepts_embedded_dialect_tuple_schema(self):
        lhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "draft7_tuple": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "items": [{"type": "integer"}],
                    "additionalItems": False,
                },
            },
            "$ref": "#/$defs/draft7_tuple",
        }
        rhs = {"type": "array", "maxItems": 1}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "unsupported")
        self.assertIn("dialect transition in lhs target", proof.reason)

    def test_static_reference_dialect_transition_can_still_be_refuted_by_validated_witness(
        self,
    ):
        lhs = True
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "target": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "const": 1,
                },
            },
            "$ref": "#/$defs/target",
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertNotEqual(proof.witness, 1)

    def test_static_reference_rule_reports_nested_reference_diagnostic(self):
        lhs = {
            "definitions": {
                "alias": {
                    "allOf": [{"$ref": "#/definitions/name"}],
                },
                "name": {"type": "string"},
            },
            "$ref": "#/definitions/alias",
        }
        engine = ProofEngine.for_schemas(
            lhs, {"type": "string"}, dialect=Dialect.DRAFT7
        )

        proof = engine._bounded_ir_proof(lhs, {"type": "string"})

        self.assertEqual(proof.status, "unsupported")
        self.assertIn("nested references in lhs target", proof.reason)
        self.assertEqual(proof.diagnostics[0].category, "static-reference")
        self.assertEqual(
            proof.diagnostics[0].path, ("definitions", "alias", "allOf", "0", "$ref")
        )

    def test_left_applicator_branch_resolves_static_ref_child_with_modern_kernel(self):
        lhs = {
            "definitions": {"name": {"type": "string"}},
            "allOf": [{"$ref": "#/definitions/name"}],
        }
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "left applicator static ref branch should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_left_applicator_branch_reports_static_ref_boundary_diagnostic(self):
        lhs = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": {
                "target": {
                    "$schema": "http://json-schema.org/draft-04/schema#",
                    "type": "string",
                },
            },
            "allOf": [{"$ref": "#/definitions/target"}],
        }
        engine = ProofEngine.for_schemas(
            lhs, {"type": "string"}, dialect=Dialect.DRAFT7
        )

        proof = engine.is_subschema(lhs, {"type": "string"})

        self.assertEqual(proof.status, "unsupported")
        self.assertEqual(proof.diagnostics[0].category, "static-reference")
        self.assertEqual(proof.diagnostics[0].path, ("allOf", "0", "$ref"))

    def test_left_anyof_with_sibling_base_proves_branch_products_with_modern_kernel(
        self,
    ):
        lhs = {"type": "string", "anyOf": [{"maxLength": 3}, {"pattern": "^a"}]}
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "left anyOf formula product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_left_oneof_with_sibling_base_proves_branch_products_with_modern_kernel(
        self,
    ):
        lhs = {"type": "string", "oneOf": [{"maxLength": 3}, {"pattern": "^a"}]}
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "left oneOf formula product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_left_anyof_sibling_base_resolves_static_ref_child_with_modern_kernel(self):
        lhs = {
            "type": "string",
            "definitions": {"name": {"type": "string"}},
            "anyOf": [{"$ref": "#/definitions/name"}],
        }
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "left anyOf static ref product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_left_allof_sibling_base_resolves_static_ref_child_with_modern_kernel(self):
        lhs = {
            "type": "string",
            "definitions": {"name": {"type": "string"}},
            "allOf": [{"$ref": "#/definitions/name"}],
        }
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "left allOf static ref product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_left_anyof_sibling_base_counterexample_is_validated_with_modern_kernel(
        self,
    ):
        lhs = {"type": "integer", "anyOf": [{"type": "number"}]}
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "left anyOf base witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        assert_witness_validates(lhs, rhs, Dialect.DRAFT7, proof.witness)

    def test_right_applicator_branches_resolve_static_ref_children_with_modern_kernel(
        self,
    ):
        lhs = {"type": "string"}
        branch = {"$ref": "#/definitions/name"}
        schemas = (
            {"definitions": {"name": {"type": "string"}}, "allOf": [branch]},
            {"definitions": {"name": {"type": "string"}}, "anyOf": [branch]},
            {
                "definitions": {"name": {"type": "string"}},
                "oneOf": [branch, {"type": "number"}],
            },
        )

        for rhs in schemas:
            with self.subTest(rhs=rhs):
                engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

                proof = engine.is_subschema(lhs, rhs)

                self.assertEqual(proof.status, "proved_true")

    def test_right_applicator_branch_reports_static_ref_boundary_diagnostic(self):
        lhs = {"type": "string"}
        rhs = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": {
                "target": {
                    "$schema": "http://json-schema.org/draft-04/schema#",
                    "type": "string",
                },
            },
            "allOf": [{"$ref": "#/definitions/target"}],
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "unsupported")
        self.assertEqual(proof.diagnostics[0].category, "static-reference")
        self.assertEqual(proof.diagnostics[0].side, "rhs")
        self.assertEqual(proof.diagnostics[0].path, ("allOf", "0", "$ref"))

    def test_right_anyof_with_sibling_base_proves_formula_product_with_modern_kernel(
        self,
    ):
        lhs = {"type": "string", "maxLength": 3}
        rhs = {"type": "string", "anyOf": [{"maxLength": 5}, {"pattern": "^a"}]}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right anyOf formula product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_right_anyof_sibling_base_counterexample_is_validated_with_modern_kernel(
        self,
    ):
        lhs = {"type": "integer"}
        rhs = {"type": "string", "anyOf": [{"type": "integer"}]}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right anyOf base witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        assert_witness_validates(lhs, rhs, Dialect.DRAFT7, proof.witness)

    def test_right_not_with_sibling_base_resolves_static_ref_child_with_modern_kernel(
        self,
    ):
        lhs = {"const": "b"}
        rhs = {
            "type": "string",
            "definitions": {"bad": {"const": "a"}},
            "not": {"$ref": "#/definitions/bad"},
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right not formula product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_right_not_sibling_base_static_ref_overlap_is_validated_with_modern_kernel(
        self,
    ):
        lhs = {"const": "a"}
        rhs = {
            "type": "string",
            "definitions": {"bad": {"const": "a"}},
            "not": {"$ref": "#/definitions/bad"},
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right not static-ref witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(proof.witness, "a")

    def test_right_not_sibling_base_counterexample_is_validated_with_modern_kernel(
        self,
    ):
        lhs = {"type": "integer"}
        rhs = {"type": "string", "not": {"type": "number"}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right not base witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        assert_witness_validates(lhs, rhs, Dialect.DRAFT7, proof.witness)

    def test_right_oneof_with_sibling_base_proves_cardinality_products_with_modern_kernel(
        self,
    ):
        lhs = {"type": "string", "minLength": 1}
        rhs = {"type": "string", "oneOf": [{"minLength": 1}, {"maxLength": 0}]}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right oneOf formula product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_right_oneof_sibling_base_counterexample_is_validated_with_modern_kernel(
        self,
    ):
        lhs = {"type": "integer"}
        rhs = {"type": "string", "oneOf": [{"type": "integer"}, {"type": "number"}]}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right oneOf base witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        assert_witness_validates(lhs, rhs, Dialect.DRAFT7, proof.witness)

    def test_right_allof_with_sibling_base_resolves_static_ref_child_with_modern_kernel(
        self,
    ):
        lhs = {"type": "string"}
        rhs = {
            "type": "string",
            "definitions": {"name": {"type": "string"}},
            "allOf": [{"$ref": "#/definitions/name"}],
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right allOf formula product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_right_allof_sibling_base_counterexample_is_validated_with_modern_kernel(
        self,
    ):
        lhs = {"type": "integer"}
        rhs = {
            "type": "string",
            "definitions": {"num": {"type": "integer"}},
            "allOf": [{"$ref": "#/definitions/num"}],
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right allOf base witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        assert_witness_validates(lhs, rhs, Dialect.DRAFT7, proof.witness)

    def test_right_allof_sibling_base_keeps_static_ref_boundary_diagnostic(self):
        lhs = {"type": "string"}
        rhs = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "string",
            "definitions": {
                "target": {
                    "$schema": "http://json-schema.org/draft-04/schema#",
                    "type": "string",
                },
            },
            "allOf": [{"$ref": "#/definitions/target"}],
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "unsupported")
        self.assertEqual(proof.diagnostics[0].category, "static-reference")
        self.assertEqual(proof.diagnostics[0].side, "rhs")
        self.assertEqual(proof.diagnostics[0].path, ("allOf", "0", "$ref"))

    def test_left_conditional_with_sibling_base_proves_guarded_products_with_modern_kernel(
        self,
    ):
        lhs = {"type": "string", "if": {"type": "string"}, "then": {"minLength": 1}}
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "left conditional formula product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_right_conditional_with_sibling_base_proves_base_and_guarded_products_with_modern_kernel(
        self,
    ):
        lhs = {"type": "string", "minLength": 2}
        rhs = {"type": "string", "if": {"type": "string"}, "then": {"minLength": 1}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right conditional formula product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_right_conditional_sibling_base_counterexample_is_validated_with_modern_kernel(
        self,
    ):
        lhs = {"type": "integer"}
        rhs = {"type": "string", "if": {"type": "integer"}, "then": {"type": "number"}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT7)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right conditional base witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        assert_witness_validates(lhs, rhs, Dialect.DRAFT7, proof.witness)

    def test_array_contains_difference_rule_runs_before_array_contains_tactic(self):
        lhs = {"type": "array", "contains": {"type": "integer"}}
        rhs = {"type": "array", "contains": {"type": "number"}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT6)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "array contains difference rule should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_array_contains_structural_max_uses_prefix_and_tail_before_array_contains_tactic(
        self,
    ):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 4,
        }
        rhs = {
            "type": "array",
            "contains": {"type": "number"},
            "minContains": 0,
            "maxContains": 1,
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "array contains structural max proof should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_array_contains_structural_min_constructs_max_contains_witness(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}, {"type": "number"}],
            "items": False,
            "minItems": 2,
        }
        rhs = {
            "type": "array",
            "contains": {"type": "number"},
            "minContains": 0,
            "maxContains": 1,
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "array contains max witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertGreaterEqual(len(proof.witness), 2)

    def test_right_not_with_left_pure_not_uses_complement_subproof(self):
        lhs = {"not": {"const": 1}}
        rhs = {"not": {"type": "integer", "minimum": 1}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "pure not complement witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIsInstance(proof.witness, int)
        self.assertNotEqual(proof.witness, 1)
        self.assertGreaterEqual(proof.witness, 1)

    def test_right_not_array_items_uses_constructive_intersection_witness(self):
        lhs = {"type": "array", "minItems": 1}
        rhs = {"not": {"type": "array", "items": {"type": "integer"}}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right-not array item witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIsInstance(proof.witness, list)
        self.assertGreaterEqual(len(proof.witness), 1)
        self.assertTrue(
            all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in proof.witness
            )
        )

    def test_right_not_array_contains_uses_constructive_intersection_witness(self):
        lhs = {"type": "array"}
        rhs = {
            "not": {"type": "array", "contains": {"type": "integer"}, "minContains": 1}
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right-not array contains witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIsInstance(proof.witness, list)
        self.assertTrue(
            any(
                isinstance(value, int) and not isinstance(value, bool)
                for value in proof.witness
            )
        )

    def test_right_not_array_contains_max_uses_constructive_intersection_witness(self):
        cases = (
            (
                {"type": "array", "contains": {"type": "integer"}, "minContains": 1},
                {
                    "not": {
                        "type": "array",
                        "contains": {"type": "integer"},
                        "minContains": 1,
                        "maxContains": 1,
                    }
                },
            ),
            (
                {"type": "array", "contains": {"type": "integer"}, "minContains": 1},
                {
                    "not": {
                        "type": "array",
                        "contains": {"const": 1},
                        "minContains": 1,
                        "maxContains": 1,
                    }
                },
            ),
            (
                {
                    "type": "array",
                    "contains": {"const": 1},
                    "minContains": 1,
                    "maxContains": 1,
                },
                {
                    "not": {
                        "type": "array",
                        "contains": {"type": "integer"},
                        "minContains": 1,
                        "maxContains": 1,
                    }
                },
            ),
        )
        for lhs, rhs in cases:
            with self.subTest(lhs=lhs, rhs=rhs):
                engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

                def fail_unexpected_proof_path(*_args, **_kwargs):
                    raise AssertionError(
                        "right-not array contains witness should not need constructive proof path"
                    )

                with patch.object(
                    engine.context,
                    "unexpected_proof_path",
                    fail_unexpected_proof_path,
                    create=True,
                ):
                    proof = engine._bounded_ir_proof(lhs, rhs)

                self.assertEqual(proof.status, "proved_false")
                self.assertIsInstance(proof.witness, list)
                self.assertEqual(len(proof.witness), 1)
                assert_witness_validates(lhs, rhs, Dialect.DRAFT202012, proof.witness)

    def test_right_not_array_prefix_items_uses_constructive_intersection_witness(self):
        lhs = {"type": "array", "minItems": 1}
        rhs = {
            "not": {
                "type": "array",
                "prefixItems": [{"type": "integer"}],
                "items": False,
            }
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "right-not array prefixItems witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIsInstance(proof.witness, list)
        self.assertEqual(len(proof.witness), 1)
        self.assertIsInstance(proof.witness[0], int)
        self.assertNotIsInstance(proof.witness[0], bool)

    def test_right_not_object_uses_constructive_intersection_witness(self):
        cases = (
            (
                {"type": "object"},
                {
                    "not": {
                        "type": "object",
                        "required": ["a"],
                        "properties": {"a": {"type": "integer"}},
                    }
                },
            ),
            (
                {"type": "object", "minProperties": 1},
                {
                    "not": {
                        "type": "object",
                        "propertyNames": {"pattern": "^a"},
                        "minProperties": 1,
                    }
                },
            ),
            (
                {
                    "type": "object",
                    "propertyNames": {"pattern": "^a"},
                    "minProperties": 1,
                },
                {
                    "not": {
                        "type": "object",
                        "required": ["a"],
                        "properties": {"a": {"const": 1}},
                    }
                },
            ),
        )
        for lhs, rhs in cases:
            with self.subTest(lhs=lhs, rhs=rhs):
                engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

                def fail_unexpected_proof_path(*_args, **_kwargs):
                    raise AssertionError(
                        "right-not object witness should not need constructive proof path"
                    )

                with patch.object(
                    engine.context,
                    "unexpected_proof_path",
                    fail_unexpected_proof_path,
                    create=True,
                ):
                    proof = engine._bounded_ir_proof(lhs, rhs)

                self.assertEqual(proof.status, "proved_false")
                self.assertIsInstance(proof.witness, dict)
                assert_witness_validates(lhs, rhs, Dialect.DRAFT202012, proof.witness)

    def test_object_required_property_value_uses_constructive_witness_when_key_is_required(
        self,
    ):
        lhs = {"type": "object", "required": ["a"], "propertyNames": {"pattern": "^a"}}
        rhs = {
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "integer"}},
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object required property-value witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(set(proof.witness), {"a"})
        assert_witness_validates(lhs, rhs, Dialect.DRAFT202012, proof.witness)

    def test_object_pattern_properties_do_not_imply_required_property(self):
        lhs = {
            "type": "object",
            "patternProperties": {"^a": {"type": "integer"}},
            "minProperties": 1,
        }
        rhs = {
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "integer"}},
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object required omission witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertNotIn("a", proof.witness)
        assert_witness_validates(lhs, rhs, Dialect.DRAFT202012, proof.witness)

    def test_object_property_names_do_not_imply_specific_required_property(self):
        lhs = {"type": "object", "propertyNames": {"pattern": "^a"}, "minProperties": 1}
        rhs = {"type": "object", "required": ["a"]}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object required omission witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertNotIn("a", proof.witness)
        assert_witness_validates(lhs, rhs, Dialect.DRAFT202012, proof.witness)

    def test_array_item_values_rule_runs_before_array_exact_tactics(self):
        lhs = {"type": "array", "items": {"type": "integer"}}
        rhs = {"type": "array", "items": {"type": "number"}}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "array item-values rule should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_array_item_values_rule_constructs_unconstrained_tail_witness(self):
        lhs = {"type": "array", "items": [{"type": "string"}]}
        rhs = {"type": "array", "items": {"type": "string"}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT4)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "array item-values witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIsInstance(proof.witness, list)
        self.assertGreaterEqual(len(proof.witness), 2)

    def test_unique_items_does_not_block_item_value_witness(self):
        lhs = {"type": "array", "uniqueItems": True, "minItems": 2, "maxItems": 2}
        rhs = {"type": "array", "items": {"type": "integer"}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "uniqueItems item-value witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIsInstance(proof.witness, list)
        self.assertEqual(len(proof.witness), 2)

    def test_array_length_does_not_mask_rhs_unique_items(self):
        lhs = {"type": "array", "minItems": 2, "maxItems": 2}
        rhs = {"type": "array", "uniqueItems": True, "minItems": 2, "maxItems": 2}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "uniqueItems duplicate witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(len(proof.witness), 2)
        self.assertEqual(
            json_semantic_key(proof.witness[0]), json_semantic_key(proof.witness[1])
        )

    def test_contains_constraint_populates_closed_tail_witness(self):
        lhs = {
            "type": "array",
            "contains": {"const": 1},
            "minContains": 1,
            "maxContains": 1,
        }
        rhs = {"type": "array", "prefixItems": [{"type": "integer"}], "items": False}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "contains closed-tail witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(len(proof.witness), 2)
        self.assertEqual(proof.witness[0], 1)

    def test_unique_array_constructs_distinct_contains_min_violation(self):
        lhs = {"type": "array", "uniqueItems": True, "minItems": 2, "maxItems": 2}
        rhs = {
            "type": "array",
            "contains": {"const": 1},
            "minContains": 1,
            "maxContains": 1,
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "unique contains min witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(len(proof.witness), 2)
        self.assertNotEqual(proof.witness[0], proof.witness[1])
        self.assertNotIn(1, proof.witness)

    def test_unique_array_constructs_distinct_contains_type_min_violation(self):
        lhs = {"type": "array", "uniqueItems": True, "minItems": 2, "maxItems": 2}
        rhs = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 1,
            "maxContains": 1,
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "unique contains type witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(len(proof.witness), 2)
        self.assertNotEqual(
            json_semantic_key(proof.witness[0]), json_semantic_key(proof.witness[1])
        )
        integer_count = sum(
            isinstance(value, int) and not isinstance(value, bool)
            for value in proof.witness
        )
        self.assertNotEqual(integer_count, 1)

    def test_contains_lhs_constructs_duplicate_against_unique_items(self):
        lhs = {
            "type": "array",
            "contains": {"const": 1},
            "minContains": 1,
            "maxContains": 1,
        }
        rhs = {"type": "array", "uniqueItems": True}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "contains duplicate witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(proof.witness.count(1), 1)
        self.assertLess(
            len({json_semantic_key(value) for value in proof.witness}),
            len(proof.witness),
        )

    def test_contains_lhs_constructs_item_value_witness(self):
        lhs = {
            "type": "array",
            "contains": {"const": 1},
            "minContains": 1,
            "maxContains": 1,
        }
        rhs = {"type": "array", "items": {"type": "integer"}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "contains item-value witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(proof.witness.count(1), 1)
        self.assertTrue(
            any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in proof.witness
            )
        )

    def test_contains_lhs_override_counts_for_rhs_item_not_schema(self):
        lhs = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 1,
            "maxContains": 1,
        }
        rhs = {"type": "array", "items": {"not": {"type": "integer"}}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "contains item-value not witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        integer_count = sum(
            isinstance(value, int) and not isinstance(value, bool)
            for value in proof.witness
        )
        self.assertEqual(integer_count, 1)

    def test_contains_lhs_constructs_broader_rhs_max_violation(self):
        lhs = {
            "type": "array",
            "contains": {"const": 1},
            "minContains": 1,
            "maxContains": 1,
        }
        rhs = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 1,
            "maxContains": 1,
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "contains rhs-only max witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(proof.witness.count(1), 1)
        integer_count = sum(
            isinstance(value, int) and not isinstance(value, bool)
            for value in proof.witness
        )
        self.assertGreater(integer_count, 1)

    def test_array_difference_does_not_treat_rhs_non_array_as_unique_items_success(
        self,
    ):
        lhs = {"type": "array", "minItems": 1, "items": {"type": "number"}}
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "array-vs-non-array difference should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIsInstance(proof.witness, list)

    def test_object_difference_rule_runs_before_object_exact_tactics_and_generic_search_path(
        self,
    ):
        lhs = {"type": "object", "minProperties": 2}
        rhs = {"type": "object", "maxProperties": 1}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object difference rule should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(len(proof.witness), 2)

    def test_closed_object_difference_rule_runs_before_closed_object_tactic(self):
        lhs = {
            "type": "object",
            "properties": {"age": {"type": "integer"}},
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "properties": {"age": {"type": "number"}},
            "additionalProperties": False,
        }
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "closed-object difference rule should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_object_presence_product_rule_runs_before_presence_tactic(self):
        lhs = {"type": "object", "required": ["a", "b"]}
        rhs = {"type": "object", "required": ["a"]}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object presence product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_object_presence_product_rule_runs_before_structure_tactic(self):
        lhs = {
            "type": "object",
            "required": ["credit_card"],
            "dependentRequired": {"credit_card": ["billing_address"]},
        }
        rhs = {"type": "object", "minProperties": 2}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT201909)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object presence product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_dependent_required_constructs_rhs_property_value_witness(self):
        lhs = {"type": "object", "dependentRequired": {"a": ["b"]}}
        rhs = {"type": "object", "properties": {"a": {"type": "integer"}}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "dependentRequired key-value witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIn("a", proof.witness)
        self.assertIn("b", proof.witness)
        self.assertFalse(
            isinstance(proof.witness["a"], int)
            and not isinstance(proof.witness["a"], bool)
        )

    def test_dependent_required_constructs_rhs_not_property_value_witness(self):
        lhs = {"type": "object", "dependentRequired": {"a": ["b"]}}
        rhs = {"type": "object", "properties": {"a": {"not": {"type": "integer"}}}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "dependentRequired not-value witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIn("a", proof.witness)
        self.assertIn("b", proof.witness)
        self.assertTrue(
            isinstance(proof.witness["a"], int)
            and not isinstance(proof.witness["a"], bool)
        )

    def test_dependent_schemas_construct_rhs_property_value_witness(self):
        lhs = {"type": "object", "dependentSchemas": {"a": {"required": ["b"]}}}
        rhs = {"type": "object", "properties": {"a": {"type": "integer"}}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "dependentSchemas key-value witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIn("a", proof.witness)
        self.assertIn("b", proof.witness)
        self.assertFalse(
            isinstance(proof.witness["a"], int)
            and not isinstance(proof.witness["a"], bool)
        )

    def test_pattern_property_can_violate_rhs_dependent_schema_required(self):
        lhs = {"type": "object", "patternProperties": {"^a": {"type": "integer"}}}
        rhs = {"type": "object", "dependentSchemas": {"a": {"required": ["b"]}}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "dependentSchemas presence witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIn("a", proof.witness)
        self.assertNotIn("b", proof.witness)

    def test_property_names_can_violate_rhs_dependent_schema_required(self):
        lhs = {"type": "object", "propertyNames": {"pattern": "^a"}}
        rhs = {"type": "object", "dependentSchemas": {"a": {"required": ["b"]}}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "dependentSchemas propertyNames witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIn("a", proof.witness)
        self.assertNotIn("b", proof.witness)

    def test_dependent_schema_key_can_violate_rhs_property_names(self):
        lhs = {"type": "object", "dependentSchemas": {"a": {"required": ["b"]}}}
        rhs = {"type": "object", "propertyNames": {"pattern": "^a"}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "dependentSchemas propertyNames keyspace witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIn("b", proof.witness)

    def test_dependent_required_constructs_rhs_pattern_value_witness(self):
        lhs = {"type": "object", "dependentRequired": {"a": ["b"]}}
        rhs = {"type": "object", "patternProperties": {"^a": {"type": "integer"}}}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "dependentRequired pattern value witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIn("a", proof.witness)
        self.assertIn("b", proof.witness)
        self.assertFalse(
            isinstance(proof.witness["a"], int)
            and not isinstance(proof.witness["a"], bool)
        )

    def test_object_presence_product_constructs_multi_fresh_max_properties_witness(
        self,
    ):
        lhs = {"type": "object", "required": ["a"]}
        rhs = {"type": "object", "maxProperties": 2}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object presence multi-fresh witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertGreater(len(proof.witness), 2)
        self.assertIn("a", proof.witness)

    def test_object_property_values_rule_runs_before_property_values_tactic(self):
        lhs = {"type": "object", "properties": {"age": {"type": "integer"}}}
        rhs = {"type": "object", "properties": {"age": {"type": "number"}}}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object property-values difference should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_object_property_values_required_witness_runs_before_property_values_tactic(
        self,
    ):
        lhs = {"type": "object", "properties": {"age": {"type": "integer"}}}
        rhs = {
            "type": "object",
            "properties": {"age": {"type": "integer"}},
            "required": ["age"],
        }
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object property-values required witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(proof.witness, {})

    def test_object_additional_properties_value_rule_runs_before_object_exact_tactics(
        self,
    ):
        lhs = {"type": "object", "additionalProperties": {"type": "integer"}}
        rhs = {"type": "object", "additionalProperties": {"type": "number"}}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object additionalProperties value rule should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_object_property_names_key_value_rule_runs_before_object_exact_tactics(
        self,
    ):
        lhs = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
            "additionalProperties": {"type": "integer"},
        }
        rhs = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
            "additionalProperties": {"type": "number"},
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT6)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object propertyNames key-value proof should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_object_property_names_key_value_rule_constructs_witness(self):
        lhs = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
            "additionalProperties": {"type": "number"},
        }
        rhs = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
            "additionalProperties": {"type": "integer"},
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT6)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object propertyNames key-value witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertTrue(any(name.startswith("a") for name in proof.witness))

    def test_object_property_names_keyspace_product_constructs_witness(self):
        lhs = {
            "type": "object",
            "propertyNames": {"pattern": "^a"},
            "additionalProperties": {"type": "integer"},
        }
        rhs = {
            "type": "object",
            "propertyNames": {"pattern": "^b"},
            "additionalProperties": {"type": "integer"},
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT6)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object propertyNames keyspace witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertTrue(any(name.startswith("a") for name in proof.witness))

    def test_object_pattern_properties_value_rule_constructs_witness(self):
        lhs = {"type": "object", "patternProperties": {"^a": {"type": "number"}}}
        rhs = {"type": "object", "patternProperties": {"^a": {"type": "integer"}}}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object patternProperties value witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIn("a", proof.witness)

    def test_object_overlapping_pattern_product_runs_before_object_exact_tactics(self):
        lhs = {"type": "object", "patternProperties": {"b.*b": {"type": "integer"}}}
        rhs = {"type": "object", "patternProperties": {"^ba+b$": {"type": "number"}}}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object regex product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_object_overlapping_pattern_product_constructs_witness(self):
        lhs = {"type": "object", "patternProperties": {"^ba+b$": {"type": "number"}}}
        rhs = {"type": "object", "patternProperties": {"b.*b": {"type": "integer"}}}
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object regex product witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertTrue(any("b" in name for name in proof.witness))

    def test_object_explicit_property_pattern_product_runs_before_object_exact_tactics(
        self,
    ):
        lhs = {
            "type": "object",
            "properties": {"email": {"type": "integer"}},
            "patternProperties": {"^e": {"type": "integer"}},
            "additionalProperties": {"type": "string"},
        }
        rhs = {
            "type": "object",
            "properties": {"email": {"type": "number"}},
            "patternProperties": {"^e": {"type": "number"}},
        }
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object explicit/pattern product should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_object_explicit_property_pattern_product_constructs_witness(self):
        lhs = {
            "type": "object",
            "properties": {"email": {"type": "integer"}},
            "patternProperties": {"^e": {"type": "number"}},
        }
        rhs = {
            "type": "object",
            "properties": {"email": {"type": "number"}},
            "patternProperties": {"^e": {"type": "integer"}},
        }
        engine = ProofEngine.for_schemas(lhs, rhs)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "object explicit/pattern product witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertTrue(
            any(name.startswith("e") and name != "email" for name in proof.witness)
        )

    def test_ir_compiles_evaluation_frontier_separately_from_domain_facts(self):
        schema = {
            "allOf": [
                {
                    "properties": {"foo": {"type": "string"}},
                    "patternProperties": {"^x-": {"type": "integer"}},
                    "additionalProperties": False,
                }
            ],
            "prefixItems": [{"type": "integer"}],
            "items": {"type": "string"},
            "contains": {"type": "number"},
            "unevaluatedProperties": False,
            "unevaluatedItems": False,
        }

        compiled = SchemaIRCompiler(Dialect.DRAFT202012).compile(schema)
        child = compiled.applicators[0].children[0]

        self.assertIsInstance(compiled.evaluation, EvaluationFrontier)
        self.assertTrue(compiled.evaluation.requires_evaluation_tracking)
        self.assertEqual(
            compiled.evaluation.constraints,
            (
                compiled.evaluation.unevaluated_properties,
                compiled.evaluation.unevaluated_items,
            ),
        )
        self.assertEqual(
            [
                (source.kind, source.index, source.start_index)
                for source in compiled.evaluation.item_sources
            ],
            [
                ("prefixItems", 0, None),
                ("items", None, 1),
                ("contains", None, None),
            ],
        )
        contains_source = compiled.evaluation.item_sources[-1]
        self.assertIsInstance(contains_source, EvaluatedItemSource)
        self.assertTrue(contains_source.marks_contains_matches)
        self.assertEqual(
            [(source.kind, source.key) for source in child.evaluation.property_sources],
            [
                ("properties", "foo"),
                ("patternProperties", "^x-"),
                ("additionalProperties", None),
            ],
        )
        self.assertIsInstance(
            child.evaluation.property_sources[0], EvaluatedPropertySource
        )
        self.assertFalse(child.evaluation.requires_evaluation_tracking)

    def test_ir_collects_nested_unsupported_evaluation_reasons(self):
        schema = {
            "allOf": [
                {
                    "type": "object",
                    "unevaluatedProperties": False,
                }
            ]
        }

        compiled = SchemaIRCompiler(Dialect.DRAFT202012).compile(schema)

        self.assertEqual(len(compiled.unsupported), 1)
        self.assertEqual(
            compiled.unsupported[0].path, ("allOf", "0", "unevaluatedProperties")
        )
        self.assertEqual(
            compiled.unsupported[0].pointer, "#/allOf/0/unevaluatedProperties"
        )
        self.assertEqual(compiled.unsupported[0].category, "evaluation-frontier")
        self.assertEqual(
            compiled.unsupported[0].reason,
            "unevaluatedProperties requires evaluated-property frontier proof support",
        )

    def test_ir_source_nodes_preserve_nested_json_pointer_context(self):
        schema = {
            "definitions": {"name": {"type": "string"}},
            "allOf": [
                {"$ref": "#/definitions/name"},
                {
                    "if": {"type": "string"},
                    "then": {"minLength": 1},
                },
            ],
        }

        compiled = SchemaIRCompiler(Dialect.DRAFT7).compile(schema)
        all_of = compiled.root.applicators[0]
        ref_child = all_of.children[0]
        conditional_child = all_of.children[1]

        self.assertEqual(compiled.source.pointer, ())
        self.assertEqual(ref_child.source.pointer, ("allOf", "0"))
        self.assertEqual(conditional_child.source.pointer, ("allOf", "1"))
        self.assertEqual(
            conditional_child.applicators[0].children[0].source.pointer,
            ("allOf", "1", "if"),
        )
        self.assertEqual(
            conditional_child.applicators[1].children[0].source.pointer,
            ("allOf", "1", "then"),
        )

        ref_formula = formulas_module._positive_formula_for_node(ref_child, "lhs")
        self.assertIsInstance(ref_formula, ReferenceFormula)
        self.assertEqual(ref_formula.source.source.pointer, ("allOf", "0"))

    def test_validation_unsupported_result_preserves_original_exception_and_diagnostic(
        self,
    ):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$vocabulary": {
                "https://example.com/custom-assertion-vocabulary": True,
            },
        }
        engine = ProofEngine.for_schemas(schema, {})

        proof = engine.is_subschema(schema, {})

        self.assertEqual(proof.status, "unsupported")
        self.assertIsInstance(proof.error, UnsupportedKeywordError)
        self.assertEqual(len(proof.diagnostics), 1)
        diagnostic = proof.diagnostics[0]
        self.assertEqual(diagnostic.category, "unknown-vocabulary")
        self.assertEqual(diagnostic.side, "lhs")
        self.assertEqual(
            diagnostic.path,
            ("$vocabulary", "https://example.com/custom-assertion-vocabulary"),
        )
        self.assertEqual(
            diagnostic.pointer,
            "#/$vocabulary/https:~1~1example.com~1custom-assertion-vocabulary",
        )
        with self.assertRaises(UnsupportedKeywordError):
            proof.as_bool(Dialect.DRAFT202012)

    def test_required_format_assertion_vocabulary_has_specific_diagnostic(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$vocabulary": {
                "https://json-schema.org/draft/2020-12/vocab/format-assertion": True,
            },
        }

        proof = ProofEngine.for_schemas({}, schema).is_subschema({}, schema)

        self.assertEqual(proof.status, "unsupported")
        self.assertEqual(proof.diagnostics[0].category, "format-assertion")
        self.assertEqual(proof.diagnostics[0].side, "rhs")
        with self.assertRaises(UnsupportedKeywordError):
            is_subschema({}, schema)

    def test_acyclic_dynamic_ref_is_no_longer_semantic_unsupported(self):
        dynamic_ref = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "node": {
                    "$dynamicAnchor": "node",
                    "type": "string",
                }
            },
            "$dynamicRef": "#node",
        }
        engine = ProofEngine.for_schemas(
            {"type": "string"}, dynamic_ref, dialect=Dialect.DRAFT202012
        )

        proof = engine._bounded_ir_proof({"type": "string"}, dynamic_ref)

        self.assertEqual(proof.status, "proved_true")
        self.assertFalse(proof.diagnostics)

    def test_non_regular_regex_is_reported_as_semantic_unsupported(self):
        lhs = {"type": "string", "pattern": "(?=a)a"}
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(lhs, rhs)

        proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "unsupported")
        self.assertEqual(proof.diagnostics[0].category, "non-regular-regex")
        self.assertEqual(proof.diagnostics[0].keyword, "pattern")
        self.assertEqual(proof.diagnostics[0].path, ("pattern",))

    def test_reference_graph_and_ref_normalization_live_in_kernel_package(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "positive": {
                    "$anchor": "positive",
                    "type": "integer",
                    "minimum": 0,
                }
            },
            "$ref": "#positive",
            "maximum": 10,
        }
        normalized = references_module.normalize_modern_refs(
            schema, Dialect.DRAFT202012
        )
        graph = references_module.ResourceGraph.build(
            normalized, dialect=Dialect.DRAFT202012
        )

        self.assertEqual(
            normalized,
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$defs": {
                    "positive": {
                        "$anchor": "positive",
                        "type": "integer",
                        "minimum": 0,
                    }
                },
                "allOf": [{"$ref": "#/$defs/positive"}, {"maximum": 10}],
            },
        )
        self.assertEqual(
            graph.resolve_ref("#/$defs/positive"), schema["$defs"]["positive"]
        )
        identified_schema = {
            "$id": "https://example.com/root",
            "$defs": {"name": {"type": "string"}},
            "$ref": "#/$defs/name",
        }
        identified_graph = references_module.ResourceGraph.build(
            identified_schema, dialect=Dialect.DRAFT7
        )
        resolution = identified_graph.resolve_ref_info("#/$defs/name")
        self.assertIsInstance(resolution, references_module.ReferenceResolution)
        self.assertEqual(
            identified_graph.to_ir().resource_uri, "https://example.com/root"
        )
        self.assertEqual(resolution.resource_uri, "https://example.com/root")
        self.assertEqual(resolution.pointer, ("$defs", "name"))
        self.assertEqual(resolution.schema, {"type": "string"})
        self.assertEqual(resolution.document_pointer, ("$defs", "name"))
        self.assertEqual(resolution.source_resource_uri, "https://example.com/root")
        self.assertEqual(resolution.source_pointer, ())
        self.assertEqual(resolution.source_resource_pointer, ())
        dialect_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$defs": {
                "draft_target": {
                    "$schema": "http://json-schema.org/draft-04/schema#",
                    "type": "string",
                },
            },
        }
        dialect_graph = references_module.ResourceGraph.build(
            dialect_schema, dialect=Dialect.DRAFT7
        )
        dialect_resolution = dialect_graph.resolve_ref_info("#/$defs/draft_target")
        self.assertEqual(dialect_resolution.dialect, Dialect.DRAFT4)

        draft4_id_schema = {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "id": "https://example.com/root",
            "definitions": {
                "number": {
                    "id": "number",
                    "type": "number",
                },
            },
            "$ref": "number",
        }
        draft4_id_graph = references_module.ResourceGraph.build(
            draft4_id_schema, dialect=Dialect.DRAFT4
        )
        draft4_resolution = draft4_id_graph.resolve_ref_info(
            "number", base_uri="https://example.com/root"
        )
        self.assertEqual(draft4_id_graph.root_uri, "https://example.com/root")
        self.assertEqual(draft4_resolution.resource_uri, "https://example.com/number")
        self.assertEqual(draft4_resolution.document_pointer, ("definitions", "number"))

        compound_schema = {
            "$id": "https://example.com/root",
            "$defs": {
                "child": {
                    "$id": "child",
                    "$defs": {
                        "name": {
                            "$anchor": "name",
                            "type": "string",
                        }
                    },
                    "$ref": "#name",
                }
            },
            "$ref": "child",
        }
        compound_graph = references_module.ResourceGraph.build(
            compound_schema, dialect=Dialect.DRAFT202012
        )
        self.assertEqual(
            sorted(compound_graph.resources),
            ["https://example.com/child", "https://example.com/root"],
        )
        self.assertEqual(
            compound_graph.resources["https://example.com/child"].pointer,
            ("$defs", "child"),
        )
        child_resolution = compound_graph.resolve_ref_info(
            "child", base_uri="https://example.com/root"
        )
        self.assertEqual(child_resolution.resource_uri, "https://example.com/child")
        self.assertEqual(child_resolution.pointer, ())
        self.assertEqual(child_resolution.document_pointer, ("$defs", "child"))
        anchor_resolution = compound_graph.resolve_ref_info(
            "#name", base_uri="https://example.com/child"
        )
        self.assertEqual(anchor_resolution.pointer, ("$defs", "name"))
        self.assertEqual(
            anchor_resolution.document_pointer, ("$defs", "child", "$defs", "name")
        )
        self.assertEqual(
            anchor_resolution.source_resource_uri, "https://example.com/child"
        )
        self.assertEqual(
            references_module.ResourceGraph.__module__, "subschema.kernel.references"
        )

    def test_embedded_resource_static_reference_proves_with_modern_kernel(self):
        lhs = {
            "$id": "https://example.com/root",
            "$defs": {
                "child": {
                    "$id": "child",
                    "$defs": {
                        "name": {
                            "$anchor": "name",
                            "type": "string",
                        }
                    },
                    "$ref": "#name",
                }
            },
            "$ref": "child",
        }
        rhs = {"type": "string"}
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "embedded-resource static ref proof should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_draft4_id_static_reference_proves_with_modern_kernel(self):
        rhs = {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "id": "https://example.com/root",
            "definitions": {
                "number": {
                    "id": "number",
                    "type": "number",
                },
            },
            "$ref": "number",
        }
        engine = ProofEngine.for_schemas(
            {"type": "integer"}, rhs, dialect=Dialect.DRAFT4
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "Draft4 id ref proof should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            true_proof = engine.is_subschema({"type": "integer"}, rhs)
            false_proof = engine.is_subschema({"type": "string"}, rhs)

        self.assertEqual(true_proof.status, "proved_true")
        self.assertEqual(false_proof.status, "proved_false")

    def test_ir_source_nodes_preserve_resource_local_and_document_pointers(self):
        schema = {
            "$id": "https://example.com/root",
            "$defs": {
                "child": {
                    "$id": "child",
                    "allOf": [{"type": "string"}],
                }
            },
            "allOf": [{"$ref": "child"}],
        }

        compiled = SchemaIRCompiler(Dialect.DRAFT202012).compile(schema)
        child_resource = compiled.graph.schema_ir_for_pointer(
            ("$defs", "child"), schema["$defs"]["child"]
        )
        nested_child = (
            SchemaIRCompiler(Dialect.DRAFT202012)
            .compile_graph(compiled.graph)
            .root.applicators[0]
            .children[0]
        )

        self.assertEqual(compiled.source.resource_uri, "https://example.com/root")
        self.assertEqual(compiled.source.pointer, ())
        self.assertEqual(compiled.source.resource_pointer, ())
        self.assertEqual(child_resource.resource_uri, "https://example.com/child")
        self.assertEqual(child_resource.pointer, ("$defs", "child"))
        self.assertEqual(child_resource.resource_pointer, ())
        self.assertEqual(child_resource.document_pointer, ("$defs", "child"))
        self.assertEqual(nested_child.source.resource_uri, "https://example.com/root")
        self.assertEqual(nested_child.source.pointer, ("allOf", "0"))
        self.assertEqual(nested_child.source.resource_pointer, ("allOf", "0"))

    def test_reference_resolution_records_embedded_source_and_target_provenance(self):
        schema = {
            "$id": "https://example.com/root/",
            "$defs": {
                "child": {
                    "$id": "child/",
                    "$defs": {
                        "escaped/name~token": {
                            "$anchor": "target",
                            "type": "string",
                        }
                    },
                    "allOf": [
                        {"$ref": "#/$defs/escaped~1name~0token"},
                        {"$ref": "#target"},
                    ],
                }
            },
        }
        graph = references_module.ResourceGraph.build(
            schema, dialect=Dialect.DRAFT202012
        )
        pointer_ref = graph.schema_ir_for_pointer(
            ("$defs", "child", "allOf", "0"),
            schema["$defs"]["child"]["allOf"][0],
        )
        anchor_ref = graph.schema_ir_for_pointer(
            ("$defs", "child", "allOf", "1"),
            schema["$defs"]["child"]["allOf"][1],
        )

        pointer_resolution = references_module.static_reference_resolution_for_schema(
            pointer_ref.schema,
            graph,
            source_resource_uri=pointer_ref.resource_uri,
            source_pointer=pointer_ref.pointer,
            source_resource_pointer=pointer_ref.resource_pointer,
            source_dialect=pointer_ref.dialect,
            side="lhs",
        )
        anchor_resolution = references_module.static_reference_resolution_for_schema(
            anchor_ref.schema,
            graph,
            source_resource_uri=anchor_ref.resource_uri,
            source_pointer=anchor_ref.pointer,
            source_resource_pointer=anchor_ref.resource_pointer,
            source_dialect=anchor_ref.dialect,
            side="lhs",
        )

        self.assertIsInstance(pointer_resolution, references_module.ReferenceResolution)
        self.assertEqual(
            pointer_resolution.source_resource_uri, "https://example.com/root/child/"
        )
        self.assertEqual(
            pointer_resolution.source_pointer, ("$defs", "child", "allOf", "0")
        )
        self.assertEqual(pointer_resolution.source_resource_pointer, ("allOf", "0"))
        self.assertEqual(
            pointer_resolution.resource_uri, "https://example.com/root/child/"
        )
        self.assertEqual(pointer_resolution.pointer, ("$defs", "escaped/name~token"))
        self.assertEqual(
            pointer_resolution.document_pointer,
            ("$defs", "child", "$defs", "escaped/name~token"),
        )
        self.assertIsInstance(anchor_resolution, references_module.ReferenceResolution)
        self.assertEqual(anchor_resolution.pointer, ("$defs", "escaped/name~token"))
        self.assertEqual(
            anchor_resolution.document_pointer, pointer_resolution.document_pointer
        )

    def test_dynamic_scope_resolves_nearest_dynamic_anchor(self):
        schema = {
            "$id": "https://example.com/root",
            "$dynamicAnchor": "node",
            "$defs": {
                "child": {
                    "$id": "child",
                    "$dynamicAnchor": "node",
                    "type": "string",
                }
            },
            "$dynamicRef": "#node",
        }
        graph = references_module.ResourceGraph.build(
            schema, dialect=Dialect.DRAFT202012
        )
        root_frame = graph.reference_frame_for_pointer(())
        child_frame = graph.reference_frame_for_pointer(("$defs", "child"))
        scope = references_module.DynamicScope().push(root_frame).push(child_frame)

        resolution = graph.resolve_dynamic_ref_info(
            "#node", root_frame, dynamic_scope=scope
        )

        self.assertIsInstance(resolution, references_module.ReferenceResolution)
        self.assertEqual(resolution.resource_uri, "https://example.com/child")
        self.assertEqual(resolution.pointer, ())
        self.assertEqual(resolution.document_pointer, ("$defs", "child"))
        self.assertEqual(resolution.source_resource_uri, "https://example.com/root")
        self.assertEqual(resolution.source_resource_pointer, ())

    def test_acyclic_root_dynamic_ref_proves_with_modern_kernel(self):
        lhs = {"type": "string"}
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "node": {
                    "$dynamicAnchor": "node",
                    "type": "string",
                }
            },
            "$dynamicRef": "#node",
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "acyclic dynamic-ref proof should not need constructive proof path"
            )

        with (
            patch.object(
                engine.context,
                "unexpected_proof_path",
                fail_unexpected_proof_path,
                create=True,
            ),
        ):
            proof = engine.is_subschema(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_unregistered_external_static_ref_stays_unsupported_with_modern_kernel(
        self,
    ):
        lhs = {
            "$id": "https://example.com/root",
            "$ref": "https://example.com/external",
        }
        engine = ProofEngine.for_schemas(
            lhs,
            {"type": "string"},
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        proof = engine.is_subschema(lhs, {"type": "string"})

        self.assertEqual(proof.status, "unsupported")
        self.assertIn("could not resolve lhs $ref", proof.reason)
        self.assertEqual(proof.diagnostics[0].category, "static-reference")
        self.assertEqual(proof.diagnostics[0].path, ("$ref",))

    def test_schema_position_normalization_lives_in_kernel_package(self):
        schema = {
            "properties": {"a": True},
            "items": [True, False],
            "additionalProperties": False,
            "enum": [True, False],
        }
        expected = {
            "properties": {"a": {}},
            "items": [{}, {"not": {}}],
            "additionalProperties": {"not": {}},
            "enum": [True, False],
        }

        self.assertEqual(
            normalization_module.normalize_boolean_schemas(schema), expected
        )
        self.assertIn(
            "normalize_simple_lhs_unevaluated_for_proof",
            inspect.getsource(driver_module),
        )
        self.assertIn("kernel.normalization", inspect.getsource(validation_module))

    def test_difference_rule_specs_replace_exact_tactic_registry(self):
        names = [spec.name for spec in difference_rule_specs()]

        self.assertEqual(
            names,
            [
                "trivial-difference",
                "finite-domain-ir",
                "static-reference-ir",
                "dynamic-reference-ir",
                "finite-rhs-domain-ir",
                "finite-complement-ir",
                "applicator-left-anyof-ir",
                "applicator-left-oneof-ir",
                "applicator-left-allof-ir",
                "applicator-right-not-ir",
                "applicator-right-anyof-ir",
                "applicator-right-oneof-ir",
                "applicator-right-allof-ir",
                "applicator-conditional-ir",
                "numeric-domain-ir",
                "type-domain-ir",
                "string-length-domain-ir",
                "string-language-domain-ir",
                "typed-scalar-domain-ir",
                "array-unevaluated-items-ir",
                "array-length-ir",
                "array-uniqueness-ir",
                "array-contains-ir",
                "array-item-values-ir",
                "object-unevaluated-properties-ir",
                "object-property-count-ir",
                "object-presence-product-ir",
                "object-property-values-ir",
                "object-key-value-ir",
                "object-property-names-ir",
                "object-closed-properties-ir",
            ],
        )
        self.assertNotIn("internal-checker", names)
        self.assertNotIn("finite-domain", names)
        self.assertIn("finite-domain-ir", names)


class TestMeetJoinProjection(unittest.TestCase):
    def test_complex_finite_meet_and_join_use_proof_projection(self):
        lhs = {"const": {"a": 1}}
        rhs = {"type": "object"}

        self.assertEqual(meet_schemas(lhs, rhs, dialect=Dialect.DRAFT7), lhs)
        self.assertEqual(join_schemas(lhs, rhs, dialect=Dialect.DRAFT7), rhs)

    def test_top_bottom_meet_and_join_are_projected(self):
        self.assertEqual(
            meet_schemas(True, {"type": "string"}, dialect=Dialect.DRAFT6),
            {"type": "string"},
        )
        self.assertIs(
            meet_schemas(False, {"type": "string"}, dialect=Dialect.DRAFT6),
            False,
        )
        self.assertIs(
            join_schemas(True, {"type": "string"}, dialect=Dialect.DRAFT6), True
        )
        self.assertEqual(
            join_schemas(False, {"type": "string"}, dialect=Dialect.DRAFT6),
            {"type": "string"},
        )

    def test_finite_meet_and_join_are_projected(self):
        lhs = {"enum": [1, 2]}
        rhs = {"enum": [2, 3]}

        self.assertEqual(meet_schemas(lhs, rhs), {"const": 2})
        self.assertEqual(join_schemas(lhs, rhs), {"enum": [1, 2, 3]})

    def test_disjoint_finite_meet_projects_false(self):
        lhs = {"enum": [1]}
        rhs = {"enum": [2]}

        self.assertIs(meet_schemas(lhs, rhs), False)

    def test_uninhabited_finite_join_projects_other_side(self):
        lhs = {"type": "string", "enum": [1]}
        rhs = {"const": "a"}

        self.assertIs(meet_schemas(lhs, rhs), False)
        self.assertEqual(join_schemas(lhs, rhs), rhs)


class TestFiniteDomainProof(unittest.TestCase):
    def test_empty_finite_lhs_is_proved(self):
        lhs = {"type": "string", "enum": [1, 2]}
        rhs = {"type": "object"}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_one_of_overlap_is_proved(self):
        lhs = {"const": 1}
        rhs = {"oneOf": [{"type": "number"}, {"const": 1}]}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT7))

    def test_right_one_of_overlapping_top_and_complement_is_not_proved_true(self):
        lhs = {"type": "integer"}
        rhs = {"oneOf": [{}, {"not": {"const": 1}}]}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT7))

    def test_double_negated_finite_rhs_is_not_reduced_to_type_only_success(self):
        lhs = {"type": "integer"}
        rhs = {"not": {"not": {"const": 1}}}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT7))

    def test_right_one_of_with_overlapping_top_and_double_negation_is_not_proved_true(
        self,
    ):
        lhs = {"oneOf": [{}, {"type": "array"}]}
        rhs = {"oneOf": [{}, {"not": {"const": 1}}]}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT7))

    def test_one_of_type_shape_does_not_treat_value_level_overlap_as_empty(self):
        lhs = {"oneOf": [{}, {"not": {"const": 1}}]}

        self.assertFalse(is_subschema(lhs, False, dialect=Dialect.DRAFT6))

    def test_json_integer_finite_values_are_proved(self):
        lhs = {"enum": [1, 2.0, 3]}
        rhs = {"type": "integer"}

        self.assertTrue(is_subschema(lhs, rhs))


class TestApplicatorCompositionProof(unittest.TestCase):
    def test_left_any_of_closed_object_branches_are_proved(self):
        lhs = {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {"b": {"type": "integer"}},
                    "additionalProperties": False,
                },
            ]
        }
        rhs = {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "number"},
            },
            "additionalProperties": False,
        }

        self.assertTrue(is_subschema(lhs, rhs))

    def test_left_any_of_branch_counterexample_is_proved(self):
        lhs = {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {"b": {"type": "integer"}},
                    "additionalProperties": False,
                },
            ]
        }
        rhs = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        }

        self.assertFalse(is_subschema(lhs, rhs))

    def test_left_one_of_branches_are_proved(self):
        lhs = {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {"alpha": {"type": "string"}},
                    "additionalProperties": False,
                },
                {"type": "array", "maxItems": 1},
            ]
        }
        rhs = {"type": ["object", "array"]}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_left_one_of_valid_counterexample_is_proved(self):
        lhs = {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {"beta": {"type": "integer"}},
                    "required": ["beta"],
                    "additionalProperties": False,
                },
                {"type": "array", "maxItems": 1},
            ]
        }
        rhs = {
            "type": "object",
            "properties": {"alpha": {"type": "integer"}},
            "additionalProperties": False,
        }

        self.assertFalse(is_subschema(lhs, rhs))

    def test_left_all_of_uses_covering_conjunct(self):
        lhs = {
            "allOf": [
                {
                    "type": "object",
                    "properties": {"alpha": {"type": "string"}},
                    "additionalProperties": False,
                },
                {"type": "object", "required": ["alpha"]},
            ]
        }
        rhs = {
            "type": "object",
            "properties": {"alpha": {"type": "string"}},
            "additionalProperties": False,
        }

        self.assertTrue(is_subschema(lhs, rhs))

    def test_left_all_of_valid_counterexample_is_proved(self):
        lhs = {
            "allOf": [
                {
                    "type": "object",
                    "properties": {"beta": {"type": "integer"}},
                    "additionalProperties": False,
                },
                {"type": "object", "required": ["beta"]},
            ]
        }
        rhs = {
            "type": "object",
            "properties": {"alpha": {"type": "integer"}},
            "additionalProperties": False,
        }

        self.assertFalse(is_subschema(lhs, rhs))

    def test_right_any_of_uses_covering_branch(self):
        lhs = {
            "type": "object",
            "properties": {"alpha": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "anyOf": [
                {"type": "array"},
                {
                    "type": "object",
                    "properties": {"alpha": {"type": "string"}},
                    "additionalProperties": False,
                },
            ]
        }

        self.assertTrue(is_subschema(lhs, rhs))

    def test_right_any_of_valid_counterexample_is_proved(self):
        lhs = {
            "type": "object",
            "properties": {"beta": {"type": "integer"}},
            "required": ["beta"],
            "additionalProperties": False,
        }
        rhs = {
            "anyOf": [
                {"type": "array"},
                {
                    "type": "object",
                    "properties": {"alpha": {"type": "integer"}},
                    "additionalProperties": False,
                },
            ]
        }

        self.assertFalse(is_subschema(lhs, rhs))

    def test_right_one_of_uses_single_disjoint_covering_branch(self):
        lhs = {
            "type": "object",
            "properties": {"alpha": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {"alpha": {"type": "string"}},
                    "additionalProperties": False,
                },
                {"type": "array"},
            ]
        }

        self.assertTrue(is_subschema(lhs, rhs))

    def test_right_one_of_overlap_counterexample_is_proved(self):
        lhs = {
            "type": "object",
            "properties": {"alpha": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "oneOf": [
                {"type": "object"},
                {
                    "type": "object",
                    "properties": {"alpha": {"type": "string"}},
                    "additionalProperties": False,
                },
            ]
        }

        self.assertFalse(is_subschema(lhs, rhs))

    def test_right_all_of_mixed_domain_conjuncts_are_proved(self):
        lhs = {
            "type": "object",
            "properties": {"alpha": True},
            "required": ["alpha"],
            "additionalProperties": False,
        }
        rhs = {
            "allOf": [
                {"type": "object", "propertyNames": {"pattern": "^a"}},
                {
                    "type": "object",
                    "properties": {"alpha": True},
                    "required": ["alpha"],
                    "additionalProperties": False,
                },
            ]
        }

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_right_all_of_conjunct_counterexample_is_proved(self):
        lhs = {
            "type": "object",
            "properties": {"alpha": True, "beta": True},
            "additionalProperties": False,
        }
        rhs = {
            "allOf": [
                {"type": "object"},
                {"type": "object", "propertyNames": {"pattern": "^a"}},
            ]
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_rhs_conditional_guarded_products_are_proved(self):
        rhs = {
            "if": {"type": "string"},
            "then": {"minLength": 2},
            "else": {"type": "integer"},
        }

        self.assertTrue(
            is_subschema(
                {"type": "string", "minLength": 2},
                rhs,
                dialect=Dialect.DRAFT7,
            )
        )
        self.assertTrue(
            is_subschema(
                {"type": "integer"},
                rhs,
                dialect=Dialect.DRAFT7,
            )
        )
        self.assertFalse(is_subschema({"type": "string"}, rhs, dialect=Dialect.DRAFT7))

    def test_lhs_conditional_guarded_products_are_proved(self):
        lhs = {
            "if": {"type": "string"},
            "then": {"minLength": 2},
            "else": False,
        }
        rhs = {"type": "string"}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT7))
        self.assertFalse(
            is_subschema(
                {"if": {"type": "string"}, "then": {"type": "integer"}},
                rhs,
                dialect=Dialect.DRAFT7,
            )
        )


class TestNumericDomainProof(unittest.TestCase):
    def test_interval_subtype_is_proved(self):
        lhs = {"type": "integer", "minimum": 5, "maximum": 10}
        rhs = {"type": "number", "minimum": 4, "maximum": 11}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_interval_counterexample_is_proved(self):
        lhs = {"type": "number", "minimum": 5}
        rhs = {"type": "number", "minimum": 6}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_untyped_numeric_all_of_equivalence_is_proved(self):
        lhs = {"minimum": 10, "maximum": 20}
        rhs = {"allOf": [{"minimum": 10}, {"maximum": 20}]}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_untyped_numeric_schema_is_not_typed_number(self):
        lhs = {"minimum": 10}
        rhs = {"type": "number", "minimum": 10}

        self.assertFalse(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_multiple_of_integer_subtype_is_proved(self):
        lhs = {"type": "number", "multipleOf": 10}
        rhs = {"type": "integer"}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_multiple_of_counterexample_is_proved(self):
        lhs = {"type": "integer", "multipleOf": 5}
        rhs = {"type": "integer", "multipleOf": 7}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_numeric_rule_does_not_prove_incomplete_non_numeric_rhs_language(self):
        lhs = True
        rhs = {"not": {"type": "array", "contains": {"type": "string"}}}
        proof = engine_module.ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
        ).is_subschema(lhs, rhs)

        self.assertNotEqual(proof.status, "proved_true")


class TestTypeDomainProof(unittest.TestCase):
    def test_mixed_type_counterexample_is_proved(self):
        lhs = {"type": ["string", "array"]}
        rhs = {"type": ["number", "string"]}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_any_of_type_equivalence_is_proved(self):
        lhs = {"type": ["string", "boolean"]}
        rhs = {"anyOf": [{"type": "string"}, {"type": "boolean"}]}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_one_of_top_complement_is_proved(self):
        lhs = {"oneOf": [{"type": "string"}, {}]}
        rhs = {"not": {"type": "string"}}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_not_type_union_is_proved(self):
        lhs = {"not": {"anyOf": [{"type": "string"}, {"type": "null"}]}}
        rhs = {"type": ["integer", "number", "boolean", "array", "object"]}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_type_counterexamples_use_left_schema_constraints(self):
        cases = [
            (
                {"type": "string", "minLength": 1, "maxLength": 2},
                {"type": "array", "minItems": 1, "maxItems": 1},
            ),
            (
                {
                    "type": "array",
                    "contains": {"const": 1},
                    "minContains": 1,
                    "maxContains": 1,
                },
                {"type": "object", "required": ["a"]},
            ),
            (
                {"type": "array", "uniqueItems": True, "minItems": 2, "maxItems": 2},
                {"type": "string"},
            ),
            (
                {"type": "object", "required": ["a"]},
                {"type": "array", "minItems": 1, "maxItems": 1},
            ),
            (
                {"type": "object", "minProperties": 1},
                {"type": "string", "minLength": 1},
            ),
            (
                {"type": "object", "minProperties": 1},
                {"type": "array", "minItems": 1},
            ),
        ]

        for lhs, rhs in cases:
            with self.subTest(lhs=lhs, rhs=rhs):
                self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012))


class TestStringLengthDomainProof(unittest.TestCase):
    def test_length_interval_subtype_is_proved(self):
        lhs = {"type": "string", "minLength": 2, "maxLength": 4}
        rhs = {"type": "string", "minLength": 1}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_length_interval_counterexample_is_proved(self):
        lhs = {"type": "string", "minLength": 2}
        rhs = {"type": "string", "maxLength": 1}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_not_min_length_interval_is_proved(self):
        lhs = {"type": "string", "maxLength": 1}
        rhs = {
            "allOf": [{"type": "string"}, {"not": {"type": "string", "minLength": 2}}]
        }

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_any_of_length_union_is_proved(self):
        lhs = {
            "anyOf": [
                {"type": "string", "maxLength": 1},
                {"type": "string", "minLength": 3},
            ]
        }
        rhs = {"type": "string", "not": {"minLength": 2, "maxLength": 2}}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))


class TestStringLanguageDomainProof(unittest.TestCase):
    def test_pattern_subtype_is_proved(self):
        lhs = {"type": "string", "pattern": "^ab", "maxLength": 4}
        rhs = {"type": "string", "pattern": "^a", "minLength": 2}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_pattern_counterexample_is_proved(self):
        lhs = {"type": "string", "pattern": "^a"}
        rhs = {"type": "string", "pattern": "^b"}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_negated_pattern_is_proved(self):
        lhs = {"type": "string", "maxLength": 1}
        rhs = {"type": "string", "not": {"pattern": "^ab"}}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_negated_language_counterexample_is_found_before_complementing_rhs(self):
        lhs = {"type": "string", "pattern": "[^a]"}
        rhs = {"not": {"type": "string", "minLength": 5, "pattern": "a"}}

        self.assertFalse(is_subschema(lhs, rhs))


class TestArrayLengthDomainProof(unittest.TestCase):
    def test_length_interval_subtype_is_proved(self):
        lhs = {"type": "array", "minItems": 2, "maxItems": 4}
        rhs = {"type": "array", "minItems": 1}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_length_interval_counterexample_is_proved(self):
        lhs = {"type": "array", "minItems": 2}
        rhs = {"type": "array", "maxItems": 1}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_not_min_items_interval_is_proved(self):
        lhs = {"type": "array", "maxItems": 1}
        rhs = {"allOf": [{"type": "array"}, {"not": {"type": "array", "minItems": 2}}]}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_any_of_length_union_is_proved(self):
        lhs = {
            "anyOf": [
                {"type": "array", "maxItems": 1},
                {"type": "array", "minItems": 3},
            ]
        }
        rhs = {"type": "array", "not": {"minItems": 2, "maxItems": 2}}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_draft7_tuple_tail_false_implies_max_items(self):
        lhs = {
            "type": "array",
            "items": [{"type": "integer"}, {"type": "string"}],
            "additionalItems": False,
        }
        rhs = {"type": "array", "maxItems": 2}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT7))

    def test_items_false_implies_empty_array(self):
        lhs = {"type": "array", "items": False}
        rhs = {"type": "array", "maxItems": 0}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_202012_prefix_items_tail_false_implies_max_items(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": False,
        }
        rhs = {"type": "array", "maxItems": 1}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012))

    def test_202012_items_false_implies_empty_array(self):
        lhs = {"type": "array", "items": False}
        rhs = {"type": "array", "maxItems": 0}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012))

    def test_array_length_rule_does_not_prove_incomplete_non_array_left_language(self):
        lhs = {"not": {"type": "array", "items": {"type": "integer"}}}
        rhs = {"type": "string"}
        proof = engine_module.ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
        ).is_subschema(lhs, rhs)

        self.assertNotEqual(proof.status, "proved_true")


class TestArrayUniquenessDomainProof(unittest.TestCase):
    def test_unique_items_implies_non_unique_items(self):
        lhs = {"type": "array", "uniqueItems": True}
        rhs = {"type": "array", "uniqueItems": False}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_non_unique_items_counterexample_is_proved(self):
        lhs = {"type": "array", "uniqueItems": False}
        rhs = {"type": "array", "uniqueItems": True}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_non_unique_typed_items_construct_duplicate_witness(self):
        lhs = {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 2,
            "uniqueItems": False,
        }
        rhs = {"type": "array", "uniqueItems": True}
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "array uniqueness duplicate witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(len(proof.witness), 2)
        self.assertEqual(proof.witness[0], proof.witness[1])
        self.assertIsInstance(proof.witness[0], int)

    def test_short_arrays_are_unique(self):
        lhs = {"type": "array", "maxItems": 1}
        rhs = {"type": "array", "uniqueItems": True}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_closed_empty_arrays_are_unique(self):
        lhs = {"type": "array", "items": False}
        rhs = {"type": "array", "uniqueItems": True}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_untyped_unique_items_may_include_non_array(self):
        lhs = {"uniqueItems": True}
        rhs = {"type": "array", "uniqueItems": True}

        self.assertFalse(is_subschema(lhs, rhs))


class TestArrayContainsDomainProof(unittest.TestCase):
    def test_contains_schema_subtype_is_proved(self):
        lhs = {"type": "array", "contains": {"type": "integer"}}
        rhs = {"type": "array", "contains": {"type": "number"}}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_contains_schema_counterexample_is_proved(self):
        lhs = {"type": "array", "contains": {"type": "number"}}
        rhs = {"type": "array", "contains": {"type": "integer"}}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_min_contains_zero_is_vacuous(self):
        lhs = {"type": "array"}
        rhs = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
        }

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT201909))

    def test_homogeneous_items_imply_min_contains(self):
        lhs = {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 2,
        }
        rhs = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 2,
        }

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT201909))

    def test_empty_homogeneous_array_counterexample(self):
        lhs = {"type": "array", "items": {"type": "integer"}}
        rhs = {"type": "array", "contains": {"type": "integer"}}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_required_tuple_item_implies_contains(self):
        lhs = {
            "type": "array",
            "items": [{"type": "integer"}, {"type": "string"}],
            "minItems": 1,
        }
        rhs = {"type": "array", "contains": {"type": "integer"}}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_max_contains_uses_max_items(self):
        lhs = {
            "type": "array",
            "items": {"type": "integer"},
            "maxItems": 1,
        }
        rhs = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
            "maxContains": 1,
        }

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT201909))

    def test_max_contains_counterexample(self):
        lhs = {
            "type": "array",
            "items": {"type": "integer"},
            "maxItems": 2,
        }
        rhs = {
            "type": "array",
            "contains": {"type": "integer"},
            "minContains": 0,
            "maxContains": 1,
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT201909))

    def test_202012_tail_items_imply_contains(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "items": {"type": "string"},
            "minItems": 2,
        }
        rhs = {
            "type": "array",
            "contains": {"type": "string"},
            "minContains": 1,
        }

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012))


class TestObjectPropertyCountDomainProof(unittest.TestCase):
    def test_property_count_interval_subtype_is_proved(self):
        lhs = {"type": "object", "minProperties": 2, "maxProperties": 4}
        rhs = {"type": "object", "minProperties": 1}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_property_count_interval_counterexample_is_proved(self):
        lhs = {"type": "object", "minProperties": 2}
        rhs = {"type": "object", "maxProperties": 1}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_not_min_properties_interval_is_proved(self):
        lhs = {"type": "object", "maxProperties": 1}
        rhs = {
            "allOf": [
                {"type": "object"},
                {"not": {"type": "object", "minProperties": 2}},
            ]
        }

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_any_of_property_count_union_is_proved(self):
        lhs = {
            "anyOf": [
                {"type": "object", "maxProperties": 1},
                {"type": "object", "minProperties": 3},
            ]
        }
        rhs = {"type": "object", "not": {"minProperties": 2, "maxProperties": 2}}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))


class TestObjectPresenceDomainProof(unittest.TestCase):
    def test_required_superset_is_proved(self):
        lhs = {"type": "object", "required": ["a", "b"]}
        rhs = {"type": "object", "required": ["a"]}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertFalse(is_subschema(rhs, lhs))

    def test_not_required_is_proved(self):
        lhs = {"type": "object"}
        rhs = {"not": {"required": ["a"]}}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_right_not_required_intersection_uses_constructive_object_witness(self):
        rhs = {"not": {"type": "object", "required": ["a"]}}
        cases = [
            {"not": {"enum": [1]}},
            {"not": {"enum": ["a"]}},
            {"not": {"type": "array", "maxItems": 0}},
        ]

        for lhs in cases:
            with self.subTest(lhs=lhs):
                self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012))

    def test_presence_product_does_not_collapse_fresh_keyspace_for_overlapping_one_of(
        self,
    ):
        lhs = {"oneOf": [True, {"type": "object", "maxProperties": 1}]}
        rhs = {"not": {"type": "object"}}
        proof = engine_module.ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
        ).is_subschema(lhs, rhs)

        self.assertNotEqual(proof.status, "proved_true")

    def test_presence_product_does_not_treat_one_of_as_union_for_value_constraints(
        self,
    ):
        lhs = {
            "oneOf": [
                True,
                {"type": "object", "properties": {"a": {"type": "integer"}}},
            ]
        }
        rhs = {"oneOf": [True, {"type": "object"}]}
        proof = engine_module.ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
        ).is_subschema(lhs, rhs)

        self.assertNotEqual(proof.status, "proved_true")

    def test_presence_product_does_not_ignore_negated_property_value_constraints(self):
        lhs = {"not": {"type": "object", "properties": {"a": {"type": "integer"}}}}
        rhs = {"not": {"type": "object"}}
        proof = engine_module.ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
        ).is_subschema(lhs, rhs)

        self.assertNotEqual(proof.status, "proved_true")

    def test_dependent_required_closure_is_proved(self):
        dependency = {
            "type": "object",
            "required": ["credit_card"],
            "dependentRequired": {"credit_card": ["billing_address"]},
        }
        explicit_required = {
            "type": "object",
            "required": ["billing_address", "credit_card"],
        }

        self.assertTrue(
            is_subschema(dependency, explicit_required, dialect=Dialect.DRAFT201909)
        )
        self.assertTrue(
            is_subschema(explicit_required, dependency, dialect=Dialect.DRAFT201909)
        )

    def test_array_valued_dependencies_are_proved(self):
        dependency = {
            "type": "object",
            "required": ["credit_card"],
            "dependencies": {"credit_card": ["billing_address"]},
        }
        explicit_required = {
            "type": "object",
            "required": ["billing_address", "credit_card"],
        }

        self.assertTrue(
            is_subschema(
                dependency,
                explicit_required,
                dialect=Dialect.DRAFT7,
            )
        )
        self.assertTrue(
            is_subschema(
                explicit_required,
                dependency,
                dialect=Dialect.DRAFT7,
            )
        )

    def test_dependent_schemas_required_closure_is_proved(self):
        dependency = {
            "type": "object",
            "required": ["credit_card"],
            "dependentSchemas": {"credit_card": {"required": ["billing_address"]}},
        }
        explicit_required = {
            "type": "object",
            "required": ["billing_address", "credit_card"],
        }

        self.assertTrue(
            is_subschema(dependency, explicit_required, dialect=Dialect.DRAFT201909)
        )
        self.assertTrue(
            is_subschema(explicit_required, dependency, dialect=Dialect.DRAFT201909)
        )

    def test_dependent_schemas_all_of_merge_is_proved(self):
        combined = {
            "allOf": [
                {
                    "type": "object",
                    "dependentSchemas": {
                        "credit_card": {"required": ["billing_address"]}
                    },
                },
                {
                    "type": "object",
                    "dependentSchemas": {"credit_card": {"required": ["zip"]}},
                },
            ]
        }
        expected = {
            "type": "object",
            "dependentSchemas": {
                "credit_card": {"required": ["billing_address", "zip"]}
            },
        }

        self.assertTrue(is_subschema(combined, expected, dialect=Dialect.DRAFT201909))
        self.assertTrue(is_subschema(expected, combined, dialect=Dialect.DRAFT201909))

    def test_one_of_required_overlap_is_proved(self):
        lhs = {"type": "object", "required": ["a", "b"]}
        rhs = {
            "oneOf": [
                {"type": "object", "required": ["a"]},
                {"type": "object", "required": ["b"]},
            ]
        }

        self.assertFalse(is_subschema(lhs, rhs))


class TestObjectStructureDomainProof(unittest.TestCase):
    def test_required_implies_min_properties(self):
        lhs = {"type": "object", "required": ["a", "b"]}
        rhs = {"type": "object", "minProperties": 2}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertFalse(is_subschema(rhs, lhs))

    def test_required_and_max_properties_are_disjoint(self):
        lhs = {"type": "object", "maxProperties": 1}
        rhs = {"type": "object", "required": ["a", "b"]}

        self.assertFalse(is_subschema(lhs, rhs))
        self.assertFalse(is_subschema(rhs, lhs))

    def test_dependency_implies_property_count(self):
        lhs = {
            "type": "object",
            "required": ["credit_card"],
            "dependentRequired": {"credit_card": ["billing_address"]},
        }
        rhs = {"type": "object", "minProperties": 2}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT201909))
        self.assertFalse(is_subschema(rhs, lhs, dialect=Dialect.DRAFT201909))

    def test_any_of_mixed_presence_and_count(self):
        lhs = {
            "anyOf": [
                {"type": "object", "required": ["a"]},
                {"type": "object", "minProperties": 2},
            ]
        }
        rhs = {"type": "object", "not": {"maxProperties": 0}}

        self.assertTrue(is_subschema(lhs, rhs))

    def test_required_with_negated_count(self):
        lhs = {"type": "object", "required": ["a"], "maxProperties": 1}
        rhs = {"type": "object", "required": ["a"], "not": {"minProperties": 2}}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))


class TestObjectPropertyValuesDomainProof(unittest.TestCase):
    def test_open_property_value_subtype_is_proved(self):
        lhs = {"type": "object", "properties": {"age": {"type": "integer"}}}
        rhs = {"type": "object", "properties": {"age": {"type": "number"}}}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertFalse(is_subschema(rhs, lhs))

    def test_open_property_value_subtype_preserves_non_object_acceptance(self):
        lhs = {"properties": {"age": {"type": "integer"}}}
        rhs = {"properties": {"age": {"type": "number"}}}

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertFalse(is_subschema(rhs, lhs))

    def test_open_property_value_detects_non_object_counterexample(self):
        lhs = {"properties": {"age": {"type": "integer"}}}
        rhs = {"type": "object", "properties": {"age": {"type": "integer"}}}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_open_property_value_all_of_constraints_are_combined(self):
        lhs = {
            "allOf": [
                {"type": "object", "properties": {"age": {"type": "integer"}}},
                {
                    "type": "object",
                    "properties": {"name": {"type": "string", "minLength": 2}},
                },
            ]
        }
        rhs = {
            "type": "object",
            "properties": {"age": {"type": "number"}, "name": {"type": "string"}},
        }

        self.assertTrue(is_subschema(lhs, rhs))


class TestObjectClosedPropertiesDomainProof(unittest.TestCase):
    def test_closed_property_value_subtype_is_proved(self):
        lhs = {
            "type": "object",
            "properties": {"age": {"type": "integer"}},
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "properties": {"age": {"type": "number"}},
            "additionalProperties": False,
        }

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertFalse(is_subschema(rhs, lhs))

    def test_closed_property_value_counterexample_is_valid_object(self):
        lhs = {
            "type": "object",
            "properties": {"age": {"type": "number"}},
            "required": ["age"],
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "properties": {"age": {"type": "integer"}},
            "required": ["age"],
            "additionalProperties": False,
        }

        self.assertFalse(is_subschema(lhs, rhs))

    def test_closed_property_all_of_constraints_are_proved(self):
        lhs = {
            "type": "object",
            "properties": {"age": {"type": "integer", "minimum": 5, "maximum": 10}},
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "properties": {"age": {"type": "number", "minimum": 4}},
            "additionalProperties": False,
        }

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertFalse(is_subschema(rhs, lhs))

    def test_closed_property_required_keyspace_is_proved(self):
        lhs = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        }

        self.assertFalse(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))

    def test_closed_properties_can_satisfy_rhs_pattern_properties(self):
        lhs = {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "emaik": {"type": "string"},
            },
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "patternProperties": {"^emai(l|k)$": {"type": "string"}},
            "additionalProperties": False,
        }

        self.assertTrue(is_subschema(lhs, rhs))

    def test_closed_property_value_violates_rhs_pattern(self):
        lhs = {
            "type": "object",
            "properties": {"email": {"type": "integer"}},
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "patternProperties": {"^emai": {"type": "string"}},
            "additionalProperties": False,
        }

        self.assertFalse(is_subschema(lhs, rhs))

    def test_closed_property_must_satisfy_all_matching_rhs_patterns(self):
        lhs = {
            "type": "object",
            "properties": {"ab": {"type": "integer"}},
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "patternProperties": {
                "^a": {"type": "number"},
                "b$": {"type": "integer", "minimum": 5},
            },
            "additionalProperties": False,
        }

        self.assertFalse(is_subschema(lhs, rhs))

    def test_closed_property_combines_explicit_and_pattern_constraints(self):
        lhs = {
            "type": "object",
            "properties": {"email": {"type": "string", "minLength": 2}},
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "properties": {"email": {"type": "string"}},
            "patternProperties": {"^email$": {"minLength": 2}},
            "additionalProperties": False,
        }

        self.assertTrue(is_subschema(lhs, rhs))

    def test_closed_all_of_intersects_explicit_and_pattern_keyspaces(self):
        lhs = {
            "allOf": [
                {
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "patternProperties": {"^email$": {"minLength": 2}},
                    "additionalProperties": False,
                },
            ]
        }
        rhs = {
            "type": "object",
            "properties": {"email": {"type": "string", "minLength": 2}},
            "additionalProperties": False,
        }

        self.assertTrue(is_subschema(lhs, rhs))
        self.assertTrue(is_subschema(rhs, lhs))


class TestObjectPropertyNamesDomainProof(unittest.TestCase):
    def test_restricted_property_names_are_object_subtype(self):
        lhs = {"type": "object", "propertyNames": {"pattern": "^a"}}
        rhs = {"type": "object"}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_arbitrary_object_counterexample_is_proved(self):
        lhs = {"type": "object"}
        rhs = {"type": "object", "propertyNames": {"pattern": "^a"}}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_property_name_pattern_subtype_is_proved(self):
        lhs = {"type": "object", "propertyNames": {"pattern": "^alpha"}}
        rhs = {"type": "object", "propertyNames": {"pattern": "^a"}}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))
        self.assertFalse(is_subschema(rhs, lhs, dialect=Dialect.DRAFT6))

    def test_required_key_rejected_by_property_names_is_proved_empty(self):
        lhs = {
            "type": "object",
            "required": ["beta"],
            "propertyNames": {"pattern": "^a"},
        }

        self.assertTrue(is_subschema(lhs, False, dialect=Dialect.DRAFT6))

    def test_all_of_property_names_is_proved(self):
        lhs = {
            "allOf": [
                {"type": "object", "propertyNames": {"pattern": "^a"}},
                {"type": "object", "propertyNames": {"minLength": 2}},
            ]
        }
        rhs = {"type": "object", "propertyNames": {"pattern": "^a", "minLength": 2}}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))
        self.assertTrue(is_subschema(rhs, lhs, dialect=Dialect.DRAFT6))

    def test_closed_properties_can_satisfy_property_names(self):
        lhs = {
            "type": "object",
            "properties": {"alpha": {"type": "number"}},
            "additionalProperties": False,
        }
        rhs = {"type": "object", "propertyNames": {"pattern": "^a"}}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_closed_properties_can_violate_property_names(self):
        lhs = {
            "type": "object",
            "properties": {"beta": {"type": "number"}},
            "additionalProperties": False,
        }
        rhs = {"type": "object", "propertyNames": {"pattern": "^a"}}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_closed_keyspace_subset_is_proved(self):
        lhs = {
            "type": "object",
            "properties": {"alpha": True},
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "properties": {"alpha": True, "beta": True},
            "additionalProperties": False,
        }

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))
        self.assertFalse(is_subschema(rhs, lhs, dialect=Dialect.DRAFT6))

    def test_open_property_names_is_not_closed_keyspace(self):
        lhs = {"type": "object", "propertyNames": {"pattern": "^a"}}
        rhs = {
            "type": "object",
            "properties": {"alpha": True},
            "additionalProperties": False,
        }

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_closed_pattern_properties_can_satisfy_property_names(self):
        lhs = {
            "type": "object",
            "patternProperties": {"^a": {"type": "number"}},
            "additionalProperties": False,
        }
        rhs = {"type": "object", "propertyNames": {"pattern": "^a"}}

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_closed_pattern_properties_can_violate_property_names(self):
        lhs = {
            "type": "object",
            "patternProperties": {"^b": {"type": "number"}},
            "additionalProperties": False,
        }
        rhs = {"type": "object", "propertyNames": {"pattern": "^a"}}

        self.assertFalse(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))

    def test_closed_pattern_keyspace_subset_is_proved(self):
        lhs = {
            "type": "object",
            "patternProperties": {"^alpha": True},
            "additionalProperties": False,
        }
        rhs = {
            "type": "object",
            "patternProperties": {"^a": True},
            "additionalProperties": False,
        }

        self.assertTrue(is_subschema(lhs, rhs, dialect=Dialect.DRAFT6))
        self.assertFalse(is_subschema(rhs, lhs, dialect=Dialect.DRAFT6))


class TestIREngineHardFeatures(unittest.TestCase):
    def test_negated_object_schema_uses_witness_search(self):
        lhs = {
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "integer"}},
        }
        rhs = {"not": {"type": "object", "required": ["a"]}}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_one_of_overlap_is_not_rewritten_away(self):
        lhs = {"const": 1}
        rhs = {"oneOf": [{"type": "number"}, {"const": 1}]}

        self.assertFalse(is_subschema(lhs, rhs))

    def test_unevaluated_properties_across_all_of(self):
        closed = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [
                {
                    "type": "object",
                    "properties": {"foo": {"type": "string"}},
                }
            ],
            "unevaluatedProperties": False,
        }

        with self.subTest("matching finite object is accepted"):
            self.assertTrue(
                is_subschema(
                    {"const": {"foo": "a"}},
                    closed,
                    dialect=Dialect.DRAFT202012,
                )
            )

        with self.subTest("extra property is rejected"):
            self.assertFalse(
                is_subschema(
                    {"const": {"foo": "a", "extra": 1}},
                    closed,
                    dialect=Dialect.DRAFT202012,
                )
            )

    def test_local_unevaluated_properties_constructs_solver_owned_witness(self):
        lhs = {"type": "object"}
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "properties": {"foo": {"type": "string"}},
            "unevaluatedProperties": False,
        }
        engine = ProofEngine.for_schemas(lhs, rhs, dialect=Dialect.DRAFT202012)

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "local unevaluatedProperties witness should not need constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertIsInstance(proof.witness, dict)
        self.assertEqual(len(proof.witness), 1)
        self.assertNotIn("foo", proof.witness)

    def test_all_of_unevaluated_properties_uses_child_evaluation_frontier(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [{"properties": {"foo": {"type": "string"}}}],
            "unevaluatedProperties": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "allOf unevaluatedProperties true proof must not use constructive proof path"
            )

        with (
            patch.object(
                engine.context,
                "unexpected_proof_path",
                fail_unexpected_proof_path,
                create=True,
            ),
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_all_of_unevaluated_properties_checks_child_value_schema(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "number"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [{"properties": {"foo": {"type": "string"}}}],
            "unevaluatedProperties": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "allOf unevaluatedProperties value proof must not use constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(set(proof.witness), {"foo"})
        self.assertIsInstance(proof.witness["foo"], int | float)

    def test_all_of_unevaluated_properties_does_not_ignore_other_assertions(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [
                {
                    "properties": {"foo": {"type": "string"}},
                    "required": ["bar"],
                }
            ],
            "unevaluatedProperties": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "unsupported")
        self.assertIn("unevaluatedProperties", proof.reason)

    def test_all_of_unevaluated_items_uses_child_evaluation_frontier(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}, {"type": "string"}],
            "maxItems": 2,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [{"prefixItems": [{"type": "number"}, {"type": "string"}]}],
            "unevaluatedItems": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "allOf unevaluatedItems true proof must not use constructive proof path"
            )

        with (
            patch.object(
                engine.context,
                "unexpected_proof_path",
                fail_unexpected_proof_path,
                create=True,
            ),
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_all_of_unevaluated_items_checks_child_value_schema(self):
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
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "allOf unevaluatedItems value proof must not use constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(len(proof.witness), 1)
        self.assertIsInstance(proof.witness[0], int | float)

    def test_all_of_unevaluated_items_constructs_extra_item_witness(self):
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
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "allOf unevaluatedItems extra item witness must not use constructive proof path"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(len(proof.witness), 2)

    def test_all_of_unevaluated_items_does_not_ignore_other_assertions(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "maxItems": 1,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [
                {
                    "prefixItems": [{"type": "number"}],
                    "minItems": 2,
                }
            ],
            "unevaluatedItems": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "unsupported")
        self.assertIn("unevaluatedItems", proof.reason)

    def test_static_ref_unevaluated_properties_uses_referenced_evaluation_effect(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "object": {
                    "type": "object",
                    "properties": {"foo": {"type": "string"}},
                }
            },
            "allOf": [{"$ref": "#/$defs/object"}],
            "unevaluatedProperties": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "static-ref unevaluatedProperties true proof must not use bounded search"
            )

        with (
            patch.object(
                engine.context,
                "unexpected_proof_path",
                fail_unexpected_proof_path,
                create=True,
            ),
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_static_ref_unevaluated_properties_checks_referenced_value_schema(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "number"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"object": {"properties": {"foo": {"type": "string"}}}},
            "allOf": [{"$ref": "#/$defs/object"}],
            "unevaluatedProperties": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "static-ref unevaluatedProperties value proof must not use bounded search"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(set(proof.witness), {"foo"})
        self.assertIsInstance(proof.witness["foo"], int | float)

    def test_static_ref_unevaluated_items_uses_referenced_evaluation_effect(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "maxItems": 1,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "array": {
                    "type": "array",
                    "prefixItems": [{"type": "number"}],
                }
            },
            "allOf": [{"$ref": "#/$defs/array"}],
            "unevaluatedItems": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "static-ref unevaluatedItems true proof must not use bounded search"
            )

        with (
            patch.object(
                engine.context,
                "unexpected_proof_path",
                fail_unexpected_proof_path,
                create=True,
            ),
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_evaluation_expression_records_reference_and_branch_provenance(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"object": {"properties": {"foo": {"type": "string"}}}},
            "allOf": [{"$ref": "#/$defs/object"}],
            "anyOf": [{"properties": {"foo": {"type": "string"}}}, False],
            "unevaluatedProperties": False,
        }
        formula = DifferenceFormula.from_schemas(lhs, rhs, Dialect.DRAFT202012)
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        expression = evaluation_module.evaluation_expression_for_source(
            formula.rhs.source,
            formula.rhs.graph,
            lhs_schema=lhs,
            context=engine.context,
        )

        kinds = [origin.kind for origin in expression.origins]
        self.assertIn("anyOf", kinds)
        self.assertIn("static-ref", kinds)
        self.assertIn("local", kinds)
        static_ref_origin = next(
            origin for origin in expression.origins if origin.kind == "static-ref"
        )
        self.assertEqual(static_ref_origin.source_pointer, ("allOf", "0"))
        self.assertEqual(static_ref_origin.target_pointer, ("$defs", "object"))
        self.assertEqual(static_ref_origin.target_document_pointer, ("$defs", "object"))

    def test_evaluation_expression_cache_reuses_branch_subproofs(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "anyOf": [
                {"properties": {"foo": {"type": "string"}}},
                {"properties": {"bar": {"type": "number"}}},
            ],
            "unevaluatedProperties": False,
        }
        formula = DifferenceFormula.from_schemas(lhs, rhs, Dialect.DRAFT202012)
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        with patch.object(
            engine.context, "subproof", wraps=engine.context.subproof
        ) as subproof:
            first = evaluation_module.evaluation_expression_for_source(
                formula.rhs.source,
                formula.rhs.graph,
                lhs_schema=lhs,
                context=engine.context,
            )
            first_call_count = subproof.call_count
            second = evaluation_module.evaluation_expression_for_source(
                formula.rhs.source,
                formula.rhs.graph,
                lhs_schema=lhs,
                context=engine.context,
            )

        self.assertIs(first, second)
        self.assertGreater(first_call_count, 0)
        self.assertEqual(subproof.call_count, first_call_count)
        self.assertTrue(engine.context.cache)

    def test_evaluation_trace_facade_preserves_expression_sources(self):
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
        formula = DifferenceFormula.from_schemas(lhs, rhs, Dialect.DRAFT202012)
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        trace = evaluation_trace_for_source(
            formula.rhs.source,
            formula.rhs.graph,
            lhs_schema=lhs,
            context=engine.context,
        )
        expression = trace.to_expression()

        self.assertIsInstance(trace, EvaluationTraceExpression)
        self.assertEqual(len(trace.paths), 1)
        self.assertTrue(trace.has_effects())
        self.assertEqual(trace.evaluated_property_sources, expression.property_sources)
        self.assertEqual(trace.evaluated_item_sources, expression.item_sources)
        self.assertEqual(trace.origins, expression.origins)
        self.assertTrue(expression.is_supported)
        self.assertEqual(expression.property_sources[0].key, "foo")
        self.assertIn("anyOf", {origin.kind for origin in expression.origins})

    def test_schema_valued_unevaluated_properties_creates_value_obligations(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "integer"}},
            "additionalProperties": False,
        }
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

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "schema-valued unevaluatedProperties proof must not use bounded search"
            )

        with (
            patch.object(
                engine.context,
                "unexpected_proof_path",
                fail_unexpected_proof_path,
                create=True,
            ),
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_schema_valued_unevaluated_properties_validates_value_witness(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "additionalProperties": False,
        }
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

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "schema-valued unevaluatedProperties witness must not use bounded search"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(set(proof.witness), {"foo"})
        self.assertIsInstance(proof.witness["foo"], str)

    def test_schema_valued_unevaluated_items_creates_item_obligations(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "maxItems": 1,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "unevaluatedItems": {"type": "number"},
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "schema-valued unevaluatedItems proof must not use bounded search"
            )

        with (
            patch.object(
                engine.context,
                "unexpected_proof_path",
                fail_unexpected_proof_path,
                create=True,
            ),
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_schema_valued_unevaluated_items_validates_item_witness(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "maxItems": 1,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "unevaluatedItems": {"type": "number"},
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "schema-valued unevaluatedItems witness must not use bounded search"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_false")
        self.assertEqual(len(proof.witness), 1)
        self.assertIsInstance(proof.witness[0], str)

    def test_any_of_unevaluated_properties_uses_proved_successful_branch_effect(self):
        lhs = {
            "type": "object",
            "required": ["foo"],
            "properties": {"foo": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "anyOf": [
                {
                    "properties": {"foo": {"type": "string"}},
                },
                {
                    "properties": {"bar": {"type": "string"}},
                },
            ],
            "unevaluatedProperties": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "covered anyOf unevaluatedProperties proof must not use bounded search"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_one_of_unevaluated_properties_uses_unique_successful_branch_effect(self):
        lhs = {
            "type": "object",
            "required": ["foo"],
            "properties": {"foo": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "oneOf": [
                {
                    "type": "object",
                    "properties": {"foo": {"type": "string"}},
                },
                False,
            ],
            "unevaluatedProperties": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "covered oneOf unevaluatedProperties proof must not use bounded search"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_conditional_unevaluated_items_uses_proved_then_branch_effect(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "minItems": 1,
            "maxItems": 1,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "if": {"type": "array"},
            "then": {"prefixItems": [{"type": "number"}]},
            "else": {"prefixItems": [{"type": "string"}]},
            "unevaluatedItems": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "covered conditional unevaluatedItems proof must not use bounded search"
            )

        with patch.object(
            engine.context,
            "unexpected_proof_path",
            fail_unexpected_proof_path,
            create=True,
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_dynamic_ref_evaluation_effect_boundary_stays_unsupported(self):
        lhs = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "additionalProperties": False,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$dynamicAnchor": "node",
            "allOf": [{"$dynamicRef": "#node"}],
            "unevaluatedProperties": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "unsupported")
        self.assertIn("$dynamicRef", proof.reason)

    def test_unevaluated_items_counts_contains_matches(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "contains": {"type": "integer"},
            "unevaluatedItems": False,
        }

        with self.subTest("contains match is evaluated"):
            self.assertTrue(
                is_subschema({"const": [1]}, schema, dialect=Dialect.DRAFT202012)
            )

        with self.subTest("non-matching item remains unevaluated"):
            self.assertFalse(
                is_subschema({"const": ["x"]}, schema, dialect=Dialect.DRAFT202012)
            )

    def test_unevaluated_items_uses_guaranteed_contains_match_effect(self):
        lhs = {
            "type": "array",
            "prefixItems": [{"type": "integer"}],
            "minItems": 1,
            "maxItems": 1,
        }
        rhs = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "contains": {"type": "number"},
            "unevaluatedItems": False,
        }
        engine = ProofEngine.for_schemas(
            lhs,
            rhs,
            dialect=Dialect.DRAFT202012,
            options=ProofOptions(),
        )

        def fail_unexpected_proof_path(*_args, **_kwargs):
            raise AssertionError(
                "guaranteed contains evaluated-item proof must not use bounded search"
            )

        with (
            patch.object(
                engine.context,
                "unexpected_proof_path",
                fail_unexpected_proof_path,
                create=True,
            ),
        ):
            proof = engine._bounded_ir_proof(lhs, rhs)

        self.assertEqual(proof.status, "proved_true")

    def test_concrete_evaluator_matches_jsonschema_for_scalar_constraints(self):
        assert_concrete_evaluator_matches_validator(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "number",
                "minimum": 1,
                "exclusiveMaximum": 5,
                "multipleOf": 0.5,
            },
            [1, 1.5, 5, 1.25, "x", True],
        )
        assert_concrete_evaluator_matches_validator(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "string",
                "minLength": 2,
                "maxLength": 4,
                "pattern": "^a",
            },
            ["a", "ab", "abcd", "abcde", "ba", 1],
        )

    def test_concrete_evaluator_matches_jsonschema_for_array_constraints(self):
        assert_concrete_evaluator_matches_validator(
            {
                "$schema": "http://json-schema.org/draft-07/schema",
                "type": "array",
                "items": [{"type": "integer"}],
                "additionalItems": {"type": "string"},
                "minItems": 1,
                "maxItems": 3,
                "uniqueItems": True,
            },
            [[1], [1, "a"], [1, 2], [], [1, "a", "b", "c"], [1, "a", 1]],
            Dialect.DRAFT7,
        )
        assert_concrete_evaluator_matches_validator(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "array",
                "prefixItems": [{"type": "integer"}],
                "items": {"type": "string"},
                "uniqueItems": True,
            },
            [[1], [1, "a"], [1, 2], [1, "a", "a"]],
        )

    def test_concrete_evaluator_matches_jsonschema_for_object_constraints(self):
        assert_concrete_evaluator_matches_validator(
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
                "dependentSchemas": {
                    "billing_address": {
                        "properties": {"zip": {"type": "string"}},
                    }
                },
                "additionalProperties": False,
            },
            [
                {"credit_card": 1, "billing_address": "x"},
                {"credit_card": 1},
                {"Billing": "x"},
                {},
                {"credit_card": 1, "billing_address": "x", "zip": "1", "extra": "x"},
                {"billing_address": "x", "zip": 1},
            ],
        )

    def test_concrete_evaluator_matches_jsonschema_for_unevaluated_items_contains(self):
        assert_concrete_evaluator_matches_validator(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "contains": {"type": "integer"},
                "unevaluatedItems": False,
            },
            ([1], ["x"], [1, "x"]),
        )

    def test_concrete_evaluator_reports_recursive_refs_unsupported(self):
        assert_concrete_evaluator_unsupported(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$defs": {
                    "node": {
                        "$ref": "#/$defs/node",
                    }
                },
                "$ref": "#/$defs/node",
            },
            "value",
            reason_contains="recursive schema",
        )

    def test_concrete_evaluator_resolves_acyclic_dynamic_ref(self):
        assert_concrete_evaluator_matches_validator(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$defs": {
                    "node": {
                        "$dynamicAnchor": "node",
                        "type": "string",
                    }
                },
                "$dynamicRef": "#node",
            },
            ("ok", 1),
        )

    def test_complex_finite_values_work_with_meet_and_join_projection(self):
        lhs = {"const": {"a": 1}}
        rhs = {"type": "object"}

        self.assertEqual(meet_schemas(lhs, rhs, dialect=Dialect.DRAFT7), lhs)
        self.assertEqual(join_schemas(lhs, rhs, dialect=Dialect.DRAFT7), rhs)
