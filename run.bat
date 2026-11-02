@echo off
rem Starts Yoru no Toshokan and opens it in the browser a few seconds later.
cd /d "%~dp0"
start "" /min cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5050"
".venv\Scripts\python.exe" app.py
