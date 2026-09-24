"""Disposable Preview's bounded call-only bridge to explicitly shared Local models.

The child receives opaque model handles, never connection settings or provider
credentials. The parent rechecks sharing and existing budgets on every call.
No generic HTTP proxy, filesystem operation or model-management action exists.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID, uuid5, NAMESPACE_URL

from . import account_auth, preview_sandbox, runtime_env
from .ai_control_center.states import ContractError


def enabled():
    return (preview_sandbox.enabled()
            and os.environ.get("STRATFORGE_PREVIEW_SCENARIO") != "agent_world_operator"
            and transport_enabled())


def transport_enabled():
    return (preview_sandbox.enabled() and bool(os.environ.get("STRATFORGE_PREVIEW_MODEL_BRIDGE"))
            and bool(os.environ.get("STRATFORGE_PREVIEW_MODEL_TOKEN")))


class Bridge:
    """One parent-owned capability, revoked when its Preview process exits."""

    def __init__(self, preview_id, *, allow_models=True):
        if not runtime_env.is_development() or preview_sandbox.enabled():
            raise ContractError("preview_bridge_development_required")
        self.preview_id = preview_id
        self.allow_models = allow_models
        self.token = secrets.token_urlsafe(48)
        self.started = time.monotonic()
        self.closed = False
        self.lock = threading.Lock()
        self.results = {}
        self.spent = 0.0
        self.last_error = None
        self.chart_connections = set()
        self.chart_lock = threading.Lock()
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                from . import owner_market_data_gateway, market_data_ws_http
                path = urllib.parse.urlsplit(self.path).path
                try:
                    bridge.authorize_chart(self.headers.get(owner_market_data_gateway.TOKEN_HEADER), path)
                except ContractError:
                    self.send_error(403, "preview chart capability denied")
                    return
                if path == "/ws/market-data":
                    with bridge.chart_lock:
                        if bridge.closed:
                            self.send_error(403)
                            return
                        bridge.chart_connections.add(self.connection)
                    stopped = threading.Event()
                    def watch_preview():
                        # Read-only charts follow the disposable process, not
                        # the separate paid-model call budget/30-minute limit.
                        while not stopped.wait(15):
                            try:
                                bridge.authorize_chart(bridge.token, path)
                            except ContractError:
                                try:
                                    self.connection.shutdown(socket.SHUT_RDWR)
                                except OSError:
                                    pass
                                return
                    threading.Thread(target=watch_preview, daemon=True, name="preview-chart-lease").start()
                    try:
                        self._remote_context = owner_market_data_gateway.service_context()
                        market_data_ws_http.handle_websocket_upgrade(self)
                    finally:
                        stopped.set()
                        with bridge.chart_lock:
                            bridge.chart_connections.discard(self.connection)
                    return
                try:
                    result = bridge.chart_history(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
                    encoded = json.dumps(result, ensure_ascii=False).encode()
                except Exception:
                    self.send_error(502, "chart history unavailable")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)

            def do_POST(self):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 2 <= size <= 50000 or self.path not in {"/catalog", "/invoke", "/social", "/account-deleted"}:
                        raise ContractError("preview_bridge_invalid_request")
                    encoded_body = self.rfile.read(size)
                    if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + bridge.token):
                        raise ContractError("preview_bridge_denied")
                    body = json.loads(encoded_body)
                    result = bridge.dispatch(self.path, body)
                    code = 200
                except Exception as exc:
                    bridge.last_error = str(exc) if isinstance(exc, ContractError) else type(exc).__name__
                    code, result = 403, {"error": "preview_shared_call_denied"}
                encoded = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        threading.Thread(target=self.server.serve_forever, daemon=True, name="preview-model-bridge").start()

    def close(self):
        self.closed = True
        with self.chart_lock:
            connections = list(self.chart_connections)
            self.chart_connections.clear()
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.results.clear()

    def authorize_chart(self, supplied, path):
        from . import dev_preview
        active = dev_preview._ACTIVE_SANDBOX or {}
        if (not runtime_env.is_development() or preview_sandbox.enabled()
                or self.closed
                or path not in {"/api/ops/runtime/bars", "/ws/market-data"}
                or not hmac.compare_digest(str(supplied or ""), self.token)
                or active.get("preview_id") != self.preview_id
                or active.get("model_bridge") is not self
                or not dev_preview._validated_preview_container(active)
                or active.get("process") is None or active["process"].poll() is not None):
            raise ContractError("preview_chart_capability_denied")

    @staticmethod
    def chart_history(query):
        from . import server, market_data_access, owner_market_data_gateway
        def value(key, default=""):
            return str((query.get(key) or [default])[0])[:160]
        instrument, timeframe = value("instrument"), value("timeframe", "1m")
        if not instrument or len(query) > 8:
            raise ContractError("preview_chart_invalid_query")
        result = server._market_bars_payload(
            instrument, timeframe, max(1, min(int(value("limit", "1500")), 20000)),
            register=False, alerts_index={}, from_ts=value("from_ts"), to_ts=value("to_ts"),
            access_decision=market_data_access.resolve_market_data_access(owner_market_data_gateway.service_context()),
        )
        # Chart transport never projects alerts, account positions or orders.
        allowed = {"instrument", "timeframe", "live", "status", "bars", "total"}
        payload = {key: result[key] for key in allowed if key in result}
        for name, keys in {
            "source": {"runtime_state", "cache_hit", "history_exhausted", "native_aggregation_fallback"},
            "history": {"requested_start_utc", "requested_end_utc", "cache_hit", "chunks", "exhausted", "native_aggregation_fallback"},
            "freshness": {"market_feed_fresh", "market_feed_stale", "offline", "market_feed_age_sec", "signalr_heartbeat_age_sec", "quote_age_sec", "bid_ask_age_sec", "last_trade_age_sec", "market_feed_as_of_utc"},
        }.items():
            row = result.get(name) or {}
            payload[name] = {key: row[key] for key in keys if key in row}
        payload["bars"] = [{key: row[key] for key in ("t", "o", "h", "l", "c", "v", "time", "open", "high", "low", "close", "volume") if key in row}
                           for row in payload.get("bars", []) if isinstance(row, dict)]
        return payload

    def _catalog(self):
        if not self.allow_models:
            return {}
        from .ai_control_center import model_sharing
        rows = model_sharing.available(environment="development", caller_user_uuid="preview:" + self.preview_id)
        return {hmac.new(self.token.encode(), row["model_id"].encode(), hashlib.sha256).hexdigest(): row for row in rows}

    def dispatch(self, path, body):
        if self.closed or time.monotonic() - self.started > 1800:
            raise ContractError("preview_bridge_expired")
        if path == "/social":
            if body != {}:
                raise ContractError("preview_bridge_invalid_request")
            from . import community, preview_public
            with community._LOCK:
                return preview_public.snapshot(community._load(include_preview=False))
        if path == "/account-deleted":
            from . import account_lifecycle, dev_preview
            if type(body) is not dict or set(body) != {"user", "reason"}:
                raise ContractError("preview_bridge_invalid_request")
            user = body["user"]
            if type(user) is not dict or set(user) != {"user_id", "user_uuid", "email", "created_at_utc"}:
                raise ContractError("preview_bridge_invalid_request")
            uid = str(UUID(user["user_uuid"]))
            if account_auth.find_active_user_by_uuid(uid) is not None:
                raise ContractError("preview_bridge_existing_identity_denied")
            active = dev_preview._ACTIVE_SANDBOX or {}
            container = dev_preview._validated_preview_container(active)
            if not container or active.get("preview_id") != self.preview_id:
                raise ContractError("preview_bridge_scope_invalid")
            original = next((row for row in account_lifecycle.preview_accounts(container, self.preview_id)
                             if account_auth._user_uuid(row) == uid and row.get("user_id") == user.get("user_id")), None)
            if original is None:
                raise ContractError("preview_bridge_scope_invalid")
            with self.lock:
                result = account_lifecycle.record_deletion(original, str(body["reason"]), preview=True)
                self.results = {key: value for key, value in self.results.items() if key[0] != uid}
                return result
        from .ai_control_center import model_sharing, contracts as c
        from .ai_control_center.model_service import ModelService
        from .ai_control_center.model_execution import ModelExecutor
        from .ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
        from .ai_control_center.domain_gateway import _private_limits
        with self.lock:
            if self.closed or time.monotonic() - self.started > 1800:
                raise ContractError("preview_bridge_expired")
            if type(body) is not dict:
                raise ContractError("preview_bridge_invalid_request")
            catalog = self._catalog()
            if path == "/catalog":
                if body:
                    raise ContractError("preview_bridge_invalid_request")
                return {"items": [{"handle": handle, "label": row["label"],
                    "provider": row["provider"], "model": row["model_key"]} for handle, row in catalog.items()]}
            if path != "/invoke" or set(body) != {"handle", "user_uuid", "workspace_id", "task_id", "agent", "prompt", "system_prompt"}:
                raise ContractError("preview_bridge_invalid_request")
            uid = str(UUID(body["user_uuid"]))
            from . import account_lifecycle
            if uid in account_lifecycle.deleted_ids():
                raise ContractError("model_caller_deleted")
            if account_auth.find_active_user_by_uuid(uid) is not None:
                raise ContractError("preview_bridge_existing_identity_denied")
            workspace = str(body["workspace_id"])
            if not workspace.startswith("ws_personal_") or len(workspace) > 96:
                raise ContractError("preview_bridge_scope_invalid")
            for field, limit in (("prompt", 20000), ("system_prompt", 10000), ("agent", 80), ("task_id", 160)):
                if type(body[field]) is not str or len(body[field]) > limit:
                    raise ContractError("preview_bridge_invalid_request")
            share = catalog.get(body["handle"])
            if share is None:
                raise ContractError("model_share_revoked")
            fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            key = (uid, workspace, body["task_id"])
            if key in self.results:
                prior_hash, prior = self.results[key]
                if prior_hash != fingerprint or prior is None:
                    raise ContractError("preview_bridge_replay_denied")
                return prior
            if len(self.results) >= 32 or self.spent >= 0.25:
                raise ContractError("preview_bridge_budget_exhausted")
            self.results[key] = (fingerprint, None)
            ctx = c.RequestContext(scope=c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id=workspace),
                user_uuid=UUID(uid), actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=UUID(uid)))
            grant = model_sharing.Grant(share, caller_user_uuid=uid)
            service = ModelService(SQLiteAgentWorldRepository(runtime_env.data_path("ai_lab", "agent-world.sqlite3"),
                read_only=True), admit=lambda *args: grant.check())
            model, account, profile = service._owner_connection(ctx, share)
            person = {"user_uuid": uid, "is_owner": False, "name": "Preview " + self.preview_id[:8]}
            def admit(context, operation, estimate=0.0):
                if self.closed or context != ctx or time.monotonic() - self.started > 1800:
                    raise ContractError("preview_bridge_expired")
                grant.check()
                if estimate < 0 or self.spent + estimate > 0.25:
                    raise ContractError("preview_bridge_budget_exhausted")
            with model_sharing.preview_principal(person):
                result = ModelExecutor(budget_limits=_private_limits)(context=ctx, model=model, account=account,
                    profile=profile, prompt=body["prompt"], system_prompt=body["system_prompt"],
                    request_id=body["task_id"], conversation_id=body["task_id"], max_output_tokens=512,
                    purpose="assistant_conversation" if body["task_id"].startswith("conversation:") else "preview_shared_model", cancelled=lambda: self.closed, admit=admit,
                    shared=grant, acting_agent=body["agent"])
            safe = {key: result.get(key) for key in ("ok", "response", "actual_model", "request_id",
                "input_tokens", "output_tokens", "cost_usd", "cost_known", "elapsed_sec")}
            safe.update(external_call=True, executor="preview_shared_local_bridge")
            self.spent += float(safe.get("cost_usd") or 0)
            self.results[key] = (fingerprint, safe)
            return safe


def request(path, body):
    if not (transport_enabled() if path in {"/social", "/account-deleted"} else enabled()):
        raise ContractError("preview_bridge_unavailable")
    request = urllib.request.Request(os.environ["STRATFORGE_PREVIEW_MODEL_BRIDGE"] + path,
        data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ["STRATFORGE_PREVIEW_MODEL_TOKEN"]})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=75) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        raise ContractError("preview_shared_call_denied") from None


def authorize(scope, *, read_only=False):
    """Refresh the actual disposable session, never accept a caller's grants."""
    from .ai_control_center import gateway
    from . import permissions, workspaces
    if not enabled() or not isinstance(scope, dict):
        raise ContractError("preview_bridge_unavailable")
    uid = int(scope.get("user_id") or 0)
    sid = str(scope.get("auth_session_id") or "")
    user = account_auth.find_active_user(uid)
    state = preview_sandbox._STATE
    if (not user or user.get("user_uuid") != str(scope.get("user_uuid"))
            or state.get("current_user_id") != uid or state.get("current_session_id") != sid
            or not account_auth.local_session_is_active(sid, uid)
            or not preview_sandbox.synthetic_identity_allowed({"user": user})):
        raise ContractError("preview_bridge_identity_required")
    workspace = workspaces.require_workspace_writer(uid, workspace_id=scope.get("workspace_id"))
    if workspace.get("owner_user_id") != uid or workspace.get("kind") != "personal":
        raise ContractError("preview_bridge_own_workspace_required")
    caps = permissions.resolve_for_user_id(uid, user)["capabilities"]
    raw = {"user": user, "user_uuid": user["user_uuid"], "role": user["role"], "ux_mode": user["ux_mode"],
        "workspace_id": workspace["workspace_id"], "active_membership": workspace["membership"],
        "capabilities": caps, "device_confirmation_state": "active"}
    context = gateway.request_context(raw, control_authorized=True)
    normalized = {**scope, "capabilities": caps, "uses_owner_runtime": False, "is_owner": False}
    return {"context": context, "chat_scope": normalized, "read_only": read_only, "preview_bridge": True,
        "admit": lambda: authorize(normalized, read_only=read_only),
        "refresh": lambda **kw: authorize(normalized, read_only=kw.get("read_only", read_only)),
        "snapshot": gateway.flag_snapshot(context), "source_scope": {"user_id": uid,
            "workspace_id": workspace["workspace_id"], "allow_legacy": False}}


