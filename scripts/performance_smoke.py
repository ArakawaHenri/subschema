from __future__ import annotations

import argparse
import io
import json
import os
import pstats
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PerformanceCase:
    key: str
    name: str
    nodeid: str
    max_seconds: float


CASES = (
    PerformanceCase(
        "bigchaindb-transaction",
        "bigchaindb transaction",
        "test/test_more.py::TestPaperBigchainDB::test_transaction",
        8.0,
    ),
    PerformanceCase(
        "bigchaindb-election",
        "bigchaindb election",
        "test/test_more.py::TestPaperBigchainDB::test_transaction_vote_transaction_validator_election",
        8.0,
    ),
    PerformanceCase(
        "ai-tfidf-housing",
        "ai tfidf housing",
        "test/test_ai_subschema.py::test_dataset_operator_pair[tfidf-housing]",
        8.0,
    ),
    PerformanceCase(
        "ai-nmf-housing",
        "ai nmf housing",
        "test/test_ai_subschema.py::test_dataset_operator_pair[nmf-housing]",
        8.0,
    ),
    PerformanceCase(
        "ai-project-creditg",
        "ai project creditG",
        "test/test_ai_subschema.py::test_dataset_operator_pair[project-creditG]",
        8.0,
    ),
    PerformanceCase(
        "object-tricky6",
        "object tricky pattern/value",
        "test/test_object.py::TestObjectSubtype::test_tricky6",
        8.0,
    ),
    PerformanceCase(
        "array-unique-finite-cardinality",
        "array unique finite cardinality",
        "test/test_low_cost_fragments.py::test_unique_items_with_finite_items_can_be_empty_by_cardinality",
        4.0,
    ),
    PerformanceCase(
        "regex-whitespace-witness",
        "regex whitespace witness",
        "test/test_regex_language.py::test_regex_language_whitespace_fast_witness_avoids_fsm",
        4.0,
    ),
    PerformanceCase(
        "external-resource-sibling-ref",
        "external resource sibling reference",
        "test/test_refs.py::TestModernRefs::test_registered_external_resource_can_reference_registered_sibling",
        4.0,
    ),
)
TOTAL_MAX_SECONDS = 30.0
PROFILE_SOURCE_FILTER = r"src/subschema"


@dataclass(frozen=True)
class PerformanceResult:
    case: PerformanceCase
    elapsed_seconds: float
    threshold_seconds: float
    passed: bool
    profile_path: Path | None = None
    profile_summary_path: Path | None = None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.list:
        for case in CASES:
            print(f"{case.key}\t{case.nodeid}")
        return 0

    root = Path(__file__).resolve().parents[1]
    thresholds_enforced = args.profile_dir is None
    threshold_multiplier = args.multiplier
    selected_cases = _selected_cases(args.case)
    total_start = time.perf_counter()
    failures: list[str] = []
    results: list[PerformanceResult] = []

    for case in selected_cases:
        profile_path = _profile_path(args.profile_dir, case)
        profile_summary_path = _profile_summary_path(args.profile_summary_dir, case)
        elapsed = _run_case(root, case, profile_path=profile_path)
        if profile_path is not None and profile_summary_path is not None:
            _write_profile_summary(
                profile_path,
                profile_summary_path,
                limit=args.profile_summary_limit,
            )
        threshold = case.max_seconds * threshold_multiplier
        result = PerformanceResult(
            case=case,
            elapsed_seconds=elapsed,
            threshold_seconds=threshold,
            passed=not thresholds_enforced or elapsed <= threshold,
            profile_path=profile_path,
            profile_summary_path=profile_summary_path,
        )
        results.append(result)
        print(f"{case.name}: {elapsed:.3f}s (limit {threshold:.3f}s)")
        if thresholds_enforced and elapsed > threshold:
            failures.append(
                f"{case.name} took {elapsed:.3f}s, above {threshold:.3f}s"
            )

    total_elapsed = time.perf_counter() - total_start
    total_threshold = TOTAL_MAX_SECONDS * threshold_multiplier
    print(f"total: {total_elapsed:.3f}s (limit {total_threshold:.3f}s)")
    if thresholds_enforced and total_elapsed > total_threshold:
        failures.append(
            f"total took {total_elapsed:.3f}s, above {total_threshold:.3f}s"
        )

    if args.json_output is not None:
        _write_json_output(
            args.json_output,
            results,
            total_elapsed=total_elapsed,
            total_threshold=total_threshold,
            passed=not failures,
        )

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a small performance smoke suite for subschema.",
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(case.key for case in CASES),
        help="Run only this case. May be passed more than once.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available case keys and exit.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Write machine-readable timing results to this JSON file.",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        help="Write cProfile .prof files for each selected case to this directory.",
    )
    parser.add_argument(
        "--profile-summary-dir",
        type=Path,
        help=(
            "Write human-readable pstats summaries for each selected case. "
            "Requires --profile-dir."
        ),
    )
    parser.add_argument(
        "--profile-summary-limit",
        type=int,
        default=30,
        help="Number of pstats rows to write per profile summary. Defaults to 30.",
    )
    parser.add_argument(
        "--multiplier",
        type=float,
        default=float(os.environ.get("SUBSCHEMA_PERF_MULTIPLIER", "1")),
        help="Threshold multiplier. Defaults to SUBSCHEMA_PERF_MULTIPLIER or 1.",
    )
    args = parser.parse_args(argv)
    if args.profile_summary_dir is not None and args.profile_dir is None:
        parser.error("--profile-summary-dir requires --profile-dir")
    return args


