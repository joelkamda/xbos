@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [R2] Frozen predecessor integrity
python scripts/verify_pc3_semantic_authority.py || goto :fail
python scripts/verify_pc6_neutral_platform.py || goto :fail
python scripts/verify_so_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pk_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pa6_platform_administration_aggregate_freeze.py || goto :fail
python scripts/verify_semantic_classification_hardening.py || goto :fail
python scripts/verify_r0_restaurant_domain_extraction.py || goto :fail
python scripts/verify_r1_restaurant_service_operation.py || goto :fail

echo [R2] Restaurant menu and fulfillment contracts
python scripts/verify_r2_restaurant_menu_fulfillment.py || goto :fail
python -m pytest -q tests/contracts/test_r2_restaurant_menu_fulfillment.py tests/contracts/test_r1_restaurant_service_operation.py tests/contracts/test_r0_restaurant_domain_extraction.py tests/contracts/test_semantic_classification_hardening.py || goto :fail

echo [R2] PostgreSQL authoritative acceptance
python scripts/verify_r2_restaurant_menu_fulfillment.py --acceptance || goto :fail

echo [R2] Full regression
python -m pytest -q || goto :fail

echo [R2] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R2_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo R2_SOURCE_CHECKPOINT=053fb8a
echo R2_PREVIOUS_HEAD=r1_restaurant_service_operation_042
echo R2_ACCEPTED_HEAD=r2_restaurant_menu_fulfillment_043
echo R2_MENU_AS_SO1_PROJECTION=PASS
echo R2_SECTIONS_MODIFIERS=PASS
echo R2_MENU_ENTRY_PLACEMENT=PASS
echo R2_VERSIONED_MODIFIER_SELECTIONS=PASS
echo R2_STATION_ROUTING=PASS
echo R2_SC41_SEMANTIC_ROUTING=PASS
echo R2_MULTI_STATION_FANOUT=PASS
echo R2_RELEASE_IDEMPOTENCY=PASS
echo R2_HOLD_FIRE_COURSE=PASS
echo R2_PARTIAL_READINESS=PASS
echo R2_RECIPE_DEPENDENCIES=PASS
echo R2_YIELD_WASTE_EVIDENCE=PASS
echo R2_INVENTORY_WRITER_DUPLICATION=NONE
echo R2_SO3_HANDOFF=PASS
echo R2_DELIVERY_JOB_WRITER_DUPLICATION=NONE
echo R2_SO8_HANDOFF=PASS
echo R2_NO_NEW_FINANCIAL_AUTHORITY=PASS
echo R2_WND_EXACTLY_ONCE_STOCK_INVARIANT=PRESERVED
echo R2_WND_SPECIMEN_NOT_STANDARD=PASS
echo R2_R3_READINESS=PASS
echo R2_SINGLE_GATE=PASS
exit /b 0

:fail
echo R2_SINGLE_GATE=FAIL
exit /b 1
