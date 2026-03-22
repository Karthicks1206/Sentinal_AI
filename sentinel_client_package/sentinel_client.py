#!/usr/bin/env python3
"""
Sentinel AI — Remote Client (Zero-Config)

Copy this single file to any machine you want monitored.

  pip install psutil          # only external dependency
  python sentinel_client.py   # auto-discovers the hub — no IP needed

The client broadcasts a discovery request on the local network.
The Sentinel AI hub responds automatically and the client starts
streaming metrics within seconds.

If auto-discovery fails (different subnet / VPN), you can still
provide the hub URL manually:
  python sentinel_client.py --hub http://192.168.1.100:5001
"""

import argparse
import json
import platform
import socket
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

try:
    import psutil
except ImportError:
    print("Missing dependency.  Run:  pip install psutil")
    sys.exit(1)

# UDP port used for hub auto-discovery (must match hub's beacon port)
DISCOVERY_PORT  = 47474
DISCOVERY_MSG   = b"SENTINEL_DISCOVER"
DISCOVERY_TRIES = 6      # broadcast attempts before giving up
DISCOVERY_WAIT  = 2.0    # seconds to wait for a reply each try


# ─────────────────────────────────────────────────────────────────────────────
# Hub auto-discovery via UDP broadcast
# ─────────────────────────────────────────────────────────────────────────────

def discover_hub(timeout_per_try: float = DISCOVERY_WAIT) -> str | None:
    """
    Broadcast a discovery request on the LAN and wait for the Sentinel AI hub
    to respond with its URL.  Returns the hub URL string or None.
    """
    print("Searching for Sentinel AI hub on local network...", flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout_per_try)

    try:
        for attempt in range(1, DISCOVERY_TRIES + 1):
            try:
                sock.sendto(DISCOVERY_MSG, ('<broadcast>', DISCOVERY_PORT))
            except OSError:
                # Some platforms don't support <broadcast> — try 255.255.255.255
                try:
                    sock.sendto(DISCOVERY_MSG, ('255.255.255.255', DISCOVERY_PORT))
                except OSError:
                    pass

            try:
                data, addr = sock.recvfrom(1024)
                payload = json.loads(data.decode())
                if payload.get('sentinel_hub'):
                    hub_url = payload['url']
                    print(f"  Found hub at {hub_url}  (via {addr[0]})")
                    return hub_url
            except socket.timeout:
                print(f"  No response yet (attempt {attempt}/{DISCOVERY_TRIES})")
            except (json.JSONDecodeError, KeyError):
                pass
    finally:
        sock.close()

    return None


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers (stdlib only — no requests dependency)
# ─────────────────────────────────────────────────────────────────────────────

def _post(url: str, payload: dict, timeout: int = 5) -> int:
    """POST JSON payload, return HTTP status code (or -1 on error)."""
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1


# ─────────────────────────────────────────────────────────────────────────────
# Metric collection (psutil only)
# ─────────────────────────────────────────────────────────────────────────────

