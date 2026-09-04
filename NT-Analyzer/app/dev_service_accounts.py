"""Development-only service accounts for the AI copilots (Claude, GPT).

These give Claude and GPT their own accounts with owner-level authority over the
*owner's* workspace and data (so they see the same strategies, NinjaTrader and
agents), while every action is audited under a distinct ``user_id`` instead of
the human owner. Login bypasses Telegram only on localhost and is impossible in
Canary/Production:

  * ``available()`` is true only in Development, and
  * ``login(...)`` additionally requires a loopback request.

The service accounts are not global owners in the account store; owner-equivalent
capability is granted only inside the localhost Development request context
(``server._dev_service_context``). The reserved id band keeps them clear of real
Telegram ids and of the dev-preview persona band.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import account_auth, observability, runtime_env, workspaces

# Reserved deterministic id band. Kept clear of real Telegram ids (~10 digits)
# and of the dev-preview persona band (9_600_000_000_000_000), and — unlike that
# band — inside the JavaScript safe-integer range so the id never loses
# precision if it round-trips through the browser.
_SERVICE_BASE = 9_300_000_000_000

SERVICE_ACCOUNTS: Dict[str, Dict[str, Any]] = {
    "claude": {
        "uid": _SERVICE_BASE + 1,
        "label": "Claude · служебный (dev)",
        "first_name": "Claude",
        "last_name": "· служебный",
        "username": "svc_claude",
    },
    "gpt": {
        "uid": _SERVICE_BASE + 2,
        "label": "GPT · служебный (dev)",
        "first_name": "GPT",
        "last_name": "· служебный",
        "username": "svc_gpt",
    },
}

_UID_TO_ACTOR = {spec["uid"]: actor for actor, spec in SERVICE_ACCOUNTS.items()}


class DevServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = code or "dev_service_error"


def available() -> bool:
    """True only in Development; never in Canary/Production."""
    return runtime_env.is_development()


def is_service_uid(user_id: Any) -> bool:
    try:
        return int(user_id or 0) in _UID_TO_ACTOR
    except (TypeError, ValueError):
        return False


def actor_for_uid(user_id: Any) -> str:
    try:
        return _UID_TO_ACTOR.get(int(user_id or 0), "")
    except (TypeError, ValueError):
        return ""


def _audit(event_type: str, **values: Any) -> None:
    """Persist a distinct audit record for the service account's action."""
    try:
        path = runtime_env.data_path("audit") / "dev-service-accounts.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": str(event_type),
            **{k: observability.redact(v, key=k) for k, v in values.items()},
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 — audit must never break the request
        pass


def ensure_service_accounts() -> Dict[str, Any]:
    """Create/refresh the Claude and GPT accounts bound to the owner's workspace."""
    if not available():
        raise DevServiceError("Служебные аккаунты доступны только в Development.", 403,
                              code="dev_only")
    owner_id = account_auth.primary_owner_id()
    if owner_id <= 0:
        raise DevServiceError(
            "Нет канонического владельца в локальном хранилище — сначала войдите "
            "как владелец.", 409, code="owner_missing",
        )
    created = []
    for actor, spec in SERVICE_ACCOUNTS.items():
        account_auth.ensure_service_account_user(
            spec["uid"], first_name=spec["first_name"], last_name=spec["last_name"],
            username=spec["username"],
        )
        workspace_id = workspaces.ensure_service_membership(spec["uid"], owner_id)
        created.append({"actor": actor, "user_id": spec["uid"], "workspace_id": workspace_id})
    return {"ok": True, "owner_id": owner_id, "accounts": created}


def login(actor: str, *, is_loopback: bool, ip: str = "127.0.0.1",
          user_agent: str = "dev-service") -> Dict[str, Any]:
    """Mint a session for a service account. Development + loopback only."""
    if not available():
        raise DevServiceError("Служебный вход доступен только в Development.", 403,
                              code="dev_only")
    if not is_loopback:
        raise DevServiceError("Служебный вход возможен только с localhost.", 403,
                              code="loopback_required")
    key = str(actor or "").strip().lower()
    spec = SERVICE_ACCOUNTS.get(key)
    if not spec:
        raise DevServiceError("Неизвестный служебный аккаунт.", 400, code="actor_invalid")
    ensure_service_accounts()
    session = account_auth.create_session_for_user(
        spec["uid"], ip=ip, user_agent=user_agent, source="dev_service",
        require_google=False, skip_dual_auth_gate=True,
        device_confirmation_required=False,
    )
    _audit("dev_service_login", actor=key, user_id=spec["uid"])
    return {
        "ok": True, "actor": key, "label": spec["label"],
        "user_id": spec["uid"],
        "session_token": str(session.get("session_token") or ""),
    }


def status() -> Dict[str, Any]:
    return {
        "available": available(),
        "accounts": [
            {"actor": actor, "label": spec["label"], "user_id": spec["uid"]}
            for actor, spec in SERVICE_ACCOUNTS.items()
        ],
    }
