import ast
import importlib
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = REPO_ROOT / "src" / "subschema"
KERNEL_ROOT = PACKAGE_ROOT / "kernel"
KERNEL_PREFIX = "subschema.kernel"


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    line: int
    scope: str

    def format(self) -> str:
        return f"{self.source} -> {self.target} ({self.scope}, line {self.line})"


def test_kernel_runtime_imports_respect_layer_boundaries():
    violations: list[str] = []
    for edge in _runtime_import_edges():
        reason = _forbidden_runtime_edge_reason(edge)
        if reason is not None:
            violations.append(f"{edge.format()}: {reason}")

    assert not violations, "forbidden kernel import edges:\n" + "\n".join(violations)


def test_kernel_type_checking_imports_do_not_leak_domain_types_into_context():
    violations: list[str] = []
    for edge in _type_checking_import_edges():
        reason = _forbidden_type_checking_edge_reason(edge)
        if reason is not None:
            violations.append(f"{edge.format()}: {reason}")

    assert not violations, "forbidden type-checking import edges:\n" + "\n".join(
        violations
    )


def test_symbolic_solver_owns_z3_and_object_presence_products():
    runtime_sources = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text()
        for path in sorted(KERNEL_ROOT.rglob("*.py"))
    }

    z3_importers = [
        path
        for path, source in runtime_sources.items()
        if "import z3" in source or "from z3" in source
    ]
    assert z3_importers == ["src/subschema/kernel/symbolic.py"]

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
        for path in sorted(KERNEL_ROOT.rglob("*.py"))
    }

    jsonschema_importers = [
        path
        for path, source in runtime_sources.items()
        if path != "src/subschema/kernel/validation.py"
        if "import jsonschema\n" in source
        or "import jsonschema as " in source
        or "from jsonschema " in source
    ]
    assert jsonschema_importers == []

    jsonschema_rs_importers = [
        path
        for path, source in runtime_sources.items()
        if "import jsonschema_rs" in source
    ]
    assert jsonschema_rs_importers == ["src/subschema/kernel/validation.py"]

    forbidden_runtime_calls = (
        "instance_validator_" + "for(",
        "normalize_for_validation(",
        "validator_" + "for(",
        "VALID" + "ATORS",
    )
    violations = [
        f"{path}: {pattern}"
        for path, source in runtime_sources.items()
        if path != "src/subschema/kernel/validation.py"
        for pattern in forbidden_runtime_calls
        if pattern in source
    ]
    assert not violations, (
        "runtime validation must be routed through ValidationBackend:\n"
        + "\n".join(violations)
    )


def test_regex_backend_owns_greenery_imports():
    runtime_sources = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text()
        for path in sorted(KERNEL_ROOT.rglob("*.py"))
    }

    greenery_importers = [
        path
        for path, source in runtime_sources.items()
        if "from greenery" in source or "import greenery" in source
    ]
    assert greenery_importers == ["src/subschema/kernel/regex.py"]


def test_strict_json_helpers_own_runtime_json_serialization():
    runtime_sources = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text()
        for path in sorted(KERNEL_ROOT.rglob("*.py"))
    }

    allowed_json_module = "src/subschema/kernel/json_data.py"
    violations = [
        f"{path}: {pattern}"
        for path, source in runtime_sources.items()
        if path != allowed_json_module
        for pattern in ("json.dumps", "json.dump", "json.loads", "json.load")
        if pattern in source
    ]
    assert not violations, (
        "kernel JSON serialization must use strict json_data helpers:\n"
        + "\n".join(violations)
    )


def test_reference_schema_position_keywords_derive_from_normalization():
    normalization = importlib.import_module("subschema.kernel.normalization")
    references = importlib.import_module("subschema.kernel.references")

    assert references.SCHEMA_ARRAY_KEYWORDS == normalization.SCHEMA_ARRAY_KEYWORDS
    assert references.SCHEMA_VALUE_KEYWORDS == normalization.SCHEMA_VALUE_KEYWORDS
    assert references.SCHEMA_MAP_KEYWORDS == normalization.SCHEMA_MAP_KEYWORDS - {
        "dependencies"
    }


def test_runtime_witness_construction_is_constructive():
    runtime_sources = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text()
        for path in sorted(KERNEL_ROOT.rglob("*.py"))
    }

    witness_source = runtime_sources["src/subschema/kernel/witnesses.py"]
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


def _runtime_import_edges() -> list[ImportEdge]:
    return [edge for edge in _kernel_import_edges() if edge.scope != "type-checking"]


def _type_checking_import_edges() -> list[ImportEdge]:
    return [edge for edge in _kernel_import_edges() if edge.scope == "type-checking"]


def _kernel_import_edges() -> list[ImportEdge]:
    edges: list[ImportEdge] = []
    for path in sorted(KERNEL_ROOT.rglob("*.py")):
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


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


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
    return isinstance(node, ast.Name) and node.id == "TYPE_CHECKING"


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
        edge.source == "subschema.kernel.context"
        and edge.target == "subschema.kernel.engine"
    ):
        return "proof context must call the proof driver, not the engine facade"

    if _source_is_domain_math(edge.source) and edge.target == "subschema.kernel.engine":
        return "domain math and difference/evaluation helpers must not construct or import ProofEngine"

    if (
        edge.source.startswith(KERNEL_PREFIX)
        and edge.source != "subschema.kernel.symbolic"
        and edge.target == "z3"
    ):
        return "kernel modules must use subschema.kernel.symbolic instead of importing z3 directly"

    return None


def _forbidden_type_checking_edge_reason(edge: ImportEdge) -> str | None:
    if edge.source == "subschema.kernel.context" and edge.target.startswith(
        "subschema.kernel.evaluation"
    ):
        return "proof context must not name evaluation-specific cache value types"
    return None


def _source_is_domain_math(source: str) -> bool:
    return source.startswith("subschema.kernel.domains.") or source in {
        "subschema.kernel.difference",
        "subschema.kernel.evaluation",
    }
