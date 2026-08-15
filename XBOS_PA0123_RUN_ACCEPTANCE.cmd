@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [PA0123] Frozen predecessor verifiers
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
python scripts/verify_pa0123_platform_administration.py || goto :fail

echo [PA0123] Focused cumulative conformance
python -m pytest -q tests/contracts/test_pc0_kernel_boundaries.py tests/contracts/test_pc6_neutral_platform_proof.py tests/contracts/test_xa_frontend_experience_architecture.py tests/contracts/test_so_aggregate_conformance_freeze.py tests/contracts/test_pk_aggregate_conformance_freeze.py tests/contracts/test_pa0123_platform_administration.py || goto :fail

echo [PA0123] PostgreSQL administration and development adoption
python scripts/verify_pa0123_platform_administration.py --acceptance || goto :fail

echo [PA0123] Full regression
python -m pytest -q || goto :fail

echo [PA0123] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('PA0123_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo PA0123_SOURCE_CHECKPOINT=2402858
echo PA0123_PREVIOUS_HEAD=pk456_pack_conformance_templates_038
echo PA0123_ACCEPTED_HEAD=pa0123_merchant_lifecycle_subscriptions_onboarding_039
echo PA0123_MERCHANT_LIFECYCLE=PASS
echo PA0123_PLANS_SUBSCRIPTIONS=PASS
echo PA0123_USAGE_QUOTAS=PASS
echo PA0123_ONBOARDING_READINESS=PASS
echo PA0123_PC1_TENANT_AUTHORITY=REUSED
echo PA0123_PC4_ENTITLEMENT_AUTHORITY=REUSED
echo PA0123_PC5_SECURITY_AUTHORITY=REUSED
echo PA0123_PK_COMPOSITION_AUTHORITY=REUSED
echo PA0123_TENANT_IDEMPOTENCY=PASS
echo PA0123_FINANCE=UNCHANGED
echo PA0123_SHARED_OPERATIONS=UNCHANGED
echo PA0123_DEPENDENCIES=UNCHANGED
echo PA0123_SINGLE_GATE=PASS
exit /b 0
:fail
echo PA0123_SINGLE_GATE=FAIL
exit /b 1
