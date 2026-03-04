# Sentinel AI - System Architecture

## Overview

Sentinel AI is a distributed, multi-agent system designed for autonomous monitoring, anomaly detection, diagnosis, and recovery of IoT infrastructure. The architecture combines edge computing with cloud services to achieve real-time self-healing at scale.

## Design Principles

1. **Loose Coupling**: Agents communicate through events, not direct calls
2. **Scalability**: Designed to run on resource-constrained devices (Raspberry Pi)
3. **Resilience**: Self-healing capabilities at multiple levels
4. **Modularity**: Each agent is independent and replaceable
5. **Observability**: Comprehensive logging and metrics
6. **Adaptability**: Learning from incidents to improve over time

## System Components

### 1. Core Infrastructure

#### Event Bus
**Purpose**: Internal publish-subscribe messaging system

**Implementation**: In-memory with thread-safe operations
- Supports synchronous and asynchronous event handlers
- Priority-based event routing
- Event buffering for persistence/replay
- Retry logic for failed handlers

**Event Types**:
- `health.metric`: Health monitoring data
- `anomaly.detected`: Anomaly detection results
- `diagnosis.complete`: Diagnosis results with recommended actions
- `recovery.action`: Recovery action execution results
- `learning.updated`: Learning/adaptation updates

**Why Event Bus?**
- Decouples agents from each other
- Enables dynamic subscription at runtime
- Provides audit trail of all system events
- Allows easy integration of new agents

#### Configuration Manager
**Purpose**: Centralized configuration with environment variable support

**Features**:
- YAML-based configuration
- Environment variable substitution (`${VAR:-default}`)
- Dot-notation access (`config.get('monitoring.interval')`)
- Runtime reloading
- Validation and error handling

**Configuration Hierarchy**:
```
config.yaml
  ├─ system (device ID, environment)
  ├─ monitoring (metrics, intervals)
  ├─ anomaly_detection (methods, thresholds)
  ├─ diagnosis (rules, LLM settings)
  ├─ recovery (actions, retry logic)
  ├─ learning (persistence, adaptation)
  └─ aws (IoT Core, CloudWatch, Bedrock)
```

#### Logging Infrastructure
**Purpose**: Structured, production-grade logging

**Features**:
- JSON-formatted logs for machine parsing
- Multiple handlers (console, file, CloudWatch)
- Automatic log rotation
- Context injection (device_id, environment)
- Exception tracking with stack traces

**Log Levels**:
- DEBUG: Detailed diagnostic information
- INFO: General system operation
- WARNING: Potential issues
- ERROR: Runtime errors
- CRITICAL: System-critical failures

#### Database Layer
**Purpose**: Local persistence with SQLite

**Tables**:
- `incidents`: Complete incident records
- `metrics_history`: Time-series metric data
- `anomalies`: Detected anomalies
- `recovery_actions`: Action execution history
- `learning_data`: Adaptive thresholds and patterns

**Features**:
- Thread-safe operations
- Automatic schema creation
- Indexed queries for performance
- Retention policy enforcement
- Cloud sync tracking

### 2. Agent Architecture

#### Base Agent Class
All agents inherit from `BaseAgent`:

```python
class BaseAgent(ABC):
    - start(): Start agent thread
    - stop(): Graceful shutdown
    - _run(): Main agent loop (abstract)
    - process_event(): Event handler (abstract)
    - publish_event(): Publish to event bus
```

**Lifecycle**:
1. Initialize with config, event bus, logger
2. Subscribe to relevant events
3. Start background thread
4. Process events or run periodic tasks
5. Graceful shutdown on stop signal

#### MonitoringAgent

**Responsibility**: Collect real-time health metrics

**Architecture**:
```
┌─────────────────────────────┐
│    MonitoringAgent          │
│                             │
│  ┌────────────────────────┐ │
│  │  Metric Collectors     │ │
│  │                        │ │
│  │  - CPUCollector        │ │
│  │  - MemoryCollector     │ │
│  │  - DiskCollector       │ │
│  │  - NetworkCollector    │ │
│  │  - MQTTCollector       │ │
│  │  - SensorCollector     │ │
│  └────────────────────────┘ │
│            ↓                │
│  ┌────────────────────────┐ │
│  │   Publish Event        │ │
│  │   "health.metric"      │ │
│  └────────────────────────┘ │
└─────────────────────────────┘
```

