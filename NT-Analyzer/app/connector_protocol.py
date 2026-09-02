"""StratForge Connector Protocol v1.

Production Connectors authenticate with a device-owned ECDSA P-256 key.  A
short one-time enrollment code creates a *pending* installation; only a valid
signature over a one-time server nonce creates an online session.  Session
tokens are random bearer credentials stored only as SHA-256 hashes server-side.

The current encrypted file repository is the Development/bootstrap adapter.
Stage 6 replaces it with the same repository contract backed by PostgreSQL.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple
import urllib.parse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from . import connector_releases, runtime_env, secure_store, workspaces


PROTOCOL_VERSION = "1.0"
ENROLLMENT_TTL_SEC = 10 * 60
CHALLENGE_TTL_SEC = 2 * 60
CHALLENGE_REQUEST_SKEW_SEC = 2 * 60
SESSION_TTL_SEC = 15 * 60
HEARTBEAT_INTERVAL_SEC = 15
OFFLINE_AFTER_SEC = 45
# The 45-second offline lease intentionally tolerates a delayed heartbeat.  It
# is a transport/security lifetime, not permission for the UI to keep making a
# categorical "NinjaTrader is running" claim.  After one expected heartbeat
# plus a small delivery allowance the last observation is shown as grace/last
# known until a new signed heartbeat arrives.
HEARTBEAT_CONFIRMED_MAX_AGE_SEC = HEARTBEAT_INTERVAL_SEC + 5
COMMAND_DELIVERY_LEASE_SEC = 30
MAX_COMMAND_TTL_SEC = 5 * 60
RUNTIME_CATALOG_FRESH_SEC = 24 * 60 * 60
MAX_RUNTIME_CATALOG_STRATEGIES = 160
MAX_RUNTIME_CATALOG_TEMPLATES = 160
# Per page, not per catalog. Two independent limits bind a command result and
# both are real: `_safe_payload` refuses any list over 100 items and
# `_safe_result` refuses the whole result over MAX_COMMAND_RESULT_BYTES. The
# full catalog is delivered as several signed pages instead of being truncated,
# because dropping valid contracts is what made the backtest unusable.
MAX_RUNTIME_CATALOG_INSTRUMENTS_PER_PAGE = 80
MAX_RUNTIME_CATALOG_PAGES = 16
# A page targets this; the hard refusal is MAX_COMMAND_RESULT_BYTES.
RUNTIME_CATALOG_PAGE_TARGET_BYTES = 12 * 1024
# A command result above this is refused outright, not truncated: an oversized
# catalog snapshot is dropped and the server silently keeps its stale roots.
MAX_COMMAND_RESULT_BYTES = 16 * 1024
MAX_ACTIVE_INSTALLATIONS_PER_WORKSPACE = 10
MAX_ACTIVE_ENROLLMENTS_PER_USER = 5
MAX_MARKET_DATA_BARS = 64
MAX_MARKET_DATA_BYTES = 128 * 1024
MAX_SOURCE_SEQUENCE = (1 << 63) - 1
MAX_ACCOUNT_SNAPSHOT_ACCOUNTS = 20
MAX_ACCOUNT_SNAPSHOT_BYTES = 48 * 1024
ACCOUNT_SNAPSHOT_FRESH_SEC = 60

CAPABILITIES = frozenset({
    "telemetry",
    "accounts_read",
    "paper_commands",
    "live_read",
    "live_commands",
})
DEFAULT_CAPABILITIES = ("telemetry", "accounts_read")
TERMINAL_COMMAND_STATES = frozenset({
    "completed", "failed", "rejected", "expired", "cancelled",
})
_MAGIC = b"STRATFORGE-CONNECTORS-DPAPI-1\n"
CONNECTOR_STORE_VERSION = 2
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,31}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{7,127}$")
_MARKET_CONTRACT_RE = re.compile(r"^[A-Za-z0-9._ -]{1,40}$")
_MARKET_TIMEFRAME_RE = re.compile(
    r"^(?:(?:[1-9]|[1-9][0-9]|1[0-9]{2}|2[0-3][0-9]|240)m|"
    r"(?:[1-9]|1[0-9]|2[0-4])h|1D)$"
)
_ENROLLMENT_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
# How long an idle long-poll sleeps between re-reads. It bounds how quickly
# a command committed by *another* process is noticed; same-process work is
# signalled immediately. Every tick costs a shared-lock acquisition and a
# database round trip per polling device, so this trades a little
# cross-process latency for a lock that other readers can actually get.
IDLE_POLL_TICK_SEC = 2.0
# A status probe waits this long for the shared lock before giving up.
HEALTH_SUMMARY_LOCK_WAIT_SEC = 1.0
# How long a status snapshot may be reused. Reading the connector document is
# expensive on an authoritative deployment -- /api/bridge/connections measured
# over twelve seconds for four rows -- and a status panel does not need the
# document, only the counts. Serving a few-seconds-old answer, labelled with its
# age, is better than a probe that times out and shows nothing at all. Nothing
# that authorises a connector uses this path.
HEALTH_SNAPSHOT_TTL_SEC = 15.0
_HEALTH_SNAPSHOT: Dict[str, Any] = {}
_HEALTH_SNAPSHOT_LOCK = threading.Lock()
_HEALTH_REFRESHING: set = set()
_RUNTIME_ACCOUNT_CACHE: Dict[str, Dict[str, Any]] = {}
_RUNTIME_ACCOUNT_CACHE_LOCK = threading.Lock()
_LOCK = threading.RLock()
_COMMANDS_CHANGED = threading.Condition(_LOCK)


def _normalize_market_timeframe(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.lower() == "1d":
        return "1D"
    lowered = raw.lower()
    return lowered if _MARKET_TIMEFRAME_RE.fullmatch(lowered) else ""


class ConnectorProtocolError(RuntimeError):
    def __init__(self, message: str, status: int = 400, code: str = "connector_error"):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code)


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return runtime_env.data_path(
        "integrations", "connectors.dpapi", project_root=_root(),
    )


def _audit_path() -> Path:
    return runtime_env.data_path(
        "audit", "connector-protocol.jsonl", project_root=_root(),
    )


def _now_iso(epoch: Optional[float] = None) -> str:
    value = time.time() if epoch is None else float(epoch)
    return datetime.fromtimestamp(value, timezone.utc).isoformat(
        timespec="seconds",
    ).replace("+00:00", "Z")


def _default_doc() -> Dict[str, Any]:
    return {
        "schema_version": CONNECTOR_STORE_VERSION,
        "enrollments": [],
        "installations": [],
        "sessions": [],
        "commands": [],
        "results": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    }


def _legacy_user_id(value: Any) -> int:
    try:
        user_id = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return user_id if user_id > 0 else 0


def _user_uuid_for_legacy_id(user_id: Any) -> str:
    try:
        from . import account_auth
        return account_auth.user_uuid_for_legacy_id(user_id)
    except Exception:
        return ""


def _backfill_user_uuid(
    row: Dict[str, Any], legacy_key: str, uuid_key: str,
    *, resolved_users: Optional[Dict[int, str]] = None,
) -> bool:
    """Backfill one compatibility UUID without re-reading auth per history row.

    A Production Connector document can retain thousands of expired sessions.
    Resolving the same legacy owner id through the authoritative auth repository
    for every row turns one Connector read into thousands of PostgreSQL reads.
    Keep the existing mismatch-repair behaviour, but share one resolver result
    per legacy id for the duration of a single document migration.
    """
    legacy_id = _legacy_user_id(row.get(legacy_key))
    if legacy_id <= 0:
        return False
    if resolved_users is None:
        user_uuid = _user_uuid_for_legacy_id(legacy_id)
    elif legacy_id in resolved_users:
        user_uuid = resolved_users[legacy_id]
    else:
        user_uuid = _user_uuid_for_legacy_id(legacy_id)
        resolved_users[legacy_id] = user_uuid
    if not user_uuid or row.get(uuid_key) == user_uuid:
        return False
    row[uuid_key] = user_uuid
    return True


def _migrate_doc(doc: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    changed = False
    resolved_users: Dict[int, str] = {}
    for key in ("enrollments", "installations", "sessions", "commands", "results"):
        if not isinstance(doc.get(key), list):
            doc[key] = []
            changed = True
    # Stamp before anything reads an installation, so _assert_environment can
    # refuse an unstamped record instead of accepting it everywhere.
    changed = bool(_stamp_environments(doc)) or changed
    for row in doc["enrollments"]:
        if isinstance(row, dict):
            changed = _backfill_user_uuid(
                row, "created_by_user_id", "created_by_user_uuid",
                resolved_users=resolved_users,
            ) or changed
    installation_users: Dict[str, int] = {}
    for row in doc["installations"]:
        if not isinstance(row, dict):
            continue
        user_id = _legacy_user_id(row.get("user_id") or row.get("enrolled_by_user_id"))
        if user_id and _legacy_user_id(row.get("user_id")) != user_id:
            row["user_id"] = user_id
            changed = True
        changed = _backfill_user_uuid(
            row, "enrolled_by_user_id", "enrolled_by_user_uuid",
            resolved_users=resolved_users,
        ) or changed
        changed = _backfill_user_uuid(
            row, "user_id", "user_uuid", resolved_users=resolved_users,
        ) or changed
        installation_id = str(row.get("installation_id") or "")
        if installation_id and user_id:
            installation_users[installation_id] = user_id
    command_users: Dict[str, int] = {}
    for row in doc["commands"]:
        if not isinstance(row, dict):
            continue
        user_id = _legacy_user_id(row.get("user_id") or row.get("issued_by_user_id"))
        if user_id and _legacy_user_id(row.get("user_id")) != user_id:
            row["user_id"] = user_id
            changed = True
        changed = _backfill_user_uuid(
            row, "issued_by_user_id", "issued_by_user_uuid",
            resolved_users=resolved_users,
        ) or changed
        changed = _backfill_user_uuid(
            row, "user_id", "user_uuid", resolved_users=resolved_users,
        ) or changed
        command_id = str(row.get("command_id") or "")
        if command_id and user_id:
            command_users[command_id] = user_id
    for row in doc["sessions"]:
        if not isinstance(row, dict):
            continue
        user_id = _legacy_user_id(row.get("user_id")) or installation_users.get(
            str(row.get("installation_id") or ""), 0,
        )
        if user_id and _legacy_user_id(row.get("user_id")) != user_id:
            row["user_id"] = user_id
            changed = True
        changed = _backfill_user_uuid(
            row, "user_id", "user_uuid", resolved_users=resolved_users,
        ) or changed
    for row in doc["results"]:
        if not isinstance(row, dict):
            continue
        user_id = _legacy_user_id(row.get("user_id")) or command_users.get(
            str(row.get("command_id") or ""), 0,
        )
        if user_id and _legacy_user_id(row.get("user_id")) != user_id:
            row["user_id"] = user_id
            changed = True
        changed = _backfill_user_uuid(
            row, "user_id", "user_uuid", resolved_users=resolved_users,
        ) or changed
    identity_schema = doc.get("identity_schema") if isinstance(doc.get("identity_schema"), dict) else {}
    expected_schema = dict(identity_schema)
    expected_schema.update({
        "stage": "dual_write",
        "canonical_key": "user_uuid",
        "legacy_key": "user_id",
    })
    if expected_schema != identity_schema:
        expected_schema.setdefault("migrated_at_utc", _now_iso())
        doc["identity_schema"] = expected_schema
        changed = True
    try:
        version = int(doc.get("schema_version") or 1)
    except (TypeError, ValueError):
        version = 1
    if version < CONNECTOR_STORE_VERSION:
        doc["schema_version"] = CONNECTOR_STORE_VERSION
        changed = True
    return doc, changed


def _read_doc() -> Dict[str, Any]:
    if runtime_env.is_server_environment() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            doc = storage_router.read_document("connectors", _default_doc())
        except StorageError as exc:
            raise ConnectorProtocolError(
                f"Production Connector repository unavailable ({exc.code}): {exc}",
                503, exc.code,
            ) from None
        if not isinstance(doc, dict):
            raise ConnectorProtocolError(
                "Production Connector repository returned invalid data.",
                500, "store_corrupt",
            )
        for name in ("enrollments", "installations", "sessions", "commands", "results"):
            if not isinstance(doc.get(name), list):
                doc[name] = []
        return _migrate_doc(doc)[0]
    path = _store_path()
    if not path.is_file():
        return _default_doc()
    try:
        raw = path.read_bytes()
        if not raw.startswith(_MAGIC):
            raise ConnectorProtocolError(
                "Неизвестный формат Connector store.", 500, "store_format",
            )
        encrypted = base64.b64decode(raw[len(_MAGIC):], validate=True)
        doc = json.loads(secure_store._unprotect(encrypted).decode("utf-8"))
    except ConnectorProtocolError:
        raise
    except secure_store.SecureStoreError as exc:
        raise ConnectorProtocolError(
            str(exc), 503, "store_unavailable",
        ) from None
    except Exception as exc:
        raise ConnectorProtocolError(
            f"Connector store повреждён: {type(exc).__name__}.",
            500,
            "store_corrupt",
        ) from None
    if not isinstance(doc, dict):
        raise ConnectorProtocolError(
            "Connector store повреждён.", 500, "store_corrupt",
        )
    for name in ("enrollments", "installations", "sessions", "commands", "results"):
        if not isinstance(doc.get(name), list):
            doc[name] = []
    doc, changed = _migrate_doc(doc)
    if changed:
        _write_doc(doc)
    return doc


def _write_doc(doc: Dict[str, Any]) -> None:
    doc, _ = _migrate_doc(doc)
    if runtime_env.is_server_environment() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.write_document("connectors", doc)
            return
        except StorageError as exc:
            raise ConnectorProtocolError(
                f"Production Connector repository write denied ({exc.code}): {exc}",
                503, exc.code,
            ) from None
    if not secure_store.available():
        raise ConnectorProtocolError(
            "Encrypted Connector repository недоступен.",
            503,
            "store_unavailable",
        )
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(
        doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    try:
        protected = secure_store._protect(plaintext)
    except secure_store.SecureStoreError as exc:
        raise ConnectorProtocolError(
            str(exc), 503, "store_unavailable",
        ) from None
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(_MAGIC + base64.b64encode(protected))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise ConnectorProtocolError(
            f"Connector store write failed: {type(exc).__name__}.",
            500,
            "store_write_failed",
        ) from None


def _audit(event: str, **values: Any) -> None:
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.append_audit("connector_protocol", event, values)
            return
        except StorageError as exc:
            raise ConnectorProtocolError(
                f"Production Connector audit unavailable ({exc.code}): {exc}",
                503, exc.code,
            ) from None
    row = {
        "timestamp_utc": _now_iso(),
        "source": "connector_protocol",
        "event": str(event),
        **values,
    }
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ) + "\n")


def audit_refusal(route: str, code: str, status: int,
                  installation_id: str = "", detail: str = "") -> None:
    """Record a refused connector request.

    Only successful steps were ever audited, so a connector that reached the
    server and was turned away left no trace at all: the installation kept its
    old last_hello_utc and looked identical to a device that never called.
    Distinguishing "not calling" from "calling and refused" is the whole
    difference when a connector goes quiet, so refusals are recorded too --
    route, error code and status only, never a body or a credential.
    """
    try:
        _audit(
            "request_refused",
            route=str(route or "")[:120],
            code=str(code or "")[:80],
            status=int(status or 0),
            installation_id=str(installation_id or "")[:64],
            # The operator-facing message, which for a storage refusal names
            # the constraint that denied the write. Bounded, and never a body.
            detail=str(detail or "")[:300],
        )
    except Exception:
        # Observability must never turn a refusal into a server error.
        pass


def recent_audit(limit: int = 50) -> list:
    """Recent connector-protocol audit rows, redacted to status fields."""
    allowed = {
        "event", "event_type", "occurred_at", "timestamp_utc", "route", "code",
        "status", "installation_id", "workspace_id", "session_id",
        "enrollment_id", "connector_version", "update_state", "update_reason",
        "public_key_fingerprint", "source", "detail",
    }
    rows: list = []
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        try:
            raw = storage_router.read_audit("connector_protocol", limit=limit)
        except Exception:
            return []
        for row in raw:
            merged = dict(row.get("payload") or row.get("document") or {})
            merged.setdefault("event", row.get("event_type"))
            merged.setdefault("occurred_at", str(row.get("occurred_at") or ""))
            rows.append({k: v for k, v in merged.items() if k in allowed})
        return rows
    path = _audit_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-max(1, int(limit)):]
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        rows.append({k: v for k, v in row.items() if k in allowed})
    return rows


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: Any, *, expected: Optional[int] = None) -> bytes:
    text = str(value or "").strip()
    if not text or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ConnectorProtocolError(
            "Некорректное base64url значение.", 400, "invalid_encoding",
        )
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise ConnectorProtocolError(
            "Некорректное base64url значение.", 400, "invalid_encoding",
        ) from exc
    if expected is not None and len(raw) != expected:
        raise ConnectorProtocolError(
            "Некорректная длина cryptographic value.", 400, "invalid_key",
        )
    return raw


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _public_key(jwk: Any) -> Tuple[Dict[str, str], Any, str]:
    if not isinstance(jwk, Mapping):
        raise ConnectorProtocolError(
            "public_key должен быть JWK object.", 400, "invalid_key",
        )
    if set(jwk) - {"kty", "crv", "x", "y"}:
        raise ConnectorProtocolError(
            "public_key содержит неизвестные поля.", 400, "invalid_key",
        )
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ConnectorProtocolError(
            "Поддерживается только EC P-256 device key.", 400, "invalid_key",
        )
    x = _b64url_decode(jwk.get("x"), expected=32)
    y = _b64url_decode(jwk.get("y"), expected=32)
    point = b"\x04" + x + y
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError as exc:
        raise ConnectorProtocolError(
            "Device public key не находится на P-256 curve.", 400, "invalid_key",
        ) from exc
    normalized = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url_encode(x),
        "y": _b64url_encode(y),
    }
    fingerprint = "SHA256:" + hashlib.sha256(point).hexdigest()
    return normalized, key, fingerprint


def public_key_fingerprint(jwk: Any) -> str:
    return _public_key(jwk)[2]


def hello_signing_message(payload: Mapping[str, Any]) -> bytes:
    fields = (
        "protocol_version",
        "connector_version",
        "nt_version",
        "installation_id",
        "workspace_id",
        "nonce",
        "public_key_fingerprint",
        "ninja_instance_id",
    )
    return _canonical_json({name: str(payload.get(name) or "") for name in fields})


def challenge_signing_message(payload: Mapping[str, Any]) -> bytes:
    """Return the canonical proof-of-possession message for nonce rotation."""
    fields = (
        "protocol_version",
        "installation_id",
        "public_key_fingerprint",
        "client_nonce",
        "requested_at",
    )
    return _canonical_json({name: str(payload.get(name) or "") for name in fields})


def _verify_signature(jwk: Mapping[str, Any], signature: Any, message: bytes) -> None:
    _, key, _ = _public_key(jwk)
    raw = _b64url_decode(signature)
    if len(raw) == 64:
        r = int.from_bytes(raw[:32], "big")
        s = int.from_bytes(raw[32:], "big")
        raw = encode_dss_signature(r, s)
    try:
        key.verify(raw, message, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError) as exc:
        raise ConnectorProtocolError(
            "Device signature verification failed.", 401, "invalid_signature",
        ) from exc


def _clean_label(value: Any, fallback: str = "NinjaTrader") -> str:
    text = " ".join(str(value or "").strip().split()) or fallback
    if not 1 <= len(text) <= 120 or any(ord(ch) < 32 for ch in text):
        raise ConnectorProtocolError(
            "Некорректная machine label.", 400, "invalid_label",
        )
    return text


def _clean_version(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not _VERSION_RE.fullmatch(text):
        raise ConnectorProtocolError(
            f"{name} имеет некорректный формат.", 400, "invalid_version",
        )
    return text


def _safe_id(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ConnectorProtocolError(
            f"{name} имеет некорректный формат.", 400, "invalid_id",
        )
    return text


def _normalize_capabilities(values: Optional[Iterable[Any]]) -> list[str]:
    requested = [str(value or "").strip() for value in (values or [])]
    if not requested:
        requested = list(DEFAULT_CAPABILITIES)
    unknown = sorted({value for value in requested if value not in CAPABILITIES})
    if unknown:
        raise ConnectorProtocolError(
            "Неизвестная Connector capability.", 400, "invalid_capability",
        )
    normalized = list(dict.fromkeys(requested))
    if "live_commands" in normalized and not runtime_env.allow_live_orders():
        raise ConnectorProtocolError(
            "Live Connector commands выключены release gate.",
            403,
            "live_commands_disabled",
        )
    return normalized


def _new_enrollment_code() -> str:
    compact = "".join(
        secrets.choice(_ENROLLMENT_ALPHABET) for _ in range(16)
    )
    return "-".join(compact[index:index + 4] for index in range(0, 16, 4))


def _enrollment_hash(code: Any) -> str:
    value = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())
    if len(value) != 16 or any(ch not in _ENROLLMENT_ALPHABET for ch in value):
        raise ConnectorProtocolError(
            "Enrollment code имеет некорректный формат.",
            400,
            "invalid_enrollment_code",
        )
    return hashlib.sha256(
        ("stratforge-connector-enrollment-v1:" + value).encode("ascii"),
    ).hexdigest()


def _find_installation(doc: Dict[str, Any], installation_id: str) -> Dict[str, Any]:
    row = next((item for item in doc["installations"] if hmac.compare_digest(
        str(item.get("installation_id") or ""), installation_id,
    )), None)
    if row is None:
        raise ConnectorProtocolError(
            "Connector installation не найдена.", 404, "installation_not_found",
        )
    return row


def _store_proves_environment(doc: Mapping[str, Any]) -> str:
    """The environment this store demonstrably belongs to, or "" if ambiguous.

    Each environment keeps a physically separate Connector repository:
    Production in the Production database, Canary in the Canary database,
    Development in a local file under its own data root. A record present in
    one of them was therefore enrolled against that one -- presence is the
    evidence.

    That inference holds only while the store is internally consistent. If any
    record here is stamped for a *different* environment, then records from two
    environments have been mixed and presence proves nothing at all, so no
    stamp is issued and the ambiguous records are left alone for a human to
    resolve.
    """
    current = runtime_env.deployment_environment()
    for key in ("installations", "enrollments", "sessions", "commands"):
        for row in doc.get(key) or []:
            if not isinstance(row, dict):
                continue
            stamped = str(row.get("deployment_environment") or "").strip()
            if stamped and stamped != current:
                return ""
    return current


def _stamp_environments(doc: Dict[str, Any]) -> int:
    """Stamp unstamped installations, but only where the store proves it.

    Records enrolled before stamping existed carry no environment, and
    _assert_environment refuses those -- correctly, since an unstamped record
    would otherwise be usable from every environment at once. This closes that
    gap for the records whose origin is provable and deliberately leaves the
    rest untouched: guessing at an ambiguous record is exactly how a Connector
    ends up bound to the wrong environment.

    ``environment_source`` records why the value was chosen, so a later reader
    can tell a proven stamp from one written at enrollment.

    Returns how many were stamped, so the caller can decide whether to write.
    """
    proven = _store_proves_environment(doc)
    if not proven:
        return 0
    stamped = 0
    for row in doc.get("installations") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("deployment_environment") or "").strip():
            continue
        row["deployment_environment"] = proven
        row["environment_source"] = "store_origin"
        stamped += 1
    return stamped


def _assert_environment(installation: Mapping[str, Any]) -> None:
    """Fail-closed: an installation may only be used in the environment that
    enrolled it. A Canary Connector must never be driven from Production, and
    vice-versa.

    An unstamped record is refused rather than accepted. The previous early
    return made such a record valid in *every* environment -- the exact
    fail-open this check exists to close -- and on live Production five
    installations were still unstamped, so the clause was not theoretical.
    _stamp_environments fills them in from the store they live in.
    """
    stamped = str(installation.get("deployment_environment") or "").strip()
    if not stamped or stamped != runtime_env.deployment_environment():
        raise ConnectorProtocolError(
            "Connector installation принадлежит другому окружению.",
            403,
            "connector_environment_mismatch",
        )


def _public_installation(row: Mapping[str, Any]) -> Dict[str, Any]:
    public = {name: copy.deepcopy(row.get(name)) for name in (
        "installation_id",
        "connection_id",
        "workspace_id",
        "user_uuid",
        "machine_label",
        "status",
        "capabilities",
        "public_key_fingerprint",
        "connector_version",
        "nt_version",
        "ninja_instance_id",
        "created_at_utc",
        "last_hello_utc",
        "last_heartbeat_utc",
        "revoked_at_utc",
        "update_state",
        "update_reason",
        "release_channel",
        "account_labels",
        # An installation belongs to exactly one environment and is refused
        # anywhere else. Without this the panel can only say "offline", which
        # is what made a Canary connector pointed at Production look like a
        # dead device rather than a rejected one.
        "deployment_environment",
        "update_policy",
    )}
    # A staged update that only needs NinjaTrader restarted is a distinct
    # state from "an update exists": it is the one the operator can act on.
    public["restart_required"] = bool(
        str(row.get("update_state") or "") == "update_available"
        and str(row.get("update_policy") or "") == "safe_restart"
    )
    public["environment_mismatch"] = bool(
        str(row.get("deployment_environment") or "")
        and str(row.get("deployment_environment") or "")
        != runtime_env.deployment_environment()
    )
    now = time.time()
    try:
        heartbeat_at = float(row.get("last_heartbeat_at") or 0)
    except (TypeError, ValueError):
        heartbeat_at = 0
    snapshot = row.get("account_snapshot")
    if not isinstance(snapshot, Mapping):
        snapshot = {}
    try:
        snapshot_at = float(snapshot.get("received_at") or 0)
    except (TypeError, ValueError):
        snapshot_at = 0
    public["heartbeat_online"] = bool(
        heartbeat_at and -5 <= now - heartbeat_at <= OFFLINE_AFTER_SEC
        and str(row.get("status") or "") == "online"
    )
    public["account_snapshot_at_utc"] = str(snapshot.get("received_at_utc") or "")
    public["account_snapshot_accounts"] = len(snapshot.get("accounts") or [])
    public["functional_online"] = bool(
        public["heartbeat_online"] and snapshot_at
        and -5 <= now - snapshot_at <= ACCOUNT_SNAPSHOT_FRESH_SEC
        and public["account_snapshot_accounts"]
    )
    return public


def _apply_release_policy(installation: Dict[str, Any]) -> Dict[str, Any]:
    decision = connector_releases.resolve_update(installation)
    installation["update_state"] = str(decision.get("state") or "blocked")
    installation["update_reason"] = str(
        decision.get("reason") or "release_policy_error"
    )
    installation["release_channel"] = str(decision.get("channel") or "")
    installation["update_policy"] = str(
        (decision.get("offer") or {}).get("apply_policy") or ""
    )
    return decision


def _refresh_states(doc: Dict[str, Any], now: float) -> bool:
    changed = False
    for enrollment in doc["enrollments"]:
        if enrollment.get("status") == "created" and float(
            enrollment.get("expires_at") or 0,
        ) <= now:
            enrollment["status"] = "expired"
            changed = True
    for session in doc["sessions"]:
        if session.get("status") == "active" and float(
            session.get("expires_at") or 0,
        ) <= now:
            session["status"] = "expired"
            session["ended_at_utc"] = _now_iso(now)
            changed = True
    for command in doc["commands"]:
        if command.get("status") not in TERMINAL_COMMAND_STATES and float(
            command.get("expires_at") or 0,
        ) <= now:
            command["status"] = "expired"
            command["finished_at_utc"] = _now_iso(now)
            changed = True
    active_sessions = {
        str(row.get("installation_id") or "")
        for row in doc["sessions"]
        if row.get("status") == "active" and float(row.get("expires_at") or 0) > now
    }
    for installation in doc["installations"]:
        if installation.get("status") != "online":
            continue
        try:
            last = float(installation.get("last_heartbeat_at") or 0)
        except (TypeError, ValueError):
            last = 0
        if (
            str(installation.get("installation_id") or "") not in active_sessions
            or now - last > OFFLINE_AFTER_SEC
        ):
            installation["status"] = "offline"
            changed = True
    return changed


def start_enrollment(
    user_id: Any,
    *,
    workspace_id: str = "",
    machine_label: str = "",
    capabilities: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    user = int(user_id or 0)
    workspace = workspaces.require_workspace_writer(user, workspace_id=workspace_id)
    workspace_value = str(workspace.get("workspace_id") or "")
    grants = _normalize_capabilities(capabilities)
    now = time.time()
    code = _new_enrollment_code()
    with _LOCK:
        doc = _read_doc()
        _refresh_states(doc, now)
        active = [
            row for row in doc["enrollments"]
            if int(row.get("created_by_user_id") or 0) == user
            and row.get("status") == "created"
            and float(row.get("expires_at") or 0) > now
        ]
        if len(active) >= MAX_ACTIVE_ENROLLMENTS_PER_USER:
            raise ConnectorProtocolError(
                "Слишком много активных enrollment codes.",
                429,
                "enrollment_limit",
            )
        enrollment = {
            "enrollment_id": "enr_" + secrets.token_urlsafe(12),
            "code_hash": _enrollment_hash(code),
            "workspace_id": workspace_value,
            "created_by_user_id": user,
            "machine_label": _clean_label(machine_label, "Мой NinjaTrader"),
            "capabilities": grants,
            "status": "created",
            "created_at_utc": _now_iso(now),
            "expires_at": now + ENROLLMENT_TTL_SEC,
        }
        doc["enrollments"].append(enrollment)
        _write_doc(doc)
    _audit(
        "enrollment_started",
        user_id=user,
        workspace_id=workspace_value,
        enrollment_id=enrollment["enrollment_id"],
    )
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "enrollment_id": enrollment["enrollment_id"],
        "code": code,
        "expires_in_sec": ENROLLMENT_TTL_SEC,
        "pairing_uri": "stratforge-connector://enroll?" + urllib.parse.urlencode({
            "code": code,
            "protocol": PROTOCOL_VERSION,
        }),
        "workspace": workspace,
        "capabilities": grants,
        "state": "created",
    }


def _issue_challenge(row: Dict[str, Any], now: float) -> str:
    nonce = _b64url_encode(secrets.token_bytes(32))
    row["challenge_nonce_hash"] = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    row["challenge_expires_at"] = now + CHALLENGE_TTL_SEC
    row["challenge_used_at_utc"] = ""
    return nonce


def enroll_device(payload: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = {
        "code", "public_key", "connector_version", "nt_version",
        "machine_label", "ninja_instance_id", "extensions",
    }
    if not isinstance(payload, Mapping) or set(payload) - allowed:
        raise ConnectorProtocolError(
            "Enrollment request содержит неизвестные поля.",
            400,
            "invalid_enrollment_request",
        )
    digest = _enrollment_hash(payload.get("code"))
    public_jwk, _, fingerprint = _public_key(payload.get("public_key"))
    connector_version = _clean_version(payload.get("connector_version"), "connector_version")
    nt_version = _clean_version(payload.get("nt_version"), "nt_version")
    ninja_instance_id = _safe_id(
        payload.get("ninja_instance_id") or "nt_unknown_instance",
        "ninja_instance_id",
    )
    now = time.time()
    with _LOCK:
        doc = _read_doc()
        _refresh_states(doc, now)
        enrollment = next((
            row for row in doc["enrollments"]
            if row.get("status") == "created"
            and float(row.get("expires_at") or 0) > now
            and hmac.compare_digest(str(row.get("code_hash") or ""), digest)
        ), None)
        if enrollment is None:
            raise ConnectorProtocolError(
                "Enrollment code истёк, уже использован или не найден.",
                404,
                "enrollment_unavailable",
            )
        workspace_id = str(enrollment.get("workspace_id") or "")
        active_count = sum(
            1 for row in doc["installations"]
            if str(row.get("workspace_id") or "") == workspace_id
            and row.get("status") != "revoked"
        )
        if active_count >= MAX_ACTIVE_INSTALLATIONS_PER_WORKSPACE:
            raise ConnectorProtocolError(
                "Достигнут лимит Connector installations для workspace.",
                409,
                "installation_limit",
            )
        if any(
            row.get("status") != "revoked"
            and hmac.compare_digest(
                str(row.get("public_key_fingerprint") or ""), fingerprint,
            )
            for row in doc["installations"]
        ):
            raise ConnectorProtocolError(
                "Этот device key уже зарегистрирован.",
                409,
                "device_key_exists",
            )
        installation = {
            "installation_id": "inst_" + secrets.token_urlsafe(18),
            "connection_id": "conn_" + secrets.token_urlsafe(14),
            "workspace_id": workspace_id,
            "enrolled_by_user_id": int(enrollment.get("created_by_user_id") or 0),
            "machine_label": _clean_label(
                payload.get("machine_label") or enrollment.get("machine_label"),
                "NinjaTrader",
            ),
            "status": "pending",
            "capabilities": list(enrollment.get("capabilities") or DEFAULT_CAPABILITIES),
            "public_key": public_jwk,
            "public_key_fingerprint": fingerprint,
            "connector_version": connector_version,
            "protocol_version": PROTOCOL_VERSION,
            "deployment_environment": runtime_env.deployment_environment(),
            "nt_version": nt_version,
            "ninja_instance_id": ninja_instance_id,
            "created_at_utc": _now_iso(now),
            "last_hello_utc": "",
            "last_heartbeat_utc": "",
            "last_heartbeat_at": 0,
            "revoked_at_utc": "",
            "update_state": "compatible",
            "update_reason": "pending_first_hello",
            "release_channel": "",
            "account_labels": [],
        }
        nonce = _issue_challenge(installation, now)
        doc["installations"].append(installation)
        enrollment["status"] = "consumed"
        enrollment["consumed_at_utc"] = _now_iso(now)
        enrollment["installation_id"] = installation["installation_id"]
        _write_doc(doc)
    _audit(
        "device_enrolled_pending",
        workspace_id=workspace_id,
        installation_id=installation["installation_id"],
        public_key_fingerprint=fingerprint,
    )
    return {
        "ok": True,
        "state": "pending",
        "protocol_version": PROTOCOL_VERSION,
        "installation_id": installation["installation_id"],
        "connection_id": installation["connection_id"],
        "workspace_id": workspace_id,
        "public_key_fingerprint": fingerprint,
        "nonce": nonce,
        "challenge_expires_in_sec": CHALLENGE_TTL_SEC,
    }


def issue_challenge(payload: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = {
        "protocol_version", "installation_id", "public_key_fingerprint",
        "client_nonce", "requested_at", "signature", "extensions",
    }
    required = allowed - {"extensions"}
    if (
        not isinstance(payload, Mapping)
        or set(payload) - allowed
        or any(name not in payload for name in required)
    ):
        raise ConnectorProtocolError(
            "Challenge contract incomplete or contains unknown fields.",
            400,
            "invalid_challenge",
        )
    if str(payload.get("protocol_version") or "") != PROTOCOL_VERSION:
        raise ConnectorProtocolError(
            "Unsupported Connector protocol version.",
            426,
            "protocol_upgrade_required",
        )
    target = _safe_id(payload.get("installation_id"), "installation_id")
    fingerprint = str(payload.get("public_key_fingerprint") or "").strip()
    client_nonce = str(payload.get("client_nonce") or "").strip()
    _b64url_decode(client_nonce, expected=32)
    requested_at = str(payload.get("requested_at") or "").strip()
    try:
        parsed_at = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        if parsed_at.tzinfo is None:
            raise ValueError("timezone required")
        requested_epoch = parsed_at.timestamp()
    except (TypeError, ValueError, OverflowError):
        raise ConnectorProtocolError(
            "Challenge requested_at must be an ISO-8601 UTC timestamp.",
            400,
            "invalid_challenge_time",
        ) from None
    now = time.time()
    if abs(now - requested_epoch) > CHALLENGE_REQUEST_SKEW_SEC:
        raise ConnectorProtocolError(
            "Challenge request timestamp is outside the accepted window.",
            401,
            "stale_challenge_request",
        )
    with _LOCK:
        doc = _read_doc()
        _refresh_states(doc, now)
        installation = _find_installation(doc, target)
        if installation.get("status") == "revoked":
            raise ConnectorProtocolError(
                "Connector installation отозвана.", 403, "installation_revoked",
            )
        _assert_environment(installation)
        if not hmac.compare_digest(
            str(installation.get("public_key_fingerprint") or ""), fingerprint,
        ):
            raise ConnectorProtocolError(
                "Challenge key fingerprint mismatch.", 401, "key_mismatch",
            )
        client_nonce_hash = hashlib.sha256(client_nonce.encode("ascii")).hexdigest()
        if hmac.compare_digest(
            str(installation.get("last_challenge_client_nonce_hash") or ""),
            client_nonce_hash,
        ):
            raise ConnectorProtocolError(
                "Challenge proof was already used.", 409, "challenge_replay",
            )
        _verify_signature(
            installation.get("public_key") or {},
            payload.get("signature"),
            challenge_signing_message(payload),
        )
        installation["last_challenge_client_nonce_hash"] = client_nonce_hash
        installation["last_challenge_requested_at_utc"] = _now_iso(now)
        nonce = _issue_challenge(installation, now)
        _write_doc(doc)
    _audit(
        "challenge_issued",
        workspace_id=installation["workspace_id"],
        installation_id=target,
    )
    return {
        "ok": True,
        "installation_id": target,
        "workspace_id": installation["workspace_id"],
        "protocol_version": PROTOCOL_VERSION,
        "nonce": nonce,
        "challenge_expires_in_sec": CHALLENGE_TTL_SEC,
        "server_time": _now_iso(now),
    }


def _next_missing_catalog_page(installation: Mapping[str, Any]) -> int:
    staging = installation.get("runtime_catalog_staging")
    if not isinstance(staging, Mapping):
        return 0
    pages = staging.get("pages") or {}
    for index in range(int(staging.get("page_count") or 1)):
        if str(index) not in pages:
            return index
    return 0


def _queue_runtime_catalog_snapshot(
    doc: Dict[str, Any],
    installation: Mapping[str, Any],
    session: Mapping[str, Any],
    now: float,
    page_index: int = 0,
) -> Dict[str, Any]:
    """Queue one bounded catalog snapshot for this signed session.

    The device already has a telemetry command channel and the server already
    has a signed command/result lifecycle. Reusing it keeps Production as the
    sole execution authority and avoids a second catalog transport. A new
    signed hello gets one request; ordinary heartbeats do not create churn.
    """
    # page_index is omitted for the first page so the wire stays byte-identical
    # for every Connector that predates paging.
    payload: Dict[str, Any] = {"command": "snapshot_runtime"}
    if int(page_index) > 0:
        payload["page_index"] = int(page_index)
    installation_id = str(installation.get("installation_id") or "")
    workspace_id = str(installation.get("workspace_id") or "")
    connection_id = str(installation.get("connection_id") or "")
    session_id = str(session.get("session_id") or "")
    key = f"runtime-catalog:{installation_id}:{session_id}:{int(page_index)}"
    clean_payload = _safe_payload(payload)
    _validate_command_capability("telemetry", clean_payload)
    envelope_hash = hashlib.sha256(_canonical_json({
        "workspace_id": workspace_id,
        "connection_id": connection_id,
        "capability": "telemetry",
        "payload": clean_payload,
    })).hexdigest()
    command = {
        "command_id": "cmd_" + secrets.token_urlsafe(18),
        "workspace_id": workspace_id,
        "connection_id": connection_id,
        "installation_id": installation_id,
        "capability": "telemetry",
        "idempotency_key": key,
        "issued_by_user_id": _legacy_user_id(installation.get("user_id")),
        "issued_at": now,
        "issued_at_utc": _now_iso(now),
        "expires_at": now + MAX_COMMAND_TTL_SEC,
        "expires_at_utc": _now_iso(now + MAX_COMMAND_TTL_SEC),
        "payload": clean_payload,
        "envelope_hash": envelope_hash,
        "status": "queued",
        "delivery_attempts": 0,
        "delivery_lease_until": 0,
        "finished_at_utc": "",
    }
    doc["commands"].append(command)
    return command


# The bounded runtime catalog landed in 0.4.2-dev.17.
_RUNTIME_CATALOG_BASE = (0, 4, 2)
_RUNTIME_CATALOG_DEV = 17


def _connector_supports_runtime_catalog(version: Any) -> bool:
    """True when this Connector can answer a runtime catalog snapshot.

    The base version decides first. Reading only the ``-dev.N`` counter treated
    0.4.3-dev.1 as older than 0.4.2-dev.17 and silently withheld the catalog
    command from a strictly newer Connector, which left the server on bare
    roots with no way to recover.
    """
    text = str(version or "").strip().lower()
    dev = re.search(r"-dev\.(\d+)$", text)
    dev_number = int(dev.group(1)) if dev else None
    base = text.split("-", 1)[0]
    try:
        parts = tuple(int(item) for item in base.split("."))
    except (TypeError, ValueError):
        return False
    if parts > _RUNTIME_CATALOG_BASE:
        return True
    if parts < _RUNTIME_CATALOG_BASE:
        return False
    # Exactly the base version: a prerelease must be at or past the dev build
    # that introduced it; the final release always has it.
    return dev_number is None or dev_number >= _RUNTIME_CATALOG_DEV


def signed_hello(payload: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = {
        "protocol_version", "connector_version", "nt_version",
        "installation_id", "workspace_id", "nonce",
        "public_key_fingerprint", "ninja_instance_id", "signature", "extensions",
    }
    required = allowed - {"extensions"}
    if (
        not isinstance(payload, Mapping)
        or set(payload) - allowed
        or any(name not in payload for name in required)
    ):
        raise ConnectorProtocolError(
            "Hello contract incomplete or contains unknown fields.",
            400,
            "invalid_hello",
        )
    if str(payload.get("protocol_version") or "") != PROTOCOL_VERSION:
        raise ConnectorProtocolError(
            "Unsupported Connector protocol version.",
            426,
            "protocol_upgrade_required",
        )
    connector_version = _clean_version(payload.get("connector_version"), "connector_version")
    nt_version = _clean_version(payload.get("nt_version"), "nt_version")
    installation_id = _safe_id(payload.get("installation_id"), "installation_id")
    ninja_instance_id = _safe_id(payload.get("ninja_instance_id"), "ninja_instance_id")
    nonce = str(payload.get("nonce") or "").strip()
    _b64url_decode(nonce, expected=32)
    now = time.time()
    catalog_command: Optional[Dict[str, Any]] = None
    with _COMMANDS_CHANGED:
        doc = _read_doc()
        _refresh_states(doc, now)
        installation = _find_installation(doc, installation_id)
        if installation.get("status") == "revoked":
            raise ConnectorProtocolError(
                "Connector installation отозвана.", 403, "installation_revoked",
            )
        _assert_environment(installation)
        if not hmac.compare_digest(
            str(installation.get("workspace_id") or ""),
            str(payload.get("workspace_id") or ""),
        ):
            raise ConnectorProtocolError(
                "Hello workspace mismatch.", 403, "workspace_mismatch",
            )
        if not hmac.compare_digest(
            str(installation.get("public_key_fingerprint") or ""),
            str(payload.get("public_key_fingerprint") or ""),
        ):
            raise ConnectorProtocolError(
                "Hello key fingerprint mismatch.", 401, "key_mismatch",
            )
        expected_nonce = str(installation.get("challenge_nonce_hash") or "")
        if (
            not expected_nonce
            or installation.get("challenge_used_at_utc")
            or float(installation.get("challenge_expires_at") or 0) <= now
            or not hmac.compare_digest(
                expected_nonce, hashlib.sha256(nonce.encode("ascii")).hexdigest(),
            )
        ):
            raise ConnectorProtocolError(
                "Hello nonce истёк, использован или не совпадает.",
                401,
                "invalid_nonce",
            )
        _verify_signature(
            installation.get("public_key") or {},
            payload.get("signature"),
            hello_signing_message(payload),
        )
        for session in doc["sessions"]:
            if (
                session.get("status") == "active"
                and str(session.get("installation_id") or "") == installation_id
            ):
                session["status"] = "superseded"
                session["ended_at_utc"] = _now_iso(now)
        raw_token = "sfc_v1_" + secrets.token_urlsafe(32)
        session = {
            "session_id": "csess_" + secrets.token_urlsafe(16),
            "installation_id": installation_id,
            "workspace_id": installation["workspace_id"],
            "token_hash": hashlib.sha256(raw_token.encode("ascii")).hexdigest(),
            "status": "active",
            "created_at_utc": _now_iso(now),
            "expires_at": now + SESSION_TTL_SEC,
            "last_sequence": 0,
            "last_seen_utc": _now_iso(now),
        }
        doc["sessions"].append(session)
        installation.update({
            "status": "online",
            "connector_version": connector_version,
            "nt_version": nt_version,
            "ninja_instance_id": ninja_instance_id,
            "deployment_environment": runtime_env.deployment_environment(),
            "last_hello_utc": _now_iso(now),
            "last_heartbeat_utc": _now_iso(now),
            "last_heartbeat_at": now,
            "challenge_used_at_utc": _now_iso(now),
        })
        release_decision = _apply_release_policy(installation)
        if (
            "telemetry" in set(installation.get("capabilities") or [])
            and _connector_supports_runtime_catalog(connector_version)
        ):
            catalog_command = _queue_runtime_catalog_snapshot(
                doc, installation, session, now,
            )
        _write_doc(doc)
        if catalog_command:
            _COMMANDS_CHANGED.notify_all()
    _audit(
        "signed_hello_accepted",
        workspace_id=installation["workspace_id"],
        installation_id=installation_id,
        session_id=session["session_id"],
    )
    _audit(
        "release_policy_evaluated",
        workspace_id=installation["workspace_id"],
        installation_id=installation_id,
        connector_version=connector_version,
        update_state=release_decision["state"],
        update_reason=release_decision["reason"],
        release_channel=release_decision["channel"],
    )
    if catalog_command:
        _audit(
            "command_queued",
            user_id=installation.get("user_id"),
            workspace_id=installation["workspace_id"],
            installation_id=installation_id,
            command_id=catalog_command["command_id"],
            capability="telemetry",
        )
    return {
        "ok": True,
        "state": "online",
        "protocol_version": PROTOCOL_VERSION,
        "session_id": session["session_id"],
        "session_token": raw_token,
        "expires_at": _now_iso(session["expires_at"]),
        "heartbeat_interval_sec": HEARTBEAT_INTERVAL_SEC,
        "server_time": _now_iso(now),
        "workspace_id": installation["workspace_id"],
        "connection_id": installation["connection_id"],
        "allowed_capabilities": list(installation["capabilities"]),
        "update_state": release_decision["state"],
        "update_reason": release_decision["reason"],
        "release_channel": release_decision["channel"],
        "update_offer": copy.deepcopy(release_decision.get("offer") or {}),
    }


def _authenticate_session(
    doc: Dict[str, Any], token: Any, now: float,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    value = str(token or "").strip()
    if not value.startswith("sfc_v1_") or len(value) < 40:
        raise ConnectorProtocolError(
            "Connector session token отсутствует или некорректен.",
            401,
            "invalid_session",
        )
    digest = hashlib.sha256(value.encode("ascii")).hexdigest()
    session = next((
        row for row in doc["sessions"]
        if hmac.compare_digest(str(row.get("token_hash") or ""), digest)
    ), None)
    if (
        session is None
        or session.get("status") != "active"
        or float(session.get("expires_at") or 0) <= now
    ):
        raise ConnectorProtocolError(
            "Connector session истекла или отозвана.",
            401,
            "session_expired",
        )
    installation = _find_installation(
        doc, str(session.get("installation_id") or ""),
    )
    if installation.get("status") == "revoked":
        raise ConnectorProtocolError(
            "Connector installation отозвана.", 403, "installation_revoked",
        )
    _assert_environment(installation)
    return session, installation


def _advance_sequence(session: Dict[str, Any], value: Any) -> int:
    try:
        sequence = int(value)
    except (TypeError, ValueError):
        raise ConnectorProtocolError(
            "connector_sequence обязателен.", 400, "invalid_sequence",
        ) from None
    previous = int(session.get("last_sequence") or 0)
    if sequence <= previous or sequence > previous + 100000:
        raise ConnectorProtocolError(
            "connector_sequence повторён или вышел за допустимое окно.",
            409,
            "sequence_replay",
        )
    session["last_sequence"] = sequence
    session["last_seen_utc"] = _now_iso()
    return sequence


def _mask_account_label(value: Any) -> str:
    text = "".join(ch for ch in str(value or "").strip() if ch.isalnum())
    if not text:
        return ""
    return "***" + text[-4:]


_ACCOUNT_SNAPSHOT_ROOT_FIELDS = frozenset({
    "generated_at_utc", "timestamp_utc", "exporter_version", "accounts", "summary",
})
_ACCOUNT_SNAPSHOT_ROW_FIELDS = frozenset({
    "account_name", "account_mode", "cash_value", "buying_power",
    "net_liquidation", "realized_pnl", "unrealized_pnl", "currency",
    "connection_status", "availability_notes",
})


def _snapshot_text(value: Any, *, maximum: int, field: str,
                   required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ConnectorProtocolError(
            f"Account snapshot: {field} обязателен.", 400, "invalid_account_snapshot",
        )
    if len(text) > maximum:
        raise ConnectorProtocolError(
            f"Account snapshot: {field} превышает лимит.",
            400, "invalid_account_snapshot",
        )
    return text


def _snapshot_number(value: Any, *, field: str) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConnectorProtocolError(
            f"Account snapshot: {field} должен быть числом.",
            400, "invalid_account_snapshot",
        ) from None
    if not math.isfinite(number) or abs(number) > 1_000_000_000_000_000:
        raise ConnectorProtocolError(
            f"Account snapshot: {field} вне допустимого диапазона.",
            400, "invalid_account_snapshot",
        )
    return number


def _normalise_account_snapshot(value: Any, now: float) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConnectorProtocolError(
            "Account snapshot должен быть объектом.", 400, "invalid_account_snapshot",
        )
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        raise ConnectorProtocolError(
            "Account snapshot не сериализуется.", 400, "invalid_account_snapshot",
        ) from None
    if len(encoded) > MAX_ACCOUNT_SNAPSHOT_BYTES:
        raise ConnectorProtocolError(
            "Account snapshot превышает допустимый размер.",
            413, "account_snapshot_too_large",
        )
    if set(value) - _ACCOUNT_SNAPSHOT_ROOT_FIELDS:
        raise ConnectorProtocolError(
            "Account snapshot содержит неизвестные поля.",
            400, "invalid_account_snapshot",
        )
    raw_accounts = value.get("accounts")
    if not isinstance(raw_accounts, list) or len(raw_accounts) > MAX_ACCOUNT_SNAPSHOT_ACCOUNTS:
        raise ConnectorProtocolError(
            "Account snapshot содержит недопустимый список счетов.",
            400, "invalid_account_snapshot",
        )

    # When the AddOn stamped the snapshot is provenance, not evidence. What
    # makes it fresh is that it arrived inside this heartbeat, which is signed,
    # nonce-bound and rejected outside a two-minute window -- so the receive
    # time is already a sound bound and is recorded below regardless.
    #
    # Refusing the whole heartbeat over this field was a mistake with a real
    # cost: a Connector sending genuine accounts was answered 400 on every
    # beat, which took it offline entirely and reported no NinjaTrader at all.
    # An unreadable optional field is dropped and said out loud instead.
    generated = _snapshot_text(
        value.get("generated_at_utc") or value.get("timestamp_utc"),
        maximum=40, field="generated_at_utc",
    )
    generated_warning = ""
    if generated:
        try:
            parsed = datetime.fromisoformat(generated.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone required")
        except ValueError:
            generated_warning = (
                "generated_at_utc не разобран; свежесть считается по времени "
                f"приёма heartbeat (получено: {generated[:40]!r})"
            )
            generated = ""

    accounts = []
    names = set()
    for raw in raw_accounts:
        if not isinstance(raw, Mapping) or set(raw) - _ACCOUNT_SNAPSHOT_ROW_FIELDS:
            raise ConnectorProtocolError(
                "Account snapshot содержит некорректную запись счёта.",
                400, "invalid_account_snapshot",
            )
        name = _snapshot_text(
            raw.get("account_name"), maximum=128, field="account_name", required=True,
        )
        if name in names:
            continue
        names.add(name)
        notes_raw = raw.get("availability_notes") or []
        if not isinstance(notes_raw, list) or len(notes_raw) > 20:
            raise ConnectorProtocolError(
                "Account snapshot: availability_notes некорректен.",
                400, "invalid_account_snapshot",
            )
        accounts.append({
            "account_name": name,
            "account_mode": _snapshot_text(
                raw.get("account_mode"), maximum=24, field="account_mode"),
            "cash_value": _snapshot_number(raw.get("cash_value"), field="cash_value"),
            "buying_power": _snapshot_number(raw.get("buying_power"), field="buying_power"),
            "net_liquidation": _snapshot_number(
                raw.get("net_liquidation"), field="net_liquidation"),
            "realized_pnl": _snapshot_number(raw.get("realized_pnl"), field="realized_pnl"),
            "unrealized_pnl": _snapshot_number(
                raw.get("unrealized_pnl"), field="unrealized_pnl"),
            "currency": _snapshot_text(raw.get("currency"), maximum=16, field="currency"),
            "connection_status": _snapshot_text(
                raw.get("connection_status"), maximum=64, field="connection_status"),
            "availability_notes": [
                _snapshot_text(item, maximum=64, field="availability_notes")
                for item in notes_raw
            ],
        })

    summary = value.get("summary") if isinstance(value.get("summary"), Mapping) else {}

    def count(name: str) -> int:
        try:
            return max(0, min(int(summary.get(name) or 0), len(accounts)))
        except (TypeError, ValueError):
            raise ConnectorProtocolError(
                f"Account snapshot: summary.{name} некорректен.",
                400, "invalid_account_snapshot",
            ) from None

    return {
        "generated_at_utc": generated,
        "generated_at_warning": generated_warning,
        "received_at_utc": _now_iso(now),
        "received_at": now,
        "exporter_version": _snapshot_text(
            value.get("exporter_version"), maximum=32, field="exporter_version"),
        "accounts": accounts,
        "summary": {
            "total": len(accounts),
            "live": count("live"),
            "paper": count("paper"),
            "playback": count("playback"),
            "unknown": count("unknown"),
        },
    }


_RUNTIME_CATALOG_ROOT_FIELDS = frozenset({
    "schema_version", "generated_at_utc", "strategies", "commission_templates",
    "strategy_count", "commission_template_count", "parameter_schemas_included",
    "truncated",
    # Instruments arrived after the first bounded catalog. An older Connector
    # simply omits them, which stays valid.
    "instruments", "instrument_count", "instruments_scanned",
    "instruments_truncated",
    # Paging. Absent means "one complete page", which is exactly how an older
    # Connector behaves, so its single result still activates a catalog.
    "catalog_id", "total_count", "page_index", "page_count",
})
_RUNTIME_CATALOG_STRATEGY_FIELDS = frozenset({
    "class_name", "display_name", "stable_id",
})
_RUNTIME_CATALOG_TEMPLATE_FIELDS = frozenset({
    "name", "display", "supported",
})
_RUNTIME_CATALOG_INSTRUMENT_FIELDS = frozenset({
    # Only what a server cannot derive. root and expiry come from the
    # instrument name, so sending them again would just spend the 16 KiB
    # command-result budget on data the server already has.
    "instrument", "data_first", "data_last",
    "tick_size", "point_value", "tick_value",
})
# A tradable name: "MNQ 09-26" for futures, "BTCUSD" for a spot pair. The
# shape alone cannot separate a bare root from a spot symbol, so the real
# check is the data range below -- a fallback root has none.
_CONTRACT_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,39}$")


def _catalog_text(value: Any, *, maximum: int, field: str,
                  required: bool = False) -> str:
    text = " ".join(str(value or "").strip().split())
    if required and not text:
        raise ConnectorProtocolError(
            f"Runtime catalog: {field} обязателен.", 400, "invalid_runtime_catalog",
        )
    if len(text) > maximum or any(ord(char) < 32 for char in text):
        raise ConnectorProtocolError(
            f"Runtime catalog: {field} некорректен.", 400, "invalid_runtime_catalog",
        )
    return text


def _normalise_runtime_catalog(value: Any, now: float) -> Dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - _RUNTIME_CATALOG_ROOT_FIELDS:
        raise ConnectorProtocolError(
            "Runtime catalog имеет некорректный контракт.",
            400, "invalid_runtime_catalog",
        )
    strategies_raw = value.get("strategies")
    templates_raw = value.get("commission_templates")
    if not isinstance(strategies_raw, list) or len(strategies_raw) > MAX_RUNTIME_CATALOG_STRATEGIES:
        raise ConnectorProtocolError(
            "Runtime catalog содержит недопустимый список стратегий.",
            400, "invalid_runtime_catalog",
        )
    if not isinstance(templates_raw, list) or len(templates_raw) > MAX_RUNTIME_CATALOG_TEMPLATES:
        raise ConnectorProtocolError(
            "Runtime catalog содержит недопустимый список комиссий.",
            400, "invalid_runtime_catalog",
        )
    instruments_raw = value.get("instruments")
    if instruments_raw is None:
        # Older Connector: no instruments in the bounded catalog. The server
        # keeps working and simply has no device-backed contracts.
        instruments_raw = []
    if (not isinstance(instruments_raw, list)
            or len(instruments_raw) > MAX_RUNTIME_CATALOG_INSTRUMENTS_PER_PAGE):
        raise ConnectorProtocolError(
            "Runtime catalog содержит недопустимый список инструментов.",
            400, "invalid_runtime_catalog",
        )
    if bool(value.get("parameter_schemas_included")):
        raise ConnectorProtocolError(
            "Runtime catalog объявил schemas, которых нет в bounded контракте.",
            400, "invalid_runtime_catalog",
        )

    strategies = []
    seen_strategies = set()
    for raw in strategies_raw:
        if not isinstance(raw, Mapping) or set(raw) - _RUNTIME_CATALOG_STRATEGY_FIELDS:
            raise ConnectorProtocolError(
                "Runtime catalog содержит некорректную стратегию.",
                400, "invalid_runtime_catalog",
            )
        class_name = _catalog_text(
            raw.get("class_name"), maximum=80, field="class_name", required=True,
        )
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,79}", class_name):
            raise ConnectorProtocolError(
                "Runtime catalog: class_name не является безопасным identifier.",
                400, "invalid_runtime_catalog",
            )
        if class_name in seen_strategies:
            continue
        seen_strategies.add(class_name)
        strategies.append({
            "class_name": class_name,
            "display_name": _catalog_text(
                raw.get("display_name") or class_name,
                maximum=160, field="display_name", required=True,
            ),
            "stable_id": _catalog_text(
                raw.get("stable_id"), maximum=128, field="stable_id",
            ),
            # Absence is explicit, not an empty schema advertised as complete.
            "parameters": [],
        })

    templates = []
    seen_templates = set()
    for raw in templates_raw:
        if not isinstance(raw, Mapping) or set(raw) - _RUNTIME_CATALOG_TEMPLATE_FIELDS:
            raise ConnectorProtocolError(
                "Runtime catalog содержит некорректный шаблон комиссии.",
                400, "invalid_runtime_catalog",
            )
        name = _catalog_text(raw.get("name"), maximum=160, field="template.name", required=True)
        if name in seen_templates:
            continue
        seen_templates.add(name)
        templates.append({
            "name": name,
            "display": _catalog_text(
                raw.get("display") or name, maximum=200,
                field="template.display", required=True,
            ),
            "supported": bool(raw.get("supported")),
        })

    instruments = []
    seen_instruments = set()
    for raw in instruments_raw:
        if not isinstance(raw, Mapping) or set(raw) - _RUNTIME_CATALOG_INSTRUMENT_FIELDS:
            raise ConnectorProtocolError(
                "Runtime catalog содержит некорректный инструмент.",
                400, "invalid_runtime_catalog",
            )
        name = _catalog_text(
            raw.get("instrument"), maximum=40, field="instrument", required=True,
        )
        if not _CONTRACT_INSTRUMENT_RE.match(name):
            raise ConnectorProtocolError(
                "Runtime catalog: instrument некорректен.",
                400, "invalid_runtime_catalog",
            )
        data_first = _catalog_text(
            raw.get("data_first"), maximum=10, field="data_first")
        data_last = _catalog_text(
            raw.get("data_last"), maximum=10, field="data_last")
        # A bare root is exactly what this channel exists to replace. What makes
        # a name a contract is a contract month -- "MNQ 09-26" -- or, for a spot
        # pair like "BTCUSD" that never has one, a scanned data range. A missing
        # range on its own means only that nothing is cached locally yet, which
        # is the normal state for every instrument before its first backtest;
        # NinjaTrader downloads the history when Strategy Analyzer asks for it.
        if " " not in name and not (data_first and data_last):
            raise ConnectorProtocolError(
                "Runtime catalog: instrument без контрактного месяца и без "
                "диапазона данных не является конкретным контрактом.",
                400, "invalid_runtime_catalog",
            )
        if name in seen_instruments:
            continue
        seen_instruments.add(name)

        def number(field: str) -> Optional[float]:
            item = raw.get(field)
            if item is None or isinstance(item, bool):
                return None
            try:
                parsed = float(item)
            except (TypeError, ValueError):
                raise ConnectorProtocolError(
                    f"Runtime catalog: {field} некорректен.",
                    400, "invalid_runtime_catalog",
                ) from None
            if parsed != parsed or parsed in (float("inf"), float("-inf")):
                raise ConnectorProtocolError(
                    f"Runtime catalog: {field} некорректен.",
                    400, "invalid_runtime_catalog",
                )
            return parsed

        root, _, expiry = name.partition(" ")
        instruments.append({
            "instrument": name,
            "root": root,
            "expiry": expiry,
            "data_first": data_first,
            "data_last": data_last,
            "tick_size": number("tick_size"),
            "point_value": number("point_value"),
            "tick_value": number("tick_value"),
            "has_minute_data": True,
            "source": "connector_runtime_catalog",
        })

    generated = _catalog_text(
        value.get("generated_at_utc"), maximum=40, field="generated_at_utc",
    )

    def declared_count(field: str, observed: int) -> int:
        try:
            value_count = int(value.get(field) or 0)
        except (TypeError, ValueError):
            raise ConnectorProtocolError(
                f"Runtime catalog: {field} некорректен.",
                400, "invalid_runtime_catalog",
            ) from None
        if value_count < 0 or value_count > 10000:
            raise ConnectorProtocolError(
                f"Runtime catalog: {field} вне допустимого диапазона.",
                400, "invalid_runtime_catalog",
            )
        return max(observed, value_count)

    def bounded_int(field: str, *, minimum: int, maximum: int, default: int) -> int:
        if field not in value or value.get(field) is None:
            return default
        raw_value = value.get(field)
        if isinstance(raw_value, bool):
            raise ConnectorProtocolError(
                f"Runtime catalog: {field} некорректен.",
                400, "invalid_runtime_catalog",
            )
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            raise ConnectorProtocolError(
                f"Runtime catalog: {field} некорректен.",
                400, "invalid_runtime_catalog",
            ) from None
        if parsed < minimum or parsed > maximum:
            raise ConnectorProtocolError(
                f"Runtime catalog: {field} вне допустимого диапазона.",
                400, "invalid_runtime_catalog",
            )
        return parsed

    # Absent paging means one complete page, which is how an older Connector
    # behaves. Its single result still activates a catalog.
    page_count = bounded_int(
        "page_count", minimum=1, maximum=MAX_RUNTIME_CATALOG_PAGES, default=1)
    page_index = bounded_int(
        "page_index", minimum=0, maximum=page_count - 1, default=0)
    total_count = bounded_int(
        "total_count", minimum=0,
        maximum=MAX_RUNTIME_CATALOG_PAGES * MAX_RUNTIME_CATALOG_INSTRUMENTS_PER_PAGE,
        default=len(instruments))
    catalog_id = _catalog_text(
        value.get("catalog_id"), maximum=64, field="catalog_id")
    if page_count > 1 and not catalog_id:
        raise ConnectorProtocolError(
            "Runtime catalog: многостраничный snapshot обязан иметь catalog_id.",
            400, "invalid_runtime_catalog",
        )

    return {
        "schema_version": 1,
        "generated_at_utc": generated,
        "received_at_utc": _now_iso(now),
        "received_at": now,
        "catalog_id": catalog_id,
        "page_index": page_index,
        "page_count": page_count,
        "total_count": total_count,
        "strategies": strategies,
        "commission_templates": templates,
        "instruments": instruments,
        "strategy_count": declared_count("strategy_count", len(strategies)),
        "commission_template_count": declared_count(
            "commission_template_count", len(templates)),
        "instrument_count": declared_count("instrument_count", len(instruments)),
        "instruments_scanned": declared_count(
            "instruments_scanned", len(instruments)),
        "instruments_truncated": bool(value.get("instruments_truncated")),
        "parameter_schemas_included": False,
        "truncated": bool(value.get("truncated")),
    }


def _accept_runtime_catalog_page(
    installation: Dict[str, Any], page: Dict[str, Any], now: float,
) -> Tuple[bool, Dict[str, Any]]:
    """Stage one page; activate the catalog only once every page has arrived.

    A half-delivered snapshot must never replace a catalog that works. The
    server keeps the last good catalog until the full set for one ``catalog_id``
    is present, then swaps atomically.

    Returns ``(activated, staging_state)``.
    """
    page_count = int(page.get("page_count") or 1)
    catalog_id = str(page.get("catalog_id") or "")

    if page_count == 1:
        # Single page, including every older Connector: complete on arrival.
        # Any half-delivered set is abandoned here rather than left to be
        # completed by pages of a snapshot that no longer exists.
        installation.pop("runtime_catalog_staging", None)
        return True, dict(page)

    staging = installation.get("runtime_catalog_staging")
    if (not isinstance(staging, Mapping)
            or str(staging.get("catalog_id") or "") != catalog_id
            or int(staging.get("page_count") or 0) != page_count):
        # A different snapshot started: drop the partial one, never the live one.
        staging = {
            "catalog_id": catalog_id,
            "page_count": page_count,
            "generated_at_utc": str(page.get("generated_at_utc") or ""),
            "total_count": int(page.get("total_count") or 0),
            "started_at": now,
            "pages": {},
        }
    else:
        staging = {
            "catalog_id": staging.get("catalog_id"),
            "page_count": int(staging.get("page_count") or 0),
            "generated_at_utc": staging.get("generated_at_utc"),
            "total_count": int(staging.get("total_count") or 0),
            "started_at": float(staging.get("started_at") or now),
            "pages": dict(staging.get("pages") or {}),
        }

    if str(page.get("generated_at_utc") or "") != str(staging["generated_at_utc"] or ""):
        raise ConnectorProtocolError(
            "Runtime catalog: страницы принадлежат разным snapshot.",
            409, "runtime_catalog_page_mismatch",
        )
    staging["pages"][str(int(page.get("page_index") or 0))] = page
    installation["runtime_catalog_staging"] = staging

    if len(staging["pages"]) < page_count:
        return False, staging

    merged_instruments: List[Dict[str, Any]] = []
    seen: set = set()
    strategies: List[Dict[str, Any]] = []
    templates: List[Dict[str, Any]] = []
    for index in range(page_count):
        part = staging["pages"].get(str(index))
        if not isinstance(part, Mapping):
            # A gap means the set is not complete; keep waiting.
            return False, staging
        for row in part.get("instruments") or []:
            name = str(row.get("instrument") or "")
            if name and name not in seen:
                seen.add(name)
                merged_instruments.append(row)
        # Strategies and templates ride page 0 so the other pages stay small.
        if part.get("strategies"):
            strategies = list(part["strategies"])
        if part.get("commission_templates"):
            templates = list(part["commission_templates"])

    declared = int(staging["total_count"] or 0)
    if declared and len(merged_instruments) != declared:
        raise ConnectorProtocolError(
            "Runtime catalog: собранный snapshot не совпадает с total_count.",
            409, "runtime_catalog_incomplete",
        )

    last = staging["pages"][str(page_count - 1)]
    complete = dict(last)
    complete.update({
        "instruments": merged_instruments,
        "instrument_count": len(merged_instruments),
        "strategies": strategies,
        "commission_templates": templates,
        "strategy_count": len(strategies),
        "commission_template_count": len(templates),
        "page_index": page_count - 1,
        "page_count": page_count,
        "total_count": declared or len(merged_instruments),
        "received_at": now,
        "received_at_utc": _now_iso(now),
    })
    installation.pop("runtime_catalog_staging", None)
    return True, complete


def _cache_runtime_installation(row: Mapping[str, Any]) -> None:
    installation_id = str(row.get("installation_id") or "")
    if not installation_id:
        return
    cached = {key: copy.deepcopy(row.get(key)) for key in (
        "installation_id", "connection_id", "workspace_id", "user_id", "user_uuid",
        "status", "last_hello_utc", "last_heartbeat_utc", "last_heartbeat_at",
        "account_snapshot", "runtime_catalog", "revoked_at_utc", "deployment_environment",
    )}
    with _RUNTIME_ACCOUNT_CACHE_LOCK:
        _RUNTIME_ACCOUNT_CACHE[installation_id] = cached


def heartbeat(token: Any, payload: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = {
        "connector_sequence", "ninja_instance_id", "connector_time",
        "account_labels", "account_snapshot", "extensions",
    }
    if not isinstance(payload, Mapping) or set(payload) - allowed:
        raise ConnectorProtocolError(
            "Heartbeat содержит неизвестные поля.", 400, "invalid_heartbeat",
        )
    now = time.time()
    with _LOCK:
        doc = _read_doc()
        _refresh_states(doc, now)
        session, installation = _authenticate_session(doc, token, now)
        sequence = _advance_sequence(session, payload.get("connector_sequence"))
        instance = str(payload.get("ninja_instance_id") or "").strip()
        if instance and instance != str(installation.get("ninja_instance_id") or ""):
            raise ConnectorProtocolError(
                "NinjaTrader instance mismatch.", 409, "instance_mismatch",
            )
        labels = []
        for value in payload.get("account_labels") or []:
            masked = _mask_account_label(value)
            if masked and masked not in labels:
                labels.append(masked)
            if len(labels) >= 20:
                break
        snapshot = None
        if "account_snapshot" in payload:
            if "accounts_read" not in set(installation.get("capabilities") or []):
                raise ConnectorProtocolError(
                    "Account snapshot не разрешён capabilities installation.",
                    403, "capability_denied",
                )
            snapshot = _normalise_account_snapshot(payload.get("account_snapshot"), now)
        installation.update({
            "status": "online",
            "last_heartbeat_utc": _now_iso(now),
            "last_heartbeat_at": now,
            "account_labels": labels,
        })
        if snapshot is not None:
            installation["account_snapshot"] = snapshot
        previous_release = (
            installation.get("update_state"),
            installation.get("update_reason"),
            installation.get("release_channel"),
        )
        release_decision = _apply_release_policy(installation)
        _write_doc(doc)
        _cache_runtime_installation(installation)
    current_release = (
        release_decision["state"],
        release_decision["reason"],
        release_decision["channel"],
    )
    if previous_release != current_release:
        _audit(
            "release_policy_changed",
            workspace_id=installation["workspace_id"],
            installation_id=installation["installation_id"],
            update_state=release_decision["state"],
            update_reason=release_decision["reason"],
            release_channel=release_decision["channel"],
        )
    return {
        "ok": True,
        "state": "online",
        "connector_sequence": sequence,
        "server_time": _now_iso(now),
        "session_expires_at": _now_iso(session["expires_at"]),
        "heartbeat_interval_sec": HEARTBEAT_INTERVAL_SEC,
        "update_state": release_decision["state"],
        "update_reason": release_decision["reason"],
        "release_channel": release_decision["channel"],
        "update_offer": copy.deepcopy(release_decision.get("offer") or {}),
    }


def _market_data_source_sequence(value: Any) -> int:
    if isinstance(value, bool):
        raise ConnectorProtocolError(
            "source_sequence обязателен.", 400, "invalid_source_sequence",
        )
    try:
        sequence = int(value)
    except (TypeError, ValueError):
        raise ConnectorProtocolError(
            "source_sequence обязателен.", 400, "invalid_source_sequence",
        ) from None
    if sequence < 1 or sequence > MAX_SOURCE_SEQUENCE:
        raise ConnectorProtocolError(
            "source_sequence вышел за допустимые границы.", 400, "invalid_source_sequence",
        )
    return sequence


def _clean_market_data_bars(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_MARKET_DATA_BARS:
        raise ConnectorProtocolError(
            "Market-data batch должен содержать от 1 до 64 bars.",
            400,
            "invalid_market_data_batch",
        )
    try:
        if len(_canonical_json(value)) > MAX_MARKET_DATA_BYTES:
            raise ConnectorProtocolError(
                "Market-data batch превышает 128 KiB.", 413, "market_data_too_large",
            )
    except (TypeError, ValueError):
        raise ConnectorProtocolError(
            "Market-data batch содержит неподдерживаемое значение.",
            400,
            "invalid_market_data_batch",
        ) from None

    fields = {
        "timestamp", "open", "high", "low", "close", "volume",
        "exact_contract", "timeframe",
    }
    clean: list[Dict[str, Any]] = []
    last_by_series: Dict[Tuple[str, str], datetime] = {}
    for row in value:
        if not isinstance(row, Mapping) or set(row) != fields:
            raise ConnectorProtocolError(
                "Market-data bar имеет неизвестные или отсутствующие поля.",
                400,
                "invalid_market_data_bar",
            )
        try:
            prices = {
                name: float(row[name])
                for name in ("open", "high", "low", "close")
            }
            volume_value = float(row["volume"])
        except (TypeError, ValueError):
            raise ConnectorProtocolError(
                "Market-data bar содержит некорректную цену или volume.",
                400,
                "invalid_market_data_bar",
            ) from None
        if (
            any(not math.isfinite(number) for number in prices.values())
            or not math.isfinite(volume_value)
            or volume_value < 0
            or not volume_value.is_integer()
            or volume_value > MAX_SOURCE_SEQUENCE
        ):
            raise ConnectorProtocolError(
                "Market-data bar содержит некорректную цену или volume.",
                400,
                "invalid_market_data_bar",
            )
        if (
            prices["high"] < prices["low"]
            or not prices["low"] <= prices["open"] <= prices["high"]
            or not prices["low"] <= prices["close"] <= prices["high"]
        ):
            raise ConnectorProtocolError(
                "Market-data OHLC нарушает диапазон bar.", 400, "invalid_market_data_bar",
            )
        timestamp = str(row["timestamp"] or "").strip()
        try:
            parsed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            parsed_at = None
        if parsed_at is None or parsed_at.tzinfo is None:
            raise ConnectorProtocolError(
                "Market-data timestamp должен содержать UTC offset.",
                400,
                "invalid_market_data_bar",
            )
        parsed_at = parsed_at.astimezone(timezone.utc)
        if parsed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ConnectorProtocolError(
                "Market-data timestamp находится недопустимо далеко в будущем.",
                400,
                "invalid_market_data_bar",
            )
        contract = str(row["exact_contract"] or "").strip().upper()
        timeframe = _normalize_market_timeframe(row["timeframe"])
        if not _MARKET_CONTRACT_RE.fullmatch(contract) or not timeframe:
            raise ConnectorProtocolError(
                "Market-data contract или timeframe имеет некорректный формат.",
                400,
                "invalid_market_data_bar",
            )
        series_key = (contract, timeframe)
        if series_key in last_by_series and parsed_at <= last_by_series[series_key]:
            raise ConnectorProtocolError(
                "Market-data bars должны строго возрастать по времени внутри серии.",
                400,
                "invalid_market_data_bar",
            )
        last_by_series[series_key] = parsed_at
        clean.append({
            "timestamp": parsed_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "open": prices["open"],
            "high": prices["high"],
            "low": prices["low"],
            "close": prices["close"],
            "volume": int(volume_value),
            "exact_contract": contract,
            "timeframe": timeframe,
        })
    return clean


def ingest_market_data(token: Any, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Accept a bounded telemetry batch bound to the authenticated Connector."""
    allowed = {"connector_sequence", "source_sequence", "bars", "extensions"}
    if not isinstance(payload, Mapping) or set(payload) - allowed:
        raise ConnectorProtocolError(
            "Market-data message содержит неизвестные поля.", 400, "invalid_market_data",
        )
    source_sequence = _market_data_source_sequence(payload.get("source_sequence"))
    bars = _clean_market_data_bars(payload.get("bars"))
    payload_sha256 = hashlib.sha256(_canonical_json(bars)).hexdigest()
    now = time.time()
    with _LOCK:
        doc = _read_doc()
        _refresh_states(doc, now)
        session, installation = _authenticate_session(doc, token, now)
        if "telemetry" not in installation.get("capabilities", []):
            raise ConnectorProtocolError(
                "Connector не имеет telemetry capability.", 403, "market_data_capability_denied",
            )
        connector_sequence = _advance_sequence(session, payload.get("connector_sequence"))
        previous_sequence = int(installation.get("last_market_data_source_sequence") or 0)
        if source_sequence < previous_sequence:
            raise ConnectorProtocolError(
                "source_sequence повторён или устарел.", 409, "source_sequence_replay",
            )
        if source_sequence == previous_sequence:
            previous_hash = str(installation.get("last_market_data_payload_sha256") or "")
            if not hmac.compare_digest(previous_hash, payload_sha256):
                raise ConnectorProtocolError(
                    "Повторный source_sequence отличается от исходного batch.",
                    409,
                    "source_sequence_conflict",
                )
            _write_doc(doc)
            return {
                "ok": True,
                "connector_sequence": connector_sequence,
                "source_sequence": source_sequence,
                "batch_id": str(installation.get("last_market_data_batch_id") or ""),
                "items": len(bars),
                "idempotent_replay": True,
                "fan_out": {"ok": True, "distributed": 0, "subscriptions": 0},
            }

        from . import market_data_ingestion

        ingested = market_data_ingestion.ingest_batch(
            str(installation.get("workspace_id") or ""),
            str(installation.get("installation_id") or ""),
            source_sequence,
            bars,
            user_id=int(installation.get("user_id") or 0),
        )
        if not ingested.get("ok"):
            code = str(ingested.get("code") or "market_data_rejected")
            if code == "storage_unavailable":
                raise ConnectorProtocolError(
                    "Market-data storage is unavailable.", 503, code,
                )
            status = 409 if code == "source_sequence_conflict" else 422
            raise ConnectorProtocolError("Market-data batch отклонён.", status, code)
        try:
            fan_out = market_data_ingestion.fan_out(
                str(installation.get("workspace_id") or ""), bars,
            )
        except Exception:
            fan_out = {"ok": False, "distributed": 0, "subscriptions": 0}
        installation.update({
            "status": "online",
            "last_heartbeat_utc": _now_iso(now),
            "last_heartbeat_at": now,
            "last_market_data_source_sequence": source_sequence,
            "last_market_data_payload_sha256": payload_sha256,
            "last_market_data_batch_id": str(ingested.get("batch_id") or ""),
        })
        _write_doc(doc)
    _audit(
        "market_data_ingested",
        workspace_id=installation["workspace_id"],
        installation_id=installation["installation_id"],
        source_sequence=source_sequence,
        batch_id=ingested.get("batch_id"),
        items=len(bars),
    )
    return {
        "ok": True,
        "connector_sequence": connector_sequence,
        "source_sequence": source_sequence,
        "batch_id": str(ingested.get("batch_id") or ""),
        "items": int(ingested.get("items") or len(bars)),
        "idempotent_replay": bool(ingested.get("deduplicated")),
        "fan_out": fan_out,
    }


