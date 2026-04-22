"""
Plume-mass map (WGS 84) + two zooms: max vs min-positive cell.
Geographic aspect 1/cos(lat); nearest resampling preserves per-cell colormap.

Step-07 raster ``tempo_delta_vcd_plume.tif`` holds ΔVCD_plume = f_p·ΔVCD (not bare ΔVCD).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import ConnectionPatch, FancyArrow
from rasterio.crs import CRS
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import Window, transform as window_transform

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MASS = _ROOT / "step-by-step" / "08 mass" / "tempo_mass_no2_kg_per_pixel.tif"
_DEFAULT_DVCD = _ROOT / "step-by-step" / "07 plume delta" / "tempo_delta_vcd_plume.tif"
_OUT = _ROOT / "step-by-step" / "presentations" / "max_mass_pixel_inset.png"
NODATA = -1.0e30
DST = CRS.from_epsg(4326)
N_A = 6.02214076e23
M_NO2 = 46.0055e-3

_FIG_BG = "#ffffff"
_PANEL_BG = "#ffffff"
_MPL_RC = {
    "figure.facecolor": _FIG_BG,
    "savefig.facecolor": _FIG_BG,
    "axes.edgecolor": "0.25",
    "axes.labelcolor": "0.15",
    "text.color": "0.1",
    "xtick.color": "0.2",
    "ytick.color": "0.2",
    "font.size": 10,
}


def _set_geo_aspect(ax, center_lat_rad: float) -> None:
    ax.set_aspect(1.0 / max(0.2, math.cos(center_lat_rad)), adjustable="box")


def _reprojected_cell_centers(
    sub: np.ndarray, ebox: tuple[float, float, float, float], target: float, *, is_max: bool
) -> tuple[float, float]:
    """Geometric center of the blob matching target mass (nearest-reprojected pixels)."""
    eL, eR, eB, eT = ebox
    h, w0 = int(sub.shape[0]), int(sub.shape[1])
    fin = np.isfinite(sub)
    if is_max:
        m = fin & (sub >= (target * (1.0 - 1e-6) - 1e-9))
    else:
        m = fin & (np.abs(sub - target) < max(1e-6 * (abs(target) + 0.1), 1e-5))
    if not np.any(m):
        tval = float(np.nanmax(sub)) if is_max else float(np.nanmin(sub[fin]))
        m = fin & (sub == tval) if is_max or np.isfinite(tval) else fin
    jj, ii = np.where(m)
    jf = float(np.mean(jj)) if len(jj) else (h - 1) * 0.5
    i_f = float(np.mean(ii)) if len(ii) else (w0 - 1) * 0.5
    x_c = eL + (i_f + 0.5) * (eR - eL) / w0
    y_c = eT - (jf + 0.5) * (eT - eB) / h
    return x_c, y_c


def _tighten_extent(
    data: np.ndarray, ext: tuple[float, float, float, float], margin: float = 0.04
) -> tuple[float, float, float, float] | None:
    """Tighter lon/lat limits around finite positive data (reduces empty margin on overview)."""
    L, R, B, T = ext
    if np.ma.is_masked(data):
        z = np.ma.filled(data.astype(float), np.nan)
    else:
        z = np.asarray(data, dtype=float)
    if z.ndim != 2:
        return None
    h, w0 = int(z.shape[0]), int(z.shape[1])
    ok = np.isfinite(z) & (z > 0) & (z < 1e30)
    if not np.any(ok):
        return None
    jj, ii = np.where(ok)
    j0, j1 = int(jj.min()), int(jj.max()) + 1
    i0, i1 = int(ii.min()), int(ii.max()) + 1
    x0 = L + i0 * (R - L) / w0
    x1 = L + i1 * (R - L) / w0
    y0 = T - j1 * (T - B) / h
    y1 = T - j0 * (T - B) / h
    dx, dy = x1 - x0, y1 - y0
    m = margin
    return x0 - m * dx, x1 + m * dx, y0 - m * dy, y1 + m * dy


def _add_scalebar_km(
    ax,
    *,
    lat_mid_deg: float,
    km: int,
    where: str = "ll",
    color: str = "0.2",
    lw: float = 2.2,
    text_font: int = 8,
) -> None:
    m_per_deg_lon = 111_320.0 * max(0.2, math.cos(math.radians(lat_mid_deg)))
    w_deg = (km * 1000.0) / m_per_deg_lon
    xlo, xhi = ax.get_xlim()
    ylo, yhi = ax.get_ylim()
    padx = 0.035 * (xhi - xlo)
    pady = 0.035 * (yhi - ylo)
    if where == "ll":
        x0 = xlo + padx
        y0 = ylo + pady
    else:
        x0 = xhi - padx - w_deg
        y0 = ylo + pady
    ax.plot(
        [x0, x0 + w_deg], [y0, y0], color=color, lw=lw, zorder=30,
        solid_capstyle="projecting", clip_on=True,
    )
    y_txt = y0 + 0.012 * (yhi - ylo)
    ax.text(
        x0 + 0.5 * w_deg, y_txt, f"{km} km",
        ha="center", va="bottom", fontsize=text_font, color=color, fontweight="600", zorder=30,
    )


def _add_north_arrow_top_left(ax, color: str = "0.2") -> None:
    # transAxes: small patch in the upper-left of the main map only
    ax_n = ax.inset_axes(
        (0.04, 0.78, 0.1, 0.14),
        transform=ax.transAxes,
        facecolor="white",
        alpha=0.92,
    )
    ax_n.set_xlim(0, 1)
    ax_n.set_ylim(0, 1)
    for s in (ax_n.spines.values()):
        s.set_visible(False)
    ax_n.set_xticks([])
    ax_n.set_yticks([])
    arr = FancyArrow(
        0.5, 0.1, 0, 0.7, width=0.12, head_width=0.35, head_length=0.25,
        color=color, length_includes_head=True, zorder=3,
    )
    ax_n.add_patch(arr)
    ax_n.text(0.5, 0.9, "N", ha="center", va="bottom", color=color, fontsize=12, fontweight="700")
    ax_n.set_zorder(25)


def _sub_to_4326(
    sub: np.ndarray, win: Window, full_t, src_crs
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    t_sub = window_transform(win, full_t)
    h, w0 = int(sub.shape[0]), int(sub.shape[1])
    l, b, r, t0 = array_bounds(h, w0, t_sub)
    dst_t, dw, dh = calculate_default_transform(src_crs, DST, w0, h, l, b, r, t0)
    out = np.empty((dh, dw), np.float32)
    reproject(
        source=sub.astype(np.float32),
        destination=out,
        src_transform=t_sub,
        src_crs=src_crs,
        dst_transform=dst_t,
        dst_crs=DST,
        resampling=Resampling.nearest,
    )
    L, B, R, T = array_bounds(dh, dw, dst_t)
    return out, (L, R, B, T)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mass", type=Path, default=_DEFAULT_MASS)
    ap.add_argument("--pad", type=int, default=3, help="Source cells on each side of mark (tighter = more zoom).")
    ap.add_argument("--out", type=Path, default=_OUT)
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args()

    if not args.mass.is_file():
        print("ERROR:", args.mass, file=sys.stderr)
        return 1

    with plt.rc_context(_MPL_RC):
        with rasterio.open(args.mass) as ds:
            z = ds.read(1).astype(np.float64)
            nod = ds.nodata
            t = ds.transform
            src_crs = ds.crs
            w0, h0 = ds.width, ds.height
            bleft, bbottom, bright, btop = ds.bounds
            h, w = int(z.shape[0]), int(z.shape[1])

        ok = np.isfinite(z) & (z > -1e20)
        if nod is not None and np.isfinite(nod):
            ok &= z != nod
        ok &= z != NODATA
        ok &= z > 0
        if not np.any(ok):
            print("No positive mass", file=sys.stderr)
            return 1

        r, c = divmod(int(np.nanargmax(np.where(ok, z, np.nan))), w)
        mmax = float(z[r, c])
        rmin, cmin = divmod(int(np.argmin(np.where(ok, z, np.inf))), w)
        mmin = float(z[rmin, cmin])

        sig_max = sig_min = None
        if _DEFAULT_DVCD.is_file():
            with rasterio.open(_DEFAULT_DVCD) as d2:
                dvv = d2.read(1)
            if dvv.shape == z.shape:
                if np.isfinite(dvv[r, c]):
                    sig_max = float(dvv[r, c])
                if np.isfinite(dvv[rmin, cmin]):
                    sig_min = float(dvv[rmin, cmin])

        a_m2 = abs(t.a * t.e - t.b * t.d)
        a_cm2 = a_m2 * 1.0e4

        def mass_from_sigma(s: float | None) -> float | None:
            return (s * a_cm2 / N_A * M_NO2) if s is not None else None

        with rasterio.open(args.mass) as ds:
            w0, h0 = ds.width, ds.height
            dst_t, dw, dh = calculate_default_transform(
                src_crs, DST, w0, h0, bleft, bbottom, bright, btop
            )
            dst = np.empty((dh, dw), np.float32)
            reproject(
                source=rasterio.band(ds, 1),
                destination=dst,
                src_transform=ds.transform,
                src_crs=src_crs,
                dst_transform=dst_t,
                dst_crs=DST,
                resampling=Resampling.nearest,
            )
        L, B, R, T = array_bounds(dh, dw, dst_t)
        ext = (L, R, B, T)
        zplot = np.ma.masked_invalid(np.where((dst > 0) & (dst < 1e30), dst, np.nan))
        ext_tight = _tighten_extent(np.asarray(zplot), ext, margin=0.04)
        vmax = max(1.0, min(900.0, mmax * 1.02))
        lat0 = np.radians(0.5 * (B + T))
        lat0_deg = float(0.5 * (B + T))

        dst_f = np.asarray(dst, dtype=np.float64)
        ov_lon1, ov_lat1 = _reprojected_cell_centers(dst_f, ext, mmax, is_max=True)
        ov_lon2, ov_lat2 = _reprojected_cell_centers(dst_f, ext, mmin, is_max=False)

        pad = max(1, args.pad)
        w_max = Window(
            max(0, c - pad), max(0, r - pad),
            min(w, c + pad + 1) - max(0, c - pad), min(h, r + pad + 1) - max(0, r - pad),
        )
        w_min = Window(
            max(0, cmin - pad), max(0, rmin - pad),
            min(w, cmin + pad + 1) - max(0, cmin - pad), min(h, rmin + pad + 1) - max(0, rmin - pad),
        )
        with rasterio.open(args.mass) as ds:
            s_max = np.asarray(ds.read(1, window=w_max, masked=True).data, dtype=float)
            s_min = np.asarray(ds.read(1, window=w_min, masked=True).data, dtype=float)
        sub_max, e_max = _sub_to_4326(s_max, w_max, t, src_crs)
        sub_min, e_min = _sub_to_4326(s_min, w_min, t, src_crs)
        x_max, y_max = _reprojected_cell_centers(sub_max, e_max, mmax, is_max=True)
        x_min, y_min = _reprojected_cell_centers(sub_min, e_min, mmin, is_max=False)

        # Left: overview; right: MAX (top) and MIN+ (bottom), extra row spacing so no overlap
        fig = plt.figure(figsize=(14.0, 9.0), dpi=100)
        fig.patch.set_facecolor(_FIG_BG)
        gs = fig.add_gridspec(
            3, 2,
            height_ratios=[0.09, 1.0, 1.0],
            width_ratios=[1.05, 0.88],
            wspace=0.14,
            hspace=0.32,
        )
        ax_t = fig.add_subplot(gs[0, :])
        ax_t.axis("off")
        ax_t.set_facecolor(_FIG_BG)
        ax_t.text(
            0.5, 0.52,
            r"TEMPO plume mass ($\mathregular{kg\ NO_2\ per\ cell}$) — WGS 84",
            ha="center", va="center", fontsize=15, fontweight="600", color="0.12",
        )
        ax_t.text(
            0.5, 0.12,
            r"Column in step 07 is the plume product:  $\Delta\mathrm{VCD}_{\mathrm{plume}} = f_p\,\Delta\mathrm{VCD}$  "
            r"(molec·cm$^{-2}$).",
            ha="center", va="center", fontsize=9, color="0.35",
        )

        ax0 = fig.add_subplot(gs[1:3, 0])
        ax0.set_facecolor(_PANEL_BG)
        im = ax0.imshow(
            zplot,
            extent=ext,
            origin="upper",
            cmap="magma",
            vmin=0,
            vmax=vmax,
            interpolation="nearest",
        )
        if ext_tight is not None:
            tL, tR, tB, tT = ext_tight
            ax0.set_xlim(tL, tR)
            ax0.set_ylim(tB, tT)
        for lon, la, col, ms, mew in (
            (ov_lon1, ov_lat1, "deepskyblue", 18, 2.0),
            (ov_lon2, ov_lat2, "chartreuse", 16, 1.8),
        ):
            ax0.plot(
                lon, la, "+", color=col, ms=ms, mew=mew, zorder=6,
            )
            ax0.plot(
                lon, la, "+", color="0.1", ms=ms + 1, mew=mew + 0.4, zorder=5, alpha=0.35,
            )
        _set_geo_aspect(ax0, lat0)
        ax0.set_xlabel(r"Longitude ($^\circ$)", color="0.2", fontsize=12)
        ax0.set_ylabel(r"Latitude ($^\circ$)", color="0.2", fontsize=12)
        ax0.tick_params(labelsize=14, colors="0.25")
        cb = fig.colorbar(
            im, ax=ax0, shrink=0.88, pad=0.02, aspect=28,
        )
        cb.set_label(
            r"$\mathrm{kg\ NO_2\ cell^{-1}}$",
            fontsize=14, color="0.2", labelpad=12,
        )
        cb.ax.yaxis.set_tick_params(colors="0.25", labelsize=14, width=0.6, length=5)
        cb.outline.set_edgecolor("0.4")
        _add_scalebar_km(ax0, lat_mid_deg=lat0_deg, km=30, where="ll", color="0.2", text_font=10)
        _add_north_arrow_top_left(ax0, color="0.2")
        ax0.set_title("Overview", color="0.4", fontsize=10, loc="right", fontweight="500", pad=2)

        panels = (
            (
                sub_max, e_max, mmax, sig_max, x_max, y_max, "deepskyblue",
                r"MAX (largest $m$)", mass_from_sigma(sig_max), True, ov_lon1, ov_lat1,
            ),
            (
                sub_min, e_min, mmin, sig_min, x_min, y_min, "yellowgreen",
                r"MIN$_{+}$ (weakest $m$ $>$ 0)", mass_from_sigma(sig_min), False, ov_lon2, ov_lat2,
            ),
        )
        ax_max = fig.add_subplot(gs[1, 1])
        ax_min = fig.add_subplot(gs[2, 1])
        axes_inset = (ax_max, ax_min)
        for j, (
            sub, ebox, mkg, s_sig, xcr, ycr, col, short_title, mcheck, _is_max, plon, pla
        ) in enumerate(panels):
            axi = axes_inset[j]
            eL, eR, eB, eT = ebox
            e_lat = np.radians(0.5 * (eB + eT))
            e_lat_deg = float(0.5 * (eB + eT))
            axi.set_facecolor(_PANEL_BG)
            axi.imshow(
                np.ma.masked_invalid(sub),
                extent=(eL, eR, eB, eT),
                origin="upper",
                cmap="magma",
                vmin=0,
                vmax=vmax,
                interpolation="nearest",
            )
            axi.plot(xcr, ycr, "+", color=col, ms=20, mew=2.6, zorder=6)
            axi.plot(xcr, ycr, "+", color="0.05", ms=22, mew=3.2, zorder=5, alpha=0.4)
            _set_geo_aspect(axi, e_lat)
            axi.set_xlabel(r"Longitude ($^\circ$)", fontsize=9, color="0.2", labelpad=2)
            axi.set_ylabel(r"Latitude ($^\circ$)", fontsize=9, color="0.2", labelpad=0)
            axi.set_title(short_title, fontsize=10, fontweight="600", color="0.1", pad=4)
            axi.tick_params(labelsize=11, labelcolor="0.25", width=0.5, length=3)
            s_str = f"{s_sig/1e16:.3f}" if s_sig is not None else "—"
            mchk = f"{mcheck:.1f}" if mcheck is not None else "—"
            # Readable block: plume column value, mass, one A line, compact check (no N_A, M list).
            box_txt = (
                r"$\Delta\mathrm{VCD}_{\mathrm{plume}} = " + s_str + r" \times 10^{16}\ \mathrm{molec\ cm}^{-2}$" + "\n"
                r"$\mathrm{(definition:\ } f_p\,\Delta\mathrm{VCD}\mathrm{)}$" + "\n"
                r"$m_{\mathrm{NO_2}} = " + f"{mkg:.2f}" + r"\ \mathrm{kg}$" + "\n"
                r"$A = " + f"{a_cm2/1e11:.4f}" + r" \times 10^{11}\ \mathrm{cm}^{2}$" + "\n"
                r"$\mathrm{Check:}\ (\Delta\mathrm{VCD}_{\mathrm{plume}} \cdot A / N_A)\, M_{\mathrm{NO_2}} \approx "
                + mchk
                + r"\ \mathrm{kg}$"
            )
            axi.text(
                0.02,
                0.98,
                box_txt,
                transform=axi.transAxes,
                ha="left",
                va="top",
                fontsize=7.5,
                color="0.1",
                linespacing=1.2,
                bbox=dict(
                    boxstyle="round,pad=0.34", facecolor="white", edgecolor="0.5", linewidth=0.5, alpha=0.95
                ),
                zorder=20,
            )

            _add_scalebar_km(axi, lat_mid_deg=e_lat_deg, km=8, where="lr", color="0.2", text_font=10)

            y_edge = 0.5 * (eB + eT)
            cp = ConnectionPatch(
                (plon, pla),
                (eL, y_edge),
                "data",
                "data",
                axesA=ax0,
                axesB=axi,
                arrowstyle="->",
                color=col,
                linewidth=1.6,
                mutation_scale=14,
                shrinkA=4,
                shrinkB=0,
                clip_on=False,
                zorder=8,
            )
            fig.add_artist(cp)

        args.out.parent.mkdir(parents=True, exist_ok=True)
        plt.subplots_adjust(left=0.05, right=0.99, top=0.95, bottom=0.05)
        fig.savefig(args.out, dpi=args.dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close()

    print("Wrote", args.out.resolve(), f"  max=({r},{c})  min+=({rmin},{cmin})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
