@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [PK0123] Frozen predecessor verifiers
python scripts/verify_pc0_kernel_boundaries.py || goto :fail
python scripts/verify_pc1_structural_authority.py || goto :fail
python scripts/verify_pc2_party_authority.py || goto :fail
python scripts/verify_pc3_semantic_authority.py || goto :fail
python scripts/verify_pc4_operating_context.py || goto :fail
python scripts/verify_pc5_identity_policy_audit.py || goto :fail
python scripts/verify_pc6_neutral_platform.py || goto :fail
python scripts/verify_xa_frontend_experience_architecture.py || goto :fail
python scripts/verify_so_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pk0123_pack_manifest_lifecycle_extensions.py || goto :fail

echo [PK0123] Focused cumulative conformance
python -m pytest -q tests/contracts/test_pc0_kernel_boundaries.py tests/contracts/test_pc6_neutral_platform_proof.py tests/contracts/test_xa_frontend_experience_architecture.py tests/contracts/test_so_aggregate_conformance_freeze.py tests/contracts/test_pk0123_pack_manifest_lifecycle_extensions.py || goto :fail

echo [PK0123] PostgreSQL replay, lifecycle and development adoption
python scripts/verify_pk0123_pack_manifest_lifecycle_extensions.py --acceptance || goto :fail

echo [PK0123] Full regression
python -m pytest -q || goto :fail

echo [PK0123] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('PK0123_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo PK0123_SOURCE_CHECKPOINT=da61371
echo PK0123_PREVIOUS_HEAD=so_aggregate_conformance_hardening_036
echo PK0123_ACCEPTED_HEAD=pk0123_pack_manifest_lifecycle_037
echo PK0123_MANIFEST=PASS
echo PK0123_LIFECYCLE=PASS
echo PK0123_PUBLIC_EXTENSIONS=PASS
echo PK0123_CONNECTOR_CONTRACT=PASS
echo PK0123_PROVIDER_FINALITY=PASS
echo PK0123_TENANT_IDEMPOTENCY=PASS
echo PK0123_FINANCE=UNCHANGED
echo PK0123_SHARED_OPERATIONS=UNCHANGED
echo PK0123_DEPENDENCIES=UNCHANGED
echo PK0123_SINGLE_GATE=PASS
exit /b 0
:fail
echo PK0123_SINGLE_GATE=FAIL
exit /b 1
