from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_inventory() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts/raw_schema_read_inventory.py"
    )
    spec = importlib.util.spec_from_file_location("raw_schema_read_inventory", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_semantic_inventory() -> ModuleType:
    _load_inventory()
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts/semantic_boundary_inventory.py"
    )
    spec = importlib.util.spec_from_file_location("semantic_boundary_inventory", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_raw_schema_inventory_detects_common_schema_dict_reads(tmp_path) -> None:
    inventory = _load_inventory()
    sample = tmp_path / "sample.py"
    sample.write_text(
        "\n".join(
            (
                "def rule(schema, rhs_schema):",
                "    schema.get('type')",
                "    rhs_schema['items']",
                "    if 'not' in schema:",
                "        pass",
                "    for key, value in schema.items():",
                "        pass",
                "    variables.get('not')",
                "",
            )
        )
    )

    reads = inventory.inventory_raw_schema_reads(sample)

    assert {(read.operation, read.keyword) for read in reads} == {
        ("get", "type"),
        ("subscript", "items"),
        ("contains", "not"),
        ("items", "*iteration*"),
    }
    assert {read.receiver for read in reads} == {"schema", "rhs_schema"}


def test_raw_schema_inventory_reports_current_domain_owned_reads() -> None:
    inventory = _load_inventory()

    reads = inventory.inventory_raw_schema_reads()

    assert not any(read.area == "runtime-proof" for read in reads)
    assert not any(read.area == "other" for read in reads)
    assert any(read.area == "compiler-domain-extractor" for read in reads)
    assert any(read.area == "schema-boundary" for read in reads)
    assert any(read.area == "validation" for read in reads)


def test_raw_schema_inventory_classifies_split_proof_modules() -> None:
    inventory = _load_inventory()

    assert (
        inventory._area_for_path("src/subschema/prover/difference_arrays.py")
        == "runtime-proof"
    )
    assert (
        inventory._area_for_path("src/subschema/prover/difference_objects.py")
        == "runtime-proof"
    )
    assert (
        inventory._area_for_path("src/subschema/prover/rules/arrays.py")
        == "runtime-proof"
    )
    assert (
        inventory._area_for_path("src/subschema/prover/rules/common.py")
        == "runtime-proof"
    )


def test_raw_schema_inventory_writes_json_summary(tmp_path) -> None:
    inventory = _load_inventory()
    output = tmp_path / "inventory.json"

    result = inventory.main(["--summary", "--json-output", str(output)])

    assert result == 0
    payload = json.loads(output.read_text())
    assert payload["total"] > 0
    assert "runtime-proof" not in payload["by_area"]
    assert "other" not in payload["by_area"]
    assert "reads" in payload


def test_raw_schema_inventory_can_fail_on_requested_areas(capsys, tmp_path) -> None:
    inventory = _load_inventory()
    sample = tmp_path / "sample.py"
    sample.write_text("def rule(schema):\n    return schema.get('type')\n")

    result = inventory.main(
        [
            "--root",
            str(sample),
            "--summary",
            "--fail-on-area",
            "other",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "raw schema read ownership check failed" in captured.err
    assert "area\tother\t1" in captured.err
    assert str(sample) in captured.err


def test_raw_schema_inventory_fail_on_area_uses_full_scan(capsys, tmp_path) -> None:
    inventory = _load_inventory()
    sample = tmp_path / "sample.py"
    sample.write_text("def rule(schema):\n    return schema.get('type')\n")

    result = inventory.main(
        [
            "--root",
            str(sample),
            "--area",
            "schema-boundary",
            "--summary",
            "--fail-on-area",
            "other",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == "total\t0\n"
    assert "area\tother\t1" in captured.err


def test_raw_schema_inventory_current_source_passes_runtime_boundary() -> None:
    inventory = _load_inventory()

    result = inventory.main(
        [
            "--summary",
            "--fail-on-area",
            "runtime-proof",
            "--fail-on-area",
            "other",
        ]
    )

    assert result == 0


def test_semantic_boundary_inventory_reports_matches_and_failures(capsys) -> None:
    inventory = _load_semantic_inventory()

    result = inventory.main(
        [
            "--summary",
            "--fail-on",
            "compiler-prover-import",
            "--fail-on",
            "compiler-validator-import",
            "--fail-on",
            "ir-runtime-import",
            "--fail-on",
            "prover-compiler-import",
            "--fail-on",
            "raw-child-schema-field",
            "--fail-on",
            "raw-subproof-api",
            "--fail-on",
            "runtime-proof-raw-read",
            "--fail-on",
            "runtime-proof-extractor-call",
            "--fail-on",
            "scheduler-reason-control",
            "--fail-on",
            "shape-compat",
            "--fail-on",
            "validator-runtime-import",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "semantic_matches\t" in captured.out
    assert "semantic_failures\t0" in captured.out
    assert "semantic_violations" not in captured.out


def test_semantic_boundary_inventory_classifies_package_import_directions() -> None:
    inventory = _load_semantic_inventory()

    assert (
        inventory._forbidden_package_import_kind(
            "subschema.prover.sat", "subschema.compiler.ir"
        )
        == "prover-compiler-import"
    )
    assert (
        inventory._forbidden_package_import_kind(
            "subschema.ir.constraints", "subschema.prover.context"
        )
        == "ir-runtime-import"
    )
    assert (
        inventory._forbidden_package_import_kind(
            "subschema.validator.core", "subschema.prover.confirmation"
        )
        == "validator-runtime-import"
    )
    assert (
        inventory._forbidden_package_import_kind(
            "subschema.compiler.semantics", "subschema.prover.sat"
        )
        == "compiler-prover-import"
    )
    assert (
        inventory._forbidden_package_import_kind(
            "subschema.compiler.finite_values", "subschema.validator.core"
        )
        == "compiler-validator-import"
    )
    assert (
        inventory._forbidden_package_import_kind(
            "subschema.prover.confirmation", "subschema.validator.core"
        )
        is None
    )
