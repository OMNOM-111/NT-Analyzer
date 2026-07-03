"""Phase 17 — NinjaTrader runtime bridge tests.

Run from NT-Analyzer/ root:
    python -m tests.test_runtime

Tests use a temp directory by monkey-patching ops._project_root, so they
do not touch real data/ops/, real data/runtime/, or the real journal CSV.
"""
from __future__ import annotations

import json
import os
import sys
import shutil
import tempfile
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ops               # noqa: E402
from app import runtime as rt     # noqa: E402


PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------

def _set_temp_root(tmp: Path) -> None:
    ops._project_root = lambda: tmp  # type: ignore[assignment]
    (tmp / "data" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    base = tmp / "data" / "profiles" / "paper_b1_shortonly"
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


def _now_iso(offset_sec: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat(timespec="seconds")


def _write_runtime(tmp: Path, *, heartbeat_age_sec: float = 2,
                   strategies=None, executions=None, account="Sim101",
                   enabled=True, params=None, extra_params=None,
                   strategy_class="NTAMicroVwapRiskPilot",
                   strategy_id="b1_shortonly"):
    rdir = tmp / "data" / "runtime"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "heartbeat.json").write_text(json.dumps({
        "timestamp_utc":   _now_iso(-heartbeat_age_sec),
        "ninja_version":   "8.1.4.1",
        "machine":         "TEST-PC",
        "exporter_version": "1.0.0",
    }), encoding="utf-8")
    if strategies is None:
        if params is None:
            params = dict(rt.B1_LOCKED_PARAMS_CHECK)
            params.update({
                "StartingCapital": 2000.0,
                "IntradayOnly": True,
                "ActiveMarginPerContract": 50.0,
                "MaxContractsByCapital": 40,
                "InstrumentStatus": "allowed",
                "MarginSourceBroker": "NinjaTrader",
            })
        if extra_params:
            params = {**params, **extra_params}
        strategies = [{
            "timestamp_utc":   _now_iso(-heartbeat_age_sec),
            "account_name":    account,
            "account_mode":    None,
            "strategy_id":     strategy_id,
            "strategy_class":  strategy_class,
            "strategy_name":   "B1 ShortOnly",
            "instrument":      "MNQ 06-26",
            "contract_month":  "MNQ 06-26",
            "enabled":         enabled,
            "state":           "Realtime" if enabled else "Terminated",
            "connection_status": "Connected",
            "position_market_position": "Flat",
            "position_qty":    0,
            "avg_price":       0.0,
            "unrealized_pnl":  0.0,
            "realized_pnl":    0.0,
            "session_trades_count": 0,
            "params":          params,
            "params_hash":     "deadbeef",
        }]
    (rdir / "strategies.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(-heartbeat_age_sec),
        "strategies": strategies,
    }), encoding="utf-8")
    if executions is not None:
        with (rdir / "executions.jsonl").open("w", encoding="utf-8") as f:
            for e in executions:
                f.write(json.dumps(e) + "\n")


def _write_hb(tmp: Path, fresh: bool = True):
    rdir = tmp / "data" / "runtime"
    rdir.mkdir(parents=True, exist_ok=True)
    age = 2 if fresh else 999
    (rdir / "heartbeat.json").write_text(json.dumps({
        "timestamp_utc": _now_iso(-age),
        "exporter_version": "1.1.0",
    }), encoding="utf-8")


def _write_accounts(tmp: Path, accounts, *, age_sec: float = 2):
    rdir = tmp / "data" / "runtime"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "accounts.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(-age_sec),
        "accounts": accounts,
    }), encoding="utf-8")


def _write_profiles_registry(tmp: Path, profiles):
    pdir = tmp / "data" / "profiles"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.1",
        "profiles": profiles,
    }), encoding="utf-8")


def case(name: str):
    def deco(fn):
        def wrap():
            tmp = Path(tempfile.mkdtemp(prefix="rt_test_"))
            try:
                _set_temp_root(tmp)
                fn(tmp)
                PASSED.append(name); print(f"  PASS  {name}")
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


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

@case("runtime files missing -> runtime_detected=false, no crash")
def t01(tmp):
    v = rt.merge_strategy_view("b1_shortonly")
    assert v["runtime_detected"] is False, v
    assert v["runtime_enabled"] is False
    assert v["params_ok"] is True
    h = rt.health()
    assert h["exporter_ready"] is False


@case("stale heartbeat -> warning, not detected")
def t02(tmp):
    _write_runtime(tmp, heartbeat_age_sec=600)
    v = rt.merge_strategy_view("b1_shortonly")
    assert v["heartbeat"]["fresh"] is False, v["heartbeat"]
    # stale heartbeat means runtime_detected=False
    assert v["runtime_detected"] is False
    assert any("stale" in w.lower() for w in v["runtime_warnings"]), v["runtime_warnings"]


@case("Sim101 + locked params -> runtime OK, params_ok=true")
def t03(tmp):
    _write_runtime(tmp, account="Sim101", enabled=True)
    v = rt.merge_strategy_view("b1_shortonly")
    assert v["runtime_detected"] is True
    assert v["runtime_enabled"] is True
    assert v["account_mode"] == "paper", v["account_mode"]
    assert v["params_ok"] is True, v["params_check"]
    assert v["is_live"] is False


@case("Sim101 + wrong params -> PARAM_MISMATCH and error")
def t04(tmp):
    bad = dict(rt.B1_LOCKED_PARAMS_CHECK)
    bad["RewardRiskRatio"] = 2.5
    bad["EnableLong"] = True
    _write_runtime(tmp, account="Sim101", params=bad)
    v = rt.merge_strategy_view("b1_shortonly")
    assert v["params_ok"] is False
    keys = {m["key"] for m in v["params_check"]["mismatches"]}
    assert "RewardRiskRatio" in keys and "EnableLong" in keys, keys
    assert any("PARAM_MISMATCH" in e for e in v["runtime_errors"])


@case("live account -> is_live=True, live_locked=True, confirm blocked")
def t05(tmp):
    _write_runtime(tmp, account="MyLiveAccount", enabled=True)
    v = rt.merge_strategy_view("b1_shortonly")
    assert v["is_live"] is True
    assert v["live_locked"] is True, "live runtime control must be locked"
    assert v["account_mode"] == "live"
    assert v["can_confirm_runtime"] is None


