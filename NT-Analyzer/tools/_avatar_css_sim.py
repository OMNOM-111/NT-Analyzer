"""Render what the CSS transform will show; must match *_final.jpg."""
from __future__ import annotations

from pathlib import Path
import json
import imageio.v3 as iio
from PIL import Image, ImageDraw
import numpy as np

ROOT = Path(r"C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer\app\static\aurora\assets\agents")
OUT = ROOT / "_preview"
PARAMS = json.loads((OUT / "crop_params.json").read_text(encoding="utf-8"))
SIZE = 256
SRC_W, SRC_H = 720, 1280


def load_frame(path: Path) -> Image.Image:
    frame = np.asarray(iio.imread(path, index=0))
    if frame.ndim == 2:
        frame = np.stack([frame] * 3, axis=-1)
    if frame.shape[-1] == 4:
        frame = frame[..., :3]
    return Image.fromarray(frame.astype("uint8"))


def render_css(aid: str, img: Image.Image, zoom: float, cx: float, cy: float) -> Image.Image:
    # video element size in circle pixels
    vh = zoom * SIZE
    vw = zoom * SIZE * (SRC_W / SRC_H)
    video = img.resize((int(round(vw)), int(round(vh))), Image.Resampling.LANCZOS)
    # circle canvas
    canvas = Image.new("RGB", (SIZE, SIZE), (12, 16, 24))
    # video center after transforms:
    # start at circle center, then + ((50-cx)% of video_w, (50-cy)% of video_h)
    shift_x = ((50 - cx) / 100.0) * vw
    shift_y = ((50 - cy) / 100.0) * vh
    # top-left of video on canvas
    left = SIZE / 2 + shift_x - vw / 2
    top = SIZE / 2 + shift_y - vh / 2
    canvas.paste(video, (int(round(left)), int(round(top))))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
    out = Image.new("RGB", (SIZE, SIZE), (12, 16, 24))
    out.paste(canvas, mask=mask)
    return out


def main() -> None:
    for aid, p in PARAMS.items():
        img = load_frame(ROOT / aid / "speaking.webm")
        out = render_css(aid, img, p["zoom"], p["cx"], p["cy"])
        out.save(OUT / f"{aid}_css.jpg", quality=92)
        print("css", aid)


if __name__ == "__main__":
    main()