def _safe_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ConnectorProtocolError(
            "Command payload должен быть object.", 400, "invalid_command_payload",
        )
    forbidden = {"password", "broker_password", "token", "secret", "api_key", "source", "code"}

    def visit(value: Any, depth: int = 0) -> Any:
        if depth > 6:
            raise ConnectorProtocolError(
                "Command payload слишком глубокий.", 400, "invalid_command_payload",
            )
        if value is None or isinstance(value, (bool, int, str)):
            if isinstance(value, str) and len(value) > 4096:
                raise ConnectorProtocolError(
                    "Command string слишком длинная.", 400, "invalid_command_payload",
                )
            return value
        if isinstance(value, float):
            if value != value or value in {float("inf"), float("-inf")}:
                raise ConnectorProtocolError(
                    "Command number некорректен.", 400, "invalid_command_payload",
                )
            return value
        if isinstance(value, list):
            if len(value) > 100:
                raise ConnectorProtocolError(
                    "Command list слишком велик.", 400, "invalid_command_payload",
                )
            return [visit(item, depth + 1) for item in value]
        if isinstance(value, Mapping):
            if len(value) > 100:
                raise ConnectorProtocolError(
                    "Command object слишком велик.", 400, "invalid_command_payload",
                )
            out = {}
            for key, item in value.items():
                name = str(key or "").strip()
                if not name or len(name) > 80 or name.lower() in forbidden:
                    raise ConnectorProtocolError(
                        "Command payload содержит запрещённое поле.",
                        400,
                        "forbidden_command_field",
                    )
                out[name] = visit(item, depth + 1)
            return out
        raise ConnectorProtocolError(
            "Command payload type не поддерживается.", 400, "invalid_command_payload",
        )

    result = visit(payload)
    if len(_canonical_json(result)) > 32768:
        raise ConnectorProtocolError(
            "Command payload превышает 32 KiB.", 413, "command_too_large",
        )
    return result


