"""Development-only developer preview: View-As personas and a single-use
localhost bootstrap.

Purpose: an automation browser (separate profile, often unauthenticated) needs
to see the full authenticated interface, the Admin Panel and real per-role UI
without weakening auth. This module never disables authentication or permissions
— it issues real, server-scoped sessions whose permissions come entirely from
the selected persona account, records preview start/end in the audit trail, and
is fail-closed outside Development.

Hard boundaries:
  * Every entry point calls ``runtime_env.require_test_auth()`` which raises in
    Canary and Production and requires ``DEPLOYMENT_ENV=development`` plus
    ``NTA_ENABLE_TEST_AUTH=1``. There is no bypass in Canary/Production.
  * The bootstrap link is single-use, time-boxed, loopback-only and stored only
    as a hash; a reused or expired token is rejected and never logged.
  * Personas are deterministic virtual accounts in a reserved id band, isolated
    in the Development store, with no real personal data, Connector sessions or
    accounts. They can be reset safely.
"""
from __future__ import annotations

import hashlib
import hmac
import atexit
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import account_auth, preview_sandbox, runtime_env, workspaces


# Reserved deterministic id band for preview personas (kept clear of real and
# external-provider id bands).
_PERSONA_BASE = 9_600_000_000_000_000
PERSONA_UNAUTHENTICATED = "unauthenticated"
PERSONA_ORDINARY = "ordinary"
PERSONA_OWNER_TRAINING = "owner_training"
PERSONA_PERSONAL_NT = "personal_nt"
PERSONA_DEVELOPER = "developer"
PERSONA_OWNER = "owner"

BOOTSTRAP_TTL_SEC = 5 * 60
_BOOTSTRAP_KEY = "dev_bootstrap_tokens"

# Developer persona gets an explicit, limited administrative grant set — never
# the full owner capability set.
_DEVELOPER_GRANTS = ("admin.view", "operations.view", "environment.switch")

_PERSONAS: Dict[str, Dict[str, Any]] = {
    PERSONA_UNAUTHENTICATED: {
        "label": "Неавторизованный",
        "kind": "unauthenticated",
        "description": "Публичный вход без сессии.",
    },
    PERSONA_ORDINARY: {
        "label": "Обычный пользователь",
        "uid": _PERSONA_BASE + 1,
        "role": "read_only",
        "ux_mode": "professional",
        "workspace": "owner_training",
        "description": "Наблюдатель общего NinjaTrader, только чтение.",
    },
    PERSONA_OWNER_TRAINING: {
        "label": "Пользователь общего NinjaTrader",
        "uid": _PERSONA_BASE + 2,
        "role": "read_only",
        "ux_mode": "professional",
        "workspace": "owner_training",
        "description": "Ограниченный координатор общего NinjaTrader.",
    },
    PERSONA_PERSONAL_NT: {
        "label": "Личный NinjaTrader",
        "uid": _PERSONA_BASE + 3,
        "role": "full_control",
        "ux_mode": "professional",
        "workspace": "personal",
        "description": "Изолированная личная команда агентов.",
    },
    PERSONA_DEVELOPER: {
        "label": "Разработчик",
        "uid": _PERSONA_BASE + 4,
        "role": "full_control",
        "ux_mode": "professional",
        "workspace": "personal",
        "grants": _DEVELOPER_GRANTS,
        "description": "Только выданные developer-возможности, не владелец.",
    },
    PERSONA_OWNER: {
        "label": "Владелец",
        "kind": "owner_self",
        "description": "Полный интерфейс владельца (собственная сессия).",
    },
}


class DevPreviewError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")


# --------------------------------------------------------------------------- #
# Full isolated Preview sandbox process.
# --------------------------------------------------------------------------- #
_SANDBOX_LOCK = threading.RLock()
_ACTIVE_SANDBOX: Optional[Dict[str, Any]] = None


def sandbox_scenarios() -> List[Dict[str, str]]:
    return preview_sandbox.scenario_catalog()


