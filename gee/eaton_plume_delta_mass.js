/**
 * Eaton TEMPO plume workflow — Google Earth Engine mirror of:
 *   scripts/tempo/delta_vcd_plume.py  (step 07)
 *   scripts/tempo/mass_no2_from_plume.py (step 08)
 *
 * WHAT TO UPLOAD AS GEE ASSETS (Image or ImageCollection→mosaic):
 *   1) VCD_adj — e.g. tempo_vcd_check_scd_over_amf_trop.tif (step 06), same grid as Python.
 *   2) f_p — e.g. tempo_fp_plume_utm11_clipped.tif (step 04), same grid & CRS as VCD_adj.
 *
 * Optional FeatureCollection (e.g. mask_reprojected): map outline / centering only.
 * It does NOT replace f_p (per-pixel fraction on the TEMPO grid).
 *
 * SET YOUR ASSET IDS BELOW, then paste this entire file into the Code Editor and Run.
 *
 * Total NO₂ kg: sum via sampleRectangle + ee.Array (native pixels), not reduceRegion sum.
 * VCD_bg fallback is 0 if all median branches fail. Optional crsTransform for zonal stats only.
 *
 * Map shift (plumes offset vs basemap / mountains): Each layer is drawn using only the
 * GeoTIFF’s CRS and affine transform. Earth Engine does not invent placement beyond that
 * metadata. A shift means the uploaded file’s bounds or CRS tag does not match your
 * local Python stack (or GEE ingestion mis-read the CRS).
 *
 * Fix on disk (preferred — avoids resampling that would corrupt mass totals):
 *   1) On the **same** GeoTIFF you upload, run `gdalinfo` and compare “Corner Coordinates”
 *      in meters to your Python reference raster; both should be EPSG:32611 (UTM 11N) and
 *      agree within a small tolerance.
 *   2) If pixel values are correct but metadata is wrong, fix tags without resampling, e.g.
 *      `gdal_edit.py your.tif -a_srs EPSG:32611` and/or `-a_gt gt0 gt1 gt2 gt3 gt4 gt5`
 *      using the six affine terms from `gdalinfo` on the **reference** grid.
 *   3) Re-upload / re-ingest the asset; if the importer guessed CRS, set EPSG:32611
 *      explicitly. The basemap is Web Mercator; EE reprojects your raster for display —
 *      wrong bounds in the file still look like a shift.
 * Do **not** use ee.Image.reproject() in this script to “nudge” the map: that resamples
 * pixels and invalidates the native-pixel mass sum. Match Python by fixing the GeoTIFF.
 *
 * Paste `gdalinfo` affine into EATON_GEOTRANSFORM below; set CONFIG.crsTransform when
 * reducers must use that exact grid (see comments on CONFIG.crsTransform).
 */

// --- user configuration ----------------------------------------------------

var PROJECT = 'projects/earthengine-441016/assets';

/**
 * Six-element GDAL GeoTransform from `gdalinfo` on **the exact GeoTIFF you uploaded** to GEE.
 * Do not use the repo default unless that file is byte-identical; wrong numbers break medians
 * and stats. If you fixed CRS/affine with gdal_edit (see header “Map shift”), paste the new
 * values here.
 */
var EATON_GEOTRANSFORM = [
  232153.3523,
  (557208.806 - 232153.3523) / 101,
  0,
  3856746.1228,
  0,
  -(3856746.1228 - 3634690.804) / 69,
];

var CONFIG = {
  /** VCD_adj — step 06 (SCD/AMF_trop); used for ΔVCD & mass. */
  assetVcd: PROJECT + '/tempo_vcd_check_scd_over_amf_trop',
  /** L2 tropospheric VCD (step 03) — map only; set null to hide. */
  assetVcdTroposphereL2: PROJECT + '/tempo_vcd_troposphere_utm11_clipped',

  /** f_p [0,1], same grid as assetVcd */
  assetFp: PROJECT + '/tempo_fp_plume_utm11_clipped',

  /**
   * Optional FeatureCollection for map outline (e.g. mask_reprojected). Set null to skip.
   * Reducers use the full valid VCD ∩ f_p extent, not this outline.
   */
  maskOutlineFc: null,

  /** Nodata on VCD GeoTIFF if applicable (set null to only use finite + > -1e20) */
  vcdNodata: null,
  /** Screening nodata on f_p (-9999 in Python pipeline) */
  fpNodata: -9999,

  /** Background column: median where f_p <= fpEps, then fallback f_p < fpLow, then all valid */
  fpEps: 1e-6,
  fpLow: 0.05,

  /** Medians / stats / charts: ~match printed VCD nominalScale (m). */
  scaleM: 3220,

  /**
   * Pixel area (m²) = |GT1 × GT5| from tempo_plume_mass_summary.json — matches Python mass step.
   */
  pixelAreaM2: 10357338.55632546,

  /**
   * Set to EATON_GEOTRANSFORM only if that grid matches your GEE asset (see file header). Else null.
   */
  crsTransform: null,

  maxPixels: 1e13,

  /** Map layer opacity */
  opacity: 0.85,
};

