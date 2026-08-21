"""Phase 16 — Strategy Control Center tests.

Run from NT-Analyzer/ root:
    python -m tests.test_ops

Tests use a temp directory by monkey-patching ops._project_root, so they
do not touch the real data/ops/ files or the real journal CSV.
"""
from __future__ import annotations

import json
import os
import sys
import shutil
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ops  # noqa: E402


# --------------------------------------------------------------------------
# Test harness
# --------------------------------------------------------------------------

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def _set_temp_root(tmp: Path):
    original_project_root = ops._project_root
    original_data_root = os.environ.get("NTA_DATA_ROOT")
    original_dev_root = os.environ.get("NTA_STAGING_DATA_ROOT")
    workspace = tmp / "NT-Analyzer"
    os.environ["NTA_DATA_ROOT"] = str(workspace / "data")
    os.environ["NTA_STAGING_DATA_ROOT"] = str(workspace / "development-data")
    ops._project_root = lambda: workspace  # type: ignore[assignment]
    (workspace / "data" / "ops").mkdir(parents=True, exist_ok=True)
    # also create a fake journal CSV with header for B1
    base = tmp / "NT-Analyzer" / "data" / "profiles" / "paper_b1_shortonly"
    base.mkdir(parents=True, exist_ok=True)
    (base / "PAPER_B1_SHORTONLY_PROFILE.json").write_text("{}", encoding="utf-8")
    (base / "PAPER_B1_SHORTONLY_RUNBOOK.md").write_text("# runbook\n", encoding="utf-8")
    (base / "PAPER_B1_SHORTONLY_CHECKLIST.md").write_text("# checklist\n", encoding="utf-8")
    csv_path = base / "PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv"
    csv_path.write_text(
        "date_pt,trading_day_number,session_status,trades_count,gross_pnl,total_qty,notes\n",
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


def case(name: str):
    def deco(fn):
        def wrap():
            tmp = Path(tempfile.mkdtemp(prefix="ops_test_"))
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


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

@case("registry loads B1 ShortOnly correctly")
def t01(tmp):
    strats = ops.list_strategies()
    sids = [s["strategy_id"] for s in strats]
    assert "vwap_short_mnq_5m_v1" in sids, sids
    b1 = ops.get_strategy("b1_shortonly")
    assert b1 is not None
    assert b1["strategy_id"] == "vwap_short_mnq_5m_v1"
    assert "b1_shortonly" in b1.get("legacy_strategy_ids", [])
    assert b1["status"] == "paper_ready"
    assert b1["class_name"] == "NTAMicroVwapRiskPilot"
    assert b1["validation_job_id"] == "ui_20260501T185820607Z"


@case("rejected strategies cannot be armed")
def t02(tmp):
    raised = False
    try:
        ops.arm("ntamicroorbpilot", "test")
    except ops.OpsError as e:
        raised = True
        assert "not allowed" in str(e).lower() or "transition" in str(e).lower() or "rejected" in str(e).lower(), str(e)
    assert raised, "arming a rejected strategy must raise OpsError"


@case("live mode cannot be started — endpoint always blocked")
def t03(tmp):
    out = ops.live_lock_status()
    assert out["live_locked"] is True
    out2 = ops.request_live_unlock(reason="please?")
    assert out2.get("ok") is False, out2
    # Audit log must contain the denial
    log = ops.read_audit_log(50)
    assert any("live/unlock" in (e.get("action") or "") for e in log)


@case("adjusted PnL is quantity-aware")
def t04(tmp):
    # qty=2, gross=$100  ->  adj = 100 - 1.90*2 = 96.20
    row = {"gross_pnl": "100", "total_qty": "2"}
    adj = ops._row_adj_pnl(row)
    assert adj is not None and abs(adj - 96.20) < 1e-6, adj
    row2 = {"gross_pnl": "-50", "total_qty": "1"}
    adj2 = ops._row_adj_pnl(row2)
    assert adj2 is not None and abs(adj2 - (-51.90)) < 1e-6, adj2


@case("risk breach: adj daily pnl <= -200 -> daily stop")
def t05(tmp):
    # arm, start, append a journal day with -250 loss
    ops.arm("b1_shortonly", "t")
    ops.start_intent("b1_shortonly", "t")
    ops.confirm_manual("b1_shortonly", "started", "t")
    from datetime import datetime, timezone
    today_pt = ops._to_pt(datetime.now(timezone.utc)).date().isoformat()
    ops.append_journal_day("b1_shortonly", {
        "date_pt": today_pt, "trading_day_number": "1", "session_status": "ok",
        "trades_count": "3", "gross_pnl": "-250", "total_qty": "3", "notes": "test breach",
    })
    s = ops.get_strategy("b1_shortonly")
    m = ops.compute_metrics_safe(s)
    assert m.get("today_adj_pnl") is not None
    assert m["today_adj_pnl"] <= -200, m["today_adj_pnl"]
    assert m.get("risk_state") in ("risk_blocked", "warn", "bad", "breach"), m.get("risk_state")
    assert any("daily" in (r or "").lower() for r in (m.get("risk_reasons") or [])), m.get("risk_reasons")


@case("paper review due only when days>=60 AND trades>=25")
def t06(tmp):
    # synthetic: days=10, trades=30 -> NOT due
    ops.arm("b1_shortonly", "t"); ops.start_intent("b1_shortonly","t")
    ops.confirm_manual("b1_shortonly","started","t")
    from datetime import date, timedelta
    base = date(2025, 1, 1)
    for i in range(10):
        ops.append_journal_day("b1_shortonly", {
            "date_pt": (base + timedelta(days=i)).isoformat(),
            "trading_day_number": str(i+1), "session_status": "ok",
            "trades_count": "3", "gross_pnl": "10", "total_qty": "1", "notes": "",
        })
    s = ops.get_strategy("b1_shortonly")
    m = ops.compute_metrics_safe(s)
    prog = m.get("progress") or {}
    assert prog.get("trading_days_completed") == 10
    res = ops.evaluate_review_due("b1_shortonly")
    states = ops.load_states()
    canon = "vwap_short_mnq_5m_v1"
    assert "b1_shortonly" not in states, states
    assert states[canon]["current_state"] != "paper_review_due", states[canon]


@case("start-intent writes audit log")
def t07(tmp):
    ops.arm("b1_shortonly", "test arm reason")
    ops.start_intent("b1_shortonly", "test start reason")
    log = ops.read_audit_log(50)
    actions = [e.get("action") for e in log]
    assert "transition/armed" in actions, actions
    assert "intent/start" in actions, actions


@case("stop-intent writes audit log")
def t08(tmp):
    ops.arm("b1_shortonly", "t")
    ops.start_intent("b1_shortonly", "t")
    ops.confirm_manual("b1_shortonly", "started", "t")
    ops.stop_intent("b1_shortonly", "test stop reason")
    log = ops.read_audit_log(50)
    actions = [e.get("action") for e in log]
    assert "intent/stop" in actions, actions


@case("missing journal CSV is recoverable warning, not crash")
def t09(tmp):
    # delete the CSV
    base = tmp / "NT-Analyzer" / "data" / "profiles" / "paper_b1_shortonly"
    csv_p = base / "PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv"
    if csv_p.exists():
        csv_p.unlink()
    s = ops.get_strategy("b1_shortonly")
    m = ops.compute_metrics_safe(s)  # must not raise
    assert isinstance(m, dict)
    j = ops.get_journal("b1_shortonly")
    assert j.get("exists") is False
    assert j.get("count", 0) == 0


@case("UI listing includes both active + archived")
def t10(tmp):
    strats = ops.list_strategies()
    statuses = sorted(set(s["status"] for s in strats))
    assert "paper_ready" in statuses
    assert "rejected" in statuses


@case("invalid transition (resume from paper_running) is denied")
def t11(tmp):
    ops.arm("b1_shortonly", "t")
    ops.start_intent("b1_shortonly", "t")
    ops.confirm_manual("b1_shortonly", "started", "t")
    raised = False
    try:
        ops.resume("b1_shortonly", "no")  # paper_running -> armed not allowed
    except ops.OpsError:
        raised = True
    assert raised, "resume from paper_running must be denied"


@case("mark_paper_passed only after paper_review_due")
def t12(tmp):
    raised = False
    try:
        ops.mark_paper_passed("b1_shortonly", "premature")
    except ops.OpsError:
        raised = True
    assert raised, "mark_paper_passed before review_due must be denied"


@case("trading cycle registry: empty by default, round-trips active cycle")
def t13(tmp):
    # No cycles.json yet -> cycle-agnostic empty registry.
    assert ops.list_cycles() == [], ops.list_cycles()
    assert ops.get_active_cycle() is None
    ops.save_cycles({
        "active_cycle_id": "CYCLE-2026-06-16-A",
        "cycles": [
            {
                "cycle_id": "CYCLE-2026-06-16-A",
                "label": "post-audit relaunch gate",
                "status": "open",
                "opened_at_utc": "2026-06-16T00:00:00Z",
                "closed_at_utc": None,
                "account_names": ["DEMO3369390"],
                "members": [
                    {"cell_id": "CELL-015", "strategy_class": "NTAMnqLiquiditySweepReversalC015",
                     "runtime_instance_id": "iid-c015", "instrument": "MNQ SEP26"},
                ],
            },
        ],
    })
    assert [c["cycle_id"] for c in ops.list_cycles()] == ["CYCLE-2026-06-16-A"]
    active = ops.get_active_cycle()
    assert active is not None and active["cycle_id"] == "CYCLE-2026-06-16-A", active
    assert ops.get_cycle("CYCLE-2026-06-16-A")["label"] == "post-audit relaunch gate"
    assert ops.get_cycle("missing") is None
    # Schema version is normalized on save.
    assert ops.load_cycles()["schema_version"] == ops.CYCLE_SCHEMA_VERSION


# --------------------------------------------------------------------------
# Run all
# --------------------------------------------------------------------------

def main() -> int:
    tests = [t01, t02, t03, t04, t05, t06, t07, t08, t09, t10, t11, t12, t13]
    print(f"Running {len(tests)} Phase 16 tests:")
    for t in tests:
        t()
    print()
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        for name, msg in FAILED:
            print(f"\n--- {name} ---")
            print(msg)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
