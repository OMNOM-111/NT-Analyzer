"""External-agent ports over the existing native repository and OS/PG locks.

No schema, queue, credential store or second registry. Every dispatcher and
lifecycle mutator must take the same scoped guard through its network boundary.
"""
from contextlib import contextmanager
import hashlib
import os
import time
from uuid import UUID, uuid5

from . import contracts as c
from .events import EventData, EventEnvelope, MutationIdentity
from .external_agent_contracts import ExternalAgentConnection
from .states import ContractError


class NativeExternalRepository:
    def __init__(self, repository):
        self.repository = repository

    def get_external_connection(self, *, context, connection_id):
        try:
            identity = UUID(str(connection_id))
            c.require_uuid(identity)
        except (ValueError, TypeError):
            raise ContractError("external_agent_id_invalid") from None
        row = self.repository.get(context=context, kind=ExternalAgentConnection.KIND, entity_id=identity)
        if row is not None:
            if not isinstance(row, ExternalAgentConnection):
                raise ContractError("external_agent_record_invalid")
            row.require_owner(context)
        return row

    def commit_external_connection(self, *, context, connection, expected_revision, idempotency_key):
        connection.require_owner(context)
        event = EventEnvelope(event_id=uuid5(connection.header.entity_id, f"revision:{connection.header.revision}"),
            event_type="stratforge.ai.external_agent_connection.changed", time=connection.header.updated_at,
            subject=connection.ref(), actor=context.actor, correlation_id=connection.header.correlation_id,
            causation_id=connection.header.causation_id, policy=connection.header.policy,
            data=EventData(reason_code="external_agent_lifecycle"))
        mutation = MutationIdentity.for_record(context=context, operation="agent_world.external_agent.write",
            idempotency_key=idempotency_key, record=connection, expected_revision=expected_revision, event=event)
        return self.repository.commit(context=context, record=connection, expected_revision=expected_revision,
                                      event=event, mutation=mutation).record

    @contextmanager
    def guard(self, context, connection_id, timeout=35.0):
        if not isinstance(context, c.RequestContext) or not 0 < timeout <= 60:
            raise ContractError("external_agent_guard_invalid")
        identity = UUID(str(connection_id))
        c.require_uuid(identity)
        self.repository._context(context)
        if self.repository.read_only:
            raise ContractError("agent_world_repository_read_only")
        # Owner included: all native private connection accesses recheck owner.
        token = hashlib.sha256(f"external-agent-v1:{context.scope.environment.value}:"
            f"{context.scope.workspace_id}:{context.user_uuid}:{identity}".encode()).digest()
        deadline = time.monotonic() + timeout
        if hasattr(self.repository, "client"):
            from app.production_storage.core import Scope
            key = int.from_bytes(token[:8], "big", signed=True)
            # Dedicated scoped transaction: DO NOT take the repository's
            # workspace advisory lock while nested native commits take it.
            with self.repository.client.transaction(Scope.workspace_scope(context.scope.workspace_id)) as conn:
                while not conn.execute("SELECT pg_try_advisory_xact_lock(%s) AS acquired", (key,)).fetchone()["acquired"]:
                    if time.monotonic() >= deadline:
                        raise ContractError("external_agent_connection_busy")
                    time.sleep(0.025)
                yield
            return
        directory = self.repository.path.parent / (self.repository.path.name + ".external-agent-locks")
        directory.mkdir(exist_ok=True)
        path = directory / (token.hex() + ".lock")
        with path.open("a+b") as handle:
            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            acquired = False
            try:
                while not acquired:
                    handle.seek(0)
                    try:
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                    except (BlockingIOError, OSError):
                        if time.monotonic() >= deadline:
                            raise ContractError("external_agent_connection_busy") from None
                        time.sleep(0.025)
                yield
            finally:
                if acquired:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
