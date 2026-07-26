@echo off
chcp 65001 >nul
title SSP Video Studio

cd /d "%~dp0"

echo.
echo   ========================================
echo     SSP Video Studio v2.0
echo     AI运动科学科普视频本地生产平台
echo   ========================================
echo.

REM Check/create venv
if not exist "venv\Scripts\python.exe" (
    echo   [SETUP] Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    python -m pip install flask flask-cors sqlalchemy pillow --quiet
) else (
    call venv\Scripts\activate.bat
)

REM Ensure deps
python -m pip install flask flask-cors sqlalchemy pillow --quiet 2>nul

echo   [OK] Environment ready
echo   [OK] Starting server at http://127.0.0.1:5199
echo.
echo   Press Ctrl+C to stop
echo   ========================================
echo.

python -m backend.app

pause
