"""Out-of-band delivery for authentication and security one-time codes.

The delivery layer is deliberately small and provider-neutral.  It never stores
codes and never returns them through an HTTP response.  Development test-auth
continues to echo test codes at the caller; Canary and Production must use an
explicitly configured SMTP provider or the environment-specific Telegram bot.
"""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import parseaddr
import os
import re
import smtplib
import ssl
from typing import Any, Dict

from . import local_secrets, runtime_env


class AuthDeliveryError(RuntimeError):
    """Safe-to-display delivery failure without credential contents."""

    def __init__(self, message: str, *, code: str = "delivery_failed") -> None:
        super().__init__(message)
        self.code = str(code or "delivery_failed")


def _smtp_settings() -> Dict[str, Any]:
    local_secrets.apply()
    provider = str(os.environ.get("NTA_EMAIL_AUTH_PROVIDER") or "").strip().lower()
    security = str(os.environ.get("NTA_SMTP_SECURITY") or "starttls").strip().lower()
    try:
        default_port = 465 if security == "ssl" else 587
        port = int(os.environ.get("NTA_SMTP_PORT") or default_port)
    except (TypeError, ValueError):
        port = 0
    try:
        timeout = float(os.environ.get("NTA_SMTP_TIMEOUT_SEC") or 15)
    except (TypeError, ValueError):
        timeout = 0
    return {
        "provider": provider,
        "host": str(os.environ.get("NTA_SMTP_HOST") or "").strip(),
        "port": port,
        "username": str(os.environ.get("NTA_SMTP_USERNAME") or "").strip(),
        "password": str(os.environ.get("NTA_SMTP_PASSWORD") or "").strip(),
        "from_address": str(os.environ.get("NTA_SMTP_FROM") or "").strip(),
        "security": security,
        "timeout": timeout,
    }


def telegram_status() -> Dict[str, Any]:
    """Return secret-free readiness for user-specific Telegram OTP delivery."""
    local_secrets.apply()
    token = str(os.environ.get("NTA_TELEGRAM_BOT_TOKEN") or "").strip()
    configured = bool(re.fullmatch(r"[1-9][0-9]{5,15}:[A-Za-z0-9_-]{20,}", token))
    return {
        "available": configured,
        "operational": configured,
        "provider": "telegram",
        "production_ready": configured,
        "code": "ok" if configured else (
            "telegram_bot_token_invalid" if token else "telegram_bot_token_not_configured"
        ),
    }


def email_status() -> Dict[str, Any]:
    """Return secret-free email delivery readiness."""
    test_backend = bool(runtime_env.is_development() and runtime_env.test_auth_enabled())
    if test_backend:
        return {
            "available": True,
            "operational": True,
            "provider": "development_test",
            "test_backend": True,
            "production_ready": False,
            "code": "ok",
            "security": "local_test_only",
        }

    cfg = _smtp_settings()
    provider = cfg["provider"]
    credentials_pair = bool(cfg["username"]) == bool(cfg["password"])
    credentials_present = bool(cfg["username"] and cfg["password"])
    from_name, from_address = parseaddr(cfg["from_address"])
    _ = from_name
    from_valid = bool(from_address and "@" in from_address and "\r" not in cfg["from_address"] and "\n" not in cfg["from_address"])
    transport_valid = bool(
        provider == "smtp"
        and cfg["host"]
        and 1 <= int(cfg["port"] or 0) <= 65535
        and 1 <= float(cfg["timeout"] or 0) <= 60
        and cfg["security"] in {"starttls", "ssl"}
        and credentials_present
        and from_valid
    )
    if not provider:
        code = "transactional_provider_not_configured"
    elif provider != "smtp":
        code = "transactional_provider_unsupported"
    elif cfg["security"] not in {"starttls", "ssl"}:
        code = "smtp_tls_required"
    elif not credentials_pair:
        code = "smtp_credentials_incomplete"
    elif not credentials_present:
        code = "smtp_credentials_missing"
    elif not transport_valid:
        code = "smtp_configuration_incomplete"
    else:
        code = "ok"
    return {
        "available": transport_valid,
        "operational": transport_valid,
        "provider": provider or "unconfigured",
        "test_backend": False,
        "production_ready": transport_valid,
        "code": code,
        "security": cfg["security"],
        "authenticated_smtp": credentials_present,
        "from_domain": from_address.rsplit("@", 1)[-1].lower() if from_valid else "",
    }


def _email_subject(purpose: str) -> str:
    if str(purpose or "").strip().lower() == "login":
        return "Код входа StratForge"
    return "Код подтверждения StratForge"


