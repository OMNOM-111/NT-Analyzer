"""Explicit PostgreSQL adapter for the reviewed Agent World repository.

No constructor I/O/DDL, environment discovery, SQLite fallback, worker, or
permission authority. Admission supplies RequestContext; the existing PG client
opens a fresh scoped transaction for every operation. Migration 0023 is an
operator-controlled prerequisite. The application role must not own the tables,
be superuser, or have BYPASSRLS. Public record DTOs retain the existing workspace
visibility contract; private Memory, artifacts, events and mutations stay owned.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid5

from app.production_storage.core import (
    PostgresClient, Scope, StorageConflictError, StorageConstraintError,
    StorageError, StorageReadOnlyError,
)

from . import contracts as c
from .events import EventEnvelope, MutationIdentity, request_digest
from .repositories import CommitResult, Page, PageRequest, validate_commit
from .sqlite_repository import _ARTIFACT_NAMESPACE, _canonical, _references, _validate_artifact, _visibility
from .states import ContractError, EntityKind
from .storage_codec import decode_event, decode_record, encode_event, encode_record


_TABLES = tuple("sf_aw_" + name for name in (
    "meta", "records", "revisions", "events", "outbox", "mutations", "inbox",
    "artifacts", "memory_grants", "memory_grant_anchors",
))
_REPLAY = """SELECT m.*,v.payload AS record_payload,e.payload AS event_payload
    FROM sf_aw_mutations m JOIN sf_aw_revisions v
      ON (v.environment,v.workspace_id,v.kind,v.entity_id,v.revision)=
         (m.environment,m.workspace_id,m.kind,m.entity_id,m.revision)
    JOIN sf_aw_events e ON (e.environment,e.workspace_id,e.event_id)=
         (m.environment,m.workspace_id,m.event_id)
    WHERE m.environment=%s AND m.workspace_id=%s AND m.operation=%s AND m.key_hash=%s"""


class PostgresAgentWorldRepository:
    def __init__(self, client: PostgresClient, *, environment: c.Environment,
                 read_only: bool = False):
        if not isinstance(client, PostgresClient):
            raise ContractError("postgres_client_required")
        c.require_enum(environment, c.Environment)
        if type(read_only) is not bool:
            raise ContractError("invalid_read_only_mode")
        if environment in {c.Environment.CANARY, c.Environment.PRODUCTION} and not client.production:
            raise ContractError("agent_world_postgres_tls_required")
        self.client, self.environment, self.read_only = client, environment, read_only
        self.events = _PostgresEvents(self)

    def _context(self, context):
        if not isinstance(context, c.RequestContext):
            raise ContractError("context_required")
        if context.scope.environment is not self.environment:
            raise ContractError("scope_mismatch")
        return context.scope.environment.value, context.scope.workspace_id

    @staticmethod
    def _identity(kind, entity_id):
        c.require_enum(kind, EntityKind)
        c.require_uuid(entity_id)
        return kind.value, entity_id

    @contextmanager
    def _transaction(self, context, *, write=False):
        scope = self._context(context)
        if write and self.read_only:
            raise ContractError("agent_world_repository_read_only")
        # Same-tenant writes serialize CAS, role assignment and publication
        # invalidation. These transaction locks are not durable worker leases.
        lock = int.from_bytes(hashlib.sha256(_canonical(["sf-aw-v1", *scope])).digest()[:8],
                              "big", signed=True)
        try:
            with self.client.transaction(Scope.workspace_scope(scope[1]), read_only=not write) as conn:
                role = conn.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
                tables = conn.execute("""SELECT c.relrowsecurity,c.relforcerowsecurity,
                    pg_has_role(current_user,c.relowner,'USAGE') AS owned
                    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='public' AND c.relname=ANY(%s) AND c.relkind='r'""", (list(_TABLES),)).fetchall()
                if not role or role["rolsuper"] or role["rolbypassrls"] or any(r["owned"] for r in tables):
                    raise ContractError("agent_world_postgres_unsafe_role")
                if len(tables) != len(_TABLES) or not all(r["relrowsecurity"] and r["relforcerowsecurity"] for r in tables):
                    raise ContractError("agent_world_storage_schema_unsupported")
                conn.execute("SELECT set_config('stratforge.aw_environment',%s,true)", (scope[0],))
                conn.execute("SELECT set_config('stratforge.aw_user_uuid',%s,true)", (str(context.user_uuid),))
                conn.execute("SELECT set_config('stratforge.aw_memory_read_id','',true)")
                conn.execute("SELECT pg_advisory_xact_lock(%s)" if write else
                             "SELECT pg_advisory_xact_lock_shared(%s)", (lock,))
                if write:
                    conn.execute("""INSERT INTO sf_aw_meta(environment,workspace_id,cursor_key)
                        VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""", (*scope, secrets.token_bytes(32)))
                yield conn
        except (StorageConstraintError, StorageConflictError) as exc:
            constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "")
            code = "idempotency_conflict" if constraint == "sf_aw_mutations_pkey" else "agent_world_storage_conflict"
            raise ContractError(code) from exc
        except StorageReadOnlyError as exc:
            raise ContractError("agent_world_repository_read_only") from exc
        except StorageError as exc:
            raise ContractError("agent_world_storage_unavailable") from exc
        except Exception as exc:
            # The shared client intentionally maps a small set of common PG
            # failures. Also sanitize missing-schema/lock/database errors here,
            # without masking a contract error or an unrelated programming bug.
            from app.production_storage.core import _psycopg
            if isinstance(exc, _psycopg().Error):
                code = ("agent_world_storage_schema_unsupported" if exc.sqlstate in {"42P01", "42703", "42883"}
                        else "agent_world_storage_unavailable")
                raise ContractError(code) from exc
            raise

    def _row(self, conn, context, kind, entity_id, *, revision=None):
        identity = (*self._context(context), *self._identity(kind, entity_id))
        if revision is None:
            row = conn.execute("""SELECT v.* FROM sf_aw_records r JOIN sf_aw_revisions v ON v.seq=r.seq
                WHERE r.environment=%s AND r.workspace_id=%s AND r.kind=%s AND r.entity_id=%s""", identity).fetchone()
        else:
            row = conn.execute("""SELECT v.* FROM sf_aw_revisions v JOIN sf_aw_records r
                ON (r.environment,r.workspace_id,r.kind,r.entity_id)=(v.environment,v.workspace_id,v.kind,v.entity_id)
                WHERE v.environment=%s AND v.workspace_id=%s AND v.kind=%s AND v.entity_id=%s AND v.revision=%s""",
                               (*identity, revision)).fetchone()
        if row is None:
            return None
        record = decode_record(row["payload"])
        c.validate_record_scope(context, record)
        if (record.KIND != kind or record.header.entity_id != entity_id
                or record.header.revision != row["revision"]
                or record.header.owner_user_uuid != row["owner_uuid"] or _visibility(record) != row["visibility"]):
            raise ContractError("stored_contract_invalid")
        return record

    def get(self, *, context, kind, entity_id):
        self._identity(kind, entity_id)
        with self._transaction(context) as conn:
            return self._row(conn, context, kind, entity_id)

    def get_revision(self, *, context, kind, entity_id, revision):
        self._identity(kind, entity_id)
        c.require_revision(revision)
        with self._transaction(context) as conn:
            record = self._row(conn, context, kind, entity_id, revision=revision)
            return record if record and record.header.owner_user_uuid == context.user_uuid else None

    def _replayed(self, conn, context, row):
        record, event = decode_record(row["record_payload"]), decode_event(row["event_payload"])
        if self._row(conn, context, record.KIND, record.header.entity_id, revision=record.header.revision) is None:
            raise ContractError("record_unavailable")
        self._verify_references(conn, context, record)
        self._verify_references(conn, context, event)
        return CommitResult(record=record, event=event, replayed=True)

    def lookup_mutation(self, *, context, operation, idempotency_key):
        scope = self._context(context)
        c.require_token(operation, limit=100)
        if (not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160
                or any(ord(char) < 33 or ord(char) > 126 for char in idempotency_key)):
            raise ContractError("invalid_idempotency_key")
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        with self._transaction(context) as conn:
            row = conn.execute(_REPLAY, (*scope, operation, key_hash)).fetchone()
            return self._replayed(conn, context, row) if row else None

    def _cursor_key(self, conn, context):
        row = conn.execute("SELECT schema_version,cursor_key FROM sf_aw_meta WHERE environment=%s AND workspace_id=%s",
                           self._context(context)).fetchone()
        if row is None:
            return None
        if row["schema_version"] != 1 or len(row["cursor_key"]) != 32:
            raise ContractError("agent_world_storage_identity_mismatch")
        return bytes(row["cursor_key"])

    def _cursor(self, conn, *, context, filter_key, snapshot, after):
        value = [1, *self._context(context), str(context.user_uuid), filter_key, snapshot, after]
        body = base64.urlsafe_b64encode(_canonical(value)).decode("ascii").rstrip("=")
        key = self._cursor_key(conn, context)
        if key is None:
            raise ContractError("agent_world_storage_identity_mismatch")
        return "c1." + body + "." + hmac.new(key, body.encode("ascii"), hashlib.sha256).hexdigest()

    def _page_start(self, conn, *, context, filter_key, page, table):
        if not isinstance(page, PageRequest):
            raise ContractError("page_required")
        if table not in {"sf_aw_events", "sf_aw_revisions"}:
            raise ContractError("invalid_page_table")
        if table == "sf_aw_revisions":
            # A private-visibility change must revoke the row, not invalidate a
            # previously issued public page. The atomic tenant watermark does
            # not fall when RLS makes the latest revision invisible to a reader.
            meta = conn.execute("SELECT revision_watermark FROM sf_aw_meta WHERE environment=%s AND workspace_id=%s",
                                self._context(context)).fetchone()
            maximum = meta["revision_watermark"] if meta else 0
        else:
            maximum = conn.execute("SELECT COALESCE(MAX(seq),0) AS maximum FROM sf_aw_events WHERE environment=%s AND workspace_id=%s",
                                   self._context(context)).fetchone()["maximum"]
        if page.cursor is None:
            return maximum, (0 if table == "sf_aw_events" else str(UUID(int=0)))
        try:
            prefix, body, signature = page.cursor.split(".")
            key = self._cursor_key(conn, context)
            if key is None or prefix != "c1" or not hmac.compare_digest(
                    hmac.new(key, body.encode("ascii"), hashlib.sha256).hexdigest(), signature):
                raise ValueError()
            value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            binding = [1, *self._context(context), str(context.user_uuid), filter_key]
            if type(value) is not list or len(value) != 7 or value[:5] != binding:
                raise ValueError()
            snapshot, after = value[5:]
            if type(snapshot) is not int or snapshot < 0:
                raise ValueError()
            if table == "sf_aw_events":
                if type(after) is not int or not 0 <= after <= snapshot:
                    raise ValueError()
            elif type(after) is not str or str(UUID(after)) != after:
                raise ValueError()
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ContractError("invalid_cursor") from exc
        if snapshot > maximum:
            raise ContractError("cursor_gap")
        return snapshot, after

    def list(self, *, context, kind, page):
        scope = self._context(context)
        c.require_enum(kind, EntityKind)
        with self._transaction(context) as conn:
            snapshot, after = self._page_start(conn, context=context, filter_key=kind.value,
                                                page=page, table="sf_aw_revisions")
            rows = conn.execute("""SELECT v.* FROM sf_aw_revisions v JOIN sf_aw_records r
                ON (r.environment,r.workspace_id,r.kind,r.entity_id)=(v.environment,v.workspace_id,v.kind,v.entity_id)
                WHERE v.environment=%s AND v.workspace_id=%s AND v.kind=%s AND v.entity_id>%s AND v.seq<=%s
                  AND v.seq=(SELECT MAX(x.seq) FROM sf_aw_revisions x WHERE
                    (x.environment,x.workspace_id,x.kind,x.entity_id)=(v.environment,v.workspace_id,v.kind,v.entity_id)
                    AND x.seq<=%s) ORDER BY v.entity_id LIMIT %s""",
                                (*scope, kind.value, UUID(after), snapshot, snapshot, page.limit + 1)).fetchall()
            records = tuple(decode_record(row["payload"]) for row in rows[:page.limit])
            for record in records:
                c.validate_record_scope(context, record)
            cursor = (self._cursor(conn, context=context, filter_key=kind.value, snapshot=snapshot,
                                   after=str(records[-1].header.entity_id)) if len(rows) > page.limit else None)
            return Page(items=records, next_cursor=cursor)

    @staticmethod
    def _verified_bytes(row, reference):
        if row is None:
            return None
        content = bytes(row["content"])
        if row["sha256"] != reference.sha256 or hashlib.sha256(content).hexdigest() != reference.sha256:
            raise ContractError("artifact_integrity_mismatch")
        _validate_artifact(content, row["media_type"])
        return content, row["media_type"]

    def _artifact(self, conn, context, reference):
        if not isinstance(reference, c.SnapshotRef):
            raise ContractError("snapshot_required")
        c.require_same_scope(context.scope, reference.scope)
        row = conn.execute("""SELECT content,media_type,sha256 FROM sf_aw_artifacts WHERE environment=%s
            AND workspace_id=%s AND owner_uuid=%s AND artifact_id=%s""",
                           (*self._context(context), context.user_uuid, reference.artifact_id)).fetchone()
        return self._verified_bytes(row, reference)

    def put_artifact(self, *, context, content, media_type):
        scope = self._context(context)
        _validate_artifact(content, media_type)
        digest = hashlib.sha256(content).hexdigest()
        identity = uuid5(_ARTIFACT_NAMESPACE, ":".join((*scope, str(context.user_uuid), media_type, digest)))
        reference = c.SnapshotRef(artifact_id=identity, sha256=digest, scope=context.scope)
        with self._transaction(context, write=True) as conn:
            conn.execute("""INSERT INTO sf_aw_artifacts
                (environment,workspace_id,owner_uuid,artifact_id,sha256,media_type,content)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                         (*scope, context.user_uuid, identity, digest, media_type, content))
            if self._artifact(conn, context, reference) != (content, media_type):
                raise ContractError("artifact_integrity_mismatch")
        return reference

    def get_artifact(self, *, context, reference):
        with self._transaction(context) as conn:
            return self._artifact(conn, context, reference)

    def get_artifact_by_id(self, *, context, artifact_id):
        scope = self._context(context)
        c.require_uuid(artifact_id)
        with self._transaction(context) as conn:
            row = conn.execute("""SELECT sha256 FROM sf_aw_artifacts WHERE environment=%s
                AND workspace_id=%s AND owner_uuid=%s AND artifact_id=%s""",
                               (*scope, context.user_uuid, artifact_id)).fetchone()
            if row is None:
                return None
            reference = c.SnapshotRef(artifact_id=artifact_id, sha256=row["sha256"], scope=context.scope)
            content, media_type = self._artifact(conn, context, reference)
            return reference, content, media_type

    def _publication(self, conn, context, memory):
        """Derive, never accept, a grant from exact currently owned revisions."""
        stamp = conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        if (not isinstance(memory, c.Memory) or memory.header.owner_user_uuid != context.user_uuid
                or memory.status != "active" or memory.visibility != c.Visibility.WORKSPACE
                or memory.memory_class != c.MemoryClass.WORKSPACE or memory.retention_until <= stamp
                or memory.verification is None):
            return None
        proof = self._artifact(conn, context, memory.verification)
        if proof is None or proof[1] != "application/json":
            return None
        publication = json.loads(proof[0])
        if (not isinstance(publication, dict) or publication.get("type") != "workspace_memory_publication"
                or publication.get("memory_id") != str(memory.header.entity_id)
                or publication.get("owner_user_uuid") != str(context.user_uuid)
                or publication.get("content_sha256") != memory.content.sha256):
            return None
        try:
            source_id = UUID(publication.get("source_memory_id", ""))
        except (ValueError, TypeError, AttributeError):
            return None
        original = self._row(conn, context, EntityKind.MEMORY, source_id)
        if (not isinstance(original, c.Memory) or original.header.owner_user_uuid != context.user_uuid
                or original.status != "active" or original.retention_until <= stamp
                or original.content != memory.content or type(publication.get("source_revision")) is not int
                or original.header.revision != publication["source_revision"]):
            return None
        anchors = [memory.ref(), original.ref()]
        if original.memory_class == c.MemoryClass.VERIFIED_LESSON:
            content = self._artifact(conn, context, memory.content)
            if content is None or content[1] != "application/json":
                return None
            origin = json.loads(content[0])
            try:
                outcome_id = UUID(origin.get("verified_outcome_id", "")) if isinstance(origin, dict) else None
            except (ValueError, TypeError, AttributeError):
                return None
            if outcome_id is None:
                return None
            outcome = self._row(conn, context, EntityKind.OUTCOME, outcome_id)
            if (not isinstance(outcome, c.Outcome) or outcome.header.owner_user_uuid != context.user_uuid
                    or outcome.status != "verified" or outcome.verification != original.verification):
                return None
            anchors.append(outcome.ref())
        return min(memory.retention_until, original.retention_until), tuple(anchors)

    def _refresh_grants(self, conn, context, record):
        scope = self._context(context)
        rows = conn.execute("""SELECT memory_id FROM sf_aw_memory_grant_anchors WHERE environment=%s
            AND workspace_id=%s AND kind=%s AND entity_id=%s""",
                            (*scope, record.KIND.value, record.header.entity_id)).fetchall()
        ids = {row["memory_id"] for row in rows}
        if isinstance(record, c.Memory):
            ids.add(record.header.entity_id)
        for memory_id in ids:
            memory = self._row(conn, context, EntityKind.MEMORY, memory_id)
            derived = self._publication(conn, context, memory)
            if derived is None:
                # Preserve source anchors for future legitimate revalidation.
                conn.execute("""UPDATE sf_aw_memory_grants SET valid=FALSE WHERE environment=%s
                    AND workspace_id=%s AND memory_id=%s""", (*scope, memory_id))
                continue
            retention, anchors = derived
            conn.execute("""INSERT INTO sf_aw_memory_grants(environment,workspace_id,owner_uuid,memory_id,
                memory_revision,content_id,content_sha256,proof_id,proof_sha256,retention_until,valid)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                ON CONFLICT(environment,workspace_id,memory_id) DO UPDATE SET
                memory_revision=EXCLUDED.memory_revision,content_id=EXCLUDED.content_id,
                content_sha256=EXCLUDED.content_sha256,proof_id=EXCLUDED.proof_id,
                proof_sha256=EXCLUDED.proof_sha256,retention_until=EXCLUDED.retention_until,valid=TRUE""",
                         (*scope, context.user_uuid, memory_id, memory.header.revision,
                          memory.content.artifact_id, memory.content.sha256,
                          memory.verification.artifact_id, memory.verification.sha256, retention))
            conn.execute("DELETE FROM sf_aw_memory_grant_anchors WHERE environment=%s AND workspace_id=%s AND memory_id=%s",
                         (*scope, memory_id))
            for anchor in set(anchors):
                conn.execute("""INSERT INTO sf_aw_memory_grant_anchors
                    (environment,workspace_id,owner_uuid,memory_id,kind,entity_id,revision)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                             (*scope, context.user_uuid, memory_id, anchor.kind.value, anchor.entity_id, anchor.revision))

    def read_memory_artifact(self, *, context, memory_id, artifact_id, now=None):
        """Explicit published-content reader. Private APIs never enable grants.

        The RLS-visible derived grant is bound to source revisions/TTL; source
        changes invalidate it atomically. No publisher impersonation, maintenance
        write, SECURITY DEFINER function, or global database scope is used here.
        """
        scope = self._context(context)
        c.require_uuid(memory_id)
        c.require_uuid(artifact_id)
        stamp = now or datetime.now(timezone.utc)
        c.require_utc(stamp)
        with self._transaction(context) as conn:
            memory = self._row(conn, context, EntityKind.MEMORY, memory_id)
            if (not isinstance(memory, c.Memory) or memory.status != "active"
                    or memory.visibility != c.Visibility.WORKSPACE or memory.memory_class != c.MemoryClass.WORKSPACE
                    or memory.retention_until <= stamp or not memory.verification
                    or artifact_id not in {memory.content.artifact_id, memory.verification.artifact_id}):
                return None
            conn.execute("SELECT set_config('stratforge.aw_memory_read_id',%s,true)", (str(memory_id),))
            grant = conn.execute("""SELECT * FROM sf_aw_memory_grants WHERE environment=%s
                AND workspace_id=%s AND memory_id=%s AND valid AND retention_until>%s
                AND retention_until>clock_timestamp()""", (*scope, memory_id, stamp)).fetchone()
            if (grant is None or grant["memory_revision"] != memory.header.revision
                    or grant["owner_uuid"] != memory.header.owner_user_uuid
                    or (grant["content_id"], grant["content_sha256"]) != (memory.content.artifact_id, memory.content.sha256)
                    or (grant["proof_id"], grant["proof_sha256"]) != (memory.verification.artifact_id, memory.verification.sha256)):
                return None
            reference = memory.content if artifact_id == memory.content.artifact_id else memory.verification
            row = conn.execute("""SELECT content,media_type,sha256 FROM sf_aw_artifacts WHERE environment=%s
                AND workspace_id=%s AND owner_uuid=%s AND artifact_id=%s""",
                               (*scope, memory.header.owner_user_uuid, artifact_id)).fetchone()
            value = self._verified_bytes(row, reference)
            return (reference, *value) if value else None

    def _verify_references(self, conn, context, value, *, pending=None):
        for reference in _references(value):
            if isinstance(reference, c.SnapshotRef):
                if self._artifact(conn, context, reference) is None:
                    raise ContractError("artifact_reference_unavailable")
            elif pending is None or reference != pending.ref():
                if self._row(conn, context, reference.kind, reference.entity_id, revision=reference.revision) is None:
                    raise ContractError("entity_reference_unavailable")

    def _verify_persona_assignment(self, conn, context, record):
        if not isinstance(record, c.Persona):
            return
        from .application_roles import role_key
        from .persona_identity import validate_assignment
        def profile(persona):
            artifact = self._artifact(conn, context, persona.profile)
            value = json.loads(artifact[0]) if artifact and artifact[1] == "application/json" else {}
            return value if isinstance(value, dict) else {}
        current = profile(record)
        role = role_key(current.get("application_role", ""))
        if record.status not in {"active", "suspended"}:
            validate_assignment(record, current, [])
            return
        rows = conn.execute("""SELECT v.payload FROM sf_aw_records r JOIN sf_aw_revisions v ON v.seq=r.seq
            WHERE r.environment=%s AND r.workspace_id=%s AND r.owner_uuid=%s
              AND r.kind='persona' AND r.entity_id!=%s""",
                            (*self._context(context), context.user_uuid, record.header.entity_id)).fetchall()
        peers = [(other, profile(other)) for row in rows for other in (decode_record(row["payload"]),)]
        previous = self._row(conn, context, EntityKind.PERSONA, record.header.entity_id)
        validate_assignment(record, current, peers, previous=(previous, profile(previous)) if previous else None)
        for other, other_profile in peers:
            if role and other.status in {"active", "suspended"} and role_key(other_profile.get("application_role", "")) == role:
                raise ContractError("application_role_already_assigned")

    def commit(self, *, context, record, expected_revision, event, mutation):
        scope = self._context(context)
        c.validate_record_scope(context, record)
        c.require_revision(expected_revision, zero=True)
        if not isinstance(event, EventEnvelope) or not isinstance(mutation, MutationIdentity):
            raise ContractError("event_and_mutation_required")
        c.require_same_scope(context.scope, event.scope)
        c.require_same_scope(context.scope, mutation.scope)
        if mutation.request_hash != request_digest(context=context, record=record, expected_revision=expected_revision, event=event):
            raise ContractError("mutation_payload_mismatch")
        with self._transaction(context, write=True) as conn:
            replay = conn.execute(_REPLAY, mutation.storage_key).fetchone()
            if replay is not None:
                if replay["request_hash"] != mutation.request_hash or replay["user_uuid"] != context.user_uuid:
                    raise ContractError("idempotency_conflict")
                return self._replayed(conn, context, replay)
            previous = self._row(conn, context, record.KIND, record.header.entity_id)
            if previous and previous.header.owner_user_uuid != context.user_uuid:
                raise ContractError("record_write_denied")
            validate_commit(context=context, record=record, expected_revision=expected_revision,
                            event=event, mutation=mutation, previous=previous)
            self._verify_references(conn, context, record)
            self._verify_references(conn, context, event, pending=record)
            self._verify_persona_assignment(conn, context, record)
            identity = (*scope, record.KIND.value, record.header.entity_id)
            row = conn.execute("""INSERT INTO sf_aw_revisions
                (environment,workspace_id,kind,entity_id,revision,owner_uuid,visibility,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING seq""",
                               (*identity, record.header.revision, record.header.owner_user_uuid,
                                _visibility(record), encode_record(record))).fetchone()
            conn.execute("UPDATE sf_aw_meta SET revision_watermark=%s WHERE environment=%s AND workspace_id=%s",
                         (row["seq"], *scope))
            if previous is None:
                conn.execute("""INSERT INTO sf_aw_records
                    (environment,workspace_id,kind,entity_id,revision,seq,owner_uuid,visibility)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                             (*identity, record.header.revision, row["seq"], record.header.owner_user_uuid, _visibility(record)))
            else:
                changed = conn.execute("""UPDATE sf_aw_records SET revision=%s,seq=%s,visibility=%s
                    WHERE environment=%s AND workspace_id=%s AND kind=%s AND entity_id=%s AND revision=%s""",
                                       (record.header.revision, row["seq"], _visibility(record), *identity, expected_revision)).rowcount
                if changed != 1:
                    raise ContractError("revision_conflict")
            conn.execute("""INSERT INTO sf_aw_events(event_id,environment,workspace_id,user_uuid,kind,entity_id,revision,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                         (event.event_id, *scope, context.user_uuid, record.KIND.value,
                          record.header.entity_id, record.header.revision, encode_event(event)))
            conn.execute("INSERT INTO sf_aw_outbox(environment,workspace_id,user_uuid,event_id) VALUES(%s,%s,%s,%s)",
                         (*scope, context.user_uuid, event.event_id))
            conn.execute("""INSERT INTO sf_aw_mutations
                (environment,workspace_id,operation,key_hash,request_hash,user_uuid,kind,entity_id,revision,event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                         (*mutation.storage_key, mutation.request_hash, context.user_uuid, record.KIND.value,
                          record.header.entity_id, record.header.revision, event.event_id))
            self._refresh_grants(conn, context, record)
            return CommitResult(record=record, event=event, replayed=False)


class _PostgresEvents:
    def __init__(self, repository):
        self._repository = repository

    def _visible(self, conn, context, row):
        event = decode_event(row["payload"])
        c.require_same_scope(context.scope, event.scope)
        reference = event.subject
        if self._repository._row(conn, context, reference.kind, reference.entity_id, revision=reference.revision) is None:
            return None
        self._repository._verify_references(conn, context, event)
        return event

    def list(self, *, context, page):
        repo = self._repository
        scope = repo._context(context)
        with repo._transaction(context) as conn:
            snapshot, after = repo._page_start(conn, context=context, filter_key="events", page=page, table="sf_aw_events")
            rows = conn.execute("""SELECT e.* FROM sf_aw_events e JOIN sf_aw_records r
                ON (r.environment,r.workspace_id,r.kind,r.entity_id)=(e.environment,e.workspace_id,e.kind,e.entity_id)
                JOIN sf_aw_revisions v ON (v.environment,v.workspace_id,v.kind,v.entity_id,v.revision)=
                  (e.environment,e.workspace_id,e.kind,e.entity_id,e.revision)
                WHERE e.environment=%s AND e.workspace_id=%s AND e.user_uuid=%s AND e.seq>%s AND e.seq<=%s
                ORDER BY e.seq LIMIT %s""", (*scope, context.user_uuid, after, snapshot, page.limit + 1)).fetchall()
            events = tuple(self._visible(conn, context, row) for row in rows[:page.limit])
            cursor = (repo._cursor(conn, context=context, filter_key="events", snapshot=snapshot,
                                   after=rows[page.limit - 1]["seq"]) if len(rows) > page.limit else None)
            return Page(items=events, next_cursor=cursor)

    def _event(self, conn, context, event_id):
        row = conn.execute("""SELECT * FROM sf_aw_events WHERE environment=%s AND workspace_id=%s
            AND user_uuid=%s AND event_id=%s""", (*self._repository._context(context), context.user_uuid, event_id)).fetchone()
        return self._visible(conn, context, row) if row else None

    def is_acknowledged(self, *, context, consumer, event_id):
        repo = self._repository
        scope = repo._context(context)
        c.require_token(consumer, limit=100)
        c.require_uuid(event_id)
        with repo._transaction(context) as conn:
            if self._event(conn, context, event_id) is None:
                return False
            return conn.execute("""SELECT 1 FROM sf_aw_inbox WHERE environment=%s AND workspace_id=%s
                AND consumer=%s AND event_id=%s""", (*scope, consumer, event_id)).fetchone() is not None

    def acknowledge(self, *, context, consumer, event_id):
        repo = self._repository
        scope = repo._context(context)
        c.require_token(consumer, limit=100)
        c.require_uuid(event_id)
        with repo._transaction(context, write=True) as conn:
            if self._event(conn, context, event_id) is None:
                return False
            return conn.execute("""INSERT INTO sf_aw_inbox(environment,workspace_id,user_uuid,consumer,event_id)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                                (*scope, context.user_uuid, consumer, event_id)).rowcount == 1
