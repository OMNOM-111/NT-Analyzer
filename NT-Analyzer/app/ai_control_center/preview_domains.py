"""Manual synthetic domains over the existing ledger, only in isolated Preview.

No fixture is created by a read. No model, judge, follow-up queue, scheduler,
credential resolver or publisher is supplied. Unsupported actions fail closed;
ordinary synthetic users retain ordinary ownership and are never operators.
"""
from __future__ import annotations

import json
from uuid import UUID

from .. import preview_sandbox
from .repositories import PageRequest
from .states import ContractError


DATASET_ID = "agent-world-domains-v1"
SUPPORTED = frozenset({"personas", "memory", "projects", "routines", "calendar"})
DOMAINS = SUPPORTED | frozenset({"models", "model_tasks", "tasks", "decisions", "court",
    "experiments", "system", "publications", "automation", "router"})
_ACTIONS = {
    "personas": {"update", "activate", "suspend", "archive"},
    "memory": {"update", "promote", "revoke", "expire", "publish_to_workspace"},
    "projects": {"update", "version", "archive"},
    "routines": {"dismiss"}, "calendar": {"dismiss"},
}
_SOURCE = {"synthetic": True, "source_kind": "preview_manual_domain",
    "source_label": "Синтетические данные · изолированный Preview",
    "model_quality_evidence": False, "external_side_effects": "blocked"}
_LIMITATIONS = [
    "Это синтетические данные отдельного Preview; реальные owner-данные и подключения не используются.",
    "Изменения сохраняются тем же DomainService с проверкой владельца, версии и идемпотентности.",
    "Ручная проверка памяти не является оценкой модели. История и ошибки не очищаются при повторе действия.",
]
_FOLLOWUP_NOTE = ("Предложение можно создать или отклонить. Принятие и фоновое выполнение недоступны в Preview: "
                  "адаптер очереди не подключён; скрытые jobs и расписания не создаются.")


