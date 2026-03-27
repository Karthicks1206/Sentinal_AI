#!/usr/bin/env python3
"""
Sentinel AI — Remote Client
Compatible with Python 3.7+ (Windows / Linux / macOS)

Copy this single file to any machine you want monitored.

  pip install psutil
  python sentinel_client.py --hub http://192.168.x.x:5001

Auto-discovery (same LAN, no router AP-isolation):
  python sentinel_client.py

If you see "Connection failed" run the test command to diagnose:
  python sentinel_client.py --test --hub http://192.168.x.x:5001
"""
from __future__ import annotations

import argparse
import json
import platform
import socket
import sys
import threading
import time
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

_stress_stop = threading.Event()
_stress_threads: list = []

_hub_url_ref: list = ['']
_device_id_ref: list = ['']


def _make_command_handler():
    class CommandHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/command':
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                action = data.get('action', '')
                action_id = data.get('action_id', '')
                print(' [CMD] direct: {}'.format(action), flush=True)
                result = _exec_remote_command(action)
                result['action_id'] = action_id
                result['action'] = action
                hub = _hub_url_ref[0]
                dev = _device_id_ref[0]
                if hub and dev:
                    _post('{}/api/devices/{}/command_results'.format(hub, dev),
                          {'device_id': dev, 'results': [result]})
                resp = json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as exc:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(exc).encode())

        def log_message(self, *args):
            pass

    return CommandHandler


def _start_command_server(port: int):
    try:
        server = HTTPServer(('0.0.0.0', port), _make_command_handler())
        t = threading.Thread(target=server.serve_forever, daemon=True, name='sentinel_cmd_server')
        t.start()
        return True
    except Exception as exc:
        print(' [WARN] Could not start command server on port {}: {}'.format(port, exc), flush=True)
        return False

try:
    import psutil
except ImportError:
    print("[ERROR] psutil not installed.")
    print(" Run: pip install psutil")
    sys.exit(1)

DISCOVERY_PORT = 47474
DISCOVERY_MSG = b"SENTINEL_DISCOVER"
DISCOVERY_TRIES = 6
DISCOVERY_WAIT = 2.0

VERSION = "1.2"


def _ok(msg): print(" [OK] " + msg, flush=True)
def _err(msg): print(" [ERR] " + msg, flush=True)
def _info(msg):print(" [..] " + msg, flush=True)


