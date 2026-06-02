import ast
import importlib
import tomllib
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


def _minimum_version_for_requirement(
    requirements: list[str], package_name: str
) -> tuple[int, ...]:
    normalized_package_name = package_name.replace("_", "-").lower()
    for requirement in requirements:
        normalized_requirement = requirement.replace("_", "-").lower()
        if not normalized_requirement.startswith(f"{normalized_package_name}>="):
            continue
        version_text = requirement.partition(">=")[2].split(",", 1)[0].strip()
        return tuple(int(part) for part in version_text.split("."))
    raise AssertionError(f"{package_name} requirement not found in {requirements!r}")


def test_public_release_metadata_matches_distribution_identity():
    metadata = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    build_system = metadata["build-system"]
    project = metadata["project"]

    assert build_system["build-backend"] == "hatchling.build"
    assert _minimum_version_for_requirement(build_system["requires"], "hatchling") >= (
        1,
        27,
        0,
    )
    assert project["name"] == "subschema"
    assert project["version"] == "0.0.1"
    assert project["license"] == "Apache-2.0"
    assert project["authors"] == [
        {"name": "Henri", "email": "henri-zhang@outlook.com"}
    ]
    assert project["urls"]["Homepage"] == "https://github.com/ArakawaHenri/subschema"
    assert project["urls"]["Repository"] == "https://github.com/ArakawaHenri/subschema"


def test_public_release_surface_has_no_removed_config_or_unused_dependencies():
    assert not (PACKAGE_ROOT / "config.py").exists()
    metadata = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert "setuptools" not in metadata.get("tool", {})
    assert "MANIFEST.in" not in metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    wheel_target = metadata["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel_target["only-include"] == ["src"]
    assert wheel_target["sources"] == ["src"]
    dependencies = metadata["project"]["dependencies"]
    assert not any(dependency.startswith("json" "ref") for dependency in dependencies)
    assert not any(dependency.startswith("por" "tion") for dependency in dependencies)

    forbidden_patterns = (
        "subschema." "config",
        "set_" "debug",
        "set_" "warn_uninhabited",
        "set_" "json_validator_version",
        "ssonsub" "schema",
    )
    violations = [
        f"{path.relative_to(REPO_ROOT).as_posix()}: {pattern}"
        for path in _release_surface_files()
        for pattern in forbidden_patterns
        if pattern in path.read_text()
    ]

    assert not violations, "public release surface contains removed names:\n" + "\n".join(violations)


def test_public_release_surface_has_only_minimal_ibm_acknowledgement():
    assert not (REPO_ROOT / ("D" "CO1.1.txt")).exists()
    if (REPO_ROOT / "docs").exists():
        assert not list((REPO_ROOT / "docs").glob("ph" "ase-*.md"))

    readme = (REPO_ROOT / "README.md").read_text()
    allowed_acknowledgement = (
        "This project is a rewrite based on I" "BM's\n"
        "[json" "subschema](https://github.com/I" "BM/json" "subschema) project and may retain\n"
        "portions of its source code. Credit to I" "BM and contributors."
    )
    assert allowed_acknowledgement in readme

    forbidden_public_history_terms = (
        "IS" "STA",
        "Distinguished " "Artifact",
        "@auth" "or",
        "D" "CO",
        "0.1.0" "a1",
        "Al" "pha",
        "Be" "ta",
    )
    violations = [
        f"{path.relative_to(REPO_ROOT).as_posix()}: {term}"
        for path in _release_surface_files()
        for term in forbidden_public_history_terms
        if term in path.read_text()
    ]
    assert not violations, "public release surface contains old project history:\n" + "\n".join(violations)

    ibm_hits = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _release_surface_files()
        if "I" "BM" in path.read_text()
        or "github.com/I" "BM/json" "subschema" in path.read_text()
    ]
    assert ibm_hits == ["README.md"]


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
    assert not violations, "object presence products must be routed through SymbolicSolver:\n" + "\n".join(violations)


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
    assert not violations, "runtime validation must be routed through ValidationBackend:\n" + "\n".join(violations)


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
    assert not violations, "kernel JSON serialization must use strict json_data helpers:\n" + "\n".join(violations)


