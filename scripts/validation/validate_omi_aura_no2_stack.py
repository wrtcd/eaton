"""
Validate OMI Aura NO₂ (OMNO2 / OMI L2) layers warped to the **same** grid as a reference GeoTIFF
(same workflow as scripts/tempo/validate_tempo_stack.py).

Edit EXPECTED to match filenames after gdalwarp to your study grid.

Usage:
  py -3 scripts/validation/validate_omi_aura_no2_stack.py
  py -3 scripts/validation/validate_omi_aura_no2_stack.py --dir data/omi --reference omi_no2_column_utm11_clipped.tif

Requires: rasterio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _REPO_ROOT / "data" / "omi_aura"

EXPECTED = (
    "omi_no2_column_utm11_clipped.tif",
    "omi_no2_column_uncertainty_utm11_clipped.tif",
    "omi_cloud_fraction_utm11_clipped.tif",
    "omi_terrain_height_utm11_clipped.tif",
)


def main() -> int:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from validation.grid_stack import validate_layers_against_reference

    p = argparse.ArgumentParser(description="Validate OMI Aura NO2 stack vs reference grid.")
    p.add_argument(
        "--reference",
        type=Path,
        default=None,
        help="Reference GeoTIFF. Default: --dir / first EXPECTED name if it exists.",
    )
    p.add_argument("--dir", type=Path, default=_DEFAULT_DIR, help="Warped OMI GeoTIFF directory.")
    args = p.parse_args()

    ref = args.reference
    if ref is None:
        cand = args.dir / EXPECTED[0]
        ref = cand if cand.is_file() else (args.dir / "omi_no2_column_utm11_clipped.tif")

    ref_path = ref if ref.is_absolute() else (args.dir / ref)
    ok = validate_layers_against_reference(ref_path, args.dir, EXPECTED, single_band_only=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
