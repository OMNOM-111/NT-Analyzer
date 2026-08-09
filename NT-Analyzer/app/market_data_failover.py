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

from . import market_data_live_adapters, runtime_env


class MarketDataProviderError(RuntimeError):
    pass


_LOCK = threading.RLock()
_CACHE: Dict[str, Dict[str, Any]] = {}
_HEALTH: Dict[str, Dict[str, Any]] = {}
_LAST_SELECTION: Dict[str, Any] = {}
_READINESS_STATE: Dict[str, Any] = {}
_READINESS_PROBE_THREAD: Optional[threading.Thread] = None
_FAILURES_BEFORE_COOLDOWN = 3
_COOLDOWN_SEC = 60
_TIMEFRAME_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1D": 86400,
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
    normalized = "1D" if raw.lower() == "1d" else raw.lower()
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
        return str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()

    def configured(self) -> bool:
        return bool(self._key())

    def public_status(self) -> Dict[str, Any]:
        configured = self.configured()
        return {
            "name": self.name, "configured": configured,
            "independent": self.independent, "tier": self.tier,
            "implementation_state": "ADAPTER_READY" if configured else "ADAPTER_READY",
            "runtime_state": "DISABLED" if not configured else "CONNECTING",
            "capability": "REALTIME_PRODUCTION" if configured else "ENTITLEMENT_MISSING",
            "live_eligible": configured,
            "production_failover_eligible": configured,
            "note": "Live key required before PRODUCTION failover eligibility.",
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
    """Personal-device ProjectX bars for read-only charts.

    Remote/public use stays fail-closed unless both remote-server and market
    data redistribution authorization are explicitly recorded in protected
    deployment configuration. This provider has no order/account methods.
    """

    name = "topstepx"
    tier = "user_owned_credentialed_market_data"
    _adapter_lock = threading.RLock()
    _adapter_instance: Optional[market_data_live_adapters.TopstepXProjectXAdapter] = None
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
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def configured(self) -> bool:
        cfg = self._settings()
        return bool(
            cfg["credentials_present"] and cfg["requested"]
            and cfg["policy_allowed"] and cfg["data_mode"] != "invalid"
        )

    def public_status(self) -> Dict[str, Any]:
        cfg = self._settings()
        configured = self.configured()
        adapter = self.__class__._adapter_instance
        if (
            not configured
            or self.__class__._credential_fingerprint != self._fingerprint(cfg)
        ):
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
            "runtime_health": {
                "runtime_state": runtime_state,
                "connected_at_utc": str(runtime_health.get("connected_at_utc") or ""),
                "last_event_utc": str(runtime_health.get("last_event_utc") or ""),
                "last_event_age_sec": runtime_health.get("last_event_age_sec"),
                "last_error": str(runtime_health.get("last_error") or "")[:160],
            },
            "note": (
                "ProjectX/TopstepX read-only bars; no account, order or trade API is used."
            ),
        }

    def _adapter(self) -> market_data_live_adapters.TopstepXProjectXAdapter:
        cfg = self._settings()
        fingerprint = self._fingerprint(cfg)
        with self._adapter_lock:
            if (
                self.__class__._adapter_instance is None
                or self.__class__._credential_fingerprint != fingerprint
            ):
                self.__class__._adapter_instance = (
                    market_data_live_adapters.TopstepXProjectXAdapter()
                )
                self.__class__._credential_fingerprint = fingerprint
            return self.__class__._adapter_instance

    def fetch(self, instrument: str, timeframe: str, limit: int) -> Dict[str, Any]:
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
        bars = normalize_bars(adapter.backfill(requested_contract, tf, limit))
        bars = bars[-max(1, min(int(limit or 1500), 20000)):]
        if not bars:
            raise MarketDataProviderError(
                adapter.health().get("last_error") or "TopstepX returned no valid OHLCV bars"
            )
        fresh = series_freshness(bars, tf)
        cfg = self._settings()
        exact_contract = adapter.resolved_exact_contract(requested_contract)
        last = float(bars[-1]["c"])
        adapter._runtime_state = "LIVE" if fresh["fresh"] else "DEGRADED"
        adapter._last_event_utc = str(fresh.get("data_as_of_utc") or "")
        adapter._last_error = ""
        return {
            "instrument": exact_contract,
            "bars": bars,
            "total": len(bars),
            "raw_total": len(bars),
            "live": bool(fresh["fresh"]),
            "status": "external_live" if fresh["fresh"] else "external_stale",
            "requested_timeframe": tf,
            "matched_timeframe": tf,
            "source": {
                "kind": "external_provider",
                "provider": self.name,
                "provider_symbol": exact_contract,
                "independent": True,
                "tier": self.tier,
                "updated_at_utc": fresh["data_as_of_utc"],
                "fetched_at_utc": _iso(),
                "age_sec": fresh["age_sec"],
                "fresh": fresh["fresh"],
                "live_eligible": True,
                "read_only": True,
                "trade_routing": False,
                "data_mode": cfg["data_mode"],
            },
            "freshness": fresh,
            "quote": _quote(last, _root_symbol(exact_contract), source=self.name),
            "note": "TopstepX read-only market data; execution remains NinjaTrader-only.",
            "data_plane": "display",
            "market_data_available": bool(fresh["fresh"]),
        }


