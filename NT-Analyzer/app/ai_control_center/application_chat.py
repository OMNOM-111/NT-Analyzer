"""Real SF Chat -> private model plan -> existing NT/Desktop -> evidence.

All scheduling, cancellation and execution belong to their existing queues.
This adapter only links their authoritative receipts to the original model task.
"""
from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from uuid import uuid5

from .. import jobqueue, market_data
from ..ai_lab import chief_agent
from . import domain_gateway, live_charts, live_gateway, model_chat
from .application_evidence import application_spec, _complete_task
from .live_backtests import LiveBacktestService
from .model_evaluation import digest, json_bytes
from .model_service import _LOCK
from .states import ContractError, EntityKind

_READ_LIMIT = 100
# This is only a bounded read cursor, not another queue or execution ledger.
# Restart loses the cursor, never task/receipt/idempotency information.
_READ_CURSORS = OrderedDict()


def _intent(message):
    backtest = bool(re.search(r"(?:запусти|запустить|выполни|проведи|run)\b.*(?:бэктест|backtest)", message, re.I))
    chart = bool(re.search(r"(?:сделай|создай|покажи)\b.*(?:снимок|скриншот).*рабоч", message, re.I))
    if backtest and chart:
        raise ContractError("application_one_action_required")
    if not backtest and not chart:
        return None
    return "backtest" if backtest else "chart"


def _chart_spec(message):
    instrument = re.search(r"\b([A-Z][A-Z0-9]{0,9})\s+(\d{2}-\d{2})\b", message)
    timeframe = re.search(r"\b([1-9]\d{0,3})\s*(?:m|мин(?:ут(?:ы)?)?)\b", message, re.I)
    if not instrument or not timeframe:
        raise ContractError("desktop_chart_explicit_instrument_timeframe_required")
    return application_spec("chart", {"instrument": instrument[1] + " " + instrument[2], "timeframe": timeframe[1] + "m"})


def _select_model(service, context, kind, *, persona_id=None):
    if persona_id is not None:
        from .persona_identity import select_model
        return select_model(service, context=context, persona_id=persona_id, kind=kind)
    from .application_roles import for_kind
    role = for_kind(kind)
    personas = [row for row in service._all(context, EntityKind.PERSONA)
                if row.status in {"active", "suspended"}
                and service._json(context, row.profile).get("application_role") == role]
    if not personas:
        return None
    if len(personas) != 1:
        raise ContractError("application_role_selection_ambiguous")
    if personas[0].status != "active":
        raise ContractError("application_persona_inactive")
    candidates = [item for item in service.models(context=context)["items"]
                  if item["status"] == "active" and item["persona_id"] == str(personas[0].header.entity_id)]
    if len(candidates) > 1:
        raise ContractError("application_model_selection_ambiguous")
    if not candidates:
        raise ContractError("application_role_model_required")
    return candidates[0]["id"]


def try_chat(message, *, scope, conversation_id, request_id, source, persona_id=None,
             persona_revision=None, user_message=None):
    if source != "app" or not live_gateway.configured(str((scope or {}).get("workspace_id") or "")):
        return None
    kind = _intent(message)
    if kind is None:
        return None
    authorized = domain_gateway.access(scope)
    service = domain_gateway.models(authorized)
    model_id = _select_model(service, authorized["context"], kind, persona_id=persona_id)
    if model_id is None:
        # No fabricated LLM participation. The existing explicit Local command
        # path remains available with its honest NinjaTrader/Desktop attribution.
        return None
    persona_ref = None
    if persona_id is not None:
        persona = service._get(authorized["context"], EntityKind.PERSONA, persona_id)
        if (type(persona_revision) is not int or persona.header.revision != persona_revision
                or persona.header.owner_user_uuid != authorized["context"].user_uuid
                or persona.status != "active"):
            raise ContractError("persona_revision_conflict")
        persona_ref = persona.ref()
    live_gateway.access(authorized["chat_scope"])
    spec = application_spec("backtest", live_gateway.parse_backtest(message)) if kind == "backtest" else _chart_spec(message)
    if kind == "backtest":
        LiveBacktestService()._registered(spec)  # existing catalog, read-only

    def execute(message_id):
        if persona_id is not None:
            # Selection is not a lasting permission. Recheck the owned Persona
            # and exact active binding immediately before the normal task path.
            authorized["admit"]()
            if _select_model(service, authorized["context"], kind, persona_id=persona_id) != model_id:
                raise ContractError("persona_model_binding_changed")
            if service._get(authorized["context"], EntityKind.PERSONA, persona_id).ref() != persona_ref:
                raise ContractError("persona_revision_conflict")
        detail = service.plan_application(context=authorized["context"], model_id=model_id, spec=spec, kind=kind,
            idempotency_key=request_id, conversation_id=conversation_id, message_id=message_id,
            **({"_persona": persona_ref} if persona_ref is not None else {}))
        envelope = model_chat.envelope(authorized, detail, request_id=request_id, pending=True)
        envelope["text"] = ("Модель персоны подготовит точную спецификацию поручения. После независимой проверки "
            "её выполнит существующий NinjaTrader/Рабочий стол. Результат и evidence вернутся в этот диалог.")
        return envelope

    return chief_agent.run_agent_world_live_request(message=user_message or message, request_id=request_id, conversation_id=conversation_id,
        scope=authorized["chat_scope"], execute=execute, domain_request=True, include_message_identity=True)


