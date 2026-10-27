@echo off
SETLOCAL
cd /d "%~dp0"

start "Kochmon API" cmd /k "cd /d ""c:\Users\Motionweb\Downloads\booking_ai_events_renewal_tavily\booking_ai"" && python main.py"
start "Kochmon Frontend" cmd /k "cd /d ""c:\Users\Motionweb\Downloads\kochmon-frontend (2)\kochmon-frontend"" && npm run dev -- --host 0.0.0.0"

echo.
echo Starting API and frontend...
choice /T 10 /D Y /N >nul
curl.exe -sS -o NUL -w "API HTTP %{http_code}\n" http://localhost:8000/docs
curl.exe -sS -o NUL -w "FRONT HTTP %{http_code}\n" http://localhost:5173
ENDLOCAL
