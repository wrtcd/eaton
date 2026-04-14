# Pipeline assumptions

This note records **explicit assumptions** used in the Eaton smoke-plume workflow (PlanetScope + TEMPO NO₂). It is meant to stay aligned with scripts and step folders; update it when inputs or formulas change.

**Step-by-step narrative** (what each folder does, commands, batch files): **`step-by-step/README.md`**.

---

## Data products and versions

- **TEMPO:** Level-2 NO₂ files (e.g. `TEMPO_NO2_L2_V03_*.nc`) are used as the source of slant columns, air mass factors, vertical columns, and 3D support fields (`scattering_weights`, `gas_profile`, `temperature_profile`, pressures). Algorithm details are defined in the **TEMPO NO₂ ATBD** (NASA ASDC).
- **Planet:** High-resolution mosaic (or scene) GeoTIFF defines the grid for **burning** the plume mask before aggregating to TEMPO.
- **Spatial reference:** TEMPO layers are warped or regridded to a **common UTM zone 11N** (EPSG:32611) study grid for stacking with masks and fractions.

---

## QA, cloud screening, and where it runs

**Warped inputs** (from `warp_tempo_subdatasets_utm11_clipped.bat`) include **`main_data_quality_flag`**, **`ground_pixel_quality_flag`**, **`eff_cloud_fraction`**, and **`amf_diagnostic_flag`**, among others.

**Filtering is implemented** in **`scripts/tempo/screen_tempo_pixels.py`** (not in the AMF or \(f_p\) scripts by default). It writes a **binary mask** (uint8: 1 = pass, 0 = fail) using:

- **`main_data_quality_flag`:** keep pixels with **`flag <= --qa-main-max`** (default **0** = nominal “good” only; see TEMPO user guide for bit meanings).
- **`eff_cloud_fraction`:** keep pixels with **`value <= --cloud-max`** (default **0.3**).
- **`vertical_column_troposphere`:** drop non-finite values and invalid fills.

Default output: **`tempo_mask_screen_utm11_clipped.tif`** in the warped GeoTIFF directory (**`step-by-step/03 tempo`**, same folder as **`warp_tempo_subdatasets_utm11_clipped.bat`** outputs).

**Orchestration:** run **`scripts/tempo/screen_tempo_pixels.py`** first (writes **`tempo_mask_screen_utm11_clipped.tif`** next to the warped stacks, default directory **`step-by-step/03 tempo`**).

**Downstream defaults:** if that mask file exists on disk,

- **`fp_planet_mask_to_tempo.py`** applies it to **\(f_p\)** (failed pixels → nodata **-9999**). Use **`--no-tempo-screen`** to skip.
- **`amf_atbd_from_tempo.py`** applies it to the **regridded AMF** and **72-band** outputs. Use **`--no-screen`** to skip.

**When to run screening:** after TEMPO layers are warped to the study grid (**step 3**), before or together with **\(f_p\)** and **AMF** products. A one-shot driver is **`scripts/tempo/run_pipeline_tempo_plume_amf.bat`** (screen → f_p → AMF).

Adjust **`--qa-main-max`** and **`--cloud-max`** in **`screen_tempo_pixels.py`** to match your analysis tolerance.

---

## Planet mosaic

- **NoData:** If the mosaic is exported with **NoData = 0**, that is appropriate only where **0 is not a valid class** in the classification band used downstream. If 0 is a real class, NoData must use a different sentinel.
- **Overlap:** Where two scenes overlap, merge order and transparency flags (`-n` / `-srcnodata` in GDAL) determine which raster “wins”; this should match the intended priority rule.

---

## Plume fraction \(f_p\)

- **Definition:** \(f_p\) is the **mean of the binary plume mask** on the Planet grid, **averaged over** each TEMPO pixel (see `scripts/fp_planet_mask_to_tempo.py`).
- **Mask:** Vector or raster mask is assumed to represent **plume extent**; **CRS** must be consistent with the Planet reference (the script reprojects vector geometries as needed).

---

## AMF and “AMF_adj” (TEMPO ATBD §3.1.3)

### What the TEMPO product uses (notation)

The operational **tropospheric AMF** is built from **scattering weights** \(W_k\), a **prior vertical shape** \(S_k\) from **NO₂ partial columns** \(n_k\), and a **temperature correction** \(c_k\) (ATBD Eq. 18, with \(T_\sigma = 220\,\mathrm{K}\)). In discrete form the implementation uses:

\[
\mathrm{AMF}_{\mathrm{trop}} \approx \sum_k W_k\,S_k\,c_k
\]

over layers classified as **tropospheric** using **hybrid \(\eta\) pressure** layer centers \(p_{\mathrm{mid}}\) between **surface pressure** \(p_s\) and **tropopause pressure** \(p_{\mathrm{trop}}\) (from the same L2 file; Eta coefficients are read from `surface_pressure` metadata).

**Profile shape** (prior):

\[
S_k = \frac{n_k}{\sum_{j\in\mathrm{trop}} n_j}
\]

with \(n_k\) from `gas_profile` (partial columns, molecules/cm²).

**Temperature correction:**

\[
c_k = 1 - 0.00316\,[T_k - T_\sigma] + 3.39\times 10^{-6}\,[T_k - T_\sigma]^2
\]

with \(T_k\) from `temperature_profile`.

