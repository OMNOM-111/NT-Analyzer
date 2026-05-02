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
    base = tmp.parent / "РАЗРАБОТКА СТРАТЕГИЙ" / "PAPER_B1_SHORTONLY"
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
                   enabled=True, params=None, strategy_class="NTAMicroVwapRiskPilot",
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


@case("live account -> is_live, live_locked, no confirm allowed")
def t05(tmp):
    _write_runtime(tmp, account="MyLiveAccount", enabled=True)
    v = rt.merge_strategy_view("b1_shortonly")
    assert v["is_live"] is True
    assert v["live_locked"] is True
    assert v["account_mode"] == "live"
    assert v["can_confirm_runtime"] is None
    try:
        rt.confirm_runtime("b1_shortonly", "started")
        raise AssertionError("expected OpsError for live confirm")
    except ops.OpsError as e:
        assert "LIVE" in str(e) or "live" in str(e).lower()


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
    m = rt.compute_runtime_today_metrics("b1_shortonly")
    assert m["trades_count"] == 2, m
    assert m["total_qty"] == 3, m
    assert m["gross_pnl"] == 40.0, m
    # commission = 1.90 * 3 = 5.70 ; adj = 34.30
    assert m["commission_estimated"] == 5.70, m
    assert m["adjusted_pnl"] == 34.30, m
    assert m["daily_win_count"] == 1 and m["daily_loss_count"] == 1
    assert m["stop_hit_count"] == 1 and m["target_hit_count"] == 1

    res = rt.journal_autofill("b1_shortonly")
    assert res["ok"] and res["action"] == "created", res
    # second call must update, not create
    res2 = rt.journal_autofill("b1_shortonly")
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


@case("phase18: live account command is hard-rejected (never written)")
def t14(tmp):
    try:
        rt.submit_command(
            command="enable_strategy",
            strategy_id="b1_shortonly",
            account_name="LiveAccount1",
            class_name="NTAMicroVwapRiskPilot",
        )
        assert False, "should have raised"
    except ops.OpsError as e:
        assert e.status == 403, e.status
        assert "live" in str(e).lower() or "paper" in str(e).lower()
    # File must not be created
    assert rt.read_commands(50) == []


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


def main() -> int:
    cases = [t01, t02, t03, t04, t05, t06, t07, t08, t09, t10, t11, t12,
             t13, t14, t15, t16, t17, t18]
    print(f"Running {len(cases)} Phase 17/18 runtime tests:")
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
