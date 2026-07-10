"""Invitation rendering — provider-based, offline-first.

Turns a promo/invite voucher into a shareable artifact: a crafted invitation
text plus a branded image. Image generation walks a provider chain and uses the
first one that succeeds, always falling back to a fully local render so it works
with no network and no API keys:

    1. AI image provider  — used only if an external generator is configured.
    2. Pillow PNG card    — local, branded raster (works for Telegram sendPhoto).
    3. SVG card           — dependency-free string (display-only fallback).

Register additional image providers with ``register_image_provider`` without
touching callers.
"""
from __future__ import annotations

import base64
import html
import io
import random
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


BRAND_NAME = "StratForge AI"
BRAND_TAGLINE = "Автономные ИИ-агенты для NinjaTrader-стратегий"
BRAND_SUBTITLE = "Разработка · контроль · аналитика на передовых моделях ИИ"

_BG_TOP = (18, 26, 42)
_BG_BOTTOM = (9, 13, 20)
_ACCENT = (31, 201, 255)
_ACCENT_2 = (124, 92, 255)
_INK = (240, 244, 250)
_MUTED = (150, 165, 185)

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

# Provider signature: (context) -> {"kind","data_url","bytes"} or None.
ImageProvider = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
_IMAGE_PROVIDERS: List[ImageProvider] = []


def register_image_provider(provider: ImageProvider, *, front: bool = True) -> None:
    if front:
        _IMAGE_PROVIDERS.insert(0, provider)
    else:
        _IMAGE_PROVIDERS.append(provider)


def build_text(*, code: str, link: str = "", plan_label: str = "", inviter: str = "") -> str:
    lines = [
        f"Приглашаю вас в {BRAND_NAME} — приложение, где автономные ИИ-агенты "
        "помогают разрабатывать, проверять и контролировать торговые стратегии "
        "NinjaTrader на передовых моделях искусственного интеллекта.",
        "",
    ]
    if inviter:
        lines.append(f"Пригласил: {inviter}")
    if plan_label:
        lines.append(f"Уровень доступа: {plan_label}")
    lines.append(f"Промокод: {code}")
    if link:
        lines.append("")
        lines.append(f"Регистрация: {link}")
    lines.append("")
    lines.append("Войдите через Telegram, подтвердите номер и активируйте доступ промокодом.")
    return "\n".join(lines)


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _brand_photo_path() -> Optional[Path]:
    """A random owner-supplied brand photo, if any were dropped into
    ``data/integrations/brand/``. Used as the invitation card background."""
    directory = _root() / "data" / "integrations" / "brand"
    if not directory.is_dir():
        return None
    images = [p for p in directory.iterdir()
              if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and p.is_file()]
    return random.choice(images) if images else None


