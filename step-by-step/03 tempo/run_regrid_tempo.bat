@echo off
cd /d "%~dp0..\..\"
py -3 scripts\tempo\regrid_tempo_3d_to_reference.py %*
