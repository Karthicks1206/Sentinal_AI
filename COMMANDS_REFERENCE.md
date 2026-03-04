# 🎯 Sentinel AI - Command Reference

## 🚀 Quick Commands (Copy & Paste)

### **DEMO: See It Working (Recommended First)**
```bash
# Terminal 1: Start dashboard
cd sentinel_ai
./start_dashboard.sh

# Terminal 2: Open browser → http://localhost:5000

# Terminal 3: Run demo
cd sentinel_ai
./run_demo.sh
```

---

## 📺 Dashboard Commands

### Start Dashboard
```bash
./start_dashboard.sh
# Opens at: http://localhost:5000
```

### Custom Port
```bash
python3 dashboard/app.py --port 8080
```

### Remote Access (from other devices)
```bash
python3 -c "from dashboard.app import run_dashboard; run_dashboard(host='0.0.0.0', port=5000)"
# Access from: http://[YOUR_IP]:5000
```

---

## 🧪 Testing Commands

### Automated Test Suite
```bash
python3 test_workflow.py
# Runs 6 comprehensive tests (~3 minutes)
```

### Real-Time Monitor (CLI)
```bash
python3 monitor_realtime.py
# Terminal-based live monitoring
```

### Complete Workflow Demo
```bash
python3 demo_complete_workflow.py
# Shows detect → diagnose → auto-fix
```

---

## 🔥 Trigger Anomalies

### CPU Overload
```bash
# Default: 60 seconds
python3 trigger_anomaly.py cpu

# Custom duration: 30 seconds
python3 trigger_anomaly.py cpu --duration 30

# Custom intensity: 8 threads
python3 trigger_anomaly.py cpu --intensity 8
```

### Memory Spike
```bash
# Default: 30% of available memory for 60s
python3 trigger_anomaly.py memory

# Custom: 50% for 45 seconds
python3 trigger_anomaly.py memory --percent 50 --duration 45
```

### Combo (CPU + Memory)
```bash
# Both at once
python3 trigger_anomaly.py combo

# Custom duration: 30s
python3 trigger_anomaly.py combo --duration 30
```

---

## 💾 Database Commands

### View Incidents
```bash
sqlite3 data/sentinel.db "SELECT * FROM incidents ORDER BY timestamp DESC LIMIT 5;"
```

### View Anomalies
```bash
sqlite3 data/sentinel.db "SELECT metric_name, anomaly_type, severity, COUNT(*) as count FROM anomalies GROUP BY metric_name, anomaly_type, severity;"
```

### View Recovery Actions
```bash
sqlite3 data/sentinel.db "SELECT action_type, status, COUNT(*) as count FROM recovery_actions GROUP BY action_type, status;"
```

### Count Statistics
```bash
sqlite3 data/sentinel.db "
SELECT
  (SELECT COUNT(*) FROM incidents) as total_incidents,
  (SELECT COUNT(*) FROM anomalies) as total_anomalies,
  (SELECT COUNT(*) FROM recovery_actions) as total_recoveries;
"
```

### Export to CSV
```bash
sqlite3 data/sentinel.db -header -csv "SELECT * FROM incidents;" > incidents.csv
```

### Interactive Mode
```bash
sqlite3 data/sentinel.db
# Then run SQL queries interactively
# Exit with: .quit
```

---

## 📋 Log Commands

### View Recent Logs
```bash
tail -50 logs/sentinel.log
```

### Follow Logs (Real-Time)
```bash
tail -f logs/sentinel.log
```

### Parse JSON Logs
```bash
tail -50 logs/sentinel.log | jq '.'
```

### Filter by Level
```bash
# Errors only
tail -100 logs/sentinel.log | jq 'select(.level=="ERROR")'

# Warnings and errors
tail -100 logs/sentinel.log | jq 'select(.level=="WARNING" or .level=="ERROR")'
```

### Search Logs
```bash
# Search for "anomaly"
grep -i "anomaly" logs/sentinel.log | jq '.'

# Search for specific metric
grep "cpu_percent" logs/sentinel.log | jq '.'
```

### View Last N Lines with Timestamps
```bash
tail -20 logs/sentinel.log | jq '{timestamp: .timestamp, level: .level, message: .message}'
```

---

## 🎛️ Configuration Commands

### View Current Config
```bash
cat config/config.yaml
```

### Edit Config
```bash
nano config/config.yaml
# or
vim config/config.yaml
```

### Validate Config (Python)
```bash
python3 -c "from core.config import get_config; c=get_config(); print('Config valid!'); print(f'Device: {c.device_id}')"
```

### Show Specific Setting
```bash
python3 -c "from core.config import get_config; print(get_config().get('monitoring.collection_interval'))"
```

---

## 🏭 Production Commands

### Run Main System
```bash
python3 main.py
```

### Run with Custom Config
```bash
python3 main.py --config config/config_demo.yaml
```

### Run with Simulation
```bash
python3 main.py --simulate
```

### Background Mode (nohup)
```bash
nohup python3 main.py > logs/nohup.out 2>&1 &
```

### Check if Running
```bash
ps aux | grep "python3 main.py"
```

### Stop Background Process
```bash
pkill -f "python3 main.py"
```

---

## 🐳 Docker Commands

### Build Image
```bash
docker build -t sentinel-ai .
```

### Run Container
```bash
docker run -d --name sentinel \
  -e DEVICE_ID=rpi-001 \
  -e AWS_REGION=us-east-1 \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -p 5000:5000 \
  sentinel-ai
```

