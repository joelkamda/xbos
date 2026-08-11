@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [M7.4] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT_BRANCH=%%B"
if not "%CURRENT_BRANCH%"=="track-b/m7-finance-facing-wnd-migration-support" goto branch_fail

echo [M7.4] Static contract and Python validation
python -m json.tool contracts\finance\v1\m74_wnd_dual_read_cutover_readiness_and_writer_retirement_support.json > nul || goto static_fail
python -m py_compile core\domain\finance\wnd_cutover_support_contract.py core\domain\finance\wnd_cutover_support_service.py core\persistence\m74_wnd_cutover_support.py scripts\verify_m74_wnd_cutover_support.py tests\contracts\test_m74_wnd_dual_read_cutover_readiness_and_writer_retirement_support.py || goto static_fail

echo [M7.4] Canonical head and focused contract validation
python -m alembic heads 2>nul | findstr /B /C:"m64_reconciliation_controls_020" > nul || goto head_fail
python -m pytest tests\contracts\test_m74_wnd_dual_read_cutover_readiness_and_writer_retirement_support.py -q || goto contract_fail

echo [M7.4] Read-only dual-read and readiness verification
python scripts\verify_m74_wnd_cutover_support.py || goto verifier_fail

echo [M7.4] Full regression and whitespace gate
python -m pytest -q || goto regression_fail
git diff --check || goto whitespace_fail

echo M74_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 dual_read=PASS readiness=PASS retirement_support=PASS writer_routing=UNCHANGED cutover=NOT_AUTHORIZED retirement=NOT_EXECUTED migration=NONE regression=PASS
exit /b 0

:branch_fail
echo M74_SINGLE_GATE=FAIL step=branch expected=track-b/m7-finance-facing-wnd-migration-support actual=%CURRENT_BRANCH%
exit /b 1
:static_fail
echo M74_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_fail
echo M74_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:contract_fail
echo M74_SINGLE_GATE=FAIL step=contract_tests
exit /b 1
:verifier_fail
echo M74_SINGLE_GATE=FAIL step=readiness_verifier
exit /b 1
:regression_fail
echo M74_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M74_SINGLE_GATE=FAIL step=whitespace
exit /b 1