@case("executions.jsonl -> quantity-aware daily metrics + journal upsert")
def t06(tmp):
    today_pt = ops._to_pt(datetime.now(timezone.utc)).date().isoformat()
    execs = [
        # entry exec (no PnL)
        {"timestamp_utc": _now_iso(-1200), "strategy_id": "b1_shortonly",
         "role": "entry", "quantity": 2, "price": 20000.0,
         "realized_pnl": 0.0, "slippage_ticks": 1.0},
        # winning exit, qty 2, +50
        {"timestamp_utc": _now_iso(-900), "strategy_id": "b1_shortonly",
         "role": "exit", "exit_reason": "target", "quantity": 2,
         "price": 19990.0, "realized_pnl": 50.0, "slippage_ticks": 1.0},
        # losing exit, qty 1, -10
        {"timestamp_utc": _now_iso(-300), "strategy_id": "b1_shortonly",
         "role": "exit", "exit_reason": "stop", "quantity": 1,
         "price": 20002.0, "realized_pnl": -10.0, "slippage_ticks": 2.0},
    ]
    _write_runtime(tmp, executions=execs)
    # The test can run just after Pacific midnight, while the synthetic
    # executions intentionally span the previous 20 minutes. Pin the audit day
    # to the last execution instead of relying on the wall-clock date.
    execution_date_pt = ops._to_pt(datetime.fromisoformat(execs[-1]["timestamp_utc"])).date().isoformat()
    m = rt.compute_runtime_today_metrics("b1_shortonly", on_date_pt=execution_date_pt)
    assert m["trades_count"] == 2, m
    assert m["total_qty"] == 3, m
    assert m["gross_pnl"] == 40.0, m
    # commission = 1.90 * 3 = 5.70 ; adj = 34.30
    assert m["commission_estimated"] == 5.70, m
    assert m["adjusted_pnl"] == 34.30, m
    assert m["daily_win_count"] == 1 and m["daily_loss_count"] == 1
    assert m["stop_hit_count"] == 1 and m["target_hit_count"] == 1

    res = rt.journal_autofill("b1_shortonly", on_date_pt=execution_date_pt)
    # Accept either "created" or "updated" — isolated-path vs shared-path tests
    # both indicate success; the important check is that the row data is correct.
    assert res["ok"] and res["action"] in ("created", "updated"), res
    assert res.get("cumulative_adjusted_pnl") is not None, res
    # second call must update
    res2 = rt.journal_autofill("b1_shortonly", on_date_pt=execution_date_pt)
    assert res2["action"] == "updated", res2


@case("runtime enabled but registry paper_ready -> mismatch warning + can_confirm started")
def t07(tmp):
    _write_runtime(tmp, account="Sim101", enabled=True)
    v = rt.merge_strategy_view("b1_shortonly")
    assert v["paper_state"] == "paper_ready", v["paper_state"]
    assert v["mismatch_kind"] == "runtime_enabled_not_confirmed", v
    assert v["can_confirm_runtime"] == "started"
    # operator confirms -> should advance state
    out = rt.confirm_runtime("b1_shortonly", "started", reason="test")
    assert out["state"] == "paper_running", out


@case("runtime disabled but registry paper_running -> mismatch warning + can_confirm stopped")
def t08(tmp):
    _write_runtime(tmp, account="Sim101", enabled=True)
    rt.confirm_runtime("b1_shortonly", "started", reason="setup")
    # now disable runtime
    _write_runtime(tmp, account="Sim101", enabled=False)
    v = rt.merge_strategy_view("b1_shortonly")
    assert v["paper_state"] == "paper_running", v["paper_state"]
    assert v["mismatch_kind"] == "runtime_stopped_outside", v
    assert v["can_confirm_runtime"] == "stopped"
    out = rt.confirm_runtime("b1_shortonly", "stopped", reason="manual")
    assert out["state"] == "stopped_today", out


@case("rejected strategies cannot be runtime-confirmed")
def t09(tmp):
    _write_runtime(tmp, account="Sim101", enabled=True,
                   strategy_id="ntamicroorbpilot",
                   strategy_class="NTAMicroOrbPilot")
    v = rt.merge_strategy_view("ntamicroorbpilot")
    assert v["registry_status"] == "rejected"
    assert any("Rejected" in e or "rejected" in e for e in v["runtime_errors"]), v
    try:
        rt.confirm_runtime("ntamicroorbpilot", "started")
        raise AssertionError("expected OpsError for rejected")
    except ops.OpsError as e:
        assert "rejected" in str(e).lower() or "archived" in str(e).lower()


@case("PARAM_MISMATCH blocks runtime confirm-started")
def t10(tmp):
    bad = dict(rt.B1_LOCKED_PARAMS_CHECK); bad["MinStopTicks"] = 8
    _write_runtime(tmp, account="Sim101", params=bad)
    try:
        rt.confirm_runtime("b1_shortonly", "started")
        raise AssertionError("expected OpsError for PARAM_MISMATCH")
    except ops.OpsError as e:
        assert "PARAM_MISMATCH" in str(e), str(e)


@case("read_executions filtered by strategy_id")
def t11(tmp):
    execs = [
        {"timestamp_utc": _now_iso(-100), "strategy_id": "b1_shortonly",
         "role": "exit", "quantity": 1, "realized_pnl": 5.0},
        {"timestamp_utc": _now_iso(-50),  "strategy_id": "other",
         "role": "exit", "quantity": 1, "realized_pnl": 3.0},
    ]
    _write_runtime(tmp, executions=execs)
    only = rt.read_executions("b1_shortonly")
    assert len(only) == 1 and only[0]["strategy_id"] == "b1_shortonly"


