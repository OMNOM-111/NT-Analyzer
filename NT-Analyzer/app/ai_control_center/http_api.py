"""Narrow HTTP facade for the isolated owner-review checkpoint.

Handler has already enforced authentication, device, active access, origin/CSRF,
role and the existing ai_lab capability. This adds context/flags, not grants.
"""
from __future__ import annotations

import base64
import binascii
import struct
import zlib
from uuid import UUID

from .. import account_auth, permissions, preview_sandbox
from ..ai_lab import chief_agent
from . import gateway
from .states import ContractError


def _open(handler):
    return gateway.service_for(handler._remote_context or {},
                               control_authorized=handler._preview_control_authorized())


def _error(handler, exc):
    code = getattr(exc, "code", "") or str(exc)
    if code == "demo_run_limit_reached":
        handler._err(409, "Достигнут лимит 20 проверочных запусков. Сохраните нужные результаты; Reset Preview очистит только тестовые данные.", code=code)
        return
    status = 403 if any(word in code for word in ("required", "denied", "scope", "expired", "disabled", "context")) else 409
    handler._err(status, "AI Центр: действие недоступно или данные изменились.", code=code)


def handle_get(handler, path: str, qs: dict) -> None:
    try:
        with preview_sandbox.data_operation():
            _handle_get(handler, path, qs)
    except preview_sandbox.PreviewSandboxError as exc:
        _error(handler, exc)


