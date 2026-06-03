@echo off
echo ====================================
echo   Colab Worker TTS Server
echo ====================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+.
    pause
    exit /b 1
)

REM Install dependencies if needed
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo Installing dependencies...
    pip install -r requirements.txt
    echo Installing Playwright browsers...
    playwright install chromium
) else (
    call .venv\Scripts\activate.bat
)

echo.
echo Starting server on http://localhost:8001
echo Dashboard: http://localhost:8001/
echo.
python run.py

pause
