@echo off
setlocal
cd /d "%~dp0.."

set "MODE=%~1"
if "%MODE%"=="" set "MODE=live"
set "PUBLIC_HOST=%~2"
if "%PUBLIC_HOST%"=="" set "PUBLIC_HOST=127.0.0.1"

set "RUNTIME_DIR=%LOCALAPPDATA%\ntpc-youbike-demo"
set "VENV_DIR=%RUNTIME_DIR%\venv"
set "TASK_DB=%RUNTIME_DIR%\task-ledger.sqlite3"
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

if not exist "%VENV_DIR%\Scripts\python.exe" (
  py -3 -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b 1
)
"%VENV_DIR%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 exit /b 1

if /I "%MODE%"=="offline" (
  "%VENV_DIR%\Scripts\python.exe" public_shell\serve_public_blackbox_gateway.py --bind 0.0.0.0 --port 8084 --directory . --task-db "%TASK_DB%" --public-base-url "http://%PUBLIC_HOST%:8084" --offline-fixture fixtures\sealed_demo_result_v1.json
  exit /b %errorlevel%
)

if /I not "%MODE%"=="live" (
  echo Usage: start_windows.cmd live^|offline [LAN-IP]
  exit /b 2
)
if "%YOUBIKE_BLACKBOX_CREDENTIAL_FILE%"=="" (
  echo YOUBIKE_BLACKBOX_CREDENTIAL_FILE is required in live mode.
  exit /b 2
)
"%VENV_DIR%\Scripts\python.exe" public_shell\serve_public_blackbox_gateway.py --bind 0.0.0.0 --port 8084 --directory . --task-db "%TASK_DB%" --public-base-url "http://%PUBLIC_HOST%:8084"
