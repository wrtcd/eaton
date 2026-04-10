"""
Build a per-pixel validity mask for TEMPO L2 rasters on the clipped UTM grid.

Rules (defaults):
  - main_data_quality_flag: keep pixels with flag <= --qa-main-max (default 0 = normal only).
  - eff_cloud_fraction: keep pixels with value <= --cloud-max (default 0.3).
  - vertical_column_troposphere: drop non-finite values and GDAL/NetCDF fill (~ -1e30).

Writes uint8 GeoTIFF: 1 = passes all rules, 0 = fails at least one.

Usage (defaults: inputs in step-by-step/03/, reference grid in data/tempo/):
  py -3 scripts/tempo/screen_tempo_pixels.py
  py -3 scripts/tempo/screen_tempo_pixels.py --qa-main-max 1 --cloud-max 0.2

Requires: numpy, rasterio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import rasterio
    from rasterio.crs import CRS
except ImportError:
    print("Install rasterio: py -3 -m pip install rasterio", file=sys.stderr)
    sys.exit(1)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_TEMPO = _REPO_ROOT / "data" / "tempo"
_STEP03 = _REPO_ROOT / "step-by-step" / "03"

DEFAULT_QA = "tempo_qa_main_data_quality_flag_utm11_clipped.tif"
DEFAULT_CLOUD = "tempo_sup_eff_cloud_fraction_utm11_clipped.tif"
DEFAULT_VCD = "tempo_vcd_troposphere_utm11_clipped.tif"
DEFAULT_REF = "tempo_no2_utm11_clipped.tif"
DEFAULT_OUT = "tempo_mask_screen_utm11_clipped.tif"


def _crs_equal(c1, c2) -> bool:
    if c1 is None or c2 is None:
        return False
    try:
        return CRS.from_string(str(c1)) == CRS.from_string(str(c2))
    except Exception:
        return str(c1) == str(c2)


def _same_transform(a, b, tol: float = 1e-3) -> bool:
    ta = [a.a, a.b, a.c, a.d, a.e, a.f]
    tb = [b.a, b.b, b.c, b.d, b.e, b.f]
    return all(abs(x - y) <= tol for x, y in zip(ta, tb))


def _vcd_valid(vcd: np.ndarray, nodata: float | None) -> np.ndarray:
    ok = np.isfinite(vcd)
    if nodata is not None and np.isfinite(nodata):
        ok &= vcd != nodata
    # NetCDF/GDAL fill often warps to ~ -1e30 even if tagged
    ok &= vcd > -1e20
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description="Screen TEMPO pixels (QA, cloud, VCD nodata).")
    p.add_argument("--dir", type=Path, default=_STEP03, help="GeoTIFF directory (warped layers; mask written here).")
    p.add_argument(
        "--reference",
        type=Path,
        default=_DATA_TEMPO / DEFAULT_REF,
        help="Raster to match CRS/shape/transform (default: data/tempo reference).",
    )
    p.add_argument("--qa", default=DEFAULT_QA, help="main_data_quality_flag GeoTIFF.")
    p.add_argument("--cloud", default=DEFAULT_CLOUD, help="eff_cloud_fraction GeoTIFF.")
    p.add_argument("--vcd", default=DEFAULT_VCD, help="tropospheric column GeoTIFF (nodata check).")
    p.add_argument(
        "--qa-main-max",
        type=int,
        default=0,
        help="Keep pixels with main_data_quality_flag <= this (0=normal only; 1 allows suspicious).",
    )
    p.add_argument(
        "--cloud-max",
        type=float,
        default=0.3,
        help="Keep pixels with eff_cloud_fraction <= this.",
    )
    p.add_argument("-o", "--output", default=DEFAULT_OUT, help="Output mask filename (uint8).")
    args = p.parse_args()
    base = args.dir

    ref_path = args.reference if args.reference.is_absolute() else (base / args.reference)
    qa_path = base / args.qa
    cloud_path = base / args.cloud
    vcd_path = base / args.vcd
    out_path = base / args.output

    for path, label in (
        (ref_path, "reference"),
        (qa_path, "QA"),
        (cloud_path, "cloud"),
        (vcd_path, "VCD"),
    ):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 1

    with rasterio.open(ref_path) as ref:
        ref_crs = ref.crs
        ref_shape = (ref.height, ref.width)
        ref_transform = ref.transform
        ref_profile = ref.profile.copy()
        if ref_crs is None:
            print("ERROR: Reference has no CRS.", file=sys.stderr)
            return 1

    def _check_grid(name: str, ds: rasterio.io.DatasetReader) -> bool:
        if not _crs_equal(ds.crs, ref_crs) or (ds.height, ds.width) != ref_shape:
            print(
                f"ERROR: {name} grid mismatch vs reference (CRS or shape).",
                file=sys.stderr,
            )
            return False
        if not _same_transform(ds.transform, ref_transform):
            print(
                f"ERROR: {name} geotransform mismatch vs reference.",
                file=sys.stderr,
            )
            return False
        return True

    with rasterio.open(qa_path) as ds:
        if not _check_grid("QA", ds):
            return 1
        qa_arr = ds.read(1)

    with rasterio.open(cloud_path) as ds:
        if not _check_grid("cloud", ds):
            return 1
        cloud_arr = ds.read(1)

    with rasterio.open(vcd_path) as ds:
        if not _check_grid("VCD", ds):
            return 1
        vcd_nodata = ds.nodata
        vcd_arr = ds.read(1)

    main_qa = np.rint(qa_arr).astype(np.int32)
    cloud = cloud_arr.astype(np.float64)
    vcd = vcd_arr.astype(np.float64)

    ok_qa = main_qa <= int(args.qa_main_max)
    ok_cloud = np.isfinite(cloud) & (cloud <= float(args.cloud_max))
    ok_vcd = _vcd_valid(vcd, vcd_nodata)

    valid = ok_qa & ok_cloud & ok_vcd
    mask_u8 = valid.astype(np.uint8)

    n = mask_u8.size
    n_ok = int(mask_u8.sum())
    n_bad_qa = int(np.sum(~ok_qa))
    n_bad_cloud = int(np.sum(~ok_cloud))
    n_bad_vcd = int(np.sum(~ok_vcd))

    profile = ref_profile.copy()
    profile.update(count=1, dtype="uint8", nodata=None, compress="deflate", predictor=2)
    profile["tiled"] = True
    profile["blockxsize"] = 256
    profile["blockysize"] = 256

    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(mask_u8, 1)

    print(f"Reference: {ref_path.name}  shape={ref_shape}  CRS={ref_crs}")
    print(f"Rules: main_data_quality_flag <= {args.qa_main_max}, eff_cloud_fraction <= {args.cloud_max}, VCD finite/not fill")
    print(f"Wrote {out_path.name}  (1=pass, 0=fail)")
    print(f"Valid pixels: {n_ok} / {n} ({100.0 * n_ok / n:.2f}%)")
    print(f"Pixels failing QA (flag > {args.qa_main_max}): {n_bad_qa}")
    print(f"Pixels failing cloud (nonfinite or > {args.cloud_max}): {n_bad_cloud}")
    print(f"Pixels failing VCD (nodata/fill): {n_bad_vcd}")
    print("Note: failure counts overlap; use mask for strict AND of all rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
