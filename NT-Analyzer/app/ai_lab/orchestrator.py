"""AI Strategy Lab main orchestrator.

Split into two phases:

- :func:`start_skeleton` — fast/synchronous: pick root, capital, hypothesis
  skeleton, allocate experiment_id + ai_cell_id, write initial draft record.
  Called from the HTTP request thread so the UI gets the id in <1s.

- :func:`run_pipeline` — slow/background: intake → generate → validate →
  write → compile → catalog → backtest. Owned by the runner's daemon thread.

Both emit ``activity.log(...)`` entries so the UI can stream the work. The
activity log contains stage transitions, file paths, model prompt previews,
and short response summaries — never full chain-of-thought.

Auto-finalize (analysis + arbitration after the backtest result.json lands) is
driven by :mod:`runner` after this module returns from :func:`run_pipeline`.

Portfolio lifecycle: every experiment write goes through
:func:`registry.write_experiment`, which stamps a ``lifecycle`` stage derived
from the experiment ``status`` (see :func:`app.strategy_lifecycle.lifecycle_for_ai_status`):
generating/backtesting/candidate → *Испытание*, portfolio_contributor →
*Утверждено для демо*, rejected/cancelled/*_failed/blocked → *Провалено → Архив*.
The lifecycle board reads these via ``/api/ai-lab/lifecycle`` so an AI strategy
appears under the "AI / LM Studio" branch and moves between the four columns as
its status advances. Rule: every started idea must be driven to a terminal
stage (approved or archived) — never left dangling mid-pipeline. See
``docs/strategies/STRATEGY_LIFECYCLE.md``.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import activity, agent_committee, agent_router, arbitration, backtest, cloud_agents, compile_pipeline, errors, generator, lessons
from . import compile_errors, goal_parser, knowledge, llm_timeouts, lm_studio, operator_notes, registry, runner, user_research
from . import signal_sanity
from .analysis_pack import build as build_pack, project_to_experiment_analysis
from .heartbeat import heartbeat


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


DEFAULT_INSTRUMENT_BY_ROOT = {
    "MNQ": "MNQ 09-26",
    "MGC": "MGC 08-26",
    "MES": "MES 09-26",
    "MCL": "MCL 08-26",
}

INSTRUMENT_UNIVERSE = ["MNQ", "MGC", "MES"]

MAX_COMPILE_ATTEMPTS = 5

_MODEL_HEALTH_CACHE: Dict[str, Dict[str, Any]] = {}
_MODEL_HEALTH_LOCK = threading.RLock()
_MODEL_HEALTH_TTL_SEC = 900


def _cached_model_health(
    role: str,
    *,
    fallback_roles: List[str],
    experiment_id: str,
) -> Dict[str, Any]:
    """Probe a local role once per run-sized window instead of per iteration."""
    now = time.time()
    with _MODEL_HEALTH_LOCK:
        cached = _MODEL_HEALTH_CACHE.get(role)
        if cached and now - float(cached.get("cached_at_epoch") or 0) < _MODEL_HEALTH_TTL_SEC:
            return dict(cached.get("value") or {})
    value = lm_studio.select_available_model(
        role, fallback_roles=fallback_roles,
        experiment_id=experiment_id, purpose="idea_generator_health_gate",
    )
    with _MODEL_HEALTH_LOCK:
        _MODEL_HEALTH_CACHE[role] = {"cached_at_epoch": now, "value": dict(value)}
    return value


def reset_runtime_caches_for_tests() -> None:
    with _MODEL_HEALTH_LOCK:
        _MODEL_HEALTH_CACHE.clear()


def _bail_if_cancelled(experiment_id: str) -> bool:
    if runner.is_cancelled(experiment_id):
        try:
            registry.transition_status(
                experiment_id, "cancelled", reason="user cancelled"
            )
        except Exception:
            pass
        return True
    return False


def _checkpoint(experiment_id: str, stage: str) -> Optional[List[Dict[str, Any]]]:
    """Bail on cancel; otherwise pull pending operator notes for the next stage.

    Returns ``None`` if cancelled (caller must return), else the list of notes
    that were applied (may be empty).
    """
    if _bail_if_cancelled(experiment_id):
        return None
    return operator_notes.apply_checkpoint(experiment_id, stage)


def choose_target_root(user_pref: Optional[str], existing: List[Dict[str, Any]]) -> str:
    if user_pref:
        return user_pref.upper()
    by_root: Dict[str, int] = {r: 0 for r in INSTRUMENT_UNIVERSE}
    for e in existing:
        r = e.get("target_root")
        if r in by_root:
            by_root[r] += 1
    return min(by_root.items(), key=lambda kv: kv[1])[0]


def choose_capital(user_capital: Optional[float]) -> float:
    if user_capital and user_capital > 0:
        return float(user_capital)
    return 5000.0


def preflight_memory(
    target_root: str,
    experiment_id: str,
    *,
    user_goal: str = "",
    goal_constraints: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
    allow_local_models: bool = True,
) -> Dict[str, Any]:
    scan = user_research.scan()
    excerpts: List[Dict[str, str]] = []
    for rel in scan.get("new", []) + scan.get("changed", []):
        text, _ = user_research.read_file(rel, max_bytes=8000)
        if text:
            excerpts.append({"rel_path": rel, "snippet": text[:2000]})
    if not excerpts:
        for meta in user_research.all_files()[:5]:
            text, _ = user_research.read_file(meta["rel_path"], max_bytes=8000)
            if text:
                excerpts.append({"rel_path": meta["rel_path"], "snippet": text[:2000]})

    rejected_patterns = errors.top_repeated_patterns(threshold=2)
    similar_rejected = [
        e["experiment_id"] for e in registry.list_experiments(target_root=target_root)
        if e.get("status") == "rejected"
    ][:10]

    knowledge_context = knowledge.build_context(
        target_root,
        user_goal=user_goal,
        goal_constraints=goal_constraints or {},
        experiment_id=experiment_id,
    )
    if not knowledge_context.get("prompt_context"):
        raise RuntimeError("knowledge_context generation failed")

    model_health: Dict[str, Any] = {}
    if use_llm and allow_local_models:
        try:
            model_health["idea_generator"] = _cached_model_health(
                "judge", fallback_roles=["strategy_researcher", "fast_assistant"],
                experiment_id=experiment_id,
            )
        except Exception as e:  # noqa: BLE001
            model_health["idea_generator"] = {
                "ok": False,
                "primary_role": "judge",
                "selected_role": None,
                "selected_model": None,
                "error": str(e),
                "checked_via": "chat/completions",
            }

    return {
        "scanned_at_utc": scan.get("scanned_at_utc"),
        "user_research_files_read": [ex["rel_path"] for ex in excerpts],
        "user_research_excerpts": excerpts,
        "rejected_patterns": rejected_patterns,
        "similar_rejected": similar_rejected,
        "similar_demo_mismatch": [],
        "similar_compile_fails": [],
        "knowledge_context_path": knowledge_context.get("path"),
        "knowledge_sources_read": [s.get("rel_path") for s in knowledge_context.get("source_refs", [])],
        "knowledge_prompt_context": knowledge_context.get("prompt_context", ""),
        "reference_examples": knowledge_context.get("reference_examples", []),
        "reference_shortlist": knowledge_context.get("reference_shortlist", []),
        "project_strategy_examples": knowledge_context.get("project_strategy_examples", []),
        "goal_constraints": goal_constraints or {},
        "model_health": model_health,
    }


def choose_hypothesis(
    target_root: str,
    intake: Dict[str, Any],
    experiment_id: str,
    *,
    use_llm: bool = True,
    cancel_event: Optional[threading.Event] = None,
    operator_notes_block: str = "",
    allow_paid_agents: bool = True,
    allow_local_models: bool = True,
) -> Dict[str, Any]:
    constraints = intake.get("goal_constraints") or {}
    research_family = str(constraints.get("strategy_family") or "").strip()
    avoided_families = {
        str(value).strip().lower()
        for value in (intake.get("avoid_families") or constraints.get("avoid_families") or [])
        if str(value).strip()
    }
    requested_pattern = constraints.get("pattern")
    shortlist = list(intake.get("reference_shortlist") or [])
    if avoided_families:
        shortlist = [
            row for row in shortlist
            if str(row.get("family") or "").strip().lower() not in avoided_families
        ]
    preferred_ref = shortlist[0] if shortlist else {}
    if research_family:
        fallback_family = research_family
        fallback_hypothesis = (
            f"Проверить следующую самостоятельную торговую гипотезу семьи {research_family} "
            f"на {target_root}, сохраняя цели активного исследования, явный рыночный режим, "
            "подтверждение входа и экономику после комиссии."
        )
    elif requested_pattern:
        fallback_family = str(requested_pattern)
        fallback_hypothesis = (
            f"Внутридневная схема {requested_pattern} на {target_root}: строгая проверка сигналов, "
            "подтверждение направления, низкая частота сделок и фильтры после комиссии."
        )
    elif target_root == "MNQ":
        fallback_family = str(preferred_ref.get("family") or "SessionLiquidityReversal")
        fallback_hypothesis = (
            f"Адаптировать {preferred_ref.get('reference_id') or 'утвержденный список референсов'} "
            f"в режимную схему {fallback_family} для MNQ. Нужны явный рыночный режим, "
            "подтверждение входа и экономика сделки выше комиссии; не использовать generic breakout."
        )
    else:
        fallback_family = "SessionLiquidityReversal"
        fallback_hypothesis = (
            f"Внутридневной разворот сессионной ликвидности на {target_root}: именованный режим, "
            "подтверждение failed-auction, ограничение сделок в день, фиксированный риск-каркас "
            "и оценка результата после комиссии."
        )
    max_trades = 2 if constraints.get("trade_frequency") == "lower" else 3
    fallback = {
        "hypothesis": fallback_hypothesis,
        "family": fallback_family,
        "lane": "research",
        "parameters": {
            "Quantity": 1,
            "StopLossTicks": 20,
            "ProfitTargetTicks": 34,
            "MaxDailyLoss": 400,
            "MaxTradesPerDay": max_trades,
            "BreakoutLookback": random.choice([30, 40, 50, 60]),
            "RoundTurnCommission": 1.90,
            "SlippageTicks": 1,
            "SessionStartTimePT": 63000,
            "SessionEndTimePT": 123000,
        },
        "_source": "fallback",
        "reference_id": preferred_ref.get("reference_id"),
        "market_regime": "требуется явный рыночный режим",
        "entry_trigger": "требуется подтверждение из выбранного референса",
        "why_not_generic": "generic breakout запрещен без режима и подтверждения",
    }
    if not use_llm:
        return fallback
    sys_prompt = (
        "/no_think\nYou are a strict trading research spec writer. Output ONLY JSON with "
        "keys: reference_id, hypothesis, family, market_regime, entry_trigger, "
        "exit_economics, why_not_generic, expected_trades_per_day, parameters. "
        "Write all human-readable JSON string values in Russian. Keep JSON keys, "
        "reference IDs, parameter names, and metric names in English. "
        "Do not expose hidden chain-of-thought; provide concise final reasoning only. "
        "Choose exactly one reference_id from the approved shortlist. WEX and "
        "rejected AI-CELL rows are negative evidence, not code templates. "
        "Reject generic breakout/crossover ideas that lack a named regime and "
        "confirmation. Keep hypothesis under 80 words and parameters to at most "
        "8 actionable scalar values."
    )
    # Keep a genuinely stable prefix before the marker.  Experiment memory,
    # ids, notes and target-specific fields belong after it; putting them in
    # the prefix made every cache key unique during the previous night run.
    user_prompt = (
        "Prepare one contract-valid intraday strategy hypothesis from approved research. "
        "Use an explicit market regime, confirmation and after-cost exit economics.\n"
        f"{lm_studio.prompt_cache_marker()}\n\n"
        f"{intake.get('knowledge_prompt_context', '')}\n\n"
        f"Approved references: {shortlist}\n"
        f"Avoid recent failure patterns: {intake.get('rejected_patterns', [])[:5]}\n"
        f"User research files just read: {intake.get('user_research_files_read', [])}\n\n"
        f"Target root: {target_root}\n"
        f"User goal constraints: {constraints}\n"
        f"Forbidden families for this staged draft: {sorted(avoided_families)}\n"
        "Propose one structurally distinct intraday hypothesis. State why it is "
        "not another generic breakout and target 0.2-3.0 trades/day. "
        "All explanations must be in Russian."
    )
    if operator_notes_block:
        user_prompt += "\n\nOperator notes for this dynamic request:\n" + operator_notes_block
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    def _validated_response(resp: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
        parsed = lm_studio.extract_json_block(resp.get("content", ""))
        if not isinstance(parsed, dict):
            activity.log(
                experiment_id, "generate", "hypothesis_contract_rejected", level="warn",
                provider=source,
                response_summary=str(parsed)[:300],
            )
            return None
        allowed_refs = {
            str(row.get("reference_id")) for row in shortlist if row.get("reference_id")
        }
        supplied_ref = str(parsed.get("reference_id") or "")
        if allowed_refs and supplied_ref not in allowed_refs and preferred_ref.get("reference_id"):
            parsed["reference_id"] = str(preferred_ref["reference_id"])
            activity.log(
                experiment_id, "generate", "hypothesis_reference_normalized",
                level="info", supplied_reference=supplied_ref[:120],
                selected_reference=parsed["reference_id"],
            )
        family_text = research_family or str(parsed.get("family") or "")
        if research_family:
            parsed["family"] = research_family
        if family_text.strip().lower() in avoided_families:
            activity.log(
                experiment_id, "generate", "hypothesis_family_rejected", level="warn",
                provider=source, family=family_text,
                avoided_families=sorted(avoided_families),
            )
            return None
        generic_without_regime = (
            any(word in family_text.lower() for word in ("generic", "pricebreakout"))
            or (
                "breakout" in family_text.lower()
                and not str(parsed.get("market_regime") or "").strip()
            )
        )
        ref_ok = not allowed_refs or str(parsed.get("reference_id") or "") in allowed_refs
        if (
            parsed.get("hypothesis")
            and ref_ok
            and not generic_without_regime
            and parsed.get("market_regime")
            and parsed.get("entry_trigger")
            and parsed.get("why_not_generic")
        ):
            params = parsed.get("parameters") or {}
            if not isinstance(params, dict):
                activity.log(
                    experiment_id, "generate", "hypothesis_contract_rejected", level="warn",
                    provider=source, contract_error="parameters_must_be_object",
                    received_type=type(params).__name__,
                )
                return None
            merged = {**fallback["parameters"], **{k: params[k] for k in params if isinstance(params[k], (int, float, str))}}
            # The model controls signal/risk tuning, never the execution
            # contract. Session, quantity, commission and slippage are fixed.
            merged.pop("SessionStartPT", None)
            merged.pop("SessionEndPT", None)
            merged["SessionStartTimePT"] = 63000
            merged["SessionEndTimePT"] = 123000
            merged["Quantity"] = 1
            merged["RoundTurnCommission"] = 1.90
            merged["SlippageTicks"] = 1
            for key, lo, hi, default in (
                ("StopLossTicks", 6, 80, 20),
                ("ProfitTargetTicks", 8, 160, 34),
                ("MaxDailyLoss", 100, 750, 400),
                ("MaxTradesPerDay", 1, 3, max_trades),
                ("BreakoutLookback", 5, 100, 30),
            ):
                try:
                    merged[key] = max(lo, min(hi, int(float(merged.get(key, default)))))
                except (TypeError, ValueError):
                    merged[key] = default
            activity.log(experiment_id, "generate", "hypothesis_response", level="success",
                         model=resp.get("model"), provider=resp.get("provider") or source,
                         cost_usd=resp.get("cost_usd"),
                         response_summary=str(parsed.get("hypothesis"))[:200])
            return {
                "hypothesis": str(parsed["hypothesis"])[:500],
                "family": parsed.get("family") or fallback["family"],
                "lane": "research",
                "parameters": merged,
                "_source": source,
                "_model": resp.get("actual_model") or resp.get("model"),
                "_provider": resp.get("provider") or source,
                "reference_id": parsed.get("reference_id"),
                "market_regime": parsed.get("market_regime"),
                "entry_trigger": parsed.get("entry_trigger"),
                "exit_economics": parsed.get("exit_economics"),
                "why_not_generic": parsed.get("why_not_generic"),
                "expected_trades_per_day": parsed.get("expected_trades_per_day"),
            }
        activity.log(
            experiment_id, "generate", "hypothesis_contract_rejected", level="warn",
            provider=source,
            response_summary=str(parsed)[:300],
        )
        return None

    model_gate = (intake.get("model_health") or {}).get("idea_generator") or {}
    selected_role = model_gate.get("selected_role") or "judge"
    selected_model = model_gate.get("selected_model")
    local_failure = ""
    # Cost-aware order: free external rotation -> local model -> paid fallback.
    # A paid Azure/DeepSeek request must not be the default for every idea.
    try:
        external_resp = agent_router.invoke_messages(
            "hypothesis", messages, max_output_tokens=700, timeout=llm_timeouts.ANALYSIS,
            purpose="hypothesis_free_primary", allow_paid=False,
        )
        candidate = _validated_response(external_resp, "external_free_primary")
        if candidate:
            return candidate
        local_failure = "external_hypothesis_contract_rejected"
    except agent_router.AgentRouterError as exc:
        local_failure = "free_external_hypothesis_request_failed"
        activity.log(
            experiment_id, "generate", "hypothesis_external_failed",
            level="warn", error=str(exc)[:300],
        )
    if not allow_local_models:
        local_failure = "local_models_disabled_by_owner"
    elif model_gate and not model_gate.get("ok"):
        local_failure = "local_model_health_failed"
        activity.log(
            experiment_id, "generate", "hypothesis_model_health_failed",
            level="warn", role="judge", response_summary=str(model_gate)[:300],
        )
    else:
        activity.log(experiment_id, "generate", "hypothesis_prompt", level="info",
                     role=selected_role, model=selected_model,
                     prompt_preview="Propose one structurally distinct intraday hypothesis in Russian.",
                     prompt_preview_ru="Сформировать одну структурно отличающуюся внутридневную гипотезу на русском языке.")
        try:
            local_resp = lm_studio.chat(
                role=selected_role, messages=messages,
                temperature=0.3, max_tokens=500, experiment_id=experiment_id,
                purpose="hypothesis", timeout=lm_studio.DEFAULT_JUDGE_TIMEOUT,
                cancel_event=cancel_event, model_override=selected_model,
            )
            candidate = _validated_response(local_resp, "local_llm")
            if candidate:
                return candidate
            local_failure = "local_hypothesis_contract_rejected"
        except lm_studio.LMStudioCancelled:
            raise
        except lm_studio.LMStudioError as exc:
            local_failure = "local_hypothesis_request_failed"
            activity.log(experiment_id, "generate", "hypothesis_lm_failed", level="warn", error=str(exc))

    if allow_paid_agents:
        try:
            paid_resp = agent_router.invoke_messages(
                "hypothesis", messages, max_output_tokens=700, timeout=llm_timeouts.ANALYSIS,
                purpose="hypothesis_paid_fallback", allow_paid=True,
            )
            candidate = _validated_response(paid_resp, "external_paid_fallback")
            if candidate:
                return candidate
            local_failure = "paid_hypothesis_contract_rejected"
        except agent_router.AgentRouterError as exc:
            activity.log(
                experiment_id, "generate", "hypothesis_external_failed",
                level="warn", fallback="paid", error=str(exc)[:300],
            )

    try:
        if not allow_paid_agents:
            raise cloud_agents.CloudAgentBlocked("paid cloud fallback disabled for this mission")
        cloud_resp = cloud_agents.invoke(
            "hypothesis_fallback", messages,
            fallback_reason=local_failure or "local_hypothesis_failed",
            experiment_id=experiment_id, purpose="hypothesis_fallback",
            temperature=0.2, max_tokens=500, timeout=llm_timeouts.ANALYSIS,
        )
        activity.log(
            experiment_id, "generate", "hypothesis_cloud_fallback", level="warn",
            role="hypothesis_fallback", provider=cloud_resp.get("provider"),
            model=cloud_resp.get("model"), cost_usd=cloud_resp.get("cost_usd"),
            reason=local_failure,
        )
        candidate = _validated_response(cloud_resp, "cloud_fallback")
        if candidate:
            return candidate
    except cloud_agents.CloudAgentBlocked as exc:
        activity.log(
            experiment_id, "generate", "hypothesis_cloud_blocked", level="info",
            role="hypothesis_fallback", reason=str(exc)[:300],
        )
    except cloud_agents.CloudAgentsError as exc:
        activity.log(
            experiment_id, "generate", "hypothesis_cloud_failed", level="warn",
            role="hypothesis_fallback", error=str(exc)[:300],
        )
    activity.log(experiment_id, "generate", "hypothesis_fallback", level="info",
                 response_summary=fallback["hypothesis"][:200])
    return fallback


def _default_period() -> Dict[str, str]:
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=180)
    return {"from_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "to_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ")}


def _catalog_contracts(target_root: str) -> List[Dict[str, Any]]:
    """Return dated contracts with minute data, newest data first."""
    try:
        from .. import jobqueue
        catalog = jobqueue.read_instruments_catalog() or {}
    except Exception:
        return []
    rows = [
        dict(row) for row in (catalog.get("instruments") or [])
        if isinstance(row, dict)
        and str(row.get("root") or "").upper() == target_root.upper()
        and bool(row.get("has_minute_data"))
        and row.get("data_first") and row.get("data_last")
    ]
    rows.sort(
        key=lambda row: (
            str(row.get("data_last") or ""),
            str(row.get("data_first") or ""),
            str(row.get("instrument") or ""),
        ),
        reverse=True,
    )
    return rows


def _backtest_instrument(target_root: str, args: Dict[str, Any]) -> str:
    explicit = args.get("backtest_instrument") or args.get("instrument")
    if explicit:
        return str(explicit)
    candidates = _catalog_contracts(target_root)
    if candidates:
        # Futures liquidity rolls before the previous contract accumulates a
        # long history.  Selecting only "mature" rows chose expired 06-26
        # contracts in July.  The row with the newest actual minute bar is the
        # honest current-contract choice.
        return str(candidates[0]["instrument"])
    return str(DEFAULT_INSTRUMENT_BY_ROOT.get(target_root, target_root))


def _bounded_period_for_instrument(
    instrument: str,
    requested_start: datetime,
    requested_end: datetime,
) -> Dict[str, Any]:
    """Clamp a requested period to catalog-proven minute-data coverage."""
    root = str(instrument).split()[0].upper()
    row = next(
        (item for item in _catalog_contracts(root)
         if str(item.get("instrument") or "") == str(instrument)),
        None,
    )
    if not row:
        return {
            "ok": False, "instrument": instrument,
            "reason": "instrument_missing_from_minute_data_catalog",
        }
    try:
        first = datetime.fromisoformat(str(row["data_first"])).replace(tzinfo=timezone.utc)
        # Catalog dates are inclusive; job periods use an exclusive upper
        # boundary, therefore include the last catalog day with +1 day.
        last_exclusive = (
            datetime.fromisoformat(str(row["data_last"])).replace(tzinfo=timezone.utc)
            + timedelta(days=1)
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "instrument": instrument, "reason": f"invalid_catalog_dates: {exc}"}
    start = max(requested_start, first)
    end = min(requested_end, last_exclusive)
    days = max(0.0, (end - start).total_seconds() / 86400.0)
    return {
        "ok": end > start,
        "instrument": instrument,
        "from_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "catalog_data_first": str(row.get("data_first") or ""),
        "catalog_data_last": str(row.get("data_last") or ""),
        "available_days": round(days, 2),
        "reason": "" if end > start else "requested_period_has_no_catalog_overlap",
    }


# ---------------------- public API ----------------------

def start_skeleton(args: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous: allocate ids and persist a draft experiment record."""
    user_goal = str(args.get("user_goal") or args.get("goal") or "").strip()
    goal_constraints = goal_parser.parse_user_goal(user_goal, args)
    if args.get("research_family_key"):
        goal_constraints["strategy_family"] = str(args.get("research_family_key"))[:80]
    if args.get("research_id"):
        goal_constraints["research_id"] = str(args.get("research_id"))[:80]
    user_pref_root = (
        args.get("user_pref_root") or args.get("target_root")
        or goal_constraints.get("target_root")
    )
    user_capital = (
        args.get("user_capital") or args.get("capital")
        or goal_constraints.get("capital")
    )
    existing = registry.list_experiments()
    target_root = choose_target_root(user_pref_root, existing)
    capital = choose_capital(float(user_capital) if user_capital not in (None, "") else None)

    skeleton = registry.new_experiment_skeleton(
        target_root=target_root, class_name="PENDING",
        hypothesis="", primary_capital=capital,
        parent_experiment_id=args.get("parent_experiment_id"),
    )
    skeleton["status"] = "draft"
    skeleton["rationale"] = f"user_goal={user_goal or 'auto'}"
    skeleton["user_goal"] = user_goal
    skeleton["allow_paid_agents"] = bool(args.get("allow_paid_agents", True))
    skeleton["allow_local_models"] = args.get("allow_local_models") is not False
    # Multi-user provenance is part of every experiment created from chat.
    # Legacy/local-owner runs keep these fields empty and remain compatible.
    skeleton["workspace_id"] = str(args.get("workspace_id") or "")[:96]
    try:
        skeleton["requested_by_user_id"] = int(args.get("user_id") or 0)
    except (TypeError, ValueError):
        skeleton["requested_by_user_id"] = 0
    skeleton["goal_constraints"] = goal_constraints
    skeleton["research_id"] = str(args.get("research_id") or "")[:80]
    skeleton["research_title"] = str(args.get("research_title") or "")[:180]
    skeleton["research_family_name"] = str(args.get("research_family_name") or "")[:180]
    skeleton["research_family_key"] = str(args.get("research_family_key") or "")[:80]
    skeleton["research_knowledge_ref"] = str(args.get("research_knowledge_ref") or "")[:260]
    skeleton["research_loop"] = {
        "mode": args.get("research_mode") or "single_cell",
        "run_id": args.get("research_run_id") or skeleton["experiment_id"],
        "attempt_index": int(args.get("research_attempt_index", 1)),
        "max_cells_per_run": int(args.get("max_cells_per_run", 1)),
        "stop_on_first_candidate": bool(args.get("stop_on_first_candidate", True)),
        "target_candidate_count": int(args.get("target_candidate_count", 1)),
    }
    registry.write_experiment(skeleton)
    activity.log(skeleton["experiment_id"], "intake", "skeleton_created",
                 level="info", target_root=target_root, capital=capital,
                 user_goal=user_goal[:160],
                 research_mode=skeleton["research_loop"]["mode"],
                 attempt_index=skeleton["research_loop"]["attempt_index"])
    return skeleton


