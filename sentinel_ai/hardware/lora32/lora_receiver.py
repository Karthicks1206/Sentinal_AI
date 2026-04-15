#!/usr/bin/env python3
"""
Sentinel AI - Pi LoRa Radio Receiver (Adafruit RFM95W / SX1276)
Receives LoRa packets from LoRa32 V3 (SX1262) at 868MHz via SPI.
Forwards metrics to Sentinel hub at /api/metrics/push.

Wiring (Adafruit RFM95W -> Raspberry Pi 5):
  VIN  -> 3.3V   Pin 1
  GND  -> GND    Pin 6
  SCK  -> GPIO11 Pin 23
  MISO -> GPIO9  Pin 21
  MOSI -> GPIO10 Pin 19
  CS   -> GPIO17 Pin 11  (NOT CE0/GPIO8 - kernel claims it)
  RST  -> GPIO25 Pin 22
  G0   -> GPIO24 Pin 18
"""
import argparse, json, logging, signal, sys, time
from datetime import datetime, timezone
import board, busio, digitalio, adafruit_rfm9x, requests

logging.basicConfig(
    format="%(asctime)s [lora-rx] %(message)s",
    level=logging.INFO, datefmt="%H:%M:%S")
log = logging.getLogger("lora_receiver")
_running = True

def _sig(s, f):
    global _running
    _running = False

_registered = set()

def register(hub, dev):
    if dev in _registered:
        return
    try:
        r = requests.post(
            hub.rstrip("/") + "/api/devices/register",
            json={"device_id": dev, "hostname": dev,
                  "platform": "MicroPython-ESP32S3-LoRa",
                  "version": "Heltec LoRa32 V3 radio"},
            timeout=5)
        if r.status_code == 200:
            _registered.add(dev)
            log.info("Registered: %s", dev)
    except Exception as e:
        log.warning("Register failed: %s", e)

def push(hub, dev, metrics, rssi=None):
    try:
        if rssi is not None:
            metrics.setdefault("network", {})["lora_rssi_dbm"] = rssi
        r = requests.post(
            hub.rstrip("/") + "/api/metrics/push",
            json={"device_id": dev,
                  "timestamp": datetime.now(timezone.utc).isoformat(),
                  "metrics": metrics},
            timeout=5)
        return r.status_code == 200
    except Exception as e:
        log.warning("Push failed: %s", e)
        return False

def parse(raw):
    """Find first { in packet bytes and parse JSON from there."""
    try:
        text = raw.decode("utf-8", errors="replace")
        idx = text.find("{")
        if idx == -1:
            return None
        data = json.loads(text[idx:])
        metrics = data.get("m") or data.get("metrics", {})
        dev = data.get("device_id", "lora32-unknown")
        if not metrics or not dev:
            return None
        return dev, metrics
    except Exception:
        return None

def init_radio(freq):
    spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
    cs  = digitalio.DigitalInOut(board.D17)
    rst = digitalio.DigitalInOut(board.D25)
    rfm = adafruit_rfm9x.RFM9x(spi, cs, rst, freq)
    rfm.tx_power         = 14
    rfm.signal_bandwidth = 125000
    rfm.spreading_factor = 7
    rfm.coding_rate      = 5
    rfm.enable_crc       = True
    rfm.preamble_length  = 8
    rfm.node             = 0xFF
    rfm.destination      = 0xFF
    log.info("RFM9x ready @ %.1f MHz  BW=125k  SF=7", freq)
    return rfm

def run(hub, freq):
    signal.signal(signal.SIGINT,  _sig)
    signal.signal(signal.SIGTERM, _sig)
    log.info("Init Adafruit RFM9x — CS=GPIO17 RST=GPIO25 G0=GPIO24")
    try:
        radio = init_radio(freq)
    except Exception as e:
        log.error("Radio init failed: %s", e)
        log.error("Check wiring: CS=GPIO17(Pin11), RST=GPIO25(Pin22), G0=GPIO24(Pin18)")
        sys.exit(1)

    log.info("Listening for LoRa packets. Forwarding to %s", hub)
    ok = 0
    while _running:
        try:
            pkt = radio.receive(timeout=5.0, with_header=True)
            if pkt is None:
                continue
            rssi = radio.last_rssi
            res  = parse(pkt)
            if not res:
                log.debug("Unparseable packet len=%d", len(pkt))
                continue
            dev, metrics = res
            if dev not in _registered:
                register(hub, dev)
            if push(hub, dev, metrics, rssi):
                ok += 1
                sens = metrics.get("sensor", {})
                t = "{}C".format(sens["temperature_c"]) if "temperature_c" in sens else "--"
                h = "{}%".format(sens["humidity_pct"])  if "humidity_pct"   in sens else "--"
                log.info("OK #%d  dev=%-20s  RSSI=%ddBm  T=%s  H=%s",
                         ok, dev, rssi, t, h)
        except Exception as e:
            log.error("Error: %s", e)
            time.sleep(1)
    log.info("Stopped. Total packets: %d", ok)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub",  default="http://localhost:5001")
    ap.add_argument("--freq", type=float, default=868.0)
    args = ap.parse_args()
    run(args.hub, args.freq)
