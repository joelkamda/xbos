@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail
where npm >nul 2>&1 || goto :fail

echo [R6.3] Frozen predecessor integrity
for /f "delims=" %%H in ('git rev-list -n 1 restaurant-r6-2-wnd-production-cutover-rehearsal-20260821') do set "R62_TAG_HEAD=%%H"
if /I not "%R62_TAG_HEAD%"=="9a8c69dfb0caf18fe010d858caceef84b863a4c2" goto :fail
python scripts/verify_pc3_semantic_authority.py || goto :fail
python scripts/verify_pc6_neutral_platform.py || goto :fail
python scripts/verify_so_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pk_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pa6_platform_administration_aggregate_freeze.py || goto :fail
python scripts/verify_semantic_classification_hardening.py || goto :fail
python scripts/verify_r0_restaurant_domain_extraction.py || goto :fail
python scripts/verify_r1_restaurant_service_operation.py || goto :fail
python scripts/verify_r2_restaurant_menu_fulfillment.py || goto :fail
python scripts/verify_r3_restaurant_financial_semantics.py || goto :fail
python scripts/verify_r4_restaurant_pack_registration.py || goto :fail
python scripts/verify_r5_wnd_tenant_template_proof.py || goto :fail
python -m pytest -q tests/contracts/test_r6_2_wnd_production_cutover_rehearsal.py tests/contracts/test_r6_1_wnd_rehearsal_adoption.py || goto :fail

echo [R6.3] Application compatibility contracts
python scripts/verify_r6_3_wnd_application_compatibility.py || goto :fail
python -m pytest -q tests/contracts/test_r6_3_wnd_application_compatibility.py tests/contracts/test_r6_2_wnd_production_cutover_rehearsal.py || goto :fail

echo [R6.3] Full regression before candidate application work
python -m pytest -q || goto :fail

echo [R6.3] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R6_3_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo [R6.3] Exact WND reference application on neutral candidate
python scripts/verify_r6_3_wnd_application_compatibility.py --acceptance || goto :fail

echo R6_3_PRODUCTION_WRITES=NONE
echo R6_3_PRODUCTION_WRITER_ROUTING=UNCHANGED
echo R6_3_LIVE_CUTOVER_AUTHORIZED=NO
echo R6_3_CANDIDATE_DATABASE=xbos_r6_3_candidate
echo R6_3_REFERENCE_BACKEND=b60a71d
echo R6_3_REFERENCE_FRONTEND=f47f574
echo R6_3_AUTOMATED_COMPATIBILITY=PASS
echo R6_3_VISUAL_UAT_REQUIRED=YES
echo R6_3_AUTOMATED_GATE=PASS
exit /b 0

:fail
echo R6_3_AUTOMATED_GATE=FAIL
exit /b 1
