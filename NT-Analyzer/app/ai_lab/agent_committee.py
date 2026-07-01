"""Advisory multi-agent review of deterministic backtest metrics.

The committee can explain results and propose the next mutation. It cannot
change the deterministic verdict, submit a backtest, or promote a strategy.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from . import agent_router


ROLE_PROMPTS = {
    "backtest_analyst": (
        "Analyze robustness, regime dependence, execution assumptions and the "
        "difference between in-sample and out-of-sample evidence."
    ),
    "risk_manager": (
        "Find drawdown, tail-risk, concentration, small-sample and execution risks. "
        "Be conservative and never recommend paper/live promotion."
    ),
    "optimizer": (
        "Propose exactly one structural mutation for the next sandbox iteration. "
        "Do not propose blind parameter grid optimization."
    ),
}


def review_backtest(experiment: Dict[str, Any]) -> Dict[str, Any]:
    metrics = {
        "experiment_id": experiment.get("experiment_id"),
        "target_root": experiment.get("target_root"),
        "family": experiment.get("family"),
        "iteration": experiment.get("current_iteration"),
        "analysis": experiment.get("analysis") or {},
        "deterministic_arbitration": experiment.get("arbitration") or {},
    }
    metric_text = json.dumps(metrics, ensure_ascii=False, default=str)
    reports: Dict[str, Any] = {}
    for role, instruction in ROLE_PROMPTS.items():
        try:
            result = agent_router.invoke_role(
                role,
                f"{instruction}\n\nMetrics only (no prompt/source secrets):\n{metric_text}",
                system_prompt=(
                    "You are an advisory member of a historical-only trading research lab. "
                    "Return concise JSON with keys decision, evidence, risks, next_action. "
                    "Your output is advisory and cannot override deterministic gates."
                ),
                max_output_tokens=700,
                timeout=120,
                purpose=f"backtest_committee_{role}",
            )
            reports[role] = {
                "ok": True,
                "provider": result.get("provider"),
                "model": result.get("actual_model") or result.get("model"),
                "agent_id": result.get("agent_id"),
                "content": str(result.get("content") or "")[:6000],
                "input_tokens": result.get("input_tokens"),
                "output_tokens": result.get("output_tokens"),
                "cost_usd": result.get("cost_usd"),
                "cost_estimated": result.get("cost_estimated"),
            }
        except agent_router.AgentRouterError as exc:
            reports[role] = {"ok": False, "error": str(exc)[:500]}
    return {
        "advisory_only": True,
        "cannot_override_deterministic_verdict": True,
        "reports": reports,
    }
