"""Production market-data ingestion, fan-out and subscription management.

Development mode uses in-memory storage via ``data_platform.MemoryCache``.
Production mode persists to PostgreSQL with fail-closed semantics.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

from . import observability, runtime_env
from .data_platform import get_platform


_LOCK = threading.RLock()
_DEV_BATCHES: List[Dict[str, Any]] = []
_DEV_SNAPSHOTS: Dict[str, Dict[str, Any]] = {}
_DEV_SUBSCRIPTIONS: Dict[str, Dict[str, Any]] = {}
_CONTRACT_RE = re.compile(r"^[A-Z0-9][A-Z0-9._ -]{0,39}$")
_TIMEFRAME_RE = re.compile(
    r"^(?:(?:[1-9]|[1-9][0-9]|1[0-9]{2}|2[0-3][0-9]|240)m|"
    r"(?:[1-9]|1[0-9]|2[0-4])h|1D)$"
)


def _normalize_timeframe(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.lower() == "1d":
        return "1D"
    lowered = raw.lower()
    return lowered if _TIMEFRAME_RE.fullmatch(lowered) else ""


def _is_prod() -> bool:
    return runtime_env.is_production() and runtime_env.environment_explicit()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False, default=str,
    ).encode("utf-8")


def _payload_sha256(bars: List[Dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical(bars)).hexdigest()


def _sub_key(workspace_id: str, installation_id: str, exact_contract: str, timeframe: str) -> str:
    return f"{workspace_id}|{installation_id}|{exact_contract.upper()}|{timeframe}"


def _series_by_contract(bars: List[Dict[str, Any]]) -> Dict[tuple[str, str], List[Dict[str, Any]]]:
    grouped: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for bar in bars:
        grouped[(bar["exact_contract"], bar["timeframe"])].append(bar)
    return grouped


def _validate_bars(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize one all-or-nothing bounded OHLCV batch."""
    if not isinstance(bars, list) or not 1 <= len(bars) <= 64:
        return []
    clean: List[Dict[str, Any]] = []
    last_by_series: Dict[tuple[str, str], datetime] = {}
    required = {
        "open", "high", "low", "close", "volume", "timestamp",
        "exact_contract", "timeframe",
    }
    for bar in bars:
        if not isinstance(bar, dict) or set(bar) != required:
            return []
        try:
            o = float(bar["open"])
            h = float(bar["high"])
            l = float(bar["low"])
            c = float(bar["close"])
            raw_volume = float(bar["volume"])
        except (TypeError, ValueError):
            return []
        if (
            any(not math.isfinite(x) for x in (o, h, l, c, raw_volume))
            or raw_volume < 0 or not raw_volume.is_integer()
            or raw_volume > 9_223_372_036_854_775_807
            or h < l or not l <= o <= h or not l <= c <= h
        ):
            return []
        timestamp = str(bar["timestamp"] or "").strip()
        try:
            observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return []
        if observed.tzinfo is None:
            return []
        observed = observed.astimezone(timezone.utc)
        if observed > datetime.now(timezone.utc) + timedelta(minutes=5):
            return []
        contract = str(bar["exact_contract"] or "").strip().upper()
        timeframe = _normalize_timeframe(bar["timeframe"])
        if not _CONTRACT_RE.fullmatch(contract) or not _TIMEFRAME_RE.fullmatch(timeframe):
            return []
        series_key = (contract, timeframe)
        if series_key in last_by_series and observed <= last_by_series[series_key]:
            return []
        last_by_series[series_key] = observed
        clean.append({
            "open": o, "high": h, "low": l, "close": c,
            "volume": int(raw_volume),
            "timestamp": observed.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "exact_contract": contract,
            "timeframe": timeframe,
        })
    return clean


def _timeframe_seconds(value: str) -> int:
    text = str(value or "1m")
    match = re.fullmatch(r"([1-9][0-9]*)([smhDWM])", text)
    if not match:
        return 60
    number = int(match.group(1))
    unit = match.group(2)
    factor = {"s": 1, "m": 60, "h": 3600, "D": 86400,
              "W": 604800, "M": 2_592_000}[unit]
    return min(number * factor, 31_536_000)


