@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [R1] Frozen predecessor integrity
python scripts/verify_pc3_semantic_authority.py || goto :fail
python scripts/verify_pc6_neutral_platform.py || goto :fail
python scripts/verify_so_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pk_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pa6_platform_administration_aggregate_freeze.py || goto :fail
python scripts/verify_semantic_classification_hardening.py || goto :fail
python scripts/verify_r0_restaurant_domain_extraction.py || goto :fail

echo [R1] Restaurant service-operation contracts
python scripts/verify_r1_restaurant_service_operation.py || goto :fail
python -m pytest -q tests/contracts/test_r1_restaurant_service_operation.py tests/contracts/test_r0_restaurant_domain_extraction.py tests/contracts/test_semantic_classification_hardening.py || goto :fail

echo [R1] PostgreSQL authoritative acceptance
python scripts/verify_r1_restaurant_service_operation.py --acceptance || goto :fail

echo [R1] Full regression
python -m pytest -q || goto :fail

echo [R1] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R1_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo R1_SOURCE_CHECKPOINT=28290b6
echo R1_PREVIOUS_HEAD=semantic_classification_hardening_041
echo R1_ACCEPTED_HEAD=r1_restaurant_service_operation_042
echo R1_DINING_AREA_TABLE_MODEL=PASS
echo R1_CONFIGURABLE_SERVICE_MODES=PASS
echo R1_ORDER_LIFECYCLE=PASS
echo R1_ORDER_IDEMPOTENCY=PASS
echo R1_ORDER_CONCURRENCY=PASS
echo R1_ORDER_HISTORY=PASS
echo R1_WAITER_ATTRIBUTION=PASS
echo R1_CASHIER_ATTRIBUTION=PASS
echo R1_NO_DUPLICATE_STAFF_AUTHORITY=PASS
echo R1_TABS_CHECKS=PASS
echo R1_SPLIT_BILL_PARTITIONING=PASS
echo R1_ORDER_TO_OBLIGATION_HANDOFF=PASS
echo R1_NO_NEW_FINANCIAL_AUTHORITY=PASS
echo R1_INVENTORY_WRITER_DUPLICATION=NONE
echo R1_WND_EXACTLY_ONCE_STOCK_INVARIANT=PRESERVED
echo R1_RESERVATION_COMPOSITION=PASS
echo R1_REMOTE_ORDER_COMPATIBILITY=PASS
echo R1_WND_SPECIMEN_NOT_STANDARD=PASS
echo R1_CROSS_RESTAURANT_NEUTRALITY=PASS
echo R1_RELEASE_METADATA_REFRESH=PASS
echo R1_R2_READINESS=PASS
echo R1_SINGLE_GATE=PASS
exit /b 0

:fail
echo R1_SINGLE_GATE=FAIL
exit /b 1
