"""
TEMPO NO2 tropospheric AMF and layer sensitivity from ATBD §3.1.3 (Algorithm Theoretical Basis).

Implements the discrete analog of:
  AMF_trop = sum_k W_k * S_k * c_k   over tropospheric layers

where (ATBD):
  - W_k = scattering_weights (sensitivity vs altitude; "W(z)" in the document)
  - S_k = n_k / sum_j n_j  over troposphere only, with n_k = gas_profile partial columns (molecules/cm^2)
  - c_k = temperature correction (Eq. 18), T_sigma = 220 K
  - Tropospheric layers: hybrid pressure layer centers between surface pressure p_s and tropopause p_trop

Outputs:
  - Single-band AMF_trop (recomputed) on the reference grid
  - Optional 72-band layer contribution A_k = W_k * S_k * c_k
  - Optional 72-band normalized weights A_k / AMF (relative layer contribution to AMF; sums to ~1 per pixel)

ATBD naming: altitude sensitivity is carried by **scattering weights W** (no separate "AK" variable in L2).
The discrete layer product **W_k * S_k * c_k** is the per-layer term in the tropospheric AMF sum; normalized
**A_k/AMF** is a convenient 72-band "where the AMF comes from" weight. For a **custom** assumed profile
**w_k** (replacing prior shape S_k), use the same sum with **S_k replaced by normalized w_k**.

Reference: https://asdc.larc.nasa.gov/documents/tempo/ATBD_TEMPO_NO2.pdf  Section 3.1.3

Usage:
  py -3 scripts/tempo/amf_atbd_from_tempo.py
  py -3 scripts/tempo/amf_atbd_from_tempo.py --nc data/tempo/YOUR.nc --reference "step-by-step/03 tempo/tempo_vcd_troposphere_utm11_clipped.tif"

Requires: numpy, scipy, rasterio, pyproj, netCDF4
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import netCDF4 as nc
import rasterio
from rasterio.transform import xy as transform_xy
from scipy.interpolate import griddata
from pyproj import Transformer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_TEMPO = _REPO_ROOT / "data" / "tempo"
_DEFAULT_NC = _DATA_TEMPO / "TEMPO_NO2_L2_V03_20250109T184504Z_S008G09.nc"
_DEFAULT_REF = _REPO_ROOT / "step-by-step" / "03 tempo" / "tempo_vcd_troposphere_utm11_clipped.tif"
_DEFAULT_OUT_DIR = _REPO_ROOT / "step-by-step" / "05 amf adj"
_DEFAULT_SCREEN = _REPO_ROOT / "step-by-step" / "03 tempo" / "tempo_mask_screen_utm11_clipped.tif"

T_SIGMA_K = 220.0  # NO2 cross section temperature (ATBD §3.1.3.7)

# TROPOMI-style coefficients from ATBD Eq. (18)
C1 = 0.00316
C2 = 3.39e-6


def _fill_value(var: nc.Variable) -> float:
    fv = getattr(var, "_FillValue", None)
    if fv is None:
        return np.nan
    return float(fv)


def _read_eta(surface_pressure_var: nc.Variable) -> tuple[np.ndarray, np.ndarray]:
    """Hybrid eta coefficients; length 73 = 72 layer interfaces."""
    eta_a = np.asarray(surface_pressure_var.Eta_A, dtype=np.float64)
    eta_b = np.asarray(surface_pressure_var.Eta_B, dtype=np.float64)
    if eta_a.size != eta_b.size or eta_a.size < 73:
        raise SystemExit(f"Unexpected Eta_A/Eta_B length: {eta_a.size}, {eta_b.size}")
    return eta_a, eta_b


def _layer_mid_pressure_hpa(ps_hpa: np.ndarray, eta_a: np.ndarray, eta_b: np.ndarray) -> np.ndarray:
    """
    Layer center pressure (hPa) for each of 72 layers, shape (..., 72).
    ps_hpa: (...,) surface pressure in hPa
    """
    # boundaries p[i] = eta_a[i] + ps * eta_b[i], i = 0..72
    p_bot = eta_a[:-1] + ps_hpa[..., np.newaxis] * eta_b[:-1]
    p_top = eta_a[1:] + ps_hpa[..., np.newaxis] * eta_b[1:]
    return 0.5 * (p_bot + p_top)


def _temperature_correction_c(t_kelvin: np.ndarray) -> np.ndarray:
    """ATBD Eq. (18); T in Kelvin."""
    dt = t_kelvin - T_SIGMA_K
    return 1.0 - C1 * dt + C2 * (dt**2)


def _troposphere_mask(p_mid_hpa: np.ndarray, ps_hpa: np.ndarray, p_trop_hpa: np.ndarray) -> np.ndarray:
    """
    Tropospheric layers: between tropopause and surface in pressure coordinates.
    Typically ps > p_trop; layer is tropospheric if p_trop <= p_mid <= ps.
    """
    return (p_mid_hpa >= p_trop_hpa[..., np.newaxis]) & (p_mid_hpa <= ps_hpa[..., np.newaxis])


def compute_amf_and_layer_terms(
    w: np.ndarray,
    n_partial: np.ndarray,
    t_prof: np.ndarray,
    ps_hpa: np.ndarray,
    p_trop_hpa: np.ndarray,
    eta_a: np.ndarray,
    eta_b: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Native grid: all (H, W, 72).

    Returns:
      amf_trop: (H, W)
      a_layer: (H, W, 72) = W * S * c
      s_layer: (H, W, 72) profile shape S
      p_mid: (H, W, 72) layer center pressure (hPa)
    """
    h, wdt, nlev = w.shape
    if n_partial.shape != (h, wdt, nlev) or t_prof.shape != (h, wdt, nlev):
        raise ValueError("W, gas_profile, temperature_profile must match shape (H,W,72)")

    p_mid = _layer_mid_pressure_hpa(ps_hpa, eta_a, eta_b)
    trop = _troposphere_mask(p_mid, ps_hpa, p_trop_hpa)

    n_safe = np.where(np.isfinite(n_partial) & trop, n_partial, 0.0)
    n_sum = np.sum(n_safe, axis=2, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        s_layer = np.where(n_sum > 0, n_safe / n_sum, 0.0)

    c_layer = _temperature_correction_c(t_prof)
    c_layer = np.where(np.isfinite(t_prof), c_layer, np.nan)

    a_layer = w * s_layer * c_layer
    a_layer = np.where(np.isfinite(a_layer) & trop, a_layer, 0.0)

    amf_trop = np.sum(a_layer, axis=2)
    amf_trop = np.where(np.isfinite(ps_hpa) & np.isfinite(p_trop_hpa), amf_trop, np.nan)
    return amf_trop, a_layer, s_layer, p_mid


def _subsample(pts: np.ndarray, vals: np.ndarray, max_points: int, rng: np.random.Generator):
    n = pts.shape[0]
    if n <= max_points:
        return pts, vals
    idx = rng.choice(n, size=max_points, replace=False)
    return pts[idx], vals[idx]


def _regrid_2d(
    src: np.ndarray,
    pts: np.ndarray,
    fill_value: float,
    dest_x: np.ndarray,
    dest_y: np.ndarray,
    max_points: int,
    seed: int,
) -> np.ndarray:
    """src (H,W) -> dest (h,w)."""
    vals = src.ravel().astype(np.float64)
    m = np.isfinite(vals)
    if np.isfinite(fill_value):
        m &= vals != fill_value
    p = pts[m]
    v = vals[m]
    fin = np.isfinite(p[:, 0]) & np.isfinite(p[:, 1]) & np.isfinite(v)
    p = p[fin]
    v = v[fin]
    rng = np.random.default_rng(seed)
    if p.shape[0] == 0:
        return np.full(dest_x.shape, np.nan, dtype=np.float64)
    p, v = _subsample(p, v, max_points, rng)
    if p.shape[0] == 0:
        return np.full(dest_x.shape, np.nan, dtype=np.float64)
    try:
        return griddata(p, v, (dest_x, dest_y), method="linear", fill_value=np.nan)
    except Exception:
        try:
            return griddata(p, v, (dest_x, dest_y), method="nearest", fill_value=np.nan)
        except Exception:
            return np.full(dest_x.shape, np.nan, dtype=np.float64)


def _regrid_3d_stack(
    src: np.ndarray,
    pts: np.ndarray,
    fill_value: float,
    dest_x: np.ndarray,
    dest_y: np.ndarray,
    max_points: int,
    seed: int,
) -> np.ndarray:
    """src (H,W,K) -> (K,h,w)."""
    k = src.shape[2]
    out = np.empty((k, dest_x.shape[0], dest_x.shape[1]), dtype=np.float64)
    for i in range(k):
        out[i] = _regrid_2d(src[:, :, i], pts, fill_value, dest_x, dest_y, max_points, seed + i)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="ATBD tropospheric AMF and layer sensitivity from TEMPO L2.")
    ap.add_argument("--nc", type=Path, default=_DEFAULT_NC, help="TEMPO NO2 L2 NetCDF")
    ap.add_argument("--reference", type=Path, default=_DEFAULT_REF, help="Reference GeoTIFF (output grid)")
    ap.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR, help="Output directory")
    ap.add_argument("--max-points", type=int, default=50000, help="Max source points per layer for regrid")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--write-bands",
        action="store_true",
        help="Write 72-band GeoTIFFs: layer contribution A_k and normalized A_k/AMF",
    )
    ap.add_argument(
        "--compare-product",
        action="store_true",
        help="Print statistics vs product support_data/amf_troposphere (native grid)",
    )
    ap.add_argument(
        "--screen-mask",
        type=Path,
        default=None,
        help=f"uint8 QA/cloud/VCD screen (1=keep). Default {_DEFAULT_SCREEN.name} if present.",
    )
    ap.add_argument("--no-screen", action="store_true", help="Do not apply TEMPO screen mask to outputs.")
    args = ap.parse_args()

    if not args.nc.is_file():
        print(f"ERROR: NetCDF not found: {args.nc}", file=sys.stderr)
        return 1
    ref_path = args.reference if args.reference.is_file() else _REPO_ROOT / args.reference
    if not ref_path.is_file():
        print(f"ERROR: Reference not found: {ref_path}", file=sys.stderr)
        return 1

    with rasterio.open(ref_path) as ref:
        crs = ref.crs
        transform = ref.transform
        height, width = ref.height, ref.width
        if crs is None:
            print("ERROR: Reference has no CRS.", file=sys.stderr)
            return 1

    ds = nc.Dataset(str(args.nc))
    sp_var = ds["support_data/surface_pressure"]
    eta_a, eta_b = _read_eta(sp_var)

    w = np.asarray(ds["support_data/scattering_weights"][:], dtype=np.float64)
    n_partial = np.asarray(ds["support_data/gas_profile"][:], dtype=np.float64)
    t_prof = np.asarray(ds["support_data/temperature_profile"][:], dtype=np.float64)
    ps = np.asarray(ds["support_data/surface_pressure"][:], dtype=np.float64)
    p_trop = np.asarray(ds["support_data/tropopause_pressure"][:], dtype=np.float64)
    lat = np.asarray(ds["geolocation/latitude"][:], dtype=np.float64)
    lon = np.asarray(ds["geolocation/longitude"][:], dtype=np.float64)

    def apply_fill(varname: str, arr: np.ndarray) -> np.ndarray:
        v = ds["support_data"][varname]
        fv = _fill_value(v)
        if np.isfinite(fv):
            arr = np.where(arr == fv, np.nan, arr)
        return arr

    w = apply_fill("scattering_weights", w)
    n_partial = apply_fill("gas_profile", n_partial)
    t_prof = apply_fill("temperature_profile", t_prof)
    ps = apply_fill("surface_pressure", ps)
    p_trop = apply_fill("tropopause_pressure", p_trop)

    amf_native, a_layer, _, _ = compute_amf_and_layer_terms(
        w, n_partial, t_prof, ps, p_trop, eta_a, eta_b
    )

    if args.compare_product:
        amf_prod = np.asarray(ds["support_data/amf_troposphere"][:], dtype=np.float64)
        fv = _fill_value(ds["support_data/amf_troposphere"])
        if np.isfinite(fv):
            amf_prod = np.where(amf_prod == fv, np.nan, amf_prod)
        m = np.isfinite(amf_native) & np.isfinite(amf_prod) & (amf_prod > 0) & (amf_native > 0)
        if np.any(m):
            ratio = amf_native[m] / amf_prod[m]
            print("Compare to product amf_troposphere (native grid, valid pixels):")
            print(f"  N: {np.sum(m)}")
            print(f"  recomputed / product: median={np.median(ratio):.4f} mean={np.mean(ratio):.4f}")
            print(f"  correlation: {np.corrcoef(amf_native[m].ravel(), amf_prod[m].ravel())[0,1]:.6f}")
        else:
            print("Compare to product: no overlapping valid pixels.")

    ds.close()

    transformer = Transformer.from_crs("EPSG:4326", crs.to_string(), always_xy=True)
    src_x, src_y = transformer.transform(lon, lat)
    pts = np.column_stack([src_x.ravel(), src_y.ravel()])

    rows, cols = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
    dest_x, dest_y = transform_xy(transform, rows, cols, offset="center")
    dest_x = np.asarray(dest_x, dtype=np.float64).reshape(height, width)
    dest_y = np.asarray(dest_y, dtype=np.float64).reshape(height, width)

    t0 = time.perf_counter()
    out_nodata = -1.0e30
    fill_native = np.nan

    amf_r = _regrid_2d(amf_native, pts, fill_native, dest_x, dest_y, args.max_points, args.seed)
    print(f"Regridded AMF_trop in {time.perf_counter() - t0:.1f}s")

    screen_arr: np.ndarray | None = None
    if not args.no_screen:
        sc_path = args.screen_mask or _DEFAULT_SCREEN
        if sc_path.is_file():
            with rasterio.open(sc_path) as sm:
                if sm.width != width or sm.height != height:
                    print(f"ERROR: screen mask size {sm.width}x{sm.height} != reference {width}x{height}", file=sys.stderr)
                    return 1
                if sm.crs != crs:
                    print("ERROR: screen mask CRS mismatch.", file=sys.stderr)
                    return 1
                screen_arr = sm.read(1) > 0
            amf_r = np.where(screen_arr, amf_r, np.nan)
            print(f"Applied TEMPO screen mask: {sc_path.name}")
        else:
            print(f"Note: no screen mask at {sc_path} — outputs not QA/cloud filtered.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_amf = args.out_dir / "tempo_amf_trop_atbd.tif"
    prof = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": out_nodata,
        "compress": "deflate",
    }
    with rasterio.open(out_amf, "w", **prof) as dst:
        wrt = np.where(np.isnan(amf_r), out_nodata, amf_r).astype(np.float32)
        dst.write(wrt, 1)
    print(f"Wrote {out_amf}")

    if args.write_bands:
        t1 = time.perf_counter()
        a_stack = _regrid_3d_stack(a_layer, pts, fill_native, dest_x, dest_y, args.max_points, args.seed + 1000)
        print(f"Regridded 72-band layer contribution in {time.perf_counter() - t1:.1f}s")

        if screen_arr is not None:
            for b in range(72):
                a_stack[b] = np.where(screen_arr, a_stack[b], np.nan)

        out_a = args.out_dir / "tempo_amf_adj_layer_contribution_W_S_c_72bands.tif"
        prof72 = {**prof, "count": 72, "dtype": "float64", "predictor": 3}
        with rasterio.open(out_a, "w", **prof72) as dst:
            for b in range(72):
                plane = np.where(np.isnan(a_stack[b]), out_nodata, a_stack[b])
                dst.write(plane.astype(np.float64), b + 1)
        print(f"Wrote {out_a}")

        # Normalized layer weights (contribution / AMF)
        amf_safe = np.where(np.isnan(amf_r) | (amf_r == 0), np.nan, amf_r)
        with np.errstate(invalid="ignore"):
            norm_stack = a_stack / amf_safe[np.newaxis, :, :]
        out_n = args.out_dir / "tempo_amf_adj_layer_weight_normalized_72bands.tif"
        with rasterio.open(out_n, "w", **prof72) as dst:
            for b in range(72):
                plane = np.where(np.isnan(norm_stack[b]), out_nodata, norm_stack[b])
                dst.write(plane.astype(np.float64), b + 1)
        print(f"Wrote {out_n}")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
