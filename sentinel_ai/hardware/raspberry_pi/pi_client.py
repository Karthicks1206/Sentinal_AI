#!/usr/bin/env python3
"""
Sentinel AI — Raspberry Pi Client
==================================
Runs on the Pi. Streams system + hardware sensor metrics to the hub.

Monitors:
  • System — CPU, RAM, disk, network (full sentinel schema)
  • Pi SoC temperature — /sys/class/thermal/thermal_zone0/temp
  • DHT11/DHT22 — temperature + humidity via GPIO
  • Motor (L298N) — enable / forward / reverse state via GPIO
  • I2C bus scan — logged once at startup

Transport: HTTP POST to hub (same /api/metrics/push as sentinel_client.py)
Commands:  Queue-based polling (cmd_port=0 — no inbound TCP needed)

Usage:
    python pi_client.py                          # uses config.py
    python pi_client.py --hub http://x.x.x.x:5001
    python pi_client.py --test                   # connectivity check only
"""

import argparse
import json
import logging
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import psutil
import requests

import config as cfg

logging.basicConfig(
    format="%(asctime)s [pi-client] %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pi_client")

_running = True


def _stop(sig, frame):
    global _running
    log.info("Shutting down...")
    _running = False


signal.signal(signal.SIGINT,  _stop)
signal.signal(signal.SIGTERM, _stop)


# ═════════════════════════════════════════════════════════════════════════════
# GPIO helpers — supports Pi 3/4/5 (gpiozero → lgpio on Pi 5 automatically)
# ═════════════════════════════════════════════════════════════════════════════

def _gpio_read_pin(pin: int) -> bool:
    """Read a single BCM GPIO pin. Returns False on any error."""
    try:
        from gpiozero import Button
        b = Button(pin, pull_up=False)
        val = b.is_pressed
        b.close()
        return val
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════════════
# DHT22 / DHT11
# ═════════════════════════════════════════════════════════════════════════════

_dht_sensor  = None
_dht_ok      = False
_dht_lock    = threading.Lock()
_dht_last    = {}     # cached last good reading

def _init_dht():
    global _dht_sensor, _dht_ok
    if not cfg.DHT_ENABLED:
        return
    try:
        import board
        import adafruit_dht

        _BCM_TO_BOARD = {
            4:  board.D4,  17: board.D17, 18: board.D18, 27: board.D27,
            22: board.D22, 23: board.D23, 24: board.D24, 25: board.D25,
            5:  board.D5,  6:  board.D6,  12: board.D12, 13: board.D13,
            16: board.D16, 19: board.D19, 20: board.D20, 21: board.D21,
            26: board.D26, 2:  board.D2,  3:  board.D3,
        }
        bp = _BCM_TO_BOARD.get(cfg.DHT_PIN)
        if bp is None:
            log.warning("DHT: BCM pin %d not mapped — add it to _BCM_TO_BOARD", cfg.DHT_PIN)
            return

        cls = adafruit_dht.DHT22 if cfg.DHT_TYPE == "DHT22" else adafruit_dht.DHT11
        _dht_sensor = cls(bp, use_pulseio=False)
        _dht_ok = True
        log.info("DHT sensor: %s on GPIO%d ready", cfg.DHT_TYPE, cfg.DHT_PIN)
    except ImportError:
        log.warning("adafruit-circuitpython-dht not installed — DHT disabled")
        log.warning("  pip install adafruit-circuitpython-dht && sudo apt install -y libgpiod2")
    except Exception as e:
        log.warning("DHT init failed: %s", e)


def _read_dht() -> dict:
    """Return temperature_c / humidity_pct. Returns cached on error, zeros on first failure."""
    global _dht_last
    if not _dht_ok or _dht_sensor is None:
        return {}
    with _dht_lock:
        for attempt in range(3):
            try:
                t = _dht_sensor.temperature
                h = _dht_sensor.humidity
                if t is not None and h is not None and -40 <= t <= 80 and 0 <= h <= 100:
                    _dht_last = {
                        'temperature_c': round(float(t), 1),
                        'humidity_pct':  round(float(h), 1),
                    }
                    return _dht_last
            except RuntimeError:
                # DHT sensors routinely throw RuntimeError — retry silently
                time.sleep(0.5)
            except Exception as e:
                log.debug("DHT read error: %s", e)
                break
        return _dht_last   # return last good reading on failure


