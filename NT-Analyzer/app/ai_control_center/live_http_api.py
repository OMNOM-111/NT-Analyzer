"""Local-owner HTTP projection; auth/device/CSRF stay in the existing Handler."""
from uuid import UUID

from .. import account_auth, permissions, workspaces
from . import duty_bridge, live_gateway as gateway, live_charts, domain_gateway, goals, legacy_view, overview_snapshot, overview_summaries
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
            return domain_gateway.task_detail(authorized, identity)
        except ContractError as exc:
            if str(exc) not in {"model_record_not_found", "model_task_not_found"}:
                raise
    scope = authorized["chat_scope"]
    if not scope.get("is_owner") or not scope.get("uses_owner_runtime"):
        return None
    owner = gateway.access(scope)
    detail = LiveBacktestService().task_detail(**gateway.service_args(owner), entity_id=UUID(identity))
    detail = detail or next((item for item in live_charts.details(owner) if item["task"]["id"] == identity), None)
    if detail:
        # The inspector reads the same computed state as the card that opened
        # it, instead of falling back to the adapter's own source status.
        detail = {**detail, "task": domain_gateway.projected_task(detail["task"])}
    return detail


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
                if found is not None:
                    try:
                        domain_gateway.domains(authorized).get(context=authorized["context"],
                            admit=domain_gateway.domain_admission(authorized, "memory"), domain="memory", entity_id=parts[1])
                    except ContractError:
                        found = None
                if found is None:
                    handler._err(404, "Публикация памяти недоступна или отозвана.", code="memory_artifact_not_found")
                else:
                    reference, content, media_type = found
                    handler._bytes(200, content, media_type, headers={"Content-Security-Policy": "default-src 'none'; sandbox",
                        "ETag": '"' + reference.sha256 + '"', "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
                return
            if parts[0] == "artifacts" and len(parts) == 2:
                found = domain_gateway.repository(authorized).get_artifact_by_id(context=authorized["context"], artifact_id=UUID(parts[1]))
                found = domain_gateway.scoped_memory_artifact(authorized, found)
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
        # The overview is "кратко обо всём": the tab summaries come in the same
        # response, each read through its own domain admission.
        build = lambda: {**domain_gateway.enrich_overview(authorized, _base_overview(authorized)),  # noqa: E731
                         "summaries": overview_summaries.build(authorized)}
        if route == "overview":
            # ?cached=1 asks for the previous overview of this exact
            # authorization for an immediate first paint; the page then reads
            # the fresh projection. Without a previous one it is computed.
            previous = overview_snapshot.last(authorized) if qs.get("cached") == ["1"] else None
            if previous is not None:
                value, computed_at = previous
                handler._json(200, {**domain_gateway.history_projection(authorized, value),
                                    "snapshot": {"cached": True, "computed_at": computed_at}})
            else:
                handler._json(200, domain_gateway.history_projection(authorized, overview_snapshot.fresh(authorized, build)))
        elif route == "goal":
            handler._json(200, {"goal": goals.read(authorized)})
        elif route == "duty":
            # The duty controller's own questions, brought by the deputy.
            handler._json(200, duty_bridge.state(authorized))
        elif route.startswith("legacy"):
            # The frozen old registry, read-only: what was there, whether the
            # archive still matches its checksums, and where the migration stands.
            limit = int((qs.get("limit") or ["100"])[0])
            if route == "legacy":
                handler._json(200, legacy_view.overview(authorized))
            elif route == "legacy/agents":
                handler._json(200, legacy_view.agents(authorized, (qs.get("archive") or [None])[0], limit))
            elif route == "legacy/calls":
                handler._json(200, legacy_view.calls(authorized, limit))
            elif route == "legacy/report":
                handler._json(200, legacy_view.report(authorized))
            else:
                handler._err(404, "Раздел архива не найден.", code="legacy_route_not_found")
        elif route == "tasks":
            handler._json(200, domain_gateway.history_projection(authorized, {"items": overview_snapshot.fresh(authorized, build)["tasks"], "next_cursor": None, "read_limit": 200}, domain="tasks"))
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
        # Any accepted or refused write may change what the overview shows.
        overview_snapshot.invalidate()
        if route.startswith("domains/"):
            parts = route.split("/")
            if len(parts) != 4:
                raise ContractError("invalid_domain_request")
            authorized = domain_gateway.from_handler(handler)
            if parts[1] == "personas" and parts[3] == "speak":
                from ..ai_lab import agent_tts
                try:
                    handler._respond_tts(domain_gateway.speak_persona(authorized, parts[2], body))
                except agent_tts.AgentTtsError:
                    handler._err(409, "Озвучивание сейчас недоступно; текст и аватар сохранены.", code="persona_voice_unavailable")
                return
            handler._json(200, domain_gateway.mutate(authorized, parts[1], parts[2], parts[3], body))
            return
        if route == "goal":
            authorized = domain_gateway.from_handler(handler)
            handler._json(200, {"goal": goals.save(authorized, body.get("goal") if isinstance(body.get("goal"), dict) else body)})
            return
        if route.startswith("duty/"):
            # Answering goes back through the engine that asked, unchanged.
            authorized = domain_gateway.from_handler(handler)
            action = route.split("/", 1)[1]
            user_id = (authorized.get("chat_scope") or {}).get("user_id") or "owner"
            if action == "decide":
                handler._json(200, duty_bridge.decide(authorized, body.get("incident_id"), body.get("decision"),
                                                      note=str(body.get("note") or ""), user_id=user_id))
            elif action == "answer":
                handler._json(200, duty_bridge.answer(authorized, body.get("task_id"), str(body.get("answer") or "")))
            elif action == "pause":
                handler._json(200, duty_bridge.pause(authorized, body.get("minutes") or 0, str(body.get("reason") or "")))
            elif action == "resume":
                handler._json(200, duty_bridge.resume(authorized))
            elif action == "check":
                handler._json(200, duty_bridge.check(authorized))
            else:
                handler._err(404, "Действие Заместителя не найдено.", code="duty_action_not_found")
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
