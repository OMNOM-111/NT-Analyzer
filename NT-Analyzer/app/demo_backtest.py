"""Canned demo backtests for free_preview users (no NinjaTrader).

Creates synthetic jobs under ``jobs/done/`` so existing report/job/trades APIs
work unchanged. Quota: ``max_demo_backtests_per_day`` (default 3).
"""
from __future__ import annotations

import json
import math
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import jobqueue, runtime_env


class DemoBacktestError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


_LOCK = threading.RLock()
_DEFAULT_DAILY_LIMIT = 3

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "mnq_orb_90d": {
        "label": "ORB Reversion · MNQ",
        "class_name": "DemoORBReversion",
        "instrument": "MNQ 09-26",
        "bars_period_type": "Minute",
        "bars_period_value": 5,
        "days": 90,
        "starting_capital": 50000,
        "trade_count": 28,
        "win_rate": 0.57,
        "net_profit": 1840.0,
        "max_dd": -620.0,
        "commission_total": 112.0,
        "seed": 101,
    },
    "mes_vwap_90d": {
        "label": "VWAP Fade · MES",
        "class_name": "DemoVwapFade",
        "instrument": "MES 09-26",
        "bars_period_type": "Minute",
        "bars_period_value": 3,
        "days": 90,
        "starting_capital": 25000,
        "trade_count": 36,
        "win_rate": 0.61,
        "net_profit": 960.0,
        "max_dd": -410.0,
        "commission_total": 144.0,
        "seed": 202,
    },
    "mgc_london_30d": {
        "label": "London Break · MGC",
        "class_name": "DemoLondonBreak",
        "instrument": "MGC 08-26",
        "bars_period_type": "Minute",
        "bars_period_value": 15,
        "days": 30,
        "starting_capital": 10000,
        "trade_count": 18,
        "win_rate": 0.55,
        "net_profit": 420.0,
        "max_dd": -190.0,
        "commission_total": 54.0,
        "seed": 303,
    },
}


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _quota_path() -> Path:
    return runtime_env.data_root(_root()) / "runtime" / "demo_backtests.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds").replace("+00:00", "Z")


def _day_key(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).strftime("%Y-%m-%d")


def list_scenarios() -> List[Dict[str, Any]]:
    return [
        {
            "id": key,
            "label": row["label"],
            "instrument": row["instrument"],
            "days": row["days"],
            "trade_count": row["trade_count"],
            "net_profit": row["net_profit"],
        }
        for key, row in SCENARIOS.items()
    ]


def _load_quota() -> Dict[str, Any]:
    path = _quota_path()
    if not path.is_file():
        return {"version": 1, "days": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "days": {}}
    return doc if isinstance(doc, dict) else {"version": 1, "days": {}}


def _save_quota(doc: Dict[str, Any]) -> None:
    path = _quota_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def remaining_today(user_id: Any, *, limit: int = _DEFAULT_DAILY_LIMIT) -> int:
    uid = str(int(user_id or 0))
    with _LOCK:
        doc = _load_quota()
        used = list((doc.get("days") or {}).get(_day_key(), {}).get(uid) or [])
    return max(0, int(limit) - len(used))


def _consume_quota(user_id: int, job_id: str, *, limit: int) -> int:
    uid = str(int(user_id))
    day = _day_key()
    with _LOCK:
        doc = _load_quota()
        days = doc.setdefault("days", {})
        # Drop old days (keep 7).
        for key in list(days.keys()):
            if key < ( _now() - timedelta(days=7)).strftime("%Y-%m-%d"):
                days.pop(key, None)
        bucket = list(days.get(day, {}).get(uid) or [])
        if len(bucket) >= int(limit):
            raise DemoBacktestError(
                f"Лимит демо-бэктестов на сегодня исчерпан ({limit}/день). "
                "Оформите подписку или введите промокод для полного доступа.",
                429,
            )
        bucket.append({"job_id": job_id, "at": _now_iso()})
        days.setdefault(day, {})[uid] = bucket
        _save_quota(doc)
        return max(0, int(limit) - len(bucket))


def _rng(seed: int):
    # Simple LCG for deterministic fake trades.
    state = seed & 0xFFFFFFFF

    def next_float() -> float:
        nonlocal state
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        return state / 0xFFFFFFFF

    return next_float


def _build_trades(scenario: Dict[str, Any], job_id: str) -> List[Dict[str, Any]]:
    rnd = _rng(int(scenario["seed"]))
    n = int(scenario["trade_count"])
    wins = int(round(n * float(scenario["win_rate"])))
    end = _now()
    start = end - timedelta(days=int(scenario["days"]))
    trades = []
    instrument = scenario["instrument"]
    for i in range(n):
        is_win = i < wins
        # Shuffle win/loss with seed noise while keeping approximate win rate.
        if rnd() > 0.55:
            is_win = not is_win and i % 3 != 0
        t0 = start + timedelta(hours=6 + i * (int(scenario["days"]) * 24 / max(n, 1)))
        t1 = t0 + timedelta(minutes=15 + int(rnd() * 90))
        qty = 1
        entry = 18000 + rnd() * 400 if "MNQ" in instrument else (5200 + rnd() * 80 if "MES" in instrument else 2300 + rnd() * 40)
        move = (8 + rnd() * 24) * (1 if is_win else -1)
        if "MGC" in instrument:
            move = (1.2 + rnd() * 3.5) * (1 if is_win else -1)
        exit_px = entry + move
        pnl = round(abs(move) * (2.0 if "MNQ" in instrument else 5.0 if "MES" in instrument else 10.0) * (1 if is_win else -1), 2)
        commission = round(float(scenario["commission_total"]) / n, 2)
        trades.append({
            "trade_no": i + 1,
            "instrument": instrument,
            "market_position": "Long" if rnd() > 0.45 else "Short",
            "quantity": qty,
            "entry_time_utc": t0.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "exit_time_utc": t1.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "entry_price": round(entry, 2),
            "exit_price": round(exit_px, 2),
            "pnl_currency": pnl,
            "commission": commission,
            "mae_currency": round(-abs(pnl) * (0.3 + rnd() * 0.4), 2),
            "mfe_currency": round(abs(pnl) * (0.6 + rnd() * 0.5), 2),
            "job_id": job_id,
            "demo": True,
        })
    # Rescale PnL to match scenario net_profit approximately.
    gross = sum(float(t["pnl_currency"]) for t in trades)
    target = float(scenario["net_profit"]) + float(scenario["commission_total"])
    if abs(gross) > 1e-6:
        scale = target / gross
        for t in trades:
            t["pnl_currency"] = round(float(t["pnl_currency"]) * scale, 2)
    return trades