def _require_owner(actor_user_id: Any) -> int:
    _require_development()
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, actor)
        if not user or not user.get("is_owner"):
            raise DevPreviewError(
                "Preview sandbox доступен только владельцу в Development.",
                403,
                code="owner_required",
            )
    return actor


def _loopback_origin(value: Any) -> str:
    origin = str(value or "").strip().rstrip("/")
    try:
        parsed = urllib.parse.urlparse(origin)
        host = str(parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError):
        parsed, host, port = None, "", None
    if (
        parsed is None
        or parsed.scheme != "http"
        or host not in {"127.0.0.1", "localhost", "::1"}
        or not port
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise DevPreviewError(
            "Preview можно запустить только из loopback Development origin.",
            403,
            code="loopback_required",
        )
    return origin


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _sandbox_base() -> Path:
    return (Path(tempfile.gettempdir()) / "stratforge-preview-sandboxes").resolve()


_SENSITIVE_ENV_MARKERS = (
    "TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY",
    "CONNECTION_STRING", "DATABASE_URL", "REDIS_URL", "WEBHOOK",
    "TELEGRAM", "PAYPAL", "RESEND", "OPENAI", "ANTHROPIC", "AZURE",
    "GEMINI", "DEEPSEEK", "TOPSTEP", "ALPACA", "IBKR", "CLOUDFLARE",
    "TUNNEL", "SENTRY_DSN",
)
_ROOT_ENV_NAMES = {
    "STRATFORGE_PREVIEW_MODEL_BRIDGE", "STRATFORGE_PREVIEW_MODEL_TOKEN",
    "STRATFORGE_DATA_ROOT", "NTA_DATA_ROOT", "STRATFORGE_CANARY_DATA_ROOT",
    "STRATFORGE_DEVELOPMENT_DATA_ROOT", "NTA_STAGING_DATA_ROOT",
}


def _sandbox_environment(
    *, preview_id: str, scenario: str, parent_origin: str,
    root: Path, base: Path, entry_token: str, control_token: str, port: int,
) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper in _ROOT_ENV_NAMES:
            continue
        if any(marker in upper for marker in _SENSITIVE_ENV_MARKERS):
            continue
        env[str(key)] = str(value)
    env.update({
        "DEPLOYMENT_ENV": "development",
        "APP_ENV": "development",
        "NTA_ENABLE_TEST_AUTH": "1",
        "NTA_ENABLE_IMPERSONATION": "0",
        "NTA_TEST_BYPASS_AUTH": "0",
        "NTA_STAGING_ALLOW_OWNER_TELEGRAM": "0",
        "NTA_NT_GOOGLE_REQUIRED": "0",
        "NTA_DUAL_AUTH_REQUIRED": "0",
        "NTA_ALLOW_REAL_PAYMENTS": "0",
        "NTA_ALLOW_LIVE_ORDERS": "0",
        "STRATFORGE_REAL_PAYMENTS_ALLOWED": "0",
        "STRATFORGE_LIVE_TRADING_ALLOWED": "0",
        "STRATFORGE_PREVIEW_SANDBOX": "1",
        "STRATFORGE_PREVIEW_ID": preview_id,
        "STRATFORGE_PREVIEW_SCENARIO": scenario,
        "STRATFORGE_PREVIEW_ENTRY_TOKEN": entry_token,
        "STRATFORGE_PREVIEW_CONTROL_TOKEN": control_token,
        "STRATFORGE_PREVIEW_PARENT_ORIGIN": parent_origin,
        "STRATFORGE_PREVIEW_BASE_ROOT": str(base),
        "STRATFORGE_DEVELOPMENT_DATA_ROOT": str(root),
        "STRATFORGE_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "STRATFORGE_PUBLIC_ORIGIN": f"http://127.0.0.1:{port}",
        "STRATFORGE_INSTANCE_ID": f"preview-{preview_id[:24]}",
        "STRATFORGE_COOKIE_NAMESPACE": f"preview-{preview_id[:24]}",
        "STRATFORGE_LOG_NAMESPACE": f"preview-{preview_id[:24]}",
        "PYTHONUNBUFFERED": "1",
    })
    # Explicit empty provider values prevent a local secret loader or inherited
    # configuration from selecting a real transport.
    for key in (
        "NTA_TELEGRAM_CHAT_ID", "NTA_TELEGRAM_BOT_TOKEN",
        "NTA_TELEGRAM_BOT_USERNAME", "NTA_EMAIL_AUTH_PROVIDER",
        "NTA_EMAIL_AUTH_FROM", "NTA_RESEND_API_KEY",
    ):
        env[key] = ""
    # A synthetic bot name, never the owner's real one. Delivery still cannot
    # happen — the token is empty and the child cannot open a socket — but the
    # login screen can render its QR and Telegram option, which is what the
    # owner is here to look at.
    env["NTA_TELEGRAM_BOT_USERNAME"] = "stratforge_preview_bot"
    return env


def _process_alive(record: Optional[Dict[str, Any]]) -> bool:
    process = (record or {}).get("process")
    return bool(process is not None and process.poll() is None)


def _validated_preview_container(record: Dict[str, Any]) -> Optional[Path]:
    try:
        base = _sandbox_base()
        container = Path(str(record.get("container") or "")).resolve()
        relative = container.relative_to(base)
        if len(relative.parts) != 2:
            return None
        if str(record.get("preview_id") or "") != relative.parts[-1]:
            return None
        return container
    except (OSError, ValueError):
        return None


def _stop_active_sandbox_locked(*, remove_data: bool) -> None:
    global _ACTIVE_SANDBOX
    record = _ACTIVE_SANDBOX
    _ACTIVE_SANDBOX = None
    if not record:
        return
    if record.get("model_bridge") is not None:
        record["model_bridge"].close()
    process = record.get("process")
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if remove_data:
        container = _validated_preview_container(record)
        if container and container.exists():
            shutil.rmtree(container)


def stop_active_sandbox(*, remove_data: bool = True) -> None:
    with _SANDBOX_LOCK:
        _stop_active_sandbox_locked(remove_data=remove_data)


def _wait_for_sandbox(record: Dict[str, Any], timeout_sec: float = 15.0) -> None:
    endpoint = f"http://127.0.0.1:{record['port']}/api/health/live"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + max(1.0, timeout_sec)
    last_error = ""
    while time.monotonic() < deadline:
        if not _process_alive(record):
            last_error = "Preview child process stopped during startup."
            break
        try:
            with opener.open(endpoint, timeout=0.4) as response:
                if int(getattr(response, "status", 0) or 0) == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = type(exc).__name__
        time.sleep(0.08)
    log_tail = ""
    try:
        log_tail = Path(str(record.get("log_path") or "")).read_text(
            encoding="utf-8", errors="replace",
        )[-1600:]
    except OSError:
        pass
    detail = (log_tail.strip() or last_error or "readiness timeout")[-1600:]
    raise DevPreviewError(
        "Preview sandbox не запустился: " + detail,
        503,
        code="preview_start_failed",
    )


def launch_sandbox(actor_user_id: Any, scenario: Any, *, origin: Any) -> Dict[str, Any]:
    """Launch one isolated child and return a single-use entry URL."""
    global _ACTIVE_SANDBOX
    actor = _require_owner(actor_user_id)
    selected = preview_sandbox.normalize_scenario(scenario)
    parent_origin = _loopback_origin(origin)
    preview_id = secrets.token_hex(12)
    entry_token = secrets.token_urlsafe(48)
    control_token = secrets.token_urlsafe(48)
    port = _free_loopback_port()
    base = _sandbox_base()
    container = (base / str(os.getpid()) / preview_id).resolve()
    root = (container / "data").resolve()
    root.mkdir(parents=True, exist_ok=False)
    log_path = container / "preview-server.log"
    env = _sandbox_environment(
        preview_id=preview_id, scenario=selected, parent_origin=parent_origin,
        root=root, base=base, entry_token=entry_token,
        control_token=control_token, port=port,
    )
    bridge = None
    if selected != "agent_world_operator":
        from .preview_shared_models import Bridge
        bridge = Bridge(preview_id)
        env["STRATFORGE_PREVIEW_MODEL_BRIDGE"] = bridge.url
        env["STRATFORGE_PREVIEW_MODEL_TOKEN"] = bridge.token
    command = [sys.executable, "-m", "app.preview_server", "--port", str(port)]
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log_handle = log_path.open("w", encoding="utf-8")
    try:
        with _SANDBOX_LOCK:
            _stop_active_sandbox_locked(remove_data=True)
            process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parent.parent),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            record: Dict[str, Any] = {
                "process": process,
                "preview_id": preview_id,
                "scenario": selected,
                "port": port,
                "container": str(container),
                "root": str(root),
                "log_path": str(log_path),
                "started_at": time.time(),
                "actor_user_id": actor,
                "model_bridge": bridge,
            }
            _ACTIVE_SANDBOX = record
        _wait_for_sandbox(record)
        def reap():
            process.wait()
            with _SANDBOX_LOCK:
                if _ACTIVE_SANDBOX and _ACTIVE_SANDBOX.get("preview_id") == preview_id:
                    _stop_active_sandbox_locked(remove_data=True)
        threading.Thread(target=reap, daemon=True, name="preview-cleanup").start()
    except Exception as exc:
        log_handle.close()
        with _SANDBOX_LOCK:
            if _ACTIVE_SANDBOX and _ACTIVE_SANDBOX.get("preview_id") == preview_id:
                _stop_active_sandbox_locked(remove_data=True)
            else:
                abandoned = _validated_preview_container({"container": str(container), "preview_id": preview_id})
                if abandoned and abandoned.exists():
                    shutil.rmtree(abandoned)
        if bridge is not None and not bridge.closed:
            bridge.close()
        if isinstance(exc, DevPreviewError):
            raise
        raise DevPreviewError(
            "Preview sandbox не запустился.",
            503,
            code="preview_start_failed",
        ) from exc
    finally:
        log_handle.close()
    url = f"http://127.0.0.1:{port}/api/dev/preview/enter?token={urllib.parse.quote(entry_token)}"
    account_auth._audit(
        "dev.preview_sandbox_started",
        user_id=actor,
        owner_id=actor,
        extra={"preview_id": preview_id, "scenario": selected, "port": port},
    )
    return {
        "ok": True,
        "preview_id": preview_id,
        "scenario": selected,
        "url": url,
        "isolated": True,
        "external_side_effects": "shared_models_only" if bridge is not None else "blocked",
    }