/** NO₂ molar mass (kg/mol), Avogadro (1/mol) — match mass_no2_from_plume.py */
var M_NO2 = 46.0055e-3;
var N_A = 6.02214076e23;

// --- load images -----------------------------------------------------------

var vcdRaw = ee.Image(CONFIG.assetVcd);
var fpRaw = ee.Image(CONFIG.assetFp);

var vcd = vcdRaw.select([0]).rename('VCD');
var fp = fpRaw.select([0]).rename('fp');

var showTropL2 =
  CONFIG.assetVcdTroposphereL2 !== null &&
  CONFIG.assetVcdTroposphereL2 !== undefined &&
  typeof CONFIG.assetVcdTroposphereL2 === 'string' &&
  CONFIG.assetVcdTroposphereL2 !== '';
var vcdTropL2 = showTropL2
  ? ee.Image(CONFIG.assetVcdTroposphereL2).select([0]).rename('VCD')
  : null;

var vcdFinite = vcd.gt(-1e20);
if (CONFIG.vcdNodata !== null) {
  vcdFinite = vcdFinite.and(vcd.neq(CONFIG.vcdNodata));
}

var fpFinite = fp.gte(0).and(fp.lte(1.000001));
if (CONFIG.fpNodata !== null && isFinite(CONFIG.fpNodata)) {
  fpFinite = fpFinite.and(fp.neq(CONFIG.fpNodata));
}

var maskValid = vcdFinite.and(fpFinite);

/** Native projection — must be passed as crs: to every reduceRegion or WGS84 resampling
 * inflates counts/sums by ~1e4–1e5× for these UTM rasters (scale in meters mis-applied). */
var proj = vcd.projection();

/** Region for reducers: valid overlap of VCD and f_p (matches Python full-grid median). */
var analysisRegion = maskValid.selfMask().geometry();

/** Optional mask FC only for map framing / outline (null = skip). */
var maskOutlineFc = CONFIG.maskOutlineFc;
var hasMaskOutline =
  maskOutlineFc !== null &&
  typeof maskOutlineFc === 'string' &&
  maskOutlineFc !== '' &&
  maskOutlineFc.indexOf('REPLACE_ME') === -1;
var maskFcGeom = hasMaskOutline ? ee.FeatureCollection(maskOutlineFc).geometry() : null;

var mapViewRegion = hasMaskOutline ? maskFcGeom : analysisRegion;

var scaleAnalysis = CONFIG.scaleM;

function _useCrsTransform() {
  return (
    CONFIG.crsTransform !== null &&
    Array.isArray(CONFIG.crsTransform) &&
    CONFIG.crsTransform.length === 6
  );
}

/** Medians, counts, stats — crs+scale; optional crsTransform if set and matches asset. */
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
  return img.reduceRegion({
    reducer: reducer,
    geometry: geometry,
    crs: 'EPSG:32611',
    scale: scaleAnalysis,
    maxPixels: CONFIG.maxPixels,
    tileScale: 4,
  });
}

/**
 * Total kg by summing native-resolution pixels (no reduceRegion reprojection path).
 * reduceRegion(..., Reducer.sum()) still resamples first; extensive per-pixel kg then sums wrong (~1e5×).
 * sampleRectangle → ee.Array; sum via reduce(..., [0, 1]) (flatten/matrixToVector not on JS ee.Array).
 */
