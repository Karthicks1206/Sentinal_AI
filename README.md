# Sentinel AI - Autonomous Self-Healing Distributed IoT Infrastructure

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![AWS](https://img.shields.io/badge/AWS-IoT%20Core%20%7C%20Bedrock-orange.svg)](https://aws.amazon.com/)

> **Production-ready multi-agent AI framework for autonomous monitoring, anomaly detection, LLM-powered diagnosis, and self-healing recovery across distributed IoT edge devices.**

## 🎯 What is Sentinel AI?

Sentinel AI is an intelligent, distributed system that monitors IoT infrastructure in real-time, detects anomalies using statistical methods and machine learning, diagnoses root causes with LLM assistance (AWS Bedrock/Claude), and autonomously executes recovery actions—all while learning and adapting from every incident.

**Think of it as:** Your IoT infrastructure's immune system that detects problems, diagnoses causes, heals itself, and gets smarter over time.

## 🚀 Key Capabilities

### Monitoring
- **Real-time health metrics**: CPU, memory, disk, network, MQTT, sensors
- **Configurable collection**: 5-second intervals (adjustable)
- **Lightweight**: Runs on Raspberry Pi with minimal overhead

### Anomaly Detection
- **Statistical methods**: Z-score, spike detection, threshold analysis
- **Machine learning**: Isolation Forest for multivariate anomalies
- **Rolling baselines**: Adapts to normal system behavior
- **Multi-severity levels**: Low, medium, high, critical

### Intelligent Diagnosis
- **Rule-based engine**: Fast, deterministic analysis (50+ rules)
- **LLM-powered**: AWS Bedrock (Claude 3 Sonnet) for complex root cause analysis
- **Context-aware**: Analyzes historical data, logs, and patterns
- **Hybrid approach**: Combines rules + AI for best results

### Autonomous Recovery
- **Self-healing actions**: Restart services, kill processes, reconnect sensors, failover
- **Retry logic**: Up to 3 attempts with configurable delays
- **Cooldown periods**: Prevents recovery loops
- **Safety mechanisms**: Critical process protection, execution timeouts

### Adaptive Learning
- **Incident persistence**: SQLite locally + AWS (DynamoDB/S3) sync
- **Threshold optimization**: Automatically adjusts based on false positive rates
- **Strategy refinement**: Tracks recovery action success rates
- **Continuous improvement**: Gets smarter with every incident

### Cloud Integration
- **AWS IoT Core**: Device coordination for 100+ devices
- **AWS Lambda**: Centralized fleet orchestration
- **Amazon Bedrock**: LLM-powered diagnostics
- **CloudWatch**: Telemetry aggregation and visualization
- **DynamoDB + S3**: Incident storage and archival

## 📊 Architecture at a Glance

```
┌─────────────────────────────────────────────────────────┐
│                    Edge Device (Raspberry Pi)            │
│                                                          │
│  MonitoringAgent → AnomalyAgent → DiagnosisAgent →      │
│                                    (Rules + LLM)         │
│                                          ↓               │
│                                    RecoveryAgent →       │
│                                          ↓               │
│                                    LearningAgent         │
│                                          ↓               │
│                                    SQLite Database       │
└─────────────────────────────────────────────────────────┘
                          ↕ (AWS IoT Core)
┌─────────────────────────────────────────────────────────┐
│                      AWS Cloud Services                  │
│                                                          │
│  IoT Core • Lambda • Bedrock • DynamoDB • S3 • CloudWatch│
└─────────────────────────────────────────────────────────┘
```

## 🎬 2-Minute Live Demo

### **See Autonomous Self-Healing in Action!**

Watch the system detect, diagnose, and fix a CPU overload **automatically**:

**Terminal 1:** Start dashboard
```bash
cd sentinel_ai
./start_dashboard.sh
```

**Terminal 2:** Open `http://localhost:5000` in browser

**Terminal 3:** Run demo
```bash
cd sentinel_ai
./run_demo.sh
```

**Timeline:**
- [00s] Normal operation
- [05s] 🔥 CPU stress applied (95%+) → Dashboard turns RED
- [15s] 🚨 **Full-screen alert** → "ANOMALY DETECTED!"
- [20s] 🔍 Diagnosis shown → "High CPU by python3"
- [27s] 🔧 **Auto-fix executed** → Process killed
- [30s] ✅ CPU normal → Dashboard turns GREEN

**Complete guide:** [COMPLETE_DEMO.md](COMPLETE_DEMO.md)

---

## 🚀 Quick Start

### Option 1: Web Dashboard (Recommended for Testing)

```bash
# Clone repository
git clone https://github.com/your-org/sentinel-ai.git
cd sentinel-ai/sentinel_ai

# Install dependencies
pip install -r requirements.txt

# Start web dashboard
./start_dashboard.sh
```

**Then open browser:** `http://localhost:5000`

See the **beautiful real-time dashboard** with:
- 📊 Live metrics (CPU, memory, disk)
- 🤖 Agent status indicators
- 📋 Auto-scrolling logs
- 🚨 Full-screen anomaly alerts
- 🔍 Real-time diagnosis

**Test it:**
```bash
# In another terminal, trigger anomaly
python3 trigger_anomaly.py cpu
```

Watch the dashboard detect, diagnose, and respond in real-time! 🚀

See: **[DASHBOARD_QUICKSTART.md](sentinel_ai/DASHBOARD_QUICKSTART.md)** for full guide.

---

### Option 2: Command Line

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
export DEVICE_ID="my-device-001"
export AWS_REGION="us-east-1"

# Run
python3 main.py
```

**Output:**
```
INFO - Sentinel AI - Autonomous Self-Healing System
INFO - Device ID: my-device-001
INFO - ✓ Monitoring Agent initialized
INFO - ✓ Anomaly Detection Agent initialized
INFO - ✓ Diagnosis Agent initialized
INFO - ✓ Recovery Agent initialized
INFO - ✓ Learning Agent initialized
INFO - Sentinel AI is now operational
```

## 📚 Documentation

- **[Complete Documentation](sentinel_ai/docs/README.md)**: Features, configuration, usage
- **[Architecture Guide](sentinel_ai/docs/ARCHITECTURE.md)**: System design, data flow, scalability
- **[Raspberry Pi Deployment](sentinel_ai/docs/RASPBERRY_PI_DEPLOYMENT.md)**: Step-by-step Pi setup
- **Configuration**: See `sentinel_ai/config/config.yaml`
- **Diagnosis Rules**: See `sentinel_ai/config/diagnosis_rules.yaml`

## 🔧 Deployment Options

### Raspberry Pi (Production)
```bash
# See detailed guide
cat sentinel_ai/docs/RASPBERRY_PI_DEPLOYMENT.md

# Quick systemd setup
sudo cp sentinel_ai/deployment/systemd/sentinel-ai.service /etc/systemd/system/
sudo systemctl enable sentinel-ai
sudo systemctl start sentinel-ai
```

### Docker
```bash
cd sentinel_ai
docker-compose up -d
```

### Local Development
```bash
cd sentinel_ai
python3 main.py --simulate
```

## 🧪 Testing Resilience

Built-in simulation environment:

```python
from simulation.simulator import FailureSimulator

simulator = FailureSimulator(config, logger, event_bus)
simulator.start()

# Manually trigger scenarios
simulator.trigger_specific_scenario('memory_spike')
simulator.trigger_specific_scenario('mqtt_drop')
simulator.trigger_specific_scenario('cpu_overload')
```

**Available scenarios:**
- Memory spike (90%+ usage)
- MQTT connection drop
- Network latency increase (5x)
- Sensor communication failure
- CPU overload (95%+ usage)

## 📈 Real-World Example

**Scenario**: Memory leak detected

```
1. MonitoringAgent: Detects memory at 87% (threshold: 85%)
   └→ Publishes "health.metric" event

2. AnomalyDetectionAgent: Z-score = 3.2, classifies as "high severity"
   └→ Publishes "anomaly.detected" event

3. DiagnosisAgent:
   - Rule match: "Memory leak - increasing trend"
   - LLM analysis: "Process 'node_app' consuming 450MB, growing 5MB/min"
   - Recommended actions: ["kill_process", "clear_cache"]
   └→ Publishes "diagnosis.complete" event

4. RecoveryAgent:
   - Executes: kill_process(node_app, PID: 1234)
   - Result: Success in 2.3s
   - Sets 5-minute cooldown
   └→ Publishes "recovery.action" event

5. LearningAgent:
   - Stores incident in SQLite
   - Syncs to DynamoDB/S3
   - Tracks kill_process success rate: 94%
   - Adjusts memory threshold: 85% → 83% (increase sensitivity)
```

## 🌟 Why Sentinel AI?

### vs Traditional Monitoring (Prometheus, Grafana, etc.)
- ✅ **Autonomous recovery** (not just alerting)
- ✅ **LLM-powered diagnosis** (not just metrics)
- ✅ **Continuous learning** (adapts over time)
- ✅ **Edge-first** (works offline, syncs later)

### vs Cloud-Only Solutions
- ✅ **Low latency** (edge processing)
- ✅ **Reduced bandwidth** (only incidents sent to cloud)
- ✅ **Offline resilience** (local-first architecture)
- ✅ **Cost-effective** (minimal cloud API calls)

### vs Manual Intervention
- ✅ **24/7 operation** (no human needed)
- ✅ **Sub-second response** (automated)
- ✅ **Consistent** (no human error)
- ✅ **Scalable** (100+ devices)

## 🏗️ Project Structure

```
sentinel_ai/
├── main.py                 # System orchestrator
├── config/
│   ├── config.yaml         # Main configuration
│   └── diagnosis_rules.yaml# Diagnosis rules
├── core/
│   ├── config.py          # Configuration management
│   ├── logging/           # Logging infrastructure
│   ├── event_bus/         # Internal messaging
│   └── database/          # SQLite persistence
├── agents/
│   ├── monitoring/        # MonitoringAgent
│   ├── anomaly/           # AnomalyDetectionAgent
│   ├── diagnosis/         # DiagnosisAgent
│   ├── recovery/          # RecoveryAgent
│   └── learning/          # LearningAgent
├── cloud/
│   └── aws_iot/           # AWS integration
├── simulation/            # Failure simulation
├── deployment/
│   ├── docker/            # Docker configs
│   ├── systemd/           # systemd service
│   └── raspberry_pi/      # Pi-specific configs
└── docs/                  # Documentation
```

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Areas for Contribution
- Additional recovery actions
- More diagnosis rules
- Custom metric collectors
- Integration with other LLMs
- Performance optimizations

## 📊 Performance

**Single Raspberry Pi 3B+ (1GB RAM):**
- CPU Usage: 5-10%
- Memory Usage: 100-200MB
- Metric Collection Latency: <100ms
- Anomaly Detection Latency: <500ms
- Recovery Action Latency: 1-30s
- Storage: ~100MB/day (with 90-day retention)

**Scalability:**
- Tested: 100+ devices with AWS IoT Core + Lambda orchestration
- Theoretical: Unlimited (AWS scales automatically)

## 🔐 Security

- **No hardcoded credentials**: Environment variables only
- **TLS/SSL**: All AWS communication encrypted
- **Certificate-based auth**: X.509 certificates for IoT Core
- **IAM roles**: Principle of least privilege
- **Audit logging**: All actions logged locally + CloudWatch

## 📝 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file.

## 🙏 Acknowledgments

- **AWS Bedrock** for LLM capabilities
- **scikit-learn** for ML algorithms
- **psutil** for system monitoring
- **Eclipse Paho** for MQTT client

## 📧 Support & Contact

- **Issues**: [GitHub Issues](https://github.com/your-org/sentinel-ai/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/sentinel-ai/discussions)
- **Email**: support@sentinel-ai.io

## 🗺️ Roadmap

- [x] Core multi-agent framework
- [x] Statistical anomaly detection
- [x] LLM-powered diagnosis
- [x] Autonomous recovery
- [x] AWS cloud integration
- [x] Adaptive learning
- [ ] Federated learning across devices
- [ ] Predictive maintenance (forecasting)
- [ ] Mobile app for monitoring
- [ ] Custom ML model training
- [ ] Edge ML (TensorFlow Lite)
- [ ] Kubernetes deployment

---

**Built with ❤️ for autonomous IoT infrastructure**

⭐ **Star this repo** if Sentinel AI helps your IoT projects!
