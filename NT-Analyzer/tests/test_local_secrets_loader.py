"""The real secret-loading path, tested on purpose.

``tests/conftest.py`` neutralises ``local_secrets.apply`` for every test, and it
has to: the function only sets a variable that is *absent* from ``os.environ``,
which is exactly the condition the conftest scrub creates, so several lazy call
sites were quietly putting the developer's real Release Center and email
configuration back in the middle of unrelated tests.

That neutralisation buys isolation at a price -- with it in place, nothing else
in the suite would notice if the loader stopped working entirely. So this file
opts back in, deliberately and in one place, and exercises the real function
against a temporary store.

Every test here re-installs the genuine ``apply`` over the conftest stub and
points ``secrets_path`` at ``tmp_path``. Nothing reads the developer's actual
secret file, and nothing leaks into the process environment beyond what
``monkeypatch`` will undo.
"""
from __future__ import annotations

import json

import pytest

from app import local_secrets

# The genuine function, captured at import time -- before the autouse conftest
# fixture has had a chance to replace the module attribute.
_REAL_APPLY = local_secrets.apply


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A temporary secret store, with the real loader restored."""
    monkeypatch.setattr(local_secrets, "apply", _REAL_APPLY)
    path = tmp_path / "secrets.local.json"
    monkeypatch.setattr(local_secrets, "secrets_path", lambda: path)
    return path


def _write(path, values):
    path.write_text(json.dumps(values), encoding="utf-8")


def test_the_conftest_stub_is_really_in_place():
    """Guards the guard. If the autouse neutralisation is ever removed, this
    fails and whoever removed it learns why it existed -- rather than the suite
    going intermittently red somewhere unrelated."""
    assert local_secrets.apply() is False, (
        "tests/conftest.py should neutralise local_secrets.apply for every test; "
        "without it, lazy call sites re-inject the workstation's real "
        "configuration mid-test"
    )
    assert local_secrets.apply is not _REAL_APPLY


def test_a_missing_store_is_not_an_error(store, monkeypatch):
    assert not store.exists()
    assert local_secrets.apply() is False


def test_values_are_loaded_into_the_environment(store, monkeypatch):
    monkeypatch.delenv("SF_LOADER_PROBE", raising=False)
    _write(store, {"SF_LOADER_PROBE": "loaded"})
    assert local_secrets.apply() is True
    import os
    assert os.environ["SF_LOADER_PROBE"] == "loaded"


def test_an_existing_value_is_never_overwritten(store, monkeypatch):
    """The whole contract of the loader: the process environment wins. A
    deployment that set a variable explicitly must not have it replaced by a
    developer's local file."""
    monkeypatch.setenv("SF_LOADER_PROBE", "from-the-process")
    _write(store, {"SF_LOADER_PROBE": "from-the-file"})
    assert local_secrets.apply() is True
    import os
    assert os.environ["SF_LOADER_PROBE"] == "from-the-process"


def test_a_removed_value_is_repopulated(store, monkeypatch):
    """The exact mechanism behind the isolation bug, pinned so it cannot be
    mistaken for something else later: deleting a name makes it eligible again,
    which is why a test that scrubs the environment then triggers a lazy apply
    gets the real value back."""
    monkeypatch.setenv("SF_LOADER_PROBE", "present")
    _write(store, {"SF_LOADER_PROBE": "from-the-file"})
    import os
    assert local_secrets.apply() is True
    assert os.environ["SF_LOADER_PROBE"] == "present"

    monkeypatch.delenv("SF_LOADER_PROBE")
    assert local_secrets.apply() is True
    assert os.environ["SF_LOADER_PROBE"] == "from-the-file"


def test_blank_values_are_skipped(store, monkeypatch):
    monkeypatch.delenv("SF_LOADER_BLANK", raising=False)
    _write(store, {"SF_LOADER_BLANK": "   ", "SF_LOADER_NULL": None})
    assert local_secrets.apply() is True
    import os
    assert "SF_LOADER_BLANK" not in os.environ
    assert "SF_LOADER_NULL" not in os.environ


def test_values_are_stripped(store, monkeypatch):
    monkeypatch.delenv("SF_LOADER_PADDED", raising=False)
    _write(store, {"SF_LOADER_PADDED": "  padded  "})
    assert local_secrets.apply() is True
    import os
    assert os.environ["SF_LOADER_PADDED"] == "padded"


@pytest.mark.parametrize("content", ["not json at all", "[1, 2, 3]", '"a string"'])
def test_a_malformed_store_is_ignored_rather_than_fatal(store, content):
    """A corrupt local file must not stop the process from starting -- it is a
    developer convenience, not a required input."""
    store.write_text(content, encoding="utf-8")
    assert local_secrets.apply() is False


def test_a_bom_prefixed_store_still_loads(store, monkeypatch):
    """Windows editors write UTF-8 with a BOM, and this file is edited by hand."""
    monkeypatch.delenv("SF_LOADER_BOM", raising=False)
    store.write_text(
        "﻿" + json.dumps({"SF_LOADER_BOM": "ok"}), encoding="utf-8",
    )
    assert local_secrets.apply() is True
    import os
    assert os.environ["SF_LOADER_BOM"] == "ok"


def test_read_does_not_touch_the_environment(store, monkeypatch):
    monkeypatch.delenv("SF_LOADER_READ", raising=False)
    _write(store, {"SF_LOADER_READ": "value"})
    assert local_secrets.read()["SF_LOADER_READ"] == "value"
    import os
    assert "SF_LOADER_READ" not in os.environ, "read() is not a loader"


def test_update_round_trips_through_the_store(store):
    assert local_secrets.update({"SF_LOADER_WRITTEN": "value"}) is True
    assert local_secrets.read()["SF_LOADER_WRITTEN"] == "value"


def test_the_real_store_is_never_read_by_these_tests(store):
    """The point of pointing secrets_path at tmp_path. If a future edit dropped
    that redirection, this catches it before the developer's real secrets are
    pulled into a test run."""
    assert str(store).startswith(str(store.parent))
    assert "secrets.local.json" == store.name
    assert local_secrets.secrets_path() == store
