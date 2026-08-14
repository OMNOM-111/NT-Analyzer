from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from datetime import datetime, timezone

import pytest

from app import durable, local_secrets, runtime_env, telegram_service
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
    monkeypatch.delenv("NTA_COMMUNITY_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("NTA_APP_ENV", raising=False)
    monkeypatch.delenv("NTA_ENV", raising=False)
    monkeypatch.delenv("NTA_STAGING_ALLOW_OWNER_TELEGRAM", raising=False)
    with telegram_service._PAIR_LOCK:
        telegram_service._PAIRING.clear()
    with telegram_service._WEBHOOK_RUN_LOCK:
        telegram_service._WEBHOOK_ACTIVE.clear()
    telegram_service._BOT_USERNAME_CACHE = ""


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


def test_bot_username_falls_back_to_configured_token_identity(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456")
    monkeypatch.setattr(
        telegram_service,
        "_bot_identity",
        lambda value=None: {"is_bot": True, "username": "StratForge_bot"},
    )
    telegram_service._BOT_USERNAME_CACHE = ""

    assert telegram_service.bot_username() == "StratForge_bot"


def test_server_auth_paths_use_bot_username_fallback() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(encoding="utf-8")

    assert 'load_settings().get("bot_username")' not in source
    assert "telegram_service.bot_username()" in source


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


def test_connection_transition_does_not_duplicate_vitek_notification(monkeypatch, tmp_path) -> None:
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
    assert not any(item[0] == "nt_connection" for item in notifications)


def test_aurora_telegram_controls_live_only_in_capability_gated_admin_panel() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (root / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    server = (root / "app" / "server.py").read_text(encoding="utf-8")
    topbar = ui.split("function wireTopbar()", 1)[1].split("function environmentHtml", 1)[0]
    assert "label: 'Telegram'" not in topbar
    assert "Интеграции и Telegram" not in ui
    assert "hasAdminCapability('connectors.manage')" in ui
    assert '"label": "Коннекторы и Telegram", "capability": "connectors.manage"' in server
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
    monkeypatch.setattr(telegram_service, "_handle_chief_command", lambda text, **kwargs: received.append(text))

    telegram_service._poll_chief_commands(state)

    deadline = time.time() + 2
    while not received and time.time() < deadline:
        time.sleep(0.01)
    assert received == ["Проверь сегодняшние бэктесты"]
    deadline = time.time() + 2
    while telegram_service._WEBHOOK_ACTIVE and time.time() < deadline:
        time.sleep(0.01)
    assert state["chief_update_id"] == 10
    assert state["last_command_update_id"] == 10
    assert state["last_command_handler"] == "queued"


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
    monkeypatch.setattr(telegram_service, "_handle_chief_command", lambda text, **kwargs: received.append(text))

    telegram_service._poll_chief_commands(state)

    deadline = time.time() + 2
    while not received and time.time() < deadline:
        time.sleep(0.01)
    assert received == ["покажи график 6С"]
    deadline = time.time() + 2
    while telegram_service._WEBHOOK_ACTIVE and time.time() < deadline:
        time.sleep(0.01)
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
    monkeypatch.setattr(telegram_service, "_handle_chief_command", lambda text, **kwargs: received.append(text))
    state = {"chief_commands_initialized": True, "chief_update_id": 9}

    telegram_service._poll_chief_commands(state)

    deadline = time.time() + 3
    while len(received) < 2 and time.time() < deadline:
        telegram_service._dispatch_update_inbox()
        time.sleep(0.01)
    assert received == ["Первое", "Второе"]
    deadline = time.time() + 2
    while telegram_service._WEBHOOK_ACTIVE and time.time() < deadline:
        time.sleep(0.01)
    assert state["chief_update_id"] == 11
    assert int(state.get("chief_update_inflight") or 0) == 0
    audit_path = tmp_path / "data" / "audit" / "telegram-updates.jsonl"
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    accepted = [row for row in rows if row["phase"] == "accepted"]
    completed = [row for row in rows if row["phase"] == "completed"]
    assert [row["update_id"] for row in accepted] == [10, 11]
    assert [row["update_id"] for row in completed] == [10, 11]
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


def test_reply_outbox_poison_topic_does_not_block_others_and_dead_letters(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    telegram_service._enqueue_reply_outbox("poison", thread_id=11, dedupe_key="POISON")
    telegram_service._enqueue_reply_outbox("healthy", thread_id=22, dedupe_key="HEALTHY")
    delivered = []

    def selective_send(text, **kwargs):
        if kwargs.get("thread_id") == 11:
            raise telegram_service.TelegramServiceError("topic deleted")
        delivered.append((text, kwargs.get("thread_id")))
        return {}

    monkeypatch.setattr(telegram_service, "_send_raw", selective_send)

    first = telegram_service._flush_reply_outbox(limit=10)

    assert first == {"sent": 1, "pending": 1}
    assert delivered == [("healthy", 22)]
    rows = telegram_service._read_json(telegram_service._reply_outbox_path())["items"]
    assert len(rows) == 1
    assert rows[0]["thread_id"] == 11
    assert rows[0]["status"] == "queued"
    assert rows[0]["attempts"] == 1
    assert telegram_service._iso_timestamp(rows[0]["available_at_utc"]) > time.time()

    rows[0]["attempts"] = telegram_service.REPLY_MAX_ATTEMPTS - 1
    rows[0]["available_at_utc"] = "2000-01-01T00:00:00Z"
    telegram_service._write_json(
        telegram_service._reply_outbox_path(), {"items": rows, "updated_at_utc": "2026-07-14T00:00:00Z"},
    )

    final = telegram_service._flush_reply_outbox(limit=10)

    assert final == {"sent": 0, "pending": 0}
    dead = telegram_service._read_json(telegram_service._reply_outbox_path())["items"]
    assert dead[0]["status"] == "dead_letter"
    assert dead[0]["attempts"] == telegram_service.REPLY_MAX_ATTEMPTS
    assert "available_at_utc" not in dead[0]
    assert telegram_service.status()["telegram_reply_queue"] == {
        "queued": 0, "dead_letter": 1,
        "max_attempts": telegram_service.REPLY_MAX_ATTEMPTS,
    }


def test_reply_outbox_never_silently_truncates_accepted_replies(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    existing = [{
        "id": f"tgr_{index}", "signature": f"signature-{index}",
        "text": f"reply-{index}", "thread_id": index + 1,
        "status": "queued", "created_at_utc": "2026-07-14T00:00:00Z",
        "available_at_utc": "2026-07-14T00:00:00Z", "attempts": 0,
        "last_error": "",
    } for index in range(200)]
    telegram_service._write_json(
        telegram_service._reply_outbox_path(), {"items": existing, "updated_at_utc": "2026-07-14T00:00:00Z"},
    )

    for index in range(5):
        telegram_service._enqueue_reply_outbox(
            f"new-reply-{index}", thread_id=500 + index, dedupe_key=f"NEW-{index}",
        )

    rows = telegram_service._read_json(telegram_service._reply_outbox_path())["items"]
    assert len(rows) == 205
    assert {row["text"] for row in rows[-5:]} == {f"new-reply-{index}" for index in range(5)}


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
        lambda text, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    state = {"chief_commands_initialized": True, "chief_update_id": 11}

    telegram_service._poll_chief_commands(state)
    assert state["chief_update_id"] == 12
    deadline = time.time() + 2
    while telegram_service._WEBHOOK_ACTIVE and time.time() < deadline:
        time.sleep(0.01)
    for _attempt in range(2):
        doc = telegram_service._read_json(telegram_service._update_inbox_path())
        doc["items"][0]["available_at_utc"] = "2000-01-01T00:00:00Z"
        telegram_service._write_json(telegram_service._update_inbox_path(), doc)
        assert telegram_service._dispatch_update_inbox() == 1
        deadline = time.time() + 2
        while telegram_service._WEBHOOK_ACTIVE and time.time() < deadline:
            time.sleep(0.01)
    queued = telegram_service._read_json(telegram_service._update_inbox_path())["items"]
    assert queued[0]["status"] == "dead_letter"
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


def test_canary_login_update_is_forwarded_from_shared_webhook(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(telegram_service.runtime_env, "deployment_environment", lambda: runtime_env.PRODUCTION)
    forwarded = []
    monkeypatch.setattr(
        telegram_service,
        "_forward_update_to_environment",
        lambda update, environment: forwarded.append((environment, update)) or True,
    )
    monkeypatch.setattr(
        telegram_service.account_auth,
        "process_update",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("production auth must not consume canary login")),
    )

    result = telegram_service._dispatch_command_update({
        "update_id": 501,
        "message": {
            "text": "/start canary_login_ABCD1234",
            "from": {"id": 987654},
            "chat": {"id": 987654, "type": "private"},
        },
    }, private_id="987654", gid="", handle_owner_commands=False)

    assert result["handler"] == "canary_forward"
    assert result["consumed"] is True
    assert forwarded and forwarded[0][0] == runtime_env.CANARY


def test_canary_forward_can_use_internal_loopback_origin(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("STRATFORGE_CANARY_INTERNAL_ORIGIN", "http://127.0.0.1:18765")
    monkeypatch.setenv(telegram_service.WEBHOOK_SECRET_ENV, "secret")
    monkeypatch.setattr(telegram_service.runtime_env, "deployment_environment", lambda: runtime_env.PRODUCTION)
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["host"] = request.get_header("Host")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", fake_urlopen)

    assert telegram_service._forward_update_to_environment({"update_id": 1}, runtime_env.CANARY) is True
    assert captured == {
        "url": "http://127.0.0.1:18765/api/telegram/webhook",
        "host": "canary.stratforges.com",
        "timeout": 5,
    }


def test_unclaimed_contact_update_is_forwarded_to_canary(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(telegram_service.runtime_env, "deployment_environment", lambda: runtime_env.PRODUCTION)
    monkeypatch.setattr(telegram_service.account_auth, "process_update", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(telegram_service.telegram_remote, "process_update", lambda *_args, **_kwargs: False)
    forwarded = []
    monkeypatch.setattr(
        telegram_service,
        "_forward_update_to_environment",
        lambda update, environment: forwarded.append((environment, update)) or True,
    )

    result = telegram_service._dispatch_command_update({
        "update_id": 502,
        "message": {
            "contact": {"user_id": 987654, "phone_number": "+15551234567"},
            "from": {"id": 987654},
            "chat": {"id": 987654, "type": "private"},
        },
    }, private_id="987654", gid="", handle_owner_commands=False)

    assert result["handler"] == "canary_contact_forward"
    assert result["consumed"] is True
    assert forwarded and forwarded[0][0] == runtime_env.CANARY


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


def test_failed_owner_mirrors_queue_identical_text_by_message_id(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    monkeypatch.setattr(
        telegram_service, "_send_raw",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            telegram_service.TelegramServiceError("network down")
        ),
    )

    first = telegram_service.mirror_owner_message("одинаковый текст", dedupe_key="MSG-1")
    second = telegram_service.mirror_owner_message("одинаковый текст", dedupe_key="MSG-2")
    duplicate = telegram_service.mirror_owner_message("одинаковый текст", dedupe_key="MSG-2")

    queued = telegram_service._read_json(telegram_service._reply_outbox_path())["items"]
    assert first is False and second is False and duplicate is False
    assert len(queued) == 2


def test_successful_owner_mirror_is_deduplicated_by_message_id(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    sent = []
    monkeypatch.setattr(
        telegram_service, "_send_raw",
        lambda text, **kwargs: sent.append((text, kwargs)) or {},
    )

    assert telegram_service.mirror_owner_message("одинаковый текст", dedupe_key="MSG-SAME") is True
    assert telegram_service.mirror_owner_message("одинаковый текст", dedupe_key="MSG-SAME") is False
    assert len(sent) == 1


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
    }) or {
        "reply": "готово",
        "message": {"message_id": "MSG-SYNC", "conversation_scope_id": "u42__ws_owner"},
    })
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


def test_default_topic_resolves_sender_workspace_without_durable_chat(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.CHAT_ENV, "42")
    monkeypatch.setattr(telegram_service.account_auth, "find_active_user", lambda uid: {
        "user_id": uid, "first_name": "Дмитрий", "last_name": "Червенко",
        "role": "owner", "is_owner": True,
    })
    monkeypatch.setattr(telegram_service.workspaces, "context_for_user", lambda *args, **kwargs: {
        "active_workspace": {
            "workspace_id": "ws_owner_training", "kind": "owner_training",
            "uses_owner_runtime": True,
        },
        "active_membership": {"role": "owner"},
        "uses_owner_runtime": True,
    })

    scope = telegram_service._conversation_scope_for_topic(
        "default", sender_user_id=42, sender_name="Telegram Name",
    )

    assert scope == {
        "user_id": 42,
        "workspace_id": "ws_owner_training",
        "workspace_kind": "owner_training",
        "uses_owner_runtime": True,
        "membership_role": "owner",
        "is_owner": True,
        "display_name": "Дмитрий Червенко",
    }


def test_named_topic_prefers_exact_sender_scope_over_newer_other_user(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(telegram_service.account_auth, "find_active_user", lambda uid: {
        "user_id": uid, "first_name": "Owner", "role": "owner", "is_owner": True,
    })
    monkeypatch.setattr(telegram_service.workspaces, "context_for_user", lambda *args, **kwargs: {
        "active_workspace": {"workspace_id": "ws-one", "kind": "owner_training"},
        "active_membership": {"role": "owner"}, "uses_owner_runtime": True,
    })
    durable.record_chat_conversation(tmp_path, {
        "scope_id": "u42__ws-one", "conversation_id": "C-SHARED",
        "user_id": "42", "workspace_id": "ws-one", "membership_role": "owner",
        "updated_at_utc": "2026-07-13T01:00:00Z",
    })
    durable.record_chat_conversation(tmp_path, {
        "scope_id": "u99__ws-other", "conversation_id": "C-SHARED",
        "user_id": "99", "workspace_id": "ws-other", "membership_role": "owner",
        "updated_at_utc": "2026-07-13T02:00:00Z",
    })

    scope = telegram_service._conversation_scope_for_topic("C-SHARED", sender_user_id=42)

    assert scope["user_id"] == 42
    assert scope["workspace_id"] == "ws-one"


def test_group_dispatch_audits_the_exact_scoped_reply(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.GROUP_ENV, "-1001")
    monkeypatch.setattr(telegram_service, "_conversation_for_thread", lambda gid, tid: "default")
    captured = {}
    monkeypatch.setattr(telegram_service, "_handle_chief_command", lambda text, **kwargs: captured.update({
        "text": text, **kwargs,
    }) or {
        "ok": True, "delivered": True, "conversation_id": "default",
        "assistant_message_id": "MSG-ANSWER",
    })
    update = {
        "update_id": 101,
        "message": {
            "message_id": 501, "message_thread_id": 13,
            "text": "Витя, какие на сегодня задания у тебя остались?",
            "from": {"id": 42, "first_name": "Дмитрий", "is_bot": False},
            "chat": {"id": -1001, "type": "supergroup"},
        },
    }

    result = telegram_service._dispatch_command_update(
        update, private_id="42", gid="-1001", handle_owner_commands=True,
    )

    assert captured["sender_user_id"] == 42
    assert captured["conversation_id"] == "default"
    assert result["conversation_id"] == "default"
    assert result["telegram_message_id"] == 501
    assert result["assistant_message_id"] == "MSG-ANSWER"
    assert result["delivered"] is True


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
    monkeypatch.setattr(telegram_service, "_dispatch_update_inbox", lambda: 0)
    update = {"update_id": 9001, "message": {"text": "привет"}}

    try:
        telegram_service.process_webhook_update(update, "wrong")
    except telegram_service.TelegramServiceError as exc:
        assert "подпись" in str(exc)
    else:
        raise AssertionError("bad webhook secret must be rejected")

    result = telegram_service.process_webhook_update(update, "expected-secret")
    assert result["handler"] == "queued"
    assert result["queued"] is True
    queued = telegram_service._read_json(telegram_service._update_inbox_path())["items"]
    assert len(queued) == 1
    telegram_service._run_queued_update(dict(queued[0]))
    state = telegram_service._load_state()
    assert 9001 in state["chief_seen_update_ids"]
    assert state["chief_received_update_id"] == 9001
    assert state["last_command_transport"] == "webhook"


def test_webhook_queue_runs_different_topics_in_parallel_and_orders_each_topic(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    release = threading.Event()
    started = []

    def blocked_dispatch(update, **kwargs):
        started.append(update["update_id"])
        release.wait(2)
        return {"update_id": update["update_id"], "handler": "chief_group", "consumed": True, "error": ""}

    monkeypatch.setattr(telegram_service, "_dispatch_command_update", blocked_dispatch)
    for update_id, thread_id in ((1, 10), (2, 10), (3, 20)):
        telegram_service._enqueue_update({
            "update_id": update_id,
            "message": {"message_thread_id": thread_id, "chat": {"id": -1001}, "text": "test"},
        }, transport="webhook")
    doc = telegram_service._read_json(telegram_service._update_inbox_path())
    for row in doc["items"]:
        row["available_at_utc"] = "2000-01-01T00:00:00Z"
    telegram_service._write_json(telegram_service._update_inbox_path(), doc)

    assert telegram_service._dispatch_update_inbox() == 2
    deadline = time.time() + 1
    while len(started) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert set(started) == {1, 3}
    assert 2 not in started

    release.set()
    deadline = time.time() + 2
    while telegram_service._WEBHOOK_ACTIVE and time.time() < deadline:
        time.sleep(0.01)
    assert telegram_service._dispatch_update_inbox() == 1
    deadline = time.time() + 1
    while 2 not in started and time.time() < deadline:
        time.sleep(0.01)
    assert 2 in started
    deadline = time.time() + 1
    while telegram_service._WEBHOOK_ACTIVE and time.time() < deadline:
        time.sleep(0.01)
    assert telegram_service._WEBHOOK_ACTIVE == {}


def test_webhook_queue_recovers_running_message_after_restart(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    telegram_service._write_json(telegram_service._update_inbox_path(), {"items": [{
        "id": "tgu-interrupted", "update_id": 77, "conversation_key": "42:default",
        "transport": "webhook", "status": "running", "attempts": 1,
        "started_at_utc": "2026-07-13T01:00:00Z", "update": {"update_id": 77},
    }]})

    assert telegram_service.recover_interrupted_updates() == 1
    row = telegram_service._read_json(telegram_service._update_inbox_path())["items"][0]
    assert row["status"] == "queued"
    assert "started_at_utc" not in row


def test_webhook_accepts_out_of_order_ids_and_deduplicates_exact_id(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.WEBHOOK_SECRET_ENV, "secret")
    monkeypatch.setattr(telegram_service, "_dispatch_update_inbox", lambda: 0)

    first = telegram_service.process_webhook_update({"update_id": 102}, "secret")
    second = telegram_service.process_webhook_update({"update_id": 101}, "secret")
    duplicate = telegram_service.process_webhook_update({"update_id": 102}, "secret")

    rows = telegram_service._read_json(telegram_service._update_inbox_path())["items"]
    assert first["queued"] is True and second["queued"] is True
    assert duplicate["handler"] == "duplicate_update"
    assert [row["update_id"] for row in rows] == [102, 101]


def test_webhook_lane_processes_buffered_updates_in_telegram_id_order(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    for update_id in (102, 101):
        telegram_service._enqueue_update({
            "update_id": update_id,
            "message": {"chat": {"id": 42}, "text": str(update_id)},
        }, transport="webhook", handle_owner_commands=True)
    doc = telegram_service._read_json(telegram_service._update_inbox_path())
    for row in doc["items"]:
        row["available_at_utc"] = "2000-01-01T00:00:00Z"
    telegram_service._write_json(telegram_service._update_inbox_path(), doc)
    processed = []
    monkeypatch.setattr(telegram_service, "_dispatch_command_update", lambda update, **kwargs: {
        "update_id": processed.append(update["update_id"]) or update["update_id"],
        "handler": "test", "consumed": True, "error": "",
    })

    for expected in (101, 102):
        assert telegram_service._dispatch_update_inbox() == 1
        deadline = time.time() + 2
        while telegram_service._WEBHOOK_ACTIVE and time.time() < deadline:
            time.sleep(0.01)
        assert processed[-1] == expected


def test_webhook_inbox_never_truncates_unfinished_items(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    for update_id in range(1, 502):
        assert telegram_service._enqueue_update({"update_id": update_id}, transport="webhook") is True

    rows = telegram_service._read_json(telegram_service._update_inbox_path())["items"]
    assert len(rows) == 501
    assert rows[0]["update_id"] == 1 and rows[-1]["update_id"] == 501


def test_poison_update_moves_to_dead_letter_and_no_longer_blocks_topic(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    notices = []
    monkeypatch.setattr(
        telegram_service, "_chief_command_reply",
        lambda text, **kwargs: notices.append((text, kwargs)) or True,
    )
    for update_id in (1, 2):
        telegram_service._enqueue_update({
            "update_id": update_id,
            "message": {"chat": {"id": 42}, "text": "test"},
        }, transport="webhook")
    doc = telegram_service._read_json(telegram_service._update_inbox_path())
    first = doc["items"][0]
    first["attempts"] = 3
    telegram_service._write_json(telegram_service._update_inbox_path(), doc)

    telegram_service._finish_queued_update(dict(first), error="poison")
    doc = telegram_service._read_json(telegram_service._update_inbox_path())
    doc["items"][1]["available_at_utc"] = "2000-01-01T00:00:00Z"
    telegram_service._write_json(telegram_service._update_inbox_path(), doc)
    claimed = []
    monkeypatch.setattr(telegram_service, "_run_queued_update", lambda item: claimed.append(item["update_id"]))

    assert telegram_service._dispatch_update_inbox() == 1
    deadline = time.time() + 1
    while not claimed and time.time() < deadline:
        time.sleep(0.01)
    rows = telegram_service._read_json(telegram_service._update_inbox_path())["items"]
    assert rows[0]["status"] == "dead_letter"
    assert claimed == [2]
    assert notices and "повторите просьбу" in notices[0][0].lower()


def test_long_poll_uses_the_same_durable_inbox(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.CHAT_ENV, "42")
    monkeypatch.setattr(telegram_service, "group_id", lambda: "")
    monkeypatch.setattr(telegram_service, "_api_call", lambda *args, **kwargs: [{
        "update_id": 77, "message": {"chat": {"id": 42}, "text": "статус"},
    }])
    monkeypatch.setattr(telegram_service, "_dispatch_update_inbox", lambda: 0)
    state = {}

    telegram_service._poll_chief_commands(state)

    rows = telegram_service._read_json(telegram_service._update_inbox_path())["items"]
    assert len(rows) == 1 and rows[0]["transport"] == "poll"
    assert state["chief_update_id"] == 77
    assert 77 in state["chief_seen_update_ids"]


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


def test_chief_report_exposes_model_provider_and_action_status(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    sent = []
    monkeypatch.setattr(telegram_service, "_send_raw", lambda text, **kwargs: sent.append(text) or {})

    assert telegram_service.send_chief_report(
        "Марина · поручение", ["Проверяю журнал."],
        model_name="gpt-5-mini", provider_name="azure_foundry",
        action_status="needs_input",
    ) is True

    assert "Модель: gpt-5-mini (azure_foundry)" in sent[0]
    assert "Ход работы: Жду ваш ответ" in sent[0]


def test_telegram_ingress_reply_uses_same_agent_model_and_action_envelope(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(telegram_service, "_conversation_scope_for_topic", lambda *args, **kwargs: None)
    monkeypatch.setattr(chief_agent, "handle_message", lambda text, **kwargs: {
        "reply": "Проверка началась.",
        "model": "fallback-model", "provider": "fallback-provider",
        "agent": {"name": "Толик"},
        "actions": [{"name": "review_strategy", "status": "running"}],
        "message": {
            "message_id": "MSG-PRESENTATION", "agent_name": "Толик",
            "model": "gpt-5-mini", "provider": "azure_foundry",
            "actions": [{"name": "review_strategy", "status": "running"}],
        },
    })
    replies = []
    monkeypatch.setattr(
        telegram_service, "_chief_command_reply",
        lambda text, **kwargs: replies.append((text, kwargs)) or True,
    )

    result = telegram_service._handle_chief_command(
        "Толик, проверь стратегию", conversation_id="C-PRESENTATION", thread_id=77,
    )

    assert result["ok"] is True
    assert len(replies) == 1
    rendered, kwargs = replies[0]
    assert "<b>Толик · ответ</b>" in rendered
    assert "Проверка началась." in rendered
    assert "Модель: gpt-5-mini (azure_foundry)" in rendered
    assert "Ход работы: Выполняется" in rendered
    assert kwargs["thread_id"] == 77
    assert kwargs["dedupe_key"] == "MSG-PRESENTATION"


def test_scoped_report_never_falls_back_to_general_when_topic_sync_fails(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    monkeypatch.setattr(telegram_service, "group_configured", lambda: True)
    monkeypatch.setattr(
        telegram_service, "sync_topic_title",
        lambda *args, **kwargs: (_ for _ in ()).throw(telegram_service.TelegramServiceError("topic unavailable")),
    )
    sent = []
    monkeypatch.setattr(telegram_service, "_send_raw", lambda *args, **kwargs: sent.append(kwargs) or {})

    delivered = telegram_service.send_chief_report(
        "Виктор · ответ", ["Готово"], conversation_id="C-42", conversation_title="Поручение",
    )

    assert delivered is False
    assert sent == []
    queued = telegram_service._read_json(telegram_service._reply_outbox_path())["items"]
    assert queued[0]["conversation_id"] == "C-42"
    assert queued[0]["conversation_title"] == "Поручение"
    assert queued[0]["thread_id"] is None


def test_unknown_group_thread_is_not_mapped_to_default(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(telegram_service, "_load_topics", lambda: {"conversations": {}, "group": {}})

    with pytest.raises(telegram_service.TelegramServiceError):
        telegram_service._conversation_for_thread("-100123", 999)


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

    deadline = time.time() + 2
    while "text" not in captured and time.time() < deadline:
        time.sleep(0.01)
    assert captured["text"] == "проверь статус"
    deadline = time.time() + 2
    while telegram_service._WEBHOOK_ACTIVE and time.time() < deadline:
        time.sleep(0.01)
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


def test_community_mirror_is_idempotent_and_workspace_bound(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setenv(telegram_service.CHAT_ENV, "987654")
    monkeypatch.setenv(telegram_service.GROUP_ENV, "-1001234567890")
    monkeypatch.setenv("NTA_COMMUNITY_TELEGRAM_CHAT_ID", "-1009999999999")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    calls = []
    monkeypatch.setattr(
        telegram_service,
        "_api_call",
        lambda method, payload=None, **kwargs: calls.append((method, payload, kwargs)) or {},
    )

    assert telegram_service.mirror_community_message(
        "hello", display_name="Alice", dedupe_key="cmsg-1", workspace_id="workspace-a",
    ) is True
    assert telegram_service.mirror_community_message(
        "hello", display_name="Alice", dedupe_key="cmsg-1", workspace_id="workspace-a",
    ) is False
    # The same external id in a different tenant is a distinct delivery.
    assert telegram_service.mirror_community_message(
        "hello", display_name="Alice", dedupe_key="cmsg-1", workspace_id="workspace-b",
    ) is True

    assert len(calls) == 2
    assert all(method == "sendMessage" for method, _payload, _kwargs in calls)
    assert all(payload["chat_id"] == "-1009999999999" for _method, payload, _kwargs in calls)
    state = telegram_service._load_state()
    assert len(state["recent_community_delivery_signatures"]) == 2


@pytest.mark.parametrize("collision_env", [telegram_service.CHAT_ENV, telegram_service.GROUP_ENV])
def test_community_mirror_rejects_owner_chat_collisions(
    monkeypatch, tmp_path, collision_env: str,
) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setenv(collision_env, "-1001234567890")
    monkeypatch.setenv("NTA_COMMUNITY_TELEGRAM_CHAT_ID", "-1001234567890")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    monkeypatch.setattr(
        telegram_service, "_api_call",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not send")),
    )

    assert telegram_service.mirror_community_message("secret", dedupe_key="cmsg-1") is False


def test_community_mirror_fails_closed_when_policy_breaks(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "fake-token")
    monkeypatch.setenv("NTA_COMMUNITY_TELEGRAM_CHAT_ID", "-1009999999999")
    telegram_service._save_settings({**telegram_service.DEFAULT_SETTINGS, "enabled": True})
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setattr(
        telegram_service, "_api_call",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not send")),
    )
    assert telegram_service.mirror_community_message("secret", dedupe_key="cmsg-1") is False

    monkeypatch.setenv("NTA_APP_ENV", "production")
    monkeypatch.setattr(
        runtime_env, "is_staging",
        lambda: (_ for _ in ()).throw(RuntimeError("policy unavailable")),
    )

    assert telegram_service.mirror_community_message("secret", dedupe_key="cmsg-1") is False
