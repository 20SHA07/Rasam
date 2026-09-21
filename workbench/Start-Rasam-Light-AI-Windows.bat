@echo off
setlocal
cd /d "%~dp0"
set "OLLAMA_MODEL=qwen3:1.7b-q4_K_M"
echo Starting Rasam with the smaller local Qwen3 model.
echo First download it with: ollama pull qwen3:1.7b-q4_K_M
echo This model may make more extraction mistakes. Review every field.
call "%~dp0Start-Rasam-Local-AI-Windows.bat"
