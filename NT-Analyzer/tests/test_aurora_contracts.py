from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

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
        assert 'src="assets/domain.js' in html, page.name
        assert html.index('src="assets/domain.js') < html.index('src="assets/ui.js'), page.name


def test_live_static_handler_routes_csp_and_assets():
    srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address
    base = f"http://{host}:{port}"
    try:
        for path, marker in (
            ("/ui/", "Обзор"),
            ("/ui/legacy/", "Бэктестирование"),
            ("/ui/assets/domain.js", "AuroraDomain"),
        ):
            with urllib.request.urlopen(base + path, timeout=5) as response:
                body = response.read().decode("utf-8")
                assert response.status == 200
                assert marker in body
                assert "script-src 'self'" in response.headers["Content-Security-Policy"]

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


def test_aurora_chart_context_sparklines_and_ai_origin_badges_are_wired():
    charts = (AURORA / "assets" / "charts.js").read_text(encoding="utf-8")
    overview = (AURORA / "assets" / "pages" / "overview.js").read_text(encoding="utf-8")
    backtesting = (AURORA / "assets" / "pages" / "backtesting.js").read_text(encoding="utf-8")
    strategies = (AURORA / "assets" / "pages" / "strategies.js").read_text(encoding="utf-8")
    ai_lab = (AURORA / "assets" / "pages" / "ai-lab.js").read_text(encoding="utf-8")

    assert "canvas._barGeo" in charts and "tooltipLabel" in charts
    assert "canvas.onmousemove" in charts and "t-detail" in charts
    assert "tooltipLabel: String(row.label" in overview
    assert "data-report-spark" in backtesting and "API.http.jobTrades" in backtesting
    assert "AI стратегия" in backtesting and "ai-origin-ribbon" in strategies
    assert "Простой" not in ai_lab and "Цикл не запущен" in ai_lab


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