def active_sandbox_status() -> Dict[str, Any]:
    with _SANDBOX_LOCK:
        record = _ACTIVE_SANDBOX
        if not record:
            return {"running": False}
        return {
            "running": _process_alive(record),
            "preview_id": str(record.get("preview_id") or ""),
            "scenario": str(record.get("scenario") or ""),
            "port": int(record.get("port") or 0),
            "started_at": float(record.get("started_at") or 0),
        }


atexit.register(stop_active_sandbox)


def _require_development() -> None:
    """Fail-closed: only Development with explicit test-auth may use previews."""
    try:
        runtime_env.require_test_auth()
    except runtime_env.RuntimeEnvError as exc:
        raise DevPreviewError(str(exc), getattr(exc, "status", 403), code="dev_preview_disabled") from None


def personas() -> List[Dict[str, Any]]:
    return [
        {"id": key, "label": val["label"], "description": val.get("description", "")}
        for key, val in _PERSONAS.items()
    ]


def _owner_id(doc: Dict[str, Any]) -> int:
    for user in doc.get("users") or []:
        if isinstance(user, dict) and user.get("is_owner"):
            return int(user.get("user_id") or 0)
    return 0


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Personas.
# --------------------------------------------------------------------------- #
def ensure_personas() -> Dict[str, Any]:
    """Create/refresh the deterministic preview personas in the Development store."""
    _require_development()
    created: List[str] = []
    for key, spec in _PERSONAS.items():
        if "uid" not in spec:
            continue
        uid = int(spec["uid"])
        account_auth.create_or_update_virtual_user(
            user_id=uid,
            username=f"preview_{key}",
            first_name=str(spec["label"]),
            last_name="(preview)",
            email=f"preview-{key}@dev.stratforge.local",
            role=str(spec.get("role") or "read_only"),
            status="active",
            google_linked=True,
            virtual=True,
            preset="dev_preview",
            ux_mode=str(spec.get("ux_mode") or "professional"),
        )
        created.append(key)
    # Wire memberships/workspaces and developer grants under one lock pass.
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        owner = _owner_id(doc)
        for key, spec in _PERSONAS.items():
            if "uid" not in spec:
                continue
            user = account_auth._user(doc, int(spec["uid"]))
            if user is None:
                continue
            user["is_dev_persona"] = True
            grants = spec.get("grants") or ()
            if grants:
                now = account_auth._now_iso()
                user["admin_permission_grants"] = {
                    cap: {"enabled": True, "granted_at_utc": now, "expires_at_utc": "",
                          "granted_by": "dev_preview"}
                    for cap in grants
                }
            else:
                user.pop("admin_permission_grants", None)
        account_auth._write_doc(doc)
    # Owner-training membership + personal workspaces (best-effort, dev only).
    for key, spec in _PERSONAS.items():
        if "uid" not in spec:
            continue
        uid = int(spec["uid"])
        try:
            if spec.get("workspace") == "owner_training" and owner:
                workspaces.context_for_user(uid, is_owner=False, owner_id=owner)
            elif spec.get("workspace") == "personal":
                workspaces.ensure_personal_workspace(
                    uid, display_name=f"{spec['label']} NinjaTrader",
                    require_entitlement=False,
                )
        except Exception:
            # Persona wiring is best-effort; a missing owner just yields no
            # owner-training membership in this dev store.
            pass
    return {"ok": True, "personas": created}


