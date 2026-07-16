"""Per-agent head+shoulders crop params verified via circle previews."""
from __future__ import annotations

from pathlib import Path
import json
import imageio.v3 as iio
from PIL import Image, ImageDraw
import numpy as np

ROOT = Path(r"C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer\app\static\aurora\assets\agents")
OUT = ROOT / "_preview"
OUT.mkdir(exist_ok=True)
IDS = ["vitek", "manager", "marina", "tolik", "nikita", "ivan"]
SIZE = 256

# Tuned after visual check of circle previews (shoulders → above hair).
# side_h = square side as fraction of frame height; pad = hairroom above content top.
TUNE = {
    "vitek": {"side_h": 0.40, "pad": 0.10},   # drop pointing hand
    "manager": {"side_h": 0.44, "pad": 0.08},
    "marina": {"side_h": 0.44, "pad": 0.08},
    "tolik": {"side_h": 0.44, "pad": 0.08},
    "nikita": {"side_h": 0.30, "pad": 0.11},  # drop thumbs-up
    "ivan": {"side_h": 0.40, "pad": 0.08},
}


def load_frame(path: Path) -> np.ndarray:
    frame = np.asarray(iio.imread(path, index=0))
    if frame.ndim == 2:
        frame = np.stack([frame] * 3, axis=-1)
    if frame.shape[-1] == 4:
        frame = frame[..., :3]
    return frame.astype(np.uint8)


def content_bbox(arr: np.ndarray, thr: int = 18) -> tuple[int, int, int, int]:
    lum = arr.max(axis=2)
    ys, xs = np.where(lum > thr)
    if len(xs) < 100:
        h, w = arr.shape[:2]
        return 0, 0, w, h
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def head_shoulders_square(aid, x0, y0, x1, y1, w, h) -> tuple[int, int, int, int]:
    tune = TUNE[aid]
    side = int(tune["side_h"] * h)
    pad = int(tune["pad"] * side)
    top = max(0, y0 - pad)
    if top + side > h:
        top = max(0, h - side)
    cx = (x0 + x1) / 2
    left = int(max(0, min(w - side, cx - side / 2)))
    return left, top, left + side, top + side


def css_from_square(sq, w, h) -> dict:
    l, t, r, b = sq
    side = max(1, r - l)
    return {
        "zoom": round(h / side, 3),
        "cx": round(((l + r) / 2) / w * 100, 2),
        "cy": round(((t + b) / 2) / h * 100, 2),
        "square": [int(l), int(t), int(r), int(b)],
        "side": int(side),
    }


def render_circle(arr: np.ndarray, sq) -> Image.Image:
    l, t, r, b = sq
    img = Image.fromarray(arr).crop((l, t, r, b)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
    out = Image.new("RGB", (SIZE, SIZE), (12, 16, 24))
    out.paste(img, mask=mask)
    return out


def main() -> None:
    params = {}
    for aid in IDS:
        arr = load_frame(ROOT / aid / "speaking.webm")
        h, w = arr.shape[:2]
        bbox = content_bbox(arr)
        sq = head_shoulders_square(aid, *bbox, w, h)
        css = css_from_square(sq, w, h)
        css["bbox"] = list(bbox)
        params[aid] = css
        render_circle(arr, sq).save(OUT / f"{aid}_circle.jpg", quality=92)
        print(aid, "sq", sq, "zoom", css["zoom"], "cx", css["cx"], "cy", css["cy"])
    (OUT / "crop_params.json").write_text(json.dumps(params, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
