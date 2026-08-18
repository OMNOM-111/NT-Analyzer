"""The Admin panel as a place to work rather than a directory to search.

Fourteen entries across five groups meant finding the tool was its own task.
What merged here merged because the two halves only ever answered one question
together; what left Admin left because it was never an operator tool. Each
check below states which of those it is protecting.
"""
from __future__ import annotations

from pathlib import Path

from app import server as server_mod

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")


def _ids():
    return [m["id"] for m in server_mod._ADMIN_MODULES]


def _groups():
    return [m.get("group", "") for m in server_mod._ADMIN_MODULES]


# --------------------------------------------------------------------------- #
# Shape of the navigation.
# --------------------------------------------------------------------------- #
def test_the_panel_stays_small_enough_to_read():
    """Not a hard cap on features -- a cap on how long the list may get before
    someone has to consolidate again."""
    assert len(_ids()) <= 12, _ids()
    assert len(set(g for g in _groups() if g)) <= 4


def test_every_module_below_the_first_belongs_to_a_group():
    modules = server_mod._ADMIN_MODULES
    assert modules[0]["group"] == ""
    assert all(m["group"] for m in modules[1:])


def test_module_ids_are_unique():
    assert len(_ids()) == len(set(_ids()))


def test_related_modules_sit_in_the_same_group():
    by_id = {m["id"]: m["group"] for m in server_mod._ADMIN_MODULES}
    access = {by_id["users"], by_id["requests"], by_id["invites"], by_id["subscriptions"]}
    assert len(access) == 1, "access and membership belong together"
    assert by_id["connectors"] == by_id["operations"]


# --------------------------------------------------------------------------- #
# Monitoring folded into Users and sessions.
# --------------------------------------------------------------------------- #
def test_monitoring_is_no_longer_its_own_entry():
    """Who is online and which sessions exist are facts about exactly the people
    the user list is about."""
    assert "monitoring" not in _ids()


def test_the_monitoring_id_opens_the_tab_it_became():
    assert "renderUsersAndSessionsInto(node, 'monitoring')" in UI


def test_the_merged_module_keeps_both_views():
    section = UI[UI.index("async function renderUsersAndSessionsInto"):]
    section = section[:section.index("\n  async function renderAdminModule")]
    assert "renderUsersInto" in section
    assert "renderMonitoringInto" in section


def test_a_delegated_admin_does_not_get_the_owner_monitoring_tab():
    """Monitoring is owner-only; offering a tab that answers 403 reads as a
    fault rather than as a boundary."""
    section = UI[UI.index("async function renderUsersAndSessionsInto"):]
    section = section[:section.index("\n  async function renderAdminModule")]
    assert "if (!owner) return renderDelegatedUsersInto(node);" in section


# --------------------------------------------------------------------------- #
# Subscriptions and grants: administrative on one side of the boundary only.
# --------------------------------------------------------------------------- #
def test_administrative_subscriptions_stay_owner_only_in_admin():
    entry = next(m for m in server_mod._ADMIN_MODULES if m["id"] == "subscriptions")
    assert entry.get("owner_only") is True


def test_the_plans_view_is_told_which_audience_it_serves():
    """The same endpoint feeds a member's own plan and the switchboard for
    everyone's. Which one is rendered must not be inferred from who is asking."""
    assert "renderPlansInto(node, await API.http.authMe(), 'admin')" in UI
    assert "renderPlansInto(cb, me, 'self')" in UI


def test_the_admin_scope_refuses_a_non_owner_rather_than_falling_back():
    section = UI[UI.index("async function renderPlansInto"):]
    section = section[:section.index("const isOwner", 10) + 400]
    assert "scope === 'admin' && !isOwner" in section


# --------------------------------------------------------------------------- #
# Connector onboarding.
# --------------------------------------------------------------------------- #
def test_onboarding_leads_with_the_three_real_steps():
    section = UI[UI.index("function connectorEnrollHtml"):]
    section = section[:section.index("async function connectorMintPairing")]
    assert "Скачать Connector" in section
    assert "Установить и открыть в NinjaTrader" in section
    assert "Авторизовать" in section
    # The code is the fallback, and it sits after the steps.
    assert section.index("conn-steps") < section.index("conn-manual")


def test_the_one_time_code_is_a_fallback_not_the_greeting():
    section = UI[UI.index("function connectorEnrollHtml"):]
    section = section[:section.index("async function connectorMintPairing")]
    manual = section[section.index("conn-manual"):]
    assert "<details" in section[:section.index("conn-manual")] or "details" in manual
    assert "вручную" in section


def test_authorising_hands_the_grant_to_the_program_not_to_the_person():
    """A code nobody has to read is a code nobody can leak."""
    section = UI[UI.index("function wireConnectorEnroll"):]
    section = section[:section.index("async function renderConnectorsInto")]
    assert "pairing_uri" in section
    authorize = section[:section.index("conn-enroll-start")]
    assert "res.code" not in authorize


def test_a_missing_installer_is_stated_rather_than_linked():
    """A download button that goes nowhere teaches the reader that the page
    lies."""
    section = UI[UI.index("function connectorInstallerHtml"):]
    section = section[:section.index("function connectorEnrollHtml")]
    assert "disabled" in section
    assert "installer.message" in section or "message" in section


def test_the_panel_is_told_whether_a_signed_package_exists():
    from app import connector_protocol

    status = connector_protocol.installer_status()
    assert "download_url" in status
    assert status["message"], "an absent installer must carry its reason"
