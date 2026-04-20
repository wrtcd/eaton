/**
 * Eaton — TROPOMI (Sentinel-5P L3) vs uploaded TEMPO comparison (Google Earth Engine)
 *
 * Companion to eaton_validate_tropomi_s5p_no2.js: this script focuses on **paired** comparison
 * diagnostics — same footprint, optional **intersection** mask, **resampling** of S5P onto the
 * TEMPO grid (`resample`: **bilinear** or **bicubic** only; GEE does not support **nearest**),
 * **correlation**, **linear fit**, **MAE/RMSE**, **Δ/S5P** and **TEMPO/S5P** maps (where bias is worst),
 * and an optional **scatter**.
 *
 * Not rigorous inter-sensor validation (L3 daily vs TEMPO granule, different AMFs). Use as a
 * sanity check; tighten further with L2 + collocation in Python if needed.
 *
 * Keep EATON_GEOTRANSFORM in sync with gdalinfo on the GeoTIFFs you upload (same as plume script).
 *
 * SET CONFIG BELOW, paste into Code Editor, Run.
 */

var PROJECT = 'projects/earthengine-441016/assets';

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
  s5pMode: 'OFFL',
  dateStart: '2025-01-09',
  dateEnd: '2025-01-10',

  alignS5pToTempoGrid: true,
  aoi: ee.Geometry.Rectangle([-118.55, 33.55, -117.45, 34.35]),

  /** Native L3 zonal stats scale (m). */
  scaleM: 1113,

  maxPixels: 1e13,

  assetVcd: PROJECT + '/tempo_vcd_check_scd_over_amf_trop',
  assetVcdTroposphereL2: PROJECT + '/tempo_vcd_troposphere_utm11_clipped',

  crsTransform: null,

  /** Mask stats to pixels where both TEMPO and S5P (on TEMPO grid) are valid. */
  useIntersectionMask: true,

  /**
   * How S5P is resampled onto the TEMPO grid after reproject (ee.Image.resample).
   * Earth Engine only allows 'bilinear' or 'bicubic' — not 'nearest'. If you set 'nearest',
   * it falls back to 'bilinear'.
   */
  s5pResample: 'bilinear',

  /**
   * Random sample size for scatter chart (overlap region). 0 = skip chart.
   */
  scatterSamplePixels: 2500,
  scatterSeed: 42,

  /**
   * Floor on S5P (molec/cm²) when computing Δ/S5P and TEMPO/S5P — avoids divide-by-near-zero.
   */
  relativeBiasDenominatorMin: 1e12,

  opacity: 0.75,
};

var analysisGeometry = CONFIG.alignS5pToTempoGrid ? SAMPLE_RECT_BBOX : CONFIG.aoi;

// --- helpers -----------------------------------------------------------------

var MOLEC_CM2_PER_MOL_M2 = ee.Number(6.02214076e19);

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

/** GEE ee.Image.resample() accepts only 'bilinear' | 'bicubic'. */
function resampleMode() {
  var m = String(CONFIG.s5pResample || 'bilinear').toLowerCase();
  if (m === 'bicubic') {
    return 'bicubic';
  }
  return 'bilinear';
}

// --- S5P L3 load -------------------------------------------------------------

var col = s5pCollection()
  .select('tropospheric_NO2_column_number_density')
  .filterDate(CONFIG.dateStart, CONFIG.dateEnd)
  .filterBounds(analysisGeometry);

var s5pMeanMolM2 = col.mean().clip(analysisGeometry);
var s5pTropMolecCm2 = molM2ToMolecCm2(s5pMeanMolM2);

// --- TEMPO + reproject S5P to TEMPO grid -------------------------------------

var tempo = ee.Image(CONFIG.assetVcd).select([0]).rename('TEMPO');
var tempoProj = tempo.projection();

var s5pOnTempoGrid = s5pTropMolecCm2
  .reproject({ crs: tempoProj, scale: tempoProj.nominalScale() })
  .resample(resampleMode());

var both = tempo.mask().and(s5pOnTempoGrid.mask());
var tempoForStats = CONFIG.useIntersectionMask ? tempo.updateMask(both) : tempo;
var s5pForStats = CONFIG.useIntersectionMask ? s5pOnTempoGrid.updateMask(both) : s5pOnTempoGrid;

