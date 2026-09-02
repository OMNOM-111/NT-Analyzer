from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app import server as server_mod
from app import portfolio_registry
from app import account_ledger
from app import performance
from app.ai_lab import lm_studio as ai_lm_studio
from app.ai_lab import paths as ai_paths
from app.ai_lab import read_model as ai_read_model


ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app" / "static" / "aurora"
DOMAIN_JS = AURORA / "assets" / "domain.js"


def _domain_eval(expression: str):
    source = DOMAIN_JS.read_text(encoding="utf-8")
    script = source + "\nconsole.log(JSON.stringify(" + expression + "));"
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(proc.stdout.strip())


def test_job_detail_adapter_uses_nested_result_and_real_trade_fields():
    fixture = {
        "job_id": "job-1",
        "status": "done",
        "report_no": 42,
        "job": {
            "strategy": {"class_name": "StrategyA", "parameters": {"Length": 12}},
            "instrument": "MNQ 09-26",
            "timeframe": {"bars_period_type": "Minute", "value": 5},
            "period": {"from_utc": "2026-01-01T00:00:00Z", "to_utc": "2026-02-01T00:00:00Z"},
            "execution": {"slippage_ticks": 2},
        },
        "result": {
            "metrics": {"trade_count": 7, "net_profit_after_commission": 123.45},
            "verification_warnings": ["verified"],
        },
    }
    trade = {
        "entry_time_utc": "2026-01-02T10:00:00Z",
        "exit_time_utc": "2026-01-02T10:05:00Z",
        "pnl_currency": -17.25,
        "pnl": 9999,
    }
    expr = (
        "(() => { const d = " + json.dumps(fixture) + "; const t = " + json.dumps(trade) + "; "
        "const m = AuroraDomain.normalizeJobDetail(d, {}); return {"
        "name:m.className,instrument:m.instrument,trades:m.metrics.trade_count,net:m.metrics.net_profit_after_commission,"
        "pnl:AuroraDomain.tradePnl(t),entry:AuroraDomain.tradeTime(t,'entry'),exit:AuroraDomain.tradeTime(t,'exit')}; })()"
    )
    out = _domain_eval(expr)
    assert out == {
        "name": "StrategyA",
        "instrument": "MNQ 09-26",
        "trades": 7,
        "net": 123.45,
        "pnl": -17.25,
        "entry": "2026-01-02T10:00:00Z",
        "exit": "2026-01-02T10:05:00Z",
    }


def test_trading_series_contains_only_trade_pnl_and_drawdown():
    strategies = [
        {"daily": [{"date": "2026-06-01", "pnl": 100}, {"date": "2026-06-02", "pnl": -40}]},
        {"daily": [{"date": "2026-06-01", "pnl": 25}, {"date": "2026-06-03", "pnl": 10}]},
    ]
    out = _domain_eval("AuroraDomain.tradingSeries(" + json.dumps(strategies) + ")")
    assert [row["tradingPnl"] for row in out] == [125, -40, 10]
    assert [row["cumulativeTradingPnl"] for row in out] == [125, 85, 95]
    assert [row["drawdown"] for row in out] == [0, -40, -30]
    assert all("deposit" not in row and "balance" not in row for row in out)


def test_aurora_report_assessment_matches_frequency_policy_and_confidence_rules():
    out = _domain_eval("""
      (() => {
        const period = {from_utc:'2026-01-01T00:00:00Z', to_utc:'2026-01-08T00:00:00Z'};
        const longPeriod = {from_utc:'2026-01-01T00:00:00Z', to_utc:'2026-04-01T00:00:00Z'};
        const metrics = {winning_pct:50, profit_factor:1, max_drawdown:100};
        return {
          frequencies:[1,2,7,8].map(n => AuroraDomain.frequencyAssessment(n, period).key),
          profitable:AuroraDomain.confidenceAssessment(100, longPeriod, {...metrics, net_profit:50000}),
          losing:AuroraDomain.confidenceAssessment(100, longPeriod, {...metrics, net_profit:-50000}),
          tones:[AuroraDomain.metricTone('win', 60), AuroraDomain.metricTone('win', 40), AuroraDomain.metricTone('pnl', -1)]
        };
      })()
    """)
    assert out["frequencies"] == ["rare", "normal", "normal", "frequent"]
    assert out["profitable"] == out["losing"]
    assert out["tones"] == ["pos", "neg", "neg"]


def test_market_phase_handles_weekend_and_daily_maintenance_in_pt():
    dates = [
        "2026-06-29T20:59:00Z",  # Monday 13:59 PT
        "2026-06-29T21:00:00Z",  # Monday 14:00 PT
        "2026-06-29T22:00:00Z",  # Monday 15:00 PT
        "2026-06-28T21:59:00Z",  # Sunday 14:59 PT
        "2026-06-28T22:00:00Z",  # Sunday 15:00 PT
    ]
    out = _domain_eval(
        "[" + ",".join("AuroraDomain.marketPhaseAt(new Date(" + json.dumps(d) + "))" for d in dates) + "]"
    )
    assert out == ["open", "maintenance", "open", "weekend", "open"]


def test_every_aurora_page_loads_domain_adapter_before_ui():
    for page in AURORA.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        # The mode picker deliberately precedes the Aurora application shell;
        # it only needs auth API + its focused controller, not domain/UI code.
        if page.name == "mode-entry.html":
            assert 'src="assets/pages/mode-entry.js' in html
            assert 'src="assets/ui.js' not in html
            continue
        assert 'src="assets/domain.js' in html, page.name
        assert html.index('src="assets/domain.js') < html.index('src="assets/ui.js'), page.name


def test_every_aurora_page_uses_one_api_cache_version():
    versions = {}
    for page in AURORA.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        marker = 'src="assets/api.js?v='
        assert marker in html, page.name
        versions[page.name] = html.split(marker, 1)[1].split('"', 1)[0]
    assert set(versions.values()) == {"20260901-community-chat1"}, versions


def test_every_aurora_page_uses_current_theme_cache_version():
    versions = {}
    for page in AURORA.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        marker = 'href="assets/theme.css?v='
        assert marker in html, page.name
        versions[page.name] = html.split(marker, 1)[1].split('"', 1)[0]
    assert set(versions.values()) == {"20260902-sfchat-messenger3"}, versions


def test_development_preview_is_rewired_after_async_build_identity():
    js = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    apply_identity = js[
        js.index("function applyBuildIdentity(payload)"):
        js.index("async function refreshBuildIdentity(seed)")
    ]

    assert "if (CURRENT_AUTH)" in apply_identity
    assert "wireAdminEnvironmentButton();" in apply_identity
    assert "wireDevPreviewButton();" in apply_identity
    assert "renderDevPreviewBanner();" in apply_identity
    assert "label: 'Developer Preview', onClick: () => openDevPreviewPanel()" in js


def test_unified_identity_ui_uses_public_uuid_and_provider_login_contract():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")

    assert "user.id || user.user_id" in ui
    assert "const telegramIdentity" in ui
    assert "auth-provider-start" in ui
    assert "authGoogleLoginStart" in api
    assert "authEmailStart" in api
    assert "authEmailVerify" in api
    assert "authEmailLinkStart" in api
    assert "authEmailLinkVerify" in api
    assert "accept_terms: details.accept_terms" in ui
    assert 'id="auth-email-verify-accept"' in ui