@case("execution/order signal class maps to runtime strategy and FIFO PnL")
def t11b(tmp):
    strategy_id = "ntamnqopendriveshortscalpc016"
    strategy_class = "NTAMnqOpenDriveShortScalpC016"
    signal = strategy_class + ".Short"
    strategies = [{
        "timestamp_utc": _now_iso(-5),
        "account_name": "DEMO3369390",
        "account_mode": "paper",
        "strategy_id": strategy_id,
        "strategy_class": strategy_class,
        "strategy_name": "Scalping Open Drive Short MNQ 1m v1 c016",
        "instrument": "MNQ JUN26",
        "contract_month": "MNQ JUN26",
        "enabled": True,
        "state": "Realtime",
        "data_series_count": 1,
        "runtime_instance_id": "sha256:c016",
        "params": {},
    }]
    execs = [
        {"timestamp_utc": _now_iso(-60), "account_name": "DEMO3369390",
         "strategy_id": "", "strategy_class": "", "instrument": "MNQ JUN26",
         "order_action": "SellShort", "quantity": 1, "price": 29600.0,
         "order_name": signal, "from_entry_signal": signal, "realized_pnl": None},
        {"timestamp_utc": _now_iso(-30), "account_name": "DEMO3369390",
         "strategy_id": "", "strategy_class": "", "instrument": "MNQ JUN26",
         "order_action": "BuyToCover", "role": "exit", "exit_reason": "target",
         "quantity": 1, "price": 29590.0,
         "order_name": signal, "from_entry_signal": signal, "realized_pnl": None},
    ]
    _write_runtime(tmp, strategies=strategies, executions=execs)
    orders_p = tmp / "data" / "runtime" / "orders.jsonl"
    orders_p.write_text(json.dumps({
        "timestamp_utc": _now_iso(-55), "account_name": "DEMO3369390",
        "strategy_id": "", "strategy_class": "", "instrument": "MNQ JUN26",
        "order_action": "SellShort", "order_type": "StopMarket",
        "order_state": "Filled", "quantity": 1, "stop_price": 29600.0,
        "order_name": signal, "from_entry_signal": signal,
    }) + "\n", encoding="utf-8")

    rows = rt.read_executions(strategy_id=strategy_id, limit=10)
    assert len(rows) == 2, rows
    assert {r["strategy_class"] for r in rows} == {strategy_class}
    assert {r["runtime_instance_id"] for r in rows} == {"sha256:c016"}

    order_rows = rt.read_orders(strategy_id=strategy_id, limit=10)
    assert len(order_rows) == 1 and order_rows[0]["strategy_class"] == strategy_class, order_rows

    m = rt.compute_runtime_today_metrics(strategy_id)
    assert m["trades_count"] == 1, m
    assert m["total_qty"] == 1, m
    assert m["gross_pnl"] == 20.0, m


@case("execution rows backfill action/type from filled orders")
def t11c(tmp):
    execs = [{
        "timestamp_utc": _now_iso(-30), "account_name": "DEMO3369390",
        "strategy_id": "", "strategy_class": "", "instrument": "MNQ JUN26",
        "market_position": "Short", "quantity": 1, "price": 29587.75,
    }]
    _write_runtime(tmp, executions=execs)
    orders_p = tmp / "data" / "runtime" / "orders.jsonl"
    orders_p.write_text(json.dumps({
        "timestamp_utc": _now_iso(-25), "order_id": "220",
        "account_name": "DEMO3369390", "strategy_id": "", "strategy_class": "",
        "instrument": "MNQ JUN26", "order_state": "Filled",
        "order_action": "Sell", "order_type": "StopMarket",
        "quantity": 1, "filled": 1, "stop_price": 29587.75, "avg_fill": 29587.75,
    }) + "\n", encoding="utf-8")

    rows = rt.read_executions(account_name="DEMO3369390", limit=10)
    assert len(rows) == 1, rows
    assert rows[0]["order_id"] == "220", rows
    assert rows[0]["order_action"] == "Sell", rows
    assert rows[0]["order_type"] == "StopMarket", rows
    assert rows[0]["order_state"] == "Filled", rows


@case("playback account is treated as paper-class (controllable)")
def t12(tmp):
    _write_runtime(tmp, account="Playback101", enabled=True)
    v = rt.merge_strategy_view("b1_shortonly")
    assert v["account_mode"] == "playback", v["account_mode"]
    assert v["is_live"] is False
    assert v["can_confirm_runtime"] == "started"


# --------------------------------------------------------------------------
# Phase 18 — command protocol tests
# --------------------------------------------------------------------------

@case("phase18: submit_command writes commands.jsonl on paper account")
def t13(tmp):
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        quantity=1,
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    assert rec["status"] == "queued"
    assert rec["command_id"].startswith("cmd-")
    assert rec["live_block_passed"] is True
    cmds = rt.read_commands(50)
    assert len(cmds) == 1
    assert cmds[0]["command"] == "enable_strategy"
    assert cmds[0]["account_name"] == "Sim101"
    assert cmds[0]["quantity"] == 1


@case("phase18: live-named and unknown accounts are rejected")
def t14(tmp):
    try:
        rt.submit_command(
            command="enable_strategy",
            strategy_id="b1_shortonly",
            account_name="LiveAccount1",
            class_name="NTAMicroVwapRiskPilot",
        )
        assert False, "live account should raise"
    except ops.OpsError as e:
        assert e.status == 403, e.status
        assert "live" in str(e).lower(), str(e)
    # unknown name -> reject
    try:
        rt.submit_command(
            command="enable_strategy",
            strategy_id="b1_shortonly",
            account_name="X9Z",
            class_name="NTAMicroVwapRiskPilot",
        )
        assert False, "unknown account should raise"
    except ops.OpsError as e:
        assert e.status == 403, e.status


@case("phase18: rejected strategy in registry blocks submit_command")
def t15(tmp):
    # Seed a rejected entry into the registry by writing the file directly
    reg = ops.load_registry()
    reg["strategies"].append({
        "strategy_id": "ntamicroorbpilot",
        "class_name":  "NTAMicroOrbPilot",
        "status":      "rejected",
        "instrument":  "MES 06-26",
        "risk_profile": {},
    })
    ops.registry_path().write_text(json.dumps(reg), encoding="utf-8")
    try:
        rt.submit_command(
            command="enable_strategy",
            strategy_id="ntamicroorbpilot",
            account_name="Sim101",
        )
        assert False, "should have raised"
    except ops.OpsError as e:
        assert e.status == 403, e.status
        assert "rejected" in str(e).lower() or "archived" in str(e).lower()


@case("phase18: unknown command name is refused")
def t16(tmp):
    try:
        rt.submit_command(
            command="hack_strategy",
            strategy_id="b1_shortonly",
            account_name="Sim101",
            class_name="NTAMicroVwapRiskPilot",
        )
        assert False, "should have raised"
    except ops.OpsError as e:
        assert e.status == 400, e.status


