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
                for index in range(connector_protocol.MAX_RUNTIME_CATALOG_INSTRUMENTS_PER_PAGE + 1)]
    with pytest.raises(connector_protocol.ConnectorProtocolError):
        connector_protocol._normalise_runtime_catalog(
            _catalog(instruments=too_many), 1_800_000_000.0)


# --------------------------------------------------------------------------- #
# The transport cap is real: a command result over 16 KiB is refused outright.
# --------------------------------------------------------------------------- #
def test_a_realistic_full_snapshot_fits_the_command_result_cap() -> None:
    """What the device actually produces must survive `_safe_result` intact.

    One page, not the whole catalog: the full set is delivered as several
    signed pages so no valid contract is dropped. An oversized
    result is not truncated -- it is refused, and the server silently keeps its
    stale roots, which is the failure this whole channel exists to remove.
    """
    instruments = [
        _contract(f"{root}{index:02d} 09-26")
        for root in ("MNQQ", "MESS", "MGCC", "M2KK")
        for index in range(20)
    ]
    assert len(instruments) == connector_protocol.MAX_RUNTIME_CATALOG_INSTRUMENTS_PER_PAGE
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


def test_the_device_page_target_leaves_headroom_under_the_cap() -> None:
    """12 KiB per page, not 15 KiB hugging a 16 KiB hard refusal."""
    source = BRIDGE.read_text(encoding="utf-8-sig")
    assert "ConnectorPageTargetBytes = 12 * 1024" in source
    assert 12 * 1024 < connector_protocol.MAX_COMMAND_RESULT_BYTES


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
    # Per-root newest-first, so active months lead the pages.
    assert "byRoot[root].Sort((a, b) => b.Key.CompareTo(a.Key));" in source
    assert "ConnectorInstrumentMaxAgeDays = 400" in source
    assert "BuildConnectorCatalogPage" in source


# --------------------------------------------------------------------------- #
# Paging: the full catalog is delivered, never truncated.
# --------------------------------------------------------------------------- #
def _page(index: int, count: int, rows, *, catalog_id="cat0123456789abcdef",
          total=None, generated="2026-09-01T05:00:00Z") -> dict:
    return {
        "schema_version": 1,
        "generated_at_utc": generated,
        "catalog_id": catalog_id,
        "page_index": index,
        "page_count": count,
        "total_count": total if total is not None else len(rows),
        "strategies": [], "commission_templates": [],
        "instruments": rows,
    }


def test_a_partial_snapshot_never_replaces_the_live_catalog() -> None:
    """The failure that matters: half a delivery must not blank the catalog."""
    live = {"instruments": [_contract("PREV 01-26")]}
    install = {"runtime_catalog": live}
    first = connector_protocol._normalise_runtime_catalog(
        _page(0, 2, [_contract("MNQ 09-26")], total=2), 1_800_000_000.0)
    activated, _ = connector_protocol._accept_runtime_catalog_page(
        install, first, 1_800_000_000.0)
    assert activated is False
    assert install["runtime_catalog"] is live


def test_the_last_page_activates_the_whole_catalog_atomically() -> None:
    install: dict = {}
    rows = [[_contract("MNQ 09-26")], [_contract("MES 09-26")]]
    for index, page_rows in enumerate(rows):
        page = connector_protocol._normalise_runtime_catalog(
            _page(index, 2, page_rows, total=2), 1_800_000_000.0)
        activated, assembled = connector_protocol._accept_runtime_catalog_page(
            install, page, 1_800_000_000.0)
    assert activated is True
    assert [row["instrument"] for row in assembled["instruments"]] == [
        "MNQ 09-26", "MES 09-26"]
    assert assembled["total_count"] == 2
    assert "runtime_catalog_staging" not in install


def test_a_newer_snapshot_discards_the_partial_one_not_the_live_one() -> None:
    live = {"instruments": [_contract("PREV 01-26")]}
    install = {"runtime_catalog": live}
    stale = connector_protocol._normalise_runtime_catalog(
        _page(0, 3, [_contract("MNQ 09-26")], catalog_id="old0000000000000", total=3),
        1_800_000_000.0)
    connector_protocol._accept_runtime_catalog_page(install, stale, 1_800_000_000.0)
    fresh = connector_protocol._normalise_runtime_catalog(
        _page(0, 1, [_contract("MES 09-26")], catalog_id="new0000000000000"),
        1_800_000_000.0)
    activated, assembled = connector_protocol._accept_runtime_catalog_page(
        install, fresh, 1_800_000_000.0)
    assert activated is True
    assert [r["instrument"] for r in assembled["instruments"]] == ["MES 09-26"]


