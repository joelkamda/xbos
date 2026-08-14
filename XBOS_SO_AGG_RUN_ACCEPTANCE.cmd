@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [SO-AGG] Frozen predecessor and component verifiers
python scripts\verify_pc0_kernel_boundaries.py || goto :fail
python scripts\verify_pc1_structural_authority.py || goto :fail
python scripts\verify_pc2_party_authority.py || goto :fail
python scripts\verify_pc3_semantic_authority.py || goto :fail
python scripts\verify_pc4_operating_context.py || goto :fail
python scripts\verify_pc5_identity_policy_audit.py || goto :fail
python scripts\verify_pc6_neutral_platform.py || goto :fail
python scripts\verify_xa_frontend_experience_architecture.py || goto :fail
python scripts\verify_so0_shared_operations.py || goto :fail
python scripts\verify_so1_atomic_catalog_pricing.py || goto :fail
python scripts\verify_so2_operational_party_relationships.py || goto :fail
python scripts\verify_so3_inventory_stock_movement.py || goto :fail
python scripts\verify_so4_procurement_supplier_operations.py || goto :fail
python scripts\verify_so5_resources_operational_assignment.py || goto :fail
python scripts\verify_so6_workflows_tasks_operational_approvals.py || goto :fail
python scripts\verify_so7_documents_files_evidence_search.py || goto :fail
python scripts\verify_so8_communications_delivery_offline.py || goto :fail
python scripts\verify_so9_reporting_read_models_automation.py || goto :fail
python scripts\verify_so10_scheduling_reservations_service_execution.py || goto :fail
python scripts\verify_so_aggregate_conformance_freeze.py || goto :fail

echo [SO-AGG] Focused cumulative conformance
python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc6_neutral_platform_proof.py tests\contracts\test_xa_frontend_experience_architecture.py tests\contracts\test_so0_shared_operations_constitution.py tests\contracts\test_so1_atomic_catalog_pricing.py tests\contracts\test_so2_operational_party_relationships.py tests\contracts\test_so3_inventory_stock_movement.py tests\contracts\test_so4_procurement_supplier_operations.py tests\contracts\test_so5_resources_operational_assignment.py tests\contracts\test_so6_workflows_tasks_operational_approvals.py tests\contracts\test_so7_documents_files_evidence_search.py tests\contracts\test_so8_communications_delivery_offline.py tests\contracts\test_so9_reporting_read_models_automation.py tests\contracts\test_so10_scheduling_reservations_service_execution.py tests\contracts\test_so_aggregate_conformance_freeze.py || goto :fail

echo [SO-AGG] PostgreSQL clean replay and aggregate hardening
python scripts\verify_so_aggregate_conformance_freeze.py --acceptance || goto :fail

echo [SO-AGG] Full regression
python -m pytest -q || goto :fail

echo [SO-AGG] Compilation, JSON and whitespace
python -m compileall -q core shared_operations scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('SO_AGG_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo SO_AGG_SOURCE_CHECKPOINT=0f2fa1b
echo SO_AGG_PREVIOUS_HEAD=so10_scheduling_reservations_service_execution_035
echo SO_AGG_ACCEPTED_HEAD=so_aggregate_conformance_hardening_036
echo SO_AGG_AUTHORITY_GRAPH=PASS
echo SO_AGG_PUBLIC_BOUNDARIES=PASS
echo SO_AGG_TENANT_ISOLATION=PASS
echo SO_AGG_SO2_TENANT_IDEMPOTENCY=PASS
echo SO_AGG_NEUTRALITY=PASS
echo SO_AGG_MIGRATION_LINEAGE=PASS
echo SO_AGG_XA_CONFORMANCE=PASS
echo SO_AGG_FINANCE_UNCHANGED=PASS
echo SO_AGG_DEPENDENCIES=UNCHANGED
echo SO_AGG_RELEASE_INTEGRITY=PASS
echo SO_AGG_PK_READINESS=PASS
echo SO_AGG_BUSINESS_CAPABILITY_CHANGE=NONE
echo SO_AGG_SINGLE_GATE=PASS
exit /b 0

:fail
echo SO_AGG_SINGLE_GATE=FAIL
exit /b 1