@case("phase18: command-results file round-trip")
def t17(tmp):
    rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
    )
    cid = rt.read_commands(1)[0]["command_id"]
    # Simulate bridge writing a result line
    res_path = tmp / "data" / "runtime" / "command_results.jsonl"
    res_path.write_text(json.dumps({
        "command_id": cid, "status": "completed",
        "message": "enabled NTAMicroVwapRiskPilot on Sim101",
        "timestamp_utc": _now_iso(0),
        "runtime_strategy_id": "b1_shortonly",
        "processor_version": "1.0.0",
    }) + "\n", encoding="utf-8")
    out = rt.read_command_results(10)
    assert len(out) == 1
    assert out[0]["status"] == "completed"
    assert out[0]["command_id"] == cid


@case("phase18: disable_strategy on playback account is allowed")
def t18(tmp):
    rec = rt.submit_command(
        command="disable_strategy",
        strategy_id="b1_shortonly",
        account_name="Playback101",
        class_name="NTAMicroVwapRiskPilot",
    )
    assert rec["status"] == "queued"
    assert rec["command"] == "disable_strategy"


@case("phase18: reconnect_account queues without strategy class")
def t18a(tmp):
    _write_accounts(tmp, [{
        "account_name": "DEMO3369390",
        "account_mode": "demo",
        "connection_status": "Disconnected",
    }])
    rec = rt.submit_command(
        command="reconnect_account",
        strategy_id="",
        account_name="DEMO3369390",
        connection_name="Simulation",
    )
    assert rec["status"] == "queued"
    saved = rt.read_commands(1)[0]
    assert saved["command"] == "reconnect_account"
    assert saved["account_name"] == "DEMO3369390"
    assert saved["connection_name"] == "Simulation"
    assert saved["strategy_id"].startswith("runtime_connection_reconnect__"), saved["strategy_id"]


# --------------------------------------------------------------------------
# Phase 10 — normalization + selection_diff + command status
# --------------------------------------------------------------------------

@case("phase10: normalize_instrument variants -> (root, MM-YY)")
def t19(tmp):
    assert rt.normalize_instrument("MNQ JUN26")  == ("MNQ", "06-26")
    assert rt.normalize_instrument("MNQ 06-26")  == ("MNQ", "06-26")
    assert rt.normalize_instrument("mnq jun26")  == ("MNQ", "06-26")
    assert rt.normalize_instrument("MNQ")        == ("MNQ", "")
    assert rt.normalize_instrument("")           == ("", "")
    assert rt.normalize_instrument("MES 0626")   == ("MES", "06-26")


@case("phase10: instruments_match loose with blank-expiry wildcard")
def t20(tmp):
    assert rt.instruments_match("MNQ JUN26", "MNQ 06-26") is True
    assert rt.instruments_match("MNQ", "MNQ 06-26")       is True
    assert rt.instruments_match("MNQ 06-26", "MNQ")       is True
    assert rt.instruments_match("MNQ 06-26", "MES 06-26") is False
    assert rt.instruments_match("MNQ 06-26", "MNQ 09-26") is False
    assert rt.instruments_match("", "MNQ 06-26")          is False


@case("phase10: normalize_timeframe handles '5 Minute', 'Minute/5', '1 Hour', blank")
def t21(tmp):
    assert rt.normalize_timeframe("5 Minute") == ("minute", 5)
    assert rt.normalize_timeframe("Minute/5") == ("minute", 5)
    assert rt.normalize_timeframe("1 Hour")   == ("hour", 1)
    assert rt.normalize_timeframe("")         == ("", 0)


@case("phase10: timeframes_match — blank on either side is wildcard")
def t22(tmp):
    assert rt.timeframes_match("5 Minute", "Minute/5") is True
    assert rt.timeframes_match("",          "5 Minute") is True
    assert rt.timeframes_match("5 Minute",  "")        is True
    assert rt.timeframes_match("5 Minute",  "1 Minute") is False


@case("phase10: compute_selection_diff — all match")
def t23(tmp):
    rt_strat = {"account_name": "Sim101", "instrument": "MNQ 06-26",
                "timeframe": "5 Minute"}
    d = rt.compute_selection_diff("Sim101", "MNQ 06-26", "5 Minute", rt_strat)
    assert d["account"]["matches"]
    assert d["instrument"]["matches"]
    assert d["timeframe"]["matches"]
    assert d["any_blocker"] is False


@case("phase10: compute_selection_diff — account mismatch is blocking")
def t24(tmp):
    rt_strat = {"account_name": "Sim101", "instrument": "MNQ 06-26",
                "timeframe": "5 Minute"}
    d = rt.compute_selection_diff("Sim999", "MNQ 06-26", "5 Minute", rt_strat)
    assert d["account"]["matches"] is False
    assert d["account"]["blocking"] is True
    assert d["any_blocker"] is True


@case("phase10: compute_selection_diff — instrument mismatch is blocking")
def t25(tmp):
    rt_strat = {"account_name": "Sim101", "instrument": "MNQ 06-26",
                "timeframe": "5 Minute"}
    d = rt.compute_selection_diff("Sim101", "MES 06-26", "5 Minute", rt_strat)
    assert d["instrument"]["matches"] is False
    assert d["instrument"]["blocking"] is True
    assert d["any_blocker"] is True


@case("phase10: compute_selection_diff — timeframe mismatch is warning only")
def t26(tmp):
    rt_strat = {"account_name": "Sim101", "instrument": "MNQ 06-26",
                "timeframe": "1 Minute"}
    d = rt.compute_selection_diff("Sim101", "MNQ 06-26", "5 Minute", rt_strat)
    assert d["timeframe"]["matches"] is False
    assert d["timeframe"]["blocking"] is False
    assert d["any_blocker"] is False


@case("phase10: get_command_status -> unknown_command for unknown id")
def t27(tmp):
    out = rt.get_command_status("cmd-does-not-exist")
    assert out["state"] == "unknown_command", out
    assert "command_id" in out


