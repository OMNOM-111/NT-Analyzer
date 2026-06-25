"""Unified test runner for the custom (non-pytest) harness modules.

Usage from the NT-Analyzer/ root:

    python -m tests              # run every suite, aggregate exit code
    python -m tests test_ops     # run a subset by module name

Each suite module exposes `main() -> int` (0 == all passed). This runner
executes them in-process, prints a combined summary, and exits non-zero if
ANY suite reported a failure — so CI cannot get a false green like
`pytest` previously did (it collected 0 tests and still exited 1).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUITES = [
    "test_jobqueue",
    "test_ops",
    "test_performance",
    "test_runtime",
    "test_scc",
    "test_trading",
    "test_server_errors",
    "test_ai_lab",
    "test_rerun_compare",
    "test_mismatch_report",
    "test_data_fingerprint",
    "test_final_decision",
]


def run(selected: list[str] | None = None) -> int:
    names = selected or SUITES
    results: list[tuple[str, int]] = []
    for name in names:
        mod = importlib.import_module(f"tests.{name}")
        print(f"\n===================== {name} =====================")
        try:
            rc = int(mod.main())
        except SystemExit as e:  # some mains call sys.exit indirectly
            rc = int(e.code or 0)
        results.append((name, rc))

    print("\n========================================================")
    print("SUITE SUMMARY")
    failed = 0
    for name, rc in results:
        status = "PASS" if rc == 0 else "FAIL"
        if rc != 0:
            failed += 1
        print(f"  {status}  {name}")
    print(f"\n{len(results) - failed}/{len(results)} suites passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    sys.exit(run(args or None))
