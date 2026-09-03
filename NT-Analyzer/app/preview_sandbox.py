"""Isolated, mutable Preview sandbox for owner-driven product acceptance.

This module runs only inside the dedicated loopback child process launched by
``app.dev_preview``.  It deliberately reuses the real account, session, device,
workspace, billing, backtest, practice and Community domain functions while the
process itself has a unique data root, cookie namespace and no external
credentials.  It is not an impersonation mechanism and never creates an owner.
"""
from __future__ import annotations

import errno
import gc
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from . import (
    account_auth,
    community,
    demo_backtest,
    in_app_notifications,
    jobqueue,
    physical_devices,
    practice_trading,
    runtime_env,
    security_devices,
    subscriptions,
    workspaces,
)


class PreviewSandboxError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "preview_sandbox_error")


SCENARIOS: Dict[str, Dict[str, str]] = {
    "new_user": {
        "label": "Новый пользователь",
        "description": "Чистая регистрация → первый вход → подтверждение устройства.",
    },
    "active_user": {
        "label": "Обычный активный пользователь",
        "description": "Активный synthetic user с доступом только до конца сессии.",
    },
    "trusted_device": {
        "label": "Пользователь с доверенным устройством",
        "description": "Активный synthetic user на постоянно доверенном клиенте.",
    },
    "pending_access": {
        "label": "Новый неподтверждённый доступ",
        "description": "Существующий synthetic user входит из нового browser/client.",
    },
}

_LOCK = threading.RLock()
_ENTRY_CONSUMED = False
_NETWORK_GUARD_INSTALLED = False
_RUNTIME_CLOCK: Optional[threading.Thread] = None
_RUNTIME_CLOCK_DIRS: List[Path] = []
_RUNTIME_CLOCK_STOP = threading.Event()
_STATE: Dict[str, Any] = {
    "scenario": "",
    "generation": 0,
    "current_user_id": 0,
    "current_user_uuid": "",
    "current_session_id": "",
    "dataset_ready": False,
    "dataset_errors": [],
}


def enabled() -> bool:
    return runtime_env.preview_sandbox_enabled()


def require_enabled() -> None:
    if not enabled():
        raise PreviewSandboxError(
            "Preview sandbox доступен только в отдельном Development test process.",
            403,
            code="preview_sandbox_disabled",
        )
    isolated_root()


def scenario_catalog() -> List[Dict[str, str]]:
    return [
        {"id": key, "label": value["label"], "description": value["description"]}
        for key, value in SCENARIOS.items()
    ]


def normalize_scenario(value: Any) -> str:
    scenario = str(value or "new_user").strip().lower()
    if scenario not in SCENARIOS:
        raise PreviewSandboxError(
            "Неизвестный Preview-сценарий.", 400, code="preview_scenario_invalid",
        )
    return scenario


def _safe_id() -> str:
    value = str(os.environ.get("STRATFORGE_PREVIEW_ID") or "").strip()
    if not re.fullmatch(r"[a-z0-9]{12,48}", value):
        raise PreviewSandboxError(
            "Preview process id невалиден.", 503, code="preview_identity_invalid",
        )
    return value


def isolated_root() -> Path:
    """Return and verify the exact temporary root owned by this child process."""
    root = runtime_env.data_root().resolve()
    configured_base = str(os.environ.get("STRATFORGE_PREVIEW_BASE_ROOT") or "").strip()
    base = Path(configured_base or (Path(tempfile.gettempdir()) / "stratforge-preview-sandboxes")).resolve()
    try:
        relative = root.relative_to(base)
    except ValueError:
        raise PreviewSandboxError(
            "Preview data root находится вне разрешённого temporary root.",
            503,
            code="preview_root_not_isolated",
        ) from None
    if len(relative.parts) < 2 or _safe_id() not in relative.parts:
        raise PreviewSandboxError(
            "Preview data root не привязан к process id.",
            503,
            code="preview_root_identity_mismatch",
        )
    root.mkdir(parents=True, exist_ok=True)
    return root


def control_cookie_name() -> str:
    return f"sf_preview_{_safe_id()[:24]}_control"


def control_cookie_value() -> str:
    require_enabled()
    value = str(os.environ.get("STRATFORGE_PREVIEW_CONTROL_TOKEN") or "").strip()
    if len(value) < 40:
        raise PreviewSandboxError(
            "Preview control token не настроен.", 503, code="preview_control_missing",
        )
    return value


def control_authorized(value: Any) -> bool:
    if not enabled():
        return False
    supplied = str(value or "")
    expected = str(os.environ.get("STRATFORGE_PREVIEW_CONTROL_TOKEN") or "")
    return bool(len(expected) >= 40 and hmac.compare_digest(supplied, expected))


def synthetic_product_access_allowed(context: Dict[str, Any]) -> bool:
    """Allow the full user product only inside the isolated Preview child.

    The environment flag alone is insufficient: the authenticated row must be
    a non-owner synthetic identity stamped for this exact sandbox.
    Administrative capabilities remain separate and are never granted here.
    """
    if not runtime_env.preview_sandbox_enabled() or not isinstance(context, dict):
        return False
    user = context.get("user") if isinstance(context.get("user"), dict) else {}
    return bool(
        not context.get("is_owner")
        and not user.get("is_owner")
        and user.get("is_preview_user")
        and hmac.compare_digest(
            str(user.get("preview_sandbox_id") or ""),
            _safe_id(),
        )
    )


