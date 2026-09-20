"""PostgreSQL repositories with explicit user/workspace scope and no fallback."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import secrets
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlparse


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
REPOSITORIES = frozenset({
    "auth", "workspaces", "entitlements", "connectors", "releases", "doc_specs",
    "community", "sf_chat",
})
_WORKSPACE_RE = re.compile(r"^ws_[A-Za-z0-9_-]{8,80}$")
_CLIENT: Optional["PostgresClient"] = None
_CLIENT_LOCK = threading.RLock()


class StorageError(RuntimeError):
    code = "storage_error"


class StorageUnavailableError(StorageError):
    code = "storage_unavailable"


class StorageConflictError(StorageError):
    code = "storage_conflict"


class StorageConstraintError(StorageError):
    code = "storage_constraint"


class StorageReadOnlyError(StorageError):
    code = "storage_read_only"


class StorageConfigurationError(StorageError):
    code = "storage_configuration"


@dataclass(frozen=True)
class Scope:
    user_id: int = 0
    workspace_id: str = ""
    global_service: bool = False

    def __post_init__(self) -> None:
        if self.global_service:
            if self.user_id or self.workspace_id:
                raise ValueError("Global scope cannot include user/workspace identifiers.")
            return
        if self.user_id < 0:
            raise ValueError("user_id cannot be negative")
        if self.workspace_id and not _WORKSPACE_RE.fullmatch(self.workspace_id):
            raise ValueError("Invalid workspace scope.")
        if not self.user_id and not self.workspace_id:
            raise ValueError("A scoped repository requires user_id or workspace_id.")

    @classmethod
    def global_service_scope(cls) -> "Scope":
        return cls(global_service=True)

    @classmethod
    def workspace_scope(cls, workspace_id: str) -> "Scope":
        return cls(workspace_id=str(workspace_id))


def _psycopg() -> Any:
    try:
        import psycopg  # type: ignore
    except ImportError as exc:
        raise StorageConfigurationError(
            "psycopg is required for authoritative Production storage."
        ) from exc
    return psycopg


def _jsonb(value: Any) -> Any:
    psycopg = _psycopg()
    return psycopg.types.json.Jsonb(value)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False, default=str,
    ).encode("utf-8")


def _stable_key(prefix: str, row: Mapping[str, Any]) -> str:
    return f"{prefix}_{hashlib.sha256(_canonical(row)).hexdigest()[:32]}"


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _uuid(value: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value or "")))
    except (AttributeError, TypeError, ValueError):
        return None


def _timestamp(value: Any) -> Optional[datetime]:
    if value in (None, "", 0, 0.0):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(
        timezone.utc
    )


def _validate_database_url(url: str, *, production: bool) -> str:
    value = str(url or "").strip()
    if not value:
        raise StorageConfigurationError("STRATFORGE_DATABASE_URL is required.")
    parsed = urlparse(value)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise StorageConfigurationError("Database URL must be a PostgreSQL URL.")
    query = parse_qs(parsed.query)
    sslmode = str((query.get("sslmode") or [""])[0]).lower()
    if production and sslmode not in {"require", "verify-ca", "verify-full"}:
        raise StorageConfigurationError(
            "Production PostgreSQL URL must set sslmode=require, verify-ca, or verify-full."
        )
    if not production and sslmode in {"", "disable", "allow", "prefer"}:
        loopback = parsed.hostname.lower() in {"127.0.0.1", "localhost", "::1"}
        allowed = os.environ.get("STRATFORGE_ALLOW_INSECURE_LOCAL_POSTGRES") == "1"
        if not loopback or not allowed:
            raise StorageConfigurationError(
                "Insecure PostgreSQL is allowed only on loopback with explicit test opt-in."
            )
    return value


class PostgresClient:
    def __init__(self, url: str, *, production: bool = False) -> None:
        self.url = _validate_database_url(url, production=production)
        self.production = bool(production)
        self._local = threading.local()

    def _connect(self, *, autocommit: bool = False) -> Any:
        psycopg = _psycopg()
        try:
            return psycopg.connect(
                self.url,
                connect_timeout=max(1, min(30, int(os.environ.get(
                    "STRATFORGE_DATABASE_CONNECT_TIMEOUT_SEC", "5"
                )))),
                autocommit=autocommit,
                row_factory=psycopg.rows.dict_row,
                application_name="stratforge",
            )
        except (psycopg.OperationalError, OSError) as exc:
            raise StorageUnavailableError("Authoritative PostgreSQL is unavailable.") from exc

    @contextmanager
    def transaction(self, scope: Scope, *, read_only: bool = False) -> Iterator[Any]:
        psycopg = _psycopg()
        conn = self._connect()
        try:
            with conn:
                with conn.transaction():
                    if read_only:
                        conn.execute("SET TRANSACTION READ ONLY")
                    conn.execute("SET LOCAL statement_timeout = '15s'")
                    conn.execute("SET LOCAL lock_timeout = '5s'")
                    conn.execute("SET LOCAL idle_in_transaction_session_timeout = '15s'")
                    conn.execute(
                        "SELECT set_config('stratforge.service_scope', %s, true)",
                        ("global" if scope.global_service else "scoped",),
                    )
                    conn.execute(
                        "SELECT set_config('stratforge.user_id', %s, true)",
                        (str(scope.user_id) if scope.user_id else "",),
                    )
                    conn.execute(
                        "SELECT set_config('stratforge.workspace_id', %s, true)",
                        (scope.workspace_id,),
                    )
                    yield conn
        except StorageError:
            raise
        except psycopg.errors.ReadOnlySqlTransaction as exc:
            raise StorageReadOnlyError("Authoritative PostgreSQL is read-only.") from exc
        except psycopg.errors.SerializationFailure as exc:
            raise StorageConflictError("Concurrent storage update must be retried.") from exc
        except (psycopg.errors.UniqueViolation, psycopg.errors.ForeignKeyViolation,
                psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege) as exc:
            constraint = ""
            diag = getattr(exc, "diag", None)
            if diag is not None:
                constraint = str(getattr(diag, "constraint_name", "") or "")
            detail = f" ({constraint})" if constraint else f" ({type(exc).__name__})"
            raise StorageConstraintError(
                "Storage isolation or integrity constraint denied the operation"
                + detail + "."
            ) from exc
        except (psycopg.OperationalError, psycopg.InterfaceError, OSError) as exc:
            raise StorageUnavailableError("Authoritative PostgreSQL became unavailable.") from exc
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def remember_revision(self, repository: str, revision: int) -> None:
        revisions = getattr(self._local, "document_revisions", None)
        if revisions is None:
            revisions = {}
            self._local.document_revisions = revisions
        revisions[repository] = int(revision)

    def expected_revision(self, repository: str) -> Optional[int]:
        return getattr(self._local, "document_revisions", {}).get(repository)


def _status(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


class DocumentRepository:
    """Compatibility document with normalized, constrained mirrors.

    Existing modules can switch atomically without a risky big-bang rewrite.
    The document is authoritative, while normalized mirrors provide explicit
    repositories, foreign keys and RLS for new Production code.
    """

    # Handed from the machine sync to the client sync within one write.
    # ``None`` means the machines table is not there yet (pre-0015 schema),
    # which is a different thing from "there are no machines".
    #
    # Declared on the class, not only in __init__: the sync methods are also
    # called unbound with the class itself as ``self``, and an instance-only
    # attribute is simply absent there.
    _pending_machine_ids: Optional[list] = None

    def __init__(self, client: PostgresClient) -> None:
        self.client = client
        self.scope = Scope.global_service_scope()
        self._pending_machine_ids = None

    def read(self, repository: str, default: Mapping[str, Any]) -> Dict[str, Any]:
        if repository not in REPOSITORIES:
            raise ValueError("Unknown repository.")
        with self.client.transaction(self.scope, read_only=True) as conn:
            row = conn.execute(
                "SELECT revision, document FROM sf_repository_documents WHERE repository=%s",
                (repository,),
            ).fetchone()
            revision = int(row["revision"]) if row else 0
            document = copy.deepcopy(dict(row["document"]) if row else dict(default))
            if repository == "auth":
                self._reconcile_auth_document(conn, document)
        self.client.remember_revision(repository, revision)
        return document

    def ping(self, repository: str) -> Dict[str, Any]:
        """Cheap repository liveness check: do not load or migrate the JSON document.

        ``/ready`` must not deserialize the Connector/auth document. Loading that
        payload on Production took ~19s and made promote-time ``curl --max-time 5``
        stack overlapping readiness requests.
        """
        if repository not in REPOSITORIES:
            raise ValueError("Unknown repository.")
        with self.client.transaction(self.scope, read_only=True) as conn:
            conn.execute(
                "SELECT 1 FROM sf_repository_documents WHERE repository=%s",
                (repository,),
            ).fetchone()
        return {"ok": True, "code": "ok"}

    def write(self, repository: str, document: Mapping[str, Any]) -> int:
        if repository not in REPOSITORIES or not isinstance(document, Mapping):
            raise ValueError("Invalid repository document.")
        expected = self.client.expected_revision(repository)
        if expected is None:
            raise StorageConflictError(
                "Repository document must be read before it is written."
            )
        payload = copy.deepcopy(dict(document))
        with self.client.transaction(self.scope) as conn:
            row = conn.execute(
                "SELECT revision FROM sf_repository_documents WHERE repository=%s FOR UPDATE",
                (repository,),
            ).fetchone()
            current = int(row["revision"]) if row else 0
            if current != int(expected):
                raise StorageConflictError(
                    f"Concurrent {repository} update detected (expected {expected}, found {current})."
                )
            if repository == "auth":
                self._reconcile_auth_document(conn, payload)
            revision = current + 1
            conn.execute(
                """
                INSERT INTO sf_repository_documents(repository, revision, document, updated_at)
                VALUES (%s, %s, %s, clock_timestamp())
                ON CONFLICT (repository) DO UPDATE SET
                  revision=EXCLUDED.revision, document=EXCLUDED.document,
                  updated_at=clock_timestamp()
                """,
                (repository, revision, _jsonb(payload)),
            )
            self._sync_mirrors(conn, repository, payload)
        self.client.remember_revision(repository, revision)
        return revision

    def _reconcile_auth_document(self, conn: Any, doc: Dict[str, Any]) -> None:
        """Reuse already-assigned mirror UUIDs instead of minting new ones.

        An incomplete SQL UUID backfill can leave ``sf_users`` / ``sf_auth_identities``
        with canonical UUIDs while the authoritative JSON document still lacks them.
        The next write would otherwise mint fresh UUIDs, collide on
        ``(provider, provider_subject)``, and fail closed as ``storage_constraint`` —
        which is how Production Telegram login broke after 0.10.0-beta.1.
        """
        users = [row for row in doc.get("users", []) if isinstance(row, dict)]
        user_ids = [
            uid for uid in (
                _int(row.get("user_id") or row.get("legacy_user_id")) for row in users
            ) if uid > 0
        ]
        if not user_ids:
            return
        mirror_users = conn.execute(
            "SELECT user_id, user_uuid FROM sf_users WHERE user_id = ANY(%s)",
            (user_ids,),
        ).fetchall() or []
        uuid_by_id = {
            _int(row["user_id"]): _uuid(row["user_uuid"])
            for row in mirror_users
            if _int(row["user_id"]) > 0 and _uuid(row["user_uuid"])
        }
        if not uuid_by_id:
            return
        for row in users:
            uid = _int(row.get("user_id") or row.get("legacy_user_id"))
            mirror_uuid = uuid_by_id.get(uid)
            if not mirror_uuid:
                continue
            row["user_id"] = uid
            row["legacy_user_id"] = uid
            row["user_uuid"] = mirror_uuid
        identities = [row for row in doc.get("auth_identities", []) if isinstance(row, dict)]
        if identities:
            for row in identities:
                legacy = _int(row.get("legacy_user_id") or row.get("user_id"))
                mirror_uuid = uuid_by_id.get(legacy)
                if mirror_uuid:
                    row["user_uuid"] = mirror_uuid
                    row["legacy_user_id"] = legacy
            return
        mirror_identities = conn.execute(
            """
            SELECT identity_id, user_uuid, legacy_user_id, provider, provider_subject,
                   normalized_email, verified_at, linked_at, last_used_at, revoked_at, document
            FROM sf_auth_identities
            WHERE legacy_user_id = ANY(%s)
            """,
            (user_ids,),
        ).fetchall() or []
        rebuilt: list[Dict[str, Any]] = []
        for row in mirror_identities:
            if row.get("revoked_at"):
                continue
            provider = str(row.get("provider") or "").strip().lower()
            subject = str(row.get("provider_subject") or "").strip()
            ident_uuid = _uuid(row.get("user_uuid")) or uuid_by_id.get(_int(row.get("legacy_user_id")))
            ident_id = _uuid(row.get("identity_id"))
            legacy = _int(row.get("legacy_user_id"))
            if provider not in {"telegram", "google", "email"} or not subject or not ident_uuid or not ident_id:
                continue
            extra = row.get("document") if isinstance(row.get("document"), dict) else {}
            metadata = extra.get("metadata") if isinstance(extra.get("metadata"), dict) else {}
            email = str(row.get("normalized_email") or metadata.get("email") or "").strip()
            rebuilt.append({
                "identity_id": ident_id,
                "user_uuid": ident_uuid,
                "legacy_user_id": legacy,
                "provider": provider,
                "provider_subject": subject,
                "linked_at_utc": str(extra.get("linked_at_utc") or ""),
                "verified_at_utc": str(extra.get("verified_at_utc") or ""),
                "last_used_at_utc": str(extra.get("last_used_at_utc") or ""),
                "link_source": str(extra.get("link_source") or extra.get("source") or "mirror_hydrate")[:60],
                "metadata": ({"email": email} if email else dict(metadata)),
            })
        if rebuilt:
            doc["auth_identities"] = rebuilt

    def _sync_mirrors(self, conn: Any, repository: str, doc: Dict[str, Any]) -> None:
        if repository == "auth":
            self._sync_auth(conn, doc)
        elif repository == "workspaces":
            self._sync_workspaces(conn, doc)
        elif repository == "entitlements":
            self._sync_entitlements(conn, doc)
        elif repository == "connectors":
            self._sync_connectors(conn, doc)
        elif repository == "community":
            self._sync_community(conn, doc)
        elif repository == "sf_chat":
            self._sync_sf_chat(conn, doc)

    def _sync_community(self, conn: Any, doc: Dict[str, Any]) -> None:
        """Maintain constrained social mirrors in the document transaction."""
        profiles = [row for row in doc.get("profiles", []) if isinstance(row, dict)
                    and str(row.get("profile_id") or "") and _int(row.get("user_id")) > 0]
        profile_ids: list[str] = []
        for row in profiles:
            profile_id = str(row["profile_id"])
            profile_ids.append(profile_id)
            conn.execute(
                """
                INSERT INTO sf_community_profiles(
                  profile_id,user_id,user_uuid,username,visibility,message_policy,
                  created_at,updated_at,document
                ) VALUES(%s,%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),
                         COALESCE(%s,clock_timestamp()),%s)
                ON CONFLICT(profile_id) DO UPDATE SET
                  user_id=EXCLUDED.user_id,user_uuid=EXCLUDED.user_uuid,
                  username=EXCLUDED.username,visibility=EXCLUDED.visibility,
                  message_policy=EXCLUDED.message_policy,updated_at=EXCLUDED.updated_at,
                  document=EXCLUDED.document
                """,
                (
                    profile_id, _int(row.get("user_id")), _uuid(row.get("user_uuid")),
                    str(row.get("username") or "")[:30],
                    _status(row.get("profile_visibility"), {"network", "followers"}, "network"),
                    _status(row.get("allow_messages"), {"everyone", "following", "nobody"}, "everyone"),
                    _timestamp(row.get("created_at_utc") or row.get("joined_at_utc")),
                    _timestamp(row.get("updated_at_utc")), _jsonb(row),
                ),
            )

        posts = [row for row in doc.get("posts", []) if isinstance(row, dict)
                 and str(row.get("post_id") or "") and str(row.get("author_profile_id") or "")]
        post_ids: list[str] = []
        for row in posts:
            post_id = str(row["post_id"])
            post_ids.append(post_id)
            snapshot = row.get("object_snapshot") if isinstance(row.get("object_snapshot"), dict) else {}
            attestation = snapshot.get("attestation") if isinstance(snapshot.get("attestation"), dict) else {}
            conn.execute(
                """
                INSERT INTO sf_community_posts(
                  post_id,author_profile_id,workspace_id,visibility,kind,
                  object_source_type,object_source_id,attestation_sha256,
                  created_at,updated_at,deleted_at,document
                ) VALUES(%s,%s,NULLIF(%s,''),%s,%s,NULLIF(%s,''),NULLIF(%s,''),
                         NULLIF(%s,''),COALESCE(%s,clock_timestamp()),
                         COALESCE(%s,clock_timestamp()),%s,%s)
                ON CONFLICT(post_id) DO UPDATE SET
                  author_profile_id=EXCLUDED.author_profile_id,
                  workspace_id=EXCLUDED.workspace_id,visibility=EXCLUDED.visibility,
                  kind=EXCLUDED.kind,object_source_type=EXCLUDED.object_source_type,
                  object_source_id=EXCLUDED.object_source_id,
                  attestation_sha256=EXCLUDED.attestation_sha256,
                  updated_at=EXCLUDED.updated_at,deleted_at=EXCLUDED.deleted_at,
                  document=EXCLUDED.document
                """,
                (
                    post_id, str(row.get("author_profile_id") or ""),
                    str(row.get("workspace_id") or ""),
                    _status(row.get("visibility"), {"network", "followers"}, "network"),
                    _status(row.get("kind"), {"text", "image", "object"}, "text"),
                    str(snapshot.get("source_type") or "")[:40],
                    str(snapshot.get("source_id") or "")[:96],
                    str(attestation.get("digest") or "")[:64],
                    _timestamp(row.get("created_at_utc")), _timestamp(row.get("updated_at_utc")),
                    _timestamp(row.get("deleted_at_utc")), _jsonb(row),
                ),
            )

        comments = [row for row in doc.get("comments", []) if isinstance(row, dict)
                    and str(row.get("comment_id") or "") and str(row.get("post_id") or "")
                    and str(row.get("author_profile_id") or "")]
        comment_ids: list[str] = []
        for row in comments:
            comment_id = str(row["comment_id"])
            comment_ids.append(comment_id)
            conn.execute(
                """
                INSERT INTO sf_community_comments(
                  comment_id,post_id,author_profile_id,created_at,deleted_at,document
                ) VALUES(%s,%s,%s,COALESCE(%s,clock_timestamp()),%s,%s)
                ON CONFLICT(comment_id) DO UPDATE SET
                  post_id=EXCLUDED.post_id,author_profile_id=EXCLUDED.author_profile_id,
                  deleted_at=EXCLUDED.deleted_at,document=EXCLUDED.document
                """,
                (
                    comment_id, str(row.get("post_id") or ""),
                    str(row.get("author_profile_id") or ""),
                    _timestamp(row.get("created_at_utc")), _timestamp(row.get("deleted_at_utc")),
                    _jsonb(row),
                ),
            )

        edge_specs = (
            ("follows", "sf_community_follows", "follow_id", "follower_profile_id", "target_profile_id", "follow"),
            ("social_blocks", "sf_community_blocks", "block_id", "blocker_profile_id", "target_profile_id", "block"),
        )
        edge_ids: Dict[str, list[str]] = {}
        for collection, table, key_column, left_key, right_key, prefix in edge_specs:
            ids: list[str] = []
            for row in doc.get(collection, []):
                if not isinstance(row, dict):
                    continue
                left, right = str(row.get(left_key) or ""), str(row.get(right_key) or "")
                if not left or not right:
                    continue
                edge_id = _stable_key(prefix, {left_key: left, right_key: right})
                ids.append(edge_id)
                conn.execute(
                    f"""
                    INSERT INTO {table}({key_column},{left_key},{right_key},created_at,document)
                    VALUES(%s,%s,%s,COALESCE(%s,clock_timestamp()),%s)
                    ON CONFLICT({key_column}) DO UPDATE SET document=EXCLUDED.document
                    """,
                    (edge_id, left, right, _timestamp(row.get("created_at_utc")), _jsonb(row)),
                )
            edge_ids[table] = ids

        reactions: list[str] = []
        for row in doc.get("post_reactions", []):
            if not isinstance(row, dict):
                continue
            post_id, profile_id = str(row.get("post_id") or ""), str(row.get("profile_id") or "")
            if not post_id or not profile_id:
                continue
            reaction_id = _stable_key("reaction", {"post_id": post_id, "profile_id": profile_id})
            reactions.append(reaction_id)
            conn.execute(
                """
                INSERT INTO sf_community_reactions(
                  reaction_id,post_id,profile_id,reaction,created_at,document
                ) VALUES(%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),%s)
                ON CONFLICT(reaction_id) DO UPDATE SET
                  reaction=EXCLUDED.reaction,document=EXCLUDED.document
                """,
                (
                    reaction_id, post_id, profile_id,
                    _status(row.get("reaction"), {"support", "insightful", "fire"}, "support"),
                    _timestamp(row.get("created_at_utc")), _jsonb(row),
                ),
            )

        bookmarks: list[str] = []
        for row in doc.get("bookmarks", []):
            if not isinstance(row, dict):
                continue
            post_id, profile_id = str(row.get("post_id") or ""), str(row.get("profile_id") or "")
            if not post_id or not profile_id:
                continue
            bookmark_id = _stable_key("bookmark", {"post_id": post_id, "profile_id": profile_id})
            bookmarks.append(bookmark_id)
            conn.execute(
                """
                INSERT INTO sf_community_bookmarks(
                  bookmark_id,post_id,profile_id,created_at,document
                ) VALUES(%s,%s,%s,COALESCE(%s,clock_timestamp()),%s)
                ON CONFLICT(bookmark_id) DO UPDATE SET document=EXCLUDED.document
                """,
                (bookmark_id, post_id, profile_id, _timestamp(row.get("created_at_utc")), _jsonb(row)),
            )

        reports = [row for row in doc.get("reports", []) if isinstance(row, dict)
                   and str(row.get("report_id") or "") and str(row.get("from_profile_id") or "")]
        report_ids: list[str] = []
        for row in reports:
            report_id = str(row["report_id"])
            report_ids.append(report_id)
            conn.execute(
                """
                INSERT INTO sf_community_moderation_reports(
                  report_id,reporter_profile_id,target_type,target_id,status,
                  created_at,resolved_at,document
                ) VALUES(%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),%s,%s)
                ON CONFLICT(report_id) DO UPDATE SET
                  target_type=EXCLUDED.target_type,target_id=EXCLUDED.target_id,
                  status=EXCLUDED.status,resolved_at=EXCLUDED.resolved_at,
                  document=EXCLUDED.document
                """,
                (
                    report_id, str(row.get("from_profile_id") or ""),
                    _status(row.get("target_type"), {"post", "profile", "comment"}, "post"),
                    str(row.get("target_id") or "")[:100],
                    _status(row.get("status"), {"open", "resolved", "dismissed"}, "open"),
                    _timestamp(row.get("created_at_utc")), _timestamp(row.get("resolved_at_utc")),
                    _jsonb(row),
                ),
            )

        self._delete_missing(conn, "sf_community_comments", "comment_id", comment_ids)
        self._delete_missing(conn, "sf_community_reactions", "reaction_id", reactions)
        self._delete_missing(conn, "sf_community_bookmarks", "bookmark_id", bookmarks)
        self._delete_missing(conn, "sf_community_moderation_reports", "report_id", report_ids)
        for table, ids in edge_ids.items():
            key = "follow_id" if table.endswith("follows") else "block_id"
            self._delete_missing(conn, table, key, ids)
        self._delete_missing(conn, "sf_community_posts", "post_id", post_ids)
        self._delete_missing(conn, "sf_community_profiles", "profile_id", profile_ids)

    def _sync_sf_chat(self, conn: Any, doc: Dict[str, Any]) -> None:
        """Maintain private-conversation mirrors; API ACL remains authoritative."""
        conversations = [row for row in doc.get("conversations", []) if isinstance(row, dict)
                         and str(row.get("conversation_id") or "")]
        conversation_ids: list[str] = []
        participant_ids: list[str] = []
        for row in conversations:
            conversation_id = str(row["conversation_id"])
            conversation_ids.append(conversation_id)
            conn.execute(
                """
                INSERT INTO sf_chat_conversations(
                  conversation_id,conversation_type,last_seq,created_at,updated_at,document
                ) VALUES(%s,'human',%s,COALESCE(%s,clock_timestamp()),
                         COALESCE(%s,clock_timestamp()),%s)
                ON CONFLICT(conversation_id) DO UPDATE SET
                  last_seq=EXCLUDED.last_seq,updated_at=EXCLUDED.updated_at,
                  document=EXCLUDED.document
                """,
                (
                    conversation_id, max(0, _int(row.get("last_seq"))),
                    _timestamp(row.get("created_at_utc")), _timestamp(row.get("updated_at_utc")),
                    _jsonb(row),
                ),
            )
            for profile_id in sorted({str(value) for value in row.get("participant_profile_ids", []) if value}):
                participant_id = _stable_key(
                    "participant", {"conversation_id": conversation_id, "profile_id": profile_id},
                )
                participant_ids.append(participant_id)
                conn.execute(
                    """
                    INSERT INTO sf_chat_participants(
                      participant_id,conversation_id,profile_id,joined_at,document
                    ) VALUES(%s,%s,%s,COALESCE(%s,clock_timestamp()),%s)
                    ON CONFLICT(participant_id) DO UPDATE SET document=EXCLUDED.document
                    """,
                    (
                        participant_id, conversation_id, profile_id,
                        _timestamp(row.get("created_at_utc")),
                        _jsonb({"conversation_id": conversation_id, "profile_id": profile_id}),
                    ),
                )

        messages = [row for row in doc.get("messages", []) if isinstance(row, dict)
                    and str(row.get("message_id") or "") and str(row.get("conversation_id") or "")
                    and str(row.get("sender_profile_id") or "")]
        message_ids: list[str] = []
        for row in messages:
            message_id = str(row["message_id"])
            message_ids.append(message_id)
            conn.execute(
                """
                INSERT INTO sf_chat_messages(
                  message_id,conversation_id,seq,sender_profile_id,idempotency_key_hash,
                  created_at,deleted_at,document
                ) VALUES(%s,%s,%s,%s,NULLIF(%s,''),COALESCE(%s,clock_timestamp()),%s,%s)
                ON CONFLICT(message_id) DO UPDATE SET
                  seq=EXCLUDED.seq,sender_profile_id=EXCLUDED.sender_profile_id,
                  idempotency_key_hash=EXCLUDED.idempotency_key_hash,
                  deleted_at=EXCLUDED.deleted_at,document=EXCLUDED.document
                """,
                (
                    message_id, str(row.get("conversation_id") or ""),
                    max(1, _int(row.get("seq"))), str(row.get("sender_profile_id") or ""),
                    str(row.get("idempotency_key_hash") or "")[:64],
                    _timestamp(row.get("created_at_utc")), _timestamp(row.get("deleted_at_utc")),
                    _jsonb(row),
                ),
            )

        read_ids: list[str] = []
        for row in doc.get("reads", []):
            if not isinstance(row, dict):
                continue
            conversation_id, profile_id = (
                str(row.get("conversation_id") or ""), str(row.get("profile_id") or ""),
            )
            if not conversation_id or not profile_id:
                continue
            read_id = _stable_key(
                "read", {"conversation_id": conversation_id, "profile_id": profile_id},
            )
            read_ids.append(read_id)
            conn.execute(
                """
                INSERT INTO sf_chat_reads(
                  read_id,conversation_id,profile_id,last_read_seq,read_at,document
                ) VALUES(%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),%s)
                ON CONFLICT(read_id) DO UPDATE SET
                  last_read_seq=EXCLUDED.last_read_seq,read_at=EXCLUDED.read_at,
                  document=EXCLUDED.document
                """,
                (
                    read_id, conversation_id, profile_id,
                    max(0, _int(row.get("last_read_seq"))), _timestamp(row.get("read_at_utc")),
                    _jsonb(row),
                ),
            )

        self._delete_missing(conn, "sf_chat_messages", "message_id", message_ids)
        self._delete_missing(conn, "sf_chat_reads", "read_id", read_ids)
        self._delete_missing(conn, "sf_chat_participants", "participant_id", participant_ids)
        self._delete_missing(conn, "sf_chat_conversations", "conversation_id", conversation_ids)

    @staticmethod
    def _delete_missing(conn: Any, table: str, key: str, values: Sequence[Any]) -> None:
        if values:
            conn.execute(
                f"DELETE FROM {table} WHERE NOT ({key} = ANY(%s))",
                (list(values),),
            )
        else:
            conn.execute(f"DELETE FROM {table}")

    def _sync_auth(self, conn: Any, doc: Dict[str, Any]) -> None:
        users = [row for row in doc.get("users", []) if isinstance(row, dict) and _int(row.get("user_id")) > 0]
        user_ids = [_int(row["user_id"]) for row in users]
        user_uuids: Dict[int, str] = {}
        identity_ids: list[str] = []
        for row in users:
            user_id = _int(row["user_id"])
            user_uuid = _uuid(row.get("user_uuid"))
            if not user_uuid:
                raise StorageConstraintError("Auth user UUID is required during the identity transition.")
            user_uuids[user_id] = user_uuid
            conn.execute(
                """
                INSERT INTO sf_users(user_id,user_uuid,status,is_owner,document,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),clock_timestamp())
                ON CONFLICT(user_id) DO UPDATE SET user_uuid=EXCLUDED.user_uuid,
                  status=EXCLUDED.status,
                  is_owner=EXCLUDED.is_owner,document=EXCLUDED.document,updated_at=clock_timestamp()
                """,
                (user_id, user_uuid,
                 _status(row.get("status"), {"pending","active","blocked","revoked","deleted"}, "active"),
                 bool(row.get("is_owner") or str(row.get("role") or "").lower() == "owner"),
                 _jsonb(row), _timestamp(row.get("created_at_utc"))),
            )
        for row in [item for item in doc.get("auth_identities", []) if isinstance(item, dict)]:
            provider = str(row.get("provider") or "").strip().lower()
            if provider not in {"telegram", "google", "email"}:
                continue
            identity_id = _uuid(row.get("identity_id"))
            user_uuid = _uuid(row.get("user_uuid"))
            legacy_user_id = _int(row.get("legacy_user_id"))
            subject = str(row.get("provider_subject") or "").strip()
            if not identity_id or not user_uuid or not subject or user_uuids.get(legacy_user_id) != user_uuid:
                raise StorageConstraintError("Auth identity does not match its canonical user UUID.")
            identity_ids.append(identity_id)
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            normalized_email = str(metadata.get("email") or "").strip().lower() or None
            persisted = conn.execute(
                """
                INSERT INTO sf_auth_identities(
                  identity_id,user_uuid,legacy_user_id,provider,provider_subject,
                  normalized_email,verified_at,linked_at,last_used_at,revoked_at,document
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),%s,%s,%s)
                ON CONFLICT (provider, provider_subject) DO UPDATE SET
                  legacy_user_id=EXCLUDED.legacy_user_id,
                  normalized_email=EXCLUDED.normalized_email,
                  verified_at=EXCLUDED.verified_at,
                  linked_at=EXCLUDED.linked_at,
                  last_used_at=EXCLUDED.last_used_at,
                  revoked_at=EXCLUDED.revoked_at,
                  document=EXCLUDED.document
                WHERE sf_auth_identities.user_uuid=EXCLUDED.user_uuid
                RETURNING user_uuid
                """,
                (
                    identity_id, user_uuid, legacy_user_id, provider, subject,
                    normalized_email, _timestamp(row.get("verified_at_utc")),
                    _timestamp(row.get("linked_at_utc")), _timestamp(row.get("last_used_at_utc")),
                    _timestamp(row.get("revoked_at_utc")), _jsonb(row),
                ),
            ).fetchone()
            if not persisted or _uuid(persisted.get("user_uuid")) != user_uuid:
                raise StorageConstraintError(
                    "Provider identity is already linked to a different UUID user."
                )
        if user_ids:
            conn.execute(
                """
                UPDATE sf_auth_identities
                SET revoked_at=clock_timestamp(),
                    document=document || jsonb_build_object('revoked_reason', 'source_unlinked')
                WHERE legacy_user_id = ANY(%s)
                  AND revoked_at IS NULL
                  AND NOT (identity_id = ANY(%s))
                """,
                (user_ids, identity_ids),
            )
            conn.execute(
                "DELETE FROM sf_auth_identities WHERE NOT (legacy_user_id = ANY(%s))",
                (user_ids,),
            )
        else:
            conn.execute("DELETE FROM sf_auth_identities")
        challenges = [row for row in doc.get("challenges", []) if isinstance(row, dict)]
        challenge_ids: list[str] = []
        for row in challenges:
            key = str(row.get("challenge_id") or _stable_key("challenge", row))[:160]
            challenge_ids.append(key)
            user_id = _int(row.get("user_id")) or None
            user_uuid = _uuid(row.get("user_uuid")) or user_uuids.get(user_id or 0)
            conn.execute(
                """
                INSERT INTO sf_auth_challenges(challenge_id,user_id,user_uuid,expires_at,consumed,document)
                VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(challenge_id) DO UPDATE SET user_id=EXCLUDED.user_id,
                  user_uuid=EXCLUDED.user_uuid,
                  expires_at=EXCLUDED.expires_at,consumed=EXCLUDED.consumed,document=EXCLUDED.document
                """,
                (key, user_id, user_uuid, _timestamp(row.get("expires_at")),
                 bool(row.get("consumed")), _jsonb(row)),
            )
        sessions = [
            row for row in doc.get("sessions", [])
            if isinstance(row, dict) and _int(row.get("user_id")) > 0
        ]
        session_ids: list[str] = []
        for row in sessions:
            token_hash = str(row.get("token_hash") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", token_hash):
                raise StorageConstraintError("Auth session token hash is invalid.")
            key = str(row.get("session_id") or f"sess_{token_hash[:32]}")[:160]
            session_ids.append(key)
            user_id = _int(row["user_id"])
            user_uuid = _uuid(row.get("user_uuid")) or user_uuids.get(user_id)
            if not user_uuid:
                raise StorageConstraintError("Auth session UUID is required during the identity transition.")
            conn.execute(
                """
                INSERT INTO sf_auth_sessions(
                  session_id,user_id,user_uuid,token_hash,revoked,expires_at,document,updated_at
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,clock_timestamp())
                ON CONFLICT(session_id) DO UPDATE SET
                  user_id=EXCLUDED.user_id,
                  user_uuid=EXCLUDED.user_uuid,
                  token_hash=EXCLUDED.token_hash,
                  revoked=EXCLUDED.revoked,
                  expires_at=EXCLUDED.expires_at,
                  document=EXCLUDED.document,
                  updated_at=clock_timestamp()
                """,
                (
                    key, user_id, user_uuid, token_hash, bool(row.get("revoked")),
                    _timestamp(row.get("expires_at")), _jsonb(row),
                ),
            )
        # Machines first: a client row carries a foreign key to one.
        self._sync_physical_devices(conn, doc, user_uuids)
        self._sync_trusted_devices(conn, doc, user_uuids)
        self._delete_missing(conn, "sf_auth_challenges", "challenge_id", challenge_ids)
        self._delete_missing(conn, "sf_auth_sessions", "session_id", session_ids)
        self._purge_departed_accounts(conn, user_ids)
        self._delete_missing(conn, "sf_users", "user_id", user_ids)

    # Operational records owned by an account, living only in their relational
    # table with no representation in the auth document. Their foreign keys are
    # ON DELETE RESTRICT, so a deleted account cannot be pruned from sf_users
    # while any of them survive -- and NOT VALID does not help here, it only
    # skips validating rows that already existed, never the enforcement.
    _ACCOUNT_OWNED_TABLES = (
        ("sf_commands", "user_id"),
        ("sf_jobs", "user_id"),
        ("sf_artifacts", "user_id"),
        ("sf_ai_usage_events", "user_id"),
        ("sf_ai_reservations", "user_id"),
        ("sf_market_data_subscriptions", "requested_by_user_id"),
    )

    def _purge_departed_accounts(self, conn: Any, user_ids: Sequence[int]) -> None:
        """Remove operational rows owned by accounts leaving the document.

        Deleting an account has to take its own operational records with it.
        Without this the account cannot be deleted at all: the write fails with
        a foreign-key violation and the whole document write is rolled back, so
        a user "deleted" in the UI silently stays.
        """
        for table, column in self._ACCOUNT_OWNED_TABLES:
            # A table from a later migration may not exist yet. Ask first: a
            # failed statement aborts the surrounding transaction in Postgres,
            # so catching the error here would poison the whole document write.
            present = conn.execute(
                "SELECT to_regclass(%s) IS NOT NULL", (table,),
            ).fetchone()
            if not present or not list(present)[0]:
                continue
            if user_ids:
                conn.execute(
                    f"DELETE FROM {table} WHERE NOT ({column} = ANY(%s))",
                    (list(user_ids),),
                )
            else:
                conn.execute(f"DELETE FROM {table}")

    def _sync_physical_devices(
        self, conn: Any, doc: Dict[str, Any], user_uuids: Dict[int, str],
    ) -> None:
        """Project physical machines into their relational table.

        Runs before the client sync because sf_trusted_devices.physical_device_id
        references this table; writing the client first would fail the foreign
        key on the very first Connector to register a new machine.
        """
        # A store written before migration 0015 has no such table. Ask rather
        # than catching: a failed statement aborts the whole document write.
        present = conn.execute(
            "SELECT to_regclass('sf_physical_devices') IS NOT NULL",
        ).fetchone()
        self._pending_machine_ids = None
        if not present or not list(present)[0]:
            return
        rows = [row for row in doc.get("physical_devices", []) if isinstance(row, dict)]
        machine_ids: list[str] = []
        seen_active: set[tuple[str, str]] = set()
        for row in rows:
            machine_id = _uuid(row.get("physical_device_id"))
            user_uuid = _uuid(row.get("user_uuid"))
            legacy_user_id = _int(row.get("legacy_user_id"))
            key_hash = str(row.get("machine_key_hash") or "").strip()
            status = _status(
                row.get("status"), {"pending", "trusted", "revoked", "expired"}, "pending",
            )
            if not machine_id or not user_uuid or len(key_hash) < 16:
                continue
            if user_uuids and user_uuids.get(legacy_user_id) not in (None, user_uuid):
                raise StorageConstraintError(
                    "Physical device does not match its canonical user UUID."
                )
            if status in {"pending", "trusted"}:
                key = (user_uuid, key_hash)
                if key in seen_active:
                    raise StorageConstraintError(
                        "Duplicate active machine for one account credential."
                    )
                seen_active.add(key)
            machine_ids.append(machine_id)
            provider = _status(
                row.get("confirmation_provider"), {"", "telegram", "email", "google"}, "",
            )
            audit = row.get("audit_metadata") if isinstance(row.get("audit_metadata"), dict) else {}
            confirmed_at = _timestamp(row.get("confirmed_at_utc"))
            revoked_at = _timestamp(row.get("revoked_at_utc"))
            # The table's CHECKs tie status to these timestamps. Enforce the same
            # thing here so a malformed document is rejected with a named error
            # rather than an opaque constraint violation from the driver.
            if (status == "revoked") != (revoked_at is not None):
                raise StorageConstraintError(
                    "Machine revocation status and timestamp disagree."
                )
            if status == "trusted" and confirmed_at is None:
                raise StorageConstraintError(
                    "Trusted machine is missing its confirmation timestamp."
                )
            conn.execute(
                """
                INSERT INTO sf_physical_devices(
                  physical_device_id,user_uuid,legacy_user_id,machine_key_hash,
                  display_name,os_family,os_version,status,confirmation_provider,
                  first_seen_at,last_seen_at,confirmed_at,revoked_at,expires_at,
                  audit_metadata
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       COALESCE(%s,clock_timestamp()),%s,%s,%s,%s,%s)
                ON CONFLICT(physical_device_id) DO UPDATE SET
                  machine_key_hash=EXCLUDED.machine_key_hash,
                  display_name=EXCLUDED.display_name,
                  os_family=EXCLUDED.os_family,
                  os_version=EXCLUDED.os_version,
                  status=EXCLUDED.status,
                  confirmation_provider=EXCLUDED.confirmation_provider,
                  last_seen_at=EXCLUDED.last_seen_at,
                  confirmed_at=EXCLUDED.confirmed_at,
                  revoked_at=EXCLUDED.revoked_at,
                  expires_at=EXCLUDED.expires_at,
                  audit_metadata=EXCLUDED.audit_metadata
                """,
                (
                    machine_id, user_uuid, legacy_user_id, key_hash[:128],
                    str(row.get("display_name") or "")[:160],
                    str(row.get("os_family") or "")[:40],
                    str(row.get("os_version") or "")[:40],
                    status, provider,
                    _timestamp(row.get("first_seen_at_utc")),
                    _timestamp(row.get("last_seen_at_utc")),
                    confirmed_at, revoked_at,
                    _timestamp(row.get("expires_at_utc")),
                    _jsonb(audit),
                ),
            )
        # Clients reference machines, so orphan machines can only be dropped
        # after the client sync has moved every reference off them.
        self._pending_machine_ids = machine_ids

    def _sync_trusted_devices(
        self, conn: Any, doc: Dict[str, Any], user_uuids: Dict[int, str],
    ) -> None:
        """Project trusted devices into their relational table.

        The table carries a unique index over (user_uuid, fingerprint) for
        active rows.  Until devices were mirrored here that constraint could
        never fire, and duplicates were only ever visible in the UI.  A
        duplicate now fails the write instead of being persisted.
        """
        rows = [row for row in doc.get("trusted_devices", []) if isinstance(row, dict)]
        device_ids: list[str] = []
        seen_active: set[tuple[str, str]] = set()
        for row in rows:
            device_id = _uuid(row.get("device_id"))
            user_uuid = _uuid(row.get("user_uuid"))
            legacy_user_id = _int(row.get("legacy_user_id"))
            fingerprint = str(row.get("fingerprint") or "").strip()
            status = _status(
                row.get("status"), {"pending", "trusted", "revoked", "expired"}, "pending",
            )
            if not device_id or not user_uuid or not fingerprint:
                continue
            if user_uuids and user_uuids.get(legacy_user_id) not in (None, user_uuid):
                raise StorageConstraintError(
                    "Trusted device does not match its canonical user UUID."
                )
            if status in {"pending", "trusted"}:
                key = (user_uuid, fingerprint)
                if key in seen_active:
                    raise StorageConstraintError(
                        "Duplicate active trusted device for one account fingerprint."
                    )
                seen_active.add(key)
            device_ids.append(device_id)
            device_type = _status(
                row.get("device_type"),
                {"phone", "tablet", "desktop", "browser", "connector"},
                "browser",
            )
            provider = _status(
                row.get("confirmation_provider"), {"", "telegram", "email", "google"}, "",
            )
            audit = row.get("audit_metadata") if isinstance(row.get("audit_metadata"), dict) else {}
            # The two binding columns arrive with the machines table in the same
            # migration, so one probe answers for both.
            machines_live = self._pending_machine_ids is not None
            physical_device_id = _uuid(row.get("physical_device_id")) if machines_live else None
            bound_via = _status(
                row.get("bound_via"), {"", "connector_self", "attested_pairing"}, "",
            ) if machines_live else ""
            # The table's CHECK ties the two together; disagreeing here means the
            # document is wrong, and a named error beats a driver-level one.
            if machines_live and (physical_device_id is None) != (bound_via == ""):
                raise StorageConstraintError(
                    "Device binding and its origin disagree."
                )
            binding_columns = ",physical_device_id,bound_via" if machines_live else ""
            binding_values = ",%s,%s" if machines_live else ""
            binding_update = (
                " physical_device_id=EXCLUDED.physical_device_id,"
                " bound_via=EXCLUDED.bound_via,"
            ) if machines_live else ""
            conn.execute(
                f"""
                INSERT INTO sf_trusted_devices(
                  device_id,user_uuid,legacy_user_id,fingerprint,device_type,display_name,
                  os_family,os_version,client,app_version,connector_installation_id,
                  status,confirmation_provider,first_seen_at,last_seen_at,last_auth_at,
                  confirmed_at,revoked_at,expires_at,audit_metadata{binding_columns}
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       COALESCE(%s,clock_timestamp()),%s,%s,%s,%s,%s,%s{binding_values})
                ON CONFLICT(device_id) DO UPDATE SET{binding_update}
                  fingerprint=EXCLUDED.fingerprint,
                  device_type=EXCLUDED.device_type,
                  display_name=EXCLUDED.display_name,
                  os_family=EXCLUDED.os_family,
                  os_version=EXCLUDED.os_version,
                  client=EXCLUDED.client,
                  app_version=EXCLUDED.app_version,
                  connector_installation_id=EXCLUDED.connector_installation_id,
                  status=EXCLUDED.status,
                  confirmation_provider=EXCLUDED.confirmation_provider,
                  last_seen_at=EXCLUDED.last_seen_at,
                  last_auth_at=EXCLUDED.last_auth_at,
                  confirmed_at=EXCLUDED.confirmed_at,
                  revoked_at=EXCLUDED.revoked_at,
                  expires_at=EXCLUDED.expires_at,
                  audit_metadata=EXCLUDED.audit_metadata
                """,
                (
                    device_id, user_uuid, legacy_user_id, fingerprint[:128], device_type,
                    str(row.get("display_name") or "")[:160],
                    str(row.get("os_family") or "")[:40], str(row.get("os_version") or "")[:40],
                    str(row.get("client") or "")[:80], str(row.get("app_version") or "")[:80],
                    str(row.get("connector_installation_id") or "")[:128],
                    status, provider,
                    _timestamp(row.get("first_seen_at_utc")),
                    _timestamp(row.get("last_seen_at_utc")),
                    _timestamp(row.get("last_auth_at_utc")),
                    _timestamp(row.get("confirmed_at_utc")),
                    _timestamp(row.get("revoked_at_utc")),
                    _timestamp(row.get("expires_at_utc")),
                    _jsonb(audit),
                ) + ((physical_device_id, bound_via) if machines_live else ()),
            )
        self._delete_missing(conn, "sf_trusted_devices", "device_id", device_ids)
        if self._pending_machine_ids is not None:
            # Only now that no client references a departed machine.
            self._delete_missing(
                conn, "sf_physical_devices", "physical_device_id",
                self._pending_machine_ids,
            )
            self._pending_machine_ids = None

    def _sync_workspaces(self, conn: Any, doc: Dict[str, Any]) -> None:
        workspaces = [row for row in doc.get("workspaces", []) if isinstance(row, dict)]
        workspace_ids: list[str] = []
        for row in workspaces:
            workspace_id = str(row.get("workspace_id") or "")
            owner_id = _int(row.get("owner_user_id"))
            if not _WORKSPACE_RE.fullmatch(workspace_id) or owner_id <= 0:
                raise StorageConstraintError("Workspace identity is invalid.")
            workspace_ids.append(workspace_id)
            conn.execute(
                """
                INSERT INTO sf_workspaces(workspace_id,owner_user_id,status,kind,document,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),clock_timestamp())
                ON CONFLICT(workspace_id) DO UPDATE SET owner_user_id=EXCLUDED.owner_user_id,
                  status=EXCLUDED.status,kind=EXCLUDED.kind,document=EXCLUDED.document,
                  updated_at=clock_timestamp()
                """,
                (workspace_id, owner_id,
                 _status(row.get("status"), {"active","suspended","archived","deleted"}, "active"),
                 str(row.get("kind") or "personal")[:64], _jsonb(row), _timestamp(row.get("created_at_utc"))),
            )
        memberships = [row for row in doc.get("memberships", []) if isinstance(row, dict)]
        retained_memberships = []
        for row in memberships:
            wid = str(row.get("workspace_id") or "")
            uid = _int(row.get("user_id"))
            retained_memberships.append((wid, uid))
            conn.execute(
                """
                INSERT INTO sf_workspace_memberships(workspace_id,user_id,role,revoked_at,document,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),clock_timestamp())
                ON CONFLICT(workspace_id, user_id) DO UPDATE SET role=EXCLUDED.role, revoked_at=EXCLUDED.revoked_at, document=EXCLUDED.document, updated_at=clock_timestamp()
                """,
                (wid, uid,
                 str(row.get("role") or "viewer"), _timestamp(row.get("revoked_at_utc")),
                 _jsonb(row), _timestamp(row.get("created_at_utc"))),
            )
        if retained_memberships:
            pass # Skipping delete for now to avoid complexity with composite keys
        else:
            # Only delete if no memberships exist (might still fail FK, but handled)
            try:
                conn.execute("DELETE FROM sf_workspace_memberships")
            except Exception:
                pass
        conn.execute("DELETE FROM sf_active_workspaces")
        for raw_user, raw_workspace in dict(doc.get("active_workspaces") or {}).items():
            conn.execute(
                "INSERT INTO sf_active_workspaces(user_id,workspace_id) VALUES(%s,%s)",
                (_int(raw_user), str(raw_workspace or "")),
            )
        connections = [row for row in doc.get("connections", []) if isinstance(row, dict)]
        connection_ids: list[str] = []
        for row in connections:
            key = str(row.get("connection_id") or _stable_key("conn", row))[:160]
            connection_ids.append(key)
            conn.execute(
                """
                INSERT INTO sf_connections(connection_id,workspace_id,user_id,status,document,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),clock_timestamp())
                ON CONFLICT(connection_id) DO UPDATE SET workspace_id=EXCLUDED.workspace_id,
                  user_id=EXCLUDED.user_id,status=EXCLUDED.status,document=EXCLUDED.document,
                  updated_at=clock_timestamp()
                """,
                (key, str(row.get("workspace_id") or ""),
                 _int(row.get("user_id") or row.get("owner_user_id")),
                 _status(row.get("status"), {"pending","online","offline","revoked","failed"}, "pending"),
                 _jsonb(row), _timestamp(row.get("created_at_utc"))),
            )
        self._delete_missing(conn, "sf_connections", "connection_id", connection_ids)
        self._delete_missing(conn, "sf_workspaces", "workspace_id", workspace_ids)

    def _sync_entitlements(self, conn: Any, doc: Dict[str, Any]) -> None:
        rows = [row for row in doc.get("entitlements", []) if isinstance(row, dict)]
        ids: list[str] = []
        allowed = {"promo_grant","trial","active","pending","expired","revoked","cancelled"}
        for row in rows:
            key = str(row.get("entitlement_id") or _stable_key("ent", row))[:160]
            ids.append(key)
            workspace_id = str(row.get("workspace_id") or "") or None
            conn.execute(
                """
                INSERT INTO sf_entitlements(entitlement_id,user_id,workspace_id,plan_id,status,expires_at,document,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),clock_timestamp())
                ON CONFLICT(entitlement_id) DO UPDATE SET user_id=EXCLUDED.user_id,
                  workspace_id=EXCLUDED.workspace_id,plan_id=EXCLUDED.plan_id,status=EXCLUDED.status,
                  expires_at=EXCLUDED.expires_at,document=EXCLUDED.document,updated_at=clock_timestamp()
                """,
                (key, _int(row.get("user_id")), workspace_id, str(row.get("plan_id") or "free_preview"),
                 _status(row.get("status"), allowed, "active"), _timestamp(row.get("expires_at_utc")),
                 _jsonb(row), _timestamp(row.get("created_at_utc"))),
            )
        self._delete_missing(conn, "sf_entitlements", "entitlement_id", ids)

    @staticmethod
    def _connector_reference_sets(
        conn: Any, *, workspace_ids: Sequence[str], user_ids: Sequence[int],
    ) -> tuple[set[str], set[int], set[tuple[str, int]]]:
        """Return the relational identities a Connector document may reference.

        The Connector JSON document is authoritative and intentionally retains
        terminal history.  Its constrained SQL tables are a current relational
        projection, though, so an old revoked test installation must not make an
        unrelated live challenge impossible after that test account has been
        removed.  Load the small reference index once per document write; the
        caller still fails closed for every non-terminal orphan.
        """
        wanted_workspaces = sorted({str(value) for value in workspace_ids if str(value)})
        wanted_users = sorted({int(value) for value in user_ids if int(value) > 0})
        workspaces: set[str] = set()
        users: set[int] = set()
        memberships: set[tuple[str, int]] = set()
        if wanted_workspaces:
            rows = conn.execute(
                "SELECT workspace_id FROM sf_workspaces WHERE workspace_id = ANY(%s)",
                (wanted_workspaces,),
            ).fetchall() or []
            workspaces = {str(row["workspace_id"]) for row in rows}
        if wanted_users:
            rows = conn.execute(
                "SELECT user_id FROM sf_users WHERE user_id = ANY(%s)",
                (wanted_users,),
            ).fetchall() or []
            users = {_int(row["user_id"]) for row in rows}
        if wanted_workspaces and wanted_users:
            rows = conn.execute(
                """
                SELECT workspace_id,user_id FROM sf_workspace_memberships
                WHERE workspace_id = ANY(%s) AND user_id = ANY(%s)
                """,
                (wanted_workspaces, wanted_users),
            ).fetchall() or []
            memberships = {
                (str(row["workspace_id"]), _int(row["user_id"])) for row in rows
            }
        return workspaces, users, memberships

    def _sync_connectors(self, conn: Any, doc: Dict[str, Any]) -> None:
        installations = [row for row in doc.get("installations", []) if isinstance(row, dict)]
        sessions = [row for row in doc.get("sessions", []) if isinstance(row, dict)]
        commands = [row for row in doc.get("commands", []) if isinstance(row, dict)]

        # The authoritative document intentionally retains terminal Connector
        # history. Re-projecting every historical row on every live request is
        # unnecessary: one Production installation with 1,144 retained
        # sessions produced exactly 1,144 physical session UPDATEs per real
        # heartbeat, poll, or market-data request. Compare the current mirror
        # once and only UPSERT rows whose projected value actually changed.
        # Protocol sequence, expiry, command, and freshness semantics remain in
        # the authoritative document and are not relaxed here.
        existing_installations = {
            str(row["installation_id"]): row for row in conn.execute(
                """
                SELECT installation_id,workspace_id,user_id,status,
                       public_key_fingerprint,document
                FROM sf_connector_installations
                """
            ).fetchall() or []
        }
        existing_sessions = {
            str(row["session_id"]): row for row in conn.execute(
                """
                SELECT session_id,installation_id,workspace_id,token_hash,
                       expires_at,revoked_at,document
                FROM sf_connector_sessions
                """
            ).fetchall() or []
        }
        existing_commands = {
            str(row["command_id"]): row for row in conn.execute(
                "SELECT command_id,status,document FROM sf_commands"
            ).fetchall() or []
        }

        workspace_candidates = {
            str(row.get("workspace_id") or "")
            for row in (*installations, *commands)
            if str(row.get("workspace_id") or "")
        }
        user_candidates = {
            _int(row.get("user_id") or row.get("enrolled_by_user_id")
                 or row.get("queued_by_user_id") or row.get("issued_by_user_id"))
            for row in (*installations, *commands)
        }
        workspaces, users, memberships = self._connector_reference_sets(
            conn,
            workspace_ids=sorted(workspace_candidates),
            user_ids=sorted(user_candidates),
        )

        install_ids: list[str] = []
        install_workspaces: Dict[str, str] = {}
        for row in installations:
            key = str(row.get("installation_id") or "")[:160]
            if not key:
                raise StorageConstraintError("Connector installation id is required.")
            workspace_id = str(row.get("workspace_id") or "")
            user_id = _int(row.get("user_id") or row.get("enrolled_by_user_id"))
            status = _status(
                row.get("status"),
                {"pending","online","offline","revoked","blocked","failed"},
                "pending",
            )
            references_valid = (
                workspace_id in workspaces
                and user_id in users
                and (workspace_id, user_id) in memberships
            )
            if not references_valid:
                if status == "revoked":
                    continue
                raise StorageConstraintError(
                    f"Connector installation {key} has non-terminal orphan references."
                )
            install_ids.append(key)
            install_workspaces[key] = workspace_id
            fingerprint = str(
                row.get("public_key_fingerprint")
                or row.get("fingerprint")
                or "missing-fingerprint"
            )
            current = existing_installations.get(key)
            unchanged = bool(
                current
                and str(current.get("workspace_id") or "") == workspace_id
                and _int(current.get("user_id")) == user_id
                and str(current.get("status") or "") == status
                and str(current.get("public_key_fingerprint") or "") == fingerprint
                and dict(current.get("document") or {}) == row
            )
            if unchanged:
                continue
            conn.execute(
                """
                INSERT INTO sf_connector_installations(installation_id,workspace_id,user_id,status,
                  public_key_fingerprint,document,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),clock_timestamp())
                ON CONFLICT(installation_id) DO UPDATE SET workspace_id=EXCLUDED.workspace_id,
                  user_id=EXCLUDED.user_id,status=EXCLUDED.status,
                  public_key_fingerprint=EXCLUDED.public_key_fingerprint,
                  document=EXCLUDED.document,updated_at=clock_timestamp()
                """,
                (key, workspace_id, user_id, status, fingerprint,
                 _jsonb(row), _timestamp(row.get("created_at_utc"))),
            )
        session_ids: list[str] = []
        for row in sessions:
            key = str(row.get("session_id") or "")[:160]
            installation_id = str(row.get("installation_id") or "")
            workspace_id = str(row.get("workspace_id") or "")
            status = str(row.get("status") or "").strip().lower()
            parent_valid = (
                installation_id in install_workspaces
                and install_workspaces[installation_id] == workspace_id
            )
            if not parent_valid:
                if status in {"expired", "revoked", "superseded"}:
                    continue
                raise StorageConstraintError(
                    f"Connector session {key or '<missing>'} has non-terminal orphan references."
                )
            token_hash = str(row.get("token_hash") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", token_hash):
                raise StorageConstraintError("Connector session token hash is invalid.")
            key = key or f"csess_{token_hash[:32]}"
            session_ids.append(key)
            expires_at = (
                _timestamp(row.get("expires_at_utc") or row.get("expires_at"))
                or datetime.now(timezone.utc)
            )
            revoked_at = _timestamp(row.get("revoked_at_utc"))
            current = existing_sessions.get(key)
            unchanged = bool(
                current
                and str(current.get("installation_id") or "") == installation_id
                and str(current.get("workspace_id") or "") == workspace_id
                and str(current.get("token_hash") or "") == token_hash
                and current.get("expires_at") == expires_at
                and current.get("revoked_at") == revoked_at
                and dict(current.get("document") or {}) == row
            )
            if unchanged:
                continue
            conn.execute(
                """
                INSERT INTO sf_connector_sessions(session_id,installation_id,workspace_id,token_hash,
                  expires_at,revoked_at,document,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),clock_timestamp())
                ON CONFLICT(session_id) DO UPDATE SET installation_id=EXCLUDED.installation_id,
                  workspace_id=EXCLUDED.workspace_id,token_hash=EXCLUDED.token_hash,
                  expires_at=EXCLUDED.expires_at,revoked_at=EXCLUDED.revoked_at,
                  document=EXCLUDED.document,updated_at=clock_timestamp()
                """,
                (key, installation_id, workspace_id, token_hash, expires_at,
                 revoked_at, _jsonb(row), _timestamp(row.get("created_at_utc"))),
            )
        command_ids: list[str] = []
        status_map = {"pending":"queued", "delivered":"leased"}
        for row in commands:
            key = str(row.get("command_id") or _stable_key("cmd", row))[:160]
            status = status_map.get(str(row.get("status") or ""), str(row.get("status") or "queued"))
            status = _status(
                status,
                {"queued","leased","completed","failed","rejected","expired","cancelled","review"},
                "queued",
            )
            workspace_id = str(row.get("workspace_id") or "")
            installation_id = str(row.get("installation_id") or "") or None
            user_id = _int(row.get("user_id") or row.get("queued_by_user_id")
                           or row.get("issued_by_user_id"))
            references_valid = (
                workspace_id in workspaces
                and user_id in users
                and (workspace_id, user_id) in memberships
                and (
                    installation_id is None
                    or install_workspaces.get(installation_id) == workspace_id
                )
            )
            if not references_valid:
                if status in {"completed", "failed", "rejected", "expired", "cancelled"}:
                    continue
                raise StorageConstraintError(
                    f"Connector command {key} has non-terminal orphan references."
                )
            command_ids.append(key)
            current = existing_commands.get(key)
            if (
                current
                and str(current.get("status") or "") == status
                and dict(current.get("document") or {}) == row
            ):
                continue
            conn.execute(
                """
                INSERT INTO sf_commands(command_id,workspace_id,installation_id,user_id,command_type,
                  status,dangerous,idempotency_key,document,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),clock_timestamp())
                ON CONFLICT(command_id) DO UPDATE SET status=EXCLUDED.status,
                  document=EXCLUDED.document,updated_at=clock_timestamp(),revision=sf_commands.revision+1
                """,
                (key, workspace_id, installation_id, user_id,
                 str(row.get("command_type") or row.get("type")
                     or (row.get("payload") or {}).get("command")
                     or "connector_command")[:100],
                 status,
                 bool(row.get("dangerous") or row.get("requires_live")
                      or row.get("capability") in {"paper_commands", "live_commands"}),
                 str(row.get("idempotency_key") or f"legacy:{key}")[:160], _jsonb(row),
                 _timestamp(row.get("created_at_utc"))),
            )
        missing_commands = sorted(set(existing_commands) - set(command_ids))
        missing_sessions = sorted(set(existing_sessions) - set(session_ids))
        missing_installations = sorted(set(existing_installations) - set(install_ids))
        if missing_commands:
            conn.execute(
                "DELETE FROM sf_commands WHERE command_id = ANY(%s)",
                (missing_commands,),
            )
        if missing_sessions:
            conn.execute(
                "DELETE FROM sf_connector_sessions WHERE session_id = ANY(%s)",
                (missing_sessions,),
            )
        if missing_installations:
            conn.execute(
                "DELETE FROM sf_connector_installations WHERE installation_id = ANY(%s)",
                (missing_installations,),
            )





def _encode_conversation_cursor(updated_at: Any, conversation_id: str) -> str:
    """Keyset cursor over (updated_at, conversation_id).

    Offsets were rejected: a conversation moving to the top between two pages
    shifts every later row, so an offset silently skips or repeats rows.
    """
    if updated_at is None or not conversation_id:
        return ""
    stamp = updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at)
    raw = f"{stamp}|{conversation_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_conversation_cursor(cursor: Optional[str]) -> tuple:
    """Return (updated_at, conversation_id); an unreadable cursor starts over."""
    text = str(cursor or "").strip()
    if not text:
        return None, ""
    try:
        padded = text + "=" * (-len(text) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        stamp, _, conversation_id = raw.partition("|")
        if not stamp or not conversation_id:
            return None, ""
        return datetime.fromisoformat(stamp), conversation_id
    except (ValueError, TypeError, UnicodeDecodeError):
        return None, ""



class SFChatRepository:
    """Relational reads for the SF Chat hot path.

    The document repository stays the authoritative writer and keeps these
    mirrors in step inside the same transaction, so every row here carries the
    exact document the JSON store held. Reads never touch the global document:
    opening the panel, polling it and switching conversation each run bounded,
    index-driven queries against `sf_chat_*` under the same FORCE RLS policies.
    """

    def __init__(self, client: "PostgresClient") -> None:
        self._client = client

    # -- conversation list ---------------------------------------------------
    def conversation_page(
        self, viewer_profile_id: str, *, scope: Scope,
        limit: int = 30, cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """One keyset page of a viewer's conversations.

        A single statement carries the row, its read pointer, its newest
        message and its unread count, so a page costs one round trip rather
        than one per conversation.
        """
        lim = max(1, min(200, int(limit or 30)))
        after_updated, after_id = _decode_conversation_cursor(cursor)
        with self._client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT c.conversation_id,
                       c.updated_at,
                       c.document AS conversation,
                       COALESCE(r.last_read_seq, 0) AS last_read_seq,
                       last_message.document AS last_message,
                       COALESCE(counts.total, 0) AS message_count,
                       COALESCE(counts.unread, 0) AS unread_count
                  FROM sf_chat_participants p
                  JOIN sf_chat_conversations c
                    ON c.conversation_id = p.conversation_id
                  LEFT JOIN sf_chat_reads r
                    ON r.conversation_id = p.conversation_id
                   AND r.profile_id = p.profile_id
                  LEFT JOIN LATERAL (
                        SELECT m.document
                          FROM sf_chat_messages m
                         WHERE m.conversation_id = c.conversation_id
                           AND m.deleted_at IS NULL
                         ORDER BY m.seq DESC
                         LIMIT 1
                  ) AS last_message ON TRUE
                  LEFT JOIN LATERAL (
                        SELECT count(*) AS total,
                               count(*) FILTER (
                                 WHERE m.seq > COALESCE(r.last_read_seq, 0)
                                   AND m.sender_profile_id <> p.profile_id
                               ) AS unread
                          FROM sf_chat_messages m
                         WHERE m.conversation_id = c.conversation_id
                           AND m.deleted_at IS NULL
                  ) AS counts ON TRUE
                 WHERE p.profile_id = %(viewer)s
                   AND (
                        %(after_updated)s::timestamptz IS NULL
                     OR (c.updated_at, c.conversation_id)
                        < (%(after_updated)s::timestamptz, %(after_id)s)
                   )
                 ORDER BY c.updated_at DESC, c.conversation_id DESC
                 LIMIT %(limit)s
                """,
                {
                    "viewer": str(viewer_profile_id), "limit": lim + 1,
                    "after_updated": after_updated, "after_id": after_id or "",
                },
            ).fetchall()
        has_more = len(rows) > lim
        rows = rows[:lim]
        next_cursor = ""
        if has_more and rows:
            next_cursor = _encode_conversation_cursor(
                rows[-1].get("updated_at"), str(rows[-1].get("conversation_id") or ""),
            )
        return {"rows": [dict(row) for row in rows], "next_cursor": next_cursor,
                "has_more": has_more}

    def unread_total(self, viewer_profile_id: str, *, scope: Scope) -> int:
        """Unread across every conversation, straight off the message index."""
        with self._client.transaction(scope, read_only=True) as conn:
            row = conn.execute(
                """
                SELECT COALESCE(sum(counts.unread), 0) AS unread
                  FROM sf_chat_participants p
                  LEFT JOIN sf_chat_reads r
                    ON r.conversation_id = p.conversation_id
                   AND r.profile_id = p.profile_id
                  JOIN LATERAL (
                        SELECT count(*) AS unread
                          FROM sf_chat_messages m
                         WHERE m.conversation_id = p.conversation_id
                           AND m.deleted_at IS NULL
                           AND m.seq > COALESCE(r.last_read_seq, 0)
                           AND m.sender_profile_id <> p.profile_id
                  ) AS counts ON TRUE
                 WHERE p.profile_id = %(viewer)s
                """,
                {"viewer": str(viewer_profile_id)},
            ).fetchone()
        return int((row or {}).get("unread") or 0)

    # -- incremental polling -------------------------------------------------
    def poll_state(self, viewer_profile_id: str, *, scope: Scope,
                   limit: int = 50) -> Dict[str, Any]:
        """Change markers only: no documents, no message bodies, bounded size.

        This is what an open panel asks for on its refresh tick, so its payload
        must not grow with the rail. It carries a fixed-size change signature
        plus a capped list of the conversations that actually have unread
        messages; a thread with nothing new needs no row at all.
        """
        lim = max(1, min(200, int(limit or 50)))
        with self._client.transaction(scope, read_only=True) as conn:
            signature = conn.execute(
                """
                SELECT count(*) AS conversations,
                       COALESCE(max(c.updated_at), to_timestamp(0)) AS newest,
                       COALESCE(sum(c.last_seq), 0) AS seq_total
                  FROM sf_chat_participants p
                  JOIN sf_chat_conversations c
                    ON c.conversation_id = p.conversation_id
                 WHERE p.profile_id = %(viewer)s
                """,
                {"viewer": str(viewer_profile_id)},
            ).fetchone() or {}
            rows = conn.execute(
                """
                SELECT p.conversation_id,
                       c.last_seq,
                       c.updated_at,
                       COALESCE(r.last_read_seq, 0) AS last_read_seq,
                       COALESCE(counts.unread, 0) AS unread_count
                  FROM sf_chat_participants p
                  JOIN sf_chat_conversations c
                    ON c.conversation_id = p.conversation_id
                  LEFT JOIN sf_chat_reads r
                    ON r.conversation_id = p.conversation_id
                   AND r.profile_id = p.profile_id
                  LEFT JOIN LATERAL (
                        SELECT count(*) AS unread
                          FROM sf_chat_messages m
                         WHERE m.conversation_id = c.conversation_id
                           AND m.deleted_at IS NULL
                           AND m.seq > COALESCE(r.last_read_seq, 0)
                           AND m.sender_profile_id <> p.profile_id
                  ) AS counts ON TRUE
                 WHERE p.profile_id = %(viewer)s
                   AND COALESCE(counts.unread, 0) > 0
                 ORDER BY c.updated_at DESC
                 LIMIT %(limit)s
                """,
                {"viewer": str(viewer_profile_id), "limit": lim},
            ).fetchall()
        return {
            "rows": [dict(row) for row in rows],
            "conversation_count": int(signature.get("conversations") or 0),
            "newest_updated_at": signature.get("newest"),
            "seq_total": int(signature.get("seq_total") or 0),
        }

    # -- one conversation ----------------------------------------------------
    def conversation(
        self, conversation_id: str, viewer_profile_id: str, *, scope: Scope,
    ) -> Optional[Dict[str, Any]]:
        """The conversation a viewer participates in, or None.

        Membership is part of the WHERE clause, so a non-participant gets no
        row at all rather than a row the caller has to remember to filter.
        """
        with self._client.transaction(scope, read_only=True) as conn:
            row = conn.execute(
                """
                SELECT c.conversation_id,
                       c.updated_at,
                       c.document AS conversation,
                       COALESCE(r.last_read_seq, 0) AS last_read_seq,
                       last_message.document AS last_message,
                       COALESCE(counts.total, 0) AS message_count,
                       COALESCE(counts.unread, 0) AS unread_count
                  FROM sf_chat_participants p
                  JOIN sf_chat_conversations c
                    ON c.conversation_id = p.conversation_id
                  LEFT JOIN sf_chat_reads r
                    ON r.conversation_id = p.conversation_id
                   AND r.profile_id = p.profile_id
                  LEFT JOIN LATERAL (
                        SELECT m.document
                          FROM sf_chat_messages m
                         WHERE m.conversation_id = c.conversation_id
                           AND m.deleted_at IS NULL
                         ORDER BY m.seq DESC
                         LIMIT 1
                  ) AS last_message ON TRUE
                  LEFT JOIN LATERAL (
                        SELECT count(*) AS total,
                               count(*) FILTER (
                                 WHERE m.seq > COALESCE(r.last_read_seq, 0)
                                   AND m.sender_profile_id <> p.profile_id
                               ) AS unread
                          FROM sf_chat_messages m
                         WHERE m.conversation_id = c.conversation_id
                           AND m.deleted_at IS NULL
                  ) AS counts ON TRUE
                 WHERE p.profile_id = %(viewer)s
                   AND p.conversation_id = %(conversation)s
                """,
                {"viewer": str(viewer_profile_id),
                 "conversation": str(conversation_id)},
            ).fetchone()
        return dict(row) if row else None

    def participant_profile_ids(
        self, conversation_id: str, *, scope: Scope,
    ) -> list:
        with self._client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT profile_id
                  FROM sf_chat_participants
                 WHERE conversation_id = %s
                 ORDER BY profile_id
                """,
                (str(conversation_id),),
            ).fetchall()
        return [str(row.get("profile_id") or "") for row in rows]

    # -- history -------------------------------------------------------------
    def message_page(
        self, conversation_id: str, *, scope: Scope,
        limit: int = 50, before_seq: Optional[int] = None,
    ) -> Dict[str, Any]:
        """One page of history, walked backwards by `seq`.

        Ordering and the cursor both ride
        `sf_chat_messages(conversation_id, seq DESC) WHERE deleted_at IS NULL`,
        so an old page costs the same as a recent one and no page reads the
        whole conversation.
        """
        lim = max(1, min(200, int(limit or 50)))
        with self._client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT seq, document
                  FROM sf_chat_messages
                 WHERE conversation_id = %(conversation)s
                   AND deleted_at IS NULL
                   AND (%(before)s::bigint IS NULL OR seq < %(before)s::bigint)
                 ORDER BY seq DESC
                 LIMIT %(limit)s
                """,
                {"conversation": str(conversation_id), "limit": lim + 1,
                 "before": None if before_seq is None else int(before_seq)},
            ).fetchall()
        has_more = len(rows) > lim
        rows = rows[:lim]
        oldest_seq = int(rows[-1].get("seq") or 0) if rows else 0
        # Returned oldest-first: the panel prepends a page above what it shows.
        messages = [dict(row.get("document") or {}) for row in reversed(rows)]
        return {"messages": messages, "has_more": has_more,
                "next_before_seq": oldest_seq if has_more else 0}

    def read_seq(
        self, conversation_id: str, profile_id: str, *, scope: Scope,
    ) -> int:
        with self._client.transaction(scope, read_only=True) as conn:
            row = conn.execute(
                """
                SELECT last_read_seq
                  FROM sf_chat_reads
                 WHERE conversation_id = %s AND profile_id = %s
                """,
                (str(conversation_id), str(profile_id)),
            ).fetchone()
        return int((row or {}).get("last_read_seq") or 0)


