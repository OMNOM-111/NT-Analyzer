"""Parse free-form AI Strategy Lab user goals into conservative constraints."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


ROOT_ALIASES = {
    "MNQ": ("mnq", "micro nasdaq", "nasdaq", "nq"),
    "MES": ("mes", "micro es", "s&p", "sp500", "es"),
    "MGC": ("mgc", "micro gold", "gold", "золото"),
    "MCL": ("mcl", "micro crude", "crude", "oil", "нефть"),
}


def _clean_number(text: str) -> Optional[float]:
    raw = re.sub(r"[^\d.,kK]", "", text or "")
    if not raw:
        return None
    multiplier = 1000.0 if raw.lower().endswith("k") else 1.0
    raw = raw.rstrip("kK").replace(",", "").replace(" ", "")
    try:
        return float(raw) * multiplier
    except ValueError:
        return None


def _extract_capital(goal: str) -> Optional[float]:
    patterns = [
        r"(?:budget|capital|account|бюджет|капитал|сч[её]т)\s*(?:\$|usd)?\s*([\d][\d,\s.]*k?)",
        r"(?:\$|usd)\s*([\d][\d,\s.]*k?)",
        r"([\d][\d,\s.]*k?)\s*(?:usd|dollars|\$|доллар)",
    ]
    for pat in patterns:
        m = re.search(pat, goal, flags=re.IGNORECASE)
        if m:
            value = _clean_number(m.group(1))
            if value and value > 0:
                return value
    return None


def _extract_root(goal: str) -> Optional[str]:
    low = goal.lower()
    for root, aliases in ROOT_ALIASES.items():
        for alias in aliases:
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", low):
                return root
    return None


def _extract_pattern(goal: str) -> Optional[str]:
    low = goal.lower()
    checks = [
        ("HeadAndShoulders", ("head and shoulders", "head-and-shoulders", "голова и плечи")),
        ("DonchianChannel", ("donchian", "дончиан", "channel breakout")),
        ("OpeningRangeBreakout", ("orb", "opening range", "open range", "диапазон открытия")),
        ("VwapPullback", ("vwap", "ввап")),
        ("RsiEmaPullback", ("rsi", "ema", "pullback", "откат")),
        ("LiquiditySweep", ("liquidity sweep", "sweep", "ликвид")),
        ("CompressionBreakout", ("compression", "сжатие", "squeeze")),
    ]
    def requested(needle: str) -> bool:
        if needle.isascii() and re.fullmatch(r"[a-z0-9]+", needle):
            matches = re.finditer(
                rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
                low,
            )
        else:
            matches = re.finditer(re.escape(needle), low)
        for match in matches:
            clause_start = max(
                low.rfind(".", 0, match.start()),
                low.rfind("!", 0, match.start()),
                low.rfind("?", 0, match.start()),
                low.rfind("\n", 0, match.start()),
            )
            prefix = low[clause_start + 1:match.start()]
            if any(marker in prefix for marker in (
                "не повторяй",
                "не используй",
                "избегай",
                "без ",
                "avoid",
                "do not use",
                "don't use",
                "without ",
            )):
                continue
            return True
        return False

    for name, needles in checks:
        if any(requested(n) for n in needles):
            return name
    return None


def _extract_trade_frequency(goal: str) -> str:
    low = goal.lower()
    if any(x in low for x in ("много сдел", "high frequency", "часто", "scalp", "скальп")):
        return "higher"
    if any(x in low for x in ("мало сдел", "low frequency", "редко", "не overtrade", "не овер")):
        return "lower"
    return "balanced"


def parse_user_goal(goal: Optional[str], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Best-effort parser for UI/API user goals.

    The parser is intentionally conservative: it extracts hard constraints but
    leaves market hypothesis selection to the knowledge-aware idea stage.
    """
    args = args or {}
    text = str(goal or args.get("goal") or args.get("user_goal") or "").strip()
    explicit_root = (
        args.get("target_root") or args.get("root") or args.get("user_pref_root")
        or args.get("instrument_root")
    )
    explicit_capital = args.get("capital") if args.get("capital") not in (None, "") else args.get("user_capital")
    capital = None
    try:
        capital = float(explicit_capital) if explicit_capital not in (None, "") else None
    except (TypeError, ValueError):
        capital = None
    parsed_capital = _extract_capital(text)
    root = str(explicit_root).upper() if explicit_root else _extract_root(text)
    pattern = _extract_pattern(text)
    frequency = _extract_trade_frequency(text)
    constraints = {
        "raw_goal": text,
        "target_root": root,
        "capital": capital or parsed_capital,
        "pattern": pattern,
        "trade_frequency": frequency,
        "budget_sensitive": bool((capital or parsed_capital or 0) <= 10_000),
        "requires_knowledge_context": True,
        "historical_only": True,
        "live_or_paper_forbidden": True,
    }
    if not pattern and root == "MNQ":
        constraints["reference_pattern"] = "DonchianChannel/WEX-007 near break-even, preferably lower turnover than 15m"
    elif pattern:
        constraints["reference_pattern"] = pattern
    else:
        constraints["reference_pattern"] = "auto_select_from_reference_library"
    return constraints
