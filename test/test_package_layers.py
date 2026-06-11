import ast
import importlib
import re
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = REPO_ROOT / "src" / "subschema"
TEST_ROOT = REPO_ROOT / "test"
PROVER_ROOT = PACKAGE_ROOT / "prover"
IR_ROOT = PACKAGE_ROOT / "ir"
PROVER_PREFIX = "subschema.prover"
BACKEND_OWNERS = {
    "greenery": "subschema.regex",
    "json": "subschema.json_data",
    "jsonschema": "subschema.validator",
    "jsonschema_rs": "subschema.validator",
    "z3": "subschema.symbolic",
}
NETWORK_IMPORT_PREFIXES = (
    "aiohttp",
    "ftplib",
    "http.client",
    "httpx",
    "requests",
    "socket",
    "urllib.request",
    "urllib3",
)
NETWORK_CALL_NAMES = {
    "HTTPConnection",
    "HTTPSConnection",
    "Request",
    "create_connection",
    "urlopen",
    "urlretrieve",
}


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    line: int
    scope: str

    def format(self) -> str:
        return f"{self.source} -> {self.target} ({self.scope}, line {self.line})"


def test_prover_runtime_imports_respect_layer_boundaries():
    violations: list[str] = []
    for edge in _runtime_import_edges():
        reason = _forbidden_runtime_edge_reason(edge)
        if reason is not None:
            violations.append(f"{edge.format()}: {reason}")

    assert not violations, "forbidden prover import edges:\n" + "\n".join(violations)


def test_prover_type_checking_imports_do_not_leak_domain_types_into_context():
    violations: list[str] = []
    for edge in _type_checking_import_edges():
        reason = _forbidden_type_checking_edge_reason(edge)
        if reason is not None:
            violations.append(f"{edge.format()}: {reason}")

    assert not violations, "forbidden type-checking import edges:\n" + "\n".join(
        violations
    )


def test_backend_imports_are_owned_by_backend_modules():
    violations: list[str] = []
    for edge in _runtime_import_edges():
        target_root = edge.target.split(".", 1)[0]
        owner = BACKEND_OWNERS.get(target_root)
        if owner is not None and edge.source != owner:
            violations.append(
                f"{edge.format()}: {target_root} is owned by {owner}"
            )

    assert not violations, "backend imports must stay isolated:\n" + "\n".join(
        violations
    )


def test_source_does_not_fetch_network_resources():
    violations = _network_fetch_violations()

    assert not violations, (
        "subschema must not fetch network resources by default:\n"
        + "\n".join(violations)
    )


def test_network_boundary_allows_uri_parsing_but_rejects_fetching_imports():
    assert not _is_forbidden_network_import("urllib.parse")
    assert _is_forbidden_network_import("urllib.request")
    assert _is_forbidden_network_import("socket")
    assert _is_forbidden_network_import("requests.sessions")


def test_source_imports_are_strictly_one_directional():
    edges_by_pair: dict[tuple[str, str], list[ImportEdge]] = {}
    for edge in _source_file_import_edges():
        edges_by_pair.setdefault((edge.source, edge.target), []).append(edge)

    violations: list[str] = []
    for source, target in sorted(edges_by_pair):
        if source > target:
            continue
        reverse_edges = edges_by_pair.get((target, source))
        if reverse_edges is None:
            continue
        forward = ", ".join(edge.format() for edge in edges_by_pair[(source, target)])
        reverse = ", ".join(edge.format() for edge in reverse_edges)
        violations.append(f"{source} <-> {target}: {forward}; {reverse}")

    assert not violations, "source imports must be one-directional:\n" + "\n".join(
        violations
    )


def test_source_modules_do_not_import_private_names_from_other_modules():
    violations: list[str] = []

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = "." * node.level + (node.module or "")
            violations.extend(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                f"from {module} import {alias.name}"
                for alias in node.names
                if _is_private_imported_name(alias.name)
            )

    assert not violations, (
        "source modules must not import underscore-prefixed names from other "
        "modules; shared internal entrypoints should be named explicitly:\n"
        + "\n".join(violations)
    )


def test_tests_do_not_access_private_public_api_names():
    violations: list[str] = []

    for path in sorted(TEST_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text())
        subschema_aliases = _subschema_module_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module is None or not node.module.startswith("subschema."):
                    continue
                violations.extend(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    f"from {node.module} import {alias.name}"
                    for alias in node.names
                    if _is_private_imported_name(alias.name)
                )
            elif isinstance(node, ast.Attribute) and _is_private_imported_name(
                node.attr
            ):
                owner = _subschema_attribute_owner(node.value, subschema_aliases)
                if owner in {"subschema", "subschema.api"}:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                        f"{owner}.{node.attr}"
                    )

    assert not violations, (
        "tests should use public package APIs or test.proof_oracle, not "
        "subschema.api underscore-prefixed internals:\n" + "\n".join(violations)
    )


def test_source_import_graph_is_acyclic():
    edges = _source_file_import_edges()
    graph = _source_import_graph(edges)
    cycles = [
        component
        for component in _strongly_connected_components(graph)
        if len(component) > 1
    ]
    violations = [_format_import_cycle(component, edges) for component in cycles]

    assert not violations, "source import graph must be acyclic:\n" + "\n\n".join(
        violations
    )


def test_prover_work_protocols_do_not_depend_on_proof_implementations():
    forbidden_targets = (
        "subschema.prover.sat",
        "subschema.prover.context",
        "subschema.prover.driver",
        "subschema.prover.engine",
        "subschema.prover.rules.",
        "subschema.compiler.domains.",
    )
    violations = [
        edge.format()
        for edge in _source_file_import_edges()
        if edge.source == "subschema.work_protocols"
        and (
            edge.target in forbidden_targets
            or any(
                edge.target.startswith(target)
                for target in forbidden_targets
                if target.endswith(".")
            )
        )
    ]

    assert not violations, (
        "shared work protocols must not depend on proof implementations:\n"
        + "\n".join(violations)
    )


