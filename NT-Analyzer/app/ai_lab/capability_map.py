"""Capability-first dispatch for common owner operations.

Personas remain presentation identities.  This module is the executable map:
an intent names a capability, and the capability selects a concrete local
handler.  Imports are lazy to keep the existing AI-Lab dependency graph acyclic.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional


CAPABILITY_MAP: Dict[str, Dict[str, Any]] = {
    "chart_snapshot": {"handler": "chart_operator", "agent": "ivan", "safe": True},
    "chart_draw": {"handler": "chart_operator", "agent": "ivan", "safe": True},
    "chart_open": {"handler": "chart_operator", "agent": "ivan", "safe": True},
    "chart_clear": {"handler": "chart_operator", "agent": "ivan", "safe": True},
    "accounting_report": {"handler": "domain_report", "agent": "marina", "safe": True},
    "strategy_report": {"handler": "domain_report", "agent": "tolik", "safe": True},
    "news_report": {"handler": "domain_report", "agent": "nikita", "safe": True},
    "deliver_report": {"handler": "combined_report", "agent": "orchestrator", "safe": True},
    "start_backtest": {"handler": "start_backtest", "agent": "tolik", "safe": True},
}


def supports(name: Any) -> bool:
    return str(name or "") in CAPABILITY_MAP


def _find_experiment(message: str, history: Iterable[Dict[str, Any]],
                     scope: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    from . import registry

    text = "\n".join([str(message or ""), *[str(row.get("content") or "") for row in history][-8:]])
    experiments = registry.list_experiments(limit=500)
    workspace_id = str((scope or {}).get("workspace_id") or "")
    if workspace_id and not bool((scope or {}).get("uses_owner_runtime")):
        experiments = [
            row for row in experiments
            if str(row.get("workspace_id") or "") == workspace_id
        ]
    exp_match = re.search(r"\bEXP-\d{8}-\d{4}\b", text, flags=re.IGNORECASE)
    if exp_match:
        wanted = exp_match.group(0).upper()
        found = registry.read_experiment(wanted)
        if found and (not workspace_id or bool((scope or {}).get("uses_owner_runtime"))
                      or str(found.get("workspace_id") or "") == workspace_id):
            return found
    low = text.lower()
    for row in experiments:
        class_name = str(row.get("class_name") or "").strip()
        if class_name and class_name != "PENDING" and class_name.lower() in low:
            return row
    root_match = re.search(r"\b(MNQ|MGC|MES|MCL)\b", text, flags=re.IGNORECASE)
    if root_match:
        root = root_match.group(1).upper()
        return next((row for row in experiments if row.get("target_root") == root and str(row.get("class_name") or "") != "PENDING"), None)
    return None


def _start_backtest(message: str, *, intent: Dict[str, Any], history: List[Dict[str, Any]],
                    scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from . import backtest, orchestrator, registry, runner

    experiment = _find_experiment(message, history, scope)
    root = str(intent.get("target_root") or "").upper()
    if experiment:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        period = experiment.get("period") if isinstance(experiment.get("period"), dict) else {}
        target_root = str(experiment.get("target_root") or root or "MNQ").upper()
        instrument = str(
            experiment.get("backtest_instrument")
            or experiment.get("instrument")
            or orchestrator.DEFAULT_INSTRUMENT_BY_ROOT.get(target_root, target_root)
        )
        submitted = backtest.submit(
            experiment_id=str(experiment.get("experiment_id") or ""),
            ai_cell_id=str(experiment.get("ai_cell_id") or ""),
            class_name=str(experiment.get("class_name") or ""),
            instrument=instrument,
            from_utc=str(period.get("from_utc") or (now - timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ")),
            to_utc=str(period.get("to_utc") or now.strftime("%Y-%m-%dT%H:%M:%SZ")),
            parameters=dict(experiment.get("parameters") or {}),
            risk_profile=dict(experiment.get("risk_profile") or {}),
            session_template=str(experiment.get("session_template") or "CME US Index Futures RTH"),
            model_chain=list(experiment.get("model_chain") or []),
            stage="owner_requested",
            workspace_id=str((scope or {}).get("workspace_id") or ""),
            user_id=int((scope or {}).get("user_id") or 0),
        )
        if not submitted.get("ok"):
            return {
                "ok": False,
                "reply": "Не удалось поставить бэктест в очередь: " + str(submitted.get("error") or "неизвестная ошибка"),
                "actions": [{"name": "start_backtest", "status": "error", "error": str(submitted.get("error") or "submit_failed")}],
            }
        audit = list(experiment.get("manual_backtests") or [])
        audit.append({"job_id": submitted.get("job_id"), "submitted_at_utc": submitted.get("submitted_at_utc"), "source": "orchestrator"})
        experiment["manual_backtests"] = audit[-50:]
        registry.write_experiment(experiment)
        job_id = str(submitted.get("job_id") or "")
        return {
            "ok": True,
            "reply": f"Бэктест {experiment.get('class_name')} поставлен в очередь. Job ID: {job_id}.",
            "actions": [{"name": "start_backtest", "status": "queued", "job_id": job_id, "experiment_id": experiment.get("experiment_id")}],
            "job_id": job_id,
        }
    if not root:
        return {
            "ok": True,
            "needs_input": True,
            "reply": "Уточните стратегию или инструмент для бэктеста — например: «запусти бэктест NTAStrategyName» или «запусти бэктест MNQ».",
            "actions": [{"name": "start_backtest", "status": "needs_input", "reason": "strategy_not_specified"}],
        }
    started = runner.start({
        "user_pref_root": root,
        "user_goal": str(message or "")[:2000],
        "strategy_count": 1,
        "iterations_per_strategy": 1,
        "max_total_runtime_minutes": 180,
        "stop_on_first_candidate": True,
        "use_llm": True,
        "workspace_id": str((scope or {}).get("workspace_id") or ""),
        "user_id": int((scope or {}).get("user_id") or 0),
        "user_name": str((scope or {}).get("display_name") or ""),
    })
    run_id = str(started.get("run_id") or "")
    experiment_id = str(started.get("experiment_id") or "")
    return {
        "ok": True,
        "reply": f"Запустил полный historical-пайплайн по {root}. Run ID: {run_id}; experiment: {experiment_id}. Job ID появится после compile и signal-sanity.",
        "actions": [{"name": "start_backtest", "status": "queued", "run_id": run_id, "experiment_id": experiment_id}],
        "run_id": run_id,
        "experiment_id": experiment_id,
    }


def execute(name: str, message: str, *, conversation_id: str = "", intent: Optional[Dict[str, Any]] = None,
            history: Optional[List[Dict[str, Any]]] = None,
            scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    capability = str(name or "")
    spec = CAPABILITY_MAP.get(capability)
    if not spec:
        raise ValueError(f"unknown capability: {capability}")
    from . import domain_agents

    handler = str(spec["handler"])
    if handler == "chart_operator":
        # Route the shared canonical form (mixed keyboard symbols such as 6с
        # are already repaired), while conversation/audit storage retains the
        # owner's original wording.
        routed_message = str((intent or {}).get("normalized_message") or message or "")
        intent_root = str((intent or {}).get("target_root") or "")
        if (intent or {}).get("followup_retry"):
            operation = {
                "chart_snapshot": "сделай снимок",
                "chart_draw": "поставь отметку",
                "chart_open": "открой график",
                "chart_clear": "очисти график",
            }.get(capability, "покажи график")
            routed_message = f"{operation} {intent_root}".strip()
        elif intent_root and intent_root.lower() not in routed_message.lower():
            routed_message = f"{routed_message} {intent_root}".strip()
        result = domain_agents.answer(
            "ivan", routed_message, conversation_id=conversation_id,
            workspace_id=str((scope or {}).get("workspace_id") or ""),
            uses_owner_runtime=bool((scope or {}).get("uses_owner_runtime", True)),
            scope=scope,
        )
    elif handler == "domain_report":
        result = domain_agents.answer(
            str(spec["agent"]), message,
            period=str((intent or {}).get("period") or "month"),
            conversation_id=conversation_id,
            workspace_id=str((scope or {}).get("workspace_id") or ""),
            uses_owner_runtime=bool((scope or {}).get("uses_owner_runtime", True)),
            scope=scope,
        )
    elif handler == "combined_report":
        result = domain_agents.deliver_report(
            str((intent or {}).get("period") or "month"),
            workspace_id=str((scope or {}).get("workspace_id") or ""),
            uses_owner_runtime=bool((scope or {}).get("uses_owner_runtime", True)),
        )
    elif handler == "start_backtest":
        result = _start_backtest(
            message, intent=dict(intent or {}), history=list(history or []), scope=scope,
        )
        result.setdefault("model", "capability dispatcher")
        result.setdefault("provider", "local")
        result.setdefault("complexity", "light")
        result.setdefault("agent", dict(domain_agents.PERSONAS["tolik"]))
    else:  # pragma: no cover - map and executor must evolve together
        raise ValueError(f"missing handler: {handler}")
    result["capability"] = capability
    return result


def recover_refusal(message: str, *, conversation_id: str = "", history: Optional[List[Dict[str, Any]]] = None,
                    scope: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Try every known in-app route before allowing a capability refusal."""
    from . import intent_classifier

    intent = intent_classifier.classify(message)
    capability = str(intent.get("capability") or "")
    if not supports(capability):
        return None
    return execute(
        capability, message, conversation_id=conversation_id,
        intent=intent, history=history, scope=scope,
    )
