@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [R5] Frozen predecessor integrity
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

echo [R5] WND tenant/template composition contracts
python scripts/verify_r5_wnd_tenant_template_proof.py || goto :fail
python -m pytest -q tests/contracts/test_r5_wnd_tenant_template_proof.py tests/contracts/test_r4_restaurant_pack_registration.py tests/contracts/test_r3_restaurant_financial_semantics.py tests/contracts/test_r2_restaurant_menu_fulfillment.py tests/contracts/test_r1_restaurant_service_operation.py tests/contracts/test_r0_restaurant_domain_extraction.py || goto :fail

echo [R5] PostgreSQL disposable composition proof
python scripts/verify_r5_wnd_tenant_template_proof.py --acceptance || goto :fail

echo [R5] Full regression before development adoption
python -m pytest -q || goto :fail

echo [R5] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R5_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo [R5] Development proof-tenant composition adoption
python scripts/verify_r5_wnd_tenant_template_proof.py --adopt-development || goto :fail

echo R5_SOURCE_CHECKPOINT=7b52093
echo R5_PREVIOUS_HEAD=r2_restaurant_menu_fulfillment_043
echo R5_ACCEPTED_HEAD=r2_restaurant_menu_fulfillment_043
echo R5_MIGRATION=NONE
echo R5_PACK_CODE=industry.restaurant
echo R5_PACK_VERSION=1.0.0
echo R5_COUNTER_TEMPLATE=restaurant.counter_service@1.0.0
echo R5_FULL_SERVICE_TEMPLATE=restaurant.full_service@1.0.0
echo R5_WND_TEMPLATE_PIN=restaurant.counter_service@1.0.0
echo R5_WND_LOGPOM_STRUCTURE=PASS
echo R5_PK_STAGE_INSTALL_ACTIVATE=PASS
echo R5_PK_TEMPLATE_REGISTRATION_APPLICATION=PASS
echo R5_PC4_08_TO_08_CALENDAR=PASS
echo R5_PC4_18H_PAYMENT_ATTRIBUTION=PASS
echo R5_COMMISSION_ORIGINAL_ORDER_CREATOR=PRESERVED
echo R5_WND_PAYMENT_METHOD_CONFIGURATION=PASS
echo R5_WND_BRANDING_TERMINOLOGY=PASS
echo R5_MENU_CATALOG_STAFF_MAPPING_PLAN=PASS
echo R5_TAXONOMY_OVERLAY_PLAN=PASS
echo R5_FINANCE_DOCUMENT_INVENTORY_MAPPING_PLAN=PASS
echo R5_NO_NEW_FINANCIAL_AUTHORITY=PASS
echo R5_NO_SHARED_OPERATION_WRITER_DUPLICATION=PASS
echo R5_DATABASE_SCHEMA_UNCHANGED=PASS
echo R5_WND_PRODUCTION=UNCHANGED
echo R5_R6_CUTOVER=NONE
echo R5_WND_SPECIMEN_NOT_STANDARD=PASS
echo R5_R6_READINESS=PASS
echo R5_SINGLE_GATE=PASS
exit /b 0

:fail
echo R5_SINGLE_GATE=FAIL
exit /b 1
