# Sentinel AI - Quick Testing Guide

## 🚀 Quick Start Testing

### Option 1: Automated Full Test Suite (Recommended)

Run the comprehensive automated test:

```bash
cd sentinel_ai
python3 test_workflow.py
```

**What it does:**
1. ✅ Tests basic monitoring (CPU, memory, disk)
2. ✅ Triggers CPU overload and verifies detection
3. ✅ Triggers memory spike and verifies detection
4. ✅ Checks recovery action execution
5. ✅ Verifies database persistence
6. ✅ Tests learning and adaptation

**Expected duration:** 2-3 minutes

**Expected output:**
```
================================================================================
SENTINEL AI - COMPREHENSIVE TEST WORKFLOW
================================================================================

TEST: Basic System Monitoring
Expected: Agent collects CPU, memory, disk metrics
✅ PASSED in 15.23s

TEST: CPU Overload Detection
Expected: Detect high CPU, diagnose, suggest recovery
🚨 ANOMALY DETECTED: cpu.cpu_percent - threshold
   Severity: critical
   Value: 97.80
🔍 DIAGNOSIS: High CPU usage caused by process python3
✅ PASSED in 22.45s

... (more tests)

TEST SUMMARY
Total Tests: 6
✅ Passed: 5
Success Rate: 83.3%
```

---

### Option 2: Real-Time Visual Monitor

Watch the system in real-time with a live dashboard:

```bash
cd sentinel_ai
python3 monitor_realtime.py
```

**What you'll see:**
```
================================================================================
SENTINEL AI - REAL-TIME MONITORING DASHBOARD
Time: 2024-01-15 10:30:45
================================================================================

AGENT STATUS:
--------------------------------------------------------------------------------
  🟢 monitoring: RUNNING
  🟢 anomaly: RUNNING
  🟢 diagnosis: RUNNING
  🟢 recovery: RUNNING

CURRENT METRICS:
--------------------------------------------------------------------------------
  CPU:    [████████████░░░░░░░░░░░░░░░░░░] 42.5%
  Memory: [████████████████████░░░░░░░░░░] 65.3%
  Disk:   [██████████████░░░░░░░░░░░░░░░░] 48.1%
  Network: Packet Loss: 0.0%

RECENT ANOMALIES:
--------------------------------------------------------------------------------
  No anomalies detected (system healthy)

Press Ctrl+C to stop monitoring
```

**Then in another terminal, trigger a test:**

```bash
# Trigger CPU overload
python3 -c "
import threading
def burn():
    while True: _ = sum(i*i for i in range(1000000))
for _ in range(4):
    threading.Thread(target=burn, daemon=True).start()
import time; time.sleep(60)
"
```

Watch the monitor detect, diagnose, and respond!

---

### Option 3: Step-by-Step Manual Testing

Follow the detailed guide:

```bash
cat docs/TESTING_GUIDE.md
```

Or run individual tests:

#### Test 1: Basic Monitoring Only

```bash
python3 << 'EOF'
import time
from core.config import get_config
from core.logging import setup_logging
from core.event_bus import get_event_bus
from agents.monitoring import MonitoringAgent

config = get_config()
config.set('aws.enabled', False)
setup_logging(config)
event_bus = get_event_bus(config)

metrics_count = [0]

def on_metric(event):
    metrics_count[0] += 1
    if metrics_count[0] == 1:
        m = event.data['metrics']
        print(f"✅ Metrics collected:")
        print(f"   CPU: {m.get('cpu', {}).get('cpu_percent', 0):.1f}%")
        print(f"   Memory: {m.get('memory', {}).get('memory_percent', 0):.1f}%")

event_bus.subscribe("health.metric", on_metric)

agent = MonitoringAgent('Monitor', config, event_bus, None, None)
agent.start()

print("Collecting metrics for 15s...")
time.sleep(15)

agent.stop()
event_bus.stop()

print(f"✅ Collected {metrics_count[0]} snapshots")
EOF
```

#### Test 2: CPU Overload Detection

```bash
python3 test_workflow.py
# Runs full test including CPU overload
```

---

## 📊 Verify Results

### Check Database

