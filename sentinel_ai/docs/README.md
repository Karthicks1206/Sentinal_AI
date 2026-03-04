# Sentinel AI - Autonomous Self-Healing Distributed IoT Infrastructure

## Overview

Sentinel AI is a production-ready, scalable multi-agent AI framework designed for autonomous monitoring, anomaly detection, diagnosis, and recovery of distributed IoT systems. The system combines edge computing (Raspberry Pi) with AWS cloud services to provide real-time self-healing capabilities across 100+ devices.

## Key Features

### 🔍 Real-Time Health Monitoring
- **CPU, Memory, Disk**: Comprehensive system resource monitoring using `psutil`
- **Network**: Packet loss detection, latency measurement, ping health checks
- **MQTT Connectivity**: Broker connection status and latency tracking
- **Sensor Health**: Custom sensor integration with latency and success rate monitoring

### 🤖 Multi-Agent Architecture
- **MonitoringAgent**: Collects real-time health metrics every 5 seconds
- **AnomalyDetectionAgent**: Detects anomalies using statistical methods + ML
- **DiagnosisAgent**: Performs root cause analysis using rules + LLM (AWS Bedrock)
- **RecoveryAgent**: Executes autonomous corrective actions
- **LearningAgent**: Learns from incidents and adapts thresholds over time

### 📊 Advanced Anomaly Detection
- **Statistical Methods**:
  - Z-score deviation analysis
  - Spike detection (sudden increases)
  - Threshold-based alerts
  - Rolling baseline comparison

- **Machine Learning**:
  - Isolation Forest for multivariate anomaly detection
  - Automatic model retraining every 24 hours
  - Contamination-based outlier detection

### 🧠 LLM-Powered Diagnosis
- **AWS Bedrock Integration**: Uses AWS Bedrock LLM for intelligent root cause analysis
- **Context-Aware**: Analyzes historical metrics, recent incidents, and system logs
- **Structured Output**: Provides actionable insights and recommended recovery actions

### 🔧 Autonomous Recovery
- **Restart MQTT Service**: Automatically restarts failed MQTT brokers
- **Kill Memory-Intensive Processes**: Terminates processes exceeding memory thresholds
- **Reconnect Sensors**: Re-establishes sensor connections
- **Failover**: Switches to backup infrastructure
- **Clear Cache**: Removes stale cache data
- **Retry Logic**: Up to 3 retries with configurable delays
- **Cooldown Periods**: Prevents recovery action loops

### 📈 Adaptive Learning
- **Incident Persistence**: Stores all incidents in local SQLite database
- **AWS Sync**: Automatically syncs to DynamoDB and S3
- **Threshold Adjustment**: Dynamically adjusts detection thresholds based on false positive rates
- **Strategy Refinement**: Tracks recovery action success rates and optimizes strategies
- **Retention Policies**: Automatic cleanup of old data (configurable)

### ☁️ AWS Cloud Integration
- **AWS IoT Core**: Device coordination and MQTT message routing
- **AWS Lambda**: Centralized orchestration for 100+ devices
- **Amazon DynamoDB**: Incident storage and querying
- **Amazon S3**: Long-term log archival
- **CloudWatch**: Telemetry aggregation and visualization
- **AWS Bedrock**: LLM-powered diagnostics

### 🧪 Simulation & Testing
- **Memory Spike Simulation**: Tests memory management
- **MQTT Drop Simulation**: Tests connectivity recovery
- **Latency Increase**: Tests network degradation handling
- **Sensor Failure**: Tests sensor reconnection logic
- **CPU Overload**: Tests resource contention handling

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Edge Device (Raspberry Pi)               │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Event Bus (Internal)                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Monitoring   │  │  Anomaly     │  │  Diagnosis   │          │
│  │   Agent      │→ │ Detection    │→ │   Agent      │          │
│  │              │  │   Agent      │  │ (Rule + LLM) │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                              ↓                   │
│                                       ┌──────────────┐          │
│                                       │  Recovery    │          │
│                                       │   Agent      │          │
│                                       └──────────────┘          │
│                                              ↓                   │
│                                       ┌──────────────┐          │
│                                       │  Learning    │          │
│                                       │   Agent      │          │
│                                       └──────────────┘          │
│                                              ↓                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    SQLite Database                          │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                  ↕ (AWS IoT Core)
┌─────────────────────────────────────────────────────────────────┐
│                          AWS Cloud                               │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  IoT Core    │  │   Lambda     │  │  Bedrock     │          │
│  │              │  │ Orchestrator │  │    (LLM)     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  DynamoDB    │  │      S3      │  │ CloudWatch   │          │
│  │  (Incidents) │  │    (Logs)    │  │  (Metrics)   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

