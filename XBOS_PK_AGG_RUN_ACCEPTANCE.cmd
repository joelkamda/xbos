@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [PK-AGG] Frozen predecessor verifiers
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
python scripts/verify_pk_aggregate_conformance_freeze.py || goto :fail

echo [PK-AGG] Focused cumulative conformance
python -m pytest -q tests/contracts/test_pc0_kernel_boundaries.py tests/contracts/test_pc6_neutral_platform_proof.py tests/contracts/test_xa_frontend_experience_architecture.py tests/contracts/test_so_aggregate_conformance_freeze.py tests/contracts/test_pk0123_pack_manifest_lifecycle_extensions.py tests/contracts/test_pk456_pack_conformance_templates.py tests/contracts/test_pk_aggregate_conformance_freeze.py || goto :fail

echo [PK-AGG] PostgreSQL cross-package aggregate acceptance
python scripts/verify_pk_aggregate_conformance_freeze.py --acceptance || goto :fail

echo [PK-AGG] Full regression
python -m pytest -q || goto :fail

echo [PK-AGG] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform experience_contracts scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('PK_AGG_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo PK_AGG_SOURCE_CHECKPOINT=97c6c75
echo PK_AGG_PREVIOUS_HEAD=pk456_pack_conformance_templates_038
echo PK_AGG_ACCEPTED_HEAD=pk456_pack_conformance_templates_038
echo PK_AGG_MIGRATION=NONE
echo PK_AGG_PK0_PK6_COVERAGE=PASS
echo PK_AGG_MANIFEST_LIFECYCLE=PASS
echo PK_AGG_PUBLIC_BOUNDARIES=PASS
echo PK_AGG_CONNECTOR_FINALITY=PASS
echo PK_AGG_PACK_CONFORMANCE=PASS
echo PK_AGG_TEMPLATE_REGISTRY=PASS
echo PK_AGG_TEMPLATE_APPLICATION_UPGRADES=PASS
echo PK_AGG_MERCHANT_DIVERGENCE=PASS
echo PK_AGG_PAYMENTS_ONLY_NEUTRALITY=PASS
echo PK_AGG_TENANT_ISOLATION=PASS
echo PK_AGG_XA_COMPOSITION=PASS
echo PK_AGG_MIGRATION_LINEAGE=PASS
echo PK_AGG_FINANCE=UNCHANGED
echo PK_AGG_SHARED_OPERATIONS=UNCHANGED
echo PK_AGG_DEPENDENCIES=UNCHANGED
echo PK_AGG_BUSINESS_CAPABILITY_CHANGE=NONE
echo PK_AGG_PA_READINESS=PASS
echo PK_AGG_SINGLE_GATE=PASS
exit /b 0

:fail
echo PK_AGG_SINGLE_GATE=FAIL
exit /b 1
