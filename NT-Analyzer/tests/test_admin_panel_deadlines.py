"""Every panel that puts up a spinner owes an answer.

A request with no deadline can leave a spinner running forever. To the reader
that is indistinguishable from a slow network, so they wait -- and the panel
never tells them it has stopped waiting. One panel had a bespoke deadline and
seven did not; this pins the shared one across all of them.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
SERVER = (ROOT / "app" / "server.py").read_text(encoding="utf-8")

# The panels an operator waits on, and the call each one is bounded by.
PANELS = {
    "renderUsersInto": "authUsers",
    "renderInvitesInto": "billingPlans",
    "renderRequestsInto": "ownerPaymentRequests",
    "renderJournalInto": "ownerJournal",
    "renderMonitoringInto": "ownerSupportMonitoring",
    "renderConnectorsInto": "adminConnectors",
    "renderPipelineInto": "adminPipeline",
    "renderAdminOperationsInto": "adminOperations",
}


def _call(text, fn):
    """The full argument list of `fn(...)`, matched by parentheses rather than
    by commas -- the arguments contain commas of their own."""
    start = text.index(fn + "(") + len(fn)
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError("unbalanced call to " + fn)


def _body(name):
    start = UI.index("async function %s(" % name)
    nxt = re.search(r"\n  (?:async )?function ", UI[start + 10:])
    return UI[start:start + 10 + (nxt.start() if nxt else len(UI))]


def test_the_deadline_helper_exists_and_is_bounded():
    assert "function withDeadline" in UI
    match = re.search(r"const PANEL_DEADLINE_MS = (\d+);", UI)
    assert match, "the default deadline should be a named constant"
    assert 3000 <= int(match.group(1)) <= 30000


def test_every_operator_panel_bounds_its_request():
    missing = [name for name in PANELS if "withDeadline" not in _body(name)]
    assert not missing, missing


def test_the_bounded_call_is_the_one_the_panel_waits_on():
    for name, call in PANELS.items():
        body = _body(name)
        deadline = body[body.index("withDeadline"):]
        assert call in deadline[:400], (name, call)


def test_the_timeout_names_what_did_not_answer():
    """"Ошибка" sends the reader looking; naming the source ends the search."""
    for name in PANELS:
        body = _body(name)
        call = _call(body, "withDeadline")
        # The label is an argument, not the first one: the request expression
        # can itself contain commas, so the check is that a readable label is
        # in there at all.
        labels = [q for q in re.findall(r"'([^']*)'", call) if len(q) >= 4]
        assert labels, name


def test_the_timer_is_cleared_so_a_fast_answer_costs_nothing():
    helper = UI[UI.index("function withDeadline"):]
    helper = helper[:helper.index("\n  }")]
    assert "clearTimeout" in helper


def test_there_is_one_deadline_mechanism_not_several():
    """A second bespoke Promise.race is how the panels drifted apart the first
    time."""
    assert UI.count("Promise.race") == 1
    assert "Promise.race" in UI[UI.index("function withDeadline"):UI.index("function withDeadline") + 700]


def test_a_timeout_lands_on_the_panel_s_existing_retry():
    """The failure is a normal error so each panel's retry path handles it;
    a separate recovery mechanism is a second thing to keep in step."""
    for name in ("renderPipelineInto", "renderAdminOperationsInto", "renderJournalInto"):
        body = _body(name)
        assert "renderError" in body or "conn-refresh" in body, name


def test_connector_summary_asks_for_status_without_doing_maintenance():
    """The panel reads a status summary, not the managing listing.

    list_installations sweeps expired enrollments, sessions and commands and
    persists the result, so using it here made a diagnostics read a write under
    the connector lock -- contending with the heartbeats of the device being
    reported on, which is what pushed the Production probe past its budget.
    """
    section = SERVER[SERVER.index("def connector_installations()") :]
    section = section[: section.index("# Concurrently")]
    assert "connector_protocol.health_summary(" in section
    assert "connector_protocol.list_installations(" not in section
    assert 'out.get("installations")' in section
    assert 'out.get("online")' in section