# ═════════════════════════════════════════════════════════════════════════════
# Motor GPIO
# ═════════════════════════════════════════════════════════════════════════════

def _read_motor() -> dict:
    if not cfg.MOTOR_ENABLED:
        return {}
    en  = _gpio_read_pin(cfg.MOTOR_ENABLE_PIN)
    in1 = _gpio_read_pin(cfg.MOTOR_IN1_PIN)
    in2 = _gpio_read_pin(cfg.MOTOR_IN2_PIN)
    return {
        'motor_enabled': en,
        'motor_forward': en and in1 and not in2,
        'motor_reverse': en and in2 and not in1,
        'motor_stopped': en and (in1 == in2),
    }


# ═════════════════════════════════════════════════════════════════════════════
# Pi SoC temperature
# ═════════════════════════════════════════════════════════════════════════════

def _pi_cpu_temp() -> float:
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        return 0.0


# ═════════════════════════════════════════════════════════════════════════════
# I2C bus scan — logged once at startup
# ═════════════════════════════════════════════════════════════════════════════

_KNOWN_I2C = {
    0x27: 'LCD(PCF8574)', 0x3C: 'OLED(SSD1306)', 0x3D: 'OLED(SSD1306)',
    0x38: 'AHT20',        0x40: 'INA219',         0x44: 'SHT30',
    0x48: 'ADS1115',      0x5C: 'AM2320',          0x68: 'MPU6050/DS3231',
    0x76: 'BME280',       0x77: 'BME280',
}

def _scan_i2c():
    try:
        import smbus2
        bus   = smbus2.SMBus(1)
        found = []
        for addr in range(0x03, 0x78):
            try:
                bus.read_byte(addr)
                found.append(addr)
            except Exception:
                pass
        bus.close()
        if found:
            labels = [_KNOWN_I2C.get(a, '0x{:02X}'.format(a)) for a in found]
            log.info("I2C devices found: %s", ', '.join(labels))
        else:
            log.info("I2C scan: no devices found (is I2C enabled? sudo raspi-config)")
    except ImportError:
        log.info("smbus2 not installed — I2C scan skipped (pip install smbus2)")
    except Exception as e:
        log.debug("I2C scan error: %s", e)


# ═════════════════════════════════════════════════════════════════════════════
# System metrics — same schema as sentinel_client.py
# ═════════════════════════════════════════════════════════════════════════════

def _collect_system() -> dict:
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
        pass
    try:
        top = max(psutil.process_iter(['pid', 'name', 'cpu_percent']),
                  key=lambda p: p.info.get('cpu_percent') or 0)
        cpu['top_process_name'] = top.info['name'] or 'unknown'
        cpu['top_process_cpu']  = top.info.get('cpu_percent') or 0
        cpu['top_process_pid']  = top.info['pid']
    except Exception:
        pass

    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    memory = {
        'memory_percent':      vm.percent,
        'memory_total_mb':     vm.total / (1024 * 1024),
        'memory_available_mb': vm.available / (1024 * 1024),
        'memory_used_mb':      vm.used / (1024 * 1024),
        'swap_percent':        sw.percent,
        'swap_used_mb':        sw.used / (1024 * 1024),
        'top_process_name':    'unknown',
        'top_process_memory':  0.0,
    }
    try:
        top = max(psutil.process_iter(['pid', 'name', 'memory_percent']),
                  key=lambda p: p.info.get('memory_percent') or 0)
        memory['top_process_name']   = top.info['name'] or 'unknown'
        memory['top_process_memory'] = top.info.get('memory_percent') or 0
    except Exception:
        pass

    du = psutil.disk_usage('/')
    disk = {
        'disk_percent':  du.percent,
        'disk_total_gb': du.total / (1024 ** 3),
        'disk_used_gb':  du.used / (1024 ** 3),
        'disk_free_gb':  du.free / (1024 ** 3),
        'disk_read_mb':  0.0,
        'disk_write_mb': 0.0,
    }
    try:
        io = psutil.disk_io_counters()
        if io:
            disk['disk_read_mb']  = io.read_bytes / (1024 * 1024)
            disk['disk_write_mb'] = io.write_bytes / (1024 * 1024)
    except Exception:
        pass

    nio = psutil.net_io_counters()
    network = {
        'bytes_sent_mb':       (nio.bytes_sent / (1024 * 1024)) if nio else 0,
        'bytes_recv_mb':       (nio.bytes_recv / (1024 * 1024)) if nio else 0,
        'packets_sent':        nio.packets_sent if nio else 0,
        'packets_recv':        nio.packets_recv if nio else 0,
        'errors_in':           nio.errin if nio else 0,
        'errors_out':          nio.errout if nio else 0,
        'ping_success':        False,
        'ping_latency_ms':     0.0,
        'packet_loss_percent': 0.0,
    }
    for host in ['8.8.8.8', '1.1.1.1']:
        try:
            t0 = time.time()
            s = socket.create_connection((host, 53), timeout=2)
            s.close()
            network['ping_success']    = True
            network['ping_latency_ms'] = round((time.time() - t0) * 1000, 2)
            break
        except Exception:
            pass

    return {'cpu': cpu, 'memory': memory, 'disk': disk, 'network': network}


