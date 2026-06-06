@echo off
REM =====================================================================
REM  Bank Reconciliation - stop everything started by run.bat
REM  Run by double-clicking this file, or typing  stop.bat  in a terminal.
REM =====================================================================

echo.
echo   Stopping Bank Reconciliation...
echo.

REM Backend - the uvicorn reloader and its worker process
taskkill /F /T /IM uvicorn.exe >nul 2>&1

REM Anything still holding the API port (8000)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /F /T /PID %%a >nul 2>&1

REM Frontend dev server (Vite) on port 5173
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr LISTENING') do taskkill /F /T /PID %%a >nul 2>&1

echo   Done - backend and frontend are stopped.
echo.
timeout /t 2 >nul
