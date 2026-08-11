@echo off
setlocal
cd /d "%~dp0"

echo [M8.0] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if not "%BRANCH%"=="track-b/m8-financial-hardening-and-exit" goto branch_fail

echo [M8.0] Static contract and Python validation
python -m json.tool contracts\finance\v1\m80_global_financial_invariants_property_concurrency_and_replay.json > nul || goto static_fail
python -m py_compile core\domain\finance\global_invariant_contract.py core\domain\finance\global_invariant_service.py core\persistence\m80_global_financial_hardening.py scripts\verify_m80_global_financial_invariants.py tests\contracts\test_m80_global_financial_invariants_property_concurrency_and_replay.py || goto static_fail

echo [M8.0] Canonical head and focused adversarial contracts
for /f "delims=" %%H in ('python -m alembic heads') do set "HEAD=%%H"
echo %HEAD% | findstr /c:"m64_reconciliation_controls_020 (head)" > nul || goto head_fail
python -m pytest tests\contracts\test_m80_global_financial_invariants_property_concurrency_and_replay.py -q || goto contract_fail

echo [M8.0] Read-only development and disposable PostgreSQL concurrency rehearsal
python scripts\verify_m80_global_financial_invariants.py verify || goto development_fail
python scripts\verify_m80_global_financial_invariants.py status || goto development_fail
python scripts\verify_m80_global_financial_invariants.py create-and-verify || goto rehearsal_fail

echo [M8.0] Full regression and whitespace gate
python -m pytest -q || goto regression_fail
git diff --check || goto whitespace_fail

echo M80_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 global_invariants=PASS property_cases=512 concurrency=PASS replay=PASS conflict=PASS rollback=PASS tenant_scope=PASS schema_neutral=PASS regression=PASS
exit /b 0

:branch_fail
echo M80_SINGLE_GATE=FAIL step=branch expected=track-b/m8-financial-hardening-and-exit actual=%BRANCH%
exit /b 1
:static_fail
echo M80_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_fail
echo M80_SINGLE_GATE=FAIL step=canonical_head actual=%HEAD%
exit /b 1
:contract_fail
echo M80_SINGLE_GATE=FAIL step=focused_contracts
exit /b 1
:development_fail
echo M80_SINGLE_GATE=FAIL step=development_preflight
exit /b 1
:rehearsal_fail
echo M80_SINGLE_GATE=FAIL step=disposable_rehearsal
exit /b 1
:regression_fail
echo M80_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M80_SINGLE_GATE=FAIL step=whitespace
exit /b 1
