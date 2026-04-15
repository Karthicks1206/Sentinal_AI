# LoRa32 Sentinel Client — Configuration
# Flash this file to the device alongside main.py and boot.py

# WiFi credentials
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

# Sentinel AI hub address (LAN IP of the machine running main.py)
HUB_URL = "http://192.168.1.100:5001"

# Device identity (shows up in the Sentinel dashboard)
DEVICE_ID = "lora32-node-01"

# How often to push metrics (seconds)
PUSH_INTERVAL = 5

# ── LoRa radio settings (SX127x chip on the LoRa32 board) ───────────────────
# These must match the Pi-side lora_gateway.py settings.
LORA_FREQUENCY = 915e6          # 915 MHz (US). Use 868e6 for EU.
LORA_BANDWIDTH = 125000         # 125 kHz
LORA_SPREADING_FACTOR = 7       # SF7 — best range/speed balance
LORA_CODING_RATE = 5            # 4/5
LORA_TX_POWER = 17              # dBm (max 20 for SX1276)

# Heltec WiFi LoRa 32 V3 SPI pin mapping
# Adjust for TTGO LoRa32 or other boards if different.
LORA_SCK  = 9
LORA_MOSI = 10
LORA_MISO = 11
LORA_CS   = 8
LORA_RST  = 12
LORA_DIO0 = 14

# OLED display (SSD1306 128×64, I2C)
OLED_SDA = 17
OLED_SCL = 18
OLED_WIDTH = 128
OLED_HEIGHT = 64

# Transport: "wifi" (HTTP POST) or "lora" (LoRa radio → Pi gateway)
TRANSPORT = "wifi"
