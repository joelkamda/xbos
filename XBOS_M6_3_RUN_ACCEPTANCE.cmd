@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [M6.3] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "XBOS_BRANCH=%%B"
if not "%XBOS_BRANCH%"=="track-b/m6-treasury-reconciliation-close-control" goto branch_fail
for /f "delims=" %%H in ('git rev-parse --short HEAD') do set "XBOS_HEAD=%%H"
if not "%XBOS_HEAD%"=="426610d" goto head_fail

echo [M6.3] Static contract and Python validation
python -m json.tool contracts\finance\v1\m63_formal_close_reopen_and_closed_period_governance.json > nul || goto static_fail
python -m py_compile core\domain\finance\reconciliation_close_contract.py core\domain\finance\reconciliation_close_repository.py core\domain\finance\reconciliation_close_engine.py core\persistence\m63_reconciliation_close_governance.py alembic_neutral\versions\m63_reconciliation_close_019_formal_close_reopen_and_period_protection.py scripts\verify_m63_reconciliation_close_governance.py tests\contracts\test_m63_formal_close_reopen_and_closed_period_governance.py || goto static_fail

echo [M6.3] Canonical head and development revision
python -m alembic heads | findstr /l /x /c:"m63_reconciliation_close_019 (head)" > nul || goto canonical_fail
python -m alembic current

echo [M6.3] Focused contract validation
python -m pytest tests\contracts\test_m63_formal_close_reopen_and_closed_period_governance.py -q || goto contract_fail

echo [M6.3] Read-only development and disposable rehearsal
python scripts\verify_m63_reconciliation_close_governance.py verify || goto development_fail
python scripts\verify_m63_reconciliation_close_governance.py status || goto disposable_status_fail
python scripts\verify_m63_reconciliation_close_governance.py create-and-verify || goto disposable_fail

echo [M6.3] Apply empty M6.3 migration to development
python -m alembic upgrade head || goto development_upgrade_fail
python scripts\verify_m63_reconciliation_close_governance.py verify || goto development_post_fail

echo [M6.3] Full regression and whitespace gate
python -m pytest -q || goto regression_fail
git diff --check || goto whitespace_fail

echo M63_SINGLE_GATE=PASS head=m63_reconciliation_close_019 development=PASS close=PASS protection=PASS reopen=PASS period_coordination=PASS history=PASS regression=PASS
exit /b 0

:branch_fail
echo M63_SINGLE_GATE=FAIL step=branch expected=track-b/m6-treasury-reconciliation-close-control actual=%XBOS_BRANCH%
exit /b 1
:head_fail
echo M63_SINGLE_GATE=FAIL step=head expected=426610d actual=%XBOS_HEAD%
exit /b 1
:static_fail
echo M63_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:canonical_fail
echo M63_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:contract_fail
echo M63_SINGLE_GATE=FAIL step=contract_tests
exit /b 1
:development_fail
echo M63_SINGLE_GATE=FAIL step=development_preflight
exit /b 1
:disposable_status_fail
echo M63_SINGLE_GATE=FAIL step=disposable_status
exit /b 1
:disposable_fail
echo M63_SINGLE_GATE=FAIL step=disposable_rehearsal
exit /b 1
:development_upgrade_fail
echo M63_SINGLE_GATE=FAIL step=development_upgrade
exit /b 1
:development_post_fail
echo M63_SINGLE_GATE=FAIL step=development_postcheck
exit /b 1
:regression_fail
echo M63_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M63_SINGLE_GATE=FAIL step=whitespace
exit /b 1
