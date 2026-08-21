@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [R6.1] Frozen predecessor integrity
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
python -m pytest -q tests/contracts/test_m75_finance_migration_support_acceptance_and_freeze.py || goto :fail

echo [R6.1] Frozen production-baseline and rehearsal contracts
python scripts/verify_r6_1_wnd_rehearsal_adoption.py || goto :fail
python -m pytest -q tests/contracts/test_r6_1_wnd_rehearsal_adoption.py tests/contracts/test_r5_wnd_tenant_template_proof.py tests/contracts/test_r4_restaurant_pack_registration.py tests/contracts/test_r3_restaurant_financial_semantics.py tests/contracts/test_r2_restaurant_menu_fulfillment.py tests/contracts/test_r1_restaurant_service_operation.py tests/contracts/test_r0_restaurant_domain_extraction.py || goto :fail

echo [R6.1] Full regression before disposable database work
python -m pytest -q || goto :fail

echo [R6.1] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R6_1_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo [R6.1] Snapshot-locked PostgreSQL clone adoption rehearsal
python scripts/verify_r6_1_wnd_rehearsal_adoption.py --acceptance || goto :fail

echo R6_0_PRODUCTION_BASELINE=PASS
echo R6_0_PRODUCTION_BACKEND=b60a71d
echo R6_0_PRODUCTION_FRONTEND=f47f574
echo R6_0_PRODUCTION_DB_HEAD=5c706797029a
echo R6_0_PRODUCTION_BACKUP_SHA256=22c105224f65dec2bc09ef0335748a1db855ee59945c170b69526ee18f39dc16
echo R6_1_PRODUCTION_WRITES=NONE
echo R6_1_PRODUCTION_WRITER_ROUTING=UNCHANGED
echo R6_1_SOURCE_CLONE=xbos_r6_1_source
echo R6_1_CANDIDATE_CLONE=xbos_r6_1_candidate
echo R6_1_SOURCE_HEAD=5c706797029a
echo R6_1_CANDIDATE_HEAD=r2_restaurant_menu_fulfillment_043
echo R6_1_LEGACY_COUNTS=PRESERVED
echo R6_1_LEGACY_CONTROL_TOTALS=PRESERVED
echo R6_1_HISTORICAL_INVENTORY_MISMATCH=PRESERVED
echo R6_1_PC1_EXISTING_BRANCH_MAPPING=PASS
echo R6_1_EXISTING_TENANT_RESTAURANT_PACK=ACTIVE
echo R6_1_EXISTING_TENANT_TEMPLATE=restaurant.counter_service@1.0.0
echo R6_1_WND_PC4_CONTEXT=PASS
echo R6_1_NEW_WND_TENANT=NONE
echo R6_1_REFERENCE_RELEASE_TAG=wnd-track-a-reference-release-20260821
echo R6_1_FULFILLMENT_REFERENCE=PRESERVED
echo R6_1_CUSTOMER_AR_IDENTITY_REFERENCE=PRESERVED
echo R6_1_HISTORICAL_UNSPECIFIED_FULFILLMENT=NOT_GUESSED
echo R6_1_HISTORICAL_AMBIGUOUS_CUSTOMER_IDENTITY=NOT_GUESSED
echo R6_1_KITCHEN_INITIAL_PRINT_ONCE_INVARIANT=PRESERVED

echo R6_1_KITCHEN_SEMANTIC_DELTA_INVARIANT=PRESERVED_FOR_LATER_CUTOVER
echo R6_1_R6_2_READINESS=PASS
echo R6_1_SINGLE_GATE=PASS
exit /b 0

:fail
echo R6_1_SINGLE_GATE=FAIL
exit /b 1
