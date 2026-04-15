#!/usr/bin/env bash
# Sentinel AI — Pi Setup for LoRa32 Bridge
# Run this on the Raspberry Pi (not on Mac).
# Sets up Python deps for lora_bridge.py.
#
# Usage:
#   chmod +x pi_setup.sh
#   ./pi_setup.sh

set -e

echo "============================================================"
echo " Sentinel AI — Pi LoRa Bridge Setup"
echo "============================================================"

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/3] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3-pip python3-venv

# ── 2. Python packages ────────────────────────────────────────────────────────
echo "[2/3] Installing Python packages..."
pip3 install pyserial requests

# ── 3. Check serial port ──────────────────────────────────────────────────────
echo "[3/3] Checking for connected serial devices..."
if ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | head -5; then
    echo "      Serial device(s) found above."
else
    echo "      No serial device detected yet — connect LoRa32 via USB-C"
fi

# Add user to dialout group so serial port access works without sudo
if ! groups | grep -q dialout; then
    sudo usermod -aG dialout "$USER"
    echo "      Added $USER to dialout group. Log out and back in for it to take effect."
fi

echo ""
echo "============================================================"
echo " Setup complete. To start the bridge:"
echo ""
echo "   # WiFi mode — LoRa32 pushes directly to hub (no bridge needed)"
echo "   # Just set TRANSPORT=wifi in config.py and flash"
echo ""
echo "   # Serial mode — Pi reads LoRa32 USB and forwards to hub:"
echo "   python3 lora_bridge.py --hub http://localhost:5001"
echo ""
echo "   # If hub is on a different Pi:"
echo "   python3 lora_bridge.py --hub http://192.168.1.100:5001"
echo "============================================================"