def _failure(service, authorized, task, checkpoint, code):
    safe = code if re.fullmatch(r"[a-z][a-z0-9_]{0,90}", str(code)) else "application_failed"
    checkpoint["application_error"] = safe
    task = service._change(authorized["context"], task, checkpoint=service._put(authorized["context"], checkpoint))
    if task.status == "waiting":
        service._change(authorized["context"], task, "failed")
    intent = service._get(authorized["context"], EntityKind.INTENT, task.intent.entity_id)
    if intent.status == "waiting":
        service._change(authorized["context"], intent, "failed")
    return service.task_detail(context=authorized["context"], task_id=task.header.entity_id)


def _publish_final(authorized, service, detail):
    # The monitor only queues the exact persisted terminal result. A separate
    # direct append here would race the claimed delivery worker across processes.
    from . import execution_v2
    execution_v2.observe(authorized, service, detail["id"])
    history = domain_gateway.access(authorized["chat_scope"], read_only=True)
    return domain_gateway.enqueue_model_delivery(history, domain_gateway.history_models(history), detail["id"])


def _cancelled(authorized, service, task_id):
    context = authorized["context"]
    with _LOCK:
        task = service._get(context, EntityKind.TASK, task_id)
        checkpoint = service._json(context, task.checkpoint)
        if task.status == "waiting":
            checkpoint["application_cancelled"] = True
            service._change(context, task, checkpoint=service._put(context, checkpoint))
        return service.cancel(context=context, task_id=task_id)


def _backtest_detail(live, checkpoint):
    dispatch = checkpoint["application_dispatch"]
    detail = LiveBacktestService().get(**live_gateway.service_args(live), job_id=dispatch["source_id"])
    if not detail:
        raise ContractError("application_source_not_found")
    task = detail["task"]
    if (task.get("conversation_id") != checkpoint["conversation_id"]
            or task.get("id") != dispatch["source_task_id"]):
        raise ContractError("application_source_scope_mismatch")
    return detail


