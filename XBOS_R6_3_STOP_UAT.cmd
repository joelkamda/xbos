@echo off
setlocal
cd /d "%~dp0"
python scripts\stop_r6_3_uat_runtime.py
if errorlevel 1 (
  echo R6_3_UAT_RUNTIME_STOPPED=FAIL
  exit /b 1
)
exit /b 0
