@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=live"
if not "%~2"=="" set "PUBLIC_HOST=%~2"

set "STATE_DIR=%LOCALAPPDATA%\NTPCYouBikeVenue"
set "VENV_DIR=%STATE_DIR%\venv"
set "PYTHON_CMD="

where py >nul 2>&1
if errorlevel 1 goto try_python_path
call :try_python 3.13
if defined PYTHON_CMD goto python_ready
call :try_python 3.12
if defined PYTHON_CMD goto python_ready
call :try_python 3.11
if defined PYTHON_CMD goto python_ready

:try_python_path
where python >nul 2>&1
if errorlevel 1 goto python_ready
python -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"

:python_ready
if "%PYTHON_CMD%"=="" (
  echo Python 3.11, 3.12 or 3.13 is required.
  echo Install Python, enable Add Python to PATH, then run this file again.
  exit /b 2
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  %PYTHON_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b 3
)
"%VENV_DIR%\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Existing runtime is not Python 3.11, 3.12 or 3.13. Recreate the external runtime directory and run again.
  exit /b 3
)

if exist "wheelhouse\qrcode-8.2-py3-none-any.whl" (
  "%VENV_DIR%\Scripts\python.exe" -m pip install --disable-pip-version-check --no-index --find-links wheelhouse -r requirements.txt
) else (
  "%VENV_DIR%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
)
if errorlevel 1 exit /b 4

if not exist "%STATE_DIR%\logs" mkdir "%STATE_DIR%\logs" >nul 2>&1

call public_shell\smoke_windows.cmd
if errorlevel 1 exit /b 5

echo Starting %MODE% mode. The launcher will validate the task URL.
if /I "%TASK_BACKEND%"=="cloud" echo Cloud runtime will require explicit YOUBIKE_AWS_PROFILE and YOUBIKE_AWS_REGION=us-west-2.
call public_shell\start_windows.cmd "%MODE%" "%PUBLIC_HOST%"
exit /b %errorlevel%

:try_python
py -%~1 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -%~1"
exit /b 0