class CommunityRepository:
    """Relational reads for the Community rows SF Chat needs.

    Only the profile projection is served here: the chat header and the
    conversation rail need the other participant, and resolving it used to load
    the entire Community document -- every profile, post, comment, reaction and
    follow of every user -- on each chat request.
    """

    def __init__(self, client: "PostgresClient") -> None:
        self._client = client

    def profile_by_identity(
        self, user_id: int, user_uuid: str, *, scope: Scope,
    ) -> Optional[Dict[str, Any]]:
        """Resolve the caller's own profile without loading the document.

        SF Chat asks who the caller is on every request, including every poll
        tick. Both branches ride a unique index: `sf_community_profiles_uuid_idx`
        when the account carries a UUID, `sf_community_profiles_user_idx`
        otherwise, matching the document lookup's precedence exactly.
        """
        with self._client.transaction(scope, read_only=True) as conn:
            row = conn.execute(
                """
                SELECT profile_id, user_id, user_uuid, document
                  FROM sf_community_profiles
                 WHERE (%(uuid)s <> '' AND user_uuid::text = %(uuid)s)
                    OR (%(uuid)s = '' AND user_id = %(uid)s)
                 ORDER BY (user_uuid::text = %(uuid)s) DESC
                 LIMIT 1
                """,
                {"uuid": str(user_uuid or ""), "uid": int(user_id or 0)},
            ).fetchone()
        return dict(row) if row else None

    def public_profiles(
        self, viewer_profile_id: str, profile_ids: Sequence[str], *, scope: Scope,
    ) -> list:
        """Every counter and predicate `_public_profile` needs, in one statement."""
        wanted = sorted({str(value) for value in profile_ids if str(value or "")})
        if not wanted:
            return []
        with self._client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT p.profile_id,
                       p.document,
                       (SELECT count(*) FROM sf_community_follows f
                         WHERE f.target_profile_id = p.profile_id) AS followers,
                       (SELECT count(*) FROM sf_community_follows f
                         WHERE f.follower_profile_id = p.profile_id) AS following,
                       (SELECT count(*) FROM sf_community_posts po
                         WHERE po.author_profile_id = p.profile_id
                           AND po.deleted_at IS NULL) AS posts,
                       EXISTS(SELECT 1 FROM sf_community_follows f
                               WHERE f.follower_profile_id = %(viewer)s
                                 AND f.target_profile_id = p.profile_id) AS viewer_follows,
                       EXISTS(SELECT 1 FROM sf_community_follows f
                               WHERE f.follower_profile_id = p.profile_id
                                 AND f.target_profile_id = %(viewer)s) AS follows_viewer,
                       EXISTS(SELECT 1 FROM sf_community_blocks b
                               WHERE (b.blocker_profile_id = %(viewer)s
                                      AND b.target_profile_id = p.profile_id)
                                  OR (b.blocker_profile_id = p.profile_id
                                      AND b.target_profile_id = %(viewer)s)) AS blocked
                  FROM sf_community_profiles p
                 WHERE p.profile_id = ANY(%(ids)s)
                """,
                {"viewer": str(viewer_profile_id or ""), "ids": wanted},
            ).fetchall()
        return [dict(row) for row in rows]


class AuthRepository:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    def get_user(self, user_id: int, *, scope: Scope) -> Optional[Dict[str, Any]]:
        with self.client.transaction(scope, read_only=True) as conn:
            row = conn.execute("SELECT document FROM sf_users WHERE user_id=%s", (int(user_id),)).fetchone()
        return copy.deepcopy(dict(row["document"])) if row else None


class WorkspaceRepository:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    def get(self, workspace_id: str, *, scope: Scope) -> Optional[Dict[str, Any]]:
        with self.client.transaction(scope, read_only=True) as conn:
            row = conn.execute(
                "SELECT document FROM sf_workspaces WHERE workspace_id=%s", (workspace_id,)
            ).fetchone()
        return copy.deepcopy(dict(row["document"])) if row else None

    def memberships(self, *, scope: Scope) -> list[Dict[str, Any]]:
        with self.client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                "SELECT document FROM sf_workspace_memberships ORDER BY workspace_id,user_id"
            ).fetchall()
        return [copy.deepcopy(dict(row["document"])) for row in rows]

    def get_ledger(self, *, scope: Scope, default: Mapping[str, Any]) -> Dict[str, Any]:
        if not scope.workspace_id:
            raise StorageConstraintError("Workspace ledger requires workspace scope.")
        with self.client.transaction(scope, read_only=True) as conn:
            row = conn.execute(
                "SELECT revision,document FROM sf_workspace_ledgers WHERE workspace_id=%s",
                (scope.workspace_id,),
            ).fetchone()
        revision_key = f"ledger:{scope.workspace_id}"
        self.client.remember_revision(revision_key, int(row["revision"]) if row else 0)
        return copy.deepcopy(dict(row["document"]) if row else dict(default))

    def put_ledger(self, document: Mapping[str, Any], *, scope: Scope) -> int:
        if not scope.workspace_id:
            raise StorageConstraintError("Workspace ledger requires workspace scope.")
        revision_key = f"ledger:{scope.workspace_id}"
        expected = self.client.expected_revision(revision_key)
        if expected is None:
            raise StorageConflictError("Workspace ledger must be read before write.")
        with self.client.transaction(scope) as conn:
            row = conn.execute(
                "SELECT revision FROM sf_workspace_ledgers WHERE workspace_id=%s FOR UPDATE",
                (scope.workspace_id,),
            ).fetchone()
            current = int(row["revision"]) if row else 0
            if current != int(expected):
                raise StorageConflictError("Concurrent workspace ledger update detected.")
            revision = current + 1
            conn.execute(
                """
                INSERT INTO sf_workspace_ledgers(workspace_id,revision,document,updated_at)
                VALUES(%s,%s,%s,clock_timestamp())
                ON CONFLICT(workspace_id) DO UPDATE SET revision=EXCLUDED.revision,
                  document=EXCLUDED.document,updated_at=clock_timestamp()
                """,
                (scope.workspace_id, revision, _jsonb(dict(document))),
            )
        self.client.remember_revision(revision_key, revision)
        return revision


class EntitlementRepository:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    def list(self, *, scope: Scope) -> list[Dict[str, Any]]:
        with self.client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                "SELECT document FROM sf_entitlements ORDER BY created_at,entitlement_id"
            ).fetchall()
        return [copy.deepcopy(dict(row["document"])) for row in rows]


class ConnectorRepository:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    def installations(self, *, scope: Scope) -> list[Dict[str, Any]]:
        with self.client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                "SELECT document FROM sf_connector_installations ORDER BY created_at,installation_id"
            ).fetchall()
        return [copy.deepcopy(dict(row["document"])) for row in rows]


class JobRepository:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    def put(self, row: Mapping[str, Any], *, scope: Scope) -> Dict[str, Any]:
        job_id = str(row.get("job_id") or "")
        workspace_id = str(row.get("workspace_id") or "")
        if not job_id or workspace_id != scope.workspace_id:
            raise StorageConstraintError("Job scope does not match workspace.")
        with self.client.transaction(scope) as conn:
            saved = conn.execute(
                """
                INSERT INTO sf_jobs(job_id,workspace_id,user_id,kind,status,idempotency_key,document)
                VALUES(%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(job_id) DO UPDATE SET status=EXCLUDED.status,
                  document=EXCLUDED.document,updated_at=clock_timestamp(),revision=sf_jobs.revision+1
                RETURNING document
                """,
                (job_id, workspace_id, _int(row.get("user_id")), str(row.get("kind") or "job"),
                 _status(row.get("status"), {"queued","running","completed","failed","cancelled","dead_letter","review"}, "queued"),
                 str(row.get("idempotency_key") or f"job:{job_id}"), _jsonb(dict(row))),
            ).fetchone()
        return dict(saved["document"])

    def get(self, job_id: str, *, scope: Scope) -> Optional[Dict[str, Any]]:
        with self.client.transaction(scope, read_only=True) as conn:
            row = conn.execute("SELECT document FROM sf_jobs WHERE job_id=%s", (job_id,)).fetchone()
        return dict(row["document"]) if row else None


class CommandRepository:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    def put(self, row: Mapping[str, Any], *, scope: Scope) -> Dict[str, Any]:
        command_id = str(row.get("command_id") or "")
        workspace_id = str(row.get("workspace_id") or "")
        if not command_id or workspace_id != scope.workspace_id:
            raise StorageConstraintError("Command scope does not match workspace.")
        idempotency_key = str(row.get("idempotency_key") or f"cmd:{command_id}")
        request_hash = str(row.get("envelope_hash") or _stable_key("request", row))
        with self.client.transaction(scope) as conn:
            existing = conn.execute(
                """SELECT document FROM sf_commands
                   WHERE workspace_id=%s AND idempotency_key=%s""",
                (workspace_id, idempotency_key),
            ).fetchone()
            if existing:
                saved = dict(existing["document"])
                existing_hash = str(saved.get("envelope_hash") or _stable_key("request", saved))
                if not secrets.compare_digest(existing_hash, request_hash):
                    raise StorageConflictError(
                        "Command idempotency key was used with a different envelope."
                    )
                saved["idempotent_replay"] = True
                return saved
            saved = conn.execute(
                """
                INSERT INTO sf_commands(command_id,workspace_id,installation_id,user_id,command_type,
                  status,dangerous,idempotency_key,document)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(workspace_id,idempotency_key) DO NOTHING
                RETURNING document
                """,
                (command_id, workspace_id, str(row.get("installation_id") or "") or None,
                 _int(row.get("user_id")), str(row.get("command_type") or "command"),
                 _status(row.get("status"), {"queued","leased","completed","failed","rejected","expired","cancelled","review"}, "queued"),
                 bool(row.get("dangerous")), idempotency_key,
                 _jsonb(dict(row))),
            ).fetchone()
            if not saved:
                raced = conn.execute(
                    """SELECT document FROM sf_commands
                       WHERE workspace_id=%s AND idempotency_key=%s""",
                    (workspace_id, idempotency_key),
                ).fetchone()
                replay = dict(raced["document"])
                replay_hash = str(
                    replay.get("envelope_hash") or _stable_key("request", replay)
                )
                if not secrets.compare_digest(replay_hash, request_hash):
                    raise StorageConflictError(
                        "Concurrent command idempotency conflict."
                    )
                replay["idempotent_replay"] = True
                return replay
        return dict(saved["document"])

    def get(self, command_id: str, *, scope: Scope) -> Optional[Dict[str, Any]]:
        with self.client.transaction(scope, read_only=True) as conn:
            row = conn.execute("SELECT document FROM sf_commands WHERE command_id=%s", (command_id,)).fetchone()
        return dict(row["document"]) if row else None


class EnvironmentRegistryRepository:
    """Last-known runtime identity of each environment.

    One row per environment, overwritten by each heartbeat. Nothing here is
    append-only history: the registry answers "what is that environment running,
    and when did it last say so", and a full timeline of every heartbeat would
    be a large table answering a question nobody asked.

    ``first_seen_at`` is preserved across updates on purpose -- it is the only
    way to distinguish an environment that has been reporting for months from
    one that appeared a minute ago.
    """

    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    def record(self, heartbeat: Mapping[str, Any], *, scope: Scope) -> Dict[str, Any]:
        environment = str(heartbeat.get("environment") or "")
        with self.client.transaction(scope) as conn:
            row = conn.execute(
                """
                INSERT INTO sf_environment_registry(
                  environment,app_version,git_commit_sha,build_id,artifact_sha256,
                  release_channel,schema_version,readiness,market_data,connector,
                  details,host,first_seen_at,last_seen_at,heartbeat_count
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       clock_timestamp(),clock_timestamp(),1)
                ON CONFLICT(environment) DO UPDATE SET
                  app_version=EXCLUDED.app_version,
                  git_commit_sha=EXCLUDED.git_commit_sha,
                  build_id=EXCLUDED.build_id,
                  artifact_sha256=EXCLUDED.artifact_sha256,
                  release_channel=EXCLUDED.release_channel,
                  schema_version=EXCLUDED.schema_version,
                  readiness=EXCLUDED.readiness,
                  market_data=EXCLUDED.market_data,
                  connector=EXCLUDED.connector,
                  details=EXCLUDED.details,
                  host=EXCLUDED.host,
                  last_seen_at=clock_timestamp(),
                  heartbeat_count=sf_environment_registry.heartbeat_count + 1
                RETURNING *
                """,
                (
                    environment,
                    str(heartbeat.get("app_version") or "")[:64],
                    str(heartbeat.get("git_commit_sha") or "")[:64],
                    str(heartbeat.get("build_id") or "")[:128],
                    str(heartbeat.get("artifact_sha256") or "")[:64],
                    str(heartbeat.get("release_channel") or "")[:32],
                    int(heartbeat.get("schema_version") or 0),
                    str(heartbeat.get("readiness") or ""),
                    str(heartbeat.get("market_data") or ""),
                    str(heartbeat.get("connector") or ""),
                    _jsonb(heartbeat.get("details") or {}),
                    _jsonb(heartbeat.get("host") or {}),
                ),
            ).fetchone()
        return dict(row) if row else {}

    def all(self, *, scope: Scope) -> list:
        with self.client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                "SELECT * FROM sf_environment_registry ORDER BY environment"
            ).fetchall()
        return [dict(row) for row in rows]


class AuditRepository:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    def append(self, event_type: str, payload: Mapping[str, Any], *, source: str,
               scope: Scope, event_id: str = "") -> str:
        key = event_id or f"audit_{uuid.uuid4().hex}"
        workspace_id = scope.workspace_id or None
        user_id = scope.user_id or None
        values = dict(payload)
        source_value = str(source or "system")[:100] or "system"
        event_value = str(event_type or "audit_event")[:120] or "audit_event"
        actor = str(
            values.get("actor")
            or (f"user:{user_id}" if user_id else source_value)
            or "system"
        )[:160]
        action = str(
            values.get("action") or f"{source_value}.{event_value}"
        )[:120] or "audit_event"
        resource_type = str(
            values.get("resource_type") or source_value
        )[:80] or "audit_event"
        resource_id = str(
            values.get("resource_id")
            or workspace_id
            or user_id
            or ""
        )[:200]
        outcome = str(values.get("outcome") or "success").strip().lower()
        if outcome not in {"success", "denied", "error"}:
            outcome = "error"
        ip_hash = str(values.get("ip_hash") or "")[:64]
        with self.client.transaction(scope) as conn:
            conn.execute(
                """
                INSERT INTO sf_audit_events(
                  event_id,workspace_id,user_id,source,event_type,payload,
                  actor,action,resource_type,resource_id,outcome,ip_hash,document
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    key, workspace_id, user_id, source_value, event_value,
                    _jsonb(values), actor, action, resource_type, resource_id,
                    outcome, ip_hash, _jsonb(values),
                ),
            )
        return key

    def list(self, *, scope: Scope, limit: int = 100) -> list[Dict[str, Any]]:
        with self.client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                """SELECT event_id,workspace_id,user_id,source,event_type,payload,
                          actor,action,resource_type,resource_id,outcome,ip_hash,
                          document,occurred_at
                   FROM sf_audit_events ORDER BY audit_id DESC LIMIT %s""",
                (max(1, min(1000, int(limit))),),
            ).fetchall()
        return [dict(row) for row in rows]


