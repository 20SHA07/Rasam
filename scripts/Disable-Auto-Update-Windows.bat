@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
echo Removing automatic GitHub updates for this Rasam folder...
if exist "..\workbench\.venv\Scripts\python.exe" (
  "..\workbench\.venv\Scripts\python.exe" manage_auto_updates.py disable
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 --version >nul 2>nul
  if not errorlevel 1 (
    py -3.11 manage_auto_updates.py disable
    goto finished
  )
  py -3 manage_auto_updates.py disable
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python manage_auto_updates.py disable
  goto finished
)
echo Install Python 3.11 to use this launcher.
echo Alternatively, remove the Rasam-GitHub-Update task for this folder in Windows Task Scheduler.
:finished
echo.
pause
