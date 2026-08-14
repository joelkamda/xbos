@echo off
setlocal
cd /d "%~dp0"
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
python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc6_neutral_platform_proof.py tests\contracts\test_xa_frontend_experience_architecture.py tests\contracts\test_so0_shared_operations_constitution.py tests\contracts\test_so1_atomic_catalog_pricing.py tests\contracts\test_so2_operational_party_relationships.py tests\contracts\test_so3_inventory_stock_movement.py tests\contracts\test_so4_procurement_supplier_operations.py tests\contracts\test_so5_resources_operational_assignment.py || goto :fail
python scripts\verify_so5_resources_operational_assignment.py --acceptance || goto :fail
python -m pytest -q || goto :fail
python -m compileall -q core shared_operations scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('SO5_JSON=PASS')" || goto :fail
git diff --check || goto :fail
echo SO5_SOURCE_CHECKPOINT=087a6d9
echo SO5_PREVIOUS_HEAD=so4_procurement_supplier_operations_029
echo SO5_ACCEPTED_HEAD=so5_resources_operational_assignment_030
echo SO5_PARTY_AUTHORITY=PC2_REUSED
echo SO5_IDENTITY_AUTHORITY=PC5_SEPARATE
echo SO5_STRUCTURE_AUTHORITY=PC1_REUSED
echo SO5_RESOURCE_AUTHORITY=PASS
echo SO5_NON_PERSON_RESOURCE=PASS
echo SO5_ASSIGNMENT=PASS
echo SO5_ASSIGNMENT_HISTORY=PASS
echo SO5_IDEMPOTENCY=PASS
echo SO5_TENANT_ISOLATION=PASS
echo SO5_NEUTRALITY=PASS
echo SO5_XA_CONTRACT=PASS
echo SO5_FINANCIAL_EFFECTS=UNCHANGED
echo SO5_SINGLE_GATE=PASS
exit /b 0
:fail
echo SO5_SINGLE_GATE=FAIL
exit /b 1
