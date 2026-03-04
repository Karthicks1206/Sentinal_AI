# 🚀 Getting Started with Sentinel AI

## Welcome!

You now have a **complete production-ready autonomous self-healing IoT infrastructure** with a beautiful real-time web dashboard!

## 🎯 Choose Your Path

### 🌟 Path 1: Visual Dashboard (Best for First-Time Users)

**Perfect if you want to:**
- See the system working visually
- Watch anomalies detected in real-time
- Test with beautiful full-screen alerts
- Demo to stakeholders

**Start here:** [`DASHBOARD_QUICKSTART.md`](sentinel_ai/DASHBOARD_QUICKSTART.md)

**Quick start:**
```bash
cd sentinel_ai
./start_dashboard.sh
# Open browser: http://localhost:5000
```

---

### 🧪 Path 2: Automated Testing (Best for Validation)

**Perfect if you want to:**
- Validate the multi-agent system
- Run comprehensive tests
- Verify anomaly detection works
- Check database persistence

**Start here:** [`TESTING_README.md`](sentinel_ai/TESTING_README.md)

**Quick start:**
```bash
cd sentinel_ai
python3 test_workflow.py
```

---

### 🏭 Path 3: Production Deployment (Best for Real Use)

**Perfect if you want to:**
- Deploy to Raspberry Pi
- Run in production
- Enable AWS cloud integration
- Scale to 100+ devices

**Start here:** [`docs/RASPBERRY_PI_DEPLOYMENT.md`](sentinel_ai/docs/RASPBERRY_PI_DEPLOYMENT.md)

**Quick start:**
```bash
# See deployment guide
cat sentinel_ai/docs/RASPBERRY_PI_DEPLOYMENT.md
```

---

### 📚 Path 4: Deep Dive (Best for Developers)

**Perfect if you want to:**
- Understand the architecture
- Customize agents
- Add new features
- Integrate with your systems

**Start here:** [`docs/ARCHITECTURE.md`](sentinel_ai/docs/ARCHITECTURE.md)

**Also read:**
- [`docs/README.md`](sentinel_ai/docs/README.md) - Complete documentation
- [`docs/TESTING_GUIDE.md`](sentinel_ai/docs/TESTING_GUIDE.md) - Detailed testing

---

## 🎬 Recommended First Experience

### Step 1: Install (1 minute)
```bash
cd sentinel_ai
pip install -r requirements.txt
```

### Step 2: Start Dashboard (30 seconds)
```bash
./start_dashboard.sh
```

Open browser: `http://localhost:5000`

### Step 3: Watch Normal Operation (1 minute)
Just watch the dashboard for 60 seconds. You'll see:
- ✅ Metrics updating every 2 seconds
- ✅ All 5 agents running (green indicators)
- ✅ Logs scrolling with "Metrics collected..."

### Step 4: Trigger Anomaly (2 minutes)
**New terminal:**
```bash
cd sentinel_ai
python3 trigger_anomaly.py cpu --duration 60
```

**Watch the dashboard:**
1. ⏱️ After ~10s: CPU bar turns red (95%+)
2. 🚨 After ~15s: **Full-screen alert appears!**
   - Shows anomaly details
   - Displays diagnosis
   - Lists recommended actions
3. 📋 Logs auto-scroll to show anomaly

Click **"Acknowledge"** to dismiss alert.

### Step 5: Check Results (1 minute)
```bash
# View database
sqlite3 data/sentinel.db "SELECT * FROM incidents LIMIT 5;"

# View logs
tail -20 logs/sentinel.log | jq '.'
```

**Congratulations! You've seen the complete workflow:**
```
Monitor → Detect Anomaly → Diagnose → Recommend Recovery
```

---

## 📁 Project Structure Quick Reference

```
sentinel_ai/
├── main.py                      # Production entry point
├── start_dashboard.sh           # Dashboard launcher
├── test_workflow.py             # Automated tests
├── trigger_anomaly.py           # Test anomaly triggers
│
├── config/
│   ├── config.yaml              # Main configuration
│   └── diagnosis_rules.yaml     # Diagnosis rules
│
├── agents/                      # 5 specialized agents
│   ├── monitoring/              # MonitoringAgent
│   ├── anomaly/                 # AnomalyDetectionAgent
│   ├── diagnosis/               # DiagnosisAgent
│   ├── recovery/                # RecoveryAgent
│   └── learning/                # LearningAgent
│
├── dashboard/                   # Web dashboard
│   ├── app.py                   # Flask server
│   └── templates/               # HTML templates
│
├── docs/                        # Documentation
│   ├── README.md                # Complete guide
│   ├── ARCHITECTURE.md          # System design
│   ├── TESTING_GUIDE.md         # Testing procedures
│   └── RASPBERRY_PI_DEPLOYMENT.md
│
└── deployment/                  # Deployment configs
    ├── systemd/                 # systemd service
    └── docker/                  # Docker configs
```