def _handle_get(handler, path: str, qs: dict) -> None:
    try:
        route = path.removeprefix(gateway.PREFIX)
        if route.startswith("domains/"):
            from .preview_domains import DOMAINS
            parts = route.split("/")
            if len(parts) not in {2, 3} or parts[1] not in DOMAINS:
                handler._err(404, "Маршрут AI Центра не найден.", code="route_not_found")
                return
            if set(qs) - {"limit", "cursor"}:
                raise ContractError("invalid_domain_request")
            service = gateway.domain_service_for(handler)
            handler._json(200, service.list(parts[1], identity=parts[2] if len(parts) == 3 else None,
                limit=int((qs.get("limit") or ["50"])[0]), cursor=(qs.get("cursor") or [None])[0]))
            return
        if route.startswith("memory-artifacts/") and len(route.split("/")) == 3:
            parts = route.split("/")
            item = gateway.domain_service_for(handler).memory_artifact(parts[1], parts[2])
            if item is None:
                handler._err(404, "Публикация памяти недоступна или отозвана.", code="memory_artifact_not_found")
            else:
                reference, content, media_type = item
                handler._bytes(200, content, media_type, headers={
                    "Content-Security-Policy": "default-src 'none'; sandbox", "ETag": '"' + reference.sha256 + '"',
                    "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
            return
        context, snapshot, service = _open(handler)
        if route == "overview":
            handler._json(200, gateway.enrich(service.overview(context=context), context, snapshot))
        elif route == "tasks":
            handler._json(200, {"items": service.work(context=context), "next_cursor": None,
                                "bounded_preview": True})
        elif route.startswith("tasks/") and len(route.split("/")) == 2:
            item = service.task_detail(context=context, entity_id=UUID(route.split("/")[1]))
            if item is None:
                handler._err(404, "Задача не найдена.", code="task_not_found")
            else:
                handler._json(200, item)
        elif route.startswith("artifacts/") and len(route.split("/")) == 2:
            item = service.repository.get_artifact_by_id(context=context, artifact_id=UUID(route.split("/")[1]))
            from .memory_policy import artifact_allowed
            item = artifact_allowed(gateway.domain_service_for(handler).service, context, item)
            if item is None:
                handler._err(404, "Артефакт не найден.", code="artifact_not_found")
            else:
                reference, content, media_type = item
                handler._bytes(200, content, media_type, headers={
                    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
                    "ETag": '"' + reference.sha256 + '"',
                })
        elif route in {"decisions", "memory", "experiments", "models", "system"}:
            notes = {
                "decisions": "Проверки результатов доступны в задачах. Consensus/Court пока выключены: судебных вердиктов здесь нет.",
                "memory": "Ручная синтетическая память доступна в разделе Память; активация требует отдельной проверки. Автоматическое извлечение из чатов выключено.",
                "experiments": "Существующие исследования сохранены в совместимом AI Lab. Запуск NinjaTrader в проверочном контуре заблокирован.",
                "models": "Персона, роль и модель разделены. В этом контуре выполняются локальные проверочные алгоритмы; внешние модели не вызываются.",
                "system": "Действуют существующие permissions, auth и budget checks. Новый job engine не создаётся. Расчёты короткие и синхронные.",
            }
            handler._json(200, {"items": [], "status": "IN DEVELOPMENT", "message": notes[route],
                                "limitations": [notes[route]], "enabled": False,
                                "flags": gateway.enrich({}, context, snapshot)["flags"] if route == "system" else {}})
        else:
            handler._err(404, "Маршрут AI Центра не найден.", code="route_not_found")
    except (ContractError, preview_sandbox.PreviewSandboxError, account_auth.AccountAuthError,
            permissions.PermissionError) as exc:
        _error(handler, exc)
    except (ValueError, TypeError):
        handler._err(400, "Некорректный идентификатор.", code="invalid_request")


def decode_chart_png(value: object) -> bytes:
    """Validate the small, explicit browser-produced chart screenshot."""
    if not isinstance(value, str) or not value.startswith("data:image/png;base64,") or len(value) > 350_000:
        raise ContractError("invalid_chart_screenshot")
    try:
        content = base64.b64decode(value.split(",", 1)[1], validate=True)
    except (ValueError, binascii.Error):
        raise ContractError("invalid_chart_screenshot") from None
    if len(content) > 256 * 1024 or len(content) < 45 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ContractError("invalid_chart_screenshot")
    # Verify the full PNG container/CRCs, bounded dimensions and no trailing
    # payload before persisting untrusted browser bytes as an inert image.
    pos, dimensions, ended, channels = 8, None, False, 0
    compressed = bytearray()
    while pos + 12 <= len(content):
        length = struct.unpack(">I", content[pos:pos + 4])[0]
        kind = content[pos + 4:pos + 8]
        stop = pos + 12 + length
        if stop > len(content):
            raise ContractError("invalid_chart_screenshot")
        data = content[pos + 8:pos + 8 + length]
        expected = struct.unpack(">I", content[pos + 8 + length:stop])[0]
        if binascii.crc32(kind + data) & 0xffffffff != expected:
            raise ContractError("invalid_chart_screenshot")
        if pos == 8:
            if kind != b"IHDR" or length != 13:
                raise ContractError("invalid_chart_screenshot")
            dimensions = struct.unpack(">II", data[:8])
            if not all(1 <= n <= 2048 for n in dimensions):
                raise ContractError("invalid_chart_screenshot")
            if data[8] != 8 or data[9] not in {2, 6} or data[10:] != b"\x00\x00\x00":
                raise ContractError("invalid_chart_screenshot")
            channels = 4 if data[9] == 6 else 3
        elif kind == b"IHDR":
            raise ContractError("invalid_chart_screenshot")
        if kind == b"IDAT":
            compressed.extend(data)
        if kind == b"IEND":
            ended = length == 0 and stop == len(content)
            break
        pos = stop
    if not ended or dimensions is None:
        raise ContractError("invalid_chart_screenshot")
    expected_size = (dimensions[0] * channels + 1) * dimensions[1]
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), expected_size + 1)
    except zlib.error:
        raise ContractError("invalid_chart_screenshot") from None
    if (len(pixels) != expected_size or not decoder.eof or decoder.unused_data
            or decoder.unconsumed_tail or any(pixels[i] > 4 for i in range(0, expected_size, dimensions[0] * channels + 1))):
        raise ContractError("invalid_chart_screenshot")
    return content


def handle_post(handler, path: str) -> None:
    try:
        with preview_sandbox.data_operation():
            _handle_post(handler, path)
    except preview_sandbox.PreviewSandboxError as exc:
        _error(handler, exc)