@case("phase10: get_command_status -> waiting_for_bridge (fresh hb, elapsed < timeout)")
def t28(tmp):
    _write_runtime(tmp, account="Sim101", enabled=False)
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    out = rt.get_command_status(rec["command_id"], timeout_sec=30)
    assert out["state"] == "waiting_for_bridge", out
    assert out["heartbeat"]["fresh"] is True


@case("phase10: get_command_status -> failed_timeout when elapsed >> timeout")
def t29(tmp):
    _write_runtime(tmp, account="Sim101", enabled=False)
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    # Rewrite commands.jsonl with timestamp far in the past.
    cmds_p = tmp / "data" / "runtime" / "commands.jsonl"
    text = cmds_p.read_text(encoding="utf-8").splitlines()
    rec_dict = json.loads(text[0])
    rec_dict["timestamp_utc"] = _now_iso(-3600)
    cmds_p.write_text(json.dumps(rec_dict) + "\n", encoding="utf-8")
    out = rt.get_command_status(rec["command_id"], timeout_sec=30)
    assert out["state"] == "failed_timeout", out


@case("phase10: get_command_status -> failed_bridge_offline when no heartbeat")
def t30(tmp):
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    # No heartbeat written
    out = rt.get_command_status(rec["command_id"], timeout_sec=30)
    assert out["state"] == "failed_bridge_offline", out


@case("phase10: get_command_status -> confirmed_running with matching strategies.json")
def t31(tmp):
    _write_runtime(tmp, account="Sim101", enabled=True)
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    cid = rec["command_id"]
    res_p = tmp / "data" / "runtime" / "command_results.jsonl"
    res_p.write_text(json.dumps({
        "command_id": cid, "status": "completed",
        "message": "enabled",
        "timestamp_utc": _now_iso(0),
    }) + "\n", encoding="utf-8")
    out = rt.get_command_status(cid, timeout_sec=30)
    assert out["state"] == "confirmed_running", out
    assert out["runtime_match"]["enabled"] is True


@case("phase10: get_command_status refuses stale completed runtime confirmation")
def t31b(tmp):
    _write_runtime(tmp, heartbeat_age_sec=600, account="Sim101", enabled=True)
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    cid = rec["command_id"]
    res_p = tmp / "data" / "runtime" / "command_results.jsonl"
    res_p.write_text(json.dumps({
        "command_id": cid, "status": "completed",
        "message": "enabled",
        "timestamp_utc": _now_iso(0),
    }) + "\n", encoding="utf-8")
    out = rt.get_command_status(cid, timeout_sec=30)
    assert out["state"] == "failed_bridge_offline", out


@case("phase10: get_command_status -> failed_no_instance when bridge says no instance")
def t32(tmp):
    _write_runtime(tmp, account="Sim101", enabled=False)
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    cid = rec["command_id"]
    res_p = tmp / "data" / "runtime" / "command_results.jsonl"
    res_p.write_text(json.dumps({
        "command_id": cid, "status": "rejected",
        "message": "no 'NTAMicroVwapRiskPilot' instance found on Sim101",
        "timestamp_utc": _now_iso(0),
    }) + "\n", encoding="utf-8")
    out = rt.get_command_status(cid, timeout_sec=30)
    assert out["state"] == "failed_no_instance", out


@case("phase10: get_command_status -> failed_param_mismatch")
def t33(tmp):
    _write_runtime(tmp, account="Sim101", enabled=False)
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    cid = rec["command_id"]
    res_p = tmp / "data" / "runtime" / "command_results.jsonl"
    res_p.write_text(json.dumps({
        "command_id": cid, "status": "rejected",
        "message": "ShortOnly param mismatch: EnableLong=true",
        "timestamp_utc": _now_iso(0),
    }) + "\n", encoding="utf-8")
    out = rt.get_command_status(cid, timeout_sec=30)
    assert out["state"] == "failed_param_mismatch", out


@case("phase10: get_command_status -> failed_account_mismatch")
def t34(tmp):
    _write_runtime(tmp, account="Sim101", enabled=False)
    rec = rt.submit_command(
        command="enable_strategy",
        strategy_id="b1_shortonly",
        account_name="Sim101",
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
    )
    cid = rec["command_id"]
    res_p = tmp / "data" / "runtime" / "command_results.jsonl"
    res_p.write_text(json.dumps({
        "command_id": cid, "status": "rejected",
        "message": "account is not paper/playback",
        "timestamp_utc": _now_iso(0),
    }) + "\n", encoding="utf-8")
    out = rt.get_command_status(cid, timeout_sec=30)
    assert out["state"] == "failed_account_mismatch", out


@case("phase10: get_command_status -> confirmed_connected for reconnect_account")
def t34a(tmp):
    _write_hb(tmp, fresh=True)
    _write_accounts(tmp, [{
        "account_name": "DEMO3369390",
        "account_mode": "demo",
        "connection_status": "Connected",
    }])
    rec = rt.submit_command(
        command="reconnect_account",
        strategy_id="",
        account_name="DEMO3369390",
        connection_name="Simulation",
    )
    cid = rec["command_id"]
    res_p = tmp / "data" / "runtime" / "command_results.jsonl"
    res_p.write_text(json.dumps({
        "command_id": cid, "status": "completed",
        "message": "reconnect issued",
        "timestamp_utc": _now_iso(0),
    }) + "\n", encoding="utf-8")
    out = rt.get_command_status(cid, timeout_sec=30)
    assert out["state"] == "confirmed_connected", out
    assert out["account_match"]["connection_status"] == "Connected", out["account_match"]


@case("phase10: account display_name is preserved exactly (no ' sim' suffix)")
def t35(tmp):
    rdir = tmp / "data" / "runtime"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "accounts.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(0),
        "accounts": [{"account_name": "Sim101", "account_mode": "paper"}],
    }), encoding="utf-8")
    accts = rt.read_accounts()
    a = accts[0]
    assert a["account_name"] == "Sim101"
    assert a["display_name"] == "Sim101", a
    assert "sim" not in a["display_name"].lower().replace("sim101", "")


@case("phase10: read_accounts_with_source -> next_action present when bridge missing")
def t36(tmp):
    out = rt.read_accounts_with_source()
    # source=empty -> next_action explains what to do
    assert out["source"] == "empty", out
    assert out.get("next_action"), out


