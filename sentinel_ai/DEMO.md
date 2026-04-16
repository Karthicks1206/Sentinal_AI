# Sentinel AI — Live Demo Script

## Hardware on table
- Raspberry Pi (running hub + AI agents)
- Heltec LoRa32 V3 (ESP32-S3) with AHT20 sensor attached
- USB cable Pi ↔ LoRa32

---

## Step 1 — Start everything (do this 2 min before presenting)
```bash
cd /Users/karthi/Desktop/Sentinal_AI/sentinel_ai
./run.sh
```
Dashboard opens automatically at **http://192.168.1.100:5001**

---

## Step 2 — Show the live dashboard (~1 min)
Point out:
- **Two devices** in the Distributed panel: `raspberry-pi-001` (Pi) + `lora32-node-01` (LoRa32)
- **Live metrics**: CPU, Memory, Disk updating every 5s
- **AHT20 sensor card** on lora32: real temperature + humidity from the physical sensor
- **Agent Status** panel: 6 agents running (Monitoring, Anomaly, Diagnosis, Recovery, Learning, Security)

---

## Step 3 — Trigger CPU spike on LoRa32 (~30 sec)
In Simulation Lab → select **lora32-node-01** from dropdown → click **CPU Spike**

Watch:
1. lora32 CPU jumps to ~94% (visible in Distributed panel)
2. **Toast notification** appears top-right: "ANOMALY — cpu.cpu_percent CRITICAL"
3. Diagnosis fires: "High CPU usage"
4. Recovery fires: kill_process + stop_stress commands sent over serial to LoRa32
5. CPU drops back to ~0%

**Say**: *"The hub detected the spike on the IoT node, diagnosed it, and autonomously sent a recovery command over serial — no human involved."*

---

## Step 4 — Trigger CPU spike on Pi itself (~30 sec)
Switch dropdown back to **raspberry-pi-001** → click **CPU Spike**

Watch:
1. Pi CPU spikes (all cores)
2. Anomaly fires, diagnosis: "High CPU — process python consuming 100%"
3. Recovery: kill_process, compact_memory, escalation if not recovered

**Say**: *"Same pipeline — works on the Pi itself, not just the IoT node."*

---

## Step 5 — Show the incident timeline (~30 sec)
Scroll to **Statistics** panel → open the incident dropdown

Point out:
- Timestamped anomaly → diagnosis → recovery chain
- Learning agent recorded each incident

---

## Step 6 — Point to the 3 innovation pillars
| Pillar | What to show |
|---|---|
| **LoRa radio hardware** | LoRa32 on table, AHT20 sensor, live T/H readings |
| **Edge AI on Pi** | 6 agents, rule-based + Ollama diagnosis, no cloud needed |
| **Closed-loop autonomy** | Spike → detect → diagnose → recover → verify, all automatic |

---

## Backup / if something goes wrong
```bash
# Restart everything cleanly
./run.sh --stop && sleep 3 && ./run.sh

# Check hub is alive
curl http://192.168.1.100:5001/api/devices

# Check bridge is running
ssh karthick12@192.168.1.100 'tail -5 /tmp/bridge.log'
```

---

## WiFi credentials (fill in before going wireless)
To untether LoRa32 from USB cable:
1. Edit `hardware/lora32/config.py` — set `WIFI_SSID` and `WIFI_PASSWORD`
2. Run `./run.sh` — it auto-flashes and LoRa32 connects over WiFi
3. Unplug the USB cable — data keeps flowing wirelessly
