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

import json
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


# --------------------------------------------------------------------------- #
# Telegram login is one click: the deep link opens itself and the page polls
# for the result. The manual /login command stays, but only as a fallback.
# --------------------------------------------------------------------------- #
def test_telegram_login_opens_the_deep_link_itself():
    assert "openedDeepLinks" in UI_JS, "the deep link must be opened by the page"
    assert "window.open(botUrl, '_blank', 'noopener')" in UI_JS
    # Opened at most once per challenge: the waiting screen re-renders on every
    # poll, and re-opening a tab each time would be a popup storm.
    assert "openedDeepLinks.has(challengeId)" in UI_JS
    assert "openedDeepLinks.add(challengeId)" in UI_JS


def test_telegram_login_polls_for_the_result():
    assert "setInterval(() => check(challengeId), 2000)" in UI_JS
    assert "API.http.authLoginStatus(challengeId)" in UI_JS


def test_manual_login_command_is_a_fallback_not_the_instruction():
    # The /login command is behind a collapsed "Telegram не открылся?" details
    # block instead of being presented as the way in.
    assert 'class="auth-manual-fallback"' in UI_JS
    assert "<summary>Telegram не открылся?</summary>" in UI_JS
    assert "auth-copy-code" in UI_JS, "the fallback keeps its copy button"
    theme = (AURORA / "assets" / "theme.css").read_text(encoding="utf-8")
    assert ".auth-manual-fallback" in theme


def test_blocked_popup_still_leaves_a_usable_button():
    assert 'id="auth-open-telegram"' in UI_JS
    assert "Браузер заблокировал автоматическое открытие" in UI_JS


# --------------------------------------------------------------------------- #
# A nameless profile still has a role: the LOCAL owner (authenticated without a
# Telegram login, so with an empty profile) must not read as "Пользователь".
# --------------------------------------------------------------------------- #
def test_owner_without_a_profile_is_labelled_as_owner():
    label = re.search(r"function userLabel\(user\) \{.*?\n  \}", UI_JS, re.S)
    assert label, "userLabel must stay a named function"
    body = label.group(0)
    assert "user.is_owner ? 'Владелец' : 'Пользователь'" in body


# --------------------------------------------------------------------------- #
# Avatars travel as cacheable URLs, not as base64 inside every JSON payload.
# --------------------------------------------------------------------------- #
def test_avatars_are_never_inlined_into_json_payloads():
    account_src = (ROOT / "app" / "account_auth.py").read_text(encoding="utf-8")
    assert "avatar_data_url" not in account_src, (
        "an inlined base64 avatar is ~27KB per user in every payload naming one"
    )
    assert "avatar_data_url" not in UI_JS


def test_avatar_endpoint_is_cacheable_and_private():
    # The URL is stamped with ?v=<avatar_updated_at_utc>, so a given URL always
    # names the same bytes -- immutable is correct and a new avatar busts it.
    assert '"Cache-Control": "private, max-age=86400, immutable"' in SERVER_SRC
    # The generic byte responder must not clobber that with no-store.
    assert 'if not (headers or {}).get("Cache-Control"):' in SERVER_SRC


# --------------------------------------------------------------------------- #
# Asset URLs are stamped by the build, not by hand.
#
# The ?v= stamps were hand-maintained per page and had drifted to nine
# different values (oldest 20260629), so a release shipped new JS under a URL
# that had not changed in months. The CDN caches those URLs for four hours,
# which is how a green deploy could still serve the previous bundle.
# --------------------------------------------------------------------------- #
def test_html_asset_stamps_are_rewritten_to_the_build():
    stamp = server_mod._asset_build_stamp()
    assert stamp, "a build with no identity cannot stamp its assets"
    html = b'<script src="assets/ui.js?v=20260813-release-workflow2"></script>'
    out = server_mod.Handler._stamp_asset_refs(server_mod.Handler, html)
    assert b"20260813-release-workflow2" not in out
    assert f'assets/ui.js?v={stamp}"'.encode() in out


def test_asset_stamping_leaves_cross_origin_and_unversioned_refs_alone():
    rewrite = lambda raw: server_mod.Handler._stamp_asset_refs(server_mod.Handler, raw)
    # No ?v= -> untouched (nothing to bust).
    assert rewrite(b'<script src="assets/x.js"></script>') == b'<script src="assets/x.js"></script>'
    # Cross-origin -> untouched, we do not rewrite other people's URLs.
    for raw in (b'<script src="https://cdn.example/x.js?v=1"></script>',
                b'<script src="//cdn.example/x.js?v=1"></script>'):
        assert rewrite(raw) == raw
    # Non-asset extensions -> untouched.
    assert rewrite(b'<a href="report.pdf?v=1">') == b'<a href="report.pdf?v=1">'