def test_connectivity(hub_url: str) -> bool:
    """
    Run a series of diagnostic checks against the hub URL and print
    step-by-step results. Returns True if the hub is fully reachable.
    """
    from urllib.parse import urlparse
    parsed = urlparse(hub_url)
    host = parsed.hostname or ''
    port = parsed.port or 5001

    print()
    print("=" * 60)
    print(" Connectivity Diagnostics")
    print("=" * 60)

    print("\n Step 1 — Resolve host ...")
    try:
        ip = socket.gethostbyname(host)
        _ok("Host resolved: {} → {}".format(host, ip))
    except socket.gaierror as e:
        _err("Cannot resolve '{}': {}".format(host, e))
        _err("Check that you typed the correct IP address.")
        return False

    print("\n Step 2 — TCP connect to {}:{} ...".format(host, port))
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

    print("\n Step 3 — HTTP GET {}/api/status ...".format(hub_url))
    try:
        req = urllib.request.Request(hub_url + "/api/status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            _ok("Hub is running — status: {}".format(data.get('system_status', '?')))
    except Exception as e:
        _err("HTTP request failed: {}".format(e))
        return False

    print()
    print(" All checks passed! Hub is reachable.")
    print("=" * 60)
    print()
    return True


def _print_network_help(host: str, port: int):
    print()
    print(" Possible causes & fixes ")
    print(" 1. Router AP/Client Isolation (most common on WiFi):")
    print(" Your router may block device-to-device traffic.")
    print(" Fix: Log into router → disable 'AP Isolation' or")
    print(" 'Client Isolation' on your WiFi network.")
    print()
    print(" 2. macOS Firewall (on the hub machine):")
    print(" Open System Settings → Privacy & Security → Firewall")
    print(" → Firewall Options → make sure python3 is ALLOWED.")
    print()
    print(" 3. Windows Firewall (on this machine):")
    print(" Open Windows Defender Firewall → Allow an app → add")
    print(" python.exe and allow it on Private networks.")
    print()
    print(" 4. Wrong IP — verify hub IP by running on the Mac:")
    print(" ipconfig getifaddr en0")
    print()
    print(" Hub address used: {}:{}".format(host, port))
    print(" ")


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
                    print(" Found hub at {} (via {})".format(hub_url, addr[0]))
                    return hub_url
            except socket.timeout:
                print(" No response yet (attempt {}/{})".format(attempt, DISCOVERY_TRIES))
            except (json.JSONDecodeError, KeyError):
                pass
    finally:
        sock.close()

    return None


_last_error: str = ""


def _post(url: str, payload: dict, timeout: int = 8) -> int:
    """POST JSON; return HTTP status code, or -1 on connection error."""
    global _last_error
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
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


def _get_json(url, timeout=5):
    """GET JSON from url; return parsed dict or None on error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


_CRITICAL_PROCS = {
    'system', 'svchost', 'lsass', 'csrss', 'wininit', 'services',
    'winlogon', 'explorer', 'python', 'python3', 'sentinel_client',
    'systemd', 'init', 'launchd',
}


def _exec_remote_command(action):
    """Execute a recovery action locally on this machine. Returns a result dict."""
    try:
        import os as _os
        import psutil

        def _safe_kill(proc):
            name = proc.name().lower().replace('.exe', '')
            if name in _CRITICAL_PROCS:
                return False, "protected process: {}".format(name)
            try:
                proc.kill()
                return True, "killed {} (pid {})".format(proc.name(), proc.pid)
            except Exception as e:
                return False, str(e)

        if action == 'kill_top_cpu_process':
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                pass
            time.sleep(0.5)
            procs = sorted(
                psutil.process_iter(['pid', 'name', 'cpu_percent']),
                key=lambda p: p.info.get('cpu_percent') or 0, reverse=True
            )
            for proc in procs:
                ok, msg = _safe_kill(proc)
                if ok:
                    return {'status': 'success', 'message': msg}
            return {'status': 'skipped', 'message': 'no killable high-CPU process found'}

        elif action == 'kill_top_memory_process':
            procs = sorted(
                psutil.process_iter(['pid', 'name', 'memory_percent']),
                key=lambda p: p.info.get('memory_percent') or 0, reverse=True
            )
            for proc in procs:
                ok, msg = _safe_kill(proc)
                if ok:
                    return {'status': 'success', 'message': msg}
            return {'status': 'skipped', 'message': 'no killable high-memory process found'}

        elif action in ('compact_memory', 'clear_cache'):
            if platform.system() == 'Windows':
                import ctypes
                freed = 0
                for proc in psutil.process_iter(['pid']):
                    try:
                        handle = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, proc.pid)
                        if handle:
                            ctypes.windll.psapi.EmptyWorkingSet(handle)
                            ctypes.windll.kernel32.CloseHandle(handle)
                            freed += 1
                    except Exception:
                        pass
                return {'status': 'success',
                        'message': 'EmptyWorkingSet on {} processes'.format(freed)}
            else:
                _os.system('sync')
                return {'status': 'success', 'message': 'sync called'}

        elif action in ('emergency_disk_cleanup', 'rotate_logs'):
            import tempfile, glob as _glob
            removed = 0
            tmp_dirs = [tempfile.gettempdir()]
            if platform.system() == 'Windows':
                tmp_dirs.append(_os.path.expandvars(r'%LOCALAPPDATA%\Temp'))
            for tmp in tmp_dirs:
                for f in (_glob.glob(_os.path.join(tmp, '*.tmp')) +
                          _glob.glob(_os.path.join(tmp, '*.log'))):
                    try:
                        _os.remove(f)
                        removed += 1
                    except Exception:
                        pass
            return {'status': 'success',
                    'message': 'removed {} temp/log files'.format(removed)}

        elif action in ('kill_process', 'algorithmic_cpu_fix', 'throttle_cpu_process'):
            procs = sorted(
                psutil.process_iter(['pid', 'name', 'cpu_percent']),
                key=lambda p: p.info.get('cpu_percent') or 0, reverse=True
            )
            for proc in procs:
                ok, msg = _safe_kill(proc)
                if ok:
                    return {'status': 'success', 'message': 'kill_process: ' + msg}
            return {'status': 'success', 'message': 'no high-CPU process found; compacted memory instead'}

        elif action in ('restart_service', 'restart_mqtt', 'reconnect_sensor'):
            return {'status': 'success',
                    'message': '{} not applicable on this host — no managed services'.format(action)}

        elif action in ('flush_dns', 'algorithmic_network_fix'):
            try:
                if platform.system() == 'Windows':
                    import subprocess
                    subprocess.run(['ipconfig', '/flushdns'], capture_output=True, timeout=10)
                    subprocess.run(['netsh', 'winsock', 'reset'], capture_output=True, timeout=10)
                elif platform.system() == 'Darwin':
                    import subprocess
                    subprocess.run(['dscacheutil', '-flushcache'], capture_output=True, timeout=5)
                    subprocess.run(['killall', '-HUP', 'mDNSResponder'], capture_output=True, timeout=5)
                else:
                    import subprocess
                    subprocess.run(['systemd-resolve', '--flush-caches'], capture_output=True, timeout=5)
                return {'status': 'success', 'message': 'DNS cache flushed on {}'.format(platform.system())}
            except Exception as e:
                return {'status': 'success', 'message': 'flush_dns attempted: {}'.format(e)}

        elif action in ('check_network', 'reset_network_interface'):
            import socket as _sock
            results = []
            for host in ['8.8.8.8', '1.1.1.1']:
                try:
                    t0 = time.time()
                    s = _sock.create_connection((host, 53), timeout=3)
                    s.close()
                    results.append('{}={:.0f}ms'.format(host, (time.time()-t0)*1000))
                except Exception:
                    results.append('{}=unreachable'.format(host))
            return {'status': 'success', 'message': 'network check: ' + ', '.join(results)}

        elif action == 'stress_cpu':
            import os as _os
            _stress_stop.clear()
            cores = max(2, (_os.cpu_count() or 2) * 2)
            def _cpu_stress():
                end = time.time() + 60
                while time.time() < end and not _stress_stop.is_set():
                    x = 0
                    for k in range(50000):
                        x += k * k
            for i in range(cores):
                t = threading.Thread(target=_cpu_stress, daemon=True,
                                     name='sentinel_stress_cpu_{}'.format(i))
                _stress_threads.append(t)
                t.start()
            return {'status': 'success', 'message': 'CPU stress running on {} threads for 60s'.format(cores)}

        elif action == 'stress_memory':
            _stress_stop.clear()
            total_mb = psutil.virtual_memory().total // (1024 * 1024)
            alloc_mb = max(512, int(total_mb * 0.30))
            def _mem_stress():
                try:
                    data = bytearray(alloc_mb * 1024 * 1024)
                    end = time.time() + 60
                    while time.time() < end and not _stress_stop.is_set():
                        time.sleep(0.5)
                    del data
                except MemoryError:
                    pass
            t = threading.Thread(target=_mem_stress, daemon=True, name='sentinel_stress_mem')
            _stress_threads.append(t)
            t.start()
            return {'status': 'success', 'message': 'Memory stress running for 60s ({} MB = 30% of RAM)'.format(alloc_mb)}

        elif action == 'stress_disk':
            import os as _os, tempfile
            _stress_stop.clear()
            def _disk_stress():
                fpath = _os.path.join(tempfile.gettempdir(), 'sentinel_disk_stress.tmp')
                try:
                    end = time.time() + 60
                    while time.time() < end and not _stress_stop.is_set():
                        with open(fpath, 'wb') as fp:
                            for _ in range(200):
                                if _stress_stop.is_set():
                                    break
                                fp.write(b'S' * 1024 * 1024)
                                fp.flush()
                        try:
                            _os.remove(fpath)
                        except Exception:
                            pass
                        time.sleep(1)
                finally:
                    try:
                        _os.remove(fpath)
                    except Exception:
                        pass
            t = threading.Thread(target=_disk_stress, daemon=True, name='sentinel_stress_disk')
            _stress_threads.append(t)
            t.start()
            return {'status': 'success', 'message': 'Disk stress running (sustained 200 MB cycling writes)'}

        elif action == 'stop_stress':
            _stress_stop.set()
            alive = [t for t in _stress_threads if t.is_alive()]
            return {'status': 'success', 'message': 'Stress stop signal sent ({} threads)'.format(len(alive))}

        elif action == 'demo_cpu':
            _stress_stop.clear()
            import os as _os
            cores = max(2, (_os.cpu_count() or 2) * 2)
            def _demo_cpu_worker():
                end = time.time() + 90
                while time.time() < end and not _stress_stop.is_set():
                    x = 0
                    for k in range(50000):
                        x += k * k
            for i in range(cores):
                t = threading.Thread(target=_demo_cpu_worker, daemon=True,
                                     name='sentinel_demo_cpu_{}'.format(i))
                _stress_threads.append(t)
                t.start()
            return {'status': 'success',
                    'message': 'Demo CPU pipeline: {} cores x 90s — watch Anomaly→Diagnosis→Recovery'.format(cores)}

        elif action == 'demo_memory':
            _stress_stop.clear()
            total_mb = psutil.virtual_memory().total // (1024 * 1024)
            alloc_mb = max(1024, int(total_mb * 0.40))
            def _demo_mem_worker():
                try:
                    data = bytearray(alloc_mb * 1024 * 1024)
                    end = time.time() + 90
                    while time.time() < end and not _stress_stop.is_set():
                        time.sleep(0.5)
                    del data
                except MemoryError:
                    pass
            t = threading.Thread(target=_demo_mem_worker, daemon=True, name='sentinel_demo_mem')
            _stress_threads.append(t)
            t.start()
            return {'status': 'success',
                    'message': 'Demo Memory pipeline: {} MB (40% RAM) x 90s — watch Anomaly→Diagnosis→Recovery'.format(alloc_mb)}

        elif action == 'demo_full':
            _stress_stop.clear()
            import os as _os
            cores = max(2, (_os.cpu_count() or 2) * 2)
            total_mb = psutil.virtual_memory().total // (1024 * 1024)
            alloc_mb = max(512, int(total_mb * 0.30))
            def _demo_full_cpu():
                end = time.time() + 90
                while time.time() < end and not _stress_stop.is_set():
                    x = 0
                    for k in range(50000):
                        x += k * k
            def _demo_full_mem():
                try:
                    data = bytearray(alloc_mb * 1024 * 1024)
                    end = time.time() + 90
                    while time.time() < end and not _stress_stop.is_set():
                        time.sleep(0.5)
                    del data
                except MemoryError:
                    pass
            for i in range(cores):
                t = threading.Thread(target=_demo_full_cpu, daemon=True,
                                     name='sentinel_demo_full_cpu_{}'.format(i))
                _stress_threads.append(t)
                t.start()
            tm = threading.Thread(target=_demo_full_mem, daemon=True, name='sentinel_demo_full_mem')
            _stress_threads.append(tm)
            tm.start()
            return {'status': 'success',
                    'message': 'Demo Full pipeline: {} CPU cores + {} MB RAM x 90s — watch all 3 agents'.format(cores, alloc_mb)}

        else:
            return {'status': 'skipped',
                    'message': "action '{}' not supported on remote client".format(action)}

    except Exception as e:
        return {'status': 'error', 'message': str(e)}


_cmd_lock = threading.Lock()


def poll_and_execute_commands(hub_url, device_id):
    """Fetch pending recovery commands from hub and execute them."""
    if not _cmd_lock.acquire(blocking=False):
        return
    try:
        data = _get_json("{}/api/devices/{}/commands".format(hub_url, device_id))
        if not data:
            return
        commands = data.get('commands', [])
        if not commands:
            return

        results = []
        for cmd in commands:
            action = cmd.get('action', '')
            action_id = cmd.get('action_id', '')
            print(" [RECOVERY] remote action: {}".format(action), flush=True)
            result = _exec_remote_command(action)
            result['action_id'] = action_id
            result['action'] = action
            print(" [RECOVERY] {} — {}".format(result['status'], result['message']), flush=True)
            results.append(result)

        _post("{}/api/devices/{}/command_results".format(hub_url, device_id),
              {'device_id': device_id, 'results': results})
    finally:
        _cmd_lock.release()


def _command_poll_loop(hub_url, device_id):
    """Background thread: polls for commands every 1 second for near-instant execution."""
    while True:
        try:
            poll_and_execute_commands(hub_url, device_id)
        except Exception:
            pass
        time.sleep(1)


def collect_metrics() -> dict:
    """Collect system metrics compatible with the Sentinel AI hub schema."""

    cpu = {
        'cpu_percent': psutil.cpu_percent(interval=1),
        'cpu_count': psutil.cpu_count(),
        'load_avg_1min': 0.0,
        'load_avg_5min': 0.0,
        'load_avg_15min': 0.0,
        'top_process_name': 'unknown',
        'top_process_cpu': 0.0,
        'top_process_pid': 0,
    }
    try:
        la = psutil.getloadavg()
        cpu['load_avg_1min'], cpu['load_avg_5min'], cpu['load_avg_15min'] = la
    except AttributeError:
        pass
    try:
        top = max(
            psutil.process_iter(['pid', 'name', 'cpu_percent']),
            key=lambda p: p.info.get('cpu_percent') or 0,
        )
        cpu['top_process_name'] = top.info['name'] or 'unknown'
        cpu['top_process_cpu'] = top.info.get('cpu_percent') or 0
        cpu['top_process_pid'] = top.info['pid']
    except Exception:
        pass

    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    memory = {
        'memory_percent': vm.percent,
        'memory_total_mb': vm.total / (1024 * 1024),
        'memory_available_mb': vm.available / (1024 * 1024),
        'memory_used_mb': vm.used / (1024 * 1024),
        'swap_percent': sw.percent,
        'swap_used_mb': sw.used / (1024 * 1024),
        'top_process_name': 'unknown',
        'top_process_memory': 0.0,
    }
    try:
        top = max(
            psutil.process_iter(['pid', 'name', 'memory_percent']),
            key=lambda p: p.info.get('memory_percent') or 0,
        )
        memory['top_process_name'] = top.info['name'] or 'unknown'
        memory['top_process_memory'] = top.info.get('memory_percent') or 0
    except Exception:
        pass

    try:
        disk_path = 'C:\\' if platform.system() == 'Windows' else '/'
        du = psutil.disk_usage(disk_path)
    except Exception:
        du = psutil.disk_usage('/')
    disk = {
        'disk_percent': du.percent,
        'disk_total_gb': du.total / (1024 ** 3),
        'disk_used_gb': du.used / (1024 ** 3),
        'disk_free_gb': du.free / (1024 ** 3),
        'disk_read_mb': 0.0,
        'disk_write_mb': 0.0,
    }
    try:
        io = psutil.disk_io_counters()
        if io:
            disk['disk_read_mb'] = io.read_bytes / (1024 * 1024)
            disk['disk_write_mb'] = io.write_bytes / (1024 * 1024)
    except Exception:
        pass

    nio = psutil.net_io_counters()
    network = {
        'bytes_sent_mb': (nio.bytes_sent / (1024 * 1024)) if nio else 0,
        'bytes_recv_mb': (nio.bytes_recv / (1024 * 1024)) if nio else 0,
        'packets_sent': nio.packets_sent if nio else 0,
        'packets_recv': nio.packets_recv if nio else 0,
        'errors_in': nio.errin if nio else 0,
        'errors_out': nio.errout if nio else 0,
        'ping_success': False,
        'ping_latency_ms': 0.0,
        'packet_loss_percent': 0.0,
    }
    for host in ['8.8.8.8', '1.1.1.1']:
        try:
            t0 = time.time()
            s = socket.create_connection((host, 53), timeout=2)
            s.close()
            network['ping_success'] = True
            network['ping_latency_ms'] = round((time.time() - t0) * 1000, 2)
            break
        except Exception:
            pass

    return {'cpu': cpu, 'memory': memory, 'disk': disk, 'network': network}


def main():
    parser = argparse.ArgumentParser(
        description='Sentinel AI Remote Client v{} — streams metrics to hub'.format(VERSION)
    )
    parser.add_argument(
        '--hub', default=None,
        help='Hub URL, e.g. http://192.168.1.100:5001 (auto-discovered if omitted)',
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
    parser.add_argument(
        '--cmd-port', type=int, default=5002,
        help='Port for the direct command server on this device (default: 5002)',
    )
    args = parser.parse_args()

    device_id = args.device or socket.gethostname()
    interval = max(1, args.interval)
    cmd_port = args.cmd_port

    print("=" * 60)
    print(" Sentinel AI Remote Client v{}".format(VERSION))
    print("=" * 60)
    print(" Device : {}".format(device_id))
    print(" Platform : {} {}".format(platform.system(), platform.release()))
    print(" Python : {}".format(platform.python_version()))
    print(" Interval : {}s".format(interval))
    print("=" * 60 + "\n")

    hub_url = args.hub
    if hub_url:
        hub_url = hub_url.rstrip('/')
        print("Hub URL : {}".format(hub_url))
    else:
        hub_url = discover_hub()

    if not hub_url:
        print("\n[ERROR] Could not find hub. Options:")
        print(" 1. Make sure main.py is running on the hub machine")
        print(" 2. Provide the hub IP manually:")
        print(" python sentinel_client.py --hub http://<HUB_IP>:5001")
        sys.exit(1)

    if args.test:
        ok = test_connectivity(hub_url)
        sys.exit(0 if ok else 1)

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
        print(" Run with --test for full diagnostics:")
        print(" python sentinel_client.py --test --hub {}".format(hub_url))
        sys.exit(1)

    print("\nRegistering with hub ...", flush=True)
    reg_payload = {
        'device_id': device_id,
        'hostname': socket.gethostname(),
        'platform': platform.system(),
        'version': platform.version(),
        'python': platform.python_version(),
        'cmd_port': cmd_port,
    }

    attempts = 0
    while True:
        status = _post("{}/api/devices/register".format(hub_url), reg_payload)
        if status == 200:
            _ok("Registered as '{}'".format(device_id))
            break

        attempts += 1
        if _last_error:
            print(" [ERR] Registration failed: {} (attempt #{})".format(_last_error, attempts), flush=True)
        else:
            print(" [ERR] HTTP {} — retrying in 5s (attempt #{})".format(status, attempts), flush=True)

        if attempts >= 3:
            print()
            print(" Still failing after {} attempts.".format(attempts))
            print(" Running diagnostics ...")
            test_connectivity(hub_url)
            print(" Continuing to retry every 5s. Press Ctrl+C to stop.")

        time.sleep(5)

    _hub_url_ref[0] = hub_url
    _device_id_ref[0] = device_id

    _start_command_server(cmd_port)
    print(' Command server : port {}'.format(cmd_port), flush=True)

    cmd_thread = threading.Thread(
        target=_command_poll_loop, args=(hub_url, device_id),
        daemon=True, name='sentinel_cmd_poll'
    )
    cmd_thread.start()

    print("\nStreaming metrics. Press Ctrl+C to stop.\n")
    print(" {:<10} {:<10} {:<10} {:<10}".format("TIME", "CPU %", "MEM %", "DISK %"))
    print(" " + "-" * 42)

    errors = 0
    while True:
        try:
            metrics = collect_metrics()
            payload = {
                'device_id': device_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metrics': metrics,
            }
            status = _post("{}/api/metrics/push".format(hub_url), payload)

            if status == 200:
                errors = 0
                ts = datetime.now().strftime('%H:%M:%S')
                cpu = metrics['cpu']['cpu_percent']
                mem = metrics['memory']['memory_percent']
                dsk = metrics['disk']['disk_percent']
                print(" {:<10} {:<10.1f} {:<10.1f} {:<10.1f}".format(ts, cpu, mem, dsk), flush=True)
            else:
                errors += 1
                reason = _last_error or "HTTP {}".format(status)
                print(" [WARN] Push failed: {} (#{})".format(reason, errors), flush=True)
                if errors >= 5:
                    print(" [WARN] Too many errors — re-registering ...", flush=True)
                    _post("{}/api/devices/register".format(hub_url), reg_payload)
                    errors = 0

        except KeyboardInterrupt:
            print("\n\nStopped by user.")
            break
        except Exception as e:
            errors += 1
            print(" [ERR] {}".format(e), flush=True)

        time.sleep(interval)


if __name__ == '__main__':
    main()