def reset_personas() -> Dict[str, Any]:
    """Remove preview personas and their sessions, then recreate them."""
    _require_development()
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        persona_ids = {
            int(spec["uid"]) for spec in _PERSONAS.values() if "uid" in spec
        }
        doc["users"] = [u for u in doc.get("users") or [] if int(u.get("user_id") or 0) not in persona_ids]
        doc["sessions"] = [s for s in doc.get("sessions") or [] if int(s.get("user_id") or 0) not in persona_ids]
        account_auth._write_doc(doc)
    return ensure_personas()


# --------------------------------------------------------------------------- #
# View As.
# --------------------------------------------------------------------------- #
def _banner(persona: str, label: str) -> str:
    return f"VIEW AS · {label}. Это предпросмотр developer; ваши реальные права не изменены."


def start_view_as(
    actor_user_id: Any, persona: str, *, ip: str = "127.0.0.1", user_agent: str = "dev-preview",
) -> Dict[str, Any]:
    """Start a scoped preview session for a persona. Owner-gated, Development-only."""
    _require_development()
    persona_id = str(persona or "").strip().lower()
    spec = _PERSONAS.get(persona_id)
    if spec is None:
        raise DevPreviewError("Неизвестная persona.", 400, code="persona_invalid")
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        owner = _owner_id(doc)
        actor_user = account_auth._user(doc, actor)
    if not actor_user or not actor_user.get("is_owner"):
        # Only the owner (in Development the local owner) starts a preview so a
        # preview can never be used to escalate a lesser actor.
        raise DevPreviewError("Предпросмотр доступен только владельцу в Development.", 403, code="owner_required")

    if spec.get("kind") == "unauthenticated":
        account_auth._audit("dev.view_as_started", user_id=0, owner_id=actor,
                            extra={"persona": persona_id})
        return {"ok": True, "persona": persona_id, "label": spec["label"],
                "clear_session": True, "banner": _banner(persona_id, spec["label"])}

    if spec.get("kind") == "owner_self":
        session = account_auth.create_session_for_user(
            actor, ip=ip, user_agent=user_agent, source="view_as_owner",
            skip_dual_auth_gate=True,
            device_confirmation_required=False,
        )
        account_auth._audit("dev.view_as_started", user_id=actor, owner_id=actor,
                            extra={"persona": persona_id})
        return {"ok": True, "persona": persona_id, "label": spec["label"],
                "session_token": session.get("session_token"),
                "banner": _banner(persona_id, spec["label"])}

    ensure_personas()
    uid = int(spec["uid"])
    session = account_auth.create_session_for_user(
        uid, ip=ip, user_agent=user_agent, source="view_as",
        skip_dual_auth_gate=True, impersonator_owner_id=actor,
        impersonation_preset="dev_preview",
        device_confirmation_required=False,
    )
    account_auth._audit("dev.view_as_started", user_id=uid, owner_id=actor,
                        extra={"persona": persona_id})
    return {
        "ok": True, "persona": persona_id, "label": spec["label"],
        "session_token": session.get("session_token"),
        "banner": _banner(persona_id, spec["label"]),
    }


