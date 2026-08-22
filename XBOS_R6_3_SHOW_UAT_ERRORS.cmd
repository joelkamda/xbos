@echo off
setlocal
cd /d "%~dp0"
python scripts\show_r6_3_uat_errors.py
exit /b %ERRORLEVEL%
