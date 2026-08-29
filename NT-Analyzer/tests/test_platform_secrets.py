"""The platform-secret contract, pinned.

Three kinds of credential exist and the rules differ: platform secrets the
deployment owns, BYOK secrets a person brings to their workspace, and
non-secret configuration. This file is about the first kind, and about the
one boundary that matters most -- a value must never leave the store.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from app import platform_secrets as ps


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv(ps._DIR_ENV, str(tmp_path / "secrets"))
    for name in ps.KNOWN_SECRETS:
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "secrets"


# --------------------------------------------------------------------------- #
# Never in the repository.
# --------------------------------------------------------------------------- #
def test_a_secrets_directory_inside_the_checkout_is_refused(monkeypatch):
    """One `git add -A` away from publishing live credentials. Refused, not
    warned about."""
    monkeypatch.setenv(ps._DIR_ENV, str(ROOT / "data" / "secrets"))
    with pytest.raises(ps.PlatformSecretError) as caught:
        ps.directory()
    assert "репозитор" in str(caught.value).lower()


def test_the_committed_example_carries_names_and_no_values():
    example = ROOT / "secrets.example.env"
    assert example.is_file()
    for line in example.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        assert name.strip() in ps.KNOWN_SECRETS, name
        assert value.strip() == "", f"{name} must not carry a value"


# --------------------------------------------------------------------------- #
# Environments never share.
# --------------------------------------------------------------------------- #
def test_canary_and_production_cannot_read_each_other(store):
    ps.replace("NTA_RESEND_API_KEY", "canary-value-aaaaaaaa",
               actor="owner", environment="canary")
    ps.replace("NTA_RESEND_API_KEY", "production-value-bbbbbbbb",
               actor="owner", environment="production")

    assert ps.get("NTA_RESEND_API_KEY", "canary") == "canary-value-aaaaaaaa"
    assert ps.get("NTA_RESEND_API_KEY", "production") == "production-value-bbbbbbbb"
    assert ps.path_for("canary") != ps.path_for("production")

    canary_text = ps.path_for("canary").read_text(encoding="utf-8")
    assert "production-value" not in canary_text


def test_an_unknown_name_is_refused_rather_than_silently_empty(store):
    with pytest.raises(ps.PlatformSecretError):
        ps.get("NTA_TYPO_NOT_A_SECRET")
    with pytest.raises(ps.PlatformSecretError):
        ps.replace("NTA_TYPO_NOT_A_SECRET", "x" * 20, actor="owner")


# --------------------------------------------------------------------------- #
# Fail closed.
# --------------------------------------------------------------------------- #
def test_a_missing_required_secret_refuses_by_name(store):
    with pytest.raises(ps.PlatformSecretMissing) as caught:
        ps.require("NTA_RESEND_API_KEY", "production")
    message = str(caught.value)
    assert "NTA_RESEND_API_KEY" in message
    assert "production" in message


def test_missing_required_lists_what_the_environment_lacks(store):
    assert set(ps.missing_required("production")) == {
        "NTA_GOOGLE_CLIENT_SECRET", "NTA_RESEND_API_KEY"}
    ps.replace("NTA_RESEND_API_KEY", "value-aaaaaaaaaa",
               actor="owner", environment="production")
    assert ps.missing_required("production") == ["NTA_GOOGLE_CLIENT_SECRET"]


def test_an_empty_replacement_is_refused(store):
    with pytest.raises(ps.PlatformSecretError):
        ps.replace("NTA_RESEND_API_KEY", "   ", actor="owner")


# --------------------------------------------------------------------------- #
# Atomic replacement and rollback.
# --------------------------------------------------------------------------- #
def test_a_bad_value_can_be_rolled_back_without_the_provider(store):
    ps.replace("NTA_RESEND_API_KEY", "good-value-aaaaaaaa",
               actor="owner", environment="production")
    ps.replace("NTA_RESEND_API_KEY", "bad-value-bbbbbbbbb",
               actor="owner", environment="production")
    assert ps.get("NTA_RESEND_API_KEY", "production") == "bad-value-bbbbbbbbb"

    ps.rollback("NTA_RESEND_API_KEY", actor="owner", environment="production")
    assert ps.get("NTA_RESEND_API_KEY", "production") == "good-value-aaaaaaaa"


def test_replacement_leaves_no_partial_file(store):
    ps.replace("NTA_RESEND_API_KEY", "value-aaaaaaaaaa",
               actor="owner", environment="production")
    path = ps.path_for("production")
    assert path.is_file()
    assert not path.with_name(path.name + ".tmp").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_a_world_readable_store_is_refused(store):
    ps.replace("NTA_RESEND_API_KEY", "value-aaaaaaaaaa",
               actor="owner", environment="production")
    path = ps.path_for("production")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.chmod(0o644)
    with pytest.raises(ps.PlatformSecretError):
        ps.get("NTA_RESEND_API_KEY", "production")


# --------------------------------------------------------------------------- #
# The value never leaves.
# --------------------------------------------------------------------------- #
def test_status_carries_no_value_and_no_fragment_of_one(store):
    secret = "super-secret-value-1234567890"
    ps.replace("NTA_RESEND_API_KEY", secret, actor="owner",
               environment="production")
    rendered = json.dumps(ps.status("production"), ensure_ascii=False)
    assert secret not in rendered
    # Not even the tail: a fingerprint is a product decision for BYOK keys,
    # not something a platform secret status may leak by default.
    assert secret[-4:] not in rendered
    row = next(r for r in ps.status("production")["secrets"]
               if r["name"] == "NTA_RESEND_API_KEY")
    assert row["configured"] is True
    assert row["last_rotated_at_utc"]


def test_the_audit_records_who_and_when_but_never_what(store):
    secret = "another-secret-value-0987654321"
    ps.replace("NTA_GOOGLE_CLIENT_SECRET", secret, actor="owner:1647145559",
               environment="canary")
    rows = ps.audit("canary")
    assert rows and rows[-1]["name"] == "NTA_GOOGLE_CLIENT_SECRET"
    assert rows[-1]["environment"] == "canary"
    assert rows[-1]["actor"] == "owner:1647145559"
    assert rows[-1]["changed_at_utc"]
    assert secret not in json.dumps(rows, ensure_ascii=False)
    assert secret not in ps._audit_path().read_text(encoding="utf-8")


def test_replace_returns_status_not_the_value(store):
    secret = "returned-value-check-123456"
    out = ps.replace("NTA_RESEND_API_KEY", secret, actor="owner",
                     environment="production")
    assert secret not in json.dumps(out, ensure_ascii=False)


def test_redaction_scrubs_a_configured_value_out_of_any_text(store):
    secret = "leaky-secret-value-abcdefgh"
    ps.replace("NTA_RESEND_API_KEY", secret, actor="owner",
               environment="production")
    message = f"Resend rejected the request using key {secret} at 12:00"
    scrubbed = ps.redact(message)
    assert secret not in scrubbed
    assert "***redacted***" in scrubbed
    # Ordinary text is untouched.
    assert ps.redact("nothing to hide here") == "nothing to hide here"


def test_redaction_leaves_short_strings_alone(store):
    """Redacting a three-character value would turn logs into asterisks."""
    assert ps.redact("abc") == "abc"


def test_no_module_returns_a_platform_secret_through_an_api():
    """A grep-level guard: the reading helpers must not be wired straight into
    a response body."""
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    for forbidden in ("platform_secrets.get(", "platform_secrets.require("):
        assert forbidden not in server, forbidden


# --------------------------------------------------------------------------- #
# The scanner that blocks a release.
# --------------------------------------------------------------------------- #
def test_the_release_scanner_knows_our_providers_credential_shapes():
    """A scanner that only ever says "clean" is worse than none.

    The literals are assembled rather than written out, because the scanner
    quite correctly refuses a repository that contains them.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import release_static_scan as scan
    finally:
        sys.path.pop(0)

    labels = {label for label, _ in scan.SECRET_PATTERNS}
    assert {"google_client_secret", "resend_api_key", "anthropic_key",
            "aws_access_key", "private_key"} <= labels

    samples = {
        "google_client_secret": "GOCSPX-" + "a" * 28,
        "resend_api_key": "re_" + "b" * 30,
        "anthropic_key": "sk-ant-" + "c" * 40,
        "aws_access_key": "AKIA" + "D" * 16,
        "private_key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    }
    for label, value in samples.items():
        pattern = dict(scan.SECRET_PATTERNS)[label]
        assert pattern.search(value), label


def test_a_value_in_the_committed_template_fails_the_release(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import release_static_scan as scan
    finally:
        sys.path.pop(0)

    assert scan.scan_secret_template() == [], "the real template must be clean"

    fake_root = tmp_path
    (fake_root / "secrets.example.env").write_text(
        "NTA_RESEND_API_KEY=oops-a-real-one" + chr(10), encoding="utf-8")
    monkeypatch.setattr(scan, "ROOT", fake_root)
    assert scan.scan_secret_template(), "a value in the template must fail"


def test_the_repository_carries_no_credentials_right_now():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "release_static_scan.py"),
         "--scan", "secrets"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stdout


def test_the_secret_scan_blocks_the_release_in_ci():
    workflow = (ROOT.parent / ".github" / "workflows"
                / "next-architecture-ci.yml").read_text(encoding="utf-8")
    assert "release_static_scan.py --scan all" in workflow


# --------------------------------------------------------------------------- #
# The owner surface.
# --------------------------------------------------------------------------- #
def _server_source() -> str:
    return (ROOT / "app" / "server.py").read_text(encoding="utf-8")


def test_there_is_no_route_that_reveals_a_platform_secret():
    """No "Show secret" button, and nothing behind one either."""
    src = _server_source()
    block = src[src.index("def _platform_secrets_post("):]
    block = block[: block.index("def _releases_post(")]
    assert "platform_secrets.get(" not in block
    assert "platform_secrets.require(" not in block
    assert '"/api/admin/platform-secrets/reveal"' not in src
    assert '"/api/admin/platform-secrets/show"' not in src


def test_reading_status_is_owner_only():
    src = _server_source()
    block = src[src.index('if path == "/api/admin/platform-secrets":'):]
    block = block[: block.index('if path == "/api/admin/connectors":')]
    assert "self._require_owner_actor()" in block


def test_mutation_requires_owner_and_a_step_up_with_no_exemption():
    """Holding the owner session is necessary and deliberately not enough."""
    src = _server_source()
    block = src[src.index("def _platform_secrets_post("):]
    block = block[: block.index("def _releases_post(")]
    assert "self._require_owner_actor()" in block
    assert "allow_owner_exempt=False" in block
    assert "ACTION_REPLACE_PLATFORM_SECRET" in block


def test_a_failure_message_cannot_carry_the_value_that_caused_it():
    src = _server_source()
    block = src[src.index("def _platform_secrets_post("):]
    block = block[: block.index("def _releases_post(")]
    assert "platform_secrets.redact(str(exc))" in block


def test_the_strict_step_up_really_skips_the_owner_exemption():
    from app import release_center

    src = (ROOT / "app" / "release_center.py").read_text(encoding="utf-8")
    fn = src[src.index("def _require_step_up("):]
    fn = fn[: fn.index("\ndef ", 10)]
    assert "if allow_owner_exempt and _is_owner(actor):" in fn
    assert release_center.ACTION_REPLACE_PLATFORM_SECRET in \
        release_center.STEP_UP_ACTIONS


# --------------------------------------------------------------------------- #
# The categories must not be mixed.
# --------------------------------------------------------------------------- #
def test_a_users_provider_key_is_not_a_platform_secret():
    """A person's own AI key belongs to their workspace, not to the platform
    store. Nothing in the platform registry may name a BYOK provider key."""
    for name in ps.KNOWN_SECRETS:
        assert "OPENAI" not in name, name
        assert "ANTHROPIC" not in name, name
        assert "GEMINI" not in name, name


def test_a_provider_key_is_never_returned_after_it_is_saved():
    """configure_provider takes the full value once and answers with status."""
    from app.ai_lab import cloud_agents

    src = (ROOT / "app" / "ai_lab" / "cloud_agents.py").read_text(encoding="utf-8")
    fn = src[src.index("def configure_provider("):]
    fn = fn[: fn.index("\ndef ", 10)]
    assert "return status()" in fn
    assert "return key" not in fn
    assert "api_key" not in fn.split("return status()")[1] if \
        "return status()" in fn else True