def test_prover_proof_protocols_do_not_depend_on_concrete_proof_engines():
    forbidden_targets = (
        "subschema.compiler.",
        "subschema.prover.context",
        "subschema.prover.difference",
        "subschema.prover.difference_arrays",
        "subschema.prover.difference_objects",
        "subschema.prover.driver",
        "subschema.prover.rules.",
        "subschema.prover.sat",
    )
    violations = [
        edge.format()
        for edge in _source_file_import_edges()
        if edge.source == "subschema.prover.protocols"
        and (
            edge.target in forbidden_targets
            or any(
                edge.target.startswith(target)
                for target in forbidden_targets
                if target.endswith(".")
            )
        )
    ]

    assert not violations, (
        "prover prover protocols must stay above IR but below proof engines:\n"
        + "\n".join(violations)
    )


def test_constraints_do_not_import_domain_implementations():
    violations = [
        edge.format()
        for edge in _source_file_import_edges()
        if edge.source == "subschema.ir.constraints"
        and edge.target.startswith("subschema.compiler.domains.")
    ]

    assert not violations, (
        "IR constraints must not depend on concrete domain implementations:\n"
        + "\n".join(violations)
    )


def test_sat_uses_compiled_type_facts_for_array_diagnostics():
    source = (PROVER_ROOT / "sat.py").read_text()

    assert "type_overapproximation_for_schema" not in source
    assert "domains.types" not in source
    assert "_lhs_is_exact_array_schema" in source
    assert "constraint.atoms == frozenset({" in source


def test_sat_trivial_difference_uses_compiled_ir_facts():
    source = _function_source(PROVER_ROOT / "sat.py", "_prove_trivial_difference")

    assert "problem.lhs_schema" not in source
    assert "problem.rhs_schema" not in source
    assert "schema_is_empty_exact" not in source
    assert "schema_is_false" not in source
    assert "schema_is_true" not in source
    assert "boolean_value" in source
    assert "ir_is_empty_exact" in source


def test_proof_engine_is_ir_native_and_raw_schema_entry_stays_in_api():
    engine_source = (PROVER_ROOT / "engine.py").read_text()
    source = _function_source(PROVER_ROOT / "engine.py", "is_ir_subschema")
    api_source = _function_source(PACKAGE_ROOT / "api.py", "is_subschema")

    assert "_raw_" not in engine_source
    assert "raw_bounded_proof" not in engine_source
    assert "def is_subschema(" not in engine_source
    assert "def _bounded_ir_proof(" not in engine_source
    assert "context.subproof(" not in source
    assert "prove_ir_subschema_with_context" in source
    assert "def is_subschema(" in api_source


def test_scalar_proof_modules_consume_ir_native_scalar_facts():
    scalar_modules = {
        "subschema.prover.scalars",
        "subschema.prover.rules.scalars",
    }
    forbidden_targets = (
        "subschema.compiler.domains.numbers",
        "subschema.compiler.domains.strings",
        "subschema.compiler.domains.types",
    )
    violations = [
        edge.format()
        for edge in _source_file_import_edges()
        if edge.source in scalar_modules and edge.target in forbidden_targets
    ]

    assert not violations, (
        "scalar proof modules must consume IR-native scalar facts:\n"
        + "\n".join(violations)
    )


def test_array_length_and_uniqueness_facts_are_ir_native():
    constraints_source = (IR_ROOT / "constraints.py").read_text()
    array_source = (PROVER_ROOT / "difference_arrays.py").read_text()

    assert "ArrayLengthShapeProtocol" not in constraints_source
    assert "ArrayUniquenessShapeProtocol" not in constraints_source
    assert "ArrayLengthShapeProtocol" not in array_source
    assert "ArrayUniquenessShapeProtocol" not in array_source
    assert "class ArrayLengthIntervalFact" in constraints_source
    assert "class ArrayLengthConstraint" in constraints_source


def test_object_property_count_fact_is_ir_native():
    constraints_source = (IR_ROOT / "constraints.py").read_text()
    object_source = (PROVER_ROOT / "difference_objects.py").read_text()

    assert "ObjectPropertyCountShapeProtocol" not in constraints_source
    assert "ObjectPropertyCountShapeProtocol" not in object_source
    assert "class ObjectPropertyCountIntervalFact" in constraints_source
    assert "class ObjectPropertyCountConstraint" in constraints_source


def test_object_key_value_and_property_facts_are_ir_native():
    constraints_source = (IR_ROOT / "constraints.py").read_text()
    difference_source = (PROVER_ROOT / "difference_objects.py").read_text()

    assert "ShapeProtocol" not in constraints_source
    assert "class ObjectPropertyNamesConstraint" in constraints_source
    assert "class ObjectPropertyValuesConstraint" in constraints_source
    assert "class ObjectClosedPropertiesConstraint" in constraints_source
    assert "class ObjectKeyValueConstraint" in constraints_source
    assert "ObjectKeyValueShape" not in difference_source
    assert "object_key_value_shape_for_schema" not in difference_source


def test_ir_package_is_pure_typed_ir_data():
    source = "\n".join(
        path.read_text() for path in sorted(IR_ROOT.glob("*.py"))
    )

    forbidden_fragments = (
        "from subschema.compiler",
        "from subschema.compiler.domains",
        "from subschema.compiler.resources",
        "from subschema.prover",
        "from subschema.validator",
        "from subschema.prover.schemas",
        "from subschema.prover.tagged_unions",
        "def from_schema(",
        "schema.get(",
        "ResourceGraph",
        "ResourceSchemaIR",
    )
    violations = [
        fragment for fragment in forbidden_fragments if fragment in source
    ]

    assert not violations, "subschema.ir must stay pure typed IR:\n" + "\n".join(
        violations
    )
    assert "source: SchemaSource" in source
    assert "graph:" not in source
    assert "def graph(" not in source


def test_ir_package_init_is_reexport_only():
    tree = _module_ast(IR_ROOT / "__init__.py")
    implementation_nodes = (
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.FunctionDef,
    )
    violations = [
        f"{type(node).__name__} at line {node.lineno}"
        for node in tree.body
        if isinstance(node, implementation_nodes)
    ]

    assert not violations, (
        "subschema.ir.__init__ must stay a re-export layer:\n"
        + "\n".join(violations)
    )


def test_ir_semantics_keep_grouped_fact_surface():
    ir_module = importlib.import_module("subschema.ir")
    fields = tuple(ir_module.SchemaSemantics.__dataclass_fields__)

    assert fields == (
        "scalar",
        "array",
        "object",
        "applicator",
        "reference",
        "evaluation",
        "vocabulary",
    )


