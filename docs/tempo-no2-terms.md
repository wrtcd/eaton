# TEMPO NO₂ — short glossary (ATBD-aligned, this repo)

For the same glossary with Unicode subscripts (no HTML math), see **`docs/tempo-no2-terms-unicode.md`**.

Layer index **k** = 72 `swt_level` bins; **trop** = layers between tropopause and surface in hybrid pressure.

## 2D fields (per pixel, after warp to study grid)

- **SCD** — Slant column density from **`fitted_slant_column`** (NO₂ along the path). Typical units: molecules cm⁻².
- **AMF** — Air mass factor: relates slant column to vertical column for the assumed atmosphere and geometry. Tropospheric product field: **`amf_troposphere`**.
- **VCD** — Vertical column density; here usually tropospheric column. Product field: **`vertical_column_troposphere`**. Operationally **VCD ≈ SCD / AMF** when using the retrieval’s tropospheric AMF.

## Layer-resolved ATBD pieces (sum over k)

- **Wₖ** — Scattering weight for layer *k* (altitude sensitivity) from **`scattering_weights`**. (ATBD uses *W*; L2 does not provide a separate variable named “averaging kernel.”)
- **nₖ** — Partial column in layer *k* from **`gas_profile`** (molecules cm⁻²).
- **Sₖ** — Normalized prior shape:

  **Sₖ = nₖ / (Σ n_j)** with the sum over tropospheric layers *j* only (same **n_j** as in **`gas_profile`**).

- **cₖ** — Temperature correction (ATBD Eq. 18) using **Tₖ** from **`temperature_profile`** and **Tσ = 220 K** (reference temperature in the ATBD).
- **AMF_trop** — Tropospheric AMF recomputed here as:

  **AMF_trop ≈ Σ Wₖ Sₖ cₖ** (sum over **k** in the troposphere).

  Raster: **`tempo_amf_trop_atbd.tif`**.

## Optional (custom profile — not default in code)

- **wₖ** — User-defined normalized vertical profile (e.g. smoke). Would **replace Sₖ** in **Σ Wₖ wₖ cₖ** (sum over **k** in the troposphere). Current scripts use prior **Sₖ** only.

## Consistency check

- **VCD_check** — **VCD_check = SCD / AMF_trop** using **`fitted_slant_column`** and **`tempo_amf_trop_atbd.tif`**. Optional QA mask: **`tempo_mask_screen_utm11_clipped.tif`**. Compare to product **VCD** when inputs align.

## Scripts

- **`scripts/tempo/amf_atbd_from_tempo.py`** — **AMF_trop** and layer stacks.
- **`scripts/tempo/vcd_check_scd_amf.py`** — **VCD_check**.

See **`docs/pipeline-assumptions.md`** for full assumptions.