def collect_metrics() -> dict:
    """Collect system metrics.  Returns the same nested structure that the hub
    expects so the anomaly pipeline processes them without any special casing."""

    # CPU
    cpu = {
        'cpu_percent':    psutil.cpu_percent(interval=1),
        'cpu_count':      psutil.cpu_count(),
        'load_avg_1min':  0.0,
        'load_avg_5min':  0.0,
        'load_avg_15min': 0.0,
        'top_process_name': 'unknown',
        'top_process_cpu':  0.0,
        'top_process_pid':  0,
    }
    try:
        la = psutil.getloadavg()
        cpu['load_avg_1min'], cpu['load_avg_5min'], cpu['load_avg_15min'] = la
    except AttributeError:
        pass  # Windows
    try:
        top = max(psutil.process_iter(['pid', 'name', 'cpu_percent']),
                  key=lambda p: p.info.get('cpu_percent') or 0)
        cpu['top_process_name'] = top.info['name'] or 'unknown'
        cpu['top_process_cpu']  = top.info.get('cpu_percent') or 0
        cpu['top_process_pid']  = top.info['pid']
    except Exception:
        pass

    # Memory
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    memory = {
        'memory_percent':     vm.percent,
        'memory_total_mb':    vm.total   / (1024 * 1024),
        'memory_available_mb': vm.available / (1024 * 1024),
        'memory_used_mb':     vm.used    / (1024 * 1024),
        'swap_percent':       sw.percent,
        'swap_used_mb':       sw.used    / (1024 * 1024),
        'top_process_name':   'unknown',
        'top_process_memory': 0.0,
    }
    try:
        top = max(psutil.process_iter(['pid', 'name', 'memory_percent']),
                  key=lambda p: p.info.get('memory_percent') or 0)
        memory['top_process_name']   = top.info['name'] or 'unknown'
        memory['top_process_memory'] = top.info.get('memory_percent') or 0
    except Exception:
        pass

    # Disk
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

    # Network
    nio = psutil.net_io_counters()
    network = {
        'bytes_sent_mb':      (nio.bytes_sent  / (1024 * 1024)) if nio else 0,
        'bytes_recv_mb':      (nio.bytes_recv  / (1024 * 1024)) if nio else 0,
        'packets_sent':       nio.packets_sent if nio else 0,
        'packets_recv':       nio.packets_recv if nio else 0,
        'errors_in':          nio.errin        if nio else 0,
        'errors_out':         nio.errout       if nio else 0,
        'ping_success':       False,
        'ping_latency_ms':    0.0,
        'packet_loss_percent': 0.0,
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
        description='Sentinel AI Remote Client — auto-discovers hub and streams metrics'
    )
    parser.add_argument(
        '--hub', default=None,
        help='Hub URL (optional — auto-discovered if omitted). e.g. http://192.168.1.100:5001',
    )
    parser.add_argument(
        '--device', default=None,
        help='Device name shown on the dashboard (default: hostname)',
    )
    parser.add_argument(
        '--interval', type=int, default=5,
        help='Metric collection interval in seconds (default: 5)',
    )
    args = parser.parse_args()

    device_id = args.device or socket.gethostname()
    interval  = max(1, args.interval)

    print("=" * 56)
    print("  Sentinel AI Remote Client")
    print("=" * 56)
    print(f"  Device   : {device_id}")
    print(f"  Platform : {platform.system()} {platform.release()}")
    print(f"  Interval : {interval}s")
    print("=" * 56 + "\n")

    # ── Step 1: resolve hub URL ──────────────────────────────────────────
    hub_url = args.hub
    if hub_url:
        hub_url = hub_url.rstrip('/')
        print(f"Hub URL provided: {hub_url}")
    else:
        hub_url = discover_hub()

    if not hub_url:
        print("\nAuto-discovery failed.  Options:")
        print("  1. Make sure the Sentinel AI hub is running (python main.py)")
        print("  2. If on a different subnet, specify manually:")
        print("       python sentinel_client.py --hub http://<HUB_IP>:5001")
        sys.exit(1)

    # ── Step 2: register with hub ────────────────────────────────────────
    print("\nRegistering with hub...", flush=True)
    reg_payload = {
        'device_id': device_id,
        'hostname':  socket.gethostname(),
        'platform':  platform.system(),
        'version':   platform.version(),
        'python':    platform.python_version(),
    }

    while True:
        status = _post(f"{hub_url}/api/devices/register", reg_payload)
        if status == 200:
            print(f"  Registered successfully as '{device_id}'")
            break
        print(f"  Hub not ready yet (HTTP {status}) — retrying in 5s...")
        time.sleep(5)

    # ── Step 3: stream metrics ───────────────────────────────────────────
    print("\nStreaming metrics to hub.  Press Ctrl+C to stop.\n")

    errors = 0
    while True:
        try:
            metrics = collect_metrics()
            payload = {
                'device_id': device_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metrics':   metrics,
            }
            status = _post(f"{hub_url}/api/metrics/push", payload)

            if status == 200:
                errors = 0
                ts  = datetime.now().strftime('%H:%M:%S')
                cpu = metrics['cpu']['cpu_percent']
                mem = metrics['memory']['memory_percent']
                dsk = metrics['disk']['disk_percent']
                print(f"[{ts}] CPU={cpu:.1f}%  MEM={mem:.1f}%  DISK={dsk:.1f}%")
            else:
                errors += 1
                print(f"  Push returned HTTP {status} (error #{errors})")

        except KeyboardInterrupt:
            print("\nStopped.")
            break

        except OSError:
            # Connection refused / network gone
            errors += 1
            print(f"  Hub unreachable (error #{errors})")
            if errors % 6 == 0:
                # Re-run discovery in case hub moved
                print("  Re-discovering hub...")
                found = discover_hub(timeout_per_try=1.5)
                if found:
                    hub_url = found
                    _post(f"{hub_url}/api/devices/register", reg_payload)

        except Exception as e:
            errors += 1
            print(f"  Error: {e}")

        time.sleep(interval)


if __name__ == '__main__':
    main()
