@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PC0_HEAD="
for /f "delims=" %%V in ('git rev-parse HEAD 2^>nul') do set "PC0_HEAD=%%V"
if not "%PC0_HEAD%"=="fa9b17e473105c7c70b8faa3a0a946ee9117d37e" goto :fail

if not defined VIRTUAL_ENV goto :fail
for %%V in ("%VIRTUAL_ENV%") do set "PC0_VENV_NAME=%%~nxV"
if /I not "%PC0_VENV_NAME%"=="xbos-track-b-b1" goto :fail

set "PC0_PYTHON_VERSION="
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PC0_PYTHON_VERSION=%%V"
if not "%PC0_PYTHON_VERSION%"=="Python 3.13.3" goto :fail

set "PC0_PYTHON_EXE="
for /f "delims=" %%V in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PC0_PYTHON_EXE=%%V"
for %%V in ("%VIRTUAL_ENV%\Scripts\python.exe") do set "PC0_EXPECTED_PYTHON=%%~fV"
if /I not "%PC0_PYTHON_EXE%"=="%PC0_EXPECTED_PYTHON%" goto :fail

python -m pytest --version >nul 2>&1
if errorlevel 1 goto :fail

python tests\contracts\test_pc0_kernel_boundaries.py
if errorlevel 1 goto :fail

python -m pytest -q
if errorlevel 1 goto :fail

python scripts\verify_pc0_kernel_boundaries.py --development
if errorlevel 1 goto :fail

git diff --check
if errorlevel 1 goto :fail

echo PC0_SINGLE_GATE=PASS
exit /b 0

:fail
echo PC0_SINGLE_GATE=FAIL
exit /b 1
