"""Fail-closed boundary for retired UI and Telegram Web App surfaces."""

from __future__ import annotations

from typing import Mapping
from urllib.parse import parse_qs, urlparse


LEGACY_UI_PREFIX = "/ui/legacy"
MINI_APP_HEADER = "X-Telegram-Init-Data"
MINI_APP_QUERY_KEYS = frozenset({"tgWebAppData", "tg_web_app_data"})
RETIRED_API_PREFIXES = (
    "/api/auth/miniapp/register",
    "/api/telegram/remote",
    "/api/telegram/tunnel",
)


def retired_surface(path_with_query: str, headers: Mapping[str, str]) -> str:
    """Return the isolated surface name, or an empty string for current traffic."""

    parsed = urlparse(str(path_with_query or "/"))
    path = parsed.path.rstrip("/") or "/"
    if path == LEGACY_UI_PREFIX or path.startswith(LEGACY_UI_PREFIX + "/"):
        return "legacy_ui"
    if any(path == prefix or path.startswith(prefix + "/") for prefix in RETIRED_API_PREFIXES):
        return "telegram_mini_app"
    if str(headers.get(MINI_APP_HEADER) or "").strip():
        return "telegram_mini_app"
    query = parse_qs(parsed.query, keep_blank_values=True)
    if MINI_APP_QUERY_KEYS.intersection(query):
        return "telegram_mini_app"
    return ""
