@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PC2_HEAD="
for /f "delims=" %%V in ('git rev-parse --short^=7 HEAD 2^>nul') do set "PC2_HEAD=%%V"
if not "%PC2_HEAD%"=="3190a07" goto :fail
if not defined VIRTUAL_ENV goto :fail
for %%V in ("%VIRTUAL_ENV%") do set "PC2_VENV_NAME=%%~nxV"
if /I not "%PC2_VENV_NAME%"=="xbos-track-b-b1" goto :fail
set "PC2_PYTHON_VERSION="
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PC2_PYTHON_VERSION=%%V"
if not "%PC2_PYTHON_VERSION%"=="Python 3.13.3" goto :fail
set "PC2_PYTHON_EXE="
for /f "delims=" %%V in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PC2_PYTHON_EXE=%%V"
for %%V in ("%VIRTUAL_ENV%\Scripts\python.exe") do set "PC2_EXPECTED_PYTHON=%%~fV"
if /I not "%PC2_PYTHON_EXE%"=="%PC2_EXPECTED_PYTHON%" goto :fail
python -m pytest --version >nul 2>&1
if errorlevel 1 goto :fail

python scripts\verify_pc0_kernel_boundaries.py
if errorlevel 1 goto :fail
python scripts\verify_pc1_structural_authority.py
if errorlevel 1 goto :fail
python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc1_structural_authority.py tests\contracts\test_historical_frozen_lineage_descendants.py tests\contracts\test_pc2_party_authority.py
if errorlevel 1 goto :fail
python scripts\verify_pc2_party_authority.py --acceptance
if errorlevel 1 goto :fail
python -m pytest -q
if errorlevel 1 goto :fail
git diff --check
if errorlevel 1 goto :fail

echo PC2_SOURCE_CHECKPOINT=3190a07
echo PC2_PREVIOUS_HEAD=pc1_structural_context_021
echo PC2_ACCEPTED_HEAD=pc2_party_authority_022
echo PC2_DISPOSABLE_REHEARSAL=PASS
echo PC2_DEVELOPMENT_ADOPTION=PASS
echo PC2_FINANCIAL_EFFECTS=UNCHANGED
echo PC2_SINGLE_GATE=PASS
exit /b 0

:fail
echo PC2_SINGLE_GATE=FAIL
exit /b 1
