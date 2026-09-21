@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 start_rasam.py
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python start_rasam.py
  goto finished
)
echo Python 3 is needed to start a localhost server.
echo You can also open Rasam.html directly without installing anything.
:finished
pause
