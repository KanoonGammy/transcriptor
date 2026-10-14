@echo off
title Transcriptor Pro
chcp 65001 > nul
echo ===================================================
echo     Transcriptor Pro - Speech to Text Webapp
echo ===================================================
echo.

if not exist ".venv" (
    echo [INFO] Creating Python virtual environment...
    python -m venv .venv
)

echo [INFO] Activating virtual environment...
call .venv\Scripts\activate.bat

echo [INFO] Installing/Checking requirements...
pip install -r requirements.txt

echo.
if "%PORT%"=="" set PORT=8080
if not "%~1"=="" set PORT=%~1

echo [INFO] Starting Transcriptor Pro server on port %PORT%...
echo [INFO] Open your browser at: http://localhost:%PORT%
echo.
python main.py --port %PORT%
pause
