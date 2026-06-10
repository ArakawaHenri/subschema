from __future__ import annotations

import argparse
import ast
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from raw_schema_read_inventory import (
    DEFAULT_SCAN_ROOT,
    REPO_ROOT,
    RawSchemaRead,
    _area_for_path,
    _python_paths,
    inventory_raw_schema_reads,
)

FAIL_CHECKS = (
    "compiler-prover-import",
    "compiler-validator-import",
    "ir-runtime-import",
    "domain-facts",
    "prover-compiler-import",
    "raw-child-schema-field",
    "raw-subproof-api",
    "runtime-proof-extractor-call",
    "runtime-proof-raw-read",
    "scheduler-reason-control",
    "shape-compat",
    "validator-runtime-import",
)
EXTRACTOR_MODULE_PREFIXES = (
    "subschema.compiler.domains.",
)
EXTRACTOR_MODULES = {
    "subschema.compiler.finite_values",
    "subschema.compiler.schemas",
    "subschema.compiler.tagged_unions",
}
EXTRACTOR_NAMES = {
    "contains_reference_keyword",
    "finite_values_for_schema",
    "schema_covers_type_atom",
    "schema_required_singleton_tags",
    "schema_type_overapproximations_are_disjoint",
    "type_overapproximation_for_schema",
}
RAW_CHILD_SCHEMA_NAMES = {
    "base_schema",
    "covering_schema",
    "lhs_schema",
    "property_schema_for",
    "rhs_schema",
    "schema_at_index",
    "value_schema_for",
}
RAW_SUBPROOF_API_NAMES = {
    "compile_schema",
    "subproof",
}


@dataclass(frozen=True)
class SemanticBoundaryMatch:
    kind: str
    area: str
    path: str
    line: int
    scope: str
    symbol: str


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    raw_reads = inventory_raw_schema_reads(args.root)
    matches = semantic_boundary_matches(args.root)
    if args.summary:
        _print_summary(raw_reads, matches, args.fail_on)
    else:
        _print_raw_reads(raw_reads)
        _print_matches(matches)

    failures = _failures(raw_reads, matches, args.fail_on)
    if failures:
        _print_failures(failures)
        return 1
    return 0


def semantic_boundary_matches(
    root: Path = DEFAULT_SCAN_ROOT,
) -> list[SemanticBoundaryMatch]:
    return [
        match
        for path in _python_paths(root)
        for match in SemanticBoundaryVisitor(path).collect()
    ]


class SemanticBoundaryVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.relative_path = _relative_path(path)
        self.source_module = _module_name(path)
        self.area = _area_for_path(self.relative_path)
        self.scope_stack: list[str] = []
        self.imported_extractors: set[str] = set()
        self.matches: list[SemanticBoundaryMatch] = []

    def collect(self) -> list[SemanticBoundaryMatch]:
        tree = ast.parse(self.path.read_text(), filename=str(self.path))
        self.visit(tree)
        return self.matches

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "" if node.module is None else node.module
        resolved_module = _resolve_import_from_module(self.source_module, node)
        if resolved_module is not None:
            if resolved_module == "subschema":
                for alias in node.names:
                    if alias.name != "*":
                        self._record_forbidden_import(
                            node, f"subschema.{alias.name}"
                        )
            else:
                self._record_forbidden_import(node, resolved_module)
        if _is_extractor_module(module):
            for alias in node.names:
                if module.startswith(EXTRACTOR_MODULE_PREFIXES) or _is_extractor_name(
                    alias.name
                ):
                    imported = alias.asname or alias.name
                    self.imported_extractors.add(imported)
                    self._record(node, "runtime-proof-extractor-call", imported)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record_forbidden_import(node, alias.name)
            if _is_extractor_module(alias.name):
                self._record(
                    node,
                    "runtime-proof-extractor-call",
                    alias.asname or alias.name,
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name is not None:
            leaf_name = name.rsplit(".", 1)[-1]
            if leaf_name in self.imported_extractors or _is_extractor_name(leaf_name):
                self._record(node, "runtime-proof-extractor-call", name)
            if leaf_name in RAW_SUBPROOF_API_NAMES:
                self._record(node, "raw-subproof-api", name)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._is_scheduler_control_scope() and node.attr == "reason":
            root = _attribute_root_name(node)
            if root == "proof":
                self._record(node, "scheduler-reason-control", "proof.reason")
        if node.attr == "shape":
            self._record(node, "shape-compat", "shape")
        if node.attr in RAW_CHILD_SCHEMA_NAMES:
            self._record(node, "raw-child-schema-field", node.attr)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "DomainFacts":
            self._record(node, "domain-facts", "DomainFacts")
        if node.id in RAW_CHILD_SCHEMA_NAMES:
            self._record(node, "raw-child-schema-field", node.id)
        self.generic_visit(node)

    def _record_forbidden_import(self, node: ast.AST, target: str) -> None:
        kind = _forbidden_package_import_kind(self.source_module, target)
        if kind is not None:
            self._record(node, kind, target)

    def _record(self, node: ast.AST, kind: str, symbol: str) -> None:
        self.matches.append(
            SemanticBoundaryMatch(
                kind=kind,
                area=self.area,
                path=self.relative_path,
                line=node.lineno,
                scope=".".join(self.scope_stack) or "<module>",
                symbol=symbol,
            )
        )

    def _is_scheduler_control_scope(self) -> bool:
        return self.source_module == "subschema.prover.sat" and bool(
            set(self.scope_stack)
            & {
                "_preferred_unsupported_result",
                "_proof_after_rule_class_guard",
                "_rule_unsupported_disposition",
                "_should_stop_after_rule_unsupported",
            }
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory semantic boundary leaks in the prover."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_SCAN_ROOT)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--fail-on", action="append", choices=FAIL_CHECKS)
    return parser.parse_args(argv)


def _failures(
    raw_reads: Sequence[RawSchemaRead],
    matches: Sequence[SemanticBoundaryMatch],
    requested: Sequence[str] | None,
) -> list[RawSchemaRead | SemanticBoundaryMatch]:
    if not requested:
        return []
    requested_set = set(requested)
    failures: list[RawSchemaRead | SemanticBoundaryMatch] = []
    if "runtime-proof-raw-read" in requested_set:
        failures.extend(read for read in raw_reads if read.area == "runtime-proof")
    package_wide_checks = {
        "compiler-prover-import",
        "compiler-validator-import",
        "ir-runtime-import",
        "prover-compiler-import",
        "validator-runtime-import",
    }
    failures.extend(
        match
        for match in matches
        if match.kind in requested_set
        and match.kind in package_wide_checks
    )
    failures.extend(
        match
        for match in matches
        if match.kind in requested_set and match.area == "runtime-proof"
    )
    return failures


def _print_summary(
    raw_reads: Sequence[RawSchemaRead],
    matches: Sequence[SemanticBoundaryMatch],
    requested: Sequence[str] | None,
) -> None:
    print(f"raw_reads\t{len(raw_reads)}")
    for area, count in Counter(read.area for read in raw_reads).items():
        print(f"raw_area\t{area}\t{count}")
    failures = _failures(raw_reads, matches, requested)
    print(f"semantic_matches\t{len(matches)}")
    print(f"semantic_failures\t{len(failures)}")
    for key, count in Counter(
        (match.kind, match.area) for match in matches
    ).items():
        kind, area = key
        print(f"semantic\t{kind}\t{area}\t{count}")
    semantic_files = Counter(match.path for match in matches)
    for path, count in semantic_files.most_common():
        print(f"semantic_file\t{path}\t{count}")


def _print_raw_reads(reads: Iterable[RawSchemaRead]) -> None:
    for read in reads:
        print(
            "\t".join(
                (
                    "raw-read",
                    read.area,
                    read.path,
                    str(read.line),
                    read.scope,
                    read.receiver,
                    read.operation,
                    read.keyword,
                )
            )
        )


def _print_matches(matches: Iterable[SemanticBoundaryMatch]) -> None:
    for match in matches:
        print(
            "\t".join(
                (
                    match.kind,
                    match.area,
                    match.path,
                    str(match.line),
                    match.scope,
                    match.symbol,
                )
            )
        )


def _print_failures(
    failures: Sequence[RawSchemaRead | SemanticBoundaryMatch],
) -> None:
    print("semantic boundary check failed", file=sys.stderr)
    for item in failures[:30]:
        print(item, file=sys.stderr)
    if len(failures) > 30:
        print(f"... {len(failures) - 30} more", file=sys.stderr)


def _relative_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _is_extractor_module(module: str) -> bool:
    return module in EXTRACTOR_MODULES or module.startswith(EXTRACTOR_MODULE_PREFIXES)


def _is_extractor_name(name: str) -> bool:
    return name in EXTRACTOR_NAMES


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return node.attr if parent is None else f"{parent}.{node.attr}"
    return None


def _attribute_root_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _attribute_root_name(node.value)
    return None


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


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


def _forbidden_package_import_kind(source: str, target: str) -> str | None:
    if source.startswith("subschema.ir") and target.startswith(
        ("subschema.compiler", "subschema.prover", "subschema.validator")
    ):
        return "ir-runtime-import"
    if source.startswith("subschema.prover") and target.startswith(
        "subschema.compiler"
    ):
        return "prover-compiler-import"
    if source.startswith("subschema.validator") and target.startswith(
        ("subschema.compiler", "subschema.prover")
    ):
        return "validator-runtime-import"
    if source.startswith("subschema.compiler") and target.startswith(
        "subschema.prover"
    ):
        return "compiler-prover-import"
    if source.startswith("subschema.compiler") and target.startswith(
        "subschema.validator"
    ):
        return "compiler-validator-import"
    return None


if __name__ == "__main__":
    raise SystemExit(main())
