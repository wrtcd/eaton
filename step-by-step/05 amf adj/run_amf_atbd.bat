@echo off
REM ATBD tropospheric AMF + layer W*S*c stacks on UTM11 reference grid (see scripts/tempo/amf_atbd_from_tempo.py)
cd /d "%~dp0..\.."
if exist "smoke\Scripts\activate.bat" call "smoke\Scripts\activate.bat"
py -3 scripts\tempo\amf_atbd_from_tempo.py --write-bands --compare-product %*
