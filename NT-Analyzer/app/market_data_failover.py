"""Independent market-data providers, automatic failover and gap recovery.

The NinjaTrader bridge remains the preferred source when it is healthy.  This
module deliberately has no dependency on NinjaTrader and can therefore keep
chart-only workflows alive after the terminal or bridge stops.

Two external adapters are available:

* Databento historical HTTP (production-grade, requires ``DATABENTO_API_KEY``
  or ``NTA_DATABENTO_API_KEY``);
* Yahoo Chart (public best-effort fallback, enabled by default for charts only).

External bars are display/research data.  They are never an authorization to
place live orders and are never written into the NinjaTrader command queues.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import local_secrets, market_data_live_adapters, owner_market_data_gateway, runtime_env


class MarketDataProviderError(RuntimeError):
    pass


_LOCK = threading.RLock()
_CACHE: Dict[str, Dict[str, Any]] = {}
_HEALTH: Dict[str, Dict[str, Any]] = {}
_LAST_SELECTION: Dict[str, Any] = {}
_FAILURES_BEFORE_COOLDOWN = 3
_COOLDOWN_SEC = 60
# Do not flap a chart back to the preferred provider after one good probe.  A
# provider that has just reconnected must stay healthy for this interval before
# it replaces the currently-serving credentialed provider.
_PRIMARY_RETURN_STABILITY_SEC = 20
_PRIMARY_PROBE_INTERVAL_SEC = 10
_EXACT_FUTURES_CONTRACT_RE = re.compile(r"^[A-Z0-9]+\s+\d{2}-\d{2}$")
_TIMEFRAME_SECONDS = {
    "1s": 1, "5s": 5, "15s": 15, "30s": 30,
    "1m": 60, "2m": 120, "3m": 180, "5m": 300, "10m": 600, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1D": 86400,
    "1W": 7 * 86400, "1M": 31 * 86400,
}
_YAHOO_SYMBOLS = {
    "MNQ": "MNQ=F", "MES": "MES=F", "MGC": "MGC=F", "NQ": "NQ=F",
    "ES": "ES=F", "GC": "GC=F", "MCL": "MCL=F", "CL": "CL=F",
    "MYM": "MYM=F", "YM": "YM=F", "M2K": "M2K=F", "RTY": "RTY=F",
    "6A": "6A=F", "6B": "6B=F", "6C": "6C=F", "6E": "6E=F",
    "6J": "6J=F", "ZN": "ZN=F", "ZB": "ZB=F",
}
_TICK_SIZES = {
    "MNQ": 0.25, "MES": 0.25, "MGC": 0.10, "NQ": 0.25, "ES": 0.25,
    "GC": 0.10, "MCL": 0.01, "CL": 0.01, "MYM": 1.0, "YM": 1.0,
    "M2K": 0.10, "RTY": 0.10, "6A": 0.0001, "6B": 0.0001,
    "6C": 0.00005, "6E": 0.00005, "6J": 0.0000005,
}


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _runtime_dir() -> Path:
    from . import runtime
    override = getattr(runtime._RUNTIME_CONTEXT, "runtime_dir", "")
    path = Path(override) if override else runtime_env.data_path("runtime", project_root=_root())
    path.mkdir(parents=True, exist_ok=True)
    return path


def _status_path() -> Path:
    return _runtime_dir() / "market_data_failover_status.json"


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        try:
            number = float(value)
            if number > 10_000_000_000:
                number /= 1_000_000_000.0
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _timeframe(value: Any) -> str:
    raw = str(value or "5m").strip()
    match = re.fullmatch(r"(\d+)\s*([smhdwMDW])", raw)
    if not match:
        raise MarketDataProviderError(f"Unsupported timeframe: {value}")
    number, suffix = match.group(1), match.group(2)
    if suffix in {"d", "D"}:
        normalized = f"{number}D"
    elif suffix in {"w", "W"}:
        normalized = f"{number}W"
    elif suffix == "M":
        normalized = f"{number}M"
    else:
        normalized = f"{number}{suffix.lower()}"
    if normalized not in _TIMEFRAME_SECONDS:
        raise MarketDataProviderError(f"Unsupported timeframe: {value}")
    return normalized


def timeframe_seconds(value: Any) -> int:
    return _TIMEFRAME_SECONDS[_timeframe(value)]


def freshness_limit_sec(value: Any) -> int:
    tf = _timeframe(value)
    if tf == "1D":
        return 172800
    return max(180, timeframe_seconds(tf) * 3)


def _root_symbol(instrument: Any) -> str:
    return str(instrument or "").strip().upper().split(" ")[0]


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _bar_time(row: Any) -> Optional[datetime]:
    if not isinstance(row, dict):
        return None
    return _parse_time(row.get("t") or row.get("time_utc") or row.get("time") or row.get("ts_event"))


def normalize_bars(rows: Iterable[Any]) -> List[Dict[str, Any]]:
    by_time: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        dt = _bar_time(row)
        o = _finite(row.get("o", row.get("open")))
        h = _finite(row.get("h", row.get("high")))
        low = _finite(row.get("l", row.get("low")))
        c = _finite(row.get("c", row.get("close")))
        volume = _finite(row.get("v", row.get("volume")))
        if dt is None or None in (o, h, low, c):
            continue
        if min(o, h, low, c) <= 0 or h < low or max(o, c) > h or min(o, c) < low:
            continue
        stamp = _iso(dt)
        by_time[stamp] = {
            "t": stamp, "o": o, "h": h, "l": low, "c": c,
            "v": max(0.0, volume or 0.0),
        }
    return [by_time[key] for key in sorted(by_time)]


def resample_bars(rows: Iterable[Any], timeframe: Any) -> List[Dict[str, Any]]:
    target = timeframe_seconds(timeframe)
    bars = normalize_bars(rows)
    if target <= 60:
        return bars
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for row in bars:
        dt = _bar_time(row)
        if dt is None:
            continue
        epoch = int(dt.timestamp())
        buckets.setdefault(epoch - (epoch % target), []).append(row)
    result = []
    for epoch in sorted(buckets):
        group = buckets[epoch]
        result.append({
            "t": _iso(datetime.fromtimestamp(epoch, tz=timezone.utc)),
            "o": group[0]["o"], "h": max(row["h"] for row in group),
            "l": min(row["l"] for row in group), "c": group[-1]["c"],
            "v": round(sum(float(row.get("v") or 0) for row in group), 8),
        })
    return result


def series_freshness(rows: Iterable[Any], timeframe: Any) -> Dict[str, Any]:
    bars = normalize_bars(rows)
    latest = _bar_time(bars[-1]) if bars else None
    age = max(0.0, (datetime.now(timezone.utc) - latest).total_seconds()) if latest else None
    limit = freshness_limit_sec(timeframe)
    return {
        "fresh": bool(age is not None and age <= limit),
        "stale": bool(age is not None and age > limit),
        "age_sec": age,
        "max_age_sec": limit,
        "data_as_of_utc": _iso(latest) if latest else "",
    }


def detect_gaps(rows: Iterable[Any], timeframe: Any, *, max_report: int = 40) -> List[Dict[str, Any]]:
    bars = normalize_bars(rows)
    expected = timeframe_seconds(timeframe)
    gaps: List[Dict[str, Any]] = []
    for previous, current in zip(bars, bars[1:]):
        before, after = _bar_time(previous), _bar_time(current)
        if before is None or after is None:
            continue
        delta = int((after - before).total_seconds())
        if delta <= int(expected * 1.5):
            continue
        gaps.append({
            "after_utc": previous["t"], "before_utc": current["t"],
            "duration_sec": delta,
            "missing_intervals": max(1, int(delta // expected) - 1),
            "session_break_likely": delta >= max(14400, expected * 20),
        })
        if len(gaps) >= max(1, int(max_report)):
            break
    return gaps


def _quote(last: float, root: str, *, source: str, actual_bid: Any = None,
           actual_ask: Any = None) -> Dict[str, Any]:
    bid, ask = _finite(actual_bid), _finite(actual_ask)
    estimated = bid is None or ask is None
    if estimated:
        tick = _TICK_SIZES.get(root, max(abs(last) * 0.00001, 0.01))
        bid, ask = last - tick, last + tick
    return {
        "bid": round(float(bid), 8), "ask": round(float(ask), 8),
        "last": round(float(last), 8), "bid_ask_estimated": estimated,
        "source": source,
        "note": "Bid/ask рассчитаны вокруг last и не используются для live-исполнения." if estimated else "",
    }


class MarketDataProvider:
    name = "provider"
    independent = True
    tier = "external"

    def configured(self) -> bool:
        return True

    def fetch(self, instrument: str, timeframe: str, limit: int) -> Dict[str, Any]:
        raise NotImplementedError

    def public_status(self) -> Dict[str, Any]:
        return {
            "name": self.name, "configured": self.configured(),
            "independent": self.independent, "tier": self.tier,
        }


class YahooChartProvider(MarketDataProvider):
    name = "yahoo_chart"
    tier = "best_effort_public"

    def configured(self) -> bool:
        return str(os.environ.get("NTA_MARKET_DATA_PUBLIC_FALLBACK", "1")).strip().lower() not in {
            "0", "false", "no", "off", "disabled",
        }

    def public_status(self) -> Dict[str, Any]:
        return {
            "name": self.name, "configured": self.configured(),
            "independent": self.independent, "tier": self.tier,
            "implementation_state": "ADAPTER_READY",
            "runtime_state": "DISABLED" if not self.configured() else "STALE",
            "capability": "DELAYED_OR_UNVERIFIED",
            "live_eligible": False,
            "production_failover_eligible": False,
        }

    def fetch(self, instrument: str, timeframe: str, limit: int) -> Dict[str, Any]:
        tf = _timeframe(timeframe)
        root = _root_symbol(instrument)
        symbol = _YAHOO_SYMBOLS.get(root)
        if not symbol:
            raise MarketDataProviderError(f"Yahoo mapping is not configured for {root or instrument}")
        interval = {
            "1m": "1m", "3m": "1m", "5m": "5m", "15m": "15m",
            "30m": "30m", "1h": "60m", "4h": "60m", "1D": "1d",
        }[tf]
        range_name = "5d" if interval == "1m" else ("1mo" if interval != "1d" else "1y")
        encoded = urllib.parse.quote(symbol, safe="")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            f"?interval={interval}&range={range_name}&includePrePost=false&events=div%2Csplits"
        )
        request = urllib.request.Request(url, headers={
            "Accept": "application/json", "User-Agent": "StratForge-MarketData/1.0",
        })
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                doc = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise MarketDataProviderError(f"Yahoo Chart request failed: {type(exc).__name__}: {exc}") from exc
        chart = doc.get("chart") if isinstance(doc, dict) else {}
        error = chart.get("error") if isinstance(chart, dict) else None
        results = chart.get("result") if isinstance(chart, dict) else None
        if error or not isinstance(results, list) or not results:
            raise MarketDataProviderError(f"Yahoo Chart returned no series: {error or 'empty result'}")
        result = results[0] if isinstance(results[0], dict) else {}
        timestamps = result.get("timestamp") if isinstance(result.get("timestamp"), list) else []
        indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
        quote_rows = indicators.get("quote") if isinstance(indicators.get("quote"), list) else []
        quote_row = quote_rows[0] if quote_rows and isinstance(quote_rows[0], dict) else {}
        raw: List[Dict[str, Any]] = []
        for index, stamp in enumerate(timestamps):
            def at(name: str) -> Any:
                values = quote_row.get(name) if isinstance(quote_row.get(name), list) else []
                return values[index] if index < len(values) else None
            raw.append({
                "t": stamp, "o": at("open"), "h": at("high"), "l": at("low"),
                "c": at("close"), "v": at("volume"),
            })
        bars = normalize_bars(raw)
        if interval in {"1m", "60m"} and timeframe_seconds(tf) != timeframe_seconds(
            "1m" if interval == "1m" else "1h"
        ):
            bars = resample_bars(bars, tf)
        bars = bars[-max(1, min(int(limit or 1500), 50000)):]
        if not bars:
            raise MarketDataProviderError("Yahoo Chart returned no valid OHLCV bars")
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        last = _finite(meta.get("regularMarketPrice")) or float(bars[-1]["c"])
        fetched_at = _iso()
        fresh = series_freshness(bars, tf)
        # Yahoo is delayed/unverified — NEVER claim LIVE for production charts.
        fresh = dict(fresh)
        fresh["fresh"] = False
        fresh["stale"] = True
        fresh["delayed"] = True
        fresh["live_eligible"] = False
        return {
            "instrument": str(instrument or root), "bars": bars, "total": len(bars),
            "raw_total": len(raw), "live": False,
            "status": "external_stale",
            "requested_timeframe": tf, "matched_timeframe": tf,
            "source": {
                "kind": "external_provider", "provider": self.name,
                "provider_symbol": symbol, "independent": True, "tier": self.tier,
                "updated_at_utc": fresh["data_as_of_utc"], "fetched_at_utc": fetched_at,
                "age_sec": fresh["age_sec"], "fresh": False,
                "delayed": True, "live_eligible": False,
                "implementation_state": "ADAPTER_READY",
                "runtime_state": "STALE",
                "capability": "DELAYED_OR_UNVERIFIED",
            },
            "freshness": fresh,
            "quote": _quote(last, root, source=self.name),
            "note": "Yahoo delayed/public fallback — не live и не eligible для automatic failover.",
            "data_plane": "display",
            "market_data_available": False,
        }


class DatabentoProvider(MarketDataProvider):
    name = "databento"
    tier = "credentialed_market_data"

    def _key(self) -> str:
        # Development credentials are deliberately local-only. Load them here
        # too (not only through the TopstepX adapter) so status and failover
        # agree after a local secret-store update.
        local_secrets.apply()
        return str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()

    def configured(self) -> bool:
        return bool(self._key() and not market_data_live_adapters.is_mock_key(self._key(), "db"))

    def public_status(self) -> Dict[str, Any]:
        configured = self.configured()
        raw_key = self._key()
        placeholder = bool(raw_key and market_data_live_adapters.is_mock_key(raw_key, "db"))
        credential_state = "configured_unverified" if configured else ("placeholder" if placeholder else "missing")
        return {
            "name": self.name, "configured": configured,
            "independent": self.independent, "tier": self.tier,
            "implementation_state": "ADAPTER_READY" if configured else "ADAPTER_READY",
            "runtime_state": "DISABLED" if not configured else "CONNECTING",
            "capability": "REALTIME_PRODUCTION" if configured else "ENTITLEMENT_MISSING",
            "live_eligible": configured,
            "production_failover_eligible": configured,
            "note": "Live key required before PRODUCTION failover eligibility.",
            "credential_state": credential_state,
            "dataset": str(os.environ.get("NTA_DATABENTO_DATASET") or "GLBX.MDP3"),
            "auth_state": "not_attempted" if configured else "not_applicable",
        }

    def fetch(self, instrument: str, timeframe: str, limit: int) -> Dict[str, Any]:
        key = self._key()
        if not key:
            raise MarketDataProviderError("Databento API key is not configured")
        tf = _timeframe(timeframe)
        root = _root_symbol(instrument)
        if not root:
            raise MarketDataProviderError("Instrument is required")
        base_tf = "1m" if tf in {"1m", "3m", "5m", "15m", "30m"} else ("1h" if tf in {"1h", "4h"} else "1D")
        schema = {"1m": "ohlcv-1m", "1h": "ohlcv-1h", "1D": "ohlcv-1d"}[base_tf]
        multiplier = max(1, timeframe_seconds(tf) // timeframe_seconds(base_tf))
        requested = max(100, min(50000, int(limit or 1500))) * multiplier
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=timeframe_seconds(base_tf) * requested * 2)
        form = urllib.parse.urlencode({
            "dataset": str(os.environ.get("NTA_DATABENTO_DATASET") or "GLBX.MDP3"),
            "symbols": f"{root}.v.0", "schema": schema, "stype_in": "continuous",
            "start": _iso(start), "end": _iso(end), "encoding": "json",
            "pretty_px": "true", "pretty_ts": "true", "map_symbols": "true",
            "limit": str(min(requested * 2, 50000)),
        }).encode("ascii")
        auth = base64.b64encode((key + ":").encode("utf-8")).decode("ascii")
        request = urllib.request.Request(
            "https://hist.databento.com/v0/timeseries.get_range", data=form, method="POST",
            headers={"Accept": "application/json", "Authorization": "Basic " + auth,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                lines = response.read().decode("utf-8").splitlines()
        except Exception as exc:
            raise MarketDataProviderError(f"Databento request failed: {type(exc).__name__}: {exc}") from exc
        raw: List[Dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            header = row.get("hd") if isinstance(row.get("hd"), dict) else {}
            raw.append({
                "t": row.get("ts_event") or header.get("ts_event"),
                "o": row.get("open"), "h": row.get("high"), "l": row.get("low"),
                "c": row.get("close"), "v": row.get("volume"),
            })
        bars = normalize_bars(raw)
        if tf != base_tf:
            bars = resample_bars(bars, tf)
        bars = bars[-max(1, min(int(limit or 1500), 50000)):]
        if not bars:
            raise MarketDataProviderError("Databento returned no valid OHLCV bars")
        fresh = series_freshness(bars, tf)
        return {
            "instrument": str(instrument or root), "bars": bars, "total": len(bars),
            "raw_total": len(raw), "live": fresh["fresh"],
            "status": "external_live" if fresh["fresh"] else "external_stale",
            "requested_timeframe": tf, "matched_timeframe": tf,
            "source": {
                "kind": "external_provider", "provider": self.name,
                "provider_symbol": f"{root}.v.0", "independent": True, "tier": self.tier,
                "updated_at_utc": fresh["data_as_of_utc"], "fetched_at_utc": _iso(),
                "age_sec": fresh["age_sec"], "fresh": fresh["fresh"],
            },
            "freshness": fresh,
            "quote": _quote(float(bars[-1]["c"]), root, source=self.name),
            "note": "Независимый Databento OHLCV поток; live-исполнение остаётся отдельным контуром.",
        }


class TopstepXProvider(MarketDataProvider):
    name = "topstepx"
    tier = "user_owned_credentialed_market_data"
    _adapter_lock = threading.RLock()
    _adapter_instance: Any = None
    _credential_fingerprint = ""

    @staticmethod
    def _settings() -> Dict[str, Any]:
        return market_data_live_adapters.TopstepXProjectXAdapter.settings()

    @staticmethod
    def _fingerprint(cfg: Dict[str, Any]) -> str:
        material = {
            "username": str(cfg.get("username") or ""),
            "api_key": str(cfg.get("api_key") or ""),
            "requested": bool(cfg.get("requested")),
            "policy_allowed": bool(cfg.get("policy_allowed")),
            "data_mode": str(cfg.get("data_mode") or ""),
            "gateway_role": "consumer" if owner_market_data_gateway.should_consume() else (
                "hub" if owner_market_data_gateway.should_open_direct_hub() else "none"
            ),
            "gateway_url": owner_market_data_gateway.gateway_url() if owner_market_data_gateway.should_consume() else "",
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def configured(self) -> bool:
        if owner_market_data_gateway.should_consume():
            return True
        if not owner_market_data_gateway.should_open_direct_hub():
            return False
        cfg = self._settings()
        return bool(
            cfg["credentials_present"] and cfg["requested"]
            and cfg["policy_allowed"] and cfg["data_mode"] != "invalid"
        )

    def public_status(self) -> Dict[str, Any]:
        cfg = self._settings()
        configured = self.configured()
        adapter = self.__class__._adapter_instance
        if not configured or self.__class__._credential_fingerprint != self._fingerprint(cfg):
            adapter = None
        runtime_health = adapter.health() if adapter is not None else {}
        runtime_state = str(runtime_health.get("runtime_state") or "")
        if not runtime_state:
            runtime_state = "CONNECTING" if configured else (
                "POLICY_BLOCKED" if not cfg["policy_allowed"] else "DISABLED"
            )
        return {
            "name": self.name,
            "configured": configured,
            "independent": self.independent,
            "tier": self.tier,
            "implementation_state": "ADAPTER_READY",
            "runtime_state": runtime_state,
            "capability": "REALTIME_READ_ONLY" if configured else "ENTITLEMENT_OR_POLICY_MISSING",
            "live_eligible": configured,
            "production_failover_eligible": configured,
            "read_only": True,
            "trade_routing": False,
            "data_mode": cfg["data_mode"],
            "username_configured": cfg["username_configured"],
            "api_key_configured": cfg["api_key_configured"],
            "remote_environment": cfg["remote_environment"],
            "remote_server_authorized": cfg["remote_server_authorized"],
            "redistribution_authorized": cfg["redistribution_authorized"],
            "blocking_reasons": list(cfg["blocking_reasons"]),
            "owner_market_data_gateway": owner_market_data_gateway.public_status(),
            "runtime_health": {
                "runtime_state": runtime_state,
                "connected_at_utc": str(runtime_health.get("connected_at_utc") or ""),
                "last_event_utc": str(runtime_health.get("last_event_utc") or ""),
                "last_event_age_sec": runtime_health.get("last_event_age_sec"),
                "last_signal_target": str(runtime_health.get("last_signal_target") or "")[:80],
                "last_signal_price_field": str(runtime_health.get("last_signal_price_field") or "")[:40],
                "signal_target_counts": dict(runtime_health.get("signal_target_counts") or {}),
                "signal_price_field_counts": dict(runtime_health.get("signal_price_field_counts") or {}),
                "event_type_counts": dict(runtime_health.get("event_type_counts") or {}),
                "event_type_age_sec": dict(runtime_health.get("event_type_age_sec") or {}),
                "trade_age_by_contract_sec": dict(runtime_health.get("trade_age_by_contract_sec") or {}),
                "signal_invocation_results": dict(runtime_health.get("signal_invocation_results") or {}),
                "market_feed": dict(runtime_health.get("market_feed") or {}),
                # Process-local counters deliberately exclude all credentials
                # and token material.  They make a cold-layout auth/session
                # audit observable without exposing sensitive data.
                "session_audit": dict(runtime_health.get("session_audit") or {}),
                "wire_subscriptions": int(runtime_health.get("wire_subscriptions") or 0),
                "logical_subscription_refcount": int(runtime_health.get("logical_subscription_refcount") or 0),
                "last_error": str(runtime_health.get("last_error") or "")[:160],
            },
            "note": "ProjectX/TopstepX read-only bars; no account, order or trade API is used.",
        }

    def _adapter(self) -> Any:
        cfg = self._settings()
        fingerprint = self._fingerprint(cfg)
        with self._adapter_lock:
            if (
                self.__class__._adapter_instance is None
                or self.__class__._credential_fingerprint != fingerprint
            ):
                old_adapter = self.__class__._adapter_instance
                if old_adapter is not None:
                    # A locally changed API key must not leave a second Market
                    # SignalR client running under the old credential set.
                    try:
                        old_adapter.disconnect()
                    except Exception:
                        pass
                if owner_market_data_gateway.should_consume():
                    adapter = owner_market_data_gateway.OwnerGatewayChartAdapter()
                else:
                    adapter = market_data_live_adapters.TopstepXProjectXAdapter()
                # The adapter's Market SignalR callbacks are the authoritative
                # read-only display stream for this provider.  History fetches
                # populate the initial chart; live events must take the same
                # canonical/router/WebSocket path as connector events so the
                # forming candle and price marker actually advance in a browser
                # with NinjaTrader disconnected.
                def forward_live_event(event: Dict[str, Any]) -> None:
                    try:
                        from . import market_data_ipc
                        normalized = dict(event)
                        # ``topstep_live`` is the adapter implementation name,
                        # not a user-facing provider.  Keep the factual chart
                        # source consistent with historical TopstepX payloads.
                        normalized["provider"] = self.name
                        market_data_ipc.ingest_event(normalized)
                    except Exception:
                        # A display stream outage must not stop TopstepX's
                        # own reconnect/history recovery loop.
                        pass
                adapter.set_sink(forward_live_event, mode="authoritative")
                self.__class__._adapter_instance = adapter
                self.__class__._credential_fingerprint = fingerprint
            return self.__class__._adapter_instance

    def _existing_adapter(self) -> Any:
        cfg = self._settings()
        adapter = self.__class__._adapter_instance
        if not self.configured() or adapter is None:
            return None
        return adapter if self.__class__._credential_fingerprint == self._fingerprint(cfg) else None

    def market_feed_freshness(self, exact_contract: str = "") -> Dict[str, Any]:
        adapter = self._existing_adapter()
        if adapter is None:
            return {
                "fresh": False, "stale": False, "offline": False,
                "connection_state": "NOT_INITIALIZED", "connection_active": False,
                "market_feed_as_of_utc": "", "last_trade_at_utc": "",
            }
        return adapter.market_feed_freshness(exact_contract)

    def acquire_chart_subscription(self, exact_contract: str, timeframe: str, consumer_id: str) -> bool:
        """Attach one browser chart to the shared market socket, not a new one."""
        if not self.configured() or not _EXACT_FUTURES_CONTRACT_RE.fullmatch(str(exact_contract or "").strip().upper()):
            return False
        adapter = self._adapter()
        adapter.subscribe(exact_contract, "quotes", timeframe=_timeframe(timeframe), consumer_id=consumer_id)
        # An HTTP response briefly primes a contract before its browser WS has
        # received the resolved expiry.  Once a real browser consumer exists,
        # remove that bootstrap reference without interrupting the shared wire
        # stream.
        adapter.release_subscription(
            exact_contract, "quotes", timeframe=_timeframe(timeframe),
            consumer_id=f"bootstrap:{' '.join(str(exact_contract).upper().split())}:{_timeframe(timeframe)}",
        )
        adapter.connect()
        return True

    def release_chart_subscription(self, exact_contract: str, timeframe: str, consumer_id: str) -> bool:
        adapter = self._existing_adapter()
        if adapter is None:
            return False
        return adapter.release_subscription(
            exact_contract, "quotes", timeframe=_timeframe(timeframe), consumer_id=consumer_id,
        )

    def refresh_payload_liveness(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh a cached TopstepX response from the shared SignalR state."""
        if not isinstance(payload, dict):
            return payload
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        exact = str(payload.get("instrument") or source.get("provider_symbol") or "")
        feed = self.market_feed_freshness(exact)
        freshness = dict(payload.get("freshness") or {})
        bar_fresh = bool(freshness.get("bar_fresh", freshness.get("fresh")))
        freshness.update({
            "bar_fresh": bar_fresh,
            "market_feed_fresh": bool(feed.get("fresh")),
            "market_feed_stale": bool(feed.get("stale")),
            "market_connection_state": str(feed.get("connection_state") or ""),
            "market_connection_active": bool(feed.get("connection_active")),
            "market_feed_age_sec": feed.get("signalr_receive_age_sec"),
            "signalr_heartbeat_age_sec": feed.get("signalr_heartbeat_age_sec"),
            "quote_age_sec": feed.get("quote_age_sec"),
            "bid_ask_age_sec": feed.get("bid_ask_age_sec"),
            "last_trade_age_sec": feed.get("last_trade_age_sec"),
            "market_feed_as_of_utc": str(feed.get("market_feed_as_of_utc") or ""),
            # ``fresh`` now means display-feed freshness, never just the age of
            # a 5m/1h bar timestamp.
            "fresh": bool(feed.get("fresh")),
            "stale": bool(feed.get("stale")),
            "offline": bool(feed.get("offline")),
        })
        source.update({
            "runtime_state": str(feed.get("connection_state") or source.get("runtime_state") or ""),
            "fresh": bool(feed.get("fresh")),
            "market_feed_fresh": bool(feed.get("fresh")),
            "market_feed_as_of_utc": str(feed.get("market_feed_as_of_utc") or ""),
            "market_connection_active": bool(feed.get("connection_active")),
        })
        if feed.get("market_feed_as_of_utc"):
            source["updated_at_utc"] = str(feed.get("market_feed_as_of_utc"))
            source["age_sec"] = feed.get("signalr_receive_age_sec")
        payload["source"] = source
        payload["freshness"] = freshness
        if feed.get("fresh"):
            payload.update({
                "live": True, "status": "external_live", "market_data_available": True,
                "price_marker_live": True,
            })
        elif feed.get("stale") or feed.get("offline"):
            payload.update({
                "live": False, "status": "external_stale", "market_data_available": True,
                "price_marker_live": False,
            })
        else:
            payload.update({
                "live": False, "status": "external_connecting", "market_data_available": True,
                "price_marker_live": False,
            })
        return payload

    def fetch_range(self, instrument: str, timeframe: str, limit: int, *,
                    start_time: Any = None, end_time: Any = None,
                    cancel_event: Any = None) -> Dict[str, Any]:
        if not self.configured():
            reasons = ",".join(self._settings()["blocking_reasons"])
            raise MarketDataProviderError(
                f"TopstepX market data is not configured: {reasons or 'unavailable'}"
            )
        requested_contract = " ".join(str(instrument or "").strip().upper().split())
        if not requested_contract:
            raise MarketDataProviderError("TopstepX requires a futures root or exact contract")
        tf = _timeframe(timeframe)
        adapter = self._adapter()
        try:
            history = adapter.history_range(
                requested_contract, tf, start_time=start_time, end_time=end_time,
                limit=max(1, min(int(limit or 1500), 20_000)), cancel_event=cancel_event,
            )
        except Exception as exc:
            raise MarketDataProviderError(f"TopstepX history failed: {type(exc).__name__}") from None
        bars = normalize_bars(history.get("bars") or [])
        bars = bars[-max(1, min(int(limit or 1500), 20_000)):]
        if not bars:
            if start_time is not None:
                cfg = self._settings()
                exact_contract = adapter.resolved_exact_contract(requested_contract)
                return {
                    "instrument": exact_contract, "bars": [], "total": 0, "raw_total": 0,
                    "live": False, "status": "external_history_exhausted",
                    "requested_timeframe": tf, "matched_timeframe": tf,
                    "source": owner_market_data_gateway.annotate_source({
                        "kind": "external_provider", "provider": self.name,
                        "provider_symbol": exact_contract, "independent": True,
                        "tier": self.tier, "read_only": True, "trade_routing": False,
                        "data_mode": cfg["data_mode"], "history_exhausted": True,
                    }),
                    "freshness": {"fresh": False, "stale": False, "age_sec": None},
                    "history": {"requested_start_utc": history.get("requested_start_utc") or "",
                                "requested_end_utc": history.get("requested_end_utc") or "",
                                "cache_hit": bool(history.get("cache_hit")), "chunks": int(history.get("chunks") or 0),
                                "exhausted": True},
                    "note": "TopstepX: доступная история этого контракта исчерпана.",
                    "data_plane": "display", "market_data_available": True,
                }
            raise MarketDataProviderError(
                adapter.health().get("last_error") or "TopstepX returned no valid OHLCV bars"
            )
        bar_freshness = series_freshness(bars, tf)
        cfg = self._settings()
        exact_contract = adapter.resolved_exact_contract(requested_contract)
        last = float(bars[-1]["c"])
        # Market SignalR remains read-only and only updates the current candle.
        # Contract lookup already happened in history_range, so subscribe does
        # not add an account/order API call.  ``bootstrap`` is replaced by the
        # browser's reference-counted subscription as soon as it subscribes.
        try:
            adapter.subscribe(
                exact_contract, "quotes", timeframe=tf,
                consumer_id=f"bootstrap:{exact_contract}:{tf}",
            )
            adapter.connect()
        except Exception:
            # History remains usable when a market is closed or SignalR is
            # temporarily reconnecting; status below distinguishes it.
            pass
        feed = adapter.market_feed_freshness(exact_contract)
        freshness = dict(bar_freshness)
        freshness.update({
            "bar_fresh": bool(bar_freshness.get("fresh")),
            "market_feed_fresh": bool(feed.get("fresh")),
            "market_feed_stale": bool(feed.get("stale")),
            "market_connection_state": str(feed.get("connection_state") or ""),
            "market_connection_active": bool(feed.get("connection_active")),
            "market_feed_age_sec": feed.get("signalr_receive_age_sec"),
            "signalr_heartbeat_age_sec": feed.get("signalr_heartbeat_age_sec"),
            "quote_age_sec": feed.get("quote_age_sec"),
            "bid_ask_age_sec": feed.get("bid_ask_age_sec"),
            "last_trade_age_sec": feed.get("last_trade_age_sec"),
            "market_feed_as_of_utc": str(feed.get("market_feed_as_of_utc") or ""),
            "fresh": bool(feed.get("fresh")),
            "stale": bool(feed.get("stale")),
            "offline": bool(feed.get("offline")),
        })
        payload = {
            "instrument": exact_contract,
            "bars": bars,
            "total": len(bars),
            "raw_total": len(bars),
            "live": bool(feed.get("fresh")),
            "status": "external_live" if feed.get("fresh") else "external_connecting",
            "requested_timeframe": tf,
            "matched_timeframe": tf,
            "source": owner_market_data_gateway.annotate_source({
                "kind": "external_provider",
                "provider": self.name,
                "provider_symbol": exact_contract,
                "independent": True,
                "tier": self.tier,
                "updated_at_utc": str(feed.get("market_feed_as_of_utc") or bar_freshness.get("data_as_of_utc") or ""),
                "fetched_at_utc": _iso(),
                "age_sec": feed.get("signalr_receive_age_sec"),
                "bar_age_sec": bar_freshness.get("age_sec"),
                "fresh": bool(feed.get("fresh")),
                "runtime_state": str(feed.get("connection_state") or ""),
                "market_feed_fresh": bool(feed.get("fresh")),
                "market_connection_active": bool(feed.get("connection_active")),
                "live_eligible": True,
                "read_only": True,
                "trade_routing": False,
                "data_mode": cfg["data_mode"],
                "history_cache_hit": bool(history.get("cache_hit")),
                "history_chunks": int(history.get("chunks") or 0),
                "history_exhausted": bool(history.get("history_exhausted")),
                "native_aggregation_fallback": bool(history.get("native_aggregation_fallback")),
            }),
            "freshness": freshness,
            "quote": _quote(last, _root_symbol(exact_contract), source=self.name),
            "note": "TopstepX read-only market data; execution remains NinjaTrader-only.",
            "data_plane": "display",
            "market_data_available": True,
            "price_marker_live": bool(feed.get("fresh")),
            # ProjectX exposes active contracts but does not publish a
            # historical rollover schedule. Until such authoritative mapping
            # exists, never splice contracts into a synthetic "continuous"
            # chart: the visible series is always this exact contract.
            "series_mode": "contract",
            "continuous_history": {
                "available": False,
                "reason": "projectx_rollover_schedule_not_available",
                "display_contract": exact_contract,
            },
            "history": {
                "requested_start_utc": history.get("requested_start_utc") or "",
                "requested_end_utc": history.get("requested_end_utc") or "",
                "cache_hit": bool(history.get("cache_hit")),
                "chunks": int(history.get("chunks") or 0),
                "exhausted": bool(history.get("history_exhausted")),
                "native_aggregation_fallback": bool(history.get("native_aggregation_fallback")),
            },
        }
        return self.refresh_payload_liveness(payload)

    def fetch(self, instrument: str, timeframe: str, limit: int) -> Dict[str, Any]:
        return self.fetch_range(instrument, timeframe, limit)


