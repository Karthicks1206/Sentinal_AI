@echo off
setlocal EnableDelayedExpansion
title Sentinel AI - Remote Client
:: Keep window open on any error
if "%1"=="" (
    cmd /k "%~f0" RUNNING
    exit /b
)

echo ================================================================
echo   SENTINEL AI - Remote Client Auto-Setup
echo ================================================================
echo.

:: ── Step 1: Open Windows Firewall ────────────────────────────────────
echo [1/5] Configuring Windows Firewall...
netsh advfirewall firewall delete rule name="SentinelAI" >nul 2>&1
netsh advfirewall firewall add rule name="SentinelAI" dir=out action=allow protocol=TCP remoteport=5001 >nul 2>&1
netsh advfirewall firewall add rule name="SentinelAI-UDP" dir=in action=allow protocol=UDP localport=47474 >nul 2>&1
netsh advfirewall firewall add rule name="SentinelAI-UDP-out" dir=out action=allow protocol=UDP remoteport=47474 >nul 2>&1
echo       Firewall rules set.

:: ── Step 2: Check Python ─────────────────────────────────────────────
echo [2/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo       Python not found. Installing via winget...
    winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo       ERROR: Could not auto-install Python.
        echo       Please install from: https://www.python.org/downloads/
        echo       Check "Add Python to PATH" during install.
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo       Found: %%i

:: ── Step 3: Install dependencies ─────────────────────────────────────
echo [3/5] Installing dependencies (psutil, requests)...
python -m pip install --quiet --upgrade psutil requests 2>&1 | find /v "already"
echo       Dependencies ready.

:: ── Step 4: Find sentinel_client.py ──────────────────────────────────
echo [4/5] Locating sentinel_client.py...
set "CLIENT="
set "LAUNCHER="

if exist "%~dp0sentinel_client.py"       set "CLIENT=%~dp0sentinel_client.py"
if exist "%~dp0sentinel_launcher.py"     set "LAUNCHER=%~dp0sentinel_launcher.py"

if not defined CLIENT if exist "%~dp0..\sentinel_client.py"  set "CLIENT=%~dp0..\sentinel_client.py"
if not defined LAUNCHER if exist "%~dp0..\sentinel_launcher.py" set "LAUNCHER=%~dp0..\sentinel_launcher.py"

if not defined CLIENT if exist "%USERPROFILE%\OneDrive\Desktop\Sentinal_AI\sentinel_ai\sentinel_client.py"  set "CLIENT=%USERPROFILE%\OneDrive\Desktop\Sentinal_AI\sentinel_ai\sentinel_client.py"
if not defined LAUNCHER if exist "%USERPROFILE%\OneDrive\Desktop\Sentinal_AI\sentinel_ai\sentinel_launcher.py" set "LAUNCHER=%USERPROFILE%\OneDrive\Desktop\Sentinal_AI\sentinel_ai\sentinel_launcher.py"

if not defined CLIENT if exist "%USERPROFILE%\Desktop\Sentinal_AI\sentinel_ai\sentinel_client.py"  set "CLIENT=%USERPROFILE%\Desktop\Sentinal_AI\sentinel_ai\sentinel_client.py"
if not defined LAUNCHER if exist "%USERPROFILE%\Desktop\Sentinal_AI\sentinel_ai\sentinel_launcher.py" set "LAUNCHER=%USERPROFILE%\Desktop\Sentinal_AI\sentinel_ai\sentinel_launcher.py"

if not defined CLIENT (
    echo.
    echo       ERROR: sentinel_client.py not found.
    echo       Please run: git pull
    pause
    exit /b 1
)
if not defined LAUNCHER (
    echo.
    echo       ERROR: sentinel_launcher.py not found.
    echo       Please run: git pull
    pause
    exit /b 1
)
echo       Found client:   %CLIENT%
echo       Found launcher: %LAUNCHER%

:: ── Step 5: Discover hub and launch ──────────────────────────────────
echo [5/5] Finding Sentinel hub...
echo.

set "SAVED_HUB=%~dp0.sentinel_hub"
python "%LAUNCHER%" "%CLIENT%" "%SAVED_HUB%"

if errorlevel 1 (
    echo.
    echo ERROR: Failed to start. See above for details.
    pause
)