---

## 🎓 What You've Built

### Multi-Agent System (5 Agents)
1. **MonitoringAgent** - Collects CPU, memory, disk, network metrics
2. **AnomalyDetectionAgent** - Detects anomalies (Z-score, ML, thresholds)
3. **DiagnosisAgent** - Diagnoses root causes (rules + LLM)
4. **RecoveryAgent** - Executes autonomous recovery actions
5. **LearningAgent** - Learns from incidents, adapts thresholds

### Core Infrastructure
- ✅ **Event Bus** - Loose coupling between agents
- ✅ **Configuration Manager** - YAML with env vars
- ✅ **Logging System** - Structured JSON logs
- ✅ **Database** - SQLite with cloud sync
- ✅ **AWS Integration** - IoT Core, Bedrock, DynamoDB, S3

### Testing & Monitoring
- ✅ **Web Dashboard** - Real-time visual monitoring
- ✅ **Automated Tests** - 6 comprehensive test scenarios
- ✅ **Simulation** - Trigger CPU/memory/network failures
- ✅ **Real-time Alerts** - Full-screen anomaly notifications

### Production Ready
- ✅ **Docker** - Containerized deployment
- ✅ **systemd** - Service management
- ✅ **Raspberry Pi** - Edge deployment guides
- ✅ **Scalable** - Designed for 100+ devices

---

## 🔥 Quick Commands Reference

### Dashboard
```bash
# Start dashboard
./start_dashboard.sh

# Custom port
python3 dashboard/app.py --port 8080
```

### Testing
```bash
# Full automated test
python3 test_workflow.py

# Real-time monitor (CLI)
python3 monitor_realtime.py
```

### Trigger Anomalies
```bash
# CPU overload (60s)
python3 trigger_anomaly.py cpu

# Memory spike (40% for 60s)
python3 trigger_anomaly.py memory --percent 40

# Both CPU + Memory
python3 trigger_anomaly.py combo
```

### Database Queries
```bash
# View incidents
sqlite3 data/sentinel.db "SELECT * FROM incidents;"

# View anomalies
sqlite3 data/sentinel.db "SELECT * FROM anomalies;"

# Statistics
sqlite3 data/sentinel.db "
SELECT anomaly_type, COUNT(*) as count
FROM anomalies
GROUP BY anomaly_type;
"
```

### Production
```bash
# Run main system
python3 main.py

# Run with simulation
python3 main.py --simulate

# systemd service
sudo systemctl start sentinel-ai
sudo systemctl status sentinel-ai
```

---

## 📊 Expected Performance

**On Raspberry Pi 3B+ (1GB RAM):**
- CPU Usage: 5-10%
- Memory: 100-200MB
- Detection Latency: <500ms
- Recovery Time: 1-30s

**On Desktop/Server:**
- CPU Usage: 1-5%
- Memory: 50-100MB
- Detection Latency: <100ms
- Recovery Time: <5s

---

## 🆘 Need Help?

### Quick Fixes

**Dashboard not loading?**
```bash
pip install -r requirements.txt
./start_dashboard.sh
```

**No anomalies detected?**
Lower thresholds in `config/config.yaml`:
```yaml
monitoring:
  metrics:
    cpu:
      threshold_percent: 50
```

**Agents not starting?**
```bash
tail -50 logs/sentinel.log
```

### Documentation

- **Dashboard Help:** [`dashboard/README.md`](sentinel_ai/dashboard/README.md)
- **Testing Help:** [`docs/TESTING_GUIDE.md`](sentinel_ai/docs/TESTING_GUIDE.md)
- **General Help:** [`docs/README.md`](sentinel_ai/docs/README.md)

---

## 🎯 Next Steps

After getting familiar with the dashboard:

1. ✅ **Test thoroughly** - Run `test_workflow.py`
2. ✅ **Customize rules** - Edit `config/diagnosis_rules.yaml`
3. ✅ **Add sensors** - Integrate your IoT devices
4. ✅ **Enable AWS** - Connect to cloud (optional)
5. ✅ **Deploy to Pi** - Production deployment
6. ✅ **Scale up** - Deploy to multiple devices

---

## 🌟 You're Ready!

Your autonomous self-healing IoT infrastructure is **production-ready** and **fully documented**.

**Start exploring:**
```bash
cd sentinel_ai
./start_dashboard.sh
# Open: http://localhost:5000
```

**Then trigger a test:**
```bash
python3 trigger_anomaly.py cpu
```

Watch your system **detect, diagnose, and respond automatically!** 🚀

---

**Built with ❤️ for autonomous systems**

Questions? Check the documentation in `docs/` or open an issue on GitHub.
