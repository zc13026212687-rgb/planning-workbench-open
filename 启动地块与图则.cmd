@echo off
setlocal
start "" powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0desktop\LaunchRegulatory.ps1"
exit /b 0