def _write_job_files(*, job_id: str, user_id: int, scenario_id: str, scenario: Dict[str, Any],
                     trades: List[Dict[str, Any]], workspace_id: str = "") -> Path:
    done = jobqueue.jobs_dir() / "done" / job_id
    done.mkdir(parents=True, exist_ok=True)
    end = _now()
    start = end - timedelta(days=int(scenario["days"]))
    created = _now_iso()
    net = float(scenario["net_profit"])
    dd = float(scenario["max_dd"])
    commission = float(scenario["commission_total"])
    n = len(trades)
    wins = sum(1 for t in trades if float(t.get("pnl_currency") or 0) > 0)
    job_doc = {
        "schema_version": "0.1",
        "job_id": job_id,
        "kind": "demo_backtest",
        "created_at_utc": created,
        "origin": {
            "type": "demo",
            "scenario_id": scenario_id,
            "user_id": int(user_id),
            "workspace_id": str(workspace_id or ""),
            "watermark": "Демоверсия. Данные нереальные.",
        },
        "strategy": {
            "class_name": scenario["class_name"],
            "display_name": scenario["label"],
            "parameters": {"DemoMode": True, "Scenario": scenario_id},
        },
        "instrument": scenario["instrument"],
        "bars_period_type": scenario["bars_period_type"],
        "bars_period_value": scenario["bars_period_value"],
        "from_utc": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "to_utc": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "risk_profile": {"StartingCapital": scenario["starting_capital"]},
        "execution": {"commission": 0, "commission_template": "None", "slippage_ticks": 1},
        "role": "demo",
    }
    result_doc = {
        "schema_version": "0.1",
        "job_id": job_id,
        "kind": "demo_backtest",
        "started_at_utc": created,
        "finished_at_utc": _now_iso(),
        "duration_ms": 1200 + int(scenario["seed"]) % 800,
        "source": {"execution_source": "synthetic", "demo": True},
        "origin": job_doc["origin"],
        "context": {
            "strategy": job_doc["strategy"],
            "instrument": scenario["instrument"],
            "timeframe": {
                "bars_period_type": scenario["bars_period_type"],
                "value": scenario["bars_period_value"],
            },
            "period": {"from_utc": job_doc["from_utc"], "to_utc": job_doc["to_utc"]},
            "risk_profile": job_doc["risk_profile"],
        },
        "metrics": {
            "trade_count": n,
            "winning_trades": wins,
            "losing_trades": n - wins,
            "percent_profitable": round(100.0 * wins / max(n, 1), 2),
            "net_profit": net,
            "gross_profit": round(sum(float(t["pnl_currency"]) for t in trades if float(t["pnl_currency"]) > 0), 2),
            "gross_loss": round(sum(float(t["pnl_currency"]) for t in trades if float(t["pnl_currency"]) < 0), 2),
            "max_drawdown": dd,
            "commission": commission,
            "profit_factor": round(abs(net / dd), 2) if dd else 0,
            "average_trade": round(net / max(n, 1), 2),
        },
        "watermark": "Демоверсия. Данные нереальные.",
    }
    (done / "job.json").write_text(json.dumps(job_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (done / "result.json").write_text(json.dumps(result_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (done / "trades.json").write_text(json.dumps(trades, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        jobqueue._ensure_report_number("job", job_id, created)
    except Exception:
        pass
    return done


def create_demo_backtest(
    user_id: Any,
    *,
    scenario_id: str = "",
    daily_limit: int = _DEFAULT_DAILY_LIMIT,
    workspace_id: str = "",
) -> Dict[str, Any]:
    uid = int(user_id or 0)
    if uid <= 0:
        raise DemoBacktestError("Требуется вход.", 401)
    sid = str(scenario_id or "").strip() or next(iter(SCENARIOS))
    scenario = SCENARIOS.get(sid)
    if scenario is None:
        raise DemoBacktestError(
            f"Неизвестный демо-сценарий: {sid}. Доступны: {', '.join(SCENARIOS)}.",
            404,
        )
    job_id = "demo_" + secrets.token_hex(10)
    remaining = _consume_quota(uid, job_id, limit=daily_limit)
    trades = _build_trades(scenario, job_id)
    path = _write_job_files(
        job_id=job_id, user_id=uid, scenario_id=sid, scenario=scenario, trades=trades,
        workspace_id=workspace_id,
    )
    return {
        "ok": True,
        "demo": True,
        "job_id": job_id,
        "scenario_id": sid,
        "label": scenario["label"],
        "path": str(path),
        "remaining_today": remaining,
        "daily_limit": int(daily_limit),
        "watermark": "Демоверсия. Данные нереальные.",
        "cta": "После подписки откроются полный бэктест, свои стратегии и live/paper контуры.",
    }
