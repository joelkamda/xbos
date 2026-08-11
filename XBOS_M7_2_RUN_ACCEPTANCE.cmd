@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "EXPECTED_BRANCH=track-b/m7-finance-facing-wnd-migration-support"
set "EXPECTED_HEAD=m64_reconciliation_controls_020"

echo [M7.2] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "ACTUAL_BRANCH=%%B"
if not "%ACTUAL_BRANCH%"=="%EXPECTED_BRANCH%" goto branch_fail

echo [M7.2] Static contract and Python validation
python -m json.tool contracts\finance\v1\m72_wnd_inventory_cogs_and_document_linkage.json > nul || goto static_fail
python -m py_compile core\domain\finance\wnd_inventory_document_contract.py core\domain\finance\wnd_inventory_document_service.py core\persistence\m72_wnd_inventory_document_mapping.py scripts\verify_m72_wnd_inventory_document_mapping.py tests\contracts\test_m72_wnd_inventory_cogs_and_document_linkage.py || goto static_fail

echo [M7.2] Canonical head and focused contract validation
python -m alembic heads | findstr /C:"%EXPECTED_HEAD%" > nul || goto head_fail
python -m pytest tests\contracts\test_m72_wnd_inventory_cogs_and_document_linkage.py -q || goto focused_fail

echo [M7.2] Read-only development verification
python scripts\verify_m72_wnd_inventory_document_mapping.py || goto development_fail

echo [M7.2] Full regression and whitespace gate
python -m pytest -q || goto regression_fail
git diff --check || goto whitespace_fail

echo M72_SINGLE_GATE=PASS head=%EXPECTED_HEAD% verified_cogs=PASS missing_cost_withheld=PASS receipt_linkage=PASS historical_documents=PASS replay=PASS no_revenue=PASS writer_routing=UNCHANGED migration=NONE regression=PASS
exit /b 0

:branch_fail
echo M72_SINGLE_GATE=FAIL step=branch expected=%EXPECTED_BRANCH% actual=%ACTUAL_BRANCH%
exit /b 1
:static_fail
echo M72_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_fail
echo M72_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:focused_fail
echo M72_SINGLE_GATE=FAIL step=focused_contracts
exit /b 1
:development_fail
echo M72_SINGLE_GATE=FAIL step=development_preflight
exit /b 1
:regression_fail
echo M72_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M72_SINGLE_GATE=FAIL step=whitespace
exit /b 1
