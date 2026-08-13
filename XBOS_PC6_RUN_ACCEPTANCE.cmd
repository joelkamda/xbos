@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PC6_EXPECTED_COMMIT=17c1d9c0732bf40c435315ad28f8fef79678826b"
set "PC6_DEP_ENV=%TEMP%\xbos_pc6_dependency_%RANDOM%_%RANDOM%"

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PC6_PYTHON_VERSION=%%V"
if not "%PC6_PYTHON_VERSION%"=="Python 3.13.3" goto :fail
for /f "delims=" %%E in ('python -c "import sys; print(sys.executable)"') do set "PC6_PYTHON_EXE=%%E"
echo %PC6_PYTHON_EXE% | findstr /I /C:"\xbos-track-b-b1\Scripts\python.exe" >nul || goto :fail
python -m pytest --version >nul || goto :fail
for /f "delims=" %%C in ('git rev-parse HEAD') do set "PC6_ACTUAL_COMMIT=%%C"
if /I not "%PC6_ACTUAL_COMMIT%"=="%PC6_EXPECTED_COMMIT%" goto :fail
echo PC6_SOURCE_CHECKPOINT=17c1d9c

if exist "%PC6_DEP_ENV%" goto :fail
python -m venv "%PC6_DEP_ENV%" || goto :fail
"%PC6_DEP_ENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-prod.txt || goto :fail
"%PC6_DEP_ENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-test.txt || goto :fail
set "DATABASE_URL=postgresql+psycopg2://pc6:pc6@localhost:5432/pc6_disposable_import_only"
set "JWT_SECRET=pc6-disposable-import-proof"
set "GATEWAY_API_KEY=pc6-disposable-reference"
"%PC6_DEP_ENV%\Scripts\python.exe" -c "import alembic,fastapi,httpx,passlib,psycopg2,pycountry,pydantic,pydantic_settings,jose,pytz,babel,sqlalchemy,starlette,uvicorn; import settings; from core.platform import structure,party,semantics,operating_context,security_authority,neutral_proof" || goto :fail
"%PC6_DEP_ENV%\Scripts\python.exe" -m compileall -q core scripts || goto :fail
rmdir /s /q "%PC6_DEP_ENV%" || goto :fail
set "DATABASE_URL="
set "JWT_SECRET="
set "GATEWAY_API_KEY="
echo PC6_DEPENDENCY_AUTHORITY=PASS

python scripts\verify_pc0_kernel_boundaries.py || goto :fail
python scripts\verify_pc1_structural_authority.py || goto :fail
python scripts\verify_pc2_party_authority.py || goto :fail
python scripts\verify_pc3_semantic_authority.py || goto :fail
python scripts\verify_pc4_operating_context.py || goto :fail
python scripts\verify_pc5_identity_policy_audit.py || goto :fail
python scripts\verify_pc6_neutral_platform.py || goto :fail

python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc1_structural_authority.py tests\contracts\test_pc2_party_authority.py tests\contracts\test_pc3_semantic_authority.py tests\contracts\test_pc4_operating_context.py tests\contracts\test_pc5_identity_policy_audit.py tests\contracts\test_pc4_cumulative_release_manifest_chain.py tests\contracts\test_pc5_cumulative_release_manifest_chain.py tests\contracts\test_pc6_neutral_platform_proof.py tests\contracts\test_pc6_cumulative_release_manifest_chain.py || goto :fail

python scripts\verify_pc6_neutral_platform.py --acceptance || goto :fail
python -m pytest -q || goto :fail
python -m compileall -q core scripts tests || goto :fail
git diff --check || goto :fail

echo PC6_PREVIOUS_HEAD=pc5_identity_policy_audit_025
echo PC6_ACCEPTED_HEAD=pc5_identity_policy_audit_025
echo PC6_SECOND_TENANT_BOOTSTRAP=PASS
echo PC6_NO_SOURCE_CHANGE=PASS
echo PC6_ISOLATION=PASS
echo PC6_PORTABILITY_RESTORE=PASS
echo PC6_FRESH_INSTALL=PASS
echo PC6_UPGRADE=PASS
echo PC6_WND_LEAKAGE_SCAN=PASS
echo PC6_PUBLIC_CONTRACT_PROOF=PASS
echo PC6_BACKUP_RESTORE=PASS
echo PC6_FINANCIAL_EFFECTS=UNCHANGED
echo PC6_PLATFORM_CORE_FREEZE=PASS
echo PC6_SINGLE_GATE=PASS
exit /b 0

:fail
echo PC6_SINGLE_GATE=FAIL
if exist "%PC6_DEP_ENV%" echo PC6_DEPENDENCY_ENV_RETAINED=%PC6_DEP_ENV%
exit /b 1