def test_legal_terms_payload_is_short_form_master_document():
    from app import legal

    payload = legal.terms_payload()

    assert payload["title"] == "Я соглашаюсь."
    assert payload["summary"] == "Пользовательское соглашение StratForge AI"
    assert payload["version"] == "2026-08-30-v2"
    assert payload["date"] == "30 августа 2026 года"
    assert len(payload["digest"]) == 64
    assert len(payload["sections"]) == 21
    headings = [section["heading"] for section in payload["sections"]]
    assert headings[0] == "Принятие соглашения"
    assert "Данные и конфиденциальность" in headings
    assert "AI-функции" in headings
    assert "Cookies, локальное хранилище и сообщения" in headings
    assert "Интеграции и market data" in headings
    assert "Определения" in headings
    assert "Возраст и правоспособность" in headings
    assert "Лицензия и интеллектуальная собственность" in headings
    assert "Запрещённое использование" in headings
    assert "Приостановка и прекращение аккаунта" in headings
    assert "Экспорт, закрытие аккаунта и удаление данных" in headings
    assert "Beta-функции, обновления и API" in headings
    assert "Обстоятельства вне контроля" in headings
    assert "Экспортный контроль и санкции" in headings
    assert "Оплата, пожертвования и сторонние платежи" in headings
    assert "Связь с Оператором" in headings
    age = next(section for section in payload["sections"] if section["heading"] == "Возраст и правоспособность")
    assert "18 лет" in age["body"]
    rendered = " ".join(section["body"] for section in payload["sections"])
    assert "ТРЕБУЕТ РЕШЕНИЯ" not in rendered
    assert "отдельной явной активации" in rendered
    assert [notice["id"] for notice in payload["notices"]] == [
        "legal-02", "legal-08", "legal-05", "legal-03", "legal-04", "legal-06",
    ]


def test_registration_terms_modal_links_informational_legal_notices():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    css = (AURORA / "assets" / "theme.css").read_text(encoding="utf-8")

    assert "showLegalNoticeModal" in ui
    # The registration screen has no session: this modal must read the public
    # legal route, never the privileged governance endpoint, or the visitor is
    # asked to accept an agreement whose linked documents will not open.
    assert "API.http.legalDocument(id)" in ui
    assert "API.http.governanceDocument(id)" not in ui
    assert 'data-legal-notice=' in ui
    assert "Отдельное принятие при регистрации не требуется" in ui
    assert "terms-notice-modal" in css


def test_unauthenticated_entry_uses_provider_login_not_promo_gate():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    boot = ui.split("async function authenticateAndStart", 1)[1].split(
        "CURRENT_AUTH = result.auth", 1
    )[0]
    assert "Вход и регистрация" in ui
    assert "Живые графики используют только разрешённый для аккаунта источник market data" in ui
    assert 'id="auth-open-promo"' in ui
    assert "Смотреть без входа" not in ui
    assert "Смотреть бесплатно" not in ui
    assert "guestAuthStub" not in ui
    assert "startGuestBrowse" not in ui
    assert "guest-browse" not in ui
    assert "renderTelegramLogin('')" in boot
    assert "if (!dismissed) renderWelcomeAccess" not in boot
    assert "stratforge.welcome.dismissed" not in boot
    require_signin = ui.split("function requireSignIn()", 1)[1].split("window.UI", 1)[0]
    assert "renderTelegramLogin('')" in require_signin
    assert "renderWelcomeAccess" not in require_signin


def test_every_aurora_page_uses_current_ui_cache_version():
    versions = {}
    for page in AURORA.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        marker = 'src="assets/ui.js?v='
        if marker not in html:
            continue
        versions[page.name] = html.split(marker, 1)[1].split('"', 1)[0]
    assert versions
    assert set(versions.values()) == {"20260902-sfchat-messenger3"}, versions


def test_build_identity_is_visible_and_never_guessed_client_side():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    entry = (AURORA / "mode-entry.html").read_text(encoding="utf-8")
    entry_js = (AURORA / "assets" / "pages" / "mode-entry.js").read_text(
        encoding="utf-8"
    )
    theme = (AURORA / "assets" / "theme.css").read_text(encoding="utf-8")

    assert 'id="app-release-badge" data-release-badge' in ui
    assert 'id="app-build-meta" data-build-meta' in ui
    assert "environment === 'development' && channel === 'dev'" in ui
    assert "short: 'DEV', full: 'РАЗРАБОТКА'" in ui
    assert "environment === 'canary' && ['beta', 'stable'].includes(channel)" in ui
    assert "short: 'CANARY', full: 'CANARY'" in ui
    assert "environment === 'production' && channel === 'beta'" in ui
    assert "short: 'BETA', full: 'ПУБЛИЧНАЯ БЕТА'" in ui
    assert "environment === 'production' && channel === 'stable'" in ui
    assert "return { short: '', full: 'PRODUCTION'" in ui
    assert "deployment.release_channel || ''" in ui
    assert "deployment.app_version || deployment.build_version" in ui
    assert "deployment.build_timestamp_utc" in ui
    assert "deployment.git_commit_sha" in ui
    assert "deployment.artifact_sha256" in ui
    assert "deployment.dirty === true" in ui
    assert "visibleParts.join(' · ')" in ui
    assert "badge.hidden = !label.short" in ui
    assert "data-release-icon" in ui
    assert 'id="mode-entry-release-badge"' in entry
    assert 'id="mode-entry-build-meta"' in entry
    assert "data-release-icon" in entry
    assert "API.http.runtimeEnv" in entry_js
    assert "never guess a channel" in entry_js
    assert ".rail-release-badge.dev" in theme
    assert ".rail-release-badge.canary" in theme
    assert ".rail-release-badge.beta" in theme
    assert ".rail-release-badge.stable[hidden]" in theme


