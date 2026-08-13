@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PC3_HEAD="
for /f "delims=" %%V in ('git rev-parse --short^=7 HEAD 2^>nul') do set "PC3_HEAD=%%V"
if not "%PC3_HEAD%"=="0163039" goto :fail
if not defined VIRTUAL_ENV goto :fail
for %%V in ("%VIRTUAL_ENV%") do set "PC3_VENV_NAME=%%~nxV"
if /I not "%PC3_VENV_NAME%"=="xbos-track-b-b1" goto :fail
set "PC3_PYTHON_VERSION="
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PC3_PYTHON_VERSION=%%V"
if not "%PC3_PYTHON_VERSION%"=="Python 3.13.3" goto :fail
set "PC3_PYTHON_EXE="
for /f "delims=" %%V in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PC3_PYTHON_EXE=%%V"
for %%V in ("%VIRTUAL_ENV%\Scripts\python.exe") do set "PC3_EXPECTED_PYTHON=%%~fV"
if /I not "%PC3_PYTHON_EXE%"=="%PC3_EXPECTED_PYTHON%" goto :fail
python -m pytest --version >nul 2>&1
if errorlevel 1 goto :fail
python scripts\verify_pc0_kernel_boundaries.py
if errorlevel 1 goto :fail
python scripts\verify_pc1_structural_authority.py
if errorlevel 1 goto :fail
python scripts\verify_pc2_party_authority.py
if errorlevel 1 goto :fail
python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc1_structural_authority.py tests\contracts\test_historical_frozen_lineage_descendants.py tests\contracts\test_pc2_party_authority.py tests\contracts\test_pc3_semantic_authority.py
if errorlevel 1 goto :fail
python scripts\verify_pc3_semantic_authority.py --acceptance
if errorlevel 1 goto :fail
python -m pytest -q
if errorlevel 1 goto :fail
git diff --check
if errorlevel 1 goto :fail
echo PC3_SOURCE_CHECKPOINT=0163039
echo PC3_PREVIOUS_HEAD=pc2_party_authority_022
echo PC3_ACCEPTED_HEAD=pc3_semantic_authority_023
echo PC3_DISPOSABLE_REHEARSAL=PASS
echo PC3_DEVELOPMENT_ADOPTION=PASS
echo PC3_FINANCIAL_EFFECTS=UNCHANGED
echo PC3_SINGLE_GATE=PASS
exit /b 0
:fail
echo PC3_SINGLE_GATE=FAIL
exit /b 1
