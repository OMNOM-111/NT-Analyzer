"""Local-owner HTTP projection; auth/device/CSRF stay in the existing Handler."""
from uuid import UUID

from .. import account_auth, permissions, workspaces
from . import live_gateway as gateway, live_charts, domain_gateway
from .live_backtests import LiveBacktestService
from .states import ContractError


def _error(handler, exc):
    code = str(exc) if isinstance(exc, ContractError) else "agent_world_access_denied"
    handler._err(403 if any(word in code for word in ("required", "denied", "disabled", "context", "scope")) else 409,
                 "AI Центр: действие недоступно или данные изменились.", code=code)


def _base_overview(authorized):
    scope = authorized["chat_scope"]
    if scope.get("is_owner") and scope.get("uses_owner_runtime") and scope.get("membership_role") == "owner":
        return gateway.overview(gateway.access(scope))
    return {}


def _task_detail(authorized, identity):
    UUID(identity)
    if authorized.get("read_only") or authorized["chat_scope"].get("capabilities", {}).get("ai_pro_models"):
        try:
            return domain_gateway.models(authorized).task_detail(context=authorized["context"], task_id=identity)
        except ContractError as exc:
            if str(exc) not in {"model_record_not_found", "model_task_not_found"}:
                raise
    scope = authorized["chat_scope"]
    if not scope.get("is_owner") or not scope.get("uses_owner_runtime"):
        return None
    owner = gateway.access(scope)
    detail = LiveBacktestService().task_detail(**gateway.service_args(owner), entity_id=UUID(identity))
    return detail or next((item for item in live_charts.details(owner) if item["task"]["id"] == identity), None)


def handle_get(handler, path, qs):
    try:
        route = path.removeprefix(gateway.PREFIX)
        if route.startswith("domains/") or route.startswith("artifacts/") or route.startswith("memory-artifacts/"):
            authorized = domain_gateway.from_handler(handler, read_only=True)
            parts = route.split("/")
            if parts[0] == "memory-artifacts" and len(parts) == 3:
                domain_gateway.domain_admission(authorized, "memory")
                found = domain_gateway.repository(authorized).read_memory_artifact(context=authorized["context"],
                          memory_id=UUID(parts[1]), artifact_id=UUID(parts[2]))
                if found is None:
                    handler._err(404, "Публикация памяти недоступна или отозвана.", code="memory_artifact_not_found")
                else:
                    reference, content, media_type = found
                    handler._bytes(200, content, media_type, headers={"Content-Security-Policy": "default-src 'none'; sandbox",
                        "ETag": '"' + reference.sha256 + '"', "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
                return
            if parts[0] == "artifacts" and len(parts) == 2:
                found = domain_gateway.repository(authorized).get_artifact_by_id(context=authorized["context"], artifact_id=UUID(parts[1]))
                if found is None:
                    handler._err(404, "Артефакт не найден.", code="artifact_not_found")
                else:
                    reference, content, media_type = found
                    handler._bytes(200, content, media_type, headers={"Content-Security-Policy": "default-src 'none'; sandbox",
                        "ETag": '"' + reference.sha256 + '"', "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
                return
            if len(parts) not in {2, 3} or parts[0] != "domains":
                raise ContractError("invalid_domain_request")
            if set(qs) - {"limit", "cursor"}:
                raise ContractError("invalid_domain_request")
            result = domain_gateway.list_domain(authorized, parts[1], identity=parts[2] if len(parts) == 3 else None,
                    limit=int((qs.get("limit") or ["50"])[0]), cursor=(qs.get("cursor") or [None])[0])
            handler._json(200, domain_gateway.history_projection(authorized, result, domain=parts[1]))
            return
        authorized = domain_gateway.from_handler(handler, read_only=True)
        if route == "overview":
            handler._json(200, domain_gateway.history_projection(authorized, domain_gateway.enrich_overview(authorized, _base_overview(authorized))))
        elif route == "tasks":
            handler._json(200, domain_gateway.history_projection(authorized, {"items": domain_gateway.enrich_overview(authorized, _base_overview(authorized))["tasks"], "next_cursor": None, "read_limit": 200}, domain="tasks"))
        elif route.startswith("tasks/") and len(route.split("/")) == 2:
            detail = _task_detail(authorized, route.split("/")[1])
            if detail is None:
                handler._err(404, "Задача не найдена.", code="task_not_found")
            else:
                handler._json(200, domain_gateway.history_projection(authorized, detail, domain="tasks"))
        else:
            handler._err(404, "Маршрут AI Центра не найден.", code="route_not_found")
    except (ContractError, account_auth.AccountAuthError, permissions.PermissionError, workspaces.WorkspaceError) as exc:
        _error(handler, exc)
    except (ValueError, TypeError):
        handler._err(400, "Некорректный идентификатор.", code="invalid_request")


def handle_post(handler, path):
    if not handler._check_local_post():
        return
    body = handler._read_body()
    if body is None:
        return
    try:
        route = path.removeprefix(gateway.PREFIX)
        if not isinstance(body, dict):
            raise ContractError("invalid_request")
        if route.startswith("domains/"):
            parts = route.split("/")
            if len(parts) != 4:
                raise ContractError("invalid_domain_request")
            authorized = domain_gateway.from_handler(handler)
            handler._json(200, domain_gateway.mutate(authorized, parts[1], parts[2], parts[3], body))
            return
        if route == "backtests":
            authorized = gateway.from_handler(handler)
            if set(body) != {"spec", "idempotency_key", "conversation_id"}:
                raise ContractError("live_backtest_explicit_spec_required")
            result = LiveBacktestService().start(**gateway.service_args(authorized), **body)
            handler._json(200, result)
        elif route.startswith("tasks/") and route.endswith("/chat") and len(route.split("/")) == 3:
            authorized = domain_gateway.from_handler(handler, read_only=True)
            if body:
                raise ContractError("invalid_request")
            detail = _task_detail(authorized, route.split("/")[1])
            if detail is None:
                handler._err(404, "Задача не найдена.", code="task_not_found")
            elif not detail["task"].get("conversation_id"):
                handler._err(409, "У этой внутренней задачи нет диалога SF Chat.", code="task_conversation_unavailable")
            else:
                # Opening a thread is not a completion/evaluation side effect.
                handler._json(200, {"conversation_id": detail["task"]["conversation_id"]})
        else:
            handler._err(404, "Маршрут AI Центра не найден.", code="route_not_found")
    except (ContractError, account_auth.AccountAuthError, permissions.PermissionError, workspaces.WorkspaceError) as exc:
        _error(handler, exc)
    except (ValueError, TypeError):
        handler._err(400, "Некорректный запрос.", code="invalid_request")
