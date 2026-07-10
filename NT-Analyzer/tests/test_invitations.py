from __future__ import annotations

from app import invitations


def test_render_invitation_has_text_and_image() -> None:
    out = invitations.render_invitation(
        code="REF-AAAA-BBBB-CCCC",
        telegram_link="https://t.me/StratForge_bot?start=ref_REF-AAAA-BBBB-CCCC",
        web_link="https://app.stratforges.com/ui/?ref=REF-AAAA-BBBB-CCCC",
        plan_label="Стандарт", inviter="Dmytro C.")
    assert "REF-AAAA-BBBB-CCCC" in out["text"]
    assert "t.me/StratForge_bot" in out["text"]
    assert out["image_kind"] in ("png", "svg")
    assert out["image_data_url"].startswith("data:image/")
    # Pillow is available in this environment, so a raster card with bytes.
    if out["image_kind"] == "png":
        assert out["png_bytes"] and out["png_bytes"][:8] == b"\x89PNG\r\n\x1a\n"


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
