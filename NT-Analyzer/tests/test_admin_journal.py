from __future__ import annotations

import json

from app import admin_journal


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_journal_merges_and_sorts(monkeypatch, tmp_path):
    monkeypatch.setattr(admin_journal, "_root", lambda: tmp_path)
    audit = tmp_path / "data" / "audit"
    _write(audit / "account-auth.jsonl", [
        {"timestamp": "2026-07-01T10:00:00Z", "event": "login_succeeded", "user_id": 42, "ip": "203.0.113.1"},
        {"timestamp": "2026-07-03T10:00:00Z", "event": "user_blocked", "owner_id": 999, "user_id": 42},
    ])
    _write(audit / "telegram-mini-app.jsonl", [
        {"timestamp": "2026-07-02T10:00:00Z", "source": "telegram_mini_app", "method": "GET",
         "path": "/api/performance", "status": 403, "user_id": 77, "role": "read_only"},
    ])

    out = admin_journal.read_journal()
    ts = [e["timestamp"] for e in out["entries"]]
    assert ts == sorted(ts, reverse=True)  # newest first
    assert len(out["entries"]) == 3
    assert {c["id"] for c in out["categories"]} >= {"account", "mini_app"}


def test_journal_filters(monkeypatch, tmp_path):
    monkeypatch.setattr(admin_journal, "_root", lambda: tmp_path)
    audit = tmp_path / "data" / "audit"
    _write(audit / "account-auth.jsonl", [
        {"timestamp": "2026-07-01T10:00:00Z", "event": "login_succeeded", "user_id": 42},
        {"timestamp": "2026-07-03T10:00:00Z", "event": "user_deleted", "owner_id": 999, "user_id": 42},
    ])
    _write(audit / "telegram-mini-app.jsonl", [
        {"timestamp": "2026-07-02T10:00:00Z", "method": "GET", "path": "/api/x", "status": 403},
        {"timestamp": "2026-07-02T11:00:00Z", "method": "GET", "path": "/api/y", "status": 200},
    ])

    only_account = admin_journal.read_journal(category="account")
    assert all(e["category"] == "account" for e in only_account["entries"])

    suspicious = admin_journal.read_journal(suspicious_only=True)
    events = {e["event"] for e in suspicious["entries"]}
    # 403 request + user_deleted are suspicious; the 200 request is not.
    assert any(e["suspicious"] for e in suspicious["entries"])
    assert all(e["suspicious"] for e in suspicious["entries"])

    search = admin_journal.read_journal(query="deleted")
    assert search["entries"] and all("deleted" in e["event"] for e in search["entries"])