def cancel_dispatch(authorized, service, *, task_id):
    """Cancel via the authoritative source; None means model-only cancellation.

    Running NinjaTrader is not preemptible. A request stays waiting until the
    source confirms cancellation; an already saved chart receipt is immutable.
    """
    authorized["admit"]()
    context = authorized["context"]
    service._access(context, "cancel")
    task = service._get(context, EntityKind.TASK, task_id)
    checkpoint = service._json(context, task.checkpoint)
    dispatch = checkpoint.get("application_dispatch")
    if not dispatch:
        return None
    if task.status in {"succeeded", "failed", "cancelled"}:
        return service.task_detail(context=context, task_id=task_id)
    live = live_gateway.access(authorized["chat_scope"])
    if live["context"] != context:
        raise ContractError("application_scope_mismatch")
    if dispatch["kind"] == "backtest":
        source = _backtest_detail(live, checkpoint)["task"]
        if source["source_status"] in {"done", "failed"}:
            raise ContractError("application_cancel_too_late")
        authorized["admit"]()
        try:
            receipt = jobqueue.cancel_job(dispatch["source_id"])
        except jobqueue.JobValidationError:
            raise ContractError("application_cancel_failed") from None
        if receipt.get("action") == "not_found":
            raise ContractError("application_source_not_found")
        if receipt.get("status") in {"done", "failed"}:
            raise ContractError("application_cancel_too_late")
    else:
        # The capture lock is not held with the model/Chief lock: capture
        # publishes to Chief, and ingress takes Chief before model mutation.
        with live_charts._CAPTURE_LOCK:
            command = next((row for row in live_charts.commands(live) if row["id"] == dispatch["source_id"]), None)
            if not command or command.get("conversation_id") != checkpoint["conversation_id"]:
                raise ContractError("application_source_not_found")
            if (command.get("result") or {}).get("agent_world_receipt") or command.get("status") == "done":
                raise ContractError("application_cancel_too_late")
            if command.get("status") in {"failed", "expired"} and (command.get("result") or {}).get("error") != "application_source_cancelled":
                raise ContractError("application_cancel_too_late")
            ack = live_charts.acknowledge({"id": dispatch["source_id"], "status": "failed",
                "result": {"error": "application_source_cancelled"}}, live)
            if ack.get("acked") is not True:
                raise ContractError("application_cancel_failed")
            receipt = {"status": "cancelled", "action": "cancelled_immediately"}
    with _LOCK:
        task = service._get(context, EntityKind.TASK, task_id)
        checkpoint = service._json(context, task.checkpoint)
        if task.status == "waiting":
            checkpoint["application_cancel_request"] = {"source_id": dispatch["source_id"],
                "source_status": receipt["status"], "action": receipt["action"]}
            service._change(context, task, checkpoint=service._put(context, checkpoint))
    if receipt["status"] == "cancelled":
        result = _cancelled(authorized, service, task_id)
        _publish_final(authorized, service, result)
        return result
    result = service.task_detail(context=context, task_id=task_id)
    envelope = model_chat.envelope(authorized, result, request_id="aw.cancel." + str(task_id), pending=True)
    envelope["text"] = "Отмена запрошена. Ожидаю подтверждения NinjaTrader; выполняющаяся операция пока не считается остановленной."
    chief_agent.report_agent_world_live_update(envelope)
    return result


def finish_dispatch(authorized, service, result):
    """Existing model worker calls this; stable existing source IDs survive retry."""
    task_dto = result.get("task") or result
    if not task_dto.get("model_plan_verified") or not task_dto.get("application_request"):
        return {"dispatched": False}
    context = authorized["context"]
    authorized["admit"]()
    from . import execution_v2
    execution_guard = execution_v2.before_application(authorized, service, task_dto["id"])
    live = live_gateway.access(authorized["chat_scope"])
    if live["context"] != context:
        raise ContractError("application_scope_mismatch")
    if callable(execution_guard):
        original_admit = live["admit"]
        def admit():
            original_admit()
            execution_guard()
        # Existing source adapters call this again immediately before enqueue.
        live = {**live, "admit": admit}
    failure = None
    with _LOCK:
        task = service._get(context, EntityKind.TASK, task_dto["id"])
        checkpoint = service._json(context, task.checkpoint)
        if task.status != "waiting":
            return {"dispatched": False, "status": task.status}
        checked = service.task_detail(context=context, task_id=task.header.entity_id)
        if not checked["model_plan_verified"]:
            raise ContractError("application_model_plan_unverified")
        request = checkpoint["application_request"]
        dispatch = checkpoint.get("application_dispatch")
        key = "aw.model." + task.header.entity_id.hex
        if not dispatch:
            try:
                if request["kind"] == "backtest":
                    source = LiveBacktestService().start(**live_gateway.service_args(live), spec=request["spec"],
                        idempotency_key=key, conversation_id=checkpoint["conversation_id"])
                    source_id = source["job_id"]
                    source_task_id = source["task_id"]
                else:
                    spec = request["spec"]
                    source = live_charts.start(message="Иван, сделай снимок рабочего стола " + spec["instrument"] + ", " + spec["timeframe"],
                        authorized=live, conversation_id=checkpoint["conversation_id"], request_id=key)
                    source_id, source_task_id = source["command_id"], source["task_id"]
                dispatch = {"kind": request["kind"], "source_id": source_id, "source_task_id": source_task_id,
                    "request_id": key, "request_sha256": request["request_sha256"]}
                checkpoint["application_dispatch"] = dispatch
                task = service._change(context, task, checkpoint=service._put(context, checkpoint))
            except ContractError as exc:
                failure = _failure(service, authorized, task, checkpoint, exc.code)
    if failure is not None:
        # Never acquire Chief's lock while holding the model mutation lock;
        # SF Chat ingress takes them in the opposite order.
        _publish_final(authorized, service, failure)
        return {"dispatched": False, "error_code": failure["error_code"]}
    # Persist source linkage before publishing; an uncertain append is retried.
    envelope = model_chat.envelope(authorized, service.task_detail(context=context, task_id=task.header.entity_id),
                                   request_id=key + ".queued", pending=True)
    envelope.update(source_task_id=dispatch["source_task_id"], source_kind="real_model_response",
        source_job_id=dispatch["source_id"] if dispatch["kind"] == "backtest" else None,
        command_id=dispatch["source_id"] if dispatch["kind"] == "chart" else None,
        text="Спецификация модели проверена. Реальное поручение передано " +
            ("NinjaTrader: " if dispatch["kind"] == "backtest" else "Рабочему столу: ") + dispatch["source_id"] +
            ". Ожидаю исходный отчёт/PNG; это ещё не готовый результат.")
    chief_agent.report_agent_world_live_update(envelope)
    return {"dispatched": True, **dispatch}


