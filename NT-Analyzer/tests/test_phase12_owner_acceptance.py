"""Phase 12 (owner acceptance) regression tests.

Covers the local, honest behaviours added for the owner-acceptance pass:

* runtime_env: Development-only QA (test-auth + impersonation) default-on, and
  impossible in Canary/Production.
* test_auth: the persona PRESETS (developer / ordinary / personal_nt / shared_nt)
  and the developer full-team capability.
* agent_allocation: owner-grantable ``agents.team.full`` capability, the shared
  owner-training single-coordinator default, the granted full team, and the
  (architecture-only) display config hook.
* security_devices: the ``online`` signal derived only from live sessions.
* release_center: the send-free update-notification preview.

These are all pure/local contracts — no external Telegram/Google/infrastructure
is required, and none is faked.
"""
from __future__ import annotations

import pytest

from app import agent_allocation, release_center, runtime_env, security_devices, test_auth


# --------------------------------------------------------------------------- #
# runtime_env: Development-only QA defaults.
# --------------------------------------------------------------------------- #
def _set_env(monkeypatch, env: str) -> None:
    for key in ("DEPLOYMENT_ENV", "STRATFORGE_ENV", "NTA_APP_ENV", "NTA_ENV"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEPLOYMENT_ENV", env)


def test_test_auth_and_impersonation_default_on_in_development(monkeypatch):
    _set_env(monkeypatch, "development")
    monkeypatch.delenv("NTA_ENABLE_TEST_AUTH", raising=False)
    monkeypatch.delenv("NTA_ENABLE_IMPERSONATION", raising=False)
    assert runtime_env.is_development() is True
    assert runtime_env.test_auth_enabled() is True
    assert runtime_env.impersonation_enabled() is True


def test_qa_defaults_can_be_explicitly_disabled(monkeypatch):
    _set_env(monkeypatch, "development")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "0")
    monkeypatch.setenv("NTA_ENABLE_IMPERSONATION", "off")
    assert runtime_env.test_auth_enabled() is False
    assert runtime_env.impersonation_enabled() is False


@pytest.mark.parametrize("env", ["canary", "production"])
def test_qa_impossible_outside_development(monkeypatch, env):
    _set_env(monkeypatch, env)
    # Even if a caller sets the enable flags, they must never work off-dev.
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_ENABLE_IMPERSONATION", "1")
    assert runtime_env.test_auth_enabled() is False
    assert runtime_env.impersonation_enabled() is False


# --------------------------------------------------------------------------- #
# test_auth: Phase 12 personas.
# --------------------------------------------------------------------------- #
def test_presets_include_owner_acceptance_personas():
    presets = test_auth.PRESETS
    for key in ("developer", "ordinary", "personal_nt", "shared_nt"):
        assert key in presets
    assert presets["developer"].get("capabilities") == ["agents.team.full"]
    assert presets["personal_nt"].get("nt_mode") == "personal"
    assert presets["shared_nt"].get("nt_mode") == "shared"
    assert presets["shared_nt"].get("role") == "read_only"


# --------------------------------------------------------------------------- #
# agent_allocation: owner-grantable full-team capability.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def grants(tmp_path, monkeypatch):
    path = tmp_path / "team_capabilities.json"
    monkeypatch.setattr(agent_allocation, "_grants_path", lambda: path)
    return path


def _shared_context(**extra):
    context = {"is_owner": False, "active_workspace": {
        "workspace_id": "ws_owner_training", "kind": "owner_training", "uses_owner_runtime": True}}
    context.update(extra)
    return context


def test_grant_capability_roundtrip(grants):
    assert agent_allocation.has_team_capability(500) is False
    out = agent_allocation.grant_team_capability(500, granted_by=999)
    assert out["ok"] is True
    assert agent_allocation.TEAM_FULL_CAPABILITY in out["capabilities"]
    assert agent_allocation.has_team_capability(500) is True
    agent_allocation.revoke_team_capability(500)
    assert agent_allocation.has_team_capability(500) is False


def test_grant_requires_user_id(grants):
    with pytest.raises(ValueError):
        agent_allocation.grant_team_capability(0)


def test_shared_default_single_coordinator(grants):
    alloc = agent_allocation.resolve_allocation(_shared_context())
    assert alloc["team_kind"] == agent_allocation.TEAM_OWNER_TRAINING
    assert alloc["agents"] == [agent_allocation.OWNER_TRAINING_COORDINATOR]
    assert alloc["administrative"] is False


