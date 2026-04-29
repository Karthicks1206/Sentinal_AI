# Sentinel AI — System Architecture

## Overview

Sentinel AI is a four-layer distributed system: physical IoT sensors feed into a Raspberry Pi gateway, which streams to an AI hub running a multi-agent pipeline, all visualised through a real-time web dashboard.

---

## Layer 1 — Sensing & Actuation

Physical hardware connected to the ESP32-S3 (Heltec board):

| Sensor / Actuator | GPIO | Data |
|-------------------|------|------|
| Soil Moisture (capacitive) | 4 (ADC) | Raw ADC count, moisture % |
| Voltage Sensor Module | 5 (ADC) | Pump supply voltage (V) |
| Relay Module IN | 6 (OUT) | Pump ON / OFF |
| 5V Water Pump | via Relay NO | Irrigation actuation |

**ESP32 Firmware** (`hardware/raspberry_pi/esp32_main_v3.py`):
- MicroPython asyncio — two concurrent tasks: `sensor_task` (reads + outputs every 2s) and `cmd_task` (awaits serial commands)
- Autonomous irrigation: soil < 40% → relay HIGH → pump ON
- Manual override via `PUMP:ON` / `PUMP:OFF` serial commands (5-minute window)
- Outputs human-readable labeled lines over USB serial at 115200 baud

---

## Layer 2 — Gateway (Raspberry Pi 5)

**`sentinel_client.py`** runs on the Pi as a systemd user service.

Responsibilities:
- Opens `/dev/ttyUSB0` at 115200 baud and parses ESP32 output in a background thread
- Collects Pi system metrics (CPU, memory, disk, network) via psutil every 5s
- Merges IoT sensor data into the metrics payload
- HTTP POSTs to hub `/api/metrics/push` every 5s
- Polls hub `/api/devices/<id>/commands` for recovery actions to execute locally
- Executes actions: renice, kill, sync, purge, DNS flush, `PUMP:ON`/`PUMP:OFF` serial commands

The sentinel_client sends commands to the ESP32 **twice** with a 600ms gap to ensure the asyncio reader catches them.

---

## Layer 3 — Hub Multi-Agent Pipeline

All agents communicate through `core/event_bus.py` (in-memory pub/sub).

### MonitoringAgent
- Collects local metrics every 5s, publishes `health.metric` events
- `RemoteDeviceManager` — accepts pushes from remote clients, injects into event bus with `device_id`

### AnomalyDetectionAgent
Three detection layers running concurrently:

1. **Adaptive Z-score** — per-metric adaptive baselines with EMA drift detection; hysteresis prevents oscillation; baseline frozen during anomalies
2. **Isolation Forest** (sklearn) — multivariate point-in-time detection, fires as `ml_isolation_forest`
3. **Keras LSTM Autoencoder** (PyTorch backend) — trains after 60+ sequences (~6.5 min), detects time-series patterns

Anomaly gate: Groq validates before pipeline entry to filter false positives.

### DiagnosisAgent
Runs in a background thread (non-blocking). Priority:
1. Groq API — `llama-3.3-70b-versatile` (fast cloud inference)
2. Ollama — `llama3.2:3b` (local, air-gapped fallback)
3. Rule-based — 14 rules in `config/diagnosis_rules.yaml` (always available)

Publishes `diagnosis.complete` with root cause, severity, and recommended actions.

### RecoveryAgent
- Consumes `diagnosis.complete` events
- **Graduated escalation** L1 (gentle) → L4 (critical) tracked per metric category
- **Algorithmic Engine** (`agents/recovery/algorithmic_engine.py`):
  - Profiles root cause: `COMPUTE_BOUND` / `IO_WAIT_BOUND` / `MEMORY_THRASH` / `TRANSIENT_SPIKE` / `MULTI_PROCESS`
  - Applies targeted algorithm (renice, ionice, cache drop, OOM adjustment)
- Remote actions queued for Pi/other devices to execute
- **Zero-skip policy**: algorithmic fixes are cooldown-exempt; all other skips escalate to an alternative action
- 30-second outcome verification; re-escalates if metric not recovered

### LearningAgent
Observes resolved incidents and adjusts detection thresholds over time.

### SecurityAgent
Demo/stub mode — scans open ports, connections, privileged processes. 4% chance of synthetic threat per scan for demo visibility.

---

## Layer 4 — Dashboard

Flask app (`dashboard/app.py`) on port 5001.

**Local Device tab** — hub machine metrics, power card, simulation lab, incident timeline, activity log, ML anomaly feeds.

**Distributed Devices & IoT Nodes tab** — device selector sidebar, per-device metrics, IoT Sensors card, agent pipeline status, remote simulation controls, anomaly/diagnosis/recovery feeds.

**IoT Sensors card** (`distIotSensorCard`) — always visible for distributed devices, populated by `updateIotCard()` which polls `/api/devices/<id>/metrics` independently every 2 seconds.

---

## Event Flow

```
Pi push → /api/metrics/push
    └──► RemoteDeviceManager.push_metrics()
              └──► event_bus.create_event('health.metric', device_id=...)
                        │
              ┌─────────┘
              ▼
    AnomalyDetectionAgent._on_metric()
    (Z-score + IsoForest + LSTM)
              │ anomaly.detected
              ▼
    DiagnosisAgent._on_anomaly() [background thread]
    (Groq → Ollama → rules)
              │ diagnosis.complete
              ▼
    RecoveryAgent._on_diagnosis()
    (algorithmic engine → execute / queue remote)
              │ recovery.action
              ▼
    DashboardState._on_recovery() → activity log
```

---

## Configuration

`config/config.yaml` controls all tunable parameters:

```yaml
anomaly:
  min_consecutive_readings: 2
  cooldown_minutes: 1

recovery:
  cooldown_period_seconds: 20     # Algorithmic actions exempt from cooldown
  escalation_window_minutes: 30
  max_retries: 3

monitoring:
  interval_seconds: 5
```
