@echo off
setlocal
cd /d "%~dp0"
python scripts\capture_r6_4_wnd_planning_baseline.py
if errorlevel 1 (
  echo R6_4_PLANNING_BASELINE=FAIL
  exit /b 1
)
exit /b 0
