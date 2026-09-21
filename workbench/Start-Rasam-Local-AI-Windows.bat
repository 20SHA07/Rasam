@echo off
setlocal
cd /d "%~dp0"
rem This applies to child processes, not an already-running Ollama app.
set "OLLAMA_NO_CLOUD=1"
echo Open Ollama first. This launcher uses your downloaded local model with no API key.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" start_rasam.py --provider ollama
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 --version >nul 2>nul
  if not errorlevel 1 (
    py -3.11 start_rasam.py --provider ollama
    goto finished
  )
  py -3 start_rasam.py --provider ollama
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python start_rasam.py --provider ollama
  goto finished
)
echo Install 64-bit Python 3.11 from https://www.python.org/downloads/ and try again.
echo You can open Rasam.html directly for manual entry while setting up.
:finished
pause
