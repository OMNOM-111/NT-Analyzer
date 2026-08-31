"""Cutover / production-integration tests for the new Aurora UI.

These assert that Aurora is wired to real backend endpoints, ships no mock data,
that the current server isolates /ui/legacy/, and that frozen classic assets are
available only in the separate read-only Legacy Viewer.

Pytest collects these `test_*` functions directly (no @case harness needed).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
AURORA = STATIC / "aurora"
LEGACY_STATIC = ROOT / "legacy_viewer" / "static"

NEW_PAGES = [
    "index.html", "backtesting.html", "trading.html", "performance.html",
    "strategies.html", "ai-lab.html", "ai-agents.html", "news.html", "topstep.html", "documents.html",
]
LEGACY_PAGES = [
    "index.html", "trading.html", "strategies.html", "performance.html",
    "ai-strategy.html", "ops.html", "docs.html",
]


def test_aurora_pages_exist_csp_and_mock_free():
    for page in NEW_PAGES:
        p = AURORA / page
        assert p.is_file(), f"aurora/{page} must exist"
        html = p.read_text(encoding="utf-8")
        assert "mock.js" not in html, f"aurora/{page} must not load mock.js"
        assert "Content-Security-Policy" in html, f"aurora/{page} must have a CSP meta tag"
        assert "assets/theme.css" in html, f"aurora/{page} must load the shared theme"


def test_production_ships_no_mock_data():
    assert not (AURORA / "assets" / "mock.js").exists(), \
        "production must not ship assets/mock.js"
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    assert "window.MOCK" not in api, "api.js must not reference window.MOCK"
    assert "API.http" in api, "api.js must expose the real async HTTP layer"
    overview = (AURORA / "assets" / "pages" / "overview.js").read_text(encoding="utf-8")
    assert "renderMock" not in overview, "overview.js must not retain a mock render path"


def test_aurora_page_controllers_call_real_endpoints():
    expected = {
        "overview.js": "API.http.performance",
        "performance.js": "API.http.performance",
        "documents.js": "API.http.governanceDocuments",
        "strategies.js": "API.http.profiles",
        "trading.js": "API.http.runtimeAccounts",
        "ai-lab.js": "API.http.aiSummary",
        "ai-agents.js": "API.http.aiAgents",
        "backtesting.js": "API.http.reports",
        "news.js": "API.http.news",
        "topstep.js": "API.http.topstepStatus",
    }
    for fname, needle in expected.items():
        js = (AURORA / "assets" / "pages" / fname).read_text(encoding="utf-8")
        assert needle in js, f"{fname} must call {needle}"
        assert "(демо)" not in js, f"{fname} must not contain demo placeholders"


def test_admin_operations_dashboard_uses_capability_contract():
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    permissions = (ROOT / "app" / "permissions.py").read_text(encoding="utf-8")
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    assert 'path == "/api/admin/operations"' in server
    assert 'self._admin_operations_payload()' in server
    assert '("/api/admin/operations", "operations.view")' in permissions
    assert "adminOperations: (o) => getJSON('/api/admin/operations', o)" in api
    assert "renderAdminOperationsInto" in ui
    cabinet = ui.split("function renderCabinet", 1)[1].split(
        "async function renderAiRatingsInto", 1,
    )[0]
    # 'card' is the canonical user card -- self-service, fed by the same
    # builder the Admin page uses at a wider scope. The point of this
    # assertion is that no *system* tab appears in the Cabinet, which the
    # negative checks below still enforce.
    assert ("const tabs = [['profile', 'Профиль'], ['card', 'Моя карточка'], "
            "['security', 'Безопасность'], ['plans', 'Тарифы']]") in cabinet
    assert "['operations'," not in cabinet


def test_server_routes_aurora_primary_and_isolates_legacy():
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    # The explicit mode choice is the root before either Aurora contour; the
    # professional shell remains available at /ui/index.html.
    assert '"aurora/mode-entry.html" if rel == "/" else "aurora" + rel' in server, \
        "server must serve the mode entry at /ui/ and Aurora pages below it"
    assert "_reject_isolated_legacy_surface" in server
    boundary = (ROOT / "app" / "legacy_boundary.py").read_text(encoding="utf-8")
    assert 'LEGACY_UI_PREFIX = "/ui/legacy"' in boundary
    assert 'path.startswith(LEGACY_UI_PREFIX + "/")' in boundary
    # Back-compat redirects for old page URLs.
    assert '"/ai-strategy.html": "/ui/ai-lab.html"' in server
    assert '"/ops.html": "/ui/trading.html"' in server
    assert '"/docs.html": "/ui/documents.html"' in server
    assert '"/accounting.html": "/ui/performance.html"' in server
    # Uniform CSP response header that blocks inline scripts.
    assert "STATIC_CSP" in server and "script-src 'self'" in server
    assert "http://127.0.0.1:*" in server and "http://localhost:*" in server
    assert 'self.send_header("Content-Security-Policy", STATIC_CSP)' in server


def test_legacy_pages_load_read_only_viewer_banner():
    for page in LEGACY_PAGES:
        html = (LEGACY_STATIC / page).read_text(encoding="utf-8")
        assert "legacy_switch.js" in html, \
            f"legacy {page} must include the read-only viewer marker"
    switch = (LEGACY_STATIC / "legacy_switch.js").read_text(encoding="utf-8")
    assert "READ ONLY SNAPSHOT" in switch
    assert "api.post = blocked" in switch and "api.delete = blocked" in switch
    assert "Новый интерфейс" not in switch


def test_legacy_navigation_stays_in_legacy_namespace():
    primary_pages = {
        "/ui/index.html", "/ui/trading.html", "/ui/performance.html",
        "/ui/strategies.html", "/ui/docs.html", "/ui/ai-strategy.html",
        "/ui/ops.html",
    }
    for page in LEGACY_PAGES:
        html = (LEGACY_STATIC / page).read_text(encoding="utf-8")
        for target in primary_pages:
            assert f'href="{target}"' not in html, \
                f"legacy {page} must not navigate into Aurora via {target}"
        if 'class="top-nav-link' in html:
            assert 'href="/ui/legacy/' in html, \
                f"legacy {page} navigation must stay under /ui/legacy/"

    for script_name in ("app.js", "trading.js", "strategies.js"):
        script = (LEGACY_STATIC / script_name).read_text(encoding="utf-8")
        for target in primary_pages:
            assert target not in script, \
                f"legacy {script_name} deep links must not target {target}"

    prefetch = (LEGACY_STATIC / "page-prefetch.js").read_text(encoding="utf-8")
    assert '"/ui/legacy/index.html"' in prefetch
    assert '"/ui/legacy/trading.html"' in prefetch


def test_launchers_open_new_ui():
    start = (ROOT / "start.ps1").read_text(encoding="utf-8")
    assert "/ui/" in start, "start.ps1 must open the /ui/ entry point"
    ai = (ROOT / "start-ai-lab.ps1").read_text(encoding="utf-8")
    assert "/ui/ai-lab.html" in ai, "start-ai-lab.ps1 must open the new AI Lab page"
