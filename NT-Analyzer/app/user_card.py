"""One user card, assembled once, rendered at two levels of detail.

The Cabinet and the Admin user page were describing the same person from
different code. Two assemblies of the same facts drift: a device revoked in one
view still looks live in the other, an identity retirement shows up in one
timeline and not the other, and there is no way to tell which of the two is
wrong. So there is exactly one builder here, and ``scope`` decides how much of
its output is returned -- never what is computed.

    scope="self"   the account looking at itself (Cabinet)
    scope="admin"  an operator looking at that same account (Admin)

Admin is a superset, not a parallel model. Everything the Cabinet shows, Admin
shows identically; Admin additionally sees operational detail (internal ids,
masked origin metadata, actor attribution) that an ordinary user has no reason
to read. If a fact appears in both, it came from the same line of code.

The card is built over the canonical models and nothing else:

    identities   sf_identity_history   (0014) -- current *and* retired, with
                                       valid_from/valid_to and why each ended
    machines     sf_physical_devices   (0015) -- real machines
    clients      sf_trusted_devices    (0015) -- browser profiles and app
                                       installations, bound to a machine only
                                       by a proven Connector pairing
    sessions     the auth document     -- live logins, each tied to its client

The device tree is deliberately three levels deep and never flattened. A
browser is not a machine, and two browsers are not one machine just because
they share a User-Agent -- grouping them without a proven binding is exactly
the inference the physical-device model exists to remove.
"""
from __future__ import annotations

import hmac
import time
from typing import Any, Dict, List, Optional

from . import account_auth, auth_identity, identity_history, physical_devices
from . import security_devices


SCOPE_SELF = "self"
SCOPE_ADMIN = "admin"
SCOPES = (SCOPE_SELF, SCOPE_ADMIN)

# How far back the security timeline reaches. Long enough to cover the retention
# window for security events (ADR-0003: 180 days), capped so one very active
# account cannot make the page unbounded.
TIMELINE_LIMIT = 200


class UserCardError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")


def _normalize_uuid(value: Any) -> str:
    return auth_identity.normalize_user_uuid(value)


def _iso(value: Any) -> str:
    return str(value or "")


# --------------------------------------------------------------------------- #
# Summary.
# --------------------------------------------------------------------------- #
def _summary(doc: Dict[str, Any], user: Dict[str, Any], *, scope: str,
             identities: List[Dict[str, Any]], devices: Dict[str, Any]) -> Dict[str, Any]:
    user_uuid = _normalize_uuid(account_auth._user_uuid(user))
    summary = {
        "user_uuid": user_uuid,
        "display_name": str(user.get("first_name") or user.get("username") or "").strip(),
        "username": str(user.get("username") or ""),
        "avatar_url": str(user.get("avatar_url") or ""),
        "role": str(user.get("role") or ""),
        "status": str(user.get("status") or ""),
        "is_owner": bool(user.get("is_owner")),
        "created_at_utc": _iso(user.get("created_at_utc")),
        "last_login_at_utc": _iso(user.get("last_login_at_utc")),
        "security": _risk(identities, devices),
    }
    if scope == SCOPE_ADMIN:
        # The legacy numeric id is an operational handle, not identity. It is
        # shown to operators because audit rows and support tickets still
        # reference it, and to nobody else.
        summary["legacy_user_id"] = int(user.get("user_id") or 0)
        summary["blocked_at_utc"] = _iso(user.get("blocked_at_utc"))
        summary["ux_mode"] = str(user.get("ux_mode") or "")
    return summary


def _risk(identities: List[Dict[str, Any]], devices: Dict[str, Any]) -> Dict[str, Any]:
    """A short, honest posture summary.

    Deliberately counts rather than a single score: "2 devices awaiting
    confirmation" is actionable, "risk 63" is not, and a score invites the
    reader to believe a precision that is not there.
    """
    machines = devices.get("machines") or []
    unbound = devices.get("unbound_clients") or []
    all_clients = [c for m in machines for c in (m.get("clients") or [])] + list(unbound)

    active_identities = [row for row in identities if row.get("state") == "active"]
    pending_devices = [
        c for c in all_clients if c.get("status") == security_devices.STATUS_PENDING
    ]
    trusted_devices = [
        c for c in all_clients if c.get("status") == security_devices.STATUS_TRUSTED
    ]
    live_sessions = [s for c in all_clients for s in (c.get("sessions") or [])]

    notes: List[str] = []
    if not active_identities:
        notes.append("no_verified_identity")
    if len(active_identities) < 2:
        # One channel means one way back in. Worth saying plainly rather than
        # burying in a score.
        notes.append("single_recovery_channel")
    if pending_devices:
        notes.append("devices_awaiting_confirmation")
    return {
        "verified_identities": len(active_identities),
        "trusted_devices": len(trusted_devices),
        "pending_devices": len(pending_devices),
        "known_machines": len(machines),
        "live_sessions": len(live_sessions),
        "attention": notes,
    }


