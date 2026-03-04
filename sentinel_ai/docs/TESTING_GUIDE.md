# Sentinel AI - Testing Guide

## Overview

This guide walks you through testing the multi-agent system step-by-step, starting with basic system monitoring and progressing to full self-healing demonstrations.

## Testing Philosophy

**Test in this order:**
1. ✅ System monitoring (logs, metrics collection)
2. ✅ Anomaly detection (CPU/RAM overload)
3. ✅ Diagnosis (root cause analysis)
4. ✅ Recovery (autonomous actions)
5. ✅ Learning (adaptation)
6. ✅ IoT components (sensors, MQTT)

## Prerequisites

```bash
cd sentinel_ai

# Install dependencies
pip install -r requirements.txt

# Ensure database directory exists
mkdir -p data logs
```

## Test 1: Basic System Monitoring

### Objective
Verify that MonitoringAgent collects system metrics correctly.

### Steps

```bash
# Run the test workflow
python3 test_workflow.py
```

**OR manually:**

```python
python3 << 'EOF'
import time
from core.config import get_config
from core.logging import setup_logging, get_logger
from core.event_bus import get_event_bus
from core.database import get_database
from agents.monitoring import MonitoringAgent

# Initialize
config = get_config()
config.set('aws.enabled', False)
setup_logging(config)
event_bus = get_event_bus(config)
database = get_database(config)

# Track events
metrics_received = []

def on_metric(event):
    metrics_received.append(event)
    print(f"Metrics collected: {len(metrics_received)}")
    if len(metrics_received) == 1:
        m = event.data['metrics']
        print(f"  CPU: {m.get('cpu', {}).get('cpu_percent', 0):.1f}%")
        print(f"  Memory: {m.get('memory', {}).get('memory_percent', 0):.1f}%")
        print(f"  Disk: {m.get('disk', {}).get('disk_percent', 0):.1f}%")

event_bus.subscribe("health.metric", on_metric)

# Start monitoring
agent = MonitoringAgent('MonitoringAgent', config, event_bus, get_logger('Monitor'), database)
agent.start()

print("Collecting metrics for 15 seconds...")
time.sleep(15)

agent.stop()
event_bus.stop()

print(f"\n✅ Test PASSED: Collected {len(metrics_received)} metric snapshots")
EOF
```

### Expected Result

```
Metrics collected: 1
  CPU: 12.3%
  Memory: 45.6%
  Disk: 67.8%
Metrics collected: 2
Metrics collected: 3

✅ Test PASSED: Collected 3 metric snapshots
```

### Verification

Check the database:
```bash
sqlite3 data/sentinel.db "SELECT COUNT(*) FROM metrics_history;"
```

Should show multiple entries.

## Test 2: CPU Overload Detection

### Objective
Trigger CPU overload and verify anomaly detection → diagnosis → recovery flow.

### Manual Test

