"""A platform secret must not travel inside anything we ship or keep.

Before the secrets store existed, every production promotion copied
production-app.env into a backup that was kept indefinitely. Three hundred and
fourteen copies of two live credentials accumulated that way, and nothing
noticed until somebody went looking. These tests are the guards that stop it
happening again -- at the release gate, in the promotion script, and in the
packaged archive.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROMOTE = ROOT / "tools" / "production_blue_green_promote.sh"


@pytest.fixture
def scan():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import release_static_scan
    finally:
        sys.path.pop(0)
    return release_static_scan


# --------------------------------------------------------------------------- #
# The release gate.
# --------------------------------------------------------------------------- #
def test_the_gate_knows_every_platform_secret_name(scan):
    from app import platform_secrets

    scanned = set(scan.PLATFORM_SECRET_NAMES)
    known = set(platform_secrets.KNOWN_SECRETS)
    missing = (known - scanned) - {"NTA_GOOGLE_CLIENT_ID"}
    assert not missing, f"the gate does not watch: {missing}"


def test_a_name_without_a_value_is_allowed(scan, tmp_path):
    """Documentation and the committed template carry names on purpose."""
    (tmp_path / "notes.md").write_text(
        "Set NTA_RESEND_API_KEY= in the environment file.\n", encoding="utf-8")
    (tmp_path / "template.env").write_text(
        "NTA_GOOGLE_CLIENT_SECRET=\n", encoding="utf-8")
    assert scan.scan_platform_secret_values(tmp_path) == []


def test_a_name_with_a_value_fails_the_release(scan, tmp_path):
    (tmp_path / "leaked.env").write_text(
        "NTA_RESEND_API_KEY=" + "x" * 30 + "\n", encoding="utf-8")
    findings = scan.scan_platform_secret_values(tmp_path)
    assert findings, "a value beside the name must fail"
    assert "NTA_RESEND_API_KEY" in findings[0]
    # The finding names the file and the line, never the value.
    assert "x" * 30 not in findings[0]


def test_an_exported_assignment_is_caught_too(scan, tmp_path):
    (tmp_path / "run.sh").write_text(
        "export NTA_GOOGLE_CLIENT_SECRET=" + "y" * 30 + "\n", encoding="utf-8")
    assert scan.scan_platform_secret_values(tmp_path)


def test_a_secrets_directory_inside_the_packaged_tree_fails(scan, tmp_path):
    (tmp_path / "secrets").mkdir()
    findings = scan.scan_platform_secret_values(tmp_path)
    assert any("secrets/" in f for f in findings), findings


def test_the_repository_ships_no_platform_secret_value(scan):
    assert scan.scan_platform_secret_values() == []


def test_the_containment_check_runs_in_the_release_scan(scan):
    src = (ROOT / "tools" / "release_static_scan.py").read_text(encoding="utf-8")
    dispatch = src[src.index('"secrets":'):]
    dispatch = dispatch[: dispatch.index("\n    }")]
    assert "scan_platform_secret_values" in dispatch


# --------------------------------------------------------------------------- #
# The promotion that made the copies.
# --------------------------------------------------------------------------- #
def test_promotion_refuses_a_config_that_carries_a_secret():
    text = PROMOTE.read_text(encoding="utf-8")
    assert "REFUSING" in text and "platform secret value" in text
    guard = text[: text.index('mkdir "$BACKUP"')]
    assert "NTA_GOOGLE_CLIENT_SECRET" in guard, \
        "the guard must run before the backup is created"
    assert "NTA_RESEND_API_KEY" in guard


def test_the_promotion_guard_matches_a_real_assignment():
    """Pin the pattern itself: a guard that never fires protects nothing."""
    text = PROMOTE.read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("if grep -qE"))
    pattern = line.split("'")[1]
    compiled = re.compile(
        pattern.replace("[^[:space:]#]", r"[^\s#]").replace("[[:space:]]", r"\s"))
    assert compiled.search("NTA_RESEND_API_KEY=" + "a" * 30)
    assert compiled.search("export NTA_GOOGLE_CLIENT_SECRET=" + "b" * 30)
    # A secret that has not been migrated yet still lives in this config, and
    # guarding it here would block every release on a false positive.
    assert not compiled.search("NTA_TELEGRAM_BOT_TOKEN=" + "c" * 30)
    # An empty assignment is configuration, not a credential.
    assert not compiled.search("NTA_RESEND_API_KEY=")
    assert not compiled.search("# NTA_RESEND_API_KEY=set-me")


def test_the_guard_sits_before_anything_is_copied():
    text = PROMOTE.read_text(encoding="utf-8")
    assert text.index("REFUSING: $PROD_ENV carries a platform secret") < \
        text.index('install -o stratforge -g root -m 0600 "$PROD_ENV"')


@pytest.mark.skipif(shutil.which("bash") is None,
                    reason="no shell on this runner")
def test_the_promotion_script_is_valid_shell():
    result = subprocess.run([shutil.which("bash"), "-n", str(PROMOTE)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
