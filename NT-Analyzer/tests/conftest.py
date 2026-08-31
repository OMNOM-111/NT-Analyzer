"""Global test safety gates.

The developer workstation may have real DPAPI-backed agents configured. Unit
tests must never discover or call them; tests that exercise routing replace the
candidate list with explicit mock agents.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

# Tests must never write the workstation's live data directory, and this has to
# be set before any app module is imported.
#
# Concurrent suites used to perform atomic `.tmp` -> rename writes into
# <project>/data and collide with each other and the running LOCAL server. Both
# environments now receive unique disposable roots before application imports,
# and every test receives a fresh pair below. CI concurrency is therefore a
# capacity choice, never a correctness requirement.
#
# The pid and random suffix matter: without them two runs would share this
# directory too and simply move the collision.
#
# Both fallback roots are claimed before any app module is imported. A test
# that does not declare an environment resolves to Production, so isolating
# Development alone still let those imports and tests write the workstation's
# live ``data`` directory. The two roots are siblings because runtime startup
# correctly rejects overlapping environment roots.
_TEST_DATA_ROOT = Path(tempfile.gettempdir()) / (
    "stratforge-tests-%d-%s" % (os.getpid(), uuid.uuid4().hex[:8])
)
_TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
_SESSION_PRODUCTION_ROOT = _TEST_DATA_ROOT / "session-production"
_SESSION_DEVELOPMENT_ROOT = _TEST_DATA_ROOT / "session-development"
_SESSION_PRODUCTION_ROOT.mkdir()
_SESSION_DEVELOPMENT_ROOT.mkdir()
os.environ["NTA_DATA_ROOT"] = str(_SESSION_PRODUCTION_ROOT)
os.environ["NTA_STAGING_DATA_ROOT"] = str(_SESSION_DEVELOPMENT_ROOT)

import pytest  # noqa: E402

from app import local_secrets  # noqa: E402
from app.ai_lab import agent_router  # noqa: E402


_LIVE_DATA = Path(__file__).resolve().parents[1] / "data"
_LIVE_BEFORE: dict = {}


def _live_manifest() -> dict:
    """Size and mtime of every file under the live data directory.

    The release suite is run with LOCAL stopped, making this byte-level guard
    exact. CI has no application runtime, so it is exact there too. Nothing is
    exempted: a test that changes even generated live state is a regression.
    """
    manifest = {}
    if not _LIVE_DATA.is_dir():
        return manifest
    for path in _LIVE_DATA.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        # Keyed relative to the data directory. An absolute path is not
        # comparable across machines, and on CI the checkout is nested under a
        # directory of the same name three times over, which defeated an
        # earlier attempt to strip a prefix by string search.
        manifest[path.relative_to(_LIVE_DATA).as_posix()] = (
            stat.st_size, stat.st_mtime_ns)
    return manifest


def pytest_sessionstart(session):  # noqa: ARG001
    _LIVE_BEFORE.update(_live_manifest())


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Fail the run if the suite changed any workstation live-data file."""
    after = _live_manifest()
    changed = (set(_LIVE_BEFORE) ^ set(after)) | {
        p for p in set(_LIVE_BEFORE) & set(after) if _LIVE_BEFORE[p] != after[p]
    }
    shutil.rmtree(_TEST_DATA_ROOT, ignore_errors=True)
    if changed:
        session.exitstatus = 1
        print("\n\nTHE SUITE CHANGED LIVE DATA FILES:")
        for path in sorted(changed)[:20]:
            print("   ", path)
        if len(changed) > 20:
            print("    ... and %d more" % (len(changed) - 20))
        print("Every test writer must use its isolated disposable root.")


@pytest.fixture(autouse=True)
def isolated_data_root(monkeypatch, tmp_path):
    """A data directory of its own for every test.

    A single session-wide root still lets tests contaminate each other. Two
    files disagreed about the on-disk format at the same path -- one wrote a
    DPAPI-encrypted workspaces store, the next read it as JSON and died with
    "'utf-8' codec can't decode byte 0xb7" -- so a test passed alone and failed
    in the suite depending on what ran before it.

    No fixture in this suite is module- or session-scoped, so nothing depends on
    state surviving between tests. The paths are created lazily by the code
    under test, preserving tests that intentionally distinguish an absent root
    from an empty one.

    Set through the fallback variables (NTA_*), so a test that manages roots
    explicitly still overrides it: setting the same name replaces this value,
    and the STRATFORGE_* names outrank it either way.
    """
    # Keep Production at ``<tmp_path>/data`` because tests that replace a
    # module's project root with tmp_path intentionally expect the normal
    # project-relative layout. Development is a sibling, not a child, so the
    # real overlap guard is exercised rather than bypassed.
    production = tmp_path / "data"
    development = tmp_path / "development-data"
    monkeypatch.setenv("NTA_DATA_ROOT", str(production))
    monkeypatch.setenv("NTA_STAGING_DATA_ROOT", str(development))
    return development


# A developer workstation now carries real Release Center and transactional
# email configuration in the local secret store, and `local_secrets.apply()`
# pushes it into `os.environ`. Fail-closed tests assert the *absence* of that
# configuration, so clear it for every test; tests that need it set it back
# explicitly, which runs after this fixture.
_WORKSTATION_ONLY_ENV = (
    # The owner's real UUID lives in the local secret store. app/server.py
    # applies that store at import time -- before any fixture runs -- so
    # without scrubbing it here every test that seeds its own owner collides
    # with the workstation's canonical value and ensure_owner raises.
    "STRATFORGE_CANONICAL_OWNER_UUID",
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


@pytest.fixture(autouse=True)
def _approved_provenance(monkeypatch, request):
    """Release-ledger tests work with synthetic candidates.

    Provenance asks git and CI about a real commit, so left alone it would
    refuse every made-up SHA and turn unrelated suites red. It is a gate with
    its own tests: tests/test_release_provenance.py opts out and exercises the
    real evaluation.
    """
    if request.node.get_closest_marker("real_provenance"):
        return
    if "test_release_provenance" in str(request.node.fspath):
        return
    from app import release_provenance

    monkeypatch.setattr(release_provenance, "eligibility", lambda sha: {
        "eligible": True, "checks": [], "blocking": [], "reason": "", "commit": sha,
    })
