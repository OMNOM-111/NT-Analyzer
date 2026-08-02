"""AI experiment registry: persistence and read-model helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths
from .io_utils import iter_jsonl, read_json, write_json_atomic

EXP_ID_RE = re.compile(r"^EXP-\d{8}-\d{4}$")
AI_CELL_RE = re.compile(r"^AI-CELL-[A-Z0-9]+-\d{3}$")

TERMINAL_STATUSES = {
    "validation_failed",
    "compile_failed",
    "compile_failed_after_fix_loop",
    "awaiting_compile_timeout",
    "blocked_by_real_environment_issue",
    "blocked_lm_studio",
    "backtest_failed",
    "pipeline_failed",
    "rejected",
    "mutation_candidate",
    "sandbox_candidate",
    "champion_candidate",
    "human_review_candidate",
    "portfolio_contributor",
    "archived",
    "cancelled",
}

VALID_STATUSES = TERMINAL_STATUSES | {
    "draft", "designing", "draft_ready", "generating", "generated",
    "awaiting_compile", "catalog_visible",
    "backtesting", "backtest_done", "analysis_ready",
}

PORTFOLIO_APPROVAL_STATES = {
    "candidate",
    "approved",
    "promoted",
    "paper_ready",
}

PORTFOLIO_ELIGIBLE_STATUSES = {
    "sandbox_candidate",
    "champion_candidate",
    "human_review_candidate",
    "portfolio_contributor",
}

PORTFOLIO_BLOCKED_STATUSES = {
    "draft",
    "designing",
    "draft_ready",
    "generating",
    "generated",
    "validation_failed",
    "awaiting_compile",
    "awaiting_compile_timeout",
    "compile_failed",
    "compile_failed_after_fix_loop",
    "blocked_by_real_environment_issue",
    "blocked_lm_studio",
    "catalog_visible",
    "backtesting",
    "backtest_failed",
    "pipeline_failed",
    "rejected",
    "cancelled",
    "archived",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def load_index() -> Dict[str, Any]:
    paths.ensure_dirs()
    idx = read_json(paths.INDEX_PATH, default={})
    if not idx:
        idx = {
            "schema_version": "0.1",
            "generated_at_utc": now_iso(),
            "experiments": [],
            "by_root": {},
            "by_status": {},
            "last_experiment_seq": 0,
            "user_research_ingest": {"last_scan_utc": None, "files": {}},
        }
    idx.setdefault("experiments", [])
    idx.setdefault("by_root", {})
    idx.setdefault("by_status", {})
    idx.setdefault("last_experiment_seq", 0)
    idx.setdefault("user_research_ingest", {"last_scan_utc": None, "files": {}})
    return idx


def save_index(idx: Dict[str, Any]) -> None:
    idx["generated_at_utc"] = now_iso()
    write_json_atomic(paths.INDEX_PATH, idx)


def _experiment_path(experiment_id: str) -> Path:
    return paths.EXPERIMENTS_DIR / f"{experiment_id}.json"


def read_experiment(experiment_id: str) -> Optional[Dict[str, Any]]:
    p = _experiment_path(experiment_id)
    if not p.exists():
        return None
    return read_json(p, default=None)


def list_experiments(
    target_root: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    paths.ensure_dirs()
    items: List[Dict[str, Any]] = []
    for f in sorted(paths.EXPERIMENTS_DIR.glob("EXP-*.json")):
        exp = read_json(f, default=None)
        if not exp:
            continue
        if target_root and exp.get("target_root") != target_root:
            continue
        if status and exp.get("status") != status:
            continue
        items.append(exp)
    items.sort(key=lambda e: e.get("created_at_utc", ""), reverse=True)
    if limit:
        items = items[:limit]
    return items


def write_experiment(experiment: Dict[str, Any]) -> None:
    eid = experiment["experiment_id"]
    if not EXP_ID_RE.match(eid):
        raise ValueError(f"Invalid experiment_id: {eid}")
    cid = experiment.get("ai_cell_id", "")
    if not AI_CELL_RE.match(cid):
        raise ValueError(f"Invalid ai_cell_id: {cid}")
    if experiment.get("lab_namespace") != "AI_SANDBOX":
        raise ValueError("lab_namespace must be AI_SANDBOX")
    status = experiment.get("status", "draft")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    portfolio = experiment.get("portfolio")
    if isinstance(portfolio, dict):
        state = portfolio.get("portfolio_status")
        if state and state not in PORTFOLIO_APPROVAL_STATES:
            raise ValueError(f"Invalid portfolio_status: {state}")
    experiment["updated_at_utc"] = now_iso()
    # Stamp the portfolio lifecycle stage on every write so the AI experiment's
    # current stage (Испытание / Утверждено для демо / Реальная торговля /
    # Провалено→Архив) is persisted and shows up in the lifecycle board.
    try:
        from .. import strategy_lifecycle as _sl
        experiment["lifecycle"] = _sl.lifecycle_for_ai_status(status)
        experiment["lifecycle_label"] = _sl.LIFECYCLE_LABELS[experiment["lifecycle"]]
    except Exception:  # noqa: BLE001 — lifecycle stamping must never block a write
        pass
    write_json_atomic(_experiment_path(eid), experiment)
    _refresh_index_entry(experiment)


def transition_status(
    experiment_id: str,
    to_status: str,
    *,
    reason: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update experiment.status and log it to the activity stream.

    Returns the updated experiment dict, or raises if not found / invalid.
    """
    from . import activity  # lazy import to avoid cycle
    if to_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {to_status}")
    exp = read_experiment(experiment_id)
    if exp is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    from_status = exp.get("status", "draft")
    if extra:
        for k, v in extra.items():
            exp[k] = v
    exp["status"] = to_status
    write_experiment(exp)
    activity.log(
        experiment_id, "status", f"{from_status} -> {to_status}",
        level="success" if to_status in TERMINAL_STATUSES else "info",
        from_status=from_status, to_status=to_status, reason=reason,
    )
    return exp


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def latest_trade_count(experiment: Dict[str, Any]) -> Optional[int]:
    analysis = experiment.get("analysis") or {}
    value = analysis.get("trades_total")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_zero_trade_experiment(experiment: Dict[str, Any]) -> bool:
    return latest_trade_count(experiment) == 0


