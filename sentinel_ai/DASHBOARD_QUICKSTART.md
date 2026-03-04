# 🚀 Sentinel AI Dashboard - Quick Start Guide

## 📺 What You'll See

A beautiful real-time web dashboard that:
- ✅ Shows live CPU, memory, and disk metrics
- ✅ Displays all 5 agents' status (green = running)
- ✅ Auto-scrolling system logs
- ✅ **Full-screen alerts when anomalies detected**
- ✅ **Auto-clears and highlights anomaly logs**
- ✅ Shows diagnosis and recovery actions in real-time

## 🎯 3-Step Quick Start

### Step 1: Install Dependencies
```bash
cd sentinel_ai
pip install -r requirements.txt
```

### Step 2: Start Dashboard
```bash
./start_dashboard.sh
```

### Step 3: Open Browser
```
http://localhost:5000
```

**That's it!** You should now see the dashboard running.

---

## 🧪 Test the Dashboard (See It In Action!)

### Test 1: Watch Normal Monitoring

Just watch the dashboard for 30 seconds. You'll see:
- ✅ Metrics updating every 2 seconds
- ✅ All agents showing green (running)
- ✅ Logs scrolling: "Metrics collected: CPU=X%, Memory=Y%"

### Test 2: Trigger CPU Anomaly 🔥

**Terminal 1:** Dashboard is running at `http://localhost:5000`

**Terminal 2:** Trigger CPU overload
```bash
cd sentinel_ai
python3 trigger_anomaly.py cpu --duration 60
```

**Watch the Magic:**
1. ⏱️ **After 5-10 seconds:** CPU bar turns red (95%+)
2. 🚨 **After 10-15 seconds:** Full-screen alert appears!
   ```
   ┌─────────────────────────────────────┐
   │      🚨 ANOMALY DETECTED!           │
   │                                     │
   │  cpu.cpu_percent - threshold        │
   │  Severity: CRITICAL                 │
   │                                     │
   │  Diagnosis:                         │
   │  High CPU usage caused by python3   │
   │                                     │
   │  Actions: kill_process, restart...  │
   │                                     │
   │  [Acknowledge]                      │
   └─────────────────────────────────────┘
   ```
3. 📋 **Logs auto-scroll and highlight:**
   ```
   🚨 ANOMALY: cpu.cpu_percent = 97.80 (severity: critical)
   🔍 DIAGNOSIS: High CPU usage caused by process python3
      Root Cause: cpu_high_with_process
      Actions: kill_process, restart_service
   ```

### Test 3: Trigger Memory Anomaly 💾

**Terminal 2:** Trigger memory spike
```bash
python3 trigger_anomaly.py memory --percent 40 --duration 60
```

**Watch:**
- Memory bar goes yellow/red (depending on your system)
- Alert: "Memory anomaly detected"
- Diagnosis with root cause

### Test 4: Combo Attack! 🚀

**Terminal 2:** Stress both CPU and memory
```bash
python3 trigger_anomaly.py combo --duration 45
```

**See:**
- Multiple anomalies detected
- Dashboard updates in real-time
- Statistics counter increases

---

## 📸 What You'll See

### Normal Dashboard
```
╔════════════════════════════════════════════════════╗
║          🛡️ SENTINEL AI                            ║
║   Autonomous Self-Healing IoT Infrastructure      ║
║          ● RUNNING                                 ║
╚════════════════════════════════════════════════════╝

┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ 🔥 CPU Usage     │ │ 💾 Memory Usage  │ │ 💿 Disk Usage    │
│                  │ │                  │ │                  │
│ Current: 42.5%   │ │ Current: 65.3%   │ │ Current: 48.1%   │
│ [████████░░░░░]  │ │ [█████████░░░░]  │ │ [██████░░░░░░]   │
└──────────────────┘ └──────────────────┘ └──────────────────┘

🤖 Agent Status:
  🟢 Monitoring Agent: RUNNING
  🟢 Anomaly Detection Agent: RUNNING
  🟢 Diagnosis Agent: RUNNING
  🟢 Recovery Agent: RUNNING
  🟢 Learning Agent: RUNNING

📊 Statistics:
  Anomalies: 0  |  Diagnoses: 0  |  Recoveries: 0  |  Logs: 45

📋 System Logs:
  [10:30:45] INFO: Metrics collected: CPU=42.5%, Memory=65.3%
  [10:30:50] INFO: Metrics collected: CPU=43.1%, Memory=65.2%
  [10:30:55] INFO: Metrics collected: CPU=42.8%, Memory=65.4%
```

