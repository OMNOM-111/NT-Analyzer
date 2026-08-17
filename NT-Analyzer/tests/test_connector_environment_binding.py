"""A Connector installation belongs to exactly one environment.

_assert_environment exists so a Canary Connector can never be driven from
Production. It used to return early for any installation with no
deployment_environment, which made such a record valid in *every* environment --
the exact fail-open it was written to close. On live Production five
installations were still unstamped, so the clause was not theoretical.
"""
from __future__ import annotations

import pytest

from app import connector_protocol, runtime_env


def _installation(**overrides):
    row = {"installation_id": "inst_test", "status": "online"}
    row.update(overrides)
    return row


def test_a_matching_environment_is_accepted(monkeypatch):
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    connector_protocol._assert_environment(
        _installation(deployment_environment="production"))


def test_a_foreign_environment_is_refused(monkeypatch):
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    with pytest.raises(connector_protocol.ConnectorProtocolError) as exc:
        connector_protocol._assert_environment(
            _installation(deployment_environment="canary"))
    assert exc.value.code == "connector_environment_mismatch"


def test_an_unstamped_installation_is_refused(monkeypatch):
    """The fail-open. Previously this returned early and the record was usable
    from every environment at once."""
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    with pytest.raises(connector_protocol.ConnectorProtocolError) as exc:
        connector_protocol._assert_environment(_installation())
    assert exc.value.code == "connector_environment_mismatch"


def test_a_blank_stamp_is_refused(monkeypatch):
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    with pytest.raises(connector_protocol.ConnectorProtocolError):
        connector_protocol._assert_environment(
            _installation(deployment_environment="   "))


# --------------------------------------------------------------------------- #
# Stamping.
# --------------------------------------------------------------------------- #
def test_unstamped_installations_take_the_store_environment(monkeypatch):
    """Not a guess: each environment keeps an isolated Connector repository, so
    an installation in this one belongs to this one."""
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    doc = {"installations": [_installation(), _installation(installation_id="b")]}
    assert connector_protocol._stamp_environments(doc) == 2
    assert all(r["deployment_environment"] == "production"
               for r in doc["installations"])


def test_stamping_never_overwrites_an_existing_environment(monkeypatch):
    """A record already claiming another environment must keep saying so --
    rewriting it here would silently move a Canary Connector to Production."""
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    doc = {"installations": [_installation(deployment_environment="canary")]}
    assert connector_protocol._stamp_environments(doc) == 0
    assert doc["installations"][0]["deployment_environment"] == "canary"


def test_stamping_is_idempotent(monkeypatch):
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    doc = {"installations": [_installation()]}
    assert connector_protocol._stamp_environments(doc) == 1
    assert connector_protocol._stamp_environments(doc) == 0


def test_stamping_tolerates_a_malformed_row(monkeypatch):
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    doc = {"installations": ["not a dict", _installation()]}
    assert connector_protocol._stamp_environments(doc) == 1


def test_the_migrator_stamps_before_anything_reads(monkeypatch):
    """Stamping has to happen in _migrate_doc, which runs on every read and
    write, or a caller could reach _assert_environment first and be refused."""
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    doc, changed = connector_protocol._migrate_doc(
        {"installations": [_installation()]})
    assert changed is True
    assert doc["installations"][0]["deployment_environment"] == "production"
    connector_protocol._assert_environment(doc["installations"][0])


# --------------------------------------------------------------------------- #
# Stamping is evidence-based, not assumed.
# --------------------------------------------------------------------------- #
def test_a_consistent_store_proves_its_environment(monkeypatch):
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    doc = {"installations": [_installation(deployment_environment="production"),
                             _installation(installation_id="b")]}
    assert connector_protocol._store_proves_environment(doc) == "production"


def test_a_mixed_store_proves_nothing(monkeypatch):
    """If records from two environments are present, presence stops being
    evidence -- so nothing is stamped and the ambiguity is left for a human."""
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    doc = {"installations": [_installation(deployment_environment="canary"),
                             _installation(installation_id="b")]}
    assert connector_protocol._store_proves_environment(doc) == ""
    assert connector_protocol._stamp_environments(doc) == 0
    assert "deployment_environment" not in doc["installations"][1]


def test_a_foreign_stamp_anywhere_in_the_store_blocks_stamping(monkeypatch):
    """Not just on installations: an enrollment or session from another
    environment is the same evidence of mixing."""
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    for key in ("enrollments", "sessions", "commands"):
        doc = {"installations": [_installation()],
               key: [{"deployment_environment": "canary"}]}
        assert connector_protocol._store_proves_environment(doc) == "", key
        assert connector_protocol._stamp_environments(doc) == 0, key


def test_a_proven_stamp_records_why_it_was_chosen(monkeypatch):
    """So a later reader can tell a stamp inferred from store origin from one
    written at enrollment time."""
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    doc = {"installations": [_installation()]}
    connector_protocol._stamp_environments(doc)
    assert doc["installations"][0]["environment_source"] == "store_origin"


def test_an_ambiguous_record_stays_refused(monkeypatch):
    """The safe outcome: unstamped and unprovable means unusable, not
    universally usable."""
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "production")
    doc = {"installations": [_installation(deployment_environment="canary"),
                             _installation(installation_id="b")]}
    connector_protocol._stamp_environments(doc)
    with pytest.raises(connector_protocol.ConnectorProtocolError):
        connector_protocol._assert_environment(doc["installations"][1])
