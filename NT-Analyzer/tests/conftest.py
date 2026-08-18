"""Global test safety gates.

The developer workstation may have real DPAPI-backed agents configured. Unit
tests must never discover or call them; tests that exercise routing replace the
candidate list with explicit mock agents.
"""
from __future__ import annotations

import itertools
import os
import shutil
import tempfile
import uuid
from pathlib import Path

# Tests must never write the workstation's live data directory, and this has to
# be set before any app module is imported.
#
# Two concurrent pytest runs -- exactly what CI does, since ci.yml/python-tests
# and next-architecture-ci/tests(windows-self-hosted) both run the full suite on
# the one self-hosted runner -- were both performing atomic `.tmp` -> rename
# writes into <project>/data. On Windows a rename onto a file another process
# holds open fails with WinError 5/32. That exception escapes inside an HTTP
# handler thread after the response line is already out, so `_handle_unexpected`
# has nothing safe left to send and the connection closes mid-response: the
# waiting client gets WSAECONNABORTED (10053) instead of the status it had been
# given. It showed up as three different "flaky" tests across four CI runs,
# never the same one twice. The running LOCAL server writes that same directory,
# which made the developer machine a third writer.
#
# The pid and random suffix matter: without them two runs would share this
# directory too and simply move the collision.
#
# It is deliberately the lower-precedence of the two development root
# variables. runtime_env.data_root() prefers STRATFORGE_DEVELOPMENT_DATA_ROOT
# over NTA_STAGING_DATA_ROOT, so claiming the preferred name here would
# silently override the tests that manage roots themselves -- which is exactly
# what test_staging_isolation exists to check. Taking the fallback name gives
# every other test isolation by default and still lets those tests win.
_TEST_DATA_ROOT = Path(tempfile.gettempdir()) / (
    "stratforge-tests-%d-%s" % (os.getpid(), uuid.uuid4().hex[:8])
)
_TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["NTA_STAGING_DATA_ROOT"] = str(_TEST_DATA_ROOT)

# The production root is deliberately NOT claimed here, and that is a known
# gap rather than an oversight. A test that declares no environment resolves to
# PRODUCTION, whose branch returns <project>/data outright, so nine live files
# are still written by the suite -- listed by the session check below.
#
# Both ways of closing it were tried and rejected. An empty production root
# fails thirty-two tests that read committed baselines; a seeded copy carries
# the workstation's live telegram inbox, durable DB and audit logs into the run
# and fails twenty-five that expect a clean slate. Seeding baselines but not
# state moves the failures again, to the market-data tests that read runtime
# baselines. Closing it properly means giving those test files their own roots
# individually, which is a change of a different size from this one.
#
# What that gap can no longer do is take CI down: the two Windows suites no
# longer run at the same time (see .github/workflows), so nothing else is
# writing these files while a test does.

# Names the per-test directories. A counter rather than the test id: node ids
# contain characters Windows will not accept in a path.
_COUNTER = itertools.count(1)

import pytest  # noqa: E402

from app import local_secrets  # noqa: E402
from app.ai_lab import agent_router  # noqa: E402


_LIVE_DATA = Path(__file__).resolve().parents[1] / "data"
_LIVE_BEFORE: dict = {}


def _live_manifest() -> dict:
    """Size and mtime of every file under the live data directory.

    governance-rendered is excluded: the running LOCAL server regenerates it,
    so it changes for reasons that have nothing to do with the suite.
    """
    manifest = {}
    if not _LIVE_DATA.is_dir():
        return manifest
    for path in _LIVE_DATA.rglob("*"):
        if not path.is_file() or "governance-rendered" in path.as_posix():
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


# The live files the suite is still known to write, because those tests resolve
# to PRODUCTION and that root is not isolated yet. Listing them explicitly means
# the check fails on a *new* writer rather than staying permanently red on the
# ones already understood -- a check that is always failing is a check nobody
# reads. Shrinking this list is the remaining work; growing it is a regression.
_KNOWN_LIVE_WRITERS = frozenset({
    "audit/paypal-webhook.jsonl",
    "audit/telegram-mini-app.jsonl",
    "durable/nt_analyzer.sqlite3",
    "durable/nt_analyzer.sqlite3-wal",
    "durable/nt_analyzer.sqlite3-shm",
    "integrations/telegram.remote-access.json",
    "integrations/telegram.state.json",
    "integrations/workspaces.dpapi",
    "operations/in_app_notifications.json",
    "operations/vitek.json",
    "reports/report_numbers.json",
    "runtime/market_data_failover_status.json",
    "runtime/market_data_gap_recovery.jsonl",
    "runtime/market_data_ipc_audit.jsonl",
    "runtime/market_data_ipc_token.json",
    "runtime/price_alerts.json",
    "runtime/user-support.json",
})


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Fail the run if the suite wrote a live file nobody has accounted for.

    This is the property that matters, and it is measured rather than assumed:
    which environment variables achieve isolation depends on which environment
    each test declares, and pinning the variables directly both over-reached
    (thirty-two tests need the committed baselines) and under-covered (nine
    files were still written). A byte-level before/after comparison cannot be
    fooled by either.
    """
    after = _live_manifest()
    changed = (set(_LIVE_BEFORE) ^ set(after)) | {
        p for p in set(_LIVE_BEFORE) & set(after) if _LIVE_BEFORE[p] != after[p]
    }
    shutil.rmtree(_TEST_DATA_ROOT, ignore_errors=True)
    unexpected = sorted(path for path in changed
                        if path not in _KNOWN_LIVE_WRITERS)
    if unexpected:
        session.exitstatus = 1
        print("\n\nTHE SUITE WROTE LIVE DATA FILES THAT ARE NOT ACCOUNTED FOR:")
        for path in unexpected[:20]:
            print("   ", path)
        if len(unexpected) > 20:
            print("    ... and %d more" % (len(unexpected) - 20))
        print("Give the test that writes it a root of its own, or list it in "
              "_KNOWN_LIVE_WRITERS with a reason.")


@pytest.fixture(autouse=True)
def isolated_data_root(request, monkeypatch):
    """A data directory of its own for every test.

    A single session-wide root still lets tests contaminate each other. Two
    files disagreed about the on-disk format at the same path -- one wrote a
    DPAPI-encrypted workspaces store, the next read it as JSON and died with
    "'utf-8' codec can't decode byte 0xb7" -- so a test passed alone and failed
    in the suite depending on what ran before it.

    No fixture in this suite is module- or session-scoped, so nothing depends on
    state surviving between tests, and a per-test root costs one mkdir.

    Set through the fallback variables (NTA_*), so a test that manages roots
    explicitly still overrides it: setting the same name replaces this value,
    and the STRATFORGE_* names outrank it either way.
    """
    root = _TEST_DATA_ROOT / ("t%04d" % next(_COUNTER))
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NTA_STAGING_DATA_ROOT", str(root))
    return root


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