### Implemented outputs (`step-by-step/05 amf adj/`)

The script `scripts/tempo/amf_atbd_from_tempo.py` writes:

- **`tempo_amf_trop_atbd.tif`** — Recomputed **tropospheric AMF** on the reference grid (matches the product `amf_troposphere` on the native grid when computed from the same inputs).
- **72-band** **`tempo_amf_adj_layer_contribution_W_S_c_72bands.tif`** — Per-layer terms **\(A_k = W_k S_k c_k\)**.
- **72-band** **`tempo_amf_adj_layer_weight_normalized_72bands.tif`** — **\(A_k / \mathrm{AMF}_{\mathrm{trop}}\)** (relative contribution by layer).

### Assumptions specific to this implementation

1. **Discrete sum vs. integral:** The ATBD uses integrals over altitude; the code uses the **sum over the 72 `swt_level` layers** supplied in L2, consistent with how the operational processor discretizes the atmosphere.
2. **No separate “AK” raster in L2:** Altitude **sensitivity** in the ATBD is carried by **scattering weights** \(W_k\). There is no additional variable named “averaging kernel” in the file; layer-wise products **\(W_k S_k c_k\)** are the building blocks for AMF.
3. **“AMF_adj” naming:** The **72-band** filenames use the word **adj** to indicate **layer-level terms used for adjusted-column work**. The current computation still uses the **operational prior shape \(S_k\)** from **`gas_profile`**. A **true** adjusted AMF in the sense of a **custom assumed profile \(w_k\)** (e.g. smoke plume between 0.5–2 km) would replace **\(S_k\)** with a **normalized \(w_k\)** on the same layers and use \(\sum_k W_k w_k c_k\). That **custom** \(w_k\) is **not** applied automatically in the current script.
4. **Regridding:** Native TEMPO dimensions (mirror × track) are interpolated to the UTM grid with **SciPy `griddata`** (linear where possible, with **nearest** or NaN fallback if triangulation fails). Resampled rasters are **not** identical to the native pixel physics at every edge; they are **consistent** with other warped stacks in this repo for mapping and zonal work.
5. **Cloud and aerosols:** The L2 **scattering** fields already reflect the retrieval’s **effective** cloud treatment (see ATBD §3.1.3.3). The script does **not** recompute a separate IPA cloud mix; it uses the **stored** \(W_k\) and pressures as provided.

---

## Adjusted vertical column (\(VCD_{\mathrm{adj}}\)) — not yet automated here

Where the science plan uses:

\[
VCD_{\mathrm{adj}} = \frac{SCD}{\mathrm{AMF}_{\mathrm{adj}}}
\]

with \(\mathrm{AMF}_{\mathrm{adj}} = \sum_k w_k\,AK_k\) in the **slide** notation, **TEMPO’s ATBD** implements **\(\mathrm{AMF}_{\mathrm{trop}}\)** via **\(W_k\)** and **\(S_k\)** (and \(c_k\)) as above. **Align symbols** with your advisor: either map **\(AK_k\)** to **\(W_k\)** in the inner product with **\(w_k\)**, or adopt the ATBD’s **\(W_k\)**, **\(S_k\)**, **\(c_k\)** decomposition explicitly.

**Not implemented in this repository:** automatic production of **\(VCD_{\mathrm{adj}}\)** rasters from `fitted_slant_column` and a **custom** \(\mathrm{AMF}_{\mathrm{adj}}\) until **\(w_k\)** is fixed and coded.

---

## \(\Delta VCD\), plume scaling, and mass (steps 07–08)

- **`delta_vcd_plume.py`:** **\(VCD_{\mathrm{bg}}\)** is the **median** of **\(VCD_{\mathrm{check}}\)** over pixels with **\(f_p \le 10^{-6}\)** (then looser fallbacks if needed). **\(\Delta VCD = VCD_{\mathrm{check}} - VCD_{\mathrm{bg}}\)**; **\(\Delta VCD_{\mathrm{plume}} = f_p \cdot \Delta VCD\)**.
- **`mass_no2_from_plume.py`:** Per-pixel **kg NO₂** = \((\Delta VCD_{\mathrm{plume}} \,[\mathrm{molecules/cm^2}] \times A \,[\mathrm{cm}^2]) / N_A \times M_{NO_2}\), with **\(A\)** from the GeoTIFF pixel area (**\(|\mathrm{det}|\)** of the affine scale in m² for UTM). **\(M_{NO_2} = 46.0055\,\mathrm{g/mol}\)**. Summary JSON reports **sum of signed** and **sum of positive-only** masses. **PNG** maps and histograms are diagnostic, not publication-grade without cartopy/labels.

---

## References

- TEMPO NO₂ **Algorithm Theoretical Basis Document** (ATBD), §3.1.3 (air mass factors, scattering weights, temperature correction):  
  [https://asdc.larc.nasa.gov/documents/tempo/ATBD_TEMPO_NO2.pdf](https://asdc.larc.nasa.gov/documents/tempo/ATBD_TEMPO_NO2.pdf)
- TEMPO Level 2–3 **User’s Guide** (trace gases and clouds): linked from ASDC collection pages (e.g. `TEMPO_NO2_L2_V03`).

---

## Maintenance

When you change the **NetCDF granule**, **reference grid**, **mask**, or **plume height assumptions**, update this file and the **step-by-step** `README.md` if behavior of a step changes.