def send_email_code(
    recipient: Any,
    code: Any,
    *,
    purpose: str,
    expires_in_sec: int,
    action: str = "",
) -> Dict[str, Any]:
    """Deliver one code through configured SMTP with mandatory TLS."""
    status = email_status()
    if not status.get("available") or status.get("test_backend"):
        raise AuthDeliveryError(
            "Почтовая доставка не настроена.", code=str(status.get("code") or "email_unavailable")
        )
    address = str(recipient or "").strip().lower()
    _, parsed_address = parseaddr(address)
    if parsed_address != address or "@" not in address or "\r" in address or "\n" in address:
        raise AuthDeliveryError("Некорректный адрес e-mail.", code="email_recipient_invalid")
    otp = str(code or "").strip()
    if len(otp) != 6 or not otp.isdigit():
        raise AuthDeliveryError("Некорректный одноразовый код.", code="otp_invalid")

    cfg = _smtp_settings()
    minutes = max(1, int(expires_in_sec or 0) // 60)
    action_note = f"\nДействие: {str(action)[:80]}." if str(action or "").strip() else ""
    message = EmailMessage()
    message["Subject"] = _email_subject(purpose)
    message["From"] = cfg["from_address"]
    message["To"] = address
    message.set_content(
        "Ваш одноразовый код StratForge:\n\n"
        f"{otp}\n\n"
        f"Код действует {minutes} мин.{action_note}\n"
        "Если вы не запрашивали код, проигнорируйте это письмо.\n"
    )
    context = ssl.create_default_context()
    try:
        if cfg["security"] == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                cfg["host"], cfg["port"], timeout=cfg["timeout"], context=context
            )
        else:
            client = smtplib.SMTP(cfg["host"], cfg["port"], timeout=cfg["timeout"])
        with client:
            client.ehlo()
            if cfg["security"] == "starttls":
                client.starttls(context=context)
                client.ehlo()
            if cfg["username"]:
                client.login(cfg["username"], cfg["password"])
            client.send_message(message)
    except (OSError, smtplib.SMTPException, TimeoutError):
        raise AuthDeliveryError(
            "Не удалось отправить письмо с кодом. Повторите позже.",
            code="smtp_delivery_failed",
        ) from None
    return {"ok": True, "provider": "smtp", "delivery": "email"}


def send_telegram_code(
    chat_id: Any,
    code: Any,
    *,
    purpose: str,
    expires_in_sec: int,
    action: str = "",
) -> Dict[str, Any]:
    """Deliver one code through the configured environment-specific bot."""
    status = telegram_status()
    if not status.get("available"):
        raise AuthDeliveryError(
            "Telegram-доставка не настроена.",
            code=str(status.get("code") or "telegram_unavailable"),
        )
    try:
        target = int(chat_id or 0)
    except (TypeError, ValueError):
        target = 0
    otp = str(code or "").strip()
    if target <= 0:
        raise AuthDeliveryError("Telegram-получатель не найден.", code="telegram_recipient_missing")
    if len(otp) != 6 or not otp.isdigit():
        raise AuthDeliveryError("Некорректный одноразовый код.", code="otp_invalid")
    minutes = max(1, int(expires_in_sec or 0) // 60)
    action_note = f"\nДействие: {str(action)[:80]}" if str(action or "").strip() else ""
    text = (
        "Одноразовый код StratForge\n\n"
        f"{otp}\n\n"
        f"Действует {minutes} мин.{action_note}\n"
        "Никому не сообщайте этот код."
    )
    try:
        from . import telegram_service

        telegram_service._api_call("sendMessage", {
            "chat_id": target,
            "text": text,
            "protect_content": True,
            "disable_notification": False,
        })
    except Exception:
        raise AuthDeliveryError(
            "Не удалось отправить код в Telegram. Повторите позже.",
            code="telegram_delivery_failed",
        ) from None
    return {"ok": True, "provider": "telegram", "delivery": "telegram"}


def deliver_security_code(
    provider: str,
    recipient: Any,
    code: Any,
    *,
    purpose: str,
    expires_in_sec: int,
    action: str = "",
) -> Dict[str, Any]:
    provider_id = str(provider or "").strip().lower()
    if provider_id == "telegram":
        return send_telegram_code(
            recipient, code, purpose=purpose, expires_in_sec=expires_in_sec, action=action
        )
    if provider_id in {"email", "google"}:
        return send_email_code(
            recipient, code, purpose=purpose, expires_in_sec=expires_in_sec, action=action
        )
    raise AuthDeliveryError("Неизвестный канал доставки.", code="provider_unsupported")
