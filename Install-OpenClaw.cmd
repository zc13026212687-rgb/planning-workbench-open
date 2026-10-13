@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\Install.ps1" -Client openclaw %*
set "QINGGUI_EXIT=%ERRORLEVEL%"
echo.
echo Setup exit code: %QINGGUI_EXIT%
pause
exit /b %QINGGUI_EXIT%