**Metrics Collected**:
- **CPU**: Utilization, frequency, load average, top process
- **Memory**: Usage, swap, top process by memory
- **Disk**: Space utilization, I/O statistics
- **Network**: Packet loss, latency, bandwidth
- **MQTT**: Connection status, publish latency
- **Sensors**: Read latency, success rate

**Collection Strategy**:
- Runs every 5 seconds (configurable)
- Non-blocking metric collection
- Graceful degradation if collector fails
- Store in database + publish to event bus

#### AnomalyDetectionAgent

**Responsibility**: Detect abnormal behavior in metrics

**Architecture**:
```
┌──────────────────────────────────────┐
│    AnomalyDetectionAgent             │
│                                      │
│  ┌─────────────────────────────────┐│
│  │  Statistical Methods            ││
│  │                                 ││
│  │  1. Threshold Detection         ││
│  │     - Static thresholds         ││
│  │                                 ││
│  │  2. Z-Score Analysis            ││
│  │     - Rolling window (N=100)    ││
│  │     - Deviation threshold=3.0   ││
│  │                                 ││
│  │  3. Spike Detection             ││
│  │     - Sudden increases (2.5x)   ││
│  │                                 ││
│  │  4. Rolling Baseline            ││
│  │     - Adaptive mean/std         ││
│  └─────────────────────────────────┘│
│                                      │
│  ┌─────────────────────────────────┐│
│  │  Machine Learning               ││
│  │                                 ││
│  │  - Isolation Forest             ││
│  │  - Multivariate analysis        ││
│  │  - Auto-retraining (24h)        ││
│  │  - Contamination: 10%           ││
│  └─────────────────────────────────┘│
│                                      │
│           ↓                          │
│  ┌─────────────────────────────────┐│
│  │   Publish Event                 ││
│  │   "anomaly.detected"            ││
│  └─────────────────────────────────┘│
└──────────────────────────────────────┘
```

**Anomaly Types**:
- `threshold`: Exceeds static threshold
- `statistical_zscore`: Z-score deviation > 3.0
- `spike`: Sudden increase > 2.5x baseline
- `ml_isolation_forest`: ML-detected multivariate anomaly

**Severity Levels**:
- `low`: Minor deviation
- `medium`: Moderate anomaly
- `high`: Significant issue
- `critical`: System-threatening condition

**Why Multiple Methods?**
- **Threshold**: Fast, simple, catches obvious issues
- **Z-Score**: Adapts to normal variation, catches statistical outliers
- **Spike**: Detects sudden changes that might be missed by others
- **Isolation Forest**: Finds complex, multivariate patterns

#### DiagnosisAgent

**Responsibility**: Determine root cause of anomalies

**Architecture**:
```
┌────────────────────────────────────────┐
│       DiagnosisAgent                   │
│                                        │
│  ┌───────────────────────────────────┐│
│  │   Rule-Based Diagnosis            ││
│  │                                   ││
│  │   1. Load diagnosis_rules.yaml   ││
│  │   2. Match conditions             ││
│  │   3. Select best rule             ││
│  │   4. Format diagnosis             ││
│  └───────────────────────────────────┘│
│                ↓                       │
│  ┌───────────────────────────────────┐│
│  │   LLM-Powered Diagnosis           ││
│  │   (AWS Bedrock)                   ││
│  │                                   ││
│  │   1. Build context                ││
│  │      - Current anomaly            ││
│  │      - Recent metrics             ││
│  │      - Historical incidents       ││
│  │                                   ││
│  │   2. Construct prompt             ││
│  │   3. Invoke AWS Bedrock LLM        ││
│  │   4. Parse JSON response          ││
│  └───────────────────────────────────┘│
│                ↓                       │
│  ┌───────────────────────────────────┐│
│  │   Merge & Prioritize              ││
│  │   - Use rule if confident         ││
│  │   - Enhance with LLM insights     ││
│  │   - Recommend actions             ││
│  └───────────────────────────────────┘│
│                ↓                       │
│  ┌───────────────────────────────────┐│
│  │   Publish Event                   ││
│  │   "diagnosis.complete"            ││
│  └───────────────────────────────────┘│
└────────────────────────────────────────┘
```

