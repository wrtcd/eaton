@echo off
REM From repo root: GDAL on PATH + activate smoke venv (Python packages stay in smoke).
cd /d "%~dp0"
call scripts\env_smoke_gdal.bat
if errorlevel 1 exit /b 1
if exist "%~dp0smoke\Scripts\activate.bat" (
  call "%~dp0smoke\Scripts\activate.bat"
) else (
  echo WARNING: smoke venv not found at smoke\Scripts\activate.bat — GDAL PATH is set anyway.
)
cmd /k
