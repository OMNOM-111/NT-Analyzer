"""Durable, bounded owner rehearsal. Existing server authority admits every step.

No background scheduler, job queue, budget account, permission grant, LLM call or
execution engine is created here. A synchronous rehearsal performs four offline
computations and commits their real evidence through the domain repositories.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid5

from . import contracts as c
from .demo_benchmark import BENCHMARK_VERSION, EXECUTOR, PERSONAS, digest, execute, fixture, json_bytes
from .demo_evaluation import evaluate
from .events import EventData, EventEnvelope, MutationIdentity
from .repositories import PageRequest
from .states import ContractError, EntityKind, INITIAL_STATES


_NAMESPACE = UUID("9cf71c69-cfb2-53f4-a352-12c82f9f732b")
_PERSONAS = {row["key"]: row for row in PERSONAS}
_POLICY = {"schema_version": 1, "version": BENCHMARK_VERSION,
           "source": "synthetic", "executor": EXECUTOR, "risk": "low", "autonomy": "draft",
           "external_calls": False, "paid_calls": False, "orders": False,
           "rating_scope": "fixed_synthetic_benchmark", "routing_effect": "none",
           "authorization": "Existing server checks required before admission and every checkpoint"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(context: c.RequestContext, value: str) -> UUID:
    return uuid5(_NAMESPACE, f"{context.scope.environment.value}:{context.scope.workspace_id}:"
                 f"{context.user_uuid}:{value}")


def _service_context(context: c.RequestContext, service_key: str) -> c.RequestContext:
    return c.RequestContext(scope=context.scope, user_uuid=context.user_uuid,
                            actor=c.ActorRef(kind=c.ActorKind.SERVICE,
                                actor_id=_id(context, f"local-service:{service_key}"),
                                on_behalf_of=context.user_uuid))


def _wire(reference: c.SnapshotRef) -> dict:
    return {"artifact_id": str(reference.artifact_id), "sha256": reference.sha256}


def _snapshot(context: c.RequestContext, value: dict) -> c.SnapshotRef:
    try:
        return c.SnapshotRef(artifact_id=UUID(value["artifact_id"]), sha256=value["sha256"],
                             scope=context.scope)
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("invalid_demo_evidence") from exc


@dataclass(frozen=True, kw_only=True)
class DemoAdmission:
    """Shape of a server admission, not a credential or alternative authorization.

