@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [M7.0] Source-control checkpoint
set "ACTUAL_BRANCH="
for /f "delims=" %%B in ('git symbolic-ref --quiet --short HEAD 2^>nul') do set "ACTUAL_BRANCH=%%B"
if not "%ACTUAL_BRANCH%"=="track-b/m7-finance-facing-wnd-migration-support" goto branch_fail
set "ACTUAL_HEAD="
for /f "delims=" %%H in ('git rev-parse --short HEAD 2^>nul') do set "ACTUAL_HEAD=%%H"
if not "%ACTUAL_HEAD%"=="9ccddd3" goto head_fail
git diff --quiet || goto working_fail
git diff --cached --quiet || goto staged_fail

echo [M7.0] Static contract and Python validation
python -m json.tool contracts\finance\v1\m70_legacy_financial_authority_inventory_and_adapter_boundary.json > nul || goto static_fail
python -m py_compile core\domain\finance\legacy_authority_contract.py core\domain\finance\legacy_authority_inventory.py core\domain\finance\wnd_finance_adapter_contract.py core\persistence\m70_finance_migration_support.py scripts\verify_m70_legacy_financial_authority.py tests\contracts\test_m70_legacy_financial_authority_inventory_and_adapter_boundary.py || goto static_fail

echo [M7.0] Canonical head and focused contract validation
python -m alembic heads | findstr /x /c:"m64_reconciliation_controls_020 (head)" > nul || goto head_validation_fail
python -m pytest tests\contracts\test_m70_legacy_financial_authority_inventory_and_adapter_boundary.py -q || goto focused_fail

echo [M7.0] Read-only development and inventory validation
python scripts\verify_m70_legacy_financial_authority.py verify || goto verifier_fail

echo [M7.0] Full regression and whitespace gate
python -m pytest -q || goto regression_fail
git diff --check || goto whitespace_fail

echo M70_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 inventory=PASS adapter_boundary=PASS writer_routing=UNCHANGED cutover_owner=R6 migration=NONE regression=PASS
exit /b 0

:branch_fail
echo M70_SINGLE_GATE=FAIL step=branch expected=track-b/m7-finance-facing-wnd-migration-support actual=%ACTUAL_BRANCH%
exit /b 1
:head_fail
echo M70_SINGLE_GATE=FAIL step=source_head expected=9ccddd3 actual=%ACTUAL_HEAD%
exit /b 1
:working_fail
echo M70_SINGLE_GATE=FAIL step=preexisting_working_diff
exit /b 1
:staged_fail
echo M70_SINGLE_GATE=FAIL step=preexisting_staged_diff
exit /b 1
:static_fail
echo M70_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_validation_fail
echo M70_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:focused_fail
echo M70_SINGLE_GATE=FAIL step=focused_contracts
exit /b 1
:verifier_fail
echo M70_SINGLE_GATE=FAIL step=development_inventory
exit /b 1
:regression_fail
echo M70_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M70_SINGLE_GATE=FAIL step=whitespace
exit /b 1
