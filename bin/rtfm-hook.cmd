@echo off
REM Windows launcher for RTFM plugin hooks.
REM Usage: rtfm-hook.cmd <hook-script-basename>
REM Exposes the extras venv via PYTHONPATH so hook code can import
REM optional parsers (pdftext, ebooklib, openpyxl, ...) and fastembed.

setlocal
set "PLUGIN_ROOT=%~dp0.."
set "SCRIPT=%PLUGIN_ROOT%\hooks\%1.py"
shift

if not exist "%SCRIPT%" (
    echo rtfm-hook: script not found: %SCRIPT% 1>&2
    exit /b 1
)

if defined CLAUDE_PLUGIN_DATA (
    set "EXTRAS_DIR=%CLAUDE_PLUGIN_DATA%\extras\venv"
) else (
    set "EXTRAS_DIR=%USERPROFILE%\.claude\plugins\data\rtfm\extras\venv"
)
set "EXTRAS_SITE=%EXTRAS_DIR%\Lib\site-packages"
if not exist "%EXTRAS_SITE%" set "EXTRAS_SITE="

if defined EXTRAS_SITE (
    if defined PYTHONPATH (
        set "PYTHONPATH=%EXTRAS_SITE%;%PYTHONPATH%"
    ) else (
        set "PYTHONPATH=%EXTRAS_SITE%"
    )
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
