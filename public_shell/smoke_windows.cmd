@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "VENV_DIR=%LOCALAPPDATA%\NTPCYouBikeVenue\venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Run ..\INSTALL_AND_RUN_WINDOWS.cmd first to create the offline runtime.
  exit /b 2
)
set "PYTHONDONTWRITEBYTECODE=1"
"%VENV_DIR%\Scripts\python.exe" -m unittest discover -s tests -v
exit /b %errorlevel%
