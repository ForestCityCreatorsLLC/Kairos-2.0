@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
set "KAIROS_EXTERNAL_SUPERVISOR=1"
set "RELOAD_ARGS="
if /I "%~1"=="--dev" set "RELOAD_ARGS=--reload --reload-dir services"

if exist ".venv\Scripts\python.exe" goto :check_ui
echo [!] First-time launch detected - running setup_kairos_2.bat...
call "%~dp0setup_kairos_2.bat"
if errorlevel 1 exit /b 1

:check_ui
if exist "%~dp0apps\desktop\node_modules" goto :start_services
echo [!] Installing desktop UI packages...
pushd "%~dp0apps\desktop"
call npm install
popd

:start_services
call "%~dp0stop_kairos_2.bat"

echo ============================================================
echo   Launching KAIROS 2.0 - Canopy Vault OS
echo   - Canopy Vault : C:\Users\igxxg\OneDrive\Documents\FCC Business Docs\Canopy Vault
echo   - Core API/MCP : http://127.0.0.1:8420
echo   - Voice Sidecar: http://127.0.0.1:8421
echo   - Desktop UI   : Electron + http://127.0.0.1:5173
echo ============================================================

start "KAIROS 2.0 Core API - 8420" /d "%~dp0" cmd /k ".venv\Scripts\python.exe -m uvicorn services.kairos_core.api:app --host 127.0.0.1 --port 8420 %RELOAD_ARGS%"
start "KAIROS 2.0 Voice Sidecar - 8421" /d "%~dp0" cmd /k ".venv\Scripts\python.exe -m uvicorn services.kairos_voice.voice_service:app --host 127.0.0.1 --port 8421 %RELOAD_ARGS%"

echo [*] Waiting for KAIROS Core API on 8420 and Voice Sidecar on 8421 to come online...
powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(30); $cOk = $false; $vOk = $false; while ((Get-Date) -lt $deadline) { if (-not $cOk) { try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8420/api/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { $cOk = $true } } catch {} } if (-not $vOk) { try { $rv = Invoke-WebRequest -Uri 'http://127.0.0.1:8421/api/voice/state' -UseBasicParsing -TimeoutSec 2; if ($rv.StatusCode -eq 200) { $vOk = $true } } catch {} } if ($cOk -and $vOk) { break } Start-Sleep -Milliseconds 400 }; if ($cOk -and $vOk) { Write-Host '[OK] Core API (8420) and Voice Sidecar (8421) online - launching KAIROS 2.0 Desktop Shell...' } else { Write-Host ('[WARN] Startup probe timed out after 30s (Core8420=' + $cOk + ', Voice8421=' + $vOk + ') - launching Desktop Shell...') }"

start "KAIROS 2.0 Desktop Shell" /d "%~dp0apps\desktop" cmd /k "set KAIROS_EXTERNAL_SUPERVISOR=1&& npm run dev"
exit /b 0
