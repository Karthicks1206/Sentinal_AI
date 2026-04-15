#!/usr/bin/env python3
"""
Sentinel AI — Pi LoRa Gateway
Receives LoRa packets from LoRa32 nodes and forwards metrics to the Sentinel hub.

Requires a LoRa HAT on the Raspberry Pi (SX1276/SX1278 via SPI).
Default wiring (adjust in LORA_* constants below):
  SPI0 CE0, DIO0→GPIO4, RST→GPIO17

Install:  pip install RPi-LoRa requests
Run:      python lora_gateway.py --hub http://localhost:5001
"""

import argparse
import json
import logging
import signal
import sys
import time

import requests

# ── Wiring constants — adjust to your LoRa HAT ───────────────────────────────
LORA_FREQUENCY     = 915e6   # Must match config.py on the LoRa32
LORA_BANDWIDTH     = 125000
LORA_SPREADING     = 7
LORA_CODING_RATE   = 5

# BCM GPIO numbers
DIO0_GPIO = 4    # LoRa IRQ line
RST_GPIO  = 17
CS_GPIO   = 25   # Not used by RPi-LoRa directly — SPI CE0

logging.basicConfig(
    format="%(asctime)s [gateway] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("lora_gateway")

_running = True


def _signal_handler(sig, frame):
    global _running
    log.info("Shutting down...")
    _running = False


def init_lora():
    """Initialise SX127x LoRa radio via SPI on the Raspberry Pi."""
    try:
        from SX127x.LoRa import LoRa
        from SX127x.board_config import BOARD
        BOARD.setup()
        lora = LoRa(verbose=False)
        lora.set_mode(0x81)  # SLEEP mode first
        lora.set_freq(LORA_FREQUENCY / 1e6)
        lora.set_bw(LORA_BANDWIDTH)
        lora.set_coding_rate(LORA_CODING_RATE)
        lora.set_spreading_factor(LORA_SPREADING)
        lora.set_mode(0x85)  # RX_CONT
        log.info("LoRa radio ready @ %.1f MHz", LORA_FREQUENCY / 1e6)
        return lora
    except ImportError:
        log.error("RPi-LoRa not installed. Run: pip install RPi-LoRa")
        sys.exit(1)
    except Exception as e:
        log.error("LoRa init failed: %s", e)
        sys.exit(1)


def forward_to_hub(hub_url: str, raw_payload: str) -> bool:
    """Parse LoRa packet and POST to Sentinel hub /api/metrics/push."""
    try:
        data = json.loads(raw_payload)
        # LoRa payloads use compact keys ("m" instead of "metrics", "ts" vs "timestamp")
        metrics = data.get("m") or data.get("metrics", {})
        device_id = data.get("device_id", "lora32-unknown")
        ts = data.get("ts") or data.get("timestamp")

        post_body = {
            "device_id": device_id,
            "timestamp": ts,
            "metrics": metrics,
            "source": "lora_gateway",
        }
        url = hub_url.rstrip("/") + "/api/metrics/push"
        r = requests.post(url, json=post_body, timeout=5)
        if r.status_code in (200, 201):
            log.info("forwarded device=%s status=%d", device_id, r.status_code)
            return True
        log.warning("hub returned HTTP %d for device=%s", r.status_code, device_id)
        return False
    except json.JSONDecodeError:
        log.warning("bad JSON from LoRa: %r", raw_payload[:80])
        return False
    except requests.RequestException as e:
        log.warning("hub unreachable: %s", e)
        return False


def run_gateway(hub_url: str):
    lora = init_lora()
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    log.info("Gateway listening. Forwarding to %s", hub_url)

    while _running:
        try:
            payload = lora.read_payload(nocheck=True)
            if payload:
                text = "".join([chr(c) for c in payload if 32 <= c < 128])
                log.debug("received %d bytes: %s", len(payload), text[:80])
                forward_to_hub(hub_url, text)
        except Exception as e:
            log.error("receive error: %s", e)
            time.sleep(1)

        time.sleep(0.05)  # ~20 Hz poll

    try:
        from SX127x.board_config import BOARD
        BOARD.teardown()
    except Exception:
        pass
    log.info("Gateway stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sentinel AI LoRa Gateway")
    parser.add_argument(
        "--hub",
        default="http://localhost:5001",
        help="Sentinel hub URL (default: http://localhost:5001)",
    )
    args = parser.parse_args()
    run_gateway(args.hub)
