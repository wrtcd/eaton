"""
Shared helpers: compare GeoTIFFs to a reference grid (CRS, shape, affine).

Used by scripts/validation/validate_*_stack.py and scripts/tempo/validate_tempo_stack.py.

Requires: rasterio
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import rasterio
    from rasterio.crs import CRS
except ImportError:
    print("Install rasterio: py -3 -m pip install rasterio", file=sys.stderr)
    raise


def read_raster_meta(path: Path) -> dict:
    with rasterio.open(path) as ds:
        return {
            "crs": ds.crs,
            "shape": (ds.height, ds.width),
            "transform": ds.transform,
            "bounds": ds.bounds,
            "dtype": ds.dtypes[0],
            "count": ds.count,
        }


def same_transform(a, b, tol: float = 1e-3) -> bool:
    ta = [a.a, a.b, a.c, a.d, a.e, a.f]
    tb = [b.a, b.b, b.c, b.d, b.e, b.f]
    return all(abs(x - y) <= tol for x, y in zip(ta, tb))


def crs_equal(c1, c2) -> bool:
    if c1 is None or c2 is None:
        return False
    try:
        return CRS.from_string(str(c1)) == CRS.from_string(str(c2))
    except Exception:
        return str(c1) == str(c2)


def validate_layers_against_reference(
    ref_path: Path,
    dir_path: Path,
    expected_filenames: tuple[str, ...],
    *,
    single_band_only: bool = True,
) -> bool:
    """
    Print one line per expected file. Returns True if all present and aligned.
    """
    if not ref_path.is_file():
        print(f"ERROR: Reference not found: {ref_path}", file=sys.stderr)
        return False

    ref = read_raster_meta(ref_path)
    ref_crs = ref["crs"]
    if ref_crs is None:
        print("ERROR: Reference has no CRS.", file=sys.stderr)
        return False

    print(f"Reference: {ref_path.name}")
    print(f"  CRS: {ref_crs}")
    print(f"  Shape (H,W): {ref['shape']}")
    print(f"  Bounds: {ref['bounds']}")
    print(f"  Transform: {ref['transform']}")
    print()

    all_ok = True
    for name in expected_filenames:
        fp = dir_path / name
        status = "OK"
        detail = ""
        if not fp.is_file():
            status = "MISSING"
            detail = "file not found"
            all_ok = False
        else:
            m = read_raster_meta(fp)
            if not crs_equal(m["crs"], ref_crs):
                status = "CRS_MISMATCH"
                detail = f"got {m['crs']}"
                all_ok = False
            elif m["shape"] != ref["shape"]:
                status = "SHAPE_MISMATCH"
                detail = f"got {m['shape']}"
                all_ok = False
            elif not same_transform(m["transform"], ref["transform"]):
                status = "TRANSFORM_MISMATCH"
                detail = f"got {m['transform']}"
                all_ok = False
            elif single_band_only and m["count"] != 1:
                status = "BAND_COUNT"
                detail = f"expected 1 band, got {m['count']}"
                all_ok = False
            elif m["count"] != 1:
                detail = f"aligned ({m['count']} bands)"

        print(f"[{status:18}] {name}: {detail or 'aligned'}")

    print()
    if all_ok:
        print("PASS: all expected layers match the reference grid.")
    else:
        print("FAIL: fix missing files or re-warp with the same -te -ts -t_srs as the reference.")
    return all_ok
