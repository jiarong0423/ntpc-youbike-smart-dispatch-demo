@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=offline"
set "PUBLIC_HOST=%~2"
if "%PUBLIC_HOST%"=="" set "PUBLIC_HOST=127.0.0.1"

set "STATE_DIR=%LOCALAPPDATA%\NTPCYouBikeVenue"
set "VENV_DIR=%STATE_DIR%\venv"
set "PYTHON_CMD="

where py >nul 2>&1
if not errorlevel 1 (
  py -3.13 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=py -3.13"
  if "%PYTHON_CMD%"=="" (
    py -3.12 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3.12"
  )
  if "%PYTHON_CMD%"=="" (
    py -3.11 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3.11"
  )
)
if "%PYTHON_CMD%"=="" (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if (3, 11) ^<= sys.version_info[:2] ^<= (3, 13) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
  )
)
if "%PYTHON_CMD%"=="" (
  echo Python 3.11, 3.12 or 3.13 is required.
  echo Install Python, enable Add Python to PATH, then run this file again.
  exit /b 2
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  %PYTHON_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b 3
)
"%VENV_DIR%\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3, 11) ^<= sys.version_info[:2] ^<= (3, 13) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Existing runtime is not Python 3.11, 3.12 or 3.13. Remove %VENV_DIR% and run again.
  exit /b 3
)

if exist "wheelhouse\qrcode-8.2-py3-none-any.whl" (
  "%VENV_DIR%\Scripts\python.exe" -m pip install --disable-pip-version-check --no-index --find-links wheelhouse -r requirements.txt
) else (
  "%VENV_DIR%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
)
if errorlevel 1 exit /b 4

if not exist "%STATE_DIR%\data\sqlite" mkdir "%STATE_DIR%\data\sqlite" >nul 2>&1
if not exist "%STATE_DIR%\logs" mkdir "%STATE_DIR%\logs" >nul 2>&1

call public_shell\smoke_windows.cmd
if errorlevel 1 exit /b 5

if /I "%MODE%"=="live" (
  if "%YOUBIKE_BLACKBOX_CREDENTIAL_FILE%"=="" set "YOUBIKE_BLACKBOX_CREDENTIAL_FILE=%STATE_DIR%\credentials\blackbox.token"
  if not exist "%YOUBIKE_BLACKBOX_CREDENTIAL_FILE%" (
    echo Live mode requires the separate private venue package and a valid short-lived credential.
    exit /b 6
  )
)

echo Starting %MODE% mode at http://%PUBLIC_HOST%:8084
call public_shell\start_windows.cmd "%MODE%" "%PUBLIC_HOST%"
exit /b %errorlevel%