```python
python3 << 'EOF'
import time
import psutil
import threading
from core.config import get_config
from core.logging import setup_logging, get_logger
from core.event_bus import get_event_bus
from core.database import get_database

from agents.monitoring import MonitoringAgent
from agents.anomaly import AnomalyDetectionAgent
from agents.diagnosis import DiagnosisAgent
from agents.recovery import RecoveryAgent

# Initialize
config = get_config()
config.set('aws.enabled', False)
config.set('recovery.auto_recovery', True)

setup_logging(config)
event_bus = get_event_bus(config)
database = get_database(config)

# Track events
anomalies = []
diagnoses = []
recoveries = []

event_bus.subscribe("anomaly.detected", lambda e: anomalies.append(e))
event_bus.subscribe("diagnosis.complete", lambda e: diagnoses.append(e))
event_bus.subscribe("recovery.action", lambda e: recoveries.append(e))

# Start all agents
agents = [
    MonitoringAgent('Monitor', config, event_bus, get_logger('Monitor'), database),
    AnomalyDetectionAgent('Anomaly', config, event_bus, get_logger('Anomaly'), database),
    DiagnosisAgent('Diagnosis', config, event_bus, get_logger('Diagnosis'), database),
    RecoveryAgent('Recovery', config, event_bus, get_logger('Recovery'), database),
]

for agent in agents:
    agent.start()

print("Agents started. Waiting for baseline...")
time.sleep(10)

print("\n🔥 Triggering CPU overload...")

# CPU stress
stop_event = threading.Event()

def cpu_burner():
    while not stop_event.is_set():
        _ = sum(i*i for i in range(100000))

# Start CPU burners
cpu_count = psutil.cpu_count()
threads = []

for _ in range(cpu_count):
    t = threading.Thread(target=cpu_burner, daemon=True)
    t.start()
    threads.append(t)

print(f"Started {cpu_count} CPU burner threads")

# Monitor for 30 seconds
for i in range(30):
    time.sleep(1)
    cpu = psutil.cpu_percent(interval=0.1)
    print(f"CPU: {cpu:.1f}% | Anomalies: {len(anomalies)} | Diagnoses: {len(diagnoses)}", end='\r')

    if len(anomalies) > 0:
        print(f"\n✅ Anomaly detected after {i+1}s!")
        break

# Stop CPU stress
stop_event.set()
for t in threads:
    t.join(timeout=1)

print("\nCPU stress stopped. Waiting for diagnosis/recovery...")
time.sleep(10)

# Results
print("\n" + "="*60)
print("RESULTS:")
print("="*60)
print(f"Anomalies detected: {len(anomalies)}")
print(f"Diagnoses completed: {len(diagnoses)}")
print(f"Recovery actions: {len(recoveries)}")

if len(anomalies) > 0:
    print("\nAnomaly Details:")
    a = anomalies[0].data['anomaly']
    print(f"  Metric: {a['metric_name']}")
    print(f"  Type: {a['type']}")
    print(f"  Severity: {a['severity']}")

if len(diagnoses) > 0:
    print("\nDiagnosis Details:")
    d = diagnoses[0].data['diagnosis']
    print(f"  Diagnosis: {d['diagnosis']}")
    print(f"  Actions: {d['recommended_actions']}")

if len(recoveries) > 0:
    print("\nRecovery Details:")
    for action in recoveries[0].data['actions']:
        print(f"  {action['action_name']}: {action['status']}")

# Cleanup
for agent in agents:
    agent.stop()
event_bus.stop()

print("\n✅ Test complete!")
EOF
```

### Expected Output

```
Agents started. Waiting for baseline...

🔥 Triggering CPU overload...
Started 4 CPU burner threads
CPU: 98.2% | Anomalies: 0 | Diagnoses: 0
✅ Anomaly detected after 8s!

CPU stress stopped. Waiting for diagnosis/recovery...

============================================================
RESULTS:
============================================================
Anomalies detected: 1
Diagnoses completed: 1
Recovery actions: 1

Anomaly Details:
  Metric: cpu.cpu_percent
  Type: threshold
  Severity: critical

Diagnosis Details:
  Diagnosis: High CPU usage caused by process python3 consuming 95%
  Actions: ['kill_process', 'restart_service']

Recovery Details:
  kill_process: skipped (cooldown_active or not enabled)

✅ Test complete!
```

## Test 3: Memory Spike Detection

### Automated Test

```bash
# Run automated test
python3 test_workflow.py
```

This will:
1. Allocate 30% of available memory
2. Wait for anomaly detection
3. Verify diagnosis
4. Release memory
5. Check recovery suggestions

### Manual Memory Test