def _validate_command_capability(capability: str, payload: Mapping[str, Any]) -> None:
    command = str(payload.get("command") or "").strip()
    allowed = {
        "telemetry": {"ping", "snapshot_runtime"},
        "accounts_read": {"snapshot_accounts"},
        "paper_commands": {
            "enable_strategy", "disable_strategy", "reconnect_account",
            "resubscribe_market_data", "resubscribe_instrument",
            # A backtest is a read-only historical replay on the paper contour:
            # it opens no position and routes no order. It rides the paper
            # capability rather than a new one so an already enrolled device
            # needs no re-enrollment, and it is allow-listed by name here so
            # the capability cannot be used to name arbitrary work.
            "run_backtest", "cancel_backtest",
        },
        "live_read": {"snapshot_live_accounts"},
        "live_commands": set(),
    }
    if command not in allowed.get(capability, set()):
        raise ConnectorProtocolError(
            "Command не разрешена для выбранной capability.",
            403,
            "command_capability_mismatch",
        )


def queue_command(
    user_id: Any,
    *,
    workspace_id: str,
    connection_id: Any,
    capability: Any,
    idempotency_key: Any,
    payload: Any,
    expires_in_sec: Any = 120,
) -> Dict[str, Any]:
    user = int(user_id or 0)
    workspace = workspaces.require_workspace_writer(user, workspace_id=workspace_id)
    workspace_value = str(workspace.get("workspace_id") or "")
    target = _safe_id(connection_id, "connection_id")
    cap = str(capability or "").strip()
    if cap not in CAPABILITIES:
        raise ConnectorProtocolError(
            "Неизвестная Connector capability.", 400, "invalid_capability",
        )
    if cap == "live_commands" and not runtime_env.allow_live_orders():
        raise ConnectorProtocolError(
            "Live commands выключены.", 403, "live_commands_disabled",
        )
    key = str(idempotency_key or "").strip()
    if not _IDEMPOTENCY_RE.fullmatch(key):
        raise ConnectorProtocolError(
            "Idempotency-Key обязателен (8..128 safe chars).",
            400,
            "invalid_idempotency_key",
        )
    clean_payload = _safe_payload(payload)
    _validate_command_capability(cap, clean_payload)
    try:
        ttl = int(expires_in_sec)
    except (TypeError, ValueError):
        ttl = 0
    if ttl < 5 or ttl > MAX_COMMAND_TTL_SEC:
        raise ConnectorProtocolError(
            "Command TTL должен быть 5..300 секунд.", 400, "invalid_command_ttl",
        )
    now = time.time()
    envelope_hash = hashlib.sha256(_canonical_json({
        "workspace_id": workspace_value,
        "connection_id": target,
        "capability": cap,
        "payload": clean_payload,
    })).hexdigest()
    with _COMMANDS_CHANGED:
        doc = _read_doc()
        _refresh_states(doc, now)
        installation = next((
            row for row in doc["installations"]
            if str(row.get("workspace_id") or "") == workspace_value
            and str(row.get("connection_id") or "") == target
        ), None)
        if installation is None:
            raise ConnectorProtocolError(
                "Connector connection не найдена в workspace.",
                404,
                "connection_not_found",
            )
        if installation.get("status") == "revoked":
            raise ConnectorProtocolError(
                "Connector connection отозвана.", 403, "installation_revoked",
            )
        release_decision = _apply_release_policy(installation)
        if (
            cap in {"paper_commands", "live_commands"}
            and release_decision["state"] == "blocked"
        ):
            _write_doc(doc)
            raise ConnectorProtocolError(
                "Connector version заблокирована release policy.",
                426,
                "connector_update_required",
            )
        if cap not in set(installation.get("capabilities") or []):
            raise ConnectorProtocolError(
                "Capability не выдана этой installation.",
                403,
                "capability_not_granted",
            )
        existing = next((
            row for row in doc["commands"]
            if str(row.get("workspace_id") or "") == workspace_value
            and hmac.compare_digest(str(row.get("idempotency_key") or ""), key)
        ), None)
        if existing is not None:
            if not hmac.compare_digest(
                str(existing.get("envelope_hash") or ""), envelope_hash,
            ):
                raise ConnectorProtocolError(
                    "Idempotency-Key уже использован с другим command body.",
                    409,
                    "idempotency_conflict",
                )
            public = _public_command(existing, include_payload=False)
            public["idempotent_replay"] = True
            return {"ok": True, "command": public}
        command = {
            "command_id": "cmd_" + secrets.token_urlsafe(18),
            "workspace_id": workspace_value,
            "connection_id": target,
            "installation_id": installation["installation_id"],
            "capability": cap,
            "idempotency_key": key,
            "issued_by_user_id": user,
            "issued_at": now,
            "issued_at_utc": _now_iso(now),
            "expires_at": now + ttl,
            "expires_at_utc": _now_iso(now + ttl),
            "payload": clean_payload,
            "envelope_hash": envelope_hash,
            "status": "queued",
            "delivery_attempts": 0,
            "delivery_lease_until": 0,
            "finished_at_utc": "",
        }
        doc["commands"].append(command)
        _write_doc(doc)
        _COMMANDS_CHANGED.notify_all()
    _audit(
        "command_queued",
        user_id=user,
        workspace_id=workspace_value,
        installation_id=installation["installation_id"],
        command_id=command["command_id"],
        capability=cap,
    )
    return {
        "ok": True,
        "command": _public_command(command, include_payload=False),
        "connector_state": installation.get("status") or "offline",
    }


