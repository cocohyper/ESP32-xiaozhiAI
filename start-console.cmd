@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 backend\console\server.py --host 127.0.0.1 --port 8004
) else (
  python backend\console\server.py --host 127.0.0.1 --port 8004
)
echo.
echo Console stopped. Python 3.10 or later is required.
echo Open http://127.0.0.1:8004 while the service is running.
pause
