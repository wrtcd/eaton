/**
 * Eaton validation — Sentinel-5P / TROPOMI NO₂ (GEE catalog)
 *
 * Workflow (same pattern as eaton_validate_tempo_l3_nasa_gee.js):
 *   1) AOI + date window → ImageCollection → composite (mean).
 *   2) Tropospheric column (mol/m²) → convert to molecules/cm² for comparison to TEMPO.
 *   3) Zonal stats on AOI; optional map vs uploaded TEMPO VCD asset (reprojected — interpret with care).
 *
 * Catalog: COPERNICUS/S5P/OFFL/L3_NO2 or COPERNICUS/S5P/NRTI/L3_NO2
 * Band: tropospheric_NO2_column_number_density (mol/m²)
 *
 * SET CONFIG BELOW, paste into Code Editor, Run.
 */

var PROJECT = 'projects/earthengine-441016/assets';

var CONFIG = {
  /** 'OFFL' (larger latency) or 'NRTI' (faster, smaller swath). */
  s5pMode: 'OFFL',

  /** Inclusive start, exclusive-style end (GEE filterDate). */
  dateStart: '2025-01-09',
  dateEnd: '2025-01-10',

  /**
   * Study area in WGS84 (lon/lat). Adjust to your Eaton / SoCal box.
   * Roughly covers UTM11N bbox used in Python (~232–557 km E, 3634–3857 km N).
   */
  aoi: ee.Geometry.Rectangle([-118.55, 33.55, -117.45, 34.35]),

  /** Zonal stats scale (m) — ~S5P L3 nominal at nadir. */
  scaleM: 1113,

  maxPixels: 1e13,

  /**
   * Optional: your uploaded TEMPO tropospheric VCD (molecules/cm²), same idea as eaton_plume_delta_mass.js.
   * Set null to skip diff layers.
   */
  assetTempoVcdTroposphere: PROJECT + '/tempo_vcd_troposphere_utm11_clipped',

  opacity: 0.75,
};

// --- helpers -----------------------------------------------------------------

/**
 * molecules/cm² per (mol/m²) = N_A / 10⁴ — one factor avoids ee.Number('…e23') (invalid in EE)
 * and split multiply/divide chains that mis-scaled in some EE builds.
 */
var MOLEC_CM2_PER_MOL_M2 = ee.Number(6.02214076e19);

/**
 * mol/m² → molecules/cm² — expression evaluates 6.022e23/1e4 on the server (stable).
 */
function molM2ToMolecCm2(img) {
  var d = img.toDouble();
  return d.expression('sigma * 6.02214076e23 / 10000.0', { sigma: d.select(0) }).rename('NO2_molec_cm2');
}

function s5pCollection() {
  var id =
    CONFIG.s5pMode === 'NRTI'
      ? 'COPERNICUS/S5P/NRTI/L3_NO2'
      : 'COPERNICUS/S5P/OFFL/L3_NO2';
  return ee.ImageCollection(id);
}

// --- load & composite --------------------------------------------------------

var col = s5pCollection()
  .select('tropospheric_NO2_column_number_density')
  .filterDate(CONFIG.dateStart, CONFIG.dateEnd)
  .filterBounds(CONFIG.aoi);

var s5pMeanMolM2 = col.mean().clip(CONFIG.aoi);
var s5pTropMolecCm2 = molM2ToMolecCm2(s5pMeanMolM2);

// --- zonal stats -------------------------------------------------------------

var redu = s5pTropMolecCm2.reduceRegion({
  reducer: ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
  geometry: CONFIG.aoi,
  scale: CONFIG.scaleM,
  maxPixels: CONFIG.maxPixels,
  tileScale: 4,
});

/** Raw mean in mol/m² (catalog units) — sanity check before ×N_A/1e4. Typical clear sky ~1e−4 mol/m² order. */
var reduMol = s5pMeanMolM2.reduceRegion({
  reducer: ee.Reducer.mean(),
  geometry: CONFIG.aoi,
  scale: CONFIG.scaleM,
  maxPixels: CONFIG.maxPixels,
  tileScale: 4,
});

