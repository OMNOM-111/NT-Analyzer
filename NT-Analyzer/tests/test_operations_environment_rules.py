"""Operations answer to the environment, not only to the capability.

Capability answers "may this person". It does not answer "does this
environment do that at all", and while it was the whole gate every environment
offered the same buttons. The restart is the sharp case: unsupervised, this
process relaunches ``python -m app.server`` from the checkout, which on a
server would put whatever is on disk in place of a released artifact -- the
exact failure the release pipeline exists to prevent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import server as server_mod

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")


@pytest.fixture
def env(monkeypatch):
    def apply(development, supervised):
        monkeypatch.setattr(server_mod.runtime_env, "is_development", lambda: development)
        if supervised:
            monkeypatch.setenv("NTA_BACKEND_SUPERVISED", "1")
        else:
            monkeypatch.delenv("NTA_BACKEND_SUPERVISED", raising=False)
        return server_mod._operations_actions()
    return apply


# --------------------------------------------------------------------------- #
# Restart.
# --------------------------------------------------------------------------- #
def test_development_may_respawn_itself(env):
    restart = env(True, False)["restart"]
    assert restart["allowed"] is True
    assert restart["mode"] == "respawn"


def test_a_supervised_server_restarts_through_its_supervisor(env):
    restart = env(False, True)["restart"]
    assert restart["allowed"] is True
    assert restart["mode"] == "supervised"


def test_an_unsupervised_server_refuses_to_relaunch_itself(env):
    """The dangerous combination: a server with nothing owning restart ordering
    would respawn from the checkout rather than from the artifact it deployed."""
    restart = env(False, False)["restart"]
    assert restart["allowed"] is False
    assert restart["mode"] == "blocked"
    assert restart["reason"]
    assert "артефакт" in restart["reason"]


def test_the_refusal_is_enforced_and_not_merely_described():
    """A client that ignores the descriptor must still be refused."""
    source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    block = source[source.index("if is_server_restart:"):]
    block = block[:block.index("if is_cancel_job:")]
    assert '_operations_actions()["restart"]' in block
    assert "restart_not_supervised" in block
    assert block.index("restart[\"allowed\"]") < block.index("restarting")


# --------------------------------------------------------------------------- #
# The rest of the panel.
# --------------------------------------------------------------------------- #
def test_ai_memory_is_a_development_action(env):
    """Unloading AI Lab memory on a server acts on something that is not
    running there."""
    assert env(True, False)["ai_unload"]["allowed"] is True
    server_rule = env(False, True)["ai_unload"]
    assert server_rule["allowed"] is False
    assert server_rule["reason"]


def test_data_refreshes_are_allowed_everywhere(env):
    actions = env(False, True)
    assert actions["catalog_refresh"]["allowed"] is True
    assert actions["margin_refresh"]["allowed"] is True


def test_every_blocked_action_carries_a_reason(env):
    for development in (True, False):
        for supervised in (True, False):
            for name, rule in env(development, supervised).items():
                if not rule["allowed"]:
                    assert rule["reason"], name


def test_the_payload_carries_the_descriptor():
    source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    block = source[source.index("def _admin_operations_payload"):]
    block = block[:block.index("def _cabinet_payload")]
    assert 'payload["actions"] = _operations_actions()' in block


# --------------------------------------------------------------------------- #
# The panel shows the boundary instead of hiding it.
# --------------------------------------------------------------------------- #
def test_a_blocked_action_is_disabled_with_its_reason_shown():
    section = UI[UI.index("async function renderAdminOperationsInto"):]
    section = section[:section.index("function adminOverviewHtml")]
    assert "data.actions" in section
    assert "rule.allowed" in section
    assert "opNotes" in section


def test_a_disabled_action_is_not_wired_to_fire():
    section = UI[UI.index("async function renderAdminOperationsInto"):]
    section = section[:section.index("function adminOverviewHtml")]
    for handle in ("restart", "unload", "catalog", "margins"):
        assert "%s && !%s.disabled" % (handle, handle) in section, handle


def test_the_confirmation_says_which_kind_of_restart_it_is():
    section = UI[UI.index("async function renderAdminOperationsInto"):]
    section = section[:section.index("function adminOverviewHtml")]
    assert "supervised" in section
    assert "Супервизор" in section
