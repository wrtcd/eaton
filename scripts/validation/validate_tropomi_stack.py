"""
Validate Sentinel-5P / TROPOMI NO₂ L2 layers warped to the **same** grid as a reference GeoTIFF
(same workflow as scripts/tempo/validate_tempo_stack.py).

Edit EXPECTED below to match the filenames you write after gdalwarp to your study grid
(typically EPSG:32611 + same extent as `tempo_vcd_troposphere_utm11_clipped.tif`).

Usage:
  py -3 scripts/validation/validate_tropomi_stack.py
  py -3 scripts/validation/validate_tropomi_stack.py --dir data/tropomi --reference tropomi_no2_tropo_utm11_clipped.tif

Requires: rasterio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _REPO_ROOT / "data" / "tropomi"

# Placeholder names — replace with your warped S5P NO2 subdatasets (single-band GeoTIFFs each).
EXPECTED = (
    "tropomi_no2_troposphere_column_utm11_clipped.tif",
    "tropomi_no2_troposphere_column_precision_utm11_clipped.tif",
    "tropomi_cloud_fraction_utm11_clipped.tif",
    "tropomi_tropopause_pressure_utm11_clipped.tif",
)


def main() -> int:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from validation.grid_stack import validate_layers_against_reference

    p = argparse.ArgumentParser(description="Validate TROPOMI (S5P NO2) stack vs reference grid.")
    p.add_argument(
        "--reference",
        type=Path,
        default=None,
        help="Reference GeoTIFF (e.g. TEMPO VCD on study grid). Default: --dir / tropomi_no2_troposphere_column_utm11_clipped.tif if present, else first EXPECTED name.",
    )
    p.add_argument(
        "--dir",
        type=Path,
        default=_DEFAULT_DIR,
        help=f"Directory with warped TROPOMI GeoTIFFs (default: { _DEFAULT_DIR.relative_to(_REPO_ROOT) }).",
    )
    args = p.parse_args()

    ref = args.reference
    if ref is None:
        cand = args.dir / EXPECTED[0]
        ref = cand if cand.is_file() else (args.dir / "tropomi_no2_troposphere_column_utm11_clipped.tif")

    ref_path = ref if ref.is_absolute() else (args.dir / ref)
    ok = validate_layers_against_reference(ref_path, args.dir, EXPECTED, single_band_only=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