def test_release_icon_assets_match_owner_sources_and_png_contract():
    expected = {
        "stratforge-dev.png": "B6F8473D19F4AC9823952A99F6271F5A7C6E55B67165B644AFCA7FACB3AE5F66",
        "stratforge-canary.png": "931B71761AD7001822AA989F9F6329A7F5047B1477FC8D2D5FD66379959131D9",
        "stratforge-beta.png": "F887F976B4FB572646E5AD3DC8A1FB8C89B7234A96E30F94EE708ED276CBE9D3",
    }

    for name, digest in expected.items():
        payload = (AURORA / "brand" / name).read_bytes()
        assert payload[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", payload[16:24]) == (1254, 1254)
        assert payload[24:26] == bytes((8, 2))  # 24-bit RGB, no alpha channel.
        assert hashlib.sha256(payload).hexdigest().upper() == digest


def test_news_tickers_have_clipped_tracks_and_global_page_coverage():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    theme = (AURORA / "assets" / "theme.css").read_text(encoding="utf-8")
    news = (AURORA / "news.html").read_text(encoding="utf-8")
    page_js = (AURORA / "assets" / "pages" / "news.js").read_text(encoding="utf-8")

    assert "data-global-news-strip" in ui and "page === 'news' ? null" not in ui
    assert "global-news-window" in ui and "overflow: hidden" in theme
    assert "news-ticker" not in news and "repeat(7,minmax(0,1fr))" in news
    assert "scheduleStrategyRows" in ui and "cal-ev-title" in page_js
    assert "item.is_confirmed" in page_js
    assert "ОТКЛЮЧИТЕ СТРАТЕГИИ" in ui


def test_live_static_handler_routes_csp_and_assets():
    srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address
    base = f"http://{host}:{port}"
    try:
        for path, marker in (
            ("/ui/", "Обзор"),
            ("/ui/assets/domain.js", "AuroraDomain"),
        ):
            with urllib.request.urlopen(base + path, timeout=5) as response:
                body = response.read().decode("utf-8")
                assert response.status == 200
                assert marker in body
                assert "script-src 'self'" in response.headers["Content-Security-Policy"]
                assert "http://127.0.0.1:*" in response.headers["Content-Security-Policy"]

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + "/ui/legacy/", timeout=5)
        assert exc.value.code == 410
        assert json.loads(exc.value.read().decode("utf-8"))["code"] == "legacy_ui_isolated"

        with urllib.request.urlopen(base + "/api/runtime/env", timeout=5) as response:
            runtime = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
            assert response.headers["Access-Control-Allow-Origin"] == "*"
            assert runtime.get("environment") or runtime.get("deployment")
            assert "data_root" not in runtime
            assert "test_auth_enabled" not in runtime

        request = urllib.request.Request(base + "/ui/ops.html", method="GET")
        opener = urllib.request.build_opener(urllib.request.HTTPHandler())
        with opener.open(request, timeout=5) as response:
            assert response.geturl().endswith("/ui/trading.html")
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_portfolio_registry_keeps_legacy_ids_and_appends_without_renumbering(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_registry, "REGISTRY_PATH", tmp_path / "cells.json")
    initial = portfolio_registry.read_registry()
    by_id = {row["cell_id"]: row for row in initial["cells"]}
    assert by_id["CELL-020"]["root"] == "MNQ" and by_id["CELL-020"]["slot"] == 10
    assert by_id["CELL-126"]["root"] == "MNQ" and by_id["CELL-126"]["slot"] == 11
    assert by_id["CELL-180"]["root"] == "MYM" and by_id["CELL-180"]["slot"] == 15

    created = portfolio_registry.add_root("MCD", slots=3, start_id=200, actor="test")
    assert [row["cell_id"] for row in created["created"]] == ["CELL-200", "CELL-201", "CELL-202"]
    extra = portfolio_registry.add_cell("MCD", "CELL-300", actor="test")
    assert extra["created"]["slot"] == 4
    assert extra["created"]["cell_id"] == "CELL-300"

    portfolio_registry.archive_cell("CELL-300", actor="test")
    automatic = portfolio_registry.add_cell("MCD", actor="test")
    assert automatic["created"]["cell_id"] == "CELL-301"
    final = portfolio_registry.read_registry()
    final_by_id = {row["cell_id"]: row for row in final["cells"]}
    assert final_by_id["CELL-020"] == by_id["CELL-020"]
    assert final_by_id["CELL-126"] == by_id["CELL-126"]
    assert final_by_id["CELL-300"]["status"] == "archived"


def test_portfolio_registry_rejects_duplicate_root_and_explicit_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_registry, "REGISTRY_PATH", tmp_path / "cells.json")
    portfolio_registry.add_root("MCD", slots=2, start_id=200)
    try:
        portfolio_registry.add_root("MCD", slots=2, start_id=300)
        raise AssertionError("duplicate root must fail")
    except ValueError as exc:
        assert "already exists" in str(exc)
    try:
        portfolio_registry.add_root("MHO", slots=2, start_id=200)
        raise AssertionError("colliding range must fail")
    except ValueError as exc:
        assert "collides" in str(exc)


def test_account_ledger_never_labels_unexplained_balance_as_profit_or_deposit(tmp_path, monkeypatch):
    monkeypatch.setattr(account_ledger, "LEDGER_PATH", tmp_path / "account_ledger.json")
    def payload(net_liq, realized=0, unrealized=0, at="2026-06-28T20:00:00Z"):
        return {
            "source": "test", "accounts_generated_at_utc": at,
            "online_accounts": [{
                "account_name": "Sim101", "net_liquidation": net_liq, "cash_value": net_liq,
                "realized_pnl": realized, "unrealized_pnl": unrealized,
            }],
        }

    account_ledger.record_accounts(payload(10_000))
    account_ledger.record_accounts(payload(11_000, at="2026-06-28T21:00:00Z"))
    history = account_ledger.account_history("Sim101")
    event = history["accounts"][0]["events"][0]
    assert event["amount"] == 1000
    assert event["kind"] == "unclassified_adjustment"
    assert event["classification_status"] == "needs_review"
    assert "profit" not in event["kind"] and event["kind"] != "deposit"

    classified = account_ledger.classify_event("Sim101", event["event_id"], "deposit", "tester", "known funding")
    assert classified["event"]["kind"] == "deposit"
    assert classified["event"]["classification_status"] == "classified"


def test_account_ledger_reconciliation_is_classified_but_not_cash_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(account_ledger, "LEDGER_PATH", tmp_path / "account_ledger.json")
    account_ledger.record_accounts({
        "source": "test", "accounts_generated_at_utc": "2026-07-01T00:00:00Z",
        "online_accounts": [{
            "account_name": "DEMO", "net_liquidation": 100, "cash_value": 100,
            "realized_pnl": 0, "unrealized_pnl": 0,
        }],
    })
    account_ledger.record_accounts({
        "source": "test", "accounts_generated_at_utc": "2026-07-01T00:01:00Z",
        "online_accounts": [{
            "account_name": "DEMO", "net_liquidation": 200, "cash_value": 200,
            "realized_pnl": 0, "unrealized_pnl": 0,
        }],
    })
    event = account_ledger.account_history("DEMO")["accounts"][0]["events"][0]

    account_ledger.classify_event(
        "DEMO", event["event_id"], "reconciliation", "owner", "after reconnect",
    )
    history = account_ledger.account_history("DEMO")["accounts"][0]

    assert history["events"][0]["kind"] == "reconciliation"
    assert history["events"][0]["classification_status"] == "classified"
    assert history["summary"]["classified_cash_flow"] == 0


def test_account_ledger_explains_equity_change_from_runtime_pnl(tmp_path, monkeypatch):
    monkeypatch.setattr(account_ledger, "LEDGER_PATH", tmp_path / "account_ledger.json")
    account_ledger.record_accounts({"online_accounts": [{"account_name": "Sim101", "net_liquidation": 10000, "cash_value": 10000, "realized_pnl": 0, "unrealized_pnl": 0}]})
    account_ledger.record_accounts({"online_accounts": [{"account_name": "Sim101", "net_liquidation": 10050, "cash_value": 10050, "realized_pnl": 50, "unrealized_pnl": 0}]})
    history = account_ledger.account_history("Sim101")
    assert history["accounts"][0]["events"] == []