def consume_entry_token(value: Any) -> None:
    """Spend the owner-issued bearer once; the browser keeps only HttpOnly control."""
    global _ENTRY_CONSUMED
    require_enabled()
    supplied = str(value or "")
    expected = str(os.environ.get("STRATFORGE_PREVIEW_ENTRY_TOKEN") or "")
    with _LOCK:
        if _ENTRY_CONSUMED:
            raise PreviewSandboxError(
                "Preview entry link уже использован.", 409, code="preview_entry_used",
            )
        if len(expected) < 40 or not hmac.compare_digest(supplied, expected):
            raise PreviewSandboxError(
                "Preview entry link недействителен.", 403, code="preview_entry_invalid",
            )
        _ENTRY_CONSUMED = True


def parent_origin() -> str:
    """Validated loopback origin to which Exit Preview may redirect."""
    value = str(os.environ.get("STRATFORGE_PREVIEW_PARENT_ORIGIN") or "").strip().rstrip("/")
    try:
        parsed = urlparse(value)
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
        raise PreviewSandboxError(
            "Preview parent origin должен быть loopback HTTP origin.",
            503,
            code="preview_parent_origin_invalid",
        )
    return value


def exit_url() -> str:
    return parent_origin() + "/ui/"


def install_network_guard() -> None:
    """Block every outbound socket from the Preview child process.

    The HTTP server uses bind/accept and is unaffected.  Domain code may still
    mutate its isolated local stores, while Telegram, e-mail, payment, broker,
    cloud-model and other network calls are technically unable to leave it.
    """
    global _NETWORK_GUARD_INSTALLED
    require_enabled()
    if _NETWORK_GUARD_INSTALLED:
        return

    def blocked_connect(_sock: socket.socket, _address: Any) -> None:
        raise OSError(errno.EPERM, "Preview sandbox blocks outbound network connections")

    def blocked_create_connection(*_args: Any, **_kwargs: Any) -> socket.socket:
        raise OSError(errno.EPERM, "Preview sandbox blocks outbound network connections")

    socket.socket.connect = blocked_connect  # type: ignore[assignment]
    socket.socket.connect_ex = blocked_connect  # type: ignore[assignment]
    socket.create_connection = blocked_create_connection  # type: ignore[assignment]
    _NETWORK_GUARD_INSTALLED = True


_BLOCKED_PREFIXES = (
    "/api/telegram/",
    "/api/connector/v1/",
    "/api/admin/releases",
    "/api/admin/platform-secrets",
    "/api/admin/environment",
    "/api/billing/paypal/",
    "/api/ai-lab/cloud",
    "/api/ai-lab/bootstrap",
    "/api/ai-lab/orchestrator/message",
    "/api/ai-lab/orchestrator/speak",
)
_BLOCKED_MUTATIONS = {
    "/api/billing/checkout",
    "/api/billing/subscribe",
    "/api/billing/payment-request",
    "/api/news/refresh",
}


def external_side_effect_blocked(method: str, path: str) -> bool:
    if not enabled():
        return False
    clean_path = str(path or "")
    if any(clean_path.startswith(prefix) for prefix in _BLOCKED_PREFIXES):
        return True
    return str(method or "").upper() not in {"GET", "HEAD"} and clean_path in _BLOCKED_MUTATIONS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(values) + ("\n" if values else ""), encoding="utf-8")
    os.replace(tmp, path)


def _write_manifest() -> None:
    payload = {
        "preview_sandbox": True,
        "preview_id": _safe_id(),
        "updated_at_utc": _now(),
        **{key: value for key, value in _STATE.items() if key != "current_token"},
    }
    _atomic_json(isolated_root() / "preview-manifest.json", payload)


def _clear_module_caches() -> None:
    for module in (account_auth, workspaces, subscriptions):
        clear = getattr(module, "_clear_doc_cache", None)
        if callable(clear):
            clear()
    with account_auth._RATE_LOCK:
        account_auth._LOGIN_RATE.clear()
        security_devices._CHALLENGE_RATE.clear()


def _wipe_isolated_root() -> None:
    root = isolated_root()
    configured_base = str(os.environ.get("STRATFORGE_PREVIEW_BASE_ROOT") or "").strip()
    base = Path(configured_base or (Path(tempfile.gettempdir()) / "stratforge-preview-sandboxes")).resolve()
    # Re-check immediately before the recursive operation.  A symlinked child is
    # unlinked, never followed, and the verified root directory itself remains.
    root.relative_to(base)
    if _safe_id() not in root.parts:
        raise PreviewSandboxError("Preview reset target failed identity check.", 503)
    # The synthetic bridge clock writes into these directories; park it before
    # the recursive delete so Reset never races a recreated heartbeat file.
    _stop_runtime_clock()
    # sqlite3 connection context managers commit/rollback but do not close the
    # connection object. In CPython those short-lived objects normally release
    # immediately; force collection here because Windows will otherwise keep
    # the synthetic WAL file locked for an indeterminate moment during Reset.
    gc.collect()
    for child in list(root.iterdir()):
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
    root.mkdir(parents=True, exist_ok=True)
    _clear_module_caches()