def _backtest_evidence(live, checkpoint):
    dispatch = checkpoint["application_dispatch"]
    detail = _backtest_detail(live, checkpoint)
    task, verification = detail["task"], detail["verification"]
    if task["source_status"] not in {"done", "failed", "cancelled"}:
        return None
    if task["source_status"] == "cancelled":
        raise ContractError("application_source_cancelled")
    if task["status"] != "succeeded" or verification.get("passed") is not True:
        raise ContractError("application_backtest_unverified")
    # This is deliberately a summary with full original checksums and exact
    # report link, not a truncated file pretending to be the canonical report.
    summary = {"schema_version": 1, "representation": "verified_existing_report_summary",
        "source_kind": "ninjatrader_report", "source_id": dispatch["source_id"], "synthetic": False,
        "model_task_id": checkpoint["task_id"], "request_sha256": checkpoint["application_request"]["request_sha256"],
        "source_checksums": verification.get("source_checksums"), "verification": verification,
        "result": detail["result"], "report_url": detail["report_url"], "summary": detail["result_text"]}
    content = json_bytes(summary)
    if len(content) > 256 * 1024:
        raise ContractError("application_summary_too_large")
    return content, "application/json", {"source_kind": "ninjatrader_report",
        "source_sha256": (verification.get("source_checksums") or {}).get("result.json"),
        "source_checksums": verification.get("source_checksums"), "report_url": detail["report_url"],
        "summary": detail["result_text"], "representation": "verified_existing_report_summary"}


def _chart_evidence(live, checkpoint):
    dispatch, spec = checkpoint["application_dispatch"], checkpoint["application_request"]["spec"]
    detail = next((row for row in live_charts.details(live, command_id=dispatch["source_id"])
                   if row["task"].get("command_id") == dispatch["source_id"]), None)
    if not detail:
        raise ContractError("application_source_not_found")
    task, verification = detail["task"], detail["verification"]
    if task.get("conversation_id") != checkpoint["conversation_id"] or task.get("id") != dispatch["source_task_id"]:
        raise ContractError("application_source_scope_mismatch")
    if task["status"] == "queued":
        return None
    command = next((row for row in live_charts.commands(live) if row["id"] == dispatch["source_id"]), {})
    if (command.get("result") or {}).get("error") == "application_source_cancelled":
        raise ContractError("application_source_cancelled")
    capture = verification.get("capture") or {}
    if (task["status"] != "succeeded" or verification.get("passed") is not True or verification.get("synthetic") is not False
            or capture.get("instrument") != spec["instrument"] or capture.get("timeframe") != spec["timeframe"]):
        raise ContractError("application_chart_unverified")
    saved = verification.get("snapshot") or {}
    path = market_data.snapshot_path(saved.get("file"))
    if not path or path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 256 * 1024:
        raise ContractError("application_snapshot_unavailable_or_too_large")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != verification.get("snapshot_sha256"):
        raise ContractError("application_source_hash_mismatch")
    # The same strict PNG validator is applied by repository.put_artifact.
    return content, "image/png", {"source_kind": "desktop_chart", "source_sha256": verification["snapshot_sha256"],
        "summary": detail["result_text"], "capture": capture, "provenance": "authenticated_desktop_canvas_receipt"}


