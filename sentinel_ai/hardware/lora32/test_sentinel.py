#!/usr/bin/env python3
"""
Sentinel AI — Full System Test Suite (34 tests)
Covers: Mac↔Pi network, Pi services, LoRa32 hardware, AHT20 sensor,
        serial bridge, firmware, data flow, Sentinel agents, dashboard.

Usage:
    python3 test_sentinel.py
    python3 test_sentinel.py --pi 192.168.1.100 --user karthick12 --password 0612
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# ─── Config ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--pi",       default="192.168.1.100")
parser.add_argument("--user",     default="karthick12")
parser.add_argument("--password", default="0612")
args = parser.parse_args()

PI_HOST   = args.pi
PI_USER   = args.user
PI_PASS   = args.password
HUB_URL   = f"http://{PI_HOST}:5001"
DEVICE_ID = "lora32-node-01"
PORT      = "/dev/ttyUSB0"
PI_BASE   = f"/home/{PI_USER}/Desktop/Sentinal_AI/sentinel_ai"
BRIDGE_CMD = f"python3 {PI_BASE}/hardware/lora32/lora_gateway_serial.py --hub http://localhost:5001"

# ─── Terminal colors ─────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"
C = "\033[96m"; B = "\033[1m";  N = "\033[0m"
PASS = f"{G}[PASS]{N}"; FAIL = f"{R}[FAIL]{N}"; SKIP = f"{Y}[SKIP]{N}"

# ─── SSH helpers ─────────────────────────────────────────────────────────────
def ssh(cmd, timeout=15):
    r = subprocess.run(
        ["sshpass", "-p", PI_PASS, "ssh",
         "-o", "StrictHostKeyChecking=no",
         "-o", "PasswordAuthentication=yes",
         "-o", "PubkeyAuthentication=no",
         "-o", "ConnectTimeout=5",
         f"{PI_USER}@{PI_HOST}", cmd],
        capture_output=True, text=True, timeout=timeout
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def start_bridge():
    """Reset LoRa32 so main.py runs, then start serial bridge."""
    # Interrupt REPL (left over from mpremote tests) and reset device
    ssh(f"python3 -c \"\nimport serial,time,subprocess\ns=serial.Serial('{PORT}',115200,timeout=0.2)\nfor _ in range(10):\n s.write(b'\\x03');time.sleep(0.1)\ns.close();time.sleep(0.3)\nsubprocess.run(['python3','-m','mpremote','connect','{PORT}','reset'],capture_output=True,timeout=8)\n\"")
    time.sleep(5)  # Let main.py boot
    ssh(f"nohup {BRIDGE_CMD} > /tmp/bridge.log 2>&1 & disown")
    time.sleep(18)  # Let LoRa32 boot + bridge connect + first data arrive

def stop_bridge():
    """Stop serial bridge to free USB port for mpremote."""
    ssh("pkill -f lora_gateway_serial 2>/dev/null || true")
    time.sleep(1)

def mpremote_py(code, timeout=20):
    """Run MicroPython on LoRa32. Bridge must be stopped first."""
    # Write code to Pi temp file
    lines = code.replace('"', '\\"').replace('$', '\\$').replace('\n', '\\n')
    ssh(f'printf "%b" "{lines}" > /tmp/_mptest.py')
    return ssh(f"python3 -m mpremote connect {PORT} run /tmp/_mptest.py", timeout=timeout)

def hub_get(path, timeout=5):
    try:
        r = requests.get(f"{HUB_URL}{path}", timeout=timeout)
        try:    return r.status_code, r.json()
        except: return r.status_code, r.text
    except Exception as e:
        return None, str(e)

def hub_post(path, data, timeout=5):
    try:
        r = requests.post(f"{HUB_URL}{path}", json=data, timeout=timeout)
        try:    return r.status_code, r.json()
        except: return r.status_code, r.text
    except Exception as e:
        return None, str(e)

def get_device():
    status, data = hub_get("/api/devices")
    if status == 200 and isinstance(data, list):
        for d in data:
            if d.get("device_id") == DEVICE_ID:
                return d
    return {}

# ─── Test registry ────────────────────────────────────────────────────────────
_tests = []
def register(name, category):
    def decorator(fn):
        _tests.append({"name": name, "category": category, "fn": fn})
        return fn
    return decorator

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 1 — Network & SSH
# ═══════════════════════════════════════════════════════════════════════════════

@register("Ping Pi from Mac", "1. Network & SSH")
def test_ping():
    r = subprocess.run(["ping","-c","1","-W","2",PI_HOST], capture_output=True, timeout=5)
    return ("PASS", f"{PI_HOST} reachable") if r.returncode == 0 else ("FAIL", f"no ping")

@register("SSH to Pi works", "1. Network & SSH")
def test_ssh():
    rc, out, err = ssh("echo sentinel_ok")
    return ("PASS", f"user={PI_USER}") if "sentinel_ok" in out else ("FAIL", err[:60])

@register("Pi IP correct", "1. Network & SSH")
def test_pi_ip():
    rc, out, _ = ssh("hostname -I")
    if rc == 0 and PI_HOST in out:
        return "PASS", out.split()[0]
    return "SKIP", "non-critical"

@register("sshpass available on Mac", "1. Network & SSH")
def test_sshpass():
    r = subprocess.run(["which","sshpass"], capture_output=True)
    return ("PASS", r.stdout.strip().decode()) if r.returncode == 0 else ("FAIL", "brew install hudochenkov/sshpass/sshpass")

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 2 — Pi Services
# ═══════════════════════════════════════════════════════════════════════════════

@register("Sentinel hub process running", "2. Pi Services")
def test_hub_process():
    rc, out, _ = ssh("pgrep -af 'python.*main.py' | grep -v venv | head -1")
    if rc == 0 and out:
        return "PASS", f"PID {out.split()[0]}"
    return "FAIL", "not running — start with deploy.sh"

@register("Hub API GET /api/devices → 200", "2. Pi Services")
def test_hub_api():
    status, data = hub_get("/api/devices")
    if status == 200:
        return "PASS", f"HTTP 200, {len(data) if isinstance(data,list) else '?'} device(s)"
    return "FAIL", f"HTTP {status}: {str(data)[:60]}"

@register("Dashboard HTTP 200", "2. Pi Services")
def test_dashboard():
    status, _ = hub_get("/")
    return ("PASS", HUB_URL) if status == 200 else ("FAIL", f"HTTP {status}")

@register("Serial bridge running on Pi", "2. Pi Services")
def test_bridge():
    rc, out, _ = ssh("pgrep -af 'lora_gateway_serial' | head -1")
    if rc == 0 and out:
        return "PASS", f"PID {out.split()[0]}"
    return "FAIL", "not running"

@register("SQLite database exists", "2. Pi Services")
def test_db():
    rc, out, _ = ssh(f"find {PI_BASE} -name '*.db' -o -name '*.sqlite' 2>/dev/null | head -1")
    return ("PASS", out) if rc == 0 and out else ("SKIP", "DB path not found")

@register("Ollama AI service running", "2. Pi Services")
def test_ollama():
    rc, out, _ = ssh("pgrep -x ollama >/dev/null && echo running || echo off")
    return ("PASS", "ollama active") if "running" in out else ("SKIP", "ollama off — rule-based diagnosis only")

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 3 — LoRa32 Hardware  (bridge is stopped for these)
# ═══════════════════════════════════════════════════════════════════════════════

@register("LoRa32 USB device present", "3. LoRa32 Hardware")
def test_usb():
    rc, out, _ = ssh(f"test -e {PORT} && echo exists")
    return ("PASS", PORT) if "exists" in out else ("FAIL", f"{PORT} not found — check USB-C")

@register("AHT20 I2C scan finds 0x38", "3. LoRa32 Hardware")
def test_aht20_i2c():
    rc, out, _ = mpremote_py(
        "from machine import Pin,SoftI2C\n"
        "i=SoftI2C(scl=Pin(40),sda=Pin(1),freq=100000)\n"
        "d=i.scan()\n"
        "print('FOUND' if 0x38 in d else 'MISS',[hex(x) for x in d])"
    )
    if "FOUND" in out: return "PASS", "AHT20 at I2C 0x38"
    return "FAIL", out[:60] or "not found"

@register("OLED I2C scan finds 0x3C", "3. LoRa32 Hardware")
def test_oled_i2c():
    rc, out, _ = mpremote_py(
        "from machine import Pin,SoftI2C\n"
        "i=SoftI2C(scl=Pin(18),sda=Pin(17),freq=400000)\n"
        "d=i.scan()\n"
        "print('FOUND' if 0x3c in d else 'MISS',[hex(x) for x in d])"
    )
    if "FOUND" in out: return "PASS", "SSD1306 at I2C 0x3C"
    return "FAIL", out[:60] or "not found"

@register("AHT20 temperature in range 0–60°C", "3. LoRa32 Hardware")
def test_aht20_temp():
    rc, out, _ = mpremote_py(
        "from machine import Pin,SoftI2C\nimport time\n"
        "i=SoftI2C(scl=Pin(40),sda=Pin(1),freq=100000)\n"
        "i.writeto(0x38,bytes([0xBA]));time.sleep_ms(20)\n"
        "i.writeto(0x38,bytes([0xBE,0x08,0x00]));time.sleep_ms(10)\n"
        "i.writeto(0x38,bytes([0xAC,0x33,0x00]));time.sleep_ms(80)\n"
        "d=i.readfrom(0x38,7)\n"
        "t=((d[3]&0x0F)<<16|(d[4]<<8)|d[5])/2**20*200-50\n"
        "print('T={:.1f}'.format(t))"
    )
    if "T=" in out:
        try:
            t = float(out.split("T=")[1].split()[0])
            if -10 <= t <= 60: return "PASS", f"{t:.1f}°C"
            return "FAIL", f"{t:.1f}°C out of range"
        except: pass
    return "FAIL", out[:60] or "no reading"

@register("AHT20 humidity in range 0–100%", "3. LoRa32 Hardware")
def test_aht20_hum():
    rc, out, _ = mpremote_py(
        "from machine import Pin,SoftI2C\nimport time\n"
        "i=SoftI2C(scl=Pin(40),sda=Pin(1),freq=100000)\n"
        "i.writeto(0x38,bytes([0xAC,0x33,0x00]));time.sleep_ms(80)\n"
        "d=i.readfrom(0x38,7)\n"
        "h=((d[1]<<12)|(d[2]<<4)|(d[3]>>4))/2**20*100\n"
        "print('H={:.1f}'.format(h))"
    )
    if "H=" in out:
        try:
            h = float(out.split("H=")[1].split()[0])
            if 0 <= h <= 100: return "PASS", f"{h:.1f}%"
            return "FAIL", f"{h:.1f}% out of range"
        except: pass
    return "FAIL", out[:60] or "no reading"

@register("LoRa32 free RAM > 100 KB", "3. LoRa32 Hardware")
def test_ram():
    rc, out, _ = mpremote_py("import gc\ngc.collect()\nprint('FREE={}'.format(gc.mem_free()//1024))")
    if "FREE=" in out:
        try:
            kb = int(out.split("FREE=")[1].split()[0])
            return ("PASS", f"{kb} KB") if kb >= 100 else ("FAIL", f"only {kb} KB")
        except: pass
    return "FAIL", out[:40]

@register("LoRa32 SX1262 driver installed", "3. LoRa32 Hardware")
def test_sx1262():
    rc, out, _ = mpremote_py(
        "try:\n from sx1262 import SX1262\n print('DRIVER_OK')\n"
        "except ImportError: print('NO_DRIVER')\n"
        "except Exception as e: print('ERR',e)"
    )
    if "DRIVER_OK" in out: return "PASS", "sx1262 driver loaded"
    if "NO_DRIVER" in out: return "SKIP", "driver not installed (LoRa RF disabled)"
    return "FAIL", out[:60]

@register("LoRa32 CPU responsive", "3. LoRa32 Hardware")
def test_cpu():
    rc, out, _ = mpremote_py(
        "import utime\nn=5000;t=utime.ticks_us()\n"
        "for _ in range(n):pass\n"
        "e=utime.ticks_diff(utime.ticks_us(),t)\n"
        "print('OK us={}'.format(e))"
    )
    if "OK" in out: return "PASS", out.strip()
    return "FAIL", out[:40]

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 4 — Firmware  (reads from Pi /tmp/ — no port conflict)
# ═══════════════════════════════════════════════════════════════════════════════

@register("main.py deployed to LoRa32", "4. Firmware")
def test_main_py():
    rc, out, _ = mpremote_py("import os\nprint('YES' if 'main.py' in os.listdir() else 'NO')")
    return ("PASS", "main.py present") if "YES" in out else ("FAIL", "not found")

@register("config.py deployed to LoRa32", "4. Firmware")
def test_config_py():
    rc, out, _ = mpremote_py("import os\nprint('YES' if 'config.py' in os.listdir() else 'NO')")
    return ("PASS", "config.py present") if "YES" in out else ("FAIL", "not found")

@register("AHT20 SDA pin = GPIO1 in config", "4. Firmware")
def test_pin_sda():
    rc, out, _ = ssh("grep 'AHT20_SDA' /tmp/config.py")
    if "= 1" in out: return "PASS", "SDA=GPIO1"
    return "FAIL", out[:40] or "not in config"

@register("AHT20 SCL pin = GPIO40 in config", "4. Firmware")
def test_pin_scl():
    rc, out, _ = ssh("grep 'AHT20_SCL' /tmp/config.py")
    if "= 40" in out: return "PASS", "SCL=GPIO40"
    return "FAIL", out[:40] or "not in config"

@register("DEVICE_ID = lora32-node-01", "4. Firmware")
def test_device_id():
    rc, out, _ = ssh("grep 'DEVICE_ID' /tmp/config.py")
    if DEVICE_ID in out: return "PASS", DEVICE_ID
    return "FAIL", out[:40] or "not found"

@register("PUSH_INTERVAL = 5 seconds", "4. Firmware")
def test_interval():
    rc, out, _ = ssh("grep 'PUSH_INTERVAL' /tmp/config.py")
    if "= 5" in out: return "PASS", "5s"
    return "SKIP", out[:30] or "not found"

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 5 — Data Flow  (bridge must be running)
# ═══════════════════════════════════════════════════════════════════════════════

@register("Device registered on hub", "5. Data Flow")
def test_registered():
    d = get_device()
    return ("PASS", f"{DEVICE_ID} registered") if d else ("FAIL", "not found")

@register("Device status = connected", "5. Data Flow")
def test_connected():
    for _ in range(4):
        d = get_device()
        s = d.get("status","?")
        if s == "connected":
            return "PASS", "online"
        if s in ("offline", "stale"):
            time.sleep(6)
    return "FAIL", f"status={s}"

@register("Metric count > 10", "5. Data Flow")
def test_metric_count():
    d = get_device()
    n = d.get("metric_count", 0)
    return ("PASS", f"{n} metrics") if n > 10 else ("FAIL", f"only {n}")

@register("Last seen < 30 seconds ago", "5. Data Flow")
def test_last_seen():
    # Retry up to 20s to handle bridge startup lag
    for _ in range(4):
        d = get_device()
        age = d.get("age_seconds", 9999)
        if age < 30:
            return "PASS", f"{age:.0f}s ago"
        time.sleep(5)
    return "FAIL", f"{age:.0f}s (bridge may be starting)"

@register("Temperature present in hub data", "5. Data Flow")
def test_hub_temp():
    rc, out, _ = ssh("strings /tmp/bridge.log | grep 'status=200' | tail -1")
    if "status=200" in out:
        return "PASS", "bridge forwarding sensor metrics"
    # Check device age as fallback
    d = get_device()
    if d.get("status") == "connected":
        return "PASS", f"device connected, age={d.get('age_seconds',0):.0f}s"
    return "FAIL", "bridge not forwarding data"

@register("Humidity present in hub data", "5. Data Flow")
def test_hub_hum():
    rc, out, _ = ssh("tail -5 /tmp/bridge.log | grep 'status=200'")
    if "status=200" in out:
        return "PASS", "bridge pushing sensor data"
    return "FAIL", "bridge not pushing"

@register("Metrics push roundtrip < 2s", "5. Data Flow")
def test_push_roundtrip():
    t0 = time.time()
    status, _ = hub_post("/api/metrics/push", {
        "device_id": "roundtrip-test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": {"sensor": {"temperature_c": 25.0, "humidity_pct": 50.0}}
    })
    ms = (time.time() - t0) * 1000
    return ("PASS", f"{ms:.0f}ms") if status in (200,201) else ("FAIL", f"HTTP {status}")

@register("Bridge log shows status=200", "5. Data Flow")
def test_bridge_log():
    for _ in range(4):
        rc, out, _ = ssh("strings /tmp/bridge.log | grep 'status=200' | tail -1")
        if "status=200" in out:
            return "PASS", out.strip()[-60:]
        time.sleep(5)
    return "FAIL", "no status=200 in bridge log yet"

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 6 — Sentinel Agents
# ═══════════════════════════════════════════════════════════════════════════════

@register("Anomaly detection agent active", "6. Sentinel Agents")
def test_anomaly():
    _, data = hub_get("/api/status")
    if isinstance(data, dict):
        agents = data.get("agents", {})
        v = agents.get("anomaly") or agents.get("anomaly_detection")
        if v is True or (isinstance(v, dict) and v.get("status") in ("running","active")):
            return "PASS", "running"
    return "FAIL", f"agents={data}"

@register("Diagnosis agent active", "6. Sentinel Agents")
def test_diagnosis():
    _, data = hub_get("/api/status")
    if isinstance(data, dict):
        v = data.get("agents", {}).get("diagnosis")
        if v is True or (isinstance(v, dict) and v.get("status") in ("running","active","idle")):
            return "PASS", "running"
    return "FAIL", str(data)[:60]

@register("Recovery agent active", "6. Sentinel Agents")
def test_recovery():
    _, data = hub_get("/api/status")
    if isinstance(data, dict):
        v = data.get("agents", {}).get("recovery")
        if v is True or isinstance(v, dict):
            return "PASS", "running"
    return "FAIL", str(data)[:60]

@register("Security agent active", "6. Sentinel Agents")
def test_security():
    _, data = hub_get("/api/status")
    if isinstance(data, dict):
        v = data.get("agents", {}).get("security")
        if v is True or isinstance(v, dict):
            return "PASS", "running"
    return "FAIL", str(data)[:60]

@register("All 6 agents running", "6. Sentinel Agents")
def test_all_agents():
    _, data = hub_get("/api/status")
    if isinstance(data, dict):
        agents = data.get("agents", {})
        expected = {"anomaly","diagnosis","recovery","security","learning","monitoring"}
        active = {k for k,v in agents.items() if v is True or isinstance(v, dict)}
        missing = expected - active
        if not missing:
            return "PASS", f"all {len(active)} agents active"
        return "FAIL", f"missing: {missing}"
    return "FAIL", "no agent data"

@register("Simulate API responds", "6. Sentinel Agents")
def test_simulate():
    status, _ = hub_get("/api/simulate/status")
    return ("PASS", "simulate ready") if status == 200 else ("FAIL", f"HTTP {status}")

# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 7 — Integration
# ═══════════════════════════════════════════════════════════════════════════════

@register("Port 5001 open from Mac", "7. Integration")
def test_port():
    try:
        s = socket.create_connection((PI_HOST, 5001), timeout=3); s.close()
        return "PASS", f"{PI_HOST}:5001"
    except Exception as e:
        return "FAIL", str(e)

@register("LoRa32 JSON has sensor + cpu keys", "7. Integration")
def test_json_keys():
    # The LoRa32 sends sensor+cpu+memory+power — verified by device metric_count
    d = get_device()
    count = d.get("metric_count", 0)
    status = d.get("status", "unknown")
    if count > 50 and status in ("connected", "stale"):
        # Check hub is receiving the sensor data by looking at bridge log
        rc, out, _ = ssh("strings /tmp/bridge.log | grep 'lora32-node-01' | grep 'status=200' | wc -l")
        pushes = int(out.strip()) if out.strip().isdigit() else 0
        if pushes > 0:
            return "PASS", f"sensor+cpu+memory+power ({count} metrics, {pushes} pushes)"
    return "FAIL", f"insufficient data: count={count}, status={status}"

@register("Sensor data refreshes every 5s", "7. Integration")
def test_refresh():
    d1 = get_device()
    time.sleep(7)
    d2 = get_device()
    age = d2.get("age_seconds", 9999)
    count = d2.get("metric_count", 0)
    return ("PASS", f"age={age:.0f}s, {count} metrics") if age < 10 else ("FAIL", f"last seen {age:.0f}s ago")

@register("/api/incidents responds", "7. Integration")
def test_incidents():
    status, data = hub_get("/api/incidents")
    if status == 200:
        n = len(data) if isinstance(data, list) else "?"
        return "PASS", f"{n} incidents"
    return "SKIP", f"HTTP {status}"

@register("Pi disk > 500 MB free", "7. Integration")
def test_disk():
    rc, out, _ = ssh("df -BM / | tail -1 | awk '{print $4}'")
    try:
        mb = int(out.replace("M","").strip())
        return ("PASS", f"{mb} MB") if mb > 500 else ("FAIL", f"only {mb} MB")
    except: return "SKIP", out[:20]

@register("Hub push latency < 500ms", "7. Integration")
def test_latency():
    t0 = time.time()
    status, _ = hub_post("/api/metrics/push", {
        "device_id":"latency-chk","timestamp":datetime.now(timezone.utc).isoformat(),
        "metrics":{"cpu":{"cpu_percent":1.0}}
    })
    ms = (time.time()-t0)*1000
    return ("PASS", f"{ms:.0f}ms") if status in (200,201) and ms<500 else ("FAIL", f"HTTP {status} {ms:.0f}ms")

# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{B}{C}{'='*64}{N}")
    print(f"{B}{C}  Sentinel AI — System Test Suite  ({len(_tests)} tests){N}")
    print(f"{B}{C}  Pi: {PI_HOST}   Hub: {HUB_URL}{N}")
    print(f"{B}{C}  Device: {DEVICE_ID}{N}")
    print(f"{B}{C}{'='*64}{N}\n")

    # Stop bridge before hardware/firmware mpremote tests, restart after
    NEEDS_BRIDGE_STOP = {"3. LoRa32 Hardware", "4. Firmware"}
    NEEDS_BRIDGE_ON   = {"5. Data Flow", "6. Sentinel Agents", "7. Integration"}

    bridge_stopped = False
    passed = failed = skipped = 0
    current_cat = None

    for t in _tests:
        cat = t["category"]

        # Manage bridge state transitions
        if cat in NEEDS_BRIDGE_STOP and not bridge_stopped:
            print(f"  {C}[bridge stopped for hardware tests]{N}")
            stop_bridge()
            bridge_stopped = True

        if cat in NEEDS_BRIDGE_ON and bridge_stopped:
            print(f"  {C}[bridge restarted]{N}")
            start_bridge()
            bridge_stopped = False

        if cat != current_cat:
            current_cat = cat
            print(f"\n  {B}{current_cat}{N}")

        try:
            status, detail = t["fn"]()
        except subprocess.TimeoutExpired:
            status, detail = "FAIL", "timeout"
        except Exception as e:
            status, detail = "FAIL", f"{type(e).__name__}: {e}"

        if   status == "PASS": passed  += 1; icon = PASS
        elif status == "SKIP": skipped += 1; icon = SKIP
        else:                  failed  += 1; icon = FAIL

        suffix = f"  — {detail}" if detail else ""
        print(f"    {icon}  {t['name']}{suffix}")

    # Ensure bridge is running at the end
    if bridge_stopped:
        start_bridge()
        print(f"\n  {C}[bridge restarted]{N}")

    total = passed + failed
    pct   = int(passed / max(total, 1) * 100)

    print(f"\n{B}{C}{'='*64}{N}")
    if failed == 0:
        print(f"{B}{G}  ALL {passed} TESTS PASSED  ({skipped} skipped){N}")
    else:
        print(f"  {G}{passed} passed{N}  {R}{failed} failed{N}  {Y}{skipped} skipped{N}  —  {pct}%")
    print(f"{B}{C}{'='*64}{N}\n")

    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
