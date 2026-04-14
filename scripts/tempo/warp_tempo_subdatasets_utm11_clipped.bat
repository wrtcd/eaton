@echo off
setlocal
REM If you run this file from cmd.exe, the path MUST be quoted when it contains spaces, e.g.:
REM   "C:\Users\...\WORK April 2026\eaton\scripts\tempo\warp_tempo_subdatasets_utm11_clipped.bat"
REM Or run step-by-step\03 tempo\run_warp_tempo.bat from the repo (no long path to type).
REM TEMPO NO2 L2: warp selected subdatasets to match tempo_no2_utm11_clipped.tif grid (EPSG:32611, 101x69).
REM GeoTIFF outputs go to step-by-step\03 tempo (edit OUTDIR below to change).
REM QA/flags: -r near. Continuous: -r bilinear + nodata.
REM Edit NC= if your granule filename differs.
REM
REM 3D fields (131 x 2048 x 72): scattering_weights, gas_profile, temperature_profile
REM are NOT warped here — gdalwarp -geoloc expects 2D rasters; use
REM regrid_tempo_3d_to_reference.py for all three (72-band GeoTIFFs each).

set "TE=-te 232153.352299999998650 3634690.804000000003725 557208.806000000000331 3856746.122800000011921"
set "TS=-ts 101 69"
set "SRS=-t_srs EPSG:32611"
set "GEO=-geoloc"
set "ND=-srcnodata -1e+30 -dstnodata -1e+30"

for %%I in ("%~dp0..\..") do set "REPO=%%~fI"
set "NC=%REPO%\data\tempo\TEMPO_NO2_L2_V03_20250109T184504Z_S008G09.nc"
set "OUTDIR=%REPO%\step-by-step\03 tempo"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

echo --- QA / integer flags (near) ---
call :near  "NETCDF:%NC%:/product/main_data_quality_flag"              "%OUTDIR%\tempo_qa_main_data_quality_flag_utm11_clipped.tif"
call :near  "NETCDF:%NC%:/support_data/ground_pixel_quality_flag"      "%OUTDIR%\tempo_sup_ground_pixel_quality_flag_utm11_clipped.tif"
call :near  "NETCDF:%NC%:/support_data/amf_diagnostic_flag"             "%OUTDIR%\tempo_sup_amf_diagnostic_flag_utm11_clipped.tif"

echo --- Continuous (bilinear) ---
call :flt   "NETCDF:%NC%:/support_data/fitted_slant_column"               "%OUTDIR%\tempo_sup_fitted_slant_column_utm11_clipped.tif"
call :flt   "NETCDF:%NC%:/support_data/fitted_slant_column_uncertainty"   "%OUTDIR%\tempo_sup_fitted_slant_column_uncertainty_utm11_clipped.tif"
call :flt   "NETCDF:%NC%:/product/vertical_column_troposphere"            "%OUTDIR%\tempo_vcd_troposphere_utm11_clipped.tif"
call :flt   "NETCDF:%NC%:/product/vertical_column_troposphere_uncertainty" "%OUTDIR%\tempo_vcd_troposphere_uncertainty_utm11_clipped.tif"
call :flt   "NETCDF:%NC%:/support_data/eff_cloud_fraction"              "%OUTDIR%\tempo_sup_eff_cloud_fraction_utm11_clipped.tif"
call :flt   "NETCDF:%NC%:/support_data/amf_troposphere"                 "%OUTDIR%\tempo_sup_amf_troposphere_utm11_clipped.tif"
call :flt   "NETCDF:%NC%:/support_data/amf_total"                       "%OUTDIR%\tempo_sup_amf_total_utm11_clipped.tif"

REM Do NOT use gdalwarp for 72-layer variables — see REM header above.
REM call :flt   "NETCDF:%NC%:/support_data/scattering_weights" ...
REM call :flt   "NETCDF:%NC%:/support_data/gas_profile" ...

REM temperature_profile: use regrid_tempo_3d_to_reference.py (same as scattering_weights / gas_profile).
REM call :flt   "NETCDF:%NC%:/product/vertical_column_stratosphere"   tempo_vcd_stratosphere_utm11_clipped.tif

echo Done.
exit /b 0

:flt
gdalwarp -of GTiff -overwrite %GEO% %SRS% %TE% %TS% -r bilinear %ND% "%~1" "%~2"
if errorlevel 1 exit /b 1
exit /b 0

:near
gdalwarp -of GTiff -overwrite %GEO% %SRS% %TE% %TS% -r near "%~1" "%~2"
if errorlevel 1 exit /b 1
exit /b 0