def exit_view_as(
    actor_user_id: Any, preview_token: str, *, ip: str = "127.0.0.1", user_agent: str = "dev-return",
) -> Dict[str, Any]:
    """Revoke the preview session and restore the owner's own session."""
    _require_development()
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        owner = _owner_id(doc)
        if actor <= 0:
            actor = owner
        digest = hashlib.sha256(str(preview_token or "").encode()).hexdigest()
        for session in doc.get("sessions") or []:
            if hmac.compare_digest(str(session.get("token_hash") or ""), digest) and not session.get("revoked"):
                session["revoked"] = True
                session["revoked_at_utc"] = account_auth._now_iso()
                session["revoked_reason"] = "view_as_end"
        account_auth._write_doc(doc)
    if not owner:
        raise DevPreviewError("Нет владельца для восстановления сессии.", 409, code="owner_missing")
    restored = account_auth.create_session_for_user(
        owner, ip=ip, user_agent=user_agent, source="view_as_return",
        skip_dual_auth_gate=True,
        device_confirmation_required=False,
    )
    account_auth._audit("dev.view_as_ended", user_id=owner, owner_id=owner, extra={})
    return {"ok": True, "restored": True, "session_token": restored.get("session_token")}


_PREVIEW_SESSION_SOURCES = {"view_as", "view_as_owner", "dev_bootstrap"}


