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
import os
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


def _set_temp_root(tmp: Path):
    original_project_root = ops._project_root
    original_data_root = os.environ.get("NTA_DATA_ROOT")
    original_dev_root = os.environ.get("NTA_STAGING_DATA_ROOT")
    os.environ["NTA_DATA_ROOT"] = str(tmp / "data")
    os.environ["NTA_STAGING_DATA_ROOT"] = str(tmp / "development-data")
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

    def restore() -> None:
        ops._project_root = original_project_root  # type: ignore[assignment]
        if original_data_root is None:
            os.environ.pop("NTA_DATA_ROOT", None)
        else:
            os.environ["NTA_DATA_ROOT"] = original_data_root
        if original_dev_root is None:
            os.environ.pop("NTA_STAGING_DATA_ROOT", None)
        else:
            os.environ["NTA_STAGING_DATA_ROOT"] = original_dev_root

    return restore


def _write_registry(tmp: Path, status: str = "paper_ready") -> None:
    reg_path = tmp / "data" / "ops" / "registry.json"
    reg_path.write_text(json.dumps({
        "schema_version": "1.0",
        "generated_at_utc": _now_iso(),
        "strategies": [{
            "strategy_id":  "b1_shortonly",
            "display_name": "VWAP Short MNQ 5m v1 c011",
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


def _write_runtime_jsonl(tmp: Path, name: str, rows: List[Dict[str, Any]]) -> None:
    rt_dir = tmp / "data" / "runtime"
    rt_dir.mkdir(parents=True, exist_ok=True)
    (rt_dir / name).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def case(name: str):
    def deco(fn):
        def wrap():
            tmp = Path(tempfile.mkdtemp(prefix="trading_test_"))
            restore = _set_temp_root(tmp)
            try:
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
                restore()
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
    by_cls = {s.get("class_name"): s for s in strats if isinstance(s, dict)}
    expected_names = {
        "VWAPPullbackMGC5mV1": "Scalping Gold MGC 5m v1 c001",
        "B1ShortOnlyMGC5mV2": "B1 ShortOnly MGC 5m v2 c002",
        "NTAMnqMicroOrbOpenScalp": "Scalping MNQ 1m v1 c012",
        "PullbackMNQ5mV2": "Pullback MNQ 5m v2",
        "StrategiyaUrovney": "Стратегия уровней",
    }
    for cls, expected in expected_names.items():
        if cls in by_cls:
            got = by_cls[cls].get("display_name")
            assert got == expected, f"{cls} display_name mismatch: got {got!r}, expected {expected!r}"


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
    assert by_name["MyLiveAccount"]["is_selectable_for_online"] is False, \
        f"live must be read-only, got {by_name['MyLiveAccount']}"
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


@case("t08: submit_command rejects live account")
def t08(tmp):
    _write_registry(tmp, status="paper_ready")
    try:
        rt.submit_command(
            command="enable_strategy",
            strategy_id="b1_shortonly",
            account_name="LiveAccount1",
            class_name="NTAMicroVwapRiskPilot",
            instrument="MNQ 06-26",
        )
        raise AssertionError("submit_command must raise OpsError for live account")
    except ops.OpsError as e:
        assert e.status == 403, f"expected 403, got {e.status}"
        assert "live" in str(e).lower(), f"error must mention live, got: {e}"


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
    catalog_dir = tmp / "data" / "catalog"
    sources_dir = tmp / "sources"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    alpha = sources_dir / "NTAAlpha.cs"
    beta = sources_dir / "NTABeta.cs"
    rejected = sources_dir / "NTAMicroVwapRiskPilot.cs"
    alpha.write_text('Name = "NTA Alpha";\n', encoding="utf-8")
    beta.write_text('Name = "NTA Beta";\n', encoding="utf-8")
    rejected.write_text('Name = "Rejected C011";\n', encoding="utf-8")
    (catalog_dir / "strategies.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(),
        "strategies": [
            {"class_name": "NTAAlpha", "display_name": "NTAAlpha", "source_file": str(alpha)},
            {"class_name": "NTABeta", "display_name": "NTABeta", "source_file": str(beta)},
            {"class_name": "NTAMicroVwapRiskPilot", "display_name": "Rejected C011", "source_file": str(rejected)},
        ],
    }), encoding="utf-8")
    (tmp / "data" / "ops" / "scc_classes.json").write_text(json.dumps({
        "rejected": ["NTAMicroVwapRiskPilot"],
    }), encoding="utf-8")

    saved_project_root = jobqueue.project_root
    jobqueue.project_root = lambda: tmp  # type: ignore[assignment]
    try:
        cat = jobqueue.build_catalog_response()
    finally:
        jobqueue.project_root = saved_project_root  # type: ignore[assignment]
    strats = cat.get("strategies") or []
    names = [s.get("class_name") for s in strats]
    if names:
        assert len(names) > 1, f"catalog must not collapse to one strategy, got {names}"
        assert "NTAMicroVwapRiskPilot" not in names, \
            f"decommissioned C011 class must be filtered from catalog, got {names}"


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


@case("t26a: trading UI exposes reconnect modeling control")
def t26a(tmp):
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert 'id="btn-reconnect-sim"' in html, "trading.html must expose the reconnect button"
    assert 'command: "reconnect_account"' in js, "trading.js must queue reconnect_account"
    assert 'confirmed_connected' in js, "trading.js must render reconnect confirmation state"


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


@case("t31: backend autofills locked params on enable_strategy when caller sends none")
def t31(tmp):
    rec = rt.submit_command(
        command="enable_strategy", strategy_id="b1_shortonly",
        account_name="Sim101", class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
        params={},
    )
    saved = rt.read_commands(1)[0]
    assert saved["params"]["EnableLong"] is False, saved["params"]
    assert saved["params"]["EnableShort"] is True, saved["params"]
    assert saved["params"]["RewardRiskRatio"] == 3.5, saved["params"]
    assert saved["params"]["TradeEndTime"] == 700, saved["params"]


@case("t32: trading UI exposes persistent hide + strategy history")
def t32(tmp):
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert 'id="chk-show-hidden"' in html, "missing show-hidden toggle"
    assert 'id="pane-history"' not in html, "strategy history must be hidden from bottom tabs"
    assert "/api/ops/runtime/strategy-display" in js, "missing display prefs endpoint"
    assert "/api/ops/runtime/strategy-history" in js, "missing strategy history endpoint"
    assert "/api/ops/runtime/history?limit=1000" in js, "runtime sessions must still feed strategy work-time analytics"
    assert "/api/ops/strategy-start-dates" in js, "strategy start-date registry must feed per-strategy all-time stats"


@case("t33: strategies page is served and wired to profile/coverage/runtime data")
def t33(tmp):
    html = (ROOT / "app" / "static" / "strategies.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    index = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    trading = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    assert "Стратегии" in html, "strategies.html must contain the new section title"
    assert 'id="strategies-page"' in html, "strategies page root must exist"
    assert 'src="strategies.js' in html, "strategies.html must reference strategies.js"
    assert "/api/profiles" in js, "strategies.js must load Strategy Profiles"
    assert "/api/coverage" in js, "strategies.js must load instrument coverage"
    assert "/api/catalog" in js, "strategies.js must load catalog strategy classes"
    assert "/api/ops/runtime/strategies" in js, "strategies.js must load runtime status"
    assert "strategies.html" in index, "Backtesting top nav must link to Strategies"
    assert "strategies.html" in trading, "Trading top nav must link to Strategies"


@case("t34: stale catalog source path resolves from NT-Analyzer_strategies")
def t34(tmp):
    import unittest.mock as mock
    from app import jobqueue

    nt_user = tmp / "NTUser"
    preferred_file = (
        nt_user / "bin" / "Custom" / "Strategies" / "NT-Analyzer_strategies" /
        "NTAMicroVwapRiskPilot" / "NTAMicroVwapRiskPilot.cs"
    )
    preferred_file.parent.mkdir(parents=True, exist_ok=True)
    preferred_file.write_text("// moved strategy\n", encoding="utf-8")
    stale_catalog_file = (
        nt_user / "bin" / "Custom" / "Strategies" /
        "NTAMicroVwapRiskPilot" / "NTAMicroVwapRiskPilot.cs"
    )

    with mock.patch.object(jobqueue, "ninjatrader_user_dir", return_value=nt_user):
        resolved = jobqueue._resolve_strategy_source_file(
            "NTAMicroVwapRiskPilot",
            str(stale_catalog_file),
        )

    assert resolved == str(preferred_file), f"expected moved file path, got {resolved!r}"


@case("t35: portfolio cell ids keep legacy 001-120 stable while extra slots append after 120")
def t35(tmp):
    from app import portfolio_cells

    cell_ids = [
        portfolio_cells.cell_id_for(root, slot)
        for root in portfolio_cells.PORTFOLIO_ROOT_ORDER
        for slot in range(1, portfolio_cells.TARGET_PORTFOLIO_SLOTS + 1)
    ]

    assert len(cell_ids) == 180, f"expected 180 cell ids, got {len(cell_ids)}"
    assert len(set(cell_ids)) == 180, "cell ids must be unique across the full matrix"
    assert cell_ids[0] == "CELL-001", f"first cell id mismatch: {cell_ids[0]!r}"
    assert cell_ids[9] == "CELL-010", f"legacy MGC slot 10 mismatch: {cell_ids[9]!r}"
    assert portfolio_cells.cell_id_for("MNQ", 1) == "CELL-011"
    assert portfolio_cells.cell_id_for("MNQ 06-26", 10) == "CELL-020"
    assert portfolio_cells.cell_id_for("MGC", 11) == "CELL-121"
    assert portfolio_cells.cell_id_for("MNQ", 11) == "CELL-126"
    assert portfolio_cells.cell_id_for("MYM", 15) == "CELL-180"
    assert portfolio_cells.slot_for_cell_id("CELL-121", "MGC") == 11
    assert portfolio_cells.slot_for_cell_id("CELL-126", "MNQ") == 11
    assert portfolio_cells.root_for_cell_id("CELL-180") == "MYM"


@case("t36: profiles and job reports surface portfolio cell metadata")
def t36(tmp):
    from app import jobqueue

    jobqueue.project_root = lambda: tmp  # type: ignore[assignment]
    jobqueue.reset_caches()

    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.1",
        "profiles": [
            {
                "profile_id": "mgc_ready_v1",
                "name": "Scalping Gold MGC 5m v1 c001",
                "strategy_class": "VWAPPullbackMGC5mV1",
                "instrument": "MGC 06-26",
                "timeframe": "5 Minute",
                "status": "ready",
            },
            {
                "profile_id": "mnq_ready_v1",
                "name": "VWAP Short MNQ 5m v1 c011",
                "strategy_class": "NTAMicroVwapRiskPilot",
                "instrument": "MNQ 06-26",
                "timeframe": "5 Minute",
                "status": "ready",
            },
        ],
    }), encoding="utf-8")

    catalog_dir = tmp / "data" / "catalog"
    sources_dir = tmp / "sources"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    mnq_source = sources_dir / "NTAMicroVwapRiskPilot.cs"
    mgc_source = sources_dir / "VWAPPullbackMGC5mV1.cs"
    mnq_source.write_text('Name = "VWAP Short MNQ 5m v1 c011";\n', encoding="utf-8")
    mgc_source.write_text('Name = "Scalping Gold MGC 5m v1 c001";\n', encoding="utf-8")
    (catalog_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.0",
        "strategies": [
            {
                "class_name": "NTAMicroVwapRiskPilot",
                "display_name": "VWAP Short MNQ 5m v1 c011",
                "source_file": str(mnq_source),
            },
            {
                "class_name": "VWAPPullbackMGC5mV1",
                "display_name": "Scalping Gold MGC 5m v1 c001",
                "source_file": str(mgc_source),
            },
        ],
    }), encoding="utf-8")

    profiles = jobqueue.read_strategy_profiles().get("profiles") or []
    by_id = {p.get("profile_id"): p for p in profiles}
    assert by_id["mgc_ready_v1"]["cell_id"] == "CELL-001"
    assert by_id["mgc_ready_v1"]["slot"] == 1
    assert by_id["mnq_ready_v1"]["cell_id"] == "CELL-011"
    assert by_id["mnq_ready_v1"]["slot"] == 1

    req = jobqueue.CreateJobRequest(
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
        bars_period_type="Minute",
        bars_period_value=5,
        from_utc="2024-01-01T00:00:00Z",
        to_utc="2024-01-31T00:00:00Z",
        parameters={},
    )
    job_id, pending_dir = jobqueue.create_job(req)
    assert job_id, "job_id must be created"
    job_doc = json.loads((pending_dir / "job.json").read_text(encoding="utf-8"))
    assert job_doc["portfolio"]["cell_id"] == "CELL-011"
    assert job_doc["portfolio"]["slot"] == 1
    assert job_doc["strategy"]["cell_id"] == "CELL-011"
    assert job_doc["strategy"]["slot"] == 1


