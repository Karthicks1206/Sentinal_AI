#!/usr/bin/env bash
# Sentinel AI — LoRa32 Flash & Package Installer
#
# Run this on your Mac/Linux machine (NOT on the Pi).
# The LoRa32 must be connected via USB.
#
# Prerequisites (run once):
#   pip install esptool mpremote adafruit-ampy
#
# Usage:
#   chmod +x install.sh
#   ./install.sh              # auto-detect USB port
#   ./install.sh /dev/cu.usbserial-0001   # specify port manually
set -e

PORT="${1:-}"

# ── 1. Detect USB port ────────────────────────────────────────────────────────
if [ -z "$PORT" ]; then
    # macOS: /dev/cu.usbserial-* or /dev/cu.SLAB_USBtoUART
    # Linux: /dev/ttyUSB0 or /dev/ttyACM0
    PORT=$(ls /dev/cu.usbserial-* /dev/cu.SLAB_USBtoUART /dev/ttyUSB0 /dev/ttyACM0 2>/dev/null | head -1)
    if [ -z "$PORT" ]; then
        echo "ERROR: No USB-serial device found. Connect the LoRa32 and retry, or pass the port as argument."
        exit 1
    fi
fi
echo "[1/5] Using port: $PORT"

# ── 2. Flash MicroPython firmware ─────────────────────────────────────────────
FIRMWARE_URL="https://micropython.org/resources/firmware/ESP32_GENERIC-20240602-v1.23.0.bin"
FIRMWARE="micropython_esp32.bin"

if [ ! -f "$FIRMWARE" ]; then
    echo "[2/5] Downloading MicroPython firmware..."
    curl -L -o "$FIRMWARE" "$FIRMWARE_URL"
else
    echo "[2/5] Firmware already downloaded."
fi

echo "      Erasing flash..."
esptool.py --chip esp32 --port "$PORT" erase_flash

echo "      Writing firmware..."
esptool.py --chip esp32 --port "$PORT" --baud 460800 write_flash \
    -z 0x1000 "$FIRMWARE"

echo "      Waiting for reboot..."
sleep 3

# ── 3. Install MicroPython packages via mpremote ──────────────────────────────
echo "[3/5] Installing MicroPython packages..."
mpremote connect "$PORT" mip install urequests
mpremote connect "$PORT" mip install ssd1306          # OLED driver
mpremote connect "$PORT" mip install micropython-umqtt.simple  # optional MQTT

# SX127x LoRa driver — community port, install from GitHub
echo "      Installing SX127x LoRa driver..."
mpremote connect "$PORT" mip install \
    github:ehong-tl/micropySX127x/SX127x.py  2>/dev/null \
    || echo "      (SX127x driver: copy SX127x.py manually if above fails)"

# ── 4. Copy Sentinel client files ─────────────────────────────────────────────
echo "[4/5] Copying Sentinel client files to device..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
mpremote connect "$PORT" cp "$SCRIPT_DIR/config.py" :config.py
mpremote connect "$PORT" cp "$SCRIPT_DIR/boot.py"   :boot.py
mpremote connect "$PORT" cp "$SCRIPT_DIR/main.py"   :main.py

# ── 5. Verify ─────────────────────────────────────────────────────────────────
echo "[5/5] Files on device:"
mpremote connect "$PORT" ls

echo ""
echo "Done. Edit config.py on the device to set your WiFi credentials and hub IP:"
echo "  mpremote connect $PORT edit :config.py"
echo ""
echo "Then reset the board:"
echo "  mpremote connect $PORT reset"
echo ""
echo "Monitor output:"
echo "  mpremote connect $PORT"