def configured_providers() -> List[MarketDataProvider]:
    available: Dict[str, MarketDataProvider] = {
        "topstepx": TopstepXProvider(), "topstep": TopstepXProvider(),
        "databento": DatabentoProvider(), "yahoo": YahooChartProvider(),
        "yahoo_chart": YahooChartProvider(),
    }
    order = str(
        os.environ.get("NTA_MARKET_DATA_PROVIDERS") or "topstepx,databento,yahoo"
    ).split(",")
    result: List[MarketDataProvider] = []
    seen = set()
    for name in order:
        provider = available.get(name.strip().lower())
        if provider and provider.name not in seen:
            seen.add(provider.name)
            result.append(provider)
    return result


def provider_config_signature() -> str:
    """Secret-free cache invalidation when provider readiness changes."""
    rows = [
        {
            "name": provider.name,
            "configured": provider.configured(),
            "production_failover_eligible": bool(
                provider.public_status().get("production_failover_eligible")
            ),
        }
        for provider in configured_providers()
    ]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cache_key(provider: MarketDataProvider, instrument: str, timeframe: str, limit: int) -> str:
    return f"{provider.name}|{str(instrument).upper()}|{_timeframe(timeframe)}|{int(limit)}"


def _cache_ttl(timeframe: str) -> int:
    return max(15, min(300, timeframe_seconds(timeframe) // 2))


def _public_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    text = re.sub(r"(?i)(access_token=)[^&\s]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+", r"\1[redacted]", text)
    text = re.sub(
        r"(?i)(api[_-]?key[\"']?\s*[:=]\s*)[^,\s}\]]+",
        r"\1[redacted]",
        text,
    )
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
                          force: bool = False) -> Optional[Dict[str, Any]]:
    tf = _timeframe(timeframe)
    now = time.time()
    candidates = list(providers) if providers is not None else configured_providers()
    attempted: List[Dict[str, Any]] = []
    selected: Optional[Dict[str, Any]] = None
    for provider in candidates:
        public = provider.public_status()
        if not provider.configured():
            attempted.append({**public, "ok": False, "skipped": "not_configured"})
            continue
        with _LOCK:
            health = _HEALTH.setdefault(provider.name, {"failures": 0, "cooldown_until": 0.0})
            cooldown_until = float(health.get("cooldown_until") or 0)
        if not force and cooldown_until > now:
            attempted.append({**public, "ok": False, "skipped": "cooldown",
                              "retry_after_sec": round(cooldown_until - now, 1)})
            continue
        key = _cache_key(provider, instrument, tf, limit)
        with _LOCK:
            cached = _CACHE.get(key)
        if not force and cached and now - float(cached.get("stored_at") or 0) <= _cache_ttl(tf):
            selected = copy.deepcopy(cached["payload"])
            selected.setdefault("source", {})["cache_hit"] = True
            attempted.append({**public, "ok": True, "cache_hit": True})
            break
        try:
            payload = provider.fetch(instrument, tf, limit)
            if not payload.get("bars"):
                raise MarketDataProviderError("provider returned no bars")
            with _LOCK:
                _CACHE[key] = {"stored_at": now, "payload": copy.deepcopy(payload)}
                _HEALTH[provider.name] = {
                    "failures": 0, "cooldown_until": 0.0, "last_ok_utc": _iso(),
                    "last_error": "", "data_live": bool(payload.get("live")),
                    "data_as_of_utc": str(
                        ((payload.get("freshness") or {}).get("data_as_of_utc")) or ""
                    ),
                }
            attempted.append({**public, "ok": True, "cache_hit": False})
            selected = payload
            break
        except Exception as exc:
            with _LOCK:
                current = _HEALTH.setdefault(provider.name, {"failures": 0, "cooldown_until": 0.0})
                failures = int(current.get("failures") or 0) + 1
                current.update({"failures": failures, "last_error": _public_error(exc),
                                "last_failure_utc": _iso()})
                if failures >= _FAILURES_BEFORE_COOLDOWN:
                    current["cooldown_until"] = now + _COOLDOWN_SEC
            attempted.append({**public, "ok": False, "error": _public_error(exc)})
    with _LOCK:
        _LAST_SELECTION.clear()
        _LAST_SELECTION.update({
            "at_utc": _iso(), "instrument": instrument, "timeframe": tf,
            "selected": ((selected or {}).get("source") or {}).get("provider") or "",
            "attempts": attempted, "ok": bool(selected and selected.get("bars")),
        })
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


def _readiness_probe_config() -> Dict[str, Any]:
    try:
        max_age = int(os.environ.get("NTA_MARKET_DATA_READINESS_MAX_AGE_SEC") or 900)
    except (TypeError, ValueError):
        max_age = 900
    try:
        refresh_after = int(os.environ.get("NTA_MARKET_DATA_READINESS_REFRESH_SEC") or 300)
    except (TypeError, ValueError):
        refresh_after = 300
    try:
        retry_after = int(os.environ.get("NTA_MARKET_DATA_READINESS_RETRY_SEC") or 30)
    except (TypeError, ValueError):
        retry_after = 30
    return {
        "instrument": str(
            os.environ.get("NTA_MARKET_DATA_HEALTHCHECK_INSTRUMENT") or "MNQ"
        ).strip().upper(),
        "timeframe": str(
            os.environ.get("NTA_MARKET_DATA_HEALTHCHECK_TIMEFRAME") or "1m"
        ).strip(),
        "max_age_sec": max(60, min(max_age, 3600)),
        "refresh_after_sec": max(30, min(refresh_after, 1800)),
        "retry_after_sec": max(10, min(retry_after, 300)),
    }


def _readiness_candidate_signature(candidates: Sequence[MarketDataProvider]) -> str:
    rows = []
    for provider in candidates:
        identity = provider.__class__.__qualname__
        if isinstance(provider, TopstepXProvider):
            identity += ":" + provider._fingerprint(provider._settings())
        elif isinstance(provider, DatabentoProvider):
            identity += ":" + hashlib.sha256(provider._key().encode("utf-8")).hexdigest()
        rows.append({"name": provider.name, "identity": identity})
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def verify_independent_market_data(
    providers: Optional[Sequence[MarketDataProvider]] = None,
) -> Dict[str, Any]:
    """Actively verify a credentialed provider with a real read-only bars call."""
    candidates = live_backup_candidates(providers)
    config = _readiness_probe_config()
    candidate_signature = _readiness_candidate_signature(candidates)
    try:
        selected = fetch_external_series(
            config["instrument"], config["timeframe"], 3,
            providers=candidates, force=True,
        ) if candidates else None
    except Exception:
        selected = None
    source = selected.get("source") if isinstance((selected or {}).get("source"), dict) else {}
    provider_name = str(source.get("provider") or "")
    success = bool(
        selected and selected.get("bars")
        and production_live_failover_eligible(provider_name)
        and any(provider.name == provider_name for provider in candidates)
    )
    now = time.time()
    with _LOCK:
        _READINESS_STATE.update({
            "in_flight": False,
            "last_completed_at": now,
            "last_completed_utc": _iso(),
            "last_result_ok": success,
            "code": "ok" if success else "provider_probe_failed",
            "candidate_signature": candidate_signature,
        })
        if success:
            freshness = selected.get("freshness") if isinstance(selected.get("freshness"), dict) else {}
            _READINESS_STATE.update({
                "last_ok_at": now,
                "last_ok_utc": _iso(),
                "verified_provider": provider_name,
                "data_live": bool(selected.get("live")),
                "data_as_of_utc": str(freshness.get("data_as_of_utc") or ""),
            })
        else:
            _READINESS_STATE["last_failure_at"] = now
            _READINESS_STATE["last_failure_utc"] = _iso()
    return independent_market_data_readiness(providers=candidates, trigger_probe=False)


def _readiness_probe_worker(candidates: Sequence[MarketDataProvider]) -> None:
    global _READINESS_PROBE_THREAD
    try:
        verify_independent_market_data(candidates)
    finally:
        with _LOCK:
            _READINESS_STATE["in_flight"] = False
            _READINESS_PROBE_THREAD = None


def _trigger_readiness_probe(candidates: Sequence[MarketDataProvider]) -> bool:
    global _READINESS_PROBE_THREAD
    config = _readiness_probe_config()
    now = time.time()
    with _LOCK:
        if _READINESS_PROBE_THREAD is not None and _READINESS_PROBE_THREAD.is_alive():
            return False
        last_started = float(_READINESS_STATE.get("last_started_at") or 0.0)
        if now - last_started < config["retry_after_sec"]:
            return False
        _READINESS_STATE.update({
            "in_flight": True,
            "last_started_at": now,
            "last_started_utc": _iso(),
        })
        _READINESS_PROBE_THREAD = threading.Thread(
            target=_readiness_probe_worker,
            args=(list(candidates),),
            name="market-data-readiness-probe",
            daemon=True,
        )
        thread = _READINESS_PROBE_THREAD
    thread.start()
    return True


def independent_market_data_readiness(
    providers: Optional[Sequence[MarketDataProvider]] = None,
    *,
    trigger_probe: bool = False,
) -> Dict[str, Any]:
    """Return green only after a recent successful provider bars response.

    A stale last bar can still prove reachability while the market is closed;
    chart payloads continue to expose it as stale instead of claiming LIVE.
    """
    candidates = live_backup_candidates(providers)
    names = [provider.name for provider in candidates]
    if not candidates:
        return {
            "ok": False,
            "code": "licensed_live_backup_missing",
            "candidate_providers": [],
            "verification_in_flight": False,
        }
    config = _readiness_probe_config()
    candidate_signature = _readiness_candidate_signature(candidates)
    now = time.time()
    with _LOCK:
        state = copy.deepcopy(_READINESS_STATE)
    last_ok = float(state.get("last_ok_at") or 0.0)
    last_failure = float(state.get("last_failure_at") or 0.0)
    verified_name = str(state.get("verified_provider") or "")
    age = max(0.0, now - last_ok) if last_ok else None
    verified = bool(
        last_ok and last_ok >= last_failure
        and verified_name in names
        and str(state.get("candidate_signature") or "") == candidate_signature
        and age is not None and age <= config["max_age_sec"]
    )
    should_refresh = bool(not verified or (age is not None and age >= config["refresh_after_sec"]))
    if trigger_probe and should_refresh:
        _trigger_readiness_probe(candidates)
        with _LOCK:
            state = copy.deepcopy(_READINESS_STATE)
    if verified:
        code = "ok"
    elif state.get("in_flight"):
        code = "provider_probe_pending"
    elif state.get("last_result_ok") is False:
        code = "provider_probe_failed"
    else:
        code = "provider_not_verified"
    return {
        "ok": verified,
        "code": code,
        "candidate_providers": names,
        "verified_provider": verified_name if verified else "",
        "last_verified_utc": str(state.get("last_ok_utc") or "") if verified else "",
        "verification_age_sec": round(age, 1) if age is not None else None,
        "verification_in_flight": bool(state.get("in_flight")),
        "data_live_at_last_probe": bool(state.get("data_live")) if verified else False,
        "data_as_of_utc": str(state.get("data_as_of_utc") or "") if verified else "",
    }


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
        last = copy.deepcopy(_LAST_SELECTION)
    rows = []
    now = time.time()
    for provider in providers:
        row = provider.public_status()
        state = health.get(provider.name) or {}
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
        "independent_provider_configured": bool(live_backup_candidates(providers)),
        "best_effort_external_provider_configured": any(row["configured"] for row in rows),
        "independent_provider_readiness": independent_market_data_readiness(
            providers=providers, trigger_probe=False,
        ),
        "last_selection": last,
        "policy": {
            "primary_collision_wins": True, "synthetic_gap_bars": False,
            "live_order_authority": False, "cooldown_after_failures": _FAILURES_BEFORE_COOLDOWN,
            "cooldown_sec": _COOLDOWN_SEC,
        },
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
        _READINESS_STATE.clear()
