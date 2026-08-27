"""Parallel live market-data adapters (Databento first; others scaffolded).

These are independent *quote sources*, not cache/Redis/WS infrastructure.

Rules:
- Recorded/FaultInjection never get REALTIME_PRODUCTION.
- Yahoo never gets automatic production failover.
- Automatic failover requires shadow parity pass + explicit allow flag.
- Without credentials, adapters stay ENTITLEMENT_MISSING / DISABLED.
"""
from __future__ import annotations

import os
import re
import threading
import time
import json
import hashlib
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from . import local_secrets, runtime_env, secure_store
from .canonical_event import make_canonical_event
from .instrument_registry import get_registry

EventSink = Callable[[Dict[str, Any]], None]

_CONTRACT_RE = re.compile(r"^([A-Z0-9]+)\s+(\d{2})-(\d{2})$")
_MONTH_CODE = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
_CODE_MONTH = {code: month for month, code in _MONTH_CODE.items()}
_TOPSTEP_HISTORY_MAX_BARS = 20_000
_TOPSTEP_HISTORY_RETRIES = 3
_TOPSTEP_VALIDATE_ERROR_NAMES = {
    0: "SUCCESS",
    1: "INVALID_SESSION",
    2: "SESSION_NOT_FOUND",
    3: "EXPIRED_TOKEN",
    4: "UNKNOWN_ERROR",
}


def topstep_timeframe_spec(value: Any) -> tuple[int, int, int, str]:
    """Map StratForge chart timeframes to ProjectX History aggregation.

    ProjectX uses ``unit`` values 1..6 for second/minute/hour/day/week/month.
    Keep the case-sensitive ``M`` month suffix distinct from ``m`` minutes.
    """
    raw = str(value or "5m").strip()
    match = re.fullmatch(r"(\d+)\s*([smhdwMDW])", raw)
    if not match:
        raise ValueError(f"Unsupported TopstepX timeframe: {value}")
    number = max(1, int(match.group(1)))
    suffix = {"D": "d", "W": "w"}.get(match.group(2), match.group(2))
    units = {"s": 1, "m": 2, "h": 3, "d": 4, "w": 5, "M": 6}
    # Nominal seconds are used only to plan a <=20k chunk. ProjectX remains
    # the authority for session boundaries and month/week aggregation.
    nominal = {"s": 1, "m": 60, "h": 3600, "d": 86400,
               "w": 7 * 86400, "M": 31 * 86400}[suffix] * number
    canonical = f"{number}{suffix}"
    return units[suffix], number, nominal, canonical


def _utc(value: Any, default: Optional[datetime] = None) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip()
    if raw:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return default or datetime.now(timezone.utc)


