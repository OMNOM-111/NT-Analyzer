"""Global test safety gates.

The developer workstation may have real DPAPI-backed agents configured. Unit
tests must never discover or call them; tests that exercise routing replace the
candidate list with explicit mock agents.
"""
from __future__ import annotations

import pytest

from app.ai_lab import agent_router


@pytest.fixture(autouse=True)
def no_real_external_agent_routes(monkeypatch):
    # Existing routing tests predate mandatory interactive Telegram login.
    # They exercise endpoint behavior, not the authentication boundary; auth
    # has dedicated integration tests that explicitly remove this flag.
    monkeypatch.setenv("NTA_TEST_BYPASS_AUTH", "1")
    monkeypatch.setattr(agent_router, "candidates", lambda *args, **kwargs: [])