def _handle_post(handler, path: str) -> None:
    if not handler._check_local_post():
        return
    body = handler._read_body()
    if body is None:
        return
    if not isinstance(body, dict):
        handler._err(400, "Требуется JSON object.", code="invalid_request")
        return
    try:
        if path.removeprefix(gateway.PREFIX).startswith("domains/"):
            parts = path.removeprefix(gateway.PREFIX).split("/")
            if len(parts) != 4:
                raise ContractError("invalid_domain_request")
            service = gateway.domain_service_for(handler)
            if parts[1] == "personas" and parts[3] == "speak":
                from ..ai_lab import agent_tts
                try:
                    handler._json(200, service.speak(parts[2], body))
                except agent_tts.AgentTtsError:
                    handler._err(409, "Голос устройства недоступен; текст и аватар сохранены.", code="persona_voice_unavailable")
            else:
                handler._json(200, service.mutate(parts[1], parts[2], parts[3], body))
            return
        context, snapshot, service = _open(handler)
        permit = gateway.admission(handler, context, snapshot)
        route = path.removeprefix(gateway.PREFIX)
        if route == "demo-runs":
            if set(body) - {"idempotency_key"}:
                raise ContractError("invalid_demo_fields")
            result = service.run(context=context, admission=permit,
                                 idempotency_key=body.get("idempotency_key", ""))
            handler._json(200, {**result, "overview": gateway.enrich(result.get("overview") or {}, context, snapshot)})
        elif route.startswith("tasks/") and len(route.split("/")) == 3 and route.endswith("/chat"):
            if set(body) - {"image_data_url"}:
                raise ContractError("invalid_chat_fields")
            task_id = UUID(route.split("/")[1])
            task = service.task_detail(context=context, entity_id=task_id)
            if task is None:
                handler._err(404, "Задача не найдена.", code="task_not_found")
                return
            meta = task.get("task") or {}
            evaluations = task.get("evaluations") or []
            if meta.get("status") != "succeeded" or not evaluations or not all(row.get("passed") is True for row in evaluations):
                raise ContractError("task_verified_result_required")
            lead = meta.get("lead") or {}
            attachments, suffix = [], "result"
            if body.get("image_data_url"):
                if not any((row.get("media_type") or row.get("mime_type")) == "image/svg+xml" for row in task.get("artifacts", [])):
                    raise ContractError("task_chart_required")
                content = decode_chart_png(body["image_data_url"])
                reference = service.repository.put_artifact(context=context, content=content, media_type="image/png")
                suffix = reference.sha256[:24]
                attachments = [{"type": "image", "url": gateway.PREFIX + "artifacts/" + str(reference.artifact_id),
                                "caption": "Снимок synthetic-графика, сделанный браузером; не биржевые данные."}]
            text = ("Проверка Agent World · SYNTHETIC\n" + str(meta.get("title") or "Задача")
                    + "\n" + str(task.get("result_text") or task.get("result") or task.get("summary") or "Результат и проверки сохранены в AI Центре.")[:5000]
                    + "\nИсполнитель: локальный детерминированный алгоритм. Внешняя LLM не вызывалась."
                    + "\nЗадача: /ui/ai-command-center.html?task=" + str(task_id))
            permit.revalidate()
            result = chief_agent.report_local_preview_result(
                conversation_id="AW-" + task_id.hex, title="Agent World · " + str(meta.get("title") or "проверка"),
                text=text, request_id="aw." + task_id.hex + "." + suffix,
                agent_id=str(lead.get("key") or "vitek"),
                agent_name=str(lead.get("display_name") or "Витёк"),
                attachments=attachments, scope=handler._ai_conversation_scope(),
            )
            handler._json(200, result)
        else:
            handler._err(404, "Маршрут AI Центра не найден.", code="route_not_found")
    except (ContractError, preview_sandbox.PreviewSandboxError, account_auth.AccountAuthError,
            permissions.PermissionError) as exc:
        _error(handler, exc)
    except (ValueError, TypeError):
        handler._err(400, "Некорректный запрос.", code="invalid_request")
