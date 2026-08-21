@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [R6.2] Frozen predecessor integrity
for /f "delims=" %%H in ('git rev-list -n 1 restaurant-r6-1-wnd-reference-clone-adoption-20260821') do set "R61_TAG_HEAD=%%H"
if /I not "%R61_TAG_HEAD%"=="0f4c72ff297b580c9a2572fe6a0068d814b22267" goto :fail
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
python -m pytest -q tests/contracts/test_m75_finance_migration_support_acceptance_and_freeze.py tests/contracts/test_r6_1_wnd_rehearsal_adoption.py || goto :fail

echo [R6.2] Production-cutover rehearsal contracts
python scripts/verify_r6_2_wnd_production_cutover_rehearsal.py || goto :fail
python -m pytest -q tests/contracts/test_r6_2_wnd_production_cutover_rehearsal.py tests/contracts/test_r6_1_wnd_rehearsal_adoption.py tests/contracts/test_m74_wnd_dual_read_cutover_readiness_and_writer_retirement_support.py tests/contracts/test_m73_wnd_shadow_execution_rehearsal_and_control_totals.py tests/contracts/test_m72_wnd_inventory_cogs_and_document_linkage.py tests/contracts/test_m71_wnd_source_to_canonical_financial_mapping.py tests/contracts/test_m70_legacy_financial_authority_inventory_and_adapter_boundary.py || goto :fail

echo [R6.2] Full regression before disposable database work
python -m pytest -q || goto :fail

echo [R6.2] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts restaurant scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R6_2_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo [R6.2] Snapshot-locked production-cutover rehearsal
python scripts/verify_r6_2_wnd_production_cutover_rehearsal.py --acceptance || goto :fail

echo R6_2_PRODUCTION_WRITES=NONE
echo R6_2_PRODUCTION_WRITER_ROUTING=UNCHANGED
echo R6_2_SOURCE_CLONE=xbos_r6_2_source
echo R6_2_CANDIDATE_CLONE=xbos_r6_2_candidate
echo R6_2_SOURCE_HEAD=5c706797029a
echo R6_2_CANDIDATE_HEAD=r2_restaurant_menu_fulfillment_043
echo R6_2_M71_PRODUCTION_SHAPED_MAPPING=PASS
echo R6_2_M72_MISSING_COST_BASIS=WITHHELD_NOT_ZERO
echo R6_2_M73_SHADOW_REHEARSAL=PASS
echo R6_2_M74_DUAL_READ_VARIANCES=VISIBLE
echo R6_2_CONTROL_EQUATION=SOURCE_EQUALS_MAPPED_PLUS_WITHHELD
echo R6_2_HISTORICAL_AR_SATISFACTION=NOT_FABRICATED
echo R6_2_HISTORICAL_DOCUMENTS=NOT_REGENERATED
echo R6_2_HISTORICAL_INVENTORY_COST=NOT_INVENTED
echo R6_2_WRITER_RETIREMENT=PREPARED_NOT_EXECUTED
echo R6_2_RECOVERY_RESTORE_REPLAY=PASS
echo R6_2_LIVE_CUTOVER_AUTHORIZED=NO
echo R6_2_R6_3_READINESS=PASS
echo R6_2_SINGLE_GATE=PASS
exit /b 0

:fail
echo R6_2_SINGLE_GATE=FAIL
exit /b 1