def _series_times(series_bars: List[Dict[str, Any]], timeframe: str) -> tuple[datetime, datetime]:
    observed = datetime.fromisoformat(
        str(series_bars[-1]["timestamp"]).replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    freshness_window = max(30, min(900, _timeframe_seconds(timeframe) * 2))
    return observed, observed + timedelta(seconds=freshness_window)


def ingest_batch(
    workspace_id: str,
    installation_id: str,
    source_sequence: int,
    bars: List[Dict[str, Any]],
    *,
    user_id: int = 0,
) -> Dict[str, Any]:
    """Validate, dedup and store a batch of OHLCV bars."""
    try:
        seq = int(source_sequence)
    except (TypeError, ValueError):
        seq = 0
    ws = str(workspace_id or "").strip()
    inst = str(installation_id or "").strip()
    clean = _validate_bars(bars)
    if not ws or not inst or seq <= 0 or not clean:
        return {"ok": False, "code": "empty_or_invalid_batch", "batch_id": "", "items": 0, "deduplicated": False}

    sha = _payload_sha256(clean)
    batch_id = "mdb_" + uuid.uuid4().hex
    series = _series_by_contract(clean)

    if _is_prod():
        from .production_storage import Scope, StorageError, get_client
        from .production_storage.core import _jsonb
        try:
            scope = Scope.workspace_scope(ws)
            with get_client().transaction(scope) as conn:
                existing = conn.execute(
                    """SELECT batch_id, payload_sha256
                       FROM sf_market_data_ingest_batches
                       WHERE installation_id=%s AND source_sequence=%s""",
                    (inst, seq),
                ).fetchone()
                if existing:
                    if str(existing["payload_sha256"] or "") != sha:
                        return {"ok": False, "code": "source_sequence_conflict",
                                "batch_id": "", "items": 0, "deduplicated": False}
                    return {"ok": True, "batch_id": str(existing["batch_id"]),
                            "items": len(clean), "deduplicated": True}
                conn.execute(
                    """INSERT INTO sf_market_data_ingest_batches(
                         batch_id,workspace_id,installation_id,source_sequence,
                         payload_sha256,item_count
                       ) VALUES(%s,%s,%s,%s,%s,%s)""",
                    (batch_id, ws, inst, seq, sha, len(clean)),
                )
                # Keep the bounded bars with their matching series so a
                # snapshot can feed a chart without another shared filesystem.
                for (contract, timeframe), series_bars in series.items():
                    observed_at, stale_after = _series_times(
                        series_bars, timeframe,
                    )
                    sig = hashlib.sha256(
                        f"{inst}:{seq}:{contract}:{timeframe}".encode("utf-8")
                    ).hexdigest()
                    conn.execute(
                        """INSERT INTO sf_market_data_snapshots(
                             workspace_id,installation_id,exact_contract,timeframe,
                             source_sequence,source_signature,payload_sha256,
                             observed_at,stale_after,document
                           ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(workspace_id,installation_id,exact_contract,timeframe)
                           DO UPDATE SET source_sequence=EXCLUDED.source_sequence,
                             source_signature=EXCLUDED.source_signature,
                             payload_sha256=EXCLUDED.payload_sha256,
                             observed_at=EXCLUDED.observed_at,
                             stale_after=EXCLUDED.stale_after,
                             document=EXCLUDED.document
                           WHERE sf_market_data_snapshots.source_sequence<EXCLUDED.source_sequence""",
                        (
                            ws, inst, contract, timeframe, seq, sig, sha,
                            observed_at, stale_after,
                            _jsonb({"bars": series_bars, "bars_count": len(series_bars)}),
                        ),
                    )
        except StorageError:
            return {"ok": False, "code": "storage_unavailable",
                    "batch_id": "", "items": 0, "deduplicated": False}
    else:
        # Development: in-memory storage
        with _LOCK:
            for batch in _DEV_BATCHES:
                if (
                    batch.get("installation_id") == inst
                    and int(batch.get("source_sequence") or 0) == seq
                ):
                    if batch.get("payload_sha256") != sha:
                        return {"ok": False, "code": "source_sequence_conflict",
                                "batch_id": "", "items": 0, "deduplicated": False}
                    return {"ok": True, "batch_id": batch["batch_id"],
                            "items": len(clean), "deduplicated": True}
            _DEV_BATCHES.append({
                "batch_id": batch_id, "workspace_id": ws,
                "installation_id": inst, "source_sequence": seq,
                "payload_sha256": sha, "item_count": len(clean),
            })
            for (contract, timeframe), series_bars in series.items():
                key = _sub_key(ws, inst, contract, timeframe)
                observed_at, stale_after = _series_times(
                    series_bars, timeframe,
                )
                _DEV_SNAPSHOTS[key] = {
                    "workspace_id": ws, "installation_id": inst,
                    "exact_contract": contract, "timeframe": timeframe,
                    "source_sequence": seq, "bar": series_bars[-1],
                    "document": {"bars": series_bars, "bars_count": len(series_bars)},
                    "source_signature": hashlib.sha256(
                        f"{inst}:{seq}:{contract}:{timeframe}".encode("utf-8")
                    ).hexdigest(),
                    "payload_sha256": sha,
                    "observed_at": observed_at,
                    "received_at": datetime.now(timezone.utc),
                    "stale_after": stale_after,
                }

    # Publish to event bus (both modes)
    try:
        platform = get_platform()
        platform.bus.publish("market_data.batch", {
            "batch_id": batch_id, "workspace_id": ws,
            "installation_id": inst, "items": len(clean),
        })
    except Exception:
        pass

    observability.event(
        "market_data", "batch_ingested",
        payload={"batch_id": batch_id, "items": len(clean),
                 "workspace_id": ws, "installation_id": inst},
    )
    return {"ok": True, "batch_id": batch_id,
            "items": len(clean), "deduplicated": False}


def latest_snapshot(
    workspace_id: str,
    installation_id: str,
    exact_contract: str,
    timeframe: str,
) -> Optional[Dict[str, Any]]:
    """Return the most recent snapshot for a contract/timeframe pair."""
    ws = str(workspace_id or "")
    inst = str(installation_id or "")
    contract = str(exact_contract or "").upper()
    tf = _normalize_timeframe(timeframe or "1m")
    if not ws or not inst or not _CONTRACT_RE.fullmatch(contract) or not tf:
        return None

    if _is_prod():
        from .production_storage import Scope, StorageError, get_client
        try:
            scope = Scope.workspace_scope(ws)
            with get_client().transaction(scope, read_only=True) as conn:
                row = conn.execute(
                    """SELECT * FROM sf_market_data_snapshots
                       WHERE workspace_id=%s AND installation_id=%s
                         AND exact_contract=%s AND timeframe=%s""",
                    (ws, inst, contract, tf),
                ).fetchone()
            return dict(row) if row else None
        except StorageError:
            return None
    else:
        key = _sub_key(ws, inst, contract, tf)
        with _LOCK:
            return dict(_DEV_SNAPSHOTS.get(key) or {}) or None


def latest_workspace_snapshot(
    workspace_id: str,
    exact_contract: str,
    timeframe: str,
) -> Optional[Dict[str, Any]]:
    """Return the newest snapshot visible to exactly one workspace.

    Installation identity is intentionally not supplied by the browser.  The
    authenticated workspace boundary selects the newest stream across that
    workspace's Connector installations, while PostgreSQL RLS provides a
    second enforcement layer in Production.
    """
    ws = str(workspace_id or "").strip()
    contract = str(exact_contract or "").strip().upper()
    tf = _normalize_timeframe(timeframe or "1m")
    if not ws or not _CONTRACT_RE.fullmatch(contract) or not _TIMEFRAME_RE.fullmatch(tf):
        return None

    if _is_prod():
        from .production_storage import Scope, StorageError, get_client
        try:
            scope = Scope.workspace_scope(ws)
            with get_client().transaction(scope, read_only=True) as conn:
                row = conn.execute(
                    """SELECT * FROM sf_market_data_snapshots
                       WHERE workspace_id=%s AND exact_contract=%s
                         AND timeframe=%s
                       ORDER BY observed_at DESC,received_at DESC,
                         source_sequence DESC
                       LIMIT 1""",
                    (ws, contract, tf),
                ).fetchone()
            return dict(row) if row else None
        except StorageError:
            return None

    with _LOCK:
        candidates = [
            dict(row) for row in _DEV_SNAPSHOTS.values()
            if row.get("workspace_id") == ws
            and row.get("exact_contract") == contract
            and row.get("timeframe") == tf
        ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            str(row.get("observed_at") or ""),
            str(row.get("received_at") or ""),
            int(row.get("source_sequence") or 0),
        ),
    )