def portfolio_metadata(experiment: Dict[str, Any]) -> Dict[str, Any]:
    portfolio = experiment.get("portfolio") if isinstance(experiment.get("portfolio"), dict) else {}
    raw_member = bool(portfolio.get("is_portfolio_member"))
    is_member = raw_member and not promotion_blockers(experiment)
    return {
        "is_experiment": True,
        "is_portfolio_member": is_member,
        "portfolio_status": portfolio.get("portfolio_status") if is_member else None,
        "promoted_at": portfolio.get("promoted_at") if is_member else None,
        "approved_at": portfolio.get("approved_at") if is_member else None,
        "approved_by": portfolio.get("approved_by") if is_member else None,
        "source_experiment_id": portfolio.get("source_experiment_id") or experiment.get("experiment_id"),
    }


def promotion_blockers(experiment: Dict[str, Any]) -> List[str]:
    status = experiment.get("status", "draft")
    blockers: List[str] = []
    if status in PORTFOLIO_BLOCKED_STATUSES:
        blockers.append(f"status {status} is history-only")
    elif status not in PORTFOLIO_ELIGIBLE_STATUSES:
        blockers.append(f"status {status} is not portfolio eligible")
    verdict = experiment.get("verdict") or {}
    if verdict.get("outcome") == "reject":
        blockers.append("verdict is reject")
    if is_zero_trade_experiment(experiment):
        blockers.append("0 trades")
    return blockers


def can_promote_to_portfolio(experiment: Dict[str, Any]) -> bool:
    return not promotion_blockers(experiment)


def set_portfolio_membership(
    experiment_id: str,
    *,
    action: str,
    approved_by: str = "ui",
) -> Dict[str, Any]:
    """Manual AI portfolio membership action.

    ``action`` is one of ``candidate``, ``approve``, ``promote``,
    ``paper_ready``, or ``remove``. This never touches production strategy
    code and never starts live/paper trading.
    """
    action = (action or "").strip().lower()
    exp = read_experiment(experiment_id)
    if exp is None:
        raise ValueError(f"experiment not found: {experiment_id}")

    if action == "remove":
        portfolio = exp.get("portfolio") if isinstance(exp.get("portfolio"), dict) else {}
        portfolio.update({
            "is_portfolio_member": False,
            "removed_at": now_iso(),
            "removed_by": approved_by or "ui",
        })
        exp["portfolio"] = portfolio
        write_experiment(exp)
        return exp

    state_by_action = {
        "candidate": "candidate",
        "approve": "approved",
        "approved": "approved",
        "promote": "promoted",
        "promoted": "promoted",
        "paper_ready": "paper_ready",
    }
    state = state_by_action.get(action)
    if not state:
        raise ValueError(f"invalid portfolio action: {action}")

    blockers = promotion_blockers(exp)
    if blockers:
        raise ValueError("cannot add to portfolio: " + "; ".join(blockers))

    ts = now_iso()
    portfolio = exp.get("portfolio") if isinstance(exp.get("portfolio"), dict) else {}
    portfolio.update({
        "is_portfolio_member": True,
        "portfolio_status": state,
        "source_experiment_id": experiment_id,
        "approved_by": approved_by or "ui",
    })
    if state in {"candidate", "promoted", "paper_ready"}:
        portfolio["promoted_at"] = portfolio.get("promoted_at") or ts
    if state in {"approved", "promoted", "paper_ready"}:
        portfolio["approved_at"] = portfolio.get("approved_at") or ts
    exp["portfolio"] = portfolio
    write_experiment(exp)
    return exp


