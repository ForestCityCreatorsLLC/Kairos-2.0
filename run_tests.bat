@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"

if exist ".venv\Scripts\pytest.exe" goto :run_pytest
echo [!] .venv not initialized yet - running setup_kairos_2.bat first...
call "%~dp0setup_kairos_2.bat"
if errorlevel 1 exit /b 1

:run_pytest
echo ============================================================
echo   [1/3] Running KAIROS 2.0 Automated Pytest Suite (98 Tests)
echo ============================================================
".venv\Scripts\python.exe" -m pytest -v
if errorlevel 1 exit /b 1

echo.
echo ============================================================
echo   [2/3] Type-Checking and Building React/TypeScript UI
echo ============================================================
pushd "%~dp0apps\desktop"
call npm run build
if errorlevel 1 (
    popd
    echo [ERROR] Frontend TypeScript/Vite build failed.
    exit /b 1
)
popd

echo.
echo ============================================================
echo   [3/3] Synchronizing Codebase Changes to Canopy Vault
echo ============================================================
".venv\Scripts\python.exe" -m services.kairos_core.vault_sync_hook --actor "run_tests.bat"
if errorlevel 1 exit /b 1

echo.
echo ============================================================
echo   All KAIROS 2.0 Tests, UI Build, and Vault Sync Passed!
echo ============================================================
exit /b 0
