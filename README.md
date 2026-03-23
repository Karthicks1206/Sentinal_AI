# Sentinel AI — Autonomous Self-Healing IoT Infrastructure

[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![AI](https://img.shields.io/badge/AI-Groq%20%7C%20Ollama%20%7C%20Isolation%20Forest-purple.svg)]()

> **Production-ready multi-agent AI framework for autonomous monitoring, anomaly detection, LLM-powered diagnosis, and self-healing recovery across distributed IoT edge devices.**

---

## What is Sentinel AI?

Sentinel AI is an intelligent, distributed system that monitors IoT infrastructure in real-time, detects anomalies using adaptive statistical methods and machine learning, diagnoses root causes with AI assistance (Groq / Ollama), and autonomously executes recovery actions — all while learning and adapting from every incident.

**Think of it as:** Your IoT infrastructure's immune system that detects problems, diagnoses causes, heals itself, and gets smarter over time.

---

## Quick Start

```bash
cd sentinel_ai
source venv/bin/activate
brew services start ollama          # start local AI (macOS)
python main.py
```

Dashboard: **http://localhost:5001**

Or use the one-liner:
```bash
cd /Users/karthi/Desktop/Sentinal_AI/sentinel_ai && kill $(lsof -ti :5001) 2>/dev/null; pkill -f "python.*main.py" 2>/dev/null; source venv/bin/activate && brew services start ollama && python main.py
```

---

## Key Capabilities

### Monitoring
- Real-time health metrics: CPU, memory, disk, network, power
- 5-second collection intervals (configurable)
- Power monitoring: voltage, current, watts, quality score
- Security threat scanning every 30 seconds
- Lightweight — runs on Raspberry Pi

### Anomaly Detection (Adaptive — No Hardcoded Thresholds)
- **Adaptive IQR + Z-score**: All detection bounds learned from live data
- **Isolation Forest**: Multivariate point-in-time anomaly detection
- **LSTM Autoencoder**: Time-series sequence anomaly detection (Keras)
- Baseline freeze during anomalies + hysteresis reset
- 5-minute cooldown per metric, 2+ consecutive readings required
- Warmup gate: suppresses alerts for first 3 minutes (baseline settling)

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

### Adaptive Learning
- Incident persistence (SQLite locally, optional AWS DynamoDB/S3 sync)
- Threshold optimization based on false positive rates
- Strategy refinement based on recovery action success rates

### Security Monitoring
- Open port scanning, connection flood detection, privileged process checks
- Demo mode: synthetic threats for visibility
- Integrated into dashboard with purple security alerts

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Sentinel AI Hub (main.py)               │
│                                                          │
│  MonitoringAgent ──► AnomalyAgent ──► DiagnosisAgent    │
│        │                                    │            │
│  SecurityAgent              Groq AI / Ollama AI          │
│        │                                    │            │
│  RemoteDeviceManager            RecoveryAgent (L1-L4)   │
│        │                                    │            │
│  Event Bus (in-memory)          LearningAgent            │
│        │                                    │            │
│  Flask Dashboard (port 5001)    SQLite / AWS sync        │
└─────────────────────────────────────────────────────────┘
          ▲ HTTP POST metrics every 5s
          │
┌─────────┴──────────────────┐
│  Remote Machines            │
│  (sentinel_client.py v1.2) │
│  macOS / Linux / Windows   │
└────────────────────────────┘
```

---

## Multi-Device Monitoring

Connect any machine on your network in 2 steps:

```bash
# On the remote machine
pip install psutil
python sentinel_client.py
```

The client auto-discovers the hub via UDP broadcast (port 47474).

**Manual hub URL** (if auto-discovery fails):
```bash
python sentinel_client.py --hub http://192.168.1.x:5001
```

**Connection diagnostics** (--test flag, new in v1.2):
```bash
python sentinel_client.py --hub http://192.168.1.x:5001 --test
```

Full guide: [`MULTI_DEVICE_SETUP.txt`](MULTI_DEVICE_SETUP.txt)

---

## Dashboard

Glassmorphism dark UI with animated background:
- Live SVG arc gauges for CPU / Memory / Disk / Power
- Per-agent status cards with activity indicators
- Toast notifications (top-right, auto-dismiss 7s, severity-colored)
- Simulation Lab: trigger CPU spike, memory pressure, disk fill, power sag
- Incident timeline with full diagnosis + recovery details
- Real-time chart: CPU / Memory / Disk / Power Quality (live line chart)

---

## Simulation Lab

Trigger scenarios from the dashboard or API:

| Scenario | API endpoint |
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
├── main.py                          # Master orchestrator
├── sentinel_client.py               # Remote device client (v1.2)
├── config/
│   ├── config.yaml                  # Main configuration
│   └── diagnosis_rules.yaml         # Rule-based diagnosis rules
├── agents/
│   ├── monitoring/                  # CPU/memory/disk/network/power
│   ├── anomaly/                     # Adaptive IQR + z-score + ML
│   │   └── keras_lstm_detector.py   # LSTM Autoencoder
│   ├── diagnosis/                   # Groq AI + Ollama + rules
│   ├── recovery/                    # 15+ actions, graduated escalation
│   ├── learning/                    # SQLite persistence + AWS sync
│   └── security/                    # Threat scanning (demo mode)
├── dashboard/
│   ├── app.py                       # Flask API + SSE (port 5001)
│   └── templates/dashboard.html     # Glassmorphism UI
├── simulation/                      # Failure simulation (InstabilityRunner)
├── core/
│   └── event_bus.py                 # In-memory event bus
├── tests/
│   └── two_week_test_suite.py       # 14-day compressed test suite
└── docs/                            # Additional documentation
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

### Docker
```bash
cd sentinel_ai
docker-compose up -d
```

---

## Security Notes

- No hardcoded credentials — all secrets via environment variables (`.env`)
- `.env` is in `.gitignore` and never committed
- TLS/SSL for all AWS communication
- AP Isolation: if remote clients can't connect on WiFi, disable "AP Isolation" / "Client Isolation" in router settings

---

## Performance (Raspberry Pi 3B+)

- CPU overhead: 5-10%
- Memory: 100-200MB
- Metric collection latency: <100ms
- Anomaly detection latency: <500ms
- Recovery action: 1-30s
- Storage: ~100MB/day (90-day retention)

---

**Built for autonomous IoT infrastructure monitoring.**
