@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [R3] Frozen predecessor integrity
python scripts/verify_pc3_semantic_authority.py || goto :fail
python scripts/verify_pc6_neutral_platform.py || goto :fail
python scripts/verify_so_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pk_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pa6_platform_administration_aggregate_freeze.py || goto :fail
python scripts/verify_semantic_classification_hardening.py || goto :fail
python scripts/verify_r0_restaurant_domain_extraction.py || goto :fail
python scripts/verify_r1_restaurant_service_operation.py || goto :fail
python scripts/verify_r2_restaurant_menu_fulfillment.py || goto :fail

echo [R3] Restaurant financial-semantics contracts
python scripts/verify_r3_restaurant_financial_semantics.py || goto :fail
python -m pytest -q tests/contracts/test_r3_restaurant_financial_semantics.py tests/contracts/test_r2_restaurant_menu_fulfillment.py tests/contracts/test_r1_restaurant_service_operation.py tests/contracts/test_r0_restaurant_domain_extraction.py || goto :fail

echo [R3] Development read-only proof
python scripts/verify_r3_restaurant_financial_semantics.py --development || goto :fail

echo [R3] Full regression
python -m pytest -q || goto :fail

echo [R3] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R3_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo R3_SOURCE_CHECKPOINT=c9ab012
echo R3_PREVIOUS_HEAD=r2_restaurant_menu_fulfillment_043
echo R3_ACCEPTED_HEAD=r2_restaurant_menu_fulfillment_043
echo R3_MIGRATION=NONE
echo R3_R1_BASE_CHARGE_COMPOSITION=PASS
echo R3_R2_MODIFIER_FINANCIAL_HANDOFF=PASS
echo R3_DISCOUNT_COMPLIMENTARY_MAPPING=PASS
echo R3_SERVICE_DELIVERY_TAKEAWAY_FEE_MAPPING=PASS
echo R3_OUTPUT_TAX_MAPPING=PASS
echo R3_TIP_MAPPING=PASS
echo R3_COMMISSION_MAPPING=PASS
echo R3_ORDER_TO_OBLIGATION_MAPPING=PASS
echo R3_PAYMENT_WRITER_DUPLICATION=NONE
echo R3_FINANCE_WRITER_DUPLICATION=NONE
echo R3_CANCELLATION_CORRECTION_MAPPING=PASS
echo R3_REFUND_REVERSAL_MAPPING=PASS
echo R3_ORIGINAL_FINANCIAL_TRUTH_IMMUTABLE=PASS
echo R3_RESTAURANT_REPORTS_OVER_FINANCE_SO9=PASS
echo R3_WND_SPECIMEN_NOT_STANDARD=PASS
echo R3_DATABASE_UNCHANGED=PASS
echo R3_R4_READINESS=PASS
echo R3_SINGLE_GATE=PASS
exit /b 0

:fail
echo R3_SINGLE_GATE=FAIL
exit /b 1
