@echo off
for /f "tokens=2" %%i in ('tasklist /v /fo csv ^| findstr /i "Kochmon API"') do (
  taskkill /PID %%~i /F >nul 2>&1
)
for /f "tokens=2" %%i in ('tasklist /v /fo csv ^| findstr /i "Kochmon Frontend"') do (
  taskkill /PID %%~i /F >nul 2>&1
)

echo API and frontend stopped.
