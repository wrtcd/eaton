@echo off
setlocal
cd /d "%~dp0"
py -3 screen_tempo_pixels.py %*
exit /b %ERRORLEVEL%