```bash
# View incidents
sqlite3 data/sentinel.db "
SELECT timestamp, severity, anomaly_type, recovery_status
FROM incidents
ORDER BY timestamp DESC
LIMIT 5;
"

# Count anomalies
sqlite3 data/sentinel.db "
SELECT COUNT(*) as total_anomalies FROM anomalies;
"

# View metrics
sqlite3 data/sentinel.db "
SELECT metric_type, COUNT(*) as count, AVG(value) as avg
FROM metrics_history
GROUP BY metric_type;
"
```

### Check Logs

```bash
# View recent logs
tail -50 logs/sentinel.log

# Parse JSON logs
tail -50 logs/sentinel.log | jq '.'

# Filter errors only
tail -100 logs/sentinel.log | jq 'select(.level=="ERROR")'
```

---

## 🧪 Advanced Testing

### Simulate Different Scenarios

```python
# Memory spike test
python3 << 'EOF'
import time, psutil
from core.config import get_config
from core.logging import setup_logging
from core.event_bus import get_event_bus
from agents.monitoring import MonitoringAgent
from agents.anomaly import AnomalyDetectionAgent

config = get_config()
config.set('aws.enabled', False)
setup_logging(config)
event_bus = get_event_bus(config)

anomalies = []
event_bus.subscribe("anomaly.detected", lambda e: anomalies.append(e))

monitor = MonitoringAgent('M', config, event_bus, None, None)
detector = AnomalyDetectionAgent('A', config, event_bus, None, None)
monitor.start()
detector.start()

time.sleep(5)

print("💾 Allocating memory...")
mem_mb = int((psutil.virtual_memory().available / (1024*1024)) * 0.3)
memory_hog = [' ' * (1024*1024) for _ in range(mem_mb)]

print(f"   Usage: {psutil.virtual_memory().percent:.1f}%")
print("   Waiting 20s for detection...")

for i in range(20):
    time.sleep(1)
    if len(anomalies) > 0:
        print(f"\n✅ Anomaly detected after {i+1}s!")
        print(f"   Type: {anomalies[0].data['anomaly']['type']}")
        break
else:
    print("\n❌ No anomaly detected")

memory_hog.clear()
monitor.stop()
detector.stop()
event_bus.stop()
EOF
```

---

## 🎯 Testing Checklist

Before moving to IoT testing, verify:

- [ ] **Monitoring**: Collects CPU, memory, disk metrics every 5s
- [ ] **Detection**: Detects CPU overload within 30s
- [ ] **Detection**: Detects memory spike within 20s
- [ ] **Diagnosis**: Provides root cause analysis
- [ ] **Database**: Stores incidents in SQLite
- [ ] **Logs**: JSON logs written to logs/sentinel.log
- [ ] **Recovery**: Suggests or executes recovery actions

Once all boxes checked: ✅ **Ready for IoT integration!**

---

## 🔧 Troubleshooting

### No anomalies detected?

Lower thresholds in `config/config.yaml`:
```yaml
monitoring:
  metrics:
    cpu:
      threshold_percent: 50  # Lower from 80
    memory:
      threshold_percent: 60  # Lower from 85
```

### Tests fail?

```bash
# Check dependencies
pip install -r requirements.txt

# Check permissions
mkdir -p data logs
chmod 755 data logs

# Reset database
rm -f data/sentinel.db
```

### Want more detail?

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python3 test_workflow.py
```

---

## 📚 Next Steps

After all tests pass:

1. **IoT Integration**: Add real sensor monitoring
2. **MQTT Testing**: Test with real MQTT broker
3. **AWS Integration**: Enable cloud sync (optional)
4. **Production Deploy**: Deploy to Raspberry Pi

See `docs/TESTING_GUIDE.md` for detailed IoT testing steps.

---

## 🎬 Demo Video Flow

To demonstrate the system:

```bash
# Terminal 1: Start real-time monitor
python3 monitor_realtime.py

# Terminal 2: Trigger CPU overload
python3 -c "import threading; [threading.Thread(target=lambda: [sum(i*i for i in range(1000000)) for _ in iter(int, 1)], daemon=True).start() for _ in range(4)]; import time; time.sleep(60)"

# Terminal 3: Watch logs
tail -f logs/sentinel.log | jq 'select(.level=="WARNING" or .level=="ERROR")'
```

You'll see:
1. Monitor shows CPU spike to 95%+
2. 🚨 Anomaly detected
3. 🔍 Diagnosis identifies high CPU
4. 🔧 Recovery action suggested
5. Database stores incident

---

**Ready to test? Start with:**
```bash
python3 test_workflow.py
```
