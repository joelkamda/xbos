@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [M8.5] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "M85_BRANCH=%%B"
if not "%M85_BRANCH%"=="track-b/m8-financial-hardening-and-exit" (
  echo M85_SINGLE_GATE=FAIL step=branch expected=track-b/m8-financial-hardening-and-exit actual=%M85_BRANCH%
  exit /b 1
)

echo [M8.5] Static contract and Python validation
python -m json.tool contracts\finance\v1\m85_track_b_aggregate_conformance_freeze_and_approved_exit.json >nul || goto :static_fail
python -m json.tool contracts\finance\v1\track_b_financial_approved_exit_manifest.json >nul || goto :static_fail
python -m py_compile core\domain\finance\track_b_exit_contract.py core\domain\finance\track_b_acceptance.py core\persistence\m85_track_b_approved_exit.py scripts\verify_m85_track_b_approved_exit.py || goto :static_fail

echo [M8.5] Canonical head and focused acceptance contracts
for /f "delims=" %%H in ('python -m alembic -c alembic.ini heads') do set "M85_HEAD=%%H"
echo %M85_HEAD% | findstr /b /c:"m64_reconciliation_controls_020" >nul || goto :head_fail
python -m pytest -q tests\contracts\test_m85_track_b_aggregate_conformance_freeze_and_approved_exit.py || goto :focused_fail

echo [M8.5] Development freeze, clean replay and selected aggregate proof
python scripts\verify_m85_track_b_approved_exit.py status || goto :status_fail
python scripts\verify_m85_track_b_approved_exit.py create-and-verify || goto :aggregate_fail

echo [M8.5] Full regression and whitespace gate
python -m pytest -q tests\contracts tests\characterization || goto :regression_fail
git diff --check || goto :whitespace_fail

echo M85_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 aggregate_conformance=PASS canonical_lineage=PASS clean_replay=PASS financial_invariants=PASS cross_milestone=PASS replay=PASS conflict=PASS concurrency=PASS ordering=PASS offline=PASS provider_failure=PASS uncertainty=PASS rollback=PASS backup_restore=PASS recovery=PASS pack_conformance=PASS hidden_writers=NONE tenant_scope=PASS organization_scope=PASS permissions=PASS approvals=PASS M7_frozen=PASS development_empty=PASS cutover=NOT_AUTHORIZED writer_retirement=NOT_EXECUTED manifest=PASS schema_neutral=PASS migration=NONE regression=PASS
exit /b 0

:static_fail
echo M85_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:head_fail
echo M85_SINGLE_GATE=FAIL step=canonical_head
exit /b 1
:focused_fail
echo M85_SINGLE_GATE=FAIL step=focused_contracts
exit /b 1
:status_fail
echo M85_SINGLE_GATE=FAIL step=disposable_status
exit /b 1
:aggregate_fail
echo M85_SINGLE_GATE=FAIL step=aggregate_rehearsal
exit /b 1
:regression_fail
echo M85_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M85_SINGLE_GATE=FAIL step=whitespace
exit /b 1
