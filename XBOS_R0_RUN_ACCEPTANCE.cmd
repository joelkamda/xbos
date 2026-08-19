@echo off
setlocal
cd /d "%~dp0"
set GIT_PAGER=cat
set PAGER=cat
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
if not "%PYTHON_VERSION%"=="Python 3.13.3" goto :fail
python -m pytest --version >nul 2>&1 || goto :fail

echo [R0] Frozen predecessor integrity
python scripts/verify_pc6_neutral_platform.py || goto :fail
python scripts/verify_so_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pk_aggregate_conformance_freeze.py || goto :fail
python scripts/verify_pa6_platform_administration_aggregate_freeze.py || goto :fail
python scripts/verify_semantic_classification_hardening.py || goto :fail

echo [R0] Restaurant extraction contracts
python scripts/verify_r0_restaurant_domain_extraction.py || goto :fail
python -m pytest -q tests/contracts/test_r0_restaurant_domain_extraction.py tests/contracts/test_semantic_classification_hardening.py tests/contracts/test_pk_aggregate_conformance_freeze.py || goto :fail

echo [R0] Development head read-only proof
python scripts/verify_r0_restaurant_domain_extraction.py --development || goto :fail

echo [R0] Full regression
python -m pytest -q || goto :fail

echo [R0] Compilation, JSON and whitespace
python -m compileall -q core shared_operations pack_platform platform_admin experience_contracts scripts tests || goto :fail
python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('contracts').rglob('*.json')]; print('R0_JSON=PASS')" || goto :fail
git --no-pager diff --check || goto :fail

echo R0_SOURCE_CHECKPOINT=64eb3e9
echo R0_ACCEPTED_MIGRATION_HEAD=semantic_classification_hardening_041
echo R0_MIGRATION=NONE
echo R0_CURRENT_RESTAURANT_INVENTORY=PASS
echo R0_AUTHORITY_CLASSIFICATION=PASS
echo R0_TENANT_LITERAL_PLAN=PASS
echo R0_AGGREGATE_BOUNDARIES=PASS
echo R0_EVENT_CATALOG=PASS
echo R0_WND_PRODUCTION_INVARIANTS=PASS
echo R0_WND_SPECIMEN_NOT_STANDARD=PASS
echo R0_MISSING_RESTAURANT_CAPABILITIES_RESERVED=PASS
echo R0_NO_DUPLICATE_SHARED_AUTHORITY=PASS
echo R0_NO_NEW_FINANCIAL_AUTHORITY=PASS
echo R0_SC41_SEMANTIC_CONFORMANCE=PASS
echo R0_WND_BEHAVIOR_ACCOUNTED_FOR=PASS
echo R0_R1_READINESS=PASS
echo R0_SINGLE_GATE=PASS
exit /b 0

:fail
echo R0_SINGLE_GATE=FAIL
exit /b 1