class PreviewDomains:
    def __init__(self, *, context, service, fresh, flags):
        self.context, self.service, self._fresh, self._flags = context, service, fresh, flags

    def _admit(self, *, write=False, operator=False):
        preview_sandbox.require_enabled()
        if self.service.enqueue is not None or self.service.judge_runner is not None:
            raise ContractError("agent_world_preview_executor_denied")
        return self._fresh(write=write, operator=operator)

    def _item(self, item):
        result = {**item, **_SOURCE}
        if "presentation" in result:
            view = result["presentation"]
            result["presentation"] = {**view, "capabilities": {
                **view.get("capabilities", {}), "server_speech": "disabled_in_preview"}}
        return result

    def _base(self):
        return {**_SOURCE, "status": "IN DEVELOPMENT", "flags": self._flags(),
            "scope": {"environment": self.context.scope.environment.value,
                "workspace_id": self.context.scope.workspace_id, "synthetic": True}}

    def list(self, domain, *, identity=None, limit=50, cursor=None):
        raw = self._admit()
        PageRequest(limit=limit, cursor=cursor)
        if domain not in DOMAINS:
            raise ContractError("unknown_domain")
        if domain in SUPPORTED:
            if identity is not None:
                return {**self._base(), **self._item(self.service.get(context=self.context,
                    admit=self._admit, domain=domain, entity_id=identity))}
            data = self.service.list(context=self.context, admit=self._admit,
                                      domain=domain, limit=limit, cursor=cursor)
            result = {**data, **self._base(), "items": [self._item(item) for item in data["items"]],
                "limitations": list(_LIMITATIONS)}
            if domain == "personas":
                from .persona_voice import catalog
                result["presentation_catalog"] = {**catalog(), "modes": ["browser"],
                    "existing_tts_note": "Внешний TTS в Preview заблокирован; доступен голос устройства, если поддерживается браузером."}
            if domain in {"routines", "calendar"}:
                result["limitations"].append(_FOLLOWUP_NOTE)
                result["process_intelligence"] = {"enabled": False, "candidates": [], "suppressed": [],
                    "excluded": [], "synthetic": True, "reason": "synthetic_outcomes_not_quality_evidence",
                    "message": "Synthetic-результаты не используются для поиска подтверждённых рабочих привычек.",
                    "automation_enabled": False, "auto_accept": False}
            return result
        if identity is not None:
            raise ContractError("domain_record_not_found")
        if domain == "system":
            can_seed = preview_sandbox.synthetic_operator_access_allowed(raw)
            dataset = {"id": DATASET_ID, "synthetic": True, "operator_required": True,
                "title": "Учебный набор Agent World", "domain_counts": {
                    "personas": 2, "memory": 1, "projects": 1, "routines": 1, "calendar": 1},
                "automatic_creation": False, "automatic_review": False,
                "actions": ["seed_preview"] if can_seed else [],
                "message": "Создаёт только черновики и предложения в профиле отдельного синтетического оператора."}
            return {**self._base(), "enabled": True, "next_cursor": None,
                "items": [self._item({"id": DATASET_ID, "title": dataset["title"], "status": "manual_only",
                    "summary": dataset["message"], "revision": 0, "actions": dataset["actions"]})],
                "preview_dataset": dataset, "capabilities": {"can_seed_preview_dataset": can_seed,
                    "can_create": False, "can_review": False, "can_accept_suggestion": False,
                    "execution_allowed": False, "automation_enabled": False},
                "mechanisms": {"storage": "isolated_sqlite", "manual_domains": "available",
                    "router": "disabled", "court": "disabled", "execution_v2": "disabled",
                    "worker": "not_started", "scheduler": "disabled", "external_models": "blocked",
                    "external_tts": "blocked", "social_publisher": "blocked", "postgres_rls": "not_used_in_preview"},
                "limitations": [*_LIMITATIONS, _FOLLOWUP_NOTE,
                    "Результаты отдельного PostgreSQL/RLS-тестирования не подменяются SQLite Preview."]}
        note = ("Этот механизм не выполняется в Preview. Реальные подключения, модели, Court, Router, "
                "NinjaTrader и публикации не включаются синтетическим просмотром. Проверочные задачи доступны в Обзоре и Работе.")
        return {**self._base(), "enabled": False, "status": "EXTERNAL BLOCKED", "items": [],
            "actions": [], "next_cursor": None, "source_candidates": [], "message": note,
            "capabilities": {"can_create": False, "can_connect": False, "can_review": False,
                "can_accept_suggestion": False, "execution_allowed": False, "automation_enabled": False},
            "limitations": [note]}

    def _envelope(self, body):
        if (type(body) is not dict or set(body) - {"payload", "expected_revision", "idempotency_key"}
                or type(body.get("payload", {})) is not dict):
            raise ContractError("invalid_domain_request")
        key = body.get("idempotency_key")
        if type(key) is not str or not 8 <= len(key) <= 120 or any(not 33 <= ord(ch) <= 126 for ch in key):
            raise ContractError("invalid_idempotency_key")
        return body.get("payload", {}), key

    def mutate(self, domain, identity, action, body):
        self._admit(write=True)
        payload, key = self._envelope(body)
        if domain == "system" and identity == DATASET_ID and action == "seed_preview":
            if payload or type(body.get("expected_revision")) is not int or body["expected_revision"] != 0:
                raise ContractError("invalid_domain_request")
            return self._seed()
        if domain not in SUPPORTED:
            raise ContractError("agent_world_preview_domain_disabled")
        admit = lambda: self._admit(write=True)
        if identity == "new" and action == "create":
            revision = body.get("expected_revision")
            if revision is not None and (type(revision) is not int or revision != 0):
                raise ContractError("invalid_domain_request")
            result = self.service.create(context=self.context, admit=admit, domain=domain,
                payload=payload, idempotency_key=key)
        else:
            if domain in {"routines", "calendar"} and action == "accept":
                raise ContractError("agent_world_preview_followup_disabled")
            if action not in _ACTIONS[domain]:
                raise ContractError("agent_world_preview_action_disabled")
            result = self.service.act(context=self.context, admit=admit, domain=domain,
                entity_id=identity, action=action, payload=payload,
                expected_revision=body.get("expected_revision"), idempotency_key=key)
        return {**result, **_SOURCE, "item": self._item(result["item"])}

    def speak(self, identity, body):
        self._admit(write=True)
        payload, _ = self._envelope(body)
        if (set(payload) != {"text"} or type(payload["text"]) is not str or len(payload["text"]) > 1200
                or type(body.get("expected_revision")) is not int or body["expected_revision"] < 1):
            raise ContractError("invalid_domain_request")
        from .persona_voice import speak
        result = speak(self.service, context=self.context, admit=lambda: self._admit(write=True),
            persona_id=identity, text=payload["text"], expected_revision=body["expected_revision"],
            scope={"environment": "development", "workspace_id": self.context.scope.workspace_id,
                "user_uuid": str(self.context.user_uuid), "is_owner": False, "uses_owner_runtime": False,
                "synthetic": True})
        if result.get("fallback") != "browser" or result.get("audio"):
            raise ContractError("agent_world_preview_external_audio_denied")
        view = result.get("persona_presentation") or {}
        return {**result, **_SOURCE, "persona_presentation": {**view,
            "capabilities": {**view.get("capabilities", {}), "server_speech": "disabled_in_preview"}}}

    def memory_artifact(self, memory_id, artifact_id):
        self._admit()
        found = self.service.repository.read_memory_artifact(context=self.context,
            memory_id=UUID(memory_id), artifact_id=UUID(artifact_id))
        self._admit()
        return found

    def _seed(self):
        """Explicit bounded fixture, deterministic per-user keys; never rewrite.

        A retry after partial failure resumes the same six create operations.
        Existing edits survive, and returned rows use their current revisions.
        Dates deliberately belong to a labelled historical example, not a live
        scheduled event. No reviews, activations or accepted jobs are fabricated.
        """
        admit = lambda: self._admit(write=True, operator=True)
        admit()
        recipe = {"dataset_id": DATASET_ID, "source_kind": "preview_fixture", "synthetic": True,
            "origin": "explicit_preview_operator_seed", "model_quality_evidence": False,
            "automatic_review": False, "automation_enabled": False, "external_side_effects": "blocked"}
        reference = self.service.repository.put_artifact(context=self.context,
            content=json.dumps(recipe, ensure_ascii=False, sort_keys=True).encode("utf-8"), media_type="application/json")
        sources = [str(reference.artifact_id)]
        fixtures = [
            ("personas", "researcher", {"name": "Иван · учебный Preview", "avatar_key": "ivan",
                "description": "SYNTHETIC: пример личной персоны для просмотра графиков. Модель и исполнение не подключены.",
                "style": "Кратко объясняет шаги и просит отдельное подтверждение результата.",
                "application_role": "chart_researcher", "voice_profile_id": "ivan", "voice_mode": "browser"}),
            ("personas", "analyst", {"name": "Марина · учебный Preview", "avatar_key": "marina",
                "description": "SYNTHETIC: независимая учебная персона; это не подключённая внешняя модель.",
                "style": "Показывает происхождение данных и ограничения выборки.", "voice_mode": "browser"}),
            ("memory", "note", {"title": "Учебная заметка · проверить источник", "content": "SYNTHETIC: перед выводом сравнить источник, период и ожидающий review. Это не реальный рабочий результат.",
                "purpose": "Preview: происхождение результата", "retention_days": 7, "source_ids": sources}),
            ("projects", "project", {"title": "Учебный проект · анализ графика", "strategy_key": "preview_chart_review",
                "description": "SYNTHETIC: черновик проекта. Стратегия не исполнялась; реальные рыночные результаты не заявлены."}),
            ("routines", "routine", {"title": "Учебное предложение · обзор результатов", "interval_minutes": 1440,
                "description": "SYNTHETIC: пример предложения. Оно не принято; фонового запуска нет.", "source_ids": sources}),
            ("calendar", "calendar", {"title": "Учебный календарь · исторический пример", "starts_at": "2026-01-15T09:00:00Z",
                "ends_at": "2026-01-15T09:30:00Z", "description": "SYNTHETIC: фиксированный исторический пример для проверки полей. Не действующее событие или расписание.", "source_ids": sources}),
        ]
        results, created = [], 0
        for domain, name, payload in fixtures:
            admit()
            result = self.service.create(context=self.context, admit=admit, domain=domain,
                payload=payload, idempotency_key=DATASET_ID + "." + name)
            created += int(not result["replayed"])
            current = self.service.get(context=self.context, admit=admit,
                domain=domain, entity_id=result["item"]["id"])
            results.append({"domain": domain, **self._item(current)})
        admit()
        return {"ok": True, **_SOURCE, "dataset_id": DATASET_ID, "items": results,
            "created_count": created, "replayed_count": len(results) - created,
            "replayed": created == 0, "automatic_review": False, "automation_enabled": False,
            "manifest_artifact_url": "/api/ai-control-center/artifacts/" + str(reference.artifact_id)}