def test_aurora_keeps_legacy_operational_capabilities_wired():
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    trading = (AURORA / "assets" / "pages" / "trading.js").read_text(encoding="utf-8")
    strategies = (AURORA / "assets" / "pages" / "strategies.js").read_text(encoding="utf-8")
    ai_lab = (AURORA / "assets" / "pages" / "ai-lab.js").read_text(encoding="utf-8")

    for path in (
        "/api/ops/runtime/history", "/api/ops/runtime/strategy-history",
        "/api/ops/runtime/strategy-display", "/api/ops/runtime/command-status",
        "/api/ops/strategy-start-dates", "/api/ai-lab/performance",
        "/api/ai-lab/calendar", "/api/ai-lab/compile-source-status",
        "/api/ai-lab/current", "/api/ai-lab/user-research/scan",
    ):
        assert path in api

    for method in ("runtimeHistory", "runtimeStrategyHistory", "runtimeStrategyDisplay", "strategyStartDates", "runtimeCommandStatus"):
        assert f"API.http.{method}" in trading
    assert "API.http.setRuntimeStrategyDisplay" in strategies
    for method in ("aiPerformance", "aiCalendar", "aiCompileSourceStatus", "aiCurrent", "aiUserResearchScan"):
        assert f"API.http.{method}" in ai_lab


def test_admin_panel_replaces_system_actions_in_personal_menu_and_cabinet() -> None:
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    css = (AURORA / "assets" / "theme.css").read_text(encoding="utf-8")

    menu = ui.split("function wireTopbar()", 1)[1].split("function environmentHtml", 1)[0]
    assert "hasAdminCapability('admin.view')" in menu
    assert "label: 'Панель администратора'" in menu
    # System OPERATIONS actions moved to the Admin Panel → Operations module.
    for legacy_action in (
        "Запустить всё окружение",
        "Диагностика системы",
        "Перезапустить backend",
    ):
        assert legacy_action not in menu
    assert "Перейти в старый интерфейс" not in menu
    assert "/ui/legacy/" not in menu

    cabinet = ui.split("function renderCabinet", 1)[1].split("async function renderAiRatingsInto", 1)[0]
    # 'card' is the canonical user card -- self-service, fed by the same
    # builder the Admin page uses at a wider scope. The point of this
    # assertion is that no *system* tab appears in the Cabinet, which the
    # negative checks below still enforce.
    assert ("const tabs = [['profile', 'Профиль'], ['card', 'Моя карточка'], "
            "['security', 'Безопасность'], ['plans', 'Тарифы']]") in cabinet
    assert "['users'," not in cabinet
    assert "['operations'," not in cabinet

    for path in (
        "/api/admin/overview",
        "/api/admin/environment-targets",
        "/api/admin/operations",
        "/admin-permission",
    ):
        assert path in api
    assert ".admin-shell" in css and ".admin-env-grid" in css


def test_remote_admin_diagnostics_is_disabled_instead_of_calling_blocked_edge_route() -> None:
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    operations = ui.split("async function renderAdminOperationsInto", 1)[1].split(
        "function adminOverviewHtml", 1,
    )[0]
    assert "deploymentEnvironment === 'development'" in operations
    assert "Локальная диагностика · DEV" in operations
    assert "bridge log доступны только в Development" in operations
    assert "diagnostics && !diagnostics.disabled" in operations


def test_environment_switcher_never_transfers_browser_credentials() -> None:
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    switcher = ui.split("async function probeEnvironmentTarget", 1)[1].split(
        "async function renderDelegatedUsersInto", 1,
    )[0]
    assert "API.http.adminEnvironmentProbe(target.environment)" in switcher
    assert "fetch(origin + '/api/runtime/env'" not in switcher
    assert "'_blank', 'noopener,noreferrer'" in switcher
    assert "origin + '/ui/'" in switcher
    assert "withMiniAppContext" not in switcher
    assert "localStorage.getItem" not in switcher
    assert "telegramInitData" not in switcher


def test_dev_preview_return_uses_the_dev_only_exit_route() -> None:
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    banner = ui.split("function renderImpersonationBanner", 1)[1].split(
        "// ---- Developer Preview", 1,
    )[0]
    assert "auth.impersonation_preset === 'dev_preview'" in banner
    assert "API.http.devPreviewExit()" in banner
    assert "API.http.ownerImpersonateEnd()" in banner


def test_aurora_trading_exposes_reconnect_modeling_control():
    html = (AURORA / "trading.html").read_text(encoding="utf-8")
    trading = (AURORA / "assets" / "pages" / "trading.js").read_text(encoding="utf-8")
    assert 'id="ctrl-reconnect"' in html
    assert "command: 'reconnect_account'" in trading
    assert "#ctrl-reconnect" in trading


def test_sf_chat_preserves_vitek_metadata_without_exposing_internal_model_beside_time():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "orchFmtTime(row.timestamp_utc)" in ui
    assert "!isUser && row.model ? esc(row.model)" not in ui
    assert "SF Chat · люди и AI-помощники" in ui
    assert '<span class="orch-head-name">SF Chat<span class="orch-head-skin"' in ui
    assert "AI · Виктор и агенты" in ui
    assert "function openSFChat" in ui
    assert "conversation_type === 'human'" in ui
    assert "Ваши чаты и данные сохранены" in ui
    assert "ORCH.conversations = []" not in ui
    assert "modelMeta" in ui and "модель:" in ui
    assert "orchActionsHtml" in ui and "Ход выполнения" in ui
    assert "ORCH_ACTION_LABELS" in ui and "ORCH_ACTION_STATES" in ui
    assert "row.thinking" not in ui
    assert "orchThinkBlock" not in ui
    assert "Анализирую задачу…" in ui


def test_sf_chat_header_chip_and_day_marks_render_real_state_not_css_literals():
    """The skin chip and the day separators must come from live state.

    Both used to be CSS `content` strings: the header read "Orbital Glass" no
    matter which of the six skins was applied, and every conversation was
    headed "Сегодня" even when its newest message was days old.
    """
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    css = (AURORA / "assets" / "theme.css").read_text(encoding="utf-8")
    assert "content: 'Orbital Glass'" not in css
    assert "content: 'Сегодня'" not in css
    assert "qsa('.orch-head-skin, .orch-skin-label')" in ui
    assert "function orchDayKey" in ui
    assert "function orchDayLabel" in ui
    assert "orchMessagesHtml(messages)" in ui
    assert "orchAppendMessage(box," in ui


def test_global_and_chat_polling_do_not_overlap_or_hammer_rate_limits():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "let stopped = false, running = false;" in ui
    assert "if (stopped || running) return;" in ui
    assert "let stopped = false, refreshing = false;" in ui
    assert "Date.now() < Number(ORCH.retryAfter || 0)" in ui
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    assert "Number(e.retryAfterMs || 0)" in ui
    assert "e instanceof HttpError && e.status >= 400 && e.status < 500" in api
    assert 'headers={"Retry-After": str(retry_after)}' in server
    assert "streamResult.ok !== true" in ui
    assert "if (!sawFinal || !sawDone)" in api
    assert "request_id: mutationRequestId('orchestrator')" in api
    assert "local_worker.enqueue_ai_message" in server
    assert "threading.Thread(target=worker, name=\"orchestrator-stream\"" not in server
    assert "ai_chief_agent.handle_message(" not in server
    assert "API.http.aiOrchestratorMessage(text, cid, agent)" not in ui
    assert "row.actor_is_owner ? 'Owner'" not in ui
    assert "async function refreshAuth()" in api and "authReady, refreshAuth" in api
    assert "authenticateAndStart(newsStrip, true)" in ui
    assert "if (ORCH.sending) { toast('Дождитесь ответа в текущем диалоге'); return; }" in ui
    assert "}, 3000);" in ui
    assert "}, 5000);" in ui
    # In-app notices: slower poll + no auto-ack while chat is open + 429 backoff.
    assert "poll(() => refreshInAppNotices(), 12000)" in ui
    assert "NOTICE.retryAfter" in ui
    assert "never auto-ack" in ui.lower() or "NEVER auto-ack" in ui
    assert 'path == "/api/notifications"' in server
    assert 'path == "/api/vitek/status"' in server


