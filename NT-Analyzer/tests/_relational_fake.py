"""In-memory stand-in for the SF Chat / Community relational read side.

The production reads are single indexed statements against the `sf_chat_*` and
`sf_community_*` mirrors. A live PostgreSQL is the only place to measure their
latency, but the properties that matter for correctness and for scaling are
checkable without one:

* the relational projection must equal the document projection byte for byte,
* the hot path must never load a global document,
* an operation must cost a bounded number of statements, not one per row.

This fake evaluates each router call with the same semantics as the SQL it
stands in for — same ordering, same keyset cursor, same membership predicate,
same unread rule — and counts statements so tests can assert the absence of
N+1. It reads the very documents the store holds, so any drift between the two
projections shows up as a failed equality assertion rather than a silent
difference in Production.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


class RelationalFake:
    def __init__(self, documents: Dict[str, Dict[str, Any]]) -> None:
        self._documents = documents
        self.queries: List[str] = []
        self.rows_returned = 0
        self.bytes_returned = 0

    # -- helpers -------------------------------------------------------------
    def _doc(self, name: str) -> Dict[str, Any]:
        return self._documents.get(name) or {}

    def _conversations(self) -> List[Dict[str, Any]]:
        return [row for row in self._doc("sf_chat").get("conversations") or []
                if isinstance(row, dict)]

    def _messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        rows = [row for row in self._doc("sf_chat").get("messages") or []
                if isinstance(row, dict)
                and str(row.get("conversation_id") or "") == conversation_id
                and not row.get("deleted_at_utc")]
        return sorted(rows, key=lambda row: int(row.get("seq") or 0))

    def _read_seq(self, conversation_id: str, profile_id: str) -> int:
        for row in self._doc("sf_chat").get("reads") or []:
            if (str(row.get("conversation_id") or "") == conversation_id
                    and str(row.get("profile_id") or "") == profile_id):
                return int(row.get("last_read_seq") or 0)
        return 0

    def _participates(self, conversation: Dict[str, Any], profile_id: str) -> bool:
        return profile_id in [str(value) for value in
                              conversation.get("participant_profile_ids") or []]

    def _summary(self, conversation: Dict[str, Any], viewer: str) -> Dict[str, Any]:
        cid = str(conversation.get("conversation_id") or "")
        messages = self._messages(cid)
        last_read = self._read_seq(cid, viewer)
        unread = sum(1 for row in messages
                     if int(row.get("seq") or 0) > last_read
                     and str(row.get("sender_profile_id") or "") != viewer)
        return {
            "conversation_id": cid,
            "updated_at": str(conversation.get("updated_at_utc") or ""),
            "conversation": dict(conversation),
            "last_read_seq": last_read,
            "last_message": dict(messages[-1]) if messages else None,
            "message_count": len(messages),
            "unread_count": unread,
        }

    def _account(self, rows: Sequence[Dict[str, Any]]) -> None:
        self.rows_returned += len(rows)
        self.bytes_returned += len(repr(rows))

    # -- router surface ------------------------------------------------------
    def conversation_page(self, viewer: str, *, limit: int = 30,
                          cursor: str = "") -> Dict[str, Any]:
        self.queries.append("conversation_page")
        mine = [row for row in self._conversations() if self._participates(row, viewer)]
        mine.sort(key=lambda row: (str(row.get("updated_at_utc") or ""),
                                   str(row.get("conversation_id") or "")), reverse=True)
        if cursor:
            key = _decode(cursor)
            mine = [row for row in mine
                    if (str(row.get("updated_at_utc") or ""),
                        str(row.get("conversation_id") or "")) < key]
        window = mine[:limit]
        has_more = len(mine) > limit
        rows = [self._summary(row, viewer) for row in window]
        self._account(rows)
        next_cursor = ""
        if has_more and window:
            next_cursor = _encode(str(window[-1].get("updated_at_utc") or ""),
                                  str(window[-1].get("conversation_id") or ""))
        return {"rows": rows, "next_cursor": next_cursor, "has_more": has_more}

    def unread_total(self, viewer: str) -> int:
        self.queries.append("unread_total")
        total = 0
        for row in self._conversations():
            if self._participates(row, viewer):
                total += self._summary(row, viewer)["unread_count"]
        return total

    def poll_state(self, viewer: str) -> Dict[str, Any]:
        self.queries.append("poll_state")
        rows = []
        for row in self._conversations():
            if not self._participates(row, viewer):
                continue
            summary = self._summary(row, viewer)
            rows.append({
                "conversation_id": summary["conversation_id"],
                "last_seq": int(row.get("last_seq") or 0),
                "updated_at": summary["updated_at"],
                "last_read_seq": summary["last_read_seq"],
                "unread_count": summary["unread_count"],
            })
        rows.sort(key=lambda item: str(item["updated_at"]), reverse=True)
        signature = {
            "conversation_count": len(rows),
            "newest_updated_at": rows[0]["updated_at"] if rows else "",
            "seq_total": sum(int(row["last_seq"]) for row in rows),
        }
        rows = [row for row in rows if int(row["unread_count"]) > 0][:50]
        self._account(rows)
        return dict(signature, rows=rows)

    def conversation(self, conversation_id: str, viewer: str) -> Optional[Dict[str, Any]]:
        self.queries.append("conversation")
        for row in self._conversations():
            if (str(row.get("conversation_id") or "") == conversation_id
                    and self._participates(row, viewer)):
                summary = self._summary(row, viewer)
                self._account([summary])
                return summary
        return None

    def participant_profile_ids(self, conversation_id: str) -> List[str]:
        self.queries.append("participant_profile_ids")
        for row in self._conversations():
            if str(row.get("conversation_id") or "") == conversation_id:
                return sorted(str(value) for value in
                              row.get("participant_profile_ids") or [])
        return []

    def message_page(self, conversation_id: str, *, limit: int = 50,
                     before_seq: int = 0) -> Dict[str, Any]:
        self.queries.append("message_page")
        history = self._messages(conversation_id)
        if before_seq:
            history = [row for row in history if int(row.get("seq") or 0) < before_seq]
        window = history[-limit:] if limit else history
        has_more = len(history) > len(window)
        self._account(window)
        return {
            "messages": [dict(row) for row in window],
            "has_more": has_more,
            "next_before_seq": int(window[0].get("seq") or 0) if (has_more and window) else 0,
        }

    def read_seq(self, conversation_id: str, profile_id: str) -> int:
        self.queries.append("read_seq")
        return self._read_seq(conversation_id, profile_id)

    def profile_by_identity(self, user_id: int, user_uuid: str) -> Optional[Dict[str, Any]]:
        self.queries.append("profile_by_identity")
        canonical = str(user_uuid or "")
        for row in self._doc("community").get("profiles") or []:
            if canonical and str(row.get("user_uuid") or "") == canonical:
                return {"profile_id": str(row.get("profile_id") or ""),
                        "user_id": row.get("user_id"),
                        "user_uuid": row.get("user_uuid"), "document": dict(row)}
        if not canonical:
            for row in self._doc("community").get("profiles") or []:
                if int(row.get("user_id") or 0) == int(user_id or 0):
                    return {"profile_id": str(row.get("profile_id") or ""),
                            "user_id": row.get("user_id"),
                            "user_uuid": row.get("user_uuid"), "document": dict(row)}
        return None

    def public_profiles(self, viewer: str, profile_ids: Sequence[str]) -> List[Dict[str, Any]]:
        self.queries.append("public_profiles")
        wanted = {str(value) for value in profile_ids if str(value or "")}
        community = self._doc("community")
        follows = community.get("follows") or []
        blocks = community.get("social_blocks") or []
        posts = community.get("posts") or []
        rows = []
        for row in community.get("profiles") or []:
            pid = str(row.get("profile_id") or "")
            if pid not in wanted:
                continue
            rows.append({
                "profile_id": pid,
                "document": dict(row),
                "followers": sum(1 for f in follows
                                 if str(f.get("target_profile_id") or "") == pid),
                "following": sum(1 for f in follows
                                 if str(f.get("follower_profile_id") or "") == pid),
                "posts": sum(1 for p in posts
                             if str(p.get("author_profile_id") or "") == pid
                             and not p.get("deleted_at_utc")),
                "viewer_follows": any(
                    str(f.get("follower_profile_id") or "") == viewer
                    and str(f.get("target_profile_id") or "") == pid for f in follows),
                "follows_viewer": any(
                    str(f.get("follower_profile_id") or "") == pid
                    and str(f.get("target_profile_id") or "") == viewer for f in follows),
                "blocked": any(
                    {str(b.get("blocker_profile_id") or ""),
                     str(b.get("target_profile_id") or "")} == {viewer, pid}
                    for b in blocks),
            })
        self._account(rows)
        return rows


def _encode(updated_at: str, conversation_id: str) -> str:
    return f"{updated_at}|{conversation_id}"


def _decode(cursor: str) -> tuple:
    stamp, _, conversation_id = str(cursor).partition("|")
    return (stamp, conversation_id)


def install(monkeypatch, documents: Dict[str, Dict[str, Any]]) -> RelationalFake:
    """Point storage_router's relational surface at an in-memory fake."""
    from app import storage_router

    fake = RelationalFake(documents)
    monkeypatch.setattr(storage_router, "sf_chat_conversation_page",
                        lambda viewer, **kw: fake.conversation_page(viewer, **kw))
    monkeypatch.setattr(storage_router, "sf_chat_unread_total", fake.unread_total)
    monkeypatch.setattr(storage_router, "sf_chat_poll_state", fake.poll_state)
    monkeypatch.setattr(storage_router, "sf_chat_conversation", fake.conversation)
    monkeypatch.setattr(storage_router, "sf_chat_participant_profile_ids",
                        fake.participant_profile_ids)
    monkeypatch.setattr(storage_router, "sf_chat_message_page",
                        lambda cid, **kw: fake.message_page(cid, **kw))
    monkeypatch.setattr(storage_router, "sf_chat_read_seq", fake.read_seq)
    monkeypatch.setattr(storage_router, "community_public_profiles", fake.public_profiles)
    monkeypatch.setattr(storage_router, "community_profile_by_identity",
                        fake.profile_by_identity)
    return fake
