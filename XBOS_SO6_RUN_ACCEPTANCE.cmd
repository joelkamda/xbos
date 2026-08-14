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
python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc6_neutral_platform_proof.py tests\contracts\test_xa_frontend_experience_architecture.py tests\contracts\test_so0_shared_operations_constitution.py tests\contracts\test_so1_atomic_catalog_pricing.py tests\contracts\test_so2_operational_party_relationships.py tests\contracts\test_so3_inventory_stock_movement.py tests\contracts\test_so4_procurement_supplier_operations.py tests\contracts\test_so5_resources_operational_assignment.py tests\contracts\test_so6_workflows_tasks_operational_approvals.py || goto :fail
python scripts\verify_so6_workflows_tasks_operational_approvals.py --acceptance || goto :fail
python -m pytest -q || goto :fail
python -m compileall -q core shared_operations scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('SO6_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail
echo SO6_SOURCE_CHECKPOINT=a6292ca
echo SO6_PREVIOUS_HEAD=so5_resources_operational_assignment_030
echo SO6_ACCEPTED_HEAD=so6_workflows_tasks_operational_approvals_031
echo SO6_SECURITY_AUTHORITY=PC5_REUSED
echo SO6_RESOURCE_AUTHORITY=SO5_REUSED
echo SO6_STRUCTURE_AUTHORITY=PC1_REUSED
echo SO6_WORKFLOW=PASS
echo SO6_TASKS=PASS
echo SO6_OPERATIONAL_APPROVAL=PASS
echo SO6_HISTORY=PASS
echo SO6_IDEMPOTENCY=PASS
echo SO6_TENANT_ISOLATION=PASS
echo SO6_NEUTRALITY=PASS
echo SO6_XA_CONTRACT=PASS
echo SO6_FINANCIAL_EFFECTS=UNCHANGED
echo SO6_SINGLE_GATE=PASS
exit /b 0
:fail
echo SO6_SINGLE_GATE=FAIL
exit /b 1
