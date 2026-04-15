#!/usr/bin/env bash
# Sentinel AI — LoRa32 V3 Flash & Setup
# Board: Heltec WiFi LoRa 32 V3  (ESP32-S3 + SX1262)
#
# Run this on your Mac/Linux (NOT on the Pi).
# LoRa32 must be connected via USB-C.
#
# Prerequisites (run once):
#   pip install esptool mpremote
#
# Usage:
#   chmod +x install.sh
#   ./install.sh                       # auto-detect port
#   ./install.sh /dev/cu.usbserial-0001   # specify port

set -e

PORT="${1:-}"

# ── 1. Detect USB port ────────────────────────────────────────────────────────
if [ -z "$PORT" ]; then
    PORT=$(ls /dev/cu.usbserial-* /dev/cu.SLAB_USBtoUART /dev/ttyUSB0 /dev/ttyACM0 2>/dev/null | head -1)
    if [ -z "$PORT" ]; then
        echo "ERROR: No USB-serial device found. Connect the LoRa32 via USB-C and retry."
        exit 1
    fi
fi
echo "[1/5] Port: $PORT"

# ── 2. Download MicroPython for ESP32-S3 ─────────────────────────────────────
# LoRa32 V3 uses ESP32-S3 — use the S3 firmware, NOT the generic ESP32 one.
FIRMWARE_URL="https://micropython.org/resources/firmware/ESP32_GENERIC_S3-20240602-v1.23.0.bin"
FIRMWARE="micropython_esp32s3.bin"

if [ ! -f "$FIRMWARE" ]; then
    echo "[2/5] Downloading MicroPython for ESP32-S3..."
    curl -L -o "$FIRMWARE" "$FIRMWARE_URL"
else
    echo "[2/5] Firmware already downloaded."
fi

echo "      Erasing flash..."
esptool.py --chip esp32s3 --port "$PORT" erase_flash

echo "      Writing firmware..."
esptool.py --chip esp32s3 --port "$PORT" --baud 460800 write_flash \
    -z 0x0 "$FIRMWARE"

echo "      Waiting for reboot..."
sleep 4

# ── 3. Install MicroPython packages ──────────────────────────────────────────
echo "[3/5] Installing MicroPython packages..."
mpremote connect "$PORT" mip install urequests
mpremote connect "$PORT" mip install ssd1306

# SX1262 driver for LoRa32 V3 (SX1262 chip, not SX127x)
echo "      Installing SX1262 LoRa driver..."
mpremote connect "$PORT" mip install \
    github:ehong-tl/micropySX126x 2>/dev/null \
    || echo "      (SX1262 driver install failed — copy sx126x.py manually if needed)"

echo "      Installing DHT sensor driver..."
mpremote connect "$PORT" mip install dht 2>/dev/null \
    || echo "      (dht built into MicroPython, may already be available)"

# ── 4. Copy Sentinel client files ────────────────────────────────────────────
echo "[4/5] Copying Sentinel files to LoRa32..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
mpremote connect "$PORT" cp "$SCRIPT_DIR/config.py" :config.py
mpremote connect "$PORT" cp "$SCRIPT_DIR/boot.py"   :boot.py
mpremote connect "$PORT" cp "$SCRIPT_DIR/main.py"   :main.py

# ── 5. Verify ─────────────────────────────────────────────────────────────────
echo "[5/5] Files on device:"
mpremote connect "$PORT" ls

echo ""
echo "============================================================"
echo " NEXT STEP: Edit config.py with your WiFi credentials"
echo "============================================================"
echo ""
echo "  mpremote connect $PORT edit :config.py"
echo ""
echo "  Set:"
echo "    WIFI_SSID     = \"your_network_name\""
echo "    WIFI_PASSWORD = \"your_password\""
echo "    HUB_URL       = \"http://<pi-ip>:5001\""
echo "    DEVICE_ID     = \"lora32-node-01\""
echo "    TRANSPORT     = \"wifi\"    # or serial if using USB bridge"
echo ""
echo "  Then reset: mpremote connect $PORT reset"
echo ""
echo "  Monitor output: mpremote connect $PORT"
echo "============================================================"
