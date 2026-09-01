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
        "data_first": "2026-05-01",
        "data_last": "2026-08-28",
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
    # root/expiry are derived, not transmitted: the wire budget is 16 KiB.
    assert row["root"] == "MNQ" and row["expiry"] == "09-26"
    assert row["tick_size"] == 0.25 and row["point_value"] == 2.0
    assert row["source"] == "connector_runtime_catalog"
    assert out["instrument_count"] == 1


def test_connector_catalog_rejects_a_bare_root() -> None:
    """The bare root is the defect this channel exists to remove.

    Shaped exactly like Production's fallback: a root name and no scanned data
    range at all.
    """
    bare = {"instrument": "MNQ", "data_first": "", "data_last": ""}
    with pytest.raises(connector_protocol.ConnectorProtocolError) as rejected:
        connector_protocol._normalise_runtime_catalog(
            _catalog(instruments=[bare]), 1_800_000_000.0)
    assert rejected.value.code == "invalid_runtime_catalog"


def test_a_spot_pair_without_an_expiry_is_still_accepted() -> None:
    """BTCUSD has no contract month and is still a real, runnable instrument.

    The real 1547-contract scan contains BTCUSD and BCHEUR; a name-shape rule
    would have silently dropped both.
    """
    out = connector_protocol._normalise_runtime_catalog(
        _catalog(instruments=[_contract("BTCUSD")]), 1_800_000_000.0)
    assert [row["instrument"] for row in out["instruments"]] == ["BTCUSD"]
    assert out["instruments"][0]["expiry"] == ""


def test_job_gate_accepts_a_spot_pair_from_the_catalog() -> None:
    jobqueue._validate_instrument_contract(
        _request("BTCUSD"), {"instruments": [_contract("BTCUSD")]})


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


# --------------------------------------------------------------------------- #
# The transport cap is real: a command result over 16 KiB is refused outright.
# --------------------------------------------------------------------------- #
def test_a_realistic_full_snapshot_fits_the_command_result_cap() -> None:
    """What the device actually produces must survive `_safe_result` intact.

    Measured against the real 1547-contract scan: filling the device budget
    round-robin yields 100 contracts across all 52 roots. An oversized
    result is not truncated -- it is refused, and the server silently keeps its
    stale roots, which is the failure this whole channel exists to remove.
    """
    instruments = [
        _contract(f"{root}{index:02d} 09-26")
        for root in ("MNQQ", "MESS", "MGCC", "M2KK")
        for index in range(25)
    ]
    assert len(instruments) == connector_protocol.MAX_RUNTIME_CATALOG_INSTRUMENTS
    payload = _catalog(
        instruments=instruments,
        strategies=[{"class_name": f"Strategy{i:03d}",
                     "display_name": f"Strategy {i:03d}", "stable_id": f"s{i:03d}"}
                    for i in range(8)],
        commission_templates=[{"name": f"Template {i}", "display": f"Template {i}",
                               "supported": True} for i in range(8)],
    )
    encoded = connector_protocol._canonical_json({"catalog": payload})
    assert len(encoded) <= connector_protocol.MAX_COMMAND_RESULT_BYTES, (
        f"{len(encoded)} bytes exceeds the "
        f"{connector_protocol.MAX_COMMAND_RESULT_BYTES} byte cap")
    connector_protocol._safe_result({"catalog": payload})


def test_an_oversized_snapshot_is_refused_not_silently_truncated() -> None:
    # _safe_payload binds first: a list over 100 items never reaches the byte
    # check, and either way the result is refused rather than quietly trimmed.
    oversized = {"catalog": _catalog(
        instruments=[_contract(f"ROOT{index:04d} 09-26") for index in range(200)])}
    with pytest.raises(connector_protocol.ConnectorProtocolError) as rejected:
        connector_protocol._safe_result(oversized)
    assert rejected.value.code in {"result_too_large", "invalid_command_payload"}


def test_the_device_budget_stays_under_the_server_cap() -> None:
    """The device budget must leave room for the envelope, not equal the cap."""
    source = BRIDGE.read_text(encoding="utf-8-sig")
    assert "ConnectorSnapshotByteBudget = 15 * 1024" in source
    assert 15 * 1024 < connector_protocol.MAX_COMMAND_RESULT_BYTES


def test_no_root_can_be_evicted_by_the_budget() -> None:
    """Round-robin, not global recency: every root keeps its live month.

    A global newest-first cap silently dropped whole roots once the catalog
    grew -- measured on the real 1547-contract scan, a 200 cap lost 10YR, 2YR,
    30YR and 5YR entirely.
    """
    source = BRIDGE.read_text(encoding="utf-8-sig")
    assert "int depth = 0;" in source
    assert "foreach (string root in roots)" in source
    assert "if (depth >= group.Count) continue;" in source
    # A per-root sort still puts each root's newest contract first.
    assert "byRoot[root].Sort((a, b) => b.Key.CompareTo(a.Key));" in source


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
    assert "ConnectorSnapshotByteBudget" in source
    assert "ConnectorInstrumentCountLimit = 100" in source
    # Per-root newest-first, so the budget never drops a live month.
    assert "byRoot[root].Sort((a, b) => b.Key.CompareTo(a.Key));" in source
    assert "ConnectorInstrumentMaxAgeDays = 400" in source
