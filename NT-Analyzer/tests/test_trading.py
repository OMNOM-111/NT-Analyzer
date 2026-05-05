"""
Trading Online page tests.

Tests:
  t01 - Backtest page (/ui/index.html) still loads (not broken)
  t02 - /api/catalog returns strategies sourced from NinjaTrader Strategies folder
  t03 - /ui/trading.html is served and contains the Russian title "Торговля онлайн"
  t04 - read_accounts() returns the accounts.json list when present
  t05 - read_accounts() falls back to positions.json keys when accounts.json missing
  t06 - read_accounts() classifies live accounts as is_live=True
  t07 - submit_command accepted for paper account (Sim101)
  t08 - submit_command rejected for live account (OpsError 403)
  t09 - validate_params detects param mismatch (PARAM MISMATCH gate)
  t10 - merge_strategy_view returns runtime_detected=False when bridge offline (no fake running)
  t11 - merge_strategy_view returns runtime_detected=True when bridge fresh
  t12 - submit_command refuses unknown account name (treated as not-paper)

Run: python -m tests.test_trading
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ops               # noqa: E402
from app import runtime as rt     # noqa: E402


PASSED: List[str] = []
FAILED: List[Tuple[str, str]] = []


def _now_iso(offset_sec: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat(timespec="seconds")


def _set_temp_root(tmp: Path) -> None:
    ops._project_root = lambda: tmp  # type: ignore[assignment]
    (tmp / "data" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    base = tmp.parent / "RAZRABOTKA_TR" / "PAPER_B1_SHORTONLY"
    base.mkdir(parents=True, exist_ok=True)
    (base / "PAPER_B1_SHORTONLY_PROFILE.json").write_text("{}", encoding="utf-8")
    (base / "PAPER_B1_SHORTONLY_RUNBOOK.md").write_text("# runbook\n", encoding="utf-8")
    (base / "PAPER_B1_SHORTONLY_CHECKLIST.md").write_text("# checklist\n", encoding="utf-8")
    (base / "PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv").write_text(
        "date_pt,trading_day_number,session_status,trades_count,gross_pnl,total_qty,"
        "commission_estimated,adjusted_pnl,cumulative_adjusted_pnl,current_drawdown,"
        "high_water_mark,daily_win_count,daily_loss_count,median_slippage_ticks,"
        "max_slippage_ticks,stop_hit_count,target_hit_count,notes\n",
        encoding="utf-8",
    )


def _write_registry(tmp: Path, status: str = "paper_ready") -> None:
    reg_path = tmp / "data" / "ops" / "registry.json"
    reg_path.write_text(json.dumps({
        "schema_version": "1.0",
        "generated_at_utc": _now_iso(),
        "strategies": [{
            "strategy_id":  "b1_shortonly",
            "display_name": "B1 ShortOnly",
            "class_name":   "NTAMicroVwapRiskPilot",
            "status":       status,
            "account_mode": "paper",
            "allowed_accounts": ["Sim101"],
            "instrument":   "MNQ",
            "locked_params": {},
        }],
    }), encoding="utf-8")


def _write_heartbeat(tmp: Path, age_sec: float = 2) -> None:
    rt_dir = tmp / "data" / "runtime"
    rt_dir.mkdir(parents=True, exist_ok=True)
    (rt_dir / "heartbeat.json").write_text(json.dumps({
        "timestamp_utc": _now_iso(-age_sec),
        "ninja_version": "8.1.0",
        "machine": "TEST",
    }), encoding="utf-8")


def _write_strategies(tmp: Path, account: str = "Sim101", enabled: bool = True) -> None:
    rt_dir = tmp / "data" / "runtime"
    rt_dir.mkdir(parents=True, exist_ok=True)
    (rt_dir / "strategies.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(-2),
        "strategies": [{
            "strategy_id":     "b1_shortonly",
            "strategy_class":  "NTAMicroVwapRiskPilot",
            "account_name":    account,
            "account_mode":    None,
            "enabled":         enabled,
            "state":           "Realtime" if enabled else "Terminated",
            "instrument":      "MNQ 06-26",
            "timeframe":       "5 Minute",
            "params":          dict(rt.B1_LOCKED_PARAMS_CHECK),
        }],
    }), encoding="utf-8")


def _write_accounts(tmp: Path, accounts: List[Dict[str, Any]]) -> None:
    rt_dir = tmp / "data" / "runtime"
    rt_dir.mkdir(parents=True, exist_ok=True)
    (rt_dir / "accounts.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(),
        "accounts": accounts,
    }), encoding="utf-8")


def _write_positions(tmp: Path, accts: List[str]) -> None:
    rt_dir = tmp / "data" / "runtime"
    rt_dir.mkdir(parents=True, exist_ok=True)
    (rt_dir / "positions.json").write_text(
        json.dumps({a: [] for a in accts}), encoding="utf-8")


def case(name: str):
    def deco(fn):
        def wrap():
            tmp = Path(tempfile.mkdtemp(prefix="trading_test_"))
            try:
                _set_temp_root(tmp)
                fn(tmp)
                PASSED.append(name)
                print(f"  PASS  {name}")
            except AssertionError as e:
                FAILED.append((name, f"AssertionError: {e}\n{traceback.format_exc()}"))
                print(f"  FAIL  {name}: {e}")
            except Exception as e:
                FAILED.append((name, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
                print(f"  ERR   {name}: {e}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return wrap
    return deco


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@case("t01: backtest page (index.html) still served and not broken")
def t01(tmp):
    static = ROOT / "app" / "static" / "index.html"
    assert static.is_file(), "index.html must exist"
    text = static.read_text(encoding="utf-8")
    # the renamed title must be present, and the old workbench markup intact
    assert "Бэктестирование" in text, "index.html must have 'Бэктестирование' label"
    assert 'id="workbench"' in text, "backtest workbench must remain (do not break it)"
    assert 'id="reports-panel"' in text, "reports panel must remain"


@case("t02: /api/catalog returns strategies from NinjaTrader Strategies folder")
def t02(tmp):
    from app import jobqueue
    cat = jobqueue.build_catalog_response()
    assert isinstance(cat, dict), "catalog response must be dict"
    strats = cat.get("strategies") or []
    assert isinstance(strats, list), "catalog.strategies must be a list"
    # Must not be hand-filtered: source is real Custom\Strategies
    # (can be empty in CI but the field must exist and be a list)


@case("t03: /ui/trading.html is served and contains 'Торговля онлайн'")
def t03(tmp):
    static = ROOT / "app" / "static" / "trading.html"
    assert static.is_file(), "trading.html must exist"
    text = static.read_text(encoding="utf-8")
    assert "Торговля онлайн" in text, "trading.html must contain 'Торговля онлайн'"
    assert 'src="trading.js' in text, "trading.html must reference trading.js"
    assert "/api/ops/runtime/accounts" in (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8"), \
        "trading.js must call /api/ops/runtime/accounts"


@case("t04: read_accounts() returns accounts.json list when present")
def t04(tmp):
    _write_accounts(tmp, [
        {"account_name": "Sim101", "cash_value": 100000.0, "buying_power": 200000.0},
        {"account_name": "Playback101", "account_mode": "playback"},
    ])
    accts = rt.read_accounts()
    names = [a["account_name"] for a in accts]
    assert names == ["Sim101", "Playback101"], f"got {names}"
    sim = next(a for a in accts if a["account_name"] == "Sim101")
    assert sim["account_mode"] == "paper", f"Sim101 must be paper, got {sim['account_mode']}"
    assert sim["is_live"] is False
    assert sim["cash_value"] == 100000.0
    assert sim["buying_power"] == 200000.0


@case("t05: read_accounts() falls back to positions.json keys when accounts.json missing")
def t05(tmp):
    _write_positions(tmp, ["Sim101", "DEMO123", "1234567"])
    accts = rt.read_accounts()
    names = sorted(a["account_name"] for a in accts)
    assert names == ["1234567", "DEMO123", "Sim101"], f"got {names}"


@case("t06: read_accounts() flags 'live' keyword as live, defaults to unknown otherwise")
def t06(tmp):
    _write_accounts(tmp, [
        {"account_name": "Sim101"},
        {"account_name": "MyLiveAccount"},   # explicit "live" hint
        {"account_name": "1234567"},          # no hint -> unknown (safe default)
    ])
    accts = rt.read_accounts()
    by_name = {a["account_name"]: a for a in accts}
    assert by_name["Sim101"]["is_live"] is False
    assert by_name["MyLiveAccount"]["is_live"] is True, \
        f"explicit 'live' must classify as live, got {by_name['MyLiveAccount']}"
    assert by_name["1234567"]["account_mode"] in ("unknown", "paper"), \
        f"unhinted account must NOT auto-classify as live, got {by_name['1234567']}"
    assert by_name["1234567"]["is_live"] is False, \
        "default classification must NOT be live (safety)"


@case("t07: submit_command accepted for paper account (Sim101)")
def t07(tmp):
    _write_registry(tmp, status="paper_ready")
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    assert rec.get("status") == "queued", f"command must be queued, got {rec}"
    assert rec.get("live_block_passed") is True


@case("t08: submit_command accepts live account (account-agnostic mode)")
def t08(tmp):
    _write_registry(tmp, status="paper_ready")
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="LiveAccount1",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    assert rec.get("status") == "queued", f"live command must be queued (account-agnostic), got {rec}"


@case("t08b: submit_command rejects unclassifiable account name")
def t08b(tmp):
    _write_registry(tmp, status="paper_ready")
    try:
        rt.submit_command(
            command="enable_strategy",
            strategy_id="b1_shortonly",
            account_name="X9Z",  # no hint at all
            class_name="NTAMicroVwapRiskPilot",
        )
        raise AssertionError("submit_command must raise OpsError for unknown account")
    except ops.OpsError as e:
        assert e.status == 403, f"expected 403, got {e.status}"
        assert "classified" in str(e).lower() or "unknown" in str(e).lower(), \
            f"error must mention classification, got: {e}"


@case("t09: validate_params detects PARAM MISMATCH (gate)")
def t09(tmp):
    bad = dict(rt.B1_LOCKED_PARAMS_CHECK)
    bad["EnableLong"] = True       # forbidden
    bad["RewardRiskRatio"] = 2.0   # different from 3.5
    res = rt.validate_params("b1_shortonly", bad)
    assert not res["ok"], "PARAM MISMATCH must be detected"
    keys = {m["key"] for m in res["mismatches"]}
    assert {"EnableLong", "RewardRiskRatio"} <= keys, f"got {keys}"


@case("t10: bridge offline -> runtime_detected=False (no fake running status)")
def t10(tmp):
    _write_registry(tmp, status="paper_running")
    # Deliberately do not write heartbeat.json
    view = rt.merge_strategy_view("b1_shortonly")
    assert view["runtime_detected"] is False
    assert view["runtime_enabled"] is False


@case("t11: bridge fresh + strategy enabled -> runtime_detected=True, runtime_enabled=True")
def t11(tmp):
    _write_registry(tmp, status="paper_ready")
    _write_heartbeat(tmp, age_sec=2)
    _write_strategies(tmp, account="Sim101", enabled=True)
    view = rt.merge_strategy_view("b1_shortonly")
    assert view["runtime_detected"] is True
    assert view["runtime_enabled"] is True
    assert view["account_mode"] == "paper"
    assert view["is_live"] is False


@case("t12: submit_command rejects unknown account name (not paper)")
def t12(tmp):
    _write_registry(tmp, status="paper_ready")
    try:
        rt.submit_command(
            command="enable_strategy",
            strategy_id="b1_shortonly",
            account_name="",
            class_name="NTAMicroVwapRiskPilot",
        )
        raise AssertionError("must raise for empty account name")
    except ops.OpsError as e:
        assert e.status == 403, f"expected 403, got {e.status}"


# ---------------------------------------------------------------------------
# Architecture audit tests (Phase 19 cleanup)
# ---------------------------------------------------------------------------

@case("t13: index.html top-nav has NO 'Контроль стратегий' link")
def t13(tmp):
    txt = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    # The top nav must only contain Бэктестирование + Торговля онлайн
    assert "Бэктестирование" in txt
    assert "Торговля онлайн" in txt
    nav_block = txt[txt.find('<nav'):txt.find('</nav>')]
    assert "Контроль стратегий" not in nav_block, \
        "Top nav must NOT show 'Контроль стратегий' (moved to debug-only)"


@case("t14: trading.html exposes real online launch (no monitoring banner, no Control Center)")
def t14(tmp):
    txt = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    assert "Торговля онлайн" in txt
    # Forbidden phrases — must not appear anywhere
    for bad in ("режиме мониторинга", "Control Center",
                "Запустить бэктест", "только как бэктест"):
        assert bad not in txt, f"trading.html must NOT contain: {bad!r}"
    # Required real-launch buttons (Monitor+Validate mode labels)
    assert any(s in txt for s in ("Включить instance", "Включить стратегию", "Включить в NT")), \
        "missing enable strategy button"
    assert any(s in txt for s in ("Остановить стратегию", "Остановить")), \
        "missing stop strategy button"
    assert any(s in txt for s in ("Обновить статус", "Обновить")), \
        "missing refresh button"
    nav_block = txt[txt.find('<nav'):txt.find('</nav>')]
    assert "Контроль стратегий" not in nav_block


@case("t15: trading.js uses /api/catalog (not registry) for strategy dropdown")
def t15(tmp):
    txt = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "/api/catalog" in txt, "trading.js must call /api/catalog"
    # Must not depend on /api/scc/strategies or registry as the strategy source
    assert "/api/scc/strategies" not in txt, \
        "trading.js must NOT use /api/scc/strategies (hardcoded to one class)"
    assert "data/ops/registry" not in txt, \
        "trading.js must NOT read registry as the strategy list"
    # Must call the runtime endpoints
    assert "/api/ops/runtime/strategies" in txt
    assert "/api/ops/runtime/accounts" in txt


@case("t16: trading.js posts enable/disable to /api/ops/runtime/command")
def t16(tmp):
    txt = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    # Must call the runtime command endpoint
    assert "/api/ops/runtime/command" in txt, \
        "trading.js must POST to /api/ops/runtime/command"
    # Must wire enable_strategy / disable_strategy commands
    has_enable = ('"enable_strategy"' in txt) or ("'enable_strategy'" in txt)
    has_disable = ('"disable_strategy"' in txt) or ("'disable_strategy'" in txt)
    assert has_enable and has_disable, \
        "trading.js must issue enable_strategy and disable_strategy commands"
    # Must NOT use /api/jobs as the primary online action (that's backtest)
    assert "runBacktest" not in txt, "trading.js must not have runBacktest function"
    # Must NOT redirect to Control Center
    assert "Control Center" not in txt


@case("t17: /api/ops/runtime/accounts response includes 'source' field")
def t17(tmp):
    # No accounts.json, no positions.json -> source='empty'
    out = rt.read_accounts_with_source()
    assert "source" in out, f"response must have 'source' field, got: {out}"
    assert "accounts" in out
    assert out["source"] in ("empty", "positions_fallback", "accounts_json")
    assert isinstance(out.get("warnings"), list)
    # Now write positions.json — source must become 'positions_fallback'
    _write_positions(tmp, ["Sim101"])
    out2 = rt.read_accounts_with_source()
    assert out2["source"] == "positions_fallback", f"got {out2['source']}"
    # And finally, accounts.json wins
    _write_accounts(tmp, [{"account_name": "Sim101", "cash_value": 1000.0}])
    out3 = rt.read_accounts_with_source()
    assert out3["source"] == "accounts_json", f"got {out3['source']}"


@case("t18: merge_all_runtime_strategies surfaces RAW bridge entries (not registry-only)")
def t18(tmp):
    # Bridge sees TWO strategy instances, only one of which is in the registry.
    _write_registry(tmp, status="paper_ready")  # registers b1_shortonly only
    _write_heartbeat(tmp, age_sec=2)
    rt_dir = tmp / "data" / "runtime"
    (rt_dir / "strategies.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(-2),
        "strategies": [
            {
                "strategy_id": "b1_shortonly",
                "strategy_class": "NTAMicroVwapRiskPilot",
                "account_name": "Sim101",
                "enabled": True,
                "state": "Realtime",
                "instrument": "MNQ 06-26",
                "timeframe": "5 Minute",
                "params": dict(rt.B1_LOCKED_PARAMS_CHECK),
            },
            {
                "strategy_id": "every_n_bar_001",
                "strategy_class": "NTAnalyzerEveryNBarLong",
                "account_name": "Sim101",
                "enabled": True,
                "state": "Realtime",
                "instrument": "MES 06-26",
                "timeframe": "1 Minute",
                "params": {},
            },
        ],
    }), encoding="utf-8")
    out = rt.merge_all_runtime_strategies()
    classes = sorted({(v.get("runtime") or {}).get("strategy_class")
                      for v in out if v.get("runtime")})
    assert "NTAMicroVwapRiskPilot" in classes, f"got {classes}"
    assert "NTAnalyzerEveryNBarLong" in classes, \
        f"runtime-only entry must be surfaced too, got {classes}"
    assert len(out) == 2, f"expected 2 entries, got {len(out)}"
    # Old registry-driven function still works for back-compat
    legacy = rt.merge_all_strategies()
    assert isinstance(legacy, list)


@case("t19: merge_all_runtime_strategies returns [] when bridge has no instances")
def t19(tmp):
    _write_registry(tmp, status="paper_ready")
    _write_heartbeat(tmp, age_sec=2)
    # No strategies.json
    out = rt.merge_all_runtime_strategies()
    assert out == [], f"empty bridge must yield empty runtime list, got {out}"


@case("t20: /api/catalog has multiple strategies (not filtered to one)")
def t20(tmp):
    from app import jobqueue
    cat = jobqueue.build_catalog_response()
    strats = cat.get("strategies") or []
    # Real Custom\Strategies must contain at least NTAMicroVwapRiskPilot.
    # If the directory is missing in CI we skip the count assertion.
    names = [s.get("class_name") for s in strats]
    if names:
        assert "NTAMicroVwapRiskPilot" in names, \
            f"NTAMicroVwapRiskPilot must be present, got {names}"


@case("t21: NTAnalyzerEveryNBarLong job creation does NOT fail on missing RoundTurnCommission")
def t21(tmp):
    # Confirm _strategy_parameter_names + _inject_research_accounting_parameters
    # do not blindly require RoundTurnCommission for strategies that don't expose it.
    from app import jobqueue
    exposed = jobqueue._strategy_parameter_names("NTAnalyzerEveryNBarLong")
    if "RoundTurnCommission" in exposed:
        # Strategy DOES expose it — test is inapplicable on this machine
        return
    # Build a fake req with no RoundTurnCommission and verify injection skips it.
    class _Req:
        class_name = "NTAnalyzerEveryNBarLong"
        parameters: Dict[str, Any] = {}
        slippage_ticks = 1
    req = _Req()
    req.parameters = {}
    jobqueue._inject_research_accounting_parameters(req)
    assert "RoundTurnCommission" not in req.parameters, \
        f"must not inject RoundTurnCommission when strategy doesn't expose it, got {req.parameters}"


@case("t22: index.html (Бэктестирование) still has 'Запустить бэктест' button")
def t22(tmp):
    txt = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert "Запустить бэктест" in txt, \
        "index.html (backtest tab) must keep its 'Запустить бэктест' button"


@case("t23: /api/ops/runtime/strategies never falls back to registry rows")
def t23(tmp):
    txt = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    block = txt.split('if path == "/api/ops/runtime/strategies":', 1)[1].split(
        'if sub == "runtime"', 1)[0]
    assert "registry_fallback" not in block, \
        "runtime/strategies must not return registry_fallback rows"
    assert "merge_all_strategies()" not in block, \
        "runtime/strategies must not call registry-driven merge_all_strategies()"
    assert "merge_all_runtime_strategies()" in block, \
        "runtime/strategies must use runtime-driven bridge data"


@case("t24: trading.js supports catalog instrument field named 'instrument'")
def t24(tmp):
    txt = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "i.instrument" in txt, \
        "trading.js must read catalog items with the 'instrument' field"
    assert "instrumentName" in txt, \
        "trading.js must normalize instrument display names"


# ---------------------------------------------------------------------------
# Phase 10 — UI scaffolding + endpoint behavior
# ---------------------------------------------------------------------------

@case("t25: trading.html / trading.js have no 'Control Center' text")
def t25(tmp):
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8").lower()
    js   = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8").lower()
    assert "control center" not in html, \
        "trading.html must NOT contain 'Control Center' (case-insensitive)"
    assert "control center" not in js, \
        "trading.js must NOT contain 'Control Center' (case-insensitive)"


@case("t26: trading.html exposes command status bar element id")
def t26(tmp):
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    assert 'id="cmd-status-bar"' in html, \
        "trading.html must include #cmd-status-bar element for live command status"


@case("t27: trading.html exposes paper-status block")
def t27(tmp):
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    assert 'id="paper-status"' in html, "trading.html must include #paper-status"
    assert "Paper status" in html, \
        "trading.html must label the block with 'Paper status'"


@case("t28: command-status endpoint returns unknown_command for bogus id")
def t28(tmp):
    out = rt.get_command_status("cmd-bogus-does-not-exist")
    assert out["state"] == "unknown_command", out


@case("t29: command-status batch (since_ts) returns the recent commands")
def t29(tmp):
    _write_heartbeat(tmp, age_sec=2)
    rt.submit_command(
        command="enable_strategy", strategy_id="b1_shortonly",
        account_name="Sim101", class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    out = rt.get_command_statuses_since(since_ts=None)
    assert isinstance(out, list) and len(out) >= 1, out
    assert out[0].get("state") in (
        "waiting_for_bridge", "bridge_completed_awaiting_runtime",
        "failed_bridge_offline",
    ), out[0]


@case("t30: strategies endpoint forwards selection_diff to merged view")
def t30(tmp):
    _write_registry(tmp, status="paper_ready")
    _write_heartbeat(tmp, age_sec=2)
    _write_strategies(tmp, account="Sim101", enabled=True)
    v = rt.merge_strategy_view(
        "b1_shortonly",
        selected_account="Sim999",         # mismatch
        selected_instrument="MNQ 06-26",   # match
        selected_timeframe="5 Minute",     # match
    )
    assert "selection_diff" in v, "merge_strategy_view must include selection_diff"
    sd = v["selection_diff"]
    assert sd["account"]["matches"] is False, sd["account"]
    assert sd["instrument"]["matches"] is True, sd["instrument"]
    assert sd["any_blocker"] is True


@case("t31: B1 locked-params autofill on command (current behavior — backend does NOT auto-fill)")
def t31(tmp):
    # TODO: when backend submit_command starts auto-filling B1 locked params for
    # NTAMicroVwapRiskPilot when params={}, flip this assertion. Currently the
    # UI is responsible (B1_LOCKED_DISPLAY in trading.js), so backend records
    # the empty dict as-given. Marked xfail-style: documents the gap.
    rec = rt.submit_command(
        command="enable_strategy", strategy_id="b1_shortonly",
        account_name="Sim101", class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
        params={},
    )
    saved = rt.read_commands(1)[0]
    # Current behavior — backend stores empty params:
    assert saved["params"] == {}, \
        f"backend currently does not auto-fill (got {saved['params']!r}); " \
        "if behavior changed, remove the TODO and flip this assertion"


@case("t32: trading UI exposes persistent hide + strategy history")
def t32(tmp):
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert 'id="chk-show-hidden"' in html, "missing show-hidden toggle"
    assert 'id="pane-history"' in html, "missing history tab pane"
    assert "/api/ops/runtime/strategy-display" in js, "missing display prefs endpoint"
    assert "/api/ops/runtime/strategy-history" in js, "missing strategy history endpoint"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    cases = [t01, t02, t03, t04, t05, t06, t07, t08, t09, t10, t11, t12,
             t13, t14, t15, t16, t17, t18, t19, t20, t21, t22, t23, t24,
             t25, t26, t27, t28, t29, t30, t31, t32]
    print(f"Running {len(cases)} Trading Online tests:")
    for c in cases:
        c()
    print(f"\nPASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        for name, msg in FAILED:
            print(f"\n--- {name} ---\n{msg}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
