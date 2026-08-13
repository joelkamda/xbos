@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PC4_HEAD="
for /f "delims=" %%V in ('git rev-parse --short^=7 HEAD 2^>nul') do set "PC4_HEAD=%%V"
if not "%PC4_HEAD%"=="601a395" goto :fail
if not defined VIRTUAL_ENV goto :fail
for %%V in ("%VIRTUAL_ENV%") do set "PC4_VENV_NAME=%%~nxV"
if /I not "%PC4_VENV_NAME%"=="xbos-track-b-b1" goto :fail
set "PC4_PYTHON_VERSION="
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PC4_PYTHON_VERSION=%%V"
if not "%PC4_PYTHON_VERSION%"=="Python 3.13.3" goto :fail
set "PC4_PYTHON_EXE="
for /f "delims=" %%V in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PC4_PYTHON_EXE=%%V"
for %%V in ("%VIRTUAL_ENV%\Scripts\python.exe") do set "PC4_EXPECTED_PYTHON=%%~fV"
if /I not "%PC4_PYTHON_EXE%"=="%PC4_EXPECTED_PYTHON%" goto :fail
python -m pytest --version >nul 2>&1
if errorlevel 1 goto :fail
python scripts\verify_pc0_kernel_boundaries.py
if errorlevel 1 goto :fail
python scripts\verify_pc1_structural_authority.py
if errorlevel 1 goto :fail
python scripts\verify_pc2_party_authority.py
if errorlevel 1 goto :fail
python scripts\verify_pc3_semantic_authority.py
if errorlevel 1 goto :fail
python -m pytest -q tests\contracts\test_pc0_kernel_boundaries.py tests\contracts\test_pc1_structural_authority.py tests\contracts\test_historical_frozen_lineage_descendants.py tests\contracts\test_pc2_party_authority.py tests\contracts\test_pc3_semantic_authority.py tests\contracts\test_pc4_operating_context.py tests\contracts\test_pc4_cumulative_release_manifest_chain.py
if errorlevel 1 goto :fail
python scripts\verify_pc4_operating_context.py --acceptance
if errorlevel 1 goto :fail
python -m pytest -q
if errorlevel 1 goto :fail
git diff --check
if errorlevel 1 goto :fail
echo PC4_SOURCE_CHECKPOINT=601a395
echo PC4_PREVIOUS_HEAD=pc3_semantic_authority_023
echo PC4_ACCEPTED_HEAD=pc4_operating_context_024
echo PC4_DISPOSABLE_REHEARSAL=PASS
echo PC4_DEVELOPMENT_ADOPTION=PASS
echo PC4_FINANCIAL_EFFECTS=UNCHANGED
echo PC4_SINGLE_GATE=PASS
exit /b 0
:fail
echo PC4_SINGLE_GATE=FAIL
exit /b 1
