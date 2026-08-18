"""The merged environments-and-releases module, as the browser meets it.

Two screens became one. The risks that creates are specific: a module that
appears in the list but whose endpoint answers 403, an owner-facing button
wired to an action the release engine does not have, and a second release
engine growing quietly inside the UI. Each is checked here.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

from app import permissions, server as server_mod

ROOT = Path(__file__).resolve().parent.parent
UI = (ROOT / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
API_JS = (ROOT / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")


def _module(module_id):
    return next((m for m in server_mod._ADMIN_MODULES if m["id"] == module_id), None)


# --------------------------------------------------------------------------- #
# One module, not two.
# --------------------------------------------------------------------------- #
def test_the_two_old_modules_are_gone_and_one_took_their_place():
    ids = {m["id"] for m in server_mod._ADMIN_MODULES}
    assert "pipeline" in ids
    assert "releases" not in ids
    assert "environments" not in ids


def test_the_old_module_ids_still_route_somewhere():
    """An existing deep link should land in the merged view, not on nothing."""
    for old in ("'environments'", "'releases'"):
        assert re.search(r"moduleId === %s\) return renderPipelineInto" % old, UI), old


def test_every_capability_that_opens_the_module_also_opens_its_endpoint():
    """A module in the list whose data endpoint answers 403 is worse than a
    module that was never offered."""
    module = _module("pipeline")
    opens = set(module.get("capability_any") or (module["capability"],))
    primary = permissions.required_admin_capability("/api/admin/pipeline")
    allowed = {primary} | set(permissions.admin_route_alternatives("/api/admin/pipeline"))
    assert opens <= allowed, opens - allowed


def test_the_read_only_view_is_not_gated_behind_a_high_risk_capability_alone():
    """Reading what an environment runs is a read. Requiring the high-risk
    switch capability for it would hide status from admins entitled to it."""
    module = _module("pipeline")
    opens = set(module.get("capability_any") or (module["capability"],))
    risks = {c["id"]: c["risk"] for c in permissions.ADMIN_CAPABILITIES}
    assert any(risks.get(cap) == "read" for cap in opens)


# --------------------------------------------------------------------------- #
# The buttons call the real engine.
# --------------------------------------------------------------------------- #
def test_the_pipeline_buttons_use_the_existing_release_actions():
    """No second release engine. Every action the module can issue must be one
    the server's release dispatcher already accepts."""
    block = UI[UI.index("const PIPE_SEQUENCE"):UI.index("function pipeBadge")]
    used = set(re.findall(r"action: '([a-z-]+)'", block))
    assert used, "the sequence table should name its actions"
    server_src = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    dispatcher = server_src[server_src.index("def _release_action("):]
    dispatcher = dispatcher[:dispatcher.index("\n    def ", 10)]
    known = set(re.findall(r'action == "([a-z-]+)"', dispatcher))
    assert used <= known, used - known


def test_every_release_call_carries_an_idempotency_key():
    """The engine requires one, and a retry after a dropped response must not
    run the transition twice. The key may be built a line or two above the
    call, so the check looks at the statement that constructs the payload."""
    bounds = [m.start() for m in re.finditer(r"^  (?:async )?function ", UI, re.M)]
    for start, end in zip(bounds, bounds[1:] + [len(UI)]):
        body = UI[start:end]
        if "adminReleaseAction(" not in body and "adminReleaseCreate(" not in body:
            continue
        assert "idempotency_key" in body, body.splitlines()[0]


def test_promotion_runs_approval_before_promotion():
    """canary_passed is not promotable on its own; the engine requires an
    active approval first, so the button that says Promote must do both."""
    block = UI[UI.index("'promote-production': ["):]
    block = block[:block.index("];")]
    assert block.index("approve-production") < block.index("action: 'promote-production'")


def test_a_deploy_result_that_reports_failure_is_treated_as_a_failure():
    """build and canary deploy report their own failure with HTTP 200."""
    assert "out.ok === false" in UI


# --------------------------------------------------------------------------- #
# What the module must not do.
# --------------------------------------------------------------------------- #
def test_the_module_never_proxies_development_through_a_server():
    """No tunnel to the development box. The only origin ever opened is the one
    the server hands back, which pipeline_view guarantees is loopback."""
    block = UI[UI.index("async function renderPipelineInto"):]
    block = block[:block.index("\n  }\n", block.index("openDev"))]
    assert "development_access" in block
    assert "localhost" not in block and "127.0.0.1" not in block


def test_the_module_asks_the_server_once():
    """One request builds the view. Joining the registry and the release centre
    in the browser is what produced two screens that disagreed."""
    block = UI[UI.index("async function renderPipelineInto"):]
    block = block[:block.index("\n  }\n\n", block.index("qsa('[data-pipe-step]"))]
    calls = re.findall(r"API\.http\.(\w+)\(", block)
    assert calls.count("adminPipeline") == 1
    assert not [c for c in calls if c != "adminPipeline"], calls


def test_the_api_layer_exposes_the_pipeline_endpoint():
    assert "adminPipeline:" in API_JS
    assert "'/api/admin/pipeline'" in API_JS