def _load_font(size: int):
    from PIL import ImageFont  # noqa: WPS433 (local import: optional dependency)
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _pillow_provider(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001 — Pillow is optional
        return None
    try:
        width, height = 1000, 525
        img = Image.new("RGB", (width, height), _BG_BOTTOM)
        used_photo = False
        photo_path = _brand_photo_path()
        if photo_path is not None:
            try:
                photo = Image.open(photo_path).convert("RGB")
                sw, sh = photo.size
                scale = max(width / sw, height / sh)
                photo = photo.resize((max(1, int(sw * scale)), max(1, int(sh * scale))), Image.LANCZOS)
                left = (photo.size[0] - width) // 2
                top = (photo.size[1] - height) // 2
                img = Image.blend(photo.crop((left, top, left + width, top + height)),
                                  Image.new("RGB", (width, height), _BG_BOTTOM), 0.58)
                used_photo = True
            except Exception:  # noqa: BLE001
                used_photo = False
        draw = ImageDraw.Draw(img)
        if not used_photo:
            for y in range(height):
                t = y / height
                draw.line(
                    [(0, y), (width, y)],
                    fill=tuple(int(_BG_TOP[i] * (1 - t) + _BG_BOTTOM[i] * t) for i in range(3)),
                )
        draw.rectangle([0, 0, width, 6], fill=_ACCENT)
        draw.text((60, 46), BRAND_NAME, font=_load_font(42), fill=_INK)
        draw.text((62, 100), BRAND_TAGLINE, font=_load_font(21), fill=(200, 214, 235))
        draw.text((62, 132), BRAND_SUBTITLE, font=_load_font(17), fill=_MUTED)
        draw.text((60, 186), "Персональное приглашение", font=_load_font(44), fill=(255, 255, 255))

        plan_label = str(ctx.get("plan_label") or "Доступ")
        chip_font = _load_font(22)
        tw = draw.textlength(plan_label, font=chip_font)
        draw.rounded_rectangle([60, 250, 60 + int(tw) + 40, 296], radius=16, fill=(26, 36, 54), outline=_ACCENT_2, width=2)
        draw.text((80, 258), plan_label, font=chip_font, fill=(210, 220, 240))

        code = str(ctx.get("code") or "")
        draw.rounded_rectangle([60, 320, 640, 392], radius=14, fill=(20, 28, 42), outline=_ACCENT, width=2)
        draw.text((80, 336), code, font=_load_font(34), fill=(230, 240, 255))

        inviter = str(ctx.get("inviter") or "")
        if inviter:
            draw.text((60, 416), f"Пригласил: {inviter}", font=_load_font(22), fill=_MUTED)

        link = str(ctx.get("link") or "")
        if link:
            draw.text((60, 470), link[:80], font=_load_font(20), fill=_ACCENT)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        blob = buffer.getvalue()
        return {"kind": "png", "bytes": blob,
                "data_url": "data:image/png;base64," + base64.b64encode(blob).decode("ascii")}
    except Exception:  # noqa: BLE001 — any drawing failure falls through to SVG
        return None


def _svg_provider(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    plan_label = html.escape(str(ctx.get("plan_label") or "Доступ"))
    code = html.escape(str(ctx.get("code") or ""))
    inviter = html.escape(str(ctx.get("inviter") or ""))
    link = html.escape(str(ctx.get("link") or ""))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="525" viewBox="0 0 1000 525">
  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#121a2a"/><stop offset="1" stop-color="#090d14"/></linearGradient></defs>
  <rect width="1000" height="525" fill="url(#g)"/>
  <rect width="1000" height="6" fill="#1fc9ff"/>
  <text x="60" y="86" fill="#f0f4fa" font-family="Segoe UI,Arial,sans-serif" font-size="42" font-weight="700">{html.escape(BRAND_NAME)}</text>
  <text x="62" y="120" fill="#96a5b9" font-family="Segoe UI,Arial,sans-serif" font-size="20">{html.escape(BRAND_TAGLINE)}</text>
  <text x="60" y="216" fill="#ffffff" font-family="Segoe UI,Arial,sans-serif" font-size="46" font-weight="700">Персональное приглашение</text>
  <rect x="60" y="250" width="260" height="46" rx="16" fill="#1a2436" stroke="#7c5cff" stroke-width="2"/>
  <text x="80" y="281" fill="#d2d8f0" font-family="Segoe UI,Arial,sans-serif" font-size="22">{plan_label}</text>
  <rect x="60" y="320" width="580" height="72" rx="14" fill="#141c2a" stroke="#1fc9ff" stroke-width="2"/>
  <text x="80" y="368" fill="#e6f0ff" font-family="Consolas,monospace" font-size="34" font-weight="700">{code}</text>
  {f'<text x="60" y="438" fill="#96a5b9" font-family="Segoe UI,Arial,sans-serif" font-size="22">Пригласил: {inviter}</text>' if inviter else ''}
  {f'<text x="60" y="492" fill="#1fc9ff" font-family="Segoe UI,Arial,sans-serif" font-size="20">{link}</text>' if link else ''}
</svg>"""
    data_url = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {"kind": "svg", "bytes": None, "data_url": data_url}


def _ai_image_provider(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Placeholder for an external AI image generator. Returns None until one is
    configured, so rendering always falls back to the local card. Wire a real
    generator with ``register_image_provider`` (front=True)."""
    return None


_IMAGE_PROVIDERS.extend([_ai_image_provider, _pillow_provider, _svg_provider])


def render_invitation(*, code: str, telegram_link: str = "", web_link: str = "",
                      plan_label: str = "", inviter: str = "") -> Dict[str, Any]:
    """Render a shareable invitation. Returns text, an image data URL for display,
    and (when a raster provider succeeds) PNG bytes for Telegram sendPhoto."""
    link = telegram_link or web_link or ""
    ctx = {"code": code, "link": link, "plan_label": plan_label, "inviter": inviter}
    image: Optional[Dict[str, Any]] = None
    for provider in _IMAGE_PROVIDERS:
        try:
            candidate = provider(ctx)
        except Exception:  # noqa: BLE001
            candidate = None
        if candidate and candidate.get("data_url"):
            image = candidate
            break
    return {
        "text": build_text(code=code, link=link, plan_label=plan_label, inviter=inviter),
        "image_kind": (image or {}).get("kind") or "none",
        "image_data_url": (image or {}).get("data_url") or "",
        "png_bytes": (image or {}).get("bytes"),
        "telegram_link": telegram_link,
        "web_link": web_link,
        "code": code,
    }