def test_context_capability_unlocks_full_team(grants):
    # A developer/persona whose request context carries the capability.
    alloc = agent_allocation.resolve_allocation(
        _shared_context(capabilities=[agent_allocation.TEAM_FULL_CAPABILITY]))
    assert alloc["team_kind"] == agent_allocation.TEAM_GRANTED_FULL
    assert alloc["administrative"] is False
    assert alloc["granted_capability"] == agent_allocation.TEAM_FULL_CAPABILITY
    assert list(alloc["agents"]) == list(agent_allocation.PERSONAL_TEAM_AGENTS)


def test_persisted_grant_unlocks_full_team(grants):
    agent_allocation.grant_team_capability(777, granted_by=999)
    alloc = agent_allocation.resolve_allocation(_shared_context(user_id=777))
    assert alloc["team_kind"] == agent_allocation.TEAM_GRANTED_FULL
    # Revoking drops the user back to the single coordinator.
    agent_allocation.revoke_team_capability(777)
    alloc2 = agent_allocation.resolve_allocation(_shared_context(user_id=777))
    assert alloc2["team_kind"] == agent_allocation.TEAM_OWNER_TRAINING


def test_owner_keeps_full_admin_team(grants):
    context = {"is_owner": True, "active_workspace": {
        "workspace_id": "ws_owner", "kind": "owner_training", "uses_owner_runtime": True}}
    alloc = agent_allocation.resolve_allocation(context)
    assert alloc["team_kind"] == agent_allocation.TEAM_OWNER
    assert alloc["administrative"] is True


def test_agent_display_config_is_read_only_hook():
    cfg = agent_allocation.agent_display_config()
    assert cfg["editable"] is False
    assert "owner_team" in cfg["roster"]
    assert "personal_team" in cfg["roster"]
    assert cfg["overrides"] == {}


# --------------------------------------------------------------------------- #
# security_devices: honest ``online`` signal.
# --------------------------------------------------------------------------- #
def _device(device_id: str, status: str = "trusted", device_type: str = "desktop"):
    return {
        "device_id": device_id, "device_type": device_type, "display_name": "Dev",
        "status": status, "first_seen_at_utc": "2025-01-01T00:00:00Z",
        "last_seen_at_utc": "2025-01-02T00:00:00Z",
    }


def test_public_device_online_only_when_live_and_active():
    active = frozenset({"dev-1"})
    online = security_devices._public_device(_device("dev-1", "trusted"), active)
    assert online["online"] is True
    offline = security_devices._public_device(_device("dev-2", "trusted"), active)
    assert offline["online"] is False


def test_public_device_revoked_never_online():
    active = frozenset({"dev-3"})
    revoked = security_devices._public_device(_device("dev-3", "revoked"), active)
    assert revoked["online"] is False


def test_active_device_ids_ignores_revoked_and_expired():
    now = security_devices._now()
    doc = {"sessions": [
        {"trusted_device_id": "live-1", "expires_at": now + 3600, "revoked": False},
        {"trusted_device_id": "revoked-1", "expires_at": now + 3600, "revoked": True},
        {"trusted_device_id": "expired-1", "expires_at": now - 10, "revoked": False},
        {"trusted_device_id": "", "expires_at": now + 3600, "revoked": False},
    ]}
    ids = security_devices._active_device_ids(doc)
    assert "live-1" in ids
    assert "revoked-1" not in ids
    assert "expired-1" not in ids
    assert "" not in ids


# --------------------------------------------------------------------------- #
# release_center: send-free update-notification preview.
# --------------------------------------------------------------------------- #
def test_notification_preview_is_send_free_and_complete():
    out = release_center.notification_preview(app_version="0.10.0-dev.9")
    kinds = {p["kind"] for p in out["previews"]}
    assert {"warn_5m", "warn_60s", "deploy_successful"} <= kinds
    # No real send is ever available in this phase.
    assert out["real_send_available"] is False
    assert "инфраструктур" in out["note"].lower()
    # The version label is rendered into the messages.
    warn5 = next(p for p in out["previews"] if p["kind"] == "warn_5m")
    assert "0.10.0-dev.9" in warn5["message"]
