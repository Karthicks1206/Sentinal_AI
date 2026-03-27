# Sentinel AI — Commands Reference

## Hub: Start / Stop

```bash
# Full start (kills any existing instance first)
cd /Users/karthi/Desktop/Sentinal_AI/sentinel_ai
kill $(lsof -ti :5001) 2>/dev/null; pkill -f "python.*main.py" 2>/dev/null
source venv/bin/activate
brew services start ollama
python main.py

# One-liner (from project root)
./run.sh

# Background mode
nohup python main.py > logs/nohup.out 2>&1 &

# Stop hub
pkill -f "python.*main.py"
kill $(lsof -ti :5001)
```

---

## Remote Client

```bash
# Auto-connect script (recommended — saves hub IP, installs deps, auto-reconnects)
bash connect.sh

# Manual connection
pip install psutil requests
python sentinel_client.py --hub http://<HUB_IP>:5001 --device <name>

# Custom interval (default 5s)
python sentinel_client.py --hub http://<HUB_IP>:5001 --device <name> --interval 3

# Custom command port (default 5002)
python sentinel_client.py --hub http://<HUB_IP>:5001 --device <name> --cmd-port 5003

# Connectivity diagnostics
python sentinel_client.py --hub http://<HUB_IP>:5001 --test

# Find hub IP (on hub machine, macOS)
ipconfig getifaddr en0
```

---

## API Endpoints

```bash
BASE=http://localhost:5001

# System status + agent states
curl $BASE/api/status | python3 -m json.tool

# Current local metrics
curl $BASE/api/metrics | python3 -m json.tool

# Adaptive thresholds (learned IQR bounds)
curl $BASE/api/thresholds | python3 -m json.tool

# Recent incidents
curl $BASE/api/incidents | python3 -m json.tool

# Recent logs
curl $BASE/api/logs | python3 -m json.tool

# Connected remote devices
curl $BASE/api/devices | python3 -m json.tool

# Specific device info
curl $BASE/api/devices/<device_id> | python3 -m json.tool

# Specific device metrics
curl $BASE/api/devices/<device_id>/metrics | python3 -m json.tool

# Device anomaly feed (filtered)
curl "$BASE/api/anomalies?device_id=<device_id>" | python3 -m json.tool
```

---

## Simulation (API)

```bash
BASE=http://localhost:5001

# Trigger CPU spike (95%, 60s)
curl -X POST $BASE/api/simulate/start/cpu_overload

# Trigger memory pressure (~250 MB, 60s)
curl -X POST $BASE/api/simulate/start/memory_spike

# Trigger disk fill (writes 200 MB temp file)
curl -X POST $BASE/api/simulate/start/disk_fill

# Trigger power sag (-0.75V for 60s)
curl -X POST $BASE/api/simulate/start/power_sag

# Stop all simulations
curl -X POST $BASE/api/simulate/stop

# Check simulation status
curl $BASE/api/simulate/status | python3 -m json.tool
```

---

## Remote Commands (API)

Send a command directly to a connected remote device:

```bash
# Stress CPU on remote device
curl -X POST http://localhost:5001/api/devices/<device_id>/queue_command \
  -H 'Content-Type: application/json' \
  -d '{"action": "stress_cpu"}'

# Stress memory
curl -X POST http://localhost:5001/api/devices/<device_id>/queue_command \
  -H 'Content-Type: application/json' \
  -d '{"action": "stress_memory"}'

# Stress disk
curl -X POST http://localhost:5001/api/devices/<device_id>/queue_command \
  -H 'Content-Type: application/json' \
  -d '{"action": "stress_disk"}'

# Stop all stress on remote device
curl -X POST http://localhost:5001/api/devices/<device_id>/queue_command \
  -H 'Content-Type: application/json' \
  -d '{"action": "stop_stress"}'
```

---

## Unit Tests

```bash
cd sentinel_ai
source venv/bin/activate

# Run all 52 tests
python -m pytest tests/test_unit.py -v

# Run specific test class
python -m pytest tests/test_unit.py::TestRemoteDeviceManager -v
python -m pytest tests/test_unit.py::TestEscalationTracker -v
python -m pytest tests/test_unit.py::TestRemoteStressCommands -v

# Run with output (no capture)
python -m pytest tests/test_unit.py -v -s
```

