@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHONDONTWRITEBYTECODE=1"

python scripts\verify_pc7_neutral_interaction_authority.py || goto :fail
python scripts\verify_pc6_neutral_platform.py || goto :fail
python scripts\verify_pc0_kernel_boundaries.py || goto :fail

python -m pytest -q ^
  tests\contracts\test_pc7_neutral_interaction_authority.py ^
  tests\contracts\test_pc7_cumulative_release_manifest_chain.py ^
  tests\contracts\test_pc6_cumulative_release_manifest_chain.py ^
  tests\contracts\test_pc6_neutral_platform_proof.py ^
  tests\contracts\test_pc0_kernel_boundaries.py || goto :fail

python -m compileall -q core scripts tests || goto :fail
git diff --check || goto :fail

echo PC7_PREVIOUS_HEAD=pc5_identity_policy_audit_025
echo PC7_ACCEPTED_HEAD=ia0_neutral_interaction_authority_045
echo PC7_RELEASE_SEQUENCE=7
echo PC7_NEUTRAL_INTERACTION_AUTHORITY=PASS
echo PC7_HISTORICAL_PC1_PC6_RESOLUTION=PASS
echo PC7_A3_DEFINITION=NOT_YET_REPOSITORY_AUTHORITY
echo PC7_PLATFORM_CORE_FREEZE=PASS
echo PC7_SINGLE_GATE=PASS
exit /b 0

:fail
echo PC7_SINGLE_GATE=FAIL
exit /b 1
