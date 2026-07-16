"""Tests for the in-app notification inbox (Telegram dual-delivery)."""
from __future__ import annotations

import json

from app import in_app_notifications
from app import telegram_service


def _isolate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(in_app_notifications, "_root", lambda: tmp_path)
    monkeypatch.setattr(telegram_service, "_root", lambda: tmp_path)


def test_record_list_ack_and_dedupe(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)

    first = in_app_notifications.record(
        "Витьёк · нужен ваш ответ",
        ["Проверка проваленных стратегий — нужно внимание."],
        urgent=True,
        conversation_id="default",
        conversation_title="Основной чат",
        dedupe_key="vitek:inc-1",
        kind="chief_agent_reports",
    )
    assert first and first["id"]
    assert first["urgent"] is True

    again = in_app_notifications.record(
        "Витьёк · нужен ваш ответ",
        ["duplicate"],
        urgent=True,
        conversation_id="default",
        dedupe_key="vitek:inc-1",
        kind="chief_agent_reports",
    )
    assert again is None

    listed = in_app_notifications.list_notices(unread_only=True)
    assert listed["unread_count"] == 1
    assert listed["items"][0]["title"].startswith("Витьёк")
    assert listed["unread_by_conversation"].get("default") == 1

    acked = in_app_notifications.ack(conversation_id="default")
    assert acked["acked"] == 1
    listed2 = in_app_notifications.list_notices(unread_only=True)
    assert listed2["unread_count"] == 0
    assert listed2["unread_by_conversation"] == {}


def test_delete_and_clear_modes(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)

    a = in_app_notifications.record("A", ["one"], conversation_id="c1", dedupe_key="a")
    b = in_app_notifications.record("B", ["two"], conversation_id="c2", dedupe_key="b")
    c = in_app_notifications.record("C", ["three"], conversation_id="c1", dedupe_key="c")
    assert a and b and c

    listed = in_app_notifications.list_notices(unread_only=False, limit=20)
    assert listed["total_count"] == 3
    assert listed["unread_by_conversation"] == {"c1": 2, "c2": 1}

    deleted = in_app_notifications.delete(ids=[a["id"]])
    assert deleted["deleted"] == 1

    in_app_notifications.ack(ids=[b["id"]])
    cleared_read = in_app_notifications.clear(mode="read")
    assert cleared_read["cleared"] == 1
    assert cleared_read["mode"] == "read"

    left = in_app_notifications.list_notices(unread_only=False, limit=20)
    assert left["total_count"] == 1
    assert left["items"][0]["id"] == c["id"]
    assert left["unread_by_conversation"] == {"c1": 1}

    cleared_all = in_app_notifications.clear(mode="all")
    assert cleared_all["cleared"] == 1
    empty = in_app_notifications.list_notices(unread_only=False)
    assert empty["total_count"] == 0
    assert empty["items"] == []


def test_notify_writes_in_app_inbox(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456:ABCDEF")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "42")
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "integrations" / "telegram.settings.json").write_text(
        json.dumps({
            "enabled": True,
            "chief_agent_reports": True,
            "app_status": True,
            "strategy_state": True,
            "nt_connection": True,
            "application_errors": True,
            "price_alerts": True,
            "important_news": True,
            "daily_summary": True,
            "weekly_summary": True,
            "monthly_summary": True,
            "quarterly_summary": True,
        }),
        encoding="utf-8",
    )
    sent = []

    def fake_send(text, *, silent=True, thread_id=None):
        sent.append({"text": text, "silent": silent, "thread_id": thread_id})
        return True

    monkeypatch.setattr(telegram_service, "_send_raw", fake_send)

    ok = telegram_service.send_chief_report(
        "Тест",
        ["Сообщение для inbox"],
        urgent=True,
        conversation_id="default",
        conversation_title="Основной чат",
        dedupe_key="msg-test-1",
    )
    assert ok is True
    assert sent

    listed = in_app_notifications.list_notices(unread_only=True)
    assert listed["unread_count"] == 1
    assert "Сообщение для inbox" in listed["items"][0]["body"]
