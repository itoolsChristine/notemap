@echo off
title Notemap Install
color 0F

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set EXITCODE=%errorlevel%
echo.
pause
exit /b %EXITCODE%
