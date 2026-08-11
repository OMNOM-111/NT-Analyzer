"""Canonical bar engine: event-time aggregation from trade events.

Builds multiple timeframes from one raw trade stream. Vendor bars are not
produced here — they remain fallback/gap/parity inputs elsewhere.

Pacific time is display-only; all aggregation keys are UTC.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .canonical_event import event_time_utc

try:
    from zoneinfo import ZoneInfo
    _PT = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    _PT = timezone(timedelta(hours=-8))

TIMEFRAME_SECONDS = {
    "tick": 0,
    "1s": 1, "5s": 5, "15s": 15, "30s": 30,
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400,
    "1d": 86400, "session": 86400,
}

BAR_STATES = ("provisional", "final", "corrected")


def _floor_time(dt: datetime, seconds: int) -> datetime:
    if seconds <= 0:
        return dt.astimezone(timezone.utc)
    ts = int(dt.timestamp())
    floored = ts - (ts % seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


@dataclass
class CanonicalBar:
    timeframe: str
    exact_contract: str
    ts_open_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    trade_count: int = 0
    state: str = "provisional"
    source_epoch: int = 0
    provider: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t": self.ts_open_utc.isoformat().replace("+00:00", "Z"),
            "o": self.open,
            "h": self.high,
            "l": self.low,
            "c": self.close,
            "v": self.volume,
            "trade_count": self.trade_count,
            "state": self.state,
            "timeframe": self.timeframe,
            "exact_contract": self.exact_contract,
            "source_epoch": self.source_epoch,
            "provider": self.provider,
            "display_pt": self.ts_open_utc.astimezone(_PT).isoformat(),
        }


@dataclass
class _Bucket:
    bar: CanonicalBar
    closed: bool = False


class CanonicalBarEngine:
    """One engine per workspace+exact_contract; many timeframes."""

    def __init__(
        self,
        exact_contract: str,
        timeframes: Optional[Iterable[str]] = None,
        *,
        close_grace_sec: float = 0.25,
        session_template: str = "cme_equity_fut_rth_eth",
    ) -> None:
        self.exact_contract = str(exact_contract or "").strip().upper()
        # These are the desktop's live chart intervals.  Historical data may
        # support more intervals, but a requested 1h chart must not receive a
        # WebSocket stream that only builds 1s/1m/5m buckets.
        tfs = list(timeframes or ("1s", "1m", "5m", "1h"))
        self.timeframes = [tf for tf in tfs if tf in TIMEFRAME_SECONDS]
        if not self.timeframes:
            self.timeframes = ["1m"]
        self.close_grace_sec = max(0.0, float(close_grace_sec))
        self.session_template = session_template
        self._buckets: Dict[str, Optional[_Bucket]] = {tf: None for tf in self.timeframes}
        self._history: Dict[str, List[CanonicalBar]] = {tf: [] for tf in self.timeframes}
        self._history_limit = 5000
        self._late_events = 0
        self._corrections = 0
        self._zero_volume_emitted = 0

    def on_trade(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        if str(event.get("type") or "").lower() not in {"trade", "correction"}:
            return []
        price = event.get("price")
        try:
            px = float(price)
        except (TypeError, ValueError):
            return []
        if px != px or px <= 0:
            return []
        ts = event_time_utc(event)
        if ts is None:
            return []
        volume = 0.0
        try:
            volume = float(event.get("volume") or 0.0)
        except (TypeError, ValueError):
            volume = 0.0
        if volume < 0:
            volume = 0.0
        is_correction = str(event.get("type") or "").lower() == "correction" or bool(
            (event.get("quality") or {}).get("corrected")
        )
        updates: List[Dict[str, Any]] = []
        for tf in self.timeframes:
            updates.extend(self._apply(tf, ts, px, volume, event, is_correction))
        return updates

    def _apply(
        self,
        timeframe: str,
        ts: datetime,
        price: float,
        volume: float,
        event: Dict[str, Any],
        is_correction: bool,
    ) -> List[Dict[str, Any]]:
        seconds = TIMEFRAME_SECONDS[timeframe]
        open_ts = _floor_time(ts, seconds) if seconds > 0 else ts
        bucket = self._buckets.get(timeframe)
        out: List[Dict[str, Any]] = []

        if bucket is not None and seconds > 0 and open_ts < bucket.bar.ts_open_utc:
            # Late event for a prior bucket.
            self._late_events += 1
            hist = self._history[timeframe]
            for bar in reversed(hist):
                if bar.ts_open_utc == open_ts:
                    bar.high = max(bar.high, price)
                    bar.low = min(bar.low, price)
                    bar.close = price
                    bar.volume += volume
                    bar.trade_count += 1
                    bar.state = "corrected"
                    self._corrections += 1
                    out.append({"action": "correction", "bar": bar.to_dict()})
                    break
            return out

        if bucket is not None and seconds > 0 and open_ts > bucket.bar.ts_open_utc:
            # Close previous (with grace already elapsed by event-time advance).
            bucket.bar.state = "final"
            out.append({"action": "close", "bar": bucket.bar.to_dict()})
            self._append_history(timeframe, bucket.bar)
            # Optionally emit zero-volume intervals between buckets.
            gap = int((open_ts - bucket.bar.ts_open_utc).total_seconds())
            steps = max(0, (gap // seconds) - 1)
            cursor = bucket.bar.ts_open_utc + timedelta(seconds=seconds)
            for _ in range(min(steps, 10)):
                empty = CanonicalBar(
                    timeframe=timeframe,
                    exact_contract=self.exact_contract,
                    ts_open_utc=cursor,
                    open=bucket.bar.close,
                    high=bucket.bar.close,
                    low=bucket.bar.close,
                    close=bucket.bar.close,
                    volume=0.0,
                    trade_count=0,
                    state="final",
                    source_epoch=int(event.get("source_epoch") or 0),
                    provider=str(event.get("provider") or ""),
                )
                self._append_history(timeframe, empty)
                out.append({"action": "close", "bar": empty.to_dict()})
                self._zero_volume_emitted += 1
                cursor += timedelta(seconds=seconds)
            bucket = None

        if bucket is None:
            bar = CanonicalBar(
                timeframe=timeframe,
                exact_contract=self.exact_contract,
                ts_open_utc=open_ts,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                trade_count=1,
                state="corrected" if is_correction else "provisional",
                source_epoch=int(event.get("source_epoch") or 0),
                provider=str(event.get("provider") or ""),
            )
            self._buckets[timeframe] = _Bucket(bar=bar)
            out.append({"action": "update", "bar": bar.to_dict()})
            return out

        bar = bucket.bar
        bar.high = max(bar.high, price)
        bar.low = min(bar.low, price)
        bar.close = price
        bar.volume += volume
        bar.trade_count += 1
        if is_correction:
            bar.state = "corrected"
            self._corrections += 1
        out.append({"action": "update", "bar": bar.to_dict()})
        return out

    def _append_history(self, timeframe: str, bar: CanonicalBar) -> None:
        hist = self._history[timeframe]
        hist.append(bar)
        if len(hist) > self._history_limit:
            del hist[: len(hist) - self._history_limit]

    def series(self, timeframe: str, limit: int = 500) -> List[Dict[str, Any]]:
        hist = list(self._history.get(timeframe) or [])
        bucket = self._buckets.get(timeframe)
        if bucket is not None:
            hist = hist + [bucket.bar]
        if limit > 0:
            hist = hist[-limit:]
        return [bar.to_dict() for bar in hist]

    def stats(self) -> Dict[str, Any]:
        return {
            "exact_contract": self.exact_contract,
            "timeframes": list(self.timeframes),
            "late_events": self._late_events,
            "corrections": self._corrections,
            "zero_volume_emitted": self._zero_volume_emitted,
            "session_template": self.session_template,
            "close_grace_sec": self.close_grace_sec,
        }


class BarEngineRegistry:
    """Fan-in: one engine per workspace + exact contract."""

    def __init__(self) -> None:
        self._engines: Dict[Tuple[str, str], CanonicalBarEngine] = {}

    def get(self, workspace_id: str, exact_contract: str, timeframes=None) -> CanonicalBarEngine:
        key = (str(workspace_id or "default"), str(exact_contract or "").upper())
        engine = self._engines.get(key)
        if engine is None:
            engine = CanonicalBarEngine(exact_contract, timeframes=timeframes)
            self._engines[key] = engine
        return engine

    def on_trade(self, workspace_id: str, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        contract = str(event.get("exact_contract") or "").upper()
        if not contract:
            return []
        return self.get(workspace_id, contract).on_trade(event)


_ENGINES = BarEngineRegistry()


def engines() -> BarEngineRegistry:
    return _ENGINES
