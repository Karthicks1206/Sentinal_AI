# Getting Started with Sentinel AI

## What You Have

A complete autonomous IoT monitoring system:

- **7 agents** running concurrently (Monitoring, Anomaly, Diagnosis, Recovery, Learning, Security, RemoteDeviceManager)
- **LLM-powered diagnosis** via Groq (free, fast) or Ollama (local, offline)
- **Multi-device support** — any machine on your network can send metrics to the hub
- **Self-healing recovery** — 15+ actions, 4 escalation levels, outcome verification
- **Real-time dashboard** — dark glassmorphism UI at http://localhost:5001

---

## First Run

### Prerequisites (hub machine — macOS)

- Python 3.9+
- Ollama installed: `brew install ollama`
- Dependencies installed in venv (already done if you received this project)

### Start everything

```bash
cd /Users/karthi/Desktop/Sentinal_AI/sentinel_ai
kill $(lsof -ti :5001) 2>/dev/null; pkill -f "python.*main.py" 2>/dev/null
source venv/bin/activate
brew services start ollama
python main.py
```

Open the dashboard: http://localhost:5001

---

## Dashboard Walkthrough

### Overview tab
- Four SVG arc gauges: CPU / Memory / Disk / Power
- Agent status cards (green = running)
- Toast notifications appear top-right when anomalies fire
- Real-time line chart: CPU, Memory, Disk, Power Quality
- "Learned fence" badges show the adaptive anomaly thresholds

### Simulation Lab tab
Trigger controlled failures to watch the full pipeline:
1. Click **CPU Spike** — CPU goes to 95% for 60 seconds
2. Wait ~15 seconds — anomaly fires, toast appears
3. Watch the Diagnosis and Recovery cards populate
4. Check the Incidents tab for the full event record

### Distributed Devices tab
Monitor remote machines:
1. Connect a remote device (see below)
2. It appears in the left sidebar with a green dot
3. Click the device name to open its full panel
4. Run stress tests on the remote device directly from the dashboard

### Incidents tab
Full timeline of every detected anomaly with diagnosis, recovery actions, and outcome.

---

## Connect a Remote Device

### Method 1 — Auto-connect script (easiest)

Copy `sentinel_client_package/` to the remote machine, then:

```bash
bash connect.sh
# Follow the prompts — it installs dependencies, tests connectivity, and connects
```

### Method 2 — Manual

```bash
pip install psutil requests
python sentinel_client.py --hub http://<HUB_IP>:5001 --device MyLaptop
```

### Find hub IP (on the hub machine)
```bash
ipconfig getifaddr en0
```

### Diagnose connection issues
```bash
python sentinel_client.py --hub http://<HUB_IP>:5001 --test
```

---

## Agent Pipeline

```
Remote Device / Local Sensors
        |
        v
  MonitoringAgent  ------>  EventBus  ------>  AnomalyDetectionAgent
                                                      |
                                              (IQR + Z-score + Isolation Forest + LSTM)
                                                      |
                                                      v
                                              DiagnosisAgent
                                              (Rules + Groq AI + Ollama)
                                                      |
                                                      v
                                              RecoveryAgent
                                              (Level 1-4 graduated actions)
                                                      |
                                                      v
                                              LearningAgent
                                              (SQLite persistence, threshold adaptation)
```

SecurityAgent runs independently, publishing `security.threat` events directly to the bus.

---

## AI Integration

| Provider | When Used | Config |
|---|---|---|
| Groq llama-3.3-70b | Primary diagnosis AI | `groq.enabled: true` in config.yaml |
| Ollama llama3.2:3b | Fallback when Groq unavailable | Runs locally via `brew services start ollama` |
| Isolation Forest | Multivariate anomaly detection | Always active, no config needed |
| LSTM Autoencoder | Time-series anomaly (trains after ~6.5 min) | Keras + PyTorch backend |

---

## Key Configuration

Edit `sentinel_ai/config/config.yaml`:

```yaml
anomaly_detection:
  min_consecutive_readings: 2   # readings before alert fires
  cooldown_minutes: 5           # cooldown per metric after alert

groq:
  enabled: true
  model: "llama-3.3-70b-versatile"
  api_key: ""                   # or set GROQ_API_KEY in .env

recovery:
  escalation_window_minutes: 30

monitoring:
  collection_interval: 5        # seconds between metric collection
```

---

## Running Tests

```bash
cd sentinel_ai
source venv/bin/activate
python -m pytest tests/test_unit.py -v
# 52 unit tests covering all core components
```

---

## Project Structure at a Glance

```
sentinel_ai/
+-- main.py                    # Start here — starts all 7 agents + dashboard
+-- sentinel_client.py         # Copy this to remote machines
+-- agents/
|   +-- monitoring/            # Collects metrics every 5s
|   +-- anomaly/               # 4 detection methods
|   +-- diagnosis/             # Groq + Ollama + rules
|   +-- recovery/              # 15+ recovery actions
|   +-- learning/              # Incident DB + adaptation
|   +-- security/              # Threat scanning
+-- dashboard/app.py           # Flask server (port 5001)
+-- dashboard/templates/       # Single-page UI
+-- config/config.yaml         # All settings
+-- tests/test_unit.py         # 52 tests
```

---

## Common Workflows

### Watch an anomaly from start to finish
1. Start hub: `python main.py`
2. Wait 3 minutes (baseline warmup)
3. Open Simulation Lab tab
4. Click CPU Spike
5. Watch: toast notification -> Incidents tab populates -> Recovery executes

### Test remote device monitoring
1. Get hub IP: `ipconfig getifaddr en0`
2. On remote machine: `bash connect.sh`
3. Open Distributed Devices tab
4. Click the remote device name
5. Click CPU Spike in the Controlled Instability card

### Check what the anomaly detector learned
```bash
curl http://localhost:5001/api/thresholds | python3 -m json.tool
```
Returns the live IQR upper bounds learned from the last N data points.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Port 5001 in use | `kill $(lsof -ti :5001)` |
| No anomalies firing | Wait 3 min warmup; run a simulation |
| Remote client SSL error | Use `http://` not `https://` |
| Remote client connection refused | Check hub IP; hub must be running `main.py` |
| Ollama not responding | `brew services restart ollama` |
| Duplicate incidents flooding | Always `pkill -f "python.*main.py"` before restarting |
