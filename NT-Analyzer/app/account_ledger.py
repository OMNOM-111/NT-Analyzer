"""Durable account snapshots with conservative cash-flow attribution.

NinjaTrader's current account export has no transaction ledger. Balance deltas
that cannot be explained by realised/unrealised P&L are therefore stored as
``unclassified_adjustment`` until a human classifies them. They are never
reported as strategy profit or silently labelled as deposits.
"""
from __future__ import annotations

import json
import math
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


LEDGER_PATH = Path(__file__).resolve().parents[1] / "data" / "runtime" / "account_ledger.json"
_LOCK = threading.RLock()
_KINDS = {
    "deposit", "withdrawal", "transfer", "fee", "reconciliation",
    "unclassified_adjustment",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _event_amount(kind: str, value: Any) -> float:
    amount = _number(value)
    if abs(amount) < 0.01:
        raise ValueError("event amount must be non-zero")
    if kind == "deposit":
        return abs(amount)
    if kind in {"withdrawal", "fee"}:
        return -abs(amount)
    return amount


def _timestamp(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return _now()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("at_utc must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("at_utc must include a timezone offset")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty() -> Dict[str, Any]:
    return {"schema_version": 1, "updated_at_utc": _now(), "accounts": {}}


def _read() -> Dict[str, Any]:
    if not LEDGER_PATH.exists():
        return _empty()
    try:
        doc = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"account ledger is unreadable: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("accounts"), dict):
        raise RuntimeError("account ledger has invalid shape")
    return doc


def _write(doc: Dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at_utc"] = _now()
    tmp = LEDGER_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LEDGER_PATH)


def _repair_fallback_artifacts(doc: Dict[str, Any]) -> bool:
    """Remove balance changes inferred from a source that has no balances.

    ``positions_fallback`` reports account identity only. Older builds
    normalised its missing balance fields to zero and could create a false
    withdrawal followed by a false deposit when accounts.json returned.
    Manual/imported and human-classified entries are never touched.
    """
    changed = False
    for account in (doc.get("accounts") or {}).values():
        snapshots = list(account.get("snapshots") or [])
        valid = [row for row in snapshots if str(row.get("source") or "") != "positions_fallback"]
        if len(valid) != len(snapshots):
            account["snapshots"] = valid
            changed = True

        expected: Dict[str, float] = {}
        for previous, current in zip(valid, valid[1:]):
            equity_delta = round(_number(current.get("net_liquidation")) - _number(previous.get("net_liquidation")), 2)
            trading_delta = round(
                (_number(current.get("realized_pnl")) - _number(previous.get("realized_pnl")))
                + (_number(current.get("unrealized_pnl")) - _number(previous.get("unrealized_pnl"))), 2
            )
            unexplained = round(equity_delta - trading_delta, 2)
            if abs(unexplained) >= 0.01:
                expected[str(current.get("at_utc") or "")] = unexplained

        repaired_events = []
        for event in account.get("events") or []:
            derived = event.get("provenance") == "derived_from_net_liquidation_minus_runtime_pnl_delta"
            unreviewed = event.get("classification_status") == "needs_review"
            if derived and unreviewed:
                expected_amount = expected.get(str(event.get("at_utc") or ""))
                if expected_amount is None or abs(_number(event.get("amount")) - expected_amount) >= 0.01:
                    changed = True
                    continue
            repaired_events.append(event)
        account["events"] = repaired_events
    return changed


def record_accounts(payload: Dict[str, Any]) -> None:
    # A positions-only fallback has no authoritative account balance fields.
    if str(payload.get("source") or "") == "positions_fallback":
        return
    rows = payload.get("accounts") or payload.get("online_accounts") or []
    if not isinstance(rows, list):
        return
    with _LOCK:
        doc = _read()
        changed = _repair_fallback_artifacts(doc)
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            if raw.get("is_system"):
                continue
            name = str(raw.get("account_name") or "").strip()
            if not name:
                continue
            account = doc["accounts"].setdefault(name, {"snapshots": [], "events": []})
            snapshots: List[Dict[str, Any]] = account.setdefault("snapshots", [])
            snapshot = {
                "at_utc": str(payload.get("accounts_generated_at_utc") or _now()),
                "net_liquidation": _number(raw.get("net_liquidation")),
                "cash_value": _number(raw.get("cash_value")),
                "realized_pnl": _number(raw.get("realized_pnl")),
                "unrealized_pnl": _number(raw.get("unrealized_pnl")),
                "source": str(payload.get("source") or "runtime_accounts"),
                "exporter_version": payload.get("exporter_version"),
            }
            previous = snapshots[-1] if snapshots else None
            comparable = ("net_liquidation", "cash_value", "realized_pnl", "unrealized_pnl")
            if previous and all(previous.get(key) == snapshot.get(key) for key in comparable):
                continue
            snapshots.append(snapshot)
            if len(snapshots) > 5000:
                del snapshots[:-5000]
            if previous:
                equity_delta = round(snapshot["net_liquidation"] - _number(previous.get("net_liquidation")), 2)
                trading_delta = round(
                    (snapshot["realized_pnl"] - _number(previous.get("realized_pnl")))
                    + (snapshot["unrealized_pnl"] - _number(previous.get("unrealized_pnl"))), 2
                )
                unexplained = round(equity_delta - trading_delta, 2)
                if abs(unexplained) >= 0.01:
                    account.setdefault("events", []).append({
                        "event_id": "EVT-" + uuid.uuid4().hex[:12],
                        "at_utc": snapshot["at_utc"],
                        "kind": "unclassified_adjustment",
                        "amount": unexplained,
                        "equity_delta": equity_delta,
                        "trading_pnl_delta": trading_delta,
                        "provenance": "derived_from_net_liquidation_minus_runtime_pnl_delta",
                        "classification_status": "needs_review",
                        "actor": "system",
                        "note": "Не классифицировано: источник не предоставляет broker cash transactions.",
                    })
            changed = True
        if changed:
            _write(doc)


def account_history(account_name: str = "", limit: int = 500) -> Dict[str, Any]:
    with _LOCK:
        doc = _read()
        if _repair_fallback_artifacts(doc):
            _write(doc)
    names = [account_name] if account_name else sorted(doc["accounts"])
    rows = []
    for name in names:
        item = doc["accounts"].get(name)
        if not item:
            continue
        snapshots = list(item.get("snapshots") or [])[-max(1, min(int(limit), 5000)):]
        events = list(item.get("events") or [])[-max(1, min(int(limit), 5000)):]
        classified = [event for event in events if event.get("classification_status") == "classified"]
        flow_by_kind = {
            kind: round(sum(_number(event.get("amount")) for event in classified if event.get("kind") == kind), 2)
            for kind in ("deposit", "withdrawal", "transfer", "fee")
        }
        rows.append({
            "account_name": name,
            "snapshots": snapshots,
            "events": events,
            "summary": {
                "snapshots": len(snapshots),
                "events": len(events),
                "needs_review": sum(1 for event in events if event.get("classification_status") == "needs_review"),
                "classified_cash_flow": round(sum(flow_by_kind.values()), 2),
                "flow_by_kind": flow_by_kind,
            },
        })
    return {
        "ok": True,
        "generated_at_utc": _now(),
        "accounts": rows,
        "cash_flow_capability": "derived_unclassified_only",
        "cash_flow_note": "Broker transaction history is unavailable; unexplained balance deltas require manual classification.",
    }


def audit_integrity(account_name: str = "", *, repair_safe: bool = False) -> Dict[str, Any]:
    """Find ledger corruption and remove only byte-equivalent safe duplicates.

    A safe repair never guesses a financial classification or amount. It may
    only remove a repeated snapshot with the same timestamp/source/values, a
    repeated source_id with identical financial fields, or a repeated
    system-derived unclassified adjustment. Every other anomaly is reported
    for a person to review.
    """
    with _LOCK:
        doc = _read()
        issues: List[Dict[str, Any]] = []
        repaired: List[Dict[str, Any]] = []
        names = [account_name] if account_name else sorted(doc["accounts"])
        changed = False
        for name in names:
            account = doc["accounts"].get(name)
            if not account:
                continue
            snapshots = list(account.get("snapshots") or [])
            kept_snapshots: List[Dict[str, Any]] = []
            seen_snapshots: Dict[tuple, int] = {}
            for index, row in enumerate(snapshots):
                signature = (
                    str(row.get("at_utc") or ""), str(row.get("source") or ""),
                    _number(row.get("net_liquidation")), _number(row.get("cash_value")),
                    _number(row.get("realized_pnl")), _number(row.get("unrealized_pnl")),
                )
                if signature in seen_snapshots:
                    issue = {"code": "duplicate_snapshot", "account_name": name, "index": index, "safe_to_repair": True}
                    issues.append(issue)
                    if repair_safe:
                        repaired.append(issue)
                        changed = True
                        continue
                else:
                    seen_snapshots[signature] = index
                kept_snapshots.append(row)

            events = list(account.get("events") or [])
            kept_events: List[Dict[str, Any]] = []
            seen_source: Dict[str, Dict[str, Any]] = {}
            seen_derived: Dict[tuple, Dict[str, Any]] = {}
            for row in events:
                event_id = str(row.get("event_id") or "")
                try:
                    raw_amount = float(row.get("amount"))
                    finite = math.isfinite(raw_amount)
                except (TypeError, ValueError):
                    finite = False
                if not finite:
                    issues.append({"code": "invalid_amount", "account_name": name, "event_id": event_id, "safe_to_repair": False})
                source_id = str(row.get("source_id") or "").strip()
                core = (
                    str(row.get("at_utc") or ""), str(row.get("kind") or ""),
                    _number(row.get("amount")), str(row.get("provenance") or ""),
                )
                duplicate = False
                if source_id and source_id in seen_source:
                    previous = seen_source[source_id]
                    previous_core = (
                        str(previous.get("at_utc") or ""), str(previous.get("kind") or ""),
                        _number(previous.get("amount")), str(previous.get("provenance") or ""),
                    )
                    safe = core == previous_core
                    issue = {"code": "duplicate_source_id", "account_name": name, "event_id": event_id, "source_id": source_id, "safe_to_repair": safe}
                    issues.append(issue)
                    duplicate = bool(safe and repair_safe)
                elif source_id:
                    seen_source[source_id] = row
                derived = (
                    row.get("provenance") == "derived_from_net_liquidation_minus_runtime_pnl_delta"
                    and row.get("classification_status") == "needs_review"
                )
                if derived:
                    derived_key = (str(row.get("at_utc") or ""), _number(row.get("amount")), str(row.get("kind") or ""))
                    if derived_key in seen_derived:
                        issue = {"code": "duplicate_derived_adjustment", "account_name": name, "event_id": event_id, "safe_to_repair": True}
                        issues.append(issue)
                        duplicate = bool(repair_safe)
                    else:
                        seen_derived[derived_key] = row
                if duplicate:
                    repaired.append(issues[-1])
                    changed = True
                    continue
                kept_events.append(row)
            if repair_safe:
                account["snapshots"] = kept_snapshots
                account["events"] = kept_events
        if changed:
            _write(doc)
        return {
            "ok": True,
            "generated_at_utc": _now(),
            "account": account_name or "__all__",
            "issues": issues,
            "repaired": repaired,
            "repair_policy": "exact_duplicates_only",
            "requires_review": sum(1 for row in issues if not row.get("safe_to_repair")),
        }


def classify_event(account_name: str, event_id: str, kind: str, actor: str, note: str = "") -> Dict[str, Any]:
    kind = str(kind or "").strip().lower()
    if kind not in _KINDS - {"unclassified_adjustment"}:
        raise ValueError("kind must be deposit, withdrawal, transfer, fee, or reconciliation")
    with _LOCK:
        doc = _read()
        account = doc["accounts"].get(str(account_name or "").strip())
        if not account:
            raise ValueError("account not found in ledger")
        event = next((row for row in account.get("events", []) if row.get("event_id") == event_id), None)
        if not event:
            raise ValueError("ledger event not found")
        amount = _number(event.get("amount"))
        if kind == "deposit" and amount < 0:
            raise ValueError("negative adjustment cannot be classified as a deposit")
        if kind in {"withdrawal", "fee"} and amount > 0:
            raise ValueError(f"positive adjustment cannot be classified as {kind}")
        event["kind"] = kind
        event["classification_status"] = "classified"
        event["actor"] = str(actor or "ui")
        event["note"] = str(note or "")
        event["classified_at_utc"] = _now()
        _write(doc)
        return {"ok": True, "event": event}


def add_event(account_name: str, kind: str, amount: Any, actor: str, note: str = "",
              at_utc: Any = None, source: str = "manual", source_id: str = "") -> Dict[str, Any]:
    kind = str(kind or "").strip().lower()
    if kind not in _KINDS - {"unclassified_adjustment"}:
        raise ValueError("kind must be deposit, withdrawal, transfer, fee, or reconciliation")
    account_name = str(account_name or "").strip()
    if not account_name:
        raise ValueError("account_name is required")
    actor = str(actor or "").strip()
    if not actor:
        raise ValueError("actor is required")
    source_id = str(source_id or "").strip()
    with _LOCK:
        doc = _read()
        account = doc["accounts"].setdefault(account_name, {"snapshots": [], "events": []})
        events = account.setdefault("events", [])
        if source_id:
            duplicate = next((event for event in events if event.get("source_id") == source_id), None)
            if duplicate:
                return {"ok": True, "duplicate": True, "event": duplicate}
        event = {
            "event_id": "EVT-" + uuid.uuid4().hex[:12],
            "at_utc": _timestamp(at_utc),
            "kind": kind,
            "amount": _event_amount(kind, amount),
            "provenance": str(source or "manual"),
            "source_id": source_id or None,
            "classification_status": "classified",
            "actor": actor,
            "note": str(note or ""),
            "classified_at_utc": _now(),
        }
        events.append(event)
        _write(doc)
        return {"ok": True, "duplicate": False, "event": event}


def import_events(account_name: str, rows: List[Dict[str, Any]], actor: str,
                  source: str = "broker_statement") -> Dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows must be a non-empty list")
    if len(rows) > 5000:
        raise ValueError("rows exceeds the 5000 event limit")
    account_name = str(account_name or "").strip()
    actor = str(actor or "").strip()
    if not account_name or not actor:
        raise ValueError("account_name and actor are required")
    prepared: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {index + 1} must be an object")
        kind = str(row.get("kind") or "").strip().lower()
        if kind not in _KINDS - {"unclassified_adjustment"}:
            raise ValueError(f"row {index + 1}: invalid kind")
        prepared.append({
            "at_utc": _timestamp(row.get("at_utc")),
            "kind": kind,
            "amount": _event_amount(kind, row.get("amount")),
            "note": str(row.get("note") or ""),
            "source_id": str(row.get("source_id") or "").strip(),
        })
    with _LOCK:
        doc = _read()
        account = doc["accounts"].setdefault(account_name, {"snapshots": [], "events": []})
        events = account.setdefault("events", [])
        existing = {str(event.get("source_id")) for event in events if event.get("source_id")}
        imported = 0
        duplicates = 0
        event_ids: List[str] = []
        for row in prepared:
            if row["source_id"] and row["source_id"] in existing:
                duplicate = next(event for event in events if event.get("source_id") == row["source_id"])
                event_ids.append(str(duplicate["event_id"]))
                duplicates += 1
                continue
            event = {
                "event_id": "EVT-" + uuid.uuid4().hex[:12],
                "at_utc": row["at_utc"],
                "kind": row["kind"],
                "amount": row["amount"],
                "provenance": str(source or "broker_statement"),
                "source_id": row["source_id"] or None,
                "classification_status": "classified",
                "actor": actor,
                "note": row["note"],
                "classified_at_utc": _now(),
            }
            events.append(event)
            if row["source_id"]:
                existing.add(row["source_id"])
            event_ids.append(event["event_id"])
            imported += 1
        if imported:
            _write(doc)
        return {"ok": True, "imported": imported, "duplicates": duplicates, "event_ids": event_ids}
