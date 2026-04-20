/**
 * Eaton validation — Sentinel-5P / TROPOMI NO₂ (GEE catalog)
 *
 * Workflow (same pattern as eaton_validate_tempo_l3_nasa_gee.js):
 *   1) AOI + date window → ImageCollection → composite (mean).
 *   2) Tropospheric column (mol/m²) → convert to molecules/cm² for comparison to TEMPO.
 *   3) Zonal stats on analysis region (TEMPO study footprint or loose AOI); optional map vs TEMPO assets.
 *
 * TEMPO assets (match eaton_plume_delta_mass.js):
 *   - VCD_adj — step 06 (SCD/AMF_trop), primary comparison to S5P when set.
 *   - L2 tropospheric VCD — step 03, optional map layer; set null to hide.
 *
 * Catalog: COPERNICUS/S5P/OFFL/L3_NO2 or COPERNICUS/S5P/NRTI/L3_NO2
 * Band: tropospheric_NO2_column_number_density (mol/m²)
 *
 * Map shift (plumes offset vs basemap): Each uploaded layer uses the GeoTIFF CRS and affine.
 * Fix CRS/bounds on disk (gdalinfo / gdal_edit) and re-upload; do not use ee.Image.reproject()
 * to “fix” placement — that resamples and breaks comparability.
 *
 * Reducers on UTM TEMPO rasters: use reduceRegion with crs: image.projection() + nominalScale(),
 * or crsTransform from gdalinfo when it matches the asset exactly — not EPSG string + scale alone
 * (can inflate counts/sums). See reduceRegionCustom below.
 *
 * Spatial alignment: set alignS5pToTempoGrid true (default) so filterBounds, clip, and
 * reduceRegion use SAMPLE_RECT_BBOX — the same UTM11 study footprint as eaton_plume_delta_mass.js
 * (paste gdalinfo GeoTransform into EATON_GEOTRANSFORM). That tightens S5P to the TEMPO grid extent
 * instead of a large lon/lat box. S5P L3 remains one day per filterDate; it is not co-temporal
 * to a single TEMPO granule (see printed note).
 *
 * Fair TEMPO vs S5P comparison: set useIntersectionMask true (default). Zonal stats on the TEMPO
 * grid then use the same pixels for both layers — mask = TEMPO valid ∧ S5P-on-grid valid — so
 * median/mean/count refer to the same spatial support. Native S5P stats (first print block) stay on
 * the L3 grid at scaleM; they are context only, not pixel-matched to TEMPO.
 *
 * Deeper pairing (Pearson, MAE/RMSE, linear fit, scatter): **eaton_compare_tropomi_tempo.js**
 *
 * SET CONFIG BELOW, paste into Code Editor, Run.
 */

var PROJECT = 'projects/earthengine-441016/assets';

/**
 * Six-element GDAL GeoTransform from `gdalinfo` on **the exact GeoTIFF you uploaded** to GEE
 * (same study grid as eaton_plume_delta_mass.js). Used for optional crsTransform reducers and
 * SAMPLE_RECT_BBOX when debugging native-grid stats.
 */
var EATON_GEOTRANSFORM = [
  232153.3523,
  (557208.806 - 232153.3523) / 101,
  0,
  3856746.1228,
  0,
  -(3856746.1228 - 3634690.804) / 69,
];

var EATON_GRID_W = 101;
var EATON_GRID_H = 69;
var _gt0 = EATON_GEOTRANSFORM[0];
var _gt1 = EATON_GEOTRANSFORM[1];
var _gt3 = EATON_GEOTRANSFORM[3];
var _gt5 = EATON_GEOTRANSFORM[5];
var EATON_XMAX = _gt0 + EATON_GRID_W * _gt1;
var EATON_YMIN = _gt3 + EATON_GRID_H * _gt5;
var SAMPLE_RECT_BBOX = ee.Geometry.Rectangle(
  [_gt0, EATON_YMIN, EATON_XMAX, _gt3],
  'EPSG:32611',
  false
);

