# Sentinel AI — Quick Start

## Start the Hub (2 minutes)

### Step 1 — Start the system

```bash
cd /Users/karthi/Desktop/Sentinal_AI/sentinel_ai
kill $(lsof -ti :5001) 2>/dev/null; pkill -f "python.*main.py" 2>/dev/null
source venv/bin/activate
brew services start ollama
python main.py
```

Or from the project root:

```bash
./run.sh
```

### Step 2 — Open the dashboard

```
http://localhost:5001
```

Wait ~3 minutes for the anomaly baseline to settle (warmup gate).

---

## Trigger a Test Anomaly

Use the **Simulation Lab** tab in the dashboard:

- Click **CPU Spike** to drive CPU to 95% for 60 seconds
- Click **Memory Pressure** to hold 250 MB for 60 seconds
- Click **Disk Fill** to write 100 MB temporarily
- Click **Power Sag** to simulate a -0.75V voltage drop
- Click **Stop All** to cancel any running simulation

After ~10-15 seconds you will see:
1. Metric card turns red (anomaly threshold breached)
2. Toast notification appears top-right with severity color
3. Diagnosis fires (rule-based + Groq AI)
4. Recovery action executes automatically
5. Incident appears in the Incidents tab

---

## Connect a Remote Device

### On the remote machine (macOS / Linux)

```bash
# Copy sentinel_client.py and connect.sh to the remote machine, then:
bash connect.sh
```

The script will:
1. Ask for (or remember) the hub IP
2. Install `psutil` and `requests` automatically
3. Test connectivity before connecting
4. Auto-reconnect if disconnected

### Manual connection

```bash
pip install psutil requests
python sentinel_client.py --hub http://<HUB_IP>:5001 --device <device-name>
```

### Find your hub IP (on the hub machine)

```bash
ipconfig getifaddr en0
```

### Test connectivity before connecting

```bash
python sentinel_client.py --hub http://<HUB_IP>:5001 --test
```

---

## View Remote Devices

1. Open the dashboard at http://localhost:5001
2. Click the **Distributed Devices** tab
3. Click any device name in the left sidebar
4. The full per-device panel opens: metrics, live chart, anomaly/diagnosis/recovery feeds, incident timeline
5. Use **Controlled Instability** buttons to stress-test the remote device directly

---

## API Quick Reference

```bash
# Hub status
curl http://localhost:5001/api/status | python3 -m json.tool

# Current metrics (local device)
curl http://localhost:5001/api/metrics | python3 -m json.tool

# Connected remote devices
curl http://localhost:5001/api/devices | python3 -m json.tool

# Recent incidents
curl http://localhost:5001/api/incidents | python3 -m json.tool

# Adaptive thresholds (learned from live data)
curl http://localhost:5001/api/thresholds | python3 -m json.tool
```

---

## Troubleshooting

**Port already in use:**
```bash
kill $(lsof -ti :5001)
```

**Remote client cannot connect:**
- Check hub IP: `ipconfig getifaddr en0`
- Use `--test` flag to diagnose
- Disable AP/Client Isolation on your router if on WiFi

**No anomalies firing:**
- Wait 3 minutes for baseline warmup
- CPU and memory need 2 consecutive high readings to trigger
- Run a simulation from the Simulation Lab tab

**Ollama not found:**
```bash
brew install ollama
brew services start ollama
ollama pull llama3.2:3b
```
