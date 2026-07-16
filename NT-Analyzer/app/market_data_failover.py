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
import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import runtime_env


class MarketDataProviderError(RuntimeError):
    pass


_LOCK = threading.RLock()
_CACHE: Dict[str, Dict[str, Any]] = {}
_HEALTH: Dict[str, Dict[str, Any]] = {}
_LAST_SELECTION: Dict[str, Any] = {}
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
        return {
            "instrument": str(instrument or root), "bars": bars, "total": len(bars),
            "raw_total": len(raw), "live": fresh["fresh"],
            "status": "external_live" if fresh["fresh"] else "external_stale",
            "requested_timeframe": tf, "matched_timeframe": tf,
            "source": {
                "kind": "external_provider", "provider": self.name,
                "provider_symbol": symbol, "independent": True, "tier": self.tier,
                "updated_at_utc": fresh["data_as_of_utc"], "fetched_at_utc": fetched_at,
                "age_sec": fresh["age_sec"], "fresh": fresh["fresh"],
            },
            "freshness": fresh,
            "quote": _quote(last, root, source=self.name),
            "note": "Независимый best-effort поток для графиков; не источник live-исполнения.",
        }


class DatabentoProvider(MarketDataProvider):
    name = "databento"
    tier = "credentialed_market_data"

    def _key(self) -> str:
        return str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()

    def configured(self) -> bool:
        return bool(self._key())

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


def configured_providers() -> List[MarketDataProvider]:
    available: Dict[str, MarketDataProvider] = {
        "databento": DatabentoProvider(), "yahoo": YahooChartProvider(),
        "yahoo_chart": YahooChartProvider(),
    }
    order = str(os.environ.get("NTA_MARKET_DATA_PROVIDERS") or "databento,yahoo").split(",")
    result: List[MarketDataProvider] = []
    seen = set()
    for name in order:
        provider = available.get(name.strip().lower())
        if provider and provider.name not in seen:
            seen.add(provider.name)
            result.append(provider)
    return result


def _cache_key(provider: MarketDataProvider, instrument: str, timeframe: str, limit: int) -> str:
    return f"{provider.name}|{str(instrument).upper()}|{_timeframe(timeframe)}|{int(limit)}"


def _cache_ttl(timeframe: str) -> int:
    return max(15, min(300, timeframe_seconds(timeframe) // 2))


def _public_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
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
                    "last_error": "",
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


def apply_failover(primary: Optional[Dict[str, Any]], instrument: str, timeframe: str,
                   limit: int = 1500, *, primary_healthy: bool = True,
                   providers: Optional[Sequence[MarketDataProvider]] = None,
                   force_external: bool = False) -> Optional[Dict[str, Any]]:
    """Return a unified series, filling only missing timestamps from secondary.

    Primary bars win on timestamp collisions.  The independent provider may
    append newer bars and fill internal holes, but never overwrites a bridge
    candle.  No synthetic OHLCV candle is invented.
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
        return primary_copy

    external = fetch_external_series(
        instrument, tf, limit, providers=providers, force=force_external,
    )
    external_bars = normalize_bars((external or {}).get("bars") or [])
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
        primary_copy.setdefault("source", {})["failover_status"] = "unavailable"
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
    external_source = (external or {}).get("source") if isinstance((external or {}).get("source"), dict) else {}

    if not primary_bars:
        result = copy.deepcopy(external)
        mode = "independent_failover"
    else:
        result = copy.deepcopy(primary_copy)
        result["bars"] = merged
        result["total"] = len(merged)
        result["raw_total"] = len(merged)
        result["live"] = freshness_after["fresh"]
        result["status"] = "failover_live" if freshness_after["fresh"] else "failover_stale"
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
        "independent_provider_configured": any(row["configured"] for row in rows),
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
