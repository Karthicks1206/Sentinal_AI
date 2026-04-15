#!/usr/bin/env python3
"""
Sentinel AI — LoRa32 USB Serial Bridge
Runs on Raspberry Pi. Reads JSON from LoRa32 connected via USB-C,
forwards metrics to the Sentinel hub via HTTP POST.

Usage:
    python lora_bridge.py --hub http://localhost:5001
    python lora_bridge.py --hub http://192.168.1.100:5001 --port /dev/ttyUSB0
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone

import serial
import serial.tools.list_ports
import requests

logging.basicConfig(
    format="%(asctime)s [bridge] %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lora_bridge")

_running = True

def _signal_handler(sig, frame):
    global _running
    log.info("Shutting down...")
    _running = False


# ── Serial port detection ─────────────────────────────────────────────────────
def detect_port():
    """Auto-detect LoRa32 / Arduino USB serial port."""
    candidates = []
    for port in serial.tools.list_ports.comports():
        desc = (port.description or "").lower()
        vid  = port.vid or 0
        # ESP32-S3 (LoRa32 V3), CP2102, CH340, Arduino
        if any(x in desc for x in ["cp210", "ch340", "ch9102", "arduino", "esp32", "heltec", "usb serial"]):
            candidates.append(port.device)
        # USB vendor IDs: Silicon Labs=0x10C4, WCH=0x1A86, FTDI=0x0403
        elif vid in (0x10C4, 0x1A86, 0x0403, 0x2341, 0x1B4F):
            candidates.append(port.device)

    if candidates:
        log.info("Found serial devices: %s", candidates)
        return candidates[0]

    # Fallback: common Pi paths
    for fallback in ("/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyUSB1"):
        import os
        if os.path.exists(fallback):
            return fallback

    return None


# ── Hub communication ─────────────────────────────────────────────────────────
_registered = set()

def register_device(hub_url, device_id, platform="MicroPython-ESP32S3"):
    if device_id in _registered:
        return True
    try:
        r = requests.post(
            hub_url.rstrip("/") + "/api/devices/register",
            json={
                "device_id": device_id,
                "hostname": device_id,
                "platform": platform,
                "version": "Heltec LoRa32 V3",
            },
            timeout=5,
        )
        if r.status_code == 200:
            _registered.add(device_id)
            log.info("Registered device: %s", device_id)
            return True
        log.warning("Registration returned HTTP %d for %s", r.status_code, device_id)
    except requests.RequestException as e:
        log.warning("Hub unreachable during registration: %s", e)
    return False


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
        log.warning("Push failed for %s: %s", device_id, e)
        return False


# ── Packet parser ─────────────────────────────────────────────────────────────
def parse_line(line: str):
    """
    Accepts two formats from the LoRa32:
      SENTINEL:{"device_id":..., "metrics":{...}}   (prefixed, from main.py serial mode)
      {"device_id":..., "metrics":{...}}             (raw JSON)

    Also accepts compact LoRa radio packets:
      {"device_id":..., "ts":..., "m":{...}}
    """
    line = line.strip()
    if not line:
        return None

    # Strip prefix if present
    if line.startswith("SENTINEL:"):
        line = line[9:]

    # Skip non-JSON debug lines from MicroPython
    if not line.startswith("{"):
        return None

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Normalise compact LoRa packet format
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


# ── Main bridge loop ──────────────────────────────────────────────────────────
def run_bridge(hub_url: str, port: str, baud: int):
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    log.info("Opening %s @ %d baud", port, baud)
    try:
        ser = serial.Serial(port, baud, timeout=2)
    except serial.SerialException as e:
        log.error("Cannot open %s: %s", port, e)
        sys.exit(1)

    log.info("Bridge running. Hub: %s", hub_url)
    ok_count = 0
    fail_count = 0

    while _running:
        try:
            raw = ser.readline()
            if not raw:
                continue

            line = raw.decode("utf-8", errors="replace").strip()

            # Print all lines so we can see debug output too
            if line and not line.startswith("{") and not line.startswith("SENTINEL:"):
                log.debug("device> %s", line)
                continue

            result = parse_line(line)
            if result is None:
                continue

            device_id, metrics, timestamp = result

            # Register once per device
            if device_id not in _registered:
                register_device(hub_url, device_id)

            ok = push_metrics(hub_url, device_id, metrics, timestamp)
            if ok:
                ok_count += 1
                cpu = metrics.get("cpu", {}).get("cpu_percent", "?")
                mem = metrics.get("memory", {}).get("memory_percent", "?")
                sens = metrics.get("sensor", {})
                t = sens.get("temperature_c", "?")
                h = sens.get("humidity_pct", "?")
                log.info("OK #%d  dev=%-20s  cpu=%s%%  mem=%s%%  T=%s°C  H=%s%%",
                         ok_count, device_id, cpu, mem, t, h)
            else:
                fail_count += 1
                log.warning("FAIL #%d for %s", fail_count, device_id)

        except serial.SerialException as e:
            log.error("Serial error: %s — reconnecting in 3s", e)
            time.sleep(3)
            try:
                ser.close()
                ser = serial.Serial(port, baud, timeout=2)
            except Exception:
                pass
        except Exception as e:
            log.error("Unexpected error: %s", e)
            time.sleep(1)

    ser.close()
    log.info("Bridge stopped. Sent %d packets, %d failures.", ok_count, fail_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sentinel AI — LoRa32 USB Serial Bridge")
    parser.add_argument("--hub",  default="http://localhost:5001",
                        help="Sentinel hub URL (default: http://localhost:5001)")
    parser.add_argument("--port", default=None,
                        help="Serial port (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200,
                        help="Baud rate (default: 115200)")
    args = parser.parse_args()

    port = args.port or detect_port()
    if not port:
        log.error("No serial port found. Connect LoRa32 via USB and retry, or pass --port /dev/ttyUSB0")
        sys.exit(1)

    run_bridge(args.hub, port, args.baud)