def _collect_sensor() -> dict:
    """Merge all hardware readings into the `sensor` key the dashboard expects."""
    sensor: dict = {}

    pi_temp = _pi_cpu_temp()
    if pi_temp > 0:
        sensor['pi_cpu_temp_c'] = pi_temp

    sensor.update(_read_dht())
    sensor.update(_read_motor())

    return sensor


# ═════════════════════════════════════════════════════════════════════════════
# Hub registration + metric push
# ═════════════════════════════════════════════════════════════════════════════

def _register(hub_url: str, device_id: str) -> bool:
    try:
        r = requests.post(
            hub_url.rstrip('/') + '/api/devices/register',
            json={
                'device_id': device_id,
                'hostname':  socket.gethostname(),
                'platform':  'Raspberry Pi — ' + platform.release(),
                'version':   platform.version(),
                'python':    platform.python_version(),
                'cmd_port':  0,   # queue-based commands only — no inbound TCP needed
            },
            timeout=6,
        )
        return r.status_code == 200
    except requests.RequestException as e:
        log.warning("Registration error: %s", e)
        return False


def _push(hub_url: str, device_id: str, metrics: dict) -> bool:
    try:
        r = requests.post(
            hub_url.rstrip('/') + '/api/metrics/push',
            json={
                'device_id': device_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metrics':   metrics,
            },
            timeout=6,
        )
        return r.status_code == 200
    except requests.RequestException as e:
        log.warning("Push failed: %s", e)
        return False


# ═════════════════════════════════════════════════════════════════════════════
# Recovery command execution (Pi-side actions)
# ═════════════════════════════════════════════════════════════════════════════

_OWN_PID = None
_CRITICAL_PROCS = {
    'systemd', 'init', 'cron', 'journald', 'dbus', 'udevd',
    'python', 'python3', 'sshd', 'NetworkManager',
}


