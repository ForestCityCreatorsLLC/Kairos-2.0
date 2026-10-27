@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   KAIROS 2.0 - Environment Setup
echo ============================================================

if exist ".venv\Scripts\python.exe" goto :venv_ready
echo [1/4] Creating isolated Python virtual environment in .venv ...
python -m venv .venv
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if not exist ".venv\Scripts\python.exe" goto :err_python

:venv_ready
echo [2/4] Installing Python Core, FastMCP, Watchdog and Pytest packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 goto :err_pip

if exist ".env" goto :env_ready
echo [3/4] Creating .env from .env.example...
copy /y ".env.example" ".env" >nul
goto :install_ui

:env_ready
echo [3/4] Existing .env preserved.

:install_ui
echo [4/4] Installing Electron + React + Vite dependencies in apps\desktop...
pushd "%~dp0apps\desktop"
call npm install
if errorlevel 1 goto :err_npm
popd

echo.
echo ============================================================
echo   KAIROS 2.0 Setup Complete!
echo ============================================================
exit /b 0

:err_python
echo [ERROR] Could not create .venv. Ensure Python 3.10+ is installed and on PATH.
exit /b 1

:err_pip
echo [ERROR] Python package installation failed.
exit /b 1

:err_npm
popd
echo [ERROR] npm install failed in apps\desktop.
exit /b 1
