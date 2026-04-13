# Analysis pipeline (todo)

- [ ] **1. Prepare TEMPO NO₂** — AMF_adj = Σ w(z)·AK(z), VCD_adj = SCD / AMF_adj (regridded 3D + SCD)
- [ ] **2. Aggregate Planet to TEMPO grid** — f_p = mean of M_Planet per TEMPO pixel → run `scripts/fp_planet_mask_to_tempo.py` or `step-by-step/04 fp/run_fp.bat`
- [ ] **3. Isolate plume NO₂** — VCD_bg, ΔVCD, ΔVCD_plume = f_p · ΔVCD
- [ ] **4. Convert column to mass** — Mass_NO2 = ΔVCD_plume · A · M_NO2 (units through to kg)