def configured_providers() -> List[MarketDataProvider]:
    available: Dict[str, MarketDataProvider] = {
        "topstepx": TopstepXProvider(), "topstep": TopstepXProvider(),
        "databento": DatabentoProvider(), "yahoo": YahooChartProvider(),
        "yahoo_chart": YahooChartProvider(),
    }
    order = str(os.environ.get("NTA_MARKET_DATA_PROVIDERS") or "topstepx,databento,yahoo").split(",")
    result: List[MarketDataProvider] = []
    seen = set()
    for name in order:
        provider = available.get(name.strip().lower())
        if provider and provider.name not in seen:
            seen.add(provider.name)
            result.append(provider)
    return result


def _provider_scope(instrument: str, timeframe: str) -> str:
    return f"{str(instrument or '').upper()}|{_timeframe(timeframe)}"


def _health_key(provider: MarketDataProvider, instrument: str, timeframe: str) -> str:
    return f"{provider.name}|{_provider_scope(instrument, timeframe)}"


def _cache_key(provider: MarketDataProvider, instrument: str, timeframe: str, limit: int,
               start_time: Any = None, end_time: Any = None) -> str:
    def stamp(value: Any) -> str:
        parsed = _parse_time(value)
        return _iso(parsed) if parsed is not None else ""
    return "|".join((provider.name, str(instrument).upper(), _timeframe(timeframe),
                     str(int(limit)), stamp(start_time), stamp(end_time)))