**Diagnosis Output**:
```json
{
  "diagnosis_id": "uuid",
  "diagnosis": "High CPU caused by process X",
  "root_cause": "Memory leak in service Y",
  "confidence": 0.85,
  "recommended_actions": ["kill_process", "restart_service"],
  "severity": "high",
  "methods_used": ["rule_based", "llm_powered"]
}
```

**Why Hybrid Approach?**
- **Rules**: Fast, deterministic, no API calls
- **LLM**: Handles complex, novel scenarios
- **Combination**: Best of both worlds

#### RecoveryAgent

**Responsibility**: Execute corrective actions autonomously

**Architecture**:
```
┌────────────────────────────────────────┐
│       RecoveryAgent                    │
│                                        │
│  ┌───────────────────────────────────┐│
│  │   Action Dispatcher               ││
│  │                                   ││
│  │   1. Check if action enabled      ││
│  │   2. Verify cooldown              ││
│  │   3. Execute with retry (3x)      ││
│  │   4. Log result                   ││
│  │   5. Set cooldown (5min)          ││
│  └───────────────────────────────────┘│
│                                        │
│  ┌───────────────────────────────────┐│
│  │   Available Actions               ││
│  │                                   ││
│  │   - restart_mqtt                  ││
│  │   - kill_process                  ││
│  │   - reconnect_sensor              ││
│  │   - failover                      ││
│  │   - clear_cache                   ││
│  │   - restart_service               ││
│  │   - check_network                 ││
│  │   - full_system_restart           ││
│  └───────────────────────────────────┘│
│                ↓                       │
│  ┌───────────────────────────────────┐│
│  │   Publish Event                   ││
│  │   "recovery.action"               ││
│  └───────────────────────────────────┘│
└────────────────────────────────────────┘
```

**Retry Logic**:
```python
for attempt in range(1, max_retries + 1):
    result = execute_action()
    if result.success:
        return success
    sleep(retry_delay)
return failure
```

**Safety Mechanisms**:
- Cooldown periods prevent loops
- Action whitelisting
- Critical process protection
- Execution timeouts
- Comprehensive logging

#### LearningAgent

**Responsibility**: Learn from incidents and adapt

**Architecture**:
```
┌────────────────────────────────────────┐
│       LearningAgent                    │
│                                        │
│  ┌───────────────────────────────────┐│
│  │   Local Persistence               ││
│  │   (SQLite)                        ││
│  │                                   ││
│  │   - Store all incidents           ││
│  │   - Track recovery results        ││
│  │   - Maintain metrics history      ││
│  └───────────────────────────────────┘│
│                ↓                       │
│  ┌───────────────────────────────────┐│
│  │   Cloud Sync                      ││
│  │                                   ││
│  │   - DynamoDB (incidents)          ││
│  │   - S3 (logs, archives)           ││
│  │   - Sync every 15 min             ││
│  └───────────────────────────────────┘│
│                ↓                       │
│  ┌───────────────────────────────────┐│
│  │   Adaptive Learning               ││
│  │                                   ││
│  │   1. Threshold Adjustment         ││
│  │      - Reduce false positives     ││
│  │      - Increase sensitivity       ││
│  │                                   ││
│  │   2. Strategy Refinement          ││
│  │      - Track success rates        ││
│  │      - Optimize action selection  ││
│  └───────────────────────────────────┘│
└────────────────────────────────────────┘
```

**Learning Mechanisms**:

1. **Threshold Adjustment**:
   - If many low-severity incidents: increase threshold 5%
   - If many critical incidents: decrease threshold 5%
   - Store adjustments in database
   - Apply globally to anomaly detection

