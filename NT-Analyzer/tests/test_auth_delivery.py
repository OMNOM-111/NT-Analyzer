from __future__ import annotations

from email.message import EmailMessage

import pytest

from app import account_auth, auth_delivery, security_devices, secure_store


def _smtp_env(monkeypatch) -> None:
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "0")
    monkeypatch.setenv("NTA_EMAIL_AUTH_PROVIDER", "smtp")
    monkeypatch.setenv("NTA_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("NTA_SMTP_PORT", "587")
    monkeypatch.setenv("NTA_SMTP_USERNAME", "mailer")
    monkeypatch.setenv("NTA_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("NTA_SMTP_FROM", "StratForge <login@example.test>")
    monkeypatch.setenv("NTA_SMTP_SECURITY", "starttls")


def _local_auth_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "_protect", lambda value: value)
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    account_auth._clear_doc_cache()
    with account_auth._RATE_LOCK:
        account_auth._LOGIN_RATE.clear()
    security_devices._CHALLENGE_RATE.clear()


def test_smtp_delivery_uses_starttls_and_auth(monkeypatch) -> None:
    _smtp_env(monkeypatch)
    calls = []

    class SMTP:
        def __init__(self, host, port, *, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            calls.append(("close",))

        def ehlo(self):
            calls.append(("ehlo",))

        def starttls(self, *, context):
            assert context is not None
            calls.append(("starttls",))

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message: EmailMessage):
            assert message["To"] == "person@example.test"
            assert "123456" in message.get_content()
            calls.append(("send",))

    monkeypatch.setattr(auth_delivery.smtplib, "SMTP", SMTP)
    status = auth_delivery.email_status()
    assert status["production_ready"] is True
    assert status["security"] == "starttls"
    out = auth_delivery.send_email_code(
        "person@example.test", "123456", purpose="login", expires_in_sec=600,
    )
    assert out == {"ok": True, "provider": "smtp", "delivery": "email"}
    assert [row[0] for row in calls] == [
        "connect", "ehlo", "starttls", "ehlo", "login", "send", "close",
    ]


def test_smtp_without_authentication_is_not_production_ready(monkeypatch) -> None:
    monkeypatch.setenv("NTA_APP_ENV", "production")
    monkeypatch.setenv("NTA_EMAIL_AUTH_PROVIDER", "smtp")
    monkeypatch.setenv("NTA_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("NTA_SMTP_PORT", "587")
    monkeypatch.setenv("NTA_SMTP_FROM", "StratForge <security@example.test>")
    monkeypatch.setenv("NTA_SMTP_SECURITY", "starttls")
    monkeypatch.delenv("NTA_SMTP_USERNAME", raising=False)
    monkeypatch.delenv("NTA_SMTP_PASSWORD", raising=False)

    status = auth_delivery.email_status()

    assert status["production_ready"] is False
    assert status["authenticated_smtp"] is False
    assert status["code"] == "smtp_credentials_missing"


def test_email_login_delivers_out_of_band_and_never_echoes_code(tmp_path, monkeypatch) -> None:
    _smtp_env(monkeypatch)
    _local_auth_store(tmp_path, monkeypatch)
    delivered = []
    monkeypatch.setattr(
        auth_delivery,
        "send_email_code",
        lambda recipient, code, **kwargs: delivered.append((recipient, code, kwargs)) or {"ok": True},
    )

    out = account_auth.start_email_auth("person@example.test", ip="127.0.0.1")

    assert out["delivery"] == "smtp"
    assert "test_code" not in out
    assert "test_magic_token" not in out
    assert delivered[0][0] == "person@example.test"
    assert len(delivered[0][1]) == 6 and delivered[0][1].isdigit()
    row = account_auth._read_doc()["challenges"][-1]
    assert row["status"] == "email_code_sent"
    assert "code" not in row


def _seed_security_user(tmp_path, monkeypatch) -> None:
    _local_auth_store(tmp_path, monkeypatch)
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "0")
    monkeypatch.setenv("NTA_TELEGRAM_BOT_TOKEN", "123456:test-token-never-sent")
    account_auth._write_doc({
        "version": 3,
        "users": [{
            "user_id": 42,
            "user_uuid": "00000000-0000-4000-8000-000000000042",
            "first_name": "Ada",
            "status": "active",
            "telegram_user_id": 42,
        }],
        "auth_identities": [{
            "identity_id": 1,
            "user_uuid": "00000000-0000-4000-8000-000000000042",
            "legacy_user_id": 42,
            "provider": "telegram",
            "provider_subject": "42",
            "verified_at_utc": "2026-08-08T00:00:00Z",
        }],
        "sessions": [],
        "challenges": [],
        "security_challenges": [],
        "trusted_devices": [],
    })


def test_security_challenge_is_delivered_via_telegram(tmp_path, monkeypatch) -> None:
    _seed_security_user(tmp_path, monkeypatch)
    delivered = []
    monkeypatch.setattr(
        auth_delivery,
        "deliver_security_code",
        lambda provider, recipient, code, **kwargs: delivered.append(
            (provider, recipient, code, kwargs)
        ) or {"ok": True},
    )

    out = security_devices.create_challenge(user_id=42, purpose="step_up")

    assert out["provider"] == "telegram"
    assert out["delivery"] == "telegram"
    assert "test_code" not in out
    assert delivered[0][0:2] == ("telegram", 42)
    assert len(delivered[0][2]) == 6


def test_failed_security_delivery_invalidates_challenge(tmp_path, monkeypatch) -> None:
    _seed_security_user(tmp_path, monkeypatch)

    def fail(*_args, **_kwargs):
        raise auth_delivery.AuthDeliveryError("delivery failed", code="telegram_delivery_failed")

    monkeypatch.setattr(auth_delivery, "deliver_security_code", fail)
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.create_challenge(user_id=42, purpose="step_up")
    assert exc.value.status == 503
    assert exc.value.code == "telegram_delivery_failed"
    row = account_auth._read_doc()["security_challenges"][-1]
    assert row["status"] == "delivery_failed"
