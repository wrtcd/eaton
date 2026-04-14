@echo off
REM Put GDAL/OGR and QGIS Python GDAL utilities on PATH for this shell.
REM Edit QGIS_ROOT if your QGIS install path differs.
set "QGIS_ROOT=C:\Program Files\QGIS 3.34.9"
if not exist "%QGIS_ROOT%\bin\gdalwarp.exe" (
  echo ERROR: gdalwarp not found at "%QGIS_ROOT%\bin". Set QGIS_ROOT in scripts\env_smoke_gdal.bat
  exit /b 1
)
set "PATH=%QGIS_ROOT%\bin;%QGIS_ROOT%\apps\Python312;%QGIS_ROOT%\apps\Python312\Scripts;%PATH%"
set "GDAL_DATA=%QGIS_ROOT%\apps\gdal\share\gdal"
set "PROJ_LIB=%QGIS_ROOT%\share\proj"