@case("t37: strategies UI removes x10 header and renders cell identifiers")
def t37(tmp):
    html = (ROOT / "app" / "static" / "strategies.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")

    assert "Инструменты x 10 стратегий" not in html, "old x10 matrix heading must be removed"
    assert "portfolioCellId" in js, "strategies.js must compute deterministic cell ids"
    assert "strategy-cell-id" in js, "matrix cells must render a visible cell id label"
    assert "Ячейка:" in js, "detail panel must show the selected cell id"
    assert "Семья (root)" in js, "matrix first column must use root-family terminology"
    assert "Семья (root):" in js, "matrix tooltips must use root-family terminology"
    assert "profileFreeze" in js and "Закрыто" in js, "closed paper-freeze profiles must render explicit closed text"
    assert "strategy-cell.closed" in css, "closed paper-freeze cells must have a red matrix style"


@case("t38: strategies slot assignment guards against duplicate family placement")
def t38(tmp):
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")
    html = (ROOT / "app" / "static" / "strategies.html").read_text(encoding="utf-8")

    assert "const assignedKeys = new Set();" in js, "slot assignment must track already placed families"
    assert "assignedKeys.has(family.key)" in js, "slot assignment must skip already placed families"
    assert "strategy-cell.approved" in css, "ready-but-offline strategies must use a non-green matrix style"
    assert "c001" in html, "name template must mention cell suffix examples"


@case("t39: strategies UI documents a compact canonical profile naming rule")
def t39(tmp):
    html = (ROOT / "app" / "static" / "strategies.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")

    assert "<code>ИмяСтратегии Инструмент Таймфрейм vN cNNN</code>" in html, \
        "strategies page must show the full naming template including cell suffix"
    assert "пример: Scalping MNQ 5m v1 c001" in html, \
        "strategies page must show a concrete cNNN example"
    assert "номер ячейки" in html, "strategies page must explain that cNNN is the cell number"
    assert "Единый словарь префиксов" not in html, \
        "strategies page must not clutter the task block with the prefix dictionary"
    assert "suffix <code>cNNN</code> обязателен" not in html, \
        "strategies page must not keep the old long naming-policy paragraph"
    assert "APPROVED_PROFILE_FAMILY_PREFIXES" in js, "strategies.js must keep an approved prefix registry"
    assert "PROFILE_DISPLAY_NAME_RE" in js, "strategies.js must validate rename format"
    assert "Ожидаемое имя для этой версии" in js, "rename prompt must show the canonical expected name"


