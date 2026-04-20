/**
 * Eaton — Google Earth Engine: tropospheric AMF from TEMPO L2 ATBD §3.1.3
 * (same discrete sum as scripts/tempo/amf_atbd_from_tempo.py)
 *
 *   AMF_trop ≈ Σ_k W_k · S_k · c_k
 *
 * over tropospheric layers only (p_trop ≤ p_mid ≤ p_s in hPa), with:
 *   W_k — scattering_weights (72 bands, swt_level order)
 *   S_k — gas_profile partial columns n_k, normalized by Σ n_j over troposphere only
 *   c_k — temperature correction from temperature_profile (Eq. 18, T_σ = 220 K)
 *
 * Hybrid η layer centers use Eta_A / Eta_B on support_data/surface_pressure in the
 * TEMPO NO2 L2 NetCDF (73 interface coefficients → 72 layers). Arrays below match
 * sample file TEMPO_NO2_L2_V03_20250109T184504Z_S008G09.nc; if your product version
 * changes coefficients, replace ETA_A / ETA_B from the same metadata on your granule.
 *
 * UPLOAD TO GEE (same grid & CRS as your Python warped stacks, e.g. UTM 11N):
 *   • 72-band GeoTIFF: scattering_weights
 *   • 72-band GeoTIFF: gas_profile
 *   • 72-band GeoTIFF: temperature_profile
 *   • 1-band: surface_pressure (hPa)
 *   • 1-band: tropopause_pressure (hPa)
 *
 * Set CONFIG asset paths, paste into Code Editor, Run. Map shows AMF_trop; optional
 * difference vs product amf_troposphere if you upload that 2-D asset too.
 */

// --- user configuration ----------------------------------------------------

var PROJECT = 'projects/earthengine-441016/assets';

var CONFIG = {
  assetScatteringWeights72: PROJECT + '/REPLACE_scattering_weights_72bands',
  assetGasProfile72: PROJECT + '/REPLACE_gas_profile_72bands',
  assetTemperatureProfile72: PROJECT + '/REPLACE_temperature_profile_72bands',
  assetSurfacePressure: PROJECT + '/REPLACE_surface_pressure',
  assetTropopausePressure: PROJECT + '/REPLACE_tropopause_pressure',
  /** Optional: product 2-D amf_troposphere on same grid — adds diff layer */
  assetAmfTroposphereProduct: null,

  /** AOI for quick stats (change or draw your own) */
  aoi: ee.Geometry.Rectangle([-118.55, 33.55, -117.45, 34.35]),

  opacity: 0.85,
};

// Eta coefficients (length 73) from TEMPO L2 surface_pressure variable metadata
var ETA_A = ee.List([
  0.0, 0.04804826155304909, 6.593751907348633, 13.13479995727539, 19.613109588623047,
  26.092010498046875, 32.57080841064453, 38.98200988769531, 45.33900833129883,
  51.696109771728516, 58.0532112121582, 64.36264038085938, 70.62197875976562,
  78.83422088623047, 89.09992218017578, 99.3652114868164, 109.18170166015625,
  118.95860290527344, 128.69590759277344, 142.91000366210938, 156.25999450683594,
  169.60899353027344, 181.61900329589844, 193.0970001220703, 203.25900268554688,
  212.14999389648438, 218.7760009765625, 223.8979949951172, 224.36300659179688,
  216.86500549316406, 201.19200134277344, 176.92999267578125, 150.39300537109375,
  127.83699798583984, 108.66300201416016, 92.36572265625, 78.5123062133789,
  66.60340881347656, 56.387908935546875, 47.6439094543457, 40.175411224365234,
  33.81000900268555, 28.367809295654297, 23.730409622192383, 19.79159927368164,
  16.45709991455078, 13.643400192260742, 11.276900291442871, 9.29294204711914,
  7.619842052459717, 6.216801166534424, 5.0468010902404785, 4.076570987701416,
  3.276431083679199, 2.620210886001587, 2.084969997406006, 1.6507899761199951,
  1.300510048866272, 1.0194400548934937, 0.7951341271400452, 0.616779088973999,
  0.4758060872554779, 0.3650411069393158, 0.27852609753608704, 0.2113489955663681,
  0.15949499607086182, 0.11970300227403641, 0.08934502303600311, 0.06600000709295273,
  0.04758501052856445, 0.03269999846816063, 0.019999999552965164, 0.009999999776482582,
]);

var ETA_B = ee.List([
  1.0, 0.9849519729614258, 0.9634060263633728, 0.9418650269508362, 0.9203870296478271,
  0.8989080190658569, 0.8774290084838867, 0.8560180068016052, 0.8346608877182007,
  0.8133038878440857, 0.7919468879699707, 0.7706375122070312, 0.7493782043457031,
  0.7211660146713257, 0.6858999133110046, 0.6506348848342896, 0.6158183813095093,
  0.5810415148735046, 0.5463042259216309, 0.4945901930332184, 0.44374018907546997,
  0.3928911089897156, 0.3433811068534851, 0.2944031059741974, 0.24674110114574432,
  0.2003501057624817, 0.1562241017818451, 0.11360210180282593, 0.06372006237506866,
  0.028010040521621704, 0.006960025057196617, 8.175413235278484e-9, 0.0, 0.0, 0.0, 0.0,
  0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
  0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
]);

