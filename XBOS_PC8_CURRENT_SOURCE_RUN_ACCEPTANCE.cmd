@echo off
setlocal DisableDelayedExpansion
REM Route A local proof; no registry promotion, protected edit or Git push.
REM Invocation must explicitly choose --local-only or --operative.
cd /d "%~dp0" || exit /b 80
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1"
set "PYTHONUTF8=1"

if /I "%~1"=="--local-only" goto LOCAL
if /I "%~1"=="--committed-preflight" goto COMMITTED
if /I "%~1"=="--operative" goto OPERATIVE
echo DENIED_EXPLICIT_SOURCE_GATE_MODE_REQUIRED
exit /b 81

:LOCAL
python -m pytest -q -p no:cacheprovider --tb=short tests/contracts/test_pc8_registered_current_source_r1.py
if errorlevel 1 goto FAILTEST
python scripts\verify_pc8_registered_current_source_r1.py --local-candidate
if errorlevel 1 goto FAILLOCAL
REM An operative gate returning success without external trust is a release breach.
python scripts\verify_pc8_registered_current_source_r1.py --operative >nul 2>nul
if not errorlevel 1 goto FAILOPEN
echo PASS_LOCAL_NONOPERATIVE_CANDIDATE_ONLY
echo OPERATIVE_D1_HOLD_NO_REQUIRED_CI_OR_DEPLOY_PROOF
exit /b 0

REM Source-only future CI: accepted GitHub event SHA MUST match checked out
REM committed code; local untracked precommit checks are intentionally excluded.
REM No source-integrity preflight can substitute for independently signed release.
:COMMITTED
if /I not "%GITHUB_ACTIONS%"=="true" goto NOCONTEXT
if "%GITHUB_SHA%"=="" goto NOCONTEXT
if /I not "%GITHUB_REPOSITORY%"=="joelkamda/xbos" goto NOCONTEXT
python -m pytest -q -p no:cacheprovider --tb=short tests/contracts/test_pc8_registered_current_source_r1.py
if errorlevel 1 goto FAILTEST
python scripts\verify_pc8_registered_current_source_r1.py --committed-preflight --expected-source-sha "%GITHUB_SHA%"
if errorlevel 1 goto FAILCOMMITTED
echo PASS_SOURCE_INTEGRITY_CANDIDATE_ONLY_NOT_OPERATIVE
echo REQUIRED_BRANCH_RULE_AND_INDEPENDENT_RELEASE_STILL_HOLD
exit /b 0

:OPERATIVE
REM Official CI must fail closed until independently approved trust is installed.
python scripts\verify_pc8_registered_current_source_r1.py --operative
if errorlevel 1 goto FAILOPERATIVE
echo ERROR_UNEXPECTED_OPERATIVE_ACCEPTANCE_REVIEW_REQUIRED
exit /b 82

:NOCONTEXT
echo DENIED_GITHUB_COMMITTED_SOURCE_CONTEXT_UNPROVEN
exit /b 87
:FAILCOMMITTED
echo DENIED_POSTCOMMIT_SOURCE_INTEGRITY
exit /b 88
:FAILTEST
echo DENIED_ROUTE_A_TARGETED_TESTS
exit /b 83
:FAILLOCAL
echo DENIED_ROUTE_A_LOCAL_SOURCE_INTEGRITY
exit /b 84
:FAILOPEN
echo DENIED_ROUTE_A_OPERATIVE_BYPASS
exit /b 85
:FAILOPERATIVE
echo DENIED_ROUTE_A_OPERATIVE_RELEASE_HOLD
exit /b 86