```python
python3 << 'EOF'
import time
import psutil
from core.config import get_config
from core.logging import setup_logging
from core.event_bus import get_event_bus
from core.database import get_database
from agents.monitoring import MonitoringAgent
from agents.anomaly import AnomalyDetectionAgent

config = get_config()
config.set('aws.enabled', False)
setup_logging(config)
event_bus = get_event_bus(config)

anomalies = []
event_bus.subscribe("anomaly.detected", lambda e: anomalies.append(e))

# Start agents
monitor = MonitoringAgent('Monitor', config, event_bus, None, None)
detector = AnomalyDetectionAgent('Anomaly', config, event_bus, None, None)

monitor.start()
detector.start()

print("Waiting for baseline...")
time.sleep(10)

print("\n💾 Allocating memory...")
mem = psutil.virtual_memory()
target_mb = int((mem.available / (1024*1024)) * 0.3)

memory_hog = []
for i in range(target_mb):
    memory_hog.append(' ' * (1024*1024))
    if i % 50 == 0:
        print(f"  Allocated: {i}MB / {target_mb}MB", end='\r')

print(f"\n  Memory usage: {psutil.virtual_memory().percent:.1f}%")

print("\nWaiting for detection...")
for i in range(20):
    time.sleep(1)
    print(f"  {i+1}s | Anomalies: {len(anomalies)}", end='\r')
    if len(anomalies) > 0:
        break

memory_hog.clear()

if len(anomalies) > 0:
    print(f"\n✅ Memory anomaly detected!")
    a = anomalies[0].data['anomaly']
    print(f"  Metric: {a['metric_name']}")
    print(f"  Value: {a['value']:.1f}%")
else:
    print("\n❌ No anomaly detected")

monitor.stop()
detector.stop()
event_bus.stop()
EOF
```

## Test 4: End-to-End Workflow

### Complete System Test

```bash
# Run full automated test suite
python3 test_workflow.py
```

This executes 6 comprehensive tests:
1. ✅ Basic System Monitoring
2. ✅ CPU Overload Detection
3. ✅ Memory Spike Detection
4. ✅ Recovery Action Execution
5. ✅ Database Persistence
6. ✅ Learning & Adaptation

### Expected Output

```
================================================================================
SENTINEL AI - COMPREHENSIVE TEST WORKFLOW
================================================================================

Initializing agents...
✅ All agents initialized

Starting agents...
  ✅ monitoring started
  ✅ anomaly started
  ✅ diagnosis started
  ✅ recovery started
  ✅ learning started

================================================================================
TEST: Basic System Monitoring
================================================================================
Expected: Agent collects CPU, memory, disk metrics

Waiting for monitoring agent to collect metrics...
  Metrics collected: 3/3

Latest Metrics Collected:
  CPU: 15.2%
  Memory: 52.3%
  Disk: 45.1%

✅ PASSED in 15.23s

================================================================================
TEST: CPU Overload Detection
================================================================================
Expected: Detect high CPU, diagnose, suggest recovery

Triggering CPU overload...
  Starting 4 CPU stress threads...
  Waiting for anomaly detection (max 30s)...
  CPU: 97.8% | Anomalies: 1

🚨 ANOMALY DETECTED: cpu.cpu_percent - threshold
   Severity: critical
   Value: 97.80

🔍 DIAGNOSIS: High CPU usage caused by process python3 consuming 95%
   Root Cause: cpu_high_with_process
   Actions: ['kill_process', 'restart_service']

  CPU stress stopped
  Waiting for diagnosis and recovery...

  Results:
    Anomalies detected: 1
    Diagnoses completed: 1
    Recovery actions: 0

✅ PASSED in 22.45s

... (more tests)

================================================================================
TEST SUMMARY
================================================================================

Total Tests: 6
✅ Passed: 5
❌ Failed: 1
⚠️  Errors: 0

Success Rate: 83.3%
```

## Test 5: Database Verification

### Check Stored Incidents

```bash
# View incidents
sqlite3 data/sentinel.db << 'EOF'
.headers on
.mode column

SELECT
    incident_id,
    timestamp,
    severity,
    anomaly_type,
    recovery_status
FROM incidents
ORDER BY timestamp DESC
LIMIT 5;
EOF
```

### Check Metrics History

