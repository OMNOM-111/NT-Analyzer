"""Unified SF Chat human conversation service.

AI conversations keep their existing authoritative storage in ``chief_agent``
and are exposed through the SF Chat API facade in ``server.py``. This module is
the single human-to-human implementation used by Community profile actions and
the global chat launcher; Community itself never keeps a parallel DM state.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import community, runtime_env


class SFChatError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


_LOCK = threading.RLock()
_STORE_KEY = "sf_chat"
_MAX_MESSAGE = 4000
_MAX_ATTACHMENTS = 3
_MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
_ATTACHMENT_RE = re.compile(
    r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\s]+)$", re.I,
)
_MIME_EXTENSION = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,96}")


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return runtime_env.data_root(_root()) / "runtime" / "sf_chat.json"


def _uploads_root() -> Path:
    return runtime_env.data_root(_root()) / "runtime" / "sf_chat_uploads"


def _empty_doc() -> Dict[str, Any]:
    return {"version": 1, "conversations": [], "messages": [], "reads": []}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load() -> Dict[str, Any]:
    from . import storage_router
    if storage_router.production_enabled():
        from .production_storage import StorageError
        try:
            parsed = storage_router.read_document(_STORE_KEY, _empty_doc())
        except StorageError as exc:
            raise SFChatError(
                f"Production SF Chat repository unavailable ({exc.code}).", 503,
            ) from None
    else:
        path = _store_path()
        if not path.is_file():
            return _empty_doc()
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _empty_doc()
    doc = parsed if isinstance(parsed, dict) else {}
    for key in ("conversations", "messages", "reads"):
        value = doc.get(key)
        doc[key] = [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []
    doc["version"] = 1
    return doc


def _save(doc: Dict[str, Any]) -> None:
    payload = {
        "version": 1,
        "conversations": list(doc.get("conversations") or [])[-5000:],
        "messages": list(doc.get("messages") or [])[-50000:],
        "reads": list(doc.get("reads") or [])[-10000:],
    }
    from . import storage_router
    if storage_router.production_enabled():
        from .production_storage import StorageError
        try:
            storage_router.write_document(_STORE_KEY, payload)
        except StorageError as exc:
            raise SFChatError(
                f"Production SF Chat repository unavailable ({exc.code}).", 503,
            ) from None
        return
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _safe_id(value: Any, label: str) -> str:
    clean = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(clean):
        raise SFChatError(f"Некорректный {label}.")
    return clean


def _image_payload_matches_mime(mime: str, payload: bytes) -> bool:
    if mime == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if mime == "image/webp":
        return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
    return False


def _identity(
    user_id: Any, *, user_uuid: Any = "", display_name: str = "",
    username: str = "", role_label: str = "Участник",
) -> Dict[str, Any]:
    try:
        return community.chat_identity(
            user_id, user_uuid=user_uuid, display_name=display_name,
            username=username, role_label=role_label,
        )
    except community.CommunityError as exc:
        raise SFChatError(str(exc), exc.status) from None


def _conversation(doc: Dict[str, Any], conversation_id: str) -> Optional[Dict[str, Any]]:
    cid = str(conversation_id or "").strip()
    return next((row for row in doc.get("conversations") or []
                 if str(row.get("conversation_id") or "") == cid), None)


def _require_participant(doc: Dict[str, Any], conversation_id: str, profile_id: str) -> Dict[str, Any]:
    cid = _safe_id(conversation_id, "conversation_id")
    row = _conversation(doc, cid)
    if row is None or profile_id not in list(row.get("participant_profile_ids") or []):
        # A single 404 response avoids confirming that somebody else's private
        # conversation exists.
        raise SFChatError("Диалог не найден.", 404)
    return row


def _read_row(doc: Dict[str, Any], conversation_id: str, profile_id: str) -> Optional[Dict[str, Any]]:
    return next((row for row in doc.get("reads") or []
                 if str(row.get("conversation_id") or "") == conversation_id
                 and str(row.get("profile_id") or "") == profile_id), None)


def _mark_read_in_doc(doc: Dict[str, Any], conversation_id: str, profile_id: str, seq: int) -> None:
    row = _read_row(doc, conversation_id, profile_id)
    if row is None:
        row = {"conversation_id": conversation_id, "profile_id": profile_id}
        doc.setdefault("reads", []).append(row)
    row["last_read_seq"] = max(int(row.get("last_read_seq") or 0), int(seq or 0))
    row["read_at_utc"] = _now_iso()


def _conversation_messages(doc: Dict[str, Any], conversation_id: str) -> List[Dict[str, Any]]:
    return [row for row in doc.get("messages") or []
            if str(row.get("conversation_id") or "") == conversation_id
            and not row.get("deleted_at_utc")]


def _messages_by_conversation(doc: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Group live messages by conversation in one pass.

    Listing conversations used to call `_conversation_messages` per row, so a
    viewer with C conversations rescanned all M messages C times. At the
    document cap (2000 conversations / 50000 messages) that is 100M row tests
    and one listing measured ~44s. Grouping once makes the same listing linear.
    """
    index: Dict[str, List[Dict[str, Any]]] = {}
    for row in doc.get("messages") or []:
        if row.get("deleted_at_utc"):
            continue
        index.setdefault(str(row.get("conversation_id") or ""), []).append(row)
    return index


