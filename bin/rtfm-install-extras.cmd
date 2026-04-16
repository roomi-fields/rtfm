@echo off
REM Install RTFM optional extras into an isolated venv at
REM %CLAUDE_PLUGIN_DATA%\extras\venv\.

setlocal
set "EXTRA=%~1"
if "%EXTRA%"=="" set "EXTRA=all"

if defined CLAUDE_PLUGIN_DATA (
    set "DATA_DIR=%CLAUDE_PLUGIN_DATA%"
) else (
    set "DATA_DIR=%USERPROFILE%\.claude\plugins\data\rtfm"
)
if not exist "%DATA_DIR%\extras" mkdir "%DATA_DIR%\extras"
set "VENV=%DATA_DIR%\extras\venv"

set "BASE_PY="
where python >nul 2>&1 && set "BASE_PY=python"
if not defined BASE_PY where py >nul 2>&1 && set "BASE_PY=py -3"

if not defined BASE_PY (
    echo rtfm-install-extras: Python 3.10+ not found on PATH 1>&2
    exit /b 1
)

if not exist "%VENV%" (
    echo Creating extras venv at %VENV% ...
    %BASE_PY% -m venv "%VENV%"
    if errorlevel 1 (
        echo rtfm-install-extras: failed to create venv 1>&2
        exit /b 1
    )
)

set "PIP=%VENV%\Scripts\pip.exe"

set "TORCH_CPU_INDEX=https://download.pytorch.org/whl/cpu"

if /i "%EXTRA%"=="embeddings" (
    echo Installing embeddings extra ^(fastembed, ~85 MB^) ...
    "%PIP%" install --quiet --upgrade fastembed
) else if /i "%EXTRA%"=="pdf" (
    echo Installing PDF extras ^(pdftext only, ~50 MB^) ...
    echo   For complex layouts ^(tables, figures, scans^), run 'pdf-full' instead.
    "%PIP%" install --quiet --upgrade pdftext
) else if /i "%EXTRA%"=="pdf-full" (
    echo Installing full PDF extras ^(pdftext + marker-pdf + CPU-only torch, ~1.5 GB^) ...
    "%PIP%" install --quiet --upgrade --index-url "%TORCH_CPU_INDEX%" torch
    "%PIP%" install --quiet --upgrade pdftext marker-pdf
) else if /i "%EXTRA%"=="all" (
    echo Installing embeddings + light PDF ^(fastembed + pdftext, ~135 MB^) ...
    echo   For marker-pdf ^(heavy, ~1.5 GB with CPU torch^), run 'pdf-full' separately.
    "%PIP%" install --quiet --upgrade fastembed pdftext
) else (
    echo Unknown extra: %EXTRA% ^(expected: embeddings, pdf, pdf-full, all^) 1>&2
    exit /b 1
)

if errorlevel 1 (
    echo Install failed 1>&2
    exit /b 1
)
echo Done. Restart Claude Code for the new extras to be picked up.
exit /b 0
