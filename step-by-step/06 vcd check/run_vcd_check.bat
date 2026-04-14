@echo off
REM VCD_check = SCD / AMF_trop (prior ATBD AMF), output in this folder
cd /d "%~dp0..\.."
if exist "smoke\Scripts\activate.bat" call "smoke\Scripts\activate.bat"
py -3 scripts\tempo\vcd_check_scd_amf.py %*