def _exec_action(action: str) -> dict:
    own = _OWN_PID or 0

    def _safe_kill(proc):
        if proc.pid == own:
            return False, "protected: self"
        if (proc.name() or '').lower() in _CRITICAL_PROCS:
            return False, "protected: {}".format(proc.name())
        try:
            proc.kill()
            return True, "killed {} (pid {})".format(proc.name(), proc.pid)
        except Exception as e:
            return False, str(e)

    try:
        if action == 'kill_top_cpu_process':
            procs = sorted(psutil.process_iter(['pid', 'name', 'cpu_percent']),
                           key=lambda p: p.info.get('cpu_percent') or 0, reverse=True)
            for proc in procs:
                ok, msg = _safe_kill(proc)
                if ok:
                    return {'status': 'success', 'message': msg}
            return {'status': 'skipped', 'message': 'no killable high-CPU process'}

        elif action == 'kill_top_memory_process':
            procs = sorted(psutil.process_iter(['pid', 'name', 'memory_percent']),
                           key=lambda p: p.info.get('memory_percent') or 0, reverse=True)
            for proc in procs:
                ok, msg = _safe_kill(proc)
                if ok:
                    return {'status': 'success', 'message': msg}
            return {'status': 'skipped', 'message': 'no killable high-memory process'}

        elif action in ('compact_memory', 'clear_cache', 'algorithmic_memory_fix'):
            subprocess.run(['sync'], capture_output=True, timeout=5)
            return {'status': 'success', 'message': 'sync flushed page cache'}

        elif action in ('emergency_disk_cleanup', 'rotate_logs', 'algorithmic_disk_fix'):
            import glob, tempfile, os as _os
            removed = 0
            for f in (glob.glob(_os.path.join(tempfile.gettempdir(), '*.tmp')) +
                      glob.glob(_os.path.join(tempfile.gettempdir(), '*.log'))):
                try:
                    _os.remove(f)
                    removed += 1
                except Exception:
                    pass
            return {'status': 'success', 'message': 'removed {} temp files'.format(removed)}

        elif action in ('flush_dns', 'algorithmic_network_fix'):
            try:
                subprocess.run(['systemd-resolve', '--flush-caches'],
                               capture_output=True, timeout=5)
            except Exception:
                pass
            return {'status': 'success', 'message': 'DNS flush attempted'}

        elif action in ('check_network', 'reset_network_interface'):
            results = []
            for host in ['8.8.8.8', '1.1.1.1']:
                try:
                    t0 = time.time()
                    s = socket.create_connection((host, 53), timeout=3)
                    s.close()
                    results.append('{}={:.0f}ms'.format(host, (time.time()-t0)*1000))
                except Exception:
                    results.append('{}=unreachable'.format(host))
            return {'status': 'success', 'message': ', '.join(results)}

        elif action in ('reconnect_sensor', 'restart_service', 'restart_mqtt'):
            return {'status': 'success', 'message': '{}: no managed services on this Pi'.format(action)}

        elif action == 'full_system_restart':
            return {'status': 'skipped', 'message': 'full_system_restart blocked for safety'}

        elif action == 'algorithmic_cpu_fix':
            procs = sorted(psutil.process_iter(['pid', 'name', 'cpu_percent']),
                           key=lambda p: p.info.get('cpu_percent') or 0, reverse=True)
            for proc in procs:
                if proc.pid == own:
                    continue
                if (proc.name() or '').lower() in _CRITICAL_PROCS:
                    continue
                try:
                    subprocess.run(['renice', '+10', '-p', str(proc.pid)],
                                   capture_output=True, timeout=5)
                    return {'status': 'success',
                            'message': 'reniced {} (pid {}) +10'.format(proc.name(), proc.pid)}
                except Exception:
                    pass
            return {'status': 'skipped', 'message': 'no suitable process to renice'}

        else:
            return {'status': 'skipped',
                    'message': "action '{}' not handled on Pi".format(action)}

    except Exception as e:
        return {'status': 'error', 'message': str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# Command poll loop — polls hub queue every 1 s, executes, posts results
# ═════════════════════════════════════════════════════════════════════════════

_cmd_lock = threading.Lock()


def _poll_and_run(hub_url: str, device_id: str):
    if not _cmd_lock.acquire(blocking=False):
        return
    try:
        resp = requests.get(
            '{}/api/devices/{}/commands'.format(hub_url, device_id), timeout=3)
        if resp.status_code != 200:
            return
        commands = resp.json().get('commands', [])
        if not commands:
            return
        results = []
        for cmd in commands:
            action    = cmd.get('action', '')
            action_id = cmd.get('action_id', '')
            log.info("[CMD] %s", action)
            result = _exec_action(action)
            result['action_id'] = action_id
            result['action']    = action
            log.info("[CMD] %s — %s", result['status'], result['message'])
            results.append(result)
        requests.post(
            '{}/api/devices/{}/command_results'.format(hub_url, device_id),
            json={'device_id': device_id, 'results': results},
            timeout=5,
        )
    except Exception as e:
        log.debug("Command poll error: %s", e)
    finally:
        _cmd_lock.release()


def _cmd_poll_loop(hub_url: str, device_id: str):
    while _running:
        try:
            _poll_and_run(hub_url, device_id)
        except Exception:
            pass
        time.sleep(1)


# ═════════════════════════════════════════════════════════════════════════════
# Connectivity test
# ═════════════════════════════════════════════════════════════════════════════

def test_connectivity(hub_url: str) -> bool:
    from urllib.parse import urlparse
    p = urlparse(hub_url)
    host, port = p.hostname, p.port or 5001
    print("\n" + "=" * 55)
    print(" Connectivity Test")
    print("=" * 55)

    print(" Step 1 — TCP {}:{}".format(host, port))
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        print("   OK — port open")
    except Exception as e:
        print("   FAIL — {} ".format(e))
        print("   Is main.py running on the Mac? Check firewall.")
        return False

    print(" Step 2 — GET /api/status")
    try:
        r = requests.get(hub_url.rstrip('/') + '/api/status', timeout=5)
        status = r.json().get('system_status', '?')
        print("   OK — hub status: {}".format(status))
    except Exception as e:
        print("   FAIL — {}".format(e))
        return False

    print("\n All checks passed!\n" + "=" * 55 + "\n")
    return True


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════

def main():
    global _OWN_PID
    _OWN_PID = __import__('os').getpid()

    parser = argparse.ArgumentParser(
        description='Sentinel AI — Raspberry Pi Client')
    parser.add_argument('--hub',      default=cfg.HUB_URL,
                        help='Hub URL (default from config.py)')
    parser.add_argument('--device',   default=cfg.DEVICE_ID,
                        help='Device name (default from config.py)')
    parser.add_argument('--interval', type=int, default=cfg.PUSH_INTERVAL,
                        help='Push interval seconds')
    parser.add_argument('--test',     action='store_true',
                        help='Connectivity test only')
    args = parser.parse_args()

    hub_url   = args.hub.rstrip('/')
    device_id = args.device
    interval  = max(1, args.interval)

    print("=" * 55)
    print(" Sentinel AI — Raspberry Pi Client")
    print("=" * 55)
    print(" Device  : {}".format(device_id))
    print(" Hub     : {}".format(hub_url))
    print(" Interval: {}s".format(interval))
    print("=" * 55)

    if args.test:
        sys.exit(0 if test_connectivity(hub_url) else 1)

    # ── hardware init ─────────────────────────────────────────────────────────
    print("\nInitialising hardware...")
    _init_dht()
    _scan_i2c()
    t = _pi_cpu_temp()
    log.info("Pi SoC temperature: %.1f °C", t)

    # ── register with hub ─────────────────────────────────────────────────────
    print("\nConnecting to hub...")
    attempt = 0
    while _running:
        attempt += 1
        if _register(hub_url, device_id):
            log.info("Registered as '%s'", device_id)
            break
        log.warning("Registration failed (attempt %d) — retrying in 5s", attempt)
        if attempt == 3:
            log.warning("Still failing — running connectivity test...")
            test_connectivity(hub_url)
        time.sleep(5)

    # ── start command poller ──────────────────────────────────────────────────
    threading.Thread(
        target=_cmd_poll_loop, args=(hub_url, device_id),
        daemon=True, name='sentinel_cmd_poll',
    ).start()

    # ── main loop ─────────────────────────────────────────────────────────────
    print("\nStreaming. Press Ctrl+C to stop.\n")
    print(" {:<10} {:<7} {:<7} {:<7} {:<8} {:<8} {:<7}".format(
          "TIME", "CPU%", "MEM%", "DISK%", "SoC°C", "T°C", "H%"))
    print(" " + "-" * 60)

    ok_count = fail_count = 0

    while _running:
        try:
            system = _collect_system()
            sensor = _collect_sensor()

            metrics = dict(system)
            if sensor:
                metrics['sensor'] = sensor

            ok = _push(hub_url, device_id, metrics)

            if ok:
                ok_count   += 1
                fail_count  = 0
                ts    = datetime.now().strftime('%H:%M:%S')
                cpu   = system['cpu']['cpu_percent']
                mem   = system['memory']['memory_percent']
                dsk   = system['disk']['disk_percent']
                soc   = sensor.get('pi_cpu_temp_c', 0.0)
                temp  = sensor.get('temperature_c', 0.0)
                hum   = sensor.get('humidity_pct', 0.0)
                print(" {:<10} {:<7.1f} {:<7.1f} {:<7.1f} {:<8.1f} {:<8.1f} {:<7.1f}".format(
                      ts, cpu, mem, dsk, soc, temp, hum), flush=True)
            else:
                fail_count += 1
                log.warning("Push failed (#%d)", fail_count)
                if fail_count >= 5:
                    log.warning("Too many failures — re-registering...")
                    _register(hub_url, device_id)
                    fail_count = 0

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("Loop error: %s", e)

        time.sleep(interval)

    log.info("Stopped. Pushed %d packets.", ok_count)


if __name__ == '__main__':
    main()
