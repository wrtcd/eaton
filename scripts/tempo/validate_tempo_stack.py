"""
Validate that all TEMPO 2D GeoTIFFs from warp_tempo_subdatasets_utm11_clipped.bat
share the same grid as a reference raster (CRS, dimensions, geotransform).

Usage (defaults: GeoTIFFs in data/tempo/):
  py -3 scripts/tempo/validate_tempo_stack.py
  py -3 scripts/tempo/validate_tempo_stack.py --reference tempo_no2_utm11_clipped.tif

Requires: rasterio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import rasterio
    from rasterio.crs import CRS
except ImportError:
    print("Install rasterio: py -3 -m pip install rasterio", file=sys.stderr)
    sys.exit(1)

_DATA_TEMPO = Path(__file__).resolve().parents[2] / "data" / "tempo"

# Outputs produced by warp_tempo_subdatasets_utm11_clipped.bat (2D stack)
EXPECTED = (
    "tempo_qa_main_data_quality_flag_utm11_clipped.tif",
    "tempo_sup_ground_pixel_quality_flag_utm11_clipped.tif",
    "tempo_sup_amf_diagnostic_flag_utm11_clipped.tif",
    "tempo_vcd_troposphere_utm11_clipped.tif",
    "tempo_vcd_troposphere_uncertainty_utm11_clipped.tif",
    "tempo_sup_eff_cloud_fraction_utm11_clipped.tif",
    "tempo_sup_amf_troposphere_utm11_clipped.tif",
    "tempo_sup_amf_total_utm11_clipped.tif",
)


def _read_meta(path: Path):
    with rasterio.open(path) as ds:
        return {
            "crs": ds.crs,
            "shape": (ds.height, ds.width),
            "transform": ds.transform,
            "bounds": ds.bounds,
            "dtype": ds.dtypes[0],
            "count": ds.count,
        }


def _same_transform(a, b, tol: float = 1e-3) -> bool:
    """Compare Affine geotransform (tolerate tiny float drift)."""
    ta = [a.a, a.b, a.c, a.d, a.e, a.f]
    tb = [b.a, b.b, b.c, b.d, b.e, b.f]
    return all(abs(x - y) <= tol for x, y in zip(ta, tb))


def _crs_equal(c1, c2) -> bool:
    if c1 is None or c2 is None:
        return False
    try:
        return CRS.from_string(str(c1)) == CRS.from_string(str(c2))
    except Exception:
        return str(c1) == str(c2)


def main() -> int:
    p = argparse.ArgumentParser(description="Validate TEMPO stack alignment.")
    p.add_argument(
        "--reference",
        default="tempo_no2_utm11_clipped.tif",
        help="Reference GeoTIFF (original clipped troposphere).",
    )
    p.add_argument(
        "--dir",
        type=Path,
        default=_DATA_TEMPO,
        help="Directory containing GeoTIFFs.",
    )
    args = p.parse_args()

    ref_path = args.dir / args.reference
    if not ref_path.is_file():
        print(f"ERROR: Reference not found: {ref_path}", file=sys.stderr)
        return 1

    ref = _read_meta(ref_path)
    ref_crs = ref["crs"]
    if ref_crs is None:
        print("ERROR: Reference has no CRS.", file=sys.stderr)
        return 1

    print(f"Reference: {ref_path.name}")
    print(f"  CRS: {ref_crs}")
    print(f"  Shape (H,W): {ref['shape']}")
    print(f"  Bounds: {ref['bounds']}")
    print(f"  Transform: {ref['transform']}")
    print()

    all_ok = True
    for name in EXPECTED:
        fp = args.dir / name
        status = "OK"
        detail = ""
        if not fp.is_file():
            status = "MISSING"
            detail = "file not found"
            all_ok = False
        else:
            m = _read_meta(fp)
            if not _crs_equal(m["crs"], ref_crs):
                status = "CRS_MISMATCH"
                detail = f"got {m['crs']}"
                all_ok = False
            elif m["shape"] != ref["shape"]:
                status = "SHAPE_MISMATCH"
                detail = f"got {m['shape']}"
                all_ok = False
            elif not _same_transform(m["transform"], ref["transform"]):
                status = "TRANSFORM_MISMATCH"
                detail = f"got {m['transform']}"
                all_ok = False

        print(f"[{status:18}] {name}: {detail or 'aligned'}")

    print()
    if all_ok:
        print("PASS: all expected layers match the reference grid.")
        return 0
    print("FAIL: fix missing files or re-run warp with same -te -ts -t_srs.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
