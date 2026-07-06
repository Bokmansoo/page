@echo off
setlocal

REM Run the validated PowerShell backend launcher from CMD.
REM Any arguments, for example -Port 8001, are forwarded unchanged.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_backend.ps1" %*
exit /b %ERRORLEVEL%
