"""Phase 11 — UI wiring regression guards (icons, CSP, legacy switch, admin panel).

These lock in the browser-QA fixes made during the Phase 11 final integration
pass so they cannot silently regress:

- every release icon (DEV / CANARY / BETA / stable) is actually served under the
  Aurora ``/ui/brand/`` path (the reported "broken images" bug);
- no Content-Security-Policy contains the invalid ``http://[::1]:*`` source that
  Chrome rejects and logs to the console on every page;
- the "Перейти в старый интерфейс" switch (and its reverse) still exist;
- the Admin Panel modules are Russian, grouped, free of the removed placeholder
  modules, and free of the old fake "coming in a planned phase" shell.
"""
from __future__ import annotations

import re
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import permissions, server as server_mod  # noqa: E402

AURORA = ROOT / "app" / "static" / "aurora"
UI_JS = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
SERVER_SRC = (ROOT / "app" / "server.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Release icons are served (the "broken images" bug: dev/canary/beta lived only
# under aurora/brand but /ui/brand/* used to resolve to the legacy static/brand).
# --------------------------------------------------------------------------- #
RELEASE_ICONS = (
    "stratforge-dev.png", "stratforge-canary.png", "stratforge-beta.png",
    "stratforge-mark.png", "stratforge-icon.ico",
)


def test_release_icon_files_exist_in_aurora_brand():
    brand = AURORA / "brand"
    for name in RELEASE_ICONS:
        assert (brand / name).is_file(), f"missing brand asset: {name}"


def test_ui_brand_path_routes_to_aurora():
    # The /ui handler must serve /brand/* from the Aurora tree, not the legacy
    # static/brand folder (which lacks the dev/canary/beta marks).
    assert 'rel.startswith("/brand/")' in SERVER_SRC


def test_release_icons_served_over_http():
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        for name in RELEASE_ICONS:
            with urllib.request.urlopen(f"{base}/ui/brand/{name}", timeout=5) as resp:
                assert resp.status == 200, name
                assert int(resp.headers.get("Content-Length") or 0) > 0, name
    finally:
        server.shutdown()


# --------------------------------------------------------------------------- #
# CSP must not contain the invalid IPv6 loopback source.
# --------------------------------------------------------------------------- #
def test_static_csp_has_no_invalid_ipv6_source():
    assert "[::1]" not in server_mod.STATIC_CSP


def test_no_aurora_html_meta_csp_has_invalid_ipv6_source():
    offenders = []
    for html in AURORA.glob("*.html"):
        text = html.read_text(encoding="utf-8")
        if "[::1]" in text:
            offenders.append(html.name)
    assert offenders == [], f"CSP still references http://[::1]:* in: {offenders}"


# --------------------------------------------------------------------------- #
# Legacy interface switch (both directions).
# --------------------------------------------------------------------------- #
def test_new_ui_has_legacy_switch_menu_item():
    assert "Перейти в старый интерфейс" in UI_JS
    assert "legacyUrl" in UI_JS
    assert "/ui/legacy/" in UI_JS


def test_legacy_reverse_switch_exists():
    legacy_switch = ROOT / "app" / "static" / "legacy_switch.js"
    assert legacy_switch.is_file()
    text = legacy_switch.read_text(encoding="utf-8")
    assert "Новый интерфейс" in text
    assert "/ui/" in text


# --------------------------------------------------------------------------- #
# Admin Panel: Russian, grouped, no removed/fake modules.
# --------------------------------------------------------------------------- #
def _cyrillic(value: str) -> bool:
    return bool(re.search("[А-Яа-яЁё]", value))


def test_admin_modules_are_russian_and_grouped():
    ids = {m["id"] for m in server_mod._ADMIN_MODULES}
    # Removed placeholder modules that had no real backend workflow.
    assert "workspaces" not in ids
    assert "security" not in ids
    for module in server_mod._ADMIN_MODULES:
        assert _cyrillic(module["label"]), f"module label not Russian: {module}"
        assert "group" in module, f"module missing group: {module['id']}"
    # overview is the only ungrouped (top) entry; the rest carry a group header.
    assert next(m for m in server_mod._ADMIN_MODULES if m["id"] == "overview")["group"] == ""
    assert all(m["group"] for m in server_mod._ADMIN_MODULES if m["id"] != "overview")


def test_admin_capability_labels_are_russian():
    for cap in permissions.ADMIN_CAPABILITIES:
        assert _cyrillic(cap["label"]), f"capability label not Russian: {cap}"


def test_admin_panel_has_no_fake_placeholder_shell():
    # The old generic "домейн workflow подключаются в своей плановой фазе"
    # placeholder must be gone; docs modules must have real renderers.
    assert "плановой фазе" not in UI_JS
    assert "renderAdminDocsGlobalInto" in UI_JS
    assert "renderAdminDocsWorkspaceInto" in UI_JS