def _selected_cases(case_keys: list[str] | None) -> tuple[PerformanceCase, ...]:
    if not case_keys:
        return CASES
    requested = set(case_keys)
    return tuple(case for case in CASES if case.key in requested)


def _write_json_output(
    path: Path,
    results: list[PerformanceResult],
    *,
    total_elapsed: float,
    total_threshold: float,
    passed: bool,
) -> None:
    payload = {
        "passed": passed,
        "total": {
            "elapsed_seconds": total_elapsed,
            "threshold_seconds": total_threshold,
        },
        "cases": [
            {
                "key": result.case.key,
                "name": result.case.name,
                "nodeid": result.case.nodeid,
                "elapsed_seconds": result.elapsed_seconds,
                "threshold_seconds": result.threshold_seconds,
                "passed": result.passed,
                "profile_path": (
                    None if result.profile_path is None else str(result.profile_path)
                ),
                "profile_summary_path": (
                    None
                    if result.profile_summary_path is None
                    else str(result.profile_summary_path)
                ),
            }
            for result in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _profile_path(profile_dir: Path | None, case: PerformanceCase) -> Path | None:
    if profile_dir is None:
        return None
    return profile_dir / f"{case.key}.prof"


def _profile_summary_path(
    profile_summary_dir: Path | None,
    case: PerformanceCase,
) -> Path | None:
    if profile_summary_dir is None:
        return None
    return profile_summary_dir / f"{case.key}.txt"


def _write_profile_summary(
    profile_path: Path,
    summary_path: Path,
    *,
    limit: int,
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    stream.write("=== cumulative ===\n")
    pstats.Stats(str(profile_path), stream=stream).strip_dirs().sort_stats(
        "cumulative"
    ).print_stats(limit)
    stream.write("\n=== subschema cumulative ===\n")
    pstats.Stats(str(profile_path), stream=stream).sort_stats("cumulative").print_stats(
        PROFILE_SOURCE_FILTER,
        limit,
    )
    stream.write("\n=== subschema internal ===\n")
    pstats.Stats(str(profile_path), stream=stream).sort_stats("tottime").print_stats(
        PROFILE_SOURCE_FILTER,
        limit,
    )
    summary_path.write_text(stream.getvalue())


def _run_case(
    root: Path,
    case: PerformanceCase,
    *,
    profile_path: Path | None = None,
) -> float:
    command = [sys.executable, "-m", "pytest", "-q", case.nodeid]
    if profile_path is not None:
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "cProfile",
            "-o",
            str(profile_path),
            "-m",
            "pytest",
            "-q",
            case.nodeid,
        ]
    start = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    if completed.returncode != 0:
        output = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        )
        raise SystemExit(f"{case.name} failed:\n{output}")
    return elapsed


if __name__ == "__main__":
    raise SystemExit(main())