def _find_user_by_public(public: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    canonical = str((public or {}).get("id") or "").strip()
    if not canonical:
        return None
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user_by_uuid(doc, canonical)
        return dict(user) if user else None


def _mark_preview_user(user_id: int) -> Dict[str, Any]:
    from . import permissions

    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, user_id)
        if not user or user.get("is_owner"):
            raise PreviewSandboxError(
                "Synthetic Preview identity отсутствует или является owner.",
                409,
                code="preview_identity_not_synthetic",
            )
        user.update({
            "is_virtual": True,
            "is_preview_user": True,
            "virtual_preset": "preview_sandbox",
            "preview_sandbox_id": _safe_id(),
            "role": "full_control",
            "status": "active",
            "ux_mode": "professional",
            "ux_mode_set_at_utc": user.get("ux_mode_set_at_utc") or _now(),
            # Preview is for full product walkthroughs. These grants remain
            # scoped to this synthetic data root; strict owner-only surfaces
            # stay owner-only in permissions.resolve and real external effects
            # are independently blocked by the child process.
            "feature_overrides": {
                feature_id: True for feature_id in account_auth.FEATURES
            },
            "permission_overrides": {
                capability_id: True for capability_id in permissions.CAPABILITY_IDS
            },
        })
        account_auth._write_doc(doc)
        return dict(user)


def _register_synthetic_user(device_credential: str, generation: int) -> Dict[str, Any]:
    suffix = f"{_safe_id()[:10]}-{generation}-{secrets.token_hex(2)}"
    email = f"preview-{suffix}@sandbox.stratforge.local"
    ip = f"127.0.0.{max(2, min(250, generation + 2))}"
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    started = account_auth.start_email_auth(email, ip=ip, user_agent=user_agent)
    code = str(started.get("test_code") or "")
    if not code or str(started.get("delivery") or "") != "preview_synthetic":
        raise PreviewSandboxError(
            "Synthetic Preview email transport не активирован.",
            503,
            code="preview_transport_missing",
        )
    result = account_auth.verify_email_auth(
        started.get("challenge_id"),
        code=code,
        profile={
            "first_name": "Алекс",
            "last_name": f"Preview {generation}",
            "accept_terms": True,
        },
        ip=ip,
        user_agent=user_agent,
        device_credential=device_credential,
    )
    if result.get("status") != "authenticated" or not result.get("session_token"):
        raise PreviewSandboxError(
            "Не удалось создать synthetic Preview session.",
            503,
            code="preview_registration_failed",
        )
    user = _find_user_by_public(result.get("user") or {})
    if not user:
        raise PreviewSandboxError("Synthetic Preview user не найден.", 503)
    marked = _mark_preview_user(int(user.get("user_id") or 0))
    result["user_id"] = int(marked.get("user_id") or 0)
    result["user_uuid"] = str(marked.get("user_uuid") or "")
    result["email"] = email
    return result


def _approve_session(token: str, mode: str) -> Dict[str, Any]:
    context = account_auth.authenticate_session(token) or {}
    if not context or not context.get("device_confirmation_required"):
        raise PreviewSandboxError("Expected pending Preview session.", 503)
    challenge = security_devices.create_challenge(
        user_id=context.get("user_id"),
        purpose=security_devices.PURPOSE_DEVICE_CONFIRM,
        device_id=str(context.get("trusted_device_id") or ""),
        provider="email",
        trust_mode=mode,
        session_id=str(context.get("session_id") or ""),
        ip="127.0.0.1",
        user_agent="Preview scenario generator",
    )
    code = str(challenge.get("test_code") or "")
    if str(challenge.get("delivery") or "") != "preview_synthetic" or not code:
        raise PreviewSandboxError("Preview device OTP transport unavailable.", 503)
    approved = security_devices.approve_device(
        user_id=context.get("user_id"),
        device_id=str(context.get("trusted_device_id") or ""),
        challenge_id=str(challenge.get("challenge_id") or ""),
        code=code,
        trust_mode=mode,
        session_id=str(context.get("session_id") or ""),
        ip="127.0.0.1",
    )
    return {"context": account_auth.authenticate_session(token) or {}, "approval": approved}