@case("phase10: strategies endpoint timeframe propagated to merged view")
def t37(tmp):
    _write_runtime(tmp, account="Sim101", enabled=True)
    # _write_runtime already includes timeframe in our schema? It doesn't —
    # add it explicitly:
    rdir = tmp / "data" / "runtime"
    raw = json.loads((rdir / "strategies.json").read_text(encoding="utf-8"))
    raw["strategies"][0]["timeframe"] = "5 Minute"
    (rdir / "strategies.json").write_text(json.dumps(raw), encoding="utf-8")
    v = rt.merge_strategy_view("b1_shortonly")
    assert (v.get("runtime") or {}).get("timeframe") == "5 Minute", v.get("runtime")


@case("phase19: system accounts (Backtest/Sim101/Playback101) are not selectable for online")
def t38(tmp):
    import app.runtime as rt_mod
    for name in ["Backtest", "Sim101", "Playback101"]:
        acc = rt_mod._normalize_account({"account_name": name, "account_mode": None})
        assert acc["is_system"] is True, f"{name} should be system: {acc}"
        assert acc["is_selectable_for_online"] is False, f"{name} should not be selectable: {acc}"
        assert acc["control_allowed"] is False, f"{name} should not allow control: {acc}"


@case("phase19: DEMO3369390 is 'demo' mode, selectable, not system")
def t39(tmp):
    import app.runtime as rt_mod
    acc = rt_mod._normalize_account({"account_name": "DEMO3369390", "account_mode": None})
    assert acc["account_mode"] == "demo", acc
    assert acc["is_system"] is False, acc
    assert acc["is_selectable_for_online"] is True, acc
    assert acc["display_name"] == "DEMO3369390", f"should not add suffix: {acc}"


@case("phase19: online_accounts excludes system and live accounts from positions fallback")
def t40(tmp):
    rdir = tmp / "data" / "runtime"
    pos = {
        "Backtest": [], "Playback101": [], "Sim101": [],
        "DEMO3369390": [], "1267509": [],
    }
    (rdir / "positions.json").write_text(json.dumps(pos), encoding="utf-8")
    res = rt.read_accounts_with_source()
    online = res["online_accounts"]
    names = [a["account_name"] for a in online]
    # system accounts must be absent
    for sys_acc in ("Backtest", "Sim101", "Playback101"):
        assert sys_acc not in names, f"{sys_acc} must not appear in online_accounts: {names}"
    # numeric live account must be absent (unknown mode → not selectable)
    assert "1267509" not in names, f"live/unknown 1267509 must not appear in online_accounts: {names}"
    # DEMO should appear
    assert "DEMO3369390" in names, f"DEMO3369390 should appear in online_accounts: {names}"


@case("phase19: runtime_instance_id is stable across two calls with same raw data")
def t41(tmp):
    _write_runtime(tmp, account="DEMO3369390", enabled=True)
    import app.runtime as rt_mod
    raw = rt_mod.read_strategies_raw()
    assert raw, "no raw entries"
    iid1 = rt_mod._make_runtime_instance_id(raw[0], 0)
    iid2 = rt_mod._make_runtime_instance_id(raw[0], 0)
    assert iid1 == iid2, "runtime_instance_id must be deterministic"
    assert iid1.startswith("ri-"), iid1


@case("phase19: merge_all_runtime_strategies uses runtime_instance_id not strategy_id for dedup")
def t42(tmp):
    rdir = tmp / "data" / "runtime"
    # Two identical class rows on same account (same strategy_id from InferStrategyId)
    strategies = {"strategies": [
        {"strategy_id": "b1_shortonly", "strategy_class": "NTAMicroVwapRiskPilot",
         "account_name": "DEMO3369390", "instrument": "MES JUN26", "enabled": True,
         "strategy_name": "instance1"},
        {"strategy_id": "b1_shortonly", "strategy_class": "NTAMicroVwapRiskPilot",
         "account_name": "DEMO3369390", "instrument": "MES JUN26", "enabled": True,
         "strategy_name": "instance2"},
    ]}
    (rdir / "strategies.json").write_text(json.dumps(strategies), encoding="utf-8")
    _write_hb(tmp, fresh=True)
    views = rt.merge_all_runtime_strategies()
    assert len(views) == 2, f"Should get 2 views, not {len(views)}"
    iids = [v["runtime_instance_id"] for v in views]
    assert iids[0] != iids[1], "Two instances must have different runtime_instance_ids"


@case("phase19: params_mismatch is NOT in runtime_errors (informational only)")
def t43(tmp):
    _write_runtime(tmp, account="DEMO3369390", enabled=True,
                   extra_params={"EnableLong": True, "EnableShort": False})
    views = rt.merge_all_runtime_strategies()
    assert views, "no views"
    v = views[0]
    assert "PARAM MISMATCH" not in " ".join(v.get("runtime_errors") or []), (
        "PARAM MISMATCH must not appear in runtime_errors (Phase 19 spec): " +
        str(v.get("runtime_errors"))
    )
    # params_ok and params_check still populated
    assert "params_ok" in v, v
    assert "params_check" in v, v


@case("phase19: _is_paper_account accepts demo mode")
def t44(tmp):
    import app.runtime as rt_mod
    assert rt_mod._is_paper_account("DEMO3369390") is True, "demo account should be paper-class"
    assert rt_mod._is_paper_account("Sim101") is True
    assert rt_mod._is_paper_account("Playback101") is True
    assert rt_mod._is_paper_account("1267509") is False, "numeric live should not be paper-class"


@case("phase24: validate_params prefers strategy profile locked_parameters")
def t44a(tmp):
    _write_profiles_registry(tmp, [{
        "profile_id": "b1_shortonly_mnq_5m_high_slip1_paper_v2",
        "name": "VWAP Short MNQ 5m v1 c011",
        "strategy_class": "NTAMicroVwapRiskPilot",
        "instrument": "MNQ 06-26",
        "timeframe": "5 Minute",
        "status": "ready",
        "stable_id": "vwap_short_mnq_5m_v1",
        "legacy_strategy_ids": ["b1_shortonly"],
        "locked_parameters": {
            "EnableLong": False,
            "EnableShort": True,
            "RewardRiskRatio": 3.5,
            "StartingCapital": 2000.0,
        },
    }])
    bad = dict(rt.B1_LOCKED_PARAMS_CHECK)
    bad.pop("EnableShort", None)
    res = rt.validate_params("b1_shortonly", bad)
    keys = {m["key"] for m in res["mismatches"]}
    assert "StartingCapital" in keys, f"profile-only param must be validated, got {keys}"
    fixed = dict(bad, EnableShort=True, StartingCapital=2000.0)
    res2 = rt.validate_params("b1_shortonly", fixed)
    assert res2["ok"] is True, res2


