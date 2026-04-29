# Sentinel AI — Presenter Script
### Target: 17–18 minutes  |  19 slides

---

## SLIDE 1 — Title  `[~20 seconds]`

> "Good morning / afternoon everyone.
> My project is called **Sentinel AI** — a self-healing distributed IoT infrastructure.
> The core idea is simple: instead of waiting for a device to fail and then fixing it manually,
> this system detects problems, figures out what caused them, and fixes them automatically —
> in under thirty seconds, with no human in the loop.
> Let me walk you through how it works."

---

## SLIDE 2 — Purpose  `[~90 seconds]`

> "Let me start with the **why**.
>
> IoT devices fail silently. A sensor reports the wrong value, a process crashes,
> a power rail sags — and nobody notices until the damage is already done.
>
> The primary use case I designed this around is **precision agriculture**.
> Crops are highly sensitive to temperature and humidity.
> A cold snap overnight can kill an entire greenhouse harvest.
> A sudden humidity spike encourages mould that spreads in hours.
> Traditionally, a farmer would check readings in the morning — by which point it's too late.
>
> Our AHT20 sensor monitors both temperature and humidity continuously.
> When a reading drifts outside the normal range, the system detects it within ten seconds,
> the AI diagnoses the root cause, an alert fires to the operator,
> and an automated corrective action is sent to the device — all without anyone watching.
>
> And while agriculture is our primary framing, look at the right side of the slide —
> the same pipeline applies anywhere physical conditions need to be monitored:
> industrial factory floors, pharmaceutical cold chains, data centre cooling,
> smart buildings, environmental monitoring stations.
> The applications are limitless.
> The sensor changes — the intelligence behind it stays exactly the same."

---

## SLIDE 3 — Hardware Used  `[~90 seconds]`

> "Now let me show you the **actual hardware** we built this on.
>
> On the left — the **AHT20** temperature and humidity sensor.
> It communicates over I²C. We connect it to the LoRa32 on GPIO 1 and 40.
> It gives us ±0.3 degrees accuracy and ±2% relative humidity — more than adequate
> for agricultural and industrial use.
>
> In the middle — the **Heltec WiFi LoRa32 V3**.
> This is our edge node. It runs an ESP32-S3 at 240 megahertz,
> has a built-in SX1262 LoRa radio for long-range communication at 868 megahertz,
> and a tiny SSD1306 OLED display on board.
> This is what I refer to as the long-range IoT node —
> the SX1262 chip on this board is capable of transmitting several kilometres.
> It runs our MicroPython firmware.
>
> On the right — the **full setup**.
> You can see the LoRa32 in the centre with the OLED screen active —
> it's showing 'Sentinel AI' and live CPU, memory, temperature and humidity readings.
> Up in the top right is the **Raspberry Pi 4B**.
> The Pi runs our bridge script that reads the LoRa32 over USB serial,
> and forwards every metric packet to the Mac hub over Wi-Fi.
> Everything is connected. Everything is live."

---

## SLIDE 4 — Project Overview  `[~60 seconds]`

> "So what is Sentinel AI at a system level?
>
> It is a **multi-agent pipeline**. Six independent agents run on the hub:
> a monitoring agent collects metrics every five seconds from every connected device;
> an anomaly detection agent watches for deviations using five different statistical methods;
> a diagnosis agent — powered by AI — identifies the root cause;
> a recovery agent sends the appropriate fix back to the device;
> a learning agent updates the baselines so the system gets smarter over time;
> and a security agent watches for cyber threats.
>
> The stat boxes at the bottom tell the story:
> five detection methods, six AI agents, under thirty seconds from detection to fix,
> and we had more than two devices monitored simultaneously in our live demo.
>
> The whole thing runs on one command — python main.py —
> and the dashboard is accessible in any browser on the local network."

---

## SLIDE 5 — Hardware & System Setup  `[~55 seconds]`