@case("t40: catalog hides internal explorers and synthesizes deploy wrappers from profiles")
def t40(tmp):
    import unittest.mock as mock
    from app import jobqueue

    jobqueue.project_root = lambda: tmp  # type: ignore[assignment]
    jobqueue.reset_caches()

    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.1",
        "profiles": [
            {
                "profile_id": "mgc_b1_shortonly_5m_paper_v2",
                "name": "B1 ShortOnly MGC 5m v2 c002",
                "strategy_class": "NTAMicroVwapRiskExplorer",
                "deploy_strategy_class": "B1ShortOnlyMGC5mV2",
                "runtime_strategy_classes": [
                    "NTAMicroVwapRiskExplorer",
                    "B1ShortOnlyMGC5mV2",
                ],
                "runtime_strategy_id": "mgc_b1_short_5m_v2",
                "instrument": "MGC 06-26",
                "timeframe": "5 Minute",
                "status": "ready",
            },
        ],
    }), encoding="utf-8")

    nt_user = tmp / "NTUser"
    base_file = (
        nt_user / "bin" / "Custom" / "Strategies" / "NT-Analyzer_strategies" /
        "NTAMicroVwapRiskExplorer" / "NTAMicroVwapRiskExplorer.cs"
    )
    wrapper_file = (
        nt_user / "bin" / "Custom" / "Strategies" / "NT-Analyzer_strategies" /
        "B1ShortOnlyMGC5mV2" / "B1ShortOnlyMGC5mV2.cs"
    )
    base_file.parent.mkdir(parents=True, exist_ok=True)
    wrapper_file.parent.mkdir(parents=True, exist_ok=True)
    base_file.write_text(
        "public abstract class NTAMicroVwapRiskExplorer {\n"
        "  void X() {\n"
        "    Name = \"Entry Micro Vwap Risk Explorer\";\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    wrapper_file.write_text(
        "public class B1ShortOnlyMGC5mV2 {\n"
        "  void X() {\n"
        "    Name = \"B1 ShortOnly MGC 5m v2 c002\";\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    catalog_dir = tmp / "data" / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.0",
        "generated_at_utc": _now_iso(),
        "strategies": [
            {
                "class_name": "NTAMicroVwapRiskExplorer",
                "display_name": "Entry Micro Vwap Risk Explorer",
                "source_file": str(base_file),
                "parameters": [
                    {"name": "EnableShort", "type": "System.Boolean"},
                    {"name": "TradeStartTime", "type": "System.Int32"},
                ],
            },
        ],
    }), encoding="utf-8")

    with mock.patch.object(jobqueue, "ninjatrader_user_dir", return_value=nt_user):
        cat = jobqueue.build_catalog_response()
        by_cls = {s.get("class_name"): s for s in (cat.get("strategies") or []) if isinstance(s, dict)}
        assert "NTAMicroVwapRiskExplorer" not in by_cls, "internal explorer must be hidden from catalog"
        assert "B1ShortOnlyMGC5mV2" in by_cls, "deploy wrapper must be synthesized into catalog"
        assert by_cls["B1ShortOnlyMGC5mV2"]["display_name"] == "B1 ShortOnly MGC 5m v2 c002"
        param_names = [p.get("name") for p in by_cls["B1ShortOnlyMGC5mV2"].get("parameters") or []]
        assert param_names == ["EnableShort", "TradeStartTime"], f"wrapper params must inherit donor param list, got {param_names}"

        allowed = jobqueue.whitelisted_strategies()
        assert "B1ShortOnlyMGC5mV2" in allowed, f"wrapper must be whitelisted, got {allowed}"
        assert "NTAMicroVwapRiskExplorer" not in allowed, f"internal explorer must not be whitelisted, got {allowed}"


@case("t41: strategies online state is not gated by catalog membership")
def t41(tmp):
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    assert "if (!cls || !catalogHasClass(cls)) return false;" not in js, \
        "runtime rows for approved profiles must not depend on catalog membership"
    assert "const sid = String(row?.strategy_id || runtimeRecord(row)?.strategy_id || \"\").trim().toLowerCase();" in js, \
        "strategies.js must match runtime rows by canonical strategy_id when catalog lags"
    assert "return classMatch || idMatch;" in js, \
        "runtime visibility must allow either class match or strategy_id match"


