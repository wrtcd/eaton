# Eaton — smoke plume / PlanetScope + TEMPO NO₂

Southern California case study: PlanetScope imagery and TEMPO L2 NO₂ for smoke plume analysis.

## Layout

| Path | Contents |
|------|----------|
| **`data/aoi/`** | AOI for tests: `circle` (+ `centroid`); methodology notes in `masscal.pdf`, `method.pdf` |
| **`data/planet/metadata/`** | Planet scene metadata (JSON) |
| **`data/planet/`** | Local Planet rasters (e.g. mosaics); not tracked |
| **`data/tempo/`** | Local TEMPO NetCDF and warped GeoTIFFs; not tracked (folder kept via `.gitkeep`) |
| **`data/case.json`** | Case notes and paths to key rasters |
| **`scripts/tempo/`** | GDAL batch and Python tools for TEMPO |

## Scripts (`scripts/tempo/`)

- **`warp_tempo_subdatasets_utm11_clipped.bat`** — GDAL `gdalwarp` for selected TEMPO NetCDF subdatasets to a fixed UTM 11 grid (matches clipped study extent). Writes into **`data/tempo/`**.
- **`regrid_tempo_3d_to_reference.py`** — Regrid 3D NetCDF fields to the same grid as a reference GeoTIFF.
- **`screen_tempo_pixels.py`** — Build a QA/cloud/VCD validity mask.
- **`validate_tempo_stack.py`** — Check that warped layers share one grid.

Large rasters (**`.tif`**, **`.nc`**) are **not** tracked; store them under `data/tempo/` or `data/planet/` locally or use cloud/object storage.

## Remote

Upstream: [github.com/wrtcd/eaton](https://github.com/wrtcd/eaton)
