"""Physical machines, and how clients are bound to them (Phase 5).

The security model has three levels:

    physical device  one real machine
      client         one browser profile or one app installation
        session      one login

``security_devices`` owns the middle level and always has. This module owns the
top one, and the single rule that makes it worth having: **a machine is never
inferred.**

User-Agent, IP address, hostname and account name were the obvious candidates
for grouping clients into machines and every one of them is wrong. They are
identical across all users of a deployment, they change without the machine
changing, and they are attacker-controlled. Grouping by them would both split
one laptop into a new "machine" on every browser update and merge two different
people's laptops into one record.

So the only source of machine identity is a hardware-bound credential the
Windows Connector holds. A browser has no such thing and can never claim one on
its own: it joins a machine only by redeeming a short-lived pairing code issued
by an already-trusted Connector running on that same machine. A client that
belongs to no known machine is a normal state, not a degraded one -- it is what
every browser is until the user deliberately pairs it.

Trust is per level. A trusted machine does not make a new browser profile on it
trusted, and revoking one browser profile does not revoke the machine. Revoking
a machine does cascade -- that direction is the whole point of the level: "this
laptop was stolen" has to kill everything running on it in one action.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from . import account_auth, auth_identity


STATUS_PENDING = "pending"
STATUS_TRUSTED = "trusted"
STATUS_REVOKED = "revoked"
STATUS_EXPIRED = "expired"
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_TRUSTED)

BOUND_VIA_CONNECTOR_SELF = "connector_self"
BOUND_VIA_ATTESTED_PAIRING = "attested_pairing"
BINDING_METHODS = (BOUND_VIA_CONNECTOR_SELF, BOUND_VIA_ATTESTED_PAIRING)

# A pairing code is read off one screen and typed into another, so it is short
# lived by design and single use. It is also the only path by which a browser
# can ever join a machine, which is why it is minted exclusively by a Connector
# that is already trusted.
PAIRING_TTL_SEC = 5 * 60
PAIRING_CODE_DIGITS = 8
PAIRING_MAX_ATTEMPTS = 5


class PhysicalDeviceError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")


def _now() -> float:
    return time.time()


def _normalize_uuid(value: Any) -> str:
    return auth_identity.normalize_user_uuid(value)


def machine_key_hash(user_uuid: str, machine_credential: str) -> str:
    """Digest of a machine credential, scoped to one account.

    Migration 0015 computes this identically in SQL to backfill Connectors that
    already existed. The separator is '|' and not a NUL byte because PostgreSQL
    text cannot carry a NUL; the UUID between separators is fixed-length, so the
    encoding is still unambiguous. Changing either side alone would make a known
    Connector register as a brand new machine.
    """
    canonical = _normalize_uuid(user_uuid)
    credential = str(machine_credential or "").strip()
    if not canonical or not credential:
        return ""
    basis = f"machine-key/v1|{canonical}|{credential}"
    return hashlib.sha256(basis.encode("utf-8", errors="ignore")).hexdigest()


# --------------------------------------------------------------------------- #
# Store helpers. Machines live in the same DPAPI document and under the same
# lock as accounts, clients and sessions, so a pairing can never half-apply.
# --------------------------------------------------------------------------- #
def _machines(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = doc.get("physical_devices")
    if not isinstance(rows, list):
        rows = []
        doc["physical_devices"] = rows
    return rows


def _pairings(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = doc.get("device_pairings")
    if not isinstance(rows, list):
        rows = []
        doc["device_pairings"] = rows
    return rows


def _owned(doc: Dict[str, Any], user_uuid: str, physical_device_id: str) -> Dict[str, Any]:
    canonical = _normalize_uuid(user_uuid)
    target = str(physical_device_id or "").strip()
    if not canonical:
        raise PhysicalDeviceError("Требуется вход.", 401, code="auth_required")
    if not target:
        raise PhysicalDeviceError("Не указано устройство.", 400, code="machine_required")
    for row in _machines(doc):
        if not isinstance(row, dict):
            continue
        if not hmac.compare_digest(str(row.get("physical_device_id") or ""), target):
            continue
        # Ownership is checked against the canonical UUID server-side; a client
        # can only ever name an id, never assert whose it is.
        if not hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), canonical):
            raise PhysicalDeviceError("Устройство не найдено.", 404, code="machine_not_found")
        return row
    raise PhysicalDeviceError("Устройство не найдено.", 404, code="machine_not_found")


def find_machine(doc: Dict[str, Any], user_uuid: str, physical_device_id: str) -> Optional[Dict[str, Any]]:
    try:
        return _owned(doc, user_uuid, physical_device_id)
    except PhysicalDeviceError:
        return None


def _default_name(os_family: str) -> str:
    """A neutral name for a machine nobody has named yet.

    Deliberately not the server's COMPUTERNAME: that is the same string for
    every user of a deployment and describes the wrong computer entirely.
    """
    family = str(os_family or "").strip()
    return f"Рабочая станция · {family}"[:160] if family else "Рабочая станция"


# --------------------------------------------------------------------------- #
# Observation. Called from security_devices while a session is being created.
# --------------------------------------------------------------------------- #
def observe_machine(
    doc: Dict[str, Any],
    user: Dict[str, Any],
    *,
    machine_credential: str,
    os_family: str = "",
    os_version: str = "",
    display_name: str = "",
    ip: str = "",
) -> Tuple[Optional[Dict[str, Any]], List[Tuple[str, Dict[str, Any]]]]:
    """Register or touch the machine identified by ``machine_credential``.

    Returns ``(machine, audit_events)``. Without a credential there is no
    machine -- the caller gets ``None`` and the client stays unbound, which is
    the correct answer for every browser.

    A revoked or expired machine is never reused: presenting its credential
    again creates a fresh ``pending`` record, so trust cannot come back by
    reconnecting.
    """
    user_uuid = _normalize_uuid(account_auth._user_uuid(user))
    key_hash = machine_key_hash(user_uuid, machine_credential)
    if not user_uuid or not key_hash:
        return None, []

    now_iso = account_auth._now_iso()
    events: List[Tuple[str, Dict[str, Any]]] = []
    machine = None
    for row in reversed(_machines(doc)):
        if not isinstance(row, dict):
            continue
        if not hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), user_uuid):
            continue
        if not hmac.compare_digest(str(row.get("machine_key_hash") or ""), key_hash):
            continue
        if str(row.get("status") or "") in ACTIVE_STATUSES:
            machine = row
            break

    if machine is None:
        machine = {
            "physical_device_id": str(uuid.uuid4()),
            "user_uuid": user_uuid,
            "legacy_user_id": int(user.get("user_id") or 0),
            "machine_key_hash": key_hash,
            "display_name": (str(display_name or "").strip()[:160]
                             or _default_name(os_family)),
            "os_family": str(os_family or "")[:40],
            "os_version": str(os_version or "")[:40],
            "status": STATUS_PENDING,
            "confirmation_provider": "",
            "first_seen_at_utc": now_iso,
            "last_seen_at_utc": now_iso,
            "confirmed_at_utc": "",
            "revoked_at_utc": "",
            "expires_at_utc": "",
            "audit_metadata": {"last_ip": account_auth._mask_ip(ip)},
        }
        _machines(doc).append(machine)
        events.append((
            "machine.pending",
            {"physical_device_id": machine["physical_device_id"]},
        ))
    else:
        machine["last_seen_at_utc"] = now_iso
        if os_family:
            machine["os_family"] = str(os_family)[:40]
        if os_version:
            machine["os_version"] = str(os_version)[:40]
        if display_name:
            machine["display_name"] = str(display_name).strip()[:160]
        meta = machine.get("audit_metadata")
        meta = meta if isinstance(meta, dict) else {}
        meta["last_ip"] = account_auth._mask_ip(ip)
        machine["audit_metadata"] = meta
    return machine, events


def bind_client(
    client: Dict[str, Any],
    machine: Dict[str, Any],
    *,
    bound_via: str,
) -> None:
    """Attach a client to a machine. The only two callers are the Connector
    registering itself and a redeemed pairing code -- there is deliberately no
    third way in."""
    if bound_via not in BINDING_METHODS:
        raise PhysicalDeviceError("Недопустимый способ привязки.", 400, code="bind_via_invalid")
    client["physical_device_id"] = str(machine.get("physical_device_id") or "")
    client["bound_via"] = bound_via


# --------------------------------------------------------------------------- #
# Pairing: the one path from a browser to a machine.
# --------------------------------------------------------------------------- #
def _pairing_hash(pairing_id: str, salt: str, code: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        str(code or "").encode("ascii", errors="ignore"),
        (str(pairing_id) + ":" + str(salt)).encode("utf-8"),
        120_000,
    ).hex()


def _prune_pairings(doc: Dict[str, Any]) -> None:
    now = _now()
    kept = []
    for row in _pairings(doc):
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") == "pending" and float(row.get("expires_at") or 0) <= now:
            row["status"] = STATUS_EXPIRED
        # Consumed and expired codes are kept only long enough to answer "was
        # this code already used", then dropped.
        if float(row.get("expires_at") or 0) + PAIRING_TTL_SEC <= now:
            continue
        kept.append(row)
    doc["device_pairings"] = kept[-200:]


def issue_pairing_code(
    doc: Dict[str, Any],
    *,
    user_uuid: str,
    machine: Dict[str, Any],
    issuing_client_id: str,
) -> Tuple[str, Dict[str, Any]]:
    """Mint a one-time code that lets one browser join ``machine``.

    Only a trusted Connector may call this. A pending Connector cannot: it has
    not itself been confirmed, so letting it hand out machine membership would
    make the confirmation step meaningless.

    Returns ``(code, pairing_row)``. The code is returned exactly once, to the
    Connector that asked for it, and only its PBKDF2 hash is stored.
    """
    canonical = _normalize_uuid(user_uuid)
    if str(machine.get("status") or "") != STATUS_TRUSTED:
        raise PhysicalDeviceError(
            "Привязку может выдать только подтверждённое устройство.",
            409, code="machine_not_trusted",
        )
    if not hmac.compare_digest(_normalize_uuid(machine.get("user_uuid")), canonical):
        raise PhysicalDeviceError("Устройство не найдено.", 404, code="machine_not_found")

    _prune_pairings(doc)
    # One live code per machine: a second request replaces the first rather than
    # leaving two valid codes in the wild.
    for row in _pairings(doc):
        if (isinstance(row, dict)
                and str(row.get("status") or "") == "pending"
                and hmac.compare_digest(
                    str(row.get("physical_device_id") or ""),
                    str(machine.get("physical_device_id") or ""))):
            row["status"] = "superseded"

    pairing_id = "pair_" + secrets.token_hex(12)
    salt = secrets.token_hex(16)
    code = "".join(secrets.choice("0123456789") for _ in range(PAIRING_CODE_DIGITS))
    row = {
        "pairing_id": pairing_id,
        "user_uuid": canonical,
        "physical_device_id": str(machine.get("physical_device_id") or ""),
        "issued_by_client_id": str(issuing_client_id or ""),
        "code_hash": _pairing_hash(pairing_id, salt, code),
        "code_salt": salt,
        "status": "pending",
        "attempts": 0,
        "created_at": _now(),
        "expires_at": _now() + PAIRING_TTL_SEC,
    }
    _pairings(doc).append(row)
    return code, row


def redeem_pairing_code(
    doc: Dict[str, Any],
    *,
    user_uuid: str,
    code: str,
    client: Dict[str, Any],
) -> Dict[str, Any]:
    """Bind ``client`` to the machine whose live pairing code matches ``code``.

    Redeeming establishes membership, not trust: the browser is now known to
    run on that machine and still has to be confirmed as a client in its own
    right. That separation is what keeps a stolen pairing code from being a
    full account compromise.
    """
    canonical = _normalize_uuid(user_uuid)
    if not canonical:
        raise PhysicalDeviceError("Требуется вход.", 401, code="auth_required")
    supplied = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(supplied) != PAIRING_CODE_DIGITS:
        raise PhysicalDeviceError("Неверный код привязки.", 400, code="pairing_code_invalid")

    _prune_pairings(doc)
    now = _now()
    for row in reversed(_pairings(doc)):
        if not isinstance(row, dict) or str(row.get("status") or "") != "pending":
            continue
        if not hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), canonical):
            continue
        if float(row.get("expires_at") or 0) <= now:
            continue
        attempts = int(row.get("attempts") or 0)
        if attempts >= PAIRING_MAX_ATTEMPTS:
            row["status"] = "failed"
            continue
        row["attempts"] = attempts + 1
        expected = str(row.get("code_hash") or "")
        actual = _pairing_hash(
            str(row.get("pairing_id") or ""), str(row.get("code_salt") or ""), supplied,
        )
        if not hmac.compare_digest(expected, actual):
            continue
        machine = _owned(doc, canonical, str(row.get("physical_device_id") or ""))
        if str(machine.get("status") or "") != STATUS_TRUSTED:
            raise PhysicalDeviceError(
                "Устройство больше не подтверждено.", 409, code="machine_not_trusted",
            )
        row["status"] = "consumed"
        row["consumed_at"] = now
        bind_client(client, machine, bound_via=BOUND_VIA_ATTESTED_PAIRING)
        return machine
    raise PhysicalDeviceError("Неверный или истёкший код привязки.", 400, code="pairing_code_invalid")


# --------------------------------------------------------------------------- #
# Trust and revocation.
# --------------------------------------------------------------------------- #
def trust_machine(machine: Dict[str, Any], *, provider: str) -> None:
    machine["status"] = STATUS_TRUSTED
    machine["confirmation_provider"] = str(provider or "")
    machine["confirmed_at_utc"] = account_auth._now_iso()
    machine["revoked_at_utc"] = ""


def clients_on(doc: Dict[str, Any], physical_device_id: str) -> List[Dict[str, Any]]:
    target = str(physical_device_id or "")
    if not target:
        return []
    rows = doc.get("trusted_devices")
    rows = rows if isinstance(rows, list) else []
    return [
        row for row in rows
        if isinstance(row, dict)
        and hmac.compare_digest(str(row.get("physical_device_id") or ""), target)
    ]


def revoke_machine(doc: Dict[str, Any], machine: Dict[str, Any], *, reason: str) -> Dict[str, int]:
    """Revoke a machine and everything running on it.

    This is the direction that cascades. "That laptop is gone" has to take its
    browser profiles and their sessions with it in one action, otherwise the
    user has to hunt down each client individually and any one they miss is
    still logged in.
    """
    from . import security_devices

    machine["status"] = STATUS_REVOKED
    machine["revoked_at_utc"] = account_auth._now_iso()
    machine["expires_at_utc"] = ""

    clients = 0
    sessions = 0
    for client in clients_on(doc, str(machine.get("physical_device_id") or "")):
        if str(client.get("status") or "") == security_devices.STATUS_REVOKED:
            continue
        sessions += security_devices._apply_revoke(doc, client, reason=reason)
        clients += 1
    # Any live pairing code the machine had handed out dies with it.
    for row in _pairings(doc):
        if (isinstance(row, dict)
                and str(row.get("status") or "") == "pending"
                and hmac.compare_digest(
                    str(row.get("physical_device_id") or ""),
                    str(machine.get("physical_device_id") or ""))):
            row["status"] = "revoked"
    return {"clients": clients, "sessions": sessions}


# --------------------------------------------------------------------------- #
# Public projection.
# --------------------------------------------------------------------------- #
def public_machine(
    machine: Dict[str, Any],
    *,
    clients: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Caller-facing view. The machine key hash never leaves the server."""
    rows = clients or []
    return {
        "physical_device_id": str(machine.get("physical_device_id") or ""),
        "display_name": str(machine.get("display_name") or "Рабочая станция"),
        "os_family": str(machine.get("os_family") or ""),
        "os_version": str(machine.get("os_version") or ""),
        "status": str(machine.get("status") or STATUS_PENDING),
        "confirmation_provider": str(machine.get("confirmation_provider") or ""),
        "first_seen_at_utc": str(machine.get("first_seen_at_utc") or ""),
        "last_seen_at_utc": str(machine.get("last_seen_at_utc") or ""),
        "confirmed_at_utc": str(machine.get("confirmed_at_utc") or ""),
        "revoked_at_utc": str(machine.get("revoked_at_utc") or ""),
        "client_count": len(rows),
        "client_ids": [str(row.get("device_id") or "") for row in rows],
        # Masked, coarse origin only -- audit metadata, never identity.
        "last_region": str((machine.get("audit_metadata") or {}).get("last_ip") or ""),
    }


def list_machines(doc: Dict[str, Any], user_uuid: str) -> List[Dict[str, Any]]:
    canonical = _normalize_uuid(user_uuid)
    rows = []
    for machine in _machines(doc):
        if not isinstance(machine, dict):
            continue
        if not hmac.compare_digest(_normalize_uuid(machine.get("user_uuid")), canonical):
            continue
        rows.append(public_machine(
            machine, clients=clients_on(doc, str(machine.get("physical_device_id") or "")),
        ))
    rows.sort(key=lambda item: str(item.get("last_seen_at_utc") or ""), reverse=True)
    return rows
