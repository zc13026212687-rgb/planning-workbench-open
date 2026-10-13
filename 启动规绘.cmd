@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0desktop\publish\PlanningStudio.exe" (
  start "Planning Studio" "%~dp0desktop\publish\PlanningStudio.exe"
  exit /b 0
)
echo Desktop executable missing. Run the dependency setup entry first.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\Setup.ps1"
pause
