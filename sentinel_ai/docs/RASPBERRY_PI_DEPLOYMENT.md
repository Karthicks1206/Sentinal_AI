# Raspberry Pi Deployment Guide

## Hardware Setup

### Components
- Raspberry Pi 5
- ESP32-S3 / Heltec board
- Soil moisture sensor → ESP32 GPIO 4
- Voltage sensor module → ESP32 GPIO 5
- 1-channel relay module IN → ESP32 GPIO 6
- 5V water pump → Relay NO contact
- External 5V/2A power supply

### Wiring Summary
```
ESP32 3.3V  ──► Soil Sensor VCC,  Voltage Sensor +
ESP32 GND   ──► Soil Sensor GND,  Voltage Sensor -, External 5V -
ESP32 GPIO4 ──► Soil Sensor AO
ESP32 GPIO5 ──► Voltage Sensor S
ESP32 GPIO6 ──► Relay IN
External 5V + ──► Relay DC+, Relay COM, Voltage Sensor VCC+
External 5V - ──► Relay DC-, Pump -, ESP32 GND (common ground)
Relay NO    ──► Pump +
```

> Common ground between ESP32 and external 5V supply is required.

---

## Step 1 — Flash MicroPython on ESP32-S3

```bash
# Install tools on Pi
pip3 install esptool mpremote --break-system-packages

# Erase existing firmware
python3 -m esptool --chip esp32s3 --port /dev/ttyUSB0 --baud 460800 erase_flash

# Download and flash MicroPython (ESP32-S3 generic)
wget https://micropython.org/resources/firmware/ESP32_GENERIC_S3-20241129-v1.24.1.bin
python3 -m esptool --chip esp32s3 --port /dev/ttyUSB0 --baud 460800 \
  write_flash -z 0x0 ESP32_GENERIC_S3-20241129-v1.24.1.bin

# Upload irrigation controller
python3 -m mpremote connect /dev/ttyUSB0 \
  cp ~/sentinel_ai/hardware/raspberry_pi/esp32_main_v3.py :main.py + reset
```

Verify it's running:
```bash
python3 -c "
import serial, time
s = serial.Serial('/dev/ttyUSB0', 115200, timeout=3)
time.sleep(2)
for _ in range(8):
    l = s.readline().decode('utf-8','ignore').strip()
    if l: print(l)
"
```

Expected:
```
Soil Raw: 1980
-------------------------------------
Soil Moisture: 42 %
Pump Supply Voltage: 4.58 V
Soil Status: WET / OK
Pump Status: OFF
-------------------------------------
```

---

## Step 2 — Install Sentinel Client

```bash
pip3 install psutil requests pyserial --break-system-packages
scp sentinel_client.py naveen242@192.168.1.100:~/sentinel_client.py
```

---

## Step 3 — Install as Systemd Service (auto-start)

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/sentinel-client.service << 'EOF'
[Unit]
Description=Sentinel AI IoT Client
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=5
ExecStart=/usr/bin/python3 /home/naveen242/sentinel_client.py \
    --hub http://192.168.1.149:5001 --device raspberry-pi-ECE510
StandardOutput=append:/home/naveen242/sentinel.log
StandardError=append:/home/naveen242/sentinel.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable sentinel-client
systemctl --user start sentinel-client
systemctl --user status sentinel-client --no-pager
```

The service auto-restarts within 5 seconds on crash and survives Pi reboots.

---

## Step 4 — Verify in Dashboard

1. Open `http://localhost:5001`
2. Click **Distributed Devices & IoT Nodes**
3. Click **raspberry-pi-ECE510** in the sidebar
4. Confirm the **🌱 IoT Sensors — ESP32** card shows live readings

---

## Troubleshooting

**No sensor data:**
```bash
systemctl --user status sentinel-client
tail -20 ~/sentinel.log
# Look for: "[ESP32] Serial connected on /dev/ttyUSB0"
```

**Pump not responding:**
```bash
grep -i pump ~/sentinel.log | tail -10
# Expected: "[RECOVERY] success — Pump relay ON"
```

**ESP32 not responding to commands:**
```bash
python3 -m mpremote connect /dev/ttyUSB0 reset
```