def _public_command(row: Mapping[str, Any], *, include_payload: bool) -> Dict[str, Any]:
    out = {name: copy.deepcopy(row.get(name)) for name in (
        "command_id", "workspace_id", "connection_id", "installation_id",
        "user_uuid", "issued_by_user_uuid",
        "capability", "idempotency_key", "issued_at_utc", "expires_at_utc",
        "status", "delivery_attempts", "finished_at_utc",
    )}
    if include_payload:
        out["payload"] = copy.deepcopy(row.get("payload") or {})
    return out


def poll_commands(
    token: Any,
    *,
    connector_sequence: Any,
    wait_seconds: Any = 0,
    limit: Any = 10,
) -> Dict[str, Any]:
    try:
        wait = max(0.0, min(float(wait_seconds or 0), 20.0))
        capped = max(1, min(int(limit or 10), 20))
    except (TypeError, ValueError):
        raise ConnectorProtocolError(
            "Некорректные poll параметры.", 400, "invalid_poll",
        ) from None
    deadline = time.monotonic() + wait
    with _COMMANDS_CHANGED:
        while True:
            now = time.time()
            doc = _read_doc()
            changed = _refresh_states(doc, now)
            session, installation = _authenticate_session(doc, token, now)
            release_decision = _apply_release_policy(installation)
            if release_decision["state"] == "blocked":
                for command in doc["commands"]:
                    if (
                        str(command.get("installation_id") or "")
                        == str(installation.get("installation_id") or "")
                        and command.get("status") not in TERMINAL_COMMAND_STATES
                        and command.get("capability")
                        in {"paper_commands", "live_commands"}
                    ):
                        command["status"] = "rejected"
                        command["finished_at_utc"] = _now_iso(now)
                        command["release_rejection"] = release_decision["reason"]
                        changed = True
            candidates = [
                row for row in doc["commands"]
                if str(row.get("installation_id") or "") == str(
                    installation.get("installation_id") or "",
                )
                and row.get("status") not in TERMINAL_COMMAND_STATES
                and (
                    row.get("status") == "queued"
                    or float(row.get("delivery_lease_until") or 0) <= now
                )
            ][:capped]
            if candidates or time.monotonic() >= deadline:
                sequence = _advance_sequence(session, connector_sequence)
                for command in candidates:
                    command["status"] = "delivered"
                    command["delivery_attempts"] = int(
                        command.get("delivery_attempts") or 0,
                    ) + 1
                    command["delivery_lease_until"] = now + COMMAND_DELIVERY_LEASE_SEC
                    command["last_delivered_at_utc"] = _now_iso(now)
                    command["delivered_session_id"] = session["session_id"]
                installation["status"] = "online"
                installation["last_heartbeat_at"] = now
                installation["last_heartbeat_utc"] = _now_iso(now)
                _write_doc(doc)
                return {
                    "ok": True,
                    "connector_sequence": sequence,
                    "server_time": _now_iso(now),
                    "commands": [
                        _public_command(row, include_payload=True)
                        for row in candidates
                    ],
                }
            if changed:
                _write_doc(doc)
            # _COMMANDS_CHANGED is bound to _LOCK, the lock every reader of the
            # connector document needs. Each idle tick re-read the document,
            # swept it and often wrote it back -- against an authoritative
            # database that is a round trip per device per tick, all of it
            # holding the shared lock. With several devices long-polling, the
            # lock was occupied most of the time and an ordinary reader could
            # queue for many seconds: /api/bridge/connections measured 12.6s on
            # Production for four rows and four kilobytes.
            #
            # A same-process enqueue still wakes this immediately through the
            # condition; the periodic tick only exists to notice work committed
            # by another process, so it can be far less frequent.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue
            _COMMANDS_CHANGED.wait(timeout=min(IDLE_POLL_TICK_SEC, remaining))


