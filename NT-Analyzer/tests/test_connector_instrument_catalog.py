"""A backtest may only name a contract the real NinjaTrader catalog lists.

Production has no NinjaTrader, so before this the instrument panel offered bare
roots like ``MNQ`` and ``6A``. Jobs were accepted, NinjaTrader could not resolve
a contract month, and the owner saw a silent ``failed`` run with no reason. The
Connector now ships concrete contracts and the server refuses anything else.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import connector_protocol, jobqueue

BRIDGE = Path(__file__).resolve().parents[1] / "bridge" / "src" / "Reporting" / "CatalogWriter.cs"


def _contract(name: str = "MNQ 09-26", **over) -> dict:
    row = {
        "instrument": name,
        "root": name.split(" ", 1)[0],
        "expiry": name.split(" ", 1)[1] if " " in name else "",
        "data_first": "2026-05-01",
        "data_last": "2026-08-28",
        "asset_class": "futures",
        "exchange": "Globex",
        "tick_size": 0.25,
        "point_value": 2.0,
        "tick_value": 0.5,
    }
    row.update(over)
    return row


def _catalog(**over) -> dict:
    doc = {
        "schema_version": 1,
        "generated_at_utc": "2026-09-01T05:00:00Z",
        "strategies": [],
        "commission_templates": [],
        "instruments": [_contract()],
    }
    doc.update(over)
    return doc


# --------------------------------------------------------------------------- #
# Protocol: instruments travel on the existing signed snapshot.
# --------------------------------------------------------------------------- #
def test_connector_catalog_accepts_concrete_contracts() -> None:
    out = connector_protocol._normalise_runtime_catalog(_catalog(), 1_800_000_000.0)
    assert [row["instrument"] for row in out["instruments"]] == ["MNQ 09-26"]
    row = out["instruments"][0]
    assert row["root"] == "MNQ" and row["expiry"] == "09-26"
    assert row["tick_size"] == 0.25 and row["point_value"] == 2.0
    assert row["source"] == "connector_runtime_catalog"
    assert out["instrument_count"] == 1


def test_connector_catalog_rejects_a_bare_root() -> None:
    """The bare root is the defect this channel exists to remove."""
    with pytest.raises(connector_protocol.ConnectorProtocolError) as rejected:
        connector_protocol._normalise_runtime_catalog(
            _catalog(instruments=[_contract("MNQ")]), 1_800_000_000.0)
    assert rejected.value.code == "invalid_runtime_catalog"


def test_connector_catalog_without_instruments_stays_valid() -> None:
    """Backward compatibility: an older Connector simply omits the field."""
    payload = _catalog()
    payload.pop("instruments")
    out = connector_protocol._normalise_runtime_catalog(payload, 1_800_000_000.0)
    assert out["instruments"] == []
    assert out["instrument_count"] == 0


def test_connector_catalog_bounds_the_instrument_list() -> None:
    too_many = [_contract(f"MNQ {index:02d}-26")
                for index in range(connector_protocol.MAX_RUNTIME_CATALOG_INSTRUMENTS + 1)]
    with pytest.raises(connector_protocol.ConnectorProtocolError):
        connector_protocol._normalise_runtime_catalog(
            _catalog(instruments=too_many), 1_800_000_000.0)


def test_connector_catalog_rejects_unknown_instrument_fields() -> None:
    with pytest.raises(connector_protocol.ConnectorProtocolError):
        connector_protocol._normalise_runtime_catalog(
            _catalog(instruments=[_contract(**{"margin": 1})]), 1_800_000_000.0)


# --------------------------------------------------------------------------- #
# Job validation: no contract, no run.
# --------------------------------------------------------------------------- #
def _request(instrument: str, runtime_catalog=None) -> jobqueue.CreateJobRequest:
    return jobqueue.CreateJobRequest(
        class_name="SampleMACrossOver",
        instrument=instrument,
        bars_period_type="Minute",
        bars_period_value=5,
        from_utc="2026-08-20T00:00:00Z",
        to_utc="2026-08-22T00:00:00Z",
        parameters={},
        role="research",
        runtime_catalog=runtime_catalog,
    )


def test_device_contract_is_accepted() -> None:
    jobqueue._validate_instrument_contract(
        _request("MNQ 09-26"), {"instruments": [_contract()]})


def test_bare_root_is_refused_with_an_actionable_message() -> None:
    with pytest.raises(jobqueue.JobValidationError) as rejected:
        jobqueue._validate_instrument_contract(
            _request("MNQ"), {"instruments": [_contract()]})
    message = str(rejected.value)
    assert "MNQ" in message and "09-26" in message


def test_instrument_outside_the_catalog_is_refused() -> None:
    with pytest.raises(jobqueue.JobValidationError) as rejected:
        jobqueue._validate_instrument_contract(
            _request("ZZZ 01-99"), {"instruments": [_contract()]})
    assert "каталоге" in str(rejected.value)


def test_a_catalog_of_only_bare_roots_blocks_the_run(monkeypatch) -> None:
    """Exactly the Production state: 36 roots, none of them runnable."""
    monkeypatch.setattr(
        jobqueue, "read_instruments_catalog",
        lambda: {"instruments": [{"instrument": root} for root in ("MNQ", "6A", "MES")]})
    with pytest.raises(jobqueue.JobValidationError) as rejected:
        jobqueue._validate_instrument_contract(_request("MNQ"), None)
    assert "недоступен" in str(rejected.value)


def test_old_connector_falls_back_to_a_real_local_catalog(monkeypatch) -> None:
    """No device instruments must not disable a machine whose scan is real."""
    monkeypatch.setattr(
        jobqueue, "read_instruments_catalog",
        lambda: {"instruments": [_contract("MNQ 09-26")]})
    jobqueue._validate_instrument_contract(
        _request("MNQ 09-26"), {"strategies": [], "commission_templates": []})


def test_bare_root_detection_is_explicit() -> None:
    assert jobqueue._instruments_are_bare_roots([{"instrument": "MNQ"}]) is True
    assert jobqueue._instruments_are_bare_roots([]) is True
    assert jobqueue._instruments_are_bare_roots([{"instrument": "MNQ 09-26"}]) is False


# --------------------------------------------------------------------------- #
# The device side ships the contracts in the first place.
# --------------------------------------------------------------------------- #
def test_connector_snapshot_source_sends_bounded_instruments() -> None:
    source = BRIDGE.read_text(encoding="utf-8-sig")
    assert '["instruments"] = instruments' in source
    assert "BuildConnectorInstruments" in source
    assert "ConnectorInstrumentLimit = 400" in source
    # Newest first, so a cap never drops the live month.
    assert "eligible.Sort((a, b) => b.Key.CompareTo(a.Key));" in source
