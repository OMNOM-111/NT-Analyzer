"""Instrument registry: exact contract ≠ continuous; explicit maps only.

Never silently substitute a continuous symbol for an exact contract.
``allow_continuous=True`` is required to expose Databento ``ROOT.v.0`` style ids,
and only for history/analytics planes — never as a hidden chart swap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

_CONTRACT_RE = re.compile(r"^([A-Z0-9]+)\s+(\d{2})-(\d{2})$")

_TICK_SIZES = {
    "MNQ": 0.25, "MES": 0.25, "MGC": 0.10, "NQ": 0.25, "ES": 0.25,
    "GC": 0.10, "MCL": 0.01, "CL": 0.01, "MYM": 1.0, "YM": 1.0,
    "M2K": 0.10, "RTY": 0.10,
}

_DATABENTO_CONTINUOUS = {
    "MNQ": "MNQ.v.0", "MES": "MES.v.0", "MGC": "MGC.v.0",
    "NQ": "NQ.v.0", "ES": "ES.v.0", "GC": "GC.v.0",
    "MCL": "MCL.v.0", "CL": "CL.v.0",
}

_YAHOO_DELAYED = {
    "MNQ": "MNQ=F", "MES": "MES=F", "MGC": "MGC=F",
    "NQ": "NQ=F", "ES": "ES=F", "GC": "GC=F",
}


@dataclass
class InstrumentDef:
    root: str
    exact_contract: str = ""
    expiry: str = ""
    tick_size: float = 0.0
    exchange: str = "CME"
    nt_symbol: str = ""
    databento_continuous: str = ""
    yahoo_symbol: str = ""
    rollover_note: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "exact_contract": self.exact_contract,
            "expiry": self.expiry,
            "tick_size": self.tick_size,
            "exchange": self.exchange,
            "nt_symbol": self.nt_symbol or self.exact_contract,
            "databento_continuous": self.databento_continuous,
            "yahoo_symbol": self.yahoo_symbol,
            "rollover_note": self.rollover_note,
            "metadata": dict(self.metadata),
            "is_exact": bool(self.exact_contract and " " in self.exact_contract),
            "is_continuous": False,
        }


class InstrumentRegistry:
    def __init__(self) -> None:
        self._by_exact: Dict[str, InstrumentDef] = {}
        self._roots: Dict[str, InstrumentDef] = {}

    def register(self, row: InstrumentDef) -> None:
        root = row.root.upper()
        row.root = root
        if row.exact_contract:
            key = row.exact_contract.upper()
            row.exact_contract = key
            self._by_exact[key] = row
        self._roots[root] = row

    def get_exact(self, symbol: str) -> Optional[InstrumentDef]:
        key = " ".join(str(symbol or "").strip().upper().split())
        return self._by_exact.get(key)

    def get_root(self, root: str) -> Optional[InstrumentDef]:
        return self._roots.get(str(root or "").strip().upper())

    def parse(self, symbol: Any) -> Tuple[str, str, bool]:
        """Return (root, exact_or_empty, is_exact)."""
        raw = " ".join(str(symbol or "").strip().upper().split())
        if not raw:
            return "", "", False
        match = _CONTRACT_RE.match(raw)
        if match:
            return match.group(1), raw, True
        if " " in raw:
            return raw.split(" ", 1)[0], raw, True
        return raw, "", False

    def resolve_exact(
        self,
        symbol: Any,
        *,
        allow_continuous: bool = False,
        data_plane: str = "display",
    ) -> Dict[str, Any]:
        """Resolve a user/UI symbol to an exact contract when possible.

        Continuous Databento ids are returned ONLY when ``allow_continuous`` is
        True and never silently substituted for chart exact contracts.
        """
        root, exact, is_exact = self.parse(symbol)
        if is_exact and exact:
            row = self.get_exact(exact) or self._synthesize(root, exact)
            out = row.to_dict()
            out["requested"] = str(symbol or "")
            out["resolved"] = exact
            out["resolution"] = "exact"
            out["allow_continuous"] = False
            return out

        # Explicit continuous request for analytics/history only — never a
        # hidden swap for display/strategy/execution chart sources.
        if allow_continuous and data_plane in {"analytics", "history_replay"}:
            continuous = _DATABENTO_CONTINUOUS.get(root, f"{root}.v.0")
            out = self._synthesize(root, "").to_dict()
            out["requested"] = str(symbol or "")
            out["resolved"] = continuous
            out["resolution"] = "continuous_explicit"
            out["is_continuous"] = True
            out["is_exact"] = False
            out["allow_continuous"] = True
            out["databento_continuous"] = continuous
            return out

        # Prefer live/catalog resolution via existing market_data helper.
        try:
            from . import market_data
            resolved = market_data.resolve_chart_instrument(root)
        except Exception:
            resolved = root
        r_root, r_exact, r_is_exact = self.parse(resolved)
        if r_is_exact and r_exact:
            row = self.get_exact(r_exact) or self._synthesize(r_root, r_exact)
            out = row.to_dict()
            out["requested"] = str(symbol or "")
            out["resolved"] = r_exact
            out["resolution"] = "root_to_exact"
            out["allow_continuous"] = False
            return out

        out = self._synthesize(root, "").to_dict()
        out["requested"] = str(symbol or "")
        out["resolved"] = root
        out["resolution"] = "root_unresolved"
        out["allow_continuous"] = False
        out["warning"] = "exact_contract_unavailable"
        return out

    def continuous_symbol(self, root: str) -> str:
        key = str(root or "").strip().upper()
        return _DATABENTO_CONTINUOUS.get(key, f"{key}.v.0")

    def yahoo_symbol(self, root: str) -> str:
        key = str(root or "").strip().upper()
        return _YAHOO_DELAYED.get(key, f"{key}=F")

    def tick_size(self, symbol: Any) -> float:
        root, _, _ = self.parse(symbol)
        return float(_TICK_SIZES.get(root, 0.0))

    def _synthesize(self, root: str, exact: str) -> InstrumentDef:
        expiry = ""
        if exact:
            parts = exact.split(" ", 1)
            if len(parts) == 2:
                expiry = parts[1]
        return InstrumentDef(
            root=root,
            exact_contract=exact,
            expiry=expiry,
            tick_size=_TICK_SIZES.get(root, 0.0),
            nt_symbol=exact or root,
            databento_continuous=_DATABENTO_CONTINUOUS.get(root, f"{root}.v.0"),
            yahoo_symbol=_YAHOO_DELAYED.get(root, f"{root}=F"),
        )

    def load_from_catalog(self) -> int:
        """Load NT catalog rows when available."""
        try:
            from . import jobqueue
            catalog = jobqueue.read_instruments_catalog() or {}
        except Exception:
            return 0
        count = 0
        for row in catalog.get("instruments") or []:
            if not isinstance(row, dict):
                continue
            instrument = str(row.get("instrument") or row.get("symbol") or "").strip().upper()
            root = str(row.get("root") or instrument.split(" ")[0]).upper()
            if not root:
                continue
            self.register(InstrumentDef(
                root=root,
                exact_contract=instrument if " " in instrument else "",
                expiry=str(row.get("expiry") or ""),
                tick_size=float(row.get("tick_size") or _TICK_SIZES.get(root, 0.0) or 0.0),
                exchange=str(row.get("exchange") or "CME"),
                nt_symbol=instrument or root,
                databento_continuous=_DATABENTO_CONTINUOUS.get(root, f"{root}.v.0"),
                yahoo_symbol=_YAHOO_DELAYED.get(root, f"{root}=F"),
                metadata={
                    "data_first": row.get("data_first"),
                    "data_last": row.get("data_last"),
                    "has_minute_data": row.get("has_minute_data"),
                },
            ))
            count += 1
        return count

    def ensure_core_roots(self) -> None:
        for root in ("MNQ", "MGC", "MES", "NQ", "ES", "GC", "MCL"):
            if root not in self._roots:
                self.register(self._synthesize(root, ""))


_REGISTRY: Optional[InstrumentRegistry] = None


def get_registry() -> InstrumentRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        reg = InstrumentRegistry()
        reg.ensure_core_roots()
        reg.load_from_catalog()
        _REGISTRY = reg
    return _REGISTRY


def reset_registry_for_tests() -> None:
    global _REGISTRY
    _REGISTRY = None
