@echo off
cd /d "%~dp0"
title ReRe Launcher

:: If not admin, re-launch this script elevated (UAC prompt). Current window then exits.
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo Starting ReRe...
echo.
:: Use py launcher (usually in system PATH when elevated); fallback to python
py -m src.main 2>&1
if %errorLevel% neq 0 (
    echo.
    echo If you see "py is not recognized", try: python -m src.main
    python -m src.main 2>&1
)
echo.
echo ReRe closed. Press any key to close this window.
pause >nul
