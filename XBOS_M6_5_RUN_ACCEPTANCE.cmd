@echo off
setlocal
cd /d "%~dp0"

echo [M6.5] Source-control checkpoint
for /f "delims=" %%B in ('git symbolic-ref --quiet --short HEAD') do set "XBOS_BRANCH=%%B"
if not "%XBOS_BRANCH%"=="track-b/m6-treasury-reconciliation-close-control" goto branch_fail
for /f "delims=" %%H in ('git rev-parse --short HEAD') do set "XBOS_HEAD=%%H"
if not "%XBOS_HEAD%"=="521dab7" goto head_fail
git diff --quiet || goto working_diff_fail
git diff --cached --quiet || goto cached_diff_fail

echo [M6.5] Static contract and Python validation
python -m json.tool contracts\finance\v1\m65_m6_acceptance_and_freeze.json > nul || goto static_fail
python -m json.tool contracts\finance\v1\m6_release_manifest.json > nul || goto static_fail
python -m py_compile core\domain\finance\m6_acceptance.py core\persistence\m65_m6_exit.py scripts\verify_m65_m6_acceptance.py tests\contracts\test_m65_m6_acceptance.py || goto static_fail

echo [M6.5] Canonical head and focused acceptance contracts
python -m alembic heads | findstr /l /x /c:"m64_reconciliation_controls_020 (head)" > nul || goto head_gate_fail
python -m alembic current | findstr /l /x /c:"m64_reconciliation_controls_020 (head)" > nul || goto current_gate_fail
python -m pytest tests\contracts\test_m65_m6_acceptance.py -q || goto focused_fail

echo [M6.5] Aggregate M6.0-M6.4 conformance and recovery
python scripts\verify_m65_m6_acceptance.py create-and-verify || goto aggregate_fail

echo [M6.5] Full regression and whitespace gate
python -m pytest -q || goto regression_fail
git diff --check || goto whitespace_fail

echo M65_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 manifest=PASS development=PASS m60_m64=PASS recovery=PASS replay=PASS concurrency=PASS correction_cascade=PASS close_reopen=PASS bank_ar_ap=PASS regression=PASS
exit /b 0

:branch_fail
echo M65_SINGLE_GATE=FAIL step=branch expected=track-b/m6-treasury-reconciliation-close-control actual=%XBOS_BRANCH%
exit /b 1
:head_fail
echo M65_SINGLE_GATE=FAIL step=source_head expected=521dab7 actual=%XBOS_HEAD%
exit /b 1
:working_diff_fail
echo M65_SINGLE_GATE=FAIL step=tracked_working_diff
exit /b 1
:cached_diff_fail
echo M65_SINGLE_GATE=FAIL step=staged_changes
exit /b 1
:static_fail
echo M65_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_gate_fail
echo M65_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:current_gate_fail
echo M65_SINGLE_GATE=FAIL step=development_revision
exit /b 1
:focused_fail
echo M65_SINGLE_GATE=FAIL step=focused_contracts
exit /b 1
:aggregate_fail
echo M65_SINGLE_GATE=FAIL step=aggregate_rehearsal
exit /b 1
:regression_fail
echo M65_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M65_SINGLE_GATE=FAIL step=whitespace
exit /b 1
