@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [M8.4] Source-control checkpoint
for /f "delims=" %%B in ('git branch --show-current') do set "M84_BRANCH=%%B"
if not "%M84_BRANCH%"=="track-b/m8-financial-hardening-and-exit" (
  echo M84_SINGLE_GATE=FAIL step=branch expected=track-b/m8-financial-hardening-and-exit actual=%M84_BRANCH%
  exit /b 1
)

echo [M8.4] Static contract and Python validation
python -m json.tool contracts\finance\v1\m84_pack_financial_conformance_and_production_readiness.json >nul || goto :static_fail
python -m py_compile core\domain\finance\pack_conformance_contract.py core\domain\finance\pack_conformance_service.py core\domain\finance\wnd_pack_conformance_profile.py core\persistence\m84_pack_financial_conformance.py scripts\verify_m84_pack_financial_conformance.py tests\contracts\test_m84_pack_financial_conformance_and_production_readiness.py || goto :static_fail

echo [M8.4] Canonical head and focused acceptance contracts
python -m pytest -q tests\contracts\test_m84_pack_financial_conformance_and_production_readiness.py || goto :focused_fail

echo [M8.4] Read-only development and disposable PostgreSQL conformance rehearsal
python scripts\verify_m84_pack_financial_conformance.py verify || goto :development_fail
python scripts\verify_m84_pack_financial_conformance.py status || goto :development_fail
python scripts\verify_m84_pack_financial_conformance.py create-and-verify || goto :rehearsal_fail

echo [M8.4] Full regression and whitespace gate
python -m pytest -q tests\contracts tests\characterization || goto :regression_fail
git diff --check || goto :whitespace_fail

echo M84_SINGLE_GATE=PASS head=m64_reconciliation_controls_020 pack_conformance=PASS generic_harness=PASS wnd_specimen=PASS exact_once=PASS replay=PASS conflict=PASS control_totals=PASS hidden_writers=NONE traceability=PASS tenant_scope=PASS organization_scope=PASS permissions=PASS approvals=PASS recovery=PASS cutover=NOT_AUTHORIZED writer_retirement=NOT_EXECUTED schema_neutral=PASS migration=NONE regression=PASS
exit /b 0

:static_fail
echo M84_SINGLE_GATE=FAIL step=static_validation
exit /b 1
:focused_fail
echo M84_SINGLE_GATE=FAIL step=focused_contracts
exit /b 1
:development_fail
echo M84_SINGLE_GATE=FAIL step=development_preflight
exit /b 1
:rehearsal_fail
echo M84_SINGLE_GATE=FAIL step=disposable_conformance_rehearsal
exit /b 1
:regression_fail
echo M84_SINGLE_GATE=FAIL step=full_regression
exit /b 1
:whitespace_fail
echo M84_SINGLE_GATE=FAIL step=whitespace
exit /b 1