def test_every_versioned_asset_ref_is_rewritable():
    # Guards against a page using a form the rewriter does not match, which
    # would silently keep serving a stale stamp for that page only.
    stamp = server_mod._asset_build_stamp()
    for page in sorted(AURORA.glob("*.html")):
        raw = page.read_bytes()
        out = server_mod.Handler._stamp_asset_refs(server_mod.Handler, raw)
        stale = re.findall(rb'(?:src|href)="(?!https?://|//)[^"?]+\.(?:js|css)\?v=([^"]*)"', out)
        assert all(v.decode() == stamp for v in stale), f"{page.name} kept a hand-written stamp: {stale}"


# --------------------------------------------------------------------------- #
# Admin is gated by role, not by environment.
#
# Every operational and diagnostic module is available to the owner on Canary
# and Production. Only the QA impersonation module -- virtual users and View-As
# personas, which are unsafe test hooks -- is Development-only, and it is
# withheld rather than offered as a dead "unavailable" panel.
# --------------------------------------------------------------------------- #
def _admin_modules(*, is_owner=True, development=False, monkeypatch=None):
    from app import runtime_env

    monkeypatch.setattr(runtime_env, "is_development", lambda: development)
    caps = {row["capability"]: True for row in server_mod._ADMIN_MODULES}
    payload = server_mod._admin_overview_payload(
        {"admin_capabilities": caps, "is_owner": is_owner, "user_id": 1}
    )
    return {m["id"] for m in payload["modules"]}


OPERATIONAL = {"overview", "users", "connectors", "operations", "releases", "environments"}


def test_operational_admin_modules_are_available_on_servers(monkeypatch):
    ids = _admin_modules(development=False, monkeypatch=monkeypatch)
    missing = OPERATIONAL - ids
    assert not missing, f"operational modules withheld from a server environment: {missing}"


def test_qa_impersonation_is_withheld_on_servers(monkeypatch):
    server = _admin_modules(development=False, monkeypatch=monkeypatch)
    local = _admin_modules(development=True, monkeypatch=monkeypatch)
    assert "staging" not in server, "the dev-only QA module must not be offered on a server"
    assert "staging" in local
    # Withholding it must not take anything else with it.
    assert OPERATIONAL <= server


def test_a_non_owner_admin_still_sees_no_owner_only_modules(monkeypatch):
    ids = _admin_modules(is_owner=False, development=True, monkeypatch=monkeypatch)
    owner_only = {row["id"] for row in server_mod._ADMIN_MODULES if row.get("owner_only")}
    assert not (ids & owner_only)


def test_only_the_qa_module_is_environment_gated():
    gated = {row["id"] for row in server_mod._ADMIN_MODULES if row.get("development_only")}
    assert gated == {"staging"}, (
        "an operational module became environment-gated; Admin must be role-gated"
    )


# --------------------------------------------------------------------------- #
# Connectors status is answered on the Admin page itself.
#
# The module used to be a single button to another screen, so the ordinary
# question -- is Telegram up, which environment holds the market-data hub --
# cost an extra navigation.
# --------------------------------------------------------------------------- #
def test_connectors_module_renders_status_in_place():
    assert "renderConnectorsInto" in UI_JS
    assert "adminConnectors" in UI_JS
    # The old placeholder (one button, no status) must be gone.
    assert "Открыть Telegram / Connector</button>'" not in UI_JS
    # The detailed screen stays reachable as a secondary action.
    assert "Подробный экран Telegram / Connector" in UI_JS


def test_connectors_dashboard_covers_the_required_sections():
    assert '"/api/admin/connectors"' in SERVER_SRC
    for section in ("telegram", "webhook", "canary_routing",
                    "market_gateway", "providers", "connector"):
        assert f'_connector_probe("{section}"' in SERVER_SRC


def test_connectors_dashboard_is_capability_gated():
    assert 'caps.get("connectors.manage")' in SERVER_SRC
    assert 'code="capability_required"' in SERVER_SRC


def test_connectors_dashboard_exposes_no_secret():
    payload = server_mod._connectors_dashboard_payload(
        {"user_id": 1, "admin_capabilities": {"connectors.manage": True}}
    )
    assert payload["secrets_exposed"] is False
    blob = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in ("token", "api_key", "password", "secret", "dsn", "bot"):
        # token_configured / bot_username are booleans and identifiers; a raw
        # value would show up as a long opaque string, never as these keys.
        assert f'"{forbidden}"' not in blob


def test_one_broken_source_does_not_blank_the_dashboard():
    def boom():
        raise RuntimeError("provider down")

    row = server_mod._connector_probe("providers", boom)
    assert row["state"] == "error"
    assert row["detail"] == "RuntimeError"
