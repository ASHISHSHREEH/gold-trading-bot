@echo off
setlocal EnableDelayedExpansion
title Gold Trading Bot Launcher

:: ════════════════════════════════════════════════════════════════════════
::  CONFIGURATION  — edit these if paths change
:: ════════════════════════════════════════════════════════════════════════
set PROJECT=D:\My projects\gold-trading-bot
set MT5_EXE=C:\Program Files\FxPro MetaTrader 5\terminal64.exe
set PYTHON=python
set LOGFILE=%PROJECT%\logs\startup.log

:: Optional: uncomment if using a virtual environment
:: call "%PROJECT%\venv\Scripts\activate.bat"

:: ════════════════════════════════════════════════════════════════════════
::  STARTUP SEQUENCE
:: ════════════════════════════════════════════════════════════════════════

call :log "========================================"
call :log "Bot launcher started"
call :log "========================================"

:: ── 1. MetaTrader 5 ─────────────────────────────────────────────────────────
if not exist "%MT5_EXE%" (
    call :log "ERROR: MT5 not found at %MT5_EXE%"
    call :log "Update MT5_EXE in start_bot.bat and retry."
    pause
    exit /b 1
)

tasklist /fi "IMAGENAME eq terminal64.exe" 2>nul | find /i "terminal64.exe" >nul 2>&1
if errorlevel 1 (
    call :log "Starting MetaTrader 5 (minimized)..."
    start /min "" "%MT5_EXE%"
    :: Give MT5 time to connect to broker before the bot tries to attach
    timeout /t 20 /nobreak >nul
    call :log "MT5 started, waiting 20s for broker connection..."
) else (
    call :log "MetaTrader 5 already running — skipping"
)

:: ── 2. Dashboard (Flask, port 5000) ─────────────────────────────────────────
netstat -an 2>nul | find ":5000 " | find "LISTENING" >nul 2>&1
if errorlevel 1 (
    call :log "Starting dashboard on http://localhost:5000"
    start "Trading Dashboard" /D "%PROJECT%" cmd /k "%PYTHON% dashboard.py"
    timeout /t 4 /nobreak >nul
) else (
    call :log "Dashboard already running on port 5000 — skipping"
)

:: ── 3. Trading Bot ───────────────────────────────────────────────────────────
::  Runs in THIS process so the bat exits only when the bot exits.
::  Task Scheduler sees a non-zero exit code on crash and auto-restarts.
call :log "Starting main_mt5.py..."
cd /d "%PROJECT%"
%PYTHON% main_mt5.py
set /a EXIT_CODE=!ERRORLEVEL!

call :log "Bot exited (code !EXIT_CODE!) — Task Scheduler will restart in 60s"
exit /b !EXIT_CODE!

:: ════════════════════════════════════════════════════════════════════════
::  LOG HELPER
:: ════════════════════════════════════════════════════════════════════════
:log
echo [%date% %time%] %~1
echo [%date% %time%] %~1 >> "%LOGFILE%"
exit /b 0
