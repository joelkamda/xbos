@echo off
setlocal EnableExtensions
cd /d "%~dp0"

for /f "delims=" %%V in ('python --version 2^>^&1') do set "SO0_PYTHON_VERSION=%%V"
if not "%SO0_PYTHON_VERSION%"=="Python 3.13.3" (
  echo SO0_PYTHON_VERSION=FAIL expected Python 3.13.3 got %SO0_PYTHON_VERSION%
  goto :fail
)
python -c "import sys; print('SO0_PYTHON=' + sys.executable)" || goto :fail
python -m pytest --version || goto :fail
for /f "delims=" %%C in ('git rev-parse HEAD 2^>nul') do set "SO0_SOURCE_HEAD=%%C"
if not "%SO0_SOURCE_HEAD%"=="56cbbb8a220fe881fcceb05b4e217e0b6c79da3c" (
  echo SO0_SOURCE_CHECKPOINT=FAIL expected 56cbbb8a220fe881fcceb05b4e217e0b6c79da3c got %SO0_SOURCE_HEAD%
  goto :fail
)

python scripts\verify_pc0_kernel_boundaries.py || goto :fail
python scripts\verify_pc1_structural_authority.py || goto :fail
python scripts\verify_pc2_party_authority.py || goto :fail
python scripts\verify_pc3_semantic_authority.py || goto :fail
python scripts\verify_pc4_operating_context.py || goto :fail
python scripts\verify_pc5_identity_policy_audit.py || goto :fail
python scripts\verify_pc6_neutral_platform.py || goto :fail
python scripts\verify_xa_frontend_experience_architecture.py || goto :fail
python scripts\verify_so0_shared_operations.py || goto :fail

python -m pytest -q tests\contracts\test_so0_shared_operations_constitution.py || goto :fail
python -m pytest -q || goto :fail
python -m compileall -q shared_operations_contracts scripts\verify_so0_shared_operations.py tests\contracts\test_so0_shared_operations_constitution.py || goto :fail
python -m json.tool contracts\shared_operations\v1\so0_shared_operations_constitution.json >nul || goto :fail
python -m json.tool contracts\shared_operations\v1\so0_module_contract.json >nul || goto :fail
python -m json.tool contracts\shared_operations\v1\so0_public_private_boundaries.json >nul || goto :fail
python -m json.tool contracts\shared_operations\v1\so0_release_manifest.json >nul || goto :fail
git diff --check || goto :fail

echo SO0_SOURCE_CHECKPOINT=56cbbb8
echo SO0_MIGRATION=NONE
echo SO0_PLATFORM_CORE=FROZEN_UNCHANGED
echo SO0_XA=FROZEN_CONSUMED
echo SO0_FINANCIAL_EFFECTS=UNCHANGED
echo SO0_SO1_PLUS_IMPLEMENTATION=NONE
echo SO0_PK_PA_FRONTEND_IMPLEMENTATION=NONE
echo SO0_SINGLE_GATE=PASS
exit /b 0

:fail
echo SO0_SINGLE_GATE=FAIL
exit /b 1
