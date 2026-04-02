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

:: ── Step 1: Open Windows Firewall for outbound on port 5001 ─────────
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
        echo       Please download and install from: https://www.python.org/downloads/
        echo       Make sure to check "Add Python to PATH" during install.
        pause
        exit /b 1
    )
    :: Refresh PATH
    call refreshenv >nul 2>&1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo       Found: %%i

:: ── Step 3: Install dependencies ────────────────────────────────────
echo [3/5] Installing dependencies (psutil, requests)...
python -m pip install --quiet --upgrade psutil requests 2>&1 | find /v "already"
echo       Dependencies ready.

:: ── Step 4: Find sentinel_client.py ─────────────────────────────────
echo [4/5] Locating sentinel_client.py...
set "CLIENT="

:: Check same folder as this bat file
if exist "%~dp0sentinel_client.py" (
    set "CLIENT=%~dp0sentinel_client.py"
    goto :found_client
)

:: Check parent folder
if exist "%~dp0..\sentinel_client.py" (
    set "CLIENT=%~dp0..\sentinel_client.py"
    goto :found_client
)

:: Search common locations
for %%d in ("%USERPROFILE%\Desktop" "%USERPROFILE%\Downloads" "%USERPROFILE%\Documents") do (
    if exist "%%~d\sentinel_client.py" (
        set "CLIENT=%%~d\sentinel_client.py"
        goto :found_client
    )
    if exist "%%~d\Sentinal_AI\sentinel_client.py" (
        set "CLIENT=%%~d\Sentinal_AI\sentinel_client.py"
        goto :found_client
    )
    if exist "%%~d\Sentinal_AI\sentinel_ai\sentinel_client.py" (
        set "CLIENT=%%~d\Sentinal_AI\sentinel_ai\sentinel_client.py"
        goto :found_client
    )
)

echo.
echo       ERROR: sentinel_client.py not found.
echo       Place sentinel_client.py in the same folder as this bat file and run again.
pause
exit /b 1

:found_client
echo       Found: %CLIENT%

:: ── Step 5: Auto-discover hub and start client ───────────────────────
echo [5/5] Discovering Sentinel hub on network...
echo.

:: Use Python to discover hub via UDP beacon then launch client
python -c "
import socket, json, sys, os, subprocess, time

DISCOVERY_PORT = 47474
DISCOVERY_MSG  = b'SENTINEL_DISCOVER'
device_name    = os.environ.get('SENTINEL_DEVICE', os.environ.get('COMPUTERNAME', 'windows-device'))
client_path    = r'%CLIENT%'

def discover(timeout=5):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        # First listen for broadcast announcements (hub broadcasts every 10s)
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_sock.settimeout(3)
        try:
            listen_sock.bind(('', DISCOVERY_PORT))
            data, _ = listen_sock.recvfrom(1024)
            info = json.loads(data.decode())
            if info.get('sentinel_hub'):
                return info['url']
        except Exception:
            pass
        finally:
            listen_sock.close()

        # Then send a discovery probe
        sock.sendto(DISCOVERY_MSG, ('<broadcast>', DISCOVERY_PORT))
        sock.sendto(DISCOVERY_MSG, ('255.255.255.255', DISCOVERY_PORT))
        data, addr = sock.recvfrom(1024)
        info = json.loads(data.decode())
        if info.get('sentinel_hub'):
            return info['url']
    except Exception:
        pass
    finally:
        sock.close()
    return None

print('  Scanning network for Sentinel hub...')
hub_url = None
for attempt in range(3):
    hub_url = discover(timeout=4)
    if hub_url:
        break
    print(f'  Attempt {attempt+1}/3 — no response yet, retrying...')
    time.sleep(2)

if not hub_url:
    print()
    print('  Hub not found automatically.')
    print('  Make sure the Sentinel hub (Mac) is running ./run.sh')
    print()
    manual = input('  Enter hub URL manually (e.g. http://10.0.0.118:5001): ').strip()
    hub_url = manual if manual else None

if not hub_url:
    print('No hub URL. Exiting.')
    sys.exit(1)

print(f'  Hub found: {hub_url}')
print(f'  Device name: {device_name}')
print()
print('================================================================')
print('  Sentinel AI Remote Client Starting...')
print(f'  Hub:    {hub_url}')
print(f'  Device: {device_name}')
print('  Press Ctrl+C to stop')
print('================================================================')
print()

os.execv(sys.executable, [sys.executable, client_path, '--hub', hub_url, '--device', device_name])
"

if errorlevel 1 (
    echo.
    echo ERROR: Failed to start. See above for details.
    pause
)
