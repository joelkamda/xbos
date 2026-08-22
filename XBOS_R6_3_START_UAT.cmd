@echo off
setlocal
cd /d "%~dp0"

python scripts\start_r6_3_uat_runtime.py
if errorlevel 1 (
  echo R6_3_UAT_RUNTIME=FAIL
  exit /b 1
)

echo.
echo Complete XBOS_R6_3_UAT_CHECKLIST.txt at:
echo   http://127.0.0.1:5174
echo.
echo Then run:
echo   XBOS_R6_3_RECORD_UAT_PASS.cmd
exit /b 0