def return_to_developer(*, ip: str = "127.0.0.1", user_agent: str = "dev-return") -> Dict[str, Any]:
    """Loopback return path that always restores the owner/developer session.

    Unlike :func:`exit_view_as` this needs no preview token or CSRF, so it can
    recover even from the unauthenticated persona (which holds no session). It is
    Development-and-loopback gated by the caller and only ever restores the
    single local owner, so it can never escalate any other identity.
    """
    _require_development()
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        owner = _owner_id(doc)
        for session in doc.get("sessions") or []:
            if session.get("revoked"):
                continue
            if str(session.get("source") or "") in _PREVIEW_SESSION_SOURCES:
                session["revoked"] = True
                session["revoked_at_utc"] = account_auth._now_iso()
                session["revoked_reason"] = "view_as_return"
        account_auth._write_doc(doc)
    if not owner:
        raise DevPreviewError("Нет владельца для восстановления сессии.", 409, code="owner_missing")
    restored = account_auth.create_session_for_user(
        owner, ip=ip, user_agent=user_agent, source="view_as_return",
        skip_dual_auth_gate=True,
        device_confirmation_required=False,
    )
    account_auth._audit("dev.view_as_ended", user_id=owner, owner_id=owner, extra={})
    return {"ok": True, "restored": True, "session_token": restored.get("session_token")}


