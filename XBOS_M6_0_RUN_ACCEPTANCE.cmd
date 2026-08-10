@echo off
setlocal EnableExtensions

echo [M6.0] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "M60_BRANCH=%%B"
if /I not "%M60_BRANCH%"=="track-b/m6-treasury-reconciliation-close-control" goto branch_fail
for /f "delims=" %%H in ('git rev-parse --short HEAD') do set "M60_HEAD=%%H"
if /I not "%M60_HEAD%"=="3f659e0" goto commit_fail

echo [M6.0] Static contract and Python validation
python -m json.tool contracts\finance\v1\m60_operational_account_and_balance_authority.json > nul
if errorlevel 1 goto static_fail
python -m py_compile core\domain\finance\operational_balance_contract.py core\domain\finance\operational_balance_repository.py core\domain\finance\operational_balance_engine.py core\domain\finance\operational_balance_service.py core\persistence\m60_operational_balance_authority.py alembic_neutral\versions\m60_operational_balance_authority_016_treasury_accounts_and_balances.py scripts\verify_m60_operational_balance_authority.py tests\contracts\test_m60_operational_account_and_balance_authority.py
if errorlevel 1 goto static_fail

echo [M6.0] Canonical-head and starting-development validation
python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; h=ScriptDirectory.from_config(Config('alembic.ini')).get_heads(); assert h==['m60_operational_balance_authority_016'],h; print(h[0]+' (head)')"
if errorlevel 1 goto head_fail
python -c "from sqlalchemy import text; from database import engine; c=engine.connect(); r=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one(); c.close(); assert r in {'m46_provider_financials_015','m60_operational_balance_authority_016'},r; print(r)"
if errorlevel 1 goto development_revision_fail

echo [M6.0] Focused contract validation
python -m pytest tests\contracts\test_m60_operational_account_and_balance_authority.py -q
if errorlevel 1 goto contract_fail

echo [M6.0] Read-only development and disposable rehearsal
python scripts\verify_m60_operational_balance_authority.py verify
if errorlevel 1 goto development_fail
python scripts\verify_m60_operational_balance_authority.py status
if errorlevel 1 goto disposable_status_fail
python scripts\verify_m60_operational_balance_authority.py create-and-verify
if errorlevel 1 goto disposable_fail

echo [M6.0] Apply empty authority migration to development
python -m alembic upgrade head
if errorlevel 1 goto development_upgrade_fail
python scripts\verify_m60_operational_balance_authority.py verify
if errorlevel 1 goto development_fail

echo [M6.0] Full regression and whitespace gate
python -m pytest -q
if errorlevel 1 goto regression_fail
git diff --check
if errorlevel 1 goto whitespace_fail

echo M60_SINGLE_GATE=PASS head=m60_operational_balance_authority_016 development=PASS disposable=PASS account_authority=PASS expected_actual_variance=PASS regression=PASS
exit /b 0

:branch_fail
echo M60_SINGLE_GATE=FAIL step=branch actual=%M60_BRANCH%
exit /b 1
:commit_fail
echo M60_SINGLE_GATE=FAIL step=starting_commit actual=%M60_HEAD%
exit /b 1
:static_fail
echo M60_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_fail
echo M60_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:development_revision_fail
echo M60_SINGLE_GATE=FAIL step=development_revision
exit /b 1
:contract_fail
echo M60_SINGLE_GATE=FAIL step=contract_tests
exit /b 1
:development_fail
echo M60_SINGLE_GATE=FAIL step=development_gate
exit /b 1
:disposable_status_fail
echo M60_SINGLE_GATE=FAIL step=disposable_status
exit /b 1
:disposable_fail
echo M60_SINGLE_GATE=FAIL step=disposable_rehearsal
exit /b 1
:development_upgrade_fail
echo M60_SINGLE_GATE=FAIL step=development_upgrade
exit /b 1
:regression_fail
echo M60_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M60_SINGLE_GATE=FAIL step=git_diff_check
exit /b 1
