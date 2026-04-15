#!/usr/bin/env python3
"""
Sentinel AI — Arduino USB Serial Bridge
Runs on Raspberry Pi. Reads JSON from Arduino connected via USB,
forwards metrics to the Sentinel hub.

Handles both LoRa32 (lora_bridge.py) and Arduino on the same Pi.
Can run multiple bridges simultaneously for multiple serial devices.

Usage:
    python arduino_bridge.py --hub http://localhost:5001
    python arduino_bridge.py --hub http://192.168.1.100:5001 --port /dev/ttyACM0
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

import serial
import serial.tools.list_ports
import requests

logging.basicConfig(
    format="%(asctime)s [arduino] %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
log = logging.getLogger("arduino_bridge")

_running = True

def _signal_handler(sig, frame):
    global _running
    _running = False


def detect_arduino_port(skip_ports=None):
    skip_ports = skip_ports or []
    for port in serial.tools.list_ports.comports():
        if port.device in skip_ports:
            continue
        desc = (port.description or "").lower()
        vid  = port.vid or 0
        if any(x in desc for x in ["arduino", "ch340", "ch9102", "ftdi"]):
            return port.device
        # Arduino Uno R3: VID=0x2341, R4: VID=0x2341 or 0x1B4F
        if vid in (0x2341, 0x1B4F, 0x1A86, 0x0403):
            return port.device

    for fallback in ("/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB1"):
        if os.path.exists(fallback):
            return fallback
    return None


_registered = set()

def register_device(hub_url, device_id):
    if device_id in _registered:
        return
    try:
        r = requests.post(
            hub_url.rstrip("/") + "/api/devices/register",
            json={
                "device_id": device_id,
                "hostname": device_id,
                "platform": "Arduino",
                "version": "Sentinel Sensor Node",
            },
            timeout=5,
        )
        if r.status_code == 200:
            _registered.add(device_id)
            log.info("Registered: %s", device_id)
    except requests.RequestException as e:
        log.warning("Registration failed: %s", e)


def push_metrics(hub_url, device_id, metrics, timestamp=None):
    try:
        r = requests.post(
            hub_url.rstrip("/") + "/api/metrics/push",
            json={
                "device_id": device_id,
                "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                "metrics": metrics,
            },
            timeout=5,
        )
        return r.status_code == 200
    except requests.RequestException as e:
        log.warning("Push failed: %s", e)
        return False


def parse_line(line: str):
    line = line.strip()
    if not line:
        return None
    if line.startswith("SENTINEL:"):
        line = line[9:]
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    device_id = data.get("device_id")
    metrics   = data.get("metrics", {})
    timestamp = data.get("timestamp")
    if not device_id or not metrics:
        return None
    return device_id, metrics, timestamp


def run_bridge(hub_url, port, baud):
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    log.info("Opening %s @ %d baud", port, baud)
    try:
        ser = serial.Serial(port, baud, timeout=2)
    except serial.SerialException as e:
        log.error("Cannot open %s: %s", port, e)
        sys.exit(1)

    log.info("Arduino bridge running. Hub: %s", hub_url)
    ok_count = 0

    while _running:
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()

            if line and not line.startswith("{") and not line.startswith("SENTINEL:"):
                log.debug("arduino> %s", line)
                continue

            result = parse_line(line)
            if not result:
                continue

            device_id, metrics, timestamp = result

            if device_id not in _registered:
                register_device(hub_url, device_id)

            ok = push_metrics(hub_url, device_id, metrics, timestamp)
            if ok:
                ok_count += 1
                sens = metrics.get("sensor", {})
                t = sens.get("temperature_c", "?")
                h = sens.get("humidity_pct", "?")
                v = metrics.get("power", {}).get("power_voltage_v", "?")
                log.info("OK #%d  dev=%-20s  T=%s°C  H=%s%%  V=%sV",
                         ok_count, device_id, t, h, v)

        except serial.SerialException as e:
            log.error("Serial error: %s — reconnecting...", e)
            time.sleep(3)
            try:
                ser.close()
                ser = serial.Serial(port, baud, timeout=2)
            except Exception:
                pass
        except Exception as e:
            log.error("Error: %s", e)
            time.sleep(1)

    ser.close()
    log.info("Arduino bridge stopped. Total packets sent: %d", ok_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sentinel AI — Arduino Serial Bridge")
    parser.add_argument("--hub",  default="http://localhost:5001")
    parser.add_argument("--port", default=None)
    parser.add_argument("--baud", type=int, default=9600)
    args = parser.parse_args()

    port = args.port or detect_arduino_port()
    if not port:
        log.error("No Arduino port found. Connect Arduino via USB or pass --port /dev/ttyACM0")
        sys.exit(1)

    run_bridge(args.hub, port, args.baud)
