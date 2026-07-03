"""Pre-backtest signal sanity checks for AI Strategy Lab.

This is not a substitute for NinjaTrader Strategy Analyzer. It is a cheap
data-aware gate that catches strategies whose own hypothesis cannot produce
any theoretical signal on local historical bars before we spend a real NT
backtest slot.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # pragma: no cover - Windows runners may not have the IANA tz database.
    from zoneinfo import ZoneInfo
except Exception:  # noqa: BLE001
    ZoneInfo = None  # type: ignore[assignment]


DEFAULT_MIN_SIGNALS = 8
DEFAULT_MAX_RAW_SIGNALS_PER_DAY = 8.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_hhmm(value: Any, fallback: str) -> time:
    raw = str(value or fallback).strip()
    try:
        if ":" in raw:
            hh, mm = raw.split(":", 1)
            return time(hour=int(hh), minute=int(mm[:2]))
        digits = "".join(ch for ch in raw if ch.isdigit()).zfill(6)
        return time(hour=int(digits[:-4]), minute=int(digits[-4:-2]))
    except Exception:  # noqa: BLE001
        hh, mm = fallback.split(":", 1)
        return time(hour=int(hh), minute=int(mm))


def _parse_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_pacific(dt_utc: datetime) -> datetime:
    if ZoneInfo is not None:
        try:
            return dt_utc.astimezone(ZoneInfo("America/Los_Angeles"))
        except Exception:  # noqa: BLE001
            pass
    return (dt_utc - timedelta(hours=8)).replace(tzinfo=timezone(timedelta(hours=-8)))


def _job_instrument_for_bars(bars_path: Path) -> str:
    for name in ("job.json", "result.json"):
        path = bars_path.parent / name
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if name == "job.json":
            value = doc.get("instrument")
        else:
            value = ((doc.get("context") or {}).get("instrument"))
        if value:
            return str(value).strip()
    return ""


def find_bars_file(target_root: str, instrument: str = "") -> Optional[Path]:
    """Find the newest local completed bars.json for a target root."""
    override = os.environ.get("AI_LAB_SIGNAL_BARS_FILE")
    if override:
        p = Path(override)
        return p if p.exists() else None

    root = (target_root or "").upper().strip()
    try:
        from .. import jobqueue
    except Exception:
        return None
    jobs_root = Path(jobqueue.jobs_dir())
    done = jobs_root / "done"
    if not done.exists():
        return None
    candidates: List[Tuple[float, Path]] = []
    try:
        entries = list(os.scandir(done))
    except OSError:
        return None
    for entry in entries:
        if not entry.is_dir():
            continue
        bars_path = Path(entry.path) / "bars.json"
        if not bars_path.exists():
            continue
        try:
            size = bars_path.stat().st_size
            mtime = bars_path.stat().st_mtime
        except OSError:
            continue
        if size > 10_000:
            candidates.append((mtime, bars_path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not root:
        return candidates[0][1]

    exact = str(instrument or "").strip().upper()
    if exact:
        for _, bars_path in candidates:
            if _job_instrument_for_bars(bars_path).upper() == exact:
                return bars_path

    root_in_name = [p for _, p in candidates if root in p.parent.name.upper()]
    if root_in_name:
        return root_in_name[0]

    for _, bars_path in candidates[:300]:
        job_path = bars_path.parent / "job.json"
        if not job_path.exists():
            continue
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        instrument = str(job.get("instrument") or "").upper()
        if root in instrument:
            return bars_path
    return candidates[0][1]


def _stream_array_objects(path: Path, *, max_bars: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    depth = 0
    in_string = False
    escape = False
    buf: List[str] = []
    with path.open("r", encoding="utf-8") as fh:
        while len(out) < max_bars:
            chunk = fh.read(65536)
            if not chunk:
                break
            for ch in chunk:
                if depth == 0:
                    if ch == "{":
                        depth = 1
                        buf = [ch]
                    continue
                buf.append(ch)
                if escape:
                    escape = False
                    continue
                if ch == "\\" and in_string:
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads("".join(buf))
                        except json.JSONDecodeError:
                            obj = None
                        if isinstance(obj, dict):
                            out.append(obj)
                        buf = []
                        if len(out) >= max_bars:
                            return out
    return out


def load_bars(path: Path, *, max_bars: int = 80_000) -> List[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            first = fh.read(1)
            while first and first.isspace():
                first = fh.read(1)
    except OSError:
        return []
    if first == "[":
        return _stream_array_objects(path, max_bars=max_bars)

    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        bars = raw.get("bars") or raw.get("data") or []
    else:
        bars = raw
    if not isinstance(bars, list):
        return []
    if len(bars) > max_bars:
        return bars[-max_bars:]
    return bars


def estimate_breakout_signals(
    bars: Iterable[Dict[str, Any]],
    parameters: Dict[str, Any],
    *,
    min_signals: int = DEFAULT_MIN_SIGNALS,
    data_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Estimate signals for the fallback ORB/breakout family.

    The generator's default implementation uses close > MAX(High, lookback)[1]
    or close < MIN(Low, lookback)[1] inside the PT session window.
    """
    rows = list(bars)
    lookback = max(2, int(parameters.get("BreakoutLookback", 20) or 20))
    max_trades_per_day = max(1, int(parameters.get("MaxTradesPerDay", 3) or 3))
    start = _parse_hhmm(
        parameters.get("SessionStartTimePT", parameters.get("SessionStartPT")),
        "06:30",
    )
    end = _parse_hhmm(
        parameters.get("SessionEndTimePT", parameters.get("SessionEndPT")),
        "12:30",
    )
    min_signals = max(0, int(min_signals))

    if len(rows) < lookback + 10:
        return {
            "ok": False,
            "environment_blocker": True,
            "reason": "insufficient_local_bars",
            "checked_at_utc": _now(),
            "bars_count": len(rows),
            "lookback": lookback,
            "data_source": data_source,
            "theoretical_signals": 0,
            "long_signals": 0,
            "short_signals": 0,
            "session_pt": f"{start:%H:%M}-{end:%H:%M}",
        }

    signals = 0
    raw_signals = 0
    long_signals = 0
    short_signals = 0
    session_bars = 0
    per_day: Dict[str, int] = {}
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None

    for i in range(lookback + 5, len(rows)):
        row = rows[i]
        dt = _parse_utc(row.get("t") or row.get("time") or row.get("timestamp"))
        if dt is None:
            continue
        first_ts = first_ts or dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        last_ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        pt = _to_pacific(dt)
        tod = pt.time().replace(second=0, microsecond=0)
        if tod < start or tod >= end:
            continue
        session_bars += 1
        day_key = pt.date().isoformat()
        prev = rows[i - lookback:i]
        try:
            hi = max(float(b["h"]) for b in prev)
            lo = min(float(b["l"]) for b in prev)
            close = float(row["c"])
        except Exception:
            continue
        if close > hi:
            raw_signals += 1
            if per_day.get(day_key, 0) >= max_trades_per_day:
                continue
            signals += 1
            long_signals += 1
            per_day[day_key] = per_day.get(day_key, 0) + 1
        elif close < lo:
            raw_signals += 1
            if per_day.get(day_key, 0) >= max_trades_per_day:
                continue
            signals += 1
            short_signals += 1
            per_day[day_key] = per_day.get(day_key, 0) + 1

    active_days = max(1, len({
        _to_pacific(dt).date().isoformat()
        for row in rows
        if (dt := _parse_utc(row.get("t") or row.get("time") or row.get("timestamp")))
    }))
    raw_per_day = raw_signals / active_days
    overtrading = raw_per_day > DEFAULT_MAX_RAW_SIGNALS_PER_DAY
    ok = signals >= min_signals and not overtrading
    reason = "overtrading_risk" if overtrading else ("ok" if ok else (
        "zero_theoretical_signals" if signals == 0 else "below_min_theoretical_signals"
    ))
    return {
        "ok": ok,
        "environment_blocker": False,
        "reason": reason,
        "checked_at_utc": _now(),
        "bars_count": len(rows),
        "session_bars": session_bars,
        "lookback": lookback,
        "min_signals": min_signals,
        "max_trades_per_day": max_trades_per_day,
        "theoretical_signals": signals,
        "raw_signals": raw_signals,
        "raw_signals_per_day": round(raw_per_day, 3),
        "overtrading_risk": overtrading,
        "long_signals": long_signals,
        "short_signals": short_signals,
        "days_with_signals": len(per_day),
        "first_bar_utc": first_ts,
        "last_bar_utc": last_ts,
        "data_source": data_source,
        "session_pt": f"{start:%H:%M}-{end:%H:%M}",
    }


