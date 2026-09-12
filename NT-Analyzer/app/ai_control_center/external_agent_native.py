"""External connections in the existing record store, Coordinator and worker.

No Model records, private queue or reputation format. All evidence uses the
shared Contribution/Outcome/Evaluation records and independent rubric verifier.
"""
import json
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import UUID, uuid5

from . import contracts as c, reputation
from .external_agent_contracts import ExternalAgentConnection, candidate
from .external_agent_protocol import A2AClient, CAPABILITIES, PROTOCOL, RemoteTask, target
from .external_agent_adapter import ExternalAgentAdapter
from .external_agent_onboarding import ExternalAgentOnboarding
from .external_agent_repository import NativeExternalRepository
from . import external_agent_development as dev
from .flags import Flag, current_snapshot, resolve
from .model_contracts import Evaluation
from .model_evaluation import prepare
from .model_service import _id, _key, _wire
from .states import ContractError, EntityKind

SOURCE = "external_agent_task_v1"


class ExternalAgentService:
    def __init__(self, authorized, records, *, enqueue, enqueue_cleanup):
        self.authorized, self.records = authorized, records
        self.context = authorized["context"]
        self.repository = NativeExternalRepository(records.repository)
        self.enqueue, self.enqueue_cleanup = enqueue, enqueue_cleanup

    def admit(self, **kw):
        self.records._access(self.context, "read" if kw.get("operation") == "read" else "external_agent")
        if not resolve(Flag.AI_EXTERNAL_AGENT_V1, scope=self.context.scope,
                       snapshot=current_snapshot(self.authorized)).enabled:
            raise ContractError("external_agent_disabled")

    def connection(self, identity):
        self.admit(operation="read")
        row = self.repository.get_external_connection(context=self.context, connection_id=str(identity))
        if row is None: raise ContractError("external_agent_not_found")
        return row

    def onboarding(self, endpoint=None):
        synthetic = endpoint == dev.ENDPOINT
        if synthetic and not dev.enabled(self.authorized):
            raise ContractError("external_agent_test_disabled")
        def validate(value):
            if synthetic and value == dev.ENDPOINT and dev.enabled(self.authorized): return
            target(value)
        return ExternalAgentOnboarding(repository=self.repository, admit=self.admit,
            policy=lambda ctx: self.records._put(ctx, {"source": "external_agent_connection", "risk": "low", "synthetic": synthetic}),
            secrets=self.records.secrets, client=dev.client(self.authorized) if synthetic else A2AClient(),
            validate_endpoint=validate, synthetic_workspace=self.context.scope.workspace_id if synthetic else None,
            enqueue_cleanup=self.enqueue_cleanup)

    def mutate(self, identity, action, payload, revision, key):
        self.admit()
        if identity == "new" and action == "create":
            # Same deterministic ID used by onboarding, so concurrent create
            # and later rotation use the very same cross-process authority lock.
            from .external_agent_onboarding import NAMESPACE
            _key(key)
            cid = uuid5(NAMESPACE, f"{self.context.scope.environment.value}:{self.context.scope.workspace_id}:{self.context.user_uuid}:{key}")
            with self.repository.guard(self.context, cid):
                row = self.onboarding(payload.get("endpoint")).create(context=self.context, payload=payload, idempotency_key=key)
            return self.detail(row["id"])
        extra = {}
        with self.repository.guard(self.context, identity):
            row = self.connection(identity)
            service = self.onboarding(row.endpoint)
            args = dict(context=self.context, connection_id=str(identity), expected_revision=revision, idempotency_key=key)
            if action == "verify" and not payload: service.verify(**args)
            elif action == "revoke" and not payload:
                # Whether the retired secret is gone or still queued for
                # deletion is part of what happened, and the page shows it.
                extra["credential_cleanup"] = service.revoke(**args).get("credential_cleanup")
            elif action == "rotate" and set(payload) == {"credential"}: service.rotate_credential(**args, credential=payload["credential"])
            elif action == "disable" and not payload:
                if row.header.revision != revision: raise ContractError("external_agent_revision_conflict")
                changed = row.transition("disabled", now=datetime.now(timezone.utc))
                self.repository.commit_external_connection(context=self.context, connection=changed,
                    expected_revision=revision, idempotency_key=key)
            elif action == "task":
                from .coordinator import commission_external
                return commission_external(self, row, payload, key)
            else: raise ContractError("external_agent_action_invalid")
        return {**self.detail(identity), **extra}

    def list(self):
        self.admit(operation="read")
        result = {"enabled": True, "items": [self.detail(row.header.entity_id) for row in self.records._all(self.context, EntityKind.EXTERNAL_AGENT_CONNECTION)],
                  "actions": ["create"], "protocols": [PROTOCOL]}
        if dev.enabled(self.authorized):
            result["test_connection"] = {"endpoint": dev.ENDPOINT, "credential": dev.CREDENTIAL, "synthetic": True}
        return result

    def detail(self, identity):
        row = self.connection(identity)
        tasks = []
        for task in self.records._all(self.context, EntityKind.TASK):
            if not task.checkpoint: continue
            cp = self.records._json(self.context, task.checkpoint)
            if cp.get("source") != SOURCE or cp.get("connection_id") != str(identity): continue
            tasks.append({**self.task_detail(task.header.entity_id)["task"], "requires_human_review": True})
        performance = reputation.measure(self.records, self.context, subject_kind=row.KIND,
            subject_id=row.header.entity_id, task_class="json_arithmetic", now=datetime.now(timezone.utc))
        # Diagnostic numbers stay evidence, not the headline professional score.
        actions = [] if row.status == "revoked" else ["verify", "revoke", "rotate"]
        if row.status not in {"disabled", "revoked"}: actions.append("disable")
        if row.status == "active": actions.append("task")
        return {**row.public(), "last_verified_at": row.public()["last_verification"], "last_error_code": row.last_error,
            "latency_ms": row.last_latency_ms, "actions": actions, "tasks": tasks,
            "current_task": next((t for t in tasks if t["status"] in {"ready", "running", "waiting"}), None),
            "performance": performance, "statistics": {"tasks_completed": sum(t["evaluation_id"] is not None for t in tasks),
                "results_received": sum(t["result_received"] is True for t in tasks),
                "reviews_completed": sum(t["human_review"]["status"] in {"accepted", "rejected"} for t in tasks),
                "awaiting_review": sum(t["display_status"] == "awaiting_review" for t in tasks),
                "sample_size": performance["sample_size"], "passed": performance["quality"]["passed"],
                "failed": performance["sample_size"] - performance["quality"]["passed"],
                "synthetic_count": performance["provenance"]["synthetic_observations"]}}

    def task_detail(self, identity):
        """Native task read model; a connection is never projected as a Model."""
        from . import task_presentation, task_review
        self.admit(operation="read")
        ctx, db = self.context, self.records
        task = db._get(ctx, EntityKind.TASK, identity)
        cp = db._json(ctx, task.checkpoint)
        if cp.get("source") != SOURCE:
            raise ContractError("external_agent_task_not_found")
        connection = self.connection(cp["connection_id"])
        receipt = db._json(ctx, cp["receipt"]) if cp.get("receipt") else {}
        evaluation = {}
        if cp.get("evaluation_id"):
            ev = db._get(ctx, EntityKind.EVALUATION, cp["evaluation_id"])
            outcome = db._get(ctx, EntityKind.OUTCOME, cp["outcome_id"])
            if (ev.subject.kind != EntityKind.EXTERNAL_AGENT_CONNECTION
                    or ev.subject.entity_id != connection.header.entity_id
                    or ev.task.entity_id != task.header.entity_id
                    or ev.outcome != outcome.ref() or outcome.verification != ev.evidence):
                raise ContractError("external_agent_evidence_mismatch")
            evaluation = db._json(ctx, ev.evidence)
            if (evaluation.get("receipt") != cp.get("receipt")
                    or evaluation.get("connection_id") != cp["connection_id"]
                    or evaluation.get("synthetic") is not cp["synthetic"]):
                raise ContractError("external_agent_evidence_mismatch")
        dto = {"id": str(task.header.entity_id), "task_id": str(task.header.entity_id),
            "revision": task.header.revision, "status": task.status,
            "title": connection.display_name + " · Диагностика внешнего агента",
            "summary": "Результат требует отдельной проверки" if evaluation else "Задание внешнему агенту",
            "source_kind": SOURCE, "synthetic": cp["synthetic"], "task_class": "json_arithmetic",
            "connection_id": cp["connection_id"], "model_id": None, "model": "unknown / externally managed",
            "performance_scope": "external_agent_performance", "quality_claim": False,
            "lead": {"id": cp["connection_id"], "display_name": connection.display_name, "role": "external_agent"},
            "conversation_id": cp.get("conversation_id"), "message_id": cp.get("message_id"),
            "correlation_id": str(task.header.correlation_id), "intent_id": str(task.intent.entity_id),
            "contribution_id": cp.get("contribution_id"), "outcome_id": cp.get("outcome_id"),
            "evaluation_id": cp.get("evaluation_id"), "error_code": cp.get("error"),
            "external_call": not cp["synthetic"] if receipt else None,
            "provider_result_received": bool(receipt), "evidence_count": 1 if evaluation else 0,
            "created_at": task.header.created_at.isoformat(), "updated_at": task.header.updated_at.isoformat()}
        review = task_review.projection(db, ctx, task, cp, dto)
        dto = task_presentation.project(dto, evaluation=evaluation, human_review=review)
        dto["actions"] = ["review_result"] if review["status"] == "pending" else []
        return {**dto, "task": dto, "human_review": review, "evaluation": evaluation,
            "result_text": json.dumps(receipt.get("response"), ensure_ascii=False) if receipt else "",
            "graph": {"nodes": [], "edges": []}, "artifacts": []}

    def tasks(self):
        self.admit(operation="read")
        result = []
        for task in self.records._all(self.context, EntityKind.TASK):
            if task.header.owner_user_uuid != self.context.user_uuid or not task.checkpoint:
                continue
            if self.records._json(self.context, task.checkpoint).get("source") == SOURCE:
                result.append(self.task_detail(task.header.entity_id)["task"])
        return result

    def assign(self, row, payload, key):
        """Called only by Coordinator after compatible-role selection."""
        if type(payload) is not dict or set(payload) != {"input_text"}: raise ContractError("external_agent_task_payload_invalid")
        # Whether this agent can be dispatched at all is answered before the
        # numbers are judged. A disabled agent replying "your numbers are
        # wrong" sends the person to fix the wrong thing — and a revoked one
        # refused as "no compatible role" is true about the wrong thing too.
        if row.status == "revoked":
            raise ContractError("external_agent_revoked")
        if row.status != "active":
            raise ContractError("external_agent_not_active")
        spec = prepare("json_arithmetic", payload["input_text"])
        if not row.synthetic:
            # No paid external-agent allowance/pricing contract is installed.
            raise ContractError("external_agent_remote_budget_not_configured")
        self.admit()
        ctx, db = self.context, self.records
        task_id = _id(ctx, "external-task:" + _key(key))
        policy = db._put(ctx, {"source": SOURCE, "synthetic": row.synthetic, "capability": sorted(CAPABILITIES)[0]})
        role = db._ensure(ctx, c.AgentRole, _id(ctx, "external-role:numeric-summary"), task_id, policy,
            role_key="external_numeric_summary", responsibilities=policy, capability_ceiling=("ai_pro_models",), autonomy_ceiling=c.Autonomy.ADVICE)
        role = db._walk(ctx, role, "active")
        if not candidate(row, context=ctx, role=role, capability=sorted(CAPABILITIES)[0]): raise ContractError("external_agent_no_compatible_role")
        old = db.repository.get(context=ctx, kind=EntityKind.TASK, entity_id=task_id)
        if old is not None:
            cp = db._json(ctx, old.checkpoint)
            if cp.get("connection_id") != str(row.header.entity_id) or cp.get("spec") != spec:
                raise ContractError("external_agent_idempotency_conflict")
            if old.status == "ready" and not cp.get("claimed"): self.enqueue(task_id)
            return {"task_id": str(task_id), "started_task_id": str(task_id), "status": old.status}
        goal = db._put(ctx, {"goal": "External numeric summary", "source": SOURCE, "spec": spec, "synthetic": row.synthetic})
        intent = db._ensure(ctx, c.Intent, _id(ctx, "external-intent:" + str(task_id)), task_id, policy,
            goal=goal, acceptance=goal, risk=c.Risk.LOW, autonomy=c.Autonomy.ADVICE,
            budget=c.ExternalRef(authority=c.ExternalAuthority.BUDGET, key="workspace.ai_budget", scope=ctx.scope))
        intent = db._walk(ctx, intent, "ready")
        cp = {"source": SOURCE, "connection_id": str(row.header.entity_id), "connection_revision": row.header.revision,
              "spec": spec, "synthetic": row.synthetic, "capability": sorted(CAPABILITIES)[0], "coordinator": "compatible_external_role_v1"}
        from . import external_agent_chat
        cp.update(external_agent_chat.bind(self.authorized, task_id, row.display_name, payload["input_text"]))
        task = db._ensure(ctx, c.Task, task_id, task_id, policy, intent=intent.ref(), role=role.ref(), checkpoint=db._put(ctx, cp))
        task = db._walk(ctx, task, "ready")
        self.enqueue(task_id)
        return {"task_id": str(task_id), "started_task_id": str(task_id), "status": task.status}

    def execute(self, task_id, cancelled, heartbeat):
        # Delivery failure cannot rewrite a verified result as execution failure.
        # Retrying this same durable job reads the terminal receipt, never sends again.
        result = self._execute(task_id, cancelled, heartbeat)
        if result.get("status") in {"review", "succeeded", "failed", "blocked", "cancelled"}:
            from . import external_agent_chat
            external_agent_chat.deliver(self.authorized, self, task_id)
        return result

    def _execute(self, task_id, cancelled, heartbeat):
        ctx, db = self.context, self.records
        task = db._get(ctx, EntityKind.TASK, task_id)
        cp = db._json(ctx, task.checkpoint)
        if cp.get("source") != SOURCE: raise ContractError("external_agent_task_not_found")
        with self.repository.guard(ctx, cp["connection_id"]):
            self.admit()
            task = db._get(ctx, EntityKind.TASK, task_id); cp = db._json(ctx, task.checkpoint)
            if task.status in {"succeeded", "review", "failed", "cancelled", "blocked"}:
                return {"ok": task.status in {"succeeded", "review"}, "task_id": str(task_id), "status": task.status}
            row = self.connection(cp["connection_id"])
            if row.status != "active" or row.header.revision != cp["connection_revision"]:
                return self.fail(task, cp, "external_agent_revoked_or_changed")
            if cancelled(): return self.fail(task, cp, "external_agent_cancelled")
            task = db._walk(ctx, task, "running")
            intent = db._get(ctx, EntityKind.INTENT, task.intent.entity_id)
            intent = db._walk(ctx, intent, "running")
            task = db._change(ctx, task, intent=intent.ref())
            role = db._get(ctx, EntityKind.AGENT_ROLE, task.role.entity_id)
            def admit(**kw):
                self.admit()
                if cancelled(): raise ContractError("external_agent_cancelled")
                heartbeat()
            def binding(**kw): return db._json(ctx, db._get(ctx, EntityKind.TASK, task_id).checkpoint)
            def claim(**kw):
                latest = db._get(ctx, EntityKind.TASK, task_id); state = db._json(ctx, latest.checkpoint)
                if state.get("claimed"): return False
                state["claimed"] = True
                db._change(ctx, latest, checkpoint=db._put(ctx, state))
                return True
            adapter = ExternalAgentAdapter(load_connection=self.repository.get_external_connection,
                load_task_binding=binding, claim_dispatch=claim, read_secret=db.secrets.get_secret, admit=admit,
                reserve_budget=lambda **kw: {"ok": True, "reservation_id": "diagnostic-zero-cost:" + str(task_id)},
                client=dev.client(self.authorized) if row.synthetic else A2AClient())
            args = dict(context=ctx, connection_id=cp["connection_id"], task=task, intent=intent, role=role,
                capability=cp["capability"], values=cp["spec"]["input"], request_id="external." + str(task_id))
            try:
                if cp.get("remote"):
                    result = adapter.poll(**args, remote=RemoteTask(**cp["remote"]), connection_revision=cp["connection_revision"])
                elif cp.get("receipt"):
                    result = None
                else:
                    result = adapter.send(**args)
                latest = db._get(ctx, EntityKind.TASK, task_id); state = db._json(ctx, latest.checkpoint)
                if result is not None:
                    state["remote"] = asdict(result.remote); state["remote_task_id"] = result.remote.task_id
                    if result.remote.state != "completed":
                        db._change(ctx, latest, "waiting", checkpoint=db._put(ctx, state))
                        return {"ok": False, "status": "waiting", "task_id": str(task_id)}
                    state["receipt"] = _wire(db._put(ctx, {"response": result.remote.data_json, "verification": result.verification,
                        "synthetic": row.synthetic, "model_id": None, "connection_id": cp["connection_id"]}))
                    latest = db._change(ctx, latest, checkpoint=db._put(ctx, state))
                return self.finish(latest, state, row)
            except ContractError as error:
                latest = db._get(ctx, EntityKind.TASK, task_id)
                return self.fail(latest, db._json(ctx, latest.checkpoint), error.code)
            except Exception:
                # The worker died between claiming the dispatch and reading a
                # reply. Whether the agent ever saw the request is unknown, so
                # it is never sent again on its own — but the task says that,
                # instead of sitting in `running` with nothing to read.
                latest = db._get(ctx, EntityKind.TASK, task_id)
                self.fail(latest, db._json(ctx, latest.checkpoint), "external_agent_reply_uncertain")
                raise

    def fail(self, task, cp, code):
        cp = {**cp, "error": code}
        self.records._change(self.context, task, "blocked", checkpoint=self.records._put(self.context, cp))
        return {"ok": False, "task_id": str(task.header.entity_id), "status": "blocked", "error_code": code}

    def finish(self, task, cp, connection):
        ctx, db = self.context, self.records
        receipt = db._json(ctx, cp["receipt"])
        from .model_evaluation import evaluate
        proof_data = {**evaluate(cp["spec"], receipt["response"]), "synthetic": cp["synthetic"],
            "connection_id": cp["connection_id"], "model_id": None, "performance_scope": "external_agent_performance",
            "external_call": not cp["synthetic"], "requires_human_review": True, "receipt": cp["receipt"]}
        proof = db._put(ctx, proof_data)
        response = db._put(ctx, receipt)
        role = db._get(ctx, EntityKind.AGENT_ROLE, task.role.entity_id)
        tid, policy = task.header.entity_id, task.header.policy
        contribution = db._ensure(ctx, c.Contribution, _id(ctx, "external-contribution:" + str(tid)), tid, policy,
            task=task.ref(), role=role.ref(), result=response, evidence=(response, proof))
        contribution = db._walk(ctx, contribution, "submitted")
        outcome = db._ensure(ctx, c.Outcome, _id(ctx, "external-outcome:" + str(tid)), tid, policy,
            task=task.ref(), evidence=(response, proof))
        if outcome.status == "pending": outcome = db._change(ctx, outcome, "verified" if proof_data["passed"] else "disputed", verification=proof)
        ev = db._ensure(ctx, Evaluation, _id(ctx, "external-evaluation:" + str(tid)), tid, policy,
            task=task.ref(), outcome=outcome.ref(), evidence=proof, subject=connection.ref(), rubric_key="json_arithmetic")
        cp.update(contribution_id=str(contribution.header.entity_id), evaluation_id=str(ev.header.entity_id), outcome_id=str(outcome.header.entity_id))
        task = db._change(ctx, task, "review", checkpoint=db._put(ctx, cp))
        return {"ok": True, "task_id": str(tid), "status": task.status, "evaluation_id": str(ev.header.entity_id), "synthetic": cp["synthetic"]}
