# ⚡ Sentinel AI - 2-Minute Quick Start

## 🎯 See It Working in 2 Minutes!

### **Terminal 1: Start Dashboard**
```bash
cd sentinel_ai
./start_dashboard.sh
```

### **Terminal 2: Open Browser**
```
http://localhost:5000
```

### **Terminal 3: Run Demo**
```bash
cd sentinel_ai
./run_demo.sh
```

## 📺 What You'll See

```
[00s] ▸ Dashboard shows normal CPU (30-40%)

[05s] ▸ CPU bar turns RED (95%+)

[15s] ▸ 🚨 FULL-SCREEN ALERT appears
       "ANOMALY DETECTED!"

[20s] ▸ Alert shows diagnosis:
       "High CPU caused by python3"
       "Actions: kill_process"

[27s] ▸ Logs show:
       "🔧 RECOVERY: Executing..."
       "✅ kill_process: success"

[30s] ▸ CPU bar turns GREEN (back to normal)
       ✅ System healed itself!
```

## ✅ That's It!

You just saw **autonomous self-healing** in action:
- ✅ Detected problem automatically
- ✅ Diagnosed root cause
- ✅ Fixed itself without human help
- ✅ All shown in real-time

---

## 📚 Want More?

**Complete Demo Guide:** `COMPLETE_DEMO.md`
**Dashboard Guide:** `DASHBOARD_QUICKSTART.md`
**Full Documentation:** `docs/README.md`

---

## 🔄 Run Again

```bash
# CPU stress
python3 trigger_anomaly.py cpu

# Memory stress
python3 trigger_anomaly.py memory

# Both at once
python3 trigger_anomaly.py combo
```

---

**Built with ❤️ for autonomous systems**
