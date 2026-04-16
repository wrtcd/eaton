# From sunlight to plume NO₂ mass (TEMPO reading–list aligned)

This note walks from **solar radiation** to the **column-integrated NO₂ mass** reported in `step-by-step/08 mass/tempo_plume_mass_summary.json` (e.g. **~30251 kg NO₂** in the current run). It is consistent with:

- **`TEMPO-reading-list.md`** — [User Guide](https://asdc.larc.nasa.gov/documents/tempo/guide/TEMPO_Level-2-3_trace_gas_clouds_user_guide_V2.0.pdf), [NO₂ ATBD](https://asdc.larc.nasa.gov/documents/tempo/ATBD_TEMPO_NO2.pdf), ASDC [TEMPO_NO2_L2_V03](https://asdc.larc.nasa.gov/project/TEMPO/TEMPO_NO2_L2_V03)
- **`docs/tempo-no2-terms.md`**
- **`step-by-step/README.md`**
- **`docs/pipeline-assumptions.md`**

The journal papers on the reading list (JGR, AMT, ACP) support general DOAS/satellite-column ideas; **field names, AMF construction, and QA** follow the **NASA User Guide** and **NO₂ ATBD** as implemented in this repo.

---

## 1. Solar radiation and the atmosphere (ATBD radiative transfer)

**Technical:** Solar spectral irradiance enters the atmosphere; NO₂ and other species absorb and scatter in the UV–visible. The **TEMPO NO₂ retrieval** is built on radiative transfer and spectral fitting described in the **[NO₂ ATBD](https://asdc.larc.nasa.gov/documents/tempo/ATBD_TEMPO_NO2.pdf)** (NASA ASDC). The **[Level 2–3 User Guide](https://asdc.larc.nasa.gov/documents/tempo/guide/TEMPO_Level-2-3_trace_gas_clouds_user_guide_V2.0.pdf)** documents how results appear in **NetCDF** products.

**ELI5:** The Sun sends many colors of light through the air; **NO₂ changes how much of certain colors get through** along the light path. NASA’s ATBD mathematics turns those spectral fingerprints into column amounts.

---

## 2. TEMPO measures Earth radiance spectra

**Technical:** The instrument records **spectral radiance** at the satellite. Field names and structure follow the **User Guide**. Those spectra feed the operational NO₂ processing that produces **Level-2** variables on the native grid.

**ELI5:** The satellite measures “rainbow brightness” at each ground pixel—the raw “what light arrived?” data before your project maps exist.

---

## 3. Slant column density (SCD) — `fitted_slant_column`

**Technical:** The retrieval fits the NO₂ absorption signature and reports a **slant column density (SCD)** along the light path. The glossary maps SCD to **`fitted_slant_column`** (units typically **molecules cm⁻²**). See **`docs/tempo-no2-terms.md`**.

**ELI5:** NASA first answers: **“How much NO₂ did the measured light pass through along its slanted path?”** That is **SCD**, not “straight up” yet.

---

## 4. Tropospheric air mass factor — `amf_troposphere` and ATBD §3.1.3

**Technical:** An **air mass factor (AMF)** relates **slant** and **vertical** columns for the assumed atmosphere and viewing geometry. The product includes **`amf_troposphere`**. The ATBD builds the **tropospheric AMF** from **scattering weights** \(W_k\), a **normalized prior vertical shape** \(S_k\) from **`gas_profile`** partial columns \(n_k\), and a **temperature correction** \(c_k\) (ATBD Eq. 18, \(T_\sigma = 220\,\mathrm{K}\)), summed over **tropospheric** layers in hybrid \(\eta\) pressure between surface and tropopause—**72 `swt_level` layers** in L2. The ATBD uses **\(W_k\)** for altitude sensitivity; L2 does **not** provide a separate variable named “averaging kernel.” See **`docs/pipeline-assumptions.md`** and **`docs/tempo-no2-terms.md`**.

**ELI5:** The atmosphere is layered. NASA combines sensitivity to each layer (\(W_k\)), the prior vertical shape (\(S_k\)), and temperature tweaks (\(c_k\)) into one number that **converts slant to tropospheric vertical**.

---

## 5. Tropospheric vertical column (VCD) — `vertical_column_troposphere`

**Technical:** **VCD** is the **tropospheric vertical column density**; the product field is **`vertical_column_troposphere`**. Operationally, **VCD ≈ SCD / AMF** when using the retrieval’s tropospheric AMF (**`docs/tempo-no2-terms.md`**).

**ELI5:** After AMF, NASA expresses NO₂ as **“how much would stack vertically in the troposphere”**—still **molecules per cm²** of column.

---

## 6. Study grid (EPSG:32611) and L2 stacks

**Technical:** **`gdalwarp`** and related tools put selected **2D** subdatasets and **3D** fields (`scattering_weights`, `gas_profile`, `temperature_profile`) onto a **common UTM zone 11N** grid (**`step-by-step/README.md`**, step 3). Regridding uses **SciPy `griddata`** as in **`docs/pipeline-assumptions.md`**.

**ELI5:** You **resample NASA’s native swath pixels** onto **your fixed map** so mask, \(f_p\), and math all align.

---

## 7. QA / cloud screening — User Guide flags

**Technical:** Screening uses **`main_data_quality_flag`**, **`eff_cloud_fraction`**, and valid **`vertical_column_troposphere`**, per **`step-by-step/README.md`** and **`docs/pipeline-assumptions.md`** (defaults: QA flag ≤ 0, cloud fraction ≤ 0.3). Output: **`tempo_mask_screen_utm11_clipped.tif`**. Flag semantics are in the **User Guide**.

**ELI5:** Drop pixels that fail NASA quality or cloud rules so bad data do not drive the result.

---

## 8. Plume fraction \(f_p\) — Planet mask → TEMPO grid

**Technical:** **\(f_p\)** is the **mean of the binary plume mask** on the Planet grid **averaged over each TEMPO pixel** (`fp_planet_mask_to_tempo.py`, **`docs/pipeline-assumptions.md`**).

**ELI5:** Each TEMPO cell gets a **fraction** (0–1): **how much of that cell is your plume** from the Planet mask.

---

## 9. ATBD tropospheric AMF recomputed — `tempo_amf_trop_atbd.tif`

**Technical:** **`amf_atbd_from_tempo.py`** recomputes **AMF\(_\mathrm{trop}\) ≈ Σ \(W_k S_k c_k\)** over tropospheric layers (ATBD §3.1.3), per **`step-by-step/README.md`** step 5. Screening can be applied after regrid.

**ELI5:** Rebuild the ATBD AMF recipe on **your grid** so it matches your warped \(W_k\), \(n_k\), \(T_k\) stacks.

---

## 10. `VCD_check` — `docs/tempo-no2-terms.md`

**Technical:** **\(VCD_{\mathrm{check}} = \mathrm{SCD} / \mathrm{AMF}_{\mathrm{trop}}\)** using **`fitted_slant_column`** and **`tempo_amf_trop_atbd.tif`**, optional **`tempo_mask_screen_utm11_clipped.tif`**. Compare to **`vertical_column_troposphere`** when inputs align (`vcd_check_scd_amf.py`).

**ELI5:** Check that **slant ÷ your AMF** matches the intended **tropospheric VCD** before \(\Delta\)column steps.

---

## 11. \(\Delta VCD\) and \(\Delta VCD_{\mathrm{plume}}\) — step 7

**Technical:** **`delta_vcd_plume.py`**: **\(VCD_{\mathrm{bg}}\)** = median of \(VCD_{\mathrm{check}}\) where **\(f_p \le 10^{-6}\)** (with fallbacks per JSON); **\(\Delta VCD = VCD_{\mathrm{check}} - VCD_{\mathrm{bg}}\)**; **\(\Delta VCD_{\mathrm{plume}} = f_p \cdot \Delta VCD\)** (**`step-by-step/README.md`**).

**ELI5:** Subtract a **background**, then keep only the **plume’s share** of that excess in each pixel.

---

## 12. Column to mass — step 8

**Technical:** **`mass_no2_from_plume.py`**: per-pixel **kg NO₂** = \((\Delta VCD_{\mathrm{plume}}\,[\mathrm{molecules/cm^2}] \times A\,[\mathrm{cm}^2]) / N_A \times M_{\mathrm{NO_2}}\), with **\(A\)** from the GeoTIFF pixel area (UTM affine), **\(M_{\mathrm{NO_2}} = 46.0055\,\mathrm{g/mol}\)** (**`docs/pipeline-assumptions.md`**). Sum yields totals in **`tempo_plume_mass_summary.json`**.

**ELI5:** Turn **molecules per cm²** into **molecules on the ground** using **pixel area**, convert to **kilograms**, then **sum all pixels**.

---

## 13. Final reported mass

**Technical:** **`tempo_plume_mass_summary.json`** reports **e.g.** `total_no2_mass_kg_sum_all_pixels` (and positive-only if applicable)—example value **30251.296200122102 kg NO₂** for the current Eaton run.

**ELI5:** That JSON is the **total account** after all NASA-aligned column steps and your plume/background rules.

---

## Maintenance

When granule, grid, mask, or mass script defaults change, update **`docs/pipeline-assumptions.md`** and **`step-by-step/README.md`** as needed, and refresh any example kg value in this file.
