@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [PA6] Frozen predecessor verifiers
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
python scripts/verify_pa45_platform_support_recovery_health.py || goto :fail
python scripts/verify_pa6_platform_administration_aggregate_freeze.py || goto :fail

echo [PA6] Focused cumulative conformance
python -m pytest -q tests/contracts/test_pc0_kernel_boundaries.py tests/contracts/test_pc6_neutral_platform_proof.py tests/contracts/test_xa_frontend_experience_architecture.py tests/contracts/test_so_aggregate_conformance_freeze.py tests/contracts/test_pk_aggregate_conformance_freeze.py tests/contracts/test_pa0123_platform_administration.py tests/contracts/test_pa45_platform_support_recovery_health.py tests/contracts/test_pa6_platform_administration_aggregate_freeze.py || goto :fail

echo [PA6] PostgreSQL full merchant administration journey
python scripts/verify_pa6_platform_administration_aggregate_freeze.py --acceptance || goto :fail

echo [PA6] Full regression
python -m pytest -q || goto :fail

echo [PA6] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('PA6_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo PA6_SOURCE_CHECKPOINT=03ede10
echo PA6_PREVIOUS_HEAD=pa45_support_recovery_health_040
echo PA6_ACCEPTED_HEAD=pa45_support_recovery_health_040
echo PA6_MIGRATION=NONE
echo PA6_PA0_PA6_COVERAGE=PASS
echo PA6_MERCHANT_LIFECYCLE=PASS
echo PA6_SUBSCRIPTIONS_ENTITLEMENTS=PASS
echo PA6_USAGE_QUOTAS=PASS
echo PA6_ONBOARDING_READINESS=PASS
echo PA6_SUPPORT_RECOVERY=PASS
echo PA6_MERCHANT_PLATFORM_HEALTH=PASS
echo PA6_PUBLIC_BOUNDARIES=PASS
echo PA6_FULL_MERCHANT_JOURNEY=PASS
echo PA6_TENANT_ISOLATION=PASS
echo PA6_TENANT_IDEMPOTENCY=PASS
echo PA6_MIGRATION_LINEAGE=PASS
echo PA6_FINANCE=UNCHANGED
echo PA6_SHARED_OPERATIONS=UNCHANGED
echo PA6_PACK_PLATFORM=UNCHANGED
echo PA6_DEPENDENCIES=UNCHANGED
echo PA6_BUSINESS_CAPABILITY_CHANGE=NONE
echo PA6_R0_READINESS=PASS
echo PA6_SINGLE_GATE=PASS
exit /b 0

:fail
echo PA6_SINGLE_GATE=FAIL
exit /b 1