The facade builds this only after authenticating the Preview control owner and
checking the synthetic user, device, trial, existing ai_lab capability, budget
and exact feature scope. ``revalidate`` repeats those checks, not a no-op in the
production facade. The budget reference names that existing authority; it does
not assert that a paid reservation exists.
"""

    scope: c.TenantScope
    user_uuid: UUID
    budget: c.ExternalRef
    expires_at: datetime
    synthetic: bool
    enabled: bool
    revalidate: Callable[[], None]

    def validate(self, context: c.RequestContext) -> None:
        if not isinstance(context, c.RequestContext):
            raise ContractError("context_required")
        c.require_same_scope(context.scope, self.scope)
        c.require_uuid(self.user_uuid)
        c.require_external(self.budget, c.ExternalAuthority.BUDGET)
        c.require_same_scope(context.scope, self.budget.scope)
        c.require_utc(self.expires_at)
        if context.user_uuid != self.user_uuid:
            raise ContractError("demo_owner_mismatch")
        if context.scope.environment != c.Environment.DEVELOPMENT:
            raise ContractError("demo_development_only")
        if self.synthetic is not True or self.enabled is not True:
            raise ContractError("demo_not_enabled")
        if self.expires_at <= _now():
            raise ContractError("demo_admission_expired")
        if not callable(self.revalidate):
            raise ContractError("demo_revalidation_required")
        self.revalidate()


class DemoWorkflowService:
    def __init__(self, repository, *, artifact_url_prefix: str = "/api/ai-control-center/artifacts/"):
        if artifact_url_prefix != "/api/ai-control-center/artifacts/":
            raise ContractError("invalid_artifact_url_prefix")
        self.repository = repository
        self.artifact_url_prefix = artifact_url_prefix

    def _put(self, context, admission, value, *, media_type="application/json"):
        admission.validate(context)
        content = value if isinstance(value, bytes) else json_bytes(value)
        return self.repository.put_artifact(context=context, content=content, media_type=media_type)

    def _json(self, context, reference):
        import json
        found = self.repository.get_artifact(context=context, reference=reference)
        if not found or found[1] != "application/json":
            raise ContractError("demo_evidence_unavailable")
        try:
            result = json.loads(found[0])
        except (ValueError, UnicodeError) as exc:
            raise ContractError("invalid_demo_evidence") from exc
        if not isinstance(result, dict):
            raise ContractError("invalid_demo_evidence")
        return result

    def _commit(self, context, admission, record, expected_revision):
        admission.validate(context)
        event_type = f"stratforge.ai.{record.KIND.value}.changed"
        event_type = {
            (EntityKind.TASK, "running"): "stratforge.ai.task.started",
            (EntityKind.TASK, "succeeded"): "stratforge.ai.task.completed",
            (EntityKind.TASK, "failed"): "stratforge.ai.task.failed",
            (EntityKind.OUTCOME, "verified"): "stratforge.ai.outcome.verified",
        }.get((record.KIND, record.status), event_type)
        event = EventEnvelope(event_id=uuid5(record.header.entity_id, f"revision:{record.header.revision}"),
                              event_type=event_type, time=record.header.updated_at, subject=record.ref(),
                              actor=context.actor, correlation_id=record.header.correlation_id,
                              policy=record.header.policy, causation_id=record.header.causation_id,
                              data=EventData(reason_code="owner_synthetic_rehearsal"))
        mutation = MutationIdentity.for_record(
            context=context, operation="agent_world.demo.write",
            idempotency_key=f"demo.{record.header.entity_id}.{record.header.revision}",
            record=record, expected_revision=expected_revision, event=event)
        try:
            return self.repository.commit(context=context, record=record,
                                          expected_revision=expected_revision, event=event, mutation=mutation).record
        except ContractError as exc:
            if exc.code not in {"revision_conflict", "idempotency_conflict", "creation_conflict"}:
                raise
            # Another admitted request may have committed this deterministic
            # step first. Its stored event/time remains authoritative.
            latest = self.repository.get(context=context, kind=record.KIND,
                                         entity_id=record.header.entity_id)
            if latest is None or latest.header.revision < record.header.revision:
                raise
            if latest.header.revision == record.header.revision and any(
                    getattr(latest, field.name) != getattr(record, field.name)
                    for field in fields(record) if field.name != "header"):
                raise
            return latest

    def _ensure(self, context, admission, record_type, entity_id, correlation_id, policy,
                *, coalesce_create=False, **payload):
        previous = self.repository.get(context=context, kind=record_type.KIND, entity_id=entity_id)
        if previous is not None:
            if not isinstance(previous, record_type) or previous.header.owner_user_uuid != context.user_uuid:
                raise ContractError("demo_record_conflict")
            return previous
        now = _now()
        header = c.RecordHeader(entity_id=entity_id, scope=context.scope, owner_user_uuid=context.user_uuid,
                                revision=1, created_at=now, updated_at=now, created_by=context.actor,
                                correlation_id=correlation_id, policy=policy)
        if record_type is c.Intent:
            payload["deadline"] = now + timedelta(minutes=5)
        item = record_type(header=header, status=INITIAL_STATES[record_type.KIND], **payload)
        try:
            return self._commit(context, admission, item, 0)
        except ContractError as exc:
            if coalesce_create and record_type is c.Intent and exc.code in {
                    "idempotency_conflict", "revision_conflict", "creation_conflict"}:
                stored = self.repository.get(context=context, kind=record_type.KIND, entity_id=entity_id)
                if stored is not None and stored.header.owner_user_uuid == context.user_uuid:
                    return stored
            raise

    def _advance(self, context, admission, record, status, **payload):
        header = replace(record.header, revision=record.header.revision + 1, updated_at=max(_now(), record.header.updated_at),
                         causation_id=uuid5(record.header.entity_id, f"revision:{record.header.revision}"))
        return self._commit(context, admission, replace(record, header=header, status=status, **payload),
                            record.header.revision)

    def _walk(self, context, admission, record, path, *, already_advanced=()):
        for _ in range(len(path) + 1):
            if record.status == path[-1] or record.status in already_advanced:
                return record
            if record.status not in path:
                raise ContractError("demo_unexpected_state")
            record = self._advance(context, admission, record, path[path.index(record.status) + 1])
        raise ContractError("demo_concurrent_progress")

    def _catalog(self, context, admission, policy):
        roles = {}
        for persona in PERSONAS:
            key = persona["key"]
            profile = self._put(context, admission, {"schema_version": 1, "source": "synthetic",
                                "persona_key": key, "display_name": persona["display_name"],
                                "role_key": persona["role_key"], "avatar_key": key,
                                "note": "Existing persona presentation; deterministic rehearsal, not an LLM identity"})
            common = (context, admission)
            record = self._ensure(*common, c.Persona, _id(context, f"persona:{key}"),
                                  _id(context, "catalog"), policy,
                                  display_name=persona["display_name"], profile=profile)
            self._walk(*common, record, ("draft", "active"))
            responsibilities = self._put(context, admission, {
                "schema_version": 1, "source": "synthetic", "role_key": persona["role_key"],
                "responsibility": persona["title"], "tools": ["offline_fixture_computation"],
                "external_execution": False})
            record = self._ensure(*common, c.AgentRole, _id(context, f"role:{key}"),
                                  _id(context, "catalog"), policy, role_key=persona["role_key"],
                                  responsibilities=responsibilities, capability_ceiling=("ai_lab",),
                                  autonomy_ceiling=c.Autonomy.DRAFT)
            roles[key] = self._walk(*common, record, ("draft", "active"))
        return roles

    def run(self, *, context: c.RequestContext, admission: DemoAdmission,
            idempotency_key: str, round_index: int | None = None) -> dict:
        admission.validate(context)
        if (not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160
                or any(ord(char) < 33 or ord(char) > 126 for char in idempotency_key)):
            raise ContractError("invalid_idempotency_key")
        if round_index is not None and (type(round_index) is not int or not 0 <= round_index < 3):
            raise ContractError("invalid_demo_round")
        requested_round = round_index
        key_hash = digest(idempotency_key.encode("ascii"))
        run_id = _id(context, f"run:{key_hash}")
        existing = self.repository.get(context=context, kind=EntityKind.INTENT, entity_id=run_id)
        if existing is not None:
            goal_data = self._json(context, existing.goal)
            if round_index is not None and goal_data["round_index"] != round_index:
                raise ContractError("idempotency_conflict")
            round_index = goal_data["round_index"]
            if existing.status in {"completed", "failed", "cancelled"}:
                return self._run_result(context, run_id, replayed=True)
            if existing.deadline <= _now():
                raise ContractError("demo_deadline_expired")
        elif round_index is None:
            page = self.repository.list(context=context, kind=EntityKind.INTENT, page=PageRequest(limit=100))
            round_index = len([item for item in page.items if item.header.owner_user_uuid == context.user_uuid]) % 3
        source = fixture(round_index)
        policy = self._put(context, admission, _POLICY)
        roles = self._catalog(context, admission, policy)
        inputs = self._put(context, admission, source)
        goal = self._put(context, admission, {"schema_version": 1, "source": "synthetic",
            "title": "Owner rehearsal: four local evidence-backed tasks", "run_id": str(run_id),
            "round_index": round_index, "idempotency_hash": key_hash, "input": _wire(inputs)})
        acceptance = self._put(context, admission, {"schema_version": 1, "benchmark": BENCHMARK_VERSION,
            "required": ["independent_recomputation", "input_integrity", "output_contract", "synthetic_provenance"],
            "external_effects": "forbidden", "model_quality_assessed": False})
        intent = self._ensure(context, admission, c.Intent, run_id, run_id, policy, goal=goal,
                              acceptance=acceptance, risk=c.Risk.LOW, autonomy=c.Autonomy.DRAFT,
                              budget=admission.budget, coalesce_create=requested_round is None)
        if intent.budget != admission.budget:
            raise ContractError("idempotency_conflict")
        # Concurrent automatic selection may observe a different catalog count.
        # The first committed intent freezes its actual fixture; never overwrite
        # that selection or let a retry execute different inputs under one key.
        canonical_goal = self._json(context, intent.goal)
        if requested_round is not None and canonical_goal["round_index"] != requested_round:
            raise ContractError("idempotency_conflict")
        round_index = canonical_goal["round_index"]
        source = fixture(round_index)
        inputs = _snapshot(context, canonical_goal["input"])
        if intent.status in {"completed", "failed", "cancelled"}:
            return self._run_result(context, run_id, replayed=True)
        intent = self._walk(context, admission, intent, ("draft", "ready", "running"),
                            already_advanced=("completed", "failed", "cancelled"))
        if intent.status in {"completed", "failed", "cancelled"}:
            return self._run_result(context, run_id, replayed=True)
        completed = {}
        upstream = None
        for persona in PERSONAS:
            if intent.deadline <= _now():
                raise ContractError("demo_deadline_expired")
            key = persona["key"]
            task_id = _id(context, f"run:{run_id}:task:{key}")
            metadata = {"schema_version": 1, "source": "synthetic", "executor": EXECUTOR,
                        "benchmark": BENCHMARK_VERSION,
                        "run_id": str(run_id), "round": round_index + 1, "fixture_id": source["fixture_id"],
                        "persona_key": key, "task_class": persona["task_class"], "title": persona["title"],
                        "input": _wire(inputs)}
            checkpoint = self._put(context, admission, metadata)
            dependencies = (completed["tolik"].ref(),) if key == "ivan" else ()
            task = self._ensure(context, admission, c.Task, task_id, run_id, policy,
                                intent=intent.ref(), role=roles[key].ref(), dependencies=dependencies,
                                checkpoint=checkpoint)
            if task.status in {"succeeded", "failed", "cancelled"}:
                completed[key] = task
                if key == "tolik" and task.status == "succeeded":
                    stored = self._json(context, task.checkpoint)
                    upstream = self._json(context, _snapshot(context, stored["result"]))
                continue
            if key == "ivan" and completed["tolik"].status != "succeeded":
                if task.status != "blocked":
                    task = self._advance(context, admission, task, "blocked")
                completed[key] = task
                continue
            if task.status != "review":
                task = self._walk(context, admission, task, ("planned", "ready", "running"),
                                  already_advanced=("review", "succeeded", "failed", "cancelled"))
            if task.status in {"succeeded", "failed", "cancelled"}:
                completed[key] = task
                if key == "tolik" and task.status == "succeeded":
                    stored = self._json(context, task.checkpoint)
                    upstream = self._json(context, _snapshot(context, stored["result"]))
                continue
            admission.validate(context)
            result, svg = execute(key, source, upstream=upstream)
            verification = evaluate(key, source, result, svg=svg, upstream=upstream)
            result_ref = self._put(context, admission, result)
            verification_ref = self._put(context, admission, verification)
            evidence = (inputs, result_ref)
            metadata.update(result=_wire(result_ref), evaluation=_wire(verification_ref))
            if svg is not None:
                chart = self._put(context, admission, svg, media_type="image/svg+xml")
                metadata["chart"] = _wire(chart)
                evidence += (chart,)
            checkpoint = self._put(context, admission, metadata)
            if task.status != "review":
                task = self._advance(context, admission, task, "review", checkpoint=checkpoint)
            executor_context = _service_context(context, f"benchmark:{key}")
            verifier_context = _service_context(context, "benchmark-verifier")
            contribution = self._ensure(executor_context, admission, c.Contribution,
                _id(context, f"run:{run_id}:contribution:{key}"), run_id, policy,
                task=task.ref(), role=roles[key].ref(), result=result_ref, evidence=evidence)
            if contribution.status not in {"accepted", "rejected"}:
                contribution = self._walk(executor_context, admission, contribution, ("draft", "submitted"),
                                         already_advanced=("accepted", "rejected"))
                if contribution.status == "submitted":
                    self._advance(verifier_context, admission, contribution,
                                  "accepted" if verification["passed"] else "rejected")
            outcome = self._ensure(verifier_context, admission, c.Outcome,
                _id(context, f"run:{run_id}:outcome:{key}"), run_id, policy,
                task=task.ref(), evidence=evidence, verification=verification_ref)
            self._walk(verifier_context, admission, outcome, ("pending", "verified") if verification["passed"]
                       else ("pending", "disputed", "rejected"))
            if task.status not in {"succeeded", "failed", "cancelled"}:
                task = self._advance(context, admission, task, "succeeded" if verification["passed"] else "failed")
            completed[key] = task
            if key == "tolik" and verification["passed"]:
                upstream = result
        status = "completed" if all(task.status == "succeeded" for task in completed.values()) else "failed"
        self._advance(context, admission, intent, status)
        return self._run_result(context, run_id, replayed=False)

    def _run_result(self, context, run_id, *, replayed):
        return {"run": {"id": str(run_id), "task_ids": [str(_id(context, f"run:{run_id}:task:{p['key']}"))
                         for p in PERSONAS], "replayed": replayed, "source": "synthetic", "executor": EXECUTOR},
                "overview": self.overview(context=context)}

    def _persona_dto(self, context, key):
        row = _PERSONAS[key]
        return {"id": str(_id(context, f"persona:{key}")), "key": key,
                "display_name": row["display_name"], "role": row["role"], "role_key": row["role_key"],
                "avatar_key": key, "synthetic": True}

    def _task_dto(self, context, task):
        data = self._json(context, task.checkpoint)
        key = data["persona_key"]
        terminal = task.status in {"succeeded", "failed", "cancelled"}
        score = None
        if "evaluation" in data:
            score = self._json(context, _snapshot(context, data["evaluation"]))["score_pct"]
        return {"id": str(task.header.entity_id), "task_id": str(task.header.entity_id),
                "title": data["title"], "status": task.status, "stage": "evaluation" if terminal else "work",
                "progress_pct": 100 if terminal else 75 if task.status == "review" else 35,
                "lead": self._persona_dto(context, key), "participants": [self._persona_dto(context, key)],
                "created_at": c.primitive(task.header.created_at), "updated_at": c.primitive(task.header.updated_at),
                "summary": "Результат независимо проверен на фиксированных синтетических данных."
                if task.status == "succeeded" else "Учебная задача локального детерминированного исполнителя.",
                "task_class": data["task_class"], "synthetic": True, "source": "synthetic", "executor": EXECUTOR,
                "evidence_count": len([key for key in ("input", "result", "evaluation", "chart") if key in data]),
                "cost_usd": 0, "paid_calls": 0, "observed_score_pct": score, "fixture_id": data["fixture_id"],
                "run_id": data["run_id"], "correlation_id": str(task.header.correlation_id),
                "dependencies": [str(ref.entity_id) for ref in task.dependencies]}

    def work(self, *, context, page: PageRequest | None = None) -> list[dict]:
        found = self.repository.list(context=context, kind=EntityKind.TASK, page=page or PageRequest(limit=100))
        return sorted([self._task_dto(context, task) for task in found.items
                       if task.checkpoint is not None and task.header.owner_user_uuid == context.user_uuid],
                      key=lambda item: (item["created_at"], item["id"]), reverse=True)

    def agents(self, *, context) -> list[dict]:
        tasks = self.work(context=context)
        result = []
        for persona in PERSONAS:
            key = persona["key"]
            samples = {}
            owned = [task for task in tasks if task["lead"]["key"] == key]
            for task in reversed(owned):
                if task["observed_score_pct"] is not None:
                    samples[task["fixture_id"]] = min(samples.get(task["fixture_id"], 100),
                                                      task["observed_score_pct"])
            n = len(samples)
            score = sum(samples.values()) // n if n else None
            result.append({**self._persona_dto(context, key), "status": "idle", "capabilities": ["ai_lab"],
                "autonomy": "draft", "model": None, "tasks_completed": sum(t["status"] == "succeeded" for t in owned),
                "evaluation": {"sample_size": n, "score_pct": score if n >= 3 else None,
                    "observed_score_pct": score, "confidence": "low" if n >= 3 else "insufficient",
                    "passed": sum(value == 100 for value in samples.values()),
                    "failed": sum(value < 100 for value in samples.values()), "task_class": persona["task_class"],
                    "window_label": "Фиксированный synthetic benchmark v1 · 3 разных случая",
                    "mode": "deterministic_synthetic", "aggregation": "worst_per_fixture",
                    "routing_effect": "none", "model_quality_assessed": False},
                "rank": None, "task_ids": [t["id"] for t in owned]})
        # A tied benchmark score is a tie, not invented differentiation. Different
        # task classes are displayed independently; no global agent ranking.
        for item in result:
            if item["evaluation"]["score_pct"] is not None:
                item["rank"] = 1
                item["rank_scope"] = item["evaluation"]["task_class"]
        return result

    def _artifact_dto(self, context, label, value):
        ref = _snapshot(context, value)
        found = self.repository.get_artifact(context=context, reference=ref)
        if not found:
            raise ContractError("demo_evidence_unavailable")
        return {"id": str(ref.artifact_id), "title": label, "sha256": ref.sha256,
                "mime_type": found[1], "media_type": found[1], "synthetic": True,
                "url": self.artifact_url_prefix + str(ref.artifact_id), "size_bytes": len(found[0])}

    def task_detail(self, *, context, entity_id: UUID) -> dict | None:
        task = self.repository.get(context=context, kind=EntityKind.TASK, entity_id=entity_id)
        if task is None or task.checkpoint is None or task.header.owner_user_uuid != context.user_uuid:
            return None
        data = self._json(context, task.checkpoint)
        result = self._json(context, _snapshot(context, data["result"])) if "result" in data else None
        evaluation = self._json(context, _snapshot(context, data["evaluation"])) if "evaluation" in data else None
        artifacts = [self._artifact_dto(context, label, data[key]) for key, label in (
            ("input", "Синтетические входные данные"), ("result", "Результат вычисления"),
            ("evaluation", "Независимая проверка"), ("chart", "График Ивана — synthetic")) if key in data]
        activity = []
        cursor = None
        # Bounded event ledger projection. No prompts or hidden reasoning.
        for _ in range(8):
            events = self.repository.events.list(context=context, page=PageRequest(limit=100, cursor=cursor))
            activity.extend({"id": str(event.event_id), "type": event.event_type,
                             "at": c.primitive(event.time), "time": c.primitive(event.time),
                             "title": event.event_type.removeprefix("stratforge.ai."),
                             "revision": event.subject.revision, "synthetic": True}
                            for event in events.items if event.subject.entity_id == entity_id)
            cursor = events.next_cursor
            if not cursor:
                break
        dto = self._task_dto(context, task)
        return {"task": dto, "task_id": dto["id"], "activity": activity, "timeline": activity,
                "activity_truncated": bool(cursor), "contributions": [{"persona": dto["lead"],
                    "status": "accepted" if evaluation and evaluation["passed"] else "submitted",
                    "result": result, "summary": dto["summary"], "synthetic": True}] if result else [],
                "outcomes": [{"status": "verified" if evaluation["passed"] else "rejected",
                              "summary": dto["summary"], "evidence_count": len(artifacts)}] if evaluation else [],
                "evaluations": [evaluation] if evaluation else [], "artifacts": artifacts,
                "result": result, "result_text": self._result_text(data["persona_key"], result),
                "decisions": [], "experiments": [], "errors": []}

    @staticmethod
    def _result_text(key, result):
        if result is None:
            return "Задача ещё не сформировала результат."
        if key == "marina":
            return f"Учебный журнал: итог {result['net_cents']} центов после {result['fees_cents']} центов комиссий."
        if key == "tolik":
            return f"Проверено {result['sample_count']} наблюдений; диапазон {result['minimum_ticks']}–{result['maximum_ticks']} ticks."
        if key == "nikita":
            return f"Разобрано {len(result['events'])} синтетических событий; review: {result['review_count']}."
        return f"Создан SVG-график: {result['bar_count']} синтетических свечей, {result['width']} × {result['height']}."

    def artifact(self, *, context, entity_id: UUID):
        """Private repository lookup; caller must still apply route authorization."""
        return self.repository.get_artifact_by_id(context=context, artifact_id=entity_id)

    def overview(self, *, context) -> dict:
        tasks = self.work(context=context)
        agents = self.agents(context=context)
        totals = {"tasks_total": len(tasks), "completed": sum(t["status"] == "succeeded" for t in tasks),
                  "running": sum(t["status"] == "running" for t in tasks),
                  "failed": sum(t["status"] == "failed" for t in tasks),
                  "evaluations": sum(t["observed_score_pct"] is not None for t in tasks),
                  "artifacts": sum(t["evidence_count"] for t in tasks), "paid_calls": 0, "cost_usd": 0}
        return {"schema_version": 1, "source": "synthetic", "executor": EXECUTOR,
                "summary": totals, "stats": totals, "work": {"items": tasks[:20]}, "agents": {"items": agents},
                "constraints": ["Fixed synthetic benchmark only; not real model quality or market performance",
                                "External AI, trading, Court and routing changes are disabled"],
                "read_limit": 100, "read_limit_reached": len(tasks) >= 100}