def test_pages_of_different_snapshots_are_refused() -> None:
    install: dict = {}
    first = connector_protocol._normalise_runtime_catalog(
        _page(0, 2, [_contract("MNQ 09-26")], total=2), 1_800_000_000.0)
    connector_protocol._accept_runtime_catalog_page(install, first, 1_800_000_000.0)
    mismatched = connector_protocol._normalise_runtime_catalog(
        _page(1, 2, [_contract("MES 09-26")], total=2,
              generated="2026-09-01T06:00:00Z"), 1_800_000_000.0)
    with pytest.raises(connector_protocol.ConnectorProtocolError) as rejected:
        connector_protocol._accept_runtime_catalog_page(
            install, mismatched, 1_800_000_000.0)
    assert rejected.value.code == "runtime_catalog_page_mismatch"


def test_an_assembled_catalog_short_of_total_count_is_refused() -> None:
    install: dict = {}
    for index in range(2):
        page = connector_protocol._normalise_runtime_catalog(
            _page(index, 2, [_contract(f"MNQ 0{index}-26")], total=9), 1_800_000_000.0)
        if index == 0:
            connector_protocol._accept_runtime_catalog_page(
                install, page, 1_800_000_000.0)
            continue
        with pytest.raises(connector_protocol.ConnectorProtocolError) as rejected:
            connector_protocol._accept_runtime_catalog_page(
                install, page, 1_800_000_000.0)
        assert rejected.value.code == "runtime_catalog_incomplete"


def test_a_multi_page_snapshot_requires_a_catalog_id() -> None:
    payload = _page(0, 2, [_contract()], total=2)
    payload.pop("catalog_id")
    with pytest.raises(connector_protocol.ConnectorProtocolError):
        connector_protocol._normalise_runtime_catalog(payload, 1_800_000_000.0)


def test_an_old_connector_result_is_one_complete_page() -> None:
    """No paging fields at all still activates, exactly as before."""
    legacy = {"schema_version": 1, "generated_at_utc": "2026-09-01T05:00:00Z",
              "strategies": [], "commission_templates": []}
    page = connector_protocol._normalise_runtime_catalog(legacy, 1_800_000_000.0)
    assert page["page_count"] == 1 and page["page_index"] == 0
    activated, _ = connector_protocol._accept_runtime_catalog_page(
        {}, page, 1_800_000_000.0)
    assert activated is True


def test_the_device_pages_by_measured_bytes_and_count() -> None:
    source = BRIDGE.read_text(encoding="utf-8-sig")
    assert "ConnectorPageTargetBytes = 12 * 1024" in source
    assert "ConnectorInstrumentsPerPage = 80" in source
    # Measured, not estimated.
    assert "row.ToString(Formatting.None).Length + 1" in source
    assert "ComputeCatalogId" in source
    # Round-robin ordering keeps active roots on the first pages without
    # discarding the rest of the eligible set.
    assert "ordered.Add(ProjectConnectorInstrument(group[depth].Value));" in source
    assert 12 * 1024 < connector_protocol.MAX_COMMAND_RESULT_BYTES


# --------------------------------------------------------------------------- #
# The version gate must not withhold the catalog from a newer Connector.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("version", "supported"), [
    ("0.4.1-dev.20", False),   # older base, high dev counter
    ("0.4.2-dev.16", False),   # the build before the feature landed
    ("0.4.2-dev.17", True),    # where it landed
    ("0.4.2", True),           # the final release contains it
    ("0.4.3-dev.1", True),     # newer base, low dev counter
    ("0.4.3", True),
    ("0.5.0-dev.1", True),
    ("", False),
    ("garbage", False),
])
def test_runtime_catalog_support_is_decided_by_the_base_version(
    version: str, supported: bool,
) -> None:
    """Reading only ``-dev.N`` ranked 0.4.3-dev.1 below 0.4.2-dev.17.

    That silently withheld the snapshot command from a strictly newer
    Connector, leaving the server on bare roots with no way to recover.
    """
    assert connector_protocol._connector_supports_runtime_catalog(version) is supported
