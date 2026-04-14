@echo off
REM Two-track Planet mosaic: gdal_merge.py produced an all-zero GeoTIFF here (8-band Float32).
REM Use gdalbuildvrt + gdal_translate instead (reliable for large multiband rasters).
REM
REM Overlap: LAST file listed wins in gdalbuildvrt. Order is M2 then M1 so mosaic1 wins
REM in overlap (same as old gdal_merge with M1 first M2 second).
REM
REM The union bounding box can have a "hole" (zeros) between swaths — that is normal.
REM QGIS may show NaN min/max if the extent includes nodata holes; zoom to where imagery exists.
cd /d "%~dp0..\.."
call scripts\env_smoke_gdal.bat
if errorlevel 1 exit /b 1

set "M1=%~dp0mosaic1.tif"
set "M2=%~dp0mosaic2.tif"
set "VRT=data\planet\mosaic_eaton_2tracks.vrt"
set "OUT=data\planet\mosaic_eaton_2tracks.tif"

if not exist "%M1%" ( echo ERROR: missing %M1% & exit /b 1 )
if not exist "%M2%" ( echo ERROR: missing %M2% & exit /b 1 )

echo Building VRT (fast): %VRT%
REM M2 first, M1 last => mosaic1 wins overlap
gdalbuildvrt -overwrite -resolution highest "%VRT%" "%M2%" "%M1%"
if errorlevel 1 exit /b 1

echo Materializing GeoTIFF (slow, large): %OUT%
gdal_translate -of GTiff -co COMPRESS=DEFLATE -co BIGTIFF=IF_SAFER -co TILED=YES "%VRT%" "%OUT%"
if errorlevel 1 exit /b 1
echo OK: wrote %VRT% and %OUT%
exit /b 0