def execute(**kwargs):
    from .ai_control_center import model_sharing
    context = kwargs["context"]
    kwargs["admit"](context, "provider_transmit", 0.0)
    grant = kwargs.get("shared")
    if grant is None:
        raise ContractError("preview_bridge_shared_only")
    grant.check()
    handle = kwargs["profile"].get("existing_registry_id", "").removeprefix("AGT-")
    result = request("/invoke", {"handle": handle, "user_uuid": str(context.user_uuid),
        "workspace_id": context.scope.workspace_id, "task_id": str(kwargs["request_id"]),
        "agent": str(kwargs.get("acting_agent") or "Preview assistant"),
        "prompt": kwargs["prompt"], "system_prompt": kwargs["system_prompt"]})
    model_sharing.observe({**result, "status": "success", "purpose": kwargs.get("purpose") or "preview_shared_model"},
        {"user_id": str(context.user_uuid), "workspace_id": context.scope.workspace_id,
         "request_source": "agent_world." + str(kwargs["request_id"]),
         "acting_agent": str(kwargs.get("acting_agent") or "Preview assistant")}, grant=grant.share)
    return result


def _scope(handler):
    if not handler._preview_control_authorized():
        raise ContractError("preview_control_required")
    scope = dict(handler._ai_conversation_scope())
    scope["auth_session_id"] = str((handler._remote_context or {}).get("session_id") or "")
    return scope