var CONFIG = {
  /** 'OFFL' (larger latency) or 'NRTI' (faster, smaller swath). */
  s5pMode: 'OFFL',

  /** Inclusive start, exclusive-style end (GEE filterDate). Match the TEMPO granule calendar day. */
  dateStart: '2025-01-09',
  dateEnd: '2025-01-10',

  /**
   * If true: filterBounds / clip / zonal stats use SAMPLE_RECT_BBOX (UTM11 Eaton study grid — same
   * extent as uploaded TEMPO GeoTIFFs). If false: use loose aoi below (regional context).
   */
  alignS5pToTempoGrid: true,

  /**
   * Loose WGS84 box — used only when alignS5pToTempoGrid is false.
   * Rough SoCal context (~232–557 km E, 3634–3857 km N in UTM11 terms).
   */
  aoi: ee.Geometry.Rectangle([-118.55, 33.55, -117.45, 34.35]),

  /** Zonal stats scale (m) on native S5P L3 — ~L3 nominal at nadir (~1113 m). */
  scaleM: 1113,

  maxPixels: 1e13,

  /** VCD_adj — step 06 (SCD/AMF_trop); primary TEMPO layer for S5P comparison. Set '' to skip. */
  assetVcd: PROJECT + '/tempo_vcd_check_scd_over_amf_trop',

  /** L2 tropospheric VCD (step 03) — map only; set null to hide. */
  assetVcdTroposphereL2: PROJECT + '/tempo_vcd_troposphere_utm11_clipped',

  /**
   * Optional: set to EATON_GEOTRANSFORM only if those six numbers match the GEE TEMPO asset exactly.
   * Default null = use image.projection() + nominalScale() for reduceRegion on TEMPO layers.
   */
  crsTransform: null,

  /**
   * If true: TEMPO and S5P-on-TEMPO-grid reduceRegion stats use mask = both valid (intersection).
   * Counts then match between the two rows; medians/means are fairly paired. If false: each layer
   * uses its own mask (unfair counts / not the same pixels).
   */
  useIntersectionMask: true,

  opacity: 0.75,
};

/** Region for S5P collection + stats: TEMPO study footprint or loose AOI. */
var analysisGeometry = CONFIG.alignS5pToTempoGrid ? SAMPLE_RECT_BBOX : CONFIG.aoi;

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

function _useCrsTransform() {
  return (
    CONFIG.crsTransform !== null &&
    Array.isArray(CONFIG.crsTransform) &&
    CONFIG.crsTransform.length === 6
  );
}

/**
 * Medians / means on UTM rasters: prefer crsTransform when it matches the asset; else
 * crs: img.projection() + nominalScale — not crs: 'EPSG:32611' + scale alone.
 */
function reduceRegionCustom(img, reducer, geometry) {
  if (_useCrsTransform()) {
    return img.reduceRegion({
      reducer: reducer,
      geometry: geometry,
      crs: 'EPSG:32611',
      crsTransform: CONFIG.crsTransform,
      maxPixels: CONFIG.maxPixels,
      tileScale: 4,
    });
  }
  var ip = img.projection();
  return img.reduceRegion({
    reducer: reducer,
    geometry: geometry,
    crs: ip,
    scale: ip.nominalScale(),
    maxPixels: CONFIG.maxPixels,
    tileScale: 4,
  });
}

// --- load & composite --------------------------------------------------------

var col = s5pCollection()
  .select('tropospheric_NO2_column_number_density')
  .filterDate(CONFIG.dateStart, CONFIG.dateEnd)
  .filterBounds(analysisGeometry);

var s5pMeanMolM2 = col.mean().clip(analysisGeometry);
var s5pTropMolecCm2 = molM2ToMolecCm2(s5pMeanMolM2);

// --- zonal stats (native S5P L3 over analysisGeometry) ------------------------

var redu = s5pTropMolecCm2.reduceRegion({
  reducer: ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
  geometry: analysisGeometry,
  scale: CONFIG.scaleM,
  maxPixels: CONFIG.maxPixels,
  tileScale: 4,
});

/** Raw mean in mol/m² (catalog units) — sanity check before ×N_A/1e4. Typical clear sky ~1e−4 mol/m² order. */
var reduMol = s5pMeanMolM2.reduceRegion({
  reducer: ee.Reducer.mean(),
  geometry: analysisGeometry,
  scale: CONFIG.scaleM,
  maxPixels: CONFIG.maxPixels,
  tileScale: 4,
});

print('=== TROPOMI / S5P L3 NO2 (Eaton validation) ===');
print(
  'Region',
  CONFIG.alignS5pToTempoGrid
    ? 'SAMPLE_RECT_BBOX (UTM11 study grid — aligned with TEMPO upload / plume script)'
    : 'CONFIG.aoi (loose lon/lat)'
);
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
print(
  'S5P trop NO2 native L3 (molecules/cm²) — median / mean / count @ scaleM — NOT mask-matched to TEMPO'
);
print('S5P trop NO2 (molecules/cm²) — median', redu.get('NO2_molec_cm2_median'));
print('S5P trop NO2 (molecules/cm²) — mean', redu.get('NO2_molec_cm2_mean'));
print('S5P trop NO2 — sample count', redu.get('NO2_molec_cm2_count'));

// --- optional: compare to uploaded TEMPO rasters (VCD_adj + optional L2) -----

var hasVcdAdj =
  CONFIG.assetVcd !== null &&
  CONFIG.assetVcd !== undefined &&
  typeof CONFIG.assetVcd === 'string' &&
  CONFIG.assetVcd !== '';

var showTropL2 =
  CONFIG.assetVcdTroposphereL2 !== null &&
  CONFIG.assetVcdTroposphereL2 !== undefined &&
  typeof CONFIG.assetVcdTroposphereL2 === 'string' &&
  CONFIG.assetVcdTroposphereL2 !== '';

