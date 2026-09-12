@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."

set "MODE=%~1"
if "%MODE%"=="" set "MODE=live"
if not "%~2"=="" set "PUBLIC_HOST=%~2"
if not defined TASK_BACKEND set "TASK_BACKEND=local"
if /I not "%MODE%"=="live" goto usage
if /I not "%TASK_BACKEND%"=="local" if /I not "%TASK_BACKEND%"=="cloud" goto usage
if /I "%TASK_BACKEND%"=="cloud" if not defined YOUBIKE_AWS_PROFILE (
  echo Cloud mode requires YOUBIKE_AWS_PROFILE to be explicitly set.
  exit /b 2
)
if /I "%TASK_BACKEND%"=="cloud" if not defined YOUBIKE_AWS_REGION set "YOUBIKE_AWS_REGION=us-west-2"
if /I "%TASK_BACKEND%"=="cloud" if /I not "%YOUBIKE_AWS_REGION%"=="us-west-2" (
  echo YouBike cloud resources require YOUBIKE_AWS_REGION=us-west-2.
  exit /b 2
)

set "STATE_DIR=%LOCALAPPDATA%\NTPCYouBikeVenue"
set "VENV_DIR=%STATE_DIR%\venv"
set "CREDENTIAL_FILE=%STATE_DIR%\credentials\blackbox.token"
set "REGISTRY_DIR=%STATE_DIR%\registry"
if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Run INSTALL_AND_RUN_WINDOWS.cmd first to create the runtime.
  exit /b 2
)
set "PYTHONDONTWRITEBYTECODE=1"

if defined PUBLIC_TASK_BASE_URL goto url_ready
if /I "%TASK_BACKEND%"=="cloud" (
  echo Cloud mode requires PUBLIC_TASK_BASE_URL set to the deployed AWS HTTPS base URL.
  exit /b 2
)
if defined PUBLIC_HOST goto host_ready
set "LAN_ADDRESS="
for /f "delims=" %%I in ('powershell.exe -NoProfile -NonInteractive -Command "$ErrorActionPreference = 'Stop'; try { $ips = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notmatch '^(127\.|169\.254\.|0\.)' -and $_.IPAddress -ne '255.255.255.255' } | Select-Object -ExpandProperty IPAddress | Sort-Object -Unique); if ($ips.Count -ne 1) { [Console]::Error.WriteLine('LAN detection requires exactly one IPv4 address. Candidates: ' + ($ips -join ', ') + '. Pass a LAN-IP or set PUBLIC_TASK_BASE_URL explicitly.'); exit 2 }; $ips[0] } catch { [Console]::Error.WriteLine('LAN detection failed. Pass a LAN-IP or set PUBLIC_TASK_BASE_URL explicitly.'); exit 2 }"') do set "LAN_ADDRESS=%%I"
if not defined LAN_ADDRESS (
  echo No unique LAN IPv4 address selected. Startup stopped; no localhost QR was generated.
  exit /b 2
)
set "PUBLIC_HOST=%LAN_ADDRESS%"

:host_ready
set "PUBLIC_TASK_BASE_URL=http://%PUBLIC_HOST%:8084"

:url_ready
if not defined YOUBIKE_BLACKBOX_CREDENTIAL_FILE set "YOUBIKE_BLACKBOX_CREDENTIAL_FILE=%CREDENTIAL_FILE%"
if not exist "%YOUBIKE_BLACKBOX_CREDENTIAL_FILE%" (
  echo Live mode credential file is missing. Configure YOUBIKE_BLACKBOX_CREDENTIAL_FILE.
  exit /b 2
)
if not defined YOUBIKE_BLACKBOX_REGISTRY_DIR set "YOUBIKE_BLACKBOX_REGISTRY_DIR=%REGISTRY_DIR%"
if not defined YOUBIKE_BLACKBOX_URL set "YOUBIKE_BLACKBOX_URL=http://127.0.0.1:8782/api/v1/dispatch/evaluate"

echo Task backend: %TASK_BACKEND%
echo QR worker service: http://localhost:8084/tasks/TASK_ID
if /I "%TASK_BACKEND%"=="cloud" goto cloud_runtime
set "TASK_DB=%STATE_DIR%\data\sqlite\task-ledger.sqlite3"
"%VENV_DIR%\Scripts\python.exe" public_shell\serve_public_blackbox_gateway.py --bind 0.0.0.0 --port 8084 --directory . --task-backend local --task-db "%TASK_DB%" --public-task-base-url "%PUBLIC_TASK_BASE_URL%"
exit /b %errorlevel%

:cloud_runtime
"%VENV_DIR%\Scripts\python.exe" public_shell\serve_public_blackbox_gateway.py --bind 0.0.0.0 --port 8084 --directory . --task-backend cloud --aws-profile "%YOUBIKE_AWS_PROFILE%" --aws-region "%YOUBIKE_AWS_REGION%" --public-task-base-url "%PUBLIC_TASK_BASE_URL%"
exit /b %errorlevel%

:usage
echo Usage: start_windows.cmd live [LAN-IP]
echo TASK_BACKEND must be local or cloud. PUBLIC_TASK_BASE_URL overrides LAN-IP detection.
echo Cloud mode also requires explicit YOUBIKE_AWS_PROFILE and uses YOUBIKE_AWS_REGION=us-west-2.
exit /b 2
