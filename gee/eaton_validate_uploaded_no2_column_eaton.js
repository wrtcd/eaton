/**
 * Eaton validation — uploaded NO₂ column (OMI, GOME-2, MISR, etc.)
 *
 * There is no public OMNO2 / GOME-2 L2 NO₂ ImageCollection in Earth Engine like S5P.
 * After you gdalwarp a product to your study grid, upload it as an Image asset and set
 * assetNo2Column below. Same workflow as the other eaton_validate_* scripts: AOI stats + optional
 * comparison to TEMPO VCD asset.
 *
 * Units: set COLUMN_UNITS to 'molec_cm2' (default) or 'mol_m2' (S5P-style).
 *
 * SET CONFIG BELOW, paste into Code Editor, Run.
 */

var PROJECT = 'projects/earthengine-441016/assets';

var CONFIG = {
  /**
   * Single-band NO2 column Image asset (warped GeoTIFF you uploaded to GEE).
   * Leave null only until you set an id below.
   * Quick test if you already imported step-03 troposphere: use the same line as eaton_plume_delta_mass.js
   *   assetNo2Column: PROJECT + '/tempo_vcd_troposphere_utm11_clipped',
   * For OMI/GOME/etc., upload that product and set its asset path here.
   */
  assetNo2Column: null,

  /** 'molec_cm2' or 'mol_m2' */
  columnUnits: 'molec_cm2',

  /**
   * AOI for stats (WGS84). Should overlap the asset; or set useAssetFootprint true.
   */
  aoi: ee.Geometry.Rectangle([-118.55, 33.55, -117.45, 34.35]),

  /** If true, ignore CONFIG.aoi and use the image footprint (bounds). */
  useAssetFootprint: false,

  scaleM: 2500,

  maxPixels: 1e13,

  /** Optional second asset (e.g. TEMPO troposphere) for difference map. */
  assetTempoReference: PROJECT + '/tempo_vcd_troposphere_utm11_clipped',

  opacity: 0.75,
};

function molM2ToMolecCm2(img) {
  var NA = 6.02214076e23;
  return img.multiply(NA).divide(1e4);
}

/** True if assetNo2Column is a non-empty string and not a placeholder. */
function hasNo2Asset() {
  var a = CONFIG.assetNo2Column;
  if (a === null || a === undefined) {
    return false;
  }
  if (typeof a !== 'string' || a === '') {
    return false;
  }
  if (a.indexOf('REPLACE_ME') !== -1) {
    return false;
  }
  return true;
}

var hasRef =
  CONFIG.assetTempoReference !== null &&
  CONFIG.assetTempoReference !== undefined &&
  typeof CONFIG.assetTempoReference === 'string' &&
  CONFIG.assetTempoReference !== '' &&
  CONFIG.assetTempoReference.indexOf('REPLACE_ME') === -1;

if (!hasNo2Asset()) {
  print('=== Uploaded NO2 column — no asset id set ===');
  print('In CONFIG, set assetNo2Column to a real Image asset, e.g.:');
  print("  assetNo2Column: " + PROJECT + "/tempo_vcd_troposphere_utm11_clipped,");
  print('or your OMI/GOME upload. No catalog here — use eaton_validate_tropomi_s5p_no2.js for S5P without an upload.');
  Map.centerObject(CONFIG.aoi, 9);
  Map.addLayer(CONFIG.aoi, { color: 'FFFFFF' }, 'AOI (set assetNo2Column)', true, 0.4);
} else {
  var raw = ee.Image(CONFIG.assetNo2Column).select([0]);
  var no2 =
    CONFIG.columnUnits === 'mol_m2' ? molM2ToMolecCm2(raw) : raw.rename('NO2_molec_cm2');

  var region = CONFIG.useAssetFootprint ? no2.geometry() : CONFIG.aoi;
  var clipped = no2.clip(region);

  var redu = clipped.reduceRegion({
    reducer: ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
    geometry: region,
    scale: CONFIG.scaleM,
    maxPixels: CONFIG.maxPixels,
    tileScale: 4,
  });

  print('=== Uploaded NO2 column (Eaton validation) ===');
  print('Asset', CONFIG.assetNo2Column, 'units', CONFIG.columnUnits);
  print('Zonal (median / mean / count)', redu);

  if (hasRef) {
    var ref = ee.Image(CONFIG.assetTempoReference).select([0]);
    var refProj = ref.projection();
    var no2OnRef = clipped.reproject({ crs: refProj, scale: refProj.nominalScale() });
    var diff = ref.subtract(no2OnRef).rename('TEMPO_minus_uploaded');

    var st = diff.reduceRegion({
      reducer: ee.Reducer.median().combine(ee.Reducer.mean(), '', true).combine(ee.Reducer.count(), '', true),
      geometry: region,
      crs: refProj,
      scale: refProj.nominalScale(),
      maxPixels: CONFIG.maxPixels,
      tileScale: 4,
    });
    print('TEMPO reference − uploaded (uploaded reprojected to TEMPO grid)', st);

    Map.addLayer(ref, { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] }, 'TEMPO reference', true, CONFIG.opacity);
    Map.addLayer(no2OnRef, { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] }, 'Uploaded on TEMPO grid', false, CONFIG.opacity);
    Map.addLayer(diff, { min: -1e16, max: 1e16, palette: ['2166ac', 'f7f7f7', 'b2182b'] }, 'TEMPO − uploaded', false, CONFIG.opacity);
  }

  Map.centerObject(region, 9);
  Map.addLayer(clipped, { min: 0, max: 5e16, palette: ['0d0887', '6a00a8', 'fca636', 'f0f921'] }, 'Uploaded NO2 (molec/cm²)', !hasRef, CONFIG.opacity);
  Map.addLayer(region, { color: 'FFFFFF' }, 'Region', true, 0.3);
}