def _safe_result(value: Any) -> Any:
    if value is None:
        return {}
    clean = _safe_payload(value if isinstance(value, Mapping) else {"message": str(value)})
    if len(_canonical_json(clean)) > MAX_COMMAND_RESULT_BYTES:
        raise ConnectorProtocolError(
            "Command result превышает 16 KiB.", 413, "result_too_large",
        )
    return clean


def submit_result(token: Any, payload: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = {
        "command_id", "idempotency_key", "status", "connector_sequence",
        "safe_result", "error_class", "extensions",
    }
    if not isinstance(payload, Mapping) or set(payload) - allowed:
        raise ConnectorProtocolError(
            "Result содержит неизвестные поля.", 400, "invalid_result",
        )
    command_id = _safe_id(payload.get("command_id"), "command_id")
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    # `cancelled` is terminal and distinct from `failed`: a run the operator
    # stopped is not a run that broke, and recording it as a failure would put
    # an error in front of somebody who got exactly what they asked for.
    if status not in {"accepted", "running", "completed",
                      "cancelled", "failed", "rejected"}:
        raise ConnectorProtocolError(
            "Некорректный command result status.", 400, "invalid_result_status",
        )
    result = _safe_result(payload.get("safe_result"))
    error_class = str(payload.get("error_class") or "").strip()[:80]
    now = time.time()
    catalog_stored = False
    with _COMMANDS_CHANGED:
        doc = _read_doc()
        _refresh_states(doc, now)
        session, installation = _authenticate_session(doc, token, now)
        sequence = _advance_sequence(session, payload.get("connector_sequence"))
        command = next((
            row for row in doc["commands"]
            if hmac.compare_digest(str(row.get("command_id") or ""), command_id)
        ), None)
        if command is None:
            raise ConnectorProtocolError(
                "Command не найдена.", 404, "command_not_found",
            )
        if (
            str(command.get("installation_id") or "")
            != str(installation.get("installation_id") or "")
            or str(command.get("workspace_id") or "")
            != str(installation.get("workspace_id") or "")
        ):
            raise ConnectorProtocolError(
                "Command принадлежит другой installation/workspace.",
                403,
                "command_scope_mismatch",
            )
        if not hmac.compare_digest(
            str(command.get("idempotency_key") or ""), idempotency_key,
        ):
            raise ConnectorProtocolError(
                "Command idempotency mismatch.", 409, "idempotency_conflict",
            )
        result_hash = hashlib.sha256(_canonical_json({
            "status": status,
            "safe_result": result,
            "error_class": error_class,
        })).hexdigest()
        existing = next((
            row for row in doc["results"]
            if str(row.get("command_id") or "") == command_id
            and str(row.get("status") or "") == status
        ), None)
        if existing is not None:
            if not hmac.compare_digest(
                str(existing.get("result_hash") or ""), result_hash,
            ):
                raise ConnectorProtocolError(
                    "Повторный result отличается от исходного.",
                    409,
                    "result_conflict",
                )
            return {
                "ok": True,
                "idempotent_replay": True,
                "command": _public_command(command, include_payload=False),
            }
        if command.get("status") == "expired" or float(
            command.get("expires_at") or 0,
        ) <= now:
            raise ConnectorProtocolError(
                "Просроченная command не может быть завершена.",
                409,
                "command_expired",
            )
        terminal = status in {"completed", "cancelled", "failed", "rejected"}
        command["status"] = status
        if terminal:
            command["finished_at_utc"] = _now_iso(now)
        command_payload = command.get("payload") \
            if isinstance(command.get("payload"), Mapping) else {}
        if (
            status == "completed"
            and str(command_payload.get("command") or "") == "snapshot_runtime"
            and isinstance(result.get("catalog"), Mapping)
        ):
            page = _normalise_runtime_catalog(result["catalog"], now)
            activated, assembled = _accept_runtime_catalog_page(
                installation, page, now)
            if activated:
                catalog = assembled or page
                catalog.update({
                    "installation_id": str(installation.get("installation_id") or ""),
                    "connection_id": str(installation.get("connection_id") or ""),
                    "workspace_id": str(installation.get("workspace_id") or ""),
                    "connector_version": str(installation.get("connector_version") or ""),
                    "nt_version": str(installation.get("nt_version") or ""),
                })
                # Swapped only here, once the whole set is present: a partial
                # snapshot leaves the previous working catalog untouched.
                installation["runtime_catalog"] = catalog
                catalog_stored = True
            else:
                # More pages are outstanding; ask for the next missing one on
                # the same signed channel so a reconnect can finish delivery.
                pending = _queue_runtime_catalog_snapshot(
                    doc, installation, session, now,
                    page_index=_next_missing_catalog_page(installation),
                )
                if pending:
                    _COMMANDS_CHANGED.notify_all()
        doc["results"].append({
            "command_id": command_id,
            "workspace_id": command["workspace_id"],
            "installation_id": command["installation_id"],
            "idempotency_key": idempotency_key,
            "status": status,
            "connector_sequence": sequence,
            "safe_result": result,
            "error_class": error_class,
            "result_hash": result_hash,
            "received_at_utc": _now_iso(now),
        })
        _write_doc(doc)
        if catalog_stored:
            _cache_runtime_installation(installation)
        _COMMANDS_CHANGED.notify_all()
    _audit(
        "command_result",
        workspace_id=command["workspace_id"],
        installation_id=command["installation_id"],
        command_id=command_id,
        status=status,
        error_class=error_class,
    )
    if catalog_stored:
        _audit(
            "runtime_catalog_received",
            workspace_id=command["workspace_id"],
            installation_id=command["installation_id"],
            command_id=command_id,
            strategies=len(installation["runtime_catalog"].get("strategies") or []),
            commission_templates=len(
                installation["runtime_catalog"].get("commission_templates") or []),
        )
    return {
        "ok": True,
        "command": _public_command(command, include_payload=False),
    }


def list_installations(user_id: Any, *, workspace_id: str = "") -> Dict[str, Any]:
    user = int(user_id or 0)
    workspace = workspaces.require_workspace_access(user, workspace_id=workspace_id)
    workspace_value = str(workspace.get("workspace_id") or "")
    now = time.time()
    with _LOCK:
        doc = _read_doc()
        changed = _refresh_states(doc, now)
        if changed:
            _write_doc(doc)
        rows = [
            _public_installation(row)
            for row in doc["installations"]
            if str(row.get("workspace_id") or "") == workspace_value
        ]
    return {"ok": True, "workspace": workspace, "connections": rows}


def _snapshot_reply(cached: Dict[str, Any], now: float) -> Dict[str, Any]:
    reply = dict(cached)
    taken = float(reply.pop("_taken_at", 0) or 0)
    reply["stale_sec"] = round(max(0.0, now - taken), 1)
    return reply


def _start_health_refresh(user: int, workspace_value: str, cache_key: str) -> None:
    """Refresh one status snapshot in the background, one worker at a time."""
    with _HEALTH_SNAPSHOT_LOCK:
        if cache_key in _HEALTH_REFRESHING:
            return
        _HEALTH_REFRESHING.add(cache_key)

    def run() -> None:
        try:
            with _LOCK:
                doc = _read_doc()
                snapshot = _summarise_installations(doc, workspace_value, time.time())
            with _HEALTH_SNAPSHOT_LOCK:
                _HEALTH_SNAPSHOT[cache_key] = snapshot
        except Exception:
            # A status refresh must never take the process down, and the last
            # good snapshot keeps being served with its age attached.
            pass
        finally:
            with _HEALTH_SNAPSHOT_LOCK:
                _HEALTH_REFRESHING.discard(cache_key)

    threading.Thread(
        target=run, name=f"connector-status-{cache_key[:16]}", daemon=True,
    ).start()


def _summarise_installations(doc: Mapping[str, Any], workspace_value: str,
                             now: float) -> Dict[str, Any]:
    installations = [
        row for row in (doc.get("installations") or [])
        if str(row.get("workspace_id") or "") == workspace_value
    ]
    active_sessions = {
        str(row.get("installation_id") or "")
        for row in (doc.get("sessions") or [])
        if row.get("status") == "active" and float(row.get("expires_at") or 0) > now
    }
    online = 0
    last_heartbeat = ""
    for row in installations:
        beat = str(row.get("last_heartbeat_utc") or "")
        if beat > last_heartbeat:
            last_heartbeat = beat
        if str(row.get("status") or "") != "online":
            continue
        if str(row.get("installation_id") or "") not in active_sessions:
            continue
        try:
            last = float(row.get("last_heartbeat_at") or 0)
        except (TypeError, ValueError):
            last = 0
        if now - last > OFFLINE_AFTER_SEC:
            continue
        online += 1
    return {
        "ok": True, "status_known": True, "workspace_id": workspace_value,
        "installations": len(installations), "online": online,
        "last_heartbeat_utc": last_heartbeat, "stale_sec": 0.0,
        "_taken_at": now,
    }


def health_summary(user_id: Any, *, workspace_id: str = "") -> Dict[str, Any]:
    """Connector health for a diagnostics panel, without writing anything.

    ``list_installations`` sweeps expired enrollments, sessions and commands and
    persists the result. That is correct for a page that manages connectors, but
    it makes a status probe a write under the global lock, competing with the
    heartbeats of the very connector it is asking about. On a deployment with a
    real enrolled device and an authoritative database that is what pushed the
    admin probe past its budget while the connector itself was perfectly
    healthy.

    So this answers the status question from a snapshot: no sweep, no write, and
    the derived states computed for the reply only. Expiry is applied in the
    reply too, so a stale row is never reported as online.
    """
    user = int(user_id or 0)
    workspace = workspaces.require_workspace_access(user, workspace_id=workspace_id)
    workspace_value = str(workspace.get("workspace_id") or "")
    now = time.time()
    # A status question must not queue indefinitely behind connector traffic.
    # If the shared lock is busy, say the state was not measured rather than
    # spending the caller's whole probe budget waiting for it.
    cache_key = workspace_value or "*"
    with _HEALTH_SNAPSHOT_LOCK:
        cached = _HEALTH_SNAPSHOT.get(cache_key)
    if cached:
        age = now - float(cached.get("_taken_at") or 0)
        if age >= HEALTH_SNAPSHOT_TTL_SEC:
            # Stale, so refresh it -- but off the request path. Waiting for the
            # store here is what made the panel slow in the first place, and a
            # snapshot that can never refresh just grows old in silence.
            _start_health_refresh(user, workspace_value, cache_key)
        return _snapshot_reply(cached, now)
    if not _LOCK.acquire(timeout=HEALTH_SUMMARY_LOCK_WAIT_SEC):
        _start_health_refresh(user, workspace_value, cache_key)
        return {
            "ok": False,
            "status_known": False,
            "reason": "connector_store_busy",
            "workspace_id": workspace_value,
        }
    try:
        doc = _read_doc()
        snapshot = _summarise_installations(doc, workspace_value, now)
    finally:
        _LOCK.release()
    with _HEALTH_SNAPSHOT_LOCK:
        _HEALTH_SNAPSHOT[cache_key] = snapshot
    return _snapshot_reply(snapshot, now)


def _refresh_runtime_account_cache() -> None:
    if not _LOCK.acquire(timeout=HEALTH_SUMMARY_LOCK_WAIT_SEC):
        return
    try:
        doc = _read_doc()
        rows = [row for row in (doc.get("installations") or []) if isinstance(row, dict)]
        for row in rows:
            _cache_runtime_installation(row)
    finally:
        _LOCK.release()


def _runtime_account_rows() -> list[Dict[str, Any]]:
    with _RUNTIME_ACCOUNT_CACHE_LOCK:
        cached = [copy.deepcopy(row) for row in _RUNTIME_ACCOUNT_CACHE.values()]
    if cached:
        return cached
    # A fresh process may receive a UI read before the next 15-second heartbeat.
    # Bound that one fallback read rather than bringing the old 12-30 second
    # Connector document latency back into every status poll.
    _refresh_runtime_account_cache()
    with _RUNTIME_ACCOUNT_CACHE_LOCK:
        return [copy.deepcopy(row) for row in _RUNTIME_ACCOUNT_CACHE.values()]


def runtime_account_status(user_id: Any, *, workspace_id: str = "",
                           uses_owner_runtime: bool = False,
                           is_owner: bool = False) -> Dict[str, Any]:
    """Latest signed heartbeat plus account data for one authenticated context.

    A normal workspace is exact-scope. The special owner-training workspace may
    resolve the same owner's Connector from another one of that owner's own
    workspaces because it is explicitly defined as ``uses_owner_runtime``. This
    is not a global-owner bypass: another user's installation never qualifies.
    """
    user = int(user_id or 0)
    workspace = workspaces.require_workspace_access(user, workspace_id=workspace_id)
    requested_workspace = str(workspace.get("workspace_id") or "")
    owner_fallback = bool(is_owner and uses_owner_runtime)
    user_uuid = ""
    if owner_fallback:
        user_uuid = _user_uuid_for_legacy_id(user)

    def select(rows: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
        found = []
        for row in rows:
            if str(row.get("deployment_environment") or "") not in {
                "", runtime_env.deployment_environment(),
            }:
                continue
            if row.get("revoked_at_utc") or str(row.get("status") or "") == "revoked":
                continue
            row_workspace = str(row.get("workspace_id") or "")
            if owner_fallback:
                same_user = _legacy_user_id(row.get("user_id")) == user
                same_uuid = bool(user_uuid) and str(row.get("user_uuid") or "") == user_uuid
                if not (same_user or same_uuid):
                    continue
            elif row_workspace != requested_workspace:
                continue
            found.append(dict(row))
        return found

    eligible = select(_runtime_account_rows())
    if not eligible:
        # The cache may currently contain only a different user's heartbeat.
        _refresh_runtime_account_cache()
        eligible = select(_runtime_account_rows())

    now = time.time()
    eligible.sort(key=lambda row: float(row.get("last_heartbeat_at") or 0), reverse=True)
    selected = eligible[0] if eligible else {}
    heartbeat_at = float(selected.get("last_heartbeat_at") or 0)
    heartbeat_age = max(0.0, now - heartbeat_at) if heartbeat_at else None
    heartbeat_fresh = bool(
        heartbeat_at and -5 <= now - heartbeat_at <= OFFLINE_AFTER_SEC
        and str(selected.get("status") or "") == "online"
    )
    heartbeat_confirmed = bool(
        heartbeat_fresh and heartbeat_age is not None
        and heartbeat_age <= HEARTBEAT_CONFIRMED_MAX_AGE_SEC
    )
    snapshot = selected.get("account_snapshot")
    if not isinstance(snapshot, Mapping):
        snapshot = {}
    snapshot_at = float(snapshot.get("received_at") or 0)
    snapshot_age = max(0.0, now - snapshot_at) if snapshot_at else None
    snapshot_fresh = bool(
        snapshot_at and -5 <= now - snapshot_at <= ACCOUNT_SNAPSHOT_FRESH_SEC
    )
    accounts = copy.deepcopy(snapshot.get("accounts") or []) if snapshot else []
    functional_live = bool(heartbeat_fresh and snapshot_fresh and accounts)
    confirmed_live = bool(heartbeat_confirmed and snapshot_fresh and accounts)
    runtime_catalog = selected.get("runtime_catalog")
    if not isinstance(runtime_catalog, Mapping):
        runtime_catalog = {}
    catalog_at = float(runtime_catalog.get("received_at") or 0)
    catalog_age = max(0.0, now - catalog_at) if catalog_at else None
    catalog_time_fresh = bool(
        catalog_at and -5 <= now - catalog_at <= RUNTIME_CATALOG_FRESH_SEC
    )
    catalog_present = bool(
        runtime_catalog
        and isinstance(runtime_catalog.get("strategies"), list)
        and isinstance(runtime_catalog.get("commission_templates"), list)
    )
    catalog_fresh = bool(catalog_present and catalog_time_fresh and heartbeat_fresh)
    if not catalog_present:
        catalog_state = "missing"
    elif not heartbeat_fresh:
        catalog_state = "offline"
    elif not catalog_time_fresh:
        catalog_state = "stale"
    else:
        catalog_state = "fresh"
    source_workspace = str(selected.get("workspace_id") or "")
    return {
        "ok": True,
        "source": "production_connector",
        "requested_workspace_id": requested_workspace,
        "source_workspace_id": source_workspace,
        "resolved_via_owner_runtime": bool(
            owner_fallback and source_workspace and source_workspace != requested_workspace),
        "installation_id": str(selected.get("installation_id") or ""),
        "connection_id": str(selected.get("connection_id") or ""),
        "present": bool(selected),
        "fresh": heartbeat_fresh,
        "functional_live": functional_live,
        "confirmed_live": confirmed_live,
        "heartbeat_confirmation_state": (
            "confirmed" if heartbeat_confirmed else
            ("grace" if heartbeat_fresh else "offline")
        ),
        "heartbeat_interval_sec": HEARTBEAT_INTERVAL_SEC,
        "heartbeat_confirmed_max_age_sec": HEARTBEAT_CONFIRMED_MAX_AGE_SEC,
        "offline_after_sec": OFFLINE_AFTER_SEC,
        "state": ("functional" if functional_live else
                  ("heartbeat_only" if heartbeat_fresh else "offline")),
        "heartbeat_at_utc": str(selected.get("last_heartbeat_utc") or ""),
        "age_sec": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "account_snapshot_present": bool(snapshot),
        "account_snapshot_fresh": snapshot_fresh,
        "account_snapshot_at_utc": str(snapshot.get("received_at_utc") or ""),
        "account_snapshot_generated_at_utc": str(snapshot.get("generated_at_utc") or ""),
        "account_snapshot_warning": str(snapshot.get("generated_at_warning") or ""),
        "account_snapshot_age_sec": (
            round(snapshot_age, 1) if snapshot_age is not None else None),
        "account_count": len(accounts),
        "accounts": accounts,
        "summary": copy.deepcopy(snapshot.get("summary") or {}),
        "exporter_version": str(snapshot.get("exporter_version") or ""),
        "last_hello_utc": str(selected.get("last_hello_utc") or ""),
        "runtime_catalog": {
            "present": catalog_present,
            "fresh": catalog_fresh,
            "stale": bool(catalog_present and not catalog_fresh),
            "state": catalog_state,
            "age_sec": round(catalog_age, 1) if catalog_age is not None else None,
            "received_at_utc": str(runtime_catalog.get("received_at_utc") or ""),
            "generated_at_utc": str(runtime_catalog.get("generated_at_utc") or ""),
            "installation_id": str(selected.get("installation_id") or ""),
            "connection_id": str(selected.get("connection_id") or ""),
            "workspace_id": source_workspace,
            "connector_version": str(runtime_catalog.get("connector_version") or ""),
            "nt_version": str(runtime_catalog.get("nt_version") or ""),
            "catalog": copy.deepcopy(runtime_catalog) if catalog_present else {},
        },
    }



def installer_status() -> Dict[str, Any]:
    """Whether there is a signed package to hand someone, and why not.

    Onboarding begins with getting the program. An empty ``download_url`` is
    the honest answer while the package waits on Authenticode and the immutable
    release gate; the reason travels with it so the panel can say so instead of
    offering a button that goes nowhere.
    """
    return {
        "state": "blocked_release_gate",
        "download_url": "",
        "package_format": "verified_windows_zip",
        "manifest_signature": "ECDSA_P256_SHA256",
        "message": (
            "Подписанный установщик ещё не опубликован: ожидает Authenticode и "
            "immutable release gate. Локально собранная сборка проверена."
        ),
    }


def setup_payload(user_id: Any, *, workspace_id: str = "",
                  uses_owner_runtime: bool = False,
                  is_owner: bool = False) -> Dict[str, Any]:
    user = int(user_id or 0)
    if uses_owner_runtime and is_owner:
        workspace = workspaces.require_workspace_access(user, workspace_id=workspace_id)
        user_uuid = _user_uuid_for_legacy_id(user)
        now = time.time()
        with _LOCK:
            doc = _read_doc()
            changed = _refresh_states(doc, now)
            if changed:
                _write_doc(doc)
            rows = [
                _public_installation(row)
                for row in doc["installations"]
                if (_legacy_user_id(row.get("user_id")) == user
                    or (user_uuid and str(row.get("user_uuid") or "") == user_uuid))
            ]
        listed = {"ok": True, "workspace": workspace, "connections": rows}
    else:
        listed = list_installations(user, workspace_id=workspace_id)
    return {
        **listed,
        "owner_runtime": bool(uses_owner_runtime and is_owner),
        "transport": "production_connector",
        "protocol_version": PROTOCOL_VERSION,
        "server_origin": runtime_env.deployment_config().public_origin,
        "connector_paths": {
            "enroll": "/api/connector/v1/enroll",
            "challenge": "/api/connector/v1/challenge",
            "hello": "/api/connector/v1/hello",
            "heartbeat": "/api/connector/v1/heartbeat",
            "market_data": "/api/connector/v1/market-data",
            "poll": "/api/connector/v1/commands/poll",
            "result": "/api/connector/v1/commands/result",
        },
        "installer": installer_status(),
        "updater": {
            "state": "implemented_local_release_gate",
            "policy": "safe_restart",
            "channels": ["stable", "canary"],
            "post_update_health": "signed_hello_and_heartbeat",
            "rollback": "one_shot_last_known_good",
            "message": (
                "Внешний updater проверяет подпись и SHA-256, ждёт закрытия "
                "NinjaTrader и автоматически возвращает last-known-good при "
                "неуспешном post-update heartbeat."
            ),
        },
        "steps": [
            "Получите одноразовый код подключения для активной рабочей области.",
            "Введите код в signed StratForge Connector installer.",
            "Сверьте fingerprint устройства и дождитесь signed hello.",
            "Статус online появляется только после heartbeat от NinjaTrader.",
        ],
    }


def command_status(
    user_id: Any, *, workspace_id: str, command_id: Any,
) -> Dict[str, Any]:
    user = int(user_id or 0)
    workspace = workspaces.require_workspace_access(user, workspace_id=workspace_id)
    target = _safe_id(command_id, "command_id")
    with _LOCK:
        doc = _read_doc()
        _refresh_states(doc, time.time())
        command = next((
            row for row in doc["commands"]
            if str(row.get("workspace_id") or "") == str(workspace["workspace_id"])
            and str(row.get("command_id") or "") == target
        ), None)
        if command is None:
            raise ConnectorProtocolError(
                "Command не найдена.", 404, "command_not_found",
            )
        result = next((
            copy.deepcopy(row) for row in reversed(doc["results"])
            if str(row.get("command_id") or "") == target
        ), None)
    if result:
        result.pop("result_hash", None)
    return {
        "ok": True,
        "command": _public_command(command, include_payload=False),
        "result": result or {},
    }


def revoke_installation(
    user_id: Any, connection_id: Any, *, workspace_id: str = "",
) -> Dict[str, Any]:
    user = int(user_id or 0)
    workspace = workspaces.require_workspace_writer(user, workspace_id=workspace_id)
    workspace_value = str(workspace.get("workspace_id") or "")
    target = _safe_id(connection_id, "connection_id")
    now = time.time()
    with _COMMANDS_CHANGED:
        doc = _read_doc()
        installation = next((
            row for row in doc["installations"]
            if str(row.get("workspace_id") or "") == workspace_value
            and str(row.get("connection_id") or "") == target
        ), None)
        if installation is None:
            raise ConnectorProtocolError(
                "Connector connection не найдена.", 404, "connection_not_found",
            )
        installation["status"] = "revoked"
        installation["revoked_at_utc"] = _now_iso(now)
        for session in doc["sessions"]:
            if (
                str(session.get("installation_id") or "")
                == str(installation.get("installation_id") or "")
                and session.get("status") == "active"
            ):
                session["status"] = "revoked"
                session["ended_at_utc"] = _now_iso(now)
        for command in doc["commands"]:
            if (
                str(command.get("installation_id") or "")
                == str(installation.get("installation_id") or "")
                and command.get("status") not in TERMINAL_COMMAND_STATES
            ):
                command["status"] = "cancelled"
                command["finished_at_utc"] = _now_iso(now)
        _write_doc(doc)
        _COMMANDS_CHANGED.notify_all()
    _audit(
        "installation_revoked",
        user_id=user,
        workspace_id=workspace_value,
        installation_id=installation["installation_id"],
        connection_id=target,
    )
    return {"ok": True, "connection": _public_installation(installation)}


def readiness_status() -> Dict[str, Any]:
    if runtime_env.is_server_environment() and runtime_env.environment_explicit():
        from . import storage_router
        result = storage_router.document_repository_readiness("connectors")
        if result.get("ok"):
            return {"ok": True, "code": "ok"}
        return {
            "ok": False,
            "code": str(result.get("code") or "connector_repository_failed")[:64],
        }
    if not secure_store.available():
        return {"ok": False, "code": "connector_repository_unavailable"}
    try:
        path = _store_path()
        if path.is_file():
            raw = path.read_bytes()[: len(_MAGIC) + 8]
            if not raw.startswith(_MAGIC):
                return {"ok": False, "code": "connector_repository_failed"}
    except OSError:
        return {"ok": False, "code": "connector_repository_failed"}
    return {"ok": True, "code": "ok"}