def sync_catalog(service):
    """Import only public call descriptors as isolated proxy records."""
    from .ai_control_center import contracts as c, model_sharing
    from .ai_control_center.model_service import ModelService
    preview_id = os.environ["STRATFORGE_PREVIEW_ID"]
    identity = uuid5(NAMESPACE_URL, "preview-shared-donor:" + preview_id)
    donor = c.RequestContext(scope=c.TenantScope(environment=c.Environment.DEVELOPMENT,
        workspace_id="ws_preview_donor_" + preview_id), user_uuid=identity,
        actor=c.ActorRef(kind=c.ActorKind.SERVICE, actor_id=identity, on_behalf_of=identity))
    def admit_proxy(context, *args):
        preview_sandbox.require_enabled()
        if context != donor:
            raise ContractError("preview_proxy_scope_invalid")
    proxy = ModelService(service.repository, admit=admit_proxy)
    policy = proxy._put(donor, {"source": "preview_shared_call_descriptor"})
    persona_id = uuid5(identity, "connection-descriptors")
    proxy._walk(donor, proxy._ensure(donor, c.Persona, persona_id, persona_id, policy,
        display_name="Local shared models", profile=proxy._put(donor, {"description": "Call descriptors only"})), "active")
    active = set()
    for row in request("/catalog", {})["items"]:
        binding = {"id": "AGT-" + row["handle"], "name": row["label"], "provider": row["provider"],
            "model": row["model"], "base_url": "", "pricing_status": "configured"}
        item = proxy.bind_existing_model(context=donor, payload={"registry_id": binding["id"],
            "persona_id": str(persona_id)}, idempotency_key="preview-share-" + row["handle"],
            resolve_binding=lambda *a, value=binding: value)
        proxy.set_sharing(context=donor, model_id=item["id"], shared=True)
        active.add(item["id"])
    for old in model_sharing.available(environment="development", caller_user_uuid=""):
        if old["owner_user_uuid"] == str(identity) and old["model_id"] not in active:
            proxy.set_sharing(context=donor, model_id=old["model_id"], shared=False)