---

## Database

```bash
DB=sentinel_ai/data/sentinel.db

# View recent incidents
sqlite3 $DB "SELECT id, device_id, metric_name, severity, timestamp FROM incidents ORDER BY timestamp DESC LIMIT 10;"

# Anomaly counts by metric
sqlite3 $DB "SELECT metric_name, COUNT(*) as count FROM anomalies GROUP BY metric_name ORDER BY count DESC;"

# Recovery action outcomes
sqlite3 $DB "SELECT action_type, status, COUNT(*) as count FROM recovery_actions GROUP BY action_type, status;"

# Summary stats
sqlite3 $DB "SELECT (SELECT COUNT(*) FROM incidents) incidents, (SELECT COUNT(*) FROM anomalies) anomalies, (SELECT COUNT(*) FROM recovery_actions) recoveries;"

# Export incidents to CSV
sqlite3 $DB -header -csv "SELECT * FROM incidents;" > incidents.csv

# Clean old records (keep 30 days)
sqlite3 $DB "DELETE FROM anomalies WHERE timestamp < datetime('now', '-30 days'); VACUUM;"

# Backup
cp $DB data/sentinel_backup_$(date +%Y%m%d).db
```

---

## Logs

```bash
# View recent logs
tail -50 sentinel_ai/logs/sentinel.log

# Follow live
tail -f sentinel_ai/logs/sentinel.log

# Parse JSON logs (requires jq)
tail -50 sentinel_ai/logs/sentinel.log | jq '.'

# Errors only
tail -200 sentinel_ai/logs/sentinel.log | jq 'select(.level=="ERROR")'

# Filter by keyword
grep "anomaly" sentinel_ai/logs/sentinel.log | tail -20
```

---

## Configuration

```bash
# View config
cat sentinel_ai/config/config.yaml

# Validate config loads correctly
cd sentinel_ai && source venv/bin/activate
python3 -c "from core.config import get_config; c=get_config(); print('OK —', c.get('device_id'))"

# Read a specific value
python3 -c "from core.config import get_config; print(get_config().get('monitoring.collection_interval'))"
```

---

## Port Management

```bash
# Check what is on port 5001 (hub dashboard)
lsof -i :5001

# Check what is on port 5002 (remote command server)
lsof -i :5002

# Kill process on port 5001
kill $(lsof -ti :5001)

# Check if hub is running
ps aux | grep "python.*main.py"
```

---

## systemd (Linux Production)

```bash
sudo cp deployment/systemd/sentinel-ai.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sentinel-ai
sudo systemctl start sentinel-ai
sudo systemctl status sentinel-ai

# View service logs
sudo journalctl -u sentinel-ai -n 50
sudo journalctl -u sentinel-ai -f

# Restart
sudo systemctl restart sentinel-ai
```

---

## Emergency

```bash
# Kill everything sentinel-related
pkill -9 -f "python.*main.py"
pkill -9 -f "sentinel_client"
kill $(lsof -ti :5001) 2>/dev/null
kill $(lsof -ti :5002) 2>/dev/null

# Remove stale DB journal (if DB locked)
rm sentinel_ai/data/sentinel.db-journal 2>/dev/null

# Clear all data and logs (destructive)
rm -rf sentinel_ai/data/* sentinel_ai/logs/*

# Fresh restart
./run.sh
```

---

## Most Used — Copy & Paste

```bash
# Start hub
cd /Users/karthi/Desktop/Sentinal_AI/sentinel_ai && kill $(lsof -ti :5001) 2>/dev/null; pkill -f "python.*main.py" 2>/dev/null; source venv/bin/activate && brew services start ollama && python main.py

# Run tests
cd /Users/karthi/Desktop/Sentinal_AI/sentinel_ai && source venv/bin/activate && python -m pytest tests/test_unit.py -v

# Check hub status
curl http://localhost:5001/api/status | python3 -m json.tool

# Trigger CPU spike
curl -X POST http://localhost:5001/api/simulate/start/cpu_overload

# Stop simulation
curl -X POST http://localhost:5001/api/simulate/stop

# View incidents
sqlite3 sentinel_ai/data/sentinel.db "SELECT device_id, metric_name, severity, timestamp FROM incidents ORDER BY timestamp DESC LIMIT 5;"
```