var diff = tempo.subtract(s5pOnTempoGrid).rename('diff').updateMask(both);

/** S5P with floor for ratios — where is TEMPO high vs S5P in relative terms? */
var s5pSafe = s5pOnTempoGrid.max(CONFIG.relativeBiasDenominatorMin).updateMask(both);
var relBias = diff.divide(s5pSafe).rename('rel_bias');
var tempoS5pRatio = tempo.updateMask(both).divide(s5pSafe).rename('ratio');

/**
 * One crs+scale for all paired-band ops. Cat() can leave bands with different projection metadata;
 * reproject unifies so reduceRegionCustom(img.projection()) works.
 */
var TEMPO_GRID = { crs: tempoProj, scale: tempoProj.nominalScale() };

// --- paired zonal stats ------------------------------------------------------

var tempoStats = reduceRegionCustom(
  tempoForStats,
  ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
  analysisGeometry
);
var s5pStats = reduceRegionCustom(
  s5pForStats,
  ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
  analysisGeometry
);
var diffStats = reduceRegionCustom(
  diff,
  ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
  analysisGeometry
);

// --- MAE / RMSE on overlap ---------------------------------------------------

var maeImg = diff.abs().rename('mae');
var maeRed = reduceRegionCustom(maeImg, ee.Reducer.mean(), analysisGeometry);
var rmseImg = diff.pow(2).rename('mse');
var rmseRed = reduceRegionCustom(rmseImg, ee.Reducer.mean(), analysisGeometry);
var rmse = ee.Number(rmseRed.get('mse')).sqrt();

var relBiasStats = reduceRegionCustom(
  relBias,
  ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
  analysisGeometry
);
var ratioStats = reduceRegionCustom(
  tempoS5pRatio,
  ee.Reducer.median().combine(ee.Reducer.mean(), '', true),
  analysisGeometry
);

// --- Pearson correlation (two bands: S5P, TEMPO) ----------------------------

var pairedXY = ee.Image.cat([s5pForStats.rename('S5P'), tempoForStats.rename('TEMPO')]).reproject(
  TEMPO_GRID
);
var pearsonRed = reduceRegionCustom(pairedXY, ee.Reducer.pearsonsCorrelation(), analysisGeometry);

// --- Linear fit: TEMPO ~ a * S5P + b (first band x = S5P, second y = TEMPO per EE linearFit) ---

var fitStack = ee.Image.cat([s5pForStats.rename('x'), tempoForStats.rename('y')]).reproject(
  TEMPO_GRID
);
var fitRed = reduceRegionCustom(fitStack, ee.Reducer.linearFit(), analysisGeometry);

// --- Console ----------------------------------------------------------------

print('=== TROPOMI (S5P L3) vs TEMPO — comparison ===');
print('S5P collection', CONFIG.s5pMode === 'NRTI' ? 'NRTI/L3_NO2' : 'OFFL/L3_NO2');
print('Date', CONFIG.dateStart, '→', CONFIG.dateEnd);
print('Region', CONFIG.alignS5pToTempoGrid ? 'SAMPLE_RECT_BBOX (UTM11)' : 'CONFIG.aoi');
print('S5P → TEMPO grid resample', resampleMode(), '(CONFIG.s5pResample)');
print('Intersection mask', CONFIG.useIntersectionMask);

print('TEMPO VCD_adj — median', tempoStats.get('TEMPO_median'));
print('TEMPO VCD_adj — mean', tempoStats.get('TEMPO_mean'));
print('TEMPO VCD_adj — count', tempoStats.get('TEMPO_count'));

print('S5P on TEMPO grid — median', s5pStats.get('NO2_molec_cm2_median'));
print('S5P on TEMPO grid — mean', s5pStats.get('NO2_molec_cm2_mean'));
print('S5P on TEMPO grid — count', s5pStats.get('NO2_molec_cm2_count'));

print('Δ (TEMPO − S5P) — median', diffStats.get('diff_median'));
print('Δ — mean (bias)', diffStats.get('diff_mean'));
print('Δ — count', diffStats.get('diff_count'));

print('MAE |TEMPO − S5P| (molec/cm²)', maeRed.get('mae'));
print('RMSE Δ (molec/cm²)', rmse);

