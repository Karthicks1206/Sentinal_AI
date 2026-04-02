"""
Sentinel AI - Windows Hub Discovery & Launcher
Run via start_sentinel_windows.bat — do not run directly.
"""
import concurrent.futures
import json
import os
import socket
import sys
import time
import urllib.request

DISCOVERY_PORT = 47474
DISCOVERY_MSG  = b"SENTINEL_DISCOVER"


def try_http(ip, port=5001, timeout=1):
    try:
        url = f"http://{ip}:{port}/api/status"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read())
            if data.get("system_status"):
                return f"http://{ip}:{port}"
    except Exception:
        pass
    return None


def udp_discover(timeout=4):
    # Try listening for hub broadcast first
    try:
        ls = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.settimeout(3)
        try:
            ls.bind(('', DISCOVERY_PORT))
            data, _ = ls.recvfrom(1024)
            info = json.loads(data.decode())
            if info.get("sentinel_hub"):
                return info["url"]
        except Exception:
            pass
        finally:
            ls.close()
    except Exception:
        pass

    # Send discovery probe
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        s.sendto(DISCOVERY_MSG, ('<broadcast>', DISCOVERY_PORT))
        s.sendto(DISCOVERY_MSG, ('255.255.255.255', DISCOVERY_PORT))
        data, _ = s.recvfrom(1024)
        info = json.loads(data.decode())
        if info.get("sentinel_hub"):
            return info["url"]
    except Exception:
        pass
    return None


def subnet_scan():
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        return None

    prefix = ".".join(local_ip.split(".")[:3])
    last   = int(local_ip.split(".")[3])
    print(f"  Scanning {prefix}.0/24 for hub on port 5001 (~10s)...")

    candidates = sorted(
        [f"{prefix}.{i}" for i in range(1, 255) if i != last],
        key=lambda ip: abs(int(ip.split(".")[3]) - last)
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
        futures = {ex.submit(try_http, ip): ip for ip in candidates}
        for f in concurrent.futures.as_completed(futures):
            result = f.result()
            if result:
                ex.shutdown(wait=False, cancel_futures=True)
                return result
    return None


def main():
    if len(sys.argv) < 3:
        print("Usage: sentinel_launcher.py <client_path> <saved_hub_file>")
        sys.exit(1)

    client_path = sys.argv[1]
    saved_file  = sys.argv[2]
    device_name = os.environ.get("SENTINEL_DEVICE",
                  os.environ.get("COMPUTERNAME", "windows-device"))

    hub_url = None

    # 1. Try saved hub from last successful connection
    if os.path.exists(saved_file):
        saved = open(saved_file).read().strip()
        if saved:
            print(f"  Trying saved hub: {saved}")
            ip = saved.replace("http://", "").split(":")[0]
            hub_url = try_http(ip, timeout=2)
            if hub_url:
                print(f"  Connected to saved hub: {hub_url}")

    # 2. UDP broadcast discovery
    if not hub_url:
        print("  Trying UDP broadcast discovery...")
        hub_url = udp_discover()
        if hub_url:
            print(f"  Found via UDP: {hub_url}")

    # 3. HTTP subnet scan (works even when router blocks UDP)
    if not hub_url:
        hub_url = subnet_scan()
        if hub_url:
            print(f"  Found via subnet scan: {hub_url}")

    # 4. Manual entry
    if not hub_url:
        print()
        print("  Could not find hub automatically.")
        print("  Make sure the Mac is running ./run.sh")
        print()
        entered = input("  Enter hub URL (e.g. http://10.0.0.118:5001): ").strip()
        if entered:
            if not entered.startswith("http"):
                entered = "http://" + entered
            hub_url = entered

    if not hub_url:
        print("No hub URL provided. Exiting.")
        sys.exit(1)

    # Save for next run
    with open(saved_file, "w") as f:
        f.write(hub_url)

    print()
    print("================================================================")
    print(f"  Hub:    {hub_url}")
    print(f"  Device: {device_name}")
    print("  Press Ctrl+C to stop")
    print("================================================================")
    print()

    os.execv(sys.executable, [sys.executable, client_path,
                               "--hub", hub_url, "--device", device_name])


if __name__ == "__main__":
    main()