# --------------------------------------------------------------------------- #
# Identities: what is current, what it replaced, and why.
# --------------------------------------------------------------------------- #
def _identities(doc: Dict[str, Any], user_uuid: str, *, scope: str) -> List[Dict[str, Any]]:
    rows = identity_history.history_for_user(doc, user_uuid)
    public = identity_history.public_history(rows)
    for row, source in zip(public, rows):
        row["is_current"] = row.get("state") == identity_history.STATE_ACTIVE
        # Why it ended, in the shape the timeline reads. An identity that was
        # retired because a new one replaced it is a different event from one
        # that was revoked, and collapsing them loses the distinction that
        # matters when reading a compromise.
        row["ended_reason"] = (
            "" if row["is_current"]
            else ("revoked" if row.get("state") == identity_history.STATE_REVOKED
                  else "replaced")
        )
        if scope == SCOPE_ADMIN:
            row["history_id"] = str(source.get("history_id") or "")
            row["actor_source"] = str(source.get("actor_source") or "")
    # Newest first, current entries above retired ones for the same provider.
    public.sort(key=lambda r: (not r["is_current"], str(r.get("valid_from") or "")),
                reverse=False)
    public.sort(key=lambda r: str(r.get("valid_from") or ""), reverse=True)
    public.sort(key=lambda r: not r["is_current"])
    return public


