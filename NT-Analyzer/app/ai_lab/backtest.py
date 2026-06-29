"""Historical backtest orchestration for AI experiments.

Thin wrapper around app.jobqueue.create_job that enforces AI-Lab execution
invariants (research role, High fill, slip >= 1, RT commission >= 1.90,
intraday session, no overnight) and stamps the job with AI origin metadata.

Source of truth for backtest results remains NT-Analyzer / NinjaTrader.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from .. import governance


# Public compatibility floors. Governance may raise them, but never lower them.
AI_COMMISSION_FLOOR = 1.90
AI_SLIPPAGE_FLOOR = 1


def _runtime_defaults() -> Dict[str, Any]:
    return governance.runtime_defaults()


def _ai_commission_floor() -> float:
    configured = float(
        _runtime_defaults().get("round_turn_commission", AI_COMMISSION_FLOOR)
        or AI_COMMISSION_FLOOR
    )
    return max(AI_COMMISSION_FLOOR, configured)


def _ai_slippage_floor() -> int:
    configured = int(
        _runtime_defaults().get("slippage_ticks", AI_SLIPPAGE_FLOOR)
        or AI_SLIPPAGE_FLOOR
    )
    return max(AI_SLIPPAGE_FLOOR, configured)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _map_parameters_to_exposed(
    parameters: Dict[str, Any],
    exposed: Any,
) -> Dict[str, Any]:
    """Map LLM snake_case/case variants onto the actual NT8 property names."""
    names = [str(name) for name in (exposed or [])]
    if not names:
        return dict(parameters or {})

    def norm(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())

    by_norm = {norm(name): name for name in names}
    aliases = {
        "maxdailytrades": "MaxTradesPerDay",
        "takeprofitticks": "ProfitTargetTicks",
    }
    mapped: Dict[str, Any] = {}
    for key, value in (parameters or {}).items():
        key_text = str(key)
        target = key_text if key_text in names else by_norm.get(norm(key_text))
        if target is None:
            alias = aliases.get(norm(key_text))
            if alias in names:
                target = alias
        if target is not None:
            mapped[target] = value
    return mapped


def submit(
    *,
    experiment_id: str,
    ai_cell_id: str,
    class_name: str,
    instrument: str,
    from_utc: str,
    to_utc: str,
    parameters: Dict[str, Any],
    risk_profile: Dict[str, Any],
    session_template: str = "CME US Index Futures RTH",
    bars_period_type: str = "Minute",
    bars_period_value: int = 5,
    model_chain: Optional[List[str]] = None,
    stage: str = "full",
) -> Dict[str, Any]:
    """Submit a historical backtest job; returns dict with job_id + meta.

    Falls back gracefully if jobqueue.create_job signature differs or is
    unavailable so the orchestrator can still record intent.
    """
    try:
        from .. import jobqueue
    except Exception as e:
        return {"ok": False, "error": f"jobqueue import failed: {e}"}

    if not hasattr(jobqueue, "CreateJobRequest") or not hasattr(jobqueue, "create_job"):
        return {"ok": False, "error": "jobqueue API missing CreateJobRequest/create_job"}

    safe_parameters = dict(parameters or {})
    safe_parameters.setdefault("RoundTurnCommission", _ai_commission_floor())
    safe_parameters.setdefault("SlippageTicks", _ai_slippage_floor())
    try:
        exposed = jobqueue._strategy_parameter_names(class_name)
        if exposed:
            safe_parameters = _map_parameters_to_exposed(safe_parameters, exposed)
    except Exception:
        pass

    origin = {
        "type": "ai_lab",
        "created_by": "ai",
        "experiment_id": experiment_id,
        "ai_cell_id": ai_cell_id,
        "model_chain": model_chain or [],
        "submitted_at_utc": _now(),
        "stage": stage,
    }

    req = jobqueue.CreateJobRequest(
        class_name=class_name,
        instrument=instrument,
        bars_period_type=bars_period_type,
        bars_period_value=bars_period_value,
        from_utc=from_utc,
        to_utc=to_utc,
        parameters=safe_parameters,
        risk_profile=risk_profile,
        calculate="OnBarClose",
        is_tick_replay=False,
        order_fill_resolution=str(_runtime_defaults().get("order_fill_resolution", "High") or "High"),
        slippage_ticks=max(
            _ai_slippage_floor(),
            int(parameters.get("SlippageTicks", parameters.get("slippage_ticks", _ai_slippage_floor()))),
        ),
        # jobqueue rejects numeric commissions; the honest research floor is
        # carried through execution.round_turn_commission / strategy params.
        commission=0.0,
        commission_template="None",
        session_template=session_template,
        timezone="UTC",
        role="research",
        origin=origin,
    )

    try:
        job_id, job_dir = jobqueue.create_job(req)
    except Exception as e:
        return {"ok": False, "error": f"create_job failed: {e}"}

    return {
        "ok": True,
        "job_id": job_id,
        "job_dir": str(job_dir),
        "submitted_at_utc": _now(),
        "request": {
            "instrument": instrument,
            "from_utc": from_utc,
            "to_utc": to_utc,
            "bars_period_type": bars_period_type,
            "bars_period_value": bars_period_value,
            "session_template": session_template,
            "stage": stage,
        },
    }


def find_job_dir(job_id: str) -> Optional[Path]:
    try:
        from .. import jobqueue
    except Exception:
        return None
    if hasattr(jobqueue, "jobs_dir"):
        root = Path(jobqueue.jobs_dir())
        for sub in ("done", "running", "failed", "cancelled", "pending"):
            candidate = root / sub / job_id
            if candidate.exists():
                return candidate
    return None


def job_status(job_id: str) -> Dict[str, Any]:
    d = find_job_dir(job_id)
    if not d:
        return {"job_id": job_id, "status": "unknown", "found": False}
    parent = d.parent.name
    return {"job_id": job_id, "status": parent, "found": True, "dir": str(d)}


def wait_for_terminal(
    job_id: str,
    *,
    timeout_sec: int = 180,
    poll_sec: float = 1.0,
) -> Dict[str, Any]:
    deadline = time.time() + max(1, timeout_sec)
    while time.time() < deadline:
        status = job_status(job_id)
        if status.get("status") in {"done", "failed", "cancelled"}:
            return status
        time.sleep(max(0.2, poll_sec))
    return {"job_id": job_id, "status": "timeout", "found": False}


def result_metrics(job_id: str) -> Dict[str, Any]:
    try:
        from .. import jobqueue
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    full = jobqueue.read_job_full(job_id) or {}
    result = full.get("result") or {}
    metrics = result.get("metrics") or {}
    return {
        "ok": full.get("status") == "done",
        "status": full.get("status"),
        "metrics": metrics,
        "trade_count": int(metrics.get("trade_count_adjusted", metrics.get("trade_count", 0)) or 0),
        "job": full,
    }
