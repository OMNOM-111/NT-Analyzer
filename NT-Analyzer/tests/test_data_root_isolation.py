"""Tests get their own data directory, and never the live one.

The suite used to read and write <project>/data -- the same directory the
running LOCAL server writes. Two concurrent pytest runs (which is what CI does:
ci.yml/python-tests and next-architecture-ci/tests(windows-self-hosted) both run
the full suite on the one self-hosted runner) therefore performed atomic
`.tmp` -> rename writes into the same files as each other and as the live
server. On Windows a rename onto a file another process holds fails with
WinError 5/32; that exception escapes inside an HTTP handler thread after the
response line is already out, so nothing safe can be sent and the connection
closes mid-response. The waiting client gets WSAECONNABORTED (10053) instead of
its status -- observed as three different "flaky" tests across four CI runs,
never the same one twice.

A single session-wide root fixed the cross-process half but not the cross-test
half: one file wrote a DPAPI-encrypted workspaces store where the next expected
JSON, so a test passed alone and failed in the suite. Hence one root per test.

The decisive check is not here but in conftest, which compares every live data
file before and after the whole session and fails the run if anything changed.
Tracked baselines needed by tests are copied into their disposable roots. The
tests here cover the mechanism; the session check covers the outcome.
"""
from __future__ import annotations

import os
from pathlib import Path

from app import runtime_env

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFTEST = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")
LEGACY_RUNNER = (Path(__file__).parent / "__main__.py").read_text(encoding="utf-8")
CI = (PROJECT_ROOT.parent / ".github" / "workflows" / "ci.yml").read_text(
    encoding="utf-8")
NEXT_CI = (PROJECT_ROOT.parent / ".github" / "workflows" /
           "next-architecture-ci.yml").read_text(encoding="utf-8")


def test_the_session_checks_the_live_directory_rather_than_trusting_the_setup():
    """The outcome is verified, not assumed."""
    assert "def pytest_sessionstart" in CONFTEST
    assert "_live_manifest()" in CONFTEST
    assert "session.exitstatus = 1" in CONFTEST


def test_the_live_check_has_no_known_writer_exemptions():
    assert "_KNOWN_LIVE_WRITERS" not in CONFTEST
    assert '"governance-rendered" in path.as_posix()' not in CONFTEST


def test_a_development_test_never_resolves_to_the_live_directory(monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "development")
    root = runtime_env.data_root().resolve()
    assert root != (PROJECT_ROOT / "data").resolve()
    assert PROJECT_ROOT not in root.parents, root


def test_a_production_test_never_resolves_to_the_live_directory(monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "production")
    root = runtime_env.data_root().resolve()
    assert root != (PROJECT_ROOT / "data").resolve()
    assert PROJECT_ROOT not in root.parents, root


def test_the_development_root_is_writable():
    root = Path(os.environ["NTA_STAGING_DATA_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    probe = root / "isolation-probe.txt"
    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"
    probe.unlink()


def test_each_test_gets_its_own_root(isolated_data_root):
    current = Path(isolated_data_root).resolve()
    assert Path(os.environ["NTA_STAGING_DATA_ROOT"]).resolve() == current
    production = Path(os.environ["NTA_DATA_ROOT"]).resolve()
    assert production.name == "data"
    assert production.parent == current.parent
    assert production != current
    test_each_test_gets_its_own_root._seen = current


def test_a_sibling_test_does_not_share_that_root(isolated_data_root):
    previous = getattr(test_each_test_gets_its_own_root, "_seen", None)
    assert previous is not None, "expected the preceding test to have recorded a root"
    assert Path(isolated_data_root).resolve() != previous


def test_writes_from_one_test_are_invisible_to_the_next(isolated_data_root):
    marker = Path(isolated_data_root) / "leak-check.txt"
    assert not marker.exists(), "a previous test's file is visible here"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("written", encoding="utf-8")


def test_the_previous_tests_marker_did_not_follow_us(isolated_data_root):
    assert not (Path(isolated_data_root) / "leak-check.txt").exists()


def test_the_conftest_takes_the_fallback_variable_not_the_preferred_one():
    """Claiming STRATFORGE_DEVELOPMENT_DATA_ROOT would silently override the
    tests that manage roots on purpose, which is what test_staging_isolation
    exists to check."""
    assert '"NTA_STAGING_DATA_ROOT"' in CONFTEST
    assert 'os.environ["STRATFORGE_DEVELOPMENT_DATA_ROOT"]' not in CONFTEST


def test_the_session_root_is_unique_per_process():
    """Two concurrent runs must not share it, or the collision simply moves."""
    assert "os.getpid()" in CONFTEST
    assert "uuid" in CONFTEST


def test_ci_correctness_does_not_depend_on_workflow_serialization():
    assert "stratforge-self-hosted-suite" not in CI
    assert "stratforge-self-hosted-suite" not in NEXT_CI


def test_legacy_runner_installs_two_disposable_roots_before_suite_imports():
    install = LEGACY_RUNNER.index('os.environ["NTA_DATA_ROOT"] =')
    suite_import = LEGACY_RUNNER.index('importlib.import_module(f"tests.{name}")')
    assert install < suite_import
    assert 'os.environ["NTA_STAGING_DATA_ROOT"] =' in LEGACY_RUNNER
    assert 'shutil.rmtree(test_root, ignore_errors=True)' in LEGACY_RUNNER