def prepare_strategy_draft(args: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare the next hypothesis while NinjaTrader backtests another cell.

    This stage never writes NinjaScript, compiles, or submits a backtest.  It
    only allocates an AI sandbox experiment, loads research memory and prepares
    a contract-valid hypothesis for the sequential execution lane.
    """
    skeleton = start_skeleton(args)
    experiment_id = str(skeleton["experiment_id"])
    try:
        skeleton["status"] = "designing"
        skeleton["staged_pipeline"] = {
            "stage": "designing", "prepared_during_backtest": True,
            "source_experiment_id": args.get("staged_source_experiment_id"),
        }
        registry.write_experiment(skeleton)
        activity.log(
            experiment_id, "staged", "parallel_design_started", level="info",
            source_experiment_id=args.get("staged_source_experiment_id"),
        )
        user_goal = str(args.get("user_goal") or args.get("goal") or "")
        constraints = goal_parser.parse_user_goal(user_goal, args)
        if args.get("research_family_key"):
            constraints["strategy_family"] = str(args.get("research_family_key"))[:80]
        if args.get("research_id"):
            constraints["research_id"] = str(args.get("research_id"))[:80]
        constraints["avoid_families"] = [
            str(value).strip() for value in (args.get("avoid_families") or [])
            if str(value).strip()
        ]
        intake = preflight_memory(
            str(skeleton.get("target_root") or "MNQ"), experiment_id,
            user_goal=user_goal, goal_constraints=constraints,
            use_llm=bool(args.get("use_llm", True)),
        )
        intake["avoid_families"] = constraints["avoid_families"]
        hypothesis = choose_hypothesis(
            str(skeleton.get("target_root") or "MNQ"), intake, experiment_id,
            use_llm=bool(args.get("use_llm", True)),
            allow_paid_agents=bool(args.get("allow_paid_agents", True)),
        )
        skeleton = registry.read_experiment(experiment_id) or skeleton
        skeleton["memory_intake"].update({
            "user_research_files_read": intake.get("user_research_files_read", []),
            "similar_rejected": intake.get("similar_rejected", []),
            "similar_demo_mismatch": intake.get("similar_demo_mismatch", []),
            "similar_compile_fails": intake.get("similar_compile_fails", []),
            "knowledge_context_path": intake.get("knowledge_context_path"),
            "knowledge_sources_read": intake.get("knowledge_sources_read", []),
            "knowledge_prompt_context": intake.get("knowledge_prompt_context", ""),
            "reference_shortlist": intake.get("reference_shortlist", []),
            "goal_constraints": constraints,
            "model_health": intake.get("model_health", {}),
        })
        skeleton["prepared_hypothesis"] = hypothesis
        skeleton["hypothesis"] = hypothesis.get("hypothesis")
        skeleton["family"] = hypothesis.get("family")
        skeleton["lane"] = hypothesis.get("lane") or "research"
        skeleton["parameters"] = hypothesis.get("parameters") or {}
        skeleton["hypothesis_spec"] = {
            key: hypothesis.get(key) for key in (
                "reference_id", "market_regime", "entry_trigger", "exit_economics",
                "why_not_generic", "expected_trades_per_day",
            ) if hypothesis.get(key) is not None
        }
        skeleton["status"] = "draft_ready"
        skeleton["staged_pipeline"].update({
            "stage": "draft_ready", "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": hypothesis.get("_model"), "provider": hypothesis.get("_provider"),
        })
        registry.write_experiment(skeleton)
        activity.log(
            experiment_id, "staged", "parallel_design_ready", level="success",
            family=hypothesis.get("family"), model=hypothesis.get("_model"),
            provider=hypothesis.get("_provider"),
        )
        return skeleton
    except Exception as exc:
        failed = registry.read_experiment(experiment_id) or skeleton
        # A staged skeleton has no runnable class/source.  Keep the failure
        # evidence but archive it immediately so PENDING rows never look like
        # unfinished strategies in the laboratory.
        failed["status_before_archive"] = "pipeline_failed"
        failed["status"] = "archived"
        failed["archive_reason"] = f"staged design failed: {exc}"
        failed["verdict"] = {
            "outcome": "reject", "reasons": [f"staged design failed: {exc}"],
            "rejection_code": "STAGED_DESIGN_FAILED", "structural": False,
        }
        failed["staged_pipeline"] = {
            **dict(failed.get("staged_pipeline") or {}),
            "stage": "failed", "error": str(exc)[:500],
            "error_type": type(exc).__name__,
        }
        registry.write_experiment(failed)
        activity.log(experiment_id, "staged", "parallel_design_failed", level="error", error=str(exc)[:300])
        return failed


def run_pipeline(experiment_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Slow background phase. Caller owns the thread.

    Honest status transitions:
        draft -> generating -> generated -> validating
        -> validation_failed                                 (TERMINAL)
        -> awaiting_compile -> compile_failed                (TERMINAL)
                            -> awaiting_compile_timeout      (TERMINAL)
                            -> catalog_visible -> backtesting
        -> backtest_failed                                   (TERMINAL)

    Note: skip_compile leaves the experiment at ``awaiting_compile`` (NOT
    ``ready``). skip_backtest leaves it at ``catalog_visible``. There is no
    fake ``ready`` terminal state any more.
    """
    skeleton = registry.read_experiment(experiment_id)
    if skeleton is None:
        raise ValueError(f"experiment not found: {experiment_id}")

    prepared_hypothesis = skeleton.get("prepared_hypothesis") if isinstance(skeleton.get("prepared_hypothesis"), dict) else None
    target_root = skeleton["target_root"]
    user_goal = str(skeleton.get("user_goal") or args.get("user_goal") or args.get("goal") or "")
    goal_constraints = skeleton.get("goal_constraints") or goal_parser.parse_user_goal(user_goal, args)
    skip_compile = bool(args.get("skip_compile", False))
    skip_backtest = bool(args.get("skip_backtest", False))
    dry_run = bool(args.get("dry_run", False))
    verify_poll_sec = int(args.get("verify_poll_sec", 0))
    use_llm = bool(args.get("use_llm", True))
    allow_template_fallback = bool(args.get("allow_template_fallback", False))
    allow_paid_agents = bool(skeleton.get("allow_paid_agents", args.get("allow_paid_agents", True)))
    allow_local_models = skeleton.get("allow_local_models", args.get("allow_local_models", True)) is not False
    cancel_event = runner.cancel_event_for(experiment_id)
    max_compile_attempts = max(
        1,
        min(10, int(args.get("max_compile_fix_attempts_per_cell") or MAX_COMPILE_ATTEMPTS)),
    )
    mutation_context = str(skeleton.get("pending_mutation_context") or "").strip()
    is_mutation_iteration = bool(
        mutation_context and int(skeleton.get("current_iteration") or 1) > 1
    )

    # --- intake / memory ---
    if _bail_if_cancelled(experiment_id):
        return registry.read_experiment(experiment_id)
    registry.transition_status(experiment_id, "generating", reason="entering intake")
    intake = preflight_memory(
        target_root,
        experiment_id,
        user_goal=user_goal,
        goal_constraints=goal_constraints,
        use_llm=use_llm,
        allow_local_models=allow_local_models,
    )
    if mutation_context:
        intake["knowledge_prompt_context"] = (
            str(intake.get("knowledge_prompt_context") or "")
            + "\n\n"
            + mutation_context
        )
    skeleton = registry.read_experiment(experiment_id)
    skeleton["memory_intake"].update({
        "user_research_files_read": intake["user_research_files_read"],
        "similar_rejected": intake["similar_rejected"],
        "similar_demo_mismatch": intake["similar_demo_mismatch"],
        "similar_compile_fails": intake["similar_compile_fails"],
        "knowledge_context_path": intake.get("knowledge_context_path"),
        "knowledge_sources_read": intake.get("knowledge_sources_read", []),
        "knowledge_prompt_context": intake.get("knowledge_prompt_context", ""),
        "reference_examples": intake.get("reference_examples", []),
        "reference_shortlist": intake.get("reference_shortlist", []),
        "project_strategy_examples": intake.get("project_strategy_examples", []),
        "goal_constraints": goal_constraints,
        "model_health": intake.get("model_health", {}),
    })
    skeleton["knowledge_context"] = {
        "required": True,
        "path": intake.get("knowledge_context_path"),
        "sources_read": intake.get("knowledge_sources_read", []),
        "built": bool(intake.get("knowledge_prompt_context")),
    }
    skeleton["goal_constraints"] = goal_constraints
    skeleton["user_goal"] = user_goal
    skeleton["user_research_refs"] = intake["user_research_files_read"]
    activity.log(experiment_id, "intake", "memory_loaded", level="info",
                 user_research_files=len(intake["user_research_files_read"]),
                 similar_rejected=len(intake["similar_rejected"]),
                 knowledge_sources=len(intake.get("knowledge_sources_read", [])),
                 knowledge_context_path=str(intake.get("knowledge_context_path") or ""))

    # --- hypothesis (judge checkpoint) ---
    judge_notes = _checkpoint(experiment_id, "judge")
    if judge_notes is None:
        return registry.read_experiment(experiment_id)
    with heartbeat(experiment_id, "generate", "awaiting judge model", every_sec=10):
        try:
            if prepared_hypothesis and prepared_hypothesis.get("hypothesis"):
                hypo = dict(prepared_hypothesis)
                activity.log(
                    experiment_id, "staged", "parallel_design_reused", level="success",
                    family=hypo.get("family"), model=hypo.get("_model"),
                )
            else:
                hypo = choose_hypothesis(
                    target_root, intake, experiment_id, use_llm=use_llm,
                    cancel_event=cancel_event,
                    operator_notes_block=operator_notes.render_entries(judge_notes),
                    allow_paid_agents=allow_paid_agents,
                    allow_local_models=allow_local_models,
                )
        except lm_studio.LMStudioCancelled:
            registry.transition_status(experiment_id, "cancelled", reason="cancelled in judge stage")
            return registry.read_experiment(experiment_id)
    skeleton["hypothesis"] = hypo["hypothesis"]
    skeleton["family"] = hypo["family"]
    skeleton["lane"] = hypo["lane"]
    skeleton["parameters"] = hypo["parameters"]
    skeleton["hypothesis_spec"] = {
        key: hypo.get(key)
        for key in (
            "reference_id", "market_regime", "entry_trigger", "exit_economics",
            "why_not_generic", "expected_trades_per_day",
        )
        if hypo.get(key) is not None
    }
    idea_gate = (intake.get("model_health") or {}).get("idea_generator") or {}
    prior_model_chain = list(skeleton.get("model_chain") or [])
    model_iteration = int(skeleton.get("current_iteration") or args.get("iteration_idx") or 1)
    if hypo.get("_model") or hypo.get("_provider"):
        prior_model_chain.append({
            "role": "idea_generator",
            "selected_model": hypo.get("_model") or "unknown",
            "provider": hypo.get("_provider") or hypo.get("_source"),
            "path": hypo.get("_source"),
            "iteration": model_iteration,
            "recorded_at_utc": _now(),
        })
    elif idea_gate:
        prior_model_chain.append({
            "role": "idea_generator",
            "configured_primary": idea_gate.get("primary_model"),
            "selected_model": idea_gate.get("selected_model"),
            "fallback_used": bool(idea_gate.get("fallback_used")),
            "primary_model_failed": bool(idea_gate.get("primary_model_failed")),
            "checked_via": idea_gate.get("checked_via"),
            "iteration": model_iteration,
            "recorded_at_utc": _now(),
        })
    skeleton["model_chain"] = prior_model_chain

    class_name = (
        str(skeleton.get("class_name"))
        if is_mutation_iteration and skeleton.get("class_name") not in (None, "", "PENDING")
        else generator.class_name_for(
            target_root, skeleton["ai_cell_id"], family=hypo["family"]
        )
    )
    skeleton["class_name"] = class_name
    skeleton["risk_profile"] = {
        "stop_loss_ticks": hypo["parameters"]["StopLossTicks"],
        "profit_target_ticks": hypo["parameters"]["ProfitTargetTicks"],
        "max_daily_loss": hypo["parameters"]["MaxDailyLoss"],
        "max_trades_per_day": hypo["parameters"].get("MaxTradesPerDay", 3),
        "round_turn_commission": hypo["parameters"].get("RoundTurnCommission", 1.90),
        "slippage_ticks": hypo["parameters"].get("SlippageTicks", 1),
        "force_flat_at_session_end": True,
        "no_overnight": True,
    }
    skeleton["session_template"] = "CME US Index Futures RTH"
    registry.write_experiment(skeleton)
    activity.log(experiment_id, "generate", "class_assigned", level="info",
                 class_name=class_name, family=hypo["family"])

    if dry_run:
        registry.transition_status(experiment_id, "generated", reason="dry_run only")
        return skeleton

    # --- generate + validate (static-first; bad code is NEVER written) ---
    coder_notes = _checkpoint(experiment_id, "coder")
    if coder_notes is None:
        return registry.read_experiment(experiment_id)
    activity.log(experiment_id, "generate", "coder_invoke", level="info",
                 role="deterministic_nt8_shell", purpose="render_strategy")
    notes_block = operator_notes.render_entries(coder_notes)
    if bool(args.get("deterministic_risk_shell", True)):
        source, report, gen_meta = generator.render_deterministic_strategy(
            class_name=class_name,
            ai_cell_id=skeleton["ai_cell_id"],
            instrument=target_root,
            family=str(hypo.get("family") or ""),
            hypothesis=str(hypo.get("hypothesis") or ""),
            reference_id=str(hypo.get("reference_id") or ""),
            parameters=hypo["parameters"],
        )
    else:
        try:
            source, report, gen_meta = generator.generate(
                class_name=class_name,
                ai_cell_id=skeleton["ai_cell_id"],
                instrument=target_root,
                hypothesis=hypo["hypothesis"],
                parameters=hypo["parameters"],
                memory_intake=skeleton["memory_intake"],
                user_research_excerpts=intake["user_research_excerpts"],
                rejected_patterns=intake["rejected_patterns"],
                experiment_id=experiment_id,
                use_llm=use_llm,
                mode="initial",
                operator_notes=notes_block,
                cancel_event=cancel_event,
                allow_template_fallback=allow_template_fallback,
            )
        except lm_studio.LMStudioCancelled:
            registry.transition_status(experiment_id, "cancelled", reason="cancelled in coder stage")
            return registry.read_experiment(experiment_id)
        except lm_studio.LMStudioUnavailable as exc:
            errors.log_infra_fail(experiment_id, "generate", str(exc))
            activity.log(experiment_id, "generate", "blocked_lm_studio", level="error",
                         error=str(exc)[:300])
            registry.transition_status(
                experiment_id, "blocked_lm_studio",
                reason="LM Studio coder unavailable and template fallback disabled",
                extra={"verdict": {"outcome": "blocked", "reasons": [str(exc)[:400]],
                                   "rejection_code": "BLOCKED_LM_STUDIO", "structural": False},
                       "lm_studio_block": exc.preflight},
            )
            return registry.read_experiment(experiment_id)
        except lm_studio.LMStudioGenerationFailed as exc:
            activity.log(
                experiment_id, "generate", "generation_failed",
                level="error", error=str(exc)[:300],
            )
            errors.log_error(
                experiment_id, "generate", "generation_no_csharp",
                str(exc), severity="error", class_name=class_name,
                target_root=target_root,
            )
            registry.transition_status(
                experiment_id,
                "validation_failed",
                reason="coder returned no contract-valid C#",
                extra={"verdict": {
                    "outcome": "reject",
                    "reasons": [str(exc)[:400]],
                    "rejection_code": "GENERATION_NO_CSHARP",
                    "structural": True,
                }},
            )
            return registry.read_experiment(experiment_id)
    model_chain = list(skeleton.get("model_chain") or [])
    if gen_meta.get("model"):
        model_chain.append({
            "role": gen_meta.get("role") or "coder",
            "selected_model": gen_meta.get("model"),
            "path": gen_meta.get("path"),
            "iteration": model_iteration,
            "recorded_at_utc": _now(),
        })
    elif gen_meta.get("path"):
        model_chain.append({
            "role": gen_meta.get("role") or "coder",
            "selected_model": (
                "deterministic_renderer"
                if gen_meta.get("path") == "deterministic_family_renderer"
                else "fallback_template"
            ),
            "path": gen_meta.get("path"),
            "iteration": model_iteration,
            "recorded_at_utc": _now(),
        })
    skeleton["model_chain"] = model_chain
    skeleton["strategy_source"]["sha256"] = gen_meta.get("sha256", "")
    skeleton.pop("pending_mutation_context", None)
    registry.write_experiment(skeleton)
    activity.log(experiment_id, "generate", "coder_done", level="info",
                 role=gen_meta.get("role"),
                 model=gen_meta.get("model") or (
                     "deterministic_renderer"
                     if gen_meta.get("path") == "deterministic_family_renderer"
                     else "fallback"
                 ),
                 path=gen_meta.get("path"),
                 bytes=gen_meta.get("bytes"), attempts=gen_meta.get("attempts"),
                 sha=str(gen_meta.get("sha256", ""))[:16])

    if _bail_if_cancelled(experiment_id):
        return registry.read_experiment(experiment_id)

    if not report.ok:
        for v in report.violations:
            errors.log_error(experiment_id, "validate", "static_validation", v, severity="error",
                             class_name=class_name, target_root=target_root)
        activity.log(experiment_id, "validate", "rejected_static", level="error",
                     violations=str(report.violations)[:200])
        errors.log_rejection(experiment_id, "STATIC_VALIDATION_FAIL", report.violations, structural=True)
        registry.transition_status(
            experiment_id, "validation_failed",
            reason="static validator blocked source",
            extra={"verdict": {"outcome": "reject", "reasons": list(report.violations),
                               "rejection_code": "STATIC_VALIDATION_FAIL", "structural": True}},
        )
        return registry.read_experiment(experiment_id)

    activity.log(experiment_id, "validate", "ok", level="success")

    # --- write to sandbox ---
    # NinjaTrader may auto-compile immediately when the .cs file changes.
    # Capture the DLL state before writing or that fast successful compile is
    # mistaken for a five-minute timeout.
    compile_baseline = compile_pipeline.capture_dll_baseline()
    compile_baseline_ts = datetime.now(timezone.utc)
    sandbox_path, mirror_path = generator.write_to_sandbox(class_name, source)
    skeleton = registry.read_experiment(experiment_id)
    skeleton["strategy_source"]["sandbox_path"] = str(sandbox_path)
    skeleton["strategy_source"]["mirror_path"] = str(mirror_path)
    skeleton["strategy_source"]["files"] = [str(sandbox_path)]
    registry.write_experiment(skeleton)
    activity.log(experiment_id, "write", "sandbox_written", level="success",
                 sandbox_path=str(sandbox_path), mirror_path=str(mirror_path))
    current_source = source

    # --- compile chain ---
    if skip_compile:
        registry.transition_status(
            experiment_id, "awaiting_compile",
            reason="skip_compile=true, waiting on manual F5",
            extra={"compile": {"attempts": int(skeleton["compile"].get("attempts", 0)),
                               "last_status": "awaiting_manual_compile",
                               "errors": skeleton["compile"].get("errors", [])}},
        )
        activity.log(experiment_id, "compile", "skipped", level="info",
                     hint=f"Press F5 in NinjaScript Editor to build {class_name}")
        return registry.read_experiment(experiment_id)

    # This is not a model prompt. Keep live notes pending for a real model
    # checkpoint such as compile autofix.
    if _bail_if_cancelled(experiment_id):
        return registry.read_experiment(experiment_id)

    compile_ok = False
    last_compile_res: Dict[str, Any] = {}
    for attempt in range(max_compile_attempts):
        if _bail_if_cancelled(experiment_id):
            return registry.read_experiment(experiment_id)
        registry.transition_status(
            experiment_id, "awaiting_compile",
            reason=f"compile attempt {attempt + 1}",
        )
        activity.log(experiment_id, "compile", "awaiting_nt_compile", level="info",
                     sandbox_path=str(sandbox_path), class_name=class_name,
                     attempt=attempt + 1)
        baseline_ts = compile_baseline_ts
        with heartbeat(experiment_id, "compile", "waiting for NT compile / dll change", every_sec=15):
            compile_res = compile_pipeline.run_compile_chain(
                experiment_id=experiment_id, class_name=class_name,
                request_restart_flag=False, verify_poll_sec=verify_poll_sec,
                baseline_mtime=compile_baseline,
            )
        last_compile_res = compile_res
        skeleton = registry.read_experiment(experiment_id)
        skeleton["compile"]["attempts"] = int(skeleton["compile"].get("attempts", 0)) + 1
        skeleton["compile"]["last_status"] = "ok" if compile_res.get("ok") else "blocker"
        skeleton["catalog"]["visible_in_whitelist"] = compile_res.get("in_whitelist", False)
        skeleton["catalog"]["visible_in_catalog"] = compile_res.get("in_catalog", False)
        skeleton["catalog"]["last_checked_utc"] = _now()
        registry.write_experiment(skeleton)
        if compile_res.get("ok"):
            compile_ok = True
            break
        errs: List[Dict[str, Any]] = list(compile_res.get("errors") or [])
        if compile_res.get("timed_out_dll"):
            if not errs:
                errs = compile_errors.read_since(baseline_ts, class_name=class_name)
            if errs:
                compile_errors.mirror_to_registry(experiment_id, class_name, errs)
                activity.log(
                    experiment_id, "compile", "timeout_with_errors_collected",
                    level="error", count=len(errs), attempt=attempt + 1,
                    sample=str([(e.get("code"), (e.get("message") or "")[:80]) for e in errs[:3]])[:200],
                )
            else:
                activity.log(experiment_id, "compile", "timeout_no_dll_change", level="error",
                             elapsed_sec=compile_res.get("elapsed_sec"), attempt=attempt + 1)
                registry.transition_status(
                    experiment_id, "awaiting_compile_timeout",
                    reason="dll mtime never changed; auto/manual NinjaScript compile did not run",
                )
                return registry.read_experiment(experiment_id)
        if not errs:
            errs = compile_errors.read_since(baseline_ts, class_name=class_name)
        if not errs:
            errs = [
                {"code": "UNKNOWN", "message": "no diagnostics captured", "file": "", "line": 0, "column": 0}
            ]
        if not compile_res.get("timed_out_dll"):
            compile_errors.mirror_to_registry(experiment_id, class_name, errs)
        activity.log(
            experiment_id, "compile", "errors_collected", level="error",
            count=len(errs),
            sample=str([(e.get("code"), (e.get("message") or "")[:80]) for e in errs[:3]])[:200],
            attempt=attempt + 1,
        )
        if attempt == max_compile_attempts - 1:
            errors.log_compile_fail(
                experiment_id, class_name,
                "\n".join(f"{e.get('code')}: {e.get('message','')}" for e in errs)[:8000],
                attempt=attempt + 1,
            )
            try:
                top_err = errs[0] if errs else {}
                lessons.record_lesson(
                    summary=(f"{class_name}: compile loop exhausted "
                             f"({top_err.get('code')}: {(top_err.get('message') or '')[:80]})"),
                    source="error_pattern", scope="global",
                    rule=("avoid: NT8 compile patterns from prior failures; "
                          "use validator + reference WORKING_STRATEGIES_RESULTS_TABLE before writing."),
                )
                errors.log_error(
                    experiment_id, "compile", "compile_loop_exhausted",
                    f"{top_err.get('code')}: {(top_err.get('message') or '')[:200]}",
                    severity="error", class_name=class_name, target_root=target_root,
                )
            except Exception:
                pass
            quarantine = compile_pipeline.quarantine_source(
                experiment_id=experiment_id,
                class_name=class_name,
                reason="autofix loop exhausted",
            )
            registry.transition_status(
                experiment_id, "compile_failed_after_fix_loop",
                reason="autofix loop exhausted",
                extra={
                    "compile": {
                        "attempts": attempt + 1,
                        "last_status": "quarantined" if quarantine.get("ok") else "failed",
                        "errors": errs,
                        "quarantine_path": quarantine.get("quarantine_path"),
                    },
                    "verdict": {
                        "outcome": "reject", "reasons": ["compile_failed"],
                        "rejection_code": "COMPILE_FAIL", "structural": True,
                    },
                },
            )
            return registry.read_experiment(experiment_id)
        autofix_notes = _checkpoint(experiment_id, "autofix")
        if autofix_notes is None:
            return registry.read_experiment(experiment_id)
        activity.log(experiment_id, "generate", "autofix_invoke", level="info",
                     role="coder-autofix", attempt=attempt + 1, errors=len(errs))
        notes_block = operator_notes.render_entries(autofix_notes)
        with heartbeat(experiment_id, "generate", "awaiting coder-autofix model", every_sec=10):
            try:
                new_src, new_report, gen_meta2 = generator.generate(
                    class_name=class_name,
                    ai_cell_id=skeleton["ai_cell_id"],
                    instrument=target_root,
                    hypothesis=hypo["hypothesis"],
                    parameters=hypo["parameters"],
                    memory_intake=skeleton["memory_intake"],
                    user_research_excerpts=intake["user_research_excerpts"],
                    rejected_patterns=intake["rejected_patterns"],
                    experiment_id=experiment_id,
                    use_llm=use_llm,
                    mode="autofix",
                    prior_compile_errors=errs,
                    prior_source=current_source,
                    operator_notes=notes_block,
                    cancel_event=cancel_event,
                    allow_template_fallback=allow_template_fallback,
                    allow_cloud_fallback=attempt >= 2,
                )
            except lm_studio.LMStudioCancelled:
                registry.transition_status(experiment_id, "cancelled", reason="cancelled in autofix")
                return registry.read_experiment(experiment_id)
            except lm_studio.LMStudioUnavailable as exc:
                errors.log_infra_fail(experiment_id, "generate", str(exc))
                activity.log(experiment_id, "generate", "blocked_lm_studio_autofix", level="error",
                             error=str(exc)[:300])
                registry.transition_status(
                    experiment_id, "blocked_lm_studio",
                    reason="LM Studio coder unavailable during autofix",
                    extra={"verdict": {"outcome": "blocked", "reasons": [str(exc)[:400]],
                                       "rejection_code": "BLOCKED_LM_STUDIO", "structural": False},
                           "lm_studio_block": exc.preflight},
                )
                return registry.read_experiment(experiment_id)
        if not new_report.ok:
            registry.transition_status(
                experiment_id, "compile_failed",
                reason="autofix produced invalid source",
                extra={"verdict": {"outcome": "reject", "reasons": list(new_report.violations),
                                   "rejection_code": "AUTOFIX_VALIDATION_FAIL", "structural": True}},
            )
            return registry.read_experiment(experiment_id)
        if _bail_if_cancelled(experiment_id):
            return registry.read_experiment(experiment_id)
        compile_baseline = compile_pipeline.capture_dll_baseline()
        compile_baseline_ts = datetime.now(timezone.utc)
        generator.write_to_sandbox(class_name, new_src)
        activity.log(experiment_id, "write", "autofix_rewrite", level="info",
                     attempt=attempt + 1, sandbox_path=str(sandbox_path),
                     sha=str(gen_meta2.get("sha256", ""))[:16])
        current_source = new_src

    if not compile_ok:
        # Defensive: loop exited without setting compile_ok and without an early return.
        registry.transition_status(experiment_id, "compile_failed",
                                   reason="compile chain did not succeed")
        return registry.read_experiment(experiment_id)

    registry.transition_status(experiment_id, "catalog_visible",
                               reason="class visible in NT catalog")
    activity.log(experiment_id, "catalog", "visible", level="success", class_name=class_name)

    if skip_backtest:
        activity.log(experiment_id, "backtest", "skipped", level="info")
        return registry.read_experiment(experiment_id)

    instrument = _backtest_instrument(target_root, args)
    sanity_min = int(args.get("min_signal_sanity", signal_sanity.DEFAULT_MIN_SIGNALS))
    exp_for_sanity = registry.read_experiment(experiment_id) or skeleton
    sanity = signal_sanity.check_experiment(
        exp_for_sanity, min_signals=sanity_min, instrument=instrument,
    )
    exp_for_sanity["signal_sanity"] = sanity
    registry.write_experiment(exp_for_sanity)
    activity.log(
        experiment_id, "signal_sanity", "checked",
        level="success" if sanity.get("ok") else "error",
        reason=str(sanity.get("reason")),
        theoretical_signals=sanity.get("theoretical_signals"),
        data_source=str(sanity.get("data_source"))[:180],
        requested_instrument=instrument,
        data_instrument=sanity.get("data_instrument"),
        advisory_only=bool(sanity.get("advisory_only")),
    )
    if sanity.get("environment_blocker"):
        registry.transition_status(
            experiment_id,
            "blocked_by_real_environment_issue",
            reason=f"signal sanity blocked by environment: {sanity.get('reason')}",
            extra={"verdict": {"outcome": "blocked", "reasons": [str(sanity.get("reason"))],
                               "rejection_code": "SIGNAL_SANITY_ENV_BLOCKER", "structural": False}},
        )
        return registry.read_experiment(experiment_id)
    if not sanity.get("ok"):
        sanity_reason = str(sanity.get("reason") or "")
        rejection_code = (
            "ZERO_THEORETICAL_SIGNALS"
            if int(sanity.get("theoretical_signals") or 0) <= 0
            else "OVERTRADING_RISK"
            if sanity_reason == "overtrading_risk"
            else "INSUFFICIENT_THEORETICAL_SIGNALS"
        )
        errors.log_rejection(
            experiment_id,
            rejection_code,
            [str(sanity.get("reason"))],
            structural=False,
        )
        try:
            family = exp_for_sanity.get("family") or "?"
            lessons.record_lesson(
                summary=(f"{family} on {target_root}: signal sanity failed "
                         f"({sanity.get('reason')}, theoretical={sanity.get('theoretical_signals')})"),
                source="rejection", scope="family", scope_key=family,
                rule=("avoid: setups whose theoretical signal count is below the sanity floor "
                      "before historical backtest; relax filter or change setup, not just lookback."),
            )
            errors.log_error(experiment_id, "validate", "signal_sanity_fail",
                             str(sanity.get("reason") or ""), severity="error",
                             target_root=target_root)
        except Exception:
            pass
        registry.transition_status(
            experiment_id,
            "rejected",
            reason=f"signal sanity failed: {sanity.get('reason')}",
            extra={"verdict": {"outcome": "reject", "reasons": [str(sanity.get("reason"))],
                               "rejection_code": rejection_code, "structural": False}},
        )
        return registry.read_experiment(experiment_id)

    if _checkpoint(experiment_id, "backtest") is None:
        return registry.read_experiment(experiment_id)

    # --- execution smoke (short real NT run before the 180-day run) ---
    skeleton = registry.read_experiment(experiment_id) or skeleton
    smoke_end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    smoke_days = max(14, min(45, int(args.get("smoke_days") or 30)))
    smoke_start = smoke_end - timedelta(days=smoke_days)
    preferred_instrument = instrument
    instrument_candidates = [preferred_instrument]
    if not (args.get("backtest_instrument") or args.get("instrument")):
        instrument_candidates.extend(
            str(row.get("instrument")) for row in _catalog_contracts(target_root)[:3]
            if row.get("instrument") and str(row.get("instrument")) != preferred_instrument
        )
    instrument_candidates = list(dict.fromkeys(instrument_candidates))[:2]
    smoke: Dict[str, Any] = {}
    smoke_state: Dict[str, Any] = {"status": "not_started"}
    smoke_result: Dict[str, Any] = {}
    instrument = preferred_instrument
    infra_attempts: List[Dict[str, Any]] = []
    for candidate_instrument in instrument_candidates:
        period_plan = _bounded_period_for_instrument(
            candidate_instrument, smoke_start, smoke_end,
        )
        if not period_plan.get("ok") or float(period_plan.get("available_days") or 0) < 10:
            infra_attempts.append({
                "instrument": candidate_instrument, "stage": "catalog_preflight",
                "reason": period_plan.get("reason") or "less_than_10_days_of_minute_data",
                "period": period_plan,
            })
            continue
        instrument = candidate_instrument
        activity.log(
            experiment_id, "safety", "contract_selected", level="info",
            instrument=instrument, data_first=period_plan.get("catalog_data_first"),
            data_last=period_plan.get("catalog_data_last"),
            available_days=period_plan.get("available_days"),
        )
        smoke = backtest.submit(
            experiment_id=experiment_id,
            ai_cell_id=skeleton["ai_cell_id"],
            class_name=class_name,
            instrument=instrument,
            from_utc=str(period_plan["from_utc"]),
            to_utc=str(period_plan["to_utc"]),
            parameters=hypo["parameters"],
            risk_profile=skeleton["risk_profile"],
            session_template=skeleton["session_template"],
            model_chain=skeleton["model_chain"],
            stage="smoke",
        )
        if not smoke.get("ok"):
            infra_attempts.append({
                "instrument": instrument, "stage": "submit",
                "reason": str(smoke.get("error") or "submit_failed")[:500],
            })
            continue
        activity.log(
            experiment_id, "backtest", "smoke_submitted", level="info",
            job_id=smoke["job_id"], days=period_plan.get("available_days"),
            instrument=instrument,
        )
        smoke_state = backtest.wait_for_terminal(
            smoke["job_id"], timeout_sec=int(args.get("smoke_timeout_sec") or 180),
        )
        smoke_result = backtest.result_metrics(smoke["job_id"])
        integrity = smoke_result.get("integrity") or {}
        if smoke_state.get("status") == "done" and integrity.get("ok"):
            break
        infra_attempts.append({
            "instrument": instrument, "stage": "result_integrity",
            "job_id": smoke.get("job_id"), "job_status": smoke_state.get("status"),
            "integrity": integrity,
        })
        activity.log(
            experiment_id, "safety", "smoke_data_invalid", level="error",
            instrument=instrument, job_id=smoke.get("job_id"),
            reasons=integrity.get("reasons") or [smoke_state.get("status")],
        )
        smoke_result = {}

    if not smoke_result:
        reason = "smoke infrastructure preflight failed: no backtest with proven historical bars"
        errors.log_infra_fail(experiment_id, "backtest", reason)
        registry.transition_status(
            experiment_id, "blocked_by_real_environment_issue", reason=reason,
            extra={
                "backtest_infrastructure_attempts": infra_attempts,
                "verdict": {
                    "outcome": "blocked", "reasons": [reason],
                    "rejection_code": "SMOKE_DATA_UNVERIFIED", "structural": True,
                },
            },
        )
        return registry.read_experiment(experiment_id)

    smoke_metrics = smoke_result.get("metrics") or {}
    smoke_trades = int(smoke_result.get("trade_count") or 0)
    smoke_pf = float(smoke_metrics.get("profit_factor_after_commission") or 0.0)
    smoke_no_edge = smoke_trades >= 10 and smoke_pf < 0.65
    smoke_limit = max(
        25,
        int((hypo["parameters"].get("MaxTradesPerDay", 3) or 3) * smoke_days * 0.85),
    )
    smoke_row = {
        "job_id": smoke["job_id"],
        "submitted_at_utc": smoke["submitted_at_utc"],
        "instrument": instrument,
        "from_utc": smoke["request"]["from_utc"],
        "to_utc": smoke["request"]["to_utc"],
        "status": smoke_state.get("status"),
        "stage": "smoke",
        "trades": smoke_trades,
        "net_after_commission": smoke_metrics.get("net_profit_after_commission"),
        "pf_after_commission": smoke_metrics.get("profit_factor_after_commission"),
        "analysis_pack_path": None,
    }
    skeleton = registry.read_experiment(experiment_id) or skeleton
    skeleton.setdefault("backtests", []).append(smoke_row)
    skeleton["execution_sanity"] = {
        "ok": (
            smoke_state.get("status") == "done"
            and 0 < smoke_trades <= smoke_limit
            and not smoke_no_edge
        ),
        "job_id": smoke["job_id"],
        "trades": smoke_trades,
        "max_allowed_trades": smoke_limit,
        "status": smoke_state.get("status"),
        "metrics": smoke_metrics,
    }
    registry.write_experiment(skeleton)
    activity.log(
        experiment_id, "signal_sanity", "smoke_checked",
        level="success" if skeleton["execution_sanity"]["ok"] else "error",
        job_id=smoke["job_id"], trades=smoke_trades,
        max_allowed=smoke_limit, status=smoke_state.get("status"),
    )
    if (
        smoke_state.get("status") != "done"
        or smoke_trades <= 0
        or smoke_trades > smoke_limit
        or smoke_no_edge
    ):
        code = (
            "SMOKE_ZERO_TRADES" if smoke_trades <= 0
            else "SMOKE_OVERTRADING" if smoke_trades > smoke_limit
            else "SMOKE_NO_EDGE" if smoke_no_edge
            else "SMOKE_BACKTEST_FAILED"
        )
        reason = (
            f"execution smoke failed: status={smoke_state.get('status')} "
            f"trades={smoke_trades} allowed=1..{smoke_limit} "
            f"pf_after_commission={smoke_pf:.3f}"
        )
        errors.log_rejection(experiment_id, code, [reason], structural=False)
        lessons.record_lesson(
            summary=f"{skeleton.get('family')} on {target_root}: {reason}",
            source="rejection", scope="family",
            scope_key=str(skeleton.get("family") or "?"),
            evidence_refs=[smoke["job_id"]],
            rule="change the entry trigger/regime before another full backtest",
        )
        registry.transition_status(
            experiment_id, "rejected", reason=reason,
            extra={"verdict": {
                "outcome": "reject", "reasons": [reason],
                "rejection_code": code, "structural": False,
            }},
        )
        return registry.read_experiment(experiment_id)

    # --- backtest submit ---
    skeleton = registry.read_experiment(experiment_id) or skeleton
    requested_period = _default_period()
    period = _bounded_period_for_instrument(
        instrument,
        datetime.fromisoformat(requested_period["from_utc"].replace("Z", "+00:00")),
        datetime.fromisoformat(requested_period["to_utc"].replace("Z", "+00:00")),
    )
    if not period.get("ok") or float(period.get("available_days") or 0) < 20:
        reason = (
            "full backtest blocked: selected contract has insufficient proven minute data "
            f"({period.get('available_days', 0)} days)"
        )
        errors.log_infra_fail(experiment_id, "backtest", reason)
        registry.transition_status(
            experiment_id, "blocked_by_real_environment_issue", reason=reason,
            extra={
                "backtest_period_preflight": period,
                "verdict": {
                    "outcome": "blocked", "reasons": [reason],
                    "rejection_code": "FULL_DATA_INSUFFICIENT", "structural": True,
                },
            },
        )
        return registry.read_experiment(experiment_id)
    activity.log(experiment_id, "backtest", "submitting", level="info",
                  instrument=instrument,
                 from_utc=period["from_utc"], to_utc=period["to_utc"])
    bt = backtest.submit(
        experiment_id=experiment_id, ai_cell_id=skeleton["ai_cell_id"],
        class_name=class_name, instrument=instrument,
        from_utc=period["from_utc"], to_utc=period["to_utc"],
        parameters=hypo["parameters"], risk_profile=skeleton["risk_profile"],
        session_template=skeleton["session_template"], model_chain=skeleton["model_chain"],
        stage="full",
    )
    if not bt.get("ok"):
        errors.log_infra_fail(experiment_id, "backtest", bt.get("error", "submit failed"))
        activity.log(experiment_id, "backtest", "submit_failed", level="error",
                     error=str(bt.get("error", "submit failed"))[:200])
        registry.transition_status(experiment_id, "backtest_failed",
                                   reason=f"submit error: {bt.get('error')}")
        return registry.read_experiment(experiment_id)

    skeleton["backtests"].append({
        "job_id": bt["job_id"], "submitted_at_utc": bt["submitted_at_utc"],
        "instrument": bt["request"]["instrument"],
        "from_utc": bt["request"]["from_utc"], "to_utc": bt["request"]["to_utc"],
        "status": "pending", "analysis_pack_path": None,
        "stage": "full",
    })
    registry.write_experiment(skeleton)
    registry.transition_status(experiment_id, "backtesting",
                               reason=f"job {bt['job_id']} submitted")
    activity.log(experiment_id, "backtest", "submitted", level="success",
                 job_id=bt["job_id"], job_dir=bt.get("job_dir"))
    return registry.read_experiment(experiment_id)


def finalize_backtest(experiment_id: str, job_id: str) -> Dict[str, Any]:
    exp = registry.read_experiment(experiment_id)
    if not exp:
        return {"ok": False, "error": "experiment not found"}
    job_dir = backtest.find_job_dir(job_id)
    if not job_dir:
        return {"ok": False, "error": "job dir not found"}
    job_state = job_dir.parent.name
    if job_state != "done":
        for bt_entry in exp.get("backtests", []):
            if bt_entry.get("job_id") == job_id:
                bt_entry["status"] = job_state
        exp["status"] = "backtest_failed" if job_state == "failed" else f"backtest_{job_state}"
        exp["analysis"] = {}
        exp["arbitration"] = {}
        exp["verdict"] = {
            "outcome": "reject",
            "reasons": [f"backtest job is {job_state}, not done"],
            "rejection_code": "BACKTEST_NOT_DONE",
            "structural": False,
        }
        registry.write_experiment(exp)
        activity.log(experiment_id, "backtest", "finalize_blocked", level="error",
                     job_id=job_id, job_state=job_state)
        return {
            "ok": False,
            "experiment_id": experiment_id,
            "job_id": job_id,
            "status": exp["status"],
            "error": f"job is {job_state}, not done",
        }

    integrity = backtest.validate_job_dir_integrity(job_dir)
    if not integrity.get("ok"):
        reason = "full backtest result has no proven historical bars"
        exp["status"] = "blocked_by_real_environment_issue"
        exp["backtest_result_integrity"] = integrity
        exp["verdict"] = {
            "outcome": "blocked", "reasons": [reason, *(integrity.get("reasons") or [])],
            "rejection_code": "FULL_DATA_UNVERIFIED", "structural": True,
        }
        registry.write_experiment(exp)
        errors.log_infra_fail(experiment_id, "backtest", reason)
        activity.log(
            experiment_id, "safety", "smoke_data_invalid", level="error",
            job_id=job_id, reasons=integrity.get("reasons") or [], backtest_stage="full",
        )
        return {
            "ok": False, "experiment_id": experiment_id, "job_id": job_id,
            "status": exp["status"], "error": reason, "integrity": integrity,
        }

    activity.log(experiment_id, "analyze", "building_pack", level="info", job_id=job_id)
    pack = build_pack(job_dir, capital=float(exp.get("primary_capital", 5000)))
    exp["analysis"] = project_to_experiment_analysis(pack)

    similar_demo = len(exp.get("memory_intake", {}).get("similar_demo_mismatch", []))
    similar_rej = len(exp.get("memory_intake", {}).get("similar_rejected", []))
    similar_cf = len(exp.get("memory_intake", {}).get("similar_compile_fails", []))
    portfolio = [e for e in registry.list_experiments(status="portfolio_contributor")
                 if e["experiment_id"] != experiment_id]
    arb = arbitration.compute(
        exp["analysis"], risk_profile=exp.get("risk_profile"),
        existing_portfolio=portfolio,
        similar_demo_mismatch_count=similar_demo,
        similar_rejected_count=similar_rej,
        similar_compile_fail_count=similar_cf,
    )
    exp["arbitration"] = arb
    score = arb.get("score", 0.0) or 0.0
    activity.log(experiment_id, "arbitrate", "score_computed", level="info", score=score)

    quality = arbitration.classify_quality(
        exp["analysis"],
        score=score,
        capital=float(exp.get("primary_capital") or 5000.0),
    )
    exp["arbitration"]["quality_decision"] = quality
    # Advisory explanations and the next structural mutation are generated
    # after deterministic metrics. They are recorded for audit but cannot
    # change ``quality`` or the verdict below.
    try:
        exp["agent_committee"] = agent_committee.review_backtest(exp)
        activity.log(
            experiment_id, "analyze", "agent_committee_completed", level="success",
            advisory_only=True,
        )
    except Exception as exc:
        exp["agent_committee"] = {
            "advisory_only": True, "reports": {}, "error": str(exc)[:500],
        }
        activity.log(
            experiment_id, "analyze", "agent_committee_failed", level="warn",
            error=str(exc)[:300],
        )
    decision = quality.get("decision")
    if decision == "reject":
        exp["status"] = "rejected"
        rejection_code = str(quality.get("code") or "LOW_QUALITY")
        rejection_reasons = list(quality.get("reasons") or ["фильтры качества не пройдены"])
        exp["verdict"] = {
            "outcome": "reject", "reasons": rejection_reasons,
            "rejection_code": rejection_code, "structural": False,
        }
        errors.log_rejection(
            experiment_id, rejection_code, rejection_reasons, structural=False
        )
        # Auto-lesson so next generation reads it via knowledge.build_context.
        try:
            family = exp.get("family") or "?"
            an = exp.get("analysis") or {}
            lessons.record_lesson(
                summary=(f"{family} на {exp.get('target_root')}: "
                         f"score={score:.1f} PF={an.get('pf_after_commission')} "
                         f"trades={an.get('trades_total')} → отклонено ({rejection_code})"),
                source="rejection", scope="family", scope_key=family,
                rule=(f"избегать низкоэффективных вариантов {family} на {exp.get('target_root')} "
                      "с похожей гипотезой/параметрами; нужен более сильный фильтр."),
            )
        except Exception:
            pass
    elif decision == "mutate":
        exp["status"] = "mutation_candidate"
        exp["verdict"] = {
            "outcome": "mutate",
            "reasons": list(quality.get("reasons") or ["почти кандидат, нужна мутация"]),
            "rejection_code": quality.get("code"),
            "structural": False,
        }
    elif score < 100:
        exp["status"] = "sandbox_candidate"
        exp["verdict"] = {"outcome": "keep", "reasons": ["фильтры кандидата пройдены"],
                          "rejection_code": None, "structural": False}
    else:
        exp["status"] = "champion_candidate"
        exp["verdict"] = {"outcome": "keep", "reasons": ["высокая оценка арбитража"],
                          "rejection_code": None, "structural": False}
        lessons.record_lesson(
            summary=f"{experiment_id} стал сильным кандидатом с оценкой {score:.1f}",
            source="rejection", scope="experiment", scope_key=experiment_id, weight=1.5,
        )

    for bt_entry in exp.get("backtests", []):
        if bt_entry.get("job_id") == job_id:
            bt_entry["status"] = "done"
    registry.write_experiment(exp)
    activity.log(experiment_id, "verdict", "set", level="success",
                 status=exp["status"], outcome=exp["verdict"]["outcome"])
    return {"ok": True, "experiment_id": experiment_id, "score": score, "status": exp["status"]}


# ---------------------- compatibility shim ----------------------

def run_once(
    *,
    user_pref_root: Optional[str] = None,
    user_capital: Optional[float] = None,
    user_goal: Optional[str] = None,
    dry_run: bool = False,
    skip_compile: bool = False,
    skip_backtest: bool = False,
    verify_poll_sec: int = 0,
) -> Dict[str, Any]:
    """Synchronous one-shot for tests and CLI. The HTTP endpoint uses
    :mod:`runner` instead so the UI is non-blocking."""
    args = {
        "user_pref_root": user_pref_root,
        "user_capital": user_capital,
        "user_goal": user_goal,
        "dry_run": dry_run,
        "skip_compile": skip_compile,
        "skip_backtest": skip_backtest,
        "verify_poll_sec": verify_poll_sec,
    }
    skeleton = start_skeleton(args)
    return run_pipeline(skeleton["experiment_id"], args)
