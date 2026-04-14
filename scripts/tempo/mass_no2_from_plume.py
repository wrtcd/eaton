"""
Column NO2 mass from plume excess column (step 08).

  mass_kg per pixel = (ΔVCD_plume [molecules/cm²] × pixel_area [cm²]) / N_A × M_NO2

  ΔVCD_plume from step 07 (tempo_delta_vcd_plume.tif), same TEMPO grid.

Outputs:
  - GeoTIFF: mass per pixel (kg)
  - summary JSON: total mass, pixel stats
  - PNG figures: maps of ΔVCD_plume and mass; histogram of positive mass

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
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
except ImportError:
    print("Install matplotlib: py -3 -m pip install matplotlib", file=sys.stderr)
    sys.exit(1)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DVCD = _REPO_ROOT / "step-by-step" / "07 plume delta" / "tempo_delta_vcd_plume.tif"
_DEFAULT_OUT_DIR = _REPO_ROOT / "step-by-step" / "08 mass"
N_A = 6.02214076e23  # Avogadro (mol^-1)
M_NO2_KG_PER_MOL = 46.0055e-3  # kg/mol
NODATA_IN = -1.0e30
NODATA_OUT = -1.0e30


def _pixel_area_m2(transform) -> float:
    """Ground area of one pixel (m²), UTM / metric CRS."""
    return abs(transform.a * transform.e)


def main() -> int:
    ap = argparse.ArgumentParser(description="NO2 mass from delta_VCD_plume column.")
    ap.add_argument("--delta-plume", type=Path, default=_DEFAULT_DVCD, help="ΔVCD_plume GeoTIFF (molecules/cm²).")
    ap.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    if not args.delta_plume.is_file():
        print(f"ERROR: not found: {args.delta_plume}", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = args.out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(args.delta_plume) as ds:
        dvcd = ds.read(1).astype(np.float64)
        nodata = ds.nodata
        tr = ds.transform
        crs = ds.crs
        h, w = ds.height, ds.width
        bounds = ds.bounds
        prof = ds.profile.copy()

    ok = np.isfinite(dvcd) & (dvcd > -1e20)
    if nodata is not None and np.isfinite(nodata):
        ok &= dvcd != nodata
    ok &= dvcd != NODATA_IN

    area_m2 = _pixel_area_m2(tr)
    area_cm2 = area_m2 * 1.0e4

    # molecules in column through pixel
    molecules = np.where(ok, dvcd * area_cm2, np.nan)
    mass_kg = np.where(ok, molecules / N_A * M_NO2_KG_PER_MOL, np.nan)

    total_kg_all = float(np.nansum(mass_kg))
    pos = mass_kg > 0
    neg = ok & (mass_kg < 0)
    total_kg_positive = float(np.nansum(np.where(pos, mass_kg, 0.0)))
    n_pos = int(np.sum(pos))
    n_neg = int(np.sum(neg))
    n_valid = int(np.sum(ok))

    summary = {
        "delta_vcd_plume_path": str(args.delta_plume.resolve()),
        "pixel_area_m2": area_m2,
        "crs": str(crs) if crs else None,
        "width": w,
        "height": h,
        "bounds": {"left": bounds.left, "bottom": bounds.bottom, "right": bounds.right, "top": bounds.top},
        "n_valid_delta_pixels": n_valid,
        "n_positive_mass_pixels": n_pos,
        "n_negative_mass_pixels": n_neg,
        "total_no2_mass_kg_sum_all_pixels": total_kg_all,
        "total_no2_mass_kg_sum_positive_only": total_kg_positive,
        "molar_mass_no2_kg_per_mol": M_NO2_KG_PER_MOL,
        "avogadro": N_A,
    }
    with open(args.out_dir / "tempo_plume_mass_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    prof.update(dtype="float32", nodata=NODATA_OUT, count=1, compress="deflate")
    out_tif = args.out_dir / "tempo_mass_no2_kg_per_pixel.tif"
    wrt = np.where(np.isfinite(mass_kg), mass_kg, NODATA_OUT).astype(np.float32)
    with rasterio.open(out_tif, "w", **prof) as dst:
        dst.write(wrt, 1)

    # --- figures ---
    extent = (bounds.left, bounds.right, bounds.bottom, bounds.top)

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(np.ma.masked_where(~ok, dvcd), extent=extent, origin="upper", cmap="viridis", aspect="auto")
    plt.colorbar(im, ax=ax, label="molecules/cm²")
    ax.set_title("Delta VCD plume (column)")
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    fig.savefig(fig_dir / "map_delta_vcd_plume.png", dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(
        np.ma.masked_where(~np.isfinite(mass_kg), mass_kg),
        extent=extent,
        origin="upper",
        cmap="magma",
        aspect="auto",
    )
    plt.colorbar(im, ax=ax, label="kg (NO2) per pixel")
    ax.set_title("NO2 mass per TEMPO pixel (plume column)")
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    fig.savefig(fig_dir / "map_mass_no2_kg_per_pixel.png", dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    vals = mass_kg[pos].ravel()
    if vals.size > 0:
        ax.hist(vals, bins=min(50, max(10, int(np.sqrt(vals.size)))), color="steelblue", edgecolor="black", alpha=0.85)
        ax.set_title("Distribution of positive NO2 mass per pixel (kg)")
        ax.set_xlabel("kg (NO2)")
        ax.set_ylabel("Pixel count")
    else:
        ax.text(0.5, 0.5, "No positive mass pixels", ha="center", va="center")
    fig.savefig(fig_dir / "histogram_mass_no2_kg.png", dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)

    if n_pos > 0:
        vmin = max(float(np.nanmin(mass_kg[pos])), 1e-30)
        vmax = max(float(np.nanmax(mass_kg[pos])), vmin * 1.0001)
        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(
            np.ma.masked_where(mass_kg <= 0, mass_kg),
            extent=extent,
            origin="upper",
            cmap="inferno",
            aspect="auto",
            norm=mcolors.LogNorm(vmin=vmin, vmax=vmax),
        )
        plt.colorbar(im, ax=ax, label="kg (NO2) per pixel (log scale)")
        ax.set_title("NO2 mass per pixel (positive values, log scale)")
        ax.set_xlabel("Easting (m)")
        ax.set_ylabel("Northing (m)")
        fig.savefig(fig_dir / "map_mass_no2_kg_log.png", dpi=args.dpi, bbox_inches="tight")
        plt.close(fig)

    print(f"Wrote {out_tif}")
    print(f"Wrote {args.out_dir / 'tempo_plume_mass_summary.json'}")
    print(f"Wrote figures under {fig_dir}")
    print(f"Total NO2 mass (sum all signed pixels): {total_kg_all:.6e} kg")
    print(f"Total NO2 mass (positive pixels only): {total_kg_positive:.6e} kg")
    print(f"Positive / negative mass pixels: {n_pos} / {n_neg} (valid {n_valid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