def workspace_snapshot_index(workspace_id: str) -> Dict[str, Any]:
    """Read every newest tenant snapshot in one bounded query.

    This is the batch-chart primitive: one authenticated workspace query feeds
    as many as 64 chart requests without falling back to Development IPC.
    """
    ws = str(workspace_id or "").strip()
    if not ws:
        return {"workspace_id": "", "snapshots": {}, "source_signature": "", "storage_available": False}
    rows: List[Dict[str, Any]] = []
    storage_available = True
    if _is_prod():
        from .production_storage import Scope, StorageError, get_client
        try:
            with get_client().transaction(Scope.workspace_scope(ws), read_only=True) as conn:
                source_rows = conn.execute(
                    """SELECT DISTINCT ON (exact_contract,timeframe) *
                       FROM sf_market_data_snapshots
                       WHERE workspace_id=%s
                       ORDER BY exact_contract,timeframe,
                         observed_at DESC,received_at DESC,
                         source_sequence DESC""",
                    (ws,),
                ).fetchall()
            rows = [dict(row) for row in source_rows]
        except StorageError:
            storage_available = False
    else:
        with _LOCK:
            candidates = [
                dict(row) for row in _DEV_SNAPSHOTS.values()
                if row.get("workspace_id") == ws
            ]
        newest: Dict[str, Dict[str, Any]] = {}
        for row in candidates:
            key = f"{row.get('exact_contract')}|{row.get('timeframe')}"
            prior = newest.get(key)
            if prior is None or (
                str(row.get("observed_at") or ""), str(row.get("received_at") or ""),
                int(row.get("source_sequence") or 0)
            ) > (
                str(prior.get("observed_at") or ""), str(prior.get("received_at") or ""),
                int(prior.get("source_sequence") or 0)
            ):
                newest[key] = row
        rows = list(newest.values())
    snapshots = {
        f"{str(row.get('exact_contract') or '').upper()}|{str(row.get('timeframe') or '')}": row
        for row in rows
        if str(row.get("exact_contract") or "") and str(row.get("timeframe") or "")
    }
    signature_rows = [
        {
            "key": key,
            "source_sequence": int(row.get("source_sequence") or 0),
            "source_signature": str(row.get("source_signature") or ""),
        }
        for key, row in sorted(snapshots.items())
    ]
    signature = hashlib.sha256(_canonical(signature_rows)).hexdigest() if signature_rows else ""
    return {
        "workspace_id": ws,
        "snapshots": snapshots,
        "source_signature": signature,
        "storage_available": storage_available,
    }


