@echo off
REM Run backend server using global Python

echo ================================================
echo Starting Weed Detection Backend
echo ================================================
echo.
echo Server URL: http://localhost:8000
echo API Docs: http://localhost:8000/docs
echo.
echo Press CTRL+C to stop the server
echo ================================================
echo.

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

pause
