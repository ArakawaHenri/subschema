from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PerformanceCase:
    name: str
    nodeid: str
    max_seconds: float


CASES = (
    PerformanceCase(
        "bigchaindb transaction",
        "test/test_more.py::TestPaperBigchainDB::test_transaction",
        8.0,
    ),
    PerformanceCase(
        "ai tfidf housing",
        "test/test_ai_subschema.py::test_dataset_operator_pair[tfidf-housing]",
        8.0,
    ),
    PerformanceCase(
        "ai nmf housing",
        "test/test_ai_subschema.py::test_dataset_operator_pair[nmf-housing]",
        8.0,
    ),
    PerformanceCase(
        "object tricky pattern/value",
        "test/test_object.py::TestObjectSubtype::test_tricky6",
        8.0,
    ),
    PerformanceCase(
        "regex whitespace witness",
        "test/test_regex_language.py::test_regex_language_whitespace_fast_witness_avoids_fsm",
        4.0,
    ),
)
TOTAL_MAX_SECONDS = 25.0


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    threshold_multiplier = float(os.environ.get("SUBSCHEMA_PERF_MULTIPLIER", "1"))
    total_start = time.perf_counter()
    failures: list[str] = []

    for case in CASES:
        elapsed = _run_case(root, case)
        threshold = case.max_seconds * threshold_multiplier
        print(f"{case.name}: {elapsed:.3f}s (limit {threshold:.3f}s)")
        if elapsed > threshold:
            failures.append(
                f"{case.name} took {elapsed:.3f}s, above {threshold:.3f}s"
            )

    total_elapsed = time.perf_counter() - total_start
    total_threshold = TOTAL_MAX_SECONDS * threshold_multiplier
    print(f"total: {total_elapsed:.3f}s (limit {total_threshold:.3f}s)")
    if total_elapsed > total_threshold:
        failures.append(
            f"total took {total_elapsed:.3f}s, above {total_threshold:.3f}s"
        )

    if failures:
        raise SystemExit("\n".join(failures))


def _run_case(root: Path, case: PerformanceCase) -> float:
    start = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", case.nodeid],
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
    main()
