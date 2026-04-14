# Step-by-step pipeline

This document describes **what we implemented** in the Eaton project: from Planet + TEMPO Level-2 data through plume fraction, columns, screening, adjusted-column checks, plume \(\Delta\)column, and NO₂ mass, with outputs under each numbered folder.

**Broader assumptions** (AMF theory, screening thresholds, units) are in **`docs/pipeline-assumptions.md`**.

---

## Flow overview

```text
AOI / mask  +  Planet mosaic  +  TEMPO L2 NetCDF
        │              │                    │
        │              │                    ├──► gdalwarp → 03 tempo/ (UTM11 stacks)
        │              │                    │
        │              └──► f_p (Planet → TEMPO grid) ──► 04 plume fraction/
        │                              │
        └──► (same TEMPO grid) ◄────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   QA/cloud    ATBD AMF      VCD_check = SCD / AMF_trop
   screen      05 amf adj/   06 vcd check/
   mask in
   03 tempo/
        │
        ▼
   ΔVCD, ΔVCD_plume = f_p · ΔVCD  ──►  07 plume delta/
        │
        ▼
   NO₂ mass + figures  ──►  08 mass/
```

Run **everything after warping** (screen → f_p → AMF → …) with:

`scripts/tempo/run_pipeline_tempo_plume_amf.bat` (then **06–08** scripts below).

---

## Summary table

| Step | Folder | What it is |
|------|--------|------------|
| **1** | `01 aoi/` | Study AOI / context vectors |
| **2** | `02 planet/` | Planet mosaic (e.g. QGIS merge); path also in `data/case.json` → `planet` |
| **3** | `03 tempo/` | Warped TEMPO GeoTIFFs + QA/cloud **screen mask** |
| **4** | `04 plume fraction/` | **\(f_p\)** — plume mask fraction on TEMPO grid |
| **5** | `05 amf adj/` | ATBD **tropospheric AMF** recomputed + optional 72-band layer terms |
| **6** | `06 vcd check/` | **\(VCD_{\mathrm{check}} = SCD / AMF_{\mathrm{trop}}\)** |
| **7** | `07 plume delta/` | **\(\Delta VCD\)**, **\(\Delta VCD_{\mathrm{plume}} = f_p \cdot \Delta VCD\)** |
| **8** | `08 mass/` | **NO₂ mass** per pixel (kg), JSON summary, **PNG** maps/histograms |

---

## Step 1 — AOI

- **Purpose:** Define study context / vectors (`step-by-step/01 aoi/`, `data/aoi/`).
- **Plume mask for \(f_p\):** `data/aoi/mask.shp` (vector polygons).

---

## Step 2 — Planet

- **Purpose:** High-resolution **Planet GeoTIFF** (mosaic or scene) that defines the grid for burning the plume mask.
- **Config:** `data/case.json` → `"planet"` path (repo-relative or under `data/`).
- **Example folder:** `step-by-step/02 planet/` (e.g. `mosaic.tif`).
- **Note:** If NoData = 0, confirm 0 is not a valid class in your classification band.

---

## Step 3 — TEMPO on the study grid

- **Purpose:** Bring TEMPO L2 variables to **EPSG:32611** (UTM 11N), same extent/resolution as your clipped study area.
- **Tools:** `scripts/tempo/warp_tempo_subdatasets_utm11_clipped.bat` (2D layers); `regrid_tempo_3d_to_reference.py` for **72-band** `scattering_weights`, `gas_profile`, `temperature_profile`.
- **Typical outputs folder:** `step-by-step/03 tempo/` (e.g. `tempo_vcd_troposphere_utm11_clipped.tif`, `tempo_sup_fitted_slant_column_utm11_clipped.tif`, QA flags, `eff_cloud_fraction`, etc.).

### Screening (QA + cloud + valid VCD)

- **Script:** `scripts/tempo/screen_tempo_pixels.py`
- **Writes:** `tempo_mask_screen_utm11_clipped.tif` (uint8: **1** = pass, **0** = fail).
- **Default rules:** `main_data_quality_flag <= 0`; `eff_cloud_fraction <= 0.3`; tropospheric **VCD** finite (not fill).
- **Defaults:** `--dir` points at **`step-by-step/03 tempo`**.

This mask is used downstream for **\(f_p\)**, **AMF**, and **\(VCD_{\mathrm{check}}\)** unless you disable screening in each script.

---

## Step 4 — Plume fraction \(f_p\)

- **Purpose:** For each TEMPO pixel, **\(f_p\)** = mean of the binary plume mask on the Planet grid (fraction of cell covered by plume), in \([0,1]\).
- **Script:** `scripts/fp_planet_mask_to_tempo.py`
- **Output:** `step-by-step/04 plume fraction/tempo_fp_plume_utm11_clipped.tif`
- **Screening:** If `03 tempo/tempo_mask_screen_utm11_clipped.tif` exists, failing pixels get **nodata −9999** (use `--no-tempo-screen` to skip).
- **Deps:** `rasterio`, `numpy`, **`pyogrio`** + **`geopandas`** (or Fiona) for vector mask.

