"""
Strategy Control Center tests (SCC v2).

Tests:
  t01 - Old reports/jobs are always visible (even if strategy is archived)
  t02 - /api/scc/strategies returns only active strategy (NTAMicroVwapRiskPilot)
  t03 - Rejected classes are excluded from active list
  t04 - submit_command raises OpsError 403 for rejected class
  t05 - B1 ShortOnly locked params mismatch is detected
  t06 - Runtime response includes required fields: account, instrument, timeframe, enabled
  t07 - SCC endpoint survives missing NT Strategies folder gracefully
  t08 - Bridge offline -> runtime_detected=False (no fake running status)

Run: python -m tests.test_scc
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


# ---------------------------------------------------------------------------
# Harness (mirrors test_runtime.py)
# ---------------------------------------------------------------------------

def _set_temp_root(tmp: Path) -> None:
    ops._project_root = lambda: tmp  # type: ignore[assignment]
    (tmp / "data" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    # Minimal files needed so ops internals do not crash on missing dirs
    base = tmp.parent / "RAZRABOTKA" / "PAPER_B1_SHORTONLY"
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


def _write_strategies(tmp: Path, account: str = "Sim101", enabled: bool = True,
                      strategy_class: str = "NTAMicroVwapRiskPilot",
                      strategy_id: str = "b1_shortonly",
                      instrument: str = "MNQ 06-26",
                      timeframe: str = "1 Minute",
                      params: Dict[str, Any] = None) -> None:
    rt_dir = tmp / "data" / "runtime"
    rt_dir.mkdir(parents=True, exist_ok=True)
    if params is None:
        params = dict(rt.B1_LOCKED_PARAMS_CHECK)
    (rt_dir / "strategies.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(-2),
        "strategies": [{
            "strategy_id":     strategy_id,
            "strategy_class":  strategy_class,
            "account_name":    account,
            "account_mode":    None,
            "enabled":         enabled,
            "state":           "Realtime" if enabled else "Terminated",
            "instrument":      instrument,
            "timeframe":       timeframe,
            "contract_month":  "MNQ 06-26",
            "params":          params or {},
        }],
    }), encoding="utf-8")


def case(name: str):
    """Test-case decorator - passes tmp Path to fn, handles cleanup + error."""
    def deco(fn):
        def wrap():
            tmp = Path(tempfile.mkdtemp(prefix="scc_test_"))
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

@case("t01: old reports always visible - list_jobs not filtered by status")
def t01(tmp):
    import inspect
    from app import jobqueue
    jobs = jobqueue.list_jobs(limit=1000)
    assert isinstance(jobs, list), "list_jobs must return a list"
    src = inspect.getsource(jobqueue.list_jobs)
    assert "registry_status" not in src, \
        "list_jobs must NOT filter by registry_status - old reports must always appear"


@case("t02: scc strategies returns only active (NTAMicroVwapRiskPilot)")
def t02(tmp):
    from app.server import _build_scc_strategies
    result = _build_scc_strategies()
    strategies = result.get("strategies") or []
    class_names = [s["class_name"] for s in strategies]
    assert "NTAMicroVwapRiskPilot" in class_names, \
        f"NTAMicroVwapRiskPilot must be in active list, got: {class_names}"
    rejected_set = set(result.get("rejected_classes") or [])
    for cls in class_names:
        assert cls not in rejected_set, \
            f"Rejected class '{cls}' must not appear in active strategies"


@case("t03: rejected classes excluded from active strategy list")
def t03(tmp):
    from app.server import _build_scc_strategies, _SCC_REJECTED_CLASSES
    result = _build_scc_strategies()
    active_names = {s["class_name"] for s in (result.get("strategies") or [])}
    for cls in _SCC_REJECTED_CLASSES:
        assert cls not in active_names, \
            f"Rejected class '{cls}' must NOT be in active strategies"


@case("t04: submit_command blocks rejected/archived strategy with OpsError 403")
def t04(tmp):
    reg_path = tmp / "data" / "ops" / "registry.json"
    reg_path.write_text(json.dumps({
        "schema_version": "1.0",
        "generated_at_utc": _now_iso(),
        "strategies": [
            {
                "strategy_id":  "b1_shortonly",
                "class_name":   "NTAMicroVwapRiskPilot",
                "status":       "paper_ready",
                "instrument":   "MNQ",
                "locked_params": {},
            },
            {
                "strategy_id":  "rej_test",
                "display_name": "RejTest",
                "class_name":   "NTAMicroOrbPilot",
                "status":       "rejected",
                "account_mode": "paper",
                "allowed_accounts": ["Sim101"],
                "instrument":   "MNQ",
                "locked_params": {},
            },
        ],
    }), encoding="utf-8")

    try:
        rt.submit_command(
            command="enable_strategy",
            strategy_id="rej_test",
            account_name="Sim101",
            class_name="NTAMicroOrbPilot",
        )
        raise AssertionError("submit_command must raise OpsError for rejected strategy")
    except ops.OpsError as e:
        assert e.status == 403, f"Expected status 403, got {e.status}"
        assert "rejected" in str(e).lower() or "archived" in str(e).lower(), \
            f"Error must mention rejected/archived, got: {e}"


@case("t05: B1 locked params mismatch is detected by validate_params")
def t05(tmp):
    bad_params = dict(rt.B1_LOCKED_PARAMS_CHECK)
    bad_params["EnableLong"] = True
    result = rt.validate_params("b1_shortonly", bad_params)
    assert not result["ok"], "EnableLong=True must cause mismatch"
    keys = [m["key"] for m in result["mismatches"]]
    assert "EnableLong" in keys, f"EnableLong must be in mismatches, got: {keys}"

    good_params = dict(rt.B1_LOCKED_PARAMS_CHECK)
    result2 = rt.validate_params("b1_shortonly", good_params)
    assert result2["ok"], f"All correct params must pass, mismatches: {result2['mismatches']}"


@case("t06: runtime response includes account/instrument/timeframe/enabled")
def t06(tmp):
    _write_registry(tmp, status="paper_ready")
    _write_heartbeat(tmp, age_sec=2)
    _write_strategies(tmp, account="Sim101", enabled=True)

    view = rt.merge_strategy_view("b1_shortonly")
    for field in ("account_name", "account_mode", "runtime_detected", "runtime_enabled"):
        assert field in view, f"merge_strategy_view must include field '{field}'"
    assert view["runtime_detected"] is True, "runtime_detected must be True with fresh heartbeat"
    assert view["runtime_enabled"] is True, "runtime_enabled must be True when enabled=True"
    rt_sub = view.get("runtime") or {}
    assert rt_sub.get("instrument"), f"runtime.instrument must be present, got: {rt_sub}"
    assert rt_sub.get("timeframe"), f"runtime.timeframe must be present, got: {rt_sub}"
    assert rt_sub.get("enabled") is not None, "runtime.enabled must be present"


@case("t07: scc survives missing NT Strategies folder")
def t07(tmp):
    import unittest.mock as mock
    from app import server
    with mock.patch.object(server, "_NT_STRATEGIES_DIR", Path("/nonexistent_path_xyz123")):
        result = server._build_scc_strategies()
    assert isinstance(result, dict), "Result must be a dict"
    assert "strategies" in result, "Result must have 'strategies' key"
    assert isinstance(result["strategies"], list), "strategies must be a list"
    assert result["nt_strat_dir_ok"] is False, "nt_strat_dir_ok must be False for missing dir"


@case("t08: bridge offline -> runtime_detected=False, no fake running status")
def t08(tmp):
    _write_registry(tmp, status="paper_running")
    # Deliberately NO heartbeat.json written -> bridge offline

    view = rt.merge_strategy_view("b1_shortonly")
    assert view["runtime_detected"] is False, \
        f"runtime_detected must be False when bridge offline, got: {view['runtime_detected']}"
    assert view["runtime_enabled"] is False, \
        f"runtime_enabled must be False when bridge offline, got: {view['runtime_enabled']}"


@case("t09: scc scans NT-Analyzer_strategies first and keeps legacy root fallback")
def t09(tmp):
    import unittest.mock as mock
    from app import server

    preferred = tmp / "Strategies" / "NT-Analyzer_strategies"
    legacy = tmp / "Strategies"
    (preferred / "NTAMicroVwapRiskPilot").mkdir(parents=True, exist_ok=True)
    (preferred / "NTAMicroVwapRiskPilot" / "NTAMicroVwapRiskPilot.cs").write_text(
        "// preferred strategy\n",
        encoding="utf-8",
    )
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "NTAnalyzerEveryNBarLong.cs").write_text("// legacy standalone\n", encoding="utf-8")

    with mock.patch.object(server, "_NT_STRATEGIES_DIR", preferred), \
         mock.patch.object(server, "_NT_STRATEGIES_LEGACY_DIR", legacy):
        result = server._build_scc_strategies()

    names = [row.get("class_name") for row in result.get("strategies") or []]
    assert "NTAMicroVwapRiskPilot" in names, f"preferred folder class missing, got {names}"
    assert "NTAnalyzerEveryNBarLong" in names, f"legacy root fallback missing, got {names}"
    assert result["nt_strat_dir_ok"] is True, "preferred NT-Analyzer_strategies dir must be reported as present"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    cases = [t01, t02, t03, t04, t05, t06, t07, t08, t09]
    print(f"Running {len(cases)} SCC v2 tests:")
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
