@echo off
setlocal
cd /d "%~dp0"

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" (
  echo SO2_VERIFY=FAIL
  echo SO2_PYTHON_VERSION=%PYTHON_VERSION%
  echo SO2_SINGLE_GATE=FAIL
  exit /b 1
)
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

python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc1_structural_authority.py tests\contracts\test_pc2_party_authority.py tests\contracts\test_pc3_semantic_authority.py tests\contracts\test_pc4_operating_context.py tests\contracts\test_pc5_identity_policy_audit.py tests\contracts\test_pc6_neutral_platform_proof.py tests\contracts\test_xa_frontend_experience_architecture.py tests\contracts\test_so0_shared_operations_constitution.py tests\contracts\test_so1_atomic_catalog_pricing.py tests\contracts\test_so2_operational_party_relationships.py || goto :fail
python scripts\verify_so2_operational_party_relationships.py --acceptance || goto :fail
python -m pytest -q || goto :fail
python -m compileall -q core shared_operations scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('SO2_JSON=PASS')" || goto :fail
git diff --check || goto :fail

echo SO2_SOURCE_CHECKPOINT=733e226
echo SO2_PREVIOUS_HEAD=so1_atomic_catalog_offer_pricing_026
echo SO2_ACCEPTED_HEAD=so2_operational_party_relationships_027
echo SO2_PARTY_AUTHORITY=PC2_REUSED
echo SO2_IDENTITY_SEPARATION=PASS
echo SO2_MULTI_RELATIONSHIP_PARTY=PASS
echo SO2_MULTI_TENANT_PARTY=PASS
echo SO2_TENANT_ISOLATION=PASS
echo SO2_NEUTRALITY=PASS
echo SO2_XA_CONTRACT=PASS
echo SO2_FINANCIAL_EFFECTS=UNCHANGED
echo SO2_SINGLE_GATE=PASS
exit /b 0

:fail
echo SO2_SINGLE_GATE=FAIL
exit /b 1
