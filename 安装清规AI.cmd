@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\InstallQingGui.ps1" %*
set "qinggui_exit=%errorlevel%"
echo.
if not "%qinggui_exit%"=="0" echo Setup is incomplete. Read the message above before retrying.
pause
exit /b %qinggui_exit%