```bash
sqlite3 data/sentinel.db << 'EOF'
SELECT
    metric_type,
    COUNT(*) as count,
    AVG(value) as avg_value,
    MAX(value) as max_value
FROM metrics_history
GROUP BY metric_type;
EOF
```

### Check Anomalies

```bash
sqlite3 data/sentinel.db << 'EOF'
SELECT
    metric_name,
    anomaly_type,
    severity,
    COUNT(*) as occurrences
FROM anomalies
GROUP BY metric_name, anomaly_type, severity;
EOF
```

## Test 6: IoT Components (Next Phase)

After validating basic system monitoring and recovery, test IoT-specific components:

### MQTT Connectivity Test

```python
# Test MQTT monitoring
python3 << 'EOF'
import time
from core.config import get_config
from core.logging import setup_logging
from core.event_bus import get_event_bus
from agents.monitoring import MonitoringAgent

config = get_config()
config.set('monitoring.metrics.mqtt.enabled', True)
config.set('monitoring.metrics.mqtt.broker_host', 'localhost')

setup_logging(config)
event_bus = get_event_bus(config)

def check_mqtt(event):
    mqtt_metrics = event.data['metrics'].get('mqtt', {})
    print(f"MQTT Connected: {mqtt_metrics.get('mqtt_connected', False)}")
    print(f"MQTT Latency: {mqtt_metrics.get('mqtt_latency_ms', 0):.1f}ms")

event_bus.subscribe("health.metric", check_mqtt)

agent = MonitoringAgent('Monitor', config, event_bus, None, None)
agent.start()

time.sleep(15)
agent.stop()
event_bus.stop()
EOF
```

### Sensor Integration Test

Add your actual sensor code to `agents/monitoring/monitoring_agent.py` in the `collect_sensor_metrics()` method.

## Test 7: Real-Time Monitoring

### Watch Logs in Real-Time

```bash
# Terminal 1: Run Sentinel AI
python3 main.py

# Terminal 2: Watch logs
tail -f logs/sentinel.log | jq '.'

# Terminal 3: Trigger load
python3 -c "
import threading
def stress():
    while True:
        _ = sum(i*i for i in range(1000000))
threads = [threading.Thread(target=stress) for _ in range(4)]
for t in threads: t.start()
"
```

## Troubleshooting

### No Anomalies Detected

**Issue**: System doesn't detect overload

**Solutions**:
1. Lower thresholds in `config/config.yaml`:
   ```yaml
   monitoring:
     metrics:
       cpu:
         threshold_percent: 50  # Lower from 80
   ```

2. Increase stress intensity:
   ```python
   # Use more threads
   for _ in range(cpu_count * 2):
       ...
   ```

### Recovery Actions Skipped

**Issue**: Recovery shows "skipped" or "not enabled"

**Solutions**:
1. Enable actions in config:
   ```yaml
   recovery:
     auto_recovery: true
     actions:
       kill_process:
         enabled: true
   ```

2. Wait for cooldown to expire (5 minutes default)

### Database Errors

**Issue**: SQLite errors or permission denied

**Solutions**:
```bash
# Fix permissions
chmod 755 data/
chmod 644 data/sentinel.db

# Reset database
rm data/sentinel.db
python3 main.py  # Will recreate
```

## Next Steps

Once all basic tests pass:

1. ✅ **IoT Integration**: Add real sensor monitoring
2. ✅ **AWS Integration**: Enable cloud sync (optional)
3. ✅ **Production Deployment**: Deploy to Raspberry Pi
4. ✅ **Fleet Management**: Scale to multiple devices

## Summary Checklist

- [ ] Basic monitoring works (collects CPU, memory, disk)
- [ ] CPU overload detected within 30s
- [ ] Memory spike detected within 20s
- [ ] Diagnosis provides root cause
- [ ] Recovery actions suggested (or executed if enabled)
- [ ] Incidents stored in database
- [ ] Logs show complete workflow
- [ ] No errors in systemd logs (if deployed)

Once all checkboxes are complete, your multi-agent system is validated! ✅
