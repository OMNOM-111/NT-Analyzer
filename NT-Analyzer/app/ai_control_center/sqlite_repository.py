"""Development-only Agent World persistence, never a Production fallback.

The caller supplies an isolated local path and authenticated context after the
existing capability/feature gates. This store grants no permissions, executes
no jobs and reserves no budgets. One transaction commits the current record,
immutable revision, event, outbox and replay result. No polling worker starts.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5
from xml.etree import ElementTree

from . import contracts as c
from .events import EventEnvelope, MutationIdentity, request_digest
from .repositories import CommitResult, Page, PageRequest, validate_commit
from .states import ContractError, EntityKind
from .storage_codec import decode_event, decode_record, encode_event, encode_record


_APPLICATION_ID = 0x53464157
_SCHEMA_VERSION = 1
_ARTIFACT_NAMESPACE = UUID("c8f1988c-3444-4da3-9c0c-034b5fe4c4bf")
MAX_ARTIFACT_BYTES = 256 * 1024
_MEDIA_TYPES = frozenset({"application/json", "image/svg+xml", "image/png"})
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS aw_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS aw_revisions (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, environment TEXT NOT NULL,
        workspace_id TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision > 0), owner_uuid TEXT NOT NULL,
        visibility TEXT NOT NULL, payload TEXT NOT NULL,
        UNIQUE(environment, workspace_id, kind, entity_id, revision))""",
    """CREATE TABLE IF NOT EXISTS aw_records (
        environment TEXT NOT NULL, workspace_id TEXT NOT NULL, kind TEXT NOT NULL,
        entity_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision > 0),
        seq INTEGER NOT NULL REFERENCES aw_revisions(seq), owner_uuid TEXT NOT NULL,
        visibility TEXT NOT NULL, PRIMARY KEY(environment, workspace_id, kind, entity_id))""",
    """CREATE TABLE IF NOT EXISTS aw_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
        environment TEXT NOT NULL, workspace_id TEXT NOT NULL, user_uuid TEXT NOT NULL,
        kind TEXT NOT NULL, entity_id TEXT NOT NULL, revision INTEGER NOT NULL,
        payload TEXT NOT NULL,
        FOREIGN KEY(environment, workspace_id, kind, entity_id, revision)
          REFERENCES aw_revisions(environment, workspace_id, kind, entity_id, revision))""",
    """CREATE TABLE IF NOT EXISTS aw_outbox (
        event_id TEXT PRIMARY KEY REFERENCES aw_events(event_id))""",
    """CREATE TABLE IF NOT EXISTS aw_mutations (
        environment TEXT NOT NULL, workspace_id TEXT NOT NULL, operation TEXT NOT NULL,
        key_hash TEXT NOT NULL, request_hash TEXT NOT NULL, user_uuid TEXT NOT NULL,
        revision_seq INTEGER NOT NULL REFERENCES aw_revisions(seq),
        event_id TEXT NOT NULL REFERENCES aw_events(event_id),
        PRIMARY KEY(environment, workspace_id, operation, key_hash))""",
    """CREATE TABLE IF NOT EXISTS aw_inbox (
        environment TEXT NOT NULL, workspace_id TEXT NOT NULL, consumer TEXT NOT NULL,
        event_id TEXT NOT NULL REFERENCES aw_events(event_id),
        PRIMARY KEY(environment, workspace_id, consumer, event_id))""",
    """CREATE TABLE IF NOT EXISTS aw_artifacts (
        environment TEXT NOT NULL, workspace_id TEXT NOT NULL, owner_uuid TEXT NOT NULL,
        artifact_id TEXT NOT NULL, sha256 TEXT NOT NULL, media_type TEXT NOT NULL,
        content BLOB NOT NULL, PRIMARY KEY(environment, workspace_id, artifact_id))""",
    "CREATE INDEX IF NOT EXISTS aw_revision_scope ON aw_revisions(environment,workspace_id,kind,entity_id,seq)",
    "CREATE INDEX IF NOT EXISTS aw_event_scope ON aw_events(environment,workspace_id,user_uuid,seq)",
)


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _references(value):
    if isinstance(value, (c.EntityRef, c.SnapshotRef)):
        yield value
    elif isinstance(value, tuple):
        for item in value:
            yield from _references(item)
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from _references(getattr(value, field.name))


