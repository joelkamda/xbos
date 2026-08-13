@echo off
setlocal EnableExtensions
cd /d "%~dp0"

for /f "delims=" %%V in ('python --version 2^>^&1') do set "XA_PYTHON_VERSION=%%V"
if not "%XA_PYTHON_VERSION%"=="Python 3.13.3" (
  echo XA_PYTHON_VERSION=FAIL expected Python 3.13.3 got %XA_PYTHON_VERSION%
  goto :fail
)
python -c "import sys; print('XA_PYTHON=' + sys.executable)" || goto :fail
python -m pytest --version || goto :fail
for /f "delims=" %%C in ('git rev-parse HEAD 2^>nul') do set "XA_SOURCE_HEAD=%%C"
if not "%XA_SOURCE_HEAD%"=="9ce8c1a5746ec7607636d6a9be20102194e9f230" (
  echo XA_SOURCE_CHECKPOINT=FAIL expected 9ce8c1a5746ec7607636d6a9be20102194e9f230 got %XA_SOURCE_HEAD%
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

python -m pytest -q tests\contracts\test_xa_frontend_experience_architecture.py || goto :fail
python -m pytest -q || goto :fail
python -m compileall -q experience_contracts scripts\verify_xa_frontend_experience_architecture.py tests\contracts\test_xa_frontend_experience_architecture.py || goto :fail
git diff --check || goto :fail

echo XA_SOURCE_CHECKPOINT=9ce8c1a
echo XA_MIGRATION=NONE
echo XA_FRONTEND_IMPLEMENTATION=NONE
echo XA_SO_PK_PA_IMPLEMENTATION=NONE
echo XA_FINANCIAL_EFFECTS=UNCHANGED
echo XA_SINGLE_GATE=PASS
exit /b 0

:fail
echo XA_SINGLE_GATE=FAIL
exit /b 1