def _history_bar_time(value: Any) -> Optional[datetime]:
    try:
        return _utc(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize_history_bars(rows: Any) -> List[Dict[str, Any]]:
    """Deduplicate and strictly sort provider bars without inventing candles."""
    by_time: Dict[str, Dict[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        stamp = _history_bar_time(row.get("t") or row.get("time"))
        try:
            o = float(row.get("o", row.get("open")))
            h = float(row.get("h", row.get("high")))
            low = float(row.get("l", row.get("low")))
            c = float(row.get("c", row.get("close")))
            v = float(row.get("v", row.get("volume", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if stamp is None or min(o, h, low, c) <= 0 or h < low or max(o, c) > h or min(o, c) < low:
            continue
        key = stamp.isoformat().replace("+00:00", "Z")
        by_time[key] = {"t": key, "o": o, "h": h, "l": low, "c": c, "v": max(0.0, v)}
    return [by_time[key] for key in sorted(by_time)]


def _aggregate_daily_calendar(rows: List[Dict[str, Any]], timeframe: str) -> List[Dict[str, Any]]:
    """Aggregate ProjectX daily bars on the CME session calendar, never fabricate rows."""
    if timeframe not in {"1w", "1M"}:
        return rows
    chicago = ZoneInfo("America/Chicago")
    groups: Dict[tuple[int, int], List[Dict[str, Any]]] = {}
    for row in _normalize_history_bars(rows):
        dt = _history_bar_time(row.get("t"))
        if dt is None:
            continue
        local = dt.astimezone(chicago)
        key = (local.isocalendar().year, local.isocalendar().week) if timeframe == "1w" else (local.year, local.month)
        groups.setdefault(key, []).append(row)
    result: List[Dict[str, Any]] = []
    for key in sorted(groups):
        group = groups[key]
        result.append({"t": group[0]["t"], "o": group[0]["o"],
                       "h": max(float(row["h"]) for row in group),
                       "l": min(float(row["l"]) for row in group),
                       "c": group[-1]["c"],
                       "v": sum(float(row.get("v") or 0) for row in group)})
    return result


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _post_json(url: str, payload: Optional[Dict[str, Any]], *, headers: Optional[Dict[str, str]] = None,
               timeout: float = 10.0) -> Dict[str, Any]:
    """POST JSON without a third-party dependency.

    ``None`` deliberately means an empty POST with no request body. ProjectX
    documents ``/api/Auth/validate`` that way; sending an otherwise harmless
    ``{}`` changes the wire contract and can make a reusable session look
    invalid.
    """
    request = urllib.request.Request(
        str(url),
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", **dict(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=float(timeout)) as response:
        raw = response.read().decode("utf-8")
    decoded = json.loads(raw or "{}")
    if not isinstance(decoded, dict):
        raise ValueError("JSON response must be an object")
    return decoded


class _TopstepXRealtimeSessionClosed(RuntimeError):
    """SignalR type=7: the Gateway closed this JWT's realtime session."""


class TopstepXSessionManager:
    """Credential-scoped, read-only ProjectX session owner.

    The desktop can request history for many windows concurrently.  ProjectX
    authentication is deliberately centralized so that this process owns one
    JWT and one Market SignalR connection per active credential set, rather
    than treating every chart request as an independent API client.  The
    public audit snapshot contains counters only; it never exposes a username,
    key, bearer token, or credential fingerprint.
    """

    _TOKEN_LIFETIME_SEC = 24 * 60 * 60
    _VALIDATE_BEFORE_EXPIRY_SEC = 5 * 60
    _LOGIN_KEY_RETRY_COOLDOWN_SEC = 60.0
    _SESSION_STORE_KEY = "market-data:topstepx:gateway-session:v1"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._fingerprint = ""
        self._token = ""
        self._expires_at = 0.0
        self._token_epoch = 0
        self._restored_token_requires_validation = False
        self._automatic_reauth_blocked = False
        self._last_token_source = "NONE"
        self._last_login_key_reason = ""
        self._last_validate_outcome = "NEVER"
        self._last_validate_error_code: Optional[int] = None
        self._login_key_cooldown_until = 0.0
        self._validate_cooldown_until = 0.0
        self._recovery_cooldown_until = 0.0
        self._recovery_cooldown_epoch = -1
        self._stats: Dict[str, int] = {
            "credential_epochs": 0,
            "adapter_instances_created": 0,
            "login_key_calls": 0,
            "jwt_issued": 0,
            "token_cache_hits": 0,
            "validate_calls": 0,
            "validate_successes": 0,
            "validate_failures": 0,
            "validate_http_401": 0,
            "validate_http_403": 0,
            "validate_api_rejections": 0,
            "validate_network_failures": 0,
            "validate_protocol_failures": 0,
            "validate_other_http_failures": 0,
            "automatic_reauth_blocked": 0,
            "signalr_connection_attempts": 0,
            "signalr_connections_opened": 0,
            "signalr_connections_closed": 0,
            "logical_subscription_requests": 0,
            "logical_subscription_deduplicated": 0,
            "logical_unsubscribe_requests": 0,
            "signalr_subscribe_invocations": 0,
            "signalr_unsubscribe_invocations": 0,
            "history_requests": 0,
            "history_cache_hits": 0,
            "persisted_token_restores": 0,
            "persisted_token_saves": 0,
            "persisted_token_invalidations": 0,
            "login_key_cooldown_suppressed": 0,
            "validate_cooldown_suppressed": 0,
            "authorization_recovery_cache_hits": 0,
            "authorization_recovery_cooldown_suppressed": 0,
            "token_source_memory": 0,
            "token_source_dpapi": 0,
            "token_source_validate": 0,
            "token_source_login_key": 0,
            "token_rotations": 0,
            "login_key_initial": 0,
            "login_key_after_rejected_token": 0,
            "history_401": 0,
            "history_403": 0,
            "history_429": 0,
            "history_5xx": 0,
            "signalr_reconnects": 0,
            "signalr_close_messages": 0,
            "signalr_auth_recovery_attempts": 0,
            "signalr_auth_recovery_successes": 0,
            "signalr_auth_recovery_failures": 0,
        }

    @staticmethod
    def _fingerprint_for(cfg: Dict[str, Any]) -> str:
        # The digest is internal-only and intentionally omitted from all
        # diagnostics.  It merely identifies a changed local credential set.
        material = "\0".join((
            str(cfg.get("username") or ""),
            str(cfg.get("api_key") or ""),
            str(cfg.get("data_mode") or ""),
        ))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def register_adapter_instance(self) -> None:
        with self._lock:
            self._stats["adapter_instances_created"] += 1

    def record(self, field: str, amount: int = 1) -> None:
        with self._lock:
            self._stats[field] = int(self._stats.get(field, 0)) + int(amount)

    def _reset_for_changed_credentials_locked(self, fingerprint: str) -> None:
        if fingerprint == self._fingerprint:
            return
        self._fingerprint = fingerprint
        self._token = ""
        self._expires_at = 0.0
        self._token_epoch = 0
        self._restored_token_requires_validation = False
        self._automatic_reauth_blocked = False
        self._last_token_source = "NONE"
        self._last_login_key_reason = ""
        self._last_validate_outcome = "NEVER"
        self._last_validate_error_code = None
        self._login_key_cooldown_until = 0.0
        self._validate_cooldown_until = 0.0
        self._recovery_cooldown_until = 0.0
        self._recovery_cooldown_epoch = -1
        self._stats["credential_epochs"] += 1

    @staticmethod
    def _persistence_allowed() -> bool:
        """Keep a Gateway JWT only in the local Windows user vault."""
        return bool(runtime_env.is_development() and secure_store.available())

    def _restore_persisted_token_locked(self, fingerprint: str, now: float) -> None:
        if self._token or self._automatic_reauth_blocked or not self._persistence_allowed():
            return
        try:
            raw = secure_store.get_secret(self._SESSION_STORE_KEY)
            record = json.loads(raw or "{}")
            token = str(record.get("token") or "").strip() if isinstance(record, dict) else ""
            expires_at = float(record.get("expires_at") or 0) if isinstance(record, dict) else 0.0
            stored_fingerprint = str(record.get("fingerprint") or "") if isinstance(record, dict) else ""
        except Exception:
            return
        # ProjectX explicitly allows an expired Gateway token to be passed to
        # /Auth/validate for rotation. Restore it even after our local expiry
        # estimate; the provider, not the clock in this record, is authoritative.
        if token and stored_fingerprint == fingerprint:
            self._token = token
            self._expires_at = expires_at
            self._token_epoch += 1
            self._restored_token_requires_validation = True
            self._last_token_source = "DPAPI"
            self._stats["persisted_token_restores"] += 1
            self._stats["token_source_dpapi"] += 1

    def _persist_token_locked(self, fingerprint: str) -> None:
        if not self._token or not self._persistence_allowed():
            return
        try:
            secure_store.set_secret(self._SESSION_STORE_KEY, json.dumps({
                "v": 1,
                "fingerprint": fingerprint,
                "token": self._token,
                "expires_at": self._expires_at,
            }, separators=(",", ":")))
            self._stats["persisted_token_saves"] += 1
        except Exception:
            # Local persistence is an optimisation.  A DPAPI fault must not
            # expose a token or make an already authenticated chart unusable.
            pass

    def _clear_persisted_token_locked(self) -> None:
        if not self._persistence_allowed():
            return
        try:
            if secure_store.delete_secret(self._SESSION_STORE_KEY):
                self._stats["persisted_token_invalidations"] += 1
        except Exception:
            pass

    def _authenticate_locked(
        self, cfg: Dict[str, Any], fingerprint: str, *, force: bool,
        login_reason: str,
    ) -> str:
        """Authenticate under ``_lock``; one caller owns each recovery path."""
        now = time.time()
        self._restore_persisted_token_locked(fingerprint, now)
        if (
            self._token and not force and not self._restored_token_requires_validation
            and self._expires_at > now + self._VALIDATE_BEFORE_EXPIRY_SEC
        ):
            self._stats["token_cache_hits"] += 1
            self._stats["token_source_memory"] += 1
            return self._token

        if self._token:
            if now < self._validate_cooldown_until:
                self._stats["validate_cooldown_suppressed"] += 1
                raise RuntimeError("TopstepX validation cooldown is active")
            self._stats["validate_calls"] += 1
            token_rejected = False
            self._last_validate_outcome = "IN_PROGRESS"
            self._last_validate_error_code = None
            try:
                validated = _post_json(
                    "https://api.topstepx.com/api/Auth/validate", None,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "text/plain",
                        "Content-Type": "application/json",
                    },
                    timeout=10.0,
                )
                new_token = str(validated.get("newToken") or "").strip()
                if validated.get("success") is False:
                    try:
                        error_code = int(validated.get("errorCode"))
                    except (TypeError, ValueError):
                        error_code = None
                    # Only definitive session failures authorize loginKey.
                    # Unknown/protocol failures remain fail-closed so a
                    # transient provider problem cannot multiply logins.
                    token_rejected = error_code in (1, 2, 3)
                    self._last_validate_error_code = error_code
                    error_name = _TOPSTEP_VALIDATE_ERROR_NAMES.get(error_code, "REJECTED")
                    self._last_validate_outcome = f"API_{error_name}"
                    self._stats["validate_api_rejections"] += 1
                    raise ValueError("session validation unsuccessful")
                if not new_token:
                    self._last_validate_outcome = "MALFORMED_RESPONSE"
                    self._stats["validate_protocol_failures"] += 1
                    raise RuntimeError("session validation returned no token")
                self._token = new_token
                self._expires_at = time.time() + self._TOKEN_LIFETIME_SEC
                self._token_epoch += 1
                self._restored_token_requires_validation = False
                self._automatic_reauth_blocked = False
                self._last_token_source = "VALIDATE"
                self._last_validate_outcome = "SUCCESS"
                self._last_validate_error_code = 0
                self._validate_cooldown_until = 0.0
                self._stats["validate_successes"] += 1
                self._stats["jwt_issued"] += 1
                self._stats["token_rotations"] += 1
                self._stats["token_source_validate"] += 1
                self._persist_token_locked(fingerprint)
                return self._token
            except urllib.error.HTTPError as exc:
                code = getattr(exc, "code", None)
                token_rejected = code in (401, 403)
                self._stats["validate_failures"] += 1
                if code == 401:
                    self._last_validate_outcome = "HTTP_401"
                    self._stats["validate_http_401"] += 1
                elif code == 403:
                    self._last_validate_outcome = "HTTP_403"
                    self._stats["validate_http_403"] += 1
                else:
                    self._last_validate_outcome = "HTTP_OTHER"
                    self._stats["validate_other_http_failures"] += 1
                if not token_rejected:
                    self._validate_cooldown_until = time.time() + 10.0
                    raise
            except (urllib.error.URLError, TimeoutError, OSError):
                self._stats["validate_failures"] += 1
                self._last_validate_outcome = "NETWORK_ERROR"
                self._stats["validate_network_failures"] += 1
                self._validate_cooldown_until = time.time() + 10.0
                raise
            except Exception:
                self._stats["validate_failures"] += 1
                if not token_rejected:
                    if self._last_validate_outcome == "IN_PROGRESS":
                        self._last_validate_outcome = "PROTOCOL_ERROR"
                        self._stats["validate_protocol_failures"] += 1
                    self._validate_cooldown_until = time.time() + 10.0
                    raise
            if token_rejected:
                # ProjectX has definitively rejected this session.  Remove the
                # unusable DPAPI record, then allow exactly one loginKey under
                # the same process-wide lock.  Concurrent chart requests will
                # reuse its result; a failed login enters the normal cooldown.
                self._token = ""
                self._expires_at = 0.0
                self._restored_token_requires_validation = False
                self._automatic_reauth_blocked = False
                self._last_token_source = "REJECTED"
                self._clear_persisted_token_locked()
                login_reason = "after_rejected_token"

        now = time.time()
        if now < self._login_key_cooldown_until:
            self._stats["login_key_cooldown_suppressed"] += 1
            raise RuntimeError("TopstepX login cooldown is active")
        self._stats["login_key_calls"] += 1
        self._stats[
            "login_key_after_rejected_token"
            if login_reason == "after_rejected_token" else "login_key_initial"
        ] += 1
        try:
            data = _post_json(
                "https://api.topstepx.com/api/Auth/loginKey",
                {"userName": cfg["username"], "apiKey": cfg["api_key"]},
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            token = str(data.get("token") or "").strip()
            if not data.get("success") or not token:
                raise ValueError("session login unsuccessful")
            self._token = token
            self._expires_at = time.time() + self._TOKEN_LIFETIME_SEC
            self._token_epoch += 1
            self._restored_token_requires_validation = False
            self._automatic_reauth_blocked = False
            self._last_token_source = "LOGIN_KEY"
            self._last_login_key_reason = login_reason
            # A successful login must also be rate-limited.  If ProjectX
            # immediately rejects the new realtime session, the next type=7
            # is allowed to validate it but cannot multiply loginKey calls.
            self._login_key_cooldown_until = (
                time.time() + self._LOGIN_KEY_RETRY_COOLDOWN_SEC
            )
            self._stats["jwt_issued"] += 1
            self._stats["token_source_login_key"] += 1
            self._persist_token_locked(fingerprint)
            return self._token
        except Exception:
            self._token = ""
            self._expires_at = 0.0
            self._restored_token_requires_validation = False
            self._automatic_reauth_blocked = False
            self._login_key_cooldown_until = time.time() + self._LOGIN_KEY_RETRY_COOLDOWN_SEC
            raise

    def authenticate(self, cfg: Dict[str, Any], *, force: bool = False) -> str:
        """Return one valid JWT, validating before re-login when possible.

        The lock intentionally spans a request. Login/validate happens rarely,
        and serialization prevents a large layout from multiplying loginKey
        calls during its first few seconds.
        """
        fingerprint = self._fingerprint_for(cfg)
        with self._lock:
            self._reset_for_changed_credentials_locked(fingerprint)
            return self._authenticate_locked(
                cfg, fingerprint, force=force, login_reason="initial",
            )

    def token_snapshot(self) -> tuple[str, int]:
        """Return a non-logging snapshot used to collapse concurrent 401s."""
        with self._lock:
            return self._token, self._token_epoch

    def recover_after_unauthorized(
        self, cfg: Dict[str, Any], *, failed_token: str, failed_epoch: int,
    ) -> str:
        """Single-flight 401/403 recovery for all charts sharing this session."""
        fingerprint = self._fingerprint_for(cfg)
        now = time.time()
        with self._lock:
            self._reset_for_changed_credentials_locked(fingerprint)
            self._restore_persisted_token_locked(fingerprint, now)
            if self._token and (
                self._token_epoch != int(failed_epoch)
                or self._token != str(failed_token or "")
            ):
                self._stats["authorization_recovery_cache_hits"] += 1
                self._stats["token_source_memory"] += 1
                return self._token
            if (
                self._recovery_cooldown_epoch == int(failed_epoch)
                and now < self._recovery_cooldown_until
            ):
                self._stats["authorization_recovery_cooldown_suppressed"] += 1
                raise RuntimeError("TopstepX authorization recovery cooldown is active")
            try:
                return self._authenticate_locked(
                    cfg, fingerprint, force=True,
                    login_reason="after_rejected_token",
                )
            except Exception:
                self._recovery_cooldown_epoch = int(failed_epoch)
                self._recovery_cooldown_until = time.time() + 10.0
                raise

    def expiry(self) -> float:
        with self._lock:
            return self._expires_at

    def invalidate(self) -> None:
        with self._lock:
            self._token = ""
            self._expires_at = 0.0
            self._restored_token_requires_validation = False
            self._automatic_reauth_blocked = False
            self._last_token_source = "NONE"
            self._login_key_cooldown_until = 0.0
            self._clear_persisted_token_locked()

    def audit(self) -> Dict[str, Any]:
        with self._lock:
            return {
                **dict(self._stats),
                "token_present": bool(self._token),
                "token_expires_in_sec": max(0, int(self._expires_at - time.time())) if self._token else 0,
                "token_source": self._last_token_source,
                "last_login_key_reason": self._last_login_key_reason,
                "last_validate_outcome": self._last_validate_outcome,
                "last_validate_error_code": self._last_validate_error_code,
                "automatic_reauth_is_blocked": self._automatic_reauth_blocked,
            }

    def reset_for_tests(self) -> None:
        """Clear process-global session state for isolated unit tests only."""
        with self._lock:
            self._fingerprint = ""
            self._token = ""
            self._expires_at = 0.0
            self._token_epoch = 0
            self._restored_token_requires_validation = False
            self._automatic_reauth_blocked = False
            self._last_token_source = "NONE"
            self._last_login_key_reason = ""
            self._last_validate_outcome = "NEVER"
            self._last_validate_error_code = None
            self._login_key_cooldown_until = 0.0
            self._validate_cooldown_until = 0.0
            self._recovery_cooldown_until = 0.0
            self._recovery_cooldown_epoch = -1
            for key in list(self._stats):
                self._stats[key] = 0


_TOPSTEP_SESSION_MANAGER = TopstepXSessionManager()


def topstepx_session_manager() -> TopstepXSessionManager:
    """Return the process-wide, credential-scoped ProjectX auth owner."""
    return _TOPSTEP_SESSION_MANAGER


def databento_raw_symbol(exact_contract: str) -> str:
    """Map NT-style ``MNQ 09-26`` → Databento raw ``MNQU6`` (1-digit year)."""
    raw = " ".join(str(exact_contract or "").strip().upper().split())
    match = _CONTRACT_RE.match(raw)
    if not match:
        raise ValueError(f"exact contract required, got {exact_contract!r}")
    root, mm, yy = match.group(1), int(match.group(2)), int(match.group(3))
    return f"{root}{_MONTH_CODE[mm]}{yy % 10}"


def topstep_exact_contract(root: str, item: Dict[str, Any]) -> str:
    normalized_root = str(root or "").strip().upper()
    contract_id = str(item.get("id") or "").strip().upper()
    suffix = contract_id.rsplit(".", 1)[-1]
    match = re.fullmatch(r"([FGHJKMNQUVXZ])(\d{2})", suffix)
    if not normalized_root or not match:
        return normalized_root
    month = _CODE_MONTH.get(match.group(1))
    if month is None:
        return normalized_root
    return f"{normalized_root} {month:02d}-{int(match.group(2)):02d}"


class LiveMarketDataAdapter(ABC):
    name = "base"

    @property
    def production_failover_eligible(self) -> bool:
        if self.name in {"yahoo", "yahoo_chart", "recorded", "fault_injection"}:
            return False
        from .market_data_router import get_router
        try:
            router = get_router()
            report = router._parity.get(self.name)
            return bool(report and report.passed)
        except Exception:
            return False

    def __init__(self) -> None:
        self._subs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._runtime_state = "DISABLED"
        self._last_error = ""
        self._last_event_utc = ""
        self._connected_at = ""
        self._event_count = 0
        self._last_signal_target = ""
        self._last_signal_price_field = ""
        self._signal_target_counts: Dict[str, int] = {}
        self._signal_price_field_counts: Dict[str, int] = {}
        self._event_type_counts: Dict[str, int] = {}
        self._last_event_type_utc: Dict[str, str] = {}
        self._last_event_type_contract_utc: Dict[str, Dict[str, str]] = {}
        self._pending_signal_invocations: Dict[str, Dict[str, str]] = {}
        self._signal_invocation_results: Dict[str, Dict[str, Any]] = {}
        self._sink: Optional[EventSink] = None
        self._mode = "shadow"  # shadow | authoritative
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._client: Any = None

    @abstractmethod
    def implementation_state(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def credentials_present(self) -> bool:
        raise NotImplementedError

    def set_sink(self, sink: Optional[EventSink], *, mode: str = "shadow") -> None:
        self._sink = sink
        self._mode = "authoritative" if mode == "authoritative" else "shadow"

    def _has_subscribers(self) -> bool:
        """Whether anything is currently asking this provider for data."""
        with self._lock:
            return bool(self._subs)

    def reported_runtime_state(self) -> str:
        """The state to show, which is not always the state of the socket.

        A provider nobody has subscribed to is idle, and saying CONNECTING
        instead described a connection attempt that was never started. Read as
        a fault it is not: the dashboard called market data degraded because a
        failover source had no subscribers, on a server whose primary was
        healthy and serving bars the whole time.

        CONNECTING now means what it says -- something is subscribed and the
        socket is being brought up for it. Anything genuinely wrong keeps its
        own state: an error, a failed authentication, a missing entitlement and
        a dropped socket are all untouched by this.

        Deliberately decided from demand rather than from a "connecting now"
        flag. Such a flag has to be cleared at every place an attempt can end,
        and one missed place puts the provider back to claiming forever that it
        is connecting -- which is the bug being fixed, reintroduced by the fix.
        """
        state = self._runtime_state
        if state != "CONNECTING":
            return state
        if self._last_error or self._has_subscribers():
            return state
        return "IDLE"

    def capabilities(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "implementation_state": self.implementation_state(),
            "runtime_state": self.reported_runtime_state(),
            "credentials_present": self.credentials_present(),
            "production_failover_eligible": self.production_failover_eligible,
            "channels": ["trades", "bid_ask"],
            "historical": False,
            "live": True,
            "reconnect": True,
            "replay_intraday_24h": False,
            "mode": self._mode,
            "REALTIME_PRODUCTION": bool(
                self.production_failover_eligible and self.credentials_present()
            ),
        }

    def health(self) -> Dict[str, Any]:
        age = None
        if self._last_event_utc:
            try:
                dt = datetime.fromisoformat(self._last_event_utc.replace("Z", "+00:00"))
                age = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
            except ValueError:
                age = None
        now_utc = datetime.now(timezone.utc)

        def event_age(value: str) -> Optional[float]:
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                return max(0.0, (now_utc - parsed).total_seconds())
            except (TypeError, ValueError):
                return None

        with self._lock:
            event_type_counts = dict(self._event_type_counts)
            event_type_ages = {
                kind: event_age(value) for kind, value in self._last_event_type_utc.items()
            }
            trade_age_by_contract = {
                contract: event_age(value)
                for contract, value in self._last_event_type_contract_utc.get("trade", {}).items()
            }
        return {
            "name": self.name,
            "runtime_state": self.reported_runtime_state(),
            "implementation_state": self.implementation_state(),
            "credentials_present": self.credentials_present(),
            "connected_at_utc": self._connected_at,
            "last_event_utc": self._last_event_utc,
            "last_event_age_sec": age,
            "event_count": self._event_count,
            "last_signal_target": self._last_signal_target,
            "last_signal_price_field": self._last_signal_price_field,
            "signal_target_counts": dict(self._signal_target_counts),
            "signal_price_field_counts": dict(self._signal_price_field_counts),
            "event_type_counts": event_type_counts,
            "event_type_age_sec": event_type_ages,
            "trade_age_by_contract_sec": trade_age_by_contract,
            "signal_invocation_results": dict(self._signal_invocation_results),
            "subscriptions": len(self._subs),
            "last_error": self._last_error,
            "mode": self._mode,
        }

    def connect(self) -> Dict[str, Any]:
        self._runtime_state = "CONNECTING"
        self._connected_at = _iso()
        return self.health()

    def disconnect(self) -> None:
        self._stop.set()
        client = self._client
        self._client = None
        try:
            if client is not None and hasattr(client, "stop"):
                client.stop()
        except Exception:
            pass
        with self._lock:
            self._subs.clear()
        self._runtime_state = "DISABLED"

    @abstractmethod
    def subscribe(self, exact_contract: str, channel: str = "trades", *, timeframe: str = "1m") -> str:
        raise NotImplementedError

    def unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            self._subs.pop(str(subscription_id), None)

    def _emit(self, event: Dict[str, Any]) -> None:
        observed = str(event.get("ts_provider") or event.get("ts_event") or _iso())
        event_type = str(event.get("type") or "unknown").lower()
        contract = str(event.get("exact_contract") or "").upper()
        with self._lock:
            self._event_count += 1
            self._last_event_utc = observed
            self._event_type_counts[event_type] = self._event_type_counts.get(event_type, 0) + 1
            self._last_event_type_utc[event_type] = observed
            if contract:
                by_contract = self._last_event_type_contract_utc.setdefault(event_type, {})
                by_contract[contract] = observed
        sink = self._sink
        if sink is not None:
            sink(event)

    def _emit_mock_tick(self, contract: str, raw_sym: str, schema: str, tick_size: float, last_prices: dict) -> None:
        import random
        from .market_data_router import get_router

        router = get_router()
        p_stream = router._primary_streams.get(contract.upper())
        base_price = None
        if p_stream:
            last_event = p_stream[-1]
            if last_event.get("price") is not None:
                base_price = float(last_event["price"])

        if base_price is None:
            root = contract.split(" ")[0]
            base_price = last_prices.setdefault(contract, {
                "MNQ": 20000.0, "NQ": 20000.0,
                "MES": 5500.0, "ES": 5500.0,
                "MGC": 2400.0, "GC": 2400.0,
                "MYM": 40000.0, "YM": 40000.0,
                "M2K": 2200.0, "RTY": 2200.0
            }.get(root, 100.0))

        change = random.choice([-tick_size, 0.0, tick_size])
        new_price = base_price + change
        last_prices[contract] = new_price

        bid = new_price - tick_size
        ask = new_price + tick_size

        reg = get_registry().resolve_exact(contract, allow_continuous=False) if contract else {}
        size = random.randint(1, 5)

        event = make_canonical_event(
            event_type="trade" if schema == "trades" else "quote",
            provider=self.name,
            raw_symbol=raw_sym,
            exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or contract),
            canonical_symbol=str(reg.get("root") or ""),
            price=new_price,
            bid=bid,
            ask=ask,
            volume=size,
            exchange_sequence=random.randint(1000, 1000000),
            provider_sequence=self._event_count + 1,
            ts_event=_iso(),
            ts_provider=_iso(),
            quality={self.name: True, "mock": True},
            data_plane="analytics" if self._mode == "shadow" else "display",
        )
        self._emit(event)


def is_mock_key(key: str, prefix: str) -> bool:
    k = key.strip()
    if not k:
        return True
    placeholders = {
        f"{prefix}-...",
        "db-...",
        "YOUR_API_KEY",
        "test-default",
    }
    if k in placeholders:
        return True
    if k.startswith(f"{prefix}-mock") or k.startswith("db-mock"):
        return True
    return False


class DatabentoLiveAdapter(LiveMarketDataAdapter):
    """Real Databento Live TCP client (GLBX.MDP3)."""

    name = "databento_live"

    def __init__(self) -> None:
        super().__init__()
        self._dataset = str(os.environ.get("NTA_DATABENTO_DATASET") or "GLBX.MDP3")
        self._generation = 0
        self._instrument_id_to_symbol_map = {}
        import time
        self._last_event_time = time.time()

    def implementation_state(self) -> str:
        try:
            import databento as db  # noqa: F401
        except ImportError:
            return "ADAPTER_READY"
        if not self.credentials_present():
            return "ADAPTER_READY"
        if self._runtime_state == "LIVE":
            return "CONNECTED"
        return "ADAPTER_READY"

    def credentials_present(self) -> bool:
        key = str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()
        return bool(key and not is_mock_key(key, "db"))

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        deps_ok = True
        try:
            import databento  # noqa: F401
        except ImportError:
            deps_ok = False
        caps.update({
            "dataset": self._dataset,
            "dependency_installed": deps_ok,
            "replay_intraday_24h": True,
            "schemas": ["trades", "mbp-1", "tbbo"],
            "note": "OPTIONAL_ENTERPRISE_PROVIDER | DISABLED_BY_DEFAULT | NOT_REQUIRED_FOR_MVP | NO PURCHASE APPROVED",
        })
        if not deps_ok:
            caps["capability"] = "DEPENDENCY_MISSING"
        else:
            caps["capability"] = "OPTIONAL_ENTERPRISE_PROVIDER"
        return caps

    def health(self) -> Dict[str, Any]:
        h = super().health()

        # Check last event age for degraded status (heartbeat timeout: 15s)
        age = h.get("last_event_age_sec")
        if self._runtime_state == "LIVE" and age is not None and age > 15.0:
            self._runtime_state = "DEGRADED"
            h["runtime_state"] = "DEGRADED"

        # Check client connection state
        client = self._client
        if client is not None and hasattr(client, "is_connected"):
            try:
                if not client.is_connected():
                    if self._runtime_state in {"LIVE", "AUTHENTICATED"}:
                        self._runtime_state = "DEGRADED"
                        h["runtime_state"] = "DEGRADED"
                    if self._runtime_state == "DEGRADED" and not getattr(client._thread, "is_alive", lambda: False)():
                        self._runtime_state = "OFFLINE"
                        h["runtime_state"] = "OFFLINE"
            except Exception:
                pass
        return h

    def connect(self) -> Dict[str, Any]:
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_DATABENTO_API_KEY not configured or is a mock key"
            return self.health()

        key = str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()
        try:
            import databento as db
        except ImportError:
            self._runtime_state = "ERROR"
            self._last_error = "databento package not installed"
            return self.health()

        try:
            self._runtime_state = "CONNECTING"
            self._generation += 1
            gen = self._generation

            # Pass reconnect_policy="reconnect" and slow_reader_behavior="skip"
            self._client = db.Live(key=key, reconnect_policy="reconnect", slow_reader_behavior="skip")
            self._client.add_callback(lambda r, g=gen: self._on_record(r, g))
            self._client.add_reconnect_callback(self._on_reconnect)
            self._client.start()
            self._connected_at = _iso()
            self._last_error = ""
            import time
            self._last_event_time = time.time()
        except Exception as exc:
            self._runtime_state = "AUTH_FAILED"
            self._last_error = f"Databento connect exception: {type(exc).__name__}: {exc}"
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        if not self.credentials_present():
            raise NotImplementedError("Real Databento live connection requires valid non-mock API credentials.")

        contract = " ".join(str(exact_contract or "").strip().upper().split())
        if not contract:
            raise ValueError("exact_contract required")

        raw = databento_raw_symbol(contract)
        schema = "tbbo" if channel in {"bid_ask", "tbbo", "quotes"} else "trades"
        sub_id = f"databento:{contract}:{schema}"
        with self._lock:
            self._subs[sub_id] = {
                "exact_contract": contract,
                "raw_symbol": raw,
                "channel": channel,
                "schema": schema,
            }

        client = self._client
        if client is not None:
            try:
                client.subscribe(
                    dataset=self._dataset,
                    schema=schema,
                    symbols=raw,
                    stype_in="raw_symbol",
                )
                self._runtime_state = "AUTHENTICATED"
            except Exception as exc:
                self._runtime_state = "AUTH_FAILED"
                self._last_error = f"subscribe failed: {exc}"
                raise exc
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            removed = self._subs.pop(str(subscription_id), None)
            if not removed:
                return

            # Safe stop/recreate/resubscribe sequence
            client = self._client
            if client is not None:
                try:
                    client.stop()
                    # wait_for_close with timeout 2.0s
                    client.wait_for_close(timeout=2.0)
                except Exception:
                    try:
                        client.terminate()
                    except Exception:
                        pass
                self._client = None

            if self.credentials_present():
                key = str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()
                try:
                    import databento as db
                    self._runtime_state = "CONNECTING"
                    self._generation += 1
                    gen = self._generation

                    self._client = db.Live(key=key, reconnect_policy="reconnect", slow_reader_behavior="skip")
                    self._client.add_callback(lambda r, g=gen: self._on_record(r, g))
                    self._client.add_reconnect_callback(self._on_reconnect)
                    self._client.start()
                    self._runtime_state = "AUTHENTICATED"

                    # Re-subscribe remaining active contracts
                    for sub in self._subs.values():
                        self._client.subscribe(
                            dataset=self._dataset,
                            schema=sub["schema"],
                            symbols=sub["raw_symbol"],
                            stype_in="raw_symbol",
                        )
                except Exception as exc:
                    self._runtime_state = "ERROR"
                    self._last_error = f"unsubscribe restart failed: {exc}"

    def _on_reconnect(self) -> None:
        self._connected_at = _iso()
        import time
        now = time.time()
        gap_sec = now - self._last_event_time
        self._last_event_time = now

        # Enqueue reconnect gap to GapRecovery worker
        from . import market_data_gap_recovery
        for sub in list(self._subs.values()):
            market_data_gap_recovery.get_worker().enqueue({
                "provider": self.name,
                "exact_contract": sub["exact_contract"],
                "gap_sec": gap_sec,
                "reason": "reconnect_gap",
            })

        # If not LIVE, keep CONNECTING until first record is processed
        if self._runtime_state != "LIVE":
            self._runtime_state = "CONNECTING"

    def _on_record(self, record: Any, generation: int) -> None:
        if generation != self._generation:
            return  # Drop old-generation records

        rec_name = type(record).__name__
        if rec_name in {"ErrorMsg", "MockErrorMsg"}:
            err_msg = getattr(record, "err", "") or "unknown databento error"
            for ph in ["db-", "YOUR_API_KEY", "test-default"]:
                if ph in err_msg:
                    err_msg = err_msg.replace(ph, "[SECRET_REDACTED]")
            self._last_error = f"databento_error_msg: {err_msg}"

            # Slow reader transitions
            if "slow reader" in err_msg.lower() or "slow_reader" in err_msg.lower():
                self._runtime_state = "DEGRADED"
            elif "skipped" in err_msg.lower() or "records dropped" in err_msg.lower():
                self._runtime_state = "DEGRADED"
                from . import market_data_gap_recovery
                for sub in list(self._subs.values()):
                    market_data_gap_recovery.get_worker().enqueue({
                        "provider": self.name,
                        "exact_contract": sub["exact_contract"],
                        "gap_sec": 10.0,
                        "reason": "slow_reader_skip",
                    })
            else:
                self._runtime_state = "ERROR"
            return
        elif rec_name in {"SystemMsg", "MockSystemMsg"}:
            self._last_event_utc = _iso()
            return
        elif rec_name in {"SymbolMappingMsg", "MockSymbolMappingMsg"}:
            inst_id = getattr(record, "instrument_id", None)
            raw_sym = getattr(record, "stype_in_symbol", "") or getattr(record, "raw_symbol", "")
            if inst_id is not None and raw_sym:
                with self._lock:
                    self._instrument_id_to_symbol_map[inst_id] = {
                        "raw_symbol": str(raw_sym),
                        "instrument_id": inst_id
                    }
            self._last_event_utc = _iso()
            return

        try:
            price_raw = getattr(record, "price", None)
            price = None
            if price_raw is not None:
                # Convert using official scale constant
                try:
                    import databento as db
                    scale = getattr(db, "FIXED_PRICE_SCALE", 1000000000)
                    if type(scale).__name__ == "MagicMock":
                        scale = 1000000000
                except Exception:
                    scale = 1000000000
                price = float(price_raw) / scale

            size = getattr(record, "size", None)

            # Authoritative mapping lookup
            inst_id = getattr(record, "instrument_id", None)
            symbol = ""
            mapping_pending = False
            if inst_id is not None:
                with self._lock:
                    mapping_info = self._instrument_id_to_symbol_map.get(inst_id)
                if mapping_info:
                    symbol = mapping_info["raw_symbol"]
                else:
                    mapping_pending = True

            # Fallback for unit-tests and direct mock feeds
            if not symbol and hasattr(record, "symbol") and record.symbol:
                symbol = str(record.symbol)
                mapping_pending = False

            if mapping_pending and not symbol:
                with self._lock:
                    if self._subs:
                        symbol = list(self._subs.values())[0]["raw_symbol"]

            if not symbol:
                return

            exact = ""
            with self._lock:
                for row in self._subs.values():
                    if row.get("raw_symbol") == symbol or symbol.startswith(str(row.get("raw_symbol") or "")):
                        exact = str(row.get("exact_contract") or "")
                        break
            if not exact:
                return  # Filter out unsubscribed messages

            import time
            self._last_event_time = time.time()

            # Transition to LIVE on first valid record
            if self._runtime_state in {"CONNECTING", "AUTHENTICATED", "DEGRADED"}:
                self._runtime_state = "LIVE"

            reg = get_registry().resolve_exact(exact, allow_continuous=False) if exact else {}
            ts_ns = getattr(record, "ts_event", None)
            ts_iso = _iso()
            if ts_ns is not None:
                ts_iso = datetime.fromtimestamp(ts_ns / 1_000_000_000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")

            quality = {"databento_live": True, "dataset": self._dataset}
            if mapping_pending:
                quality["SYMBOL_MAPPING_PENDING"] = True

            event = make_canonical_event(
                event_type="trade" if size is not None else "quote",
                provider=self.name,
                raw_symbol=symbol,
                exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or exact),
                canonical_symbol=str(reg.get("root") or ""),
                price=price,
                volume=size,
                exchange_sequence=getattr(record, "sequence", None),
                provider_sequence=self._event_count + 1,
                ts_event=ts_iso,
                ts_provider=_iso(),
                quality=quality,
                data_plane="analytics" if self._mode == "shadow" else "display",
            )
            self._emit(event)
        except Exception as exc:
            self._last_error = f"record_parse: {type(exc).__name__}: {exc}"


class TopstepXProjectXAdapter(LiveMarketDataAdapter):
    """Read-only TopstepX / ProjectX market-data client.

    Remote use remains policy-blocked unless the deployment records both the
    remote-server and redistribution permissions required for that contour.
    """

    name = "topstep_live"
    # ProjectX caps retrieveBars at 50 requests / 30 seconds. This process-wide
    # gate is a FIFO-equivalent serialized queue for history chunks, leaving a
    # little headroom for retries and other authenticated endpoints.
    _history_rate_lock = threading.Lock()
    _history_next_at = 0.0
    _history_min_interval_sec = 0.62
    # The official ProjectX SignalR example uses a 10-second transport
    # timeout.  Keep every small protocol write bounded so a dead socket
    # cannot strand reconnect cleanup behind an unfinished bulk resubscribe.
    _signalr_send_timeout_sec = 10.0
    _signalr_close_timeout_sec = 5.0
    _signalr_write_spacing_sec = 0.03

    def __init__(self) -> None:
        super().__init__()
        self._session = topstepx_session_manager()
        self._session.register_adapter_instance()
        self._token = ""
        self._token_expires_at = 0.0
        self._loop = None
        self._ws_client = None
        self._signalr_send_lock = None
        self._signalr_invoke_lock = None
        self._signal_completion_waiters: Dict[str, Any] = {}
        self._contract_id_map = {}
        self._contract_symbol_map = {}
        self._resolved_exact_map = {}
        self._session_refresh_thread = None
        # Range cache is intentionally owned by this credential-scoped adapter.
        # A second chart opening the same viewport therefore reuses the bars
        # without exposing them across accounts or sending another API request.
        self._history_lock = threading.RLock()
        # Reconnect gap-fill is intentionally single-flight and runs outside
        # the SignalR receive loop.  A large desktop can have dozens of
        # contracts; waiting for their rate-limited history calls before
        # reading the hub starves the socket and causes a reconnect loop.
        self._gap_fill_lock = threading.Lock()
        self._history_cache: Dict[tuple[str, str, bool], Dict[str, Any]] = {}
        self._history_inflight: Dict[tuple[str, str, bool, str, str], threading.Event] = {}
        self._history_stats = {"requests": 0, "cache_hits": 0, "retries": 0, "gap_fills": 0}
        self._latest_quotes: Dict[str, Dict[str, Any]] = {}
        self._last_reconnect_gap_fill_utc = ""
        # Receive-time freshness is intentionally distinct from market price.
        # A still lastPrice is normal; a recent GatewayQuote/bid-ask or SignalR
        # heartbeat proves the feed is alive without inventing a trade.
        self._last_signalr_receive_utc = ""
        self._last_signalr_heartbeat_utc = ""
        self._last_quote_receive_utc: Dict[str, str] = {}
        self._last_bid_ask_receive_utc: Dict[str, str] = {}
        self._last_trade_receive_utc: Dict[str, str] = {}
        self._market_connection_opened_once = False
        # One wire subscription per provider contract; logical chart consumers
        # share it through ``_subs`` and release it independently.
        self._wire_subscribed_contract_ids: set[str] = set()
        self._wire_subscribe_pending: set[str] = set()

    @staticmethod
    def _utc_age(value: Any, now: Optional[datetime] = None) -> Optional[float]:
        if not value:
            return None
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(0.0, ((now or datetime.now(timezone.utc)) - stamp.astimezone(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None

    def market_feed_freshness(self, exact_contract: str = "") -> Dict[str, Any]:
        """Return transport freshness without conflating it with last trade age."""
        requested = " ".join(str(exact_contract or "").strip().upper().split())
        now = datetime.now(timezone.utc)
        with self._lock:
            resolved = str(self._resolved_exact_map.get(requested) or requested)
            # A root can be resolved during history before the browser updates
            # its saved layout.  Use that mapping for a truthful feed status.
            if not resolved and requested:
                resolved = requested
            quote_at = self._last_quote_receive_utc.get(resolved, "")
            bid_ask_at = self._last_bid_ask_receive_utc.get(resolved, "")
            trade_at = self._last_trade_receive_utc.get(resolved, "")
            if not requested:
                quote_at = max(self._last_quote_receive_utc.values(), default="")
                bid_ask_at = max(self._last_bid_ask_receive_utc.values(), default="")
                trade_at = max(self._last_trade_receive_utc.values(), default="")
            signal_at = self._last_signalr_receive_utc
            heartbeat_at = self._last_signalr_heartbeat_utc
            connected_at = self._connected_at
            state = self._runtime_state
            connected = bool(self._ws_client is not None and state in {"AUTHENTICATED", "LIVE"})
        signal_age = self._utc_age(signal_at, now)
        heartbeat_age = self._utc_age(heartbeat_at, now)
        quote_age = self._utc_age(quote_at, now)
        bid_ask_age = self._utc_age(bid_ask_at, now)
        trade_age = self._utc_age(trade_at, now)
        connection_age = self._utc_age(connected_at, now)
        # SignalR emits type=6 heartbeats; 45 seconds allows normal quiet
        # intervals while detecting a genuinely stalled socket.  Actual quote
        # arrivals are equally valid evidence even when lastPrice is unchanged.
        fresh_transport = any(age is not None and age <= 45.0 for age in (signal_age, heartbeat_age))
        fresh_quote = any(age is not None and age <= 45.0 for age in (quote_age, bid_ask_age))
        fresh = bool(connected and (fresh_quote or fresh_transport))
        awaiting_first_signal = bool(connected and not fresh and (connection_age is None or connection_age <= 45.0))
        feed_as_of = max((value for value in (quote_at, bid_ask_at, heartbeat_at, signal_at) if value), default="")
        return {
            "fresh": fresh,
            "stale": bool(connected and not fresh and not awaiting_first_signal),
            "offline": bool(not connected and state in {"AUTH_FAILED", "DISABLED", "ENTITLEMENT_MISSING", "POLICY_BLOCKED", "OFFLINE"}),
            "connection_state": state,
            "connection_active": connected,
            "connection_age_sec": connection_age,
            "signalr_receive_age_sec": signal_age,
            "signalr_heartbeat_age_sec": heartbeat_age,
            "quote_age_sec": quote_age,
            "bid_ask_age_sec": bid_ask_age,
            "last_trade_age_sec": trade_age,
            "market_feed_as_of_utc": feed_as_of,
            "last_trade_at_utc": trade_at,
        }

    def _has_subscribers(self) -> bool:
        with self._lock:
            if self._wire_subscribed_contract_ids or self._subs:
                return True
            return bool(self._pending_signal_invocations)

    def health(self) -> Dict[str, Any]:
        out = super().health()
        out["market_feed"] = self.market_feed_freshness()
        out["session_audit"] = self._session.audit()
        with self._lock:
            out["wire_subscriptions"] = len(self._wire_subscribed_contract_ids)
            out["logical_subscription_refcount"] = sum(
                len(set(row.get("consumers") or set())) for row in self._subs.values()
            )
            out["pending_signal_invocations"] = len(self._pending_signal_invocations)
        return out

    def implementation_state(self) -> str:
        if self._runtime_state == "LIVE":
            return "CONNECTED"
        return "ADAPTER_READY"

    @staticmethod
    def _flag(name: str, *, default: bool = False) -> bool:
        raw = str(os.environ.get(name) or "").strip().lower()
        if not raw:
            return bool(default)
        return raw in {"1", "true", "yes", "on"}

    @classmethod
    def settings(cls) -> Dict[str, Any]:
        local_secrets.apply()
        username = str(
            os.environ.get("NTA_TOPSTEPX_USERNAME")
            or os.environ.get("NTA_TOPSTEP_USERNAME")
            or ""
        ).strip()
        api_key = str(
            os.environ.get("NTA_TOPSTEPX_API_KEY")
            or os.environ.get("NTA_TOPSTEP_API_KEY")
            or ""
        ).strip()
        requested = cls._flag("NTA_ENABLE_TOPSTEPX_MARKET_DATA", default=True)
        if "NTA_ENABLE_TOPSTEPX_LIVE" in os.environ:
            requested = requested and cls._flag("NTA_ENABLE_TOPSTEPX_LIVE")
        remote = not runtime_env.is_development()
        remote_authorized = cls._flag("NTA_TOPSTEPX_REMOTE_SERVER_AUTHORIZED")
        redistribution_authorized = cls._flag("NTA_TOPSTEPX_REDISTRIBUTION_AUTHORIZED")
        policy_allowed = bool(not remote or (remote_authorized and redistribution_authorized))
        mode = str(os.environ.get("NTA_TOPSTEPX_DATA_MODE") or "sim").strip().lower()
        if mode not in {"sim", "live"}:
            mode = "invalid"
        credentials_present = bool(
            username and api_key and not is_mock_key(api_key, "topstep")
        )
        blocking_reasons: List[str] = []
        if not username:
            blocking_reasons.append("topstepx_username_missing")
        if not api_key or is_mock_key(api_key, "topstep"):
            blocking_reasons.append("topstepx_api_key_missing")
        if mode == "invalid":
            blocking_reasons.append("topstepx_data_mode_invalid")
        if not requested:
            blocking_reasons.append("topstepx_market_data_disabled")
        if remote and not remote_authorized:
            blocking_reasons.append("remote_server_authorization_missing")
        if remote and not redistribution_authorized:
            blocking_reasons.append("market_data_redistribution_authorization_missing")
        from . import owner_market_data_gateway
        if not owner_market_data_gateway.should_open_direct_hub():
            if owner_market_data_gateway.should_consume():
                blocking_reasons.append("owner_market_data_gateway_consumer")
            else:
                blocking_reasons.append("owner_market_data_gateway_fail_closed")
            if credentials_present:
                blocking_reasons.append("owner_credentials_present_but_direct_hub_forbidden")
        return {
            "username": username,
            "api_key": api_key,
            "username_configured": bool(username),
            "api_key_configured": bool(api_key and not is_mock_key(api_key, "topstep")),
            "credentials_present": credentials_present,
            "requested": requested,
            "remote_environment": remote,
            "remote_server_authorized": remote_authorized,
            "redistribution_authorized": redistribution_authorized,
            "policy_allowed": policy_allowed,
            "data_mode": mode,
            "live_subscription": mode == "live",
            "blocking_reasons": blocking_reasons,
        }

    @staticmethod
    def enabled() -> bool:
        from . import owner_market_data_gateway
        if not owner_market_data_gateway.should_open_direct_hub():
            return False
        cfg = TopstepXProjectXAdapter.settings()
        return bool(cfg["requested"] and cfg["policy_allowed"] and cfg["data_mode"] != "invalid")

    def credentials_present(self) -> bool:
        return bool(self.settings()["credentials_present"])

    def capabilities(self) -> Dict[str, Any]:
        cfg = self.settings()
        return {
            **super().capabilities(),
            "historical": True,
            "read_only": True,
            "trade_routing": False,
            "data_mode": cfg["data_mode"],
            "policy_allowed": cfg["policy_allowed"],
            "remote_environment": cfg["remote_environment"],
            "blocking_reasons": list(cfg["blocking_reasons"]),
        }

    def _authenticate(
        self, *, force: bool = False, failed_token: str = "", failed_epoch: int = -1,
    ) -> bool:
        if not self.enabled():
            cfg = self.settings()
            self._runtime_state = "POLICY_BLOCKED" if not cfg["policy_allowed"] else "DISABLED"
            self._last_error = ",".join(cfg["blocking_reasons"]) or "TopstepX market data disabled"
            return False
        from . import owner_market_data_gateway
        lease = owner_market_data_gateway.acquire_hub_lease()
        if lease.get("duplicate_blocked") or not lease.get("held"):
            self._runtime_state = "POLICY_BLOCKED"
            self._last_error = str(lease.get("warning") or "owner_market_data_hub_lease_unavailable")
            return False
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_TOPSTEPX_USERNAME or NTA_TOPSTEPX_API_KEY missing"
            return False
        cfg = self.settings()
        try:
            # ``subscribe`` and ``history_range`` authenticate defensively on
            # every caller path, but a cache hit must never relabel an already
            # healthy market socket as CONNECTING.  That short state flip made
            # a cached HTTP refresh report ``external_connecting`` until the
            # next market frame arrived, even though SignalR and quotes were
            # still flowing.  Preserve the proven transport state; only a
            # socket that is not already active starts in CONNECTING.
            with self._lock:
                transport_is_live = bool(
                    self._ws_client is not None
                    and self._runtime_state in {"AUTHENTICATED", "LIVE"}
                )
                if not transport_is_live:
                    self._runtime_state = "CONNECTING"
            if failed_token:
                self._token = self._session.recover_after_unauthorized(
                    cfg, failed_token=failed_token, failed_epoch=failed_epoch,
                )
            else:
                self._token = self._session.authenticate(cfg, force=force)
            self._token_expires_at = self._session.expiry()
            self._last_error = ""
            return True
        except Exception as exc:
            self._token = ""
            self._token_expires_at = 0.0
            self._runtime_state = "AUTH_FAILED"
            self._last_error = "TopstepX login failed"
            return False

    def _history_request(self, payload: Dict[str, Any], *, cancel_event: Any = None) -> Dict[str, Any]:
        """ProjectX request with bounded 429/network retry and cancellation checks."""
        delay = 0.35
        last_error: Optional[Exception] = None
        for attempt in range(_TOPSTEP_HISTORY_RETRIES):
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                raise RuntimeError("TopstepX history request cancelled")
            try:
                with self.__class__._history_rate_lock:
                    delay_until = self.__class__._history_next_at - time.monotonic()
                    if delay_until > 0:
                        time.sleep(delay_until)
                    self.__class__._history_next_at = time.monotonic() + self.__class__._history_min_interval_sec
                if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                    raise RuntimeError("TopstepX history request cancelled")
                self._session.record("history_requests")
                request_token, request_epoch = self._session.token_snapshot()
                if request_token:
                    self._token = request_token
                data = _post_json(
                    "https://api.topstepx.com/api/History/retrieveBars", payload,
                    headers={"Authorization": f"Bearer {request_token or self._token}", "Content-Type": "application/json"},
                    timeout=15.0,
                )
                if data.get("success") is False:
                    # Gateway implementations use either HTTP 429 or an error
                    # payload. Retry only an explicit throttling response.
                    if str(data.get("errorCode") or "") == "429":
                        raise urllib.error.HTTPError("", 429, "rate limited", None, None)
                    raise ValueError(str(data.get("errorMessage") or "TopstepX history request failed"))
                return data
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                code = getattr(exc, "code", None)
                if code == 401:
                    self._session.record("history_401")
                elif code == 403:
                    self._session.record("history_403")
                elif code == 429:
                    self._session.record("history_429")
                elif isinstance(code, int) and 500 <= code < 600:
                    self._session.record("history_5xx")
                revalidated = False
                if code in (401, 403):
                    # The manager owns a credential-wide single-flight
                    # recovery. A concurrent chart that already refreshed the
                    # same JWT receives that new token rather than issuing a
                    # second validate or loginKey request.
                    revalidated = self._authenticate(
                        force=True, failed_token=request_token,
                        failed_epoch=request_epoch,
                    )
                    if not revalidated:
                        break
                retryable = bool(
                    revalidated or code in (None, 429)
                    or (isinstance(code, int) and 500 <= code < 600)
                    or isinstance(exc, (urllib.error.URLError, TimeoutError, OSError))
                )
                if not retryable or attempt + 1 >= _TOPSTEP_HISTORY_RETRIES:
                    break
                with self._history_lock:
                    self._history_stats["retries"] += 1
                time.sleep(delay)
                delay = min(delay * 2, 4.0)
        raise RuntimeError(f"TopstepX history request failed: {type(last_error).__name__ if last_error else 'unknown'}")

    @staticmethod
    def _range_missing(covered: List[tuple[datetime, datetime]], start: datetime,
                       end: datetime) -> List[tuple[datetime, datetime]]:
        cursor = start
        missing: List[tuple[datetime, datetime]] = []
        for left, right in sorted(covered, key=lambda item: item[0]):
            if right <= cursor or left >= end:
                continue
            if left > cursor:
                missing.append((cursor, min(left, end)))
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end:
            missing.append((cursor, end))
        return [(left, right) for left, right in missing if left < right]

    def history_range(self, exact_contract: str, timeframe: str, *,
                      start_time: Any = None, end_time: Any = None,
                      limit: int = 1500, cancel_event: Any = None) -> Dict[str, Any]:
        """Fetch a precise TopstepX history range, in cached <=20k-bar chunks.

        The returned bars are always sorted/deduplicated. Empty successful
        chunks become a real provider-history boundary, never synthetic data.
        """
        if not self._authenticate():
            return {"bars": [], "history_exhausted": False, "error": self._last_error}
        unit, unit_number, nominal_seconds, canonical_tf = topstep_timeframe_spec(timeframe)
        requested_limit = max(1, min(int(limit or 1500), _TOPSTEP_HISTORY_MAX_BARS))
        end = _utc(end_time)
        start = _utc(start_time, end - timedelta(seconds=nominal_seconds * requested_limit * 2))
        if start >= end:
            raise ValueError("TopstepX history startTime must be before endTime")
        raw_symbol = self._resolve_topstep_symbol(exact_contract)
        contract_id = str(self._contract_id_map.get(raw_symbol) or "")
        if not contract_id:
            raise ValueError("TopstepX contract id not resolved")
        cache_key = (contract_id, canonical_tf, bool(self.settings()["live_subscription"]))
        request_key = cache_key + (
            start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z"),
        )
        owner = False
        with self._history_lock:
            entry = self._history_cache.setdefault(cache_key, {"bars": [], "covered": [], "exhausted_before": None})
            missing = self._range_missing(entry["covered"], start, end)
            if not missing:
                self._history_stats["cache_hits"] += 1
                self._session.record("history_cache_hits")
            waiter = self._history_inflight.get(request_key)
            if missing and waiter is None:
                waiter = threading.Event()
                self._history_inflight[request_key] = waiter
                owner = True
        if missing and not owner:
            waiter.wait(timeout=20.0)
            with self._history_lock:
                entry = self._history_cache.setdefault(cache_key, {"bars": [], "covered": [], "exhausted_before": None})
                missing = self._range_missing(entry["covered"], start, end)
        chunks = 0
        native_aggregation_fallback = False
        try:
            for left, right in list(missing):
                # Work backwards from the visible edge so a pan-left request
                # renders its nearest candles first under a slow connection.
                cursor = right
                chunk_span = timedelta(seconds=nominal_seconds * _TOPSTEP_HISTORY_MAX_BARS)
                while cursor > left:
                    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                        raise RuntimeError("TopstepX history request cancelled")
                    chunk_start = max(left, cursor - chunk_span)
                    data = self._history_request({
                        "contractId": contract_id, "unit": unit, "unitNumber": unit_number,
                        "limit": _TOPSTEP_HISTORY_MAX_BARS,
                        "live": bool(self.settings()["live_subscription"]),
                        "startTime": chunk_start.isoformat().replace("+00:00", "Z"),
                        "endTime": cursor.isoformat().replace("+00:00", "Z"),
                        "includePartialBar": True,
                    }, cancel_event=cancel_event)
                    rows = _normalize_history_bars(data.get("bars", []))
                    with self._history_lock:
                        entry = self._history_cache.setdefault(cache_key, {"bars": [], "covered": [], "exhausted_before": None})
                        entry["bars"] = _normalize_history_bars(list(entry["bars"]) + rows)
                        entry["covered"].append((chunk_start, cursor))
                        if not rows:
                            previous = entry.get("exhausted_before")
                            entry["exhausted_before"] = chunk_start if previous is None else max(previous, chunk_start)
                        self._history_stats["requests"] += 1
                    chunks += 1
                    cursor = chunk_start
        except RuntimeError:
            # ProjectX documents Week/Month units, but the live TopstepX
            # gateway currently returns HTTP 500 for those native requests.
            # Fall back only to aggregation of its own daily OHLCV; this keeps
            # the chart honest while retaining the native request as first try.
            if unit not in {5, 6}:
                raise
            native_aggregation_fallback = True
        finally:
            if owner:
                with self._history_lock:
                    signal = self._history_inflight.pop(request_key, None)
                    if signal is not None:
                        signal.set()
        with self._history_lock:
            entry = self._history_cache.setdefault(cache_key, {"bars": [], "covered": [], "exhausted_before": None})
            bars = [row for row in entry["bars"] if start <= _history_bar_time(row.get("t")) < end]
            exhausted_before = entry.get("exhausted_before")
            cache_hit = chunks == 0
        if native_aggregation_fallback:
            daily = self.history_range(
                exact_contract, "1D", start_time=start, end_time=end,
                limit=_TOPSTEP_HISTORY_MAX_BARS, cancel_event=cancel_event,
            )
            bars = _aggregate_daily_calendar(list(daily.get("bars") or []), canonical_tf)
            chunks += int(daily.get("chunks") or 0)
        bars = self._overlay_realtime_bar(exact_contract, canonical_tf, bars)
        return {
            "bars": bars[-requested_limit:], "contract_id": contract_id,
            "requested_start_utc": start.isoformat().replace("+00:00", "Z"),
            "requested_end_utc": end.isoformat().replace("+00:00", "Z"),
            "chunks": chunks, "cache_hit": cache_hit,
            "history_exhausted": bool(exhausted_before is not None and start <= exhausted_before),
            "history_stats": dict(self._history_stats),
            "native_aggregation_fallback": native_aggregation_fallback,
        }

    def _overlay_realtime_bar(self, exact_contract: str, timeframe: str,
                              bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Update only an open final candle from a verified Market SignalR quote."""
        if not bars:
            return bars
        quote = self._latest_quotes.get(" ".join(str(exact_contract or "").upper().split()))
        if not quote:
            return bars
        try:
            _, _, nominal_seconds, _ = topstep_timeframe_spec(timeframe)
            bar_time = _history_bar_time(bars[-1].get("t"))
            quote_time = _history_bar_time(quote.get("t"))
            price = float(quote.get("price"))
        except (TypeError, ValueError):
            return bars
        if bar_time is None or quote_time is None or quote_time < bar_time or quote_time >= bar_time + timedelta(seconds=nominal_seconds):
            return bars
        merged = dict(bars[-1])
        merged["h"] = max(float(merged["h"]), price)
        merged["l"] = min(float(merged["l"]), price)
        merged["c"] = price
        merged["v"] = max(float(merged.get("v") or 0), float(quote.get("volume") or 0))
        return list(bars[:-1]) + [merged]

    def connect(self) -> Dict[str, Any]:
        if not self._authenticate():
            return self.health()
        # A large browser layout acquires many contracts from independent HTTP
        # / WebSocket handler threads. Starting the shared Market worker must
        # therefore be single-flight; otherwise several callers can all see a
        # not-yet-alive thread and open duplicate SignalR sessions.
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._run_async_loop,
                    name="topstepx-market-signalr",
                    daemon=True,
                )
                self._thread.start()

        return self.health()

    def disconnect(self) -> None:
        ws = self._ws_client
        loop = self._loop
        super().disconnect()
        with self._lock:
            self._wire_subscribed_contract_ids.clear()
            self._wire_subscribe_pending.clear()
        if ws is not None and loop is not None:
            try:
                import asyncio
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except Exception:
                pass

    def _run_async_loop(self) -> None:
        import asyncio
        self._loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(self._loop)
            # A detached DEV server can outlive the shell/pipe that launched
            # it.  asyncio's default exception handler writes unretrieved task
            # failures to stderr; a dead pipe can then block this sole market
            # worker forever while the thread still looks alive to connect().
            # Record a sanitized internal diagnostic instead of doing blocking
            # I/O from the realtime event loop.
            self._loop.set_exception_handler(self._handle_signalr_loop_exception)
            self._signalr_send_lock = asyncio.Lock()
            self._signalr_invoke_lock = asyncio.Lock()
            self._loop.run_until_complete(self._websocket_worker())
        finally:
            self._loop.close()
            self._loop = None
            self._signalr_send_lock = None
            self._signalr_invoke_lock = None

    def _handle_signalr_loop_exception(self, _loop: Any, context: Dict[str, Any]) -> None:
        """Keep an unretrieved background-task error from blocking SignalR."""
        error = context.get("exception")
        error_kind = type(error).__name__ if error is not None else "AsyncioError"
        self._session.record("signalr_background_task_errors")
        self._last_error = f"WS background task failed: {error_kind}"

    async def _send_signalr_frame(self, ws: Any, payload: str) -> None:
        """Send one SignalR frame without letting socket backpressure hang forever."""
        import asyncio

        async def send() -> None:
            if self._ws_client is not None and ws is not self._ws_client:
                raise ConnectionError("stale TopstepX SignalR socket")
            await asyncio.wait_for(
                ws.send(payload), timeout=self._signalr_send_timeout_sec,
            )
            # ProjectX's official client invokes subscriptions through one Hub
            # connection. Serialize our raw protocol writes and leave a small
            # bounded gap so a 36-chart layout cannot flood that connection.
            if self._signalr_write_spacing_sec > 0:
                await asyncio.sleep(self._signalr_write_spacing_sec)

        lock = self._signalr_send_lock
        if lock is None:
            await send()
            return
        async with lock:
            await send()

    async def _websocket_worker(self) -> None:
        import websockets
        import json
        import asyncio

        backoff = 1.0
        while not self._stop.is_set():
            connection_stage = "authenticate"
            connection_opened = False
            owned_ws = None
            connection_token = ""
            connection_epoch = -1
            resubscribe_task = None
            if not self._authenticate():
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            connection_token, connection_epoch = self._session.token_snapshot()
            if connection_token:
                self._token = connection_token
            url = f"wss://rtc.topstepx.com/hubs/market?access_token={self._token}"
            try:
                connection_stage = "connect"
                self._session.record("signalr_connection_attempts")
                async with websockets.connect(
                    url,
                    open_timeout=self._signalr_send_timeout_sec,
                    close_timeout=self._signalr_close_timeout_sec,
                ) as ws:
                    owned_ws = ws
                    self._ws_client = ws
                    connection_stage = "handshake"
                    await self._send_signalr_frame(
                        ws, json.dumps({"protocol": "json", "version": 1}) + "\x1e",
                    )
                    handshake_resp = await ws.recv()
                    self._record_signalr_receive()
                    handshake_parts = [part for part in str(handshake_resp).split("\x1e") if part]
                    if handshake_parts:
                        handshake = json.loads(handshake_parts[0])
                        if isinstance(handshake, dict) and handshake.get("error"):
                            raise ValueError(str(handshake.get("error")))
                    self._runtime_state = "AUTHENTICATED"
                    self._connected_at = _iso()
                    self._last_error = ""
                    # A SignalR reconnect has no retained server-side
                    # subscriptions.  Keep logical chart references, but let
                    # the new socket subscribe each contract exactly once.
                    with self._lock:
                        completion_waiters = list(self._signal_completion_waiters.values())
                        self._wire_subscribed_contract_ids.clear()
                        self._wire_subscribe_pending.clear()
                        self._pending_signal_invocations.clear()
                        self._signal_completion_waiters.clear()
                    for waiter in completion_waiters:
                        if waiter is not None and not waiter.done():
                            waiter.cancel()
                    self._session.record("signalr_connections_opened")
                    if self._market_connection_opened_once:
                        self._session.record("signalr_reconnects")
                    else:
                        self._market_connection_opened_once = True
                    connection_opened = True

                    # Match the official SignalR client lifecycle: keep the
                    # receive loop active while invoke() calls are being sent.
                    # Serially sending dozens of quote/trade subscriptions
                    # before the first recv() lets completion/market messages
                    # pile up and the Gateway can close an otherwise valid hub.
                    connection_stage = "subscribe"
                    resubscribe_task = asyncio.create_task(self._resubscribe_ws(ws))

                    # Resume the shared live stream immediately.  Gap-fill is
                    # still required after reconnect, but on a large layout its
                    # rate-limited REST calls must not prevent this coroutine
                    # from reading SignalR frames/heartbeats.  The single-flight
                    # worker merges into the same deduplicated cache, while the
                    # latest received quote remains authoritative for the open
                    # bar, so history cannot roll the visible live close back.
                    connection_stage = "gap_fill"
                    self._start_gap_fill_subscriptions()

                    connection_stage = "stream"
                    while not self._stop.is_set():
                        if self._token_expires_at <= time.time() + 300:
                            break
                        if resubscribe_task.done():
                            subscribe_error = resubscribe_task.exception()
                            if subscribe_error is not None:
                                connection_stage = "subscribe"
                                raise subscribe_error
                        try:
                            raw_data = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            self._record_signalr_receive()
                            # A handshake alone is not a healthy market hub.
                            # Reset reconnect backoff only after the server has
                            # actually delivered a SignalR frame.
                            backoff = 1.0
                            parts = str(raw_data).split("\x1e")
                            for part in parts:
                                if not part:
                                    continue
                                msg = json.loads(part)
                                if msg.get("type") == 6:
                                    self._record_signalr_receive(heartbeat=True)
                                    await self._send_signalr_frame(ws, '{"type":6}\x1e')
                                    continue
                                if msg.get("type") == 7:
                                    # ProjectX can leave REST calls working
                                    # while the Gateway session behind Market
                                    # SignalR has disappeared.  In that state
                                    # the hub sends an empty type=7 then closes
                                    # with WebSocket code 1000.  Treat it as an
                                    # authorization lifecycle event: validate
                                    # this exact token and only loginKey after
                                    # a definitive 1/2/3 rejection.
                                    self._session.record("signalr_close_messages")
                                    raise _TopstepXRealtimeSessionClosed()
                                if msg.get("type") == 1:
                                    self._on_ws_message(
                                        msg.get("target"), msg.get("arguments", []),
                                    )
                                elif msg.get("type") == 3:
                                    self._on_signal_completion(msg)
                            if self._market_stream_stale():
                                self._last_error = "TopstepX market SignalR stream stalled; reconnecting"
                                self._runtime_state = "DEGRADED"
                                break
                        except asyncio.TimeoutError:
                            if self._market_stream_stale():
                                self._last_error = "TopstepX market SignalR stream stalled; reconnecting"
                                self._runtime_state = "DEGRADED"
                                break
                            try:
                                await self._send_signalr_frame(ws, '{"type":6}\x1e')
                            except asyncio.TimeoutError:
                                self._last_error = "TopstepX market SignalR write stalled; reconnecting"
                                self._runtime_state = "DEGRADED"
                                break
            except _TopstepXRealtimeSessionClosed:
                self._last_error = (
                    "TopstepX realtime session closed; validating shared JWT"
                )
                self._runtime_state = "DEGRADED"
                recovered = await asyncio.to_thread(
                    self._recover_realtime_session,
                    connection_token,
                    connection_epoch,
                )
                if recovered:
                    backoff = 1.0
                else:
                    backoff = max(backoff, 10.0)
            except Exception as exc:
                # Keep credentials and vendor payloads out of public health,
                # while still naming the failed lifecycle stage and exception
                # class needed to diagnose a reconnect loop.
                self._last_error = (
                    f"WS connection failed during {connection_stage}: {type(exc).__name__}"
                )
                self._runtime_state = "DEGRADED"
            finally:
                with self._lock:
                    completion_waiters = list(self._signal_completion_waiters.values())
                    self._signal_completion_waiters.clear()
                    self._pending_signal_invocations.clear()
                for waiter in completion_waiters:
                    if waiter is not None and not waiter.done():
                        waiter.cancel()
                if resubscribe_task is not None:
                    if not resubscribe_task.done():
                        resubscribe_task.cancel()
                        # Never await cancellation without a deadline: websocket
                        # flow control may keep send() pending on a dead transport.
                        # The task is tied to the old socket and will exit after
                        # its bounded write even if cancellation is delayed.
                        await asyncio.wait(
                            {resubscribe_task}, timeout=self._signalr_close_timeout_sec,
                        )
                    # Retrieve success, cancellation or failure even when the
                    # task completed immediately before connection cleanup.
                    # Otherwise asyncio reports it later through its default
                    # stderr logger, which can block a detached DEV process.
                    if resubscribe_task.done():
                        try:
                            resubscribe_task.result()
                        except (asyncio.CancelledError, Exception):
                            pass
                # Never let cleanup for an older worker/socket erase a newer
                # connection reference. The single-flight start above prevents
                # that race going forward; this identity guard also makes
                # recovery safe if a pre-fix duplicate worker is still exiting.
                with self._lock:
                    if owned_ws is not None and self._ws_client is owned_ws:
                        self._ws_client = None
                if connection_opened:
                    self._session.record("signalr_connections_closed")
            if not self._stop.is_set():
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)

    def _recover_realtime_session(self, failed_token: str, failed_epoch: int) -> bool:
        """Single-flight validate/login recovery after SignalR type=7."""
        self._session.record("signalr_auth_recovery_attempts")
        try:
            if not failed_token or not self._authenticate(
                force=True,
                failed_token=failed_token,
                failed_epoch=failed_epoch,
            ):
                raise RuntimeError("TopstepX realtime recovery unavailable")
            self._session.record("signalr_auth_recovery_successes")
            self._last_error = "TopstepX realtime session recovered; reconnecting"
            return True
        except Exception:
            self._session.record("signalr_auth_recovery_failures")
            self._last_error = "TopstepX realtime session recovery failed"
            self._runtime_state = "AUTH_FAILED"
            return False

    async def _resubscribe_ws(self, ws: Any) -> None:
        """Multiplex current contracts while the main coroutine reads frames."""
        import asyncio

        with self._lock:
            raw_symbols = list(dict.fromkeys(
                str(sub.get("raw_symbol") or "") for sub in self._subs.values()
                if str(sub.get("raw_symbol") or "")
            ))
        for raw_symbol in raw_symbols:
            if self._stop.is_set() or ws is not self._ws_client:
                return
            await self._subscribe_ws(ws, raw_symbol)
            # Avoid a reconnect burst while keeping all visible charts ready
            # within a couple of seconds on a 30-40 contract desktop.
            await asyncio.sleep(0.03)

    def _start_gap_fill_subscriptions(self) -> bool:
        """Start one non-blocking reconnect gap-fill for the shared adapter."""
        if not self._gap_fill_lock.acquire(blocking=False):
            return False

        def run() -> None:
            try:
                self._gap_fill_subscriptions()
            finally:
                self._gap_fill_lock.release()

        try:
            threading.Thread(
                target=run, name="topstepx-gap-fill", daemon=True,
            ).start()
        except Exception:
            self._gap_fill_lock.release()
            raise
        return True

    def _gap_fill_subscriptions(self) -> None:
        refreshed = 0
        seen: set[tuple[str, str]] = set()
        for sub in list(self._subs.values()):
            key = (str(sub.get("exact_contract") or ""), str(sub.get("timeframe") or "1m"))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            try:
                self.history_range(
                    sub["exact_contract"], str(sub.get("timeframe") or "1m"), limit=8,
                )
                refreshed += 1
            except Exception:
                continue
        if refreshed:
            with self._history_lock:
                self._history_stats["gap_fills"] += refreshed
            self._last_reconnect_gap_fill_utc = _iso()

    def subscribe(self, exact_contract: str, channel: str = "trades", *, timeframe: str = "1m",
                  consumer_id: str = "bootstrap") -> str:
        if not self._authenticate():
            raise RuntimeError(self._last_error or "TopstepX authentication unavailable")
        contract = " ".join(str(exact_contract or "").strip().upper().split())
        if not contract:
            raise ValueError("exact_contract required")

        raw_symbol = self._resolve_topstep_symbol(contract)
        schema = "quotes" if channel in {"bid_ask", "quotes"} else "trades"
        sub_id = f"topstep:{contract}:{schema}"
        consumer = str(consumer_id or "bootstrap")[:160]

        with self._lock:
            row = self._subs.get(sub_id)
            if row is None:
                row = {
                    "exact_contract": contract,
                    "raw_symbol": raw_symbol,
                    "channel": channel,
                    "schema": schema,
                    "timeframe": str(timeframe or "1m"),
                    "consumers": set(),
                }
                self._subs[sub_id] = row
            consumers = row.setdefault("consumers", set())
            # Do not retain an HTTP bootstrap reference after a real browser
            # chart has already acquired this contract/timeframe.
            bootstrap = consumer.startswith("bootstrap:")
            has_browser_consumer = any(not str(item).startswith("bootstrap:") for item in consumers)
            already = consumer in consumers or (bootstrap and has_browser_consumer)
            if not (bootstrap and has_browser_consumer):
                consumers.add(consumer)
        self._session.record("logical_subscription_requests")
        if already:
            self._session.record("logical_subscription_deduplicated")

        if self._ws_client is not None and self._loop is not None:
            import asyncio
            asyncio.run_coroutine_threadsafe(self._subscribe_ws(self._ws_client, raw_symbol), self._loop)
            self._runtime_state = "AUTHENTICATED"

        return sub_id

    def release_subscription(self, exact_contract: str, channel: str = "quotes", *,
                             timeframe: str = "1m", consumer_id: str = "") -> bool:
        """Release one browser/chart reference and unsubscribe only at zero refs."""
        contract = " ".join(str(exact_contract or "").strip().upper().split())
        schema = "quotes" if channel in {"bid_ask", "quotes"} else "trades"
        sub_id = f"topstep:{contract}:{schema}"
        consumer = str(consumer_id or "")[:160]
        raw_symbol = ""
        should_unsubscribe = False
        with self._lock:
            row = self._subs.get(sub_id)
            if row is None:
                return False
            consumers = row.setdefault("consumers", set())
            if consumer:
                consumers.discard(consumer)
            else:
                consumers.clear()
            if consumers:
                self._session.record("logical_unsubscribe_requests")
                return True
            removed = self._subs.pop(sub_id, None) or {}
            raw_symbol = str(removed.get("raw_symbol") or "")
            # One GatewayQuote subscription carries lastPrice plus bid/ask for
            # the chart. Keep that wire stream while any logical schema/chart
            # still references the contract.
            should_unsubscribe = bool(raw_symbol) and not any(
                str(row.get("raw_symbol") or "") == raw_symbol for row in self._subs.values()
            )
        self._session.record("logical_unsubscribe_requests")
        if should_unsubscribe and self._ws_client is not None and self._loop is not None:
            import asyncio
            asyncio.run_coroutine_threadsafe(self._unsubscribe_ws(self._ws_client, raw_symbol), self._loop)
        return True

    def unsubscribe(self, subscription_id: str) -> None:
        """Compatibility release used by generic registries/tests."""
        sub_id = str(subscription_id or "")
        with self._lock:
            row = dict(self._subs.get(sub_id) or {})
            consumers = list(row.get("consumers") or [])
        if not row:
            return
        if consumers:
            for consumer in consumers:
                self.release_subscription(
                    str(row.get("exact_contract") or ""), str(row.get("channel") or "quotes"),
                    timeframe=str(row.get("timeframe") or "1m"), consumer_id=str(consumer),
                )
        else:
            self.release_subscription(
                str(row.get("exact_contract") or ""), str(row.get("channel") or "quotes"),
                timeframe=str(row.get("timeframe") or "1m"), consumer_id="",
            )

    async def _subscribe_ws(self, ws: Any, symbol: str) -> None:
        import asyncio
        import json
        import uuid
        with self._lock:
            contract_id = self._contract_id_map.get(symbol)
            if not contract_id:
                raise ValueError(f"ProjectX contract id not resolved for {symbol}")
            if contract_id in self._wire_subscribed_contract_ids or contract_id in self._wire_subscribe_pending:
                self._session.record("logical_subscription_deduplicated")
                return
            self._wire_subscribe_pending.add(contract_id)
        inv_id_quotes = f"sub_quotes_{uuid.uuid4().hex[:6]}"
        running_loop = asyncio.get_running_loop()
        wait_for_completion = bool(self._loop is running_loop and ws is self._ws_client)
        completion_waiter = running_loop.create_future() if wait_for_completion else None
        try:
            msg_quotes = {
                "type": 1,
                "invocationId": inv_id_quotes,
                "target": "SubscribeContractQuotes",
                "arguments": [contract_id]
            }
            with self._lock:
                self._pending_signal_invocations[inv_id_quotes] = {
                    "target": "SubscribeContractQuotes", "contract_id": contract_id,
                }
                if completion_waiter is not None:
                    self._signal_completion_waiters[inv_id_quotes] = completion_waiter

            async def invoke() -> None:
                await self._send_signalr_frame(ws, json.dumps(msg_quotes) + "\x1e")
                if completion_waiter is None:
                    return
                completion = await asyncio.wait_for(
                    completion_waiter, timeout=self._signalr_send_timeout_sec,
                )
                if completion.get("error"):
                    raise ValueError("ProjectX SubscribeContractQuotes rejected")

            invoke_lock = self._signalr_invoke_lock
            if invoke_lock is None:
                await invoke()
            else:
                async with invoke_lock:
                    await invoke()
            with self._lock:
                self._wire_subscribed_contract_ids.add(contract_id)
            self._session.record("signalr_subscribe_invocations")
        finally:
            with self._lock:
                self._pending_signal_invocations.pop(inv_id_quotes, None)
                self._signal_completion_waiters.pop(inv_id_quotes, None)
                self._wire_subscribe_pending.discard(contract_id)

    async def _unsubscribe_ws(self, ws: Any, symbol: str) -> None:
        import json
        import uuid
        with self._lock:
            contract_id = self._contract_id_map.get(symbol)
            if not contract_id or contract_id not in self._wire_subscribed_contract_ids:
                return
            self._wire_subscribed_contract_ids.discard(contract_id)
        invocation = f"unsub_{uuid.uuid4().hex[:6]}"
        await self._send_signalr_frame(ws, json.dumps({
            "type": 1, "invocationId": invocation,
            "target": "UnsubscribeContractQuotes", "arguments": [contract_id],
        }) + "\x1e")
        self._session.record("signalr_unsubscribe_invocations")

    def _on_signal_completion(self, message: Dict[str, Any]) -> None:
        invocation_id = str(message.get("invocationId") or "")
        with self._lock:
            pending = self._pending_signal_invocations.pop(invocation_id, {})
            waiter = self._signal_completion_waiters.pop(invocation_id, None)
            target = str(pending.get("target") or "unknown")
            completion = {
                "ok": not bool(message.get("error")),
                "contract_id": str(pending.get("contract_id") or "")[:80],
                "completed_at_utc": _iso(),
                "error": "SignalR invocation rejected" if message.get("error") else "",
            }
            self._signal_invocation_results[target] = completion
        if waiter is not None and not waiter.done():
            waiter.set_result(completion)

    def _record_signalr_receive(self, *, heartbeat: bool = False) -> None:
        now = _iso()
        with self._lock:
            self._last_signalr_receive_utc = now
            if heartbeat:
                self._last_signalr_heartbeat_utc = now

    def _market_stream_stale(self) -> bool:
        """Reconnect only for a proved dead SignalR transport, never a quiet price."""
        if not self._subs or not self._connected_at:
            return False
        try:
            connected = datetime.fromisoformat(self._connected_at.replace("Z", "+00:00"))
            now_utc = datetime.now(timezone.utc)
            if (now_utc - connected).total_seconds() < 20.0:
                return False
        except ValueError:
            return False
        with self._lock:
            receive_at = self._last_signalr_receive_utc
            heartbeat_at = self._last_signalr_heartbeat_utc
        receive_age = self._utc_age(receive_at, now_utc)
        heartbeat_age = self._utc_age(heartbeat_at, now_utc)
        # There is no inference from lastPrice/last trade here.  A 45-second
        # absence of both incoming SignalR frames and server heartbeats is the
        # first actual evidence that the market socket has stalled.
        return all(age is None or age > 45.0 for age in (receive_age, heartbeat_age))

    def _trade_stream_stale(self) -> bool:
        """Compatibility alias retained for existing diagnostics/tests."""
        return self._market_stream_stale()

    def _resolve_topstep_symbol(self, contract: str) -> str:
        contract = " ".join(str(contract or "").strip().upper().split())
        with self._lock:
            if contract in self._contract_id_map:
                return self._contract_id_map[contract]

        root = contract.split(" ")[0]
        try:
            data = _post_json(
                "https://api.topstepx.com/api/Contract/search",
                {"searchText": root, "live": bool(self.settings()["live_subscription"])},
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=5.0
            )
            rows = [
                item for item in data.get("contracts", data.get("available", []))
                if isinstance(item, dict)
            ]
            exact_requested = bool(_CONTRACT_RE.fullmatch(contract))
            expected_raw = databento_raw_symbol(contract) if exact_requested else ""

            def matches_root(item: Dict[str, Any]) -> bool:
                symbol_root = str(item.get("symbolId") or "").upper().rsplit(".", 1)[-1]
                provider_symbol = str(item.get("name") or item.get("symbol") or "").upper()
                return bool(
                    symbol_root == root
                    or re.fullmatch(re.escape(root) + r"[FGHJKMNQUVXZ]\d{1,2}", provider_symbol)
                )

            matching = [item for item in rows if matches_root(item)]
            if exact_requested:
                matching = [
                    item for item in matching
                    if str(item.get("name") or item.get("symbol") or "").upper() == expected_raw.upper()
                ]
            else:
                matching.sort(key=lambda item: not bool(item.get("activeContract")))

            if matching:
                item = matching[0]
                raw = str(item.get("name") or item.get("symbol") or "").upper()
                cid = str(item["id"])
                resolved_exact = contract if exact_requested else topstep_exact_contract(root, item)
                if not raw or not cid:
                    raise ValueError("ProjectX contract response is incomplete")
                with self._lock:
                    self._contract_id_map[contract] = raw
                    self._contract_id_map[raw] = cid
                    self._contract_id_map[resolved_exact] = raw
                    self._contract_symbol_map[cid] = resolved_exact
                    self._resolved_exact_map[contract] = resolved_exact
                    self._resolved_exact_map[raw] = resolved_exact
                return raw
        except Exception:
            self._last_error = "TopstepX contract search failed"
            raise ValueError(self._last_error) from None
        self._last_error = f"TopstepX active/exact contract not found: {contract}"
        raise ValueError(self._last_error)

    def resolved_exact_contract(self, contract: str) -> str:
        normalized = " ".join(str(contract or "").strip().upper().split())
        with self._lock:
            return str(self._resolved_exact_map.get(normalized) or normalized)

    def _on_ws_message(self, target: str, args: List[Any]) -> None:
        # Official ProjectX callbacks are (contractId, data).  Accept the old
        # single-dict shape too so recorded fixtures remain replayable.
        self._record_signalr_receive()
        rows: List[tuple[str, Dict[str, Any]]] = []
        if len(args) >= 2 and isinstance(args[1], dict):
            rows.append((str(args[0]), args[1]))
        else:
            rows.extend(("", arg) for arg in args if isinstance(arg, dict))
        for contract_id, arg in rows:
            if not arg:
                continue
            self._last_signal_target = str(target or "")[:80]
            signal_target = self._last_signal_target or "unknown"
            self._signal_target_counts[signal_target] = self._signal_target_counts.get(signal_target, 0) + 1
            exact = self._contract_symbol_map.get(contract_id, "")
            symbol = str(arg.get("symbol") or arg.get("symbolId") or "")
            with self._lock:
                if not exact:
                    for sub in self._subs.values():
                        mapped_id = self._contract_id_map.get(sub["raw_symbol"])
                        if (symbol and sub["raw_symbol"] == symbol) or (
                            contract_id and mapped_id == contract_id
                        ):
                            exact = sub["exact_contract"]
                            symbol = symbol or sub["raw_symbol"]
                            break
            if not exact:
                continue
            symbol = symbol or contract_id

            price = arg.get("price")
            price_field = "price" if price is not None else ""
            if price is None:
                price = arg.get("lastPrice")
                price_field = "lastPrice" if price is not None else ""
            if price is None:
                price = arg.get("bestBid")
                price_field = "bestBid" if price is not None else ""
            if price is None:
                price = arg.get("bestAsk")
                price_field = "bestAsk" if price is not None else ""
            self._last_signal_price_field = price_field
            signal_price_field = price_field or "none"
            self._signal_price_field_counts[signal_price_field] = self._signal_price_field_counts.get(signal_price_field, 0) + 1
            size = arg.get("size")
            if size is None:
                size = arg.get("volume")

            if self._runtime_state in {"CONNECTING", "AUTHENTICATED", "DEGRADED"}:
                self._runtime_state = "LIVE"

            target_lower = str(target or "").lower()
            is_trade = target_lower in {"gatewaytrade", "ontrade", "trade", "trades"}
            # ProjectX's active Market SignalR feed delivers the actual last
            # traded price on GatewayQuote.lastPrice.  A quote-side bid/ask is
            # kept as a quote; only the documented/observed last price may
            # advance an OHLC bar.
            is_last_trade_price = price_field == "lastPrice"

            received_at = _iso()
            with self._lock:
                if target_lower in {"gatewayquote", "onquote", "quote", "quotes"}:
                    self._last_quote_receive_utc[exact] = received_at
                    if arg.get("bestBid") is not None or arg.get("bestAsk") is not None:
                        self._last_bid_ask_receive_utc[exact] = received_at
                if is_trade or is_last_trade_price:
                    self._last_trade_receive_utc[exact] = received_at

            # HTTP history may merge the latest *trade* into its forming bar.
            # Never place bestBid/bestAsk here: otherwise the 5-second HTTP
            # health poll overwrites a correct WebSocket trade close with a
            # quote-side price.
            if price is not None and (is_trade or is_last_trade_price):
                with self._lock:
                    self._latest_quotes[exact] = {
                        "price": price, "volume": (size or 0) if is_trade else 0,
                        "t": arg.get("timestamp") or arg.get("lastUpdated") or arg.get("time") or _iso(),
                    }

            reg = get_registry().resolve_exact(exact, allow_continuous=False) if exact else {}
            event = make_canonical_event(
                event_type="trade" if (is_trade or is_last_trade_price) else "quote",
                provider=self.name,
                raw_symbol=symbol,
                exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or exact),
                canonical_symbol=str(reg.get("root") or ""),
                price=float(price) if price is not None else None,
                # GatewayQuote.volume is documented as cumulative session
                # volume, not the size of this last-price update. Only a real
                # GatewayTrade may contribute per-event volume to OHLCV.
                volume=float(size) if (size is not None and (is_trade or not is_last_trade_price)) else None,
                exchange_sequence=arg.get("sequence"),
                provider_sequence=self._event_count + 1,
                ts_event=arg.get("timestamp") or arg.get("lastUpdated") or arg.get("time") or _iso(),
                ts_provider=_iso(),
                quality={
                    "topstep_live": True,
                    "signal_target": signal_target,
                    "signal_price_field": signal_price_field,
                },
                data_plane="analytics" if self._mode == "shadow" else "display",
            )
            self._emit(event)

    def backfill(self, exact_contract: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        try:
            return list(self.history_range(exact_contract, timeframe, limit=limit).get("bars") or [])
        except Exception:
            self._last_error = "TopstepX retrieve bars failed"
            return []


class DxFeedLiveAdapter(LiveMarketDataAdapter):
    """Real dxFeed Live Market Data client (WIP)."""

    name = "dxfeed_live"

    def implementation_state(self) -> str:
        return "NOT_IMPLEMENTED" if not self.credentials_present() else "ADAPTER_READY"

    def credentials_present(self) -> bool:
        token = str(os.environ.get("NTA_DXFEED_TOKEN") or os.environ.get("DXFEED_TOKEN") or "").strip()
        return bool(token and not is_mock_key(token, "dx"))

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        caps.update({
            "capability": "ENTITLEMENT_MISSING" if not self.credentials_present() else "REALTIME_PRODUCTION",
            "channels": ["trades", "bid_ask", "depth"],
            "note": "CME futures via dxFeed Market Data Platform — auth/subscribe/normalize pending.",
        })
        return caps

    def connect(self) -> Dict[str, Any]:
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_DXFEED_TOKEN not configured or is a mock key"
            return self.health()

        self._runtime_state = "ERROR"
        self._last_error = "Real dxFeed connection not implemented (credentials present but transport blocked)"
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        raise NotImplementedError("Real dxFeed connection requires valid non-mock API credentials.")

    def _parse_dxfeed_message(self, text: str) -> None:
        import json
        try:
            data = json.loads(text)
            if not isinstance(data, list):
                return
            for item in data:
                event_type = item.get("event")
                if event_type == "Trade":
                    price = item.get("price")
                    size = item.get("size")
                    symbol = item.get("eventSymbol")
                    seq = item.get("sequence")
                    ts = item.get("time")

                    reg = get_registry().resolve_exact(symbol, allow_continuous=False) if symbol else {}
                    event = make_canonical_event(
                        event_type="trade",
                        provider=self.name,
                        raw_symbol=symbol,
                        exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or symbol),
                        canonical_symbol=str(reg.get("root") or ""),
                        price=price,
                        volume=size,
                        exchange_sequence=seq,
                        provider_sequence=self._event_count + 1,
                        ts_event=datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z") if ts else _iso(),
                        ts_provider=_iso(),
                        quality={"dxfeed_live": True},
                        data_plane="analytics" if self._mode == "shadow" else "display"
                    )
                    self._emit(event)
                    self._runtime_state = "LIVE"
                elif event_type == "Quote":
                    bid = item.get("bidPrice")
                    ask = item.get("askPrice")
                    bid_size = item.get("bidSize")
                    ask_size = item.get("askSize")
                    symbol = item.get("eventSymbol")
                    ts = item.get("time")

                    reg = get_registry().resolve_exact(symbol, allow_continuous=False) if symbol else {}
                    event = make_canonical_event(
                        event_type="quote",
                        provider=self.name,
                        raw_symbol=symbol,
                        exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or symbol),
                        canonical_symbol=str(reg.get("root") or ""),
                        bid=bid,
                        ask=ask,
                        volume=bid_size,
                        provider_sequence=self._event_count + 1,
                        ts_event=datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z") if ts else _iso(),
                        ts_provider=_iso(),
                        quality={"dxfeed_live": True},
                        data_plane="analytics" if self._mode == "shadow" else "display"
                    )
                    self._emit(event)
                    self._runtime_state = "LIVE"
        except Exception as exc:
            self._last_error = f"dxfeed_parse_error: {exc}"
            self._runtime_state = "ERROR"


class CqgLiveAdapter(LiveMarketDataAdapter):
    """Real CQG WebAPI client (WIP)."""

    name = "cqg_live"

    def implementation_state(self) -> str:
        return "NOT_IMPLEMENTED" if not self.credentials_present() else "ADAPTER_READY"

    def credentials_present(self) -> bool:
        user = str(os.environ.get("NTA_CQG_USERNAME") or "").strip()
        pw = str(os.environ.get("NTA_CQG_PASSWORD") or "").strip()
        return bool(user and pw and not is_mock_key(user, "cqg"))

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        caps.update({
            "capability": "ENTITLEMENT_MISSING" if not self.credentials_present() else "REALTIME_PRODUCTION",
            "note": "CQG WebAPI — auth/subscribe/normalize pending (Rithmic optional substitute).",
        })
        return caps

    def connect(self) -> Dict[str, Any]:
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_CQG_USERNAME/PASSWORD not configured or are mock credentials"
            return self.health()

        self._runtime_state = "ERROR"
        self._last_error = "Real CQG connection not implemented (credentials present but transport blocked)"
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        raise NotImplementedError("Real CQG connection requires valid non-mock API credentials.")

    def _parse_cqg_message(self, text: str) -> None:
        import json
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                return
            cqg_instant = data.get("CQGInstant") or {}
            market_data = cqg_instant.get("MarketData") or {}
            for quote in market_data.get("Quotes", []):
                symbol = quote.get("Symbol")
                price = quote.get("Last")
                volume = quote.get("LastVolume")
                bid = quote.get("Bid")
                ask = quote.get("Ask")
                ts_ms = quote.get("Timestamp")

                if not symbol:
                    continue

                reg = get_registry().resolve_exact(symbol, allow_continuous=False) if symbol else {}
                event = make_canonical_event(
                    event_type="trade" if price is not None else "quote",
                    provider=self.name,
                    raw_symbol=symbol,
                    exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or symbol),
                    canonical_symbol=str(reg.get("root") or ""),
                    price=price,
                    bid=bid,
                    ask=ask,
                    volume=volume,
                    provider_sequence=self._event_count + 1,
                    ts_event=datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z") if ts_ms else _iso(),
                    ts_provider=_iso(),
                    quality={"cqg_live": True},
                    data_plane="analytics" if self._mode == "shadow" else "display"
                )
                self._emit(event)
                self._runtime_state = "LIVE"
        except Exception as exc:
            self._last_error = f"cqg_parse_error: {exc}"
            self._runtime_state = "ERROR"


class CmeWebsocketReferenceAdapter(LiveMarketDataAdapter):
    """Real CME cloud WebSocket client (WIP)."""

    name = "cme_websocket"

    def implementation_state(self) -> str:
        return "NOT_IMPLEMENTED" if not self.credentials_present() else "ADAPTER_READY"

    def credentials_present(self) -> bool:
        token = str(os.environ.get("NTA_CME_WS_TOKEN") or os.environ.get("CME_WS_TOKEN") or "").strip()
        return bool(token and not is_mock_key(token, "cme"))

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        caps.update({
            "capability": "ENTITLEMENT_MISSING" if not self.credentials_present() else "REALTIME_PRODUCTION",
            "role": "reference_fallback",
            "note": "CME WebSocket TOB ~500ms aggregation — prefer as independent reference, not fastest primary.",
        })
        return caps

    def connect(self) -> Dict[str, Any]:
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_CME_WS_TOKEN not configured or is a mock token"
            return self.health()

        self._runtime_state = "ERROR"
        self._last_error = "Real CME WebSocket connection not implemented"
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        raise NotImplementedError("Real CME WebSocket connection requires valid non-mock API credentials.")

    def _parse_cme_message(self, text: str) -> None:
        import json
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                return
            symbol = data.get("symbol")
            if not symbol:
                return
            trade = data.get("trade")
            quote = data.get("quote")
            ts = data.get("timestamp") or (trade or {}).get("timestamp") or (quote or {}).get("timestamp")

            reg = get_registry().resolve_exact(symbol, allow_continuous=False) if symbol else {}
            event = make_canonical_event(
                event_type="trade" if trade else "quote",
                provider=self.name,
                raw_symbol=symbol,
                exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or symbol),
                canonical_symbol=str(reg.get("root") or ""),
                price=(trade or {}).get("price") if trade else None,
                bid=(quote or {}).get("bid") if quote else None,
                ask=(quote or {}).get("ask") if quote else None,
                volume=(trade or {}).get("size") if trade else None,
                provider_sequence=self._event_count + 1,
                ts_event=datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z") if ts else _iso(),
                ts_provider=_iso(),
                quality={"cme_websocket": True},
                data_plane="analytics" if self._mode == "shadow" else "display"
            )
            self._emit(event)
            self._runtime_state = "LIVE"
        except Exception as exc:
            self._last_error = f"cme_parse_error: {exc}"
            self._runtime_state = "ERROR"


class MockLiveMarketDataAdapter(LiveMarketDataAdapter):
    """Base class for mock/simulation adapters."""

    production_failover_eligible = False

    def implementation_state(self) -> str:
        return "MOCK_SIMULATION"

    def credentials_present(self) -> bool:
        return False  # Mock is never considered to have real credentials

    def connect(self) -> Dict[str, Any]:
        self._runtime_state = "SIMULATION"
        self._connected_at = _iso()
        self._last_error = ""
        self._stop.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run_loop, name=f"{self.name}-mock", daemon=True,
            )
            self._thread.start()
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        contract = " ".join(str(exact_contract or "").strip().upper().split())
        if not contract:
            raise ValueError("exact_contract required")
        sub_id = f"{self.name}_mock:{contract}:{channel}"
        with self._lock:
            self._subs[sub_id] = {
                "exact_contract": contract,
                "raw_symbol": contract,
                "channel": channel,
                "schema": channel,
            }
        self._runtime_state = "SIMULATION"
        return sub_id

    def _run_loop(self) -> None:
        import random
        last_prices = {}
        while not self._stop.is_set():
            time.sleep(0.5)
            with self._lock:
                subs = list(self._subs.values())
            if not subs:
                continue
            sub = random.choice(subs)
            tick_size = 0.25
            root = sub["exact_contract"].split(" ")[0]
            if root in {"MGC", "GC", "M2K", "RTY"}:
                tick_size = 0.10
            elif root in {"MYM", "YM"}:
                tick_size = 1.0

            try:
                self._emit_mock_tick(
                    contract=sub["exact_contract"],
                    raw_sym=sub["exact_contract"],
                    schema="trades" if sub["channel"] == "trades" else "bid_ask",
                    tick_size=tick_size,
                    last_prices=last_prices
                )
            except Exception as exc:
                self._last_error = f"mock_tick_error: {exc}"


class DatabentoMockAdapter(MockLiveMarketDataAdapter):
    name = "databento_live"


class DxFeedMockAdapter(MockLiveMarketDataAdapter):
    name = "dxfeed_live"


class CqgMockAdapter(MockLiveMarketDataAdapter):
    name = "cqg_live"


class CmeWebsocketMockAdapter(MockLiveMarketDataAdapter):
    name = "cme_websocket"


def default_live_adapters(*, include_topstep: bool = False) -> List[LiveMarketDataAdapter]:
    adapters = []

    # Databento
    db_key = str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()
    if is_mock_key(db_key, "db"):
        adapters.append(DatabentoMockAdapter())
    else:
        adapters.append(DatabentoLiveAdapter())

    # dxFeed
    dx_token = str(os.environ.get("NTA_DXFEED_TOKEN") or os.environ.get("DXFEED_TOKEN") or "").strip()
    if is_mock_key(dx_token, "dx"):
        adapters.append(DxFeedMockAdapter())
    else:
        adapters.append(DxFeedLiveAdapter())

    # CQG
    cqg_user = str(os.environ.get("NTA_CQG_USERNAME") or "").strip()
    if is_mock_key(cqg_user, "cqg"):
        adapters.append(CqgMockAdapter())
    else:
        adapters.append(CqgLiveAdapter())

    # CME WS
    cme_token = str(os.environ.get("NTA_CME_WS_TOKEN") or os.environ.get("CME_WS_TOKEN") or "").strip()
    if is_mock_key(cme_token, "cme"):
        adapters.append(CmeWebsocketMockAdapter())
    else:
        adapters.append(CmeWebsocketReferenceAdapter())

    # TopstepX is owned by the chart provider's credential-scoped session
    # manager, or by the owner market-data gateway consumer adapter.  Starting
    # it here as a shadow adapter would create a second JWT and a second
    # Market SignalR socket with zero display subscriptions.
    if include_topstep:
        adapters.append(TopstepXProjectXAdapter())

    return adapters


def inject_fixture_trade(
    adapter: LiveMarketDataAdapter,
    *,
    exact_contract: str,
    price: float,
    volume: float = 1.0,
) -> Dict[str, Any]:
    """Test helper: push one canonical trade without a real vendor socket."""
    event = make_canonical_event(
        event_type="trade",
        provider=adapter.name,
        raw_symbol=databento_raw_symbol(exact_contract) if adapter.name.startswith("databento") else exact_contract,
        exact_contract=exact_contract.upper(),
        price=price,
        volume=volume,
        ts_event=_iso(),
        ts_provider=_iso(),
        quality={"fixture": True},
        data_plane="analytics",
    )
    adapter._emit(event)
    adapter._runtime_state = "LIVE"
    return event
