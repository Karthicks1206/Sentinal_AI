# Sentinel AI - Web Dashboard

## 🎯 Overview

A beautiful, real-time web dashboard for monitoring Sentinel AI system. Watch as it detects anomalies, diagnoses issues, and executes recovery actions - all in real-time with visual alerts!

## 🚀 Quick Start

### Option 1: Using the startup script (Easiest)

```bash
cd sentinel_ai
./start_dashboard.sh
```

### Option 2: Direct Python execution

```bash
cd sentinel_ai
python3 dashboard/app.py
```

### Option 3: With custom port

```bash
cd sentinel_ai
python3 -c "from dashboard.app import run_dashboard; run_dashboard(port=8080)"
```

## 🌐 Access the Dashboard

Once started, open your browser and navigate to:

```
http://localhost:5000
```

Or from another device on the same network:

```
http://[YOUR_IP]:5000
```

## 📊 Dashboard Features

### 1. Real-Time Metrics
- **CPU Usage**: Live CPU percentage with visual progress bar
- **Memory Usage**: Current memory consumption
- **Disk Usage**: Disk space utilization
- **Network Status**: Packet loss monitoring

**Color Coding:**
- 🟢 Green: Normal (< 80%)
- 🟡 Yellow: Warning (80-90%)
- 🔴 Red: Critical (> 90%)

### 2. Agent Status Panel
Shows real-time status of all 5 agents:
- 🟢 Pulsing green = Running
- 🔴 Solid red = Stopped

**Agents:**
- Monitoring Agent
- Anomaly Detection Agent
- Diagnosis Agent
- Recovery Agent
- Learning Agent

### 3. Live System Logs
- Auto-scrolling log viewer
- Color-coded by severity:
  - 🔵 Blue: INFO
  - 🟡 Yellow: WARNING
  - 🔴 Red: ERROR

**Auto-clears and highlights when anomalies detected!**

### 4. Statistics Dashboard
Real-time counters:
- Total Anomalies Detected
- Diagnoses Completed
- Recovery Actions Executed
- Log Entries Generated

### 5. Anomaly Alert System
When an anomaly is detected:
1. ✅ Screen displays full-screen alert overlay
2. ✅ Shows anomaly details (severity, metric, value)
3. ✅ Displays diagnosis and root cause
4. ✅ Lists recommended recovery actions
5. ✅ Auto-dismisses after recovery complete

## 🧪 Testing the Dashboard

### Test 1: Watch Normal Operation

Just start the dashboard and watch it collect metrics:

```bash
./start_dashboard.sh
```

Open browser → `http://localhost:5000`

You should see:
- Metrics updating every 2 seconds
- Agents all showing green (running)
- Logs scrolling with "Metrics collected" messages

### Test 2: Trigger CPU Anomaly

**Terminal 1:** Run dashboard
```bash
./start_dashboard.sh
```

**Terminal 2:** Trigger CPU overload
```bash
python3 -c "
import threading
def burn():
    while True: _ = sum(i*i for i in range(1000000))

# Start CPU burners
for _ in range(4):
    threading.Thread(target=burn, daemon=True).start()

# Keep running for 60 seconds
import time
time.sleep(60)
"
```

**Watch the dashboard:**
1. ⏱️ CPU bar turns red (95%+)
2. 🚨 Alert overlay appears: "ANOMALY DETECTED!"
3. 🔍 Diagnosis shows: "High CPU usage..."
4. 🔧 Recommended actions displayed
5. 📋 Logs auto-scroll to show anomaly details

### Test 3: Trigger Memory Anomaly

**Terminal 2:** Trigger memory spike
```bash
python3 -c "
import psutil
import time

print('Allocating memory...')
mem_mb = int((psutil.virtual_memory().available / (1024*1024)) * 0.4)
memory_hog = [' ' * (1024*1024) for _ in range(mem_mb)]

print(f'Allocated {mem_mb}MB, holding for 60s...')
time.sleep(60)
print('Releasing memory...')
"
```

**Dashboard shows:**
- Memory bar goes yellow/red
- Alert: Memory anomaly detected
- Diagnosis with recommended actions

## 📸 Dashboard Screenshots

### Normal Operation
```
┌─────────────────────────────────────────────┐
│  🛡️ SENTINEL AI                             │
│  Autonomous Self-Healing IoT Infrastructure │
│  ● RUNNING                                  │
└─────────────────────────────────────────────┘

CPU: [████████░░░░░░░░] 42.5%    Memory: [██████████░░░░] 65.3%
Disk: [███████░░░░░░░░] 48.1%

Agent Status:
  🟢 Monitoring Agent: RUNNING
  🟢 Anomaly Detection: RUNNING
  🟢 Diagnosis Agent: RUNNING
  🟢 Recovery Agent: RUNNING
  🟢 Learning Agent: RUNNING

Statistics:
  Anomalies: 0  |  Diagnoses: 0  |  Recoveries: 0

Logs:
  [10:30:45] INFO: Metrics collected: CPU=42.5%, Memory=65.3%
  [10:30:50] INFO: Metrics collected: CPU=43.1%, Memory=65.2%
```

