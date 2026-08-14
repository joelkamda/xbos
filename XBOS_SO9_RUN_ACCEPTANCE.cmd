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
python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc6_neutral_platform_proof.py tests\contracts\test_xa_frontend_experience_architecture.py tests\contracts\test_so0_shared_operations_constitution.py tests\contracts\test_so1_atomic_catalog_pricing.py tests\contracts\test_so2_operational_party_relationships.py tests\contracts\test_so3_inventory_stock_movement.py tests\contracts\test_so4_procurement_supplier_operations.py tests\contracts\test_so5_resources_operational_assignment.py tests\contracts\test_so6_workflows_tasks_operational_approvals.py tests\contracts\test_so7_documents_files_evidence_search.py tests\contracts\test_so8_communications_delivery_offline.py tests\contracts\test_so9_reporting_read_models_automation.py || goto :fail
python scripts\verify_so9_reporting_read_models_automation.py --acceptance || goto :fail
python -m pytest -q || goto :fail
python -m compileall -q core shared_operations scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('SO9_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail
echo SO9_SOURCE_CHECKPOINT=bdca5e6
echo SO9_PREVIOUS_HEAD=so8_communications_delivery_offline_033
echo SO9_ACCEPTED_HEAD=so9_reporting_read_models_automation_034
echo SO9_SECURITY_AUTHORITY=PC5_REUSED
echo SO9_READ_MODEL_AUTHORITY=PASS
echo SO9_REPORTING=PASS
echo SO9_METRICS=PASS
echo SO9_AUTOMATION=PASS
echo SO9_DELIVERY_AUTHORITY=SO8_REUSED
echo SO9_TENANT_ISOLATION=PASS
echo SO9_NEUTRALITY=PASS
echo SO9_XA_CONTRACT=PASS
echo SO9_FINANCIAL_EFFECTS=UNCHANGED
echo SO9_SINGLE_GATE=PASS
exit /b 0
:fail
echo SO9_SINGLE_GATE=FAIL
exit /b 1
