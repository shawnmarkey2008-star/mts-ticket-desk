@echo off
cd /d "%~dp0"
set "MTS_HOST=127.0.0.1"
where py >nul 2>&1
if errorlevel 1 (
  python server.py
) else (
  py -3 server.py
)
pause
