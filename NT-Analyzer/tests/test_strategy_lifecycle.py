"""Strategy lifecycle pure-function tests.

Run from NT-Analyzer/ root:
    python -m tests.test_strategy_lifecycle
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import strategy_lifecycle as sl  # noqa: E402

PASSED: List[str] = []
FAILED: List[Tuple[str, str]] = []

NOW = datetime(2026, 6, 26, tzinfo=timezone.utc)


def case(name: str):
    def deco(fn):
        def wrap():
            try:
                fn()
                PASSED.append(name)
                print(f"  PASS  {name}")
            except Exception as e:  # noqa: BLE001
                FAILED.append((name, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
                print(f"  FAIL  {name}: {e}")
        return wrap
    return deco


# --- classify_lifecycle -----------------------------------------------------

@case("explicit lifecycle wins over status")
def t01() -> None:
    assert sl.classify_lifecycle({"lifecycle": "approved_live", "status": "ready"}) == sl.APPROVED_LIVE


@case("legacy ready -> approved_demo")
def t02() -> None:
    assert sl.classify_lifecycle({"status": "ready"}) == sl.APPROVED_DEMO
    assert sl.classify_lifecycle({"status": "paper_ready"}) == sl.APPROVED_DEMO


@case("legacy in_progress/candidate -> trial")
def t03() -> None:
    assert sl.classify_lifecycle({"status": "in_progress"}) == sl.TRIAL
    assert sl.classify_lifecycle({"status": "demo_trial"}) == sl.TRIAL


@case("rejected/archived -> failed_archived")
def t04() -> None:
    assert sl.classify_lifecycle({"status": "rejected"}) == sl.FAILED_ARCHIVED
    assert sl.classify_lifecycle({"status": "archived"}) == sl.FAILED_ARCHIVED


@case("matrix_hidden heuristic -> failed_archived")
def t05() -> None:
    assert sl.classify_lifecycle({"status": "weird", "matrix_hidden": True}) == sl.FAILED_ARCHIVED


@case("unknown -> trial fallback")
def t06() -> None:
    assert sl.classify_lifecycle({}) == sl.TRIAL


# --- detect_origin ----------------------------------------------------------

@case("explicit origin ai_lab")
def t07() -> None:
    assert sl.detect_origin({"origin": "ai_lab"}) == sl.ORIGIN_AI_LAB


@case("created_by ai -> ai_lab")
def t08() -> None:
    assert sl.detect_origin({"created_by": "ai"}) == sl.ORIGIN_AI_LAB
    assert sl.is_ai_lab({"created_by": "lm_studio"}) is True


@case("experiment id pattern -> ai_lab")
def t09() -> None:
    assert sl.detect_origin({"ai_experiment_id": "EXP-20260601-0001"}) == sl.ORIGIN_AI_LAB


@case("plain profile -> production")
def t10() -> None:
    assert sl.detect_origin({"strategy_class": "NTAMicroVwapRiskPilot"}) == sl.ORIGIN_PRODUCTION


# --- compute_plan_progress --------------------------------------------------

@case("time plan running with remaining days")
def t11() -> None:
    plan = {"basis": "time", "started_at_utc": "2026-06-20T00:00:00Z",
            "planned_end_utc": "2026-07-04T00:00:00Z"}
    p = sl.compute_plan_progress(plan, NOW)
    assert p["state"] == "running", p
    assert p["remaining_days"] == 8, p
    assert "осталось 8" in p["label"], p


@case("time plan via duration weeks")
def t12() -> None:
    plan = {"basis": "time", "started_at_utc": "2026-06-26T00:00:00Z",
            "duration": {"value": 2, "unit": "weeks"}}
    p = sl.compute_plan_progress(plan, NOW)
    assert p["state"] == "running", p
    assert p["remaining_days"] == 14, p


@case("time plan completed when past end")
def t13() -> None:
    plan = {"basis": "time", "started_at_utc": "2026-05-01T00:00:00Z",
            "planned_end_utc": "2026-06-01T00:00:00Z"}
    p = sl.compute_plan_progress(plan, NOW)
    assert p["state"] == "completed", p


@case("gates plan progress")
def t14() -> None:
    plan = {"basis": "gates", "total_gates": 5, "completed_gates": 2}
    p = sl.compute_plan_progress(plan, NOW)
    assert p["state"] == "running", p
    assert "3/5" in p["label"], p
    assert p["percent"] == 40.0, p


@case("gates plan completed")
def t15() -> None:
    plan = {"basis": "gates", "total_gates": 4, "completed_gates": 4}
    p = sl.compute_plan_progress(plan, NOW)
    assert p["state"] == "completed", p


@case("condition plan running")
def t16() -> None:
    p = sl.compute_plan_progress({"basis": "condition", "condition_text": "200 сделок"}, NOW)
    assert p["state"] == "running", p
    assert "200 сделок" in p["label"], p


@case("no plan -> no_data")
def t17() -> None:
    p = sl.compute_plan_progress(None, NOW)
    assert p["state"] == "no_data", p
    assert p["label"] == "нет данных", p


# --- reconcile --------------------------------------------------------------

@case("reconcile on_track within tolerance")
def t18() -> None:
    r = sl.reconcile(1000.0, 700.0, tolerance=0.5)
    assert r["verdict"] == "on_track", r
    assert r["delta"] == -300.0, r


@case("reconcile underperforming")
def t19() -> None:
    r = sl.reconcile(1000.0, 200.0, tolerance=0.5)
    assert r["verdict"] == "underperforming", r


@case("reconcile insufficient without sample")
def t20() -> None:
    r = sl.reconcile(1000.0, None, has_sample=False)
    assert r["verdict"] == "insufficient", r


# --- archive_fingerprint ----------------------------------------------------

@case("fingerprint stable for same idea, differs by id")
def t21() -> None:
    a = {"profile_id": "x1", "strategy_class": "C", "instrument": "MNQ 06-26",
         "timeframe": "5 Minute", "locked_parameters": {"EnableShort": True}}
    b = {"profile_id": "x2", "strategy_class": "C", "instrument": "MNQ SEP26",
         "timeframe": "5 Minute", "locked_parameters": {"EnableShort": True}}
    assert sl.archive_fingerprint(a) == sl.archive_fingerprint(b), (a, b)


@case("fingerprint differs by timeframe")
def t22() -> None:
    a = {"strategy_class": "C", "instrument": "MNQ", "timeframe": "5 Minute"}
    b = {"strategy_class": "C", "instrument": "MNQ", "timeframe": "1 Minute"}
    assert sl.archive_fingerprint(a) != sl.archive_fingerprint(b)


# --- annotate ---------------------------------------------------------------

@case("annotate enriches trial with progress + reserved flag")
def t23() -> None:
    prof = {"status": "in_progress",
            "trial_plan": {"basis": "time", "started_at_utc": "2026-06-20T00:00:00Z",
                           "planned_end_utc": "2026-07-04T00:00:00Z"}}
    out = sl.annotate(prof, NOW)
    assert out["lifecycle"] == sl.TRIAL, out
    assert out["lifecycle_label"] == "Испытание", out
    assert out["portfolio_reserved"] is True, out
    assert out["trial_progress"]["remaining_days"] == 8, out
    assert "trial_plan" in prof and "lifecycle" not in prof  # input not mutated


@case("annotate marks ai origin + label")
def t24() -> None:
    out = sl.annotate({"status": "ready", "created_by": "ai"}, NOW)
    assert out["origin"] == sl.ORIGIN_AI_LAB, out
    assert out["origin_label"] == "AI / LM Studio", out
    assert out["is_ai_lab"] is True, out


@case("annotate builds demo reconciliation from forecast + live")
def t25() -> None:
    prof = {"status": "ready",
            "demo_plan": {"forecast_net": 1000.0},
            "approved_demo": {"live": {"net_pnl": 800.0}}}
    out = sl.annotate(prof, NOW)
    assert out["lifecycle"] == sl.APPROVED_DEMO, out
    assert out["demo_reconciliation"]["verdict"] == "on_track", out


# --- AI status -> lifecycle -------------------------------------------------

@case("ai trial statuses -> trial")
def t26() -> None:
    for s in ["draft", "generating", "backtesting", "sandbox_candidate", "champion_candidate"]:
        assert sl.lifecycle_for_ai_status(s) == sl.TRIAL, s


@case("ai portfolio_contributor -> approved_demo")
def t27() -> None:
    assert sl.lifecycle_for_ai_status("portfolio_contributor") == sl.APPROVED_DEMO


@case("ai failed/cancelled/rejected -> failed_archived")
def t28() -> None:
    for s in ["rejected", "cancelled", "compile_failed", "backtest_failed",
              "blocked_lm_studio", "pipeline_failed", "archived"]:
        assert sl.lifecycle_for_ai_status(s) == sl.FAILED_ARCHIVED, s


@case("ai unknown status -> failed_archived (safe terminal)")
def t29() -> None:
    assert sl.lifecycle_for_ai_status("weird_unknown") == sl.FAILED_ARCHIVED


@case("ai status label ru is human readable")
def t30() -> None:
    assert sl.ai_status_label_ru("backtesting") == "идёт бэктест"
    assert sl.ai_status_label_ru("rejected") == "отклонено"


def main() -> int:
    print("strategy_lifecycle tests")
    for name, fn in sorted(globals().items()):
        if name.startswith("t") and callable(fn) and name[1:].isdigit():
            fn()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for n, err in FAILED:
            print(f"\nFAIL {n}\n{err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
