"""Global test safety gates.

The developer workstation may have real DPAPI-backed agents configured. Unit
tests must never discover or call them; tests that exercise routing replace the
candidate list with explicit mock agents.
"""
from __future__ import annotations

import pytest

from app.ai_lab import agent_router


# A developer workstation now carries real Release Center and transactional
# email configuration in the local secret store, and `local_secrets.apply()`
# pushes it into `os.environ`. Fail-closed tests assert the *absence* of that
# configuration, so clear it for every test; tests that need it set it back
# explicitly, which runs after this fixture.
_WORKSTATION_ONLY_ENV = (
    "STRATFORGE_RELEASE_DEPLOY_ADAPTER",
    "STRATFORGE_RELEASE_SSH_HOST",
    "STRATFORGE_RELEASE_SSH_USER",
    "STRATFORGE_RELEASE_SSH_KEY",
    "STRATFORGE_RELEASE_SSH_PROXY_COMMAND",
    "STRATFORGE_RELEASE_PRODUCTION_EXECUTION",
    "NTA_EMAIL_AUTH_PROVIDER",
    "NTA_EMAIL_AUTH_FROM",
    "NTA_RESEND_API_KEY",
)


@pytest.fixture(autouse=True)
def no_real_operator_configuration(monkeypatch):
    for name in _WORKSTATION_ONLY_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_real_external_agent_routes(monkeypatch):
    # Existing routing tests predate mandatory interactive Telegram login.
    # They exercise endpoint behavior, not the authentication boundary; auth
    # has dedicated integration tests that explicitly remove this flag.
    monkeypatch.setenv("NTA_TEST_BYPASS_AUTH", "1")
    monkeypatch.setattr(agent_router, "candidates", lambda *args, **kwargs: [])
