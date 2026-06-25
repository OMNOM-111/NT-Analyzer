"""Pytest bridge for the custom harness suites.

The legacy suites use a hand-rolled `@case` harness with a `main() -> int`
entry point rather than pytest-style `test_*` functions, so a bare
`pytest tests` used to collect nothing and exit non-zero with "no tests ran".

This module exposes one parametrized pytest test per suite that runs the
suite's `main()` and asserts it returned 0. Now `pytest tests -q` actually
exercises the whole suite. The standalone runner (`python -m tests`) and the
per-module form (`python -m tests.test_ops`) remain available too.
"""
from __future__ import annotations

import importlib

import pytest

SUITES = [
    "test_jobqueue",
    "test_ops",
    "test_performance",
    "test_runtime",
    "test_scc",
    "test_trading",
    "test_server_errors",
]


@pytest.mark.parametrize("suite", SUITES)
def test_legacy_suite(suite: str) -> None:
    mod = importlib.import_module(f"tests.{suite}")
    rc = int(mod.main())
    assert rc == 0, f"suite '{suite}' reported failures (exit code {rc})"
