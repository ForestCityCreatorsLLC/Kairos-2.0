@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"

if not exist ".venv\Scripts\python.exe" goto :missing_venv
".venv\Scripts\python.exe" -m services.kairos_core.vault_sync_hook --summary "%~1"
exit /b %ERRORLEVEL%

:missing_venv
echo [ERROR] .venv not found. Run setup_kairos_2.bat first.
exit /b 1