> "Here is the physical architecture.
>
> On the left you can see the system diagram showing all three nodes connected together.
>
> The Mac runs the full AI pipeline — all six agents, the Flask web dashboard on port 5001,
> and the SQLite incident database.
>
> The Raspberry Pi runs two scripts simultaneously:
> the bridge script that reads the LoRa32 over USB serial and forwards metrics,
> and the client script that also pushes the Pi's own CPU and memory metrics.
> So the Pi is both a bridge and a device being monitored.
>
> The LoRa32 sends its metrics — including AHT20 sensor readings —
> via USB serial to the Pi, which relays them to the hub.
> When the hub wants to send a command — like 'start CPU stress test' or 'stop simulation' —
> it queues the command, the bridge polls every three seconds and writes it to the LoRa32 over serial.
> The LoRa32 firmware executes it immediately."

---

## SLIDE 6 — Hardware Constraints  `[~55 seconds]`

> "Building on real embedded hardware means working within real physical limits.
>
> **Power**: the LoRa32 is powered via USB-C at five volts, five hundred milliamps.
> Under CPU stress it draws around three hundred and fifty milliamps.
> The LoRa radio transmitting at full power pulls a hundred and forty milliamp burst.
> We handle this by duty-cycling the radio and using the INA219 sensor to monitor voltage sag.
>
> **Processing**: the ESP32-S3 has 512 kilobytes of RAM.
> There is no operating system scheduler — it is a cooperative loop.
> This means all machine learning inference must happen on the hub, not the edge node.
>
> **Pin conflicts**: every GPIO on the LoRa32 is shared between functions.
> The LoRa SX1262 claims five pins, the AHT20 takes two, the OLED takes three.
> We verified all buses are non-conflicting and we print an I²C scan on every boot
> to catch wiring errors immediately.
>
> **Radio**: the SX1262 is capable but EU regulation limits LoRa duty cycle to one percent.
> For this project we use USB serial as the transport — no limit —
> and keep the radio for the mesh networking future work."

---

## SLIDE 7 — Software Constraints  `[~55 seconds]`

> "On the software side there are equally important constraints.
>
> **Real-time collection**: every metric cycle must complete under five seconds.
> Blocking calls like psutil run in a background thread so they never delay the event bus.
> The AI diagnosis runs in its own background thread too — it never blocks anything.
>
> **False-positive prevention**: this is critical for a system making automated decisions.
> We suppress anomaly alerts for the first seventy-five seconds while the baseline settles.
> An anomaly must appear in two consecutive readings before it fires.
> After it fires, it cannot fire again for one minute.
> This combination eliminates noise while keeping genuine issues fast.
>
> **LLM rate limits**: Groq's free tier allows thirty requests per minute.
> We fire diagnosis at most once per anomaly and fall back to local Ollama LLaMA if the limit is hit.
> Ollama runs entirely offline — so AI diagnosis is always available regardless of internet access.
>
> **Multi-device coordination**: every device gets its own isolated anomaly baseline,
> cooldown state, and escalation level — one device spiking does not contaminate another's baseline."

---

## SLIDE 8 — Where Does Our Data Come From?  `[~55 seconds]`

> "Every metric we monitor comes from real sensor reads — no synthetic data in production.
>
> On the LoRa32: the AHT20 gives us temperature and humidity every five seconds.
> CPU and memory are read directly from the ESP32-S3's runtime counters in MicroPython.
>
> On the Pi and Mac hub: psutil provides CPU percent, memory percent, disk usage,
> and network ping latency — all without needing root access.
>
> Power is monitored via simulated INA219 reads on the development Mac —
> on real production hardware we replace that function body with actual I²C reads
> from a physical INA219 sensor, which gives us voltage in volts,
> current in amps, and power in watts.
>
> Every five seconds, metrics from all connected devices flow into the hub's event bus.
> The anomaly agent sees them all in real time."

---

## SLIDE 9 — How Thresholds Work  `[~65 seconds]`