def _cache_ttl(timeframe: str) -> int:
    return max(15, min(300, timeframe_seconds(timeframe) // 2))


def _public_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    text = re.sub(r"(?i)(access_token=)[^&\\s]+", r"\\1[redacted]", text)
    text = re.sub(r"(?i)(bearer\\s+)[A-Za-z0-9._~+/=-]+", r"\\1[redacted]", text)
    text = re.sub(r"(?i)(api[_-]?key[\"']?\\s*[:=]\\s*)[^,\\s}\\]]+", r"\\1[redacted]", text)
    return text[:300]


def _write_status() -> None:
    path = _status_path()
    with _LOCK:
        doc = status(include_file=False)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def fetch_external_series(instrument: str, timeframe: str, limit: int = 1500,
                          *, providers: Optional[Sequence[MarketDataProvider]] = None,
                          force: bool = False, start_time: Any = None,
                          end_time: Any = None) -> Optional[Dict[str, Any]]:
    """Fetch one normalized provider series with scoped health and hysteresis.

    The selected payload is intentionally from one provider only.  Combining
    same-timestamp bars from two feeds can conceal contract/session differences,
    so a source transition replaces the chart range and the caller records it.
    ``start_time``/``end_time`` are passed only to adapters which explicitly
    implement range retrieval; legacy providers retain their bounded latest
    history behaviour.
    """
    tf = _timeframe(timeframe)
    now = time.time()
    candidates = list(providers) if providers is not None else configured_providers()
    scope = _provider_scope(instrument, tf)
    with _LOCK:
        previous = copy.deepcopy(_LAST_SELECTION.get(scope) or {})
    previous_name = str(previous.get("selected") or "")
    primary_name = candidates[0].name if candidates else ""
    # While a backup is carrying a chart, probe the preferred provider at a
    # controlled cadence.  This avoids both a request storm and rapid source
    # oscillation around a flaky reconnect.
    return_probe_due = False
    if previous_name and previous_name != primary_name:
        by_name = {provider.name: provider for provider in candidates}
        active = by_name.get(previous_name)
        primary = by_name.get(primary_name)
        next_probe = float(previous.get("next_primary_probe_at") or 0)
        return_probe_due = bool(primary and now >= next_probe)
        ordered = [primary] if return_probe_due else []
        if active:
            ordered.append(active)
        ordered.extend(provider for provider in candidates if provider not in ordered)
        candidates = ordered
    attempted: List[Dict[str, Any]] = []
    selected: Optional[Dict[str, Any]] = None
    selected_provider = ""
    primary_success = False
    primary_probe_successes = int(previous.get("primary_probe_successes") or 0)
    for provider in candidates:
        public = provider.public_status()
        if not provider.configured():
            attempted.append({**public, "ok": False, "skipped": "not_configured"})
            continue
        health_key = _health_key(provider, instrument, tf)
        with _LOCK:
            health = _HEALTH.setdefault(health_key, {"failures": 0, "cooldown_until": 0.0})
            cooldown_until = float(health.get("cooldown_until") or 0)
        if not force and cooldown_until > now:
            attempted.append({**public, "ok": False, "skipped": "cooldown",
                              "retry_after_sec": round(cooldown_until - now, 1)})
            continue
        key = _cache_key(provider, instrument, tf, limit, start_time, end_time)
        with _LOCK:
            cached = _CACHE.get(key)
        if not force and cached and now - float(cached.get("stored_at") or 0) <= _cache_ttl(tf):
            selected = copy.deepcopy(cached["payload"])
            refresh_liveness = getattr(provider, "refresh_payload_liveness", None)
            if callable(refresh_liveness):
                selected = refresh_liveness(selected)
            selected.setdefault("source", {})["cache_hit"] = True
            attempted.append({**public, "ok": True, "cache_hit": True})
            if provider.name == primary_name and previous_name and previous_name != primary_name and return_probe_due:
                primary_success = True
                primary_probe_successes += 1
                if primary_probe_successes < 2:
                    attempted.append({**public, "ok": True, "skipped": "return_hysteresis"})
                    continue
            selected_provider = provider.name
            break
        try:
            if start_time is not None or end_time is not None:
                fetch_range = getattr(provider, "fetch_range", None)
                payload = fetch_range(instrument, tf, limit, start_time=start_time, end_time=end_time) \
                    if callable(fetch_range) else provider.fetch(instrument, tf, limit)
            else:
                payload = provider.fetch(instrument, tf, limit)
            if not payload.get("bars"):
                raise MarketDataProviderError("provider returned no bars")
            refresh_liveness = getattr(provider, "refresh_payload_liveness", None)
            if callable(refresh_liveness):
                payload = refresh_liveness(payload)
            with _LOCK:
                _CACHE[key] = {"stored_at": now, "payload": copy.deepcopy(payload)}
                _HEALTH[health_key] = {
                    "failures": 0, "cooldown_until": 0.0, "last_ok_utc": _iso(),
                    "last_error": "",
                }
            attempted.append({**public, "ok": True, "cache_hit": False})
            if provider.name == primary_name and previous_name and previous_name != primary_name and return_probe_due:
                primary_success = True
                primary_probe_successes += 1
                if primary_probe_successes < 2:
                    attempted.append({**public, "ok": True, "skipped": "return_hysteresis"})
                    continue
            selected = payload
            selected_provider = provider.name
            break
        except Exception as exc:
            with _LOCK:
                current = _HEALTH.setdefault(health_key, {"failures": 0, "cooldown_until": 0.0})
                failures = int(current.get("failures") or 0) + 1
                current.update({"failures": failures, "last_error": _public_error(exc),
                                "last_failure_utc": _iso()})
                if failures >= _FAILURES_BEFORE_COOLDOWN:
                    current["cooldown_until"] = now + _COOLDOWN_SEC
            attempted.append({**public, "ok": False, "error": _public_error(exc)})
    with _LOCK:
        selected_name = selected_provider or ((selected or {}).get("source") or {}).get("provider") or ""
        transition_from = previous_name if previous_name and selected_name and previous_name != selected_name else ""
        _LAST_SELECTION[scope] = {
            "at_utc": _iso(), "instrument": instrument, "timeframe": tf,
            "selected": selected_name, "previous": previous_name,
            "transition_from": transition_from, "attempts": attempted,
            "ok": bool(selected and selected.get("bars")),
            "primary_recovered_since": (float(previous.get("primary_recovered_since") or now)
                                        if primary_success else 0.0),
            "primary_probe_successes": primary_probe_successes if primary_success else 0,
            "next_primary_probe_at": now + _PRIMARY_PROBE_INTERVAL_SEC,
        }
    if selected:
        source = selected.setdefault("source", {})
        source["active"] = selected_name
        source["selection_scope"] = scope
        source["failover_from"] = transition_from
        source["failover_status"] = "switched" if transition_from else "primary"
    try:
        _write_status()
    except OSError:
        pass
    return copy.deepcopy(selected) if selected else None


def _source_name(payload: Optional[Dict[str, Any]]) -> str:
    source = (payload or {}).get("source") if isinstance((payload or {}).get("source"), dict) else {}
    return str(source.get("provider") or source.get("kind") or "unknown")


def production_live_failover_eligible(provider_name: str) -> bool:
    """Yahoo/Recorded/FaultInjection are never production live failover."""
    name = str(provider_name or "").strip().lower()
    return name not in {
        "", "yahoo", "yahoo_chart", "recorded", "fault_injection", "unknown",
    }


def live_backup_candidates(
    providers: Optional[Sequence[MarketDataProvider]] = None,
) -> List[MarketDataProvider]:
    """Credentialed, production-eligible live backups only (never Yahoo)."""
    candidates = list(providers) if providers is not None else configured_providers()
    return [
        provider for provider in candidates
        if production_live_failover_eligible(provider.name) and provider.configured()
    ]


def remember_selected_provider(provider_name: str, instrument: str, timeframe: str,
                               *, reason: str = "") -> Dict[str, Any]:
    """Record a non-adapter source (currently the NinjaTrader connector).

    This is metadata only: it never changes price data.  Keeping the connector
    in the same scoped selection state lets the next TopstepX request use the
    same return hysteresis as other providers.
    """
    tf = _timeframe(timeframe)
    scope = _provider_scope(instrument, tf)
    now = time.time()
    with _LOCK:
        previous = copy.deepcopy(_LAST_SELECTION.get(scope) or {})
        previous_name = str(previous.get("selected") or "")
        # A successful preferred-provider probe may deliberately return no
        # payload during return hysteresis. Preserve that probe evidence while
        # the connector continues to serve the chart in the meantime.
        pending_probe = previous_name == "" and str(previous.get("previous") or "") == str(provider_name or "")
        carried_probe_successes = int(previous.get("primary_probe_successes") or 0) if pending_probe else 0
        carried_recovered_since = float(previous.get("primary_recovered_since") or 0) if pending_probe else 0.0
        transition_from = previous_name if previous_name and previous_name != provider_name else ""
        state = {
            "at_utc": _iso(), "instrument": instrument, "timeframe": tf,
            "selected": str(provider_name or ""), "previous": previous_name,
            "transition_from": transition_from, "attempts": [], "ok": bool(provider_name),
            "primary_recovered_since": carried_recovered_since,
            "primary_probe_successes": carried_probe_successes,
            "next_primary_probe_at": now + _PRIMARY_PROBE_INTERVAL_SEC,
            "reason": str(reason or ""),
        }
        _LAST_SELECTION[scope] = state
    return state


def mark_offline_snapshot(
    payload: Optional[Dict[str, Any]],
    *,
    reason: str,
    last_source: str = "ninjatrader",
    backup_providers_available: int = 0,
) -> Dict[str, Any]:
    """Force safe OFFLINE semantics — never present cache as LIVE."""
    out = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    freshness = dict(out.get("freshness") or {})
    age = freshness.get("age_sec")
    data_as_of = freshness.get("data_as_of_utc") or ""
    source = dict(out.get("source") or {})
    source.update({
        "fresh": False,
        "live_eligible": False,
        "runtime_state": "OFFLINE",
        "failover_status": "offline_no_live_backup",
        "reason": reason,
        "last_source": last_source,
        "backup_providers_available": int(backup_providers_available),
    })
    freshness.update({
        "fresh": False,
        "stale": True,
        "offline": True,
        "live_eligible": False,
    })
    out["live"] = False
    out["status"] = "offline"
    out["freshness"] = freshness
    out["source"] = source
    out["market_data_available"] = False
    out["strategy_blocked"] = True
    out["execution_blocked"] = True
    out["price_marker_live"] = False
    out["offline_banner"] = {
        "title": "OFFLINE — LIVE MARKET DATA UNAVAILABLE",
        "last_valid_event": data_as_of,
        "age_sec": age,
        "last_source": last_source,
        "backup_providers_available": int(backup_providers_available),
        "reason": reason,
    }
    out["note"] = (
        f"OFFLINE: {reason}. Last event {data_as_of or 'unknown'}; "
        f"age_sec={age}. Cache/history only — not live."
    )
    return out


def apply_failover(primary: Optional[Dict[str, Any]], instrument: str, timeframe: str,
                   limit: int = 1500, *, primary_healthy: bool = True,
                   providers: Optional[Sequence[MarketDataProvider]] = None,
                   force_external: bool = False) -> Optional[Dict[str, Any]]:
    """Return a unified series, filling only missing timestamps from secondary.

    Primary bars win on timestamp collisions.  The independent provider may
    append newer bars and fill internal holes, but never overwrites a bridge
    candle.  No synthetic OHLCV candle is invented.

    Safety: Yahoo/Recorded are never LIVE. When primary is unhealthy and no
    credentialed live backup is available, return an explicit OFFLINE snapshot.
    """
    tf = _timeframe(timeframe)
    primary_copy = copy.deepcopy(primary) if isinstance(primary, dict) else None
    primary_bars = normalize_bars((primary_copy or {}).get("bars") or [])
    freshness_before = series_freshness(primary_bars, tf)
    gaps_before = detect_gaps(primary_bars, tf)
    actionable_gaps = [gap for gap in gaps_before if not gap.get("session_break_likely")]
    need_external = bool(
        force_external or not primary_bars or not primary_healthy
        or not freshness_before["fresh"] or actionable_gaps
    )
    if not need_external and primary_copy:
        primary_copy["bars"] = primary_bars[-max(1, int(limit)):]
        primary_copy["freshness"] = freshness_before
        primary_copy["gap_recovery"] = {
            "attempted": False, "recovered_bars": 0, "gaps_before": gaps_before,
            "gaps_after": gaps_before, "unresolved_gaps": len(gaps_before),
        }
        primary_copy.setdefault("source", {})["fresh"] = freshness_before["fresh"]
        primary_copy.setdefault("source", {})["runtime_state"] = (
            "LIVE" if freshness_before["fresh"] else "STALE"
        )
        primary_copy["live"] = bool(freshness_before["fresh"] and primary_healthy)
        if not primary_copy["live"]:
            primary_copy["status"] = "stale"
            primary_copy["price_marker_live"] = False
        return primary_copy

    # When NinjaTrader is down, NEVER fan out to Yahoo/delayed HTTP per chart.
    # That caused 12–20s timeouts × 30–64 panels. Only credentialed live backups
    # may be contacted; otherwise serve cache immediately as OFFLINE.
    if not primary_healthy:
        live_cands = live_backup_candidates(providers)
        if not live_cands:
            base = primary_copy
            if not base:
                return mark_offline_snapshot(
                    {"bars": [], "instrument": instrument},
                    reason="ninjatrader_offline_no_live_backup",
                    last_source="none",
                    backup_providers_available=0,
                )
            base["bars"] = primary_bars[-max(1, int(limit)):]
            base["freshness"] = freshness_before
            base["gap_recovery"] = {
                "attempted": False,
                "provider_available": False,
                "mode": "offline_cache_fastpath",
                "recovered_bars": 0,
                "gaps_before": gaps_before,
                "gaps_after": gaps_before,
                "unresolved_gaps": len(gaps_before),
                "primary_healthy": False,
                "skipped_delayed_providers": True,
            }
            return mark_offline_snapshot(
                base,
                reason="ninjatrader_offline_no_live_backup",
                last_source="ninjatrader" if primary_bars else "cache",
                backup_providers_available=0,
            )
        external = fetch_external_series(
            instrument, tf, limit, providers=live_cands, force=force_external,
        )
    else:
        external = fetch_external_series(
            instrument, tf, limit, providers=providers, force=force_external,
        )
    external_bars = normalize_bars((external or {}).get("bars") or [])
    external_source = (external or {}).get("source") if isinstance((external or {}).get("source"), dict) else {}
    external_provider = str(external_source.get("provider") or "")
    live_backup_ok = bool(
        external_bars
        and production_live_failover_eligible(external_provider)
        and bool((external or {}).get("live"))
        and bool(external_source.get("live_eligible", True))
    )

    if not primary_healthy and not live_backup_ok:
        # Correct offline mode: serve history fast, never claim LIVE.
        base = primary_copy
        if not base and external:
            # Delayed Yahoo/etc may still paint history with STALE, not LIVE.
            base = copy.deepcopy(external)
        if not base:
            return mark_offline_snapshot(
                {"bars": [], "instrument": instrument},
                reason="ninjatrader_offline_no_live_backup",
                last_source="none",
                backup_providers_available=0,
            )
        if base is primary_copy:
            base["bars"] = primary_bars[-max(1, int(limit)):]
            base["freshness"] = freshness_before
        # If only Yahoo-like delayed data exists, keep bars but mark offline/stale.
        reason = "ninjatrader_offline_no_live_backup"
        if external_provider and not production_live_failover_eligible(external_provider):
            reason = f"ninjatrader_offline_delayed_only:{external_provider}"
            # Prefer richer delayed bars for display history if primary empty.
            if not primary_bars and external_bars:
                base["bars"] = external_bars[-max(1, int(limit)):]
                base["freshness"] = series_freshness(base["bars"], tf)
        return mark_offline_snapshot(
            base,
            reason=reason,
            last_source="ninjatrader" if primary_bars else (external_provider or "cache"),
            backup_providers_available=0,
        )

    if not external_bars:
        if not primary_copy:
            return None
        primary_copy["bars"] = primary_bars[-max(1, int(limit)):]
        primary_copy["freshness"] = freshness_before
        primary_copy["gap_recovery"] = {
            "attempted": True, "provider_available": False, "recovered_bars": 0,
            "gaps_before": gaps_before, "gaps_after": gaps_before,
            "unresolved_gaps": len(gaps_before),
        }
        if not primary_healthy:
            return mark_offline_snapshot(
                primary_copy,
                reason="ninjatrader_offline_external_unavailable",
                last_source="ninjatrader",
                backup_providers_available=0,
            )
        primary_copy.setdefault("source", {})["failover_status"] = "unavailable"
        primary_copy["live"] = False
        return primary_copy

    primary_by_time = {row["t"]: row for row in primary_bars}
    merged_by_time = {row["t"]: row for row in external_bars}
    merged_by_time.update(primary_by_time)  # Bridge is authoritative on collisions.
    merged = [merged_by_time[key] for key in sorted(merged_by_time)]
    recovered_stamps = [key for key in merged_by_time if key not in primary_by_time]
    merged = merged[-max(1, min(int(limit or 1500), 50000)):]
    recovered_in_window = len([row for row in merged if row["t"] in recovered_stamps])
    gaps_after = detect_gaps(merged, tf)
    freshness_after = series_freshness(merged, tf)

    if not primary_bars:
        result = copy.deepcopy(external)
        mode = "independent_failover"
    else:
        result = copy.deepcopy(primary_copy)
        result["bars"] = merged
        result["total"] = len(merged)
        result["raw_total"] = len(merged)
        result["quote"] = copy.deepcopy((external or {}).get("quote") or result.get("quote") or {})
        result["source"] = {
            "kind": "market_data_composite", "provider": external_source.get("provider"),
            "independent": True, "active": (
                external_source.get("provider") if (not primary_healthy or not freshness_before["fresh"])
                else _source_name(primary_copy)
            ),
            "primary": copy.deepcopy((primary_copy or {}).get("source") or {}),
            "secondary": copy.deepcopy(external_source),
            "updated_at_utc": freshness_after["data_as_of_utc"],
            "age_sec": freshness_after["age_sec"], "fresh": freshness_after["fresh"],
        }
        mode = "gap_recovery" if recovered_in_window else "validated_failover"

    # Only credentialed live backups may claim LIVE after primary failure.
    if live_backup_ok:
        result["live"] = True
        result["status"] = "failover_live"
        result.setdefault("source", {})["runtime_state"] = "LIVE"
        result.setdefault("source", {})["live_eligible"] = True
    else:
        result["live"] = False
        result["status"] = "failover_stale" if freshness_after.get("stale") else "external_stale"
        result.setdefault("source", {})["runtime_state"] = "STALE"
        result.setdefault("source", {})["live_eligible"] = False
        result["price_marker_live"] = False

    result["freshness"] = freshness_after
    result["gap_recovery"] = {
        "attempted": True, "provider_available": True, "mode": mode,
        "provider": external_source.get("provider") or "",
        "recovered_bars": recovered_in_window, "gaps_before": gaps_before,
        "gaps_after": gaps_after, "unresolved_gaps": len(gaps_after),
        "primary_healthy": bool(primary_healthy),
    }
    result["bars"] = merged
    result["total"] = len(merged)
    result["requested_timeframe"] = tf
    result["matched_timeframe"] = tf
    return result


def status(*, include_file: bool = True) -> Dict[str, Any]:
    providers = configured_providers()
    with _LOCK:
        health = copy.deepcopy(_HEALTH)
        selections = copy.deepcopy(_LAST_SELECTION)
    last = max(selections.values(), key=lambda item: str(item.get("at_utc") or ""), default={})
    rows = []
    now = time.time()
    for provider in providers:
        row = provider.public_status()
        scoped = [entry for key, entry in health.items() if key == provider.name or key.startswith(provider.name + "|")]
        state = max(scoped, key=lambda entry: str(entry.get("last_ok_utc") or entry.get("last_failure_utc") or ""), default={})
        cooldown_until = float(state.get("cooldown_until") or 0)
        row.update({
            "failures": int(state.get("failures") or 0),
            "cooldown": cooldown_until > now,
            "retry_after_sec": round(max(0.0, cooldown_until - now), 1),
            "last_ok_utc": state.get("last_ok_utc") or "",
            "last_failure_utc": state.get("last_failure_utc") or "",
            "last_error": state.get("last_error") or "",
        })
        rows.append(row)
    doc = {
        "ok": True, "generated_at_utc": _iso(),
        "preferred_primary": "ninjatrader_runtime",
        "external_providers": rows,
        "independent_provider_configured": any(row["configured"] for row in rows),
        "last_selection": last,
        "selections_by_instrument": selections,
        "policy": {
            "primary_collision_wins": True, "synthetic_gap_bars": False,
            "live_order_authority": False, "cooldown_after_failures": _FAILURES_BEFORE_COOLDOWN,
            "cooldown_sec": _COOLDOWN_SEC,
        },
        "owner_market_data_gateway": owner_market_data_gateway.public_status(),
    }
    if include_file and not last:
        path = _status_path()
        if path.is_file():
            try:
                stored = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(stored, dict) and isinstance(stored.get("last_selection"), dict):
                    doc["last_selection"] = stored["last_selection"]
            except (OSError, ValueError):
                pass
    return doc


def reset_runtime_state() -> None:
    """Test/maintenance helper; does not remove persisted market bars."""
    with _LOCK:
        _CACHE.clear()
        _HEALTH.clear()
        _LAST_SELECTION.clear()