```text
py -3 scripts/fp_planet_mask_to_tempo.py
```

---

## Step 5 — AMF (ATBD tropospheric)

- **Purpose:** Recompute **tropospheric AMF** as in TEMPO NO₂ ATBD §3.1.3: \(\sum_k W_k S_k c_k\) over tropospheric layers (**\(W\)** = scattering weights, **\(S\)** = normalized `gas_profile`, **\(c\)** = temperature correction).
- **Script:** `scripts/tempo/amf_atbd_from_tempo.py`
- **Input:** TEMPO L2 **NetCDF** (same granule as your warped stacks).
- **Output folder:** `step-by-step/05 amf adj/`
  - `tempo_amf_trop_atbd.tif`
  - Optional 72-band: `tempo_amf_adj_layer_contribution_W_S_c_72bands.tif`, `tempo_amf_adj_layer_weight_normalized_72bands.tif`
- **Screening:** Applied after regrid if the screen mask exists (`--no-screen` to skip).
- **Deps:** `netCDF4`, `rasterio`, `scipy`, `pyproj`

```text
py -3 scripts/tempo/amf_atbd_from_tempo.py --write-bands --compare-product
```

---

## Step 6 — \(VCD_{\mathrm{check}}\) from SCD and AMF

- **Purpose:** **\(VCD_{\mathrm{check}} = SCD / AMF_{\mathrm{trop}}\)** using warped **fitted_slant_column** and **`tempo_amf_trop_atbd.tif`** (validation path; matches product AMF on native grid).
- **Script:** `scripts/tempo/vcd_check_scd_amf.py`
- **Output:** `step-by-step/06 vcd check/tempo_vcd_check_scd_over_amf_trop.tif`
- **Screening:** Applied if the mask exists (`--no-screen` to skip).

```text
py -3 scripts/tempo/vcd_check_scd_amf.py
```

---

## Step 7 — \(\Delta VCD\) and \(\Delta VCD_{\mathrm{plume}}\)

- **Purpose:**
  - **\(VCD_{\mathrm{bg}}\)** = median of \(VCD_{\mathrm{check}}\) where **\(f_p \le 10^{-6}\)** (with fallbacks if needed; see JSON).
  - **\(\Delta VCD = VCD_{\mathrm{check}} - VCD_{\mathrm{bg}}\)**
  - **\(\Delta VCD_{\mathrm{plume}} = f_p \cdot \Delta VCD\)**
- **Script:** `scripts/tempo/delta_vcd_plume.py`
- **Outputs:** `step-by-step/07 plume delta/`
  - `tempo_delta_vcd.tif`
  - `tempo_delta_vcd_plume.tif`
  - `tempo_delta_vcd_plume_meta.json`

```text
py -3 scripts/tempo/delta_vcd_plume.py
```

---

## Step 8 — NO₂ mass and figures

- **Purpose:** Per-pixel **kg NO₂** from \(\Delta VCD_{\mathrm{plume}}\) (molecules/cm²) × pixel area (cm²) / **\(N_A\)** × **\(M_{NO_2}\)**.
- **Script:** `scripts/tempo/mass_no2_from_plume.py`
- **Outputs:** `step-by-step/08 mass/`
  - `tempo_mass_no2_kg_per_pixel.tif`
  - `tempo_plume_mass_summary.json` (includes totals: all pixels vs positive-only)
  - `figures/` — PNG maps (ΔVCD_plume, mass linear/log) and histogram

```text
py -3 scripts/tempo/mass_no2_from_plume.py
```

---

## Batch helpers

| File | Role |
|------|------|
| `scripts/tempo/run_pipeline_tempo_plume_amf.bat` | Screen → **\(f_p\)** → AMF (with **`smoke`** venv if present) |
| `04 plume fraction/run_fp.bat` | **\(f_p\)** only |
| `06 vcd check/run_vcd_check.bat` | Step 6 |
| `07 plume delta/run_delta_vcd_plume.bat` | Step 7 |
| `08 mass/run_mass_no2.bat` | Step 8 |

---

## What is *not* automated (optional next work)

- Custom **\(w(z)\)** **\(AMF_{\mathrm{adj}}\)** and **\(VCD_{\mathrm{adj}}\)** with that AMF (see ATBD / advisor).
- Full **uncertainty** propagation.
- Alternate **\(VCD_{\mathrm{bg}}\)** (e.g. buffer outside plume only).
- Publication-quality maps (cartopy, scale bars, etc.).

---

## Dependencies (typical)

Activate **`smoke`** venv from repo root when using the batch files. Python packages used across steps include: **numpy**, **rasterio**, **netCDF4**, **scipy**, **pyproj**, **matplotlib**, **pyogrio**, **geopandas**.

GDAL/QGIS paths for **`warp`** batches: see **`scripts/env_smoke_gdal.bat`**.
