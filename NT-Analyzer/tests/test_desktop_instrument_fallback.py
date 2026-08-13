from app.server import _DESKTOP_INSTRUMENT_ROOTS, apply_desktop_instrument_fallbacks


def test_empty_catalog_desktop_fallback_uses_supported_roots() -> None:
    out = apply_desktop_instrument_fallbacks([], desktop=True)
    assert {row["root"] for row in out} == set(_DESKTOP_INSTRUMENT_ROOTS)
    assert all(row["front_month"]["instrument"] == row["root"] for row in out)
    assert all(
        row["front_month"]["source"] == "desktop_root_fallback" for row in out
    )


def test_catalog_front_month_is_preserved_and_missing_roots_are_added() -> None:
    existing = [{
        "root": "MNQ",
        "front_month": {"instrument": "MNQ 09-26", "expiry": "09-26"},
        "contracts": [{"instrument": "MNQ 09-26"}],
    }]
    out = apply_desktop_instrument_fallbacks(existing, desktop=True)
    mnq = next(row for row in out if row["root"] == "MNQ")
    assert mnq["front_month"]["instrument"] == "MNQ 09-26"
    assert "MES" in {row["root"] for row in out}
    assert len(out) == len(_DESKTOP_INSTRUMENT_ROOTS)


def test_missing_front_month_uses_root_without_replacing_other_contracts() -> None:
    existing = [{
        "root": "MES",
        "front_month": None,
        "contracts": [{"instrument": "MES 12-26"}],
    }]
    out = apply_desktop_instrument_fallbacks(existing, desktop=True)
    mes = next(row for row in out if row["root"] == "MES")
    assert mes["front_month"]["instrument"] == "MES"
    assert [row["instrument"] for row in mes["contracts"]] == ["MES", "MES 12-26"]


def test_non_desktop_payload_is_unchanged() -> None:
    payload = [{"root": "ES", "front_month": {"instrument": "ES 09-26"}}]
    assert apply_desktop_instrument_fallbacks([], desktop=False) == []
    assert apply_desktop_instrument_fallbacks(payload, desktop=False) is payload
