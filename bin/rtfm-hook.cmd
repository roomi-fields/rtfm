@echo off
REM Windows launcher for RTFM plugin hooks.
REM Usage: rtfm-hook.cmd <hook-script-basename>

setlocal
set "PLUGIN_ROOT=%~dp0.."
set "SCRIPT=%PLUGIN_ROOT%\hooks\%1.py"
shift

if not exist "%SCRIPT%" (
    echo rtfm-hook: script not found: %SCRIPT% 1>&2
    exit /b 1
)

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    py -3 "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

echo rtfm-hook: Python 3.10+ not found on PATH 1>&2
exit /b 1