function sumMassKgNative(imgUnmaskedOrMasked) {
  var bbox = analysisRegion.bounds(1, proj);
  var rect = imgUnmaskedOrMasked.unmask(0).sampleRectangle({
    region: bbox,
    defaultValue: 0,
  });
  var arr = ee.Array(rect.get('mass_kg'));
  return arr.reduce(ee.Reducer.sum(), [0, 1]).get([0, 0]);
}

// --- VCD_bg: same decision tree as delta_vcd_plume._vcd_background ------------

function medianAndCount(img, maskBool, geometry) {
  var masked = img.updateMask(maskBool);
  var med = reduceRegionCustom(masked, ee.Reducer.median(), geometry);
  var cnt = reduceRegionCustom(masked, ee.Reducer.count(), geometry);
  return { median: med.get('VCD'), count: ee.Number(cnt.get('VCD')) };
}

var base = maskValid;
var m0 = base.and(fp.lte(CONFIG.fpEps));
var m1 = base.and(fp.lt(CONFIG.fpLow));

var r0 = medianAndCount(vcd, m0, analysisRegion);
var r1 = medianAndCount(vcd, m1, analysisRegion);
var r2 = medianAndCount(vcd, base, analysisRegion);

var n0 = r0.count;
var n1 = r1.count;
var n2 = r2.count;

var vcdBg = ee.Number(
  ee.Algorithms.If(
    n0.gt(0),
    r0.median,
    ee.Algorithms.If(
      n1.gt(0),
      r1.median,
      ee.Algorithms.If(n2.gt(0), r2.median, 0)
    )
  )
);

var vcdBgMethod = ee.String(
  ee.Algorithms.If(
    n0.gt(0),
    'median where f_p <= fpEps',
    ee.Algorithms.If(
      n1.gt(0),
      'median where f_p < fpLow (no strict non-plume pixels)',
      ee.Algorithms.If(
        n2.gt(0),
        'median over all valid pixels (fallback)',
        'failed'
      )
    )
  )
);

// --- ΔVCD and ΔVCD_plume = f_p * ΔVCD --------------------------------------

var delta = vcd.subtract(vcdBg).updateMask(vcdFinite);
var deltaPlume = fp.multiply(delta).updateMask(maskValid).rename('dplume');

/** Match Python: screened f_p pixels should not contribute (already excluded from maskValid) */

// --- Mass (kg) per pixel — mass_no2_from_plume ------------------------------
//
// Python uses one m² per cell: abs(transform.a * transform.e). ee.Image.pixelArea()
// (even reprojected) has produced ~10⁶× wrong areas on these assets — use constant
// m² per pixel on the same grid as deltaPlume: nominalScale², or CONFIG.pixelAreaM2.

var ns = ee.Number(vcd.projection().nominalScale());
var m2PerPx =
  CONFIG.pixelAreaM2 !== null && CONFIG.pixelAreaM2 > 0
    ? ee.Number(CONFIG.pixelAreaM2)
    : ns.multiply(ns);
var areaM2 = deltaPlume.multiply(0).add(m2PerPx).rename('area_m2');
var areaCm2 = areaM2.multiply(1e4);
var massKg = deltaPlume.multiply(areaCm2).divide(N_A).multiply(M_NO2).rename('mass_kg');

// --- zonal / summary stats -------------------------------------------------

function imageStats(img) {
  return reduceRegionCustom(
    img,
    ee.Reducer.minMax()
      .combine(ee.Reducer.mean(), '', true)
      .combine(ee.Reducer.stdDev(), '', true)
      .combine(ee.Reducer.count(), '', true),
    analysisRegion
  );
}

var totalKgAllPixels = sumMassKgNative(massKg);

var posMask = massKg.gt(0);
var totalKgPositiveOnly = sumMassKgNative(massKg.updateMask(posMask));

var negMask = massKg.lt(0).and(massKg.mask());
var nPos = reduceRegionCustom(massKg.updateMask(posMask), ee.Reducer.count(), analysisRegion);
var nNeg = reduceRegionCustom(massKg.updateMask(negMask), ee.Reducer.count(), analysisRegion);
var nValid = reduceRegionCustom(massKg.mask(), ee.Reducer.count(), analysisRegion);

// --- print numeric summary (Console) ---------------------------------------

