"""
Validate that TEMPO GeoTIFFs (warped 2D layers + optional regridded 3D stacks)
share the same grid as a reference raster (CRS, dimensions, geotransform).

Usage (defaults: GeoTIFFs in step-by-step/03 tempo/, reference: VCD troposphere there):
  py -3 scripts/tempo/validate_tempo_stack.py
  py -3 scripts/tempo/validate_tempo_stack.py --dir data/tempo --reference tempo_vcd_troposphere_utm11_clipped.tif

Requires: rasterio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STEP03 = _REPO_ROOT / "step-by-step" / "03 tempo"

# warp_tempo_subdatasets_utm11_clipped.bat (2D) + regrid_tempo_3d_to_reference.py (72 bands each)
EXPECTED = (
    "tempo_qa_main_data_quality_flag_utm11_clipped.tif",
    "tempo_sup_ground_pixel_quality_flag_utm11_clipped.tif",
    "tempo_sup_amf_diagnostic_flag_utm11_clipped.tif",
    "tempo_sup_fitted_slant_column_utm11_clipped.tif",
    "tempo_sup_fitted_slant_column_uncertainty_utm11_clipped.tif",
    "tempo_vcd_troposphere_utm11_clipped.tif",
    "tempo_vcd_troposphere_uncertainty_utm11_clipped.tif",
    "tempo_sup_eff_cloud_fraction_utm11_clipped.tif",
    "tempo_sup_amf_troposphere_utm11_clipped.tif",
    "tempo_sup_amf_total_utm11_clipped.tif",
    "tempo_sup_scattering_weights_utm11_clipped.tif",
    "tempo_sup_gas_profile_utm11_clipped.tif",
    "tempo_sup_temperature_profile_utm11_clipped.tif",
)


def main() -> int:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from validation.grid_stack import validate_layers_against_reference

    p = argparse.ArgumentParser(description="Validate TEMPO stack alignment.")
    p.add_argument(
        "--reference",
        type=Path,
        default=_STEP03 / "tempo_vcd_troposphere_utm11_clipped.tif",
        help="Reference GeoTIFF (grid to match). Default: step-by-step/03 tempo/tempo_vcd_troposphere_utm11_clipped.tif",
    )
    p.add_argument(
        "--dir",
        type=Path,
        default=_STEP03,
        help="Directory containing warped GeoTIFFs (default: step-by-step/03 tempo).",
    )
    args = p.parse_args()

    ref_path = args.reference if args.reference.is_absolute() else (args.dir / args.reference)
    ok = validate_layers_against_reference(ref_path, args.dir, EXPECTED, single_band_only=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