> "This is one of the most important technical aspects of the project —
> how we detect anomalies without hardcoded thresholds.
>
> Traditional monitoring tools say: 'if CPU is above 80%, alert'.
> The problem is that 80% is normal for some workloads and catastrophic for others.
> Hardcoded thresholds produce constant false positives.
>
> Our system learns the normal behaviour of each metric from live data using four methods.
> First, z-score: how many standard deviations from the mean is this reading?
> Second, IQR outlier: is this reading outside the Tukey fence of the rolling data window?
> Third, trend elevation: has the metric been above mean plus one-and-a-half sigma for five consecutive readings?
> Fourth, rate-of-change spike: did the metric jump faster than normal?
>
> All four bounds are computed from the actual live data — they adapt to the device.
>
> We also keep a hard floor: CPU above 80%, memory above 85% always fires,
> even before the warmup period ends. So we get the best of both worlds —
> adaptive detection that learns normal behaviour,
> with a safety net that catches extreme values immediately."

---

## SLIDE 10 — How Monitors Work  `[~50 seconds]`

> "For anyone unfamiliar with what these metrics actually represent —
>
> **CPU percent** tells us how hard the processor is working.
> Above 80% sustained means the device cannot keep up with its workload.
>
> **Memory percent** tells us how much RAM is in use.
> Above 85% risks the operating system running out of memory and crashing processes.
>
> **Disk percent** tells us how full storage is.
> Above 90% means new data cannot be written — critical for logging systems.
>
> **Ping latency in milliseconds** measures network round-trip time.
> Above 200 milliseconds indicates a connectivity problem.
>
> **Voltage in volts** tracks power rail health.
> A deviation of more than 10% from the nominal 5 volts means the power supply is under stress —
> which on a Raspberry Pi or ESP32 can cause random reboots and data corruption."

---

## SLIDE 11 — Role of the AI Agents  `[~65 seconds]`

> "Now let's look at what the AI agents actually do.
>
> The slide shows two screenshots from a real run.
> On the left — the dashboard detecting a CPU anomaly on the LoRa32 node.
> On the right — the recovery actions the system sent automatically.
>
> When an anomaly fires, the **diagnosis agent** is triggered.
> It assembles context: the metric values, the recent history, the device ID,
> and sends it to the Groq LLaMA-3.3-70b language model.
> The model returns a structured diagnosis — what the root cause likely is,
> how severe it is, and what recovery action to recommend.
>
> The **recovery agent** receives this and executes.
> For a CPU spike, level one sends a renice command to throttle the highest CPU process.
> Level two kills the top CPU consumer.
> Level three kills all stress workers.
> Level four triggers a full service restart.
>
> Thirty seconds after each action, the system checks if the metric recovered.
> If it did, escalation resets. If it didn't, it escalates to the next level.
>
> The recovery actions shown at the bottom — kill process, clear cache, stop stress, algorithmic fix —
> were all executed and verified automatically on a live remote device."

---

## SLIDE 12 — What AI Models Are We Using?  `[~55 seconds]`

> "We use five distinct AI methods in a layered stack.
>
> At the top, **Groq LLaMA-3.3-70b** — a cloud language model running on Groq's inference hardware.
> This gives us high-quality natural language diagnosis in two to eight seconds.
> It requires internet access.
>
> When Groq is unavailable — rate limited or offline —
> we fall back to **Ollama llama3.2:3b** running entirely on the local Mac.
> It's slower, eight to twenty seconds, but works completely offline.
>
> For anomaly detection, we use **Isolation Forest** from scikit-learn.
> This is a classical machine learning algorithm for multivariate anomaly detection.
> It runs in under a tenth of a second and requires no internet.
>
> We also run a **Keras LSTM Autoencoder** on time-series sequences.
> This trains after sixty sequences — about six and a half minutes of data —
> and then flags patterns that don't match normal temporal behaviour.
>
> Finally, **rule-based heuristics** from a YAML config file are always available —
> zero latency, no model needed, always fires as a fallback.
>
> This five-layer stack means: we always get a diagnosis.
> The quality degrades gracefully, but it never fails silently."

---

## SLIDE 13 — How Are We Testing?  `[~60 seconds]`

