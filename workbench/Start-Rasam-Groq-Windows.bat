@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" start_rasam.py --provider groq
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 --version >nul 2>nul
  if not errorlevel 1 (
    py -3.11 start_rasam.py --provider groq
    goto finished
  )
  py -3 start_rasam.py --provider groq
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python start_rasam.py --provider groq
  goto finished
)
echo Install 64-bit Python 3.11 from https://www.python.org/downloads/ and try again.
echo You can open Rasam.html directly for manual entry while setting up.
:finished
pause