- **Hardware**: Raspberry Pi 3/4/5 (or any Linux system)
- **OS**: Raspbian/Raspberry Pi OS or Ubuntu
- **Python**: 3.8+
- **AWS Account**: For cloud integration (optional but recommended)

### Step 1: Clone Repository

```bash
git clone <repository-url>
cd sentinel_ai
```

### Step 2: Install Dependencies

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev

# Install Python packages
pip3 install -r requirements.txt
```

### Step 3: Configure Environment

```bash
# Set environment variables
export DEVICE_ID="raspberry-pi-001"
export ENVIRONMENT="production"
export AWS_REGION="us-east-1"

# Optional: MQTT broker
export MQTT_BROKER="localhost"

# Optional: AWS credentials (if not using IAM role)
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
```

### Step 4: Configure Sentinel AI

Edit `config/config.yaml`:

```yaml
system:
  device_id: "${DEVICE_ID:-raspberry-pi-001}"
  environment: "${ENVIRONMENT:-production}"

monitoring:
  collection_interval: 5

aws:
  enabled: true  # Set to false for local-only mode
  region: "us-east-1"
```

### Step 5: AWS Setup (Optional)

If using AWS integration:

1. **Create IoT Thing**:
   ```bash
   aws iot create-thing --thing-name sentinel-device-001
   ```

2. **Generate Certificates**:
   ```bash
   aws iot create-keys-and-certificate \
     --set-as-active \
     --certificate-pem-outfile certs/device.cert.pem \
     --public-key-outfile certs/device.public.key \
     --private-key-outfile certs/device.private.key
   ```

3. **Create DynamoDB Table**:
   ```bash
   aws dynamodb create-table \
     --table-name sentinel-incidents \
     --attribute-definitions AttributeName=incident_id,AttributeType=S \
     --key-schema AttributeName=incident_id,KeyType=HASH \
     --billing-mode PAY_PER_REQUEST
   ```

4. **Create S3 Bucket**:
   ```bash
   aws s3 mb s3://sentinel-logs-<your-account-id>
   ```

### Step 6: Run Sentinel AI

```bash
# Run directly
python3 main.py

# Or with specific config
python3 main.py --config /path/to/config.yaml

# With simulation mode
python3 main.py --simulate
```

## Configuration

### Key Configuration Sections

#### Monitoring Configuration
```yaml
monitoring:
  collection_interval: 5  # seconds
  metrics:
    cpu:
      enabled: true
      threshold_percent: 80
    memory:
      enabled: true
      threshold_percent: 85
```

#### Anomaly Detection Configuration
```yaml
anomaly_detection:
  methods:
    z_score:
      enabled: true
      threshold: 3.0
    ml:
      enabled: true
      model: "isolation_forest"
```

#### Diagnosis Configuration
```yaml
diagnosis:
  llm:
    enabled: true
    provider: "aws_bedrock"
    model_id: "anthropic.claude-3-sonnet-20240229-v1:0"
```

#### Recovery Configuration
```yaml
recovery:
  auto_recovery: true
  max_retries: 3
  cooldown_period_seconds: 300
```

## Usage Examples

### Basic Operation

```bash
# Start Sentinel AI
python3 main.py

# Expected output:
# 2024-01-15 10:30:00 - INFO - Sentinel AI - Autonomous Self-Healing System
# 2024-01-15 10:30:00 - INFO - Device ID: raspberry-pi-001
# 2024-01-15 10:30:01 - INFO - ✓ Monitoring Agent initialized
# 2024-01-15 10:30:01 - INFO - ✓ Anomaly Detection Agent initialized
# 2024-01-15 10:30:01 - INFO - ✓ Diagnosis Agent initialized
# 2024-01-15 10:30:01 - INFO - ✓ Recovery Agent initialized
# 2024-01-15 10:30:01 - INFO - ✓ Learning Agent initialized
# 2024-01-15 10:30:02 - INFO - Sentinel AI is now operational
```

### Triggering Simulations

```python
from simulation.simulator import FailureSimulator
from core.config import get_config
from core.logging import get_logger

