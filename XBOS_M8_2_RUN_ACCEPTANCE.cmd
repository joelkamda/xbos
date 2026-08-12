@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%"

echo [M8.2] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if not "%BRANCH%"=="track-b/m8-financial-hardening-and-exit" goto :branch_fail

echo [M8.2] Static contract and Python validation
python -m json.tool contracts\finance\v1\m82_external_provider_and_infrastructure_failure_resilience.json >nul || goto :static_fail
python -m py_compile core\domain\finance\external_failure_resilience_contract.py core\domain\finance\external_failure_resilience_service.py core\persistence\m82_external_failure_resilience.py scripts\verify_m82_external_failure_resilience.py tests\contracts\test_m82_external_provider_and_infrastructure_failure_resilience.py || goto :static_fail

echo [M8.2] Canonical head and focused acceptance contracts
for /f "delims=" %%R in ('python -c "from database import engine; from sqlalchemy import text; c=engine.connect(); print(c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()); c.close()"') do set "REVISION=%%R"
if not "%REVISION%"=="m64_reconciliation_controls_020" goto :head_fail
python -m pytest -q tests\contracts\test_m82_external_provider_and_infrastructure_failure_resilience.py || goto :focused_fail

echo [M8.2] Read-only development and disposable PostgreSQL rehearsal
python scripts\verify_m82_external_failure_resilience.py create-and-verify || goto :rehearsal_fail

echo [M8.2] Full regression and whitespace gate
python -m pytest -q || goto :regression_fail
git diff --check || goto :whitespace_fail

echo M82_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 webhook_security=PASS provider_outage=PASS uncertainty=PASS replay=PASS rollback=PASS atomicity=PASS tenant_scope=PASS schema_neutral=PASS regression=PASS
exit /b 0

:branch_fail
echo M82_SINGLE_GATE=FAIL step=branch expected=track-b/m8-financial-hardening-and-exit actual=%BRANCH%
exit /b 1
:static_fail
echo M82_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_fail
echo M82_SINGLE_GATE=FAIL step=canonical_head actual=%REVISION%
exit /b 1
:focused_fail
echo M82_SINGLE_GATE=FAIL step=focused_contracts
exit /b 1
:rehearsal_fail
echo M82_SINGLE_GATE=FAIL step=disposable_rehearsal
exit /b 1
:regression_fail
echo M82_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M82_SINGLE_GATE=FAIL step=whitespace
exit /b 1
