@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [PA45] Frozen predecessor verifiers
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

echo [PA45] Focused cumulative conformance
python -m pytest -q tests/contracts/test_pc0_kernel_boundaries.py tests/contracts/test_pc6_neutral_platform_proof.py tests/contracts/test_xa_frontend_experience_architecture.py tests/contracts/test_so_aggregate_conformance_freeze.py tests/contracts/test_pk_aggregate_conformance_freeze.py tests/contracts/test_pa0123_platform_administration.py tests/contracts/test_pa45_platform_support_recovery_health.py || goto :fail

echo [PA45] PostgreSQL support, recovery, health and development adoption
python scripts/verify_pa45_platform_support_recovery_health.py --acceptance || goto :fail

echo [PA45] Full regression
python -m pytest -q || goto :fail

echo [PA45] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('PA45_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo PA45_SOURCE_CHECKPOINT=8ff3d8b
echo PA45_PREVIOUS_HEAD=pa0123_merchant_lifecycle_subscriptions_onboarding_039
echo PA45_ACCEPTED_HEAD=pa45_support_recovery_health_040
echo PA45_SUPPORT_DELEGATION=PASS
echo PA45_BREAK_GLASS=PASS
echo PA45_RECOVERY=PASS
echo PA45_MERCHANT_HEALTH=PASS
echo PA45_PLATFORM_HEALTH=PASS
echo PA45_PC5_SECURITY_AUTHORITY=REUSED
echo PA45_PA0123_MERCHANT_AUTHORITY=REUSED
echo PA45_TENANT_ISOLATION=PASS
echo PA45_TENANT_IDEMPOTENCY=PASS
echo PA45_FINANCE=UNCHANGED
echo PA45_SHARED_OPERATIONS=UNCHANGED
echo PA45_DEPENDENCIES=UNCHANGED
echo PA45_SINGLE_GATE=PASS
exit /b 0
:fail
echo PA45_SINGLE_GATE=FAIL
exit /b 1
