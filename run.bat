@echo off
echo ====================================
echo   Clone TTS Server
echo ====================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+.
    pause
    exit /b 1
)

REM Check if Node.js is available for frontend
node --version >nul 2>&1
if errorlevel 1 (
    echo WARNING: Node.js not found. Frontend will not start.
    echo Install Node.js from https://nodejs.org/
    echo.
)

REM Install Python dependencies if needed
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

REM Install frontend dependencies if needed
if exist "frontend\package.json" (
    if not exist "frontend\node_modules" (
        echo Installing frontend dependencies...
        cd frontend
        call npm install
        cd ..
    )
)

echo.
echo Starting servers...
echo   Backend API: http://localhost:8090
echo   Frontend:    http://localhost:3000
echo   Admin:       http://localhost:8090/admin/
echo.

REM Start backend in current window
start "Clone TTS Backend" cmd /c "cd /d %CD% && .venv\Scripts\python run.py"

REM Start frontend in new window (if Node.js available)
if exist "frontend\node_modules" (
    start "Clone TTS Frontend" cmd /c "cd /d %CD%\frontend && npm run dev"
)

echo Both servers starting in separate windows.
echo.
echo   Backend: http://localhost:8090
echo   Frontend: http://localhost:3000
echo.
pause
