@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create the environment first: python -m venv .venv
  echo Then install: .venv\Scripts\python.exe -m pip install -r requirements.lock
  pause
  exit /b 1
)
echo Incident Atlas: http://127.0.0.1:8765
echo Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m incident_atlas
pause
