"""Staging-only virtual auth: fake Telegram + Google without real phones/OAuth.

Enabled only when:
  NTA_APP_ENV=staging
  NTA_ENABLE_TEST_AUTH=1

Never loads in production (``runtime_env.require_test_auth`` raises).
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import account_auth, google_auth, runtime_env


class TestAuthError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


# Presets for owner QA of the full user funnel.
PRESETS: Dict[str, Dict[str, Any]] = {
    "new": {
        "label": "Новый пользователь",
        "status": "active",
        "role": "read_only",
        "plan_hint": "free_preview",
        "google_linked": True,
        "onboarding_complete": False,
    },
    "no_google": {
        "label": "Telegram без Google (миграция)",
        "status": "active",
        "role": "read_only",
        "plan_hint": "free_preview",
        "google_linked": False,
        "onboarding_complete": True,
    },
    "demo": {
        "label": "Demo доступ",
        "status": "active",
        "role": "read_only",
        "plan_hint": "free_preview",
        "google_linked": True,
        "onboarding_complete": True,
    },
    "paid": {
        "label": "Платный тариф",
        "status": "active",
        "role": "full_control",
        "plan_hint": "pro",
        "google_linked": True,
        "onboarding_complete": True,
    },
    "blocked": {
        "label": "Заблокирован",
        "status": "blocked",
        "role": "read_only",
        "plan_hint": "free_preview",
        "google_linked": True,
        "onboarding_complete": True,
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def status() -> Dict[str, Any]:
    runtime_env.require_staging("Test auth status")
    return {
        "ok": True,
        "enabled": runtime_env.test_auth_enabled(),
        "presets": [
            {"id": key, "label": str(val.get("label") or key), **{k: v for k, v in val.items() if k != "label"}}
            for key, val in PRESETS.items()
        ],
        "app_env": runtime_env.app_env(),
    }


def create_virtual_user(
    *,
    preset: str = "demo",
    display_name: str = "",
    telegram_id: int = 0,
    google_email: str = "",
) -> Dict[str, Any]:
    runtime_env.require_test_auth()
    preset_key = str(preset or "demo").strip().lower()
    if preset_key not in PRESETS:
        raise TestAuthError(f"Неизвестный preset: {preset_key}. Доступны: {', '.join(PRESETS)}.")
    spec = PRESETS[preset_key]
    uid = int(telegram_id) if int(telegram_id or 0) > 0 else _alloc_virtual_telegram_id()
    name = str(display_name or "").strip() or f"Virtual {preset_key.title()}"
    parts = name.split(None, 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else "User"
    google_linked = bool(spec.get("google_linked"))
    user = account_auth.create_or_update_virtual_user(
        user_id=uid,
        username=f"virtual_{uid}",
        first_name=first,
        last_name=last,
        email=str(google_email or f"virtual{uid}@staging.stratforge.local").strip().lower(),
        role=str(spec.get("role") or "read_only"),
        status=str(spec.get("status") or "active"),
        google_linked=google_linked,
        google_sub=f"test-google-{uid}" if google_linked else "",
        google_email=str(google_email or f"virtual{uid}@staging.stratforge.local").strip().lower() if google_linked else "",
        virtual=True,
        preset=preset_key,
        terms_accepted=True,
    )
    return {"ok": True, "preset": preset_key, "user": user}


def _alloc_virtual_telegram_id() -> int:
    # Keep virtual IDs in a high band unlikely to collide with real Telegram ids in tests.
    base = 9_000_000_000
    return base + (secrets.randbelow(899_999_999) + 100_000_000)


def login_virtual(*, user_id: int, ip: str = "127.0.0.1", user_agent: str = "staging-test-auth") -> Dict[str, Any]:
    """Create a real session cookie for a virtual (or any staging) user."""
    runtime_env.require_test_auth()
    return account_auth.create_session_for_user(
        int(user_id),
        ip=ip,
        user_agent=user_agent,
        source="test_auth",
        require_google=False,  # virtual login may be used to test no_google preset
        skip_dual_auth_gate=True,
    )


def link_fake_google(*, user_id: int, google_sub: str = "", email: str = "") -> Dict[str, Any]:
    runtime_env.require_test_auth()
    identity = google_auth.fake_identity(google_sub=google_sub, email=email)
    return account_auth.link_google_identity(
        int(user_id),
        google_sub=identity["google_sub"],
        google_email=identity["google_email"],
        google_name=identity.get("google_name") or "",
        source="test_auth",
    )


def list_virtual_users() -> Dict[str, Any]:
    runtime_env.require_test_auth()
    users = account_auth.list_virtual_users()
    return {"ok": True, "users": users, "count": len(users)}
