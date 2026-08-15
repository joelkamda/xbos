@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [PK456] Frozen predecessor verifiers
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
python scripts/verify_pk456_pack_conformance_templates.py || goto :fail

echo [PK456] Focused cumulative conformance
python -m pytest -q tests/contracts/test_pc0_kernel_boundaries.py tests/contracts/test_pc6_neutral_platform_proof.py tests/contracts/test_xa_frontend_experience_architecture.py tests/contracts/test_so_aggregate_conformance_freeze.py tests/contracts/test_pk0123_pack_manifest_lifecycle_extensions.py tests/contracts/test_pk456_pack_conformance_templates.py || goto :fail

echo [PK456] PostgreSQL conformance, templates and development adoption
python scripts/verify_pk456_pack_conformance_templates.py --acceptance || goto :fail

echo [PK456] Full regression
python -m pytest -q || goto :fail

echo [PK456] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('PK456_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo PK456_SOURCE_CHECKPOINT=8f0034a
echo PK456_PREVIOUS_HEAD=pk0123_pack_manifest_lifecycle_037
echo PK456_ACCEPTED_HEAD=pk456_pack_conformance_templates_038
echo PK456_PACK_CONFORMANCE=PASS
echo PK456_TEMPLATE_REGISTRY=PASS
echo PK456_TEMPLATE_APPLICATION=PASS
echo PK456_TEMPLATE_UPGRADES=PASS
echo PK456_MERCHANT_DIVERGENCE=PASS
echo PK456_PAYMENTS_ONLY_NEUTRALITY=PASS
echo PK456_TENANT_IDEMPOTENCY=PASS
echo PK456_FINANCE=UNCHANGED
echo PK456_SHARED_OPERATIONS=UNCHANGED
echo PK456_DEPENDENCIES=UNCHANGED
echo PK456_SINGLE_GATE=PASS
exit /b 0
:fail
echo PK456_SINGLE_GATE=FAIL
exit /b 1