class SharedDomains:
    def __init__(self, base, handler):
        self.base, self.handler = base, handler

    def __getattr__(self, name):
        return getattr(self.base, name)

    def _open(self):
        from .ai_control_center import domain_gateway
        authorized = authorize(_scope(self.handler))
        service = domain_gateway.models(authorized)
        sync_catalog(service)
        return authorized, service

    def list(self, domain, identity=None, **kwargs):
        if domain not in {"models", "model_tasks", "tasks"}:
            return self.base.list(domain, identity=identity, **kwargs)
        authorized, service = self._open()
        context = authorized["context"]
        if domain == "models":
            if identity:
                return service.model_detail(context=context, model_id=identity)
            result = service.models(context=context)
            result["actions"] = []
            result["limitations"] = ["Live shared Local calls only; owner keys/settings stay in Local. Preview data is disposable."]
            return result
        return (service.task_detail(context=context, task_id=identity) if identity else service.tasks(context=context))

    def mutate(self, domain, identity, action, body):
        if domain not in {"models", "model_tasks"}:
            return self.base.mutate(domain, identity, action, body)
        if domain != "models" or action not in {"task", "test"}:
            raise ContractError("preview_bridge_shared_only")
        payload, key = self.base._envelope(body)
        authorized, service = self._open()
        return run_task(authorized, service, identity, payload, key, test=action == "test")


