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
``docs/STRATEGY_LIFECYCLE.md``.
"""

from __future__ import annotations

import random
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import activity, arbitration, backtest, compile_pipeline, errors, generator, lessons
from . import compile_errors, goal_parser, knowledge, lm_studio, operator_notes, registry, runner, user_research
from . import signal_sanity
from .analysis_pack import build as build_pack, project_to_experiment_analysis
from .heartbeat import heartbeat


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


DEFAULT_INSTRUMENT_BY_ROOT = {
    "MNQ": "MNQ 12-26",
    "MGC": "MGC 08-26",
    "MES": "MES 12-26",
    "MCL": "MCL 09-26",
}

INSTRUMENT_UNIVERSE = ["MNQ", "MGC", "MES"]

MAX_COMPILE_ATTEMPTS = 5


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
    if use_llm:
        try:
            model_health["idea_generator"] = lm_studio.select_available_model(
                "judge",
                fallback_roles=["strategy_researcher", "fast_assistant"],
                experiment_id=experiment_id,
                purpose="idea_generator_health_gate",
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
) -> Dict[str, Any]:
    constraints = intake.get("goal_constraints") or {}
    requested_pattern = constraints.get("pattern")
    shortlist = list(intake.get("reference_shortlist") or [])
    preferred_ref = shortlist[0] if shortlist else {}
    if requested_pattern:
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
    try:
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
        model_gate = (intake.get("model_health") or {}).get("idea_generator") or {}
        if model_gate and not model_gate.get("ok"):
            activity.log(
                experiment_id, "generate", "hypothesis_model_health_failed",
                level="warn", role="judge", response_summary=str(model_gate)[:300],
            )
            return fallback
        selected_role = model_gate.get("selected_role") or "judge"
        selected_model = model_gate.get("selected_model")
        user_prompt = (
            f"{intake.get('knowledge_prompt_context', '')}\n\n"
            f"Approved references: {shortlist}\n"
            f"Avoid recent failure patterns: {intake.get('rejected_patterns', [])[:5]}\n"
            f"User research files just read: {intake.get('user_research_files_read', [])}\n\n"
            f"{lm_studio.prompt_cache_marker()}\n\n"
            f"Target root: {target_root}\n"
            f"User goal constraints: {constraints}\n"
            "Propose one structurally distinct intraday hypothesis. State why it is "
            "not another generic breakout and target 0.2-3.0 trades/day. "
            "All explanations must be in Russian."
        )
        if operator_notes_block:
            user_prompt = (
                user_prompt
                + "\n\nOperator notes for this dynamic request:\n"
                + operator_notes_block
            )
        activity.log(experiment_id, "generate", "hypothesis_prompt", level="info",
                     role=selected_role, model=selected_model,
                     prompt_preview="Propose one structurally distinct intraday hypothesis in Russian.",
                     prompt_preview_ru="Сформировать одну структурно отличающуюся внутридневную гипотезу на русском языке.")
        resp = lm_studio.chat(
            role=selected_role,
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.3, max_tokens=500, experiment_id=experiment_id,
            purpose="hypothesis", timeout=lm_studio.DEFAULT_JUDGE_TIMEOUT,
            cancel_event=cancel_event,
            model_override=selected_model,
        )
        parsed = lm_studio.extract_json_block(resp.get("content", ""))
        if not isinstance(parsed, dict):
            activity.log(
                experiment_id,
                "generate",
                "hypothesis_contract_rejected",
                level="warn",
                response_summary=str(parsed)[:300],
            )
            return fallback
        allowed_refs = {
            str(row.get("reference_id")) for row in shortlist if row.get("reference_id")
        }
        family_text = str(parsed.get("family") or "")
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
                         model=resp.get("model"), response_summary=str(parsed.get("hypothesis"))[:200])
            return {
                "hypothesis": str(parsed["hypothesis"])[:500],
                "family": parsed.get("family") or fallback["family"],
                "lane": "research",
                "parameters": merged,
                "_source": "llm",
                "reference_id": parsed.get("reference_id"),
                "market_regime": parsed.get("market_regime"),
                "entry_trigger": parsed.get("entry_trigger"),
                "exit_economics": parsed.get("exit_economics"),
                "why_not_generic": parsed.get("why_not_generic"),
                "expected_trades_per_day": parsed.get("expected_trades_per_day"),
            }
        activity.log(
            experiment_id,
            "generate",
            "hypothesis_contract_rejected",
            level="warn",
            response_summary=str(parsed)[:300],
        )
    except lm_studio.LMStudioCancelled:
        raise
    except lm_studio.LMStudioError as e:
        activity.log(experiment_id, "generate", "hypothesis_lm_failed", level="warn", error=str(e))
    activity.log(experiment_id, "generate", "hypothesis_fallback", level="info",
                 response_summary=fallback["hypothesis"][:200])
    return fallback


def _default_period() -> Dict[str, str]:
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=180)
    return {"from_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "to_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ")}


def _backtest_instrument(target_root: str, args: Dict[str, Any]) -> str:
    explicit = args.get("backtest_instrument") or args.get("instrument")
    if explicit:
        return str(explicit)
    try:
        from .. import jobqueue
        catalog = jobqueue.read_instruments_catalog() or {}
        candidates = [
            row for row in (catalog.get("instruments") or [])
            if isinstance(row, dict)
            and str(row.get("root") or "").upper() == target_root.upper()
            and bool(row.get("has_minute_data"))
            and row.get("data_last")
        ]
        mature = []
        for row in candidates:
            try:
                first = datetime.fromisoformat(str(row.get("data_first")))
                last = datetime.fromisoformat(str(row.get("data_last")))
                if (last - first).days >= 60:
                    mature.append(row)
            except (TypeError, ValueError):
                continue
        # Avoid a just-rolled contract with only a few days of history. The
        # AI Lab needs enough observations for smoke and after-cost scoring.
        if mature:
            candidates = mature
        candidates.sort(
            key=lambda row: (
                str(row.get("data_last") or ""),
                str(row.get("data_first") or ""),
                str(row.get("instrument") or ""),
            ),
            reverse=True,
        )
        if candidates:
            return str(candidates[0]["instrument"])
    except Exception:
        pass
    return str(DEFAULT_INSTRUMENT_BY_ROOT.get(target_root, target_root))


# ---------------------- public API ----------------------

def start_skeleton(args: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous: allocate ids and persist a draft experiment record."""
    user_goal = str(args.get("user_goal") or args.get("goal") or "").strip()
    goal_constraints = goal_parser.parse_user_goal(user_goal, args)
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
    skeleton["goal_constraints"] = goal_constraints
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

    target_root = skeleton["target_root"]
    user_goal = str(skeleton.get("user_goal") or args.get("user_goal") or args.get("goal") or "")
    goal_constraints = skeleton.get("goal_constraints") or goal_parser.parse_user_goal(user_goal, args)
    skip_compile = bool(args.get("skip_compile", False))
    skip_backtest = bool(args.get("skip_backtest", False))
    dry_run = bool(args.get("dry_run", False))
    verify_poll_sec = int(args.get("verify_poll_sec", 0))
    use_llm = bool(args.get("use_llm", True))
    allow_template_fallback = bool(args.get("allow_template_fallback", False))
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
            hypo = choose_hypothesis(
                target_root, intake, experiment_id, use_llm=use_llm,
                cancel_event=cancel_event,
                operator_notes_block=operator_notes.render_entries(judge_notes),
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
    if idea_gate:
        skeleton["model_chain"] = [{
            "role": "idea_generator",
            "configured_primary": idea_gate.get("primary_model"),
            "selected_model": idea_gate.get("selected_model"),
            "fallback_used": bool(idea_gate.get("fallback_used")),
            "primary_model_failed": bool(idea_gate.get("primary_model_failed")),
            "checked_via": idea_gate.get("checked_via"),
        }]

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
        baseline_ts = datetime.now(timezone.utc)
        with heartbeat(experiment_id, "compile", "waiting for NT compile / dll change", every_sec=15):
            compile_res = compile_pipeline.run_compile_chain(
                experiment_id=experiment_id, class_name=class_name,
                request_restart_flag=False, verify_poll_sec=verify_poll_sec,
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

    sanity_min = int(args.get("min_signal_sanity", signal_sanity.DEFAULT_MIN_SIGNALS))
    exp_for_sanity = registry.read_experiment(experiment_id) or skeleton
    sanity = signal_sanity.check_experiment(exp_for_sanity, min_signals=sanity_min)
    exp_for_sanity["signal_sanity"] = sanity
    registry.write_experiment(exp_for_sanity)
    activity.log(
        experiment_id, "signal_sanity", "checked",
        level="success" if sanity.get("ok") else "error",
        reason=str(sanity.get("reason")),
        theoretical_signals=sanity.get("theoretical_signals"),
        data_source=str(sanity.get("data_source"))[:180],
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
    instrument = _backtest_instrument(target_root, args)
    smoke_end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    smoke_days = max(14, min(45, int(args.get("smoke_days") or 30)))
    smoke_start = smoke_end - timedelta(days=smoke_days)
    smoke = backtest.submit(
        experiment_id=experiment_id,
        ai_cell_id=skeleton["ai_cell_id"],
        class_name=class_name,
        instrument=instrument,
        from_utc=smoke_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        to_utc=smoke_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        parameters=hypo["parameters"],
        risk_profile=skeleton["risk_profile"],
        session_template=skeleton["session_template"],
        model_chain=skeleton["model_chain"],
        stage="smoke",
    )
    if not smoke.get("ok"):
        registry.transition_status(
            experiment_id, "backtest_failed",
            reason=f"smoke submit error: {smoke.get('error')}",
        )
        return registry.read_experiment(experiment_id)
    activity.log(
        experiment_id, "backtest", "smoke_submitted", level="info",
        job_id=smoke["job_id"], days=smoke_days,
    )
    smoke_state = backtest.wait_for_terminal(
        smoke["job_id"],
        timeout_sec=int(args.get("smoke_timeout_sec") or 180),
    )
    smoke_result = backtest.result_metrics(smoke["job_id"])
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
    period = _default_period()
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