def _session_row(doc: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
    return next(
        (
            row for row in doc.get("sessions") or []
            if isinstance(row, dict)
            and hmac.compare_digest(account_auth._session_id(row), str(session_id or ""))
        ),
        None,
    )


def _seed_security_inventory(user_id: int) -> None:
    """Add proven-machine, paired-client, standalone and remote examples."""
    connector = account_auth.create_session_for_user(
        user_id,
        ip="198.51.100.24",
        user_agent="StratForge Connector/1.0 (Windows 11)",
        source="preview_connector",
        skip_dual_auth_gate=True,
        device_credential="preview-connector-client",
        device_confirmation_required=True,
    )
    embedded = account_auth.create_session_for_user(
        user_id,
        ip="198.51.100.24",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0"
        ),
        source="preview_embedded_browser",
        skip_dual_auth_gate=True,
        device_credential="preview-embedded-client",
        device_confirmation_required=True,
    )
    remote = account_auth.create_session_for_user(
        user_id,
        ip="203.0.113.80",
        user_agent="StratForge Remote API Client/2.1",
        source="remote_access",
        skip_dual_auth_gate=True,
        device_credential="preview-remote-client",
        device_confirmation_required=True,
    )
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, user_id)
        if not user:
            return
        connector_session = _session_row(doc, str(connector.get("context", {}).get("session_id") or ""))
        if connector_session is None:
            connector_ctx = account_auth.authenticate_session(str(connector.get("session_token") or "")) or {}
            connector_session = _session_row(doc, str(connector_ctx.get("session_id") or ""))
        embedded_ctx = account_auth.authenticate_session(str(embedded.get("session_token") or "")) or {}
        remote_ctx = account_auth.authenticate_session(str(remote.get("session_token") or "")) or {}
        embedded_session = _session_row(doc, str(embedded_ctx.get("session_id") or ""))
        remote_session = _session_row(doc, str(remote_ctx.get("session_id") or ""))
        if connector_session is not None:
            security_devices.observe_session(
                doc,
                connector_session,
                user,
                ip="198.51.100.24",
                user_agent="StratForge Connector/1.0 (Windows 11)",
                source="connector",
                connector_installation_id="preview-installation-hardware-bound",
                device_credential="preview-connector-client",
            )
        machine = None
        connector_device = None
        if connector_session is not None:
            connector_device = next(
                (
                    row for row in security_devices._devices(doc)
                    if str(row.get("device_id") or "") == str(connector_session.get("trusted_device_id") or "")
                ),
                None,
            )
        if connector_device is not None:
            security_devices._trust_device(connector_device, provider="email")
            machine = physical_devices.find_machine(
                doc,
                account_auth._user_uuid(user),
                str(connector_device.get("physical_device_id") or ""),
            )
            if machine is not None:
                machine["display_name"] = "Preview Workstation"
                physical_devices.trust_machine(machine, provider="email")
            security_devices._activate_session_access(
                connector_session, mode=security_devices.TRUST_MODE_PERMANENT,
            )
        for session, location in (
            (embedded_session, "Seattle, WA, US"),
            (remote_session, "Remote access · New York, NY, US"),
        ):
            if session is None:
                continue
            device = next(
                (
                    row for row in security_devices._devices(doc)
                    if str(row.get("device_id") or "") == str(session.get("trusted_device_id") or "")
                ),
                None,
            )
            if device is None:
                continue
            device.setdefault("audit_metadata", {})["location"] = location
            security_devices._trust_device(device, provider="email")
            security_devices._activate_session_access(
                session, mode=security_devices.TRUST_MODE_PERMANENT,
            )
            if session is embedded_session and machine is not None:
                physical_devices.bind_client(
                    device, machine,
                    bound_via=physical_devices.BOUND_VIA_ATTESTED_PAIRING,
                )
                session["physical_device_id"] = str(machine.get("physical_device_id") or "")
        account_auth._write_doc(doc)


def _seed_runtime_files(runtime_dir: Path) -> None:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat().replace("+00:00", "Z")
    account_name = "DEMO-PREVIEW-101"
    strategy_id = "ntamnqliquiditysweepreversalc015"
    strategy_class = "NTAMnqLiquiditySweepReversalC015"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(runtime_dir / "heartbeat.json", {
        "timestamp_utc": now_iso,
        "ninja_version": "8.1 Preview Sandbox",
        "machine": "Preview Workstation",
        "exporter_version": "preview-synthetic-1",
        "preview_synthetic": True,
    })
    _atomic_json(runtime_dir / "accounts.json", {
        "generated_at_utc": now_iso,
        "exporter_version": "preview-synthetic-1",
        "accounts": [{
            "account_name": account_name,
            "account_mode": "demo",
            "cash_value": 50_725.50,
            "buying_power": 101_451.00,
            "net_liquidation": 50_812.75,
            "realized_pnl": 725.50,
            "unrealized_pnl": 87.25,
            "currency": "USD",
            "connection_status": "Connected",
            "preview_synthetic": True,
        }],
    })
    _atomic_json(runtime_dir / "positions.json", {
        account_name: [{
            "instrument": "MNQ SEP26", "market_position": "Long",
            "quantity": 1, "average_price": 21482.25,
            "unrealized_pnl": 87.25, "preview_synthetic": True,
        }],
    })
    _atomic_json(runtime_dir / "strategies.json", {
        "generated_at_utc": now_iso,
        "preview_synthetic": True,
        "strategies": [{
            "strategy_id": strategy_id,
            "strategy_class": strategy_class,
            "strategy_name": "MNQ Liquidity Sweep · Preview",
            "account_name": account_name,
            "account_mode": "demo",
            "enabled": True,
            "state": "Realtime",
            "instrument": "MNQ SEP26",
            "timeframe": "1 Minute",
            "runtime_instance_id": "preview-ri-c015",
            "data_series_count": 1,
            "params": {"RoundTurnCommission": 1.90, "TradeStartTime": 630, "TradeEndTime": 1200},
            "preview_synthetic": True,
        }],
    })
    executions: List[Dict[str, Any]] = []
    prices = [(21420.00, 21448.25), (21470.50, 21456.00), (21436.75, 21482.25)]
    for index, (entry, exit_price) in enumerate(prices):
        opened = (now - timedelta(hours=5 - index)).isoformat().replace("+00:00", "Z")
        closed = (now - timedelta(hours=4, minutes=40 - index * 5)).isoformat().replace("+00:00", "Z")
        for stamp, action, price in ((opened, "Buy", entry), (closed, "Sell", exit_price)):
            executions.append({
                "timestamp_utc": stamp,
                "account_name": account_name,
                "runtime_instance_id": "preview-ri-c015",
                "strategy_class": strategy_class,
                "strategy_id": strategy_id,
                "instrument": "MNQ SEP26",
                "order_action": action,
                "quantity": 1,
                "price": price,
                "commission": 0.95,
                "preview_synthetic": True,
            })
    _write_jsonl(runtime_dir / "executions.jsonl", executions)
    _write_jsonl(runtime_dir / "orders.jsonl", [{
        "timestamp_utc": now_iso,
        "order_id": "preview-order-working",
        "account_name": account_name,
        "strategy_id": strategy_id,
        "strategy_class": strategy_class,
        "runtime_instance_id": "preview-ri-c015",
        "instrument": "MNQ SEP26",
        "order_action": "Sell",
        "order_type": "StopMarket",
        "quantity": 1,
        "stop_price": 21428.00,
        "order_state": "Working",
        "preview_synthetic": True,
    }])
    _write_jsonl(runtime_dir / "errors.jsonl", [])


