"""
Regrid TEMPO L2 3D fields (mirror_step x xtrack x swt_level) onto the same
UTM grid as a reference GeoTIFF.

Uses lat/lon -> target CRS, then scipy.interpolate.griddata (linear) onto
reference pixel centers. Source points are subsampled per layer for speed
(--max-points; default 50000).

Outputs (72 bands each):
  - tempo_sup_scattering_weights_utm11_clipped.tif
  - tempo_sup_gas_profile_utm11_clipped.tif
  - tempo_sup_temperature_profile_utm11_clipped.tif

Usage (defaults: NetCDF in data/tempo/; reference + 72-band outputs in step-by-step/03):
  py -3 scripts/tempo/regrid_tempo_3d_to_reference.py
  py -3 scripts/tempo/regrid_tempo_3d_to_reference.py --max-points 80000 --seed 42

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
_STEP03 = _REPO_ROOT / "step-by-step" / "03"

VARS_DEFAULT = (
    ("support_data", "scattering_weights", "tempo_sup_scattering_weights_utm11_clipped.tif"),
    ("support_data", "gas_profile", "tempo_sup_gas_profile_utm11_clipped.tif"),
    ("support_data", "temperature_profile", "tempo_sup_temperature_profile_utm11_clipped.tif"),
)


def _fill_value(var: nc.Variable) -> float:
    fv = getattr(var, "_FillValue", None)
    if fv is None:
        return np.nan
    return float(fv)


def _subsample(
    pts: np.ndarray,
    vals: np.ndarray,
    max_points: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    n = pts.shape[0]
    if n <= max_points:
        return pts, vals
    idx = rng.choice(n, size=max_points, replace=False)
    return pts[idx], vals[idx]


def regrid_stack(
    data: np.ndarray,
    fill_value: float,
    pts: np.ndarray,
    dest_x: np.ndarray,
    dest_y: np.ndarray,
    max_points: int,
    seed: int,
) -> np.ndarray:
    """data (H, W, n_levels); pts (N,2) source UTM coords for each pixel."""
    n_levels = data.shape[2]
    height, width = dest_x.shape
    out = np.empty((n_levels, height, width), dtype=np.float64)
    rng = np.random.default_rng(seed)

    for k in range(n_levels):
        vals = data[:, :, k].ravel().astype(np.float64)
        m = np.isfinite(vals)
        if np.isfinite(fill_value):
            m &= vals != fill_value
        p = pts[m]
        v = vals[m]
        if p.size == 0:
            out[k] = np.full(dest_x.shape, np.nan, dtype=np.float64)
            continue
        p, v = _subsample(p, v, max_points, rng)
        t0 = time.perf_counter()
        out[k] = griddata(p, v, (dest_x, dest_y), method="linear", fill_value=np.nan)
        if (k + 1) % 12 == 0 or k == 0:
            dt = time.perf_counter() - t0
            print(f"    level {k + 1}/{n_levels} ({dt:.2f}s this layer)")

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Regrid TEMPO 3D NetCDF fields to reference grid.")
    ap.add_argument("--nc", type=Path, default=_DATA_TEMPO / "TEMPO_NO2_L2_V03_20250109T184504Z_S008G09.nc")
    ap.add_argument(
        "--reference",
        type=Path,
        default=_STEP03 / "tempo_vcd_troposphere_utm11_clipped.tif",
        help="Reference GeoTIFF (grid to match). Default: step-by-step/03/tempo_vcd_troposphere_utm11_clipped.tif",
    )
    ap.add_argument("--out-dir", type=Path, default=_STEP03)
    ap.add_argument("--max-points", type=int, default=50000, help="Max source points per layer (subsample for speed).")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for subsampling.")
    args = ap.parse_args()

    if not args.nc.is_file():
        print(f"ERROR: NetCDF not found: {args.nc}", file=sys.stderr)
        return 1
    if not args.reference.is_file():
        print(f"ERROR: Reference raster not found: {args.reference}", file=sys.stderr)
        return 1

    with rasterio.open(args.reference) as ref:
        crs = ref.crs
        transform = ref.transform
        height, width = ref.height, ref.width
        if crs is None:
            print("ERROR: Reference has no CRS.", file=sys.stderr)
            return 1

    rows, cols = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
    dest_x, dest_y = transform_xy(transform, rows, cols, offset="center")
    dest_x = np.asarray(dest_x, dtype=np.float64)
    dest_y = np.asarray(dest_y, dtype=np.float64)
    if dest_x.ndim != 2:
        dest_x = dest_x.reshape(height, width)
        dest_y = dest_y.reshape(height, width)

    ds = nc.Dataset(str(args.nc))
    lat = ds["geolocation"]["latitude"][:].astype(np.float64)
    lon = ds["geolocation"]["longitude"][:].astype(np.float64)

    transformer = Transformer.from_crs("EPSG:4326", crs.to_string(), always_xy=True)
    src_x, src_y = transformer.transform(lon, lat)
    pts = np.column_stack([src_x.ravel(), src_y.ravel()])

    for group_name, var_name, out_name in VARS_DEFAULT:
        var = ds.groups[group_name][var_name]
        data = np.asarray(var[:], dtype=np.float64)
        fill_value = _fill_value(var)
        print(f"{group_name}/{var_name} shape={data.shape}, fill={fill_value}, max_points={args.max_points}")

        t_all = time.perf_counter()
        arr = regrid_stack(data, fill_value, pts, dest_x, dest_y, args.max_points, args.seed)
        print(f"  total regrid time: {time.perf_counter() - t_all:.1f}s")

        out_nodata = -1.0e30
        out_arr = np.where(np.isnan(arr), out_nodata, arr)

        out_path = args.out_dir / out_name
        profile = {
            "driver": "GTiff",
            "width": width,
            "height": height,
            "count": arr.shape[0],
            "dtype": "float64",
            "crs": crs,
            "transform": transform,
            "nodata": out_nodata,
            "compress": "deflate",
            "predictor": 3,
        }
        with rasterio.open(out_path, "w", **profile) as dst:
            for b in range(arr.shape[0]):
                dst.write(out_arr[b].astype(np.float64), b + 1)
        print(f"  Wrote {out_path} ({arr.shape[0]} bands)")

    ds.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
