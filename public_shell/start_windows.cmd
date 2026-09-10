@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "MODE=%~1"
if "%MODE%"=="" set "MODE=live"
set "PUBLIC_HOST=%~2"
if "%PUBLIC_HOST%"=="" set "PUBLIC_HOST=127.0.0.1"

set "STATE_DIR=%LOCALAPPDATA%\NTPCYouBikeVenue"
set "VENV_DIR=%STATE_DIR%\venv"
set "TASK_DB=%STATE_DIR%\data\sqlite\task-ledger.sqlite3"
set "CREDENTIAL_FILE=%STATE_DIR%\credentials\blackbox.token"
set "REGISTRY_DIR=%STATE_DIR%\registry"
if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Run ..\INSTALL_AND_RUN_WINDOWS.cmd first to create the offline runtime.
  exit /b 2
)
if not exist "%STATE_DIR%\data\sqlite" mkdir "%STATE_DIR%\data\sqlite" >nul 2>&1
set "PYTHONDONTWRITEBYTECODE=1"

if /I "%MODE%"=="offline" (
  "%VENV_DIR%\Scripts\python.exe" public_shell\serve_public_blackbox_gateway.py --bind 0.0.0.0 --port 8084 --directory . --task-db "%TASK_DB%" --public-base-url "http://%PUBLIC_HOST%:8084" --offline-fixture fixtures\sealed.json
  exit /b %errorlevel%
)

if /I not "%MODE%"=="live" (
  echo Usage: start_windows.cmd live^|offline [LAN-IP]
  exit /b 2
)
if "%YOUBIKE_BLACKBOX_CREDENTIAL_FILE%"=="" set "YOUBIKE_BLACKBOX_CREDENTIAL_FILE=%CREDENTIAL_FILE%"
if not exist "%YOUBIKE_BLACKBOX_CREDENTIAL_FILE%" (
  echo Run ..\INSTALL_AND_RUN_WINDOWS.cmd first to issue the local credential.
  exit /b 2
)
set "YOUBIKE_BLACKBOX_REGISTRY_DIR=%REGISTRY_DIR%"
set "YOUBIKE_BLACKBOX_URL=http://127.0.0.1:8781/api/v1/dispatch/evaluate"
"%VENV_DIR%\Scripts\python.exe" public_shell\serve_public_blackbox_gateway.py --bind 0.0.0.0 --port 8084 --directory . --task-db "%TASK_DB%" --public-base-url "http://%PUBLIC_HOST%:8084"
exit /b %errorlevel%