> "We validate the system using a built-in simulation lab in the dashboard.
>
> **CPU Spike** pins all cores of the target device to 100% for 120 seconds
> using a Python subprocess that spawns as many busy-loop workers as there are cores.
> We used this to trigger and verify the full detection→diagnosis→recovery pipeline on the LoRa32.
>
> **Memory Pressure** allocates 40% of RAM using a list of byte arrays held in memory.
> This tests whether the recovery agent correctly identifies and kills the memory consumer.
>
> **Disk Fill** writes 200 megabyte temporary files in a cycle.
> On large disks this won't spike the percentage significantly — known limitation.
>
> **Power Sag** artificially reduces the simulated voltage by 0.75 volts for 60 seconds,
> testing whether the z-score anomaly detector catches the deviation and fires correctly.
>
> We also ran a **live remote demo** with the LoRa32, Raspberry Pi, and Mac all connected simultaneously.
> The CPU spike was triggered on the LoRa32 via the web dashboard,
> the command travelled from hub to Pi to LoRa32 over USB serial,
> the LoRa32 hit 93.9% CPU, the anomaly fired within ten seconds,
> and the recovery actions executed automatically."

---

## SLIDE 14 — Key Challenges & Solutions  `[~80 seconds]`

> "Let me walk through the hardest problems we encountered — and how we solved each one.
>
> **AHT20 showing dashes**: the sensor would initialise but return no data.
> Root cause was missing calibration bit check and no retry on I²C scan failure.
> We added a soft reset, a CAL bit check, and three auto-retry attempts on every boot.
>
> **CPU spike going to the wrong device**: when we triggered a CPU spike on the LoRa32,
> the command was sent to the Raspberry Pi instead.
> The problem was that the LoRa32 registered with a cmd_port of 5002 — the Pi's port.
> We fixed this by registering with cmd_port zero, which forces queue-based delivery,
> and added a guard in the hub to only direct-push when cmd_port is greater than zero.
>
> **USB errno minus 71**: after unplugging and replugging the LoRa32,
> the USB xhci controller entered a bad state and refused to communicate.
> We fixed this with a usbreset command on the root USB hub, which forces re-enumeration.
>
> **Recovery actions all in cooldown**: after a test run, all recovery actions were blocked
> for five minutes. We reduced the demo cooldown to sixty seconds and made it configurable.
>
> **Anomaly detection too sensitive**: stress test data was inflating the baseline,
> causing normal values to trigger anomalies after the test ended.
> We fixed this by using only the lower 60% of the data window and freezing the baseline during active anomalies."

---

## SLIDE 15 — Project Timeline  `[~50 seconds]`

> "The project ran for 44 days from the 3rd of March to the 16th of April,
> accumulating 58 git commits across four phases.
>
> **Weeks one and two**: foundation work — project structure, config, event bus,
> monitoring agent, Flask dashboard skeleton, SQLite database.
>
> **Weeks three and four**: intelligence layer — the anomaly detection engine,
> rule-based diagnosis, Ollama LLM integration, the full recovery agent with fifteen-plus actions
> and graduated escalation from level one to level four.
>
> **Weeks five and six**: hardware integration — MicroPython firmware for the LoRa32,
> AHT20 sensor driver, OLED display, the lora_bridge serial bridge,
> Raspberry Pi integration, and the distributed device panel on the dashboard.
>
> **Week seven**: final integration and demo — CPU spike over serial, full pipeline verification
> on all three devices, Groq LLM, security agent, Keras LSTM, and the demo recording."

---

## SLIDE 16 — Team Member Work Contributions  `[~40 seconds]`

> "This was a solo project.
>
> I handled every layer of the stack:
> firmware in MicroPython on the ESP32-S3,
> the hardware bridge in Python,
> all six AI agents,
> the Flask dashboard with live Chart.js visualisations,
> multi-device coordination across three different machines,
> and the complete testing and demo pipeline.
>
> The breadth of the project — from bare-metal I²C drivers
> all the way up to cloud LLM API calls — was intentional.
> The goal was to prove that a single coherent system
> can span the full IoT stack: sense, transmit, detect, diagnose, recover."

