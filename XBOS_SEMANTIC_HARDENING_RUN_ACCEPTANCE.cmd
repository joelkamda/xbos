@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [SEMANTIC HARDENING] Frozen predecessor integrity
python scripts/verify_pc3_semantic_authority.py || goto :fail
python scripts/verify_pc6_neutral_platform.py || goto :fail
python scripts/verify_so_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pk_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pa6_platform_administration_aggregate_freeze.py || goto :fail

echo [SEMANTIC HARDENING] Static and focused contracts
python scripts/verify_semantic_classification_hardening.py || goto :fail
python -m pytest -q tests/contracts/test_pc3_semantic_authority.py tests/contracts/test_so1_atomic_catalog_pricing.py tests/contracts/test_pk_aggregate_conformance_freeze.py tests/contracts/test_pa6_platform_administration_aggregate_freeze.py tests/contracts/test_semantic_classification_hardening.py || goto :fail

echo [SEMANTIC HARDENING] PostgreSQL authoritative acceptance
python scripts/verify_semantic_classification_hardening.py --acceptance || goto :fail

echo [SEMANTIC HARDENING] Full regression
python -m pytest -q || goto :fail

echo [SEMANTIC HARDENING] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('SEMANTIC_HARDENING_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo SEMANTIC_HARDENING_SOURCE_CHECKPOINT=11e7c90
echo SEMANTIC_HARDENING_PREVIOUS_HEAD=pa45_support_recovery_health_040
echo SEMANTIC_HARDENING_ACCEPTED_HEAD=semantic_classification_hardening_041
echo SEMANTIC_HARDENING_GLOBAL_TAXONOMY=PASS
echo SEMANTIC_HARDENING_TAXONOMY_SYSTEMS=40
echo SEMANTIC_HARDENING_UNBOUNDED_DEPTH=PASS
echo SEMANTIC_HARDENING_HISTORICAL_PLACEMENT=PASS
echo SEMANTIC_HARDENING_TENANT_OVERLAYS=PASS
echo SEMANTIC_HARDENING_ROOT_PARENT_OVERRIDE=PASS
echo SEMANTIC_HARDENING_EFFECTIVE_CYCLE_GUARD=PASS
echo SEMANTIC_HARDENING_TENANT_IDEMPOTENCY=PASS
echo SEMANTIC_HARDENING_TARGET_GOVERNANCE=PASS
echo SEMANTIC_HARDENING_FIVE_READ_LENSES=PASS
echo SEMANTIC_HARDENING_CROSS_INDUSTRY_NEUTRALITY=PASS
echo SEMANTIC_HARDENING_FROZEN_PC3_FILES=UNCHANGED
echo SEMANTIC_HARDENING_SHARED_OPERATIONS_AUTHORITY=UNCHANGED
echo SEMANTIC_HARDENING_PACK_PLATFORM_AUTHORITY=UNCHANGED
echo SEMANTIC_HARDENING_PLATFORM_ADMIN_AUTHORITY=UNCHANGED
echo SEMANTIC_HARDENING_FINANCE_AUTHORITY=UNCHANGED
echo SEMANTIC_HARDENING_RELEASE_METADATA_REFRESH=PASS
echo SEMANTIC_HARDENING_DEPENDENCIES=UNCHANGED
echo SEMANTIC_HARDENING_WND_PRODUCTION=UNCHANGED
echo SEMANTIC_HARDENING_R0_READINESS=PASS
echo SEMANTIC_HARDENING_SINGLE_GATE=PASS
exit /b 0

:fail
echo SEMANTIC_HARDENING_SINGLE_GATE=FAIL
exit /b 1
