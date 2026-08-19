@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [R4] Frozen predecessor integrity
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

echo [R4] Restaurant pack-registration contracts
python scripts/verify_r4_restaurant_pack_registration.py || goto :fail
python -m pytest -q tests/contracts/test_r4_restaurant_pack_registration.py tests/contracts/test_r3_restaurant_financial_semantics.py tests/contracts/test_r2_restaurant_menu_fulfillment.py tests/contracts/test_r1_restaurant_service_operation.py tests/contracts/test_r0_restaurant_domain_extraction.py || goto :fail

echo [R4] PostgreSQL disposable registration/certification proof
python scripts/verify_r4_restaurant_pack_registration.py --acceptance || goto :fail

echo [R4] Full regression before development adoption
python -m pytest -q || goto :fail

echo [R4] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R4_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo [R4] Development global pack registration/certification adoption
python scripts/verify_r4_restaurant_pack_registration.py --adopt-development || goto :fail

echo R4_SOURCE_CHECKPOINT=64fa78e
echo R4_PREVIOUS_HEAD=r2_restaurant_menu_fulfillment_043
echo R4_ACCEPTED_HEAD=r2_restaurant_menu_fulfillment_043
echo R4_MIGRATION=NONE
echo R4_PACK_CODE=industry.restaurant
echo R4_PACK_VERSION=1.0.0
echo R4_PK_REGISTRATION=PASS
echo R4_PK_CERTIFICATION=PASS
echo R4_SEMANTIC_CONTRIBUTION=PASS
echo R4_CONFIGURATION_DECLARATIONS=PASS
echo R4_PERMISSION_REFERENCES=PASS
echo R4_XA_COMPOSITION_METADATA=PASS
echo R4_NO_NEW_FINANCIAL_AUTHORITY=PASS
echo R4_NO_SHARED_OPERATION_WRITER_DUPLICATION=PASS
echo R4_TENANT_INSTALLATION=NONE
echo R4_TEMPLATE_APPLICATION=NONE
echo R4_WND_CUTOVER=NONE
echo R4_WND_SPECIMEN_NOT_STANDARD=PASS
echo R4_DATABASE_SCHEMA_UNCHANGED=PASS
echo R4_R5_READINESS=PASS
echo R4_SINGLE_GATE=PASS
exit /b 0

:fail
echo R4_SINGLE_GATE=FAIL
exit /b 1
