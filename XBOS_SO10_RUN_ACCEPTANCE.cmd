@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail
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
python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc6_neutral_platform_proof.py tests\contracts\test_xa_frontend_experience_architecture.py tests\contracts\test_so0_shared_operations_constitution.py tests\contracts\test_so1_atomic_catalog_pricing.py tests\contracts\test_so2_operational_party_relationships.py tests\contracts\test_so3_inventory_stock_movement.py tests\contracts\test_so4_procurement_supplier_operations.py tests\contracts\test_so5_resources_operational_assignment.py tests\contracts\test_so6_workflows_tasks_operational_approvals.py tests\contracts\test_so7_documents_files_evidence_search.py tests\contracts\test_so8_communications_delivery_offline.py tests\contracts\test_so9_reporting_read_models_automation.py tests\contracts\test_so10_scheduling_reservations_service_execution.py || goto :fail
python scripts\verify_so10_scheduling_reservations_service_execution.py --acceptance || goto :fail
python -m pytest -q || goto :fail
python -m compileall -q core shared_operations scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('SO10_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail
echo SO10_SOURCE_CHECKPOINT=1ed3c4e
echo SO10_PREVIOUS_HEAD=so9_reporting_read_models_automation_034
echo SO10_ACCEPTED_HEAD=so10_scheduling_reservations_service_execution_035
echo SO10_TIME_AUTHORITY=PC4_REUSED
echo SO10_RESOURCE_AUTHORITY=SO5_REUSED
echo SO10_PARTY_AUTHORITY=PC2_SO2_REUSED
echo SO10_SCHEDULING=PASS
echo SO10_RESERVATIONS=PASS
echo SO10_CAPACITY_CONFLICT=PASS
echo SO10_SERVICE_EXECUTION=PASS
echo SO10_IDEMPOTENCY=PASS
echo SO10_TENANT_ISOLATION=PASS
echo SO10_NEUTRALITY=PASS
echo SO10_XA_CONTRACT=PASS
echo SO10_FINANCIAL_EFFECTS=UNCHANGED
echo SO10_SINGLE_GATE=PASS
exit /b 0
:fail
echo SO10_SINGLE_GATE=FAIL
exit /b 1
