from __future__ import annotations

import base64

from app import invitations


def test_render_invitation_has_text_and_image() -> None:
    out = invitations.render_invitation(
        code="REF-AAAA-BBBB-CCCC",
        telegram_link="https://t.me/StratForge_bot?start=ref_REF-AAAA-BBBB-CCCC",
        web_link="https://app.stratforges.com/ui/?ref=REF-AAAA-BBBB-CCCC",
        plan_label="Стандарт", inviter="Dmytro C.")
    assert "REF-AAAA-BBBB-CCCC" in out["text"]
    assert "t.me/StratForge_bot" in out["text"]
    assert "Тариф: Стандарт" in out["text"]
    assert out["image_kind"] in ("png", "svg")
    assert out["image_data_url"].startswith("data:image/")
    # Pillow is available in this environment, so a raster card with bytes.
    if out["image_kind"] == "png":
        assert out["png_bytes"] and out["png_bytes"][:8] == b"\x89PNG\r\n\x1a\n"


def test_offer_lines_free_and_discount() -> None:
    tariff, deal = invitations._offer_lines("Developer Free", 100, 0.0, "")
    assert tariff == "Developer Free"
    assert "100%" in deal and "Бесплатно" in deal

    tariff, deal = invitations._offer_lines("Стандарт", 50, 9.99, "мес")
    assert tariff == "Стандарт"
    assert "−50%" in deal
    assert "$4.99" in deal
    assert "было $9.99" in deal


def test_render_text_includes_discount_offer() -> None:
    out = invitations.render_invitation(
        code="SF-DISC-50PC-TEST",
        plan_label="Стандарт",
        discount_percent=50,
        price_usd=9.99,
        period="мес",
        inviter="Owner",
    )
    assert "Тариф: Стандарт" in out["text"]
    assert "Предложение:" in out["text"]
    assert "50%" in out["text"] or "−50%" in out["text"]
    assert out["image_kind"] in ("png", "svg")


def test_svg_fallback_contains_tariff_and_offer_chips(monkeypatch) -> None:
    monkeypatch.setattr(invitations, "_pillow_provider", lambda ctx: None)
    monkeypatch.setattr(invitations, "_ai_image_provider", lambda ctx: None)
    monkeypatch.setattr(invitations, "_IMAGE_PROVIDERS",
                        [invitations._ai_image_provider, invitations._pillow_provider, invitations._svg_provider])
    out = invitations.render_invitation(
        code="SF-1234-5678-9012", plan_label="Free Preview", discount_percent=100)
    assert out["image_kind"] == "svg"
    assert out["png_bytes"] is None
    raw = base64.b64decode(out["image_data_url"].split(",", 1)[1]).decode("utf-8")
    assert "ТАРИФ" in raw and "ПРЕДЛОЖЕНИЕ" in raw
    assert "Free Preview" in raw
    assert "Бесплатно" in raw or "100%" in raw


def test_render_falls_back_to_svg_without_raster(monkeypatch) -> None:
    monkeypatch.setattr(invitations, "_pillow_provider", lambda ctx: None)
    monkeypatch.setattr(invitations, "_ai_image_provider", lambda ctx: None)
    monkeypatch.setattr(invitations, "_IMAGE_PROVIDERS",
                        [invitations._ai_image_provider, invitations._pillow_provider, invitations._svg_provider])
    out = invitations.render_invitation(code="SF-1234-5678-9012", plan_label="Free Preview")
    assert out["image_kind"] == "svg"
    assert out["image_data_url"].startswith("data:image/svg+xml;base64,")
    assert out["png_bytes"] is None


def test_register_image_provider_front() -> None:
    calls = {"n": 0}

    def fake(ctx):
        calls["n"] += 1
        return {"kind": "png", "bytes": b"x", "data_url": "data:image/png;base64,eA=="}

    invitations.register_image_provider(fake, front=True)
    try:
        out = invitations.render_invitation(code="SF-AAAA-BBBB-CCCC")
        assert out["image_kind"] == "png" and calls["n"] == 1
    finally:
        invitations._IMAGE_PROVIDERS.remove(fake)
