@echo off
REM From repo root: QA/cloud screen -> f_p (screened) -> ATBD AMF (screened).
REM Requires: smoke venv, warped TEMPO GeoTIFFs in step-by-step\03 tempo
setlocal
for %%I in ("%~dp0..\..") do set "REPO=%%~fI"
cd /d "%REPO%"
if exist "smoke\Scripts\activate.bat" call "smoke\Scripts\activate.bat"

set "D03=%REPO%\step-by-step\03 tempo"

echo === 1. TEMPO QA/cloud/VCD screen mask ===
py -3 scripts\tempo\screen_tempo_pixels.py --dir "%D03%"
if errorlevel 1 exit /b 1

echo === 2. f_p on TEMPO grid (masked with screen when present) ===
py -3 scripts\fp_planet_mask_to_tempo.py
if errorlevel 1 exit /b 1

echo === 3. ATBD AMF + optional 72-band stacks (screened) ===
py -3 scripts\tempo\amf_atbd_from_tempo.py --write-bands --compare-product
if errorlevel 1 exit /b 1

echo Done.
exit /b 0
