"""
Compare plume ΔVCD and NO2 mass rasters: VCD_check path vs operational tropospheric VCD.

Reads (same grid):
  - step 07: tempo_delta_vcd_plume.tif vs tempo_delta_vcd_plume_operational.tif
  - step 08: tempo_mass_no2_kg_per_pixel.tif vs operational/tempo_mass_no2_kg_per_pixel.tif

Writes PNGs under step-by-step/08 mass/comparison/ and a small stats JSON.

Usage:
  py -3 scripts/tempo/compare_plume_mass_check_vs_operational.py

Requires: numpy, rasterio, matplotlib
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    import rasterio
except ImportError:
    print("Install rasterio: py -3 -m pip install rasterio", file=sys.stderr)
    sys.exit(1)

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("Install matplotlib: py -3 -m pip install matplotlib", file=sys.stderr)
    sys.exit(1)

_REPO = Path(__file__).resolve().parents[2]
_NODATA = -1.0e30
_STEP07 = _REPO / "step-by-step" / "07 plume delta"
_STEP08 = _REPO / "step-by-step" / "08 mass"
_DEFAULT_OUT = _STEP08 / "comparison"


def _read_one(path: Path) -> tuple[np.ndarray, object]:
    with rasterio.open(path) as ds:
        a = ds.read(1).astype(np.float64)
        tr = ds.transform
        crs = ds.crs
        bounds = ds.bounds
        h, w = ds.height, ds.width
        nd = ds.nodata
    ok = np.isfinite(a) & (a > -1e20)
    if nd is not None and np.isfinite(nd):
        ok &= a != nd
    ok &= a != _NODATA
    # Drop absurd fills (nodata not exactly matching file sentinel)
    ok &= np.abs(a) < 1e19
    return a, {"transform": tr, "crs": crs, "bounds": bounds, "height": h, "width": w, "ok": ok}


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare check vs operational plume rasters.")
    ap.add_argument("--delta-check", type=Path, default=_STEP07 / "tempo_delta_vcd_plume.tif")
    ap.add_argument("--delta-op", type=Path, default=_STEP07 / "tempo_delta_vcd_plume_operational.tif")
    ap.add_argument("--mass-check", type=Path, default=_STEP08 / "tempo_mass_no2_kg_per_pixel.tif")
    ap.add_argument("--mass-op", type=Path, default=_STEP08 / "operational" / "tempo_mass_no2_kg_per_pixel.tif")
    ap.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT)
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    for p, label in (
        (args.delta_check, "delta check"),
        (args.delta_op, "delta operational"),
        (args.mass_check, "mass check"),
        (args.mass_op, "mass operational"),
    ):
        if not p.is_file():
            print(f"ERROR: missing {label}: {p}", file=sys.stderr)
            return 1

    d_chk, m_d_chk = _read_one(args.delta_check)
    d_op, m_d_op = _read_one(args.delta_op)
    mass_chk, m_m_chk = _read_one(args.mass_check)
    mass_op, m_m_op = _read_one(args.mass_op)

    if d_chk.shape != d_op.shape or mass_chk.shape != mass_op.shape:
        print("ERROR: raster shape mismatch.", file=sys.stderr)
        return 1

    both_d = m_d_chk["ok"] & m_d_op["ok"]
    both_m = m_m_chk["ok"] & m_m_op["ok"]
    bounds = m_d_chk["bounds"]
    extent = (bounds.left, bounds.right, bounds.bottom, bounds.top)

    diff_d = np.full_like(d_chk, np.nan, dtype=np.float64)
    np.subtract(d_op, d_chk, out=diff_d, where=both_d)

    diff_m = np.full_like(mass_chk, np.nan, dtype=np.float64)
    np.subtract(mass_op, mass_chk, out=diff_m, where=both_m)

    total_chk = float(np.nansum(np.where(m_m_chk["ok"], mass_chk, np.nan)))
    total_op = float(np.nansum(np.where(m_m_op["ok"], mass_op, np.nan)))
    total_both = float(np.nansum(np.where(both_m, mass_chk, np.nan)))  # sanity

    plume_d = both_d & (np.abs(d_chk) + np.abs(d_op) > 1e12)
    stats = {
        "delta_valid_check": int(m_d_chk["ok"].sum()),
        "delta_valid_operational": int(m_d_op["ok"].sum()),
        "delta_valid_both": int(both_d.sum()),
        "delta_plume_pixels_both": int(plume_d.sum()),
        "mass_valid_check": int(m_m_chk["ok"].sum()),
        "mass_valid_operational": int(m_m_op["ok"].sum()),
        "mass_valid_both": int(both_m.sum()),
        "total_mass_kg_check": total_chk,
        "total_mass_kg_operational": total_op,
        "total_mass_kg_difference_op_minus_check": total_op - total_chk,
        "fractional_difference": (total_op - total_chk) / total_chk if total_chk else None,
        "rmse_delta_molecules_cm2_all_valid_pixels": float(np.sqrt(np.mean((diff_d[both_d]) ** 2))) if both_d.any() else None,
        "rmse_delta_molecules_cm2_plume_subset_abs_sum_gt_1e12": float(np.sqrt(np.mean((diff_d[plume_d]) ** 2)))
        if plume_d.any()
        else None,
        "median_abs_delta_diff_molecules_cm2": float(np.median(np.abs(diff_d[both_d]))) if both_d.any() else None,
        "rmse_mass_kg": float(np.sqrt(np.mean((diff_m[both_m]) ** 2))) if both_m.any() else None,
        "median_abs_mass_diff_kg": float(np.median(np.abs(diff_m[both_m]))) if both_m.any() else None,
        "mean_delta_difference_op_minus_check_molecules_cm2": float(np.mean(diff_d[both_d])) if both_d.any() else None,
        "mean_mass_difference_op_minus_check_kg": float(np.mean(diff_m[both_m])) if both_m.any() else None,
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stats_path = args.out_dir / "check_vs_operational_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    vmax_d = float(np.nanpercentile(np.abs(np.r_[d_chk[m_d_chk["ok"]], d_op[m_d_op["ok"]]]), 99))
    if not np.isfinite(vmax_d) or vmax_d <= 0:
        vmax_d = 1.0
    vmax_dm = float(np.nanpercentile(np.abs(diff_d[both_d]), 99)) if both_d.any() else 1.0
    if not np.isfinite(vmax_dm) or vmax_dm <= 0:
        vmax_dm = 1.0

    pos_m = np.isfinite(mass_chk) & np.isfinite(mass_op) & (mass_chk > 0) & (mass_op > 0)
    vmax_m = float(np.nanpercentile(np.r_[mass_chk[pos_m], mass_op[pos_m]], 99)) if pos_m.any() else 1.0
    if not np.isfinite(vmax_m) or vmax_m <= 0:
        vmax_m = 1.0
    vmax_diffm = float(np.nanpercentile(np.abs(diff_m[both_m]), 99)) if both_m.any() else 1.0
    if not np.isfinite(vmax_diffm) or vmax_diffm <= 0:
        vmax_diffm = 1.0

    # --- ΔVCD_plume maps ---
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for ax, arr, mask, title, cmap, vm in (
        (axes[0], d_chk, m_d_chk["ok"], "ΔVCD plume (VCD_check = SCD/AMFₜᵣₒₚ)", "viridis", vmax_d),
        (axes[1], d_op, m_d_op["ok"], "ΔVCD plume (operational VCD trop)", "viridis", vmax_d),
        (axes[2], diff_d, both_d, "Difference (operational − check)", "coolwarm", vmax_dm),
    ):
        im = ax.imshow(
            np.ma.masked_where(~mask, arr),
            extent=extent,
            origin="upper",
            cmap=cmap,
            aspect="auto",
            vmin=-vm if ax is axes[2] else 0,
            vmax=vm,
        )
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        ax.set_title(title)
        ax.set_xlabel("Easting (m)")
    axes[0].set_ylabel("Northing (m)")
    fig.suptitle("Plume-scaled column excess (molecules cm⁻²)", y=1.02)
    fig.tight_layout()
    fig.savefig(args.out_dir / "compare_delta_vcd_plume_maps.png", dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)

    # --- Mass maps ---
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for ax, arr, mask, title, cmap, vm in (
        (axes[0], mass_chk, m_m_chk["ok"], "Mass kg px⁻¹ (VCD_check path)", "magma", vmax_m),
        (axes[1], mass_op, m_m_op["ok"], "Mass kg px⁻¹ (operational VCD)", "magma", vmax_m),
        (axes[2], diff_m, both_m, "Difference (operational − check)", "coolwarm", vmax_diffm),
    ):
        im = ax.imshow(
            np.ma.masked_where(~mask, arr),
            extent=extent,
            origin="upper",
            cmap=cmap,
            aspect="auto",
            vmin=-vm if ax is axes[2] else 0,
            vmax=vm,
        )
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        ax.set_title(title)
        ax.set_xlabel("Easting (m)")
    axes[0].set_ylabel("Northing (m)")
    fig.suptitle("NO₂ mass per pixel (plume column)", y=1.02)
    fig.tight_layout()
    fig.savefig(args.out_dir / "compare_mass_kg_maps.png", dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)

    # --- Histograms: ΔVCD ---
    fig, ax = plt.subplots(figsize=(7, 4))
    v0 = d_chk[both_d].ravel()
    v1 = d_op[both_d].ravel()
    if v0.size > 0:
        hi = max(float(np.percentile(np.r_[v0, v1], 99.5)), 1.0)
        bins = np.linspace(0, hi, 50)
        ax.hist(v0, bins=bins, alpha=0.5, label="VCD_check path", color="C0", edgecolor="none")
        ax.hist(v1, bins=bins, alpha=0.5, label="Operational VCD", color="C1", edgecolor="none")
        ax.set_xlabel("ΔVCD plume (molecules cm⁻²)")
        ax.set_ylabel("Pixel count (both valid)")
        ax.legend()
        ax.set_title("Histogram: plume-scaled column excess")
    fig.tight_layout()
    fig.savefig(args.out_dir / "histogram_delta_vcd_plume_both.png", dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)

    # --- Histograms: mass (positive) ---
    fig, ax = plt.subplots(figsize=(7, 4))
    w0 = mass_chk[both_m].ravel()
    w1 = mass_op[both_m].ravel()
    pos_both = both_m & (mass_chk > 0) & (mass_op > 0)
    w0p = mass_chk[pos_both].ravel()
    w1p = mass_op[pos_both].ravel()
    if w0p.size > 0:
        hi = max(float(np.percentile(np.r_[w0p, w1p], 99.5)), 1e-30)
        bins = np.linspace(0, hi, 40)
        ax.hist(w0p, bins=bins, alpha=0.55, label="VCD_check path", color="C0", edgecolor="none")
        ax.hist(w1p, bins=bins, alpha=0.55, label="Operational VCD", color="C1", edgecolor="none")
        ax.set_xlabel("NO₂ mass per pixel (kg)")
        ax.set_ylabel("Pixel count (both valid, mass>0)")
        ax.legend()
        ax.set_title("Histogram: positive mass per pixel")
    fig.tight_layout()
    fig.savefig(args.out_dir / "histogram_mass_kg_positive_both.png", dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)

    # Scatter: mass op vs check (both valid)
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    if both_m.sum() > 0:
        x = mass_chk[both_m].ravel()
        y = mass_op[both_m].ravel()
        ax.scatter(x, y, s=8, alpha=0.5, c="0.2")
        mx = max(float(np.nanmax(x)), float(np.nanmax(y)), 1e-30)
        ax.plot([0, mx], [0, mx], "r--", lw=1, label="1:1")
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("Mass kg px⁻¹ (VCD_check)")
        ax.set_ylabel("Mass kg px⁻¹ (operational)")
        ax.legend()
        ax.set_title("Per-pixel mass comparison")
    fig.tight_layout()
    fig.savefig(args.out_dir / "scatter_mass_check_vs_operational.png", dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)

    print(f"Wrote comparison figures and {stats_path}")
    print(f"  Total mass kg - check: {total_chk:.6e}, operational: {total_op:.6e}, op-check: {total_op - total_chk:.6e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
