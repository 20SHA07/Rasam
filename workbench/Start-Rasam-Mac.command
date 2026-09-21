#!/bin/sh
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 start_rasam.py
else
  printf '%s\n' 'Python 3 is needed to start a localhost server.' 'You can also open Rasam.html directly without installing anything.'
  printf 'Press Enter to close. '
  read -r rasam_response
fi
