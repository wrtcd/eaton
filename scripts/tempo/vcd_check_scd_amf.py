"""
VCD_check = SCD / AMF_trop  (validation path; ATBD prior AMF from recomputed raster).

Inputs (same grid):
  - fitted_slant_column (SCD)
  - tempo_amf_trop_atbd.tif from amf_atbd_from_tempo.py

Optional: apply tempo_mask_screen_utm11_clipped.tif (set nodata where screen fails).

Usage:
  py -3 scripts/tempo/vcd_check_scd_amf.py

Requires: numpy, rasterio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import rasterio
except ImportError:
    print("Install rasterio: py -3 -m pip install rasterio", file=sys.stderr)
    sys.exit(1)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SCD = _REPO_ROOT / "step-by-step" / "03 tempo" / "tempo_sup_fitted_slant_column_utm11_clipped.tif"
_DEFAULT_AMF = _REPO_ROOT / "step-by-step" / "05 amf adj" / "tempo_amf_trop_atbd.tif"
_DEFAULT_SCREEN = _REPO_ROOT / "step-by-step" / "03 tempo" / "tempo_mask_screen_utm11_clipped.tif"
_DEFAULT_OUT_DIR = _REPO_ROOT / "step-by-step" / "06 vcd check"
_DEFAULT_OUT = "tempo_vcd_check_scd_over_amf_trop.tif"

NODATA_OUT = -1.0e30


def _finite_raster(a: np.ndarray, nodata: float | None) -> np.ndarray:
    ok = np.isfinite(a)
    if nodata is not None and np.isfinite(nodata):
        ok &= a != nodata
    ok &= a > -1e20
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="VCD_check = SCD / AMF_trop (prior ATBD AMF).")
    ap.add_argument("--scd", type=Path, default=_DEFAULT_SCD)
    ap.add_argument("--amf", type=Path, default=_DEFAULT_AMF)
    ap.add_argument("--screen", type=Path, default=_DEFAULT_SCREEN, help="uint8 mask 1=keep; omit if file missing.")
    ap.add_argument("--no-screen", action="store_true")
    ap.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    ap.add_argument("-o", "--output", default=_DEFAULT_OUT, help="Output filename.")
    args = ap.parse_args()

    for p, label in ((args.scd, "SCD"), (args.amf, "AMF")):
        if not p.is_file():
            print(f"ERROR: {label} not found: {p}", file=sys.stderr)
            return 1

    with rasterio.open(args.scd) as ds_s:
        scd = ds_s.read(1).astype(np.float64)
        prof = ds_s.profile.copy()
        scd_nd = ds_s.nodata
        tr_s = ds_s.transform
        crs_s = ds_s.crs
        h, w = ds_s.height, ds_s.width

    with rasterio.open(args.amf) as ds_a:
        amf = ds_a.read(1).astype(np.float64)
        amf_nd = ds_a.nodata
        if ds_a.height != h or ds_a.width != w:
            print("ERROR: AMF grid size mismatch vs SCD.", file=sys.stderr)
            return 1
        if ds_a.crs != crs_s or ds_a.transform != tr_s:
            print("ERROR: AMF CRS/transform mismatch vs SCD.", file=sys.stderr)
            return 1

    ok_scd = _finite_raster(scd, scd_nd)
    ok_amf = _finite_raster(amf, amf_nd)
    ok = ok_scd & ok_amf & (amf > 0)

    vcd = np.full_like(scd, np.nan, dtype=np.float64)
    np.divide(scd, amf, out=vcd, where=ok)

    if not args.no_screen and args.screen.is_file():
        with rasterio.open(args.screen) as ds_m:
            if ds_m.height != h or ds_m.width != w:
                print("ERROR: Screen mask size mismatch.", file=sys.stderr)
                return 1
            m = ds_m.read(1) > 0
        vcd = np.where(m, vcd, np.nan)
        print(f"Applied screen: {args.screen.name}")
    elif not args.no_screen:
        print(f"Note: no screen file at {args.screen} — VCD_check not QA-filtered.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / args.output

    out_arr = np.where(np.isfinite(vcd), vcd, NODATA_OUT).astype(np.float32)
    prof.update(
        driver="GTiff",
        dtype="float32",
        nodata=NODATA_OUT,
        count=1,
        compress="deflate",
    )

    with rasterio.open(out_path, "w", **prof) as dst:
        dst.write(out_arr, 1)

    n_ok = int(np.isfinite(vcd).sum())
    print(f"Wrote {out_path}")
    print(f"  Valid VCD_check pixels: {n_ok} / {h * w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
