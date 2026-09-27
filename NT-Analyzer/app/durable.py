"""Small SQLite WAL durability layer for local-first metadata.

The file queue remains the compatibility boundary with the NinjaTrader bridge.
This module adds an indexed, recoverable metadata contract around that queue so
the backend can survive restarts without treating the filesystem as the only DB.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import runtime_env


SCHEMA_VERSION = 3
DEFAULT_DB_NAME = "nt_analyzer.sqlite3"
_LOCK = threading.RLock()


def project_root() -> Path:
    env = os.environ.get("NT_ANALYZER_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def db_path(root: Optional[Path] = None) -> Path:
    override = os.environ.get("NT_ANALYZER_SQLITE_PATH")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(root or project_root()).resolve()
    return runtime_env.data_path("durable", DEFAULT_DB_NAME, project_root=base)


class _ClosingConnection(sqlite3.Connection):
    """Close transaction-scoped handles deterministically (required on Windows)."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(root: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _ensure_schema(conn)
    return conn


def init(root: Optional[Path] = None) -> Path:
    with _LOCK:
        with connect(root):
            return db_path(root)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
          job_id TEXT PRIMARY KEY,
          workspace_id TEXT NOT NULL DEFAULT '',
          user_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT '',
          class_name TEXT NOT NULL DEFAULT '',
          instrument TEXT NOT NULL DEFAULT '',
          timeframe TEXT NOT NULL DEFAULT '',
          created_at_utc TEXT NOT NULL DEFAULT '',
          updated_at_utc TEXT NOT NULL DEFAULT '',
          finished_at_utc TEXT NOT NULL DEFAULT '',
          path TEXT NOT NULL DEFAULT '',
          dir_mtime REAL NOT NULL DEFAULT 0,
          origin_json TEXT NOT NULL DEFAULT '{}',
          job_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_workspace_status
          ON jobs(workspace_id, status, updated_at_utc);
        CREATE INDEX IF NOT EXISTS idx_jobs_status_updated
          ON jobs(status, updated_at_utc);

        CREATE TABLE IF NOT EXISTS chat_conversations (
          scope_id TEXT NOT NULL DEFAULT '',
          conversation_id TEXT NOT NULL,
          user_id TEXT NOT NULL DEFAULT '',
                    user_uuid TEXT NOT NULL DEFAULT '',
          workspace_id TEXT NOT NULL DEFAULT '',
          membership_role TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '',
          message_count INTEGER NOT NULL DEFAULT 0,
          work_state TEXT NOT NULL DEFAULT '',
          closed INTEGER NOT NULL DEFAULT 0,
          created_at_utc TEXT NOT NULL DEFAULT '',
          updated_at_utc TEXT NOT NULL DEFAULT '',
          path TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(scope_id, conversation_id)
        );
        CREATE INDEX IF NOT EXISTS idx_chat_workspace_updated
          ON chat_conversations(workspace_id, updated_at_utc);

        CREATE TABLE IF NOT EXISTS telemetry_files (
          name TEXT PRIMARY KEY,
          path TEXT NOT NULL DEFAULT '',
          size_bytes INTEGER NOT NULL DEFAULT 0,
          mtime_ns INTEGER NOT NULL DEFAULT 0,
          first_seen_utc TEXT NOT NULL DEFAULT '',
          updated_at_utc TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS worker_jobs (
          worker_job_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          status TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 100,
          attempts INTEGER NOT NULL DEFAULT 0,
          max_attempts INTEGER NOT NULL DEFAULT 1,
          timeout_sec INTEGER NOT NULL DEFAULT 300,
          queued_at_utc TEXT NOT NULL DEFAULT '',
          started_at_utc TEXT NOT NULL DEFAULT '',
          finished_at_utc TEXT NOT NULL DEFAULT '',
          updated_at_utc TEXT NOT NULL DEFAULT '',
          locked_until REAL NOT NULL DEFAULT 0,
          deadline_at REAL NOT NULL DEFAULT 0,
          worker_id TEXT NOT NULL DEFAULT '',
          heartbeat_at_utc TEXT NOT NULL DEFAULT '',
          cancel_requested INTEGER NOT NULL DEFAULT 0,
          user_id TEXT NOT NULL DEFAULT '',
          workspace_id TEXT NOT NULL DEFAULT '',
          payload_json TEXT NOT NULL DEFAULT '{}',
          result_json TEXT NOT NULL DEFAULT '{}',
          error TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_worker_jobs_status_priority
          ON worker_jobs(status, priority, queued_at_utc);
        CREATE INDEX IF NOT EXISTS idx_worker_jobs_workspace_status
          ON worker_jobs(workspace_id, status, updated_at_utc);
        """
    )
    # ``CREATE TABLE IF NOT EXISTS`` does not evolve an existing v1 WAL.
    # Keep the migration additive so production metadata upgrades in place.
    worker_columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(worker_jobs)").fetchall()
    }
    for name, definition in (
        ("deadline_at", "REAL NOT NULL DEFAULT 0"),
        ("worker_id", "TEXT NOT NULL DEFAULT ''"),
        ("heartbeat_at_utc", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in worker_columns:
            conn.execute(f"ALTER TABLE worker_jobs ADD COLUMN {name} {definition}")
    chat_columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(chat_conversations)").fetchall()
    }
    if "user_uuid" not in chat_columns:
        conn.execute("ALTER TABLE chat_conversations ADD COLUMN user_uuid TEXT NOT NULL DEFAULT ''")
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"


def _row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    out = dict(row)
    for key in ("origin_json", "job_json"):
        if key in out:
            try:
                out[key[:-5]] = json.loads(out.get(key) or "{}")
            except (TypeError, ValueError):
                out[key[:-5]] = {}
    return out


def record_job(root: Optional[Path], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert one job metadata row.

    Expected payload keys are intentionally plain dict fields so callers can
    pass normalized data without depending on a dataclass contract.
    """
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id required")
    with _LOCK:
        with connect(root) as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                  job_id, workspace_id, user_id, status, kind, class_name,
                  instrument, timeframe, created_at_utc, updated_at_utc,
                  finished_at_utc, path, dir_mtime, origin_json, job_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id) DO UPDATE SET
                  workspace_id=excluded.workspace_id,
                  user_id=excluded.user_id,
                  status=excluded.status,
                  kind=excluded.kind,
                  class_name=excluded.class_name,
                  instrument=excluded.instrument,
                  timeframe=excluded.timeframe,
                  created_at_utc=COALESCE(NULLIF(excluded.created_at_utc,''), jobs.created_at_utc),
                  updated_at_utc=excluded.updated_at_utc,
                  finished_at_utc=excluded.finished_at_utc,
                  path=excluded.path,
                  dir_mtime=excluded.dir_mtime,
                  origin_json=excluded.origin_json,
                  job_json=excluded.job_json
                """,
                (
                    job_id,
                    str(payload.get("workspace_id") or ""),
                    str(payload.get("user_id") or ""),
                    str(payload.get("status") or "unknown"),
                    str(payload.get("kind") or ""),
                    str(payload.get("class_name") or ""),
                    str(payload.get("instrument") or ""),
                    str(payload.get("timeframe") or ""),
                    str(payload.get("created_at_utc") or ""),
                    str(payload.get("updated_at_utc") or payload.get("created_at_utc") or ""),
                    str(payload.get("finished_at_utc") or ""),
                    str(payload.get("path") or ""),
                    float(payload.get("dir_mtime") or 0.0),
                    _compact_json(payload.get("origin")),
                    _compact_json(payload.get("job")),
                ),
            )
            conn.commit()
    row = get_job(root, job_id)
    return row or {"job_id": job_id}


def get_job(root: Optional[Path], job_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        with connect(root) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (str(job_id),)).fetchone()
    return _row_dict(row) if row else None


def list_jobs(root: Optional[Path], *, status: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(1000, int(limit or 100)))
    with _LOCK:
        with connect(root) as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status=? ORDER BY updated_at_utc DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY updated_at_utc DESC LIMIT ?",
                    (limit,),
                ).fetchall()
    return [_row_dict(row) for row in rows]


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return dict(doc) if isinstance(doc, dict) else {}


def _job_payload_from_dir(status: str, job_dir: Path) -> Dict[str, Any]:
    job_doc = _read_json(job_dir / "job.json")
    result_doc = _read_json(job_dir / "result.json")
    strategy = job_doc.get("strategy") if isinstance(job_doc.get("strategy"), dict) else {}
    timeframe = job_doc.get("timeframe") if isinstance(job_doc.get("timeframe"), dict) else {}
    execution = job_doc.get("execution") if isinstance(job_doc.get("execution"), dict) else {}
    origin = job_doc.get("origin") if isinstance(job_doc.get("origin"), dict) else {}
    try:
        mtime = job_dir.stat().st_mtime
    except OSError:
        mtime = 0.0
    tf_value = timeframe.get("value") if isinstance(timeframe, dict) else ""
    tf_type = timeframe.get("bars_period_type") if isinstance(timeframe, dict) else ""
    return {
        "job_id": job_doc.get("job_id") or job_dir.name,
        "workspace_id": origin.get("workspace_id") or job_doc.get("workspace_id") or "",
        "user_id": origin.get("user_id") or job_doc.get("user_id") or "",
        "status": str(result_doc.get("status") or status),
        "kind": job_doc.get("kind") or "",
        "class_name": strategy.get("class_name") or "",
        "instrument": job_doc.get("instrument") or "",
        "timeframe": f"{tf_value} {tf_type}".strip(),
        "created_at_utc": job_doc.get("created_at_utc") or "",
        "updated_at_utc": (
            result_doc.get("finished_at_utc")
            or result_doc.get("updated_at_utc")
            or job_doc.get("created_at_utc")
            or ""
        ),
        "finished_at_utc": result_doc.get("finished_at_utc") or "",
        "path": str(job_dir),
        "dir_mtime": mtime,
        "origin": origin,
        "job": {
            "strategy": strategy,
            "execution": execution,
            "batch": job_doc.get("batch") if isinstance(job_doc.get("batch"), dict) else {},
        },
    }


def sweep_job_queue(root: Optional[Path], jobs_root: Path,
                    statuses: Iterable[str]) -> Dict[str, Any]:
    """Rebuild/update the durable job index from queue folders."""
    counts: Dict[str, int] = {}
    indexed = 0
    for status in statuses:
        d = jobs_root / status
        if not d.is_dir():
            counts[status] = 0
            continue
        count = 0
        for child in d.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            record_job(root, _job_payload_from_dir(status, child))
            count += 1
            indexed += 1
        counts[status] = count
    return {"ok": True, "indexed": indexed, "counts": counts, "db_path": str(db_path(root))}


def record_chat_conversation(root: Optional[Path], payload: Dict[str, Any]) -> Dict[str, Any]:
    conversation_id = str(payload.get("conversation_id") or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id required")
    scope_id = str(payload.get("scope_id") or payload.get("conversation_scope_id") or "")
    with _LOCK:
        with connect(root) as conn:
            conn.execute(
                """
                INSERT INTO chat_conversations(
                                    scope_id, conversation_id, user_id, user_uuid, workspace_id,
                  membership_role, title, message_count, work_state, closed,
                  created_at_utc, updated_at_utc, path
                                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(scope_id, conversation_id) DO UPDATE SET
                  user_id=excluded.user_id,
                                    user_uuid=excluded.user_uuid,
                  workspace_id=excluded.workspace_id,
                  membership_role=excluded.membership_role,
                  title=excluded.title,
                  message_count=excluded.message_count,
                  work_state=excluded.work_state,
                  closed=excluded.closed,
                  created_at_utc=COALESCE(NULLIF(excluded.created_at_utc,''), chat_conversations.created_at_utc),
                  updated_at_utc=excluded.updated_at_utc,
                  path=excluded.path
                """,
                (
                    scope_id,
                    conversation_id,
                    str(payload.get("user_id") or ""),
                    str(payload.get("user_uuid") or ""),
                    str(payload.get("workspace_id") or ""),
                    str(payload.get("membership_role") or ""),
                    str(payload.get("title") or ""),
                    int(payload.get("message_count") or 0),
                    str(payload.get("work_state") or ""),
                    1 if payload.get("closed") else 0,
                    str(payload.get("created_at_utc") or ""),
                    str(payload.get("updated_at_utc") or ""),
                    str(payload.get("path") or ""),
                ),
            )
            conn.commit()
    return get_chat_conversation(root, conversation_id, scope_id=scope_id) or {
        "scope_id": scope_id,
        "conversation_id": conversation_id,
    }


def get_chat_conversation(root: Optional[Path], conversation_id: str,
                          *, scope_id: str = "") -> Optional[Dict[str, Any]]:
    with _LOCK:
        with connect(root) as conn:
            row = conn.execute(
                "SELECT * FROM chat_conversations WHERE scope_id=? AND conversation_id=?",
                (str(scope_id or ""), str(conversation_id)),
            ).fetchone()
    return dict(row) if row else None


def find_chat_conversation(root: Optional[Path], conversation_id: str,
                           *, prefer_scoped: bool = True) -> Optional[Dict[str, Any]]:
    """Find a conversation when an external transport only knows its id.

    Telegram topics predate workspace-scoped chat storage and carry only the
    conversation id. Prefer an owner/scoped row so incoming topic messages are
    appended to the same transcript the authenticated app is displaying,
    instead of silently creating a legacy unscoped duplicate.
    """
    cid = str(conversation_id or "").strip()
    if not cid:
        return None
    order = (
        "CASE WHEN scope_id<>'' THEN 0 ELSE 1 END, "
        "CASE WHEN membership_role='owner' THEN 0 ELSE 1 END, updated_at_utc DESC"
        if prefer_scoped else "updated_at_utc DESC"
    )
    with _LOCK:
        with connect(root) as conn:
            row = conn.execute(
                f"SELECT * FROM chat_conversations WHERE conversation_id=? ORDER BY {order} LIMIT 1",
                (cid,),
            ).fetchone()
    return dict(row) if row else None


def delete_chat_conversation(root: Optional[Path], conversation_id: str,
                             *, scope_id: str = "") -> None:
    with _LOCK:
        with connect(root) as conn:
            conn.execute(
                "DELETE FROM chat_conversations WHERE scope_id=? AND conversation_id=?",
                (str(scope_id or ""), str(conversation_id)),
            )
            conn.commit()


def record_telemetry_file(root: Optional[Path], *, name: str, path: Path,
                          updated_at_utc: str = "") -> Dict[str, Any]:
    try:
        st = path.stat()
        size = int(st.st_size)
        mtime_ns = int(st.st_mtime_ns)
    except OSError:
        size = 0
        mtime_ns = 0
    key = str(name or path.name)
    with _LOCK:
        with connect(root) as conn:
            existing = conn.execute(
                "SELECT first_seen_utc FROM telemetry_files WHERE name=?",
                (key,),
            ).fetchone()
            first_seen = (existing["first_seen_utc"] if existing else updated_at_utc) or updated_at_utc
            conn.execute(
                """
                INSERT INTO telemetry_files(name, path, size_bytes, mtime_ns, first_seen_utc, updated_at_utc)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                  path=excluded.path,
                  size_bytes=excluded.size_bytes,
                  mtime_ns=excluded.mtime_ns,
                  updated_at_utc=excluded.updated_at_utc
                """,
                (key, str(path), size, mtime_ns, first_seen, updated_at_utc),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM telemetry_files WHERE name=?",
                (key,),
            ).fetchone()
    return dict(row) if row else {"name": key}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def enqueue_worker_job(root: Optional[Path], *, worker_job_id: str, kind: str,
                       payload: Optional[Dict[str, Any]] = None,
                       priority: int = 100, max_attempts: int = 1,
                       timeout_sec: int = 300, user_id: Any = "",
                       workspace_id: str = "") -> Dict[str, Any]:
    jid = str(worker_job_id or "").strip()
    clean_kind = str(kind or "").strip()
    if not jid:
        raise ValueError("worker_job_id required")
    if not clean_kind:
        raise ValueError("worker job kind required")
    now = _now_iso()
    with _LOCK:
        with connect(root) as conn:
            conn.execute(
                """
                INSERT INTO worker_jobs(
                  worker_job_id, kind, status, priority, max_attempts,
                  timeout_sec, queued_at_utc, updated_at_utc, user_id,
                  workspace_id, payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    jid, clean_kind, "queued", int(priority), max(1, int(max_attempts or 1)),
                    max(1, int(timeout_sec or 300)), now, now, str(user_id or ""),
                    str(workspace_id or "system"), _compact_json(payload or {}),
                ),
            )
            conn.commit()
    return get_worker_job(root, jid) or {"worker_job_id": jid}


def _worker_row(row: sqlite3.Row) -> Dict[str, Any]:
    out = dict(row)
    for key in ("payload_json", "result_json"):
        try:
            out[key[:-5]] = json.loads(out.get(key) or "{}")
        except (TypeError, ValueError):
            out[key[:-5]] = {}
    return out


def get_worker_job(root: Optional[Path], worker_job_id: str, *,
                   workspace_id: str = "") -> Optional[Dict[str, Any]]:
    with _LOCK:
        with connect(root) as conn:
            if workspace_id:
                row = conn.execute(
                    "SELECT * FROM worker_jobs WHERE worker_job_id=? AND workspace_id=?",
                    (str(worker_job_id), str(workspace_id)),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM worker_jobs WHERE worker_job_id=?",
                    (str(worker_job_id),),
                ).fetchone()
    return _worker_row(row) if row else None


def list_worker_jobs(root: Optional[Path], *, status: str = "",
                     limit: int = 100, workspace_id: str = "", kind: str = "",
                     after_id: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(1000, int(limit or 100)))
    with _LOCK:
        with connect(root) as conn:
            if kind or after_id is not None:
                # Internal recovery uses an immutable keyset, not a newest-N
                # window which can permanently hide an interrupted old job.
                # Omitted selectors preserve the existing listing order.
                where, params = [], []
                for column, value in (("status", status), ("workspace_id", workspace_id), ("kind", kind)):
                    if value:
                        where.append(column + "=?")
                        params.append(str(value))
                if after_id is not None:
                    where.append("worker_job_id>?")
                    params.append(str(after_id))
                order = "worker_job_id" if after_id is not None else "updated_at_utc DESC"
                rows = conn.execute("SELECT * FROM worker_jobs" +
                    (" WHERE " + " AND ".join(where) if where else "") +
                    " ORDER BY " + order + " LIMIT ?", (*params, limit)).fetchall()
            elif status and workspace_id:
                rows = conn.execute(
                    "SELECT * FROM worker_jobs WHERE status=? AND workspace_id=? "
                    "ORDER BY updated_at_utc DESC LIMIT ?",
                    (status, str(workspace_id), limit),
                ).fetchall()
            elif status:
                rows = conn.execute(
                    "SELECT * FROM worker_jobs WHERE status=? ORDER BY updated_at_utc DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            elif workspace_id:
                rows = conn.execute(
                    "SELECT * FROM worker_jobs WHERE workspace_id=? "
                    "ORDER BY updated_at_utc DESC LIMIT ?",
                    (str(workspace_id), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM worker_jobs ORDER BY updated_at_utc DESC LIMIT ?",
                    (limit,),
                ).fetchall()
    return [_worker_row(row) for row in rows]


def worker_job_counts(root: Optional[Path], *, workspace_id: str = "") -> Dict[str, int]:
    with _LOCK:
        with connect(root) as conn:
            if workspace_id:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS count FROM worker_jobs "
                    "WHERE workspace_id=? GROUP BY status",
                    (str(workspace_id),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS count FROM worker_jobs GROUP BY status"
                ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def prune_terminal_worker_jobs(root: Optional[Path], *, kind: str,
                               workspace_id: str, keep: int = 4) -> int:
    """Bound bulky terminal job results without touching active work."""
    keep_n = max(0, min(100, int(keep or 0)))
    with _LOCK:
        with connect(root) as conn:
            rows = conn.execute(
                """
                SELECT worker_job_id FROM worker_jobs
                WHERE kind=? AND workspace_id=?
                  AND status IN ('succeeded','failed','cancelled','stale')
                ORDER BY updated_at_utc DESC, worker_job_id DESC
                """,
                (str(kind), str(workspace_id)),
            ).fetchall()
            stale_ids = [str(row["worker_job_id"]) for row in rows[keep_n:]]
            if stale_ids:
                conn.executemany(
                    "DELETE FROM worker_jobs WHERE worker_job_id=?",
                    ((job_id,) for job_id in stale_ids),
                )
            conn.commit()
    return len(stale_ids)


def request_worker_cancel(root: Optional[Path], worker_job_id: str, *,
                          workspace_id: str = "") -> Optional[Dict[str, Any]]:
    now = _now_iso()
    with _LOCK:
        with connect(root) as conn:
            scope_sql = " AND workspace_id=?" if workspace_id else ""
            select_params = ((str(worker_job_id), str(workspace_id)) if workspace_id
                             else (str(worker_job_id),))
            row = conn.execute(
                "SELECT status FROM worker_jobs WHERE worker_job_id=?" + scope_sql,
                select_params,
            ).fetchone()
            if row is None:
                return None
            if str(row["status"]) == "queued":
                conn.execute(
                    """
                    UPDATE worker_jobs
                    SET status='cancelled', cancel_requested=1, finished_at_utc=?,
                        updated_at_utc=?
                    WHERE worker_job_id=?""" + scope_sql,
                    (now, now, *select_params),
                )
            elif str(row["status"]) == "running":
                conn.execute(
                    """
                    UPDATE worker_jobs
                    SET cancel_requested=1, updated_at_utc=?
                    WHERE worker_job_id=?""" + scope_sql,
                    (now, *select_params),
                )
            # Terminal rows are immutable: late cancellation cannot rewrite history.
            conn.commit()
    return get_worker_job(root, worker_job_id, workspace_id=workspace_id)


def finalize_worker_cancel(root: Optional[Path], worker_job_id: str, *,
                           worker_id: str = "") -> Optional[Dict[str, Any]]:
    now = _now_iso()
    worker_sql = " AND worker_id=?" if worker_id else ""
    params = ((now, now, str(worker_job_id), str(worker_id)) if worker_id else
              (now, now, str(worker_job_id)))
    with _LOCK:
        with connect(root) as conn:
            conn.execute(
                """
                UPDATE worker_jobs
                SET status='cancelled', cancel_requested=1, finished_at_utc=?,
                    updated_at_utc=?, locked_until=0, deadline_at=0,
                    error='cancelled by request'
                WHERE worker_job_id=? AND status='running'""" + worker_sql,
                params,
            )
            conn.commit()
    return get_worker_job(root, worker_job_id)


def heartbeat_worker_job(root: Optional[Path], worker_job_id: str, *,
                         worker_id: str, now: Optional[float] = None,
                         lease_sec: float = 30.0) -> bool:
    current = time.time() if now is None else float(now)
    stamp = _now_iso()
    lease = max(1.0, min(60.0, float(lease_sec or 30.0)))
    with _LOCK:
        with connect(root) as conn:
            cur = conn.execute(
                """
                UPDATE worker_jobs
                SET heartbeat_at_utc=?, updated_at_utc=?, locked_until=?
                WHERE worker_job_id=? AND worker_id=? AND status='running'
                  AND cancel_requested=0 AND deadline_at>?
                """,
                (stamp, stamp, current + lease, str(worker_job_id), str(worker_id), current),
            )
            conn.commit()
            return int(cur.rowcount or 0) == 1


def worker_cancel_requested(root: Optional[Path], worker_job_id: str, *,
                            worker_id: str = "") -> bool:
    row = get_worker_job(root, worker_job_id)
    if not row or str(row.get("status") or "") != "running":
        return True
    if worker_id and str(row.get("worker_id") or "") != str(worker_id):
        return True
    return bool(int(row.get("cancel_requested") or 0))


def sweep_stale_worker_jobs(root: Optional[Path], *, now: Optional[float] = None) -> int:
    current = time.time() if now is None else float(now)
    stamp = _now_iso()
    changed = 0
    with _LOCK:
        with connect(root) as conn:
            rows = conn.execute(
                """
                SELECT worker_job_id, attempts, max_attempts, cancel_requested,
                       deadline_at, locked_until
                FROM worker_jobs
                WHERE status='running' AND (
                  (deadline_at > 0 AND deadline_at < ?) OR
                  (locked_until > 0 AND locked_until < ?)
                )
                """,
                (current, current),
            ).fetchall()
            for row in rows:
                cancelled = bool(int(row["cancel_requested"] or 0))
                can_retry = int(row["attempts"] or 0) < int(row["max_attempts"] or 1)
                deadline_value = float(row["deadline_at"] or 0)
                deadline_hit = deadline_value > 0 and deadline_value < current
                if cancelled:
                    status, finished, error = "cancelled", stamp, "cancelled by request"
                elif can_retry:
                    status, finished = "queued", ""
                    error = "worker execution timed out" if deadline_hit else "worker heartbeat timed out"
                else:
                    status, finished = ("failed" if deadline_hit else "stale"), stamp
                    error = "worker execution timed out" if deadline_hit else "worker heartbeat timed out"
                cur = conn.execute(
                    """
                    UPDATE worker_jobs
                    SET status=?, finished_at_utc=?, updated_at_utc=?, locked_until=0,
                        deadline_at=0, worker_id='', heartbeat_at_utc='', error=?
                    WHERE worker_job_id=? AND status='running'
                    """,
                    (status, finished, stamp, error, str(row["worker_job_id"])),
                )
                changed += int(cur.rowcount or 0)
            conn.commit()
    return changed


def claim_worker_job(root: Optional[Path], *, worker_id: str,
                     now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    current = time.time() if now is None else float(now)
    stamp = _now_iso()
    claimed_id = ""
    with _LOCK:
        with connect(root) as conn:
            # BEGIN IMMEDIATE serializes the SELECT+UPDATE across worker processes.
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM worker_jobs
                WHERE status='queued' AND cancel_requested=0
                ORDER BY priority ASC, queued_at_utc ASC
                LIMIT 1
                """
            ).fetchone()
            if row is not None:
                timeout_sec = max(1, int(row["timeout_sec"] or 300))
                lease_sec = min(30, timeout_sec)
                claimed_id = str(row["worker_job_id"])
                cur = conn.execute(
                    """
                    UPDATE worker_jobs
                    SET status='running', attempts=attempts+1, started_at_utc=?,
                        finished_at_utc='', updated_at_utc=?, locked_until=?,
                        deadline_at=?, worker_id=?, heartbeat_at_utc=?, error=''
                    WHERE worker_job_id=? AND status='queued' AND cancel_requested=0
                    """,
                    (
                        stamp, stamp, current + lease_sec, current + timeout_sec,
                        str(worker_id), stamp, claimed_id,
                    ),
                )
                if int(cur.rowcount or 0) != 1:
                    claimed_id = ""
            conn.commit()
    return get_worker_job(root, claimed_id) if claimed_id else None


def finish_worker_job(root: Optional[Path], worker_job_id: str,
                      result: Optional[Dict[str, Any]] = None, *,
                      worker_id: str = "") -> Optional[Dict[str, Any]]:
    now = _now_iso()
    worker_sql = " AND worker_id=?" if worker_id else ""
    params = ((now, now, _compact_json(result or {}), str(worker_job_id), str(worker_id))
              if worker_id else
              (now, now, _compact_json(result or {}), str(worker_job_id)))
    with _LOCK:
        with connect(root) as conn:
            conn.execute(
                """
                UPDATE worker_jobs
                SET status='succeeded', finished_at_utc=?, updated_at_utc=?,
                    locked_until=0, deadline_at=0, result_json=?, error=''
                WHERE worker_job_id=? AND status='running' AND cancel_requested=0""" + worker_sql,
                params,
            )
            conn.commit()
    return get_worker_job(root, worker_job_id)


def fail_worker_job(root: Optional[Path], worker_job_id: str, error: str,
                    *, retry: bool = True, worker_id: str = "") -> Optional[Dict[str, Any]]:
    now = _now_iso()
    current = get_worker_job(root, worker_job_id) or {}
    if not current or str(current.get("status") or "") != "running":
        return current or None
    if worker_id and str(current.get("worker_id") or "") != str(worker_id):
        return current
    if int(current.get("cancel_requested") or 0):
        return finalize_worker_cancel(root, worker_job_id, worker_id=worker_id)
    attempts = int(current.get("attempts") or 0)
    max_attempts = int(current.get("max_attempts") or 1)
    status = "queued" if retry and attempts < max_attempts else "failed"
    finished = "" if status == "queued" else now
    worker_sql = " AND worker_id=?" if worker_id else ""
    params = ((status, finished, now, str(error or "")[:1000], str(worker_job_id), str(worker_id))
              if worker_id else
              (status, finished, now, str(error or "")[:1000], str(worker_job_id)))
    with _LOCK:
        with connect(root) as conn:
            conn.execute(
                """
                UPDATE worker_jobs
                SET status=?, finished_at_utc=?, updated_at_utc=?,
                    locked_until=0, deadline_at=0, worker_id='', heartbeat_at_utc='', error=?
                WHERE worker_job_id=? AND status='running'""" + worker_sql,
                params,
            )
            conn.commit()
    return get_worker_job(root, worker_job_id)
