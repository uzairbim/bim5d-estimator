@echo off
REM BIM 5D Estimator - double-click to start. Needs Python 3.10+ (python.org, tick "Add to PATH").
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo First start: installing, this takes a few minutes...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
echo Starting BIM 5D Estimator on http://localhost:8000  (close this window to stop)
start "" http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn server:app --port 8000
pause
