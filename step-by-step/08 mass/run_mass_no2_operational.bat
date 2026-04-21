@echo off
cd /d "%~dp0..\.."
if exist "smoke\Scripts\activate.bat" call "smoke\Scripts\activate.bat"
py -3 scripts\tempo\mass_no2_from_plume.py --operational-vcd %*
