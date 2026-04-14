# Eaton — smoke plume / PlanetScope + TEMPO NO₂

Southern California case study: PlanetScope imagery and TEMPO L2 NO₂ for smoke plume analysis.

## Layout

| Path | Contents |
|------|----------|
| **`data/aoi/`** | Hand-drawn plume mask `mask.shp` (2 polygons); methodology PDFs `masscal.pdf`, `method.pdf` |
| **`data/planet/metadata/`** | Planet scene metadata (JSON) |
| **`data/planet/`** | Local Planet rasters (e.g. mosaics); not tracked |
| **`data/tempo/`** | Local TEMPO NetCDF; not tracked (folder kept via `.gitkeep`). Warped/regridded GeoTIFFs live under **`step-by-step/03 tempo/`**. |
| **`data/case.json`** | Case notes and paths to key rasters |
| **`docs/pipeline-assumptions.md`** | Pipeline assumptions (AMF, AMF_adj, regridding, masks) |
| **`step-by-step/06 vcd check/`** | \(VCD_{\mathrm{check}} = SCD / AMF_{\mathrm{trop}}\) from **`vcd_check_scd_amf.py`** |
| **`step-by-step/08 mass/`** | NO₂ mass + figures — **`mass_no2_from_plume.py`** |
| **`scripts/tempo/`** | GDAL batch and Python tools for TEMPO |

## Scripts (`scripts/tempo/`)

- **`warp_tempo_subdatasets_utm11_clipped.bat`** — GDAL `gdalwarp` for selected TEMPO NetCDF subdatasets to a fixed UTM 11 grid (matches clipped study extent). Writes into **`step-by-step/03 tempo/`** (launch via **`step-by-step/03 tempo/run_warp_tempo.bat`**).
- **`regrid_tempo_3d_to_reference.py`** — Regrid 3D NetCDF fields (`scattering_weights`, `gas_profile`, `temperature_profile`; 72 bands each) to the same grid as a reference GeoTIFF.
- **`screen_tempo_pixels.py`** — Build a QA/cloud/VCD validity mask (defaults: **`step-by-step/03 tempo`**).
- **`run_pipeline_tempo_plume_amf.bat`** — Screen → **\(f_p\)** → ATBD AMF (uses **`smoke`** venv if present).
- **`validate_tempo_stack.py`** — Check that warped layers share one grid.
- **`amf_atbd_from_tempo.py`** — ATBD tropospheric AMF and layer \(W S c\) stacks; assumptions in **`docs/pipeline-assumptions.md`**.
- **`vcd_check_scd_amf.py`** — \(VCD_{\mathrm{check}} =\) **`fitted_slant_column` / `tempo_amf_trop_atbd.tif`** (optional QA screen); writes **`06 vcd check/`**.
- **`delta_vcd_plume.py`** — \(\Delta VCD\), \(\Delta VCD_{\mathrm{plume}} = f_p \cdot \Delta VCD\); writes **`07 plume delta/`**.
- **`mass_no2_from_plume.py`** — \(\mathrm{kg}_{NO_2}\) per pixel + PNG maps/histogram; writes **`08 mass/`**.

Large rasters (**`.tif`**, **`.nc`**) are **not** tracked; store them under `data/tempo/` or `data/planet/` locally or use cloud/object storage.

## Remote

Upstream: [github.com/wrtcd/eaton](https://github.com/wrtcd/eaton)