print('=== Eaton plume delta / mass (GEE mirror of steps 07–08) ===');
print('Assets:', { vcd_adj: CONFIG.assetVcd, f_p: CONFIG.assetFp });
print('VCD projection (CRS)', proj);
print('VCD nominalScale (m) — set CONFIG.scaleM equal to this for reducers', vcd.projection().nominalScale());
print('CRS strings (must match for aligned stacks)', { vcd_crs: proj.crs(), fp_crs: fp.projection().crs() });
print('m² per pixel used for mass (Python: abs(a·e); here nominalScale² or CONFIG.pixelAreaM2)', m2PerPx);
print(
  'Zonal stats:',
  _useCrsTransform()
    ? 'crsTransform for reduceRegion (optional)'
    : 'reduceRegion @ scale ' + scaleAnalysis + ' m (medians, counts, imageStats)'
);
print(
  'Total NO₂ kg uses sampleRectangle + sum(native pixels) — not reduceRegion sum (avoids ~1e5× bug).'
);

print('VCD_bg (molecules/cm²)', vcdBg);
print('VCD_bg method', vcdBgMethod);
print('Delta VCD stats (band VCD: min/max/mean/stdDev/count)', imageStats(delta));
print('Delta VCD_plume stats (band dplume)', imageStats(deltaPlume));
print('Total NO₂ mass, all signed pixels (kg)', totalKgAllPixels);
print('Total NO₂ mass, positive pixels only (kg)', totalKgPositiveOnly);
print('Counts: valid / positive mass / negative mass', {
  valid: nValid.get('mass_kg'),
  positive: nPos.get('mass_kg'),
  negative: nNeg.get('mass_kg'),
});
print(
  'Python reference (local step 08 / tempo_plume_mass_summary.json): total NO₂ ~30251 kg; ' +
    'counts n_valid ~4504, n_positive ~152 — GEE totals should match order of magnitude.'
);

// --- Map --------------------------------------------------------------------

Map.centerObject(mapViewRegion, 10);

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
  vcd,
  { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'b12a90', 'e16462', 'fca636', 'f0f921'] },
  'VCD_adj (step 06 check)',
  true,
  CONFIG.opacity
);
Map.addLayer(
  delta,
  { min: -5e15, max: 5e15, palette: ['2166ac', 'f7f7f7', 'b2182b'] },
  'Delta VCD',
  false,
  CONFIG.opacity
);
Map.addLayer(
  deltaPlume,
  { min: 0, max: 5e15, palette: ['440154', '31688e', '35b779', 'fde725'] },
  'Delta VCD_plume (f_p · ΔVCD)',
  true,
  CONFIG.opacity
);
Map.addLayer(
  massKg,
  { min: 0, max: 5e4, palette: ['ffffcc', 'fd8d3c', 'd7301f', '7f0000'] },
  'NO₂ mass kg/pixel (signed)',
  true,
  CONFIG.opacity
);
Map.addLayer(
  posMask.selfMask(),
  { palette: ['00aa00'] },
  'Positive mass pixels',
  false,
  0.35
);

if (hasMaskOutline) {
  Map.addLayer(ee.FeatureCollection(maskOutlineFc), { color: 'white' }, 'mask outline (display only)', true, 0.6);
}

// --- Charts (ui) — ΔVCD_plume in ×10¹⁵ molec/cm² so bucket labels stay readable

var dp1e15 = deltaPlume.divide(1e15).rename('d15');
var chartDeltaPlume = ui.Chart.image.histogram({
  image: dp1e15,
  region: analysisRegion,
  scale: scaleAnalysis,
  maxBuckets: 40,
})
  .setOptions({
    title: 'Histogram: ΔVCD_plume (units: ×10¹⁵ molecules/cm²)',
    hAxis: { title: 'ΔVCD_plume / 1e15' },
    vAxis: { title: 'Pixel count' },
    legend: { position: 'none' },
  });

var chartMassPos = ui.Chart.image.histogram({
  image: massKg.updateMask(massKg.gt(0)),
  region: analysisRegion,
  scale: scaleAnalysis,
  maxBuckets: 40,
})
  .setOptions({
    title: 'Histogram: positive NO₂ mass (kg/pixel)',
    hAxis: { title: 'kg', format: 'decimal' },
    vAxis: { title: 'Pixel count' },
  });

print(chartDeltaPlume);
print(chartMassPos);
