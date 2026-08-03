"""Phase 11 finding 6 — per-environment cookie / local-storage isolation.

Every environment must use a distinct session cookie name and a distinct
local-storage namespace, and the session cookie must be host-only (no Domain=),
so a token minted for one contour is never accepted by another even across a
shared parent domain. See docs/adr/0008-environment-cookie-and-storage-isolation.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import runtime_env  # noqa: E402


def _cookie_name(monkeypatch, env: str) -> str:
    monkeypatch.setenv("DEPLOYMENT_ENV", env)
    return runtime_env.session_cookie_name()


def _ls_ns(monkeypatch, env: str) -> str:
    monkeypatch.setenv("DEPLOYMENT_ENV", env)
    return runtime_env.local_storage_namespace()


def test_session_cookie_names_distinct_per_environment(monkeypatch):
    assert _cookie_name(monkeypatch, "development") == "sf_session"
    assert _cookie_name(monkeypatch, "canary") == "sf_canary_session"
    assert _cookie_name(monkeypatch, "production") == "sf_production_session"


def test_session_cookie_names_are_mutually_unique(monkeypatch):
    names = {
        _cookie_name(monkeypatch, "development"),
        _cookie_name(monkeypatch, "canary"),
        _cookie_name(monkeypatch, "production"),
    }
    assert len(names) == 3


def test_local_storage_namespaces_distinct_per_environment(monkeypatch):
    assert _ls_ns(monkeypatch, "development") == ""
    assert _ls_ns(monkeypatch, "canary") == "canary"
    assert _ls_ns(monkeypatch, "production") == "production"


def test_set_session_cookie_is_host_only():
    # The cookie is host-only (no Domain=) so it is never sent to a sibling
    # subdomain; the distinct name is the second, defence-in-depth barrier.
    source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    idx = source.index("def _set_session_cookie(")
    body = source[idx: idx + 600]
    assert "runtime_env.session_cookie_name()" in body
    assert "Domain=" not in body
    assert "HttpOnly" in body and "SameSite=Strict" in body


def test_js_local_storage_namespace_matches_backend():
    ui = (ROOT / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    idx = ui.index("function lsNamespace(")
    body = ui[idx: idx + 400]
    assert "'canary'" in body
    assert "'production'" in body
