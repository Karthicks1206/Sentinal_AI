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

if exist "%~dp0sentinel_client.py"                                          set "CLIENT=%~dp0sentinel_client.py"
if not defined CLIENT if exist "%~dp0..\sentinel_client.py"                 set "CLIENT=%~dp0..\sentinel_client.py"
if not defined CLIENT if exist "%USERPROFILE%\Desktop\sentinel_client.py"   set "CLIENT=%USERPROFILE%\Desktop\sentinel_client.py"
if not defined CLIENT if exist "%USERPROFILE%\Downloads\sentinel_client.py" set "CLIENT=%USERPROFILE%\Downloads\sentinel_client.py"
if not defined CLIENT if exist "%USERPROFILE%\Desktop\Sentinal_AI\sentinel_ai\sentinel_client.py" set "CLIENT=%USERPROFILE%\Desktop\Sentinal_AI\sentinel_ai\sentinel_client.py"
if not defined CLIENT if exist "%USERPROFILE%\OneDrive\Desktop\Sentinal_AI\sentinel_ai\sentinel_client.py" set "CLIENT=%USERPROFILE%\OneDrive\Desktop\Sentinal_AI\sentinel_ai\sentinel_client.py"

if not defined CLIENT (
    echo.
    echo       ERROR: sentinel_client.py not found.
    echo       Place sentinel_client.py in the same folder as this bat file.
    pause
    exit /b 1
)
echo       Found: %CLIENT%

:: ── Step 5: Write discovery helper and launch ────────────────────────
echo [5/5] Finding Sentinel hub...
echo.

set "HELPER=%TEMP%\sentinel_launcher.py"
set "SAVED_HUB=%~dp0.sentinel_hub"

(
echo import socket, json, sys, os, time, threading, concurrent.futures
echo import urllib.request
echo.
echo DISCOVERY_PORT = 47474
echo DISCOVERY_MSG  = b"SENTINEL_DISCOVER"
echo SAVED_FILE     = sys.argv[2]
echo device_name    = os.environ.get^("SENTINEL_DEVICE", os.environ.get^("COMPUTERNAME", "windows-device"^)^)
echo client_path    = sys.argv[1]
echo.
echo def try_http^(ip, port=5001, timeout=1^):
echo     try:
echo         url = f"http://{ip}:{port}/api/status"
echo         with urllib.request.urlopen^(url, timeout=timeout^) as r:
echo             data = json.loads^(r.read^(^)^)
echo             if data.get^("system_status"^):
echo                 return f"http://{ip}:{port}"
echo     except Exception:
echo         pass
echo     return None
echo.
echo def udp_discover^(timeout=4^):
echo     try:
echo         ls = socket.socket^(socket.AF_INET, socket.SOCK_DGRAM^)
echo         ls.setsockopt^(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1^)
echo         ls.settimeout^(3^)
echo         try:
echo             ls.bind^(^('', DISCOVERY_PORT^)^)
echo             data, _ = ls.recvfrom^(1024^)
echo             info = json.loads^(data.decode^(^)^)
echo             if info.get^("sentinel_hub"^): return info["url"]
echo         except Exception:
echo             pass
echo         finally:
echo             ls.close^(^)
echo     except Exception:
echo         pass
echo     try:
echo         s = socket.socket^(socket.AF_INET, socket.SOCK_DGRAM^)
echo         s.setsockopt^(socket.SOL_SOCKET, socket.SO_BROADCAST, 1^)
echo         s.settimeout^(timeout^)
echo         s.sendto^(DISCOVERY_MSG, ^("<broadcast>", DISCOVERY_PORT^)^)
echo         s.sendto^(DISCOVERY_MSG, ^("255.255.255.255", DISCOVERY_PORT^)^)
echo         data, _ = s.recvfrom^(1024^)
echo         info = json.loads^(data.decode^(^)^)
echo         if info.get^("sentinel_hub"^): return info["url"]
echo     except Exception:
echo         pass
echo     return None
echo.
echo def subnet_scan^(^):
echo     try:
echo         hostname = socket.gethostname^(^)
echo         local_ip = socket.gethostbyname^(hostname^)
echo     except Exception:
echo         return None
echo     prefix = ".".join^(local_ip.split^("."^)[:3]^)
echo     print^(f"  Scanning subnet {prefix}.0/24 for hub on port 5001..."^)
echo     candidates = []
echo     parts = local_ip.split^("."^)
echo     last = int^(parts[3]^)
echo     for i in range^(1, 255^):
echo         if i != last:
echo             candidates.append^(f"{prefix}.{i}"^)
echo     candidates.sort^(key=lambda ip: abs^(int^(ip.split^("."^)[3]^) - last^)^)
echo     with concurrent.futures.ThreadPoolExecutor^(max_workers=50^) as ex:
echo         futures = {ex.submit^(try_http, ip^): ip for ip in candidates}
echo         for f in concurrent.futures.as_completed^(futures^):
echo             result = f.result^(^)
echo             if result:
echo                 ex.shutdown^(wait=False, cancel_futures=True^)
echo                 return result
echo     return None
echo.
echo hub_url = None
echo.
echo if os.path.exists^(SAVED_FILE^):
echo     with open^(SAVED_FILE^) as f:
echo         saved = f.read^(^).strip^(^)
echo     if saved:
echo         print^(f"  Trying saved hub: {saved}"^)
echo         hub_url = try_http^(saved.replace^("http://",""^).split^(":"^)[0], timeout=2^)
echo         if hub_url:
echo             print^(f"  Connected to saved hub: {hub_url}"^)
echo.
echo if not hub_url:
echo     print^("  Step 1: UDP broadcast discovery..."^)
echo     hub_url = udp_discover^(^)
echo     if hub_url:
echo         print^(f"  Found via UDP: {hub_url}"^)
echo.
echo if not hub_url:
echo     print^("  Step 2: HTTP subnet scan (router blocks UDP - this takes ~10s)..."^)
echo     hub_url = subnet_scan^(^)
echo     if hub_url:
echo         print^(f"  Found via scan: {hub_url}"^)
echo.
echo if not hub_url:
echo     print^(^)
echo     print^("  Could not find hub automatically."^)
echo     print^("  Make sure the Mac is running ./run.sh"^)
echo     print^(^)
echo     hub_url = input^("  Enter hub URL (e.g. http://10.0.0.118:5001): "^).strip^(^)
echo     if hub_url and not hub_url.startswith^("http"^):
echo         hub_url = "http://" + hub_url
echo.
echo if not hub_url:
echo     print^("No hub URL. Exiting."^)
echo     sys.exit^(1^)
echo.
echo with open^(SAVED_FILE, "w"^) as f:
echo     f.write^(hub_url^)
echo.
echo print^(^)
echo print^("================================================================"^)
echo print^(f"  Hub:    {hub_url}"^)
echo print^(f"  Device: {device_name}"^)
echo print^("  Press Ctrl+C to stop"^)
echo print^("================================================================"^)
echo print^(^)
echo os.execv^(sys.executable, [sys.executable, client_path, "--hub", hub_url, "--device", device_name]^)
) > "%HELPER%"

python "%HELPER%" "%CLIENT%" "%SAVED_HUB%"

if errorlevel 1 (
    echo.
    echo ERROR: Failed to start. See above for details.
    pause
)
