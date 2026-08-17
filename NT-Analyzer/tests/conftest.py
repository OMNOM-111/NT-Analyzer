"""Global test safety gates.

The developer workstation may have real DPAPI-backed agents configured. Unit
tests must never discover or call them; tests that exercise routing replace the
candidate list with explicit mock agents.
"""
from __future__ import annotations

import pytest

from app import local_secrets
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
    # Deleting the variables is not enough on its own. `local_secrets.apply()`
    # only sets a name that is *absent* from os.environ, so the scrub above is
    # exactly the condition that makes it put the workstation's real values
    # back -- and several call sites invoke it lazily, in the middle of a test,
    # long after this fixture has run.
    #
    # The symptom is remote and confusing: a Release Center test that deleted
    # STRATFORGE_RELEASE_DEPLOY_ADAPTER suddenly sees the real `stage9_ssh`
    # adapter, deploy_canary treats a dry run as a blocked real deploy, the
    # candidate lands in canary_failed instead of canary_checking, and an
    # unrelated test fails. Which test fails depends on when the lazy call
    # happens, so the suite is intermittently red for reasons that have nothing
    # to do with the change under test.
    #
    # Three call sites already worked around this individually with
    # `monkeypatch.setattr(..., "apply", lambda: False)`. Neutralising it once,
    # here, closes the whole class: a test that genuinely needs the local store
    # points `secrets_path` at a temporary file and calls the loader directly.
    monkeypatch.setattr(local_secrets, "apply", lambda: False)


@pytest.fixture(autouse=True)
def no_real_external_agent_routes(monkeypatch):
    # Existing routing tests predate mandatory interactive Telegram login.
    # They exercise endpoint behavior, not the authentication boundary; auth
    # has dedicated integration tests that explicitly remove this flag.
    monkeypatch.setenv("NTA_TEST_BYPASS_AUTH", "1")
    monkeypatch.setattr(agent_router, "candidates", lambda *args, **kwargs: [])
