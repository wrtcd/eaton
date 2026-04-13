# Step-by-step pipeline

| Step | Name | Status | Notes |
|------|------|--------|--------|
| **1** | AOI | Done | Study extent / context (`data/aoi/`, `step-by-step/01 aoi/`) |
| **2** | Planet | Ready | Mosaic under `data/planet/`; path in `data/case.json` |
| **3** | TEMPO | Ready | Warp, 3D regrid, validate (`scripts/tempo/`; outputs in `step-by-step/03/` or `step-by-step/03 tempo/`) |
| **4** | **f_p (Planet → TEMPO grid)** | Next | Plume mask fraction per TEMPO pixel — `scripts/fp_planet_mask_to_tempo.py`, launcher `04 fp/run_fp.bat` |
| **5** | Adjusted TEMPO column | Todo | \(VCD_\text{adj} = SCD / AMF_\text{adj}\); needs AK / ATBD + your \(w(z)\) |
| **6** | Plume isolation | Todo | \(VCD_\text{bg}\), \(\Delta VCD\), \(\Delta VCD_\text{plume} = f_p \cdot \Delta VCD\) |
| **7** | Column → mass | Todo | \(\text{Mass}_{NO_2} = \Delta VCD_\text{plume} \cdot A \cdot M_{NO_2}\) |

## Mask for f_p

- **Vector:** `data/aoi/mask.shp` (hand-drawn plume polygons; README in repo root).
- **Optional:** raster mask GeoTIFF on any grid — script warps it to the Planet reference first.

## f_p in one command

From repo root (with `smoke` venv activated if you use it):

```text
py -3 scripts/fp_planet_mask_to_tempo.py
```

Defaults: `--mask data/aoi/mask.shp`, Planet path from `data/case.json` → `planet`, `--tempo-ref step-by-step/03/tempo_vcd_troposphere_utm11_clipped.tif`, output `step-by-step/03/tempo_fp_plume_utm11_clipped.tif`.

Override Planet or paths if your files live elsewhere:

```text
py -3 scripts/fp_planet_mask_to_tempo.py --planet-ref data/planet/YOUR.tif --tempo-ref "step-by-step/03 tempo/tempo_vcd_troposphere_utm11_clipped.tif"
```

Requires: **numpy**, **rasterio**, **fiona** (`py -3 -m pip install fiona`).
