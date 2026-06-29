"""Queue contract tests.

Run from NT-Analyzer/ root:
    python -m tests.test_jobqueue
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import jobqueue as jq  # noqa: E402


PASSED: List[str] = []
FAILED: List[Tuple[str, str]] = []


def _set_temp_root(tmp: Path) -> Callable[[], None]:
    original = jq.project_root
    jq.project_root = lambda: tmp  # type: ignore[assignment]
    (tmp / "jobs").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "batches").mkdir(parents=True, exist_ok=True)
    jq.reset_caches()

    def restore() -> None:
        jq.project_root = original  # type: ignore[assignment]
        jq.reset_caches()

    return restore


def case(name: str):
    def deco(fn):
        def wrap():
            tmp = Path(tempfile.mkdtemp(prefix="jq_test_"))
            restore = _set_temp_root(tmp)
            try:
                fn(tmp)
                PASSED.append(name)
                print(f"  PASS  {name}")
            except Exception:
                FAILED.append((name, traceback.format_exc()))
                print(f"  FAIL  {name}")
            finally:
                restore()
                shutil.rmtree(tmp, ignore_errors=True)
        return wrap
    return deco


@case("safe ids reject traversal and dot folders")
def t01(tmp: Path) -> None:
    for bad in (".", "..", ".hidden", "bad.", "CON"):
        try:
            jq._safe_job_id(bad)
            raise AssertionError(f"job_id {bad!r} should be rejected")
        except jq.JobValidationError:
            pass
        try:
            jq._safe_batch_id(bad)
            raise AssertionError(f"batch_id {bad!r} should be rejected")
        except jq.JobValidationError:
            pass
    assert jq._safe_job_id("ui_20260509T120000000Z") == "ui_20260509T120000000Z"
    assert jq._safe_batch_id("batch_20260509T120000000Z") == "batch_20260509T120000000Z"


@case("delete APIs reject traversal ids")
def t02(tmp: Path) -> None:
    for fn, value in ((jq.delete_job, ".."), (jq.delete_batch, "..")):
        try:
            fn(value)
            raise AssertionError(f"{fn.__name__} should reject {value!r}")
        except jq.JobValidationError:
            pass


@case("dot queue directories are ignored")
def t03(tmp: Path) -> None:
    (tmp / "jobs" / "failed" / ".quarantine" / "job1").mkdir(parents=True)
    (tmp / "jobs" / "pending" / ".staging" / "job2").mkdir(parents=True)
    counts = jq.queue_counts()
    assert counts["failed"] == 0, counts
    assert counts["pending"] == 0, counts


@case("cancelled is first-class read-side terminal status")
def t04(tmp: Path) -> None:
    jdir = tmp / "jobs" / "cancelled" / "job_ok"
    jdir.mkdir(parents=True)
    (jdir / "job.json").write_text(json.dumps({
        "job_id": "job_ok",
        "created_at_utc": "2026-05-09T12:00:00Z",
        "strategy": {"class_name": "SampleMACrossOver"},
        "instrument": "MNQ 06-26",
    }), encoding="utf-8")
    (jdir / "result.json").write_text(json.dumps({
        "status": "cancelled",
        "finished_at_utc": "2026-05-09T12:01:00Z",
        "reason": "cancelled by test",
        "metrics": {"trade_count": 0},
        "verification_warnings": ["cancelled by user"],
    }), encoding="utf-8")

    summary = jq.read_job_summary("job_ok")
    assert summary is not None, "summary missing"
    assert summary["status"] == "cancelled", summary
    assert summary["finished_at_utc"] == "2026-05-09T12:01:00Z", summary
    assert summary["cancel_reason"] == "cancelled by test", summary

    full = jq.read_job_full("job_ok")
    assert full is not None, "full missing"
    assert full["status"] == "cancelled", full
    assert full["result"]["status"] == "cancelled", full


@case("profile rename enforces canonical display-name policy")
def t05(tmp: Path) -> None:
    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.1",
        "profiles": [
            {
                "profile_id": "mgc_b1_shortonly_5m_paper_v2",
                "name": "draft",
                "strategy_class": "NTAMicroVwapRiskExplorer",
                "instrument": "MGC 06-26",
                "timeframe": "5 Minute",
                "slot": 2,
                "cell_id": "CELL-002",
                "status": "ready",
                "stable_id": "mgc_b1_short_5m_v2",
            }
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        jq.update_strategy_profile(
            "mgc_b1_shortonly_5m_paper_v2",
            {"name": "Scalping MGC 5m v2 c002"},
            action="rename",
        )
        raise AssertionError("non-canonical display name must be rejected")
    except jq.JobValidationError as e:
        assert "must be exactly" in str(e), e

    out = jq.update_strategy_profile(
        "mgc_b1_shortonly_5m_paper_v2",
        {"name": "B1 ShortOnly MGC 5m v2 c002"},
        action="rename",
    )
    assert out["ok"] is True, out
    assert out["profile"]["name"] == "B1 ShortOnly MGC 5m v2 c002", out
    assert out["profile"]["expected_name"] == "B1 ShortOnly MGC 5m v2 c002", out


@case("deploy strategy class overrides generic setup-mode family in canonical name")
def t06(tmp: Path) -> None:
    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.1",
        "profiles": [
            {
                "profile_id": "sev2_mgc_vwappullback_shortonly_paper_v1",
                "name": "Scalping Gold MGC 5m v1 c001",
                "strategy_class": "NTAMicroSessionEdgeExplorer",
                "deploy_strategy_class": "VWAPPullbackMGC5mV1",
                "runtime_strategy_classes": [
                    "NTAMicroSessionEdgeExplorer",
                    "VWAPPullbackMGC5mV1",
                ],
                "instrument": "MGC 06-26",
                "timeframe": "5 Minute",
                "slot": 1,
                "cell_id": "CELL-001",
                "status": "ready",
                "locked_parameters": {
                    "SetupMode": "VwapPullback",
                },
            }
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    jq.project_root = lambda: tmp  # type: ignore[assignment]
    jq.reset_caches()

    profiles = jq.read_strategy_profiles().get("profiles") or []
    assert len(profiles) == 1, profiles
    profile = profiles[0]
    assert profile["expected_name"] == "Scalping Gold MGC 5m v1 c001", profile
    assert profile["name_matches_policy"] is True, profile


@case("strategy profiles receive root and strategy family metadata")
def t07(tmp: Path) -> None:
    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "strategy_families.json").write_text(json.dumps({
        "schema_version": "1.0",
        "class_map": {
            "NTAMnqResearchHub": {
                "root_family": "MNQ",
                "strategy_family": "mnq_session_edge",
                "family_status": "research_hub",
                "family_role": "research_hub",
                "hub_class": "NTAMnqResearchHub",
                "new_research_allowed": True,
            },
            "B1ShortOnlyMGC5mV2": {
                "root_family": "MGC",
                "strategy_family": "mgc_b1_transfer",
                "family_status": "active",
                "family_role": "deploy_wrapper",
                "hub_class": "NTAMicroVwapRiskExplorer",
                "new_research_allowed": True,
            },
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
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
                "instrument": "MGC 06-26",
                "timeframe": "5 Minute",
                "slot": 2,
                "cell_id": "CELL-002",
                "status": "ready",
            }
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    jq.project_root = lambda: tmp  # type: ignore[assignment]
    jq.reset_caches()

    profile = (jq.read_strategy_profiles().get("profiles") or [])[0]
    assert profile["root_family"] == "MGC", profile
    assert profile["strategy_family"] == "mgc_b1_transfer", profile
    assert profile["family_status"] == "active", profile
    assert profile["hub_class"] == "NTAMicroVwapRiskExplorer", profile
    assert profile["new_research_allowed"] is True, profile


@case("same strategy family profiles keep explicit portfolio cells")
def t08(tmp: Path) -> None:
    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "strategy_families.json").write_text(json.dumps({
        "schema_version": "1.0",
        "class_map": {
            "B1ShortOnlyMGC5mV2": {
                "root_family": "MGC",
                "strategy_family": "mgc_b1_transfer",
                "family_status": "active",
                "family_role": "deploy_wrapper",
                "hub_class": "NTAMicroVwapRiskExplorer",
                "new_research_allowed": True,
            },
            "B1Stop24MGC5mC003": {
                "root_family": "MGC",
                "strategy_family": "mgc_b1_transfer",
                "family_status": "active",
                "family_role": "deploy_wrapper",
                "hub_class": "NTAMicroVwapRiskExplorer",
                "new_research_allowed": True,
            },
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (profiles_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.1",
        "profiles": [
            {
                "profile_id": "mgc_b1_shortonly_5m_paper_v2",
                "name": "B1 ShortOnly MGC 5m v2 c002",
                "strategy_class": "NTAMicroVwapRiskExplorer",
                "deploy_strategy_class": "B1ShortOnlyMGC5mV2",
                "instrument": "MGC 06-26",
                "timeframe": "5 Minute",
                "slot": 2,
                "cell_id": "CELL-002",
                "status": "ready",
            },
            {
                "profile_id": "mgc_b1_stop24_5m_paper_c003",
                "name": "B1 Stop24 MGC 5m c003",
                "strategy_class": "NTAMicroVwapRiskExplorer",
                "deploy_strategy_class": "B1Stop24MGC5mC003",
                "instrument": "MGC 06-26",
                "timeframe": "5 Minute",
                "slot": 3,
                "cell_id": "CELL-003",
                "status": "ready",
            },
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    jq.project_root = lambda: tmp  # type: ignore[assignment]
    jq.reset_caches()

    profiles = jq.read_strategy_profiles().get("profiles") or []
    by_id = {p["profile_id"]: p for p in profiles}
    assert by_id["mgc_b1_shortonly_5m_paper_v2"]["cell_id"] == "CELL-002", profiles
    assert by_id["mgc_b1_stop24_5m_paper_c003"]["cell_id"] == "CELL-003", profiles
    assert by_id["mgc_b1_shortonly_5m_paper_v2"]["strategy_family"] == "mgc_b1_transfer", profiles
    assert by_id["mgc_b1_stop24_5m_paper_c003"]["strategy_family"] == "mgc_b1_transfer", profiles


@case("research modes registry is readable")
def t08b(tmp: Path) -> None:
    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "research_modes.json").write_text(json.dumps({
        "schema_version": "1.0",
        "modes": [
            {
                "root_family": "MNQ",
                "strategy_family": "mnq_session_edge",
                "hub_class": "NTAMnqResearchHub",
                "mode": "FailedBreak",
                "status": "active",
            }
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    jq.project_root = lambda: tmp  # type: ignore[assignment]

    doc = jq.read_research_modes()
    assert doc["schema_version"] == "1.0", doc
    assert doc["modes"][0]["hub_class"] == "NTAMnqResearchHub", doc
    assert doc["modes"][0]["mode"] == "FailedBreak", doc


@case("favorite reports are snapshotted and deletion-protected")
def t09(tmp: Path) -> None:
    jdir = tmp / "jobs" / "done" / "job_fav"
    jdir.mkdir(parents=True)
    (jdir / "job.json").write_text(json.dumps({
        "job_id": "job_fav",
        "created_at_utc": "2026-05-09T12:00:00Z",
        "strategy": {
            "class_name": "SampleMACrossOver",
            "parameters": {"Fast": 10, "Slow": 25},
        },
        "instrument": "MNQ 06-26",
        "timeframe": {"bars_period_type": "Minute", "bars_period_value": 5},
        "period": {
            "from_utc": "2026-05-08T00:00:00Z",
            "to_utc": "2026-05-09T00:00:00Z",
        },
    }), encoding="utf-8")
    (jdir / "result.json").write_text(json.dumps({
        "status": "done",
        "finished_at_utc": "2026-05-09T12:01:00Z",
        "metrics": {"trade_count": 3, "winning_pct": 66.7, "net_profit": 120.0},
    }), encoding="utf-8")
    (jdir / "trades.json").write_text("[]", encoding="utf-8")

    out = jq.favorite_report("job", "job_fav", "keep this")
    assert out["ok"] is True, out
    assert out["favorite"]["description"] == "keep this", out
    raw_favorite = jq._read_report_favorites_raw()["favorites"]["job:job_fav"]
    assert raw_favorite["snapshot"]["full"]["job_id"] == "job_fav", raw_favorite
    assert jq.is_report_favorite("job", "job_fav") is True

    blocked = jq.delete_job("job_fav")
    assert blocked["deleted"] is False and blocked["reason"] == "favorite", blocked

    favs = jq.read_report_favorites()["favorites"]
    assert len(favs) == 1, favs
    assert favs[0]["validation"]["report_exists"] is True, favs

    jq.unfavorite_report("job", "job_fav")
    deleted = jq.delete_job("job_fav")
    assert deleted["deleted"] is True, deleted


@case("favorite repeat reuses stored snapshot")
def t10(tmp: Path) -> None:
    jdir = tmp / "jobs" / "done" / "job_repeat"
    jdir.mkdir(parents=True)
    (jdir / "job.json").write_text(json.dumps({
        "job_id": "job_repeat",
        "created_at_utc": "2026-05-09T12:00:00Z",
        "strategy": {
            "class_name": "SampleMACrossOver",
            "parameters": {"Fast": 10, "Slow": 25},
        },
        "instrument": "MNQ 06-26",
        "timeframe": {"bars_period_type": "Minute", "value": 5},
        "period": {
            "from_utc": "2026-05-08T00:00:00Z",
            "to_utc": "2026-05-09T00:00:00Z",
        },
        "risk_profile": {"capital": 25000},
        "execution": {
            "calculate": "OnBarClose",
            "is_tick_replay": False,
            "order_fill_resolution": "High",
            "slippage_ticks": 1,
            "commission": 0.0,
            "commission_template": "None",
            "session_template": "CME US Index Futures RTH",
            "timezone": "UTC",
            "role": "research",
        },
    }), encoding="utf-8")
    (jdir / "result.json").write_text(json.dumps({
        "status": "done",
        "finished_at_utc": "2026-05-09T12:01:00Z",
        "metrics": {"trade_count": 3, "winning_pct": 66.7, "net_profit": 120.0},
    }), encoding="utf-8")
    (jdir / "trades.json").write_text("[]", encoding="utf-8")

    jq.favorite_report("job", "job_repeat", "repeat this")

    (jdir / "job.json").write_text(json.dumps({
        "job_id": "job_repeat",
        "created_at_utc": "2026-05-09T12:00:00Z",
        "strategy": {
            "class_name": "ChangedStrategy",
            "parameters": {"Fast": 1, "Slow": 2},
        },
        "instrument": "ES 06-26",
        "timeframe": {"bars_period_type": "Minute", "value": 60},
        "period": {
            "from_utc": "2026-05-01T00:00:00Z",
            "to_utc": "2026-05-02T00:00:00Z",
        },
    }), encoding="utf-8")

    captured = {}
    original_create_job = jq.create_job

    def fake_create_job(req):
        captured["req"] = req
        return "ui_repeat_1", tmp / "jobs" / "pending" / "ui_repeat_1"

    jq.create_job = fake_create_job  # type: ignore[assignment]
    try:
        out = jq.repeat_report_favorite("job", "job_repeat")
    finally:
        jq.create_job = original_create_job  # type: ignore[assignment]

    assert out["ok"] is True, out
    assert out["job_id"] == "ui_repeat_1", out
    req = captured["req"]
    assert req.class_name == "SampleMACrossOver", req
    assert req.instrument == "MNQ 06-26", req
    assert req.bars_period_type == "Minute", req
    assert req.bars_period_value == 5, req
    assert req.from_utc == "2026-05-08T00:00:00Z", req
    assert req.to_utc == "2026-05-09T00:00:00Z", req
    assert req.parameters == {"Fast": 10, "Slow": 25}, req
    assert req.risk_profile == {"capital": 25000}, req


@case("batch favorite is blocked in favor of concrete child runs")
def t11(tmp: Path) -> None:
    for jid, instrument in (("job_child_a", "MNQ 06-26"), ("job_child_b", "MES 06-26")):
        jdir = tmp / "jobs" / "done" / jid
        jdir.mkdir(parents=True)
        (jdir / "job.json").write_text(json.dumps({
            "job_id": jid,
            "created_at_utc": "2026-05-09T12:00:00Z",
            "strategy": {
                "class_name": "SampleMACrossOver",
                "parameters": {"Fast": 10, "Slow": 25},
            },
            "instrument": instrument,
            "timeframe": {"bars_period_type": "Minute", "value": 5},
            "period": {
                "from_utc": "2026-05-08T00:00:00Z",
                "to_utc": "2026-05-09T00:00:00Z",
            },
        }), encoding="utf-8")
        (jdir / "result.json").write_text(json.dumps({
            "status": "done",
            "finished_at_utc": "2026-05-09T12:01:00Z",
            "metrics": {"trade_count": 3, "winning_pct": 66.7, "net_profit": 120.0},
        }), encoding="utf-8")
        (jdir / "trades.json").write_text("[]", encoding="utf-8")

    bdir = tmp / "data" / "batches" / "batch_pack"
    bdir.mkdir(parents=True)
    (bdir / "batch.json").write_text(json.dumps({
        "batch_id": "batch_pack",
        "created_at_utc": "2026-05-09T12:00:00Z",
        "name": "pack",
        "strategy": {
            "class_name": "SampleMACrossOver",
            "parameters": {"Fast": 10, "Slow": 25},
        },
        "timeframe": {"bars_period_type": "Minute", "value": 5},
        "period": {
            "from_utc": "2026-05-08T00:00:00Z",
            "to_utc": "2026-05-09T00:00:00Z",
        },
        "risk_profile": {},
        "execution": {"role": "research"},
        "children": [
            {"job_id": "job_child_a", "instrument": "MNQ 06-26", "batch_index": 0},
            {"job_id": "job_child_b", "instrument": "MES 06-26", "batch_index": 1},
        ],
        "total": 2,
    }), encoding="utf-8")

    try:
        jq.favorite_report("batch", "batch_pack")
        raise AssertionError("batch favorite should be rejected")
    except jq.JobValidationError as e:
        assert "нижней таблице" in str(e), e


@case("research jobs keep NTAMicroVwapRiskPilot submitted time window")
def t12(tmp: Path) -> None:
    req = jq.CreateJobRequest(
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
        bars_period_type="Minute",
        bars_period_value=5,
        from_utc="2024-01-01T00:00:00Z",
        to_utc="2024-01-31T00:00:00Z",
        parameters={"TradeStartTime": 635, "TradeEndTime": 1230},
        role="research",
    )
    jq._apply_locked_strategy_parameters(req)
    assert req.parameters["TradeEndTime"] == 1230, req.parameters

    smoke = jq.CreateJobRequest(
        class_name="NTAMicroVwapRiskPilot",
        instrument="MNQ 06-26",
        bars_period_type="Minute",
        bars_period_value=5,
        from_utc="2024-01-01T00:00:00Z",
        to_utc="2024-01-31T00:00:00Z",
        parameters={"TradeStartTime": 635, "TradeEndTime": 1230},
        role="smoke",
    )
    jq._apply_locked_strategy_parameters(smoke)
    assert smoke.parameters["TradeEndTime"] == 700, smoke.parameters


@case("reports are paged by stable report number, not folder mtime")
def t13(tmp: Path) -> None:
    for i in range(1, 61):
        minute = i // 2
        second = i % 60
        jdir = tmp / "jobs" / "done" / f"job_{i:03d}"
        jdir.mkdir(parents=True)
        (jdir / "job.json").write_text(json.dumps({
            "job_id": f"job_{i:03d}",
            "created_at_utc": f"2026-05-09T12:{minute:02d}:{second:02d}Z",
            "strategy": {"class_name": "SampleMACrossOver"},
            "instrument": "MNQ 06-26",
            "timeframe": {"bars_period_type": "Minute", "bars_period_value": 5},
            "period": {
                "from_utc": "2026-05-08T00:00:00Z",
                "to_utc": "2026-05-09T00:00:00Z",
            },
        }), encoding="utf-8")
        (jdir / "result.json").write_text(json.dumps({
            "status": "done",
            "finished_at_utc": f"2026-05-09T13:{minute:02d}:{second:02d}Z",
            "metrics": {"trade_count": i},
        }), encoding="utf-8")

    jq.sync_report_numbers()
    old_dir = tmp / "jobs" / "done" / "job_001"
    os.utime(old_dir, (4102444800, 4102444800))
    jq.reset_caches()

    first = jq.list_reports(limit=50, offset=0, sort_col="mtime", sort_dir="desc")
    second = jq.list_reports(limit=50, offset=50, sort_col="mtime", sort_dir="desc")

    assert first["limit"] == 50 and first["total"] == 60, first
    assert first["jobs"][0]["report_no"] == 60, first["jobs"][:3]
    assert first["jobs"][-1]["report_no"] == 11, first["jobs"][-3:]
    assert second["jobs"][0]["report_no"] == 10, second["jobs"][:3]
    assert second["jobs"][-1]["report_no"] == 1, second["jobs"][-3:]


@case("report filters use frequency, statistical confidence, and column metrics")
def t14(tmp: Path) -> None:
    fixtures = [
        ("job_rare", 1, 80, 2.0, 120),
        ("job_normal", 4, 55, 1.3, 90),
        ("job_frequent", 10, 40, 0.8, 60),
    ]
    for index, (job_id, trades, win, profit_factor, drawdown) in enumerate(fixtures, start=1):
        jdir = tmp / "jobs" / "done" / job_id
        jdir.mkdir(parents=True)
        (jdir / "job.json").write_text(json.dumps({
            "job_id": job_id,
            "created_at_utc": f"2026-05-0{index}T12:00:00Z",
            "strategy": {"class_name": "SampleMACrossOver"},
            "instrument": "MNQ 06-26",
            "timeframe": {"bars_period_type": "Minute", "bars_period_value": 5},
            "period": {"from_utc": "2026-05-01T00:00:00Z", "to_utc": "2026-05-08T00:00:00Z"},
        }), encoding="utf-8")
        (jdir / "result.json").write_text(json.dumps({
            "status": "done",
            "metrics": {
                "trade_count": trades, "winning_pct": win, "profit_factor": profit_factor,
                "max_drawdown": drawdown, "net_profit": 100,
            },
        }), encoding="utf-8")
    jq.sync_report_numbers()
    jq.reset_caches()

    normal = jq.list_reports(limit=20, frequency="normal")
    assert [row["job_id"] for row in normal["jobs"]] == ["job_normal"], normal
    strong = jq.list_reports(limit=20, min_win=50, min_pf=1.0)
    assert {row["job_id"] for row in strong["jobs"]} == {"job_rare", "job_normal"}, strong
    confidence = jq.list_reports(limit=20, sort_col="confidence", sort_dir="desc")
    scores = [row["confidence"]["score"] for row in confidence["jobs"]]
    assert scores == sorted(scores, reverse=True), confidence


@case("stage2 backtest requirements flag optimistic assumptions")
def t15(tmp: Path) -> None:
    # Optimistic defaults: Standard fill, slip 0, synthetic 0 commission, no
    # contract month -> every Stage 2 honesty check should warn.
    req = jq.CreateJobRequest(
        class_name="SampleMACrossOver",
        instrument="MNQ",
        bars_period_type="Minute",
        bars_period_value=1,
        from_utc="2026-05-08T00:00:00Z",
        to_utc="2026-05-09T00:00:00Z",
        parameters={},
        order_fill_resolution="Standard",
        slippage_ticks=0,
        commission_template="None",
        session_template="",
        timezone="",
    )
    reqs = jq.stage2_backtest_requirements(req)
    assert reqs["contract_version"] == "0.2", reqs
    assert reqs["requires_runtime_historical_data_fingerprint"] is True, reqs
    blob = " ".join(reqs["warnings"]).lower()
    assert "session_template" in blob, reqs
    assert "timezone" in blob, reqs
    assert "high" in blob, reqs
    assert "slippage" in blob, reqs
    assert "commission" in blob, reqs
    assert "contract month" in blob, reqs

    # Honest, explicit assumptions: no warnings.
    ok = jq.CreateJobRequest(
        class_name="SampleMACrossOver",
        instrument="MNQ SEP26",
        bars_period_type="Minute",
        bars_period_value=1,
        from_utc="2026-05-08T00:00:00Z",
        to_utc="2026-05-09T00:00:00Z",
        parameters={},
        order_fill_resolution="High",
        slippage_ticks=3,
        commission_template="NinjaTrader Micro",
        session_template="CME US Index Futures RTH",
        timezone="UTC",
    )
    ok_reqs = jq.stage2_backtest_requirements(ok)
    assert ok_reqs["warnings"] == [], ok_reqs


@case("internal profile metadata keys are stripped from bridge strategy parameters")
def t16(tmp: Path) -> None:
    req = jq.CreateJobRequest(
        class_name="SampleMACrossOver",
        instrument="MNQ 09-26",
        bars_period_type="Minute",
        bars_period_value=1,
        from_utc="2026-05-08T00:00:00Z",
        to_utc="2026-05-09T00:00:00Z",
        parameters={
            "Fast": 10,
            "_session_template": "Nymex Metals RTH1",
            "_profile_note": "metadata only",
        },
    )
    jq._strip_internal_strategy_parameters(req)  # type: ignore[attr-defined]
    assert req.parameters == {"Fast": 10}, req.parameters


@case("current-contract jobs align ContractName and InstrumentName parameters")
def t17(tmp: Path) -> None:
    req = jq.CreateJobRequest(
        class_name="NTAMnqLiquiditySweepReversalC015",
        instrument="MNQ 09-26",
        bars_period_type="Minute",
        bars_period_value=1,
        from_utc="2026-05-08T00:00:00Z",
        to_utc="2026-05-09T00:00:00Z",
        parameters={
            "ContractName": "MNQ 06-26",
            "InstrumentName": "MNQ",
            "RoundTurnCommission": 1.90,
        },
    )
    jq._align_instrument_strategy_parameters(req)  # type: ignore[attr-defined]
    assert req.parameters["ContractName"] == "MNQ 09-26", req.parameters
    assert req.parameters["InstrumentName"] == "MNQ", req.parameters


@case("catalog excludes rejected/decommissioned strategy classes")
def t18(tmp: Path) -> None:
    jq.project_root = lambda: tmp  # type: ignore[assignment]
    jq.reset_caches()

    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.1",
        "profiles": [{
            "profile_id": "mgc_b1_shortonly_5m_paper_v2",
            "name": "B1 ShortOnly MGC 5m v2 c002",
            "strategy_class": "NTAMicroVwapRiskExplorer",
            "deploy_strategy_class": "B1ShortOnlyMGC5mV2",
            "instrument": "MGC 08-26",
            "timeframe": "5 Minute",
            "status": "archived",
        }],
    }), encoding="utf-8")

    ops_dir = tmp / "data" / "ops"
    ops_dir.mkdir(parents=True, exist_ok=True)
    (ops_dir / "scc_classes.json").write_text(json.dumps({
        "rejected": ["B1ShortOnlyMGC5mV2"],
    }), encoding="utf-8")

    src = (
        tmp / "NTUser" / "bin" / "Custom" / "Strategies" /
        "NT-Analyzer_strategies" / "B1ShortOnlyMGC5mV2" / "B1ShortOnlyMGC5mV2.cs"
    )
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("public class B1ShortOnlyMGC5mV2 { }", encoding="utf-8")

    catalog_dir = tmp / "data" / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.0",
        "strategies": [{
            "class_name": "B1ShortOnlyMGC5mV2",
            "display_name": "B1 ShortOnly MGC 5m v2 c002",
            "source_file": str(src),
            "parameters": [],
        }],
    }), encoding="utf-8")

    out = jq.build_catalog_response()
    classes = {s.get("class_name") for s in out.get("strategies") or []}
    assert "B1ShortOnlyMGC5mV2" not in classes, out


@case("archiving profile auto-triggers NinjaTrader cleanup")
def t19(tmp: Path) -> None:
    profiles_dir = tmp / "data" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "strategies.json").write_text(json.dumps({
        "schema_version": "1.1",
        "profiles": [
            {
                "profile_id": "mnq_daily_open_allmodules_2h_1m_c018_ready_v1",
                "name": "Scalping MNQ 1m v1 c018",
                "strategy_class": "NTAMicroMnqScalpPilot",
                "deploy_strategy_class": "NTAMnqDailyOpenScalpC018",
                "instrument": "MNQ 09-26",
                "timeframe": "1 Minute",
                "cell_id": "CELL-018",
                "status": "ready",
                "notes": "old",
            }
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    calls: list[str | None] = []
    original = jq.remove_archived_from_ninjatrader

    def fake_cleanup(profile_id: str | None = None) -> dict:
        calls.append(profile_id)
        data = json.loads((profiles_dir / "strategies.json").read_text(encoding="utf-8"))
        prof = data["profiles"][0]
        prof.setdefault("failed_archive", {})
        prof["failed_archive"]["removed_from_ninjatrader"] = True
        prof["failed_archive"]["removal"] = {"reason": "already_absent"}
        (profiles_dir / "strategies.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"ok": True, "count": 1, "removed": 1, "results": [{"profile_id": profile_id, "removed": True}]}

    jq.remove_archived_from_ninjatrader = fake_cleanup  # type: ignore[assignment]
    try:
        out = jq.update_strategy_profile(
            "mnq_daily_open_allmodules_2h_1m_c018_ready_v1",
            {"status": "archived", "notes": "Rejected in paper"},
            action="archive",
        )
    finally:
        jq.remove_archived_from_ninjatrader = original  # type: ignore[assignment]

    assert calls == ["mnq_daily_open_allmodules_2h_1m_c018_ready_v1"], calls
    assert out["ok"] is True, out
    assert out["profile"]["status"] == "archived", out
    assert out["profile"]["matrix_hidden"] is True, out
    assert out["profile"]["failed_archive"]["removed_from_ninjatrader"] is True, out
    assert out["ninjatrader_cleanup"]["removed"] == 1, out
    assert out["profile"]["failed_archive"]["fingerprint"], out


def main() -> int:
    cases = [t01, t02, t03, t04, t05, t06, t07, t08, t08b, t09, t10, t11, t12, t13, t14, t15, t16, t17, t18]
    print(f"Running {len(cases)} queue contract tests:")
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
