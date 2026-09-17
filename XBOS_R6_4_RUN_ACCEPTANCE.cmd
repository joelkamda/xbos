@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
set PYTHONDONTWRITEBYTECODE=1

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.5" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail
python -c "from zoneinfo import ZoneInfo; import alembic; assert str(ZoneInfo('Africa/Douala'))=='Africa/Douala'; assert alembic.__version__=='1.17.2'; print('R6_4_CONTROL_RUNTIME=PASS')" || goto :fail
python -c "import bcrypt; from passlib.hash import bcrypt as passlib_bcrypt; assert passlib_bcrypt.get_backend()=='bcrypt'; print('R6_4_BCRYPT_BACKEND=PASS')" || goto :fail

echo [R6.4] Static package authority
python scripts\verify_r6_4_wnd_production_cutover_package.py || goto :fail
python -m pytest -q tests/contracts/test_r6_4_wnd_production_cutover_package.py tests/contracts/test_r6_3_wnd_application_compatibility.py tests/contracts/test_r6_2_wnd_production_cutover_rehearsal.py || goto :fail

echo [R6.4] Frozen predecessor gates
python scripts\verify_pc3_semantic_authority.py || goto :fail
python scripts\verify_pc6_neutral_platform.py || goto :fail
python scripts\verify_so_aggregate_conformance_freeze.py || goto :fail
python scripts\verify_pk_aggregate_conformance_freeze.py || goto :fail
python scripts\verify_pa6_platform_administration_aggregate_freeze.py || goto :fail
python scripts\verify_semantic_classification_hardening.py || goto :fail
python scripts\verify_r0_restaurant_domain_extraction.py || goto :fail
python scripts\verify_r1_restaurant_service_operation.py || goto :fail
python scripts\verify_r2_restaurant_menu_fulfillment.py || goto :fail
python scripts\verify_r3_restaurant_financial_semantics.py || goto :fail
python scripts\verify_r4_restaurant_pack_registration.py || goto :fail
python scripts\verify_r5_wnd_tenant_template_proof.py || goto :fail

echo [R6.4] Isolated full regression
python scripts\run_r6_4_isolated_full_regression.py || goto :fail

echo [R6.4] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R6_4_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo [R6.4] Fresh-production cutover rehearsal
python scripts\verify_r6_4_wnd_production_cutover_package.py --acceptance || goto :fail

echo R6_4_PRODUCTION_WRITES=NONE
echo R6_4_PRODUCTION_WRITER_ROUTING=UNCHANGED
echo R6_4_LEGACY_WRITER_RETIREMENT=DEFERRED_TO_POST_HYPERCARE
echo R6_4_LIVE_CUTOVER_AUTHORIZED=NO
echo R6_4_R6_5_READINESS=PASS
echo R6_4_SINGLE_GATE=PASS
exit /b 0

:fail
echo R6_4_SINGLE_GATE=FAIL
exit /b 1
