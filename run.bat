@echo off
REM =====================================================================
REM  Bank Reconciliation - one-click launcher
REM  Starts the backend API and the frontend UI, then opens the browser.
REM  Run it by double-clicking this file, or typing  run.bat  in a terminal.
REM =====================================================================

echo.
echo   Starting Bank Reconciliation...
echo.

REM --- 1) Backend API (FastAPI) on http://localhost:8765 -----------------
REM     Port 8765 MUST match the Vite proxy target in frontend/vite.config.ts.
REM     (Windows/Hyper-V often reserves 8000/8001, so the app standardised on 8765.)
start "Bank Recon - Backend (API)" cmd /k "py -3.13 -m uvicorn api.main:app --reload --port 8765"

REM give the API a few seconds to boot before the UI starts calling it
timeout /t 4 >nul

REM --- 2) Frontend UI (React/Vite) on http://localhost:5173 --------------
REM    first run installs npm packages automatically, then starts the UI
start "Bank Recon - Frontend (UI)" cmd /k "cd frontend && (if not exist node_modules npm install) && npm run dev"

REM give the UI a few seconds, then open it in the default browser
timeout /t 6 >nul
start "" http://localhost:5173

echo.
echo   Backend : http://localhost:8765
echo   Frontend: http://localhost:5173   (opening in your browser now)
echo.
echo   Two windows opened - one for the API, one for the UI.
echo   To stop the app, just close those two windows.
echo.
pause
