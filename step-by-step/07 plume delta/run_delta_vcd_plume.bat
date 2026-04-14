@echo off
cd /d "%~dp0..\.."
if exist "smoke\Scripts\activate.bat" call "smoke\Scripts\activate.bat"
py -3 scripts\tempo\delta_vcd_plume.py %*