config = get_config()
logger = get_logger('Simulator')
simulator = FailureSimulator(config, logger)

# Trigger specific scenario
simulator.trigger_specific_scenario('memory_spike')
```

### Querying Incidents

```python
from core.database import get_database

db = get_database()

# Get recent incidents
incidents = db.get_recent_incidents(limit=10)

for incident in incidents:
    print(f"Incident: {incident['diagnosis']}")
    print(f"Recovery: {incident['recovery_status']}")
```

## Deployment

### Raspberry Pi Deployment

See `docs/RASPBERRY_PI_DEPLOYMENT.md` for detailed instructions.

### Docker Deployment

```bash
docker build -t sentinel-ai .
docker run -d --name sentinel \
  -e DEVICE_ID=rpi-001 \
  -e AWS_REGION=us-east-1 \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  sentinel-ai
```

### systemd Service

```bash
sudo cp deployment/systemd/sentinel-ai.service /etc/systemd/system/
sudo systemctl enable sentinel-ai
sudo systemctl start sentinel-ai
```

## Monitoring & Observability

### Local Logs

```bash
# View logs
tail -f logs/sentinel.log

# Parse JSON logs
tail -f logs/sentinel.log | jq '.'
```

### AWS CloudWatch

Navigate to CloudWatch console and view:
- **Namespace**: `SentinelAI`
- **Dimensions**: `DeviceId`
- **Metrics**: CPU, memory, disk, network metrics per device

### Database Queries

```sql
-- Get recent anomalies
SELECT * FROM anomalies
ORDER BY timestamp DESC
LIMIT 10;

-- Get recovery success rate
SELECT
  action_type,
  COUNT(*) as total,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful
FROM recovery_actions
GROUP BY action_type;
```

## Scaling to 100+ Devices

### Cloud Coordinator Architecture

Deploy Lambda function for centralized orchestration:

```python
# lambda_orchestrator.py
def lambda_handler(event, context):
    # Aggregate anomalies from all devices
    # Distribute adaptive policies
    # Coordinate failover across fleet
    pass
```

### Fleet Management

- **AWS IoT Device Management**: Organize devices into groups
- **Fleet-Wide Policies**: Push configuration updates to all devices
- **Aggregated Analytics**: CloudWatch dashboards for entire fleet

## Performance Considerations

- **Edge Computing**: All agents run locally on Raspberry Pi
- **Minimal Latency**: Sub-second anomaly detection
- **Low Bandwidth**: Only anomalies/incidents sent to cloud
- **Efficient Storage**: SQLite with automatic cleanup
- **Scalable**: Tested on Raspberry Pi 3B+ with 1GB RAM

## Security

- **TLS/SSL**: All AWS communication encrypted
- **Certificate-Based Auth**: AWS IoT Core X.509 certificates
- **Principle of Least Privilege**: IAM roles with minimal permissions
- **No Hardcoded Secrets**: Environment variable configuration
- **Audit Logging**: All actions logged locally and in cloud

## Troubleshooting

### Agent Not Starting

```bash
# Check logs
journalctl -u sentinel-ai -f

# Verify configuration
python3 -c "from core.config import get_config; print(get_config().to_dict())"
```

### AWS Connection Issues

```bash
# Test IoT connectivity
mosquitto_pub --cafile certs/root-CA.crt \
  --cert certs/device.cert.pem \
  --key certs/device.private.key \
  -h <iot-endpoint> -p 8883 \
  -t test/topic -m "test"
```

### High Memory Usage

Adjust configuration:
```yaml
learning:
  local_db:
    retention_days: 30  # Reduce from 90
```

## Contributing

1. Fork repository
2. Create feature branch
3. Add tests
4. Submit pull request

## License

[Your License Here]

## Support

For issues and questions:
- GitHub Issues: [Link]
- Documentation: `docs/`
- Examples: `examples/`
