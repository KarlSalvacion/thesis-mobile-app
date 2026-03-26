@echo off
REM Setup script for backend - installs dependencies globally

echo ================================================
echo Weed Detection Backend Setup
echo ================================================
echo.
echo This will install Python packages globally
echo (No virtual environment)
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8 or higher from https://www.python.org/
    pause
    exit /b 1
)

echo Current Python version:
python --version
echo.
echo Installing/Updating dependencies...
echo.

python -m pip install --upgrade pip
pip install -r backend\requirements.txt

echo.
echo ================================================
echo Setup Complete!
echo ================================================
echo.
echo To start the backend server, run:
echo   run-backend.bat
echo.
echo Or manually:
echo   python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
echo.
pause
