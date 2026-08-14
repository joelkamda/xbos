@echo off
setlocal EnableExtensions
cd /d "%~dp0"

for /f "delims=" %%V in ('python --version 2^>^&1') do set "SO1_PYTHON_VERSION=%%V"
if not "%SO1_PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -c "import sys; print('SO1_PYTHON=' + sys.executable)" || goto :fail
python -m pytest --version || goto :fail
for /f "delims=" %%C in ('git rev-parse HEAD 2^>nul') do set "SO1_SOURCE_HEAD=%%C"
if not "%SO1_SOURCE_HEAD%"=="f72f4b5d8ad8e576212347615458fcd801e9f7bd" goto :fail

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
python -m pytest -q tests\contracts\test_so1_atomic_catalog_pricing.py || goto :fail
python scripts\verify_so1_atomic_catalog_pricing.py --acceptance || goto :fail
python -m pytest -q || goto :fail
python -m compileall -q shared_operations\so1 scripts\verify_so1_atomic_catalog_pricing.py tests\contracts\test_so1_atomic_catalog_pricing.py || goto :fail
python -m json.tool contracts\shared_operations\v1\so1_authority.json >nul || goto :fail
python -m json.tool contracts\shared_operations\v1\so1_legacy_adoption_manifest.json >nul || goto :fail
python -m json.tool contracts\shared_operations\v1\so1_public_interfaces.json >nul || goto :fail
python -m json.tool contracts\shared_operations\v1\so1_xa_metadata.json >nul || goto :fail
git diff --check || goto :fail

echo SO1_SOURCE_CHECKPOINT=f72f4b5
echo SO1_PREVIOUS_HEAD=pc5_identity_policy_audit_025
echo SO1_ACCEPTED_HEAD=so1_atomic_catalog_offer_pricing_026
echo SO1_LEGACY_ATOMIC_UNIT_IDENTITY=PRESERVED
echo SO1_TAXONOMY_BRIDGE=PASS
echo SO1_NEUTRALITY=PASS
echo SO1_TENANT_ISOLATION=PASS
echo SO1_PRICING_RESOLUTION=PASS
echo SO1_FINANCIAL_EFFECTS=UNCHANGED
echo SO1_XA_CONTRACT=PASS
echo SO1_SINGLE_GATE=PASS
exit /b 0

:fail
echo SO1_SINGLE_GATE=FAIL
exit /b 1
