@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PC1_HEAD="
for /f "delims=" %%V in ('git rev-parse --short^=7 HEAD 2^>nul') do set "PC1_HEAD=%%V"
if not "%PC1_HEAD%"=="9830ebb" goto :fail

if not defined VIRTUAL_ENV goto :fail
for %%V in ("%VIRTUAL_ENV%") do set "PC1_VENV_NAME=%%~nxV"
if /I not "%PC1_VENV_NAME%"=="xbos-track-b-b1" goto :fail
set "PC1_PYTHON_VERSION="
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PC1_PYTHON_VERSION=%%V"
if not "%PC1_PYTHON_VERSION%"=="Python 3.13.3" goto :fail
set "PC1_PYTHON_EXE="
for /f "delims=" %%V in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PC1_PYTHON_EXE=%%V"
for %%V in ("%VIRTUAL_ENV%\Scripts\python.exe") do set "PC1_EXPECTED_PYTHON=%%~fV"
if /I not "%PC1_PYTHON_EXE%"=="%PC1_EXPECTED_PYTHON%" goto :fail
python -m pytest --version >nul 2>&1
if errorlevel 1 goto :fail

python scripts\verify_pc0_kernel_boundaries.py
if errorlevel 1 goto :fail
python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc1_structural_authority.py tests\contracts\test_historical_frozen_lineage_descendants.py
if errorlevel 1 goto :fail
python scripts\verify_pc1_structural_authority.py --acceptance
if errorlevel 1 goto :fail
python -m pytest -q
if errorlevel 1 goto :fail
git diff --check
if errorlevel 1 goto :fail

echo PC1_SOURCE_CHECKPOINT=9830ebb
echo PC1_PREVIOUS_HEAD=m64_reconciliation_controls_020
echo PC1_ACCEPTED_HEAD=pc1_structural_context_021
echo PC1_DISPOSABLE_REHEARSAL=PASS
echo PC1_DEVELOPMENT_ADOPTION=PASS
echo PC1_FINANCIAL_EFFECTS=UNCHANGED
echo PC1_SINGLE_GATE=PASS
exit /b 0

:fail
echo PC1_SINGLE_GATE=FAIL
exit /b 1