@case("t42: strategies top panel renders approved backtest research statistics")
def t42(tmp):
    html = (ROOT / "app" / "static" / "strategies.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="strategies-research-panel"' in html, "strategies page must expose the research panel container"
    assert 'id="strategies-research-body"' in html, "strategies page must expose a research panel body"
    assert "renderTaskResearch" in js, "strategies.js must render the top research panel"
    assert "ensureResearchReportLoaded" in js, "strategies.js must load the full report for the selected strategy"
    assert "drawHistoryEquity" in js, "research panel must reuse the equity chart renderer"
    assert "В среднем за неделю" in js and "В среднем за месяц" in js and "В среднем за квартал" in js and "В среднем за год" in js, \
        "research panel must show average income/trade metrics for week/month/quarter/year"
    assert "Win rate" in js and "Итоговый доход" in js and "Всего сделок" in js, \
        "research panel must show the reordered summary facts"
    assert "полный backtest" in html and "выбранного backtest" in js, \
        "research panel copy must work for reserved research strategies, not only approved profiles"
    assert ".strategies-research-panel" in css, "style.css must style the new research panel"
    assert ".strategies-research-metrics" in css, "style.css must style the research metrics block"
    assert ".strategies-research-metric-row" in css, "style.css must style list rows under the chart"
    assert ".strategies-research-layout" in css, "style.css must split chart and facts into side-by-side layout"
    assert ".strategies-research-facts-scroll" in css, "research facts must scroll inside their own column"
    assert "researchFactColumn" in js, "strategies.js must group research facts into readable columns"


@case("t43: strategies infer runtime root from strategy metadata when instrument field lags")
def t43(tmp):
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    assert "function runtimeRootCandidates" in js, "strategies.js must derive runtime root candidates"
    assert "r.strategy_name" in js and "r.strategy_id" in js and "r.strategy_class" in js, \
        "runtime root inference must consider strategy metadata, not just instrument field"
    assert "return candidates[0] || rootOf(r.instrument || r.contract_month || \"\");" in js, \
        "runtime root must fall back to instrument only after strategy metadata"


@case("t44: strategies page exposes horizontal top-bottom resizer")
def t44(tmp):
    html = (ROOT / "app" / "static" / "strategies.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="strategies-top-resizer"' in html, "strategies page must expose a horizontal top resizer"
    assert 'aria-orientation="horizontal"' in html, "top resizer must announce horizontal orientation"
    assert "function applyTopHeight" in js, "strategies.js must support resizing the top panel height"
    assert "function onTopResizePointerDown" in js and "function onTopResizePointerMove" in js, \
        "strategies.js must wire pointer drag handlers for the horizontal resizer"
    assert ".strategies-row-resizer" in css, "style.css must style the horizontal resizer"
    assert "--strategies-top-height" in css, "style.css must define an adjustable top-panel height variable"


@case("t45: strategies research period uses readable Russian dates and denser metrics layout")
def t45(tmp):
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")

    assert "const RU_DATE_FORMATTER = new Intl.DateTimeFormat(\"ru-RU\"" in js, \
        "strategies.js must format research periods via a Russian date formatter"
    assert "function fmtDateRu" in js, "strategies.js must expose a human-readable date formatter"
    assert "month: \"long\"" in js and "year: \"numeric\"" in js, \
        "research period must render full month names instead of raw ISO timestamps"
    assert "${value.from_utc || \"—\"} → ${value.to_utc || \"—\"}" not in js, \
        "raw UTC timestamp period formatting must be removed from the strategies page"
    assert "minmax(var(--strategies-research-chart-min), var(--strategies-research-chart-width))" in css, \
        "research layout must use a persisted chart width variable"
    assert "min-height: 68px;" in css and "padding: 7px 9px;" in css, \
        "research metric rows must be denser to reduce scrolling"


@case("t46: strategies research panel keeps chart fixed and exposes inner width resizer")
def t46(tmp):
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")

    assert "function applyResearchChartWidth" in js, \
        "strategies.js must support resizing the research chart width"
    assert "function bindResearchResizer" in js, \
        "strategies.js must bind a dedicated resizer inside the research panel"
    assert "id: \"strategies-research-resizer\"" in js, \
        "renderTaskResearch must render a visible inner resizer between chart and facts"
    assert "overflow: hidden;" in css and ".strategies-research-body" in css, \
        "research body must stop scrolling as a whole so the chart can stay fixed"
    assert ".strategies-research-resizer" in css, \
        "style.css must style the inner research resizer"
    assert ".strategies-research-scroll-side" in css and ".strategies-research-facts-scroll" in css, \
        "research panel must isolate scrolling to the facts column"
    assert "height: clamp(286px, 34vh, 340px);" in css, \
        "research chart canvas must use a stable explicit height during width resizing"


@case("t47: coverage status counts do not double-count ready profiles")
def t47(tmp):
    from app import jobqueue

    jobqueue.project_root = lambda: tmp  # type: ignore[assignment]
    jobqueue.reset_caches()

    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.1",
        "profiles": [
            {
                "profile_id": "mnq_ready_v1",
                "name": "VWAP Short MNQ 5m v1 c011",
                "strategy_class": "NTAMicroVwapRiskPilot",
                "instrument": "MNQ 06-26",
                "timeframe": "5 Minute",
                "status": "ready",
                "slot": 1,
                "cell_id": "CELL-011",
            },
            {
                "profile_id": "mnq_candidate_v1",
                "name": "Scalping MNQ 1m v1 c012",
                "strategy_class": "NTAMicroMnqScalpPilot",
                "deploy_strategy_class": "NTAMnqMicroOrbOpenScalp",
                "instrument": "MNQ 06-26",
                "timeframe": "1 Minute",
                "status": "research_baseline",
                "slot": 2,
                "cell_id": "CELL-012",
            },
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (profiles_dir / "instrument_strategy_coverage.json").write_text(json.dumps({
        "schema_version": 1,
        "generated_at_utc": "2026-05-10T00:00:00Z",
        "summary": {"ready": 1, "in_progress": 11, "total_micros": 12},
        "micros": [
            {
                "root": "MNQ",
                "groups": ["Micros", "Indexes"],
                "current_contract": "MNQ 06-26",
                "status": "ready",
                "status_badge": "✅ Готова",
                "strategy_count": 2,
                "best_profile_id": "mnq_ready_v1",
                "strategy_class": "NTAMicroVwapRiskPilot",
                "setup_mode": None,
                "timeframe": "5 Minute",
                "evidence_bundle": "test_bundle",
                "evidence_job_ids": [],
                "metrics": {},
                "notes": "",
                "next_action": "",
                "is_locked": True,
            }
        ],
        "non_micros_with_profiles": [],
        "legend": {"ready": "✅ Готова", "in_progress": "В процессе"},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    catalog_dir = tmp / "data" / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.0",
        "strategies": [
            {"class_name": "NTAMicroVwapRiskPilot", "display_name": "VWAP Short MNQ 5m v1 c011"},
        ],
    }), encoding="utf-8")

    out = jobqueue.read_instrument_coverage()
    assert out["instruments"], out
    mnq = out["instruments"][0]
    counts = mnq["status_counts"]
    assert counts["total"] == 2, counts
    assert counts["ready"] == 1, counts
    assert counts["in_progress"] == 1, counts
    assert counts["research_baseline"] == 1, counts
    assert counts["available"] == 1, counts
    assert counts["approved_available"] == 1, counts


@case("t48: strategies page keeps reserved research cells visible without counting them as approved slots")
def t48(tmp):
    html = (ROOT / "app" / "static" / "strategies.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")

    assert "Исследовательские версии с закрепленной ячейкой" in html, \
        "strategies page must explain that reserved research cells stay visible"
    assert "function profileVisibleInMatrix" in js, \
        "strategies.js must allow reserved research profiles into the matrix"
    assert "const approvedFamilies = slotLayout.families.filter(family => family.approved);" in js, \
        "approved slot counters must remain separate from visible research cells"
    assert "исследовательских ячеек отображаются отдельно" in js, \
        "detail summary must distinguish approved slot counts from visible research cells"
    assert ".strategy-cell.baseline" in css, \
        "matrix must style reserved research cells distinctly"


@case("t48b: strategies matrix can hide explicitly closed cells without renumbering live slots")
def t48b(tmp):
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")

    assert "if (profile.matrix_hidden) return false;" in js, \
        "matrix must allow explicitly removed profiles to stop occupying their reserved cell"


@case("t48c: CELL-018 is operationally closed but keeps archive evidence")
def t48c(tmp):
    raw = json.loads((ROOT / "examples" / "strategy-profiles.example.json").read_text(encoding="utf-8"))
    profiles = raw.get("profiles") or []
    profile = next(p for p in profiles if p.get("profile_id") == "mnq_daily_open_allmodules_2h_1m_c018_ready_v1")

    assert profile["name"] == "Scalping MNQ 1m v1 c018", profile
    assert profile["deploy_strategy_class"] == "NTAMnqDailyOpenScalpC018", profile
    assert "NTAMnqDailyOpenScalpC018" in (profile.get("runtime_strategy_classes") or []), profile
    assert profile["status"] == "archived", profile
    assert profile["matrix_hidden"] is True, profile
    assert profile["cell_id"] == "", profile
    assert profile["archived_cell_id"] == "CELL-018", profile
    assert (profile.get("operational_closure") or {}).get("final_action") == "archived_purged", profile

    # New architecture: archived strategies are removed from the NinjaTrader
    # compile path; their source is preserved as evidence under _quarantine/.
    active_path = ROOT / "ninjatrader" / "strategies" / "NTAMnqDailyOpenScalpC018"
    assert not active_path.exists(), "archived strategy must be removed from NinjaTrader"
    quarantined = list((ROOT / "ninjatrader" / "strategies" / "_quarantine").glob(
        "CELL-018_*/NTAMnqDailyOpenScalpC018/NTAMnqDailyOpenScalpC018.cs"))
    assert quarantined, "archived wrapper evidence must be preserved in quarantine"
    assert 'Name = "Scalping MNQ 1m v1 c018";' in quarantined[0].read_text(encoding="utf-8")


@case("t48d: CELL-017 post-active profile is operationally closed")
def t48d(tmp):
    raw = json.loads((ROOT / "examples" / "strategy-profiles.example.json").read_text(encoding="utf-8"))
    profiles = raw.get("profiles") or []
    profile = next(p for p in profiles if p.get("profile_id") == "mnq_postactive_allmodules_1m_c017_ready_v1")

    assert profile["name"] == "Scalping Post-Active MNQ 1m v1 c017", profile
    assert profile["deploy_strategy_class"] == "NTAMnqPostActiveScalpC017", profile
    assert "NTAMnqPostActiveScalpC017" in (profile.get("runtime_strategy_classes") or []), profile
    assert profile["status"] == "archived", profile
    assert profile["matrix_hidden"] is True, profile
    assert profile["cell_id"] == "", profile
    assert profile["archived_cell_id"] == "CELL-017", profile
    assert (profile.get("operational_closure") or {}).get("final_action") == "archived_purged", profile
    assert profile["locked_parameters"]["TradeStartTime"] == 1250, profile
    assert profile["locked_parameters"]["TradeEndTime"] == 1325, profile
    assert profile["locked_parameters"]["RewardRiskRatio"] == 6.0, profile

    # New architecture: archived strategy removed from NinjaTrader; source kept
    # as evidence in _quarantine/.
    active_path = ROOT / "ninjatrader" / "strategies" / "NTAMnqPostActiveScalpC017"
    assert not active_path.exists(), "archived strategy must be removed from NinjaTrader"
    quarantined = list((ROOT / "ninjatrader" / "strategies" / "_quarantine").glob(
        "CELL-017_*/NTAMnqPostActiveScalpC017/NTAMnqPostActiveScalpC017.cs"))
    assert quarantined, "archived wrapper evidence must be preserved in quarantine"
    text = quarantined[0].read_text(encoding="utf-8")
    assert 'Name = "Scalping Post-Active MNQ 1m v1 c017";' in text
    assert "TradeStartTime = 1250;" in text and "TradeEndTime = 1325;" in text


@case("t49: trading UI reads locked params from runtime-backed profile data")
def t49(tmp):
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")

    assert "function strategyConfigForView" in js, \
        "trading.js must derive strategy launch config from the selected runtime view"
    assert "view.locked_params" in js, \
        "trading.js must use backend-provided locked params when available"
    assert "view.display_name" in js, \
        "trading.js must surface the profile display name for runtime-backed strategies"
    assert "strategyConfigLabel" in js, \
        "trading.js must render a clean label for dynamic locked-param configs"
    assert "const stratCfg = strategyConfigForView(view);" in js, \
        "enable_strategy must use the runtime-backed config, not only static JS presets"


@case("t50: runtime executions/orders support account-level unmapped telemetry")
def t50(tmp):
    _write_runtime_jsonl(tmp, "executions.jsonl", [
        {
            "timestamp_utc": _now_iso(), "account_name": "DEMO3369390",
            "strategy_id": "", "strategy_class": "", "instrument": "MGC JUN26",
            "order_action": "SellShort", "quantity": 1, "price": 4688.9,
        },
        {
            "timestamp_utc": _now_iso(), "account_name": "DEMO3369390",
            "strategy_id": "Short", "strategy_class": "Short", "instrument": "MNQ JUN26",
            "order_action": "BuyToCover", "quantity": 1, "price": 29200.25,
        },
        {
            "timestamp_utc": _now_iso(), "account_name": "Sim101",
            "strategy_id": "vwap_short_mnq_5m_v1", "strategy_class": "NTAMicroVwapRiskPilot",
            "instrument": "MNQ JUN26", "quantity": 1, "price": 29197.5,
        },
    ])
    _write_runtime_jsonl(tmp, "orders.jsonl", [
        {
            "timestamp_utc": _now_iso(), "account_name": "DEMO3369390",
            "strategy_id": "", "instrument": "MGC JUN26",
            "order_state": "Filled", "order_action": "SellShort",
        },
        {
            "timestamp_utc": _now_iso(), "account_name": "Sim101",
            "strategy_id": "vwap_short_mnq_5m_v1", "instrument": "MNQ JUN26",
            "order_state": "Working", "order_action": "SellShort",
        },
    ])

    demo_execs = rt.read_executions(account_name="DEMO3369390", limit=10)
    assert len(demo_execs) == 2, f"account-level DEMO executions must include unmapped rows, got {demo_execs}"
    assert {r.get("strategy_id") for r in demo_execs} == {"", "Short"}

    demo_orders = rt.read_orders(account_name="DEMO3369390", limit=10)
    assert len(demo_orders) == 1, f"account-level DEMO orders must include blank strategy_id, got {demo_orders}"
    assert demo_orders[0]["order_state"] == "Filled"

    strategy_execs = rt.read_executions(strategy_id="vwap_short_mnq_5m_v1", limit=10)
    assert len(strategy_execs) == 1 and strategy_execs[0]["account_name"] == "Sim101", \
        f"strategy filter must remain exact/canonical and not swallow account-level unmapped rows: {strategy_execs}"


@case("t51: trading UI exposes account overview and per-strategy analytics tabs")
def t51(tmp):
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert 'id="account-overview-band"' not in html, "central account overview band must stay removed"
    assert 'id="acct-pnl-chart"' in html and "<canvas" in html, "All-time equity curve must live in Performance Center as canvas"
    assert "Доход по инструментам с 13.05" in html, "instrument income panel must be in Performance Center"
    assert 'id="trade-calendar"' in html, "missing per-day trading calendar"
    assert 'id="snapshot-working-orders"' in html, "missing working orders snapshot"
    # Expanded strategy analytics layout: Обзор / Капитал / Сделки / Заметки
    assert 'id="pane-overview"' in html, "missing Обзор tab pane"
    assert 'id="pane-equity"' in html, "missing Капитал tab pane"
    assert 'id="pane-trades"' in html, "missing Сделки tab pane"
    assert 'id="pane-orders"' not in html, "Orders tab must be merged into Сделки"
    assert 'id="pane-history"' not in html, "История tab must be hidden from strategy analytics"
    assert 'id="pane-notes"' in html, "missing Заметки tab pane"
    assert 'id="pane-strategies"' not in html, "Strategies tab pane must stay removed"
    assert "renderEquityPane" in js and "renderTradesPane" in js and "renderNotesPane" in js, \
        "expanded strategy analytics panes must be wired in trading.js"
    assert "Факт: PnL стратегии от нуля" in js and "План по бэктесту за тот же срок" in js, \
        "capital tab must compare actual zero-based strategy PnL against backtest expectation"
    assert "tradesPaneOrdersSectionHTML" in js, "Сделки tab must include orders section"
    assert "renderOrdersPane" not in js, "standalone Orders pane must be removed"
    assert "rowIsUnmappedCandidate" in js, "UI must still surface unmapped candidates for selected strategy"
    assert "renderTradingCalendar" in js, "UI must expose selectable daily trading calendar"


@case("t52: runtime executions are deduped by execution_id after NinjaTrader restart replay")
def t52(tmp):
    _write_runtime_jsonl(tmp, "executions.jsonl", [
        {
            "timestamp_utc": "2026-05-13T13:35:20Z", "execution_id": "E1",
            "account_name": "DEMO3369390", "strategy_id": "",
            "strategy_class": "", "instrument": "MGC JUN26",
            "order_action": "SellShort", "quantity": 1, "price": 4688.9,
        },
        {
            "timestamp_utc": "2026-05-13T16:43:08Z", "execution_id": "E1",
            "account_name": "DEMO3369390", "strategy_id": "",
            "strategy_class": "", "instrument": "MGC JUN26",
            "order_action": "", "quantity": 1, "price": 4688.9,
        },
        {
            "timestamp_utc": "2026-05-13T13:35:59Z", "execution_id": "E2",
            "account_name": "DEMO3369390", "strategy_id": "Short",
            "strategy_class": "Short", "instrument": "MGC JUN26",
            "order_action": "BuyToCover", "role": "exit", "exit_reason": "target",
            "quantity": 1, "price": 4684.7,
        },
    ])
    rows, meta = rt.read_executions_with_meta(account_name="DEMO3369390", limit=10)
    assert len(rows) == 2, f"restart replay with same execution_id must not double-count: {rows}"
    assert meta["raw_count"] == 3 and meta["deduped_count"] == 2 and meta["duplicate_count"] == 1, meta
    e1 = next(r for r in rows if r["execution_id"] == "E1")
    assert e1["timestamp_utc"] == "2026-05-13T13:35:20Z", "dedupe must keep original execution time"
    assert e1["order_action"] == "SellShort", "dedupe must preserve richer original execution details"


@case("t53: same fill replayed with new execution_id collapses when order_id + fill fingerprint match")
def t53(tmp):
    _write_runtime_jsonl(tmp, "executions.jsonl", [
        {
            "timestamp_utc": "2026-05-13T18:30:00.123Z",
            "execution_id": "EX_BEFORE_REBOOT",
            "order_id": "NT-ORD-1001",
            "account_name": "DEMO3369390",
            "strategy_id": "vwap_short_mnq_5m_v1",
            "strategy_class": "NTAMicroVwapRiskPilot",
            "instrument": "MGC JUN26",
            "order_action": "Buy",
            "market_position": "Long",
            "position_action": "",
            "quantity": 1,
            "price": 4688.9,
        },
        {
            "timestamp_utc": "2026-05-13T18:30:00.123Z",
            "execution_id": "EX_AFTER_REBOOT",
            "order_id": "NT-ORD-1001",
            "account_name": "DEMO3369390",
            "strategy_id": "",
            "strategy_class": "",
            "instrument": "MGC JUN26",
            "order_action": "",
            "market_position": "",
            "position_action": "",
            "quantity": 1,
            "price": 4688.9,
        },
    ])
    rows, meta = rt.read_executions_with_meta(account_name="DEMO3369390", limit=10)
    assert len(rows) == 1, f"expected single logical fill, got {rows}"
    assert meta["raw_count"] == 2 and meta["deduped_count"] == 1 and meta["duplicate_count"] == 1, meta
    assert rows[0]["strategy_id"] == "vwap_short_mnq_5m_v1"
    assert rows[0]["order_action"] == "Buy"


@case("t54: execution fallback dedupe does not use row index (identical lines merge)")
def t54(tmp):
    row = {
        "timestamp_utc": "2026-05-13T12:00:00.000Z",
        "account_name": "Sim101",
        "instrument": "MNQ 06-26",
        "order_action": "buy",
        "market_position": "long",
        "position_action": "",
        "quantity": 1,
        "price": 21000.25,
        "strategy_id": "",
        "strategy_class": "",
    }
    _write_runtime_jsonl(tmp, "executions.jsonl", [dict(row), dict(row)])
    rows, meta = rt.read_executions_with_meta(account_name="Sim101", limit=10)
    assert len(rows) == 1, rows
    assert meta["duplicate_count"] == 1, meta


@case("t55: trading calendar does not trust zero account RealizedPnL over nonzero closed executions")
def t55(tmp):
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "function reliableAccountRealizedPnl" in js, \
        "trading.js must distinguish provider-zero RealizedPnL from authoritative account PnL"
    assert "function accountEquityDeltaPnl" in js, \
        "trading.js must use cash/net liquidation delta when account RealizedPnL is provider-zero"
    assert "function activeStartingCapitalForAccount" in js, \
        "cash delta must be anchored to runtime StartingCapital"
    assert "STATE.runtimeRawStrats = (all && all.raw) || [];" in js, \
        "UI must keep raw strategy params for cash-delta fallback when heartbeat is stale"
    assert "for (const row of (STATE.runtimeRawStrats || []))" in js
    assert "const acctRealizedRaw = acct ? numOrNull(acct.realized_pnl) : null;" in js
    assert "const acctRealized = reliableAccountRealizedPnl(acctRealizedRaw, execNet, closedToday.length);" in js
    assert "account_cash_delta" in js
    assert "execution_net" in js
    assert "function roundTurnCommissionForExecution" in js, \
        "calendar execution estimates must subtract RoundTurnCommission instead of showing gross price PnL"
    assert "deduped net est." in js
    assert "cash/netliq минус StartingCapital" in js, \
        "UI must explain when daily PnL is taken from balance delta instead of account RealizedPnL=0"


@case("t56: trading UI warns when bridge is older than execution strategy-mapping exporter")
def t56(tmp):
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "function versionLt" in js, "bridge version comparison must be numeric, not string-based"
    assert 'versionLt(ev, "1.3.0")' in js, \
        "bridge < 1.3.0 must be flagged because it can miss cycle/cell attribution fields in executions/orders"
    assert "strategy_id/class/name/runtime_instance_id/order_name/from_entry_signal" in js
    assert "trading_cycle_id/cell_id/attribution_status/param_snapshot_hash" in js


@case("t57: account headline re-renders without deleting its currency node")
def t57(tmp):
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "const setBalance = (amountHtml, currencyText = \"\") =>" in js, \
        "account headline must recreate ah-currency whenever ah-balance innerHTML is replaced"
    assert "if (!elMode || !elName || !elConn || !elBal || !elSub || !elWarn) return;" in js, \
        "renderAccountHeadline must tolerate removed/legacy headline DOM nodes"
    assert 'id="ah-currency"' in js


@case("t58: trading UI groups PnL by strategy lot key and shows signal columns")
def t58(tmp):
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "function executionLotKey" in js, \
        "FIFO PnL must not pair executions from different strategies on the same instrument"
    assert "executionStrategyIdentity(row)" in js
    assert "const lotKey = executionLotKey(r);" in js
    assert "closedMapped" in js, \
        "strategy summaries must use closed trades, not raw fill rows, for PnL"
    assert "from_entry_signal" in js and "order_name" in js, \
        "trades/orders tables must show the signal that was used for strategy mapping"


@case("t59: selected calendar day trades render inside session details")
def t59(tmp):
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")

    details_pos = html.find('<div class="session-details">')
    trades_pos = html.find('id="session-day-trades"')
    positions_pos = html.find('id="snapshot-positions"')
    assert details_pos >= 0 and trades_pos >= 0 and positions_pos >= 0, \
        "session details, selected-day trades, and positions blocks must exist"
    assert details_pos < trades_pos < positions_pos, \
        "#session-day-trades must live inside .session-details, before positions"
    assert "cal-orders" in html and "cal-fills" not in html, \
        "calendar trade count label must not be styled as fills"
    assert "нет закрытых сделок" in js and "сделок" in js and "cal-fills" not in js, \
        "calendar cells must show closed trade counts from dailyWall.closedTrades, not orders or raw fills"
    assert "tradesTableHTML(trades, \"\", 500)" in js, \
        "selected-day trades panel must reuse the Orders closed-trades table"


@case("t63: backtest reports use server-sorted 50-row pagination")
def t63_reports_server_sorted_pagination(tmp):
    js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert "const REPORTS_PAGE_SIZE = 50;" in js
    assert "const REPORTS_RESET_PAGE_SIZE = 50;" in js
    assert "function _reportsQuery(offset, limit)" in js
    assert "sort: _sortCol || \"mtime\"" in js and "filter: _jobsFilter || \"all\"" in js, \
        "report pages must ask the backend for the current sort/filter"
    assert "_createdSortMs(j.created_at_utc, j.report_no)" in js and "_createdSortMs(b.created_at_utc, b.report_no)" in js, \
        "client fallback sort must use created/report_no, not filesystem folder mtime"
    assert "reportsView.v2" in js, "old persisted tree view must not override the standard table"
    assert "График (опц.)" in html, "chart tab must be visibly optional"


@case("t64: selected calendar day shows all orders with cancelled/rejected statuses")
def t64_selected_day_orders_are_visible(tmp):
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "day-orders-table-wrap" in html, "selected-day order table must be styled"
    assert "day-order-cancelled" in html and "day-order-rejected" in html, \
        "cancelled/rejected daily orders must have muted row styles"
    assert "function selectedDayOrderRows" in js
    assert "function orderReason" in js
    assert "function filledOrdersMissingExecutions" in js, \
        "daily order panel must flag Filled orders that have no matching execution rows"
    assert "показан последний статус каждого Order ID" in js
    assert "filled без executions" in js
    assert "dayOrdersTableHTML(orders)" in js
    assert "STATE.dayExplicitlySelected = true;" in js, \
        "Today/calendar selection must open the daily details panel"


@case("t65: account-level PnL can pair unmapped exits without attributing them to strategies")
def t65_account_level_fifo_handles_unmapped_exits(tmp):
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "function executionAccountLotKey" in js, \
        "account-level FIFO must be able to pair fills by account+instrument"
    assert "function executionHasLegacyAttribution" in js
    assert "function closingLotsForRow" in js and "function lotsOpposeSignedQty" in js, \
        "strategy-scoped FIFO must be able to close mapped lots from unmapped account exits"
    assert "const activeLotKey = strategyScoped || executionHasLegacyAttribution(r) ? lotKey : accountLotKey;" in js
    assert "annotateExecutionsWithPnl(execs, { strategyScoped: false })" in js, \
        "account calendar PnL must use account-level FIFO"
    assert "entry_strategy_class" in js and "entry_runtime_instance_id" in js, \
        "closed trade rows should retain entry-side mapping for audit"
    assert "function isClosedTradeUnmapped" in js and "function effectiveStrategyField" in js, \
        "closed trade attribution must merge exit identity with entry identity"
    assert "const tolerance = Math.max(3, 0.03 * Math.max(Math.abs(ar), Math.abs(eg)));" in js, \
        "nonzero account RealizedPnL must be rejected when it conflicts with execution net"
    assert "unmapped ${escapeHtml(fmtMoney(unmappedPnl))}" in js, \
        "active strategy PnL cell may show truly unattributed account PnL separately"
    assert "function closedUnmappedTradeMatchesStrategyView" in js and "rowEntryMatchesStrategyView" in js, \
        "truly unmapped closed trades must remain scoped and not fan out to every strategy on the same instrument"
    assert "closedUnmapped: closedRows.filter(isUnmappedTelemetry)" not in js, \
        "closed-trade unmapped buckets must not use per-fill telemetry"
    assert "Unmapped / неизвестная стратегия" in js, \
        "unattributed closed trades must be surfaced as their own Performance Center row"
    assert "PERFORMANCE_START_DATE_PT = \"2026-05-13\"" in js
    assert "PERFORMANCE_STARTING_CAPITAL = 2000" in js
    assert "isPerformanceWindowTimestamp(r.timestamp_utc)" in js, \
        "calendar and account metrics must ignore pre-start activity"


@case("t66: strategies selection reveals the active matrix cell and planner bar")
def t66_strategies_selection_reveals_matrix_cell(tmp):
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    assert "function requestSelectedStrategyReveal" in js
    assert "function revealSelectedStrategyIfNeeded" in js
    assert "STATE.selectedKey = families[0].key;" in js, \
        "selected family key must be synchronized before the matrix renders"
    assert ".strategies-matrix-table .strategy-cell.selected" in js
    assert "selectedCell.scrollIntoView({ block: \"nearest\", inline: \"center\" })" in js
    assert ".strategies-day-track-scroll .strategies-session-bar.selected" in js
    assert "selectedPlannerBar.scrollIntoView({ block: \"center\", inline: \"nearest\" })" in js
    assert "requestSelectedStrategyReveal();" in js


@case("t67: legacy Short telemetry gets exact mappings only when provable")
def t67_legacy_short_strategy_attribution(tmp):
    _write_runtime_jsonl(tmp, "executions.jsonl", [
        {
            "timestamp_utc": "2026-05-13T13:35:20Z",
            "execution_id": "355476070233_1",
            "account_name": "DEMO3369390",
            "strategy_id": "",
            "strategy_class": "",
            "instrument": "MGC JUN26",
            "order_action": "SellShort",
            "quantity": 1,
            "price": 4688.9,
        },
        {
            "timestamp_utc": "2026-05-13T13:38:09Z",
            "execution_id": "355476070267_1",
            "account_name": "DEMO3369390",
            "strategy_id": "Short",
            "strategy_class": "Short",
            "instrument": "MGC JUN26",
            "order_action": "BuyToCover",
            "quantity": 1,
            "price": 4681.9,
        },
        {
            "timestamp_utc": "2026-05-14T13:40:11Z",
            "execution_id": "355476070430_1",
            "account_name": "DEMO3369390",
            "strategy_id": "",
            "strategy_class": "",
            "instrument": "MNQ JUN26",
            "order_action": "SellShort",
            "quantity": 1,
            "price": 29578.25,
        },
    ])
    _write_runtime_jsonl(tmp, "orders.jsonl", [
        {
            "timestamp_utc": "2026-05-14T14:43:04Z",
            "account_name": "DEMO3369390",
            "strategy_id": "Short",
            "strategy_class": "",
            "instrument": "MNQ JUN26",
            "order_id": "130",
            "order_state": "Filled",
            "order_action": "BuyToCover",
            "order_type": "StopMarket",
            "quantity": 1,
            "avg_fill": 29671.5,
            "stop_price": 29671.5,
            "limit_price": 0,
        },
    ])

    rows = rt.read_executions(account_name="DEMO3369390", limit=10)
    exact = [r for r in rows if r.get("instrument") == "MGC JUN26"]
    assert {r.get("strategy_class") for r in exact} == {"B1Stop20MGC5mC004"}, exact
    assert {r.get("strategy_id") for r in exact} == {"mgc_b1_stop20_5m_c004"}, exact

    ambiguous = next(r for r in rows if r.get("instrument") == "MNQ JUN26")
    assert ambiguous.get("strategy_class") in ("", None), ambiguous
    assert ambiguous.get("_strategy_attribution_confidence") == "ambiguous", ambiguous
    cands = [c.get("strategy_class") for c in ambiguous.get("_strategy_attribution_candidates") or []]
    assert cands == ["NTAMnqLiquiditySweepReversalC015", "NTAMnqOpenDriveShortScalpC016"], ambiguous

    c015_orders = rt.read_orders(class_name="NTAMnqLiquiditySweepReversalC015", account_name="DEMO3369390", limit=10)
    assert len(c015_orders) == 1 and c015_orders[0].get("strategy_id") == "ntamnqliquiditysweepreversalc015", c015_orders


@case("t68: closed trade inherits strategy from entry when exit is unmapped")
def t68_closed_trade_inherits_entry_strategy_when_exit_unmapped(tmp):
    _write_runtime_jsonl(tmp, "executions.jsonl", [
        {
            "timestamp_utc": "2026-05-21T15:00:00Z",
            "execution_id": "entry-c015-1",
            "account_name": "DEMO3369390",
            "strategy_id": "ntamnqliquiditysweepreversalc015",
            "strategy_class": "NTAMnqLiquiditySweepReversalC015",
            "strategy_name": "NTAMnqLiquiditySweepReversalC015",
            "runtime_instance_id": "iid-c015",
            "instrument": "MNQ JUN26",
            "order_action": "SellShort",
            "quantity": 1,
            "price": 19000.0,
        },
        {
            "timestamp_utc": "2026-05-21T15:03:00Z",
            "execution_id": "exit-c015-1",
            "account_name": "DEMO3369390",
            "strategy_id": "Short",
            "strategy_class": "",
            "strategy_name": "",
            "runtime_instance_id": "",
            "instrument": "MNQ JUN26",
            "order_action": "BuyToCover",
            "quantity": 1,
            "price": 18996.0,
        },
    ])
    rows = rt.read_executions(account_name="DEMO3369390", limit=10)
    entry = next(r for r in rows if r.get("execution_id") == "entry-c015-1")
    exit_row = next(r for r in rows if r.get("execution_id") == "exit-c015-1")
    assert entry["strategy_class"] == "NTAMnqLiquiditySweepReversalC015", rows
    assert exit_row["strategy_id"] == "Short" and not exit_row.get("strategy_class"), rows

    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "function effectiveStrategyField" in js, \
        "UI must have one helper for exit-or-entry strategy fields"
    assert "function isClosedTradeUnmapped" in js, \
        "closed trades must decide unmapped using both exit and entry identity"
    assert "function closedTradeStrategyLabel" in js, \
        "closed trade label must fall back to entry strategy identity"
    assert "closedTrade[field] = effectiveStrategyField(closedTrade, field);" in js, \
        "annotateExecutionsWithPnl must write effective strategy fields into closed trades"
    assert "closedTrade.unmapped = isClosedTradeUnmapped(closedTrade);" in js, \
        "closed trades must not inherit per-fill unmapped telemetry from the exit"
    assert "unmapped: isUnmappedTelemetry(r)" not in js, \
        "annotateExecutionsWithPnl must not mark closed trades unmapped solely from the exit fill"
    assert "const label = closedTradeStrategyLabel(t);" in js, \
        "tradeStrategyLabel must use the closed-trade entry fallback"
    assert "filter(r => isClosedTradeUnmapped(r) && !running.some(s => closedUnmappedTradeMatchesStrategyView(r, s)))" in js, \
        "Performance Center unknown row must use closed-trade attribution"


@case("t69: Performance Center stays all-time while strategy panes use selected day")
def t69_performance_center_all_time_selected_day_tabs(tmp):
    _ = tmp
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert 'aria-label="Весь период"' in html, \
        "Performance Center account chart block must not be labelled as a selected-day widget"
    assert "const allTime = accountAllTimeStats(m);" in js, \
        "Performance Center summary/chart must compute all-time account stats"
    chart_start = js.index("function renderAccountPnlChart")
    chart_end = js.index("function renderInstrumentPnlBars")
    chart_src = js[chart_start:chart_end]
    assert "m.allClosedTrades || m.closedTrades" in chart_src, \
        "Performance Center equity canvas must use all closed trades"
    assert "m.selectedClosedTrades" not in chart_src and "m.selectedPnl" not in chart_src, \
        "Performance Center equity canvas must not follow the selected calendar day"
    assert "renderRuntimeTable();" in js and "const dayRows = acctMetrics.selectedExecs" in js, \
        "Active strategies table must refresh from the selected calendar day"
    assert "const daySets = strategyExecutionSets(view, selectedDate);" in js, \
        "Strategy Overview must expose selected-day stats"
    assert "tradesPaneOrderRows" in js and "tradesPaneOrdersSectionHTML" in js, \
        "Сделки tab must expose selected-day orders alongside trades"
    assert "function strategyRiskBreachForDay" in js and ">HALT</span>" in js, \
        "Selected-day strategy rows must expose risk-limit breaches"


@case("t61: strategy metrics must not attribute unmapped instrument fills")
def t61_no_instrument_fill_fallback(tmp):
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "best-effort attribution when classSet matched nothing" not in js, \
        "instrument-only fallback must not inflate per-strategy fill metrics"
    assert "unmappedFills" in js and "paramsMismatchBadgeTitle" in js
    assert "не входят" in js or "не в PnL" in js


@case("t62: per-strategy PnL must not treat unmapped rows as strategy PnL")
def t62_unmapped_excluded_from_strategy_pnl(tmp):
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "unmappedRows.length ? null : numOrNull(rt.realized_pnl)" not in js
    assert "ambiguous ? \"unmapped\"" not in js


@case("t60: trading UI shows entry window column and PT window logic")
def t60_trade_windows_ui(tmp):
    _ = tmp
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "Окно входа" in html, "active strategies table must have entry-window column"
    assert "strategy-in-window" in html and "strategy-out-window" in html, \
        "trading.html must style in-window vs out-of-window rows"
    assert "computeTradeWindowState" in js and "ptNowHhmm" in js, \
        "trading.js must evaluate PT entry windows client-side"
    assert "trade_window_pt" in js or "resolveTradeWindow" in js, \
        "trading.js must read trade_window_pt from API payload"
    assert "fmtHhmmDisplay" in js and '"AM"' in js and "reformatTradeWindowPtString" in js, \
        "trading.js must format entry windows in 12-hour AM/PM"


@case("t70: strategies day planner keeps the full exchange session")
def t70_strategies_day_planner_full_session(tmp):
    _ = tmp
    js = (ROOT / "app" / "static" / "strategies.js").read_text(encoding="utf-8")
    assert 'MNQ: { start: 1500, end: 1400, label: "Биржевая сессия" }' in js, \
        "planner must show the full CME-style exchange session, not just the RTH morning block"
    assert "if (minute === 0) return 60;" in js, \
        "full-session planner should render one-hour time cells when the session starts on the hour"
    assert "function plannerWindowInSession" in js and "plannerWindowInSession(window, session.start)" in js, \
        "morning strategy windows must be shifted into the 15:00->14:00 trading-day timeline"


@case("t71: runtime strategies table has all-time PnL and sortable headers")
def t71_runtime_table_all_time_pnl_and_sorting(tmp):
    _ = tmp
    html = (ROOT / "app" / "static" / "trading.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "trading.js").read_text(encoding="utf-8")
    assert "PnL за всё время" in html, "runtime strategies table must show all-time strategy PnL"
    assert "Работает" in html and 'data-trading-sort="runtime_duration"' in html, \
        "runtime strategies table must show total strategy work time after Last update"
    assert 'colspan="16"' in html and 'colspan="15"' not in html and 'colspan="14"' not in html, \
        "runtime strategies empty row colspan must match the new column count"
    assert 'data-trading-sort-table="runtimeStrategies"' in html, \
        "runtime strategies headers must be wired into the shared sort handler"
    assert "runtimeStrategies: { col: \"cell\", dir: \"asc\" }" in js, \
        "runtime table must have a deterministic default sort"
    assert "function runtimeSortValue" in js and "function sortRuntimeRows" in js, \
        "runtime table must sort rows client-side"
    assert "const strategyAllClosed = acctMetrics.allStrategyClosedTrades || acctMetrics.allClosedTrades || [];" in js, \
        "runtime table must use strategy-scoped closed trades for all-time PnL"
    assert "const allClosedRows = strategyAllClosed.filter(r => rowMatchesStrategyView(r, s) && rowOnOrAfterDate(r, startDatePt));" in js, \
        "all-time PnL must stay mapped to the current strategy row without account-level FIFO bleed"
    assert 'data-trading-sort="pnl_all"' in html and 'case "pnl_all": return metrics.pnlAll;' in js, \
        "all-time PnL column must be sortable"
    assert 'case "runtime_duration": return strategyRuntimeDurationSec(view) ?? -1;' in js, \
        "runtime duration column must be sortable"
    assert "function strategyStartDateForView" in js and "rowOnOrAfterDate(r, startDatePt)" in js, \
        "strategy all-time stats must honor the established strategy start date"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    cases = [t01, t02, t03, t04, t05, t06, t07, t08, t09, t10, t11, t12,
             t13, t14, t15, t16, t17, t18, t19, t20, t21, t22, t23, t24,
             t25, t26, t26a, t27, t28, t29, t30, t31, t32, t33, t34, t35, t36,
             t37, t38, t39, t40, t41, t42, t43, t44, t45, t46, t47, t48, t48b, t48c, t48d, t49,
             t50, t51, t52, t53, t54, t55, t56, t57, t58, t59, t60_trade_windows_ui,
             t61_no_instrument_fill_fallback, t62_unmapped_excluded_from_strategy_pnl,
             t63_reports_server_sorted_pagination, t64_selected_day_orders_are_visible,
             t65_account_level_fifo_handles_unmapped_exits, t66_strategies_selection_reveals_matrix_cell,
             t67_legacy_short_strategy_attribution, t68_closed_trade_inherits_entry_strategy_when_exit_unmapped,
             t69_performance_center_all_time_selected_day_tabs, t70_strategies_day_planner_full_session,
             t71_runtime_table_all_time_pnl_and_sorting]
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
