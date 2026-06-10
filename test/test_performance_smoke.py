from __future__ import annotations

import cProfile
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_performance_smoke() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts/performance_smoke.py"
    spec = importlib.util.spec_from_file_location("performance_smoke", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_performance_smoke_lists_cases(capsys) -> None:
    performance_smoke = _load_performance_smoke()

    assert performance_smoke.main(["--list"]) == 0

    output = capsys.readouterr().out
    assert "array-unique-finite-cardinality" in output
    assert "ai-project-creditg" in output
    assert "bigchaindb-transaction" in output
    assert "external-resource-sibling-ref" in output
    assert "regex-whitespace-witness" in output


def test_performance_smoke_filters_cases_and_writes_json(monkeypatch, tmp_path) -> None:
    performance_smoke = _load_performance_smoke()
    seen: list[str] = []

    def fake_run_case(root: Path, case, *, profile_path=None) -> float:
        assert profile_path is None
        seen.append(case.key)
        return 0.25

    monkeypatch.setattr(performance_smoke, "_run_case", fake_run_case)
    json_output = tmp_path / "performance.json"

    result = performance_smoke.main(
        [
            "--case",
            "regex-whitespace-witness",
            "--json-output",
            str(json_output),
        ]
    )

    assert result == 0
    assert seen == ["regex-whitespace-witness"]
    payload = json.loads(json_output.read_text())
    assert payload["passed"] is True
    assert [case["key"] for case in payload["cases"]] == [
        "regex-whitespace-witness"
    ]
    assert payload["cases"][0]["profile_path"] is None
    assert payload["cases"][0]["profile_summary_path"] is None


def test_performance_smoke_profiles_selected_cases(monkeypatch, tmp_path) -> None:
    performance_smoke = _load_performance_smoke()
    seen_profiles: list[Path | None] = []

    def fake_run_case(root: Path, case, *, profile_path=None) -> float:
        seen_profiles.append(profile_path)
        if profile_path is not None:
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.write_bytes(b"profile")
        return 0.25

    monkeypatch.setattr(performance_smoke, "_run_case", fake_run_case)
    profile_dir = tmp_path / "profiles"
    json_output = tmp_path / "performance.json"

    result = performance_smoke.main(
        [
            "--case",
            "regex-whitespace-witness",
            "--profile-dir",
            str(profile_dir),
            "--json-output",
            str(json_output),
        ]
    )

    assert result == 0
    assert seen_profiles == [profile_dir / "regex-whitespace-witness.prof"]
    assert seen_profiles[0] is not None
    assert seen_profiles[0].read_bytes() == b"profile"
    payload = json.loads(json_output.read_text())
    assert payload["cases"][0]["profile_path"] == str(seen_profiles[0])
    assert payload["cases"][0]["profile_summary_path"] is None


def test_performance_smoke_writes_profile_summaries(monkeypatch, tmp_path) -> None:
    performance_smoke = _load_performance_smoke()

    def fake_run_case(root: Path, case, *, profile_path=None) -> float:
        assert profile_path is not None
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profiler = cProfile.Profile()
        profiler.runcall(lambda: sum(range(10)))
        profiler.dump_stats(profile_path)
        return 0.25

    monkeypatch.setattr(performance_smoke, "_run_case", fake_run_case)
    profile_dir = tmp_path / "profiles"
    summary_dir = tmp_path / "profile-summaries"
    json_output = tmp_path / "performance.json"

    result = performance_smoke.main(
        [
            "--case",
            "regex-whitespace-witness",
            "--profile-dir",
            str(profile_dir),
            "--profile-summary-dir",
            str(summary_dir),
            "--json-output",
            str(json_output),
        ]
    )

    summary_path = summary_dir / "regex-whitespace-witness.txt"
    assert result == 0
    assert summary_path.exists()
    assert "function calls" in summary_path.read_text()
    payload = json.loads(json_output.read_text())
    assert payload["cases"][0]["profile_summary_path"] == str(summary_path)


def test_performance_smoke_reports_threshold_failures(monkeypatch, capsys) -> None:
    performance_smoke = _load_performance_smoke()

    def fake_run_case(root: Path, case, *, profile_path=None) -> float:
        assert profile_path is None
        return case.max_seconds + 1

    monkeypatch.setattr(performance_smoke, "_run_case", fake_run_case)

    result = performance_smoke.main(
        [
            "--case",
            "regex-whitespace-witness",
            "--multiplier",
            "1",
        ]
    )

    assert result == 1
    assert "regex whitespace witness took" in capsys.readouterr().err