def _runtime_dirs(workspace: Dict[str, Any]) -> List[Path]:
    """Every runtime store a Preview page may read.

    A personal workspace keeps its own bridge export, while Финансы, Обзор and
    the portfolio widgets read the process-global ``runtime`` directory. Both
    are inside this disposable data root, so the synthetic bridge snapshot is
    written to both and every product surface shows the same trades.
    """
    dirs: List[Path] = []
    try:
        scoped = str(workspaces.runtime_storage_dir_for_context(
            {"active_workspace": workspace},
        ) or "")
        if scoped:
            dirs.append(Path(scoped))
    except Exception:
        pass
    dirs.append(Path(runtime_env.data_path("runtime")))
    unique: List[Path] = []
    for path in dirs:
        resolved = path.resolve()
        if resolved not in [item.resolve() for item in unique]:
            unique.append(path)
    return unique


def _touch_runtime_heartbeat(dirs: Iterable[Path]) -> None:
    """Keep the synthetic bridge heartbeat fresh for this process.

    Trading Online hides strategies whenever the bridge heartbeat is stale,
    which is correct for a real NinjaTrader install and wrong for a sandbox
    whose bridge is a file written once at seeding time.
    """
    stamp = _now()
    for runtime_dir in dirs:
        try:
            _atomic_json(Path(runtime_dir) / "heartbeat.json", {
                "timestamp_utc": stamp,
                "ninja_version": "8.1 Preview Sandbox",
                "machine": "Preview Workstation",
                "exporter_version": "preview-synthetic-1",
                "state": "CONNECTED",
                "preview_synthetic": True,
            })
        except OSError:
            continue


def _start_runtime_clock(dirs: List[Path]) -> None:
    global _RUNTIME_CLOCK
    with _LOCK:
        if _RUNTIME_CLOCK is not None and _RUNTIME_CLOCK.is_alive():
            _RUNTIME_CLOCK_DIRS.clear()
            _RUNTIME_CLOCK_DIRS.extend(dirs)
            return
        _RUNTIME_CLOCK_DIRS.clear()
        _RUNTIME_CLOCK_DIRS.extend(dirs)

        def tick() -> None:
            while True:
                with _LOCK:
                    targets = list(_RUNTIME_CLOCK_DIRS)
                if not targets:
                    return
                _touch_runtime_heartbeat(targets)
                _RUNTIME_CLOCK_STOP.wait(20.0)
                if _RUNTIME_CLOCK_STOP.is_set():
                    return

        _RUNTIME_CLOCK = threading.Thread(
            target=tick, name="preview-runtime-clock", daemon=True,
        )
        _RUNTIME_CLOCK.start()


def _stop_runtime_clock() -> None:
    with _LOCK:
        _RUNTIME_CLOCK_DIRS.clear()


def _require_isolated_target(path: Any, *, what: str) -> Path:
    """Refuse to seed anything that would land outside this sandbox.

    ``app.ai_lab.paths`` resolves its directories once at import time, so a
    module imported before the Preview environment was established would point
    at the repository's own ``ai_lab`` tree. Seeding there would write synthetic
    Preview material into real local data, which this sandbox must never do.
    """
    target = Path(str(path or ""))
    try:
        target.resolve().relative_to(isolated_root())
    except (OSError, ValueError):
        raise PreviewSandboxError(
            f"Preview отказался писать {what} вне изолированного data root.",
            503,
            code="preview_target_not_isolated",
        ) from None
    return target


def _seed_ai_lab_research() -> None:
    """Two catalogued research directions so AI Lab is browsable, not empty."""
    from .ai_lab import paths as ai_lab_paths, research_catalog

    _require_isolated_target(ai_lab_paths.REGISTRY_DIR, what="AI Lab registry")
    research_catalog.create({
        "title": "MNQ · ликвидностные свипы на открытии",
        "source_type": "research",
        "family_name": "MNQ Liquidity Sweep",
        "summary": "Synthetic Preview: гипотезы разворота после снятия ликвидности.",
        "objectives": [
            "Проверить разворот после свипа предыдущего экстремума",
            "Сравнить утреннюю и дневную сессии",
        ],
        "hypotheses": [
            "Свип уровня азиатской сессии даёт положительное матожидание",
        ],
        "content": (
            "Preview sandbox: материал создан локально для визуальной проверки "
            "AI Lab. Реальные модели и внешние источники не вызывались."
        ),
    })
    research_catalog.create({
        "title": "MGC · контроль риска на лондонской сессии",
        "source_type": "research",
        "family_name": "MGC Risk Pilot",
        "summary": "Synthetic Preview: ограничение просадки золота в лондонскую сессию.",
        "objectives": ["Ограничить дневную просадку", "Сократить число сделок"],
        "content": (
            "Preview sandbox: synthetic-исследование без обращения к внешним "
            "сервисам."
        ),
    })