def _replacement_timeline(identities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each provider, the chain of what replaced what.

    Built from the same rows the identity list uses -- not a second query --
    so the two can never disagree about when something was retired.
    """
    by_provider: Dict[str, List[Dict[str, Any]]] = {}
    for row in identities:
        by_provider.setdefault(str(row.get("provider") or ""), []).append(row)
    chains = []
    for provider, rows in sorted(by_provider.items()):
        ordered = sorted(rows, key=lambda r: str(r.get("valid_from") or ""))
        if len(ordered) < 2:
            continue
        steps = []
        for previous, current in zip(ordered, ordered[1:]):
            steps.append({
                "from": previous.get("display_value"),
                "to": current.get("display_value"),
                "at_utc": current.get("valid_from"),
                "reason": current.get("replacement_reason") or previous.get("ended_reason") or "",
            })
        chains.append({"provider": provider, "steps": steps})
    return chains


# --------------------------------------------------------------------------- #
# Devices: machine -> client -> session, never flattened.
# --------------------------------------------------------------------------- #
def _sessions_for_client(doc: Dict[str, Any], client_id: str, *,
                         scope: str) -> List[Dict[str, Any]]:
    now = time.time()
    out = []
    for row in doc.get("sessions") or []:
        if not isinstance(row, dict):
            continue
        if not hmac.compare_digest(str(row.get("trusted_device_id") or ""), client_id):
            continue
        revoked = bool(row.get("revoked"))
        expired = float(row.get("expires_at") or 0) <= now
        if revoked or expired:
            continue
        session = {
            "session_id": account_auth._session_id(row),
            "created_at_utc": _iso(row.get("created_at_utc")),
            "expires_at": float(row.get("expires_at") or 0),
            "environment": str(row.get("environment") or ""),
            "client": str(row.get("client") or ""),
        }
        if scope == SCOPE_ADMIN:
            # Masked origin only, as audit metadata. Never identity, and never
            # the raw address.
            session["last_region"] = account_auth._mask_ip(str(row.get("ip") or ""))
        out.append(session)
    out.sort(key=lambda s: str(s.get("created_at_utc") or ""), reverse=True)
    return out


def _client_view(doc: Dict[str, Any], client: Dict[str, Any], *,
                 active_ids: frozenset, scope: str) -> Dict[str, Any]:
    public = security_devices._public_device(client, active_ids)
    view = {
        "device_id": public["device_id"],
        "kind": "connector" if public["device_type"] == "connector" else "browser_app",
        "device_type": public["device_type"],
        "display_name": public["display_name"],
        "client": public["client"],
        "os_family": public["os_family"],
        "os_version": public["os_version"],
        "app_version": public["app_version"],
        "status": public["status"],
        "online": public["online"],
        "confirmation_provider": public["confirmation_provider"],
        "first_seen_at_utc": public["first_seen_at_utc"],
        "last_seen_at_utc": public["last_seen_at_utc"],
        "confirmed_at_utc": public["confirmed_at_utc"],
        "revoked_at_utc": public["revoked_at_utc"],
        "bound_via": public["bound_via"],
        # Which machine this client belongs to, empty when none is proven. The
        # UI needs it to render the tree, and a consumer that only checked
        # bound_via would have to infer the id from position in the payload.
        "physical_device_id": public["physical_device_id"],
        "sessions": _sessions_for_client(doc, public["device_id"], scope=scope),
        # The two terminations are different actions with different blast
        # radius, so they are advertised separately and never behind one button.
        "actions": {
            "end_session": True,
            "revoke_client": public["status"] in security_devices._ACTIVE_STATUSES,
        },
    }
    if scope == SCOPE_ADMIN:
        view["last_region"] = public["last_region"]
        view["connector_installation_id_present"] = bool(
            public["connector_installation_id"]
        )
    return view


def _devices(doc: Dict[str, Any], user_uuid: str, *, scope: str) -> Dict[str, Any]:
    active_ids = security_devices._active_device_ids(doc)
    owned = [
        row for row in doc.get("trusted_devices") or []
        if isinstance(row, dict)
        and hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), user_uuid)
    ]

    machines = []
    for machine in physical_devices._machines(doc):
        if not isinstance(machine, dict):
            continue
        if not hmac.compare_digest(_normalize_uuid(machine.get("user_uuid")), user_uuid):
            continue
        machine_id = str(machine.get("physical_device_id") or "")
        clients = [
            _client_view(doc, client, active_ids=active_ids, scope=scope)
            for client in owned
            if hmac.compare_digest(str(client.get("physical_device_id") or ""), machine_id)
        ]
        public = physical_devices.public_machine(machine)
        view = {
            "physical_device_id": public["physical_device_id"],
            "display_name": public["display_name"],
            "os_family": public["os_family"],
            "os_version": public["os_version"],
            "status": public["status"],
            "confirmation_provider": public["confirmation_provider"],
            "first_seen_at_utc": public["first_seen_at_utc"],
            "last_seen_at_utc": public["last_seen_at_utc"],
            "confirmed_at_utc": public["confirmed_at_utc"],
            "revoked_at_utc": public["revoked_at_utc"],
            "clients": sorted(clients, key=lambda c: c["kind"] != "connector"),
            # Revoking a machine takes every client on it and their sessions.
            # It is a separate action from revoking one client, and the card
            # says so rather than leaving the reader to guess the blast radius.
            "actions": {
                "revoke_physical_device":
                    public["status"] in physical_devices.ACTIVE_STATUSES,
            },
        }
        if scope == SCOPE_ADMIN:
            view["last_region"] = public["last_region"]
        machines.append(view)
    machines.sort(key=lambda m: str(m.get("last_seen_at_utc") or ""), reverse=True)

    # Clients belonging to no known machine. This is the normal state for a
    # browser: it joins a machine only through a Connector-attested pairing, and
    # listing it under an invented machine would be a guess presented as a fact.
    unbound = [
        _client_view(doc, client, active_ids=active_ids, scope=scope)
        for client in owned
        if not str(client.get("physical_device_id") or "")
    ]
    unbound.sort(key=lambda c: str(c.get("last_seen_at_utc") or ""), reverse=True)

    return {
        "machines": machines,
        "unbound_clients": unbound,
        "unbound_explanation": (
            "Клиент привязывается к компьютеру только кодом привязки от "
            "подтверждённого Connector этого компьютера. Браузеры без такой "
            "привязки показаны отдельно и не приписаны ни к какой машине."
        ),
    }


def _environments(doc: Dict[str, Any], user_uuid: str) -> List[str]:
    """Environments this account actually has sessions in."""
    seen = []
    for row in doc.get("sessions") or []:
        if not isinstance(row, dict):
            continue
        environment = str(row.get("environment") or "").strip()
        if environment and environment not in seen:
            seen.append(environment)
    return sorted(seen)


# --------------------------------------------------------------------------- #
# Security timeline.
# --------------------------------------------------------------------------- #
# Events that belong on a security timeline, and how each reads. Anything not
# listed is not security-relevant and would only add noise.
_TIMELINE_EVENTS = {
    "login": ("login", "Вход в аккаунт"),
    "login.success": ("login", "Вход в аккаунт"),
    "login.failed": ("login", "Неудачная попытка входа"),
    "session.revoked": ("session", "Сессия завершена"),
    "session.revoked_by_device": ("session", "Сессии устройства завершены"),
    "identity.linked": ("identity", "Привязан идентификатор"),
    "identity.changed": ("identity", "Идентификатор изменён"),
    "identity.retired": ("identity", "Идентификатор выведен из использования"),
    "identity.revoked": ("identity", "Идентификатор отозван"),
    "identity.unlinked": ("identity", "Идентификатор отвязан"),
    "device.pending": ("device", "Новое устройство ожидает подтверждения"),
    "device.approved": ("device", "Устройство подтверждено"),
    "device.rejected": ("device", "Устройство отклонено"),
    "device.revoked": ("device", "Устройство отозвано"),
    "machine.pending": ("machine", "Новый компьютер обнаружен"),
    "machine.approved": ("machine", "Компьютер подтверждён"),
    "machine.revoked": ("machine", "Компьютер отозван"),
    "machine.pairing_issued": ("machine", "Выдан код привязки"),
    "machine.client_bound": ("machine", "Клиент привязан к компьютеру"),
    "user.blocked": ("admin", "Аккаунт заблокирован"),
    "user.unblocked": ("admin", "Аккаунт разблокирован"),
    "user.role_changed": ("admin", "Изменена роль"),
    "user.deleted": ("admin", "Аккаунт удалён"),
}


def _timeline(user: Dict[str, Any], *, scope: str) -> List[Dict[str, Any]]:
    """Security events for this account, newest first.

    Read from the audit trail rather than reconstructed from current state:
    current state says a device is revoked, the audit says when and by whom,
    and only the second answers "what happened to my account".
    """
    legacy_id = int(user.get("user_id") or 0)
    rows = _read_audit(limit=TIMELINE_LIMIT * 4)
    out = []
    for row in rows:
        event = str(row.get("event") or row.get("event_type") or "")
        mapped = _TIMELINE_EVENTS.get(event)
        if not mapped:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        subject = payload.get("user_id", row.get("user_id"))
        try:
            subject_id = int(subject or 0)
        except (TypeError, ValueError):
            subject_id = 0
        if subject_id != legacy_id:
            continue
        category, label = mapped
        entry = {
            "at_utc": _iso(row.get("timestamp") or row.get("timestamp_utc")
                           or row.get("occurred_at")),
            "category": category,
            "event": event,
            "label": label,
        }
        if scope == SCOPE_ADMIN:
            # Who did it and from roughly where. An administrative action taken
            # on someone's account is exactly the thing an operator has to be
            # able to attribute.
            actor = payload.get("owner_id") or row.get("owner_id") or 0
            entry["actor_user_id"] = int(actor or 0)
            entry["origin"] = account_auth._mask_ip(str(payload.get("ip") or ""))
            entry["detail"] = {
                key: payload[key] for key in ("device_id", "physical_device_id",
                                              "provider", "count", "reason")
                if key in payload
            }
        out.append(entry)
        if len(out) >= TIMELINE_LIMIT:
            break
    return out


def _read_audit(*, limit: int) -> List[Dict[str, Any]]:
    """Audit rows from wherever this environment keeps them.

    Production and Canary write to PostgreSQL; Development writes JSONL. Both
    are read here so the timeline is not an empty panel in one of them.
    """
    try:
        from . import storage_router

        if storage_router.production_enabled():
            from .production_storage import AuditRepository, Scope, get_client

            rows = AuditRepository(get_client(production=True)).list(
                scope=Scope.global_service_scope(), limit=min(1000, limit),
            )
            return [
                {
                    "event": row.get("event_type"),
                    "timestamp": row.get("occurred_at"),
                    "payload": row.get("payload") or {},
                    "user_id": row.get("user_id"),
                }
                for row in rows
            ]
    except Exception:
        # A timeline that cannot be read is an empty timeline, not a failed
        # page: the rest of the card is still worth showing.
        return []

    import json

    path = account_auth._audit_path()
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows[-limit:][::-1]


# --------------------------------------------------------------------------- #
# Admin-only extras.
#
# Additions to the same card, not a second card. They are absent from the self
# view because the builder does not produce them for that scope -- the renderer
# does not decide what to hide.
# --------------------------------------------------------------------------- #
def _admin_extras(user: Dict[str, Any], user_uuid: str) -> Dict[str, Any]:
    grants = []
    try:
        from . import permissions

        resolved = permissions.resolve_admin_capabilities(user)
        grants = sorted(name for name, enabled in (resolved or {}).items() if enabled)
    except Exception:
        grants = []

    workspaces = []
    try:
        from . import workspaces as workspace_store

        footprint = workspace_store.user_footprint(
            user_uuid, int(user.get("user_id") or 0),
        )
        for row in footprint.get("owned_workspaces") or footprint.get("owned") or []:
            entry = row if isinstance(row, dict) else {"workspace_id": str(row)}
            workspaces.append({
                "workspace_id": str(entry.get("workspace_id") or ""),
                "kind": str(entry.get("kind") or ""),
                "status": str(entry.get("status") or ""),
                "role": "owner",
            })
        for row in footprint.get("memberships") or []:
            if not isinstance(row, dict):
                continue
            workspace_id = str(row.get("workspace_id") or "")
            if any(w["workspace_id"] == workspace_id for w in workspaces):
                continue
            workspaces.append({
                "workspace_id": workspace_id,
                "kind": "",
                "status": str(row.get("status") or ""),
                "role": str(row.get("role") or "member"),
            })
    except Exception:
        # A workspace store that cannot be read costs one panel, not the card.
        workspaces = []

    return {"grants": grants, "workspaces": workspaces}


# --------------------------------------------------------------------------- #
# The one entry point.
# --------------------------------------------------------------------------- #
def build(*, actor_id: Any, target_id: Any = None, scope: str = SCOPE_SELF) -> Dict[str, Any]:
    """Assemble the card for ``target_id`` as seen by ``actor_id``.

    ``scope="self"`` ignores ``target_id`` entirely: an account can only ask
    for its own card, and letting it name a subject would make the id the
    authorization boundary.
    """
    if scope not in SCOPES:
        raise UserCardError("Недопустимая область карточки.", 400, code="scope_invalid")
    try:
        actor = int(actor_id or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor <= 0:
        raise UserCardError("Требуется вход.", 401, code="auth_required")

    with account_auth._LOCK:
        doc = account_auth._read_doc()
        if scope == SCOPE_ADMIN:
            # Authorization first, and by capability rather than by role name.
            account_auth._require_admin_capability_in_doc(doc, actor, "users.manage")
            try:
                subject = int(target_id or 0)
            except (TypeError, ValueError):
                subject = 0
        else:
            subject = actor
        if subject <= 0:
            raise UserCardError("Пользователь не указан.", 400, code="user_required")

        user = account_auth._user(doc, subject)
        if user is None:
            raise UserCardError("Пользователь не найден.", 404, code="user_not_found")

        # Expiring stale devices before rendering, so the card never shows a
        # device as trusted when the next request would call it expired.
        if security_devices._expire_stale(doc):
            account_auth._write_doc(doc)

        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        identities = _identities(doc, user_uuid, scope=scope)
        devices = _devices(doc, user_uuid, scope=scope)
        environments = _environments(doc, user_uuid)
        summary = _summary(doc, user, scope=scope, identities=identities, devices=devices)
        step_up = security_devices._available_providers(doc, user)
        extras = _admin_extras(user, user_uuid) if scope == SCOPE_ADMIN else None

    return {
        "ok": True,
        "scope": scope,
        "summary": summary,
        "identities": {
            "current": [row for row in identities if row["is_current"]],
            "history": [row for row in identities if not row["is_current"]],
            "replacement_timeline": _replacement_timeline(identities),
            "step_up_providers": step_up,
        },
        "devices": devices,
        "environments": environments,
        "timeline": _timeline(user, scope=scope),
        **({"admin": extras} if extras is not None else {}),
        "policy": {
            "device_confirmation_required": True,
            "trust_ttl_sec": security_devices.DEVICE_TRUST_TTL_SEC,
            "pairing_ttl_sec": physical_devices.PAIRING_TTL_SEC,
        },
    }
