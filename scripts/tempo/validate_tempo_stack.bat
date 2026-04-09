@echo off
cd /d "%~dp0"
py -3 validate_tempo_stack.py %*