def _reads_by_conversation(doc: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Index read rows by (conversation, profile) so lookups are not scans."""
    index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in doc.get("reads") or []:
        index[(str(row.get("conversation_id") or ""),
               str(row.get("profile_id") or ""))] = row
    return index


def _other_profile_id(conversation: Dict[str, Any], viewer_profile_id: str) -> str:
    return next((str(value) for value in conversation.get("participant_profile_ids") or []
                 if str(value) != viewer_profile_id), "")


def _public_attachments(value: Any) -> List[Dict[str, Any]]:
    return [
        {
            "attachment_id": str(row.get("attachment_id") or ""),
            "name": str(row.get("name") or "image")[:120],
            "mime_type": str(row.get("mime_type") or ""),
            "size": max(0, int(row.get("size") or 0)),
            "url": "/api/sf-chat/attachments/" + str(row.get("attachment_id") or ""),
        }
        for row in (value if isinstance(value, list) else []) if isinstance(row, dict)
    ]


def _public_message(row: Dict[str, Any], profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    sender_id = str(row.get("sender_profile_id") or "")
    return {
        "message_id": str(row.get("message_id") or ""),
        "conversation_id": str(row.get("conversation_id") or ""),
        "seq": int(row.get("seq") or 0),
        "role": "user",
        "sender_type": "human",
        "sender_profile_id": sender_id,
        "sender": profiles.get(sender_id),
        "content": str(row.get("text") or "")[:_MAX_MESSAGE],
        "attachments": _public_attachments(row.get("attachments")),
        "timestamp_utc": str(row.get("created_at_utc") or ""),
    }


def _conversation_payload(
    row: Dict[str, Any], viewer_profile_id: str,
    profiles: Dict[str, Dict[str, Any]], *,
    last: Optional[Dict[str, Any]], message_count: int, unread: int,
) -> Dict[str, Any]:
    """The single public shape of a conversation.

    Both read paths land here — the Development document store and the
    Production relational mirrors — so the payload cannot drift between them.
    Only the three message-derived facts are supplied by the caller, because
    only their *source* differs.
    """
    cid = str(row.get("conversation_id") or "")
    other_id = _other_profile_id(row, viewer_profile_id)
    other = profiles.get(other_id) or {
        "profile_id": other_id, "display_name": "Участник", "username": "",
    }
    preview = str((last or {}).get("text") or "").strip()
    if not preview and (last or {}).get("attachments"):
        preview = "Изображение"
    return {
        "conversation_id": cid,
        "conversation_type": "human",
        "title": str(other.get("display_name") or "Диалог"),
        "subtitle": "Человек · @" + str(other.get("username") or "участник"),
        "participant": other,
        "participant_profile_ids": [str(value) for value in row.get("participant_profile_ids") or []],
        "message_count": int(message_count),
        "unread_count": int(unread),
        "last_message_id": str((last or {}).get("message_id") or ""),
        "last_message_preview": preview[:240],
        "updated_at_utc": str(row.get("updated_at_utc") or row.get("created_at_utc") or ""),
        "created_at_utc": str(row.get("created_at_utc") or ""),
        "closed": False,
        "pinned": False,
        "is_default": False,
        "work_state": "open",
    }


def _public_conversation(
    doc: Dict[str, Any], row: Dict[str, Any], viewer_profile_id: str,
    profiles: Dict[str, Dict[str, Any]],
    *,
    messages_index: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    reads_index: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Document-store projection: message facts come from the loaded document."""
    cid = str(row.get("conversation_id") or "")
    messages = (messages_index.get(cid) or []) if messages_index is not None         else _conversation_messages(doc, cid)
    read = (reads_index.get((cid, viewer_profile_id)) if reads_index is not None
            else _read_row(doc, cid, viewer_profile_id)) or {}
    last_read_seq = int(read.get("last_read_seq") or 0)
    unread = sum(1 for message in messages
                 if int(message.get("seq") or 0) > last_read_seq
                 and str(message.get("sender_profile_id") or "") != viewer_profile_id)
    return _conversation_payload(
        row, viewer_profile_id, profiles,
        last=messages[-1] if messages else None,
        message_count=len(messages), unread=unread,
    )


def _relational_conversation(
    relational_row: Dict[str, Any], viewer_profile_id: str,
    profiles: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Relational projection: message facts come from the indexed mirrors."""
    conversation = dict(relational_row.get("conversation") or {})
    if not conversation.get("conversation_id"):
        conversation["conversation_id"] = str(relational_row.get("conversation_id") or "")
    last = relational_row.get("last_message")
    return _conversation_payload(
        conversation, viewer_profile_id, profiles,
        last=dict(last) if isinstance(last, dict) else None,
        message_count=int(relational_row.get("message_count") or 0),
        unread=int(relational_row.get("unread_count") or 0),
    )


def start_conversation(
    user_id: Any, target_profile_id: str, *, user_uuid: Any = "",
    display_name: str = "", username: str = "", role_label: str = "Участник",
) -> Dict[str, Any]:
    actor = _identity(
        user_id, user_uuid=user_uuid, display_name=display_name,
        username=username, role_label=role_label,
    )
    try:
        target = community.chat_target(actor["profile_id"], target_profile_id)
    except community.CommunityError as exc:
        raise SFChatError(str(exc), exc.status) from None
    participants = sorted({actor["profile_id"], str(target["profile_id"])})
    if len(participants) != 2:
        raise SFChatError("Получатель не найден.", 404)
    conversation_id = "sfh_" + hashlib.sha256("|".join(participants).encode("utf-8")).hexdigest()[:20]
    with _LOCK:
        doc = _load()
        row = _conversation(doc, conversation_id)
        if row is None:
            now = _now_iso()
            row = {
                "conversation_id": conversation_id,
                "conversation_type": "human",
                "participant_profile_ids": participants,
                "created_at_utc": now,
                "updated_at_utc": now,
                "last_seq": 0,
            }
            doc.setdefault("conversations", []).append(row)
        profiles = community.chat_public_profiles(actor["profile_id"], participants)
        _save(doc)
        return {"ok": True, "conversation": _public_conversation(doc, row, actor["profile_id"], profiles)}


def _relational_reads() -> bool:
    """True when the authoritative read side is PostgreSQL.

    Development keeps the document store: it is the import/fallback source and
    is small by construction. Production and Canary read the mirrors, so no
    ordinary chat action deserialises a document holding every user's history.
    """
    from . import storage_router
    return bool(storage_router.production_enabled())


DEFAULT_CONVERSATION_PAGE = 30
DEFAULT_HISTORY_PAGE = 50


def list_conversations(
    user_id: Any, *, user_uuid: Any = "", display_name: str = "",
    username: str = "", role_label: str = "Участник",
    limit: int = DEFAULT_CONVERSATION_PAGE, cursor: str = "",
) -> Dict[str, Any]:
    actor = _identity(
        user_id, user_uuid=user_uuid, display_name=display_name,
        username=username, role_label=role_label,
    )
    viewer_id = str(actor["profile_id"])
    if _relational_reads():
        return _list_conversations_relational(viewer_id, limit=limit, cursor=cursor)
    with _LOCK:
        doc = _load()
        rows = [row for row in doc.get("conversations") or []
                if viewer_id in list(row.get("participant_profile_ids") or [])]
        profile_ids = [str(pid) for row in rows for pid in row.get("participant_profile_ids") or []]
        profiles = community.chat_public_profiles(viewer_id, profile_ids)
        messages_index = _messages_by_conversation(doc)
        reads_index = _reads_by_conversation(doc)
        public = [_public_conversation(doc, row, viewer_id, profiles,
                                       messages_index=messages_index,
                                       reads_index=reads_index)
                  for row in rows]
        # Same ordering key as the relational keyset, tie-breaker included:
        # conversations created in the same second would otherwise come back in
        # insertion order here and in id order in Production.
        public.sort(key=lambda item: (str(item.get("updated_at_utc") or ""),
                                      str(item.get("conversation_id") or "")), reverse=True)
        unread_total = sum(int(row.get("unread_count") or 0) for row in public)
        page = max(1, min(200, int(limit or DEFAULT_CONVERSATION_PAGE)))
        # Development pages the already-loaded list so the API contract — and
        # therefore the client's paging code — is identical in both modes.
        start = 0
        if cursor:
            ids = [row.get("conversation_id") for row in public]
            if cursor in ids:
                start = ids.index(cursor) + 1
        window = public[start:start + page]
        has_more = len(public) > start + page
        return {
            "ok": True,
            "conversations": window,
            "next_cursor": str(window[-1].get("conversation_id") or "") if (has_more and window) else "",
            "has_more": has_more,
            "unread_count": unread_total,
            "viewer_profile_id": viewer_id,
        }


def _list_conversations_relational(
    viewer_id: str, *, limit: int, cursor: str,
) -> Dict[str, Any]:
    from . import storage_router
    from .production_storage import StorageError
    try:
        page = storage_router.sf_chat_conversation_page(
            viewer_id, limit=limit or DEFAULT_CONVERSATION_PAGE, cursor=cursor,
        )
        rows = list(page.get("rows") or [])
        profile_ids = [
            str(pid)
            for row in rows
            for pid in (row.get("conversation") or {}).get("participant_profile_ids") or []
        ]
        profiles = community.chat_public_profiles(viewer_id, profile_ids)
        unread_total = storage_router.sf_chat_unread_total(viewer_id)
    except StorageError as exc:
        raise SFChatError(
            f"Production SF Chat repository unavailable ({exc.code}).", 503,
        ) from None
    return {
        "ok": True,
        "conversations": [_relational_conversation(row, viewer_id, profiles) for row in rows],
        "next_cursor": str(page.get("next_cursor") or ""),
        "has_more": bool(page.get("has_more")),
        "unread_count": int(unread_total),
        "viewer_profile_id": viewer_id,
    }


def poll_state(
    user_id: Any, *, user_uuid: Any = "", display_name: str = "",
    username: str = "", role_label: str = "Участник",
) -> Dict[str, Any]:
    """Change markers for an open panel: no message bodies, no documents.

    A refresh tick asks this instead of re-reading the conversation list. In
    Production it is one indexed statement returning a handful of integers per
    conversation, so an idle panel transfers almost nothing.
    """
    actor = _identity(
        user_id, user_uuid=user_uuid, display_name=display_name,
        username=username, role_label=role_label,
    )
    viewer_id = str(actor["profile_id"])
    if _relational_reads():
        from . import storage_router
        from .production_storage import StorageError
        try:
            state = storage_router.sf_chat_poll_state(viewer_id)
        except StorageError as exc:
            raise SFChatError(
                f"Production SF Chat repository unavailable ({exc.code}).", 503,
            ) from None
        rows = [{
            "conversation_id": str(row.get("conversation_id") or ""),
            "last_seq": int(row.get("last_seq") or 0),
            "updated_at_utc": _iso(row.get("updated_at")),
            "last_read_seq": int(row.get("last_read_seq") or 0),
            "unread_count": int(row.get("unread_count") or 0),
        } for row in state.get("rows") or []]
        signature = {
            "conversation_count": int(state.get("conversation_count") or 0),
            "newest_updated_at_utc": _iso(state.get("newest_updated_at")),
            "seq_total": int(state.get("seq_total") or 0),
        }
    else:
        with _LOCK:
            doc = _load()
            messages_index = _messages_by_conversation(doc)
            reads_index = _reads_by_conversation(doc)
            rows = []
            for row in doc.get("conversations") or []:
                cid = str(row.get("conversation_id") or "")
                if viewer_id not in [str(v) for v in row.get("participant_profile_ids") or []]:
                    continue
                last_read = int((reads_index.get((cid, viewer_id)) or {}).get("last_read_seq") or 0)
                unread = sum(1 for message in messages_index.get(cid) or []
                             if int(message.get("seq") or 0) > last_read
                             and str(message.get("sender_profile_id") or "") != viewer_id)
                rows.append({
                    "conversation_id": cid,
                    "last_seq": int(row.get("last_seq") or 0),
                    "updated_at_utc": str(row.get("updated_at_utc") or ""),
                    "last_read_seq": last_read,
                    "unread_count": unread,
                })
            rows.sort(key=lambda item: str(item["updated_at_utc"]), reverse=True)
            signature = {
                "conversation_count": len(rows),
                "newest_updated_at_utc": rows[0]["updated_at_utc"] if rows else "",
                "seq_total": sum(int(row["last_seq"]) for row in rows),
            }
            # Only threads with something new earn a row, matching Production.
            rows = [row for row in rows if int(row["unread_count"]) > 0][:50]
    return {
        "ok": True,
        "conversations": rows,
        "unread_count": sum(int(row["unread_count"]) for row in rows),
        "signature": signature,
        "viewer_profile_id": viewer_id,
    }


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return str(value)


def conversation_messages(
    user_id: Any, conversation_id: str, *, user_uuid: Any = "",
    display_name: str = "", username: str = "", role_label: str = "Участник",
    limit: int = DEFAULT_HISTORY_PAGE, before_seq: int = 0,
) -> Dict[str, Any]:
    actor = _identity(
        user_id, user_uuid=user_uuid, display_name=display_name,
        username=username, role_label=role_label,
    )
    viewer_id = str(actor["profile_id"])
    lim = max(1, min(500, int(limit or DEFAULT_HISTORY_PAGE)))
    before = max(0, int(before_seq or 0))
    if _relational_reads():
        return _conversation_messages_relational(
            viewer_id, conversation_id, limit=lim, before_seq=before,
        )
    with _LOCK:
        doc = _load()
        conv = _require_participant(doc, conversation_id, viewer_id)
        history = _conversation_messages(doc, str(conv["conversation_id"]))
        if before:
            history = [row for row in history if int(row.get("seq") or 0) < before]
        window = history[-lim:]
        has_more = len(history) > len(window)
        profile_ids = [str(pid) for pid in conv.get("participant_profile_ids") or []]
        profiles = community.chat_public_profiles(viewer_id, profile_ids)
        return {
            "ok": True,
            "conversation": _public_conversation(doc, conv, viewer_id, profiles),
            "messages": [_public_message(row, profiles) for row in window],
            "has_more": has_more,
            "next_before_seq": int(window[0].get("seq") or 0) if (has_more and window) else 0,
            "viewer_profile_id": viewer_id,
        }


def _conversation_messages_relational(
    viewer_id: str, conversation_id: str, *, limit: int, before_seq: int,
) -> Dict[str, Any]:
    from . import storage_router
    from .production_storage import StorageError
    cid = _safe_id(conversation_id, "conversation_id")
    try:
        row = storage_router.sf_chat_conversation(cid, viewer_id)
        if row is None:
            # Membership is part of the query, so a non-participant and a
            # missing conversation are indistinguishable here — the same single
            # 404 the document path returns, for the same reason.
            raise SFChatError("Диалог не найден.", 404)
        page = storage_router.sf_chat_message_page(
            cid, limit=limit, before_seq=before_seq,
        )
        conversation = dict(row.get("conversation") or {})
        profile_ids = [str(pid) for pid in conversation.get("participant_profile_ids") or []]
        profiles = community.chat_public_profiles(viewer_id, profile_ids)
    except StorageError as exc:
        raise SFChatError(
            f"Production SF Chat repository unavailable ({exc.code}).", 503,
        ) from None
    messages = list(page.get("messages") or [])
    return {
        "ok": True,
        "conversation": _relational_conversation(row, viewer_id, profiles),
        "messages": [_public_message(message, profiles) for message in messages],
        "has_more": bool(page.get("has_more")),
        "next_before_seq": int(page.get("next_before_seq") or 0),
        "viewer_profile_id": viewer_id,
    }


def _store_attachments(
    value: Any, *, conversation_id: str, message_id: str,
) -> List[Dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > _MAX_ATTACHMENTS:
        raise SFChatError(f"Можно приложить до {_MAX_ATTACHMENTS} изображений.")
    target_dir = (_uploads_root() / conversation_id).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    root = _uploads_root().resolve()
    try:
        target_dir.relative_to(root)
    except ValueError:
        raise SFChatError("Некорректный путь вложения.") from None
    rows: List[Dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise SFChatError("Некорректное вложение SF Chat.")
        match = _ATTACHMENT_RE.fullmatch(str(raw.get("data_url") or ""))
        if not match:
            raise SFChatError("Поддерживаются только PNG, JPEG и WebP-изображения.")
        mime = match.group(1).lower()
        try:
            payload = base64.b64decode(match.group(2), validate=True)
        except (ValueError, binascii.Error):
            raise SFChatError("Повреждённые данные изображения.") from None
        if not payload or len(payload) > _MAX_ATTACHMENT_BYTES:
            raise SFChatError("Размер каждого изображения не должен превышать 2 МБ.")
        if not _image_payload_matches_mime(mime, payload):
            raise SFChatError("Содержимое изображения не соответствует MIME-типу.")
        attachment_id = "sfa_" + secrets.token_hex(9)
        stored_name = f"{message_id}_{index}{_MIME_EXTENSION[mime]}"
        target = (target_dir / stored_name).resolve()
        try:
            target.relative_to(target_dir)
        except ValueError:
            raise SFChatError("Некорректный путь вложения.") from None
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, target)
        name = re.sub(r"[\\/:*?\"<>|]+", "_", str(raw.get("name") or "image"))[:120]
        rows.append({
            "attachment_id": attachment_id,
            "name": name or "image",
            "mime_type": mime,
            "size": len(payload),
            "stored_name": stored_name,
        })
    return rows


def send_message(
    user_id: Any, conversation_id: str, *, text: str = "", attachments: Any = None,
    user_uuid: Any = "", display_name: str = "", username: str = "",
    role_label: str = "Участник", idempotency_key: str = "",
) -> Dict[str, Any]:
    actor = _identity(
        user_id, user_uuid=user_uuid, display_name=display_name,
        username=username, role_label=role_label,
    )
    viewer_id = str(actor["profile_id"])
    body = str(text or "").strip()
    if not body and not attachments:
        raise SFChatError("Сообщение не может быть пустым.")
    if len(body) > _MAX_MESSAGE:
        raise SFChatError("Сообщение слишком длинное.")
    key = str(idempotency_key or "").strip()
    if len(key) > 200:
        raise SFChatError("Idempotency key слишком длинный.")
    idem_hash = hashlib.sha256(key.encode("utf-8")).hexdigest() if key else ""
    with _LOCK:
        doc = _load()
        conv = _require_participant(doc, conversation_id, viewer_id)
        target_id = _other_profile_id(conv, viewer_id)
        try:
            community.chat_target(viewer_id, target_id)
        except community.CommunityError as exc:
            raise SFChatError(str(exc), exc.status) from None
        if idem_hash:
            existing = next((row for row in doc.get("messages") or []
                             if str(row.get("conversation_id") or "") == str(conversation_id)
                             and str(row.get("sender_profile_id") or "") == viewer_id
                             and str(row.get("idempotency_key_hash") or "") == idem_hash), None)
            if existing:
                profiles = community.chat_public_profiles(
                    viewer_id, [str(pid) for pid in conv.get("participant_profile_ids") or []],
                )
                return {"ok": True, "message": _public_message(existing, profiles), "deduplicated": True}
        next_seq = int(conv.get("last_seq") or 0) + 1
        message_id = "sfm_" + secrets.token_hex(9)
        stored = _store_attachments(
            attachments, conversation_id=str(conversation_id), message_id=message_id,
        )
        now = _now_iso()
        row = {
            "message_id": message_id,
            "conversation_id": str(conversation_id),
            "seq": next_seq,
            "sender_profile_id": viewer_id,
            "text": body,
            "attachments": stored,
            "created_at_utc": now,
        }
        if idem_hash:
            row["idempotency_key_hash"] = idem_hash
        doc.setdefault("messages", []).append(row)
        conv["last_seq"] = next_seq
        conv["updated_at_utc"] = now
        _mark_read_in_doc(doc, str(conversation_id), viewer_id, next_seq)
        profiles = community.chat_public_profiles(
            viewer_id, [str(pid) for pid in conv.get("participant_profile_ids") or []],
        )
        _save(doc)
        return {
            "ok": True,
            "message": _public_message(row, profiles),
            "conversation": _public_conversation(doc, conv, viewer_id, profiles),
            "deduplicated": False,
        }


def mark_read(
    user_id: Any, conversation_id: str, *, user_uuid: Any = "",
    display_name: str = "", username: str = "", role_label: str = "Участник",
) -> Dict[str, Any]:
    actor = _identity(
        user_id, user_uuid=user_uuid, display_name=display_name,
        username=username, role_label=role_label,
    )
    viewer_id = str(actor["profile_id"])
    if _relational_reads():
        # The open panel calls this on every refresh tick. Checking the read
        # pointer against the conversation head first costs two indexed lookups
        # and, in the steady state where nothing new arrived, avoids loading and
        # rewriting the whole document for a no-op advance.
        from . import storage_router
        from .production_storage import StorageError
        try:
            row = storage_router.sf_chat_conversation(_safe_id(conversation_id, "conversation_id"), viewer_id)
            if row is None:
                raise SFChatError("Диалог не найден.", 404)
            head = int((row.get("conversation") or {}).get("last_seq") or 0)
            already = int(row.get("last_read_seq") or 0)
        except StorageError as exc:
            raise SFChatError(
                f"Production SF Chat repository unavailable ({exc.code}).", 503,
            ) from None
        if already >= head:
            return {"ok": True, "conversation_id": str(conversation_id),
                    "read_through_seq": head, "advanced": 0}
    with _LOCK:
        doc = _load()
        conv = _require_participant(doc, conversation_id, viewer_id)
        last_seq = int(conv.get("last_seq") or 0)
        before = int((_read_row(doc, str(conversation_id), viewer_id) or {}).get("last_read_seq") or 0)
        _mark_read_in_doc(doc, str(conversation_id), viewer_id, last_seq)
        _save(doc)
        return {"ok": True, "conversation_id": str(conversation_id),
                "read_through_seq": last_seq, "advanced": max(0, last_seq - before)}


def attachment(
    user_id: Any, attachment_id: str, *, user_uuid: Any = "",
    display_name: str = "", username: str = "", role_label: str = "Участник",
) -> Dict[str, Any]:
    actor = _identity(
        user_id, user_uuid=user_uuid, display_name=display_name,
        username=username, role_label=role_label,
    )
    viewer_id = str(actor["profile_id"])
    aid = _safe_id(attachment_id, "attachment_id")
    with _LOCK:
        doc = _load()
        found_message: Optional[Dict[str, Any]] = None
        found_attachment: Optional[Dict[str, Any]] = None
        for message in doc.get("messages") or []:
            for row in message.get("attachments") or []:
                if str(row.get("attachment_id") or "") == aid:
                    found_message, found_attachment = message, row
                    break
            if found_attachment:
                break
        if found_message is None or found_attachment is None:
            raise SFChatError("Вложение не найдено.", 404)
        conv = _require_participant(doc, str(found_message.get("conversation_id") or ""), viewer_id)
        target = (_uploads_root() / str(conv["conversation_id"]) /
                  str(found_attachment.get("stored_name") or "")).resolve()
        root = _uploads_root().resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise SFChatError("Вложение не найдено.", 404) from None
        if not target.is_file():
            raise SFChatError("Вложение не найдено.", 404)
        return {
            "path": target,
            "mime_type": str(found_attachment.get("mime_type") or "application/octet-stream"),
            "size": int(found_attachment.get("size") or 0),
            "name": str(found_attachment.get("name") or "image"),
        }