def reconcile(authorized, service):
    """Called by the existing Chief monitor, never an unauthenticated GET."""
    authorized["admit"]()
    context = authorized["context"]
    live = live_gateway.access(authorized["chat_scope"])
    if live["context"] != context:
        raise ContractError("application_scope_mismatch")
    completed, errors, cancelled, candidates = [], [], [], []
    for task in service._all(context, EntityKind.TASK):
        if not task.checkpoint:
            continue
        checkpoint = service._json(context, task.checkpoint)
        if not checkpoint.get("application_request"):
            continue
        if task.status in {"succeeded", "failed", "cancelled"}:
            event_id = uuid5(task.header.entity_id, f"revision:{task.header.revision}")
            if service.repository.events.is_acknowledged(context=context, consumer=model_chat.DELIVERY_CONSUMER, event_id=event_id):
                continue
        elif task.status not in {"waiting", "ready", "running"}:
            continue
        candidates.append(task)
    candidates.sort(key=lambda row: (row.header.created_at, str(row.header.entity_id)))
    scope_key = (context.scope.environment.value, context.scope.workspace_id, str(context.user_uuid))
    with _LOCK:
        previous = _READ_CURSORS.get(scope_key)
        position = next((i + 1 for i, row in enumerate(candidates) if str(row.header.entity_id) == previous), 0)
        selected = (candidates[position:] + candidates[:position])[:_READ_LIMIT]
        if selected:
            _READ_CURSORS[scope_key] = str(selected[-1].header.entity_id)
            _READ_CURSORS.move_to_end(scope_key)
            while len(_READ_CURSORS) > 128:
                _READ_CURSORS.popitem(last=False)
    for task in selected:
        try:
            authorized["admit"]()
            task = service._get(context, EntityKind.TASK, task.header.entity_id)
            checkpoint = service._json(context, task.checkpoint)
            current = service.task_detail(context=context, task_id=task.header.entity_id)
            # Replay final append after an uncertain chat write; no provider or
            # source execution is repeated. The existing inbox ends this retry.
            if current.get("application_result"):
                with _LOCK:
                    _complete_task(service, context, task)
                _publish_final(authorized, service, service.task_detail(context=context, task_id=task.header.entity_id))
                continue
            if task.status in {"failed", "cancelled"}:
                _publish_final(authorized, service, current)
                continue
            if task.status != "waiting" or not current.get("model_plan_verified"):
                continue  # still the existing model worker's responsibility
            if not checkpoint.get("application_dispatch"):
                finish_dispatch(authorized, service, current)
                task = service._get(context, EntityKind.TASK, task.header.entity_id)
                checkpoint = service._json(context, task.checkpoint)
                if not checkpoint.get("application_dispatch"):
                    continue
            evidence = _backtest_evidence(live, checkpoint) if checkpoint["application_request"]["kind"] == "backtest" else _chart_evidence(live, checkpoint)
            if evidence is None:
                continue
            content, mime, observed = evidence
            ref = service.repository.put_artifact(context=context, content=content, media_type=mime)
            verification = {**observed, "verified": True, "synthetic": False,
                "source_id": checkpoint["application_dispatch"]["source_id"], "sha256": ref.sha256,
                "request_sha256": checkpoint["application_request"]["request_sha256"]}
            service.record_application_result(context=context, task_id=task.header.entity_id,
                source_id=verification["source_id"], verification=verification, artifact_refs=(ref,))
            result = service.task_detail(context=context, task_id=task.header.entity_id)
            _publish_final(authorized, service, result)
            completed.append(str(task.header.entity_id))
        except ContractError as exc:
            if exc.code == "application_source_cancelled":
                result = _cancelled(authorized, service, task.header.entity_id)
                _publish_final(authorized, service, result)
                cancelled.append(str(task.header.entity_id))
                continue
            errors.append({"task_id": str(task.header.entity_id), "code": exc.code})
            if exc.code in {"application_backtest_unverified", "application_chart_unverified"}:
                latest = service._get(context, EntityKind.TASK, task.header.entity_id)
                if latest.status == "waiting":
                    failed = _failure(service, authorized, latest, service._json(context, latest.checkpoint), exc.code)
                    _publish_final(authorized, service, failed)
    return {"completed": completed, "errors": errors, "cancelled": cancelled,
            "examined": len(selected), "read_limit": _READ_LIMIT, "remaining": max(0, len(candidates) - len(selected))}
