#!/usr/bin/env bash
# Sentinel AI — Raspberry Pi Setup
# Run once on the Pi: chmod +x setup.sh && ./setup.sh
set -e

echo "=================================================="
echo "  Sentinel AI — Raspberry Pi Setup"
echo "=================================================="

# ── 1. System packages ─────────────────────────────────
echo "[1/5] Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y \
    python3-pip python3-venv python3-dev \
    i2c-tools libi2c-dev libgpiod2 \
    python3-lgpio python3-gpiozero

# ── 2. Enable interfaces ───────────────────────────────
echo "[2/5] Enabling I2C and UART..."
sudo raspi-config nonint do_i2c 0        # I2C for sensors
sudo raspi-config nonint do_serial_hw 0  # UART hardware (for ESP on ttyS0)
sudo raspi-config nonint do_serial_cons 1 # disable login shell on serial

# ── 3. Group permissions ───────────────────────────────
echo "[3/5] Adding $USER to gpio and dialout groups..."
sudo usermod -aG gpio    "$USER" 2>/dev/null || true
sudo usermod -aG dialout "$USER" 2>/dev/null || true
sudo usermod -aG i2c     "$USER" 2>/dev/null || true

# ── 4. Python packages ─────────────────────────────────
echo "[4/5] Installing Python packages..."
pip3 install --upgrade pip --quiet
pip3 install \
    psutil \
    requests \
    gpiozero \
    adafruit-blinka \
    adafruit-circuitpython-dht \
    smbus2 \
    pyserial

# ── 5. Verify ──────────────────────────────────────────
echo "[5/5] Verifying..."
python3 - <<'EOF'
import importlib, sys
checks = [
    ("psutil",          "System metrics"),
    ("requests",        "HTTP client"),
    ("gpiozero",        "GPIO (motor)"),
    ("adafruit_dht",    "DHT22 sensor"),
    ("smbus2",          "I2C (sensor scan)"),
    ("serial",          "Serial (ESP bridge)"),
]
all_ok = True
for mod, label in checks:
    try:
        importlib.import_module(mod)
        print(f"  OK  {label}")
    except ImportError:
        print(f"  MISS {label} — pip install {mod}")
        all_ok = False
print()
if all_ok:
    print("All dependencies ready.")
else:
    print("Some optional deps missing — check above.")
EOF

echo ""
echo "=================================================="
echo "  Setup complete!"
echo ""
echo "  IMPORTANT: Log out and back in for group changes"
echo "  (gpio, dialout) to take effect."
echo ""
echo "  Edit config.py, then run:"
echo "    python3 pi_client.py          # Pi system + DHT + motor"
echo "    python3 esp_bridge.py         # ESP serial bridge"
echo "=================================================="
