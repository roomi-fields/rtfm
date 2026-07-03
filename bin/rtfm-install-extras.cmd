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
) else if /i "%EXTRA%"=="epub" (
    echo Installing EPUB extras ^(ebooklib + beautifulsoup4, ~5 MB^) ...
    "%PIP%" install --quiet --upgrade ebooklib beautifulsoup4
) else if /i "%EXTRA%"=="office" (
    echo Installing office extras ^(python-docx + odfpy + striprtf, ~2 MB^) ...
    "%PIP%" install --quiet --upgrade python-docx odfpy striprtf
) else if /i "%EXTRA%"=="mobi" (
    echo Installing MOBI extras ^(mobi + beautifulsoup4, ~2 MB^) ...
    "%PIP%" install --quiet --upgrade mobi beautifulsoup4
) else if /i "%EXTRA%"=="ocr" (
    echo Installing OCR extras ^(pytesseract + pypdfium2 + Pillow, ~30 MB^) ...
    echo   Needs the tesseract binary on the host.
    "%PIP%" install --quiet --upgrade pytesseract pypdfium2 Pillow
) else if /i "%EXTRA%"=="xlsx" (
    echo Installing XLSX extras ^(openpyxl, ~1 MB^) ...
    "%PIP%" install --quiet --upgrade openpyxl
) else if /i "%EXTRA%"=="all" (
    echo Installing everything except pdf-full ^(~130 MB^) ...
    echo   For marker-pdf ^(heavy, ~1.5 GB with CPU torch^), run 'pdf-full' separately.
    "%PIP%" install --quiet --upgrade fastembed pdftext ebooklib beautifulsoup4 python-docx odfpy striprtf mobi pytesseract pypdfium2 Pillow openpyxl
) else (
    echo Unknown extra: %EXTRA% ^(expected: embeddings, pdf, pdf-full, epub, office, mobi, ocr, xlsx, all^) 1>&2
    exit /b 1
)

if errorlevel 1 (
    echo Install failed 1>&2
    exit /b 1
)
echo Done. Restart Claude Code for the new extras to be picked up.
exit /b 0
