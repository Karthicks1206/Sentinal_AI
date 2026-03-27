# Sentinel AI — Autonomous Self-Healing IoT Infrastructure

[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![AI](https://img.shields.io/badge/AI-Groq%20%7C%20Ollama%20%7C%20Isolation%20Forest-purple.svg)]()

> **Production-ready multi-agent AI framework for autonomous monitoring, anomaly detection, LLM-powered diagnosis, and self-healing recovery across distributed IoT edge devices.**

---

## What is Sentinel AI?

Sentinel AI is an intelligent distributed system that monitors IoT infrastructure in real-time, detects anomalies using adaptive statistical methods and machine learning, diagnoses root causes with AI assistance (Groq / Ollama), and autonomously executes recovery actions — all while learning and adapting from every incident.

---

## Quick Start (Hub Machine)

```bash
cd /Users/karthi/Desktop/Sentinal_AI/sentinel_ai
kill $(lsof -ti :5001) 2>/dev/null; pkill -f "python.*main.py" 2>/dev/null
source venv/bin/activate
brew services start ollama
python main.py
```

Dashboard: **http://localhost:5001**

Or use the single script at the project root:

```bash
./run.sh
```

---

## Connect a Remote Device

On any machine on the same network:

```bash
# Auto-connect script (recommended)
bash connect.sh

# Or manually
pip install psutil requests
python sentinel_client.py --hub http://<HUB_IP>:5001 --device <name>

# Run connectivity diagnostics
python sentinel_client.py --hub http://<HUB_IP>:5001 --test
```

Find your hub IP on macOS: `ipconfig getifaddr en0`

---

## Key Capabilities

### Monitoring
- Real-time health metrics: CPU, memory, disk, network, power
- 5-second collection intervals
- Power monitoring: voltage, current, watts, quality score
- Security threat scanning every 30 seconds
- Lightweight — runs on Raspberry Pi

### Anomaly Detection (Adaptive — No Hardcoded Thresholds)
- **Adaptive IQR + Z-score**: All detection bounds learned from live data stream
- **Isolation Forest**: Multivariate point-in-time anomaly detection
- **LSTM Autoencoder**: Time-series sequence anomaly detection (Keras + PyTorch)
- Baseline freeze during anomalies + hysteresis reset
- 5-minute cooldown per metric, 2+ consecutive readings required
- Warmup gate: anomaly alerts suppressed for first 3 minutes (baseline settling)

### Intelligent Diagnosis
- Rule-based engine (fast, deterministic)
- **Groq llama-3.3-70b** (primary AI — free tier, fast)
- **Ollama llama3.2:3b** (local fallback — offline capable)
- Runs in background thread to avoid blocking the event bus

### Autonomous Recovery (15+ Actions, Graduated Escalation)
- **Level 1** — gentle: throttle CPU process, compact memory, flush DNS
- **Level 2** — moderate: clear cache, rotate logs, reset network interface
- **Level 3** — aggressive: kill top CPU/memory process, emergency disk cleanup
- **Level 4** — critical: restart services
- Outcome verification 30 seconds after each action
- Escalation resets per metric when issue resolves

### Distributed Device Monitoring
- Connect any number of remote machines via `sentinel_client.py`
- Per-device full panel: metrics, chart, anomaly/diagnosis/recovery feeds, incident timeline
- Direct HTTP command push to remote devices (port 5002, <50ms) with queue fallback
- Controlled instability (CPU spike, memory pressure, disk fill, stop) on any remote device
- Live adaptive threshold indicators on remote device metric cards

### Adaptive Learning
- Incident persistence (SQLite)
- Threshold optimization based on false positive rates
- Strategy refinement based on recovery action success rates

### Security Monitoring
- Open port scanning, connection flood detection, privileged process checks
- Demo mode: synthetic threats for visibility
- Purple security alerts bypass warmup gate (always shown immediately)

---

## Architecture

```
+----------------------------------------------------------+
|                  Sentinel AI Hub (main.py)               |
|                                                          |
|  MonitoringAgent --> AnomalyAgent --> DiagnosisAgent     |
|        |                                   |             |
|  SecurityAgent             Groq AI / Ollama AI           |
|        |                                   |             |
|  RemoteDeviceManager           RecoveryAgent (L1-L4)     |
|        |                                   |             |
|  Event Bus (in-memory)         LearningAgent             |
|        |                                   |             |
|  Flask Dashboard (port 5001)   SQLite                    |
+----------------------------------------------------------+
          ^ HTTP POST metrics every 5s
          | HTTP command push (port 5002) v
+--------------------------+
|  Remote Machines         |
|  (sentinel_client.py)    |
|  macOS / Linux / Windows |
+--------------------------+
```

---

## Dashboard Tabs

| Tab | Description |
|-----|-------------|
| Overview | Live gauges, agent status, real-time chart, toast notifications |
| Incidents | Full incident timeline with diagnosis + recovery detail |
| Simulation Lab | Trigger CPU spike, memory pressure, disk fill, power sag |
| Distributed Devices | Per-device panels for all connected remote machines |
| Security | Threat feed, open ports, connection stats |

---

## Simulation Lab

Trigger scenarios from the dashboard UI or directly via API:

| Scenario | API |
|---|---|
| CPU Spike (95%) | `POST /api/simulate/start/cpu_overload` |
| Memory Pressure (90%) | `POST /api/simulate/start/memory_spike` |
| Disk Fill | `POST /api/simulate/start/disk_fill` |
| Power Sag (-0.75V) | `POST /api/simulate/start/power_sag` |
| Stop all | `POST /api/simulate/stop` |

---

## AI Stack

| Provider | Model | Role | Cost |
|---|---|---|---|
| **Groq** | llama-3.3-70b-versatile | Primary AI diagnosis | Free tier |
| **Ollama** | llama3.2:3b | Local fallback | Free (local) |
| Isolation Forest | sklearn | Multivariate anomaly | Free (local) |
| LSTM Autoencoder | Keras + PyTorch | Time-series anomaly | Free (local) |

Configure in `config/config.yaml`.

---

## Configuration

```yaml
# config/config.yaml
anomaly_detection:
  min_consecutive_readings: 2   # 2+ consecutive before alert fires
  cooldown_minutes: 5           # per-metric cooldown after alert

groq:
  enabled: true
  model: "llama-3.3-70b-versatile"

recovery:
  escalation_window_minutes: 30
  max_retries: 3
```

---

## Project Structure

```
sentinel_ai/
+-- main.py                          # Master orchestrator
+-- sentinel_client.py               # Remote device client
+-- run.sh                           # One-command startup (project root)
+-- connect.sh                       # Remote device auto-connect script
+-- config/
|   +-- config.yaml                  # Main configuration
|   +-- diagnosis_rules.yaml         # Rule-based diagnosis rules
+-- agents/
|   +-- monitoring/                  # CPU/memory/disk/network/power collection
|   |   +-- remote_device_manager.py # Manages connected remote devices
|   +-- anomaly/                     # Adaptive IQR + z-score + ML detection
|   |   +-- keras_lstm_detector.py   # LSTM Autoencoder
|   +-- diagnosis/                   # Groq AI + Ollama + rule-based
|   +-- recovery/                    # 15+ actions, graduated escalation L1-L4
|   +-- learning/                    # SQLite persistence + threshold adaptation
|   +-- security/                    # Threat scanning (demo mode)
+-- dashboard/
|   +-- app.py                       # Flask API (port 5001)
|   +-- templates/dashboard.html     # Glassmorphism dark UI
+-- simulation/                      # InstabilityRunner (cpu/memory/disk/power)
+-- core/
|   +-- event_bus.py                 # In-memory event bus connecting all agents
+-- tests/
|   +-- test_unit.py                 # 52-test unit suite
+-- docs/                            # Architecture, deployment, testing guides
```

---

## Unit Tests

```bash
cd sentinel_ai
source venv/bin/activate
python -m pytest tests/test_unit.py -v
# 52 tests covering all core components
```

---

## Deployment

### Raspberry Pi
```bash
pip3 install -r requirements.txt
python3 main.py
```

### systemd service (Linux)
```bash
sudo cp deployment/systemd/sentinel-ai.service /etc/systemd/system/
sudo systemctl enable sentinel-ai
sudo systemctl start sentinel-ai
```

---

## Security Notes

- No hardcoded credentials — all secrets via environment variables (`.env`)
- `.env` is in `.gitignore` and never committed
- AP Isolation: if remote clients cannot connect on WiFi, disable "AP Isolation" / "Client Isolation" in router settings

---

## Performance (Raspberry Pi 3B+)

- CPU overhead: 5-10%
- Memory: 100-200 MB
- Metric collection latency: <100ms
- Anomaly detection latency: <500ms
- Recovery action: 1-30s
- Remote command push latency: <50ms (direct) / ~1s (queue fallback)

---

**Built for autonomous IoT infrastructure monitoring.**