def test_prover_uses_grouped_ir_fact_access():
    flat_fact_names = (
        "array_any_of_item_schemas_constraint",
        "array_cardinality_length_constraint",
        "array_contains_constraint",
        "array_contains_counts",
        "array_contains_fragment_constraint",
        "array_item_model_constraint",
        "array_item_values_fragment_constraint",
        "array_length_lhs_constraint",
        "array_length_rhs_constraint",
        "array_tuple_anyof_distribution_constraint",
        "array_unevaluated_items_true_fragment_supported",
        "array_uniqueness_lhs_constraint",
        "array_uniqueness_rhs_constraint",
        "finite_constraint",
        "has_dynamic_reference",
        "has_recursive_reference",
        "has_static_reference_boundary",
        "numeric_constraint",
        "object_closed_properties_constraint",
        "object_dependent_required_constraint",
        "object_dependent_schema_properties_constraint",
        "object_dependent_schema_required_constraint",
        "object_key_value_constraint",
        "object_presence_product_constraint",
        "object_property_count_bounds_constraint",
        "object_property_count_constraint",
        "object_property_names_constraint",
        "object_property_names_has_value_constraints",
        "object_property_values_constraint",
        "object_unevaluated_properties_true_fragment_supported",
        "string_language_constraint",
        "string_length_constraint",
        "tagged_one_of",
        "type_constraint",
    )
    flat_alias_names = (
        "array_length_lhs_shape",
        "array_length_rhs_shape",
        "array_uniqueness_lhs_shape",
        "array_uniqueness_rhs_shape",
        "numeric_shape",
        "object_closed_properties_shape",
        "object_property_count_shape",
        "object_property_names_shape",
        "object_property_values_shape",
        "string_language_shape",
        "string_length_shape",
        "type_shape",
    )
    prefixes = (
        "applicator",
        "array",
        "object",
        "reference",
        "scalar",
        "semantics",
    )
    negative_prefixes = "".join(f"(?<!{prefix})" for prefix in prefixes)
    pattern = re.compile(
        rf"{negative_prefixes}\.({'|'.join(flat_fact_names + flat_alias_names)})\b"
    )
    violations: list[str] = []

    for path in sorted(PROVER_ROOT.rglob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if pattern.search(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert not violations, (
        "prover code must read grouped IR facts through semantics.scalar/array/"
        "object/applicator/reference:\n" + "\n".join(violations)
    )


def test_ir_document_cache_keys_do_not_use_python_object_ids():
    pattern = re.compile(r"id\([^\n]*(?:\.document|document)[^\n]*\)")
    violations: list[str] = []

    for root in (IR_ROOT, PROVER_ROOT):
        for path in sorted(root.rglob("*.py")):
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                if pattern.search(line):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                    )

    assert not violations, (
        "IR/prover cache keys must use SchemaDocumentIR.cache_identity instead of "
        "Python object ids:\n" + "\n".join(violations)
    )


def test_ir_package_does_not_import_runtime_packages():
    forbidden_prefixes = (
        "subschema.compiler",
        "subschema.prover",
        "subschema.validator",
    )
    violations = [
        edge.format()
        for edge in _source_file_import_edges()
        if edge.source.startswith("subschema.ir")
        and any(edge.target.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "IR modules must stay pure typed semantic data:\n" + "\n".join(violations)
    )


def test_compiler_package_does_not_import_prover_package():
    forbidden_prefixes = ("subschema.prover",)
    violations = [
        edge.format()
        for edge in _source_file_import_edges()
        if edge.source.startswith("subschema.compiler")
        and any(edge.target.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "compiler modules must only compile raw schema into IR:\n"
        + "\n".join(violations)
    )


def test_compiler_package_does_not_import_validator_package():
    forbidden_prefixes = ("subschema.validator",)
    violations = [
        edge.format()
        for edge in _source_file_import_edges()
        if edge.source.startswith("subschema.compiler")
        and any(edge.target.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "compiler modules must not confirm finite candidates with validator:\n"
        + "\n".join(violations)
    )


def test_validator_package_does_not_import_compiler_or_prover_packages():
    forbidden_prefixes = ("subschema.compiler", "subschema.prover")
    violations = [
        edge.format()
        for edge in _source_file_import_edges()
        if edge.source.startswith("subschema.validator")
        and any(edge.target.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "validator modules must validate raw schemas without compiler/prover coupling:\n"
        + "\n".join(violations)
    )


def test_prover_formulas_do_not_compile_raw_schemas():
    source = (PROVER_ROOT / "formulas.py").read_text()

    forbidden_fragments = (
        "from subschema.compiler",
        "from subschema.prover.schemas",
        "SchemaIRCompiler",
        "ResourceGraph",
        "from_schemas(",
        "from_graphs(",
        "source.schema",
    )
    violations = [
        fragment for fragment in forbidden_fragments if fragment in source
    ]

    assert not violations, (
        "prover.formulas must stay a pure formula/IR lowering layer:\n"
        + "\n".join(violations)
    )


def test_prover_core_proof_orchestration_does_not_own_compiler_services():
    core_modules = ("context.py", "driver.py", "sat.py")
    violations = [
        f"{module}: {fragment}"
        for module in core_modules
        for fragment in ("from subschema.compiler", "import subschema.compiler")
        if fragment in (PROVER_ROOT / module).read_text()
    ]

    assert not violations, (
        "prover context/driver/SAT must not own raw compiler services:\n"
        + "\n".join(violations)
    )


def test_prover_package_does_not_import_compiler_package():
    violations = [
        edge.format()
        for edge in _source_file_import_edges()
        if edge.source.startswith("subschema.prover.")
        and edge.target.startswith("subschema.compiler.")
    ]

    assert not violations, (
        "prover modules must consume typed IR, not compiler services:\n"
        + "\n".join(violations)
    )


def test_prover_disjointness_consumes_compiled_ir_services():
    source = (PROVER_ROOT / "disjointness.py").read_text()

    forbidden_fragments = (
        "from subschema.compiler",
        "SchemaIRCompiler",
    )
    violations = [
        fragment for fragment in forbidden_fragments if fragment in source
    ]

    assert not violations, (
        "prover.disjointness must not own raw schema compilation:\n"
        + "\n".join(violations)
    )
    assert "def ir_is_empty_exact(" in source
    assert "def irs_are_disjoint(" in source
    assert "def terms_are_disjoint(" in source


def test_projection_uses_ir_and_term_proof_services():
    source = (PROVER_ROOT / "projection.py").read_text()

    assert "source.schema" not in source
    assert "context.compile_schema(" not in source
    assert "schemas_are_disjoint" not in source
    assert "schema_is_false" not in source
    assert "schema_is_true" not in source
    assert "schemas_equal" not in source
    assert "context.subproof(" not in source
    assert '{"not": rhs}' not in source
    assert "irs_are_disjoint" in source
    assert "subproof_terms(" in source
    assert "SchemaTerm.not_" in source


def test_public_projection_emitter_owns_schema_materialization():
    source = (PACKAGE_ROOT / "projection.py").read_text()

    assert "source.schema" in source
    assert "ProjectionDecision" in source


def test_sat_scheduler_uses_typed_disposition_not_reason_strings():
    scheduler_functions = (
        "_preferred_unsupported_result",
        "_proof_after_rule_class_guard",
        "_should_stop_after_rule_unsupported",
        "_rule_unsupported_disposition",
    )
    source = "\n".join(
        _function_source(PROVER_ROOT / "sat.py", name) for name in scheduler_functions
    )

    assert "proof.reason" not in source
    assert ".reason ==" not in source
    assert ".reason in" not in source
    assert ".spec.domain" in source
    assert ".name.startswith" not in source


def test_witness_builder_uses_term_children():
    source = (PROVER_ROOT / "witnesses.py").read_text()

    assert "context.compile_schema(" not in source
    assert "schema_at_index(" not in source
    assert "property_schema_for(" not in source
    assert "value_schema_for(" not in source
    assert "_child_witness(" in source
    assert "_term_witness(" in source


def test_reference_rules_use_compiled_ir_facts():
    source = (PROVER_ROOT / "sat.py").read_text()

    forbidden_fragments = (
        "root_dynamic_reference_resolution",
        "root_static_reference_resolution",
        "DynamicReferenceUnsupported",
        "StaticReferenceUnsupported",
    )
    violations = [
        fragment for fragment in forbidden_fragments if fragment in source
    ]

    assert not violations, (
        "reference SAT proofs must consume compiled IR reference facts:\n"
        + "\n".join(violations)
    )


def test_applicator_rules_use_compiled_reference_facts():
    source = (PROVER_ROOT / "rules" / "applicators.py").read_text()

    forbidden_fragments = (
        "from subschema.compiler.resources",
        "resource_graph_for_source",
        "static_reference_resolution_for_schema",
        "ReferenceResolution",
        "StaticReferenceUnsupported",
    )
    violations = [
        fragment for fragment in forbidden_fragments if fragment in source
    ]

    assert not violations, (
        "applicator rules must consume compiled IR reference facts:\n"
        + "\n".join(violations)
    )


def test_evaluation_traces_use_compiled_ir_facts():
    source = (PROVER_ROOT / "evaluation_traces.py").read_text()

    forbidden_fragments = (
        "from subschema.compiler",
        "resource_graph_for_source",
        "evaluation_frontier_for_schema",
        "static_reference_resolution_for_schema",
        "dynamic_reference_resolution_for_schema",
        "source.schema",
        "lhs_schema",
        "context.subproof(",
    )
    violations = [
        fragment for fragment in forbidden_fragments if fragment in source
    ]

    assert not violations, (
        "evaluation traces must consume compiled IR facts and terms:\n"
        + "\n".join(violations)
    )


def test_symbolic_solver_owns_object_presence_products():
    runtime_sources = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text()
        for path in sorted(PROVER_ROOT.rglob("*.py"))
    }

    forbidden_presence_products = (
        "_object_presence_property_sets",
        "presence_property_sets(",
        "multi_fresh_presence_property_sets(",
        "1 << len(names)",
        "for mask in range(1 << len(names))",
    )
    violations = [
        f"{path}: {pattern}"
        for path, source in runtime_sources.items()
        for pattern in forbidden_presence_products
        if pattern in source
    ]
    assert not violations, (
        "object presence products must be routed through SymbolicSolver:\n"
        + "\n".join(violations)
    )


def test_validation_backend_owns_runtime_validator_compilation():
    runtime_sources = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text()
        for path in sorted(PROVER_ROOT.rglob("*.py"))
    }

    forbidden_runtime_calls = (
        "instance_validator_" + "for(",
        "normalize_for_validation(",
        "validator_" + "for(",
        "VALID" + "ATORS",
    )
    violations = [
        f"{path}: {pattern}"
        for path, source in runtime_sources.items()
        if path != "src/subschema/validator/core.py"
        for pattern in forbidden_runtime_calls
        if pattern in source
    ]
    assert not violations, (
        "runtime validation must be routed through ValidationBackend:\n"
        + "\n".join(violations)
    )


def test_strict_json_helpers_own_runtime_json_serialization():
    violations = _json_call_violations()
    assert not violations, (
        "prover JSON serialization must use strict json_data helpers:\n"
        + "\n".join(violations)
    )


def test_reference_schema_position_keywords_derive_from_normalization():
    normalization = importlib.import_module("subschema.compiler.normalization")
    references = importlib.import_module("subschema.compiler.resources")

    assert references.SCHEMA_ARRAY_KEYWORDS == normalization.SCHEMA_ARRAY_KEYWORDS
    assert references.SCHEMA_VALUE_KEYWORDS == normalization.SCHEMA_VALUE_KEYWORDS
    assert references.SCHEMA_MAP_KEYWORDS == normalization.SCHEMA_MAP_KEYWORDS - {
        "dependencies"
    }


def test_runtime_witness_construction_is_constructive():
    runtime_sources = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text()
        for path in sorted(PROVER_ROOT.rglob("*.py"))
    }

    witness_source = runtime_sources["src/subschema/prover/witnesses.py"]
    forbidden_probe_patterns = (
        ".is_valid(",
        "validates_difference(",
    )
    probe_violations = [
        pattern for pattern in forbidden_probe_patterns if pattern in witness_source
    ]
    assert not probe_violations, (
        "WitnessBuilder must not validator-probe constructed values"
    )


def test_confirmation_and_array_boundaries_are_domain_owned():
    runtime_sources = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text()
        for path in sorted(PROVER_ROOT.rglob("*.py"))
    }
    forbidden_patterns = (
        "_is_validation_backend_exception",
        "_FiniteConfirmationContext",
        "_rhs_unique_items_fragment_is_complete",
        "_schema_requires_unique_items",
    )
    violations = [
        f"{path}: {pattern}"
        for path, source in runtime_sources.items()
        for pattern in forbidden_patterns
        if pattern in source
    ]

    assert not violations, (
        "proof confirmation and array uniqueness boundaries must stay owned by "
        "their domain modules:\n"
        + "\n".join(violations)
    )


def test_rhs_anyof_array_item_certificate_uses_compiled_ir_fact():
    source = _function_source(
        PROVER_ROOT / "rules" / "applicators.py",
        "_certified_array_item_against_rhs_anyof",
    )

    assert "array_any_of_item_schemas" in source
    assert 'rhs_schema.get("anyOf")' not in source
    assert "rhs_schema.get('anyOf')" not in source


def test_lhs_tuple_anyof_distribution_uses_compiled_ir_fact():
    source = _function_source(
        PROVER_ROOT / "rules" / "applicators.py",
        "_prove_lhs_tuple_anyof_distribution",
    )

    assert "array_tuple_anyof_distribution_constraint" in source
    assert "branch_terms" in source
    assert 'schema.get("items")' not in source
    assert "schema.get('items')" not in source


def test_applicator_disjointness_uses_terms_not_raw_schema():
    source = "\n".join(
        _function_source(PROVER_ROOT / "rules" / "applicators.py", name)
        for name in (
            "_prove_rhs_one_of_disjointness_product",
            "_plan_rhs_not_difference",
        )
    )

    assert "terms_are_disjoint" in source
    assert "schemas_are_disjoint" not in source


def test_one_of_overlap_product_is_term_backed():
    applicators_source = (PROVER_ROOT / "applicators.py").read_text()
    overlap_builder = _function_source(
        PROVER_ROOT / "applicators.py", "one_of_overlap_product"
    )
    overlap_witness = _function_source(
        PROVER_ROOT / "applicators.py", "one_of_overlap_witness_plan"
    )

    assert "class ApplicatorOneOfOverlapProduct:\n    lhs_schema" not in (
        applicators_source
    )
    assert "lhs_schema" not in overlap_builder
    assert "context.compile_schema(" not in overlap_witness
    assert "build_term_witness" in overlap_witness


def test_object_property_count_sat_helpers_use_compiled_ir_facts():
    helper_names = (
        "_rhs_rejects_empty_object",
        "_rhs_has_property_count_constraint",
        "_rhs_property_count_is_directly_satisfied",
    )
    source = "\n".join(
        _function_source(PROVER_ROOT / "rules" / "objects.py", name)
        for name in helper_names
    )

    assert "object_property_count_bounds_constraint" in source
    assert ".get(" not in source
    assert "problem.rhs_schema" not in source
    assert "problem.lhs_schema" not in source


def test_dependent_schema_property_value_witness_uses_compiled_ir_fact():
    source = _function_source(
        PROVER_ROOT / "rules" / "objects.py",
        "_rhs_dependent_schema_property_value_witness",
    )

    assert "object_dependent_schema_properties_constraint" in source
    assert ".get(" not in source
    assert "problem.rhs_schema" not in source


def test_difference_models_are_owned_by_domain_modules():
    difference_tree = _module_ast(PROVER_ROOT / "difference.py")
    array_tree = _module_ast(PROVER_ROOT / "difference_arrays.py")
    object_tree = _module_ast(PROVER_ROOT / "difference_objects.py")

    difference_classes = _class_definitions(difference_tree)
    assert "ArrayDifferenceModel" not in difference_classes
    assert "ObjectDifferenceModel" not in difference_classes
    assert "ArrayDifferenceModel" in _class_definitions(array_tree)
    assert "ObjectDifferenceModel" in _class_definitions(object_tree)


def test_sat_rule_bodies_are_owned_by_rule_modules():
    sat_functions = _function_definitions(_module_ast(PROVER_ROOT / "sat.py"))
    rule_owners = {
        PROVER_ROOT / "rules" / "applicators.py": (
            "prove_right_not_applicator_difference",
            "_prove_lhs_tuple_anyof_distribution",
        ),
        PROVER_ROOT / "rules" / "arrays.py": (
            "prove_array_length_difference",
            "prove_array_contains_difference",
        ),
        PROVER_ROOT / "rules" / "objects.py": (
            "prove_object_key_value_difference",
            "prove_closed_object_properties_difference",
        ),
        PROVER_ROOT / "rules" / "scalars.py": (
            "prove_numeric_difference",
            "prove_typed_scalar_difference",
        ),
    }

    for expected_functions in rule_owners.values():
        for name in expected_functions:
            assert name not in sat_functions

    for path, expected_functions in rule_owners.items():
        owner_functions = _function_definitions(_module_ast(path))
        for name in expected_functions:
            assert name in owner_functions


def test_array_contains_difference_model_uses_compiled_ir_fact():
    source = (PROVER_ROOT / "difference_arrays.py").read_text()

    assert "def _array_contains(" not in source
    assert "return self.lhs.semantics.array.array_contains_constraint" in source
    assert "return self.rhs.semantics.array.array_contains_constraint" in source
    assert "array_contains_fragment_constraint" in source


def test_array_item_values_difference_model_uses_compiled_fragment_fact():
    source = (PROVER_ROOT / "difference_arrays.py").read_text()

    assert "def _is_array_item_values_fragment_schema(" not in source
    assert "array_item_values_fragment_constraint" in source


def test_array_unevaluated_items_difference_model_uses_compiled_fragment_fact():
    source = (PROVER_ROOT / "difference_arrays.py").read_text()

    assert "def _rhs_all_of_unevaluated_items_true_fragment_supported(" not in source
    assert "array_unevaluated_items_true_fragment_supported" in source


def test_array_cardinality_emptiness_uses_compiled_array_facts():
    source = (PROVER_ROOT / "disjointness.py").read_text()

    assert "def _local_array_cardinality_length_shape(" not in source
    assert "def _reachable_array_item_schemas(" not in source
    assert "def _array_contains_counts(" not in source
    assert "def _schemas_covering_all_array_items(" not in source
    assert 'schema.get("uniqueItems")' not in source
    assert "array_cardinality_length_shape_for_schema" not in source
    assert "array_reachable_item_schemas_for_shape" not in source
    assert "array_contains_counts_for_schema" not in source
    assert "array_item_schemas_covering_all_items" not in source
    assert "array_requires_unique_items_for_schema" not in source
    assert "array_cardinality_length_constraint" in source
    assert "array_item_model_constraint" in source


def test_object_required_property_disjointness_uses_compiled_object_facts():
    source = (PROVER_ROOT / "disjointness.py").read_text()

    assert "def _required_names(" not in source
    assert "def _property_schemas(" not in source
    assert "object_required_names_for_schema" not in source
    assert "object_property_schemas_for_schema" not in source
    assert "object_key_value_constraint" in source


def test_object_dependency_presence_facts_use_compiled_object_facts():
    source = (PROVER_ROOT / "difference_objects.py").read_text()
    domain_source = (PACKAGE_ROOT / "compiler" / "domains" / "objects.py").read_text()

    assert "def _object_dependent_required_entries(" not in source
    assert "def _object_required_names_from_presence_schema(" not in source
    assert "def _object_dependency_closed_present_names(" not in source
    assert "object_dependent_required_entries_for_schema" not in source
    assert "object_dependent_schema_required_entries_for_schema" not in source
    assert "object_dependent_schema_required_constraint" in source
    assert "dependency_closed_present_names" in source
    assert "object_required_names_in_presence_schema" in domain_source


def test_object_key_value_difference_consumes_ir_native_facts():
    source = (PROVER_ROOT / "difference_objects.py").read_text()

    assert "def object_key_value_shape_for_schema(" not in source
    assert "def _is_object_key_value_fragment_schema(" not in source
    assert "def _object_key_value_value_schema_is_solver_local(" not in source
    assert "def _object_key_value_partition_patterns(" not in source
    assert "ObjectKeyValueConstraint" in source
    assert "object_key_value_shape_for_schema" not in source
    assert "object_key_value_mixed_product_supported" in source
    assert "object_key_value_obligations_budget_exhausted" in source
    assert "object_key_value_partition_patterns" in source


def test_object_property_names_difference_uses_compiled_object_facts():
    source = (PROVER_ROOT / "difference_objects.py").read_text()

    assert "def _object_property_names_has_value_constraints(" not in source
    assert "object_property_names_schema_has_value_constraints" not in source
    assert "object_property_names_has_value_constraints" in source


def test_object_presence_product_guards_use_compiled_object_facts():
    source = (PROVER_ROOT / "difference_objects.py").read_text()

    assert "def _object_schema_has_property_count_constraint(" not in source
    assert "def _object_presence_product_has_upper_count_constraint(" not in source
    assert "def _object_presence_product_has_one_of(" not in source
    assert "def _object_presence_schema_has_unmodeled_value_constraints(" not in source
    assert "def _object_presence_lhs_has_negative_value_constraints(" not in source
    assert "object_schema_has_property_count_constraint" not in source
    assert "object_presence_product_has_upper_count_constraint" not in source
    assert "object_presence_product_has_one_of" not in source
    assert "object_presence_schema_has_unmodeled_value_constraints" not in source
    assert "object_presence_lhs_has_negative_value_constraints" not in source
    assert "has_upper_count_constraint" in source
    assert "has_one_of" in source
    assert "has_unmodeled_value_constraints" in source
    assert "lhs_has_negative_value_constraints" in source


def test_object_presence_product_uses_compiled_object_facts():
    source = (PROVER_ROOT / "difference_objects.py").read_text()

    assert "OBJECT_PRESENCE_PRODUCT_KEYWORDS" not in source
    assert "def _collect_object_presence_product_names(" not in source
    assert "def _object_presence_product_accepts(" not in source
    assert "def _object_presence_product_symbolic_expr(" not in source
    assert "def _local_object_presence_product_symbolic_expr(" not in source
    assert "def _local_object_presence_product_accepts(" not in source
    assert "def _is_object_presence_product_schema(" not in source
    assert "def _object_schema_max_properties_bound(" not in source
    assert "def _object_schema_min_properties_lower_bound(" not in source
    assert "object_presence_product_names_for_schemas" not in source
    assert "object_presence_product_accepts" not in source
    assert "object_presence_product_symbolic_expr" not in source
    assert "object_presence_product_constraint" in source
    assert ".accepts(" in source
    assert ".symbolic_expr(" in source
    assert "object_max_properties_bound_for_schema" not in source
    assert "object_min_properties_lower_bound_for_schema" not in source
    assert "_object_property_count_upper_bound" in source
    assert "_object_property_count_lower_bound" in source


def test_object_key_classes_use_compiled_required_names():
    source = _function_source(
        PROVER_ROOT / "difference_objects.py", "_object_key_classes"
    )

    assert 'schema.get("required")' not in source
    assert "object_required_names_for_schema" not in source
    assert "object_key_value_constraint.required" in source


def test_applicator_projection_uses_compiled_base_facts():
    source = (PROVER_ROOT / "applicators.py").read_text()

    assert "def _schema_without_keyword(" not in source
    assert "def _schema_without_keywords(" not in source
    assert "schema_without_keyword" not in source
    assert "schema_without_keywords" not in source
    assert "base_semantic_keywords" in source


def test_union_disjointness_uses_compiled_applicator_terms():
    source = (PROVER_ROOT / "disjointness.py").read_text()

    assert "schema_array_keyword_value" not in source
    assert "schema_without_keyword" not in source
    assert "schema_semantic_key_set" not in source
    assert "_union_applicator_branch_terms" in source
    assert "SchemaTerm.node" in source


def test_evaluation_layers_are_ir_and_term_based():
    source = "\n".join(
        (
            (IR_ROOT / "evaluation.py").read_text(),
            (PROVER_ROOT / "evaluation_traces.py").read_text(),
        )
    )

    assert "schema.get(" not in source
    assert "source.schema.get(" not in source
    assert 'schema["' not in source
    assert 'source.schema["' not in source
    assert "from subschema.compiler" not in source
    assert "SchemaTerm.node" in source
    assert "subproof_terms" in source


def test_finite_compiler_adapter_uses_schema_boundary_and_domain_helpers():
    source = (PACKAGE_ROOT / "compiler" / "finite_values.py").read_text()

    assert 'schema["allOf"]' not in source
    assert 'schema["anyOf"]' not in source
    assert 'schema["oneOf"]' not in source
    assert 'schema["not"]' not in source
    assert "schema_array_keyword_value" in source
    assert "pure_not_target" in source
    assert "object_finite_value_shape_for_schema" in source
    assert "object_pattern_property_schemas_for_schema" in source
    assert "object_property_names_schema_for_schema" in source
    assert "array_finite_fragment_shape_for_schema" in source
    assert "finite_values_for_type_schema" in source
    assert "string_schema_has_finite_language_for_values" in source
    assert "from subschema.validator" not in source
    assert "validate_source_instance" not in source
    assert "def resolve_schema_reference(" not in source
    assert "resolve_schema_reference" in source


def test_finite_service_consumes_compiled_ir_facts_only():
    source = (PROVER_ROOT / "finite.py").read_text()

    assert 'schema["allOf"]' not in source
    assert 'schema["anyOf"]' not in source
    assert 'schema["oneOf"]' not in source
    assert 'schema["not"]' not in source
    assert "schema.get(" not in source
    assert 'schema.get("type")' not in source
    assert "from subschema.compiler.domains" not in source
    assert "finite_values_for_schema" not in source
    assert "LogicalSchemaIR" in source
    assert "finite_constraint" in source


def test_witness_service_consumes_compiled_ir_facts_only():
    source = (PROVER_ROOT / "witnesses.py").read_text()

    assert 'schema["allOf"]' not in source
    assert 'schema["anyOf"]' not in source
    assert 'schema["oneOf"]' not in source
    assert 'schema["not"]' not in source
    assert "schema.get(" not in source
    assert "from subschema.compiler.domains" not in source
    assert "LogicalSchemaIR" in source
    assert "finite_values_for_ir" in source
    assert "object_property_values_constraint" in source
    assert "array_item_model_constraint" in source


def test_array_witness_builder_uses_array_ir_facts():
    source = _function_source(PROVER_ROOT / "witnesses.py", "_array_witness")
    implementation_source = _function_source(
        PROVER_ROOT / "witnesses.py", "_array_witness_from_irs"
    )

    assert "_array_item_schema_for_witness" not in source
    assert 'schema.get("minItems")' not in source
    assert 'schema.get("maxItems")' not in source
    assert 'schema.get("prefixItems")' not in source
    assert 'schema.get("uniqueItems")' not in source
    assert "_first_constrained_item_model" in implementation_source
    assert "_all_of_child_irs" in source


def test_object_unevaluated_properties_difference_model_uses_compiled_fragment_fact():
    source = (PROVER_ROOT / "difference_objects.py").read_text()

    assert (
        "def _rhs_all_of_unevaluated_properties_true_fragment_supported("
        not in source
    )
    assert "object_unevaluated_properties_true_fragment_supported" in source


def test_typed_scalar_rules_use_compiled_assertion_presence_facts():
    source = "\n".join(
        _function_source(PROVER_ROOT / "rules" / "scalars.py", name)
        for name in (
            "prove_numeric_difference",
            "prove_typed_scalar_difference",
            "_typed_scalar_rhs_atom_is_modeled",
            "_numeric_constraint_for_typed_scalar",
        )
    )

    assert "has_non_numeric_assertions" in source
    assert "has_object_or_array_assertions" in source
    assert "has_numeric_assertions" in source
    assert "covers_type_atom" in source
    assert "schema_covers_type_atom" not in source
    assert "_schema_has_" not in source
    assert ".items()" not in source


def test_sat_static_reference_guards_use_compiled_ir_facts():
    source = "\n".join(
        _function_source(PROVER_ROOT / "rules" / "common.py", name)
        for name in (
            "array_static_reference_unsupported",
            "object_static_reference_unsupported",
            "lhs_static_reference_unsupported",
            "contains_static_reference",
        )
    )

    assert "has_static_reference_boundary" in source
    assert "contains_reference_keyword" not in source
    assert "problem.lhs_schema" not in source
    assert "problem.rhs_schema" not in source


def _runtime_import_edges() -> list[ImportEdge]:
    return [edge for edge in _kernel_import_edges() if edge.scope != "type-checking"]


def _type_checking_import_edges() -> list[ImportEdge]:
    return [edge for edge in _kernel_import_edges() if edge.scope == "type-checking"]


def _kernel_import_edges() -> list[ImportEdge]:
    edges: list[ImportEdge] = []
    for path in sorted(PROVER_ROOT.rglob("*.py")):
        source = _module_name(path)
        tree = ast.parse(path.read_text(), filename=str(path))
        _attach_parents(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                scope = _import_scope(node)
                edges.extend(
                    ImportEdge(source, alias.name, node.lineno, scope)
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                edges.extend(_import_from_edges(source, node))

    return edges


def _source_file_import_edges() -> list[ImportEdge]:
    module_names = {_module_name(path) for path in PACKAGE_ROOT.rglob("*.py")}
    edges: list[ImportEdge] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source = _module_name(path)
        tree = ast.parse(path.read_text(), filename=str(path))
        _attach_parents(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                scope = _import_scope(node)
                for alias in node.names:
                    target = _source_module_for_import(alias.name, module_names)
                    if target is not None and target != source:
                        edges.append(ImportEdge(source, target, node.lineno, scope))
            elif isinstance(node, ast.ImportFrom):
                edges.extend(_source_import_from_edges(source, node, module_names))

    return edges


def _source_import_graph(edges: list[ImportEdge]) -> dict[str, set[str]]:
    graph = {
        _module_name(path): set[str]()
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
    }
    for edge in edges:
        graph.setdefault(edge.source, set()).add(edge.target)
        graph.setdefault(edge.target, set())
    return graph


def _strongly_connected_components(
    graph: dict[str, set[str]]
) -> list[tuple[str, ...]]:
    index = 0
    index_by_node: dict[str, int] = {}
    lowlink_by_node: dict[str, int] = {}
    stack: list[str] = []
    stack_members: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        index_by_node[node] = index
        lowlink_by_node[node] = index
        index += 1
        stack.append(node)
        stack_members.add(node)

        for target in sorted(graph[node]):
            if target not in index_by_node:
                visit(target)
                lowlink_by_node[node] = min(
                    lowlink_by_node[node], lowlink_by_node[target]
                )
            elif target in stack_members:
                lowlink_by_node[node] = min(
                    lowlink_by_node[node], index_by_node[target]
                )

        if lowlink_by_node[node] != index_by_node[node]:
            return

        component: list[str] = []
        while True:
            member = stack.pop()
            stack_members.remove(member)
            component.append(member)
            if member == node:
                break
        components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in index_by_node:
            visit(node)
    return components


def _format_import_cycle(component: tuple[str, ...], edges: list[ImportEdge]) -> str:
    members = set(component)
    component_edges = [
        edge
        for edge in edges
        if edge.source in members and edge.target in members
    ]
    formatted_edges = "\n".join(
        f"  - {edge.format()}" for edge in sorted(
            component_edges, key=lambda edge: (edge.source, edge.target, edge.line)
        )
    )
    return f"cycle component: {' -> '.join(component)}\n{formatted_edges}"


def _source_import_from_edges(
    source: str, node: ast.ImportFrom, module_names: set[str]
) -> list[ImportEdge]:
    target_base = _resolve_import_from_module(source, node)
    if target_base is None:
        return []

    scope = _import_scope(node)
    edges: list[ImportEdge] = []
    for alias in node.names:
        if alias.name == "*":
            continue
        target = _source_module_for_import(f"{target_base}.{alias.name}", module_names)
        if target is None:
            target = _source_module_for_import(target_base, module_names)
        if target is not None and target != source:
            edges.append(ImportEdge(source, target, node.lineno, scope))
    return edges


def _source_module_for_import(
    imported: str, module_names: set[str]
) -> str | None:
    if not imported.startswith("subschema"):
        return None
    candidate = imported
    while candidate:
        if candidate in module_names:
            return candidate
        candidate = ".".join(candidate.split(".")[:-1])
    return None


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _function_source(path: Path, name: str) -> str:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{name} not found in {path}")


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _class_definitions(tree: ast.AST) -> set[str]:
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def _function_definitions(tree: ast.AST) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _attach_parents(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent


def _import_scope(node: ast.AST) -> str:
    if _is_under_type_checking(node):
        return "type-checking"
    if _is_under_local_scope(node):
        return "local"
    return "module"


def _is_under_type_checking(node: ast.AST) -> bool:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if isinstance(parent, ast.If) and _is_type_checking_test(parent.test):
            return True
        parent = getattr(parent, "parent", None)
    return False


def _is_type_checking_test(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    return isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"


def _is_under_local_scope(node: ast.AST) -> bool:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return True
        parent = getattr(parent, "parent", None)
    return False


def _import_from_edges(source: str, node: ast.ImportFrom) -> list[ImportEdge]:
    target_base = _resolve_import_from_module(source, node)
    if target_base is None:
        return []

    scope = _import_scope(node)
    if target_base == "subschema":
        return [
            ImportEdge(source, f"subschema.{alias.name}", node.lineno, scope)
            for alias in node.names
            if alias.name != "*"
        ]
    return [ImportEdge(source, target_base, node.lineno, scope)]


def _resolve_import_from_module(source: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module

    source_parts = source.split(".")
    if source_parts[-1] != "__init__":
        source_parts = source_parts[:-1]
    if node.level > len(source_parts):
        return None

    base_parts = source_parts[: len(source_parts) - node.level + 1]
    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(base_parts)


def _forbidden_runtime_edge_reason(edge: ImportEdge) -> str | None:
    if (
        edge.source == "subschema.prover.context"
        and edge.target == "subschema.prover.engine"
    ):
        return "proof context must call the proof driver, not the public engine entrypoint"

    if _source_is_domain_math(edge.source) and edge.target == "subschema.prover.engine":
        return "domain math and difference/evaluation helpers must not construct or import ProofEngine"

    if (
        edge.source.startswith(PROVER_PREFIX)
        and edge.source != "subschema.symbolic"
        and edge.target == "z3"
    ):
        return "prover modules must use subschema.symbolic instead of importing z3 directly"

    return None


def _forbidden_type_checking_edge_reason(edge: ImportEdge) -> str | None:
    if edge.source == "subschema.prover.context" and edge.target.startswith(
        "subschema.ir.evaluation"
    ):
        return "proof context must not name evaluation-specific cache value types"
    return None


def _is_private_imported_name(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _subschema_module_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("subschema"):
                    continue
                local_name = alias.asname or alias.name.split(".", 1)[0]
                aliases[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or not node.module.startswith("subschema"):
                continue
            for alias in node.names:
                if _is_private_imported_name(alias.name):
                    continue
                local_name = alias.asname or alias.name
                aliases[local_name] = f"{node.module}.{alias.name}"
    return aliases


def _subschema_attribute_owner(
    value: ast.expr, aliases: dict[str, str]
) -> str | None:
    if isinstance(value, ast.Name):
        return aliases.get(value.id)
    if isinstance(value, ast.Attribute):
        owner = _subschema_attribute_owner(value.value, aliases)
        if owner is not None:
            return f"{owner}.{value.attr}"
    return None


def _source_is_domain_math(source: str) -> bool:
    return source.startswith("subschema.compiler.domains.") or source in {
        "subschema.prover.difference",
        "subschema.ir.evaluation",
    }


def _json_call_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(PROVER_ROOT.rglob("*.py")):
        source = _module_name(path)
        if source == BACKEND_OWNERS["json"]:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        violations.extend(
            f"{source}: json.{node.func.attr} call at line {node.lineno}"
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "json"
                and node.func.attr in {"dump", "dumps", "load", "loads"}
            )
        )
    return violations


def _network_fetch_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend(
                    f"{relative_path}:{node.lineno}: import {alias.name}"
                    for alias in node.names
                    if _is_forbidden_network_import(alias.name)
                )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_forbidden_network_import(module):
                    violations.append(
                        f"{relative_path}:{node.lineno}: from {module} import ..."
                    )
            elif isinstance(node, ast.Call):
                call_name = _call_name(node.func)
                if call_name in NETWORK_CALL_NAMES:
                    violations.append(
                        f"{relative_path}:{node.lineno}: call {call_name}"
                    )
    return violations


def _is_forbidden_network_import(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in NETWORK_IMPORT_PREFIXES
    )


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