2. **Strategy Refinement**:
   - Track success rate per action type
   - Recommend more successful actions
   - Flag low-performing actions

### 3. AWS Cloud Integration

#### IoT Core Integration
```
Edge Device                  AWS IoT Core
    │                              │
    ├─ Telemetry ───────────────→ │
    ├─ Anomalies ───────────────→ │
    ├─ Recovery ────────────────→ │
    │                              │
    │ ←──────────── Policy ────────┤
```

**Topics**:
- `sentinel/telemetry/{device_id}`: Health metrics
- `sentinel/anomalies/{device_id}`: Detected anomalies
- `sentinel/recovery/{device_id}`: Recovery actions
- `sentinel/policy/{device_id}`: Configuration updates

#### CloudWatch Integration
- Publishes metrics in batches
- Custom namespace: `SentinelAI`
- Dimensions: `DeviceId`
- Enables fleet-wide dashboards

#### Bedrock Integration
- Model: `anthropic.claude-3-sonnet-20240229-v1:0`
- Use case: Advanced root cause analysis
- Fallback: Rule-based diagnosis if unavailable

## Data Flow

### Normal Operation
```
1. MonitoringAgent collects metrics
   ↓
2. Publishes "health.metric" event
   ↓
3. AnomalyDetectionAgent receives event
   ↓
4. If anomaly detected:
   - Publishes "anomaly.detected" event
   ↓
5. DiagnosisAgent receives anomaly
   - Runs rule-based diagnosis
   - Optionally queries LLM
   - Publishes "diagnosis.complete"
   ↓
6. RecoveryAgent receives diagnosis
   - Executes recommended actions
   - Publishes "recovery.action"
   ↓
7. LearningAgent stores incident
   - Saves to SQLite
   - Syncs to cloud
   - Adapts thresholds
```

## Scalability

### Edge Scalability
- Lightweight: Runs on Raspberry Pi 1GB RAM
- Efficient: 5-10% CPU, 100-200MB memory
- Local-first: Works offline, syncs when online

### Cloud Scalability
```
100+ Devices
     ↓
AWS IoT Core (handles millions of devices)
     ↓
Lambda Orchestrator (auto-scales)
     ↓
DynamoDB (pay-per-request)
     ↓
S3 (unlimited storage)
     ↓
CloudWatch (aggregated metrics)
```

## Performance

### Latency
- Metric collection: <100ms
- Anomaly detection: <500ms
- Diagnosis (rule-based): <200ms
- Diagnosis (LLM): 2-5 seconds
- Recovery action: 1-30 seconds

### Throughput
- 1 device: 200 metrics/second
- 100 devices: 20,000 metrics/second (cloud)

### Resource Usage (Per Device)
- CPU: 5-10%
- Memory: 100-200MB
- Disk: ~100MB/day (with retention)
- Network: ~10 KB/s

## Security

### Edge Security
- No hardcoded credentials
- Certificate-based auth (AWS IoT)
- Encrypted storage (optional)
- Minimal attack surface

### Cloud Security
- TLS 1.2+ for all communication
- IAM roles with least privilege
- VPC isolation (optional)
- CloudTrail audit logging

## Resilience

### Edge Resilience
- Agents run independently
- Event bus retries failed handlers
- Database persistence survives restarts
- Works offline (local-only mode)

### Cloud Resilience
- Multi-region deployment (optional)
- DynamoDB on-demand scaling
- S3 durability: 99.999999999%
- IoT Core: Managed, highly available

## Future Enhancements

1. **Federated Learning**: Share patterns across devices
2. **Predictive Maintenance**: Forecast failures before they occur
3. **Fleet Coordination**: Cross-device anomaly correlation
4. **Custom ML Models**: Train device-specific models
5. **Edge ML**: Run models locally (TensorFlow Lite)

## Conclusion

Sentinel AI's architecture balances edge autonomy with cloud coordination, providing a scalable, resilient, and adaptive self-healing system for IoT infrastructure. The multi-agent design ensures modularity and maintainability, while the learning capabilities enable continuous improvement over time.