def _visibility(record: c.Record) -> str:
    return record.visibility.value if isinstance(record, c.Memory) else "workspace"


def _validate_artifact(content: bytes, media_type: str) -> None:
    if type(content) is not bytes or not 1 <= len(content) <= MAX_ARTIFACT_BYTES:
        raise ContractError("invalid_artifact_size")
    if type(media_type) is not str or media_type not in _MEDIA_TYPES:
        raise ContractError("unsupported_artifact_media_type")
    try:
        if media_type == "application/json":
            def finite_float(value):
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError()
                return number

            json.loads(content, parse_float=finite_float,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        elif media_type == "image/png":
            if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError()
        else:
            # Only inert drawing elements are accepted, including direct URL
            # reads. Serving code must still use an image context and strict CSP.
            if b"<!" in content or b"<?" in content:
                raise ValueError()
            tree = ElementTree.fromstring(content)
            allowed = {"svg", "g", "path", "rect", "line", "polyline", "polygon",
                       "circle", "ellipse", "text", "tspan", "title", "desc", "defs",
                       "linearGradient", "radialGradient", "stop", "clipPath"}
            attributes = {"id", "class", "role", "aria-label", "aria-labelledby", "x", "y", "x1", "y1", "x2", "y2",
                          "width", "height", "rx", "ry", "cx", "cy", "r", "d", "points", "fill", "fill-opacity",
                          "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-linecap", "stroke-linejoin",
                          "stroke-dasharray", "stroke-dashoffset", "opacity", "viewbox", "preserveaspectratio", "transform",
                          "font-family", "font-size", "font-weight", "text-anchor", "dominant-baseline", "dy", "dx",
                          "gradientunits", "gradienttransform", "offset", "stop-color", "stop-opacity", "clippathunits",
                          "clip-path", "version", "letter-spacing", "textlength", "lengthadjust"}
            if tree.tag.split("}")[-1] != "svg":
                raise ValueError()
            for element in tree.iter():
                if element.tag.split("}")[-1] not in allowed:
                    raise ValueError()
                for name, value in element.attrib.items():
                    local = name.split("}")[-1].lower()
                    normalized = "".join(value.lower().split())
                    if (local not in attributes or "}" in name or "\\" in value
                            or ("url(" in normalized and not re.fullmatch(r"url\(#[a-z0-9_.:-]+\)", normalized))
                            or "javascript:" in normalized or "data:" in normalized):
                        raise ValueError()
    except (ValueError, TypeError, UnicodeError, RecursionError, ElementTree.ParseError) as exc:
        raise ContractError("invalid_artifact_content") from exc


class SQLiteAgentWorldRepository:
    """Explicit path, one connection per operation, bounded signed pagination.

    Records can be workspace-visible after caller admission; private Memory,
    artifacts and each user's event stream remain owner-isolated. Revisions and
    events are append-only. There is no retention deletion or outbox dispatcher
    in this checkpoint. Future PostgreSQL support needs its own tested adapter.
    """

    def __init__(self, path: str | Path, *, environment: c.Environment = c.Environment.DEVELOPMENT,
                 read_only: bool = False):
        if environment is not c.Environment.DEVELOPMENT:
            raise ContractError("agent_world_sqlite_development_only")
        if not isinstance(path, (str, Path)) or str(path) in {"", ":memory:"}:
            raise ContractError("durable_path_required")
        if type(read_only) is not bool:
            raise ContractError("invalid_read_only_mode")
        self.path = Path(path).resolve()
        self.environment = environment
        self.read_only = read_only
        self._empty_read_only = read_only and not self.path.exists()
        if read_only:
            if not self._empty_read_only:
                self._validate_read_only()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()
        self.events = _SQLiteEvents(self)

    def _connect(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro" if self.read_only else str(self.path),
                                     timeout=10, isolation_level=None, uri=self.read_only)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA query_only=ON" if self.read_only else "PRAGMA synchronous=FULL")
        return connection

    def _validate_read_only(self):
        """Validate without migration, journal mode or persisted metadata writes.

        SQLite may materialize operational -wal/-shm sidecars even in mode=ro.
        We retain ordinary locking and current WAL visibility, not immutable=1
        (which would silently ignore committed WAL records) or exclusive locks.
        """
        with self._transaction() as connection:
            if connection.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID:
                raise ContractError("agent_world_storage_identity_mismatch")
            if connection.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION:
                raise ContractError("agent_world_storage_schema_unsupported")
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"aw_meta", "aw_records", "aw_revisions", "aw_events", "aw_outbox", "aw_mutations", "aw_inbox", "aw_artifacts"} <= tables:
                raise ContractError("agent_world_storage_schema_unsupported")
            row = connection.execute("SELECT value FROM aw_meta WHERE key='cursor_key'").fetchone()
            key = row[0] if row else None
            if not isinstance(key, str) or not re.fullmatch("[0-9a-f]{64}", key):
                raise ContractError("agent_world_storage_identity_mismatch")
            self._cursor_key = bytes.fromhex(key)

    @staticmethod
    def _empty_page(page):
        if not isinstance(page, PageRequest):
            raise ContractError("page_required")
        if page.cursor is not None:
            raise ContractError("invalid_cursor")
        return Page(items=(), next_cursor=None)

    def _initialize(self):
        connection = self._connect()
        try:
            app_id = connection.execute("PRAGMA application_id").fetchone()[0]
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            if app_id not in (0, _APPLICATION_ID) or (app_id == 0 and tables):
                raise ContractError("agent_world_storage_identity_mismatch")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, _SCHEMA_VERSION):
                raise ContractError("agent_world_storage_schema_unsupported")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA:
                connection.execute(statement)
            connection.execute("INSERT OR IGNORE INTO aw_meta(key,value) VALUES ('cursor_key',?)", (secrets.token_hex(32),))
            connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            key = connection.execute("SELECT value FROM aw_meta WHERE key='cursor_key'").fetchone()[0]
            if type(key) is not str or len(key) != 64:
                raise ContractError("agent_world_storage_identity_mismatch")
            self._cursor_key = bytes.fromhex(key)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _transaction(self, *, write=False):
        if self.read_only and write:
            raise ContractError("agent_world_repository_read_only")
        if self._empty_read_only:
            raise ContractError("agent_world_storage_unavailable")
        connection = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ContractError("agent_world_storage_conflict") from exc
        except sqlite3.Error as exc:
            raise ContractError("agent_world_storage_unavailable") from exc
        finally:
            if connection is not None:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()

    def _context(self, context):
        if not isinstance(context, c.RequestContext):
            raise ContractError("context_required")
        if context.scope.environment is not self.environment:
            raise ContractError("scope_mismatch")
        return (context.scope.environment.value, context.scope.workspace_id)

    @staticmethod
    def _identity(kind, entity_id):
        c.require_enum(kind, EntityKind)
        c.require_uuid(entity_id)
        return kind.value, str(entity_id)

    def _row(self, connection, context, kind, entity_id, *, revision=None):
        identity = (*self._context(context), *self._identity(kind, entity_id))
        if revision is None:
            row = connection.execute("""SELECT v.* FROM aw_records r JOIN aw_revisions v ON v.seq=r.seq
                WHERE r.environment=? AND r.workspace_id=? AND r.kind=? AND r.entity_id=?
                AND (r.visibility!='private' OR r.owner_uuid=?)""", (*identity, str(context.user_uuid))).fetchone()
        else:
            row = connection.execute("""SELECT v.* FROM aw_revisions v JOIN aw_records r
                ON r.environment=v.environment AND r.workspace_id=v.workspace_id AND r.kind=v.kind AND r.entity_id=v.entity_id
                WHERE v.environment=? AND v.workspace_id=? AND v.kind=? AND v.entity_id=? AND v.revision=?
                AND (v.visibility!='private' OR v.owner_uuid=?) AND (r.visibility!='private' OR r.owner_uuid=?)""",
                                     (*identity, revision, str(context.user_uuid), str(context.user_uuid))).fetchone()
        if row is None:
            return None
        record = decode_record(row["payload"])
        c.validate_record_scope(context, record)
        if (record.KIND != kind or record.header.entity_id != entity_id
                or record.header.revision != row["revision"]
                or str(record.header.owner_user_uuid) != row["owner_uuid"]
                or _visibility(record) != row["visibility"]):
            raise ContractError("stored_contract_invalid")
        return record

    def get(self, *, context: c.RequestContext, kind: EntityKind, entity_id: UUID) -> c.Record | None:
        self._context(context)
        self._identity(kind, entity_id)
        if self._empty_read_only:
            return None
        with self._transaction() as connection:
            return self._row(connection, context, kind, entity_id)

    def get_revision(self, *, context: c.RequestContext, kind: EntityKind,
                     entity_id: UUID, revision: int) -> c.Record | None:
        """Read an immutable revision under the current record's private ACL."""
        self._context(context)
        self._identity(kind, entity_id)
        c.require_revision(revision)
        if self._empty_read_only:
            return None
        with self._transaction() as connection:
            record = self._row(connection, context, kind, entity_id, revision=revision)
            return record if record is not None and record.header.owner_user_uuid == context.user_uuid else None

    def lookup_mutation(self, *, context: c.RequestContext, operation: str,
                        idempotency_key: str) -> CommitResult | None:
        """Read an existing atomic result, never reserve a second replay ledger.

        Application services compare their canonical semantic request digest
        before returning it. Only this exact user's committed result is visible.
        """
        scope = self._context(context)
        c.require_token(operation, limit=100)
        if (not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160
                or any(ord(char) < 33 or ord(char) > 126 for char in idempotency_key)):
            raise ContractError("invalid_idempotency_key")
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        if self._empty_read_only:
            return None
        with self._transaction() as connection:
            row = connection.execute("""SELECT v.payload AS record_payload,e.payload AS event_payload
                FROM aw_mutations m JOIN aw_revisions v ON v.seq=m.revision_seq
                JOIN aw_events e ON e.event_id=m.event_id
                WHERE m.environment=? AND m.workspace_id=? AND m.operation=? AND m.key_hash=?
                AND m.user_uuid=?""", (*scope, operation, key_hash, str(context.user_uuid))).fetchone()
            if row is None:
                return None
            record, event = decode_record(row["record_payload"]), decode_event(row["event_payload"])
            if self._row(connection, context, record.KIND, record.header.entity_id,
                         revision=record.header.revision) is None:
                raise ContractError("record_unavailable")
            self._verify_references(connection, context, record)
            self._verify_references(connection, context, event)
            return CommitResult(record=record, event=event, replayed=True)

    def _cursor(self, *, context, filter_key, snapshot, after):
        value = [1, *self._context(context), str(context.user_uuid), filter_key, snapshot, after]
        body = base64.urlsafe_b64encode(_canonical(value)).decode("ascii").rstrip("=")
        signature = hmac.new(self._cursor_key, body.encode("ascii"), hashlib.sha256).hexdigest()
        return "c1." + body + "." + signature

    def _page_start(self, connection, *, context, filter_key, page, table):
        if not isinstance(page, PageRequest):
            raise ContractError("page_required")
        maximum = connection.execute(f"SELECT COALESCE(MAX(seq),0) FROM {table}").fetchone()[0]
        if page.cursor is None:
            return maximum, (0 if table == "aw_events" else "")
        try:
            prefix, body, signature = page.cursor.split(".")
            expected = hmac.new(self._cursor_key, body.encode("ascii"), hashlib.sha256).hexdigest()
            if prefix != "c1" or not hmac.compare_digest(expected, signature):
                raise ValueError()
            value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            binding = [1, *self._context(context), str(context.user_uuid), filter_key]
            if type(value) is not list or len(value) != 7 or value[:5] != binding:
                raise ValueError()
            snapshot, after = value[5:]
            if type(snapshot) is not int or snapshot < 0:
                raise ValueError()
            if table == "aw_events":
                if type(after) is not int or not 0 <= after <= snapshot:
                    raise ValueError()
            elif type(after) is not str or str(UUID(after)) != after:
                raise ValueError()
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ContractError("invalid_cursor") from exc
        if snapshot > maximum:
            raise ContractError("cursor_gap")
        return snapshot, after

    def list(self, *, context: c.RequestContext, kind: EntityKind, page: PageRequest) -> Page[c.Record]:
        scope = self._context(context)
        c.require_enum(kind, EntityKind)
        if self._empty_read_only:
            return self._empty_page(page)
        with self._transaction() as connection:
            snapshot, after = self._page_start(connection, context=context, filter_key=kind.value,
                                                page=page, table="aw_revisions")
            rows = connection.execute("""SELECT v.* FROM aw_revisions v JOIN aw_records r
                ON r.environment=v.environment AND r.workspace_id=v.workspace_id AND r.kind=v.kind AND r.entity_id=v.entity_id
                WHERE v.environment=? AND v.workspace_id=? AND v.kind=? AND v.entity_id>? AND v.seq<=?
                AND v.seq=(SELECT MAX(x.seq) FROM aw_revisions x WHERE x.environment=v.environment
                  AND x.workspace_id=v.workspace_id AND x.kind=v.kind AND x.entity_id=v.entity_id AND x.seq<=?)
                AND (v.visibility!='private' OR v.owner_uuid=?) AND (r.visibility!='private' OR r.owner_uuid=?)
                ORDER BY v.entity_id LIMIT ?""", (*scope, kind.value, after, snapshot, snapshot,
                                                    str(context.user_uuid), str(context.user_uuid), page.limit + 1)).fetchall()
            records = tuple(decode_record(row["payload"]) for row in rows[:page.limit])
            for record in records:
                c.validate_record_scope(context, record)
            cursor = (self._cursor(context=context, filter_key=kind.value, snapshot=snapshot,
                                   after=str(records[-1].header.entity_id)) if len(rows) > page.limit else None)
            return Page(items=records, next_cursor=cursor)

    def put_artifact(self, *, context: c.RequestContext, content: bytes, media_type: str) -> c.SnapshotRef:
        scope = self._context(context)
        _validate_artifact(content, media_type)
        digest = hashlib.sha256(content).hexdigest()
        identity = uuid5(_ARTIFACT_NAMESPACE, ":".join((*scope, str(context.user_uuid), media_type, digest)))
        with self._transaction(write=True) as connection:
            connection.execute("""INSERT OR IGNORE INTO aw_artifacts
                (environment,workspace_id,owner_uuid,artifact_id,sha256,media_type,content) VALUES (?,?,?,?,?,?,?)""",
                               (*scope, str(context.user_uuid), str(identity), digest, media_type, content))
            reference = c.SnapshotRef(artifact_id=identity, sha256=digest, scope=context.scope)
            stored = self._artifact(connection, context, reference)
            if stored != (content, media_type):
                raise ContractError("artifact_integrity_mismatch")
            return reference

    def _artifact(self, connection, context, reference):
        if not isinstance(reference, c.SnapshotRef):
            raise ContractError("snapshot_required")
        c.require_same_scope(context.scope, reference.scope)
        row = connection.execute("""SELECT content,media_type,sha256 FROM aw_artifacts WHERE environment=?
            AND workspace_id=? AND owner_uuid=? AND artifact_id=?""",
                                 (*self._context(context), str(context.user_uuid), str(reference.artifact_id))).fetchone()
        if row is None:
            return None
        content = bytes(row["content"])
        if hashlib.sha256(content).hexdigest() != reference.sha256 or row["sha256"] != reference.sha256:
            raise ContractError("artifact_integrity_mismatch")
        _validate_artifact(content, row["media_type"])
        return content, row["media_type"]

    def get_artifact(self, *, context: c.RequestContext, reference: c.SnapshotRef) -> tuple[bytes, str] | None:
        self._context(context)
        if not isinstance(reference, c.SnapshotRef):
            raise ContractError("snapshot_required")
        c.require_same_scope(context.scope, reference.scope)
        if self._empty_read_only:
            return None
        with self._transaction() as connection:
            return self._artifact(connection, context, reference)

    def get_artifact_by_id(self, *, context: c.RequestContext, artifact_id: UUID) -> tuple[c.SnapshotRef, bytes, str] | None:
        """HTTP facade lookup without accepting a client-asserted content hash."""
        scope = self._context(context)
        c.require_uuid(artifact_id)
        if self._empty_read_only:
            return None
        with self._transaction() as connection:
            row = connection.execute("""SELECT sha256 FROM aw_artifacts WHERE environment=? AND workspace_id=?
                AND owner_uuid=? AND artifact_id=?""", (*scope, str(context.user_uuid), str(artifact_id))).fetchone()
            if row is None:
                return None
            reference = c.SnapshotRef(artifact_id=artifact_id, sha256=row["sha256"], scope=context.scope)
            content, media_type = self._artifact(connection, context, reference)
            return reference, content, media_type

    def read_memory_artifact(self, *, context: c.RequestContext, memory_id: UUID,
                             artifact_id: UUID, now: datetime | None = None) -> tuple[c.SnapshotRef, bytes, str] | None:
        """Read ONLY content explicitly published by an active same-tenant Memory.

        This does not impersonate the publisher and does not relax the private
        artifact APIs. Source revocation/expiry removes the grant immediately;
        no GET mutates history. The service must freshly admit workspace access.
        """
        scope = self._context(context)
        c.require_uuid(memory_id)
        c.require_uuid(artifact_id)
        stamp = now or datetime.now(timezone.utc)
        c.require_utc(stamp)
        if self._empty_read_only:
            return None
        with self._transaction() as connection:
            memory = self._row(connection, context, EntityKind.MEMORY, memory_id)
            if (not isinstance(memory, c.Memory) or memory.status != "active"
                    or memory.visibility != c.Visibility.WORKSPACE or memory.memory_class != c.MemoryClass.WORKSPACE
                    or memory.retention_until <= stamp or not memory.verification
                    or artifact_id not in {memory.content.artifact_id, memory.verification.artifact_id}):
                return None

            def bytes_for(reference):
                row = connection.execute("""SELECT content,media_type,sha256 FROM aw_artifacts
                    WHERE environment=? AND workspace_id=? AND owner_uuid=? AND artifact_id=?""",
                                         (*scope, str(memory.header.owner_user_uuid), str(reference.artifact_id))).fetchone()
                if row is None:
                    return None
                content = bytes(row["content"])
                if row["sha256"] != reference.sha256 or hashlib.sha256(content).hexdigest() != reference.sha256:
                    raise ContractError("artifact_integrity_mismatch")
                _validate_artifact(content, row["media_type"])
                return reference, content, row["media_type"]

            proof = bytes_for(memory.verification)
            if proof is None or proof[2] != "application/json":
                return None
            publication = json.loads(proof[1])
            if (not isinstance(publication, dict) or publication.get("type") != "workspace_memory_publication"
                    or publication.get("memory_id") != str(memory_id)
                    or publication.get("owner_user_uuid") != str(memory.header.owner_user_uuid)
                    or publication.get("content_sha256") != memory.content.sha256):
                return None
            source = connection.execute("""SELECT v.payload FROM aw_records r JOIN aw_revisions v ON v.seq=r.seq
                WHERE r.environment=? AND r.workspace_id=? AND r.kind='memory' AND r.entity_id=? AND r.owner_uuid=?""",
                                        (*scope, publication.get("source_memory_id"), str(memory.header.owner_user_uuid))).fetchone()
            if source is None:
                return None
            original = decode_record(source["payload"])
            if (not isinstance(original, c.Memory) or original.header.scope != context.scope
                    or original.header.owner_user_uuid != memory.header.owner_user_uuid or original.status != "active"
                    or original.retention_until <= stamp or original.content != memory.content
                    or original.header.revision != publication.get("source_revision")):
                return None
            if original.memory_class == c.MemoryClass.VERIFIED_LESSON:
                content = bytes_for(memory.content)
                if content is None or content[2] != "application/json":
                    return None
                origin = json.loads(content[1])
                outcome_row = connection.execute("""SELECT v.payload FROM aw_records r JOIN aw_revisions v ON v.seq=r.seq
                    WHERE r.environment=? AND r.workspace_id=? AND r.kind='outcome' AND r.entity_id=? AND r.owner_uuid=?""",
                                                  (*scope, origin.get("verified_outcome_id"), str(memory.header.owner_user_uuid))).fetchone()
                outcome = decode_record(outcome_row["payload"]) if outcome_row else None
                if not isinstance(outcome, c.Outcome) or outcome.status != "verified" or outcome.verification != original.verification:
                    return None
            return bytes_for(memory.content if artifact_id == memory.content.artifact_id else memory.verification)

    def _verify_references(self, connection, context, value, *, pending=None):
        for reference in _references(value):
            if isinstance(reference, c.SnapshotRef):
                if self._artifact(connection, context, reference) is None:
                    raise ContractError("artifact_reference_unavailable")
            elif pending is None or reference != pending.ref():
                if self._row(connection, context, reference.kind, reference.entity_id,
                             revision=reference.revision) is None:
                    raise ContractError("entity_reference_unavailable")

    def commit(self, *, context: c.RequestContext, record: c.Record, expected_revision: int,
               event: EventEnvelope, mutation: MutationIdentity) -> CommitResult:
        scope = self._context(context)
        c.validate_record_scope(context, record)
        c.require_revision(expected_revision, zero=True)
        if not isinstance(event, EventEnvelope) or not isinstance(mutation, MutationIdentity):
            raise ContractError("event_and_mutation_required")
        c.require_same_scope(context.scope, mutation.scope)
        c.require_same_scope(context.scope, event.scope)
        if mutation.request_hash != request_digest(context=context, record=record,
                                                    expected_revision=expected_revision, event=event):
            raise ContractError("mutation_payload_mismatch")
        with self._transaction(write=True) as connection:
            replay = connection.execute("""SELECT m.*,v.payload AS record_payload,e.payload AS event_payload
                FROM aw_mutations m JOIN aw_revisions v ON v.seq=m.revision_seq
                JOIN aw_events e ON e.event_id=m.event_id
                WHERE m.environment=? AND m.workspace_id=? AND m.operation=? AND m.key_hash=?""",
                                        mutation.storage_key).fetchone()
            if replay is not None:
                if replay["request_hash"] != mutation.request_hash or replay["user_uuid"] != str(context.user_uuid):
                    raise ContractError("idempotency_conflict")
                original, original_event = decode_record(replay["record_payload"]), decode_event(replay["event_payload"])
                if self._row(connection, context, original.KIND, original.header.entity_id,
                             revision=original.header.revision) is None:
                    raise ContractError("record_unavailable")
                self._verify_references(connection, context, original)
                self._verify_references(connection, context, original_event)
                return CommitResult(record=original, event=original_event, replayed=True)
            previous = self._row(connection, context, record.KIND, record.header.entity_id)
            validate_commit(context=context, record=record, expected_revision=expected_revision,
                            event=event, mutation=mutation, previous=previous)
            self._verify_references(connection, context, record)
            self._verify_references(connection, context, event, pending=record)
            payload, event_payload = encode_record(record), encode_event(event)
            identity = (*scope, record.KIND.value, str(record.header.entity_id))
            revision = connection.execute("""INSERT INTO aw_revisions
                (environment,workspace_id,kind,entity_id,revision,owner_uuid,visibility,payload) VALUES (?,?,?,?,?,?,?,?)""",
                                          (*identity, record.header.revision, str(record.header.owner_user_uuid),
                                           _visibility(record), payload)).lastrowid
            if previous is None:
                connection.execute("""INSERT INTO aw_records
                    (environment,workspace_id,kind,entity_id,revision,seq,owner_uuid,visibility) VALUES (?,?,?,?,?,?,?,?)""",
                                   (*identity, record.header.revision, revision, str(record.header.owner_user_uuid), _visibility(record)))
            else:
                changed = connection.execute("""UPDATE aw_records SET revision=?,seq=?,visibility=?
                    WHERE environment=? AND workspace_id=? AND kind=? AND entity_id=? AND revision=?""",
                                             (record.header.revision, revision, _visibility(record), *identity, expected_revision)).rowcount
                if changed != 1:
                    raise ContractError("revision_conflict")
            connection.execute("""INSERT INTO aw_events
                (event_id,environment,workspace_id,user_uuid,kind,entity_id,revision,payload) VALUES (?,?,?,?,?,?,?,?)""",
                               (str(event.event_id), *scope, str(context.user_uuid), record.KIND.value,
                                str(record.header.entity_id), record.header.revision, event_payload))
            connection.execute("INSERT INTO aw_outbox(event_id) VALUES (?)", (str(event.event_id),))
            connection.execute("""INSERT INTO aw_mutations
                (environment,workspace_id,operation,key_hash,request_hash,user_uuid,revision_seq,event_id) VALUES (?,?,?,?,?,?,?,?)""",
                               (*mutation.storage_key, mutation.request_hash, str(context.user_uuid), revision, str(event.event_id)))
            return CommitResult(record=record, event=event, replayed=False)


