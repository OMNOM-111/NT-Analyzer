"""Shared natural-language normalization for Orchestrator commands.

The owner often types short futures symbols from a Russian keyboard or dictates
them to Telegram.  Those tokens must be canonicalized before intent routing and
before numbers are interpreted as prices.  This module deliberately performs
only high-confidence corrections: a mixed-script token is normalized when it
maps to exactly one instrument supported by the chart desktop.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Tuple


INSTRUMENT_ALIASES: Dict[str, Tuple[str, ...]] = {
    "MBT": ("mbt", "битк", "биткоин", "bitcoin", "btc"),
    "MET": ("met", "эфир", "эфириум", "ether", "eth"),
    "MNQ": ("mnq", "насдак", "нэсдак", "наздак", "nasdaq", "нэсдэк"),
    "MES": ("mes", "сипи", "сп500", "s&p", "sp500", "эс энд пи", "эсенпи"),
    "MYM": ("mym", "доу", "dow"),
    "M2K": ("m2k", "рассел", "russell"),
    "RTY": ("rty",),
    "MCL": ("mcl", "нефт", "нефть", "oil", "crude"),
    "MNG": ("mng", "газ", "natural gas", "henry hub"),
    "RB": ("rb", "бензин", "gasoline", "rbob"),
    "HO": ("ho", "печное топливо", "heating oil"),
    "MGC": ("mgc", "золот", "золото", "gold"),
    "SIL": ("sil", "серебр", "серебро", "silver"),
    "MHG": ("mhg", "медь", "copper"),
    "6E": ("евро", "euro", "eurusd", "eur", "шесть е", "шесть и"),
    "6B": ("фунт", "pound", "gbp", "шесть би", "шесть б"),
    "6J": ("иена", "йена", "yen", "jpy", "шесть джей"),
    "6A": ("осси", "aud", "australian", "шесть эй", "шесть а"),
    "6C": (
        "канадск", "канадский доллар", "cad", "canadian",
        "шесть си", "шесть с", "шестерка си", "шестёрка си",
    ),
    "6S": ("швейцарск", "швейцарский франк", "swiss franc", "chf", "шесть эс"),
    "E7": ("e7", "мини евро", "e-mini euro"),
    "6M": ("мексиканск", "мексиканский песо", "mexican peso", "mxn", "шесть эм"),
    "6N": ("новозеландск", "новозеландский доллар", "new zealand", "nzd", "шесть эн"),
    "HE": ("he", "свинина", "lean hogs", "hogs"),
    "LE": ("le", "крупный рогатый скот", "live cattle", "cattle"),
    "ZC": ("кукуруз", "corn"),
    "ZW": ("пшениц", "wheat"),
    "ZS": ("соя", "соев", "soybean"),
    "ZM": ("соевый шрот", "soybean meal"),
    "ZL": ("соевое масло", "soybean oil"),
    "ZT": ("двухлетние ноты", "2-year note", "2 year note"),
    "ZF": ("пятилетние ноты", "5-year note", "5 year note"),
    "ZN": ("трежерис", "10-year", "10 year", "ust"),
    "TN": ("ультра десятилетние ноты", "10-year ultra", "10 year ultra"),
    "ZB": ("бонд", "bond"),
    "UB": ("ультра бонд", "ultra-bond", "ultra bond"),
}

INSTRUMENT_ROOTS = frozenset(INSTRUMENT_ALIASES)

# Cyrillic glyphs which are visually indistinguishable from Latin letters in
# futures symbols.  Replacement is restricted to symbol-shaped tokens below;
# normal Russian words are never transliterated.
_SYMBOL_HOMOGLYPHS = str.maketrans({
    "А": "A", "а": "A", "В": "B", "в": "B", "С": "C", "с": "C",
    "Е": "E", "е": "E", "К": "K", "к": "K", "М": "M", "м": "M",
    "Н": "H", "н": "H", "О": "O", "о": "O", "Р": "P", "р": "P",
    "Т": "T", "т": "T", "Х": "X", "х": "X",
})


def _canonical_symbol_token(token: str) -> str:
    raw = str(token or "")
    # Normal Cyrillic words are language, not futures symbols.  In particular,
    # Russian ``не`` used to become Latin ``HE`` and route unrelated work to
    # the lean-hogs chart. Mixed-keyboard tokens (``6с``) remain eligible, as
    # do deliberately typed all-uppercase symbol lookalikes.
    if re.fullmatch(r"[А-Яа-я]{2,4}", raw) and raw != raw.upper():
        return raw
    candidate = raw.translate(_SYMBOL_HOMOGLYPHS).upper()
    return candidate if candidate in INSTRUMENT_ROOTS else raw


def normalize_command(value: Any) -> str:
    """Return a conservative, whitespace-normalized command string.

    Examples: ``6с``/``6С`` -> ``6C`` and ``шесть си`` -> ``6C``.  The
    canonical form is used for routing only; the original owner message remains
    unchanged in conversation history and audit records.
    """
    text = str(value or "").strip().replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"(?<![\w])([0-9A-Za-zА-Яа-я]{2,4})(?![\w])",
                  lambda match: _canonical_symbol_token(match.group(1)), text)
    low = text.lower()
    # Spoken aliases are replaced longest-first and only on word boundaries.
    spoken = []
    for root, aliases in INSTRUMENT_ALIASES.items():
        for alias in aliases:
            if " " in alias and alias.startswith(("шесть", "шестер", "канад")):
                spoken.append((alias, root))
    for alias, root in sorted(spoken, key=lambda row: len(row[0]), reverse=True):
        low = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", root, low, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", low).strip()


def resolve_instrument(value: Any) -> str:
    """Resolve exactly one supported root from normalized natural language."""
    text = normalize_command(value)
    low = f" {text.lower()} "
    explicit = [
        token.upper() for token in re.findall(r"(?<![A-Za-z0-9])([A-Za-z0-9]{2,4})(?![A-Za-z0-9])", text)
        if token.upper() in INSTRUMENT_ROOTS
    ]
    if explicit:
        return explicit[0]
    matches = []
    for root, aliases in INSTRUMENT_ALIASES.items():
        matched = []
        for alias in aliases:
            # Short Latin aliases such as ``he``/``le`` must be complete
            # tokens, never substrings of ordinary prose.
            if re.fullmatch(r"[a-z0-9]{1,3}", alias):
                found = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", low)
            else:
                found = alias in low
            if found:
                matched.append(len(alias))
        best = max(matched, default=0)
        if best:
            matches.append((best, root))
    matches.sort(reverse=True)
    return matches[0][1] if matches else ""


def has_unresolved_symbol(value: Any) -> bool:
    """Whether text contains a symbol-shaped token that failed resolution."""
    original = str(value or "")
    for token in re.findall(r"(?<!\w)([0-9][A-Za-zА-Яа-я]{1,3})(?!\w)", original):
        if not resolve_instrument(token):
            return True
    return False


def supported_roots() -> Iterable[str]:
    return tuple(sorted(INSTRUMENT_ROOTS))