def _utc_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def workspace_series(
    workspace_id: str,
    exact_contract: str,
    timeframe: str,
    limit: int = 1500,
    *,
    snapshot_index: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Convert a tenant-bound Connector snapshot into a chart-safe payload."""
    normalized_tf = _normalize_timeframe(timeframe or "1m")
    if not normalized_tf:
        return None
    if snapshot_index is not None:
        if str(snapshot_index.get("workspace_id") or "") != str(workspace_id or ""):
            return None
        candidates = snapshot_index.get("snapshots")
        candidates = candidates if isinstance(candidates, Mapping) else {}
        snapshot = candidates.get(
            f"{str(exact_contract or '').strip().upper()}|{normalized_tf}"
        )
        snapshot = dict(snapshot) if isinstance(snapshot, Mapping) else None
    else:
        snapshot = latest_workspace_snapshot(workspace_id, exact_contract, normalized_tf)
    if not snapshot:
        return None
    document = snapshot.get("document")
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except (TypeError, ValueError):
            document = {}
    if not isinstance(document, dict):
        document = {}
    raw_bars = document.get("bars") if isinstance(document.get("bars"), list) else []
    validated_bars = _validate_bars(raw_bars)
    if not validated_bars:
        return None
    try:
        capped = max(1, min(50_000, int(limit or 1500)))
    except (TypeError, ValueError):
        capped = 1500
    bars = [
        {
            "t": str(row.get("timestamp") or ""),
            "o": float(row["open"]),
            "h": float(row["high"]),
            "l": float(row["low"]),
            "c": float(row["close"]),
            "v": int(row["volume"]),
        }
        for row in validated_bars
    ][-capped:]
    if not bars:
        return None

    now = datetime.now(timezone.utc)
    observed = _utc_datetime(snapshot.get("observed_at"))
    stale_after = _utc_datetime(snapshot.get("stale_after"))
    received = _utc_datetime(snapshot.get("received_at"))
    age = max(0.0, (now - observed).total_seconds()) if observed else None
    max_age = (
        max(0.0, (stale_after - observed).total_seconds())
        if stale_after and observed else float(max(30, min(900, _timeframe_seconds(normalized_tf) * 2)))
    )
    fresh = bool(observed and stale_after and now <= stale_after)
    observed_iso = (
        observed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if observed else ""
    )
    stale_iso = (
        stale_after.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if stale_after else ""
    )
    received_iso = (
        received.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if received else ""
    )
    last = float(bars[-1]["c"])
    return {
        "instrument": str(snapshot.get("exact_contract") or exact_contract),
        "bars": bars,
        "total": len(bars),
        "raw_total": len(raw_bars),
        "live": fresh,
        "status": "live" if fresh else "offline",
        "requested_timeframe": normalized_tf,
        "matched_timeframe": str(snapshot.get("timeframe") or normalized_tf),
        "source": {
            "kind": "connector_remote",
            "provider": "ninjatrader",
            "transport": "connector_https",
            "workspace_id": str(workspace_id or ""),
            "installation_id": str(snapshot.get("installation_id") or ""),
            "source_sequence": int(snapshot.get("source_sequence") or 0),
            "source_signature": str(snapshot.get("source_signature") or ""),
            "payload_sha256": str(snapshot.get("payload_sha256") or ""),
            "updated_at_utc": observed_iso,
            "received_at_utc": received_iso,
            "stale_after_utc": stale_iso,
            "age_sec": age,
            "fresh": fresh,
            "live_eligible": fresh,
            "runtime_state": "LIVE" if fresh else "OFFLINE",
        },
        "freshness": {
            "fresh": fresh,
            "stale": not fresh,
            "offline": not fresh,
            "age_sec": age,
            "max_age_sec": max_age,
            "data_as_of_utc": observed_iso,
            "stale_after_utc": stale_iso,
            "live_eligible": fresh,
        },
        "quote": {"last": last, "source": "ninjatrader_connector"},
        "market_data_available": fresh,
        "strategy_blocked": not fresh,
        "execution_blocked": not fresh,
        "price_marker_live": fresh,
    }


def subscribe(
    workspace_id: str,
    installation_id: str,
    user_id: int,
    exact_contract: str,
    timeframe: str,
    *,
    max_bars: int = 1500,
    ttl_sec: int = 300,
) -> Dict[str, Any]:
    """Register a market-data subscription."""
    ws = str(workspace_id or "")
    inst = str(installation_id or "")
    contract = str(exact_contract or "").strip().upper()
    tf = _normalize_timeframe(timeframe or "1m")
    try:
        normalized_user_id = int(user_id)
        capped_bars = max(100, min(int(max_bars), 10000))
        ttl = max(30, min(int(ttl_sec), 3600))
    except (TypeError, ValueError):
        return {"ok": False, "code": "invalid_subscription"}
    if (
        not ws or not inst or normalized_user_id <= 0
        or not _CONTRACT_RE.fullmatch(contract) or not tf
    ):
        return {"ok": False, "code": "invalid_subscription"}

    if _is_prod():
        from .production_storage import Scope, StorageError, get_client
        try:
            scope = Scope.workspace_scope(ws)
            with get_client().transaction(scope) as conn:
                conn.execute(
                    """INSERT INTO sf_market_data_subscriptions(
                         workspace_id,installation_id,requested_by_user_id,
                         exact_contract,timeframe,max_bars,status,
                         expires_at
                       ) VALUES(%s,%s,%s,%s,%s,%s,'active',
                         clock_timestamp()+(%s*interval '1 second'))
                       ON CONFLICT(workspace_id,installation_id,exact_contract,timeframe)
                       DO UPDATE SET status='active',max_bars=EXCLUDED.max_bars,
                         expires_at=EXCLUDED.expires_at""",
                    (ws, inst, normalized_user_id, contract, tf, capped_bars, ttl),
                )
            return {"ok": True, "code": "subscribed"}
        except StorageError:
            return {"ok": False, "code": "storage_unavailable"}
    else:
        key = _sub_key(ws, inst, contract, tf)
        with _LOCK:
            _DEV_SUBSCRIPTIONS[key] = {
                "workspace_id": ws, "installation_id": inst,
                "exact_contract": contract, "timeframe": tf,
                "max_bars": capped_bars, "status": "active",
            }
        return {"ok": True, "code": "subscribed"}


def unsubscribe(
    workspace_id: str,
    installation_id: str,
    exact_contract: str,
    timeframe: str,
) -> bool:
    """Deactivate a market-data subscription."""
    ws = str(workspace_id or "")
    inst = str(installation_id or "")
    contract = str(exact_contract or "").upper()
    tf = _normalize_timeframe(timeframe)
    if not ws or not inst or not _CONTRACT_RE.fullmatch(contract) or not tf:
        return False

    if _is_prod():
        from .production_storage import Scope, StorageError, get_client
        try:
            scope = Scope.workspace_scope(ws)
            with get_client().transaction(scope) as conn:
                conn.execute(
                    """UPDATE sf_market_data_subscriptions SET status='deleted'
                       WHERE workspace_id=%s AND installation_id=%s
                         AND exact_contract=%s AND timeframe=%s""",
                    (ws, inst, contract, tf),
                )
            return True
        except StorageError:
            return False
    else:
        key = _sub_key(ws, inst, contract, tf)
        with _LOCK:
            if key in _DEV_SUBSCRIPTIONS:
                _DEV_SUBSCRIPTIONS[key]["status"] = "deleted"
                return True
            return False


def active_subscriptions(
    workspace_id: str,
    installation_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List active subscriptions for a workspace."""
    ws = str(workspace_id or "")

    if _is_prod():
        from .production_storage import Scope, StorageError, get_client
        try:
            scope = Scope.workspace_scope(ws)
            with get_client().transaction(scope, read_only=True) as conn:
                if installation_id:
                    rows = conn.execute(
                        """SELECT * FROM sf_market_data_subscriptions
                           WHERE workspace_id=%s AND installation_id=%s
                             AND status='active' AND expires_at>clock_timestamp()""",
                        (ws, str(installation_id)),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT * FROM sf_market_data_subscriptions
                           WHERE workspace_id=%s AND status='active'
                             AND expires_at>clock_timestamp()""",
                        (ws,),
                    ).fetchall()
            return [dict(r) for r in rows]
        except StorageError:
            return []
    else:
        with _LOCK:
            out = []
            for key, sub in _DEV_SUBSCRIPTIONS.items():
                if sub["workspace_id"] == ws and sub["status"] == "active":
                    if installation_id and sub["installation_id"] != str(installation_id):
                        continue
                    out.append(dict(sub))
            return out


def fan_out(
    workspace_id: str,
    bars: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Distribute bars to all active subscriptions that match the contract/timeframe."""
    ws = str(workspace_id or "")
    subs = active_subscriptions(ws)
    if not subs:
        return {"ok": True, "distributed": 0, "subscriptions": 0}
    # Group bars by (contract, timeframe)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for bar in (bars or []):
        if not isinstance(bar, dict):
            continue
        key = f"{str(bar.get('exact_contract') or '').upper()}|{bar.get('timeframe') or '1m'}"
        grouped[key].append(bar)
    distributed = 0
    for sub in subs:
        key = f"{sub['exact_contract']}|{sub['timeframe']}"
        matching = grouped.get(key)
        if matching:
            capped = matching[:int(sub.get("max_bars") or 1500)]
            try:
                platform = get_platform()
                platform.bus.publish("market_data.fan_out", {
                    "workspace_id": ws,
                    "installation_id": sub["installation_id"],
                    "exact_contract": sub["exact_contract"],
                    "timeframe": sub["timeframe"],
                    "bars_count": len(capped),
                })
            except Exception:
                pass
            distributed += 1
    return {"ok": True, "distributed": distributed, "subscriptions": len(subs)}


def reset_for_tests() -> None:
    """Clear all in-memory development state."""
    with _LOCK:
        _DEV_BATCHES.clear()
        _DEV_SNAPSHOTS.clear()
        _DEV_SUBSCRIPTIONS.clear()
