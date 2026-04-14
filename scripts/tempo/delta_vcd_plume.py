"""
Plume isolation on the TEMPO grid:

  VCD_bg   = median(VCD_adj) over pixels with negligible plume fraction (f_p ~ 0)
  ΔVCD     = VCD_adj - VCD_bg
  ΔVCD_plume = f_p · ΔVCD

Inputs (same CRS, transform, dimensions):
  - VCD_adj (e.g. tempo_vcd_check_scd_over_amf_trop.tif from step 06)
  - f_p (e.g. tempo_fp_plume_utm11_clipped.tif from step 04)

f_p nodata (-9999) from screening: output nodata for those pixels.

Usage:
  py -3 scripts/tempo/delta_vcd_plume.py

Requires: numpy, rasterio
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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_VCD = _REPO_ROOT / "step-by-step" / "06 vcd check" / "tempo_vcd_check_scd_over_amf_trop.tif"
_DEFAULT_FP = _REPO_ROOT / "step-by-step" / "04 plume fraction" / "tempo_fp_plume_utm11_clipped.tif"
_DEFAULT_OUT_DIR = _REPO_ROOT / "step-by-step" / "07 plume delta"
_FP_NODATA = -9999.0
_OUT_NODATA = -1.0e30


def _vcd_ok(a: np.ndarray, nodata: float | None) -> np.ndarray:
    ok = np.isfinite(a) & (a > -1e20)
    if nodata is not None and np.isfinite(nodata):
        ok &= a != nodata
    return ok


def _fp_ok(fp: np.ndarray) -> np.ndarray:
    """Valid f_p in [0, 1]; screened-out pixels are ~ -9999."""
    return np.isfinite(fp) & (fp >= 0.0) & (fp <= 1.0 + 1e-6)


def _vcd_background(vcd: np.ndarray, fp: np.ndarray, v_ok: np.ndarray, fp_ok: np.ndarray, fp_eps: float, fp_low: float) -> tuple[float, str]:
    """Scalar VCD_bg; returns (value, method description)."""
    base = v_ok & fp_ok
    m0 = base & (fp <= fp_eps)
    if np.any(m0):
        return float(np.median(vcd[m0])), f"median where f_p <= {fp_eps}"
    m1 = base & (fp < fp_low)
    if np.any(m1):
        return float(np.median(vcd[m1])), f"median where f_p < {fp_low} (no strict non-plume pixels)"
    m2 = base
    if np.any(m2):
        return float(np.median(vcd[m2])), "median over all valid pixels (fallback — no low-f_p sample)"
    return float("nan"), "failed"


def main() -> int:
    ap = argparse.ArgumentParser(description="ΔVCD and f_p·ΔVCD on TEMPO grid.")
    ap.add_argument("--vcd-adj", type=Path, default=_DEFAULT_VCD, help="VCD_adj single-band GeoTIFF.")
    ap.add_argument("--fp", type=Path, default=_DEFAULT_FP, help="f_p plume fraction GeoTIFF.")
    ap.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    ap.add_argument("--fp-eps", type=float, default=1e-6, help="Treat f_p <= this as non-plume for VCD_bg.")
    ap.add_argument("--fp-low", type=float, default=0.05, help="Second try: f_p < this for VCD_bg median.")
    args = ap.parse_args()

    if not args.vcd_adj.is_file():
        print(f"ERROR: VCD_adj not found: {args.vcd_adj}", file=sys.stderr)
        return 1
    if not args.fp.is_file():
        print(f"ERROR: f_p not found: {args.fp}", file=sys.stderr)
        return 1

    with rasterio.open(args.vcd_adj) as ds_v:
        vcd = ds_v.read(1).astype(np.float64)
        prof = ds_v.profile.copy()
        v_nd = ds_v.nodata
        tr = ds_v.transform
        crs = ds_v.crs
        h, w = ds_v.height, ds_v.width

    with rasterio.open(args.fp) as ds_f:
        fp = ds_f.read(1).astype(np.float64)
        f_nd = ds_f.nodata
        if ds_f.height != h or ds_f.width != w:
            print("ERROR: f_p grid size mismatch vs VCD_adj.", file=sys.stderr)
            return 1
        if ds_f.transform != tr or ds_f.crs != crs:
            print("ERROR: f_p georeference mismatch vs VCD_adj.", file=sys.stderr)
            return 1

    v_ok = _vcd_ok(vcd, v_nd)
    fp_ok = _fp_ok(fp)
    if f_nd is not None and np.isfinite(f_nd):
        fp_ok &= fp != f_nd
    fp_ok &= ~np.isclose(fp, _FP_NODATA)

    vcd_bg, bg_method = _vcd_background(vcd, fp, v_ok, fp_ok, args.fp_eps, args.fp_low)
    if not np.isfinite(vcd_bg):
        print("ERROR: Could not estimate VCD_bg.", file=sys.stderr)
        return 1

    delta = np.full_like(vcd, np.nan, dtype=np.float64)
    np.subtract(vcd, vcd_bg, out=delta, where=v_ok)

    delta_plume = np.full_like(vcd, np.nan, dtype=np.float64)
    use = v_ok & fp_ok
    np.multiply(fp, delta, out=delta_plume, where=use)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "vcd_bg_molecules_cm2": vcd_bg,
        "vcd_bg_method": bg_method,
        "fp_eps": args.fp_eps,
        "fp_low_fallback": args.fp_low,
        "vcd_adj_path": str(args.vcd_adj.as_posix()),
        "fp_path": str(args.fp.as_posix()),
    }
    meta_path = args.out_dir / "tempo_delta_vcd_plume_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    prof.update(dtype="float32", nodata=_OUT_NODATA, count=1, compress="deflate")

    out_d = args.out_dir / "tempo_delta_vcd.tif"
    out_p = args.out_dir / "tempo_delta_vcd_plume.tif"

    def write_arr(path: Path, arr: np.ndarray) -> None:
        wrt = np.where(np.isfinite(arr), arr, _OUT_NODATA).astype(np.float32)
        with rasterio.open(path, "w", **prof) as dst:
            dst.write(wrt, 1)

    write_arr(out_d, delta)
    write_arr(out_p, delta_plume)

    n_dp = int(np.isfinite(delta_plume).sum())
    print(f"VCD_bg = {vcd_bg:.6e} molecules/cm^2 ({bg_method})")
    print(f"Wrote {out_d}")
    print(f"Wrote {out_p}")
    print(f"Wrote {meta_path}")
    print(f"Finite delta_VCD_plume pixels: {n_dp} / {h * w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