def test_reference_schema_position_keywords_derive_from_normalization():
    normalization = importlib.import_module("subschema.kernel.normalization")
    references = importlib.import_module("subschema.kernel.references")

    assert references.SCHEMA_ARRAY_KEYWORDS == normalization.SCHEMA_ARRAY_KEYWORDS
    assert references.SCHEMA_VALUE_KEYWORDS == normalization.SCHEMA_VALUE_KEYWORDS
    assert references.SCHEMA_MAP_KEYWORDS == normalization.SCHEMA_MAP_KEYWORDS - {"dependencies"}


def test_runtime_witness_construction_is_constructive_not_candidate_probe():
    runtime_sources = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text()
        for path in sorted(KERNEL_ROOT.rglob("*.py"))
    }

    deleted_witness_api = (
        "NO_WITNESS",
        "SchemaWitnessPlan",
        "first_valid_value_for_schema",
        "schema_witness_plan",
        "_typed_witness_candidates",
    )
    violations = [
        f"{path}: {pattern}"
        for path, source in runtime_sources.items()
        for pattern in deleted_witness_api
        if pattern in source
    ]
    assert not violations, "runtime witness construction must use WitnessBuilder:\n" + "\n".join(violations)

    witness_source = runtime_sources["src/subschema/kernel/witnesses.py"]
    forbidden_probe_patterns = (
        "for candidate in",
        ".is_valid(",
        "validates_difference(",
    )
    probe_violations = [pattern for pattern in forbidden_probe_patterns if pattern in witness_source]
    assert not probe_violations, "WitnessBuilder must construct values rather than validator-probing candidates"


def _runtime_import_edges() -> list[ImportEdge]:
    return [edge for edge in _kernel_import_edges() if edge.scope != "type-checking"]


def _release_surface_files() -> list[Path]:
    roots = (
        PACKAGE_ROOT,
        REPO_ROOT / "test",
        REPO_ROOT / "docs",
        REPO_ROOT / ".github",
    )
    files = [
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*")
        if path.suffix in {".md", ".py", ".toml", ".yml", ".yaml"}
    ]
    files.extend(
        path
        for path in (
            REPO_ROOT / "README.md",
            REPO_ROOT / "pyproject.toml",
            REPO_ROOT / "LICENSE",
        )
        if path.exists()
    )
    return [
        path
        for path in files
        if "__pycache__" not in path.parts
        and path != Path(__file__)
    ]


def _kernel_import_edges() -> list[ImportEdge]:
    edges: list[ImportEdge] = []
    for path in sorted(KERNEL_ROOT.rglob("*.py")):
        source = _module_name(path)
        tree = ast.parse(path.read_text(), filename=str(path))
        _attach_parents(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                scope = _import_scope(node)
                edges.extend(ImportEdge(source, alias.name, node.lineno, scope) for alias in node.names)
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
    if edge.source == "subschema.kernel.context" and edge.target == "subschema.kernel.engine":
        return "proof context must call the proof driver, not the engine facade"

    if _source_is_domain_math(edge.source) and edge.target == "subschema.kernel.engine":
        return "domain math and difference/evaluation helpers must not construct or import ProofEngine"

    if edge.source.startswith(KERNEL_PREFIX) and edge.source != "subschema.kernel.symbolic" and edge.target == "z3":
        return "kernel modules must use subschema.kernel.symbolic instead of importing z3 directly"

    return None


def _source_is_domain_math(source: str) -> bool:
    return source.startswith("subschema.kernel.domains.") or source in {
        "subschema.kernel.difference",
        "subschema.kernel.evaluation",
    }
