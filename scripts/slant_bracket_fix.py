"""
Fix troposphere diagram: slant path is SLANT (diagonal along the beam), not vertical.
Uses the high-quality reference PNG: inpaint old vertical brace + text, redraw diagonal
bracket + label.

  py scripts/slant_bracket_fix.py [input.png] [output.png]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    default_in = Path(
        r"C:\Users\aeaturu\.cursor\projects\c-Users-aeaturu-Desktop-WORK-April-2026-eaton\assets\c__Users_aeaturu_AppData_Roaming_Cursor_User_workspaceStorage_8827ef4c954b292c5943e3c1b41dac2b_images_image-8cf7b790-13d0-459c-a8a1-350e0bfeaf37.png"
    )
    in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_in
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "troposphere_diagram.png"

    if not in_path.is_file():
        print("Input not found:", in_path, file=sys.stderr)
        sys.exit(1)

    img = Image.open(in_path).convert("RGB")
    arr = np.array(img)
    h, w = arr.shape[:2]

    # Remove old vertical brace + left label: smooth fill from sky strip (avoids single-column banding)
    x0, x1 = 72, min(310, w - 1)
    ref_lo, ref_hi = min(315, w - 6), min(335, w - 1)
    ref = arr[:, ref_lo:ref_hi].mean(axis=1).astype(np.uint8)
    for x in range(x0, x1):
        arr[:, x] = ref

    out = Image.fromarray(arr)
    draw = ImageDraw.Draw(out)

    # Diagonal bracket parallel to the slant beam (slant = along line of sight, not vertical)
    # Endpoints follow the beam from upper-left toward lower-right (~1024x571 reference)
    x_top, y_top = 208, 98
    x_bot, y_bot = 488, 452
    dx, dy = x_bot - x_top, y_bot - y_top
    ln = math.hypot(dx, dy)
    ux, uy = dx / ln, dy / ln
    px, py = -uy, ux
    off = 9.0

    def parallel_line(o: float) -> tuple[tuple[int, int], tuple[int, int]]:
        ox, oy = px * o, py * o
        return (
            (int(x_top + ox), int(y_top + oy)),
            (int(x_bot + ox), int(y_bot + oy)),
        )

    p1a, p1b = parallel_line(-off)
    p2a, p2b = parallel_line(off)
    lw = max(2, w // 400)
    draw.line([p1a, p1b], fill=(25, 25, 28), width=lw)
    draw.line([p2a, p2b], fill=(25, 25, 28), width=lw)
    # End caps (short perpendicular ticks)
    for pa, pb in ((p1a, p1b), (p2a, p2b)):
        mx = (pa[0] + pb[0]) // 2
        my = (pa[1] + pb[1]) // 2
        # small caps at top and bottom along the pair
    # Top caps
    ca = 7
    mid_top_x = int((p1a[0] + p2a[0]) / 2)
    mid_top_y = int((p1a[1] + p2a[1]) / 2)
    mid_bot_x = int((p1b[0] + p2b[0]) / 2)
    mid_bot_y = int((p1b[1] + p2b[1]) / 2)
    draw.line(
        [
            (mid_top_x - int(px * ca), mid_top_y - int(py * ca)),
            (mid_top_x + int(px * ca), mid_top_y + int(py * ca)),
        ],
        fill=(25, 25, 28),
        width=lw,
    )
    draw.line(
        [
            (mid_bot_x - int(px * ca), mid_bot_y - int(py * ca)),
            (mid_bot_x + int(px * ca), mid_bot_y + int(py * ca)),
        ],
        fill=(25, 25, 28),
        width=lw,
    )

    f = _font(max(15, w // 58))
    lines = ["Slant path", "(what the instrument senses)"]
    tx, ty = 78, min(508, h - 58)
    for i, line in enumerate(lines):
        for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            draw.text((tx + ox, ty + i * 22 + oy), line, fill=(255, 255, 255), font=f)
        draw.text((tx, ty + i * 22), line, fill=(18, 20, 26), font=f)

    out.save(out_path, "PNG", optimize=True)
    print("Wrote", out_path.resolve())


if __name__ == "__main__":
    main()
