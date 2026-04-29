# LoRa32 Sentinel Client — Configuration
# Board: Heltec WiFi LoRa 32 V3 (ESP32-S3 + SX1262)
# Flash this file to the device alongside main.py and boot.py

# ── WiFi credentials ──────────────────────────────────────────────────────────
WIFI_SSID = "A2B"
WIFI_PASSWORD = "3159boys*"

# Sentinel AI hub address (LAN IP of Pi #1 running main.py)
HUB_URL = "http://192.168.1.100:5001"

# Device identity (shows up in the Sentinel dashboard)
DEVICE_ID = "lora32-node-01"

# How often to push metrics (seconds)
PUSH_INTERVAL = 5

# ── LoRa radio settings (SX1262 on LoRa32 V3) ────────────────────────────────
# NOTE: V3 uses SX1262, NOT SX1276/SX1278. Frequency range: 863–928 MHz.
# 868 MHz is the EU standard ISM band — use this for India/EU.
LORA_FREQUENCY = 868e6          # 868 MHz (EU/India ISM band)
LORA_BANDWIDTH = 125000         # 125 kHz
LORA_SPREADING_FACTOR = 7       # SF7 — good balance of range and speed
LORA_CODING_RATE = 5            # 4/5
LORA_TX_POWER = 14              # dBm (SX1262 max is 22, keep at 14 for indoor)

# Heltec WiFi LoRa 32 V3 — SX1262 SPI pin mapping (fixed, do not change)
LORA_SCK  = 9
LORA_MOSI = 10
LORA_MISO = 11
LORA_CS   = 8
LORA_RST  = 12
LORA_DIO1 = 14   # V3 uses DIO1 (not DIO0) for IRQ — critical difference from V1/V2
LORA_BUSY = 13   # SX1262-specific BUSY pin

# ── OLED display (SSD1306 128×64, I2C) ───────────────────────────────────────
OLED_SDA = 17
OLED_SCL = 18
OLED_RST = 21     # OLED reset pin (active low)
VEXT_CTRL = 36    # External power enable (LOW = on)
OLED_WIDTH = 128
OLED_HEIGHT = 64

# ── Sensor GPIO pins ──────────────────────────────────────────────────────────
# AHT20 temperature + humidity sensor (I2C, address 0x38)
AHT20_SDA = 1         # I2C SDA pin
AHT20_SCL = 40        # I2C SCL pin
# Analog voltage sensor (voltage divider on ADC)
VOLTAGE_PIN = 7       # ADC pin for voltage reading

# ── Transport mode ────────────────────────────────────────────────────────────
# "wifi"   — HTTP POST directly to hub (recommended, no extra hardware)
# "serial" — send JSON over USB serial → Pi reads and forwards to hub
# "lora"   — LoRa radio → needs Adafruit LoRa/second LoRa receiver on Pi side
TRANSPORT = "serial"
