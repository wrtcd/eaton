"""
High-quality troposphere schematic (supersampled raster, smooth gradients).

  py scripts/build_troposphere_diagram.py [output.png]

Default: troposphere_diagram.png at 1920x920 (good for slides).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = (
        (r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeui.ttf")
        if bold
        else (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf")
    )
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _lerp_rgb(t: float, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return a + (b - a) * t


def _text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    if hasattr(draw, "textlength"):
        return float(draw.textlength(text, font=font))
    bbox = draw.textbbox((0, 0), text, font=font)
    return float(bbox[2] - bbox[0])


def _draw_text_shadow(
    draw: ImageDraw.ImageDraw,
    pos: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    shadow: tuple[int, int, int, int] = (255, 255, 255, 180),
    off: tuple[int, int] = (1, 1),
) -> None:
    x, y = pos
    ox, oy = off
    draw.text((x + ox, y + oy), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def _sky_gradient(h: int, w: int) -> np.ndarray:
    """Soft vertical sky + very subtle horizontal vignette."""
    top = np.array([118, 168, 228], dtype=np.float32)
    mid = np.array([168, 208, 238], dtype=np.float32)
    bot = np.array([210, 228, 248], dtype=np.float32)
    col = np.zeros((h, 3), dtype=np.float32)
    for i in range(h):
        t = i / max(h - 1, 1)
        if t < 0.55:
            col[i] = _lerp_rgb(t / 0.55, top, mid)
        else:
            col[i] = _lerp_rgb((t - 0.55) / 0.45, mid, bot)
    a = np.repeat(col[:, None, :], w, axis=1)
    xg = np.linspace(-1, 1, w, dtype=np.float32)[None, :, None]
    vignette = 1.0 - 0.06 * (xg**2)
    return np.clip(a * vignette, 0, 255).astype(np.uint8)


def _ground_and_hills(rgb: np.ndarray, h: int, w: int, y0: int) -> None:
    """Paint earth strip + soft layered hills (vectorized blend)."""
    hh, ww = rgb.shape[:2]
    ys = np.arange(hh, dtype=np.float32)[:, None]
    xs = np.arange(ww, dtype=np.float32)[None, :]

    # Base soil
    soil = np.array([92, 118, 72], dtype=np.float32)
    rgb[np.arange(hh) >= y0, :] = soil.astype(np.uint8)

    # Hill 1: smooth bump
    peak_x, peak_y, sigma_x, sigma_y = w * 0.35, y0 - 25, w * 0.45, 120.0
    g1 = np.exp(-(((xs - peak_x) / sigma_x) ** 2 + ((ys - peak_y) / sigma_y) ** 2))
    col1 = np.array([78, 142, 88], dtype=np.float32)
    mask1 = (ys >= y0 - 5) & (g1 > 0.02)
    for c in range(3):
        plane = rgb[:, :, c].astype(np.float32)
        plane[mask1] = plane[mask1] * (1 - g1[mask1] * 0.92) + col1[c] * (g1[mask1] * 0.92)
        rgb[:, :, c] = np.clip(plane, 0, 255).astype(np.uint8)

    # Hill 2
    peak_x2, peak_y2 = w * 0.72, y0 - 18
    g2 = np.exp(-(((xs - peak_x2) / (w * 0.38)) ** 2 + ((ys - peak_y2) / 100.0) ** 2))
    col2 = np.array([62, 128, 72], dtype=np.float32)
    mask2 = (ys >= y0 - 8) & (g2 > 0.02)
    for c in range(3):
        plane = rgb[:, :, c].astype(np.float32)
        plane[mask2] = plane[mask2] * (1 - g2[mask2] * 0.88) + col2[c] * (g2[mask2] * 0.88)
        rgb[:, :, c] = np.clip(plane, 0, 255).astype(np.uint8)


def _trees(img: Image.Image, y0: int, w: int, rng: np.random.Generator) -> None:
    draw = ImageDraw.Draw(img, "RGBA")
    n = 14
    xs = np.linspace(w * 0.06, w * 0.94, n) + rng.normal(0, w * 0.012, n)
    for tx in xs:
        tx = int(np.clip(tx, 20, w - 20))
        ty = int(y0 + 6 + rng.integers(-4, 10))
        trunk = (48, 78, 42, 255)
        crown = (58, 118, 68, 245)
        draw.rounded_rectangle((tx - 3, ty - 22, tx + 3, ty + 4), radius=2, fill=trunk)
        draw.ellipse((tx - 14, ty - 48, tx + 14, ty - 18), fill=crown)


def _tropopause_fill(
    rgba: np.ndarray,
    box_l: int,
    box_r: int,
    box_t: int,
    box_b: int,
) -> None:
    """Soft vertical gradient inside troposphere with mild edge darkening."""
    h, w = rgba.shape[:2]
    yy = np.arange(h, dtype=np.float32)[:, None]
    xx = np.arange(w, dtype=np.float32)[None, :]
    inside = (xx >= box_l) & (xx <= box_r) & (yy >= box_t) & (yy <= box_b)
    Y = np.broadcast_to(np.arange(h, dtype=np.float32)[:, None], (h, w))
    t = np.clip((Y - box_t) / max(box_b - box_t, 1), 0, 1)
    top_c = np.array([168, 212, 242], dtype=np.float32)
    bot_c = np.array([255, 252, 238], dtype=np.float32)
    col = top_c[None, None, :] + (bot_c - top_c)[None, None, :] * t[:, :, None]
    cx = (box_l + box_r) / 2
    half = (box_r - box_l) / 2
    XX = np.broadcast_to(np.arange(w, dtype=np.float32)[None, :], (h, w))
    edge = 1.0 - 0.14 * np.abs(XX - cx) / max(half, 1.0)
    edge = np.clip(edge, 0.86, 1.0)
    for c in range(3):
        plane = rgba[:, :, c].astype(np.float32)
        ch = col[:, :, c]
        plane[inside] = ch[inside] * edge[inside]
        rgba[:, :, c] = np.clip(plane, 0, 255)
    alpha = rgba[:, :, 3].astype(np.float32)
    alpha[inside] = np.maximum(alpha[inside], 245)
    rgba[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)


def draw_column_high_quality(
    w: int,
    h: int,
    cx: float,
    y_top: float,
    y_bottom: float,
    rx: float,
    ry_cap: float,
) -> np.ndarray:
    """Per-pixel shaded cylinder: aloft (blue) to surface (amber), 3D-ish lighting."""
    layer = np.zeros((h, w, 4), dtype=np.float32)
    Y = np.broadcast_to(np.arange(h, dtype=np.float32)[:, None], (h, w))
    X = np.broadcast_to(np.arange(w, dtype=np.float32)[None, :], (h, w))
    height = max(y_bottom - y_top, 1.0)
    t_vert = np.clip((Y - y_top) / height, 0, 1)
    aloft = np.array([108, 176, 228], dtype=np.float32)
    surf = np.array([255, 198, 92], dtype=np.float32)
    core = aloft[None, None, :] + (surf - aloft)[None, None, :] * t_vert[:, :, None]

    nx = (X - cx) / max(rx * 0.92, 1e-6)
    inside_body = (Y >= y_top) & (Y <= y_bottom) & (np.abs(nx) <= 1.0)
    light = 0.55 + 0.45 * np.sqrt(np.clip(1.0 - nx**2, 0, 1))
    rgb = core * light[:, :, None]

    for cap_y in (y_top, y_bottom):
        dy = (Y - cap_y) / max(ry_cap, 1.0)
        cap_mask = (np.abs(dy) <= 1.0) & (np.abs(nx) <= 1.0) & (np.abs(Y - cap_y) <= ry_cap + 1)
        cap_rgb = np.array([198, 176, 138], dtype=np.float32)
        a_cap = np.clip(1.0 - np.abs(dy), 0, 1) * 0.35
        for c in range(3):
            rgb[:, :, c] = np.where(
                cap_mask,
                rgb[:, :, c] * (1 - a_cap) + cap_rgb[c] * a_cap,
                rgb[:, :, c],
            )

    alpha = np.zeros((h, w), dtype=np.float32)
    alpha[inside_body] = 230 * np.sqrt(np.clip(1.0 - nx[inside_body] ** 2, 0, 1))

    shell_l = (X < cx - rx * 0.15) & inside_body
    shell_r = (X > cx + rx * 0.15) & inside_body
    tan = np.array([188, 158, 118], dtype=np.float32)
    for sm in (shell_l, shell_r):
        rgb = np.where(sm[:, :, None], rgb * 0.7 + tan * 0.3, rgb)

    layer[:, :, :3] = np.clip(rgb, 0, 255)
    layer[:, :, 3] = np.clip(alpha, 0, 255)
    return layer.astype(np.uint8)


def _smoke_plume(w: int, h: int, cx: int, base_y: int) -> np.ndarray:
    """Soft gaussian blobs, additive grey."""
    layer = np.zeros((h, w, 4), dtype=np.float32)
    yy = np.arange(h, dtype=np.float32)[:, None]
    xx = np.arange(w, dtype=np.float32)[None, :]
    blobs = [
        (cx, base_y - 40, 58, 40, 0.18),
        (cx + 38, base_y - 88, 52, 44, 0.15),
        (cx - 30, base_y - 118, 46, 52, 0.13),
        (cx + 12, base_y - 168, 56, 48, 0.11),
    ]
    for bx, by, sx, sy, peak in blobs:
        g = np.exp(-0.5 * (((xx - bx) / sx) ** 2 + ((yy - by) / sy) ** 2))
        a = g * peak * 255
        layer[:, :, 0] += a * 0.55
        layer[:, :, 1] += a * 0.56
        layer[:, :, 2] += a * 0.58
        layer[:, :, 3] = np.maximum(layer[:, :, 3], a)
    return np.clip(layer, 0, 255).astype(np.uint8)


def _fire_glow(w: int, h: int, cx: int, base_y: int) -> np.ndarray:
    layer = np.zeros((h, w, 4), dtype=np.float32)
    yy = np.arange(h, dtype=np.float32)[:, None]
    xx = np.arange(w, dtype=np.float32)[None, :]
    # Triangle-ish fire core + radial bloom
    tri = (yy >= base_y) & (yy <= base_y + 38) & (np.abs(xx - cx) <= (yy - base_y) * 0.55 + 1)
    hot = np.array([255, 120, 45], dtype=np.float32)
    warm = np.array([255, 210, 80], dtype=np.float32)
    d = np.sqrt((xx - cx) ** 2 + (yy - (base_y + 8)) ** 2)
    bloom = np.exp(-(d**2) / (28.0**2)) * 180
    for c in range(3):
        layer[:, :, c] = np.where(tri, hot[c], 0)
        layer[:, :, c] += bloom * (warm[c] / 255.0)
    layer[:, :, 3] = np.clip(np.where(tri, 245.0, bloom), 0, 255)
    # Inner yellow tip
    tip = (yy >= base_y) & (yy <= base_y + 22) & (np.abs(xx - cx) < 14)
    layer[:, :, 0] = np.where(tip, np.maximum(layer[:, :, 0], 255), layer[:, :, 0])
    layer[:, :, 1] = np.where(tip, np.maximum(layer[:, :, 1], 230), layer[:, :, 1])
    return np.clip(layer, 0, 255).astype(np.uint8)


def _beam_layer(w: int, h: int, pts: list[tuple[float, float]]) -> np.ndarray:
    """Soft slant beam: filled polygon + blur."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.polygon(pts, fill=(130, 195, 245, 45))
    return np.array(layer)