def _seed_strategy_catalog() -> None:
    now = _now()
    catalog = jobqueue.catalog_dir()
    profiles = jobqueue.profiles_dir()
    _atomic_json(catalog / "instruments.json", {
        "generated_at_utc": now,
        "count": 2,
        "instruments": [
            {
                "instrument": "MNQ SEP26", "root": "MNQ", "master_instrument": "MNQ",
                "exchange": "CME", "tick_size": 0.25, "point_value": 2,
                "has_minute_data": True, "data_first": "2026-06-01", "data_last": "2026-09-03",
            },
            {
                "instrument": "MGC OCT26", "root": "MGC", "master_instrument": "MGC",
                "exchange": "COMEX", "tick_size": 0.1, "point_value": 10,
                "has_minute_data": True, "data_first": "2026-06-01", "data_last": "2026-09-03",
            },
        ],
        "preview_synthetic": True,
    })
    _atomic_json(catalog / "strategies.json", {
        "generated_at_utc": now,
        "count": 2,
        "strategies": [
            {"class_name": "NTAMnqLiquiditySweepReversalC015", "display_name": "MNQ Liquidity Sweep · Preview"},
            {"class_name": "B1Stop24MGC5mC003", "display_name": "MGC Risk Pilot · Preview"},
        ],
        "preview_synthetic": True,
    })
    _atomic_json(profiles / "strategies.json", {
        "schema_version": "1.1",
        "generated_at_utc": now,
        "preview_synthetic": True,
        "profiles": [
            {
                "profile_id": "preview-mnq-c015", "strategy_id": "ntamnqliquiditysweepreversalc015",
                "class_name": "NTAMnqLiquiditySweepReversalC015", "name": "MNQ Liquidity Sweep · Preview",
                "root": "MNQ", "cell_id": "C015", "status": "paper_ready",
                "status_label": "Paper ready", "notes": "Synthetic Preview strategy",
            },
            {
                "profile_id": "preview-mgc-c003", "strategy_id": "b1stop24mgc5mc003",
                "class_name": "B1Stop24MGC5mC003", "name": "MGC Risk Pilot · Preview",
                "root": "MGC", "cell_id": "C003", "status": "testing",
                "status_label": "Testing", "notes": "Synthetic Preview strategy",
            },
        ],
    })
    _atomic_json(runtime_env.data_path("ops", "registry.json"), {
        "schema_version": "1.0",
        "generated_at_utc": now,
        "preview_synthetic": True,
        "strategies": [{
            "strategy_id": "ntamnqliquiditysweepreversalc015",
            "display_name": "MNQ Liquidity Sweep · Preview",
            "class_name": "NTAMnqLiquiditySweepReversalC015",
            "status": "paper_ready", "account_mode": "demo",
            "allowed_accounts": ["DEMO-PREVIEW-101"], "instrument": "MNQ SEP26",
            "locked_params": {"RoundTurnCommission": 1.90},
        }],
    })


def _seed_chat(user: Dict[str, Any], workspace: Dict[str, Any]) -> None:
    try:
        from .ai_lab import chief_agent, paths as ai_lab_paths

        _require_isolated_target(ai_lab_paths.REGISTRY_DIR, what="SF Chat store")
        scope = {
            "user_id": int(user.get("user_id") or 0),
            "user_uuid": str(user.get("user_uuid") or ""),
            "workspace_id": str(workspace.get("workspace_id") or ""),
            "membership_role": "owner",
        }
        conversation = chief_agent.create_conversation(
            "Preview: разбор утренней сессии", scope=scope,
        )
        cid = str(conversation.get("conversation_id") or "")
        path = chief_agent._conversation_file(cid, scope=scope)
        chief_agent._append_conversation(
            "user", "Покажи краткий разбор synthetic-сделок за сегодня.",
            source="preview_synthetic", path=path, scope=scope,
        )
        chief_agent._append_conversation(
            "assistant",
            "Preview dataset готов: 3 завершённые synthetic-сделки, результат положительный. Реальные ордера не отправлялись.",
            source="preview_synthetic", agent_name="Витёк", agent_id="vitek",
            provider="preview", model="synthetic", path=path, scope=scope,
        )
    except Exception:
        # Chat is supplemental; status records a failure only through the caller.
        raise