---

## SLIDE 17 — Future Work  `[~55 seconds]`

> "There is a clear production roadmap from here.
>
> The most impactful next step is enabling the **LoRa radio** as the actual transport.
> Right now we use USB serial — the SX1262 chip on the LoRa32 is capable of
> transmitting several kilometres. Moving to a mesh topology means removing the Pi bridge
> and having nodes communicate directly with each other and the hub over radio.
>
> **OTA firmware updates** would allow pushing new MicroPython code to deployed nodes
> without physical access — essential for any real field deployment.
>
> **AWS IoT Core integration** is already partially scaffolded in the config —
> pushing telemetry to DynamoDB and using IoT shadow documents
> gives us persistent device state and remote configuration.
>
> **LSTM inference on-device** using TFLite Micro would make the anomaly detection
> truly edge-native — no hub needed for the initial detection.
>
> And a **custom PCB** replacing the current breadboard wiring would make
> the hardware robust enough for outdoor agricultural deployment."

---

## SLIDE 18 — Demo  `[~60 seconds]`

> "Here is the system running live.
>
> What you are seeing is the Sentinel AI dashboard with all three devices connected —
> the Mac hub, the Raspberry Pi, and the Heltec LoRa32 node.
>
> The distributed devices panel on the right shows the LoRa32's live metrics —
> CPU percent, memory, and crucially, the orange temperature and humidity tile
> showing the AHT20 readings directly from the sensor.
>
> When I triggered the CPU spike on the LoRa32 from the Simulation Lab button,
> you saw the following sequence:
> the command travelled from the hub, through the Pi, down the USB serial cable to the LoRa32 —
> the LoRa32 firmware started spawning busy-loop workers,
> CPU climbed to 93.9 percent,
> the anomaly agent detected it within ten seconds,
> the toast notification fired,
> Groq LLaMA diagnosed it as process overload,
> and the recovery agent executed — throttle, kill, stop stress — in sequence,
> verifying after thirty seconds that the CPU returned to normal.
>
> That entire pipeline — sense, detect, diagnose, recover, verify —
> ran automatically without any human intervention."

---

## SLIDE 19 — References  `[~20 seconds]`

> "All references are on screen.
> The key academic foundations are:
> Tukey 1977 for IQR outlier detection,
> Chandola et al. 2009 for the anomaly detection survey,
> Liu et al. 2008 for Isolation Forest,
> and Hochreiter & Schmidhuber 1997 for LSTM.
>
> Thank you. I am happy to take any questions."

---

## TIMING SUMMARY

| Slide | Title | Time |
|-------|-------|------|
| 1 | Title | 20s |
| 2 | Purpose | 90s |
| 3 | Hardware Photos | 90s |
| 4 | Project Overview | 60s |
| 5 | Hardware & System Setup | 55s |
| 6 | Hardware Constraints | 55s |
| 7 | Software Constraints | 55s |
| 8 | Where Does Data Come From | 55s |
| 9 | How Thresholds Work | 65s |
| 10 | How Monitors Work | 50s |
| 11 | Role of AI Agents | 65s |
| 12 | What AI Models | 55s |
| 13 | How Are We Testing | 60s |
| 14 | Key Challenges | 80s |
| 15 | Project Timeline | 50s |
| 16 | Team Contributions | 40s |
| 17 | Future Work | 55s |
| 18 | Demo | 60s |
| 19 | References | 20s |
| **Total** | | **~17m 50s** |

---

## TIPS

- Slide 2 (Purpose) and Slide 3 (Hardware) set the story — take your time here.
- Slide 14 (Challenges) shows real problem-solving — be confident describing each fix.
- If running short on time, trim Slides 10 and 16 first — they are the most self-explanatory.
- If running long, cut the detail on Slide 12 (AI Models) to just the top two rows.
- Practice the Slide 9 (Thresholds) explanation — it is the most technical and easiest to rush.
