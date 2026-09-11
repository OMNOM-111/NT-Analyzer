"""Admitted-task A2A adapter, with mandatory existing-authority dependencies.

This is a worker/Coordinator integration seam, not a second queue, registry,
permission engine or history store. Native composition is deliberately absent
until the integrator registers the separate connection/evaluation contract.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json

from . import contracts as c
from .external_agent_contracts import ExternalAgentConnection, candidate
from .external_agent_protocol import A2AClient, RemoteTask
from .model_evaluation import evaluate, prepare
from .states import ContractError


@dataclass(frozen=True)
class AdapterResult:
    remote: RemoteTask
    connection_id: str
    connection_revision: int
    synthetic: bool
    verification: dict | None
    model_id: None = None
    performance_scope: str = "external_agent"


class ExternalAgentAdapter:
    def __init__(self, *, load_connection, load_task_binding, claim_dispatch, read_secret, admit, reserve_budget, client=None):
        for port in (load_connection, load_task_binding, claim_dispatch, read_secret, admit, reserve_budget):
            if not callable(port):
                raise ContractError("external_agent_composition_required")
        self.load_connection = load_connection
        self.load_task_binding = load_task_binding
        self.claim_dispatch = claim_dispatch
        self.read_secret = read_secret
        self.admit = admit
        self.reserve_budget = reserve_budget
        self.client = client or A2AClient()

    def _bound(self, *, context, connection_id, task, intent, role, capability, expected_revision=None):
        # The host must refresh actual membership/device, task cancellation,
        # current role/grant and workspace budget; a valid DTO is not admission.
        self.admit(context=context, task=task, operation="external_agent_step")
        if not isinstance(context, c.RequestContext) or context.scope.environment != c.Environment.DEVELOPMENT:
            raise ContractError("external_agent_environment_denied")
        if not isinstance(task, c.Task) or not isinstance(intent, c.Intent) or not isinstance(role, c.AgentRole):
            raise ContractError("external_agent_task_contract_required")
        for record in (task, intent, role):
            c.require_same_scope(context.scope, record.header.scope)
            if record.header.owner_user_uuid != context.user_uuid:
                raise ContractError("external_agent_task_owner_denied")
        if (task.intent != intent.ref() or task.role != role.ref() or task.status not in {"ready", "running", "waiting"}
                or intent.status not in {"ready", "running"} or intent.risk != c.Risk.LOW
                or intent.autonomy != c.Autonomy.ADVICE or intent.deadline <= datetime.now(timezone.utc)):
            raise ContractError("external_agent_task_authority_denied")
        connection = self.load_connection(context=context, connection_id=connection_id)
        if not isinstance(connection, ExternalAgentConnection) or str(connection.header.entity_id) != connection_id:
            raise ContractError("external_agent_not_found")
        if not candidate(connection, context=context, role=role, capability=capability):
            raise ContractError("external_agent_unavailable")
        if expected_revision is not None and connection.header.revision != expected_revision:
            raise ContractError("external_agent_connection_changed")
        return connection

    def send(self, *, context, connection_id, task, intent, role, capability, values, request_id):
        spec = prepare("json_arithmetic", json.dumps(values))
        bound = dict(context=context, connection_id=connection_id, task=task, intent=intent, role=role, capability=capability)
        connection = self._bound(**bound)
        self._binding(context, task, connection, spec)
        # No advertised price or request payload can invent a budget. A host
        # must use its existing bounded reservation and idempotency facility.
        reservation = self.reserve_budget(context=context, task=task, connection=connection, request_id=request_id)
        if not isinstance(reservation, dict) or reservation.get("ok") is not True or not reservation.get("reservation_id"):
            raise ContractError("external_agent_budget_denied")
        connection = self._bound(**bound, expected_revision=connection.header.revision)
        self._binding(context, task, connection, spec)
        if self.claim_dispatch(context=context, task=task, request_id=request_id) is not True:
            raise ContractError("external_agent_dispatch_already_claimed")
        secret = self.read_secret(connection.credential.key)
        result = self.client.send(connection.endpoint, secret, task_id=str(task.header.entity_id),
            intent_id=str(intent.header.entity_id), capability=capability, values=values, request_id=request_id)
        self._bound(**bound, expected_revision=connection.header.revision)
        return self._result(result, connection, spec)

    def poll(self, *, context, connection_id, task, intent, role, capability, values, remote, request_id, connection_revision):
        bound = dict(context=context, connection_id=connection_id, task=task, intent=intent, role=role,
                     capability=capability, expected_revision=connection_revision)
        connection = self._bound(**bound)
        if not isinstance(remote, RemoteTask) or remote.context_id != str(intent.header.entity_id):
            raise ContractError("external_agent_task_binding_invalid")
        spec = prepare("json_arithmetic", json.dumps(values))
        self._binding(context, task, connection, spec, remote_id=remote.task_id)
        result = self.client.get(connection.endpoint, self.read_secret(connection.credential.key),
            task_id=remote.task_id, context_id=remote.context_id, request_id=request_id)
        self._bound(**bound)
        return self._result(result, connection, spec)

    def _binding(self, context, task, connection, spec, remote_id=None):
        # Load only the approved checkpoint, never an envelope from the agent.
        binding = self.load_task_binding(context=context, task=task)
        if (not isinstance(binding, dict) or binding.get("connection_id") != str(connection.header.entity_id)
                or binding.get("connection_revision") != connection.header.revision or binding.get("spec") != spec
                or (remote_id is not None and binding.get("remote_task_id") != remote_id)):
            raise ContractError("external_agent_approved_scope_changed")

    def cancel(self, *, context, connection_id, task, intent, role, capability, values, remote, request_id, connection_revision):
        """Cancel a bound remote task, not an arbitrary user-supplied task ID.

        Revoked credentials are never resurrected for cleanup. The host must
        request cancellation before revocation; a remote completion can win.
        Cancellation observations do not constitute an Evaluation or review.
        """
        bound = dict(context=context, connection_id=connection_id, task=task, intent=intent, role=role,
                     capability=capability, expected_revision=connection_revision)
        connection = self._bound(**bound)
        if not isinstance(remote, RemoteTask) or remote.context_id != str(intent.header.entity_id):
            raise ContractError("external_agent_task_binding_invalid")
        spec = prepare("json_arithmetic", json.dumps(values))
        self._binding(context, task, connection, spec, remote_id=remote.task_id)
        result = self.client.cancel(connection.endpoint, self.read_secret(connection.credential.key),
            task_id=remote.task_id, context_id=remote.context_id, request_id=request_id)
        self._bound(**bound)
        return AdapterResult(result, str(connection.header.entity_id), connection.header.revision, connection.synthetic, None)

    @staticmethod
    def _result(remote, connection, spec):
        proof = evaluate(spec, remote.data_json) if remote.state == "completed" else None
        if proof is not None:
            proof = {**proof, "synthetic": connection.synthetic, "performance_scope": "external_agent",
                "model_id": None, "model_performance_effect": "none", "quality_claim": False,
                "real_benchmark_eligible": False, "requires_human_review": True}
        return AdapterResult(remote, str(connection.header.entity_id), connection.header.revision, connection.synthetic, proof)
