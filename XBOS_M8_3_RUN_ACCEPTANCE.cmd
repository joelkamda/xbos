@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "EXPECTED_BRANCH=track-b/m8-financial-hardening-and-exit"
set "EXPECTED_HEAD=m64_reconciliation_controls_020"

echo [M8.3] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "ACTUAL_BRANCH=%%B"
if not "%ACTUAL_BRANCH%"=="%EXPECTED_BRANCH%" (
  echo M83_SINGLE_GATE=FAIL step=branch expected=%EXPECTED_BRANCH% actual=%ACTUAL_BRANCH%
  exit /b 1
)

echo [M8.3] Static contract and Python validation
python -m json.tool contracts\finance\v1\m83_performance_index_backup_restore_and_deployment_recovery.json >nul || goto :static_fail
python -m py_compile core\domain\finance\performance_recovery_contract.py core\domain\finance\performance_recovery_service.py core\persistence\m83_performance_recovery_hardening.py scripts\verify_m83_performance_recovery.py tests\contracts\test_m83_performance_index_backup_restore_and_deployment_recovery.py || goto :static_fail
where pg_dump >nul 2>nul || goto :tools_fail
where pg_restore >nul 2>nul || goto :tools_fail

echo [M8.3] Canonical head and focused acceptance contracts
for /f "delims=" %%H in ('alembic -c alembic.ini heads 2^>nul') do set "ALEMBIC_HEAD=%%H"
echo %ALEMBIC_HEAD% | findstr /b /c:"%EXPECTED_HEAD%" >nul || goto :head_fail
python -m pytest -q tests\contracts\test_m83_performance_index_backup_restore_and_deployment_recovery.py || goto :focused_fail

echo [M8.3] Read-only development, volume, plans, backup/restore and recovery rehearsal
python scripts\verify_m83_performance_recovery.py create-and-verify || goto :rehearsal_fail

echo [M8.3] Full regression and whitespace gate
python -m pytest -q || goto :regression_fail
git diff --check || goto :whitespace_fail

echo M83_SINGLE_GATE=PASS head=%EXPECTED_HEAD% performance=PASS volume=PASS indexes=PASS query_plans=PASS backup_restore=PASS financial_equivalence=PASS rollback_rehearsal=PASS operator_recovery=PASS financial_invariants=PASS tenant_scope=PASS schema_neutral=PASS regression=PASS
exit /b 0

:static_fail
echo M83_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:tools_fail
echo M83_SINGLE_GATE=FAIL step=postgresql_tools required=pg_dump,pg_restore
exit /b 1
:head_fail
echo M83_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:focused_fail
echo M83_SINGLE_GATE=FAIL step=contract_tests
exit /b 1
:rehearsal_fail
echo M83_SINGLE_GATE=FAIL step=disposable_recovery_rehearsal
exit /b 1
:regression_fail
echo M83_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M83_SINGLE_GATE=FAIL step=whitespace
exit /b 1
