"""AI Arbitration scoring.

Transparent composite score:

    AI_Arbitration_Score =
        GrowthScore + RobustnessScore + LongevityScore + TradeConfidenceScore + PortfolioFitScore
        - RiskPenalty - OverfitPenalty - DemoMismatchPenalty - RepeatMistakePenalty

All component scores are roughly in [0, 100] before weighting; the final
``score`` is a weighted sum (default weights below). The breakdown is exposed
so the UI can show *why* a strategy scored as it did.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional

DEFAULT_WEIGHTS = {
    "growth": 1.0,
    "robustness": 0.8,
    "longevity": 0.6,
    "trade_confidence": 0.5,
    "portfolio_fit": 0.8,
    "risk_penalty": 1.0,
    "overfit_penalty": 1.0,
    "demo_mismatch_penalty": 1.0,
    "repeat_mistake_penalty": 1.0,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _coalesce(v: Any, fallback: float = 0.0) -> float:
    if v is None:
        return fallback
    try:
        return float(v)
    except (TypeError, ValueError):
        return fallback


def growth_score(analysis: Dict[str, Any]) -> float:
    """Reward monthly growth %, anchored: 0% -> 0, 20%/mo -> 50, 50%/mo -> 100."""
    g = _coalesce(analysis.get("monthly_growth_pct"))
    return _clamp(g * (50.0 / 20.0))


def robustness_score(analysis: Dict[str, Any]) -> float:
    pf = _coalesce(analysis.get("pf_after_commission"))
    dd = _coalesce(analysis.get("dd_after_commission"))
    pm = _coalesce(analysis.get("profitable_months_pct"))
    pq = _coalesce(analysis.get("profitable_quarters_pct"))

    pf_pts = _clamp((pf - 1.0) * 50.0) if pf > 0 else 0.0  # PF 1.0 -> 0, 3.0 -> 100
    dd_pts = _clamp(100.0 - abs(dd) / 50.0) if dd else 50.0  # smaller |dd| better
    months_pts = 50.0 if analysis.get("profitable_months_pct") is None else _clamp(pm)
    quarters_pts = 50.0 if analysis.get("profitable_quarters_pct") is None else _clamp(pq)
    return 0.3 * pf_pts + 0.3 * dd_pts + 0.2 * months_pts + 0.2 * quarters_pts


def longevity_score(analysis: Dict[str, Any]) -> float:
    yrs = _coalesce(analysis.get("years_tested"))
    py = _coalesce(analysis.get("profitable_years_pct"))
    yrs_pts = _clamp(yrs * 25.0)  # 4y -> 100
    py_pts = 50.0 if analysis.get("profitable_years_pct") is None else _clamp(py)
    return 0.6 * yrs_pts + 0.4 * py_pts


def trade_confidence_score(analysis: Dict[str, Any]) -> float:
    total = _coalesce(analysis.get("trades_total"))
    per_day = _coalesce(analysis.get("trades_per_day"))
    total_pts = _clamp(total / 5.0)  # 500 trades -> 100
    density_pts = _clamp(per_day * 20.0)  # 5/day -> 100
    return 0.7 * total_pts + 0.3 * density_pts


def portfolio_fit_score(
    analysis: Dict[str, Any],
    existing_portfolio: Optional[List[Dict[str, Any]]] = None,
    target_monthly_growth_pct: float = 100.0,
) -> float:
    """Reward strategies that close the gap to target monthly growth and
    don't already duplicate an accepted lane.
    """
    g = _coalesce(analysis.get("monthly_growth_pct"))
    if not existing_portfolio:
        return _clamp(50.0 + g)  # neutral fit when no peers
    portfolio_growth = sum(_coalesce((p.get("analysis") or {}).get("monthly_growth_pct")) for p in existing_portfolio)
    gap = max(0.0, target_monthly_growth_pct - portfolio_growth)
    contribution_pts = _clamp((g / max(1.0, gap)) * 100.0) if gap else 50.0
    families = {p.get("family") for p in existing_portfolio if p.get("family")}
    dedupe_pts = 100.0 if not families else 60.0
    return 0.6 * contribution_pts + 0.4 * dedupe_pts


def risk_penalty(analysis: Dict[str, Any], risk_profile: Optional[Dict[str, Any]] = None) -> float:
    dd = abs(_coalesce(analysis.get("dd_after_commission")))
    pen = _clamp(dd / 20.0, 0.0, 100.0)  # |dd|=$2000 -> 100
    if risk_profile is not None and not risk_profile.get("max_daily_loss"):
        pen += 25.0
    return _clamp(pen)


def overfit_penalty(analysis: Dict[str, Any]) -> float:
    yrs = _coalesce(analysis.get("years_tested"))
    total = _coalesce(analysis.get("trades_total"))
    pen = 0.0
    if yrs and yrs < 1.0:
        pen += 30.0 * (1.0 - yrs)
    if total and total < 50:
        pen += 30.0
    return _clamp(pen)


def demo_mismatch_penalty(similar_demo_mismatch_count: int) -> float:
    return _clamp(similar_demo_mismatch_count * 20.0)


def repeat_mistake_penalty(similar_rejected_count: int, similar_compile_fail_count: int) -> float:
    # Saturating penalty: ten historical rejects must not make every future
    # strategy mathematically impossible to mutate into a candidate.
    return _clamp(
        7.0 * math.sqrt(max(0, similar_rejected_count))
        + 6.0 * math.sqrt(max(0, similar_compile_fail_count)),
        0.0,
        35.0,
    )


def classify_quality(
    analysis: Dict[str, Any],
    *,
    score: float,
    capital: float = 5000.0,
) -> Dict[str, Any]:
    """Calibrated hard gates first, score second.

    ``reject`` means the edge is structurally absent. ``mutate`` means a
    near-miss worth changing at the hypothesis/filter level. ``candidate``
    requires positive after-cost economics, enough trades, and bounded DD.
    """
    trades = int(_coalesce(analysis.get("trades_total")))
    net = _coalesce(analysis.get("net_after_commission"))
    pf = _coalesce(analysis.get("pf_after_commission"))
    dd = abs(_coalesce(analysis.get("dd_after_commission")))
    per_day = _coalesce(analysis.get("trades_per_day"))
    profitable_months = analysis.get("profitable_months_pct")
    reasons: List[str] = []

    if trades <= 0:
        return {"decision": "reject", "code": "NO_TRADES", "reasons": ["нет завершенных сделок"]}
    if per_day > 3.25:
        return {
            "decision": "reject", "code": "OVERTRADING",
            "reasons": [f"сделок в день {per_day:.2f} больше лимита 3.25"],
        }
    if pf < 0.80 and net < 0:
        return {
            "decision": "reject", "code": "NO_EDGE",
            "reasons": [f"PF {pf:.3f} и net {net:.2f} не показывают преимущества после комиссии"],
        }
    if dd > max(1000.0, capital * 0.60):
        return {
            "decision": "reject", "code": "EXCESSIVE_DRAWDOWN",
            "reasons": [f"просадка {dd:.2f} выше риск-лимита"],
        }

    candidate_gates = {
        "positive_net": net > 0,
        "pf": pf >= 1.05,
        "trades": trades >= 30,
        "drawdown": dd <= max(750.0, capital * 0.35),
        "score": score >= 25.0,
        "monthly_stability": (
            profitable_months is None or _coalesce(profitable_months) >= 45.0
        ),
    }
    failed = [name for name, passed in candidate_gates.items() if not passed]
    if not failed:
        return {
            "decision": "candidate", "code": None,
            "reasons": ["все фильтры кандидата после комиссии пройдены"],
            "gates": candidate_gates,
        }

    near_miss = (
        (pf >= 0.85 or net > 0)
        and trades >= 8
        and per_day <= 3.25
        and dd <= max(1000.0, capital * 0.60)
    )
    reasons.append("не пройдены фильтры кандидата: " + ", ".join(failed))
    return {
        "decision": "mutate" if near_miss else "reject",
        "code": "NEAR_MISS" if near_miss else "LOW_QUALITY",
        "reasons": reasons,
        "gates": candidate_gates,
    }


@dataclass
class ScoreBreakdown:
    growth: float
    robustness: float
    longevity: float
    trade_confidence: float
    portfolio_fit: float
    risk_penalty: float
    overfit_penalty: float
    demo_mismatch_penalty: float
    repeat_mistake_penalty: float
    score: float
    rationale: str


def compute(
    analysis: Dict[str, Any],
    risk_profile: Optional[Dict[str, Any]] = None,
    existing_portfolio: Optional[List[Dict[str, Any]]] = None,
    similar_demo_mismatch_count: int = 0,
    similar_rejected_count: int = 0,
    similar_compile_fail_count: int = 0,
    target_monthly_growth_pct: float = 100.0,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    if _coalesce(analysis.get("trades_total")) <= 0:
        return {
            "score": 0.0,
            "growth_score": 0.0,
            "robustness_score": 0.0,
            "longevity_score": 0.0,
            "trade_confidence_score": 0.0,
            "portfolio_fit_score": 0.0,
            "risk_penalty": 100.0,
            "overfit_penalty": 100.0,
            "demo_mismatch_penalty": round(demo_mismatch_penalty(similar_demo_mismatch_count), 2),
            "repeat_mistake_penalty": round(repeat_mistake_penalty(similar_rejected_count, similar_compile_fail_count), 2),
            "weights": w,
            "rationale": "нет завершенных сделок => отклонить",
        }
    g = growth_score(analysis)
    r = robustness_score(analysis)
    lv = longevity_score(analysis)
    tc = trade_confidence_score(analysis)
    pf = portfolio_fit_score(analysis, existing_portfolio, target_monthly_growth_pct)
    rp = risk_penalty(analysis, risk_profile)
    op = overfit_penalty(analysis)
    dp = demo_mismatch_penalty(similar_demo_mismatch_count)
    mp = repeat_mistake_penalty(similar_rejected_count, similar_compile_fail_count)
    score = (
        w["growth"] * g
        + w["robustness"] * r
        + w["longevity"] * lv
        + w["trade_confidence"] * tc
        + w["portfolio_fit"] * pf
        - w["risk_penalty"] * rp
        - w["overfit_penalty"] * op
        - w["demo_mismatch_penalty"] * dp
        - w["repeat_mistake_penalty"] * mp
    )
    rationale = (
        f"рост={g:.1f}(вес {w['growth']}) устойчивость={r:.1f} длительность={lv:.1f} "
        f"сделки={tc:.1f} портфель={pf:.1f} | риск-{rp:.1f} переобучение-{op:.1f} "
        f"демо-{dp:.1f} повторы-{mp:.1f} => {score:.1f}"
    )
    return {
        "score": round(score, 2),
        "growth_score": round(g, 2),
        "robustness_score": round(r, 2),
        "longevity_score": round(lv, 2),
        "trade_confidence_score": round(tc, 2),
        "portfolio_fit_score": round(pf, 2),
        "risk_penalty": round(rp, 2),
        "overfit_penalty": round(op, 2),
        "demo_mismatch_penalty": round(dp, 2),
        "repeat_mistake_penalty": round(mp, 2),
        "weights": w,
        "rationale": rationale,
    }
