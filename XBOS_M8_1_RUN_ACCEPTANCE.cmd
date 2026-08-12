@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo [M8.1] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT_BRANCH=%%B"
if not "!CURRENT_BRANCH!"=="track-b/m8-financial-hardening-and-exit" (
  echo M81_SINGLE_GATE=FAIL step=branch expected=track-b/m8-financial-hardening-and-exit actual=!CURRENT_BRANCH!
  exit /b 1
)

echo [M8.1] Static contract and Python validation
python -m json.tool contracts\finance\v1\m81_ordering_offline_isolation_and_authorization.json >nul || goto :static_fail
python -m py_compile core\domain\finance\adversarial_ordering_contract.py core\domain\finance\adversarial_ordering_service.py core\persistence\m81_ordering_offline_security_hardening.py scripts\verify_m81_ordering_offline_isolation_authorization.py tests\contracts\test_m81_ordering_offline_isolation_and_authorization.py || goto :static_fail

echo [M8.1] Canonical head and focused acceptance contracts
for /f "tokens=1" %%H in ('alembic heads') do set "ALEMBIC_HEAD=%%H"
if not "!ALEMBIC_HEAD!"=="m64_reconciliation_controls_020" (
  echo M81_SINGLE_GATE=FAIL step=canonical_head actual=!ALEMBIC_HEAD!
  exit /b 1
)
python -m pytest tests\contracts\test_m81_ordering_offline_isolation_and_authorization.py -q || goto :focused_fail

echo [M8.1] Read-only development and disposable PostgreSQL rehearsal
python scripts\verify_m81_ordering_offline_isolation_authorization.py verify || goto :rehearsal_fail
python scripts\verify_m81_ordering_offline_isolation_authorization.py status || goto :rehearsal_fail
python scripts\verify_m81_ordering_offline_isolation_authorization.py create-and-verify || goto :rehearsal_fail

echo [M8.1] Full regression and whitespace gate
python -m pytest -q || goto :regression_fail
git diff --check || goto :whitespace_fail
echo M81_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 ordering=PASS offline=PASS tenant_scope=PASS organization_scope=PASS permissions=PASS approvals=PASS replay=PASS conflict=PASS schema_neutral=PASS regression=PASS
exit /b 0

:static_fail
echo M81_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:focused_fail
echo M81_SINGLE_GATE=FAIL step=focused_contracts
exit /b 1
:rehearsal_fail
echo M81_SINGLE_GATE=FAIL step=disposable_rehearsal
exit /b 1
:regression_fail
echo M81_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M81_SINGLE_GATE=FAIL step=whitespace
exit /b 1
