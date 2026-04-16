@echo off
REM Windows launcher for the RTFM MCP server.

setlocal
set "PLUGIN_ROOT=%~dp0.."

if defined CLAUDE_PLUGIN_DATA (
    set "EXTRAS_DIR=%CLAUDE_PLUGIN_DATA%\extras\venv"
) else (
    set "EXTRAS_DIR=%USERPROFILE%\.claude\plugins\data\rtfm\extras\venv"
)
set "EXTRAS_SITE=%EXTRAS_DIR%\Lib\site-packages"
if not exist "%EXTRAS_SITE%" set "EXTRAS_SITE="

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"

if not defined PY (
    echo rtfm-serve: Python 3.10+ not found on PATH 1>&2
    exit /b 1
)

if defined EXTRAS_SITE (
    %PY% -c "import sys; sys.path.insert(0, r'%EXTRAS_SITE%'); sys.path.insert(0, r'%PLUGIN_ROOT%'); from rtfm.mcp import main; main()" %*
) else (
    %PY% -c "import sys; sys.path.insert(0, r'%PLUGIN_ROOT%'); from rtfm.mcp import main; main()" %*
)
exit /b %ERRORLEVEL%
