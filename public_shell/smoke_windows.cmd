@echo off
setlocal
cd /d "%~dp0.."
set "VENV_DIR=%LOCALAPPDATA%\ntpc-youbike-demo\venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Run public_shell\start_windows.cmd once to create the runtime.
  exit /b 2
)
"%VENV_DIR%\Scripts\python.exe" -m unittest discover -s tests -v
exit /b %errorlevel%
