# Eaton — smoke plume / PlanetScope + TEMPO NO₂

Southern California case study: PlanetScope imagery and TEMPO L2 NO₂ for smoke plume analysis.

## Repository contents

- **`data/tempo/warp_tempo_subdatasets_utm11_clipped.bat`** — GDAL `gdalwarp` batch for selected TEMPO NetCDF subdatasets to a fixed UTM 11 grid (matches clipped study extent).
- **`data/planet/*_metadata.json`** — Planet scene metadata (acquisition times, satellite IDs).
- **`data/shapefiles/`** — AOI box shapefile.
- **`data/case.json`** — Case notes.

Large rasters (**`.tif`**, **`.nc`**) are **not** tracked; store them locally or use cloud/object storage.

## Remote

Upstream: [github.com/wrtcd/eaton](https://github.com/wrtcd/eaton)
