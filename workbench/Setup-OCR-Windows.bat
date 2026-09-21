@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 --version >nul 2>nul
  if not errorlevel 1 (
    py -3.11 setup_ocr.py 
    goto finished
  )
  py -3 setup_ocr.py 
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python setup_ocr.py 
  goto finished
)
echo Install 64-bit Python 3.11 from https://www.python.org/downloads/ and try again.
echo You can open Rasam.html directly for manual entry while setting up.
:finished
pause
