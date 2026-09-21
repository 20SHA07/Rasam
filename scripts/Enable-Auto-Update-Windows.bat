@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
echo Setting up automatic GitHub updates for this Rasam folder...
if exist "..\workbench\.venv\Scripts\python.exe" (
  "..\workbench\.venv\Scripts\python.exe" manage_auto_updates.py enable
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 --version >nul 2>nul
  if not errorlevel 1 (
    py -3.11 manage_auto_updates.py enable
    goto finished
  )
  py -3 manage_auto_updates.py enable
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python manage_auto_updates.py enable
  goto finished
)
echo Install Python 3.11 and Git for Windows, then try again.
:finished
echo.
pause
