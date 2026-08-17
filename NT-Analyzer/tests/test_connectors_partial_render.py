"""The connectors dashboard has to degrade well.

It is read when something is already wrong, so the failure modes matter more
than the happy path: a source that hangs must not hold the page, a source that
raises must not blank it, and the answer must say plainly which sources did not
report rather than leaving the reader to infer it from a missing card.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest

from app import server as server_mod

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app" / "static" / "aurora" / "assets" / "ui.js"


# --------------------------------------------------------------------------- #
# Per-source isolation and timeout.
# --------------------------------------------------------------------------- #
def test_a_healthy_source_reports_normally():
    row = server_mod._connector_probe("probe", lambda: {"label": "X", "state": "healthy"})
    assert row["state"] == "healthy"
    assert row["id"] == "probe"
    assert "elapsed_ms" in row


def test_a_raising_source_degrades_only_itself():
    def boom():
        raise RuntimeError("provider exploded")

    row = server_mod._connector_probe("probe", boom)
    assert row["state"] == "error"
    assert row["detail"] == "RuntimeError"


def test_a_hanging_source_times_out_instead_of_blocking():
    """The endless spinner, at its source. Before this the call had no ceiling,
    so one unresponsive socket held the entire response."""
    release = threading.Event()

    def hang():
        release.wait(30)
        return {"state": "healthy"}

    started = time.time()
    row = server_mod._connector_probe("probe", hang, timeout_sec=0.3)
    elapsed = time.time() - started
    release.set()

    assert row["state"] == "timeout"
    assert elapsed < 5, "the probe must return long before the source does"
    assert row["elapsed_ms"] >= 300


def test_a_timed_out_source_does_not_keep_the_process_alive():
    """The worker is a daemon: we stop waiting rather than stop serving."""
    release = threading.Event()
    names_before = {t.name for t in threading.enumerate()}

    def hang():
        release.wait(30)

    server_mod._connector_probe("lingering", hang, timeout_sec=0.2)
    worker = next(
        (t for t in threading.enumerate()
         if t.name == "connector-probe-lingering" and t.name not in names_before),
        None,
    )
    assert worker is not None and worker.daemon is True
    release.set()


def test_the_error_detail_is_a_type_not_a_message():
    """Provider exceptions can carry credentials in their text, so only the
    class name is reported."""
    def boom():
        raise RuntimeError("token=super-secret-value")

    row = server_mod._connector_probe("probe", boom)
    assert row["detail"] == "RuntimeError"
    assert "super-secret-value" not in str(row)


def test_a_non_dict_result_does_not_corrupt_the_row():
    row = server_mod._connector_probe("probe", lambda: "not a dict")
    assert row["state"] == "unknown"
    assert row["id"] == "probe"


# --------------------------------------------------------------------------- #
# The payload states its own completeness.
# --------------------------------------------------------------------------- #
def test_the_payload_names_the_sources_that_did_not_report(monkeypatch):
    real = server_mod._connector_probe

    def fake(label, fn, timeout_sec=None):
        if label in {"providers", "telegram"}:
            return {"id": label, "state": "timeout", "detail": "no answer"}
        return {"id": label, "state": "healthy"}

    monkeypatch.setattr(server_mod, "_connector_probe", fake)
    payload = server_mod._connectors_dashboard_payload({"user_id": 1})

    assert payload["partial"] is True
    assert sorted(payload["unavailable_sources"]) == ["providers", "telegram"]
    # Every source still has a card. A missing card would read as "there is no
    # such connector", which is a different and wrong statement.
    assert len(payload["sections"]) == 6
    assert payload["secrets_exposed"] is False
    assert real is not None


def test_a_complete_payload_says_so(monkeypatch):
    monkeypatch.setattr(
        server_mod, "_connector_probe",
        lambda label, fn, timeout_sec=None: {"id": label, "state": "healthy"},
    )
    payload = server_mod._connectors_dashboard_payload({"user_id": 1})
    assert payload["partial"] is False
    assert payload["unavailable_sources"] == []
    assert payload["probe_timeout_sec"] > 0


def test_one_hanging_source_does_not_multiply_the_wait(monkeypatch):
    """Sources are probed concurrently, so the page costs the slowest one, not
    the sum of all of them."""
    release = threading.Event()

    def slow_probe(label, fn, timeout_sec=None):
        release.wait(0.4)
        return {"id": label, "state": "healthy"}

    monkeypatch.setattr(server_mod, "_connector_probe", slow_probe)
    started = time.time()
    server_mod._connectors_dashboard_payload({"user_id": 1})
    elapsed = time.time() - started
    release.set()
    # Six sources at 0.4s each would be 2.4s sequentially.
    assert elapsed < 1.6, "probes should overlap, not queue"


# --------------------------------------------------------------------------- #
# The renderer never leaves a spinner behind.
# --------------------------------------------------------------------------- #
def _renderer() -> str:
    """The whole connectors renderer: the per-card function and the page
    function together, since the card's unavailable state lives in the first
    and the page's failure paths in the second."""
    text = UI.read_text(encoding="utf-8")
    start = text.index("function connectorSectionHtml")
    end = text.index("async function renderStagingInto", start)
    return text[start:end]


def test_the_client_has_its_own_deadline():
    source = _renderer()
    assert "CONNECTOR_DEADLINE_MS" in source
    assert "Promise.race" in source, (
        "without a client-side deadline a request that never completes leaves "
        "the spinner up until the browser gives up"
    )


def test_every_failure_path_replaces_the_spinner():
    """Each exit from the renderer must write something over the loading state.
    A path that returns without rendering is an endless spinner."""
    text = UI.read_text(encoding="utf-8")
    start = text.index("async function renderConnectorsInto")
    source = text[start:text.index("async function renderStagingInto", start)]
    # The loading state is set once at the top.
    assert source.count("state-loading") == 1
    # And every `return` below it is preceded by an innerHTML assignment.
    body = source.split("state-loading", 1)[1]
    for chunk in body.split("return")[:-1]:
        assert "innerHTML" in chunk, "a return path leaves the spinner running"


def test_a_total_failure_still_offers_a_retry():
    source = _renderer()
    assert "Повторить" in source
    assert "conn-refresh" in source


def test_unavailable_sources_are_named_in_the_page():
    source = _renderer()
    assert "unavailable_sources" in source
    assert "Остальные карточки показывают актуальные данные" in source


def test_an_unavailable_card_is_kept_rather_than_dropped():
    source = _renderer()
    assert "is-unavailable" in source
    assert "conn-unavailable" in source


def test_timeout_has_its_own_label_and_style():
    text = UI.read_text(encoding="utf-8")
    labels = re.search(r"CONNECTOR_STATE_LABEL = \{(.*?)\}", text, re.S)
    assert labels and "timeout:" in labels.group(1)
    css = (ROOT / "app" / "static" / "aurora" / "assets" / "theme.css").read_text(
        encoding="utf-8")
    assert ".conn-timeout" in css
