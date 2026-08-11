@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [M7.3] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT_BRANCH=%%B"
if not "%CURRENT_BRANCH%"=="track-b/m7-finance-facing-wnd-migration-support" goto branch_fail

echo [M7.3] Static contract and Python validation
python -m json.tool contracts\finance\v1\m73_wnd_shadow_execution_rehearsal_and_control_totals.json > nul || goto static_fail
python -m py_compile core\domain\finance\wnd_shadow_rehearsal_contract.py core\domain\finance\wnd_shadow_rehearsal_service.py core\persistence\m73_wnd_shadow_rehearsal.py scripts\verify_m73_wnd_shadow_rehearsal.py tests\contracts\test_m73_wnd_shadow_execution_rehearsal_and_control_totals.py || goto static_fail

echo [M7.3] Canonical head and focused contract validation
python -m alembic heads 2>nul | findstr /B /C:"m64_reconciliation_controls_020" > nul || goto head_fail
python -m pytest tests\contracts\test_m73_wnd_shadow_execution_rehearsal_and_control_totals.py -q || goto contract_fail

echo [M7.3] Shadow rehearsal and deterministic control totals
python scripts\verify_m73_wnd_shadow_rehearsal.py || goto rehearsal_fail

echo [M7.3] Full regression and whitespace gate
python -m pytest -q || goto regression_fail
git diff --check || goto whitespace_fail

echo M73_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 shadow=PASS production_shape=PASS control_totals=PASS variance=PASS replay=PASS writer_routing=UNCHANGED migration=NONE regression=PASS
exit /b 0

:branch_fail
echo M73_SINGLE_GATE=FAIL step=branch expected=track-b/m7-finance-facing-wnd-migration-support actual=%CURRENT_BRANCH%
exit /b 1
:static_fail
echo M73_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_fail
echo M73_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:contract_fail
echo M73_SINGLE_GATE=FAIL step=contract_tests
exit /b 1
:rehearsal_fail
echo M73_SINGLE_GATE=FAIL step=shadow_rehearsal
exit /b 1
:regression_fail
echo M73_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M73_SINGLE_GATE=FAIL step=whitespace
exit /b 1
