#!/usr/bin/env python3
"""
Sentinel AI — ESP Serial Bridge
=================================
Runs on the Raspberry Pi alongside pi_client.py.
Reads JSON metric packets from an ESP8266/ESP32 over USB serial,
registers the ESP as a separate device on the hub, and forwards data.

Also polls the hub for recovery commands and writes them to the ESP.

ESP firmware should print one JSON line per interval:
  {"device_id":"esp-sensor-01","metrics":{"sensor":{"temperature_c":28.5,"humidity_pct":62.1}}}

Or compact format (device_id baked in config on ESP side):
  SENTINEL:{"device_id":"esp-sensor-01","metrics":{...}}

Usage:
    python esp_bridge.py --hub http://192.168.1.100:5001
    python esp_bridge.py --hub http://192.168.1.100:5001 --port /dev/ttyUSB0
    python esp_bridge.py --hub http://192.168.1.100:5001 --port /dev/ttyS0 --baud 115200
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone

import serial
import serial.tools.list_ports
import requests

logging.basicConfig(
    format="%(asctime)s [esp-bridge] %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
log = logging.getLogger("esp_bridge")

_running = True


def _stop(sig, frame):
    global _running
    log.info("Shutting down...")
    _running = False


signal.signal(signal.SIGINT,  _stop)
signal.signal(signal.SIGTERM, _stop)


# ═════════════════════════════════════════════════════════════════════════════
# Serial port auto-detection
# ═════════════════════════════════════════════════════════════════════════════

def detect_port() -> str | None:
    """Auto-detect ESP8266/ESP32 USB serial port."""
    for port in serial.tools.list_ports.comports():
        desc = (port.description or "").lower()
        vid  = port.vid or 0
        # CH340 (NodeMCU), CP2102 (ESP dev boards), CH9102, FTDI
        if any(x in desc for x in ["cp210", "ch340", "ch9102", "esp", "ftdi", "usb serial"]):
            log.info("Auto-detected port: %s (%s)", port.device, port.description)
            return port.device
        # Vendor IDs: Silicon Labs=0x10C4, WCH=0x1A86, FTDI=0x0403
        if vid in (0x10C4, 0x1A86, 0x0403):
            log.info("Auto-detected port by VID: %s (vid=0x%04X)", port.device, vid)
            return port.device

    # Common Pi fallbacks
    for fallback in ("/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0"):
        if os.path.exists(fallback):
            log.info("Using fallback port: %s", fallback)
            return fallback

    return None


# ═════════════════════════════════════════════════════════════════════════════
# Packet parser — same logic as lora_bridge.py (battle-tested)
# ═════════════════════════════════════════════════════════════════════════════

def parse_line(line: str):
    """
    Accepts:
      SENTINEL:{"device_id":..., "metrics":{...}}   ← prefixed
      {"device_id":..., "metrics":{...}}             ← raw JSON
      {"device_id":..., "m":{...}}                   ← compact (m = metrics)

    Returns (device_id, metrics, timestamp) or None.
    """
    line = line.strip()
    if not line:
        return None

    if line.startswith("SENTINEL:"):
        line = line[9:]

    if not line.startswith("{"):
        return None   # debug/status line from ESP firmware

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    # normalise compact format
    if "m" in data and "metrics" not in data:
        data["metrics"] = data.pop("m")
    if "ts" in data and "timestamp" not in data:
        data["timestamp"] = data.pop("ts")

    device_id = data.get("device_id")
    metrics   = data.get("metrics", {})
    timestamp = data.get("timestamp")

    if not device_id or not metrics:
        return None

    return device_id, metrics, timestamp


# ═════════════════════════════════════════════════════════════════════════════
# Hub communication
# ═════════════════════════════════════════════════════════════════════════════

_registered: set = set()


def register_device(hub_url: str, device_id: str, platform: str = "ESP8266/ESP32") -> bool:
    if device_id in _registered:
        return True
    try:
        r = requests.post(
            hub_url.rstrip("/") + "/api/devices/register",
            json={
                "device_id": device_id,
                "hostname":  device_id,
                "platform":  platform,
                "version":   "ESP Sensor Node",
                "cmd_port":  0,   # queue-based commands — bridge polls and writes to serial
            },
            timeout=5,
        )
        if r.status_code == 200:
            _registered.add(device_id)
            log.info("Registered device: %s", device_id)
            return True
        log.warning("Registration returned HTTP %d for %s", r.status_code, device_id)
    except requests.RequestException as e:
        log.warning("Registration error: %s", e)
    return False


def push_metrics(hub_url: str, device_id: str, metrics: dict, timestamp=None) -> bool:
    try:
        r = requests.post(
            hub_url.rstrip("/") + "/api/metrics/push",
            json={
                "device_id": device_id,
                "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                "metrics":   metrics,
            },
            timeout=5,
        )
        return r.status_code == 200
    except requests.RequestException as e:
        log.warning("Push failed for %s: %s", device_id, e)
        return False


# ═════════════════════════════════════════════════════════════════════════════
# Command → serial translation
# Hub sends an action string; we write a CMD: line to ESP firmware.
# Mirror this in your ESP Arduino/MicroPython sketch.
# ═════════════════════════════════════════════════════════════════════════════

def _action_to_serial(action: str, duration: int = 60) -> str | None:
    if action in ('stress_cpu', 'cpu_spike', 'cpu_overload', 'demo_cpu', 'demo_full'):
        return "CMD:cpu_stress:{}\n".format(duration)
    if action in ('stop_stress', 'stop_simulation'):
        return "CMD:stop_stress\n"
    if action in ('restart_service', 'reconnect_sensor', 'restart_mqtt'):
        return "CMD:restart\n"
    return None   # unhandled — hub will log as skipped


# ═════════════════════════════════════════════════════════════════════════════
# Command poller — polls hub queue, writes CMD: to ESP serial
# ═════════════════════════════════════════════════════════════════════════════

def _command_poller(hub_url: str, device_id: str, ser_ref: list):
    """Background thread: polls hub every 3s for queued commands, writes to ESP."""
    url = hub_url.rstrip('/') + '/api/devices/{}/commands'.format(device_id)
    while _running:
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                for cmd in resp.json().get('commands', []):
                    action   = cmd.get('action', '')
                    duration = int(cmd.get('duration', 60))
                    serial_cmd = _action_to_serial(action, duration)
                    if serial_cmd:
                        ser = ser_ref[0]
                        if ser and ser.is_open:
                            ser.write(serial_cmd.encode())
                            log.info("CMD → ESP: %s (action=%s)", serial_cmd.strip(), action)
                        else:
                            log.warning("Serial closed, dropping cmd: %s", action)
                    else:
                        log.debug("No serial mapping for action: %s", action)
        except Exception as e:
            log.debug("Command poll error: %s", e)
        time.sleep(3)


# ═════════════════════════════════════════════════════════════════════════════
# Bridge main loop
# ═════════════════════════════════════════════════════════════════════════════

def run_bridge(hub_url: str, port: str, baud: int):
    log.info("Opening %s @ %d baud", port, baud)
    try:
        ser = serial.Serial(port, baud, timeout=2)
    except serial.SerialException as e:
        log.error("Cannot open %s: %s", port, e)
        log.error("Tip: sudo usermod -aG dialout $USER  (then logout/login)")
        sys.exit(1)

    log.info("ESP bridge running. Hub: %s", hub_url)

    ser_ref: list        = [ser]
    pollers_started: set = set()

    def _start_poller(device_id: str):
        if device_id not in pollers_started:
            pollers_started.add(device_id)
            t = threading.Thread(
                target=_command_poller,
                args=(hub_url, device_id, ser_ref),
                daemon=True,
                name='CmdPoller-{}'.format(device_id),
            )
            t.start()
            log.info("Command poller started for %s", device_id)

    ok_count = fail_count = 0

    while _running:
        try:
            raw = ser.readline()
            if not raw:
                continue

            line = raw.decode('utf-8', errors='replace').strip()

            # Pass non-JSON debug lines through as debug logs
            if line and not line.startswith('{') and not line.startswith('SENTINEL:'):
                log.debug("ESP> %s", line)
                continue

            result = parse_line(line)
            if result is None:
                continue

            device_id, metrics, timestamp = result

            # Register once; start command poller on first packet
            if device_id not in _registered:
                register_device(hub_url, device_id)
                _start_poller(device_id)

            ok = push_metrics(hub_url, device_id, metrics, timestamp)
            if ok:
                ok_count   += 1
                fail_count  = 0
                sen = metrics.get('sensor', {})
                t_  = sen.get('temperature_c', '?')
                h_  = sen.get('humidity_pct', '?')
                pwr = metrics.get('power', {}).get('power_voltage_v', '?')
                log.info("OK #%d  dev=%-20s  T=%s°C  H=%s%%  V=%sV",
                         ok_count, device_id, t_, h_, pwr)
            else:
                fail_count += 1
                log.warning("Push FAIL #%d for %s", fail_count, device_id)

        except serial.SerialException as e:
            log.error("Serial error: %s — reconnecting in 3s...", e)
            time.sleep(3)
            try:
                ser.close()
                ser = serial.Serial(port, baud, timeout=2)
                ser_ref[0] = ser   # update reference so poller threads see new instance
                log.info("Serial reconnected: %s", port)
            except Exception as re:
                log.error("Reconnect failed: %s", re)
        except Exception as e:
            log.error("Unexpected error: %s", e)
            time.sleep(1)

    ser.close()
    log.info("Bridge stopped. Sent %d packets, %d failures.", ok_count, fail_count)


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Sentinel AI — ESP Serial Bridge')
    parser.add_argument('--hub',   default='http://localhost:5001',
                        help='Sentinel hub URL')
    parser.add_argument('--port',  default=None,
                        help='Serial port (auto-detected if omitted)')
    parser.add_argument('--baud',  type=int, default=115200,
                        help='Baud rate (default: 115200)')
    args = parser.parse_args()

    port = args.port or detect_port()
    if not port:
        log.error("No ESP serial port found.")
        log.error("  Connect ESP via USB, or pass: --port /dev/ttyUSB0")
        log.error("  Also check: sudo usermod -aG dialout $USER")
        sys.exit(1)

    run_bridge(args.hub, port, args.baud)


if __name__ == '__main__':
    main()
