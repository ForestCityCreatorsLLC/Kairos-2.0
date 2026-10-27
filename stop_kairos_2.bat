@echo off
echo [*] Stopping KAIROS 2.0 services on ports 8420, 8421, and 5173...

for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8420 " ^| findstr "LISTENING"') do taskkill /PID %%p /T /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8421 " ^| findstr "LISTENING"') do taskkill /PID %%p /T /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":5173 " ^| findstr "LISTENING"') do taskkill /PID %%p /T /F >nul 2>&1

taskkill /FI "WINDOWTITLE eq KAIROS 2.0 Core API*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq KAIROS 2.0 Voice Sidecar*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq KAIROS 2.0 Desktop Shell*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq KAIROS 2.0*" /T /F >nul 2>&1

timeout /t 1 /nobreak >nul
echo [OK] Ports 8420, 8421, and 5173 are clear.
exit /b 0