### During Anomaly
```
┌─────────────────────────────────────────────┐
│           🚨 ANOMALY DETECTED!              │
│                                             │
│  Anomaly detected: cpu.cpu_percent - spike │
│  Severity: CRITICAL                         │
│                                             │
│  Diagnosis:                                 │
│  High CPU usage caused by process python3   │
│                                             │
│  Root Cause: cpu_high_with_process          │
│                                             │
│  Recommended Actions:                       │
│  • kill_process                             │
│  • restart_service                          │
│                                             │
│  [Acknowledge]                              │
└─────────────────────────────────────────────┘
```

## 🔧 Configuration

### Change Port

Edit `dashboard/app.py` or run:

```python
from dashboard.app import run_dashboard
run_dashboard(port=8080)
```

### Remote Access

To allow access from other devices:

```python
run_dashboard(host='0.0.0.0', port=5000)
```

**Security Note:** Only expose to trusted networks!

### Custom Refresh Rates

Edit `templates/dashboard.html`:

```javascript
setInterval(updateMetrics, 2000);  // Change from 2000ms (2s)
setInterval(updateLogs, 1000);     // Change from 1000ms (1s)
```

## 🐛 Troubleshooting

### Dashboard won't start

**Error:** `ModuleNotFoundError: No module named 'flask'`

**Solution:**
```bash
pip install -r requirements.txt
```

### Can't access from browser

**Error:** Connection refused

**Solutions:**
1. Check dashboard is running:
   ```bash
   ps aux | grep "dashboard/app.py"
   ```

2. Verify port 5000 is not blocked:
   ```bash
   netstat -an | grep 5000
   ```

3. Try different port:
   ```bash
   python3 dashboard/app.py --port 8080
   ```

### Metrics not updating

**Issue:** Dashboard loads but shows "0%" everywhere

**Solutions:**
1. Wait 5-10 seconds for first metrics collection
2. Check logs in terminal for errors
3. Verify agents started successfully

### Alert not showing

**Issue:** CPU/Memory overload but no alert

**Solutions:**
1. Check anomaly detection is enabled in config:
   ```yaml
   anomaly_detection:
     enabled: true
   ```

2. Lower thresholds for testing:
   ```yaml
   monitoring:
     metrics:
       cpu:
         threshold_percent: 50
   ```

3. Check browser console for JavaScript errors (F12)

## 🎯 Use Cases

### 1. Development & Testing
Monitor your tests in real-time as you develop new features.

### 2. Demonstrations
Show stakeholders the self-healing capabilities with visual feedback.

### 3. Training
Use the dashboard to teach how autonomous systems work.

### 4. Production Monitoring
Deploy on a large screen for NOC (Network Operations Center) monitoring.

### 5. Debugging
Watch the complete flow: metric → anomaly → diagnosis → recovery

## 🚀 Advanced Usage

### Run Multiple Dashboards

Monitor multiple devices simultaneously:

```bash
# Device 1
DEVICE_ID=rpi-001 python3 dashboard/app.py --port 5001

# Device 2
DEVICE_ID=rpi-002 python3 dashboard/app.py --port 5002

# Device 3
DEVICE_ID=rpi-003 python3 dashboard/app.py --port 5003
```

Open three browser tabs for each port!

### Embed in Larger Dashboard

The dashboard can be embedded in an iframe:

```html
<iframe src="http://localhost:5000" width="100%" height="800px"></iframe>
```

### API Access

Use the REST API for custom integrations:

```bash
# Get current metrics
curl http://localhost:5000/api/metrics

# Get system status
curl http://localhost:5000/api/status

# Get recent logs
curl http://localhost:5000/api/logs

# Get statistics
curl http://localhost:5000/api/stats

# Get active alert
curl http://localhost:5000/api/alert
```

### Stream Events

Connect to Server-Sent Events endpoint:

```javascript
const eventSource = new EventSource('http://localhost:5000/api/stream');

eventSource.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('Event:', data);
};
```

## 📊 Performance

- **Resource Usage:**
  - CPU: ~1-2% additional overhead
  - Memory: ~50-100MB for Flask server
  - Network: ~1KB/s for real-time updates

- **Refresh Rates:**
  - Metrics: 2 seconds
  - Agent Status: 3 seconds
  - Logs: 1 second
  - Statistics: 5 seconds

## 🎨 Customization

### Change Theme Colors

Edit `templates/dashboard.html` CSS:

```css
/* Change primary color from cyan to purple */
background: linear-gradient(90deg, #00d4ff, #00ff88);
/* to */
background: linear-gradient(90deg, #9d00ff, #ff00dd);
```

### Add Custom Metrics

1. Collect metric in monitoring agent
2. Add to dashboard state in `app.py`
3. Display in HTML template

## 📝 Summary

The Sentinel AI Dashboard provides:
- ✅ Real-time visual monitoring
- ✅ Auto-clearing logs on anomaly detection
- ✅ Full-screen alerts with diagnosis
- ✅ Live agent status indicators
- ✅ Beautiful, modern UI
- ✅ Zero configuration required

**Start monitoring:**
```bash
./start_dashboard.sh
```

**Then open:** `http://localhost:5000`

Enjoy watching your autonomous self-healing system in action! 🚀
