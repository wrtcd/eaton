@echo off
cd /d "%~dp0..\..\"
py -3 scripts\tempo\validate_tempo_stack.py %*