def ensure_synthetic_dataset(user_id: int) -> Dict[str, Any]:
    require_enabled()
    user = _mark_preview_user(int(user_id or 0))
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        stored = account_auth._user(doc, int(user_id))
        if stored and stored.get("preview_dataset_version") == 1:
            existing = {
                "ok": True,
                "ready": True,
                "user_id": int(user_id),
                "errors": list(stored.get("preview_dataset_errors") or []),
            }
        else:
            existing = {}
    if existing:
        # The dataset survives re-authentication inside the same sandbox; the
        # synthetic bridge clock has to keep running with it.
        try:
            _start_runtime_clock(_runtime_dirs(workspaces.ensure_personal_workspace(
                user_id,
                display_name="Preview Personal Workspace",
                require_entitlement=False,
            )))
        except Exception:
            pass
        return existing

    errors: List[str] = []
    workspace: Dict[str, Any] = {}
    try:
        entitlement = subscriptions.activate_paid(
            user_id, "pro", provider="preview_synthetic",
            provider_subscription_id=f"preview-{_safe_id()}-{user_id}",
        ).get("entitlement") or {}
        workspace = workspaces.ensure_personal_workspace(
            user_id,
            display_name="Preview Personal Workspace",
            entitlement_id=str(entitlement.get("entitlement_id") or ""),
            require_entitlement=False,
        )
    except Exception as exc:
        errors.append(f"workspace:{type(exc).__name__}")

    workspace_id = str(workspace.get("workspace_id") or "")
    if workspace_id:
        try:
            pairing = workspaces.start_bridge_pairing(
                user_id, workspace_id=workspace_id, machine_label="Preview Workstation",
            )
            workspaces.complete_bridge_pairing(
                user_id,
                code=pairing.get("code"),
                device_id="preview-workstation",
                bridge_instance_id=f"preview-bridge-{_safe_id()[:8]}",
                machine_label="Preview Workstation",
                capabilities=["accounts_read", "paper_commands"],
            )
        except Exception as exc:
            errors.append(f"bridge:{type(exc).__name__}")
        try:
            runtime_dirs = _runtime_dirs(workspace)
            for runtime_dir in runtime_dirs:
                _seed_runtime_files(runtime_dir)
            _start_runtime_clock(runtime_dirs)
        except Exception as exc:
            errors.append(f"runtime:{type(exc).__name__}")
        try:
            practice_trading.create_account(
                user_id, deposit=50_000, commission=1.90,
                daily_loss_limit=1_000, max_drawdown=2_000,
                position_limit=4, symbol="MNQ", workspace_id=workspace_id,
            )
        except Exception as exc:
            errors.append(f"practice:{type(exc).__name__}")
        for scenario_id in ("mnq_orb_90d", "mes_vwap_90d", "mgc_london_30d"):
            try:
                demo_backtest.create_demo_backtest(
                    user_id, scenario_id=scenario_id,
                    daily_limit=10, workspace_id=workspace_id,
                )
            except Exception as exc:
                errors.append(f"backtest:{scenario_id}:{type(exc).__name__}")
        display = "Алекс Preview"
        try:
            community.post_message(
                user_id,
                text="Проверяю Preview sandbox: это synthetic-публикация без Telegram mirror.",
                display_name=display,
                workspace_id=workspace_id,
                channel_id="general",
                idempotency_key="preview-welcome",
                user_uuid=user.get("user_uuid"),
            )
            community.share_report(
                user_id,
                title="MNQ Preview — утренняя сессия",
                summary="Synthetic report для визуальной проверки Community.",
                metrics={"net_profit": 725.50, "win_rate": 66.7, "max_drawdown": 184.25},
                display_name=display,
                workspace_id=workspace_id,
                user_uuid=user.get("user_uuid"),
            )
            community.publish_strategy(
                user_id,
                title="MNQ Liquidity Sweep · Preview",
                metrics={"net_profit": 725.50, "win_rate": 66.7, "profit_factor": 1.84},
                notes="Synthetic strategy — только Preview sandbox.",
                display_name=display,
                workspace_id=workspace_id,
                idempotency_key="preview-strategy",
                user_uuid=user.get("user_uuid"),
            )
        except Exception as exc:
            errors.append(f"community:{type(exc).__name__}")
        try:
            _seed_chat(user, workspace)
        except Exception as exc:
            errors.append(f"chat:{type(exc).__name__}")

    try:
        _seed_strategy_catalog()
    except Exception as exc:
        errors.append(f"catalog:{type(exc).__name__}")
    try:
        _seed_ai_lab_research()
    except Exception as exc:
        errors.append(f"ai_lab_research:{type(exc).__name__}")
    try:
        # Local rule-based schedule generator; it performs no network call and
        # writes only inside this data root.
        from . import market_events

        market_events.write_news_json()
    except Exception as exc:
        errors.append(f"calendar:{type(exc).__name__}")
    try:
        _seed_security_inventory(user_id)
    except Exception as exc:
        errors.append(f"security_inventory:{type(exc).__name__}")
    try:
        in_app_notifications.record(
            "Preview sandbox готов",
            ["Synthetic dataset создан.", "Платежи, live trading и внешние вызовы заблокированы."],
            urgent=False,
            dedupe_key=f"preview-ready-{user_id}",
            kind="preview_synthetic",
        )
        in_app_notifications.record(
            "Новый доступ ожидает проверки",
            ["Откройте Безопасность → Устройства, чтобы проверить список клиентов."],
            urgent=True,
            dedupe_key=f"preview-security-{user_id}",
            kind="security",
        )
    except Exception as exc:
        errors.append(f"notifications:{type(exc).__name__}")

    with account_auth._LOCK:
        doc = account_auth._read_doc()
        stored = account_auth._user(doc, int(user_id))
        if stored:
            stored["preview_dataset_version"] = 1
            stored["preview_dataset_generated_at_utc"] = _now()
            stored["preview_dataset_errors"] = errors
            account_auth._write_doc(doc)
    with _LOCK:
        _STATE["dataset_ready"] = True
        _STATE["dataset_errors"] = errors
        _write_manifest()
    return {"ok": True, "ready": True, "user_id": user_id, "errors": errors}


