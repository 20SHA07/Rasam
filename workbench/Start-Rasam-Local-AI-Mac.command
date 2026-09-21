#!/bin/sh
cd "$(dirname "$0")" || exit 1
# This applies to child processes, not an already-running Ollama app.
export OLLAMA_NO_CLOUD=1
printf '%s\n' 'Open Ollama first. This launcher uses your downloaded local model with no API key.'
if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python start_rasam.py --provider ollama
fi
if command -v python3.11 >/dev/null 2>&1; then
  python3.11 start_rasam.py --provider ollama
elif command -v python3 >/dev/null 2>&1; then
  python3 start_rasam.py --provider ollama
else
  printf '%s\n' 'Install 64-bit Python 3.11 from https://www.python.org/downloads/ and try again.'
  printf '%s\n' 'You can open Rasam.html directly for manual entry while setting up.'
fi
printf 'Press Enter to close. '
read -r rasam_response
