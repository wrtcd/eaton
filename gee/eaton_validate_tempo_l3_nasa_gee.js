/**
 * Eaton validation — TEMPO NO₂ Level 3 from NASA (GEE catalog)
 *
 * Same workflow as eaton_validate_tropomi_s5p_no2.js:
 *   AOI + dates → NASA/TEMPO/NO2_L3 → tropospheric column (already molecules/cm²).
 *   Zonal stats; optional compare to uploaded GeoTIFF asset (your warped L2 pipeline).
 *
 * Catalog: NASA/TEMPO/NO2_L3  (QA-filtered variant: NASA/TEMPO/NO2_L3_QA)
 * Primary band: vertical_column_troposphere (molecules/cm²)
 *
 * SET CONFIG BELOW, paste into Code Editor, Run.
 */

var PROJECT = 'projects/earthengine-441016/assets';

var CONFIG = {
  /** false = NASA/TEMPO/NO2_L3 ; true = NASA/TEMPO/NO2_L3_QA */
  useQaFiltered: false,

  dateStart: '2025-01-09',
  dateEnd: '2025-01-10',

  aoi: ee.Geometry.Rectangle([-118.55, 33.55, -117.45, 34.35]),

  /** ~TEMPO L3 nominal scale in EE catalog. */
  scaleM: 2226,

  maxPixels: 1e13,

  /** Optional upload for comparison (your step 03 warped troposphere). */
  assetTempoVcdTroposphere: PROJECT + '/tempo_vcd_troposphere_utm11_clipped',

  opacity: 0.75,
};

function tempoL3Collection() {
  var id = CONFIG.useQaFiltered ? 'NASA/TEMPO/NO2_L3_QA' : 'NASA/TEMPO/NO2_L3';
  return ee.ImageCollection(id).select('vertical_column_troposphere');
}

var col = tempoL3Collection().filterDate(CONFIG.dateStart, CONFIG.dateEnd).filterBounds(CONFIG.aoi);

var tempoMean = col.mean().clip(CONFIG.aoi).rename('TEMPO_L3_trop_molec_cm2');

var redu = tempoMean.reduceRegion({
  reducer: ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
  geometry: CONFIG.aoi,
  scale: CONFIG.scaleM,
  maxPixels: CONFIG.maxPixels,
  tileScale: 4,
});

print('=== TEMPO L3 (NASA GEE catalog) ===');
print('Collection', CONFIG.useQaFiltered ? 'NASA/TEMPO/NO2_L3_QA' : 'NASA/TEMPO/NO2_L3');
print('Date', CONFIG.dateStart, '→', CONFIG.dateEnd);
print('Images in filter', col.size());
print('vertical_column_troposphere (molecules/cm²) — median / mean / count', redu);

var hasAsset =
  CONFIG.assetTempoVcdTroposphere !== null &&
  CONFIG.assetTempoVcdTroposphere !== undefined &&
  CONFIG.assetTempoVcdTroposphere !== '';

if (hasAsset) {
  var asset = ee.Image(CONFIG.assetTempoVcdTroposphere).select([0]).rename('asset');
  var assetProj = asset.projection();
  var l3OnAsset = tempoMean.reproject({ crs: assetProj, scale: assetProj.nominalScale() });
  var diff = asset.subtract(l3OnAsset).rename('asset_minus_L3');

  var st = diff.reduceRegion({
    reducer: ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
    geometry: CONFIG.aoi,
    crs: assetProj,
    scale: assetProj.nominalScale(),
    maxPixels: CONFIG.maxPixels,
    tileScale: 4,
  });
  print('Difference uploaded TEMPO − GEE L3 (L3 reprojected to asset grid)', st);
  print('Large offsets can mean different granule time, L3 compositing, or warp vs product grid.');

  Map.addLayer(asset, { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] }, 'Uploaded TEMPO VCD', true, CONFIG.opacity);
  Map.addLayer(l3OnAsset, { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] }, 'GEE TEMPO L3 on asset grid', false, CONFIG.opacity);
  Map.addLayer(diff, { min: -1e16, max: 1e16, palette: ['2166ac', 'f7f7f7', 'b2182b'] }, 'asset − L3', false, CONFIG.opacity);
}

Map.centerObject(CONFIG.aoi, 9);
Map.addLayer(
  tempoMean,
  { min: 0, max: 1.5e16, bands: ['TEMPO_L3_trop_molec_cm2'], palette: ['000080', '0080FF', 'FF8080', '800000'] },
  'TEMPO L3 trop (GEE, mean over window)',
  !hasAsset,
  CONFIG.opacity
);
Map.addLayer(CONFIG.aoi, { color: 'FFFFFF' }, 'AOI', true, 0.3);