def _refresh_index_entry(experiment: Dict[str, Any]) -> None:
    idx = load_index()
    eid = experiment["experiment_id"]
    root = experiment.get("target_root", "UNKNOWN")
    status = experiment.get("status", "draft")
    score = (experiment.get("arbitration") or {}).get("score")
    entry = {
        "experiment_id": eid,
        "ai_cell_id": experiment.get("ai_cell_id"),
        "target_root": root,
        "class_name": experiment.get("class_name"),
        "status": status,
        "score": score,
        "created_at_utc": experiment.get("created_at_utc"),
        "updated_at_utc": experiment.get("updated_at_utc"),
    }
    others = [e for e in idx["experiments"] if e.get("experiment_id") != eid]
    idx["experiments"] = others + [entry]
    by_root: Dict[str, List[str]] = {}
    by_status: Dict[str, List[str]] = {}
    for e in idx["experiments"]:
        by_root.setdefault(e.get("target_root", "UNKNOWN"), []).append(e["experiment_id"])
        by_status.setdefault(e.get("status", "draft"), []).append(e["experiment_id"])
    idx["by_root"] = by_root
    idx["by_status"] = by_status
    save_index(idx)


def next_experiment_id() -> str:
    idx = load_index()
    today = _today_compact()
    seq = 1
    for e in idx.get("experiments", []):
        eid = e.get("experiment_id", "")
        m = re.match(rf"^EXP-{today}-(\d{{4}})$", eid)
        if m:
            seq = max(seq, int(m.group(1)) + 1)
    return f"EXP-{today}-{seq:04d}"


def next_ai_cell_id(target_root: str) -> str:
    target_root = target_root.upper()
    idx = load_index()
    seq = 0
    for e in idx.get("experiments", []):
        if e.get("target_root") != target_root:
            continue
        cid = e.get("ai_cell_id", "")
        m = re.match(rf"^AI-CELL-{re.escape(target_root)}-(\d{{3}})$", cid)
        if m:
            seq = max(seq, int(m.group(1)))
    return f"AI-CELL-{target_root}-{seq + 1:03d}"


def new_experiment_skeleton(
    target_root: str,
    class_name: str,
    hypothesis: str,
    lane: str = "research",
    family: str = "uncategorized",
    capital_scenarios: Optional[List[float]] = None,
    primary_capital: Optional[float] = None,
    parent_experiment_id: Optional[str] = None,
    user_research_refs: Optional[List[str]] = None,
    model_chain: Optional[List[str]] = None,
) -> Dict[str, Any]:
    target_root = target_root.upper()
    eid = next_experiment_id()
    cid = next_ai_cell_id(target_root)
    return {
        "experiment_id": eid,
        "ai_cell_id": cid,
        "target_root": target_root,
        "lab_namespace": "AI_SANDBOX",
        "class_name": class_name,
        "lane": lane,
        "family": family,
        "capital_scenarios": capital_scenarios or [2000, 3000, 5000, 10000],
        "primary_capital": primary_capital or 5000,
        "created_at_utc": now_iso(),
        "updated_at_utc": now_iso(),
        "status": "draft",
        "parent_experiment_id": parent_experiment_id,
        "lineage": ([] if not parent_experiment_id else [parent_experiment_id]),
        "hypothesis": hypothesis,
        "rationale": "",
        "user_research_refs": user_research_refs or [],
        "memory_intake": {
            "user_research_files_read": [],
            "similar_rejected": [],
            "similar_demo_mismatch": [],
            "similar_compile_fails": [],
            "knowledge_context_path": None,
            "knowledge_sources_read": [],
            "knowledge_prompt_context": "",
            "reference_examples": [],
            "project_strategy_examples": [],
            "goal_constraints": {},
            "model_health": {},
        },
        "knowledge_context": {"required": True, "path": None, "sources_read": [], "built": False},
        "user_goal": "",
        "goal_constraints": {},
        "research_loop": {},
        "model_chain": model_chain or [],
        "strategy_source": {"sandbox_path": "", "mirror_path": "", "files": [], "sha256": ""},
        "parameters": {},
        "risk_profile": {},
        "session_template": "",
        "compile": {"attempts": 0, "last_status": "pending", "errors": []},
        "catalog": {"visible_in_whitelist": False, "visible_in_catalog": False, "last_checked_utc": None},
        "backtests": [],
        "analysis": {},
        "arbitration": {},
        "verdict": {"outcome": "pending", "reasons": [], "rejection_code": None, "structural": False},
    }


def history_for(experiment_id: str) -> List[Dict[str, Any]]:
    """Return all log records (errors, rejections) attached to an experiment."""
    history: List[Dict[str, Any]] = []
    for rec in iter_jsonl(paths.ERROR_LOG_PATH):
        if rec.get("experiment_id") == experiment_id:
            history.append({"kind": "error", **rec})
    for rec in iter_jsonl(paths.REJECTED_HYPOTHESES_PATH):
        if rec.get("experiment_id") == experiment_id:
            history.append({"kind": "reject", **rec})
    for rec in iter_jsonl(paths.COMPILE_FAIL_PATH):
        if rec.get("experiment_id") == experiment_id:
            history.append({"kind": "compile_fail", **rec})
    for rec in iter_jsonl(paths.LESSON_LOG_PATH):
        if rec.get("scope") == "experiment" and rec.get("scope_key") == experiment_id:
            history.append({"kind": "lesson", **rec})
    history.sort(key=lambda r: r.get("timestamp_utc", ""))
    return history
