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
 * Total NO₂ kg: reproject to EATON_GEOTRANSFORM, then reduceRegion.sum + crsTransform; if sum is 0,
 * fallback sum @ projection+nominalScale ÷ 65536 (EE resampling quirk). Paste gdalinfo GeoTransform
 * on your uploaded file into EATON_GEOTRANSFORM so the native sum path matches and fallback is unused.
 * VCD_bg fallback is 0 if all median branches fail.
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
 * Paste `gdalinfo` affine into EATON_GEOTRANSFORM for reference. Set CONFIG.crsTransform to
 * that array only after verifying it matches the ingested asset; otherwise leave null.
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

/** Pixel grid (must match uploaded GeoTIFF). sampleRectangle needs this exact UTM rectangle — vcd.geometry().bounds() can misalign and return all zeros. */
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

  /**
   * Histogram / chart resampling (m). Reducers use crsTransform when set, else proj.nominalScale().
   */
  scaleM: 3220,

  /**
   * Pixel area (m²) = |GT1 × GT5| from tempo_plume_mass_summary.json — matches Python mass step.
   */
  pixelAreaM2: 10357338.55632546,

  /**
   * Optional: set to EATON_GEOTRANSFORM only if those six numbers match the GEE asset *exactly*
   * (same gdalinfo GeoTransform as ingested). If they differ even slightly, reduceRegion returns
   * no samples → VCD_bg "failed", mass 0. Default null = use proj.nominalScale() (matches Python).
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

/**
 * Medians, counts, stats, and mass sums.
 * Prefer crsTransform (native affine). Otherwise use crs: img.projection() + nominalScale —
 * NOT crs: 'EPSG:32611' + scale alone: that reprojects onto a new grid and can duplicate
 * pixels in Reducer.sum() (~10^4–10^5× mass inflation vs Python).
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

var deltaRaw = vcd.subtract(vcdBg);
var delta = deltaRaw.updateMask(vcdFinite);
var deltaPlume = fp.multiply(delta).updateMask(maskValid).rename('dplume');

/** Match Python: screened f_p pixels should not contribute (already excluded from maskValid) */

// Unmasked plume column for mass totals (zeros where invalid) — matches Python finite mask
var deltaPlumeUnmasked = fp.multiply(deltaRaw).multiply(maskValid.toFloat()).rename('dplume');

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
// Constant pixel area on every cell (Python: abs(a·e) per pixel). Do not leave area masked from
// deltaPlume — masked area × unmasked ΔVCD_plume zeros yields masked mass → sampleRectangle sum 0.
var areaM2 = deltaPlume.multiply(0).add(m2PerPx).rename('area_m2');
var cm2PerPx = m2PerPx.multiply(1e4);
var areaCm2 = areaM2.multiply(1e4).unmask(cm2PerPx);
var massKg = deltaPlume.multiply(areaCm2).divide(N_A).multiply(M_NO2).rename('mass_kg');
/** Same formula on unmasked ΔVCD_plume (invalid pixels = 0) — for native-pixel sum only */
var massKgForSum = deltaPlumeUnmasked
  .multiply(areaCm2)
  .divide(N_A)
  .multiply(M_NO2)
  .unmask(0)
  .rename('mass_kg');

// --- zonal / summary stats -------------------------------------------------

/**
 * Mass total on the 101×69 grid. Prefer reproject → crsTransform sum (matches affine).
 * If that is 0 (ingested GeoTransform ≠ EATON_GEOTRANSFORM), fall back to projection+scale sum
 * ÷ 65536 — observed EE inflation when scale does not match native pixels (~256² subcells).
 */
function sumMassKgOnNativeGrid(imgUnmaskedMass) {
  var img = imgUnmaskedMass.unmask(0).rename('mass_kg');
  var onGrid = img.reproject({
    crs: 'EPSG:32611',
    crsTransform: EATON_GEOTRANSFORM,
  });
  var sumNative = ee.Number(
    onGrid
      .reduceRegion({
        reducer: ee.Reducer.sum(),
        geometry: SAMPLE_RECT_BBOX,
        crs: 'EPSG:32611',
        crsTransform: EATON_GEOTRANSFORM,
        maxPixels: CONFIG.maxPixels,
        tileScale: 4,
      })
      .get('mass_kg')
  );
  var sumInflated = ee.Number(
    img.reduceRegion({
      reducer: ee.Reducer.sum(),
      geometry: SAMPLE_RECT_BBOX,
      crs: proj,
      scale: proj.nominalScale(),
      maxPixels: CONFIG.maxPixels,
      tileScale: 4,
    }).get('mass_kg')
  );
  var inflationFactor = 65536;
  return ee.Number(
    ee.Algorithms.If(sumNative.gt(0), sumNative, sumInflated.divide(inflationFactor))
  );
}

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

var totalKgAllPixels = sumMassKgOnNativeGrid(massKgForSum);

var posMask = massKg.gt(0);
var massKgPositiveOnly = massKgForSum.multiply(massKgForSum.gt(0).toFloat()).rename('mass_kg');
var totalKgPositiveOnly = sumMassKgOnNativeGrid(massKgPositiveOnly);

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
    ? 'reduceRegion + crsTransform (must match asset exactly)'
    : 'reduceRegion @ crs: image.projection() + nominalScale (avoid EPSG string + scale)'
);
print(
  'Total NO₂ kg: native crsTransform sum if >0; else inflated sum ÷ 65536 (see sumMassKgOnNativeGrid).'
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
