# Sentinel AI — Testing Guide

## Prerequisites

- Hub running: `python main.py` (port 5001)
- Pi connected: `systemctl --user status sentinel-client` → active
- ESP32 flashed with `esp32_main_v3.py` and connected via `/dev/ttyUSB0`

---

## 1. Verify All Devices Connected

```bash
curl http://localhost:5001/api/devices | python3 -m json.tool
```

Expected output: both `raspberry-pi-001` (hub) and `raspberry-pi-ECE510` (Pi) with `"status": "connected"`.

---

## 2. Verify IoT Sensor Data

```bash
curl http://localhost:5001/api/devices/raspberry-pi-ECE510/metrics | python3 -c "
import sys,json; d=json.load(sys.stdin); s=d.get('sensor',{})
print('Soil Moisture :', s.get('soil_moisture_pct'), '%')
print('Pump Voltage  :', s.get('pump_voltage_v'), 'V')
print('Pump Status   :', s.get('pump_status'))
print('Soil Status   :', s.get('soil_status'))
"
```

---

## 3. Test Pump Manual Control

```bash
# Turn pump ON (overrides autonomous mode for 5 minutes)
curl -X POST http://localhost:5001/api/devices/raspberry-pi-ECE510/queue_command \
  -H "Content-Type: application/json" -d '{"action":"pump_on"}'
sleep 8
curl http://localhost:5001/api/devices/raspberry-pi-ECE510/metrics | \
  python3 -c "import sys,json;d=json.load(sys.stdin);print('Pump:', d['sensor']['pump_status'])"
# Expected: ON

# Turn pump OFF
curl -X POST http://localhost:5001/api/devices/raspberry-pi-ECE510/queue_command \
  -H "Content-Type: application/json" -d '{"action":"pump_off"}'
sleep 8
curl http://localhost:5001/api/devices/raspberry-pi-ECE510/metrics | \
  python3 -c "import sys,json;d=json.load(sys.stdin);print('Pump:', d['sensor']['pump_status'])"
# Expected: OFF
```

---

## 4. Test Self-Healing Pipeline — CPU

```bash
# Start CPU stress on hub (90 seconds)
curl -X POST http://localhost:5001/api/simulate/start/cpu_spike \
  -H "Content-Type: application/json" -d '{"duration":90}'

# Start CPU stress on Pi
curl -X POST http://localhost:5001/api/devices/raspberry-pi-ECE510/queue_command \
  -H "Content-Type: application/json" -d '{"action":"stress_cpu"}'
```

Wait 60 seconds, then check pipeline results:

```bash
curl http://localhost:5001/api/logs?limit=100 | python3 -c "
import sys,json; d=json.load(sys.stdin)
anoms=[x for x in d if 'ANOMALY' in x.get('message','')]
diags=[x for x in d if 'DIAGNOSIS' in x.get('message','')]
recs=[x for x in d if 'RECOVERY' in x.get('message','')]
print('Anomalies:', len(anoms))
print('Diagnoses:', len(diags))
print('Recoveries:', len(recs))
for x in (anoms+diags+recs)[-8:]:
    print(' ', x['timestamp'][-8:], x['message'][:100])
"
```

**Pass criteria:** Anomalies ≥ 2, Diagnoses ≥ 1, Recoveries ≥ 1 with no `[SKIPPED]` entries.

---

## 5. Test Self-Healing Pipeline — Memory

```bash
curl -X POST http://localhost:5001/api/simulate/start/memory_pressure \
  -H "Content-Type: application/json" -d '{"duration":90}'

curl -X POST http://localhost:5001/api/devices/raspberry-pi-ECE510/queue_command \
  -H "Content-Type: application/json" -d '{"action":"stress_memory"}'
```

Recovery actions expected: `algorithmic_memory_fix` (purge + renice on macOS; drop_caches on Linux), `compact_memory`, `kill_top_memory_process`.

---

## 6. Test Power Monitoring

```bash
curl -X POST http://localhost:5001/api/simulate/start/power_sag
```

Triggers a -0.75V simulated voltage sag for 60 seconds. Within 1–2 anomaly cycles, expect:
- `power.power_voltage_v` anomaly (severity: critical)
- Diagnosis mentioning voltage/power fault
- Recovery: `reconnect_sensor`, `reset_network_interface`

---

## 7. Brute Force — All Devices Simultaneously

```bash
# Launch everything at once
curl -X POST http://localhost:5001/api/simulate/start/cpu_spike \
  -H "Content-Type: application/json" -d '{"duration":120}' &
curl -X POST http://localhost:5001/api/simulate/start/memory_pressure \
  -H "Content-Type: application/json" -d '{"duration":120}' &
curl -X POST http://localhost:5001/api/devices/raspberry-pi-ECE510/queue_command \
  -H "Content-Type: application/json" -d '{"action":"stress_cpu"}' &
curl -X POST http://localhost:5001/api/devices/raspberry-pi-ECE510/queue_command \
  -H "Content-Type: application/json" -d '{"action":"stress_memory"}' &
wait
```

**Pass criteria (after 90s):**
- Mac CPU recovered from stress peak back toward baseline
- Pipeline: Anomalies ≥ 10, Diagnoses ≥ 4, Recoveries ≥ 4
- Skip rate: 0% (no `[SKIPPED]` entries)
- IoT: soil moisture reported, pump state correct

---

## 8. Algorithmic Fix Verification

```bash
curl http://localhost:5001/api/logs?limit=200 | python3 -c "
import sys,json; d=json.load(sys.stdin)
alg=[x for x in d if 'algorithmic' in x.get('message','').lower()]
skips=[x for x in alg if '[SKIPPED]' in x.get('message','')]
ok=[x for x in alg if 'REMOTE ACTION' in x.get('message','') or '[OK]' in x.get('message','')]
print('Algorithmic actions executed:', len(ok))
print('Algorithmic actions skipped :', len(skips))
for x in ok: print(' ✅', x['message'][:100])
for x in skips: print(' ❌', x['message'][:100])
"
```

**Pass criteria:** 0 skipped algorithmic actions, at least 2 executed.

---

## 9. Stop All Tests

```bash
curl -X POST http://localhost:5001/api/simulate/stop
```
