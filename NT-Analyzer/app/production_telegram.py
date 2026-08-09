"""PostgreSQL-backed single-consumer Telegram inbox and transactional outbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from . import observability, runtime_env
from .production_storage import Scope, StorageError, StorageUnavailableError, get_client
from .production_storage.core import PostgresClient, _jsonb


MAX_UPDATE_BYTES = 256 * 1024
MAX_OUTBOX_TEXT = 4000
MAX_ATTEMPTS = 5
WEBHOOK_REORDER_GRACE_SEC = 0.75
_SAFE_LEASE = re.compile(r"^[a-z][a-z0-9_.:-]{2,99}$")


class ProductionTelegramError(StorageError):
    code = "production_telegram_error"


class TelegramConsumerBusy(ProductionTelegramError):
    code = "telegram_consumer_busy"


class TelegramPayloadRejected(ProductionTelegramError):
    code = "telegram_payload_rejected"


def _canonical(value: Any) -> bytes:
    if not isinstance(value, Mapping):
        raise TelegramPayloadRejected("Telegram payload must be an object.")
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TelegramPayloadRejected("Telegram payload is not valid JSON.") from exc


def _bot_hash() -> str:
    identity = runtime_env.deployment_config().telegram_bot_id
    return hashlib.sha256(str(identity).encode("utf-8")).hexdigest()


def _update_key(bot_hash: str, update_id: int) -> str:
    return "tgu_" + hashlib.sha256(f"{bot_hash}:{update_id}".encode("ascii")).hexdigest()[:32]


def _conversation_key(update: Mapping[str, Any]) -> str:
    message = update.get("message") if isinstance(update.get("message"), Mapping) else {}
    if not message:
        callback = update.get("callback_query") if isinstance(update.get("callback_query"), Mapping) else {}
        message = callback.get("message") if isinstance(callback.get("message"), Mapping) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), Mapping) else {}
    raw = f"{chat.get('id') or 'unknown'}:{message.get('message_thread_id') or 'default'}"
    return "lane_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _safe_error(exc: BaseException) -> str:
    return str(observability.redact(str(exc) or exc.__class__.__name__))[:1000]


class ProductionTelegramQueue:
    def __init__(self, client: Optional[PostgresClient] = None) -> None:
        self.client = client or get_client()
        self.scope = Scope.global_service_scope()

    def acquire_service_lease(
        self, lease_name: str, owner_id: str, *, ttl_sec: int = 30,
    ) -> Optional[str]:
        name = str(lease_name or "")
        owner = str(owner_id or "")[:160]
        if not _SAFE_LEASE.fullmatch(name) or len(owner) < 3:
            raise ProductionTelegramError("Invalid Telegram service lease identity.")
        token = str(uuid.uuid4())
        ttl = max(5, min(int(ttl_sec), 300))
        with self.client.transaction(self.scope) as conn:
            row = conn.execute(
                """
                INSERT INTO sf_service_leases(lease_name,owner_id,lease_token,leased_until)
                VALUES(%s,%s,%s::uuid,clock_timestamp()+(%s*interval '1 second'))
                ON CONFLICT(lease_name) DO UPDATE SET
                  owner_id=EXCLUDED.owner_id,lease_token=EXCLUDED.lease_token,
                  leased_until=EXCLUDED.leased_until,heartbeat_at=clock_timestamp()
                WHERE sf_service_leases.leased_until < clock_timestamp()
                   OR sf_service_leases.owner_id=EXCLUDED.owner_id
                RETURNING lease_token
                """,
                (name, owner, token, ttl),
            ).fetchone()
        return str(row["lease_token"]) if row else None

    def renew_service_lease(
        self, lease_name: str, owner_id: str, lease_token: str, *, ttl_sec: int = 30,
    ) -> bool:
        ttl = max(5, min(int(ttl_sec), 300))
        with self.client.transaction(self.scope) as conn:
            row = conn.execute(
                """
                UPDATE sf_service_leases SET
                  leased_until=clock_timestamp()+(%s*interval '1 second'),
                  heartbeat_at=clock_timestamp()
                WHERE lease_name=%s AND owner_id=%s AND lease_token=%s::uuid
                  AND leased_until >= clock_timestamp()
                RETURNING lease_name
                """,
                (ttl, str(lease_name), str(owner_id), str(lease_token)),
            ).fetchone()
        return bool(row)

    def release_service_lease(self, lease_name: str, owner_id: str, lease_token: str) -> None:
        with self.client.transaction(self.scope) as conn:
            conn.execute(
                "DELETE FROM sf_service_leases WHERE lease_name=%s AND owner_id=%s AND lease_token=%s::uuid",
                (str(lease_name), str(owner_id), str(lease_token)),
            )

    def enqueue_update(self, update: Mapping[str, Any], *, transport: str) -> bool:
        if not isinstance(update, Mapping):
            raise TelegramPayloadRejected("Telegram update must be an object.")
        try:
            update_id = int(update.get("update_id") or 0)
        except (TypeError, ValueError):
            update_id = 0
        if update_id <= 0:
            raise TelegramPayloadRejected("Telegram update_id must be positive.")
        raw = _canonical(update)
        if len(raw) > MAX_UPDATE_BYTES:
            raise TelegramPayloadRejected("Telegram update exceeds 256 KiB.")
        mode = str(transport or "webhook")
        if mode not in {"webhook", "poll", "recovery"}:
            raise TelegramPayloadRejected("Unsupported Telegram transport.")
        bot_hash = _bot_hash()
        reorder_delay = WEBHOOK_REORDER_GRACE_SEC if mode == "webhook" else 0.0
        with self.client.transaction(self.scope) as conn:
            row = conn.execute(
                """
                INSERT INTO sf_telegram_updates(
                  update_key,bot_identity_hash,update_id,conversation_key,transport,
                  available_at,document
                ) VALUES(%s,%s,%s,%s,%s,
                         clock_timestamp()+(%s*interval '1 second'),%s)
                ON CONFLICT(bot_identity_hash,update_id) DO NOTHING
                RETURNING update_key
                """,
                (
                    _update_key(bot_hash, update_id), bot_hash, update_id,
                    _conversation_key(update), mode, reorder_delay,
                    _jsonb(dict(update)),
                ),
            ).fetchone()
        return bool(row)

    def claim_update(self, worker_id: str, *, lease_sec: int = 900) -> Optional[Dict[str, Any]]:
        token = str(uuid.uuid4())
        lease = max(30, min(int(lease_sec), 3600))
        with self.client.transaction(self.scope) as conn:
            row = conn.execute(
                """
                WITH candidate AS (
                  SELECT candidate_row.update_key FROM sf_telegram_updates candidate_row
                  WHERE (
                    (candidate_row.status='queued' AND candidate_row.available_at <= clock_timestamp())
                    OR (candidate_row.status='running' AND candidate_row.leased_until < clock_timestamp())
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM sf_telegram_updates earlier
                    WHERE earlier.bot_identity_hash=candidate_row.bot_identity_hash
                      AND earlier.conversation_key=candidate_row.conversation_key
                      AND earlier.update_id<candidate_row.update_id
                      AND earlier.status IN ('queued','running')
                  )
                  ORDER BY candidate_row.update_id,candidate_row.received_at
                  FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE sf_telegram_updates target SET
                  status='running',attempts=target.attempts+1,
                  lease_owner=%s,lease_token=%s::uuid,
                  leased_until=clock_timestamp()+(%s*interval '1 second'),
                  updated_at=clock_timestamp()
                FROM candidate WHERE target.update_key=candidate.update_key
                RETURNING target.*
                """,
                (str(worker_id)[:160], token, lease),
            ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["lease_token"] = token
        out["update"] = dict(out.get("document") or {})
        return out

    def finish_update(
        self, update_key: str, lease_token: str, *, error: str = "",
    ) -> bool:
        clean_error = str(observability.redact(str(error or "")))[:1000]
        with self.client.transaction(self.scope) as conn:
            current = conn.execute(
                "SELECT attempts FROM sf_telegram_updates WHERE update_key=%s AND lease_token=%s::uuid FOR UPDATE",
                (str(update_key), str(lease_token)),
            ).fetchone()
            if not current:
                return False
            attempts = int(current["attempts"] or 0)
            if clean_error and attempts < MAX_ATTEMPTS:
                delay = min(300, 5 * (2 ** max(0, attempts - 1)))
                status = "queued"
                finished = None
            else:
                delay = 0
                status = "dead_letter" if clean_error else "completed"
                finished = datetime.now(timezone.utc)
            conn.execute(
                """
                UPDATE sf_telegram_updates SET status=%s,last_error=%s,
                  available_at=clock_timestamp()+(%s*interval '1 second'),
                  lease_owner=NULL,lease_token=NULL,leased_until=NULL,
                  finished_at=%s,updated_at=clock_timestamp(),
                  document=CASE WHEN %s IN ('completed','dead_letter')
                    THEN '{}'::jsonb ELSE document END
                WHERE update_key=%s
                """,
                (status, clean_error, delay, finished, status, str(update_key)),
            )
        return True

    def enqueue_text(
        self,
        text: str,
        *,
        thread_id: Optional[int] = None,
        chat_id: str = "",
        silent: bool = False,
        dedupe_key: str = "",
        parse_mode: str = "HTML",
    ) -> Dict[str, Any]:
        clean = str(text or "")[:MAX_OUTBOX_TEXT]
        if not clean:
            raise TelegramPayloadRejected("Telegram outbox text is empty.")
        mode = str(parse_mode or "HTML")
        if mode not in {"HTML", "MarkdownV2", ""}:
            raise TelegramPayloadRejected("Unsupported Telegram parse mode.")
        identity = str(dedupe_key or f"unique:{uuid.uuid4().hex}")[:300]
        bot_hash = _bot_hash()
        dedupe_hash = hashlib.sha256(
            f"{thread_id or 0}|{identity}".encode("utf-8")
        ).hexdigest()
        outbox_id = "tgo_" + uuid.uuid4().hex
        document = {
            "kind": "text", "text": clean,
            "thread_id": int(thread_id) if thread_id else None,
            "chat_id": str(chat_id or "")[:80],
            "silent": bool(silent), "parse_mode": mode,
        }
        with self.client.transaction(self.scope) as conn:
            row = conn.execute(
                """
                INSERT INTO sf_telegram_outbox(
                  outbox_id,bot_identity_hash,dedupe_hash,document
                ) VALUES(%s,%s,%s,%s)
                ON CONFLICT(bot_identity_hash,dedupe_hash) DO UPDATE SET
                  updated_at=sf_telegram_outbox.updated_at
                RETURNING outbox_id,status,(outbox_id=%s) AS inserted
                """,
                (outbox_id, bot_hash, dedupe_hash, _jsonb(document), outbox_id),
            ).fetchone()
        return {
            "ok": True, "queued": str(row["status"]) in {"queued", "sending"},
            "outbox_id": str(row["outbox_id"]), "status": str(row["status"]),
            "deduplicated": not bool(row["inserted"]),
        }

    def claim_outbox(self, worker_id: str, *, lease_sec: int = 60) -> Optional[Dict[str, Any]]:
        token = str(uuid.uuid4())
        lease = max(10, min(int(lease_sec), 300))
        with self.client.transaction(self.scope) as conn:
            row = conn.execute(
                """
                WITH candidate AS (
                  SELECT outbox_id FROM sf_telegram_outbox
                  WHERE (status='queued' AND available_at <= clock_timestamp())
                     OR (status='sending' AND leased_until < clock_timestamp())
                  ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE sf_telegram_outbox target SET
                  status='sending',attempts=target.attempts+1,
                  lease_owner=%s,lease_token=%s::uuid,
                  leased_until=clock_timestamp()+(%s*interval '1 second'),
                  updated_at=clock_timestamp()
                FROM candidate WHERE target.outbox_id=candidate.outbox_id
                RETURNING target.*
                """,
                (str(worker_id)[:160], token, lease),
            ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["lease_token"] = token
        out["payload"] = dict(out.get("document") or {})
        return out

    def finish_outbox(
        self, outbox_id: str, lease_token: str, *, error: str = "",
    ) -> bool:
        clean_error = str(observability.redact(str(error or "")))[:1000]
        with self.client.transaction(self.scope) as conn:
            current = conn.execute(
                "SELECT attempts FROM sf_telegram_outbox WHERE outbox_id=%s AND lease_token=%s::uuid FOR UPDATE",
                (str(outbox_id), str(lease_token)),
            ).fetchone()
            if not current:
                return False
            attempts = int(current["attempts"] or 0)
            if clean_error and attempts < MAX_ATTEMPTS:
                status = "queued"
                delay = min(300, 5 * (2 ** max(0, attempts - 1)))
                sent_at = None
            else:
                status = "dead_letter" if clean_error else "sent"
                delay = 0
                sent_at = datetime.now(timezone.utc) if not clean_error else None
            conn.execute(
                """
                UPDATE sf_telegram_outbox SET status=%s,last_error=%s,
                  available_at=clock_timestamp()+(%s*interval '1 second'),
                  lease_owner=NULL,lease_token=NULL,leased_until=NULL,
                  sent_at=%s,updated_at=clock_timestamp(),
                  document=CASE WHEN %s IN ('sent','dead_letter')
                    THEN '{"kind":"redacted_after_delivery"}'::jsonb
                    ELSE document END
                WHERE outbox_id=%s
                """,
                (status, clean_error, delay, sent_at, status, str(outbox_id)),
            )
        return True

    def bot_state(self) -> Dict[str, Any]:
        bot_hash = _bot_hash()
        with self.client.transaction(self.scope) as conn:
            row = conn.execute(
                """
                INSERT INTO sf_telegram_bot_state(bot_identity_hash)
                VALUES(%s) ON CONFLICT(bot_identity_hash) DO UPDATE SET
                  updated_at=sf_telegram_bot_state.updated_at
                RETURNING poll_offset,webhook_configured,document
                """,
                (bot_hash,),
            ).fetchone()
        return dict(row)

    def update_bot_state(
        self, *, poll_offset: Optional[int] = None,
        webhook_configured: Optional[bool] = None,
        document: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        current = self.bot_state()
        offset = max(int(current.get("poll_offset") or 0), int(poll_offset or 0))
        configured = (
            bool(current.get("webhook_configured"))
            if webhook_configured is None else bool(webhook_configured)
        )
        clean_document = dict(current.get("document") or {})
        clean_document.update(observability.redact(dict(document or {})))
        with self.client.transaction(self.scope) as conn:
            row = conn.execute(
                """
                UPDATE sf_telegram_bot_state SET poll_offset=%s,
                  webhook_configured=%s,document=%s,updated_at=clock_timestamp()
                WHERE bot_identity_hash=%s
                RETURNING poll_offset,webhook_configured,document
                """,
                (offset, configured, _jsonb(clean_document), _bot_hash()),
            ).fetchone()
        return dict(row)

    def status(self) -> Dict[str, Any]:
        with self.client.transaction(self.scope, read_only=True) as conn:
            counts = dict(conn.execute(
                """
                SELECT
                  (SELECT count(*) FROM sf_telegram_updates WHERE status='queued') AS updates_queued,
                  (SELECT count(*) FROM sf_telegram_updates WHERE status='running') AS updates_running,
                  (SELECT count(*) FROM sf_telegram_updates WHERE status='dead_letter') AS updates_dead_letter,
                  (SELECT count(*) FROM sf_telegram_outbox WHERE status='queued') AS outbox_queued,
                  (SELECT count(*) FROM sf_telegram_outbox WHERE status='sending') AS outbox_sending,
                  (SELECT count(*) FROM sf_telegram_outbox WHERE status='dead_letter') AS outbox_dead_letter
                """
            ).fetchone())
            lease = conn.execute(
                """SELECT owner_id,leased_until,heartbeat_at,
                          leased_until >= clock_timestamp() AS active
                   FROM sf_service_leases WHERE lease_name='telegram-consumer'"""
            ).fetchone()
        return {
            "ok": True, "counts": counts,
            "consumer": dict(lease) if lease else {"active": False},
        }

    def sweep_retention(self, *, limit: int = 5000) -> Dict[str, int]:
        capped = max(1, min(int(limit), 100_000))
        removed = {}
        with self.client.transaction(self.scope) as conn:
            for label, table in (
                ("updates", "sf_telegram_updates"),
                ("outbox", "sf_telegram_outbox"),
            ):
                rows = conn.execute(
                    f"""WITH doomed AS (
                           SELECT ctid FROM {table}
                           WHERE retention_until < clock_timestamp() LIMIT %s
                         ) DELETE FROM {table} target USING doomed
                           WHERE target.ctid=doomed.ctid RETURNING 1""",
                    (capped,),
                ).fetchall()
                removed[label] = len(rows)
        return removed


_QUEUE: Optional[ProductionTelegramQueue] = None
_QUEUE_LOCK = threading.Lock()


def get_queue() -> ProductionTelegramQueue:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            _QUEUE = ProductionTelegramQueue()
        return _QUEUE


def reset_for_tests() -> None:
    global _QUEUE
    with _QUEUE_LOCK:
        _QUEUE = None


def accept_webhook(update: Mapping[str, Any], supplied_secret: str) -> Dict[str, Any]:
    from . import telegram_service

    expected = str(os.environ.get(telegram_service.WEBHOOK_SECRET_ENV) or "").strip()
    supplied = str(supplied_secret or "").strip()
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise TelegramPayloadRejected("Invalid Telegram webhook signature.")
    queued = get_queue().enqueue_update(update, transport="webhook")
    return {
        "ok": True, "handler": "queued" if queued else "duplicate_update",
        "queued": queued, "update_id": int(update.get("update_id") or 0),
    }


def enqueue_text(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return get_queue().enqueue_text(*args, **kwargs)


def readiness_status() -> Dict[str, Any]:
    try:
        state = get_queue().status()
        active = bool((state.get("consumer") or {}).get("active"))
        return {"ok": active, "code": "ready" if active else "consumer_offline"}
    except StorageError as exc:
        return {"ok": False, "code": exc.code}


def _ensure_webhook(queue: ProductionTelegramQueue) -> bool:
    from . import telegram_service

    secret = str(os.environ.get(telegram_service.WEBHOOK_SECRET_ENV) or "").strip()
    token = str(os.environ.get(telegram_service.TOKEN_ENV) or "").strip()
    if not secret or not token:
        queue.update_bot_state(
            webhook_configured=False,
            document={"webhook_error": "missing_protected_token_or_secret"},
        )
        return False
    origin = runtime_env.deployment_config().public_origin.rstrip("/")
    try:
        result = telegram_service._api_call("setWebhook", {  # noqa: SLF001
            "url": origin + "/api/telegram/webhook",
            "secret_token": secret,
            "allowed_updates": ["message", "my_chat_member", "callback_query"],
            "drop_pending_updates": False,
        })
        configured = bool(result is True or (isinstance(result, dict) and result.get("ok", True)))
        queue.update_bot_state(
            webhook_configured=configured,
            document={"webhook_url": origin + "/api/telegram/webhook" if configured else ""},
        )
        return configured
    except Exception as exc:
        queue.update_bot_state(
            webhook_configured=False,
            document={"webhook_error": _safe_error(exc)},
        )
        return False


def _poll_updates(queue: ProductionTelegramQueue) -> int:
    from . import telegram_service

    state = queue.bot_state()
    offset = int(state.get("poll_offset") or 0) + 1
    updates = telegram_service._api_call(  # noqa: SLF001
        "getUpdates",
        {
            "offset": offset, "limit": 30, "timeout": 20,
            "allowed_updates": ["message", "my_chat_member", "callback_query"],
        },
        timeout=25,
    )
    if not isinstance(updates, list):
        return 0
    highest = int(state.get("poll_offset") or 0)
    accepted = 0
    for update in updates:
        if not isinstance(update, dict):
            continue
        update_id = int(update.get("update_id") or 0)
        highest = max(highest, update_id)
        accepted += int(queue.enqueue_update(update, transport="poll"))
    if highest:
        queue.update_bot_state(poll_offset=highest)
    return accepted


def _dispatch_update(queue: ProductionTelegramQueue, item: Dict[str, Any]) -> None:
    from . import telegram_service

    update = item.get("update") if isinstance(item.get("update"), dict) else {}
    try:
        result = telegram_service._dispatch_command_update(  # noqa: SLF001
            update,
            private_id=str(os.environ.get(telegram_service.CHAT_ENV) or "").strip(),
            gid=telegram_service.group_id(),
            handle_owner_commands=bool(telegram_service.load_settings().get("enabled")),
        )
        queue.finish_update(str(item["update_key"]), str(item["lease_token"]))
        observability.event(
            "telegram", "update_completed",
            payload={
                "update_id": item.get("update_id"),
                "handler": result.get("handler"),
                "transport": item.get("transport"),
                "consumed": bool(result.get("consumed")),
            },
            fingerprint=hashlib.sha256(
                f"telegram:update:{item.get('update_id')}".encode("ascii")
            ).hexdigest(),
        )
    except Exception as exc:
        error = _safe_error(exc)
        queue.finish_update(str(item["update_key"]), str(item["lease_token"]), error=error)
        observability.event(
            "telegram", "update_failed", severity="warning",
            payload={"update_id": item.get("update_id"), "error_class": exc.__class__.__name__},
        )


def _deliver_outbox(queue: ProductionTelegramQueue, item: Dict[str, Any]) -> None:
    from . import telegram_service

    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    try:
        if payload.get("kind") != "text":
            raise ProductionTelegramError("Unsupported Production Telegram outbox kind.")
        telegram_service._send_raw_direct(  # noqa: SLF001
            str(payload.get("text") or ""),
            silent=bool(payload.get("silent")),
            thread_id=(int(payload["thread_id"]) if payload.get("thread_id") else None),
            chat_id=str(payload.get("chat_id") or "") or None,
            parse_mode=str(payload.get("parse_mode") or "HTML"),
        )
        queue.finish_outbox(str(item["outbox_id"]), str(item["lease_token"]))
    except Exception as exc:
        queue.finish_outbox(
            str(item["outbox_id"]), str(item["lease_token"]), error=_safe_error(exc),
        )


def run(*, poll_interval_sec: float = 0.25) -> int:
    config = runtime_env.assert_startup_safe()
    if config.environment != runtime_env.PRODUCTION:
        raise ProductionTelegramError("Production Telegram service requires Production environment.")
    if config.deployment_role not in {"telegram", "all-in-one"}:
        raise ProductionTelegramError("Production Telegram service requires telegram role.")
    from . import storage_router, telegram_service

    storage_router.assert_production_storage_safe()
    if not str(os.environ.get(telegram_service.TOKEN_ENV) or "").strip():
        raise ProductionTelegramError("Protected Telegram bot token is not configured.")
    # Environment injection bypasses the local configure-token UI. Validate the
    # token against Telegram and populate the public username needed by login
    # deep links before advertising the consumer as available.
    telegram_service.refresh_bot_identity()
    queue = get_queue()
    owner_id = f"{config.instance_id}:{os.getpid()}"
    lease_token = queue.acquire_service_lease("telegram-consumer", owner_id, ttl_sec=30)
    if not lease_token:
        raise TelegramConsumerBusy("Another Production Telegram consumer owns the lease.")
    stop = threading.Event()

    def stop_handler(_signum, _frame) -> None:
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, stop_handler)
        except (ValueError, OSError, AttributeError):
            pass
    emitter = observability.HeartbeatEmitter("telegram", details=queue.status)
    emitter.start()
    next_renew = 0.0
    next_webhook = 0.0
    webhook_active = False
    next_retention = time.monotonic() + 3600
    try:
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_renew:
                if not queue.renew_service_lease(
                    "telegram-consumer", owner_id, lease_token, ttl_sec=30,
                ):
                    raise TelegramConsumerBusy("Production Telegram consumer lease was lost.")
                next_renew = now + 10
            if now >= next_webhook:
                webhook_active = _ensure_webhook(queue)
                next_webhook = now + (300 if webhook_active else 30)
            if not webhook_active:
                try:
                    _poll_updates(queue)
                except Exception as exc:
                    observability.event(
                        "telegram", "poll_failed", severity="warning",
                        payload={"error_class": exc.__class__.__name__},
                    )
            item = queue.claim_update(owner_id)
            if item:
                _dispatch_update(queue, item)
            delivered = 0
            while delivered < 10:
                outgoing = queue.claim_outbox(owner_id)
                if not outgoing:
                    break
                _deliver_outbox(queue, outgoing)
                delivered += 1
            if now >= next_retention:
                queue.sweep_retention(limit=5000)
                next_retention = now + 3600
            if not item and not delivered:
                stop.wait(max(0.05, min(float(poll_interval_sec), 5.0)))
        return 0
    finally:
        emitter.stop()
        try:
            queue.release_service_lease("telegram-consumer", owner_id, lease_token)
        except StorageError:
            pass


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-ms", type=int, default=250)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.status:
            print(json.dumps(get_queue().status(), ensure_ascii=False, default=str, sort_keys=True))
            return 0
        return run(poll_interval_sec=max(50, min(args.poll_ms, 5000)) / 1000.0)
    except StorageError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
