#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sentinel AI — Remote Client
Compatible with Python 3.7+  (Windows / Linux / macOS)

Copy this single file to any machine you want monitored.

  pip install psutil
  python sentinel_client.py --hub http://192.168.x.x:5001

Auto-discovery (same LAN, no router AP-isolation):
  python sentinel_client.py

If you see "Connection failed" run the test command to diagnose:
  python sentinel_client.py --test --hub http://192.168.x.x:5001
"""
from __future__ import annotations   # makes type hints work on Python 3.7+

import argparse
import json
import platform
import socket
import sys
import time
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timezone

try:
    import psutil
except ImportError:
    print("[ERROR] psutil not installed.")
    print("        Run:  pip install psutil")
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────────────────────
DISCOVERY_PORT  = 47474
DISCOVERY_MSG   = b"SENTINEL_DISCOVER"
DISCOVERY_TRIES = 6
DISCOVERY_WAIT  = 2.0

VERSION = "1.2"


# ── Pretty-print helpers ───────────────────────────────────────────────────────

def _ok(msg):  print("  [OK]  " + msg, flush=True)
def _err(msg): print("  [ERR] " + msg, flush=True)
def _info(msg):print("  [..] " + msg,  flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Pre-flight connectivity test
# ─────────────────────────────────────────────────────────────────────────────

def test_connectivity(hub_url: str) -> bool:
    """
    Run a series of diagnostic checks against the hub URL and print
    step-by-step results.  Returns True if the hub is fully reachable.
    """
    from urllib.parse import urlparse
    parsed  = urlparse(hub_url)
    host    = parsed.hostname or ''
    port    = parsed.port or 5001

    print()
    print("=" * 60)
    print("  Connectivity Diagnostics")
    print("=" * 60)

    # ── Step 1: DNS / IP resolution ───────────────────────────────────
    print("\n  Step 1 — Resolve host ...")
    try:
        ip = socket.gethostbyname(host)
        _ok("Host resolved: {} → {}".format(host, ip))
    except socket.gaierror as e:
        _err("Cannot resolve '{}': {}".format(host, e))
        _err("Check that you typed the correct IP address.")
        return False

    # ── Step 2: TCP reachability ──────────────────────────────────────
    print("\n  Step 2 — TCP connect to {}:{} ...".format(host, port))
    try:
        s = socket.create_connection((host, port), timeout=4)
        s.close()
        _ok("TCP connection succeeded on port {}".format(port))
    except socket.timeout:
        _err("Connection TIMED OUT after 4 seconds.")
        _print_network_help(host, port)
        return False
    except ConnectionRefusedError:
        _err("Connection REFUSED — nothing listening on {}:{}".format(host, port))
        _err("Make sure Sentinel AI hub (main.py) is running on the Mac.")
        return False
    except OSError as e:
        _err("TCP connect failed: {}".format(e))
        _print_network_help(host, port)
        return False

    # ── Step 3: HTTP GET /api/status ─────────────────────────────────
    print("\n  Step 3 — HTTP GET {}/api/status ...".format(hub_url))
    try:
        req = urllib.request.Request(hub_url + "/api/status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            _ok("Hub is running — status: {}".format(data.get('system_status', '?')))
    except Exception as e:
        _err("HTTP request failed: {}".format(e))
        return False

    print()
    print("  All checks passed!  Hub is reachable.")
    print("=" * 60)
    print()
    return True


def _print_network_help(host: str, port: int):
    print()
    print("  ── Possible causes & fixes ──────────────────────────────")
    print("  1. Router AP/Client Isolation (most common on WiFi):")
    print("     Your router may block device-to-device traffic.")
    print("     Fix: Log into router → disable 'AP Isolation' or")
    print("          'Client Isolation' on your WiFi network.")
    print()
    print("  2. macOS Firewall (on the hub machine):")
    print("     Open System Settings → Privacy & Security → Firewall")
    print("     → Firewall Options → make sure python3 is ALLOWED.")
    print()
    print("  3. Windows Firewall (on this machine):")
    print("     Open Windows Defender Firewall → Allow an app → add")
    print("     python.exe and allow it on Private networks.")
    print()
    print("  4. Wrong IP — verify hub IP by running on the Mac:")
    print("     ipconfig getifaddr en0")
    print()
    print("  Hub address used: {}:{}".format(host, port))
    print("  ─────────────────────────────────────────────────────────")


# ─────────────────────────────────────────────────────────────────────────────
# Hub auto-discovery via UDP broadcast
# ─────────────────────────────────────────────────────────────────────────────

def discover_hub(timeout_per_try: float = DISCOVERY_WAIT) -> str | None:
    """Broadcast on the LAN; return hub URL string or None."""
    print("Searching for Sentinel AI hub on local network...", flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout_per_try)

    try:
        for attempt in range(1, DISCOVERY_TRIES + 1):
            for dest in ('<broadcast>', '255.255.255.255'):
                try:
                    sock.sendto(DISCOVERY_MSG, (dest, DISCOVERY_PORT))
                    break
                except OSError:
                    continue

            try:
                data, addr = sock.recvfrom(1024)
                payload = json.loads(data.decode())
                if payload.get('sentinel_hub'):
                    hub_url = payload['url']
                    print("  Found hub at {}  (via {})".format(hub_url, addr[0]))
                    return hub_url
            except socket.timeout:
                print("  No response yet (attempt {}/{})".format(attempt, DISCOVERY_TRIES))
            except (json.JSONDecodeError, KeyError):
                pass
    finally:
        sock.close()

    return None


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers (stdlib only — no external dependencies)
# ─────────────────────────────────────────────────────────────────────────────

_last_error: str = ""   # stores the last connection error for diagnostics


def _post(url: str, payload: dict, timeout: int = 8) -> int:
    """POST JSON; return HTTP status code, or -1 on connection error."""
    global _last_error
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _last_error = ""
            return resp.status
    except urllib.error.HTTPError as e:
        _last_error = "HTTP {}".format(e.code)
        return e.code
    except urllib.error.URLError as e:
        _last_error = str(e.reason)
        return -1
    except socket.timeout:
        _last_error = "Timed out after {}s".format(timeout)
        return -1
    except ConnectionRefusedError:
        _last_error = "Connection refused — hub may not be running"
        return -1
    except OSError as e:
        _last_error = str(e)
        return -1
    except Exception as e:
        _last_error = repr(e)
        return -1


# ─────────────────────────────────────────────────────────────────────────────
# Metric collection (psutil only — no extra dependencies)
# ─────────────────────────────────────────────────────────────────────────────

def collect_metrics() -> dict:
    """Collect system metrics compatible with the Sentinel AI hub schema."""

    # ── CPU ──────────────────────────────────────────────────────────────
    cpu = {
        'cpu_percent':      psutil.cpu_percent(interval=1),
        'cpu_count':        psutil.cpu_count(),
        'load_avg_1min':    0.0,
        'load_avg_5min':    0.0,
        'load_avg_15min':   0.0,
        'top_process_name': 'unknown',
        'top_process_cpu':  0.0,
        'top_process_pid':  0,
    }
    try:
        la = psutil.getloadavg()
        cpu['load_avg_1min'], cpu['load_avg_5min'], cpu['load_avg_15min'] = la
    except AttributeError:
        pass  # Windows does not expose getloadavg
    try:
        top = max(
            psutil.process_iter(['pid', 'name', 'cpu_percent']),
            key=lambda p: p.info.get('cpu_percent') or 0,
        )
        cpu['top_process_name'] = top.info['name'] or 'unknown'
        cpu['top_process_cpu']  = top.info.get('cpu_percent') or 0
        cpu['top_process_pid']  = top.info['pid']
    except Exception:
        pass

    # ── Memory ───────────────────────────────────────────────────────────
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    memory = {
        'memory_percent':      vm.percent,
        'memory_total_mb':     vm.total    / (1024 * 1024),
        'memory_available_mb': vm.available / (1024 * 1024),
        'memory_used_mb':      vm.used     / (1024 * 1024),
        'swap_percent':        sw.percent,
        'swap_used_mb':        sw.used     / (1024 * 1024),
        'top_process_name':    'unknown',
        'top_process_memory':  0.0,
    }
    try:
        top = max(
            psutil.process_iter(['pid', 'name', 'memory_percent']),
            key=lambda p: p.info.get('memory_percent') or 0,
        )
        memory['top_process_name']   = top.info['name'] or 'unknown'
        memory['top_process_memory'] = top.info.get('memory_percent') or 0
    except Exception:
        pass

    # ── Disk ─────────────────────────────────────────────────────────────
    try:
        # On Windows use C:\ instead of /
        disk_path = 'C:\\' if platform.system() == 'Windows' else '/'
        du = psutil.disk_usage(disk_path)
    except Exception:
        du = psutil.disk_usage('/')
    disk = {
        'disk_percent':  du.percent,
        'disk_total_gb': du.total / (1024 ** 3),
        'disk_used_gb':  du.used  / (1024 ** 3),
        'disk_free_gb':  du.free  / (1024 ** 3),
        'disk_read_mb':  0.0,
        'disk_write_mb': 0.0,
    }
    try:
        io = psutil.disk_io_counters()
        if io:
            disk['disk_read_mb']  = io.read_bytes  / (1024 * 1024)
            disk['disk_write_mb'] = io.write_bytes / (1024 * 1024)
    except Exception:
        pass

    # ── Network ──────────────────────────────────────────────────────────
    nio = psutil.net_io_counters()
    network = {
        'bytes_sent_mb':       (nio.bytes_sent  / (1024 * 1024)) if nio else 0,
        'bytes_recv_mb':       (nio.bytes_recv  / (1024 * 1024)) if nio else 0,
        'packets_sent':         nio.packets_sent if nio else 0,
        'packets_recv':         nio.packets_recv if nio else 0,
        'errors_in':            nio.errin        if nio else 0,
        'errors_out':           nio.errout       if nio else 0,
        'ping_success':         False,
        'ping_latency_ms':      0.0,
        'packet_loss_percent':  0.0,
    }
    for host in ['8.8.8.8', '1.1.1.1']:
        try:
            t0 = time.time()
            s  = socket.create_connection((host, 53), timeout=2)
            s.close()
            network['ping_success']    = True
            network['ping_latency_ms'] = round((time.time() - t0) * 1000, 2)
            break
        except Exception:
            pass

    return {'cpu': cpu, 'memory': memory, 'disk': disk, 'network': network}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Sentinel AI Remote Client v{} — streams metrics to hub'.format(VERSION)
    )
    parser.add_argument(
        '--hub', default=None,
        help='Hub URL, e.g.  http://192.168.1.100:5001  (auto-discovered if omitted)',
    )
    parser.add_argument(
        '--device', default=None,
        help='Device name on the dashboard (default: hostname)',
    )
    parser.add_argument(
        '--interval', type=int, default=5,
        help='Metric push interval in seconds (default: 5)',
    )
    parser.add_argument(
        '--test', action='store_true',
        help='Run connectivity diagnostics and exit',
    )
    args = parser.parse_args()

    device_id = args.device or socket.gethostname()
    interval  = max(1, args.interval)

    print("=" * 60)
    print("  Sentinel AI Remote Client  v{}".format(VERSION))
    print("=" * 60)
    print("  Device   : {}".format(device_id))
    print("  Platform : {} {}".format(platform.system(), platform.release()))
    print("  Python   : {}".format(platform.python_version()))
    print("  Interval : {}s".format(interval))
    print("=" * 60 + "\n")

    # ── Step 1: Resolve hub URL ───────────────────────────────────────────
    hub_url = args.hub
    if hub_url:
        hub_url = hub_url.rstrip('/')
        print("Hub URL : {}".format(hub_url))
    else:
        hub_url = discover_hub()

    if not hub_url:
        print("\n[ERROR] Could not find hub.  Options:")
        print("  1. Make sure main.py is running on the hub machine")
        print("  2. Provide the hub IP manually:")
        print("       python sentinel_client.py --hub http://<HUB_IP>:5001")
        sys.exit(1)

    # ── --test mode: run diagnostics and exit ─────────────────────────────
    if args.test:
        ok = test_connectivity(hub_url)
        sys.exit(0 if ok else 1)

    # ── Step 2: Pre-flight check before registering ───────────────────────
    print("\nChecking hub connectivity ...", flush=True)
    try:
        from urllib.parse import urlparse
        parsed = urlparse(hub_url)
        s = socket.create_connection((parsed.hostname, parsed.port or 5001), timeout=5)
        s.close()
        _ok("Hub is reachable at {}".format(hub_url))
    except Exception as e:
        _err("Cannot reach hub: {}".format(e))
        print()
        _print_network_help(
            hub_url.split("//")[-1].split(":")[0],
            int(hub_url.split(":")[-1]) if hub_url.count(":") == 2 else 5001,
        )
        print()
        print("  Run with --test for full diagnostics:")
        print("    python sentinel_client.py --test --hub {}".format(hub_url))
        sys.exit(1)

    # ── Step 3: Register ──────────────────────────────────────────────────
    print("\nRegistering with hub ...", flush=True)
    reg_payload = {
        'device_id': device_id,
        'hostname':  socket.gethostname(),
        'platform':  platform.system(),
        'version':   platform.version(),
        'python':    platform.python_version(),
    }

    attempts = 0
    while True:
        status = _post("{}/api/devices/register".format(hub_url), reg_payload)
        if status == 200:
            _ok("Registered as '{}'".format(device_id))
            break

        attempts += 1
        if _last_error:
            print("  [ERR] Registration failed: {} (attempt #{})".format(_last_error, attempts), flush=True)
        else:
            print("  [ERR] HTTP {} — retrying in 5s (attempt #{})".format(status, attempts), flush=True)

        if attempts >= 3:
            print()
            print("  Still failing after {} attempts.".format(attempts))
            print("  Running diagnostics ...")
            test_connectivity(hub_url)
            print("  Continuing to retry every 5s.  Press Ctrl+C to stop.")

        time.sleep(5)

    # ── Step 4: Stream metrics ────────────────────────────────────────────
    print("\nStreaming metrics.  Press Ctrl+C to stop.\n")
    print("  {:<10} {:<10} {:<10} {:<10}".format("TIME", "CPU %", "MEM %", "DISK %"))
    print("  " + "-" * 42)

    errors = 0
    while True:
        try:
            metrics = collect_metrics()
            payload = {
                'device_id': device_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metrics':   metrics,
            }
            status = _post("{}/api/metrics/push".format(hub_url), payload)

            if status == 200:
                errors = 0
                ts    = datetime.now().strftime('%H:%M:%S')
                cpu   = metrics['cpu']['cpu_percent']
                mem   = metrics['memory']['memory_percent']
                dsk   = metrics['disk']['disk_percent']
                print("  {:<10} {:<10.1f} {:<10.1f} {:<10.1f}".format(ts, cpu, mem, dsk), flush=True)
            else:
                errors += 1
                reason = _last_error or "HTTP {}".format(status)
                print("  [WARN] Push failed: {} (#{})".format(reason, errors), flush=True)
                if errors >= 5:
                    print("  [WARN] Too many errors — re-registering ...", flush=True)
                    _post("{}/api/devices/register".format(hub_url), reg_payload)
                    errors = 0

        except KeyboardInterrupt:
            print("\n\nStopped by user.")
            break
        except Exception as e:
            errors += 1
            print("  [ERR] {}".format(e), flush=True)

        time.sleep(interval)


if __name__ == '__main__':
    main()