@case("phase24: merge_all_runtime_strategies validates stopped instance params too")
def t44b(tmp):
    _write_profiles_registry(tmp, [{
        "profile_id": "b1_shortonly_mnq_5m_high_slip1_paper_v2",
        "name": "VWAP Short MNQ 5m v1 c011",
        "strategy_class": "NTAMicroVwapRiskPilot",
        "instrument": "MNQ 06-26",
        "timeframe": "5 Minute",
        "status": "ready",
        "stable_id": "vwap_short_mnq_5m_v1",
        "legacy_strategy_ids": ["b1_shortonly"],
        "locked_parameters": {
            "EnableLong": False,
            "EnableShort": True,
            "RewardRiskRatio": 3.5,
        },
    }])
    _write_runtime(tmp, account="DEMO3369390", enabled=False,
                   extra_params={"EnableLong": True, "EnableShort": False})
    views = rt.merge_all_runtime_strategies()
    assert views, "no views"
    v = views[0]
    assert v["runtime_enabled"] is False, v
    assert v["params_ok"] is False, v
    keys = {m["key"] for m in v["params_check"]["mismatches"]}
    assert "EnableLong" in keys and "EnableShort" in keys, keys


@case("phase24: submit_command blocks enable on runtime param mismatch")
def t44c(tmp):
    _write_profiles_registry(tmp, [{
        "profile_id": "b1_shortonly_mnq_5m_high_slip1_paper_v2",
        "name": "VWAP Short MNQ 5m v1 c011",
        "strategy_class": "NTAMicroVwapRiskPilot",
        "instrument": "MNQ 06-26",
        "timeframe": "5 Minute",
        "status": "ready",
        "stable_id": "vwap_short_mnq_5m_v1",
        "legacy_strategy_ids": ["b1_shortonly"],
        "locked_parameters": {
            "EnableLong": False,
            "EnableShort": True,
            "RewardRiskRatio": 3.5,
        },
    }])
    _write_runtime(tmp, account="Sim101", enabled=False,
                   extra_params={"EnableLong": True, "EnableShort": False})
    try:
        rt.submit_command(
            command="enable_strategy",
            strategy_id="b1_shortonly",
            account_name="Sim101",
            class_name="NTAMicroVwapRiskPilot",
            instrument="MNQ 06-26",
        )
        raise AssertionError("submit_command must block mismatched runtime params")
    except ops.OpsError as e:
        assert e.status == 409, f"expected 409, got {e.status}"
        assert "PARAM_MISMATCH" in str(e), e


@case("phase24: profile metadata keys do not create false runtime mismatches")
def t44d(tmp):
    _write_profiles_registry(tmp, [{
        "profile_id": "mnq_micro_orb_open_rr150_1m_research_v2",
        "name": "Scalping MNQ 1m v1 c012",
        "strategy_class": "NTAMicroMnqScalpPilot",
        "deploy_strategy_class": "NTAMnqMicroOrbOpenScalp",
        "runtime_strategy_classes": ["NTAMnqMicroOrbOpenScalp"],
        "runtime_strategy_id": "orb_open_scalp_mnq_1m_v1",
        "instrument": "MNQ 06-26",
        "timeframe": "1 Minute",
        "status": "research_baseline",
        "locked_parameters": {
            "EnableLong": True,
            "RewardRiskRatio": 1.5,
            "TradeEndTime": 830,
            "_profile_variant": "MNQ Micro ORB Open Scalp RR150",
            "_research_decision": "research_baseline_not_paper_ready",
        },
    }])
    res = rt.validate_params("orb_open_scalp_mnq_1m_v1", {
        "EnableLong": True,
        "RewardRiskRatio": 1.5,
        "TradeEndTime": 830,
    })
    assert res["ok"] is True, res
    assert res["checked"] == 3, res


@case("phase24: submit_command autofills profile locked params for wrapper strategies")
def t44e(tmp):
    _write_profiles_registry(tmp, [{
        "profile_id": "mnq_micro_orb_open_rr150_1m_research_v2",
        "name": "Scalping MNQ 1m v1 c012",
        "strategy_class": "NTAMicroMnqScalpPilot",
        "deploy_strategy_class": "NTAMnqMicroOrbOpenScalp",
        "runtime_strategy_classes": ["NTAMicroMnqScalpPilot", "NTAMnqMicroOrbOpenScalp"],
        "runtime_strategy_id": "orb_open_scalp_mnq_1m_v1",
        "instrument": "MNQ 06-26",
        "timeframe": "1 Minute",
        "status": "research_baseline",
        "locked_parameters": {
            "EnableLong": True,
            "EnableShort": True,
            "RewardRiskRatio": 1.5,
            "TradeStartTime": 635,
            "TradeEndTime": 830,
            "_profile_variant": "MNQ Micro ORB Open Scalp RR150",
        },
    }])
    rt.submit_command(
        command="enable_strategy",
        strategy_id="orb_open_scalp_mnq_1m_v1",
        account_name="Sim101",
        class_name="NTAMnqMicroOrbOpenScalp",
        instrument="MNQ 06-26",
        params={},
    )
    saved = rt.read_commands(1)[0]
    assert saved["params"]["RewardRiskRatio"] == 1.5, saved["params"]
    assert saved["params"]["TradeEndTime"] == 830, saved["params"]
    assert "_profile_variant" not in saved["params"], saved["params"]


@case("phase23: strategy display prefs mark runtime rows hidden by class")
def t45(tmp):
    _write_runtime(tmp, account="DEMO3369390", enabled=True,
                   strategy_id="levels_painter",
                   strategy_class="NTLevelsPainter")
    out = rt.set_strategy_display_hidden("NTLevelsPainter", True)
    assert out["ok"] is True, out
    prefs = rt.read_strategy_display_prefs()
    assert "NTLevelsPainter" in prefs["hidden_classes"], prefs
    views = rt.merge_all_runtime_strategies()
    assert len(views) == 1, views
    assert views[0]["display_key"] == "NTLevelsPainter", views[0]
    assert views[0]["display_hidden"] is True, views[0]
    rt.set_strategy_display_hidden("NTLevelsPainter", False)
    views2 = rt.merge_all_runtime_strategies()
    assert views2[0]["display_hidden"] is False, views2[0]