class _SQLiteEvents:
    def __init__(self, repository):
        self._repository = repository

    def _visible(self, connection, context, row):
        event = decode_event(row["payload"])
        reference = event.subject
        c.require_same_scope(context.scope, event.scope)
        if self._repository._row(connection, context, reference.kind, reference.entity_id,
                                 revision=reference.revision) is None:
            return None
        self._repository._verify_references(connection, context, event)
        return event

    def list(self, *, context: c.RequestContext, page: PageRequest) -> Page[EventEnvelope]:
        repo = self._repository
        scope = repo._context(context)
        if repo._empty_read_only:
            return repo._empty_page(page)
        with repo._transaction() as connection:
            snapshot, after = repo._page_start(connection, context=context, filter_key="events",
                                               page=page, table="aw_events")
            rows = connection.execute("""SELECT e.* FROM aw_events e JOIN aw_records r
                ON r.environment=e.environment AND r.workspace_id=e.workspace_id AND r.kind=e.kind AND r.entity_id=e.entity_id
                JOIN aw_revisions v ON v.environment=e.environment AND v.workspace_id=e.workspace_id
                  AND v.kind=e.kind AND v.entity_id=e.entity_id AND v.revision=e.revision
                WHERE e.environment=? AND e.workspace_id=? AND e.user_uuid=? AND e.seq>? AND e.seq<=?
                AND (r.visibility!='private' OR r.owner_uuid=?) AND (v.visibility!='private' OR v.owner_uuid=?)
                ORDER BY e.seq LIMIT ?""", (*scope, str(context.user_uuid), after, snapshot,
                                            str(context.user_uuid), str(context.user_uuid), page.limit + 1)).fetchall()
            events = tuple(self._visible(connection, context, row) for row in rows[:page.limit])
            cursor = (repo._cursor(context=context, filter_key="events", snapshot=snapshot,
                                   after=rows[page.limit - 1]["seq"]) if len(rows) > page.limit else None)
            return Page(items=events, next_cursor=cursor)

    def is_acknowledged(self, *, context: c.RequestContext, consumer: str, event_id: UUID) -> bool:
        """Read this consumer's receipt only through the caller's visible event.

        A receipt is never an authorization grant. In particular an event ID
        from another user/workspace cannot disclose whether it was consumed.
        """
        repo = self._repository
        scope = repo._context(context)
        c.require_token(consumer, limit=100)
        c.require_uuid(event_id)
        if repo._empty_read_only:
            return False
        with repo._transaction() as connection:
            row = connection.execute("SELECT * FROM aw_events WHERE environment=? AND workspace_id=? AND user_uuid=? AND event_id=?",
                                     (*scope, str(context.user_uuid), str(event_id))).fetchone()
            if row is None or self._visible(connection, context, row) is None:
                return False
            return connection.execute("SELECT 1 FROM aw_inbox WHERE environment=? AND workspace_id=? AND consumer=? AND event_id=?",
                                      (*scope, consumer, str(event_id))).fetchone() is not None

    def acknowledge(self, *, context: c.RequestContext, consumer: str, event_id: UUID) -> bool:
        repo = self._repository
        scope = repo._context(context)
        c.require_token(consumer, limit=100)
        c.require_uuid(event_id)
        with repo._transaction(write=True) as connection:
            row = connection.execute("SELECT * FROM aw_events WHERE environment=? AND workspace_id=? AND user_uuid=? AND event_id=?",
                                     (*scope, str(context.user_uuid), str(event_id))).fetchone()
            if row is None or self._visible(connection, context, row) is None:
                return False
            return connection.execute("INSERT OR IGNORE INTO aw_inbox(environment,workspace_id,consumer,event_id) VALUES (?,?,?,?)",
                                      (*scope, consumer, str(event_id))).rowcount == 1
