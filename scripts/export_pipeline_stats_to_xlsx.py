"""Write Eaton pipeline summary JSON stats to an Excel workbook."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_MASS_JSON = _REPO / "step-by-step" / "08 mass" / "tempo_plume_mass_summary.json"
_DELTA_META = _REPO / "step-by-step" / "07 plume delta" / "tempo_delta_vcd_plume_meta.json"
_OUT = _REPO / "eaton_pipeline_stats.xlsx"


def main() -> None:
    mass = json.loads(_MASS_JSON.read_text(encoding="utf-8"))
    delta_meta = json.loads(_DELTA_META.read_text(encoding="utf-8"))

    rows_mass = [
        ("CRS", mass["crs"]),
        ("Grid width (pixels)", mass["width"]),
        ("Grid height (pixels)", mass["height"]),
        ("Pixel area (m²)", mass["pixel_area_m2"]),
        ("Bounds left (m, EPSG:32611)", mass["bounds"]["left"]),
        ("Bounds right (m)", mass["bounds"]["right"]),
        ("Bounds bottom (m)", mass["bounds"]["bottom"]),
        ("Bounds top (m)", mass["bounds"]["top"]),
        ("Valid Δ pixels (count)", mass["n_valid_delta_pixels"]),
        ("Positive mass pixels (count)", mass["n_positive_mass_pixels"]),
        ("Negative mass pixels (count)", mass["n_negative_mass_pixels"]),
        ("Total NO₂ mass, all valid pixels (kg)", mass["total_no2_mass_kg_sum_all_pixels"]),
        ("Total NO₂ mass, positive-only (kg)", mass["total_no2_mass_kg_sum_positive_only"]),
        ("Molar mass NO₂ (kg/mol)", mass["molar_mass_no2_kg_per_mol"]),
        ("Avogadro (1/mol)", mass["avogadro"]),
        ("ΔVCD_plume raster", mass["delta_vcd_plume_path"]),
    ]
    df_mass = pd.DataFrame(rows_mass, columns=["Statistic", "Value"])

    rows_delta = [
        ("VCD background (molecules/cm²)", delta_meta["vcd_bg_molecules_cm2"]),
        ("VCD background method", delta_meta["vcd_bg_method"]),
        ("f_p epsilon", delta_meta["fp_eps"]),
        ("f_p low fallback", delta_meta["fp_low_fallback"]),
        ("VCD_check / input path", delta_meta["vcd_adj_path"]),
        ("f_p raster path", delta_meta["fp_path"]),
    ]
    df_delta = pd.DataFrame(rows_delta, columns=["Parameter", "Value"])

    notes = pd.DataFrame(
        [
            ("Source", str(_MASS_JSON)),
            ("", ""),
            ("Mass totals", "From tempo_plume_mass_summary.json after mass_no2_from_plume.py"),
            ("Delta params", "From tempo_delta_vcd_plume_meta.json after delta_vcd_plume.py"),
        ],
        columns=["Field", "Note"],
    )

    with pd.ExcelWriter(_OUT, engine="openpyxl") as w:
        df_mass.to_excel(w, sheet_name="Mass summary", index=False)
        df_delta.to_excel(w, sheet_name="Delta VCD parameters", index=False)
        notes.to_excel(w, sheet_name="Notes", index=False)

    print(f"Wrote {_OUT}")


if __name__ == "__main__":
    main()