def _bar_values(row: Dict[str, Any]) -> Optional[Tuple[float, float, float, float, float]]:
    try:
        return (
            float(row.get("o", row.get("open"))),
            float(row.get("h", row.get("high"))),
            float(row.get("l", row.get("low"))),
            float(row.get("c", row.get("close"))),
            float(row.get("v", row.get("volume", 0.0)) or 0.0),
        )
    except (TypeError, ValueError):
        return None


def _ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    alpha = 2.0 / (max(2, period) + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def _rsi(values: List[float], period: int) -> List[float]:
    out = [50.0] * len(values)
    if len(values) <= period:
        return out
    gains = [0.0]
    losses = [0.0]
    for idx in range(1, len(values)):
        delta = values[idx] - values[idx - 1]
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    for idx in range(period, len(values)):
        if idx > period:
            avg_gain = ((period - 1) * avg_gain + gains[idx]) / period
            avg_loss = ((period - 1) * avg_loss + losses[idx]) / period
        out[idx] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def estimate_family_signals(
    bars: Iterable[Dict[str, Any]],
    parameters: Dict[str, Any],
    *,
    family: str,
    hypothesis: str = "",
    min_signals: int = DEFAULT_MIN_SIGNALS,
    data_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Approximate the declared family instead of always testing a breakout."""
    rows = list(bars)
    values = [_bar_values(row) for row in rows]
    closes = [item[3] if item else 0.0 for item in values]
    volumes = [item[4] if item else 0.0 for item in values]
    fast_period = max(2, int(parameters.get("EmaFast", parameters.get("ema_fast", 9)) or 9))
    slow_period = max(fast_period + 1, int(parameters.get("EmaSlow", parameters.get("ema_slow", 20)) or 20))
    lookback = max(5, int(parameters.get("BreakoutLookback", parameters.get("Lookback", 20)) or 20))
    rsi_period = max(2, int(parameters.get("RsiPeriod", parameters.get("rsi_period", 14)) or 14))
    max_trades = max(1, min(3, int(parameters.get("MaxTradesPerDay", 3) or 3)))
    start = _parse_hhmm(
        parameters.get("SessionStartTimePT", parameters.get("SessionStartPT")),
        "06:30",
    )
    end = _parse_hhmm(
        parameters.get("SessionEndTimePT", parameters.get("SessionEndPT")),
        "12:30",
    )
    ema_fast = _ema(closes, fast_period)
    ema_slow = _ema(closes, slow_period)
    try:
        trend_ema_period = max(5, min(50, int(float(
            parameters.get("ema_slope_filter", parameters.get("TrendEmaPeriod", 20))
        ))))
    except (TypeError, ValueError):
        trend_ema_period = 20
    trend_ema = _ema(closes, trend_ema_period)
    rsi = _rsi(closes, rsi_period)
    mode_text = f"{family} {hypothesis}".lower()
    mode = "trend_pullback"
    family_text = str(family or "").lower()
    if any(word in family_text for word in ("vwap", "volume")):
        mode = "volume_vwap"
    elif any(word in mode_text for word in ("liquidity", "sweep", "reversal")):
        mode = "liquidity_reversal"
    elif any(word in mode_text for word in ("mean reversion", "mean_reversion", "bollinger")):
        mode = "mean_reversion"
    elif any(word in mode_text for word in ("opening range", "orb", "session edge")):
        mode = "opening_range"
    elif "breakout" in mode_text or "donchian" in mode_text:
        return {
            **estimate_breakout_signals(
                rows, parameters, min_signals=min_signals, data_source=data_source
            ),
            "estimator": "breakout",
        }

    raw = long_count = short_count = session_bars = 0
    capped = 0
    per_day: Dict[str, int] = {}
    session_days: set[str] = set()
    day_vwap_num: Dict[str, float] = {}
    day_vwap_den: Dict[str, float] = {}
    day_open_range: Dict[str, Dict[str, float]] = {}

    for idx in range(max(lookback, slow_period, rsi_period) + 2, len(rows)):
        item = values[idx]
        dt = _parse_utc(rows[idx].get("t") or rows[idx].get("time") or rows[idx].get("timestamp"))
        if item is None or dt is None:
            continue
        pt = _to_pacific(dt)
        tod = pt.time().replace(second=0, microsecond=0)
        if tod < start or tod >= end:
            continue
        session_bars += 1
        day = pt.date().isoformat()
        session_days.add(day)
        o, h, l, c, v = item
        prev_values = [x for x in values[idx - lookback:idx] if x is not None]
        if len(prev_values) < lookback:
            continue
        signal = 0
        if mode == "liquidity_reversal":
            prev_hi = max(x[1] for x in prev_values)
            prev_lo = min(x[2] for x in prev_values)
            if l < prev_lo and c > prev_lo and c > o:
                signal = 1
            elif h > prev_hi and c < prev_hi and c < o:
                signal = -1
        elif mode == "mean_reversion":
            window = closes[idx - lookback:idx]
            mean = sum(window) / len(window)
            variance = sum((x - mean) ** 2 for x in window) / len(window)
            band = max(1e-9, variance ** 0.5 * 1.8)
            if closes[idx - 1] < mean - band and c > closes[idx - 1]:
                signal = 1
            elif closes[idx - 1] > mean + band and c < closes[idx - 1]:
                signal = -1
        elif mode == "volume_vwap":
            typical = (h + l + c) / 3.0
            day_vwap_num[day] = day_vwap_num.get(day, 0.0) + typical * max(v, 1.0)
            day_vwap_den[day] = day_vwap_den.get(day, 0.0) + max(v, 1.0)
            vwap = day_vwap_num[day] / day_vwap_den[day]
            avg_vol = sum(volumes[idx - 20:idx]) / max(1, len(volumes[idx - 20:idx]))
            high_volume = v >= max(
                1.0,
                avg_vol * float(
                    parameters.get(
                        "MinVolumeFactor",
                        parameters.get("volume_multiplier", 1.15),
                    ) or 1.15
                ),
            )
            if (
                high_volume and l <= vwap <= c
                and c > trend_ema[idx] > trend_ema[idx - 3]
            ):
                signal = 1
            elif (
                high_volume and h >= vwap >= c
                and c < trend_ema[idx] < trend_ema[idx - 3]
            ):
                signal = -1
        elif mode == "opening_range":
            rec = day_open_range.setdefault(day, {"high": h, "low": l})
            minutes = pt.hour * 60 + pt.minute
            start_minutes = start.hour * 60 + start.minute
            if minutes < start_minutes + 30:
                rec["high"] = max(rec["high"], h)
                rec["low"] = min(rec["low"], l)
                continue
            if c > rec["high"] and ema_fast[idx] > ema_slow[idx]:
                signal = 1
            elif c < rec["low"] and ema_fast[idx] < ema_slow[idx]:
                signal = -1
        else:
            if ema_fast[idx] > ema_slow[idx] and l <= ema_fast[idx] < c and rsi[idx] >= 50:
                signal = 1
            elif ema_fast[idx] < ema_slow[idx] and h >= ema_fast[idx] > c and rsi[idx] <= 50:
                signal = -1

        if not signal:
            continue
        raw += 1
        if per_day.get(day, 0) >= max_trades:
            continue
        per_day[day] = per_day.get(day, 0) + 1
        capped += 1
        if signal > 0:
            long_count += 1
        else:
            short_count += 1

    days = max(1, len(session_days))
    raw_per_day = raw / days
    expected = parameters.get("ExpectedTradesPerDay")
    expected_max = 3.0
    try:
        if expected is not None:
            expected_max = min(3.0, max(0.2, float(expected)))
    except (TypeError, ValueError):
        pass
    overtrading = raw_per_day > max(DEFAULT_MAX_RAW_SIGNALS_PER_DAY, expected_max * 4.0)
    ok = capped >= max(1, min_signals) and not overtrading
    reason = (
        "overtrading_risk" if overtrading
        else "ok" if ok
        else "zero_theoretical_signals" if capped == 0
        else "below_min_theoretical_signals"
    )
    return {
        "ok": ok,
        "environment_blocker": False,
        "reason": reason,
        "checked_at_utc": _now(),
        "bars_count": len(rows),
        "session_bars": session_bars,
        "min_signals": min_signals,
        "max_trades_per_day": max_trades,
        "theoretical_signals": capped,
        "raw_signals": raw,
        "raw_signals_per_day": round(raw_per_day, 3),
        "overtrading_risk": overtrading,
        "long_signals": long_count,
        "short_signals": short_count,
        "days_with_signals": len(per_day),
        "data_source": data_source,
        "session_pt": f"{start:%H:%M}-{end:%H:%M}",
        "estimator": mode,
        "family": family,
    }


def check_experiment(
    experiment: Dict[str, Any],
    *,
    min_signals: int = DEFAULT_MIN_SIGNALS,
    bars_file: Optional[Path] = None,
    instrument: str = "",
) -> Dict[str, Any]:
    target_root = str(experiment.get("target_root") or "").upper()
    path = Path(bars_file) if bars_file else find_bars_file(target_root, instrument)
    if path is None:
        return {
            "ok": False,
            "environment_blocker": True,
            "reason": "no_local_bars_data",
            "checked_at_utc": _now(),
            "target_root": target_root,
            "data_source": None,
            "theoretical_signals": 0,
        }
    try:
        bars = load_bars(path)
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "environment_blocker": True,
            "reason": f"bars_load_failed: {e}",
            "checked_at_utc": _now(),
            "target_root": target_root,
            "data_source": str(path),
            "theoretical_signals": 0,
        }
    parameters = dict(experiment.get("parameters") or {})
    expected = (experiment.get("hypothesis_spec") or {}).get("expected_trades_per_day")
    if expected is not None:
        parameters["ExpectedTradesPerDay"] = expected
    out = estimate_family_signals(
        bars,
        parameters,
        family=str(experiment.get("family") or ""),
        hypothesis=str(experiment.get("hypothesis") or ""),
        min_signals=min_signals,
        data_source=str(path),
    )
    out["target_root"] = target_root
    out["requested_instrument"] = str(instrument or "")
    out["data_instrument"] = _job_instrument_for_bars(path)
    if instrument and out["data_instrument"].upper() != str(instrument).upper():
        # Cross-contract bars are useful as a rough diagnostic but cannot
        # reject the current contract before its authoritative smoke run.
        out["original_ok"] = out.get("ok")
        out["original_reason"] = out.get("reason")
        out["ok"] = True
        out["advisory_only"] = True
        out["reason"] = "contract_mismatch_advisory_only"
    return out


def markdown_summary(result: Dict[str, Any]) -> str:
    lines = [
        "# Signal Sanity Check",
        "",
        f"- ok: {result.get('ok')}",
        f"- reason: {result.get('reason')}",
        f"- theoretical_signals: {result.get('theoretical_signals')}",
        f"- long_signals: {result.get('long_signals')}",
        f"- short_signals: {result.get('short_signals')}",
        f"- session_pt: {result.get('session_pt')}",
        f"- bars_count: {result.get('bars_count')}",
        f"- data_source: {result.get('data_source')}",
    ]
    return "\n".join(lines) + "\n"