# --------------------------------------------------------------------------- #
# Development bootstrap (single-use, loopback-only, signed).
# --------------------------------------------------------------------------- #
def _tokens(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = doc.get(_BOOTSTRAP_KEY)
    if not isinstance(rows, list):
        rows = []
        doc[_BOOTSTRAP_KEY] = rows
    return rows


def _prune_tokens(doc: Dict[str, Any]) -> None:
    now = time.time()
    doc[_BOOTSTRAP_KEY] = [
        row for row in _tokens(doc)
        if not row.get("used") and float(row.get("expires_at") or 0) > now
    ][-50:]


def mint_bootstrap_token(actor_user_id: Any, *, origin: str = "") -> Dict[str, Any]:
    """Mint a single-use, time-boxed Development bootstrap token (owner-only)."""
    _require_development()
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    token = secrets.token_urlsafe(32)
    now = time.time()
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        owner = _owner_id(doc)
        actor_user = account_auth._user(doc, actor)
        if not actor_user or not actor_user.get("is_owner"):
            raise DevPreviewError("Bootstrap может выдать только владелец.", 403, code="owner_required")
        _prune_tokens(doc)
        _tokens(doc).append({
            "token_hash": _token_hash(token),
            "environment": runtime_env.deployment_environment(),
            "created_at_utc": account_auth._now_iso(),
            "expires_at": now + BOOTSTRAP_TTL_SEC,
            "used": False,
            "minted_by": actor,
        })
        account_auth._write_doc(doc)
    account_auth._audit("dev.bootstrap_minted", user_id=actor, owner_id=owner or actor, extra={})
    base = str(origin or "").rstrip("/")
    url = f"{base}/api/dev/bootstrap/redeem?token={token}" if base else ""
    return {"ok": True, "token": token, "url": url, "expires_in_sec": BOOTSTRAP_TTL_SEC}


def redeem_bootstrap_token(
    token: str, *, is_loopback: bool, ip: str = "127.0.0.1", user_agent: str = "dev-bootstrap",
) -> Dict[str, Any]:
    """Redeem a bootstrap token into a fresh owner session. Single-use + expiry."""
    _require_development()
    if not is_loopback:
        raise DevPreviewError("Bootstrap разрешён только с localhost/loopback.", 403, code="loopback_required")
    digest = _token_hash(token)
    now = time.time()
    current_env = runtime_env.deployment_environment()
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        owner = _owner_id(doc)
        row = None
        for candidate in _tokens(doc):
            if hmac.compare_digest(str(candidate.get("token_hash") or ""), digest):
                row = candidate
                break
        if row is None:
            raise DevPreviewError("Bootstrap token не найден.", 404, code="token_not_found")
        if row.get("used"):
            raise DevPreviewError("Bootstrap token уже использован.", 409, code="token_used")
        if float(row.get("expires_at") or 0) <= now:
            row["used"] = True
            account_auth._write_doc(doc)
            raise DevPreviewError("Bootstrap token истёк.", 410, code="token_expired")
        if str(row.get("environment") or "") != current_env:
            raise DevPreviewError("Bootstrap token из другого окружения.", 409, code="token_wrong_environment")
        if not owner:
            raise DevPreviewError("Нет владельца для bootstrap-сессии.", 409, code="owner_missing")
        row["used"] = True
        row["redeemed_at_utc"] = account_auth._now_iso()
        account_auth._write_doc(doc)
    session = account_auth.create_session_for_user(
        owner, ip=ip, user_agent=user_agent, source="dev_bootstrap",
        skip_dual_auth_gate=True,
        device_confirmation_required=False,
    )
    account_auth._audit("dev.bootstrap_redeemed", user_id=owner, owner_id=owner, extra={})
    return {"ok": True, "session_token": session.get("session_token"), "owner_id": owner}


def status(actor_user_id: Any) -> Dict[str, Any]:
    """Developer preview status: personas + whether the actor may use it."""
    _require_development()
    try:
        actor = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor = 0
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        actor_user = account_auth._user(doc, actor)
        is_owner = bool(actor_user and actor_user.get("is_owner"))
    return {
        "ok": True,
        "environment": runtime_env.deployment_environment(),
        "available": is_owner,
        "personas": personas(),
        "sandbox_scenarios": sandbox_scenarios(),
        "active_sandbox": active_sandbox_status(),
        "architecture": "isolated_process",
        "bootstrap_available": is_owner,
    }
