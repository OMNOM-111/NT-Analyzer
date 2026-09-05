"""Local-owner HTTP projection; auth/device/CSRF stay in the existing Handler."""
from uuid import UUID

from .. import account_auth, permissions, workspaces
from . import live_gateway as gateway, live_charts
from .live_backtests import LiveBacktestService
from .states import ContractError


def _error(handler, exc):
    code = str(exc) if isinstance(exc, ContractError) else "agent_world_access_denied"
    handler._err(403 if any(word in code for word in ("required", "denied", "disabled", "context", "scope")) else 409,
                 "AI Центр: действие недоступно или данные изменились.", code=code)


def handle_get(handler, path, qs):
    try:
        authorized = gateway.from_handler(handler)
        route = path.removeprefix(gateway.PREFIX)
        service, args = LiveBacktestService(), gateway.service_args(authorized)
        if route == "overview":
            handler._json(200, gateway.overview(authorized))
        elif route == "tasks":
            handler._json(200, {"items": gateway.overview(authorized)["tasks"], "next_cursor": None, "read_limit": 200})
        elif route.startswith("tasks/") and len(route.split("/")) == 2:
            detail = service.task_detail(**args, entity_id=UUID(route.split("/")[1]))
            if detail is None:
                detail = next((item for item in live_charts.details(authorized) if item["task"]["id"] == route.split("/")[1]), None)
            if detail is None:
                handler._err(404, "Задача не найдена.", code="task_not_found")
            else:
                handler._json(200, detail)
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
        authorized = gateway.from_handler(handler)
        route = path.removeprefix(gateway.PREFIX)
        if not isinstance(body, dict):
            raise ContractError("invalid_request")
        if route == "backtests":
            if set(body) != {"spec", "idempotency_key", "conversation_id"}:
                raise ContractError("live_backtest_explicit_spec_required")
            result = LiveBacktestService().start(**gateway.service_args(authorized), **body)
            handler._json(200, result)
        elif route.startswith("tasks/") and route.endswith("/chat") and len(route.split("/")) == 3:
            if body:
                raise ContractError("invalid_request")
            detail = LiveBacktestService().task_detail(**gateway.service_args(authorized), entity_id=UUID(route.split("/")[1]))
            if detail is None:
                detail = next((item for item in live_charts.details(authorized) if item["task"]["id"] == route.split("/")[1]), None)
            if detail is None:
                handler._err(404, "Задача не найдена.", code="task_not_found")
            else:
                # Opening a thread is not a completion/evaluation side effect.
                handler._json(200, {"conversation_id": detail["task"]["conversation_id"]})
        else:
            handler._err(404, "Маршрут AI Центра не найден.", code="route_not_found")
    except (ContractError, account_auth.AccountAuthError, permissions.PermissionError, workspaces.WorkspaceError) as exc:
        _error(handler, exc)
    except (ValueError, TypeError):
        handler._err(400, "Некорректный запрос.", code="invalid_request")
