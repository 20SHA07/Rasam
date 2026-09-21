#!/bin/sh
cd "$(dirname "$0")" || exit 1
if command -v python3.11 >/dev/null 2>&1; then
  python3.11 setup_ocr.py 
elif command -v python3 >/dev/null 2>&1; then
  python3 setup_ocr.py 
else
  printf '%s\n' 'Install 64-bit Python 3.11 from https://www.python.org/downloads/ and try again.'
  printf '%s\n' 'You can open Rasam.html directly for manual entry while setting up.'
fi
printf 'Press Enter to close. '
read -r rasam_response