def after_public_auth(result: Dict[str, Any]) -> None:
    """Attach a newly registered real-flow account to this synthetic sandbox."""
    if not enabled() or str(result.get("status") or "") != "authenticated":
        return
    user = _find_user_by_public(result.get("user") or {})
    if not user or user.get("is_owner"):
        raise PreviewSandboxError(
            "Preview registration resolved outside synthetic identity.",
            409,
            code="preview_owner_resolution_blocked",
        )
    uid = int(user.get("user_id") or 0)
    marked = _mark_preview_user(uid)
    context = account_auth.authenticate_session(str(result.get("session_token") or "")) or {}
    with _LOCK:
        _STATE.update({
            "current_user_id": uid,
            "current_user_uuid": str(marked.get("user_uuid") or ""),
            "current_session_id": str(context.get("session_id") or ""),
        })
        _write_manifest()
    ensure_synthetic_dataset(uid)


def activate_scenario(scenario: Any, *, device_credential: str) -> Dict[str, Any]:
    require_enabled()
    selected = normalize_scenario(scenario)
    credential = str(device_credential or "").strip()
    if len(credential) < 16:
        raise PreviewSandboxError("Preview device credential отсутствует.", 503)
    os.environ["STRATFORGE_PREVIEW_SCENARIO"] = selected
    with _LOCK:
        _STATE.update({
            "scenario": selected,
            "current_user_id": 0,
            "current_user_uuid": "",
            "current_session_id": "",
            "dataset_ready": False,
            "dataset_errors": [],
        })
        _write_manifest()
    if selected == "new_user":
        return {"ok": True, "scenario": selected, "authenticated": False}

    generation = int(_STATE.get("generation") or 1)
    registration_credential = (
        credential if selected in {"active_user", "trusted_device"}
        else "preview-known-device-" + secrets.token_urlsafe(18)
    )
    registered = _register_synthetic_user(registration_credential, generation)
    mode = (
        security_devices.TRUST_MODE_SESSION
        if selected == "active_user"
        else security_devices.TRUST_MODE_PERMANENT
    )
    approved = _approve_session(str(registered["session_token"]), mode)
    user_id = int(registered["user_id"])
    ensure_synthetic_dataset(user_id)
    token = str(registered["session_token"])
    context = approved.get("context") or {}
    if selected == "pending_access":
        pending = account_auth.create_session_for_user(
            user_id,
            ip="203.0.113.42",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            source="preview_new_client",
            skip_dual_auth_gate=True,
            device_credential=credential,
            device_confirmation_required=True,
        )
        token = str(pending.get("session_token") or "")
        context = account_auth.authenticate_session(token) or {}
    with _LOCK:
        _STATE.update({
            "current_user_id": user_id,
            "current_user_uuid": str(registered.get("user_uuid") or ""),
            "current_session_id": str(context.get("session_id") or ""),
            "dataset_ready": True,
        })
        _write_manifest()
    return {
        "ok": True,
        "scenario": selected,
        "authenticated": True,
        "session_token": token,
        "session_cookie_persistent": bool(
            str(context.get("device_trust_mode") or "") == security_devices.TRUST_MODE_PERMANENT
        ),
        "user_id": user_id,
        "device_access": context.get("device_access") or {},
    }


def enter(entry_token: Any, *, device_credential: str) -> Dict[str, Any]:
    consume_entry_token(entry_token)
    with _LOCK:
        _STATE["generation"] = max(1, int(_STATE.get("generation") or 0) + 1)
    scenario = normalize_scenario(os.environ.get("STRATFORGE_PREVIEW_SCENARIO") or "new_user")
    return activate_scenario(scenario, device_credential=device_credential)


def reset(scenario: Any, *, device_credential: str) -> Dict[str, Any]:
    require_enabled()
    selected = normalize_scenario(scenario)
    with _LOCK:
        generation = int(_STATE.get("generation") or 0) + 1
    _wipe_isolated_root()
    with _LOCK:
        _STATE["generation"] = generation
    return activate_scenario(selected, device_credential=device_credential)


def new_user(*, device_credential: str) -> Dict[str, Any]:
    return reset("new_user", device_credential=device_credential)


def simulate_new_client(*, device_credential: str) -> Dict[str, Any]:
    require_enabled()
    with _LOCK:
        user_id = int(_STATE.get("current_user_id") or 0)
    if user_id <= 0:
        raise PreviewSandboxError(
            "Сначала создайте или откройте active synthetic user.",
            409,
            code="preview_user_required",
        )
    pending = account_auth.create_session_for_user(
        user_id,
        ip="203.0.113.99",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0"
        ),
        source="preview_simulated_client",
        skip_dual_auth_gate=True,
        device_credential=device_credential,
        device_confirmation_required=True,
    )
    token = str(pending.get("session_token") or "")
    context = account_auth.authenticate_session(token) or {}
    os.environ["STRATFORGE_PREVIEW_SCENARIO"] = "pending_access"
    with _LOCK:
        _STATE["scenario"] = "pending_access"
        _STATE["current_session_id"] = str(context.get("session_id") or "")
        _write_manifest()
    return {
        "ok": True,
        "scenario": "pending_access",
        "authenticated": True,
        "session_token": token,
        "session_cookie_persistent": False,
        "user_id": user_id,
        "device_access": context.get("device_access") or {},
    }


def status() -> Dict[str, Any]:
    require_enabled()
    with _LOCK:
        state = dict(_STATE)
    state.pop("current_token", None)
    return {
        "ok": True,
        "available": True,
        "preview_sandbox": runtime_env.preview_public_metadata(),
        "state": state,
        "scenarios": scenario_catalog(),
        "data_root_fingerprint": hashlib.sha256(str(isolated_root()).encode("utf-8")).hexdigest()[:16],
        "external_side_effects": "blocked",
        "exit_url": exit_url(),
    }
