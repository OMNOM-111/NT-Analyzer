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
import os
import shutil
import sys
import tempfile
import uuid
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
    "test_strategy_safety",
]


def run(selected: list[str] | None = None) -> int:
    # This runner does not load pytest's conftest, so it must establish the
    # same fail-closed boundary before importing any suite/app module. The two
    # roots are siblings because runtime startup deliberately rejects nested
    # Production/Development data roots.
    test_root = Path(tempfile.gettempdir()) / (
        f"stratforge-legacy-tests-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    production_root = test_root / "production-data"
    development_root = test_root / "development-data"
    production_root.mkdir(parents=True)
    development_root.mkdir(parents=True)
    previous = {
        "NTA_DATA_ROOT": os.environ.get("NTA_DATA_ROOT"),
        "NTA_STAGING_DATA_ROOT": os.environ.get("NTA_STAGING_DATA_ROOT"),
    }
    os.environ["NTA_DATA_ROOT"] = str(production_root)
    os.environ["NTA_STAGING_DATA_ROOT"] = str(development_root)

    try:
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
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(test_root, ignore_errors=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    sys.exit(run(args or None))
