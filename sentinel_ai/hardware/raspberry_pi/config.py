# Sentinel AI — Raspberry Pi Hardware Config
# Edit this file before running pi_client.py or esp_bridge.py

# ── Hub ───────────────────────────────────────────────────────────────────────
HUB_URL  = "http://192.168.1.100:5001"   # Mac running main.py  ← CHANGE THIS
DEVICE_ID = "raspberry-pi-01"             # shows on dashboard

PUSH_INTERVAL = 5    # seconds

# ── DHT22 / DHT11 temperature + humidity sensor ───────────────────────────────
DHT_ENABLED = True
DHT_TYPE    = "DHT22"   # "DHT11" or "DHT22"
DHT_PIN     = 4          # GPIO BCM pin number

# ── Motor (L298N or similar driver) — read-only state monitoring ──────────────
MOTOR_ENABLED    = True
MOTOR_ENABLE_PIN = 18   # ENA — motor enabled when HIGH
MOTOR_IN1_PIN    = 23   # IN1
MOTOR_IN2_PIN    = 24   # IN2

# ── ESP serial bridge (run esp_bridge.py separately) ─────────────────────────
# ESP_PORT = "/dev/ttyUSB0"   # set this in esp_bridge.py --port
# ESP_BAUD = 115200
