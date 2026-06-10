from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCAN_ROOT = REPO_ROOT / "src" / "subschema"
SCHEMA_BOUNDARY_FILES = {
    "src/subschema/dialects.py",
    "src/subschema/json_data.py",
    "src/subschema/provenance.py",
    "src/subschema/values.py",
    "src/subschema/compiler/schemas.py",
    "src/subschema/prover/formulas.py",
    "src/subschema/validator/normalization.py",
}
VALIDATION_FILES = {
    "src/subschema/validator/core.py",
}
DIAGNOSTIC_FILES = {
    "src/subschema/prover/driver.py",
}
DOMAIN_FACT_FILES = {
    "src/subschema/compiler/literals.py",
}
RUNTIME_PROOF_FILES = {
    "src/subschema/prover/applicators.py",
    "src/subschema/prover/confirmation.py",
    "src/subschema/prover/difference.py",
    "src/subschema/prover/difference_arrays.py",
    "src/subschema/prover/difference_objects.py",
    "src/subschema/prover/disjointness.py",
    "src/subschema/prover/evaluation_traces.py",
    "src/subschema/prover/overlaps.py",
    "src/subschema/prover/finite.py",
    "src/subschema/prover/projection.py",
    "src/subschema/prover/sat.py",
    "src/subschema/prover/scalars.py",
    "src/subschema/prover/witnesses.py",
}
RUNTIME_PROOF_PREFIXES = (
    "src/subschema/prover/rules/",
)
SCHEMA_LIKE_NAMES = {
    "dependent_schema",
    "lhs",
    "lhs_schema",
    "negated",
    "rhs",
    "rhs_schema",
    "schema",
    "subschema",
}
SCHEMA_LIKE_ATTRIBUTE_NAMES = {
    "lhs_schema",
    "rhs_schema",
    "schema",
}
DICT_READ_METHODS = {"get", "items", "keys", "values"}
AREA_CHOICES = (
    "compiler-domain-extractor",
    "diagnostics",
    "runtime-proof",
    "schema-boundary",
    "validation",
    "other",
)


@dataclass(frozen=True)
class RawSchemaRead:
    path: str
    line: int
    column: int
    scope: str
    area: str
    receiver: str
    operation: str
    keyword: str


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    all_reads = inventory_raw_schema_reads(args.root)
    reads = all_reads
    if args.area:
        requested_areas = set(args.area)
        reads = [read for read in reads if read.area in requested_areas]

    if args.json_output is not None:
        _write_json_output(args.json_output, reads)

    if args.summary:
        _print_summary(reads)
    else:
        _print_reads(reads)

    violations = _fail_on_area_violations(all_reads, args.fail_on_area)
    if violations:
        _print_fail_on_area_violations(violations)
        return 1
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory direct raw schema dictionary reads in prover code. "
            "Tests enforce the runtime-proof boundary from this inventory."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_SCAN_ROOT,
        help="Directory or file to scan. Defaults to src/subschema.",
    )
    parser.add_argument(
        "--area",
        action="append",
        choices=AREA_CHOICES,
        help="Filter output to one area. May be passed more than once.",
    )
    parser.add_argument(
        "--fail-on-area",
        action="append",
        choices=AREA_CHOICES,
        help=(
            "Exit non-zero if any read is found in this area. "
            "Unlike --area, this checks the full scan result."
        ),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print counts by area and file instead of every read.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Write the full inventory as JSON.",
    )
    return parser.parse_args(argv)


def inventory_raw_schema_reads(root: Path = DEFAULT_SCAN_ROOT) -> list[RawSchemaRead]:
    return [
        read
        for path in _python_paths(root)
        for read in RawSchemaReadVisitor(path).collect()
    ]


def _python_paths(root: Path) -> tuple[Path, ...]:
    if root.is_file():
        return (root,)
    return tuple(sorted(root.rglob("*.py")))


class RawSchemaReadVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.relative_path = _relative_path(path)
        self.area = _area_for_path(self.relative_path)
        self.scope_stack: list[str] = []
        self.reads: list[RawSchemaRead] = []

    def collect(self) -> list[RawSchemaRead]:
        tree = ast.parse(self.path.read_text(), filename=str(self.path))
        self.visit(tree)
        return self.reads

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

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in DICT_READ_METHODS:
            receiver = node.func.value
            if _is_schema_like_expr(receiver):
                keyword = (
                    _string_constant(node.args[0])
                    if node.func.attr == "get" and node.args
                    else "*iteration*"
                )
                self._record(
                    node,
                    receiver=receiver,
                    operation=node.func.attr,
                    keyword=keyword or "*dynamic*",
                )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_schema_like_expr(node.value):
            self._record(
                node,
                receiver=node.value,
                operation="subscript",
                keyword=_slice_string(node.slice) or "*dynamic*",
            )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if len(node.ops) == 1 and len(node.comparators) == 1:
            op = node.ops[0]
            comparator = node.comparators[0]
            if isinstance(op, ast.In | ast.NotIn) and _is_schema_like_expr(
                comparator
            ):
                keyword = _string_constant(node.left)
                self._record(
                    node,
                    receiver=comparator,
                    operation="contains" if isinstance(op, ast.In) else "not-contains",
                    keyword=keyword or "*dynamic*",
                )
        self.generic_visit(node)

    def _record(
        self,
        node: ast.AST,
        *,
        receiver: ast.AST,
        operation: str,
        keyword: str,
    ) -> None:
        self.reads.append(
            RawSchemaRead(
                path=self.relative_path,
                line=node.lineno,
                column=node.col_offset,
                scope=".".join(self.scope_stack) or "<module>",
                area=self.area,
                receiver=_expr_name(receiver) or "<expr>",
                operation=operation,
                keyword=keyword,
            )
        )


def _relative_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _area_for_path(relative_path: str) -> str:
    if relative_path in SCHEMA_BOUNDARY_FILES:
        return "schema-boundary"
    if relative_path in VALIDATION_FILES:
        return "validation"
    if relative_path in DIAGNOSTIC_FILES:
        return "diagnostics"
    if relative_path.startswith("src/subschema/compiler/"):
        return "compiler-domain-extractor"
    if relative_path.startswith("src/subschema/prover/domains/"):
        return "compiler-domain-extractor"
    if relative_path in DOMAIN_FACT_FILES:
        return "compiler-domain-extractor"
    if relative_path in RUNTIME_PROOF_FILES:
        return "runtime-proof"
    if relative_path.startswith(RUNTIME_PROOF_PREFIXES):
        return "runtime-proof"
    return "other"


def _is_schema_like_expr(node: ast.AST) -> bool:
    name = _expr_name(node)
    if name is None:
        return False
    parts = name.split(".")
    return (
        parts[-1] in SCHEMA_LIKE_NAMES
        or parts[-1] in SCHEMA_LIKE_ATTRIBUTE_NAMES
    )


def _expr_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expr_name(node.value)
        if parent is None:
            return node.attr
        return f"{parent}.{node.attr}"
    return None


def _string_constant(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _slice_string(node: ast.AST) -> str | None:
    return _string_constant(node)


def _write_json_output(path: Path, reads: Sequence[RawSchemaRead]) -> None:
    payload = {
        "total": len(reads),
        "by_area": dict(_count_by(reads, "area")),
        "by_file": dict(_count_by(reads, "path")),
        "reads": [asdict(read) for read in reads],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _print_summary(reads: Sequence[RawSchemaRead]) -> None:
    print(f"total\t{len(reads)}")
    for area, count in _count_by(reads, "area").items():
        print(f"area\t{area}\t{count}")
    for path, count in _count_by(reads, "path").most_common():
        print(f"file\t{path}\t{count}")


def _print_reads(reads: Iterable[RawSchemaRead]) -> None:
    for read in reads:
        print(
            "\t".join(
                (
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


def _fail_on_area_violations(
    reads: Sequence[RawSchemaRead],
    requested_areas: Sequence[str] | None,
) -> list[RawSchemaRead]:
    if not requested_areas:
        return []
    requested = set(requested_areas)
    return [read for read in reads if read.area in requested]


def _print_fail_on_area_violations(reads: Sequence[RawSchemaRead]) -> None:
    print("raw schema read ownership check failed", file=sys.stderr)
    for area, count in _count_by(reads, "area").items():
        print(f"area\t{area}\t{count}", file=sys.stderr)
    for read in reads[:20]:
        print(
            "\t".join(
                (
                    read.area,
                    read.path,
                    str(read.line),
                    read.scope,
                    read.receiver,
                    read.operation,
                    read.keyword,
                )
            ),
            file=sys.stderr,
        )
    if len(reads) > 20:
        print(f"... {len(reads) - 20} more", file=sys.stderr)


def _count_by(
    reads: Sequence[RawSchemaRead], field_name: str
) -> Counter[str]:
    return Counter(str(getattr(read, field_name)) for read in reads)


if __name__ == "__main__":
    raise SystemExit(main())
