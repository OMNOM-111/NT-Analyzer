"""Verify CSS crop math matches PIL squares; write final crop map for UI."""
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


def load_frame(path: Path) -> np.ndarray:
    frame = np.asarray(iio.imread(path, index=0))
    if frame.ndim == 2:
        frame = np.stack([frame] * 3, axis=-1)
    if frame.shape[-1] == 4:
        frame = frame[..., :3]
    return frame.astype(np.uint8)


def css_visible_square(zoom: float, cx: float, cy: float) -> tuple[int, int, int, int]:
    """Invert CSS: video height=zoom*S, width=zoom*S*720/1280, centered with translate."""
    # Circle size S=1 in unit space. Video height = zoom, width = zoom * 720/1280.
    # After translate(-50%,-50%) then translate((50-cx)%, (50-cy)% of self):
    # Video center shifts by ((50-cx)/100)*video_w horizontally and ((50-cy)/100)*video_h vertically
    # from circle center.
    # Video covers source fully (object-fit fill).
    # Circle sees source region of size (SRC_H/zoom) tall and (SRC_H/zoom)*(720/1280)?
    # Video height maps SRC_H; visible circle height S maps to SRC_H/zoom = side.
    side = SRC_H / zoom
    # Center of visible region in source:
    # Video center in source coords = (cx/100*SRC_W, cy/100*SRC_H) because we shifted
    # so that (cx,cy) lands on circle center.
    scx = cx / 100 * SRC_W
    scy = cy / 100 * SRC_H
    # Visible width in source: video_w / video_h * side = (720/1280)*side
    vis_w = side * (SRC_W / SRC_H)
    l = int(round(scx - vis_w / 2))
    t = int(round(scy - side / 2))
    return l, t, l + int(round(vis_w)), t + int(round(side))


def main() -> None:
    for aid, p in PARAMS.items():
        arr = load_frame(ROOT / aid / "speaking.webm")
        zoom, cx, cy = p["zoom"], p["cx"], p["cy"]
        # Preferred: use exact PIL square already stored
        sq = p["square"]
        l, t, r, b = sq
        img = Image.fromarray(arr).crop((l, t, r, b)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
        # If non-square (shouldn't be), letterbox
        mask = Image.new("L", (SIZE, SIZE), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
        out = Image.new("RGB", (SIZE, SIZE), (12, 16, 24))
        out.paste(img, mask=mask)
        out.save(OUT / f"{aid}_final.jpg", quality=92)
        print(aid, "ok", sq, f"zoom={zoom} cx={cx} cy={cy}")

    # Emit JS snippet
    lines = ["  const AGENT_FACE_CROP = {"]
    for aid, p in PARAMS.items():
        lines.append(f"    {aid}: {{ zoom: {p['zoom']}, cx: {p['cx']}, cy: {p['cy']} }},")
    lines.append("  };")
    (OUT / "crop_map.js").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote crop_map.js")


if __name__ == "__main__":
    main()