print('=== TROPOMI / S5P L3 NO2 (Eaton validation) ===');
print('Collection', CONFIG.s5pMode === 'NRTI' ? 'COPERNICUS/S5P/NRTI/L3_NO2' : 'COPERNICUS/S5P/OFFL/L3_NO2');
print('Date', CONFIG.dateStart, '→', CONFIG.dateEnd);
print('Images in filter', col.size());
var meanMolM2 = reduMol.get('tropospheric_NO2_column_number_density');
print('S5P mean tropospheric column (mol/m², catalog units)', meanMolM2);
/** Same as σ × N_A / 1e4 (one multiply by MOLEC_CM2_PER_MOL_M2). */
print(
  'Expected mean (molec/cm²) from mean(mol/m²)×(N_A/1e4)',
  ee.Number(meanMolM2).multiply(MOLEC_CM2_PER_MOL_M2)
);
print('S5P trop NO2 (molecules/cm²) — median', redu.get('NO2_molec_cm2_median'));
print('S5P trop NO2 (molecules/cm²) — mean', redu.get('NO2_molec_cm2_mean'));
print('S5P trop NO2 — pixel count', redu.get('NO2_molec_cm2_count'));

// --- optional: compare to uploaded TEMPO raster ------------------------------

var hasTempo =
  CONFIG.assetTempoVcdTroposphere !== null &&
  CONFIG.assetTempoVcdTroposphere !== undefined &&
  CONFIG.assetTempoVcdTroposphere !== '';

if (hasTempo) {
  var tempo = ee.Image(CONFIG.assetTempoVcdTroposphere).select([0]).rename('TEMPO');
  var tempoProj = tempo.projection();
  var s5pOnTempoGrid = s5pTropMolecCm2
    .reproject({ crs: tempoProj, scale: tempoProj.nominalScale() })
    .resample('bilinear');
  var both = tempo.mask().and(s5pOnTempoGrid.mask());
  var diff = tempo.subtract(s5pOnTempoGrid).rename('TEMPO_minus_S5P_molec_cm2').updateMask(both);

  var tempoAoi = tempo.reduceRegion({
    reducer: ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
    geometry: CONFIG.aoi,
    crs: tempoProj,
    scale: tempoProj.nominalScale(),
    maxPixels: CONFIG.maxPixels,
    tileScale: 4,
  });
  print('Uploaded TEMPO troposphere (molecules/cm²) — median', tempoAoi.get('TEMPO_median'));
  print('Uploaded TEMPO troposphere (molecules/cm²) — mean', tempoAoi.get('TEMPO_mean'));
  print('Uploaded TEMPO — count', tempoAoi.get('TEMPO_count'));

  var s5pOnTempoAoi = s5pOnTempoGrid.reduceRegion({
    reducer: ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
    geometry: CONFIG.aoi,
    crs: tempoProj,
    scale: tempoProj.nominalScale(),
    maxPixels: CONFIG.maxPixels,
    tileScale: 4,
  });
  print('S5P on TEMPO grid (molecules/cm²) — median', s5pOnTempoAoi.get('NO2_molec_cm2_median'));
  print('S5P on TEMPO grid (molecules/cm²) — mean', s5pOnTempoAoi.get('NO2_molec_cm2_mean'));

  var st = diff.reduceRegion({
    reducer: ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
    geometry: CONFIG.aoi,
    crs: tempoProj,
    scale: tempoProj.nominalScale(),
    maxPixels: CONFIG.maxPixels,
    tileScale: 4,
  });
  print('TEMPO − S5P (masked where both valid) — median', st.get('TEMPO_minus_S5P_molec_cm2_median'));
  print('TEMPO − S5P — mean', st.get('TEMPO_minus_S5P_molec_cm2_mean'));
  print('TEMPO − S5P — count', st.get('TEMPO_minus_S5P_molec_cm2_count'));
  print(
    'Note: different granule time, L3 orbit composite, resolution, AMF — sanity check only, not validation truth.'
  );

  Map.addLayer(tempo, { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] }, 'TEMPO VCD (asset)', true, CONFIG.opacity);
  Map.addLayer(s5pOnTempoGrid, { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] }, 'S5P trop (on TEMPO grid)', false, CONFIG.opacity);
  Map.addLayer(diff, { min: -1e16, max: 1e16, palette: ['2166ac', 'f7f7f7', 'b2182b'] }, 'TEMPO − S5P', false, CONFIG.opacity);
}

// --- map (native S5P L3 grid) ------------------------------------------------

Map.centerObject(CONFIG.aoi, 9);
Map.addLayer(
  s5pTropMolecCm2,
  { min: 0, max: 5e15, palette: ['0d0887', '6a00a8', 'b12a90', 'e16462', 'fca636', 'f0f921'] },
  'S5P trop NO2 (molec/cm², mean over window)',
  !hasTempo,
  CONFIG.opacity
);
Map.addLayer(CONFIG.aoi, { color: 'FFFFFF' }, 'AOI', true, 0.3);
