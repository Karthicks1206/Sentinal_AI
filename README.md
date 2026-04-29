# Sentinel AI — Autonomous Self-Healing IoT Infrastructure

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![MicroPython](https://img.shields.io/badge/MicroPython-ESP32--S3-orange.svg)](https://micropython.org/)
[![AI](https://img.shields.io/badge/AI-Groq%20%7C%20Ollama%20%7C%20Isolation%20Forest-purple.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **Multi-agent AI system for real-time monitoring, anomaly detection, LLM-powered diagnosis, and autonomous self-healing across distributed computers and physical IoT hardware — featuring a live smart irrigation node (ESP32 + Raspberry Pi 5).**

---

## What It Does

1. **Monitors** — collects CPU, memory, disk, network, power, and IoT sensor metrics every 5 seconds from any connected device
2. **Detects** — finds anomalies using Z-score adaptive baselines, Isolation Forest, and a Keras LSTM autoencoder
3. **Diagnoses** — Groq cloud LLM (llama-3.3-70b) or local Ollama (llama3.2:3b) performs root-cause analysis
4. **Recovers** — executes 15+ targeted recovery actions (renice, kill, purge, log-rotate, remote commands) with graduated escalation
5. **Controls IoT hardware** — soil moisture triggers autonomous pump on/off; dashboard has manual pump override buttons

---

## Architecture

```
LAYER 1 — SENSING & ACTUATION
  Soil Moisture Sensor ──► ESP32-S3/Heltec ──USB Serial──► Raspberry Pi 5
  Voltage Sensor       ──►    (GPIO 4,5,6)                    (gateway)
  Relay + 5V Pump    ◄──┘

LAYER 2 — GATEWAY (Raspberry Pi 5)
  sentinel_client.py — reads ESP32 serial, streams metrics via HTTP POST

LAYER 3 — HUB (Mac / Server, port 5001)
  MonitoringAgent ──► AnomalyAgent ──► DiagnosisAgent ──► RecoveryAgent
                                                              │
                                                         (local + remote)

LAYER 4 — DASHBOARD
  http://localhost:5001  —  real-time UI for all devices and IoT sensors
```

---

## Quick Start

```bash
# 1. Start hub
cd sentinel_ai
kill $(lsof -ti :5001) 2>/dev/null; pkill -f "python.*main.py" 2>/dev/null
source venv/bin/activate && brew services start ollama
python main.py
# Dashboard → http://localhost:5001

# 2. Connect Raspberry Pi (run on the Pi)
python3 sentinel_client.py --hub http://<HUB_IP>:5001 --device raspberry-pi-ECE510

# 3. Flash ESP32 firmware (MicroPython asyncio irrigation controller)
mpremote connect /dev/ttyUSB0 cp hardware/raspberry_pi/esp32_main_v3.py :main.py + reset
```

---

## Dashboard

**Local Device tab** — hub machine metrics + simulation lab (trigger CPU/memory/power stress)

**Distributed Devices & IoT Nodes tab:**
- Sidebar shows all connected devices and IoT nodes with live readings
- **IoT Sensors card** — soil moisture %, pump voltage, relay state, ADC raw, moisture progress bar
- **▶ ON / ■ OFF** — manual pump buttons, 5-minute override then autonomous mode resumes
- Agent Pipeline view — Monitor → Anomaly → Diagnosis → Recovery per device
- Anomaly / Diagnosis / Recovery event feeds

---

## IoT Hardware (ECE-510 Group 3)

| Component | Connection | Role |
|-----------|-----------|------|
| Soil Moisture Sensor | ESP32 GPIO 4 (ADC) | Measures soil water content |
| Voltage Sensor Module | ESP32 GPIO 5 (ADC) | Monitors pump supply voltage |
| Relay Module IN | ESP32 GPIO 6 (OUT) | Switches 5V pump circuit |
| 5V Water Pump | Relay NO contact | Irrigation actuation |
| Raspberry Pi 5 | USB serial (/dev/ttyUSB0) | Gateway to Sentinel AI hub |

**Autonomous logic:** soil < 40% → pump ON · soil ≥ 40% → pump OFF
**Manual override:** 5-minute window via dashboard buttons, then reverts to auto

---

## Self-Healing Pipeline

```
Every 5s: metric push
    │
    ▼ AnomalyDetectionAgent
    ├── Adaptive Z-score (per metric, EMA drift, hysteresis)
    ├── Isolation Forest (sklearn, multivariate)
    └── Keras LSTM Autoencoder (sequence, PyTorch backend)
    │
    ▼ DiagnosisAgent (runs in background thread)
    ├── Groq LLM — llama-3.3-70b (fast cloud, default)
    ├── Ollama — llama3.2:3b (local, no data sent out)
    └── Rule-based — 14 rules, instant fallback
    │
    ▼ RecoveryAgent
    ├── Graduated escalation L1 → L4
    ├── Algorithmic engine: profile → classify → targeted fix
    ├── Remote action queue (Pi executes locally)
    └── 30s outcome verification → re-escalate if needed
```

**Zero skips** — every recovery action either executes or escalates to an alternative. Algorithmic fixes are cooldown-exempt and always produce a real action.

---

## Project Structure

```
sentinel_ai/
├── main.py                        # Orchestrator — starts all agents + dashboard
├── sentinel_client.py             # Remote client for Pi / laptops
├── config/
│   ├── config.yaml                # Thresholds, cooldowns, escalation config
│   └── diagnosis_rules.yaml       # 14 rule-based diagnosis rules
├── agents/
│   ├── monitoring/                # Metric collection, remote device manager
│   ├── anomaly/                   # Z-score + Isolation Forest + LSTM
│   ├── diagnosis/                 # Groq / Ollama / rule-based AI
│   ├── recovery/                  # Recovery engine + algorithmic healer
│   ├── learning/                  # Adaptive threshold learning
│   └── security/                  # Security threat detection (demo mode)
├── dashboard/
│   ├── app.py                     # Flask app (port 5001)
│   └── templates/dashboard.html  # Full UI — local + distributed + IoT
├── hardware/
│   ├── lora32/                    # Heltec LoRa32 V3 MicroPython client
│   └── raspberry_pi/              # Pi sentinel client + ESP32 firmware
│       └── esp32_main_v3.py       # Asyncio irrigation controller (MicroPython)
├── simulation/                    # CPU / memory / disk / power stress runners
├── core/event_bus.py              # In-memory pub/sub event bus
└── docs/                          # Architecture, deployment, testing guides
```

---

## Key API Endpoints

```bash
GET  /api/metrics                           # Local hub metrics
GET  /api/devices                           # All connected devices
GET  /api/devices/<id>/metrics              # Device-specific metrics
POST /api/devices/<id>/queue_command        # Send action to device
POST /api/simulate/start/<scenario>         # cpu_spike | memory_pressure | power_sag
POST /api/simulate/stop                     # Stop all simulations
GET  /api/logs?limit=100                    # Activity log
GET  /api/anomalies                         # Detected anomalies
GET  /api/recoveries                        # Recovery actions taken
```

---

## Requirements

**Hub:** Python 3.9+, Ollama, see `requirements.txt`

**Raspberry Pi:** `pip install psutil requests pyserial`

**ESP32-S3:** MicroPython v1.24+ (flash with `esptool.py`)