print(
  '--- Relative bias (Δ/S5P), S5P floored at CONFIG.relativeBiasDenominatorMin — where % diff is largest ---'
);
print('Δ/S5P — median (dimensionless)', relBiasStats.get('rel_bias_median'));
print('Δ/S5P — mean', relBiasStats.get('rel_bias_mean'));
print('TEMPO/S5P — median (~1 if unbiased)', ratioStats.get('ratio_median'));
print('TEMPO/S5P — mean', ratioStats.get('ratio_mean'));

print('Pearson r (S5P, TEMPO)', pearsonRed.get('correlation'));
print('Pearson p-value', pearsonRed.get('p-value'));

print('Linear fit TEMPO ~ offset + scale·S5P — offset (intercept)', fitRed.get('offset'));
print('Linear fit — scale (slope)', fitRed.get('scale'));
print(
  'Linear fit — EE linearFit() only returns offset & scale (no SS in Dictionary). Use RMSE Δ above for error size.'
);

print(
  'Note: L3 daily composite vs TEMPO granule; interpret correlation/slope as exploratory.'
);

// --- Scatter chart (optional) ------------------------------------------------

if (CONFIG.scatterSamplePixels > 0) {
  var scatterImg = pairedXY.clip(analysisGeometry);
  var samples = scatterImg.updateMask(both).sample({
    region: analysisGeometry,
    scale: tempoProj.nominalScale(),
    numPixels: CONFIG.scatterSamplePixels,
    seed: CONFIG.scatterSeed,
    geometries: false,
    tileScale: 4,
  });

  var scatterChart = ui.Chart.feature
    .byFeature({
      features: samples,
      xProperty: 'S5P',
      yProperties: ['TEMPO'],
    })
    .setChartType('ScatterChart')
    .setOptions({
      title: 'TEMPO vs S5P (overlap, molecules/cm²)',
      hAxis: { title: 'S5P on TEMPO grid' },
      vAxis: { title: 'TEMPO VCD_adj' },
      dataOpacity: 0.35,
      pointSize: 2,
      legend: { position: 'none' },
    });

  print(scatterChart);
}

// --- Map ---------------------------------------------------------------------

Map.centerObject(analysisGeometry, 10);

Map.addLayer(
  tempo,
  { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] },
  'TEMPO VCD_adj',
  true,
  CONFIG.opacity
);
Map.addLayer(
  s5pOnTempoGrid,
  { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] },
  'S5P on TEMPO grid (' + resampleMode() + ')',
  false,
  CONFIG.opacity
);
Map.addLayer(
  diff,
  { min: -1e16, max: 1e16, palette: ['2166ac', 'f7f7f7', 'b2182b'] },
  'TEMPO − S5P (absolute)',
  false,
  CONFIG.opacity
);
Map.addLayer(
  relBias,
  {
    min: -0.5,
    max: 1.5,
    palette: ['2166ac', 'abd9e9', 'ffffbf', 'fdae61', 'b2182b'],
  },
  'Relative bias Δ/S5P (dimensionless; redder = TEMPO ≫ S5P)',
  false,
  CONFIG.opacity
);
Map.addLayer(
  tempoS5pRatio,
  { min: 0.5, max: 2.5, palette: ['313695', '4575b4', 'abd9e9', 'fee090', 'd73027'] },
  'TEMPO/S5P ratio (~1 = same column)',
  false,
  CONFIG.opacity
);
Map.addLayer(both.selfMask(), { palette: ['000000'] }, 'Overlap mask', false, 0.35);
Map.addLayer(ee.Feature(analysisGeometry), { color: '00ff88' }, 'Analysis footprint', true, 0.45);

var showL2 =
  CONFIG.assetVcdTroposphereL2 !== null &&
  CONFIG.assetVcdTroposphereL2 !== undefined &&
  typeof CONFIG.assetVcdTroposphereL2 === 'string' &&
  CONFIG.assetVcdTroposphereL2 !== '';

if (showL2) {
  Map.addLayer(
    ee.Image(CONFIG.assetVcdTroposphereL2).select([0]),
    { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'b12a90', 'e16462', 'fca636', 'f0f921'] },
    'L2 VCD troposphere (ref)',
    false,
    CONFIG.opacity
  );
}
