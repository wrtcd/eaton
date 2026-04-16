"""
Compare two **already aligned** NO₂ column GeoTIFFs (same CRS, shape, transform) — for
cross-satellite or model-vs-observation checks (e.g. TEMPO vs TROPOMI on the same grid).

Reports bias, RMSE, MAE, Pearson r, and fraction of pixels within a column tolerance (optional).

Usage:
  py -3 scripts/validation/compare_aligned_no2_columns.py --a tempo_vcd.tif --b tropomi_no2.tif
  py -3 scripts/validation/compare_aligned_no2_columns.py --a a.tif --b b.tif --mask valid_mask.tif

Requires: numpy, rasterio
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

try:
    import rasterio
except ImportError:
    print("Install rasterio: py -3 -m pip install rasterio", file=sys.stderr)
    sys.exit(1)

def _read_band(path: Path, band: int = 1) -> tuple[np.ndarray, object | None, object]:
    with rasterio.open(path) as ds:
        a = ds.read(band).astype(np.float64)
        nodata = ds.nodata
        tr = ds.transform
        crs = ds.crs
        h, w = ds.height, ds.width
    return a, nodata, {"transform": tr, "crs": crs, "shape": (h, w)}


def _valid_mask(
    a: np.ndarray,
    b: np.ndarray,
    nodata_a: float | None,
    nodata_b: float | None,
    fill: float = -1e30,
) -> np.ndarray:
    ok = np.isfinite(a) & np.isfinite(b)
    ok &= a > fill
    ok &= b > fill
    if nodata_a is not None and np.isfinite(nodata_a):
        ok &= a != nodata_a
    if nodata_b is not None and np.isfinite(nodata_b):
        ok &= b != nodata_b
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare two aligned NO2 column rasters.")
    ap.add_argument("--a", type=Path, required=True, help="GeoTIFF A (e.g. TEMPO VCD).")
    ap.add_argument("--b", type=Path, required=True, help="GeoTIFF B (e.g. TROPOMI).")
    ap.add_argument("--mask", type=Path, default=None, help="Optional single-band mask (1 = use pixel).")
    ap.add_argument("--band-a", type=int, default=1)
    ap.add_argument("--band-b", type=int, default=1)
    ap.add_argument(
        "--within",
        type=float,
        default=None,
        help="If set, report fraction of valid pixels with |A-B| <= this (same units as rasters).",
    )
    args = ap.parse_args()

    if not args.a.is_file() or not args.b.is_file():
        print("ERROR: --a and --b must exist.", file=sys.stderr)
        return 1

    a, nd_a, meta_a = _read_band(args.a, args.band_a)
    b, nd_b, meta_b = _read_band(args.b, args.band_b)

    if meta_a["shape"] != meta_b["shape"]:
        print(f"ERROR: shape mismatch {meta_a['shape']} vs {meta_b['shape']}", file=sys.stderr)
        return 1
    if str(meta_a["crs"]) != str(meta_b["crs"]):
        print(f"WARNING: CRS differ: {meta_a['crs']} vs {meta_b['crs']}", file=sys.stderr)

    ok = _valid_mask(a, b, nd_a, nd_b)
    if args.mask is not None:
        with rasterio.open(args.mask) as ds:
            m = ds.read(1)
        if m.shape != a.shape:
            print("ERROR: mask shape mismatch.", file=sys.stderr)
            return 1
        ok &= m > 0

    n = int(np.sum(ok))
    if n == 0:
        print("No valid overlapping pixels.")
        return 1

    da = a[ok]
    db = b[ok]
    diff = da - db
    bias = float(np.mean(diff))
    rmse = float(math.sqrt(np.mean(diff**2)))
    mae = float(np.mean(np.abs(diff)))
    r = float(np.corrcoef(da, db)[0, 1]) if n > 1 else float("nan")

    print("=== compare_aligned_no2_columns ===")
    print(f"A: {args.a}")
    print(f"B: {args.b}")
    print(f"Valid pixels: {n}")
    print(f"Mean A: {float(np.mean(da)):.6g}  Mean B: {float(np.mean(db)):.6g}")
    print(f"Bias (mean A-B): {bias:.6g}")
    print(f"RMSE(A-B): {rmse:.6g}")
    print(f"MAE(A-B): {mae:.6g}")
    print(f"Pearson r: {r:.6g}")
    if args.within is not None:
        frac = float(np.mean(np.abs(diff) <= args.within))
        print(f"P(|A-B| <= {args.within}): {frac:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
