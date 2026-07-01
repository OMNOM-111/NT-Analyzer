from __future__ import annotations

import json
from datetime import datetime, timezone

from app import local_secrets, telegram_service


def _isolate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(telegram_service, "_root", lambda: tmp_path)
    monkeypatch.setattr(
        local_secrets,
        "secrets_path",
        lambda: tmp_path / "data" / "integrations" / "secrets.local.json",
    )
    monkeypatch.delenv(telegram_service.TOKEN_ENV, raising=False)
    monkeypatch.delenv(telegram_service.CHAT_ENV, raising=False)
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
