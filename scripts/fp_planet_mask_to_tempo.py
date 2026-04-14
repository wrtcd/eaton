"""
Aggregate a Planet-resolution plume mask onto the TEMPO grid (f_p).

For each TEMPO pixel, f_p is the mean of the binary mask M over all Planet pixels
that fall inside that cell (equivalently: fraction of the TEMPO cell covered by plume).

  f_p = sum(M) / N   with M in {0,1}  =>  mean(M) per TEMPO pixel

Mask input:
  - Vector: shapefile/geojson (polygons burned as 1, exterior 0), or
  - Raster: GeoTIFF (values > 0 treated as in-plume); warped to the Planet reference
    grid first if shape/CRS differ.

Planet reference: any GeoTIFF that defines the high-res grid (same as your Planet mosaic).

TEMPO reference: warped TEMPO layer (defines output CRS, transform, dimensions).

Usage (defaults match eaton layout):
  py -3 scripts/fp_planet_mask_to_tempo.py
  py -3 scripts/fp_planet_mask_to_tempo.py --mask data/aoi/mask.shp \\
      --planet-ref data/planet/20250109_184929_70_24bd_3B_AnalyticMS_SR_8b.tif \\
      --tempo-ref "step-by-step/03 tempo/tempo_vcd_troposphere_utm11_clipped.tif"

Requires: numpy, rasterio, and for vector masks either **pyogrio** (+ shapely/geopandas, typical on Py3.14) or **fiona**.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import rasterio
    from rasterio.crs import CRS
    from rasterio.features import rasterize
    from rasterio.warp import reproject, Resampling, transform_geom
except ImportError as e:
    print("Install rasterio: py -3 -m pip install rasterio", file=sys.stderr)
    raise SystemExit(1) from e

try:
    import pyogrio
except ImportError:
    pyogrio = None
try:
    import fiona
except ImportError:
    fiona = None

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_STEP03 = _REPO_ROOT / "step-by-step" / "03 tempo"
_DEFAULT_STEP04 = _REPO_ROOT / "step-by-step" / "04 plume fraction"
_DEFAULT_MASK = _REPO_ROOT / "data" / "aoi" / "mask.shp"
_DEFAULT_TEMPO = _DEFAULT_STEP03 / "tempo_vcd_troposphere_utm11_clipped.tif"
_DEFAULT_OUT = _DEFAULT_STEP04 / "tempo_fp_plume_utm11_clipped.tif"
_DEFAULT_TEMPO_SCREEN = _DEFAULT_STEP03 / "tempo_mask_screen_utm11_clipped.tif"
_FP_SCREEN_NODATA = -9999.0


def _vector_shapes_pyogrio(mask_path: Path, planet) -> list:
    """GeoJSON geometries for rasterize, reprojected to planet CRS."""
    from shapely.geometry import mapping

    shapes: list = []
    gdf = pyogrio.read_dataframe(mask_path)
    crs = gdf.crs
    src_crs = CRS.from_epsg(4326) if crs is None else CRS.from_user_input(crs)
    for geom in gdf.geometry:
        if geom is None:
            continue
        if getattr(geom, "is_empty", False):
            continue
        g = mapping(geom)
        if src_crs != planet.crs:
            g = transform_geom(src_crs, planet.crs, g)
        shapes.append((g, 1))
    return shapes


def _vector_shapes_fiona(mask_path: Path, planet) -> list:
    shapes: list = []
    with fiona.open(mask_path) as src:
        src_crs = CRS.from_user_input(src.crs or "EPSG:4326")
        for feat in src:
            geom = feat["geometry"]
            if geom is None:
                continue
            if src_crs != planet.crs:
                geom = transform_geom(src_crs, planet.crs, geom)
            shapes.append((geom, 1))
    return shapes


def _rasterize_vector_to_planet(mask_path: Path, planet) -> np.ndarray:
    """Binary mask on planet grid (uint8 0/1)."""
    shapes: list = []
    if pyogrio is not None:
        try:
            shapes = _vector_shapes_pyogrio(mask_path, planet)
        except Exception:
            shapes = []
    if not shapes and fiona is not None:
        shapes = _vector_shapes_fiona(mask_path, planet)
    if not shapes and pyogrio is None and fiona is None:
        print(
            "ERROR: vector mask needs pyogrio or fiona. "
            "Try: py -3 -m pip install pyogrio shapely",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not shapes:
        raise SystemExit(f"No features in {mask_path} (or failed to read with pyogrio/fiona)")

    out = rasterize(
        shapes,
        out_shape=(planet.height, planet.width),
        transform=planet.transform,
        fill=0,
        dtype=np.uint8,
        all_touched=False,
    )
    return out


def _read_mask_raster_to_planet(mask_path: Path, planet) -> np.ndarray:
    """Warp mask raster onto planet grid; plume where value > 0 (after nodata cleared)."""
    with rasterio.open(mask_path) as m:
        dst = np.zeros((planet.height, planet.width), dtype=np.float32)
        src = m.read(1).astype(np.float32)
        nodata = m.nodatavals[0] if m.nodatavals else None
        if nodata is not None and np.isfinite(nodata):
            src[src == nodata] = np.nan
        reproject(
            source=src,
            destination=dst,
            src_transform=m.transform,
            src_crs=m.crs,
            dst_transform=planet.transform,
            dst_crs=planet.crs,
            resampling=Resampling.nearest,
        )
    binary = (np.isfinite(dst) & (dst > 0)).astype(np.uint8)
    return binary


def _mask_on_planet_grid(mask_path: Path, planet) -> np.ndarray:
    suf = mask_path.suffix.lower()
    if suf in (".shp", ".json", ".geojson"):
        return _rasterize_vector_to_planet(mask_path, planet)
    if suf in (".tif", ".tiff"):
        return _read_mask_raster_to_planet(mask_path, planet)
    raise SystemExit(f"Unsupported mask type: {mask_path}")


def _average_to_tempo(mask_planet: np.ndarray, planet, tempo) -> np.ndarray:
    """Float32 f_p in [0, 1] on tempo grid."""
    src = mask_planet.astype(np.float32)
    dest = np.zeros((tempo.height, tempo.width), dtype=np.float32)
    reproject(
        source=src,
        destination=dest,
        src_transform=planet.transform,
        src_crs=planet.crs,
        dst_transform=tempo.transform,
        dst_crs=tempo.crs,
        resampling=Resampling.average,
    )
    np.clip(dest, 0.0, 1.0, out=dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="f_p: mean Planet plume mask on TEMPO grid.")
    ap.add_argument("--mask", type=Path, default=_DEFAULT_MASK, help="Plume mask (.shp / .geojson / .tif).")
    ap.add_argument(
        "--planet-ref",
        type=Path,
        help="Planet GeoTIFF defining high-res grid (required unless set in data/case.json).",
    )
    ap.add_argument("--tempo-ref", type=Path, default=_DEFAULT_TEMPO, help="TEMPO reference GeoTIFF (output grid).")
    ap.add_argument("-o", "--output", type=Path, default=_DEFAULT_OUT, help="Output f_p GeoTIFF (float32).")
    ap.add_argument(
        "--tempo-screen-mask",
        type=Path,
        default=None,
        help=f"uint8 QA/cloud/VCD screen (1=keep). Default: {_DEFAULT_TEMPO_SCREEN} if present.",
    )
    ap.add_argument(
        "--no-tempo-screen",
        action="store_true",
        help="Do not apply TEMPO QA/cloud screen mask.",
    )
    args = ap.parse_args()

    case_planet = _REPO_ROOT / "data" / "case.json"
    planet_path = args.planet_ref
    if planet_path is None:
        if case_planet.is_file():
            import json

            with open(case_planet, encoding="utf-8") as f:
                case = json.load(f)
            rel = case.get("planet")
            if rel:
                p_data = _REPO_ROOT / "data" / rel
                p_repo = _REPO_ROOT / rel
                planet_path = p_data if p_data.is_file() else p_repo
        if planet_path is None:
            print("ERROR: pass --planet-ref or set planet in data/case.json", file=sys.stderr)
            return 1

    if not args.mask.is_file():
        print(f"ERROR: mask not found: {args.mask}", file=sys.stderr)
        return 1
    if not planet_path.is_file():
        print(f"ERROR: planet reference not found: {planet_path}", file=sys.stderr)
        return 1
    if not args.tempo_ref.is_file():
        print(f"ERROR: tempo reference not found: {args.tempo_ref}", file=sys.stderr)
        return 1

    out_path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(planet_path) as planet, rasterio.open(args.tempo_ref) as tempo:
        if tempo.crs is None:
            print("ERROR: tempo reference has no CRS.", file=sys.stderr)
            return 1
        mask_p = _mask_on_planet_grid(args.mask, planet)
        fp = _average_to_tempo(mask_p, planet, tempo)

        screen_path: Path | None = None
        if not args.no_tempo_screen:
            cand = args.tempo_screen_mask or _DEFAULT_TEMPO_SCREEN
            if cand.is_file():
                screen_path = cand

        nodata_out: float | None = None
        if screen_path is not None:
            with rasterio.open(screen_path) as sm:
                if sm.width != tempo.width or sm.height != tempo.height:
                    print(
                        f"ERROR: tempo screen mask grid {sm.width}x{sm.height} != tempo ref {tempo.width}x{tempo.height}",
                        file=sys.stderr,
                    )
                    return 1
                if sm.crs != tempo.crs:
                    print("ERROR: tempo screen mask CRS mismatch vs tempo reference.", file=sys.stderr)
                    return 1
                scr = sm.read(1)
            m = scr > 0
            fp = np.where(m, fp, _FP_SCREEN_NODATA).astype(np.float32)
            nodata_out = _FP_SCREEN_NODATA
            print(f"Applied TEMPO QA/cloud screen: {screen_path.name} (failed pixels -> nodata {_FP_SCREEN_NODATA})")

        profile = tempo.profile.copy()
        profile.update(
            driver="GTiff",
            count=1,
            dtype="float32",
            nodata=nodata_out,
            compress="deflate",
        )
        tw, th = tempo.width, tempo.height
        tcrs = tempo.crs
        pw, ph = planet.width, planet.height
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(fp, 1)

    n_valid = int(np.sum(np.isfinite(fp) & (fp > 0) & (fp != _FP_SCREEN_NODATA)))
    print(f"Wrote {out_path}")
    print(f"  TEMPO grid: {tw}x{th}  CRS={tcrs}")
    print(f"  Planet grid: {pw}x{ph}  (mask aggregated with average resampling)")
    print(f"  TEMPO pixels with f_p > 0: {n_valid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
