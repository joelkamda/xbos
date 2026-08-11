@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [M7.5] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT_BRANCH=%%B"
if not "%CURRENT_BRANCH%"=="track-b/m7-finance-facing-wnd-migration-support" goto branch_fail

echo [M7.5] Static contract and Python validation
python -m json.tool contracts\finance\v1\m75_finance_migration_support_acceptance_and_freeze.json > nul || goto static_fail
python -m json.tool contracts\finance\v1\m7_release_manifest.json > nul || goto static_fail
python -m py_compile core\domain\finance\m7_acceptance.py core\persistence\m75_finance_migration_support_exit.py scripts\verify_m75_m7_acceptance.py tests\contracts\test_m75_finance_migration_support_acceptance_and_freeze.py || goto static_fail

echo [M7.5] Canonical head and focused acceptance contracts
python -m alembic heads 2>nul | findstr /B /C:"m64_reconciliation_controls_020" > nul || goto head_fail
python -m pytest tests\contracts\test_m75_finance_migration_support_acceptance_and_freeze.py -q || goto contract_fail

echo [M7.5] Aggregate M7.0-M7.4 conformance
python scripts\verify_m75_m7_acceptance.py create-and-verify || goto aggregate_fail

echo [M7.5] Full regression and whitespace gate
python -m pytest -q || goto regression_fail
git diff --check || goto whitespace_fail

echo M75_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 manifest=PASS development=PASS m70_m74=PASS inventory=PASS mapping=PASS cogs_documents=PASS shadow=PASS control_totals=PASS dual_read=PASS readiness=PASS replay=PASS writer_routing=UNCHANGED cutover=NOT_AUTHORIZED retirement=NOT_EXECUTED migration=NONE regression=PASS
exit /b 0

:branch_fail
echo M75_SINGLE_GATE=FAIL step=branch expected=track-b/m7-finance-facing-wnd-migration-support actual=%CURRENT_BRANCH%
exit /b 1
:static_fail
echo M75_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_fail
echo M75_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:contract_fail
echo M75_SINGLE_GATE=FAIL step=contract_tests
exit /b 1
:aggregate_fail
echo M75_SINGLE_GATE=FAIL step=aggregate_conformance
exit /b 1
:regression_fail
echo M75_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M75_SINGLE_GATE=FAIL step=whitespace
exit /b 1
