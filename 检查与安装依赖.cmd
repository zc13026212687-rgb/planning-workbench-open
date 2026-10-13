@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\Setup.ps1"
echo.
echo To install project dependencies and build missing artifacts:
echo powershell -NoProfile -ExecutionPolicy Bypass -File desktop\Setup.ps1 -Install
pause