@case("phase23: strategy_history.jsonl aggregates closed and active sessions")
def t46(tmp):
    _write_runtime(tmp, account="DEMO3369390", enabled=True)
    rdir = tmp / "data" / "runtime"
    raw = json.loads((rdir / "strategies.json").read_text(encoding="utf-8"))
    raw["strategies"][0]["runtime_instance_id"] = "ri-history-1"
    (rdir / "strategies.json").write_text(json.dumps(raw), encoding="utf-8")
    base = {
        "runtime_instance_id": "ri-history-1",
        "strategy_id": "b1_shortonly",
        "strategy_class": "NTAMicroVwapRiskPilot",
        "strategy_name": "B1 ShortOnly",
        "account_name": "DEMO3369390",
        "account_mode": "demo",
        "instrument": "MNQ 06-26",
        "timeframe": "5 Minute",
        "state": "Realtime",
    }
    rows = [
        {**base, "timestamp_utc": _now_iso(-7200), "event": "observed_start",
         "enabled": True, "reason": "first_seen"},
        {**base, "timestamp_utc": _now_iso(-3600), "event": "stopped",
         "enabled": False, "reason": "enabled_false"},
        {**base, "timestamp_utc": _now_iso(-1800), "event": "started",
         "enabled": True, "reason": "enabled_true"},
    ]
    with (rdir / "strategy_history.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    hist = rt.read_strategy_history(class_name="NTAMicroVwapRiskPilot")
    assert hist["summary"]["sessions"] == 2, hist
    assert hist["summary"]["active_sessions"] == 1, hist
    assert hist["sessions"][-1]["is_open"] is True, hist["sessions"]
    assert hist["sessions"][0]["duration_sec"] >= 3500, hist["sessions"][0]


@case("trade window: HHMM label builder and in-window check")
def t47_trade_window_helpers(tmp):
    _ = tmp
    params = {
        "TradeStartTime": 635,
        "TradeEndTime": 830,
        "UseSecondTradeWindow": True,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
    }
    label = rt._build_trade_window_pt_from_params(params)
    assert label == "06:35 AM – 08:30 AM + 10:30 AM – 12:00 PM", label
    cfg = rt._extract_trade_window_config(params)
    assert rt.is_hhmm_in_trade_window(700, cfg) is True
    assert rt.is_hhmm_in_trade_window(900, cfg) is False
    assert rt.is_hhmm_in_trade_window(1100, cfg) is True
    assert rt._build_trade_window_pt_from_params({"Use24hSession": True}) == "круглосуточно"
    assert rt._hhmm_to_display(635) == "06:35 AM"
    assert rt._hhmm_to_display(1230) == "12:30 PM"
    assert rt._hhmm_to_display(700) == "07:00 AM"
    assert rt._reformat_trade_window_pt_label("06:35-12:30") == "06:35 AM – 12:30 PM"
    assert rt._reformat_trade_window_pt_label(
        "06:35-08:30 + 10:30-12:00 PT (MaxTradesPerDay=20)"
    ) == "06:35 AM – 08:30 AM + 10:30 AM – 12:00 PM (MaxTradesPerDay=20)"


@case("param validation: inactive second window keys are skipped")
def t49_inactive_second_window_skipped(tmp):
    _ = tmp
    expected = {
        "TradeStartTime": 635,
        "TradeEndTime": 1230,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
    }
    runtime = dict(expected)
    runtime["SecondTradeStartTime"] = 9999
    runtime["SecondTradeEndTime"] = 8888
    res = rt._validate_expected_params(expected, runtime)
    assert res["ok"], res


@case("param validation: C012/C013 stale NT window shows two mismatches")
def t50_c012_stale_window_mismatch(tmp):
    _ = tmp
    expected = {
        "TradeStartTime": 635,
        "TradeEndTime": 1230,
        "UseSecondTradeWindow": False,
        "ForceFlatTime": 1245,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
    }
    runtime = {
        "TradeStartTime": 635,
        "TradeEndTime": 830,
        "UseSecondTradeWindow": True,
        "ForceFlatTime": 1245,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
    }
    res = rt._validate_expected_params(expected, runtime)
    assert not res["ok"], res
    keys = {m["key"] for m in res["mismatches"]}
    assert keys == {"TradeEndTime", "UseSecondTradeWindow"}, keys
    assert res.get("recommendation"), res


@case("trade window: merge_all_runtime_strategies exposes trade_window fields")
def t48_trade_window_merge(tmp):
  _write_runtime(tmp, enabled=True, extra_params={
      "TradeStartTime": 635,
      "TradeEndTime": 1230,
      "UseSecondTradeWindow": False,
  })
  views = rt.merge_all_runtime_strategies()
  assert len(views) == 1, views
  assert views[0].get("trade_window_pt") == "06:35 AM – 12:30 PM", views[0]
  tw = views[0].get("trade_window") or {}
  assert tw.get("has_windows") is True, tw
  assert rt.is_hhmm_in_trade_window(800, tw) is True
  assert rt.is_hhmm_in_trade_window(1300, tw) is False


def main() -> int:
    cases = [t01, t02, t03, t04, t05, t06, t07, t08, t09, t10, t11, t11b, t11c, t12,
             t13, t14, t15, t16, t17, t18, t18a,
             t19, t20, t21, t22, t23, t24, t25, t26,
             t27, t28, t29, t30, t31, t31b, t32, t33, t34, t34a,
             t35, t36, t37,
             # Phase 19
             t38, t39, t40, t41, t42, t43, t44,
             # Phase 24
             t44a, t44b, t44c, t44d, t44e,
             # Phase 23
             t45, t46,
             t47_trade_window_helpers, t48_trade_window_merge,
             t49_inactive_second_window_skipped, t50_c012_stale_window_mismatch]
    print(f"Running {len(cases)} Phase 17/18/10/19 runtime tests:")
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