def build_diagram(w: int = 1920, h: int = 920) -> Image.Image:
    rng = np.random.default_rng(42)
    rgb = _sky_gradient(h, w)
    y0 = int(h * 0.815)
    _ground_and_hills(rgb, h, w, y0)

    img = Image.fromarray(rgb, mode="RGB").convert("RGBA")
    _trees(img, y0, w, rng)

    box_l, box_r = int(w * 0.035), int(w * 0.965)
    box_t, box_b = int(h * 0.11), int(h * 0.755)
    cx = (box_l + box_r) // 2
    rr = int(min(w, h) * 0.018)

    arr = np.array(img)
    _tropopause_fill(arr, box_l, box_r, box_t, box_b)
    img = Image.fromarray(arr, mode="RGBA")

    # Soft outer shadow for box (draw blurred dark rounded rect behind)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (box_l + 4, box_t + 5, box_r + 4, box_b + 5),
        radius=rr,
        fill=(20, 35, 55, 55),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=6))
    img = Image.alpha_composite(Image.alpha_composite(Image.new("RGBA", (w, h), (0, 0, 0, 0)), shadow), img)

    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (box_l, box_t, box_r, box_b),
        radius=rr,
        outline=(38, 48, 62, 255),
        width=max(2, w // 500),
    )

    # Clouds (softer)
    for cx_cl, cy, rw in [(box_l + 160, box_t + 52, int(w * 0.055)), (cx - 20, box_t + 68, int(w * 0.048)), (box_r - 170, box_t + 55, int(w * 0.052))]:
        for dx, dy, sc in [(0, 0, 1.0), (-rw * 0.65, 8, 0.85), (rw * 0.5, 6, 0.9)]:
            draw.ellipse(
                (cx_cl + dx - rw * sc, cy + dy - 20, cx_cl + dx + rw * sc, cy + dy + 22),
                fill=(255, 255, 255, 228),
            )

    sat_x, sat_y = int(w * 0.048), int(h * 0.048)
    draw.rounded_rectangle((sat_x, sat_y, sat_x + 32, sat_y + 14), radius=3, fill=(148, 152, 162, 255), outline=(88, 92, 102, 255))
    draw.rounded_rectangle((sat_x - 22, sat_y - 1, sat_x - 3, sat_y + 15), radius=2, fill=(62, 118, 198, 255))
    draw.rounded_rectangle((sat_x + 32, sat_y - 1, sat_x + 50, sat_y + 15), radius=2, fill=(62, 118, 198, 255))

    gx = int(w * 0.36)
    beam = _beam_layer(
        w,
        h,
        [
            (sat_x + 16, sat_y + 24),
            (gx - 10, y0 - 5),
            (gx + 62, y0 + 22),
            (sat_x + 10, sat_y + 42),
        ],
    )
    beam_img = Image.fromarray(beam, mode="RGBA").filter(ImageFilter.GaussianBlur(radius=2))
    img = Image.alpha_composite(img, beam_img)

    y_top = float(box_t + 22)
    y_bot = float(box_b - 26)
    rx = float(min(0.11 * w, (box_r - box_l) * 0.22))
    ry_cap = max(8.0, rx * 0.16)
    col_arr = draw_column_high_quality(w, h, float(cx), y_top, y_bot, rx, ry_cap)
    col_img = Image.fromarray(col_arr, mode="RGBA")
    cd = ImageDraw.Draw(col_img)
    xl, xr = int(cx - rx), int(cx + rx)
    cd.line([(xl, int(y_top)), (xl, int(y_bot))], fill=(95, 78, 58, 200), width=max(2, w // 640))
    cd.line([(xr, int(y_top)), (xr, int(y_bot))], fill=(230, 218, 195, 140), width=max(1, w // 800))
    img = Image.alpha_composite(img, col_img)

    fire_y = box_b - 4
    fire_arr = _fire_glow(w, h, cx, fire_y)
    smoke_arr = _smoke_plume(w, h, cx, fire_y)
    img = Image.alpha_composite(img, Image.fromarray(fire_arr, mode="RGBA"))
    img = Image.alpha_composite(img, Image.fromarray(smoke_arr, mode="RGBA"))

    draw = ImageDraw.Draw(img)
    f_title = _font(max(26, w // 55), bold=True)
    f_sub = _font(max(15, w // 95))
    title = "Troposphere"
    tw = _text_w(draw, title, f_title)
    _draw_text_shadow(draw, (cx - tw / 2, box_t + 8), title, f_title, (28, 38, 52, 255))
    sub = "Slant path (instrument)"
    _draw_text_shadow(draw, (box_l + 16, box_t + 44), sub, f_sub, (32, 52, 82, 255))

    return img.convert("RGB")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "troposphere_diagram.png"
    # High-res render then downscale for smooth edges (anti-alias)
    scale = 1.5
    w, h = int(1920 * scale), int(920 * scale)
    img = build_diagram(w, h)
    img = img.resize((1920, 920), Image.Resampling.LANCZOS)
    img.save(out, "PNG", optimize=True)
    print("Wrote", out.resolve())


if __name__ == "__main__":
    main()
