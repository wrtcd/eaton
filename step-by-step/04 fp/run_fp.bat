@echo off
REM f_p: aggregate Planet plume mask to TEMPO grid (see step-by-step/README.md)
cd /d "%~dp0..\.."
py -3 scripts\fp_planet_mask_to_tempo.py %*
