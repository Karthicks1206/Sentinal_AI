#!/usr/bin/env bash
# Sentinel AI — Raspberry Pi 5 Setup Script
# Run once on the Pi:  chmod +x setup_rpi5.sh && ./setup_rpi5.sh
set -e

echo "[1/6] Updating system packages..."
sudo apt-get update -q
sudo apt-get install -y \
    python3-pip python3-venv python3-dev \
    i2c-tools libi2c-dev \
    python3-lgpio python3-gpiozero \
    libatlas-base-dev libopenblas-dev \
    mosquitto mosquitto-clients \
    git curl

echo "[2/6] Enabling I2C and SPI interfaces..."
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_serial_hw 0   # UART hardware (for USB-serial to LoRa32)

echo "[3/6] Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "[4/6] Installing Python requirements..."
pip install --upgrade pip wheel setuptools
pip install -r requirements_rpi5.txt

echo "[5/6] Verifying hardware libraries..."
python3 - <<'EOF'
import importlib, sys
libs = {
    "lgpio": "GPIO (Pi 5)",
    "gpiozero": "gpiozero",
    "smbus2": "I2C",
    "spidev": "SPI",
    "serial": "pyserial / UART",
    "adafruit_ina219": "INA219 power sensor",
    "SX127x": "LoRa SX127x (RPi-LoRa)",
}
ok = True
for mod, label in libs.items():
    try:
        importlib.import_module(mod)
        print(f"  OK  {label}")
    except ImportError:
        print(f"  --  {label}  (optional — skip if not using this hardware)")
        ok = False
print()
print("Core check done. Optional hardware libraries only needed for attached sensors.")
EOF

echo "[6/6] Setup complete."
echo ""
echo "To run as a monitoring HUB (full dashboard):"
echo "  source venv/bin/activate && python main.py"
echo ""
echo "To run as a REMOTE CLIENT only (lightweight, no ML):"
echo "  source venv/bin/activate && python sentinel_client.py --hub http://<hub-ip>:5001 --device rpi5"
echo ""
echo "To receive metrics from LoRa32 over LoRa radio, enable the LoRa gateway:"
echo "  source venv/bin/activate && python hardware/lora32/lora_gateway.py --hub http://localhost:5001"
