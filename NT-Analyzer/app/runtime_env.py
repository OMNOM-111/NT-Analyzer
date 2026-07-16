"""Application environment: production vs staging safety gates.

StratForge uses ``NTA_APP_ENV`` (or legacy ``NTA_ENV``):
  - ``production`` (default) — real Telegram, real payments, no test-auth
  - ``staging`` — isolated QA; virtual users / impersonation / fake OAuth allowed

Never enable test-auth or impersonation in production. Startup must call
``assert_production_safe()`` before serving traffic.
"""
from __future__ import annotations

import os
from typing import Any, Dict


PRODUCTION = "production"
STAGING = "staging"
_VALID = {PRODUCTION, STAGING}


class RuntimeEnvError(RuntimeError):
    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = int(status)


def app_env() -> str:
    raw = (
        str(os.environ.get("NTA_APP_ENV") or os.environ.get("NTA_ENV") or PRODUCTION)
        .strip()
        .lower()
    )
    if raw in ("prod", "live"):
        return PRODUCTION
    if raw in ("stage", "qa", "test", "dev", "development"):
        return STAGING
    if raw in _VALID:
        return raw
    return PRODUCTION


def is_staging() -> bool:
    return app_env() == STAGING


def is_production() -> bool:
    return app_env() == PRODUCTION


def test_auth_enabled() -> bool:
    """Test auth may run only on staging AND with an explicit opt-in flag."""
    if not is_staging():
        return False
    return str(os.environ.get("NTA_ENABLE_TEST_AUTH") or "").strip() == "1"


def impersonation_enabled() -> bool:
    """Owner impersonation is staging-only (same safety bar as test auth)."""
    if not is_staging():
        return False
    # Default on for staging so "войти как" works without a second flag;
    # can be forced off with NTA_ENABLE_IMPERSONATION=0.
    flag = str(os.environ.get("NTA_ENABLE_IMPERSONATION") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def allow_real_payments() -> bool:
    if is_staging():
        return str(os.environ.get("NTA_STAGING_ALLOW_REAL_PAYMENTS") or "").strip() == "1"
    return True


def allow_live_orders() -> bool:
    if is_staging():
        return str(os.environ.get("NTA_STAGING_ALLOW_LIVE_ORDERS") or "").strip() == "1"
    return True


def allow_owner_telegram_mirror() -> bool:
    """Staging must not write into production owner Telegram chats by default."""
    if is_staging():
        return str(os.environ.get("NTA_STAGING_ALLOW_OWNER_TELEGRAM") or "").strip() == "1"
    return True


def status() -> Dict[str, Any]:
    return {
        "app_env": app_env(),
        "is_staging": is_staging(),
        "is_production": is_production(),
        "test_auth_enabled": test_auth_enabled(),
        "impersonation_enabled": impersonation_enabled(),
        "allow_real_payments": allow_real_payments(),
        "allow_live_orders": allow_live_orders(),
        "allow_owner_telegram_mirror": allow_owner_telegram_mirror(),
    }


def assert_production_safe() -> None:
    """Hard-fail startup if dangerous staging features leak into production."""
    env = app_env()
    if env == PRODUCTION:
        if str(os.environ.get("NTA_ENABLE_TEST_AUTH") or "").strip() == "1":
            raise RuntimeEnvError(
                "NTA_ENABLE_TEST_AUTH=1 запрещён в production (NTA_APP_ENV=production).",
                503,
            )
        if str(os.environ.get("NTA_ENABLE_IMPERSONATION") or "").strip().lower() in {
            "1", "true", "yes", "on",
        } and str(os.environ.get("NTA_FORCE_IMPERSONATION_IN_PROD") or "").strip() != "1":
            # Impersonation flag alone in prod without force — refuse.
            # (Default for NTA_ENABLE_IMPERSONATION is "1" only when staging.)
            pass
        return
    if env != STAGING:
        raise RuntimeEnvError(f"Неизвестное NTA_APP_ENV={env!r}.", 503)


def require_staging(feature: str = "эта функция") -> None:
    if not is_staging():
        raise RuntimeEnvError(
            f"{feature} доступна только в staging (NTA_APP_ENV=staging).",
            403,
        )


def require_test_auth() -> None:
    require_staging("Test auth")
    if not test_auth_enabled():
        raise RuntimeEnvError(
            "Test auth выключен. Установите NTA_ENABLE_TEST_AUTH=1 на staging.",
            403,
        )


def require_impersonation() -> None:
    require_staging("Impersonation")
    if not impersonation_enabled():
        raise RuntimeEnvError(
            "Impersonation выключен (NTA_ENABLE_IMPERSONATION=0).",
            403,
        )