def test_ai_lab_uses_conversational_orchestrator_not_literal_mission_form():
    html = (AURORA / "ai-lab.html").read_text(encoding="utf-8")
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    # AI Lab keeps only a compact status card + a launcher for the global chat.
    assert "Виктор · правая рука руководителя" in html
    assert 'id="orchestrator-open"' in html
    assert 'id="chief-hours"' not in html
    assert 'id="chief-task"' not in html
    # The full conversational surface is the global floating widget in the shell:
    # launcher FAB, per-conversation switching and the message API are all wired.
    assert "openOrchestrator" in ui
    assert "orch-fab" in ui
    assert "API.http.aiOrchestratorMessage" in ui
    assert "sfChatConversations" in ui
    assert "aiOrchestratorConversations" in api
    assert "/api/ai-lab/orchestrator/message" in api
    assert "/api/ai-lab/orchestrator/conversations" in api
    assert "aiOrchestratorSpeak" in api and "/api/ai-lab/orchestrator/speak" in api
    assert "domainAgentVoices" in api and "/api/ai-lab/domain-agents/voices" in api
    assert "domainAgentVoiceSave" in api and "domainAgentVoicePreview" in api
    assert 'path == "/api/ai-lab/orchestrator/speak"' in (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    assert "domain-agents/voices" in (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    assert "agentSpeakFromFace" in ui and "AGENT_SPEAK_HOVER_MS" in ui
    html = (AURORA / "ai-agents.html").read_text(encoding="utf-8")
    page = (AURORA / "assets" / "pages" / "ai-agents.js").read_text(encoding="utf-8")
    assert "staff-voice-grid" in html and "openVoiceSettings" in page


def test_community_v2_and_unified_sf_chat_are_real_api_backed_surfaces():
    html = (AURORA / "community.html").read_text(encoding="utf-8")
    page = (AURORA / "assets" / "pages" / "community.js").read_text(encoding="utf-8")
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")

    for contract in (
        "community-social-dock",
        "community-stream-toolbar",
        "community-feed",
        "community-composer-v2",
        "community-profile-wall-feed",
        "community-profile-modal",
        "community-channels-view",
    ):
        assert contract in html
    assert "community-hero" not in html
    assert "Торговое сообщество внутри StratForge" not in html
    assert 'id="community-nav"' not in html
    assert 'id="community-visibility-modal"' in html and 'id="community-visibility-form"' in html
    assert 'data-community-sort="recent"' in html and 'data-community-sort="relevant"' in html
    assert 'data-community-wall-tab="posts"' in html and 'data-community-wall-tab="saved"' in html
    for action in ("График", "Стратегия", "Файл", "Опубликовать"):
        assert action in html
    assert "communityV2Feed" in page and "communityV2Post" in page
    assert 'data-community-object="result"' in html and 'data-community-object="result" disabled' not in html
    assert "communityV2Objects" in page and "communityV2PublishObject" in page
    assert "data-community-rich-object" in page
    assert "raw.startsWith('@')" in page
    assert "data-share-post" in page and "Поделиться публикацией" in page
    assert "openProfileVisibility" in page and "communityV2UpdateProfile" in page
    assert "community-post-action" in page and "actionIcon" in page
    assert "server-attested" in page
    assert "sfChatStartConversation" in page and "UI.openSFChat" in page
    assert "mock" not in page.lower()
    assert "sfChatConversations" in ui and "sfChatConversation" in ui and "sfChatMessage" in ui
    assert 'id="orch-convo-search"' in ui and 'id="orch-new-side"' in ui
    assert 'data-orch-convo-filter="pinned"' in ui and 'data-orch-convo-filter="recent"' in ui
    assert "ORCH.listQuery" in ui and "participant.username" in ui
    assert "sideCreate.hidden = ORCH.aiAvailable === false" in ui
    assert "NOTICE_MAX_VISIBLE = 1" in ui and "Открыть в чате" in ui
    assert "/api/community/v2/feed" in api and "/api/sf-chat/conversations" in api
    assert "/api/community/v2/objects" in api
    assert 'path == "/api/community/v2/feed"' in server
    assert 'path == "/api/sf-chat/conversations"' in server
    assert 'path == "/api/community/v2/objects"' in server


def test_named_domain_agents_and_unified_finance_page_contract():
    finance = (AURORA / "performance.html").read_text(encoding="utf-8")
    finance_js = (AURORA / "assets" / "pages" / "performance.js").read_text(encoding="utf-8")
    strategies = (AURORA / "strategies.html").read_text(encoding="utf-8")
    strategies_js = (AURORA / "assets" / "pages" / "strategies.js").read_text(encoding="utf-8")
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")

    assert "Финансы" in finance and "Марина · финансовый контроль" in finance
    assert "renderMarina" in finance_js and "API.http.accounting" in finance_js
    assert not (AURORA / "accounting.html").exists()
    assert "Толик · контроль качества стратегий" in strategies
    assert "tolik-message" not in strategies and "domainAgentMessage('tolik'" not in strategies_js
    assert "/api/ai-lab/accounting" in api and "/api/ai-lab/strategy-analysis" in api
    assert "aiOrchestratorRateMessage" in api and "/api/ai-lab/orchestrator/message/" in api
    assert "aiOrchestratorFulfillMessage" in api and "/fulfillment" in api and "/fulfillment" in server
    assert "aiOrchestratorSetConversationState" in api and "/orchestrator/conversations/state" in server
    assert "rate_message" in server and "message/" in server and "/rating" in server
    assert "set_message_fulfillment" in server
    assert "orchRatingHtml" in ui and "data-orch-rate" in ui and "orch-feedback-area" in ui
    assert "orchFooterHtml" in ui and "orch-fulfill-marks" in ui and "orch-chain" in ui
    assert "Тема завершена" in ui
    assert "isDefault" in ui and "badge.hidden = true" in ui
    assert "orchStartFeedbackVoice" in ui and "orch-feedback-mic" in ui
    assert "orch-feedback-archive" in ui and "orch-feedback-edit" in ui
    assert "orchStopFeedbackVoice" in ui and "rec.continuous = true" in ui
    assert "messagesSignature" in ui and "ta.dataset.dirty" in ui
    assert "orch-task-state" in ui and "orchToggleConversationState" in ui
    assert "Текущая тема ещё не завершена" in ui
    # Vitek chooses the model internally; the owner never sees a model menu.
    assert "data-orch-mode=" not in ui and "ORCH_MODES" in ui
    assert 'id="orch-model-picker" hidden' in ui
    assert "orch-model-trigger" not in ui and "orch-model-item" not in ui
    assert "fast:" not in ui and "standard:" not in ui and "max:" not in ui
    assert "agent: 'secretary'" not in ui and "agent: 'manager'" not in ui
    # The old role rail is fully removed from the menu.
    assert "data-orch-role" not in ui and "ORCH_ROLES" not in ui and "orch-agent-rail" not in ui
    assert "accounting.html" not in ui and "label: 'Финансы'" in ui


def test_news_agent_page_ticker_and_api_contract():
    html = (AURORA / "news.html").read_text(encoding="utf-8")
    news = (AURORA / "assets" / "pages" / "news.js").read_text(encoding="utf-8")
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")

    assert "Никита · новостной аналитик" in html
    assert "renderAgentAnalysis" in news and "API.http.newsAnalysis" in news
    assert "news-agent-instruments" in html and "agentWhen" in news and "agentRelevance" in news
    assert "news-agent-details" in html and "детерминированный анализ · без токенов" not in news
    assert "news-agent-thumb-wrap" in html and "agentThumbHtml" in news
    assert "🧠 Никита:" not in news and "🧠 Никита:" not in ui
    assert "/api/ai-lab/news-analysis" in api


def test_aurora_chart_context_sparklines_and_ai_origin_badges_are_wired():
    charts = (AURORA / "assets" / "charts.js").read_text(encoding="utf-8")
    overview = (AURORA / "assets" / "pages" / "overview.js").read_text(encoding="utf-8")
    backtesting = (AURORA / "assets" / "pages" / "backtesting.js").read_text(encoding="utf-8")
    strategies = (AURORA / "assets" / "pages" / "strategies.js").read_text(encoding="utf-8")
    ai_lab = (AURORA / "assets" / "pages" / "ai-lab.js").read_text(encoding="utf-8")

    assert "canvas._barGeo" in charts and "tooltipLabel" in charts
    assert "function pnl(" in charts and "function price(" in charts
    assert "entry_time_utc" in charts and "exit_time_utc" in charts
    assert "canvas.onmousemove" in charts and "t-detail" in charts
    assert "tooltipLabel: String(row.label" in overview
    assert "data-report-spark" in backtesting and "API.http.jobTrades" in backtesting
    assert "ai-origin-badge" in backtesting and "ai-origin-ribbon" in strategies
    assert "Простой" not in ai_lab and "Цикл не запущен" in ai_lab


def test_connector_heartbeat_grace_is_not_rendered_as_running_or_active_account():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    overview = (AURORA / "assets" / "pages" / "overview.js").read_text(
        encoding="utf-8")
    status_block = ui[ui.index("function wireSystemStatus()"):
                      ui.index("async function action(")]

    assert "connector_confirmed_live" in status_block
    assert "NinjaTrader · ожидание" in status_block
    assert "NinjaTrader · OFF" in status_block
    assert "accounts.confirmed_live" in status_block
    assert "последние подтверждённые данные" in status_block
    assert "'NinjaTrader запущен'" not in status_block
    assert "connectorConfirmed" in overview


def test_runtime_strategy_adapter_uses_real_nested_contract():
    result = _domain_eval("""
      (() => {
        const strategy = AuroraDomain.normalizeRuntimeStrategy({
          strategy_id: 'managed-c007', display_name: 'Managed C007',
          registry_status: 'ready', runtime_enabled: true, runtime_detected: true,
          display_hidden: false, params_ok: true, source: 'runtime+registry',
          trade_window_pt: '06:35-10:00', trade_window: {windows:[{start:635,end:1000}]},
          runtime: {strategy_class:'ManagedClass', instrument:'MGC AUG26', account_name:'DEMO',
                    timeframe:'5 Minute', state:'Realtime', enabled:true,
                    position_market_position:'Flat', realized_pnl:12.5}
        }, new Date('2026-06-29T14:00:00Z'));
        return {strategy, operational:AuroraDomain.strategyOperationalState(strategy, {phase:'open'})};
      })()
    """)
    strategy = result["strategy"]
    assert strategy["enabled"] is True
    assert strategy["instrument"] == "MGC AUG26"
    assert strategy["className"] == "ManagedClass"
    assert strategy["external"] is False
    assert strategy["windowState"]["inWindow"] is True
    assert result["operational"]["kind"] == "working"


def test_ai_run_without_state_is_active_when_run_id_exists():
    result = _domain_eval("""
      (() => {
        const merged = AuroraDomain.mergeAiRunStatus(
          {run:{run_id:'RUN-1', current_experiment_id:'EXP-1', cancelled:false}},
          {current:{experiment_id:'EXP-1', status:'awaiting_compile'}}
        );
        return {merged, active:AuroraDomain.aiRunIsActive(merged), idle:AuroraDomain.aiRunIsActive(null)};
      })()
    """)
    assert result["active"] is True
    assert result["idle"] is False
    assert result["merged"]["status"] == "awaiting_compile"


def test_account_ledger_records_all_non_system_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(account_ledger, "LEDGER_PATH", tmp_path / "account_ledger.json")
    account_ledger.record_accounts({
        "online_accounts": [{"account_name": "Demo", "net_liquidation": 10}],
        "accounts": [
            {"account_name": "Demo", "net_liquidation": 10, "is_system": False},
            {"account_name": "Live", "net_liquidation": 20, "is_system": False},
            {"account_name": "Backtest", "net_liquidation": 100000, "is_system": True},
        ],
    })
    names = {row["account_name"] for row in account_ledger.account_history()["accounts"]}
    assert names == {"Demo", "Live"}


def test_account_ledger_ignores_position_only_balance_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(account_ledger, "LEDGER_PATH", tmp_path / "account_ledger.json")
    account_ledger.record_accounts({
        "source": "accounts_json",
        "accounts_generated_at_utc": "2026-06-28T20:00:00Z",
        "accounts": [{"account_name": "Demo", "net_liquidation": 10_000, "cash_value": 10_000}],
    })
    account_ledger.record_accounts({
        "source": "positions_fallback",
        "accounts_generated_at_utc": "2026-06-28T20:01:00Z",
        "accounts": [{"account_name": "Demo", "net_liquidation": 0, "cash_value": 0}],
    })
    account_ledger.record_accounts({
        "source": "accounts_json",
        "accounts_generated_at_utc": "2026-06-28T20:02:00Z",
        "accounts": [{"account_name": "Demo", "net_liquidation": 10_000, "cash_value": 10_000}],
    })
    row = account_ledger.account_history("Demo")["accounts"][0]
    assert len(row["snapshots"]) == 1
    assert row["events"] == []


def test_account_ledger_manual_and_imported_events_are_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(account_ledger, "LEDGER_PATH", tmp_path / "account_ledger.json")
    first = account_ledger.add_event("Demo", "deposit", 500, "tester", "funding", source_id="BROKER-1")
    duplicate = account_ledger.add_event("Demo", "deposit", 500, "tester", "funding", source_id="BROKER-1")
    imported = account_ledger.import_events("Demo", [
        {"at_utc": "2026-06-28T20:00:00Z", "kind": "withdrawal", "amount": 100, "source_id": "BROKER-2"},
        {"at_utc": "2026-06-28T20:01:00Z", "kind": "fee", "amount": 5, "source_id": "BROKER-3"},
    ], "tester")
    assert first["duplicate"] is False and duplicate["duplicate"] is True
    assert imported["imported"] == 2
    events = account_ledger.account_history("Demo")["accounts"][0]["events"]
    assert [event["amount"] for event in events] == [500, -100, -5]


def test_performance_time_breakdowns_keep_commission_aware_metrics():
    trades = [
        {"date_pt": "2026-06-22", "time_pt": "08:15", "direction": "long", "pnl": 90, "gross_pnl": 100, "commission": 10},
        {"date_pt": "2026-06-22", "time_pt": "09:20", "direction": "short", "pnl": -55, "gross_pnl": -50, "commission": 5},
        {"date_pt": "2026-06-23", "time_pt": "08:40", "direction": "long", "pnl": 37, "gross_pnl": 40, "commission": 3},
    ]
    result = performance._time_breakdowns(trades)
    assert result["daily"][0]["pnl"] == 35
    assert result["hourly"][0]["pnl"] == 127
    assert result["direction"][0]["commission"] == 13
    assert result["weekly"][0]["trades"] == 3


def test_performance_trade_detail_route_is_get(monkeypatch):
    monkeypatch.setattr(performance, "build_trades_response", lambda **kwargs: {"ok": True, "offset": kwargs["offset"], "limit": kwargs["limit"], "total": 0, "trades": []})
    srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/performance/trades?offset=10&limit=25", timeout=5) as response:
            payload = json.load(response)
        assert payload["ok"] is True
        assert payload["offset"] == 10 and payload["limit"] == 25
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_ai_model_telemetry_records_usage_and_aggregates(tmp_path, monkeypatch):
    log_dir = tmp_path / "prompts_log"
    log_dir.mkdir()
    monkeypatch.setattr(ai_paths, "PROMPTS_LOG_DIR", log_dir)
    monkeypatch.setattr(ai_paths, "ensure_dirs", lambda: None)
    captured = []
    monkeypatch.setattr(ai_lm_studio, "append_jsonl", lambda _path, row: captured.append(row))
    ai_lm_studio._log_round_trip(
        "EXP-1", "generate", "coder", "model-a", [{"role": "user", "content": "build"}],
        {"usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}},
        "response", 0, 2.5, None,
    )
    assert captured[0]["usage"]["total_tokens"] == 30
    assert captured[0]["success"] is True and captured[0]["response_chars"] == 8
    slower = dict(captured[0])
    slower["elapsed_sec"] = 10.0
    slower["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    (log_dir / "2026-06-28.jsonl").write_text(
        json.dumps(captured[0]) + "\n" + json.dumps(slower) + "\n", encoding="utf-8"
    )
    result = ai_read_model.model_performance(30)
    assert result["requests"] == 2
    assert result["models"][0]["model"] == "model-a"
    assert result["models"][0]["total_tokens"] == 30
    assert result["models"][0]["p95_latency_sec"] == 10.0
    assert result["roles"][0]["role"] == "coder"


def test_documents_page_has_privileged_compact_revision_journal_and_law_anchors():
    html = (AURORA / "documents.html").read_text(encoding="utf-8")
    js = (AURORA / "assets" / "pages" / "documents.js").read_text(encoding="utf-8")
    theme = (AURORA / "assets" / "theme.css").read_text(encoding="utf-8")
    assert "assets/pages/documents.js" in html
    assert "openAmendmentDrawer" in js
    assert "resolveAmendmentTarget" in js
    assert "parseLawIds" in js
    assert "doc-law-anchor" in js
    assert "data-amendment-no" in js
    assert "API.http.governanceRevisions" in js
    assert "Редакция №" in js
    assert "Было:" in js and "Стало:" in js
    assert "Подробнее" in js
    assert "edit-actor" not in html
    assert "saveDocument(current.id, { content, reason })" in js
    assert "Object.values(me.admin_capabilities).some(Boolean)" not in js
    assert "docs-privileged" in html
    assert "docs-journal-hidden" in html
    assert "style.gridTemplateColumns" not in js
    assert "classList.toggle('docs-privileged'" in js
    assert "classList.toggle('docs-journal-hidden'" in js
    assert "STATUS_PILL" in js
    assert "doc-tablewrap" in js and "listStack" in js
    assert "bq-lead" in js
    assert "Юридические документы (проекты)" in js
    assert js.count("badge: 'ПРОЕКТ'") >= 9
    assert ".doc .st-pill" in html
    assert ".doc .doc-tablewrap" in html
    assert ".rev-summary del" in html and "var(--neg)" in html
    assert ".rev-summary ins" in html and "var(--pos)" in html
    assert ".tl-item.clickable" in theme
    assert ".doc-law-highlight" in theme


def test_admin_panel_module_switching_uses_stale_render_guard():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "let renderSeq = 0;" in ui
    assert "const seq = ++renderSeq;" in ui
    assert "admin-module-render" in ui
    assert "moduleBody.replaceChildren(container);" in ui
    assert "await renderAdminModule(container, id, overview);" in ui
    assert "renderAdminModule(moduleBody, id, overview)" not in ui


def test_deliberate_page_cleanup_abort_never_surfaces_as_a_ui_error():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "function isAbortError(err)" in ui
    assert "/AbortError|signal is aborted/i.test(message)" in ui
    report = ui.split("function reportError(err)", 1)[1].split("\n  }", 1)[0]
    assert "if (isAbortError(err)) return;" in report
    assert report.index("if (isAbortError(err)) return;") < report.index("console.error('[UI]', err)")


def test_release_center_describes_real_executor_without_stale_dry_run_copy():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "function releaseAdapterSummary(adapter)" in ui
    assert "if (adapter.real_available)" in ui
    assert "Canary executor подключён и готов" in ui
    assert "Production остаётся заблокирован до отдельного подтверждения владельца" in ui
    assert "реальный executor не подключён, поэтому внешний результат остаётся PENDING" not in ui
    assert "function releaseBlueGreenSummary(detail)" in ui
    assert "Canary deploy и rollback rehearsal выполняются реальным executor" in ui
    assert "Проверить rollback в Canary (реально)" in ui
    assert "Реальный executor не подключён: expand→migrate→contract" not in ui


def test_desktop_removes_drawings_whose_backend_alert_was_deleted():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "aurora" / "assets" / "pages" / "desktop.js").read_text(encoding="utf-8")
    assert "!drawing.alertId || alertIds.has(drawing.alertId)" in js
    assert "if (changed || removed)" in js


def test_desktop_root_contracts_auto_roll_but_fixed_contracts_do_not():
    js = (AURORA / "assets" / "pages" / "desktop.js").read_text(encoding="utf-8")
    assert "m.config.contract_mode !== 'fixed'" in js
    assert "if (model.config.contract_mode === 'fixed') continue;" in js
    assert "config.contract_mode === 'auto' ? (config.root || config.instrument)" in js
    assert "source.name || 'NO DATA'" in js
    assert "age > 8" not in js
    assert "provider freshness limit" in js
    assert "rec.loadQueued" in js
    assert "loadWindowData(rec);" in js
    assert "rec.chart.appendBar(liveBar)" in js
    assert "rec.chart.setLivePriceEnabled(true)" in js
    assert "mergeFormingLiveBar" in js
    assert "rec.liveBarAt" in js
    assert "rec.node.dataset.marketWsPayload" in js
    assert "rec.node.dataset.externalLive" in js
    assert "rec.node.dataset.backendPriceMarkerLive" in js
    assert "rec.node.dataset.priceMarkerLive" in js
    assert "rec.node.dataset.providerConnectionState" in js
    assert "rec.node.dataset.lastBarClose" in js


def test_dense_desktop_grid_scales_virtual_windows_instead_of_overlapping_controls():
    js = (AURORA / "assets" / "pages" / "desktop.js").read_text(encoding="utf-8")
    assert "const GRID_COLUMNS" in js and "function gridShape(count)" in js
    assert "const minW = cols * MIN_W" in js
    assert "const minH = rows * MIN_H" in js
    assert "zoom = Math.min(1, s.w / minW, s.h / minH);" in js
    sync = js.split("async function syncInstrumentGrid", 1)[1].split("function openInstrumentPicker", 1)[0]
    grid_set = sync.index("layout.grid = layout.windows.length;")
    canvas_fit = sync.index("applyCanvas();", grid_set)
    assert grid_set < canvas_fit < sync.index("retileGrid();", grid_set)


def test_chart_live_price_marker_follows_latest_tick_not_candle_open():
    js = (AURORA / "assets" / "chart-engine.js").read_text(encoding="utf-8")

    assert "nextClose > previousClose ? 1 : -1" in js
    assert "this.livePriceDirection === 0" in js
    assert "this.livePriceDirection > 0" in js
    assert "this.host.dataset.renderedPriceMarkerText = label" in js
    assert "this.host.dataset.renderedPriceMarkerColor = tagColor" in js
    assert "this.host.dataset.renderedPriceMarkerLive = String(live)" in js


def test_desktop_preserves_backend_freshness_across_http_poll():
    js = (AURORA / "assets" / "pages" / "desktop.js").read_text(encoding="utf-8")
    html = (AURORA / "desktop.html").read_text(encoding="utf-8")

    assert "freshness: (res && res.freshness) || {}" in js
    assert "price_marker_live: !!(res && res.price_marker_live)" in js
    assert "const liveTransportFresh = topstepSource && marketDataWsOk && marketFeedFresh" in js
    assert "Date.now() - Number(rec.liveBarAt || 0) <= 15000 || liveTransportFresh" in js
    assert "desktop.js?v=20260813-live-marker-freshness1" in html


def test_command_language_covers_every_desktop_instrument():
    import re
    from app.ai_lab import command_language

    js = (AURORA / "assets" / "pages" / "desktop.js").read_text(encoding="utf-8")
    start = js.index("const DESKTOP_INSTRUMENTS")
    block = js[start:js.index("];", start) + 2]
    desktop_roots = set(re.findall(r"\['([A-Z0-9]+)'", block))
    assert desktop_roots <= set(command_language.INSTRUMENT_ROOTS)


def test_heartbeat_and_ipc_contracts():
    from app import runtime as ops_runtime
    from app import market_data_ipc

    # 1. Verify read_heartbeat payload contract
    hb = ops_runtime.read_heartbeat()
    expected_hb_keys = {
        "present", "fresh", "age_sec", "timestamp_utc", "ninja_version",
        "machine", "exporter_version", "state", "last_tick_at",
        "subscription_count", "active_contracts", "reconnect_count"
    }
    for key in expected_hb_keys:
        assert key in hb, f"Missing key {key} in heartbeat response"

    # 2. Verify market_data_ipc.metrics() payload contract
    ipc = market_data_ipc.metrics()
    expected_ipc_keys = {
        "last_tick_at", "subscription_count", "active_contracts",
        "event_rate", "dropped", "reconnect_count", "active_generation",
        "rejected_auth", "rejected_protocol"
    }
    for key in expected_ipc_keys:
        assert key in ipc, f"Missing key {key} in IPC metrics"


def test_victor_ui_exposes_durable_progress_workflow_and_selective_cleanup():
    js = (AURORA / "assets" / "victor.js").read_text(encoding="utf-8")
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    theme = (AURORA / "assets" / "theme.css").read_text(encoding="utf-8")
    assert "items_remaining" in js
    assert "progress_revision" in js
    assert "workflow.participants" in js
    assert "безопасный режим" in js
    assert "backend_instance_id" in js
    assert "data-cleanup-kinds" in js
    assert "vitekReconcile(true, kinds)" in js
    assert "vitekTaskProgress" in api
    assert ".btn:disabled" in theme
    assert "cursor: not-allowed" in theme


def test_backtesting_uses_template_commission_and_submits_without_browser_confirm():
    html = (AURORA / "backtesting.html").read_text(encoding="utf-8")
    js = (AURORA / "assets" / "pages" / "backtesting.js").read_text(
        encoding="utf-8"
    )

    assert 'id="f-commission-template"' in html
    assert 'id="f-commission"' not in html
    assert "renderCommissionTemplates();" in js
    assert "commission: 0" in js
    # Resolved through the guard rather than a bare || 'None', so a missing or
    # unsupported template cannot become "no commission" on the way out.
    assert "commission_template: commissionTemplateOrDefault(" in js
    assert "parseFloat(UI.qs('#f-commission').value)" not in js
    assert "confirm(`Запустить бэктест" not in js
    assert "confirm(`Запустить пакетный прогон" not in js
    assert "confirm('Повторить прогон" not in js


def test_backtesting_never_falls_back_to_zero_commission_silently():
    """The bridge applies commission only through a NinjaTrader template and
    rejects a numeric one, so the request always carries commission=0. That
    makes the template the only thing between a backtest and honest costs.

    A run that quietly defaulted to "None" would report a strategy as cheaper
    than it is, which is worse than refusing to run: the number looks real.
    """
    html = (AURORA / "backtesting.html").read_text(encoding="utf-8")
    js = (AURORA / "assets" / "pages" / "backtesting.js").read_text(encoding="utf-8")

    # The catalog default is a real template; None is only ever an explicit
    # choice, and it says out loud that the costs are not real.
    assert "function defaultCommissionTemplate()" in js
    assert "catalog.execution_defaults.commission_template" in js
    assert "Без комиссии" in js and "Без комиссии" in html
    assert 'id="f-commission-zero-note"' in html

    # Both submit paths resolve through the same guard rather than || 'None'.
    assert "commission_template: commissionTemplateOrDefault(" in js
    assert "commission_template: execution.commission_template || 'None'" not in js
    assert "UI.qs('#f-commission-template').value || 'None'" not in js


def test_backtesting_strategy_dropdown_uses_authoritative_device_catalog():
    html = (AURORA / "backtesting.html").read_text(encoding="utf-8")
    js = (AURORA / "assets" / "pages" / "backtesting.js").read_text(
        encoding="utf-8"
    )

    assert 'id="f-strategy-source-note"' in html
    assert "function renderStrategyCatalog()" in js
    assert "catalog && catalog.strategies" in js
    assert "catalog && catalog.device_catalog" in js
    assert "Каталог VMNINJA актуален" in js
    assert "device-стратегии не подтверждены" in js
    assert "API.http.strategies()" not in js
    assert "strategies = (strat && strat.strategies) || []" not in js