if (hasVcdAdj) {
  var tempo = ee.Image(CONFIG.assetVcd).select([0]).rename('TEMPO');
  var tempoProj = tempo.projection();
  print('TEMPO VCD_adj projection (CRS)', tempoProj);
  print(
    'TEMPO nominalScale (m) — match CONFIG.scaleM for any chart using this grid',
    tempoProj.nominalScale()
  );
  print('SAMPLE_RECT_BBOX (UTM11 native grid ref, same as plume script)', SAMPLE_RECT_BBOX);

  var vcdTropL2 = showTropL2
    ? ee.Image(CONFIG.assetVcdTroposphereL2).select([0]).rename('VCD')
    : null;

  var s5pOnTempoGrid = s5pTropMolecCm2
    .reproject({ crs: tempoProj, scale: tempoProj.nominalScale() })
    .resample('bilinear');
  var both = tempo.mask().and(s5pOnTempoGrid.mask());
  var diff = tempo.subtract(s5pOnTempoGrid).rename('TEMPO_minus_S5P_molec_cm2').updateMask(both);

  var tempoForStats = CONFIG.useIntersectionMask ? tempo.updateMask(both) : tempo;
  var s5pOnTempoForStats = CONFIG.useIntersectionMask ? s5pOnTempoGrid.updateMask(both) : s5pOnTempoGrid;

  print(
    'Fair comparison (TEMPO grid): useIntersectionMask =',
    CONFIG.useIntersectionMask,
    '— stats below use the SAME pixels where both TEMPO and S5P (reprojected) are valid.'
  );

  var tempoAoi = reduceRegionCustom(
    tempoForStats,
    ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
    analysisGeometry
  );
  print('Uploaded TEMPO VCD_adj (molecules/cm²) — median', tempoAoi.get('TEMPO_median'));
  print('Uploaded TEMPO VCD_adj (molecules/cm²) — mean', tempoAoi.get('TEMPO_mean'));
  print('Uploaded TEMPO VCD_adj — count', tempoAoi.get('TEMPO_count'));

  var s5pOnTempoAoi = reduceRegionCustom(
    s5pOnTempoForStats,
    ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
    analysisGeometry
  );
  print('S5P on TEMPO grid (molecules/cm²) — median', s5pOnTempoAoi.get('NO2_molec_cm2_median'));
  print('S5P on TEMPO grid (molecules/cm²) — mean', s5pOnTempoAoi.get('NO2_molec_cm2_mean'));

  var st = reduceRegionCustom(
    diff,
    ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
    analysisGeometry
  );
  print('TEMPO VCD_adj − S5P (masked where both valid) — median', st.get('TEMPO_minus_S5P_molec_cm2_median'));
  print('TEMPO VCD_adj − S5P — mean', st.get('TEMPO_minus_S5P_molec_cm2_mean'));
  print('TEMPO VCD_adj − S5P — count', st.get('TEMPO_minus_S5P_molec_cm2_count'));
  print(
    'Note: different granule time, L3 orbit composite, resolution, AMF — sanity check only, not validation truth.'
  );

  Map.addLayer(
    tempo,
    { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] },
    'TEMPO VCD_adj (step 06)',
    true,
    CONFIG.opacity
  );
  if (showTropL2) {
    Map.addLayer(
      vcdTropL2,
      { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'b12a90', 'e16462', 'fca636', 'f0f921'] },
      'L2 VCD troposphere (step 03, compare)',
      false,
      CONFIG.opacity
    );
  }
  Map.addLayer(
    s5pOnTempoGrid,
    { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] },
    'S5P trop (on TEMPO grid)',
    false,
    CONFIG.opacity
  );
  Map.addLayer(
    diff,
    { min: -1e16, max: 1e16, palette: ['2166ac', 'f7f7f7', 'b2182b'] },
    'TEMPO VCD_adj − S5P',
    false,
    CONFIG.opacity
  );
  Map.addLayer(
    both.selfMask(),
    { palette: ['000000'] },
    'Overlap mask (both valid — fair stats region)',
    false,
    0.35
  );
}

// --- map (native S5P L3 grid) ------------------------------------------------

Map.centerObject(analysisGeometry, 10);
Map.addLayer(
  s5pTropMolecCm2,
  { min: 0, max: 5e15, palette: ['0d0887', '6a00a8', 'b12a90', 'e16462', 'fca636', 'f0f921'] },
  'S5P trop NO2 (molec/cm², mean over window)',
  !hasVcdAdj,
  CONFIG.opacity
);
Map.addLayer(ee.Feature(analysisGeometry), { color: '00ff88' }, 'Analysis footprint (S5P stats region)', true, 0.45);
if (!CONFIG.alignS5pToTempoGrid) {
  Map.addLayer(CONFIG.aoi, { color: 'FFFFFF' }, 'Loose AOI (CONFIG.aoi)', false, 0.25);
}
