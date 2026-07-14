from __future__ import annotations

import json
from datetime import datetime, timezone

from app import durable, local_secrets, telegram_service
from app.ai_lab import chief_agent


def _isolate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(telegram_service, "_root", lambda: tmp_path)
    monkeypatch.setattr(
        local_secrets,
        "secrets_path",
        lambda: tmp_path / "data" / "integrations" / "secrets.local.json",
    )
    monkeypatch.delenv(telegram_service.TOKEN_ENV, raising=False)
    monkeypatch.delenv(telegram_service.CHAT_ENV, raising=False)
    monkeypatch.delenv(telegram_service.GROUP_ENV, raising=False)
    monkeypatch.delenv(telegram_service.WEBHOOK_SECRET_ENV, raising=False)
    with telegram_service._PAIR_LOCK:
        telegram_service._PAIRING.clear()


def test_token_is_validated_and_never_returned(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"
    monkeypatch.setattr(
        telegram_service,
        "_bot_identity",
        lambda value=None: {"is_bot": True, "username": "StratForge_test_bot", "first_name": "StratForge"},
    )

    result = telegram_service.configure_token(token)

    assert result["token_configured"] is True
    assert result["chat_configured"] is False
    assert token not in json.dumps(result)
    stored = json.loads(local_secrets.secrets_path().read_text(encoding="utf-8"))
    assert stored[telegram_service.TOKEN_ENV] == token


def test_private_chat_pairing_uses_one_time_code(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456")
    monkeypatch.setattr(
        telegram_service,
        "_bot_identity",
        lambda value=None: {"is_bot": True, "username": "StratForge_test_bot"},
    )
    pair = telegram_service.start_pairing()

    def fake_api(method, payload=None, **_kwargs):
        assert method == "getUpdates"
        return [{
            "update_id": 1,
            "message": {
                "text": f"/start connect_{pair['code']}",
                "from": {"id": 42, "is_bot": False},
                "chat": {"id": 424242, "type": "private", "first_name": "Operator"},
            },
        }]

    sent = []
    monkeypatch.setattr(telegram_service, "_api_call", fake_api)
    monkeypatch.setattr(telegram_service, "_send_raw", lambda text, **_kwargs: sent.append(text) or {})

    result = telegram_service.complete_pairing()

    assert result["configured"] is True
    assert result["chat_label"] == "Operator"
    assert "424242" not in json.dumps(result)
    assert sent and "подключён" in sent[0]


def test_settings_are_persisted_without_secrets(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")

    result = telegram_service.update_settings({"enabled": True, "monthly_summary": False})

    assert result["settings"]["enabled"] is True
    assert result["settings"]["monthly_summary"] is False
    assert "fake-token" not in json.dumps(result)
    assert "987654" not in json.dumps(result)


def test_connection_transition_produces_urgent_notification(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    telegram_service._write_json(telegram_service._state_path(), {
        "initialized": True,
        "nt_connected": True,
        "strategies": {},
        "last_error_signature": "",
    })
    monkeypatch.setattr(telegram_service.runtime, "read_heartbeat", lambda: {
        "present": True, "fresh": False, "age_sec": 90.0,
    })
    monkeypatch.setattr(telegram_service.runtime, "read_strategies_raw", lambda: [])
    monkeypatch.setattr(telegram_service.runtime, "read_errors", lambda _limit=20: [])
    monkeypatch.setattr(telegram_service, "_poll_news", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(telegram_service, "_poll_chief_commands", lambda *_args, **_kwargs: None)
    notifications = []
    monkeypatch.setattr(
        telegram_service,
        "_notify",
        lambda setting, title, lines, **kwargs: notifications.append((setting, title, lines, kwargs)) or True,
    )

    result = telegram_service.poll_once(
        now_utc=datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc),
    )

    assert result["connected"] is False
    assert any(item[0] == "nt_connection" and "Потеряна связь" in item[1] for item in notifications)


def test_aurora_menu_exposes_only_telegram_label() -> None:
    from pathlib import Path

    ui = (Path(__file__).resolve().parents[1] / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (Path(__file__).resolve().parents[1] / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    assert "label: 'Telegram'" in ui
    assert "Интеграции и Telegram" not in ui
    assert "telegramSaveToken" in api and "/api/telegram/test" in api


def test_send_test_validates_bot_and_delivers(monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(telegram_service, "_bot_identity", lambda token=None: {"username": "StratForgeAI_bot"})
    monkeypatch.setattr(telegram_service, "_send_raw", lambda text, **kwargs: sent.append(text))

    result = telegram_service.send_test()

    assert result == {"ok": True, "bot_username": "StratForgeAI_bot"}
    assert sent and "Тест StratForge AI" in sent[0]


def test_paired_chat_routes_free_text_to_orchestrator(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    state = {"chief_commands_initialized": True, "chief_update_id": 9}
    monkeypatch.setattr(telegram_service, "_api_call", lambda *_a, **_k: [{
        "update_id": 10,
        "message": {"text": "Проверь сегодняшние бэктесты", "from": {"is_bot": False},
                    "chat": {"id": 987654, "type": "private"}},
    }])
    received = []
    monkeypatch.setattr(telegram_service, "_handle_chief_command", lambda text: received.append(text))

    telegram_service._poll_chief_commands(state)

    assert received == ["Проверь сегодняшние бэктесты"]
    assert state["chief_update_id"] == 10
    assert state["last_command_update_id"] == 10
    assert state["last_command_handler"] == "chief_private"


def test_first_pending_batch_is_processed_instead_of_discarded(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    state = {}
    monkeypatch.setattr(telegram_service, "_api_call", lambda *_a, **_k: [{
        "update_id": 10,
        "message": {"text": "покажи график 6С", "from": {"is_bot": False},
                    "chat": {"id": 987654, "type": "private"}},
    }])
    received = []
    monkeypatch.setattr(telegram_service, "_handle_chief_command", lambda text: received.append(text))

    telegram_service._poll_chief_commands(state)

    assert received == ["покажи график 6С"]
    assert state["chief_commands_initialized"] is True
    assert state["chief_update_id"] == 10
    assert state["last_command_transport"] == "poll"


def test_command_dispatcher_persists_offset_and_audit_per_update(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    updates = [
        {
            "update_id": 10,
            "message": {"text": "Первое", "from": {"is_bot": False},
                        "chat": {"id": 987654, "type": "private"}},
        },
        {
            "update_id": 11,
            "message": {"text": "Второе", "from": {"is_bot": False},
                        "chat": {"id": 987654, "type": "private"}},
        },
    ]
    monkeypatch.setattr(telegram_service, "_api_call", lambda *_a, **_k: updates)
    received = []
    monkeypatch.setattr(telegram_service, "_handle_chief_command", lambda text: received.append(text))
    state = {"chief_commands_initialized": True, "chief_update_id": 9}

    telegram_service._poll_chief_commands(state)

    assert received == ["Первое", "Второе"]
    assert state["chief_update_id"] == 11
    assert int(state.get("chief_update_inflight") or 0) == 0
    audit_path = tmp_path / "data" / "audit" / "telegram-updates.jsonl"
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert [row["update_id"] for row in rows] == [10, 11]
    assert all(row["consumed"] for row in rows)
    assert telegram_service.status()["telegram_update_offset"] == 11


def test_notifier_save_preserves_concurrent_webhook_offset(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    telegram_service._write_json(telegram_service._state_path(), {
        "initialized": True, "chief_update_id": 77,
        "chief_commands_initialized": True, "last_command_handler": "chief_group",
    })
    stale_notifier = {
        "initialized": True, "monitoring": True,
        "webhook_error": "stale tunnel error",
    }

    telegram_service._save_notifier_state(stale_notifier)

    saved = telegram_service._load_state()
    assert saved["chief_update_id"] == 77
    assert saved["chief_commands_initialized"] is True
    assert saved["last_command_handler"] == "chief_group"
    assert "webhook_error" not in saved


def test_failed_command_reply_is_queued_and_retried(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    attempts = []

    def failing_send(text, **kwargs):
        attempts.append((text, kwargs))
        raise telegram_service.TelegramServiceError("temporary send failure")

    monkeypatch.setattr(telegram_service, "_send_raw", failing_send)
    assert telegram_service._chief_command_reply("готово", thread_id=42) is False
    queued = telegram_service._read_json(telegram_service._reply_outbox_path())["items"]
    assert len(queued) == 1 and queued[0]["thread_id"] == 42

    monkeypatch.setattr(telegram_service, "_send_raw", lambda text, **kwargs: attempts.append((text, kwargs)) or {})
    flushed = telegram_service._flush_reply_outbox()
    assert flushed == {"sent": 1, "pending": 0}
    assert telegram_service._read_json(telegram_service._reply_outbox_path())["items"] == []


def test_webhook_duplicate_update_is_not_executed_twice(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.WEBHOOK_SECRET_ENV, "webhook-secret")
    telegram_service._write_json(telegram_service._state_path(), {
        "chief_update_id": 101, "chief_commands_initialized": True,
    })
    calls = []
    monkeypatch.setattr(telegram_service, "_dispatch_command_update", lambda *args, **kwargs: calls.append(1))

    result = telegram_service.process_webhook_update({"update_id": 101}, "webhook-secret")

    assert result["handler"] == "duplicate_update"
    assert result["consumed"] is True
    assert calls == []


def test_command_dispatcher_retries_then_drops_poison_update(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    update = {
        "update_id": 12,
        "message": {"text": "сломайся", "from": {"is_bot": False},
                    "chat": {"id": 987654, "type": "private"}},
    }
    monkeypatch.setattr(telegram_service, "_api_call", lambda *_a, **_k: [update])
    monkeypatch.setattr(
        telegram_service,
        "_handle_chief_command",
        lambda text: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    state = {"chief_commands_initialized": True, "chief_update_id": 11}

    telegram_service._poll_chief_commands(state)
    assert state["chief_update_id"] == 11
    assert state["chief_update_retries"]["12"] == 1

    telegram_service._poll_chief_commands(state)
    telegram_service._poll_chief_commands(state)
    assert state["chief_update_id"] == 12
    assert "12" not in state.get("chief_update_retries", {})
    rows = [
        json.loads(line)
        for line in (tmp_path / "data" / "audit" / "telegram-updates.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["dropped"] is True
    assert rows[-1]["retry_count"] == 3


def test_command_receiver_uses_long_poll_for_low_latency(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    captured = {}

    def fake_api(method, payload=None, **kwargs):
        captured.update({"method": method, "payload": payload or {}, **kwargs})
        return []

    monkeypatch.setattr(telegram_service, "_api_call", fake_api)
    state = {"chief_commands_initialized": True, "chief_update_id": 10}

    telegram_service._poll_chief_commands(state, long_poll_timeout=20)

    assert captured["method"] == "getUpdates"
    assert captured["payload"]["timeout"] == 20
    assert captured["timeout"] == 25


def test_forum_topic_is_created_once_and_dedupes(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.GROUP_ENV, "-1001234567890")
    calls: list = []

    def fake_api(method, payload=None, **kwargs):
        calls.append(method)
        if method == "createForumTopic":
            return {"message_thread_id": 42, "name": (payload or {}).get("name")}
        return {}

    monkeypatch.setattr(telegram_service, "_api_call", fake_api)

    first = telegram_service.ensure_topic("C-ABC", "Стратегия MNQ")
    second = telegram_service.ensure_topic("C-ABC", "Стратегия MNQ")

    assert first["message_thread_id"] == 42
    assert second["message_thread_id"] == 42
    assert calls.count("createForumTopic") == 1  # no duplicate topic
    assert telegram_service._conversation_for_thread("-1001234567890", 42) == "C-ABC"
    # unbound / General topic → default app chat
    assert telegram_service._conversation_for_thread("-1001234567890", None) == "default"


def test_forum_topic_title_tracks_app_conversation(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.GROUP_ENV, "-1001234567890")
    calls = []

    def fake_api(method, payload=None, **kwargs):
        calls.append((method, payload or {}))
        if method == "createForumTopic":
            return {"message_thread_id": 42, "name": (payload or {}).get("name")}
        return {}

    monkeypatch.setattr(telegram_service, "_api_call", fake_api)
    telegram_service.ensure_topic("C-ABC", "Новый чат")
    updated = telegram_service.sync_topic_title("C-ABC", "Исследование MNQ")

    assert updated["name"] == "Исследование MNQ"
    edits = [payload for method, payload in calls if method == "editForumTopic"]
    assert edits == [{"chat_id": "-1001234567890", "message_thread_id": 42, "name": "Исследование MNQ"}]


def test_owner_app_message_is_mirrored_into_bound_topic(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.GROUP_ENV, "-1001234567890")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    monkeypatch.setattr(telegram_service, "_api_call",
                        lambda *a, **k: {"message_thread_id": 77, "name": "тема"})
    telegram_service.ensure_topic("C-ABC", "тема")

    sent = []
    monkeypatch.setattr(telegram_service, "_send_raw",
                        lambda text, **kwargs: sent.append((text, kwargs)) or {})

    ok = telegram_service.mirror_owner_message(
        "Проверь статус MNQ", conversation_id="C-ABC", conversation_title="тема",
    )

    assert ok is True
    assert len(sent) == 1
    text, kwargs = sent[0]
    assert "Проверь статус MNQ" in text
    assert "Вы:" in text
    assert kwargs.get("thread_id") == 77


def test_owner_app_message_mirror_respects_master_switch(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": False})
    sent = []
    monkeypatch.setattr(telegram_service, "_send_raw",
                        lambda text, **kwargs: sent.append(text) or {})

    ok = telegram_service.mirror_owner_message("привет", conversation_id="C-ABC")

    assert ok is False
    assert sent == []


def test_incoming_topic_message_uses_scoped_app_conversation(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    durable.record_chat_conversation(tmp_path, {
        "scope_id": "", "conversation_id": "C-SYNC", "title": "legacy",
        "updated_at_utc": "2026-07-11T01:00:00Z",
    })
    durable.record_chat_conversation(tmp_path, {
        "scope_id": "u42__ws_owner", "conversation_id": "C-SYNC",
        "user_id": "42", "workspace_id": "ws_owner", "membership_role": "owner",
        "title": "scoped", "updated_at_utc": "2026-07-11T02:00:00Z",
    })
    captured = {}
    monkeypatch.setattr(chief_agent, "migrate_legacy_conversation_to_scope",
                        lambda cid, scope: captured.update({"migrated": (cid, scope)}) or {"migrated": 0})
    monkeypatch.setattr(chief_agent, "handle_message", lambda text, **kwargs: captured.update({
        "text": text, **kwargs,
    }) or {"reply": "готово"})
    replies = []
    monkeypatch.setattr(telegram_service, "_chief_command_reply",
                        lambda text, **kwargs: replies.append((text, kwargs)))

    telegram_service._handle_chief_command(
        "ответ из Telegram", conversation_id="C-SYNC", thread_id=77,
    )

    assert captured["conversation_id"] == "C-SYNC"
    assert captured["scope"]["user_id"] == 42
    assert captured["scope"]["workspace_id"] == "ws_owner"
    assert captured["scope"]["is_owner"] is True
    assert captured["migrated"][0] == "C-SYNC"
    assert replies and replies[0][1]["thread_id"] == 77


def test_getupdates_process_lease_rejects_second_local_owner(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(telegram_service, "_updates_lease_path", lambda: tmp_path / "updates.lock")
    original = telegram_service._UPDATES_LEASE
    telegram_service._UPDATES_LEASE = None
    first = None
    try:
        assert telegram_service._acquire_updates_lease() is True
        first = telegram_service._UPDATES_LEASE
        telegram_service._UPDATES_LEASE = None
        assert telegram_service._acquire_updates_lease() is False
    finally:
        if telegram_service._UPDATES_LEASE is not None and telegram_service._UPDATES_LEASE is not first:
            telegram_service._UPDATES_LEASE.close()
        if first is not None:
            first.close()
        telegram_service._UPDATES_LEASE = original


def test_webhook_configuration_uses_secret_and_public_tunnel(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456")
    monkeypatch.setattr(telegram_service.telegram_remote, "admin_status", lambda: {
        "remote_enabled": True, "public_url": "https://app.example.test",
    })
    monkeypatch.setattr(telegram_service, "_webhook_reachable", lambda _url: True)
    saved = {}
    monkeypatch.setattr(local_secrets, "update", lambda values: saved.update(values) or True)
    calls = []
    monkeypatch.setattr(telegram_service, "_api_call",
                        lambda method, payload=None, **kwargs: calls.append((method, payload)) or True)

    out = telegram_service.ensure_webhook()

    assert out == {
        "ok": True, "configured": True,
        "url": "https://app.example.test/api/telegram/webhook",
    }
    assert saved[telegram_service.WEBHOOK_SECRET_ENV]
    method, payload = calls[0]
    assert method == "setWebhook"
    assert payload["secret_token"] == saved[telegram_service.WEBHOOK_SECRET_ENV]
    assert "secret" not in out


def test_dead_webhook_is_removed_without_dropping_pending_updates(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setattr(telegram_service.telegram_remote, "admin_status", lambda: {
        "remote_enabled": True, "public_url": "https://dead.example.test",
    })
    monkeypatch.setattr(telegram_service, "_webhook_reachable", lambda _url: False)
    calls = []
    monkeypatch.setattr(telegram_service, "_api_call",
                        lambda method, payload=None, **kwargs: calls.append((method, payload)) or True)

    out = telegram_service.ensure_webhook()

    assert out["reason"] == "public_tunnel_unreachable"
    assert calls == [("deleteWebhook", {"drop_pending_updates": False})]
    state = telegram_service._load_state()
    assert state["webhook_configured"] is False
    assert "long polling" in state["webhook_error"]


def test_webhook_probe_self_heals_configured_tunnel(monkeypatch) -> None:
    from app import tunnel_manager

    monkeypatch.setattr(tunnel_manager, "status", lambda **kwargs: {
        "public": {"reachable": False}, "remote_enabled": True,
        "cloudflared": {"config_exists": True},
    })
    starts = []
    monkeypatch.setattr(tunnel_manager, "start", lambda **kwargs: starts.append(kwargs) or {
        "ready": True, "public": {"reachable": True},
    })

    assert telegram_service._webhook_reachable("https://app.example.test") is True
    assert starts == [{"port": 8765, "wait_sec": 6}]


def test_webhook_rejects_bad_secret_and_dispatches_valid_update(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.WEBHOOK_SECRET_ENV, "expected-secret")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "42")
    monkeypatch.setattr(telegram_service, "_dispatch_command_update", lambda update, **kwargs: {
        "update_id": update["update_id"], "handler": "chief_private", "consumed": True, "error": "",
    })
    update = {"update_id": 9001, "message": {"text": "привет"}}

    try:
        telegram_service.process_webhook_update(update, "wrong")
    except telegram_service.TelegramServiceError as exc:
        assert "подпись" in str(exc)
    else:
        raise AssertionError("bad webhook secret must be rejected")

    result = telegram_service.process_webhook_update(update, "expected-secret")
    assert result["handler"] == "chief_private"
    state = telegram_service._load_state()
    assert state["chief_update_id"] == 9001
    assert state["last_command_transport"] == "webhook"


def test_identical_chief_report_is_sent_only_once(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    sent = []
    monkeypatch.setattr(telegram_service, "_send_raw", lambda text, **kwargs: sent.append(text) or {})

    first = telegram_service.send_chief_report("Готово", ["Результат не изменился"])
    second = telegram_service.send_chief_report("Готово", ["Результат не изменился"])

    assert first is True
    assert second is False
    assert len(sent) == 1


def test_send_document_uses_telegram_document_endpoint(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    report = tmp_path / "report.txt"
    report.write_text("verified report", encoding="utf-8")
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = request.data
        return Response()

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", fake_urlopen)

    assert telegram_service.send_document(report, "Отчёт") is True
    assert captured["url"].endswith("/sendDocument")
    assert b'name="document"' in captured["body"]
    assert b"verified report" in captured["body"]


def test_interactive_reply_with_dedupe_key_is_always_sent(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    sent = []
    monkeypatch.setattr(telegram_service, "_send_raw", lambda text, **kwargs: sent.append(text) or {})

    # Two identical chat replies (e.g. two answers to "Как дела?") must both be
    # delivered — the 24h text-dedup must not swallow the second.
    first = telegram_service.send_chief_report("StratForge Orchestrator", ["Всё под контролем."], dedupe_key="MSG-1")
    second = telegram_service.send_chief_report("StratForge Orchestrator", ["Всё под контролем."], dedupe_key="MSG-2")
    # The very same message id is still a true duplicate and is suppressed.
    third = telegram_service.send_chief_report("StratForge Orchestrator", ["Всё под контролем."], dedupe_key="MSG-2")

    assert first is True and second is True
    assert third is False
    assert len(sent) == 2


def test_group_topic_message_routes_to_bound_conversation(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.GROUP_ENV, "-1001234567890")
    monkeypatch.setattr(telegram_service, "_api_call", lambda *a, **k: {"message_thread_id": 55, "name": "x"})
    telegram_service.ensure_topic("C-XYZ", "тема")

    monkeypatch.setattr(
        telegram_service, "_api_call",
        lambda method, payload=None, **k: ([{
            "update_id": 100,
            "message": {
                "text": "проверь статус", "from": {"is_bot": False},
                "chat": {"id": -1001234567890, "type": "supergroup"},
                "message_thread_id": 55,
            },
        }] if method == "getUpdates" else {}),
    )
    captured: dict = {}
    monkeypatch.setattr(telegram_service, "_handle_chief_command",
                        lambda text, **kwargs: captured.update({"text": text, **kwargs}))

    state = {"chief_commands_initialized": True, "chief_update_id": 99}
    telegram_service._poll_chief_commands(state)

    assert captured["text"] == "проверь статус"
    assert captured["conversation_id"] == "C-XYZ"
    assert captured["thread_id"] == 55
    assert state["chief_update_id"] == 100


def test_telegram_vitek_message_uses_orchestrator_once(monkeypatch, tmp_path) -> None:
    from app import vitek

    _isolate(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(chief_agent, "handle_message", lambda text, **kwargs: calls.append((text, kwargs)) or {
        "reply": "Витёк: активных задач нет; открытых ситуаций: 2.",
        "domain_agent": "vitek",
        "gateway": {"ingress": "stratforge_orchestrator", "target": "vitek", "single_response": True},
    })
    # Telegram must never call Vitek around the gateway and create a second
    # reply. The only Vitek call belongs inside chief_agent.handle_message.
    monkeypatch.setattr(vitek, "handle_text_command", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Telegram bypassed the Orchestrator gateway")
    ))
    replies = []
    monkeypatch.setattr(telegram_service, "_chief_command_reply", lambda text, **kwargs: replies.append(text) or True)

    result = telegram_service._handle_chief_command(
        "Витя перечисли список нерешённых задач", conversation_id="default", thread_id=88,
    )

    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][0].startswith("Витя")
    assert calls[0][1]["source"] == "telegram"
    assert calls[0][1]["mirror_to_telegram"] is False
    assert len(replies) == 1
    assert "активных задач нет" in replies[0]


def test_configure_group_requires_forum_topics(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(telegram_service, "_bot_identity", lambda value=None: {"is_bot": True, "id": 555})
    monkeypatch.setattr(
        telegram_service, "_api_call",
        lambda method, payload=None, **k: ({"type": "supergroup", "is_forum": False, "title": "G"} if method == "getChat" else {}),
    )
    try:
        telegram_service.configure_group("-1001234567890")
    except telegram_service.TelegramServiceError as exc:
        assert "темы" in str(exc).lower()
    else:
        raise AssertionError("must require forum topics enabled")
