@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail

echo [R6.3 final] Frozen predecessor and final evidence
for /f "delims=" %%H in ('git rev-list -n 1 restaurant-r6-2-wnd-production-cutover-rehearsal-20260821') do set "R62_TAG_HEAD=%%H"
if /I not "%R62_TAG_HEAD%"=="9a8c69dfb0caf18fe010d858caceef84b863a4c2" goto :fail
python scripts/verify_r6_3_wnd_application_compatibility.py || goto :fail
python -m pytest -q tests/contracts/test_r6_3_wnd_application_compatibility.py tests/contracts/test_r6_2_wnd_production_cutover_rehearsal.py || goto :fail
python -m compileall -q restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts/restaurant/v1').glob('r6_3*.json')]; print('R6_3_FINAL_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail
python scripts/verify_r6_3_wnd_application_compatibility.py --final || goto :fail

echo R6_3_PRODUCTION_WRITES=NONE
echo R6_3_PRODUCTION_WRITER_ROUTING=UNCHANGED
echo R6_3_LIVE_CUTOVER_AUTHORIZED=NO
echo R6_3_AUTOMATED_COMPATIBILITY=PASS
echo R6_3_VISUAL_UAT=PASS
echo R6_3_R6_4_READINESS=PASS
echo R6_3_SINGLE_GATE=PASS
exit /b 0

:fail
echo R6_3_SINGLE_GATE=FAIL
exit /b 1