def run_task(authorized, service, identity, payload, key, *, conversation_id=None, user_message=None, test=False, deputy=False):
    from .ai_control_center import model_chat
    detail = service.model_detail(context=authorized["context"], model_id=identity)
    if detail.get("ownership") != "shared":
        raise ContractError("preview_bridge_shared_only")
    task = model_chat.start(authorized, service, identity, payload, key,
        conversation_id=conversation_id, user_message=user_message, test=test, deputy=deputy)
    service.execute(context=authorized["context"], task_id=task["id"])
    done = service.task_detail(context=authorized["context"], task_id=task["id"])
    model_chat.publish(authorized, done)
    return done


def chat(handler, body):
    from .ai_control_center import domain_gateway, model_chat
    if type(body) is not dict or not isinstance(body.get("message"), str):
        raise ContractError("preview_chat_invalid")
    authorized = authorize(_scope(handler))
    service = domain_gateway.models(authorized)
    sync_catalog(service)
    available = [row for row in service.shared_models(context=authorized["context"]) if row["shared_access"] == "available"]
    if not available:
        raise ContractError("model_share_revoked")
    identity = body.get("selected_model_id") or available[0]["id"]
    if identity not in {row["id"] for row in available}:
        raise ContractError("model_share_not_found")
    from .ai_control_center import deputy_chat
    if not deputy_chat.is_work_request(body["message"]):
        return deputy_chat.reply(authorized, service, identity, message=body["message"],
            conversation_id=str(body.get("conversation_id") or "preview-shared-chat"),
            request_id=str(body.get("request_id") or "preview-chat-" + secrets.token_hex(12)))
    done = run_task(authorized, service, identity,
        {"rubric_key": "assistant_response", "input_text": body["message"]},
        str(body.get("request_id") or "preview-chat-" + secrets.token_hex(12)),
        conversation_id=str(body.get("conversation_id") or "preview-shared-chat"), user_message=body["message"], deputy=True)
    return model_chat.publish(authorized, done)