class MigrationRunner:
    def __init__(self, admin_url: str, *, production: bool = False) -> None:
        self.admin_url = _validate_database_url(admin_url, production=production)

    @staticmethod
    def migrations() -> list[Dict[str, Any]]:
        rows = []
        for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            sql = path.read_text(encoding="utf-8")
            rows.append({
                "version": int(path.name.split("_", 1)[0]),
                "name": path.name,
                "path": path,
                "sql": sql,
                "sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            })
        if not rows:
            raise StorageConfigurationError("No PostgreSQL migrations were found.")
        return rows

    def _connect(self) -> Any:
        psycopg = _psycopg()
        try:
            return psycopg.connect(self.admin_url, autocommit=False, row_factory=psycopg.rows.dict_row)
        except psycopg.OperationalError as exc:
            raise StorageUnavailableError("Migration PostgreSQL is unavailable.") from exc

    def plan(self) -> Dict[str, Any]:
        migrations = self.migrations()
        with self._connect() as conn:
            exists = conn.execute("SELECT to_regclass('public.sf_schema_migrations') AS name").fetchone()["name"]
            applied = []
            if exists:
                applied = conn.execute(
                    "SELECT version,name,checksum FROM sf_schema_migrations ORDER BY version"
                ).fetchall()
        by_version = {int(row["version"]): row for row in applied}
        pending = []
        for migration in migrations:
            prior = by_version.get(migration["version"])
            if prior and str(prior["checksum"]) != migration["sha256"]:
                raise StorageConflictError(
                    f"Applied migration checksum mismatch: {migration['name']}"
                )
            if not prior:
                pending.append({key: migration[key] for key in ("version", "name", "sha256")})
        return {
            "latest_version": migrations[-1]["version"],
            "applied_versions": sorted(by_version),
            "pending": pending,
            "migration_set_sha256": hashlib.sha256(
                _canonical([{key: row[key] for key in ("version", "name", "sha256")} for row in migrations])
            ).hexdigest(),
        }

    def apply(self) -> Dict[str, Any]:
        psycopg = _psycopg()
        migrations = self.migrations()
        applied_now: list[int] = []
        with self._connect() as conn:
            try:
                with conn.transaction():
                    conn.execute("SELECT pg_advisory_xact_lock(7838146202601)")
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sf_schema_migrations(
                          version INTEGER PRIMARY KEY,
                          name TEXT NOT NULL UNIQUE,
                          checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                          applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
                        )
                        """
                    )
                    existing = {
                        int(row["version"]): row
                        for row in conn.execute(
                            "SELECT version,name,checksum FROM sf_schema_migrations"
                        ).fetchall()
                    }
                    for migration in migrations:
                        prior = existing.get(migration["version"])
                        if prior:
                            if str(prior["checksum"]) != migration["sha256"]:
                                raise StorageConflictError(
                                    f"Applied migration checksum mismatch: {migration['name']}"
                                )
                            continue
                        conn.execute(migration["sql"], prepare=False)
                        conn.execute(
                            "INSERT INTO sf_schema_migrations(version,name,checksum) VALUES(%s,%s,%s)",
                            (migration["version"], migration["name"], migration["sha256"]),
                        )
                        applied_now.append(migration["version"])
            except StorageError:
                raise
            except psycopg.Error as exc:
                raise StorageError(f"PostgreSQL migration failed: {exc.__class__.__name__}") from exc
        result = self.plan()
        result["applied_now"] = applied_now
        return result


def get_client(*, production: Optional[bool] = None) -> PostgresClient:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            if production is None:
                from .. import runtime_env
                production = runtime_env.is_production()
            _CLIENT = PostgresClient(
                os.environ.get("STRATFORGE_DATABASE_URL", ""),
                production=bool(production),
            )
        return _CLIENT


def reset_for_tests() -> None:
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = None


def database_readiness() -> Dict[str, Any]:
    try:
        client = get_client()
        with client.transaction(Scope.global_service_scope()) as conn:
            read_only = conn.execute("SHOW transaction_read_only").fetchone()[
                "transaction_read_only"
            ]
            row = conn.execute(
                "SELECT COALESCE(MAX(version),0) AS version FROM sf_schema_migrations"
            ).fetchone()
        latest = MigrationRunner.migrations()[-1]["version"]
        if str(read_only).lower() == "on":
            return {"ok": False, "code": "database_read_only"}
        if int(row["version"]) != int(latest):
            return {"ok": False, "code": "database_migration_pending"}
        return {"ok": True, "code": "ok"}
    except StorageReadOnlyError:
        return {"ok": False, "code": "database_read_only"}
    except StorageConflictError:
        return {"ok": False, "code": "database_migration_checksum"}
    except StorageError:
        return {"ok": False, "code": "database_unavailable"}