### During Anomaly (Full-Screen Alert)
```
╔════════════════════════════════════════════════════╗
║                                                    ║
║                  🚨 ALERT ACTIVE 🚨                ║
║                                                    ║
║              ANOMALY DETECTED!                     ║
║                                                    ║
║  Anomaly detected: cpu.cpu_percent - spike        ║
║  Severity: CRITICAL                                ║
║                                                    ║
║  Diagnosis:                                        ║
║  High CPU usage caused by process python3         ║
║  consuming 95% CPU                                 ║
║                                                    ║
║  Root Cause: cpu_high_with_process                 ║
║                                                    ║
║  Recommended Actions:                              ║
║  • kill_process                                    ║
║  • restart_service                                 ║
║                                                    ║
║              [Acknowledge Alert]                   ║
║                                                    ║
╚════════════════════════════════════════════════════╝
```

### Logs During Anomaly (Auto-Scrolled)
```
📋 System Logs (Auto-scrolled to anomaly):

  [10:35:12] INFO: Metrics collected: CPU=97.8%, Memory=65.3%
  [10:35:12] WARNING: 🚨 ANOMALY: cpu.cpu_percent = 97.80 (severity: critical)
  [10:35:13] WARNING: 🔍 DIAGNOSIS: High CPU usage caused by process python3
  [10:35:13] INFO:    Root Cause: cpu_high_with_process
  [10:35:13] INFO:    Actions: kill_process, restart_service
  [10:35:15] INFO: 🔧 RECOVERY: Executing 1 action(s)
  [10:35:15] INFO:    ⚠️ kill_process: skipped (not enabled)
```

---

## 🎮 Complete Testing Workflow

### Two-Terminal Setup

**Terminal 1: Dashboard**
```bash
cd sentinel_ai
./start_dashboard.sh

# Output:
# Starting dashboard server...
# Open your browser: http://localhost:5000
# Press Ctrl+C to stop
```

**Terminal 2: Trigger Anomalies**
```bash
cd sentinel_ai

# Test 1: CPU (60 seconds)
python3 trigger_anomaly.py cpu

# Wait for alert, then acknowledge

# Test 2: Memory (60 seconds)
python3 trigger_anomaly.py memory --percent 35

# Wait for alert, then acknowledge

# Test 3: Combo (45 seconds)
python3 trigger_anomaly.py combo --duration 45
```

**Browser: Watch the Show**
1. Open `http://localhost:5000`
2. Watch metrics in real-time
3. See alerts pop up
4. Read diagnosis
5. Acknowledge alerts
6. Check statistics increase

---

## 💡 Pro Tips

### 1. Multiple Windows
Open the dashboard in multiple browser windows to simulate a NOC (Network Operations Center):
- Window 1: Full dashboard view
- Window 2: Just the metrics (zoom in)
- Window 3: Just the logs (auto-scrolling)

### 2. Mobile Access
Access from your phone/tablet:
```bash
# Find your IP
ifconfig | grep "inet "

# Example: 192.168.1.100
# Then open on phone: http://192.168.1.100:5000
```

### 3. Continuous Monitoring
Run longer tests:
```bash
# 10-minute CPU stress
python3 trigger_anomaly.py cpu --duration 600

# 5-minute memory test
python3 trigger_anomaly.py memory --duration 300
```

### 4. Custom Scenarios
Edit thresholds to trigger more easily:

`config/config.yaml`:
```yaml
monitoring:
  metrics:
    cpu:
      threshold_percent: 50  # Lower for easier testing
    memory:
      threshold_percent: 60  # Lower for easier testing
```

---

## 🐛 Troubleshooting

### Dashboard shows "0%" everywhere
**Wait 5-10 seconds** for first metric collection.

### Alert not appearing
1. Check browser console (F12) for errors
2. Verify anomaly detection is enabled in config
3. Try lowering thresholds (see Pro Tips #4)

### Can't connect to `localhost:5000`
1. Check dashboard is running (Terminal 1 should show "Running on...")
2. Try: `http://127.0.0.1:5000`
3. Check firewall/antivirus

### Agents showing red (stopped)
Wait 10-15 seconds for agents to start. If still red:
```bash
# Check logs
tail -50 logs/sentinel.log
```

---

## 📊 API Endpoints (Advanced)

Access data programmatically:

```bash
# Current metrics
curl http://localhost:5000/api/metrics | jq

# System status
curl http://localhost:5000/api/status | jq

# Recent logs
curl http://localhost:5000/api/logs | jq

# Statistics
curl http://localhost:5000/api/stats | jq

# Active alert
curl http://localhost:5000/api/alert | jq
```

---

## 🎯 Summary

**Start Dashboard:**
```bash
./start_dashboard.sh
```

**Open Browser:**
```
http://localhost:5000
```

**Trigger Test:**
```bash
python3 trigger_anomaly.py cpu
```

**Watch:**
- 🔴 Metrics go red
- 🚨 Alert appears
- 🔍 Diagnosis shows
- 📋 Logs auto-scroll

**Enjoy watching your self-healing system work!** 🚀

---

## 📚 More Information

- **Full Dashboard Guide:** `dashboard/README.md`
- **Testing Guide:** `docs/TESTING_GUIDE.md`
- **Main Documentation:** `docs/README.md`

---

**Made with ❤️ for autonomous IoT monitoring**
