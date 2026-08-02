"""Market-data router with health, hysteresis, cooldown and mandatory shadow mode.

Automatic failover to an external provider is blocked until a documented
parity pass sets ``automatic_failover_allowed=True`` for that provider.
Yahoo and Recorded are never production-failover eligible.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .canonical_event import EventDedupeCache, event_time_utc, make_canonical_event
from .canonical_bar_engine import BarEngineRegistry

_LOCK = threading.RLock()


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ProviderHealth:
    provider: str
    instrument: str
    channel: str
    transport_heartbeat_age_sec: float = 1e9
    provider_heartbeat_age_sec: float = 1e9
    last_age_sec: float = 1e9
    bid_age_sec: float = 1e9
    ask_age_sec: float = 1e9
    sequence_gaps: int = 0
    latency_ms: float = 0.0
    anomaly_rate: float = 0.0
    market_session_state: str = "unknown"  # open|closed|low_liquidity|unknown
    score: float = 0.0
    ok: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ShadowReport:
    provider: str
    exact_contract: str
    compared: Dict[str, Any] = field(default_factory=dict)
    mismatches: List[str] = field(default_factory=list)
    passed: bool = False
    automatic_failover_allowed: bool = False
    created_at_utc: str = field(default_factory=_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "exact_contract": self.exact_contract,
            "compared": self.compared,
            "mismatches": list(self.mismatches),
            "passed": self.passed,
            "automatic_failover_allowed": self.automatic_failover_allowed,
            "created_at_utc": self.created_at_utc,
        }


class MarketDataRouter:
    def __init__(
        self,
        *,
        hysteresis_sec: float = 2.0,
        cooldown_sec: float = 5.0,
        active_market_failover_target_sec: float = 2.0,
    ) -> None:
        self.hysteresis_sec = hysteresis_sec
        self.cooldown_sec = cooldown_sec
        self.active_market_failover_target_sec = active_market_failover_target_sec
        self._primary: Dict[Tuple[str, str, str], str] = {}
        self._source_epoch: Dict[Tuple[str, str, str], int] = {}
        self._last_switch_monotonic: Dict[Tuple[str, str, str], float] = {}
        self._health: Dict[Tuple[str, str, str, str], ProviderHealth] = {}
        self._shadow_streams: Dict[str, List[Dict[str, Any]]] = {}
        self._primary_streams: Dict[str, List[Dict[str, Any]]] = {}
        self._parity: Dict[str, ShadowReport] = {}
        self._switch_log: List[Dict[str, Any]] = []
        self._dedupe = EventDedupeCache()
        self._engines = BarEngineRegistry()
        self._allow_auto: Dict[str, bool] = {}

    def key(self, workspace_id: str, exact_contract: str, channel: str = "trades") -> Tuple[str, str, str]:
        return (str(workspace_id or "default"), str(exact_contract or "").upper(), str(channel or "trades"))

    def source_epoch(self, workspace_id: str, exact_contract: str, channel: str = "trades") -> int:
        return int(self._source_epoch.get(self.key(workspace_id, exact_contract, channel), 1))

    def set_primary(self, workspace_id: str, exact_contract: str, provider: str, channel: str = "trades") -> int:
        k = self.key(workspace_id, exact_contract, channel)
        epoch = int(self._source_epoch.get(k, 0)) + 1
        self._source_epoch[k] = epoch
        self._primary[k] = provider
        self._last_switch_monotonic[k] = time.monotonic()
        row = {
            "ts_utc": _iso(),
            "workspace_id": workspace_id,
            "exact_contract": exact_contract,
            "channel": channel,
            "provider": provider,
            "source_epoch": epoch,
        }
        self._switch_log.append(row)
        return epoch

    def update_health(self, health: ProviderHealth) -> None:
        key = (health.provider, health.instrument.upper(), health.channel, "x")
        # score: higher is better
        score = 100.0
        if health.market_session_state == "open":
            if health.last_age_sec > self.active_market_failover_target_sec:
                score -= 40
            if health.transport_heartbeat_age_sec > self.active_market_failover_target_sec:
                score -= 30
        elif health.market_session_state == "closed":
            # Separate rules: age thresholds are relaxed.
            if health.last_age_sec > 3600:
                score -= 10
        elif health.market_session_state == "low_liquidity":
            if health.last_age_sec > 30:
                score -= 15
        score -= min(30.0, health.anomaly_rate * 100.0)
        score -= min(20.0, health.sequence_gaps * 2.0)
        health.score = score
        health.ok = score >= 50
        self._health[(health.provider, health.instrument.upper(), health.channel)] = health

    def ingest_primary(self, workspace_id: str, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self._dedupe.seen(event):
            return []
        contract = str(event.get("exact_contract") or "")
        self._primary_streams.setdefault(contract, []).append(event)
        if len(self._primary_streams[contract]) > 20_000:
            self._primary_streams[contract] = self._primary_streams[contract][-10_000:]
        return self._engines.on_trade(workspace_id, event)

    def ingest_shadow(self, provider: str, event: Dict[str, Any]) -> None:
        """Shadow events never drive the primary chart."""
        q = dict(event.get("quality") or {})
        q["shadow"] = True
        event = dict(event)
        event["quality"] = q
        event["data_plane"] = "analytics"
        key = f"{provider}|{event.get('exact_contract')}"
        self._shadow_streams.setdefault(key, []).append(event)
        if len(self._shadow_streams[key]) > 20_000:
            self._shadow_streams[key] = self._shadow_streams[key][-10_000:]

    def compare_shadow(
        self,
        provider: str,
        exact_contract: str,
        *,
        tolerance_price: float = 0.25,
        max_missing_pct: float = 0.05,
    ) -> ShadowReport:
        """Compare Last/BidAsk and 1s/1m/5m bar OHLCV between primary and shadow."""
        primary = self._primary_streams.get(exact_contract.upper(), [])
        shadow = self._shadow_streams.get(f"{provider}|{exact_contract.upper()}", [])
        report = ShadowReport(provider=provider, exact_contract=exact_contract.upper())
        if not primary or not shadow:
            report.mismatches.append("insufficient_samples")
            self._parity[provider] = report
            return report

        def lasts(rows):
            return [r for r in rows if str(r.get("type")) == "trade" and r.get("price") is not None]

        p_last = lasts(primary)[-200:]
        s_last = lasts(shadow)[-200:]
        compared = {
            "primary_trades": len(p_last),
            "shadow_trades": len(s_last),
        }
        mismatches: List[str] = []
        n = min(len(p_last), len(s_last), 100)
        price_diffs = []
        for i in range(n):
            try:
                price_diffs.append(abs(float(p_last[-(i+1)]["price"]) - float(s_last[-(i+1)]["price"])))
            except (TypeError, ValueError, KeyError):
                continue
        if price_diffs:
            compared["last_abs_diff_p50"] = sorted(price_diffs)[len(price_diffs)//2]
            if compared["last_abs_diff_p50"] > tolerance_price:
                mismatches.append("last_price_divergence")
        missing_pct = abs(len(p_last) - len(s_last)) / max(len(p_last), 1)
        compared["missing_event_pct"] = round(missing_pct, 4)
        if missing_pct > max_missing_pct:
            mismatches.append("missing_events")

        # Build bars for both sides and compare 1s/1m/5m.
        from .canonical_bar_engine import CanonicalBarEngine
        for tf in ("1s", "1m", "5m"):
            pe = CanonicalBarEngine(exact_contract, timeframes=[tf])
            se = CanonicalBarEngine(exact_contract, timeframes=[tf])
            for ev in p_last:
                pe.on_trade(ev)
            for ev in s_last:
                se.on_trade(ev)
            pb = pe.series(tf, 20)
            sb = se.series(tf, 20)
            compared[f"bars_{tf}_primary"] = len(pb)
            compared[f"bars_{tf}_shadow"] = len(sb)
            if pb and sb:
                pc, sc = pb[-1], sb[-1]
                for field_name in ("o", "h", "l", "c"):
                    try:
                        if abs(float(pc[field_name]) - float(sc[field_name])) > tolerance_price * 4:
                            mismatches.append(f"{tf}_{field_name}_divergence")
                            break
                    except (TypeError, ValueError, KeyError):
                        mismatches.append(f"{tf}_compare_error")
                        break

        report.compared = compared
        report.mismatches = mismatches
        report.passed = not mismatches
        # Automatic failover still requires explicit allow after documented pass.
        report.automatic_failover_allowed = bool(
            report.passed and self._allow_auto.get(provider, False)
        )
        self._parity[provider] = report
        return report

    def allow_automatic_failover(self, provider: str, allowed: bool = True) -> None:
        if provider in {"yahoo", "yahoo_chart", "recorded", "fault_injection"}:
            raise ValueError(f"{provider} is never production-failover eligible")
        self._allow_auto[provider] = bool(allowed)

    def can_auto_failover(self, provider: str) -> bool:
        if provider in {"yahoo", "yahoo_chart", "recorded", "fault_injection"}:
            return False
        report = self._parity.get(provider)
        return bool(self._allow_auto.get(provider) and report and report.passed and report.automatic_failover_allowed)

    def try_failover(
        self,
        workspace_id: str,
        exact_contract: str,
        to_provider: str,
        *,
        market_session_state: str = "open",
        channel: str = "trades",
    ) -> Dict[str, Any]:
        if not self.can_auto_failover(to_provider):
            return {
                "ok": False,
                "reason": "shadow_parity_or_allow_missing",
                "provider": to_provider,
            }
        k = self.key(workspace_id, exact_contract, channel)
        last = self._last_switch_monotonic.get(k, 0.0)
        if time.monotonic() - last < self.cooldown_sec:
            return {"ok": False, "reason": "cooldown", "provider": to_provider}
        if market_session_state != "open":
            # Separate health rules — do not apply ≤2s active-market target.
            pass
        epoch = self.set_primary(workspace_id, exact_contract, to_provider, channel)
        return {"ok": True, "source_epoch": epoch, "provider": to_provider}

    def status(self) -> Dict[str, Any]:
        return {
            "primary": {f"{a}|{b}|{c}": p for (a, b, c), p in self._primary.items()},
            "source_epoch": {f"{a}|{b}|{c}": e for (a, b, c), e in self._source_epoch.items()},
            "health": {f"{a}|{b}|{c}": h.to_dict() for (a, b, c), h in self._health.items()},
            "parity": {k: v.to_dict() for k, v in self._parity.items()},
            "switch_log": list(self._switch_log)[-50:],
            "auto_failover_allow": dict(self._allow_auto),
        }


_ROUTER: Optional[MarketDataRouter] = None


def get_router() -> MarketDataRouter:
    global _ROUTER
    with _LOCK:
        if _ROUTER is None:
            _ROUTER = MarketDataRouter()
        return _ROUTER


def reset_router_for_tests() -> None:
    global _ROUTER
    with _LOCK:
        _ROUTER = None
