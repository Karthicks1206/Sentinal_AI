# Sentinel AI — Quick Start

## Start the Hub (2 minutes)

```bash
cd sentinel_ai
kill $(lsof -ti :5001) 2>/dev/null; pkill -f "python.*main.py" 2>/dev/null
source venv/bin/activate
brew services start ollama
python main.py
```

Open **http://localhost:5001**

---

## Connect the Raspberry Pi

SSH into the Pi and run:

```bash
python3 sentinel_client.py --hub http://<HUB_IP>:5001 --device raspberry-pi-ECE510
```

Or start it permanently via systemd (auto-restarts on crash/reboot):

```bash
systemctl --user start sentinel-client
```

The Pi streams CPU, memory, disk, network, and **ESP32 IoT sensor data** (soil moisture, pump voltage, relay state) to the hub every 5 seconds.

---

## View IoT Sensor Data

1. Go to dashboard → **Distributed Devices & IoT Nodes** tab
2. Click **raspberry-pi-ECE510** in the sidebar
3. Scroll up to the **🌱 IoT Sensors — ESP32** card

Readings update every 2 seconds:
- **Soil Moisture %** — color-coded: green (wet), yellow (moderate), red (dry)
- **Pump Voltage** — supply voltage from the external 5V PSU
- **Relay / Pump** — ON or OFF
- **Soil ADC Raw** — raw 12-bit ADC reading
- **Moisture progress bar**

---

## Control the Pump

In the IoT Sensors card at the bottom:

| Button | Action |
|--------|--------|
| **▶ ON** | Forces pump relay ON for 5 minutes |
| **■ OFF** | Forces pump relay OFF for 5 minutes |

After the 5-minute override, the ESP32 returns to **autonomous mode**: soil < 40% → pump ON, soil ≥ 40% → pump OFF.

---

## Run a Stress Test (Full Pipeline Demo)

```bash
# Trigger CPU spike on hub machine
curl -X POST http://localhost:5001/api/simulate/start/cpu_spike

# Trigger on Pi
curl -X POST http://localhost:5001/api/devices/raspberry-pi-ECE510/queue_command \
  -H "Content-Type: application/json" -d '{"action":"stress_cpu"}'

# Watch the pipeline fire:
# Anomaly → AI Diagnosis → Recovery actions
# Check: http://localhost:5001 → Activity Log
```

Within 30–60 seconds you'll see:
1. **Anomaly detected** — CPU/memory spike flagged
2. **AI Diagnosis** — Groq LLM identifies root cause
3. **Recovery** — algorithmic fix applied (renice, throttle, kill, purge)

---

## Power Sag Test (IoT Power Monitoring)

```bash
curl -X POST http://localhost:5001/api/simulate/start/power_sag
```

Simulates a -0.75V voltage drop on the hub's simulated power metrics. The anomaly detector fires a **critical** power anomaly within one detection cycle.

---

## Stop Everything

```bash
curl -X POST http://localhost:5001/api/simulate/stop
pkill -f "python.*main.py"
```