### Using Docker Compose
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Restart specific service
docker-compose restart sentinel-ai
```

### Check Container Status
```bash
docker ps | grep sentinel
```

### View Container Logs
```bash
docker logs -f sentinel
```

### Execute Command in Container
```bash
docker exec -it sentinel bash
```

---

## 🔧 systemd Commands (Linux Service)

### Install Service
```bash
sudo cp deployment/systemd/sentinel-ai.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sentinel-ai
```

### Start Service
```bash
sudo systemctl start sentinel-ai
```

### Stop Service
```bash
sudo systemctl stop sentinel-ai
```

### Restart Service
```bash
sudo systemctl restart sentinel-ai
```

### Check Status
```bash
sudo systemctl status sentinel-ai
```

### View Logs
```bash
# Recent logs
sudo journalctl -u sentinel-ai -n 50

# Follow logs
sudo journalctl -u sentinel-ai -f

# Logs since boot
sudo journalctl -u sentinel-ai -b
```

### Disable Service
```bash
sudo systemctl disable sentinel-ai
```

---

## 📊 Monitoring Commands

### Check System Resources
```bash
# CPU and Memory
htop

# Or using top
top

# Disk usage
df -h

# Directory sizes
du -sh data/ logs/
```

### Check Agent Status (via API)
```bash
curl http://localhost:5000/api/status | jq '.'
```

### Check Current Metrics (via API)
```bash
curl http://localhost:5000/api/metrics | jq '.'
```

### Check Recent Logs (via API)
```bash
curl http://localhost:5000/api/logs | jq '.'
```

### Check Statistics (via API)
```bash
curl http://localhost:5000/api/stats | jq '.'
```

---

## 🔄 Maintenance Commands

### Clear Old Logs
```bash
# Keep last 7 days
find logs/ -name "*.log" -mtime +7 -delete
```

### Backup Database
```bash
# Create backup
cp data/sentinel.db data/sentinel_backup_$(date +%Y%m%d).db

# Or use SQLite backup
sqlite3 data/sentinel.db ".backup data/sentinel_backup.db"
```

### Cleanup Old Data
```bash
sqlite3 data/sentinel.db "
DELETE FROM metrics_history WHERE timestamp < datetime('now', '-30 days');
DELETE FROM anomalies WHERE timestamp < datetime('now', '-30 days');
VACUUM;
"
```

### Reset Database (CAUTION!)
```bash
rm data/sentinel.db
# Will be recreated on next run
```

### Update Dependencies
```bash
pip install -r requirements.txt --upgrade
```

---

## 🧹 Cleanup Commands

### Stop All Processes
```bash
pkill -f sentinel
pkill -f dashboard
```

### Clear All Data (CAUTION!)
```bash
rm -rf data/*
rm -rf logs/*
```

### Fresh Start
```bash
# Stop everything
pkill -f sentinel

# Clear data
rm -rf data/* logs/*

# Restart
./start_dashboard.sh
```

---

## 🔍 Debugging Commands

### Enable Debug Logging
```bash
export LOG_LEVEL=DEBUG
python3 main.py
```

### Check Dependencies
```bash
pip list | grep -E "flask|psutil|pyyaml|boto3|scikit-learn"
```

### Test Individual Agent
```bash
python3 -c "
from core.config import get_config
from core.logging import setup_logging
from core.event_bus import get_event_bus
from agents.monitoring import MonitoringAgent

config = get_config()
setup_logging(config)
event_bus = get_event_bus(config)

agent = MonitoringAgent('Test', config, event_bus, None, None)
agent.start()

import time
time.sleep(10)
agent.stop()
print('Test complete!')
"
```

### Check Port Availability
```bash
# Check if port 5000 is in use
lsof -i :5000

# Or
netstat -an | grep 5000
```

---

## 🎓 Quick Scenarios

### Scenario: Fresh Installation
```bash
cd sentinel_ai
pip install -r requirements.txt
./quickstart.sh
./start_dashboard.sh
```

### Scenario: Quick Test
```bash
python3 test_workflow.py
```

### Scenario: Demo for Stakeholders
```bash
# Terminal 1
./start_dashboard.sh

# Share screen showing browser at localhost:5000

# Terminal 2
./run_demo.sh
```

### Scenario: Production Deployment
```bash
sudo cp deployment/systemd/sentinel-ai.service /etc/systemd/system/
sudo systemctl start sentinel-ai
sudo journalctl -u sentinel-ai -f
```

### Scenario: Debugging Issue
```bash
export LOG_LEVEL=DEBUG
python3 main.py 2>&1 | tee debug.log
```

---

## 📞 Emergency Commands

### System Overloaded (Kill Everything)
```bash
pkill -9 -f python3
pkill -9 -f sentinel
```

### Dashboard Won't Start
```bash
# Check port
lsof -i :5000
# Kill existing
kill $(lsof -t -i:5000)
# Restart
./start_dashboard.sh
```

### Database Locked
```bash
# Close all connections
pkill -f sentinel
# Remove lock
rm data/sentinel.db-journal 2>/dev/null
# Restart
python3 main.py
```

---

## 🎯 Most Used Commands (Quick Copy)

```bash
# Start dashboard
./start_dashboard.sh

# Run demo
./run_demo.sh

# Trigger CPU test
python3 trigger_anomaly.py cpu

# View incidents
sqlite3 data/sentinel.db "SELECT * FROM incidents LIMIT 5;"

# Watch logs
tail -f logs/sentinel.log | jq '.'

# Check status (API)
curl localhost:5000/api/status | jq '.'
```

---

**Save this file for quick reference!** 📌