var T_SIGMA_K = 220.0;
var C1 = 0.00316;
var C2 = 3.39e-6;

// --- helpers ---------------------------------------------------------------

function selectBandByIndex(img, bandNamesList, k) {
  var name = ee.String(bandNamesList.get(ee.Number(k)));
  return img.select([name]);
}

function layerMidPressureHpa(ps, k) {
  k = ee.Number(k);
  var ea0 = ee.Number(ETA_A.get(k));
  var ea1 = ee.Number(ETA_A.get(k.add(1)));
  var eb0 = ee.Number(ETA_B.get(k));
  var eb1 = ee.Number(ETA_B.get(k.add(1)));
  var pBot = ee.Image(ea0).add(ps.multiply(eb0));
  var pTop = ee.Image(ea1).add(ps.multiply(eb1));
  return pBot.add(pTop).multiply(0.5);
}

function temperatureCorrectionC(tKelvin) {
  var dt = tKelvin.subtract(T_SIGMA_K);
  return ee.Image(1.0)
    .subtract(ee.Image(C1).multiply(dt))
    .add(ee.Image(C2).multiply(dt.pow(2)));
}

/**
 * @param {ee.Image} w - 72 bands scattering weights
 * @param {ee.Image} gas - 72 bands gas_profile (molecules cm^-2 partial columns)
 * @param {ee.Image} temp - 72 bands temperature (K)
 * @param {ee.Image} ps - surface pressure hPa
 * @param {ee.Image} pTrop - tropopause pressure hPa
 * @return {{ amf: ee.Image, nSum: ee.Image }} AMF_trop and tropospheric n sum (QA)
 */
function computeAmfTropAtbd(w, gas, temp, ps, pTrop) {
  var wNames = ee.List(w.bandNames());
  var gNames = ee.List(gas.bandNames());
  var tNames = ee.List(temp.bandNames());

  var layers = ee.List.sequence(0, 71);

  var nPartialImages = layers.map(function (k) {
    k = ee.Number(k);
    var pMid = layerMidPressureHpa(ps, k);
    var trop = pMid.gte(pTrop).and(pMid.lte(ps));
    var nk = selectBandByIndex(gas, gNames, k).unmask(0).multiply(trop);
    return nk;
  });
  var nSum = ee.ImageCollection(nPartialImages).sum();

  var amfLayers = layers.map(function (k) {
    k = ee.Number(k);
    var pMid = layerMidPressureHpa(ps, k);
    var trop = pMid.gte(pTrop).and(pMid.lte(ps));
    var nSafe = selectBandByIndex(gas, gNames, k).unmask(0).multiply(trop);
    var sk = ee.Image(0).where(nSum.gt(0), nSafe.divide(nSum));
    var tk = selectBandByIndex(temp, tNames, k);
    var ck = temperatureCorrectionC(tk);
    var wk = selectBandByIndex(w, wNames, k);
    var ak = wk.multiply(sk).multiply(ck).multiply(trop);
    return ak;
  });

  var amf = ee.ImageCollection(amfLayers).sum();
  var valid = ps.mask().and(pTrop.mask());
  amf = amf.updateMask(valid);
  return { amf: amf.rename('AMF_trop_ATBD'), nSum: nSum.rename('n_trop_sum') };
}

// --- load assets & run -----------------------------------------------------

var w = ee.Image(CONFIG.assetScatteringWeights72);
var gas = ee.Image(CONFIG.assetGasProfile72);
var temp = ee.Image(CONFIG.assetTemperatureProfile72);
var ps = ee.Image(CONFIG.assetSurfacePressure).select([0]);
var pTrop = ee.Image(CONFIG.assetTropopausePressure).select([0]);

var out = computeAmfTropAtbd(w, gas, temp, ps, pTrop);
var amf = out.amf;

Map.addLayer(
  amf,
  { min: 0.5, max: 4.0, palette: ['0d0887', '6a00a8', 'b12a90', 'e16462', 'fca636', 'f0f921'] },
  'AMF_trop (GEE ATBD)',
  true,
  CONFIG.opacity
);

if (CONFIG.assetAmfTroposphereProduct) {
  var amfProd = ee.Image(CONFIG.assetAmfTroposphereProduct).select([0]).rename('amf_prod');
  var diff = amf.subtract(amfProd).rename('AMF_recomputed_minus_product');
  Map.addLayer(
    diff,
    { min: -0.2, max: 0.2, palette: ['2166ac', 'f7f7f7', 'b2182b'] },
    'AMF recompute − product',
    false,
    CONFIG.opacity
  );
}

var stats = amf.reduceRegion({
  reducer: ee.Reducer.minMax().combine(ee.Reducer.mean().combine(ee.Reducer.count(), '', true), '', true),
  geometry: CONFIG.aoi,
  scale: 3000,
  maxPixels: 1e13,
});

print('AMF_trop ATBD (sample region)', stats);
print('Tropospheric partial-column sum (gas_profile, QA)', out.nSum.reduceRegion({
  reducer: ee.Reducer.mean().combine(ee.Reducer.count(), '', true),
  geometry: CONFIG.aoi,
  scale: 3000,
  maxPixels: 1e13,
}));

Map.centerObject(CONFIG.aoi, 9);
