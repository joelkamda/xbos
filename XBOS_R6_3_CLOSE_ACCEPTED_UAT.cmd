@echo off
setlocal EnableExtensions
cd /d "%~dp0"

python scripts\close_r6_3_after_accepted_uat.py
set "RC=%ERRORLEVEL%"

if exist "%USERPROFILE%\Downloads\XBOS_R6_3_CLOSE_RESULT.txt" (
  start "" notepad.exe "%USERPROFILE%\Downloads\XBOS_R6_3_CLOSE_RESULT.txt"
)

exit /b %RC%
