#!/usr/bin/env python3
"""
Sentinel AI - Web Dashboard
Real-time monitoring dashboard with live updates
"""

import sys
import json
import time
import math
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, render_template, jsonify, Response, request
from flask_cors import CORS
import threading
from collections import deque

CST = ZoneInfo('America/Chicago')

def now_cst() -> str:
    """Return current time formatted in CST/CDT."""
    return datetime.now(CST).strftime('%H:%M:%S')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import get_config
from core.logging import setup_logging, get_logger
from core.event_bus import get_event_bus
from core.database import get_database

from agents.monitoring import MonitoringAgent
from agents.anomaly import AnomalyDetectionAgent
from agents.diagnosis import DiagnosisAgent
from agents.recovery import RecoveryAgent
from agents.learning import LearningAgent


# Flask app
app = Flask(__name__)
CORS(app)


class DashboardState:
    """
    Shared state for dashboard
    """
    def __init__(self):
        self.latest_metrics = {}
        self.anomalies = deque(maxlen=50)
        self.diagnoses = deque(maxlen=50)
        self.recoveries = deque(maxlen=50)
        self.logs = deque(maxlen=100)
        self.system_status = "starting"
        self.agents_status = {}
        self.alert_active = False
        self.current_alert = None
        # Rolling history for live graphs (last 60 data points)
        self.cpu_history = deque(maxlen=60)
        self.memory_history = deque(maxlen=60)
        self.disk_history = deque(maxlen=60)
        self.network_latency_history = deque(maxlen=60)  # ping latency ms
        self.power_voltage_history = deque(maxlen=60)   # input voltage V
        self.power_quality_history = deque(maxlen=60)   # power quality 0-100
        self.timestamps = deque(maxlen=60)


# Global state
state = DashboardState()


class SentinelDashboard:
    """
    Dashboard backend that subscribes to Sentinel AI events for display.
    When run_agents=True it also starts its own agent set (standalone mode).
    When run_agents=False (embedded in main.py) it is display-only.
    """

    def __init__(self, run_agents: bool = True):
        """Initialize dashboard"""
        # Configuration
        self.config = get_config()
        self.config.set('aws.enabled', False)  # Disable AWS for dashboard

        setup_logging(self.config)
        self.logger = get_logger('Dashboard')

        # Infrastructure
        self.event_bus = get_event_bus(self.config)
        self.database = get_database(self.config)

        # Subscribe to events (always — for display)
        self._setup_event_subscriptions()

        # Only initialize agents in standalone mode
        self._run_agents = run_agents
        self.agents = self._init_agents() if run_agents else {}

        # Update state
        state.system_status = "initialized"

    def _setup_event_subscriptions(self):
        """Subscribe to all events"""
        self.event_bus.subscribe("health.metric", self._on_metric)
        self.event_bus.subscribe("anomaly.detected", self._on_anomaly)
        self.event_bus.subscribe("diagnosis.complete", self._on_diagnosis)
        self.event_bus.subscribe("recovery.action", self._on_recovery)
        self.event_bus.subscribe("security.threat", self._on_security_threat)

    def _on_metric(self, event):
        """Handle metric event"""
        state.latest_metrics = event.data.get('metrics', {})

        # Add to logs
        timestamp = now_cst()
        cpu  = state.latest_metrics.get('cpu',     {}).get('cpu_percent',        0)
        mem  = state.latest_metrics.get('memory',  {}).get('memory_percent',     0)
        disk = state.latest_metrics.get('disk',    {}).get('disk_percent',       0)
        net_latency = state.latest_metrics.get('network', {}).get('ping_latency_ms', 0)
        power       = state.latest_metrics.get('power', {})
        pwr_voltage = power.get('power_voltage_v', 0)
        pwr_quality = power.get('power_quality', 100)

        # Append to rolling graph history
        state.cpu_history.append(round(cpu, 1))
        state.memory_history.append(round(mem, 1))
        state.disk_history.append(round(disk, 1))
        state.network_latency_history.append(round(net_latency, 1))
        state.power_voltage_history.append(round(pwr_voltage, 3))
        state.power_quality_history.append(round(pwr_quality, 1))
        state.timestamps.append(timestamp)

        state.logs.append({
            'timestamp': timestamp,
            'level': 'INFO',
            'message': f'Metrics collected: CPU={cpu:.1f}%, Memory={mem:.1f}%'
        })

    def _on_anomaly(self, event):
        """Handle anomaly event"""
        anomaly = event.data.get('anomaly', {})
        state.anomalies.append({
            'timestamp': datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S'),
            'anomaly': anomaly
        })

        # Set alert
        state.alert_active = True
        state.current_alert = {
            'type': 'anomaly',
            'severity': anomaly.get('severity', 'unknown'),
            'message': f"Anomaly detected: {anomaly.get('metric_name')} - {anomaly.get('type')}",
            'details': anomaly
        }

        # Add to logs
        timestamp = now_cst()
        state.logs.append({
            'timestamp': timestamp,
            'level': 'WARNING',
            'message': f"ANOMALY: {anomaly.get('metric_name')} = {anomaly.get('value', 0):.2f} (severity: {anomaly.get('severity')})"
        })

        self.logger.warning(f"Anomaly detected: {anomaly}")

    def _on_diagnosis(self, event):
        """Handle diagnosis event"""
        diagnosis = event.data.get('diagnosis', {})
        state.diagnoses.append({
            'timestamp': datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S'),
            'diagnosis': diagnosis
        })

        # Update alert with diagnosis
        if state.alert_active:
            state.current_alert['diagnosis'] = diagnosis.get('diagnosis')
            state.current_alert['root_cause'] = diagnosis.get('root_cause')
            state.current_alert['actions'] = diagnosis.get('recommended_actions', [])

        # Add to logs
        timestamp = now_cst()
        state.logs.append({
            'timestamp': timestamp,
            'level': 'WARNING',
            'message': f"DIAGNOSIS: {diagnosis.get('diagnosis', 'N/A')}"
        })
        state.logs.append({
            'timestamp': timestamp,
            'level': 'INFO',
            'message': f"   Root Cause: {diagnosis.get('root_cause', 'Unknown')}"
        })
        state.logs.append({
            'timestamp': timestamp,
            'level': 'INFO',
            'message': f"   Actions: {', '.join(diagnosis.get('recommended_actions', []))}"
        })

        self.logger.info(f"Diagnosis complete: {diagnosis.get('diagnosis')}")

    def _on_security_threat(self, event):
        """Handle security threat event — push to logs and state for SSE."""
        threat = event.data.get('threat', {})
        timestamp = now_cst()
        state.logs.append({
            'timestamp': timestamp,
            'level': 'ERROR' if threat.get('severity') in ('high', 'critical') else 'WARNING',
            'message': f"[SECURITY] {threat.get('severity', '?').upper()} — "
                       f"{threat.get('title', '?')}: {threat.get('detail', '')}"
        })
        # Attach to current_alert for SSE stream pickup
        state.security_threats = getattr(state, 'security_threats', [])
        state.security_threats.append({
            'timestamp': timestamp,
            'threat':    threat
        })
        # Keep only last 50
        if len(state.security_threats) > 50:
            state.security_threats = state.security_threats[-50:]

    def _on_recovery(self, event):
        """Handle recovery event"""
        actions = event.data.get('actions', [])
        state.recoveries.append({
            'timestamp': datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S'),
            'actions': actions
        })

        # Add to logs
        timestamp = now_cst()
        state.logs.append({
            'timestamp': timestamp,
            'level': 'INFO',
            'message': f"RECOVERY: Executing {len(actions)} action(s)"
        })

        for action in actions:
            status = 'OK' if action['status'] == 'success' else 'FAILED'
            state.logs.append({
                'timestamp': timestamp,
                'level': 'INFO' if action['status'] == 'success' else 'ERROR',
                'message': f"   [{status}] {action['action_name']}: {action.get('message', 'N/A')}"
            })

        # Clear alert after recovery
        state.alert_active = False
        state.current_alert = None

        self.logger.info(f"Recovery actions executed: {len(actions)}")

    def _init_agents(self):
        """Initialize all agents"""
        agents = {
            'monitoring': MonitoringAgent(
                'MonitoringAgent', self.config, self.event_bus,
                get_logger('MonitoringAgent'), self.database
            ),
            'anomaly': AnomalyDetectionAgent(
                'AnomalyDetectionAgent', self.config, self.event_bus,
                get_logger('AnomalyDetectionAgent'), self.database
            ),
            'diagnosis': DiagnosisAgent(
                'DiagnosisAgent', self.config, self.event_bus,
                get_logger('DiagnosisAgent'), self.database
            ),
            'recovery': RecoveryAgent(
                'RecoveryAgent', self.config, self.event_bus,
                get_logger('RecoveryAgent'), self.database
            ),
            'learning': LearningAgent(
                'LearningAgent', self.config, self.event_bus,
                get_logger('LearningAgent'), self.database
            ),
        }

        return agents

    def start(self):
        """Start all agents"""
        self.logger.info("Starting Sentinel AI agents...")

        for name, agent in self.agents.items():
            agent.start()
            state.agents_status[name] = 'running'
            self.logger.info(f"Started {name}")

        state.system_status = "running"

        # Add startup log
        timestamp = now_cst()
        state.logs.append({
            'timestamp': timestamp,
            'level': 'INFO',
            'message': 'Sentinel AI system started'
        })

    def stop(self):
        """Stop all agents"""
        self.logger.info("Stopping Sentinel AI agents...")

        for name, agent in self.agents.items():
            agent.stop()
            state.agents_status[name] = 'stopped'

        self.event_bus.stop()
        state.system_status = "stopped"

    def get_agent_status(self, name):
        """Get agent running status"""
        agent = self.agents.get(name)
        return agent.is_running() if agent else False


def _active_ai_provider() -> str:
    """Return which AI provider the diagnosis agent is currently using."""
    try:
        agent = external_agents.get('diagnosis') or (
            dashboard.agents.get('diagnosis') if dashboard and hasattr(dashboard, 'agents') else None
        )
        if agent is None:
            return 'unknown'
        if getattr(agent, 'groq_client', None):
            return 'groq'
        if getattr(agent, 'ollama_available', False):
            return 'ollama'
        if getattr(agent, 'openai_client', None):
            return 'openai'
        return 'rule_based'
    except Exception:
        return 'unknown'


# Global dashboard instance
dashboard = None

# Optional: external agent registry (set by main.py when run_agents=False)
external_agents = {}


# Flask Routes
@app.route('/')
def index():
    """Render dashboard"""
    return render_template('dashboard.html')


@app.route('/api/status')
def get_status():
    """Get current system status"""
    def _agent_running(name):
        if external_agents:
            agent = external_agents.get(name)
            return agent.is_running() if agent else False
        return dashboard.get_agent_status(name) if dashboard else False

    # LSTM status from anomaly agent
    lstm_status = {}
    try:
        if external_agents:
            anomaly_agent = external_agents.get('anomaly')
            if anomaly_agent and hasattr(anomaly_agent, 'lstm_detector') and anomaly_agent.lstm_detector:
                lstm_status = anomaly_agent.lstm_detector.status
    except Exception:
        pass

    return jsonify({
        'system_status': state.system_status,
        'agents': {
            name: _agent_running(name)
            for name in ['monitoring', 'anomaly', 'diagnosis', 'recovery', 'learning', 'security']
        },
        'alert_active': state.alert_active,
        'lstm': lstm_status,
        'ai_provider': _active_ai_provider(),
    })


@app.route('/api/metrics')
def get_metrics():
    """Get current metrics"""
    return jsonify(state.latest_metrics)


@app.route('/api/logs')
def get_logs():
    """Get recent logs"""
    return jsonify(list(state.logs))


@app.route('/api/anomalies')
def get_anomalies():
    """Get recent anomalies"""
    return jsonify(list(state.anomalies))


@app.route('/api/diagnoses')
def get_diagnoses():
    """Get recent diagnoses"""
    return jsonify(list(state.diagnoses))


@app.route('/api/recoveries')
def get_recoveries():
    """Get recent recoveries"""
    return jsonify(list(state.recoveries))


@app.route('/api/security/threats')
def get_security_threats():
    """Get recent security threats"""
    threats = getattr(state, 'security_threats', [])
    return jsonify(list(threats))


@app.route('/api/alert')
def get_alert():
    """Get current alert"""
    return jsonify(state.current_alert if state.alert_active else None)


@app.route('/api/stats')
def get_stats():
    """Get statistics"""
    return jsonify({
        'total_anomalies': len(state.anomalies),
        'total_diagnoses': len(state.diagnoses),
        'total_recoveries': len(state.recoveries),
        'total_logs': len(state.logs)
    })


@app.route('/api/thresholds')
def get_thresholds():
    """
    Return the LIVE adaptive bounds learned by the anomaly detection agent.

    The anomaly detection agent uses no hardcoded thresholds — all bounds
    are computed at runtime from the rolling data stream via IQR and z-score
    statistics.  This endpoint reads those learned values directly from the
    agent's AdaptiveMetricBaseline instances so the dashboard always shows
    what the detector is actually using.

    Falls back to config reference values during warm-up (first ~2.5 minutes).
    """
    config = get_config()
    # Reference values for display fallback only — NOT used for detection
    ref = {
        'cpu':     config.get('monitoring.metrics.cpu.threshold_percent', 80),
        'memory':  config.get('monitoring.metrics.memory.threshold_percent', 85),
        'disk':    config.get('monitoring.metrics.disk.threshold_percent', 90),
        'network': config.get('monitoring.metrics.network.max_packet_loss_percent', 5),
    }

    # Map dashboard key → flattened metric name used by the anomaly agent
    metric_map = {
        'cpu':    'cpu.cpu_percent',
        'memory': 'memory.memory_percent',
        'disk':   'disk.disk_percent',
    }

    # Try to pull live bounds from the anomaly agent's baselines
    try:
        anomaly_agent = (
            external_agents.get('anomaly')
            or (dashboard.agents.get('anomaly') if dashboard and hasattr(dashboard, 'agents') else None)
        )

        if anomaly_agent and hasattr(anomaly_agent, '_baselines'):
            result = {}
            baseline_info = {}

            for key, flat_name in metric_map.items():
                baseline = anomaly_agent._baselines.get(flat_name)
                if baseline and baseline.ready:
                    stats = baseline.stats()
                    if stats:
                        # Show the IQR mild-fence as the "adaptive threshold" line
                        result[key] = round(stats['upper_mild'], 1)
                        baseline_info[key] = {
                            'mean':          round(stats['mean'], 1),
                            'std':           round(stats['std'], 2),
                            'upper_mild':    round(stats['upper_mild'], 1),
                            'upper_extreme': round(stats['upper_extreme'], 1),
                            'iqr':           round(stats['iqr'], 2),
                            'warmup_done':   True,
                        }
                    else:
                        result[key] = ref[key]
                        baseline_info[key] = {'warmup_done': False}
                else:
                    result[key] = ref[key]
                    baseline_info[key] = {'warmup_done': False}

            result['network'] = ref['network']
            result['adaptive'] = True
            result['baselines'] = baseline_info
            return jsonify(result)

    except Exception as e:
        pass  # fall through to config fallback

    return jsonify({**ref, 'adaptive': False, 'baselines': {}})


@app.route('/api/incidents')
def get_incidents():
    """Return recent incident timeline with diagnosis and recovery details"""
    if not dashboard:
        return jsonify([])
    try:
        db = dashboard.database
        rows = db.get_recent_incidents(limit=20)
        result = []
        for row in rows:
            import json as _json
            actions_raw = row.get('recovery_actions') or '[]'
            try:
                actions = _json.loads(actions_raw)
            except Exception:
                actions = []

            # Determine overall status
            # "skipped" means cooldown/not-applicable — not a failure
            if any(a.get('status') == 'success' for a in actions):
                status = 'resolved'
            elif any(a.get('status') == 'failed' for a in actions):
                status = 'failed'
            elif all(a.get('status') == 'skipped' for a in actions) and actions:
                status = 'attempted'   # all skipped = cooldown active, not a failure
            elif actions:
                status = 'attempted'
            else:
                status = 'detected'

            # Parse metrics JSON
            metrics_raw = row.get('metrics') or '{}'
            try:
                metrics = _json.loads(metrics_raw) if isinstance(metrics_raw, str) else (metrics_raw or {})
            except Exception:
                metrics = {}

            result.append({
                'incident_id':   row['incident_id'][:8],
                'timestamp':     row['timestamp'],
                'anomaly_type':  row['anomaly_type'],
                'severity':      row['severity'],
                'diagnosis':     row.get('diagnosis') or 'Pending diagnosis',
                'root_cause':    row.get('root_cause') or 'Unknown',
                'actions':       actions,
                'status':        status,
                'metrics':       metrics,
                'resolution_time': row.get('resolution_time_seconds'),
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/history')
def get_history():
    """Get rolling metric history for live graphs"""
    return jsonify({
        'timestamps':     list(state.timestamps),
        'cpu':            list(state.cpu_history),
        'memory':         list(state.memory_history),
        'disk':           list(state.disk_history),
        'network':        list(state.network_latency_history),
        'power_voltage':  list(state.power_voltage_history),
        'power_quality':  list(state.power_quality_history),
    })


@app.route('/api/stream')
def stream():
    """Server-sent events for real-time updates"""
    def event_stream():
        last_log_count     = 0
        last_anomaly_count = 0
        last_threat_count  = 0

        while True:
            # Check for new logs
            if len(state.logs) > last_log_count:
                last_log_count = len(state.logs)
                yield f"data: {json.dumps({'type': 'log', 'data': list(state.logs)[-1]})}\n\n"

            # Check for new anomalies
            if len(state.anomalies) > last_anomaly_count:
                last_anomaly_count = len(state.anomalies)
                yield f"data: {json.dumps({'type': 'anomaly', 'data': list(state.anomalies)[-1]})}\n\n"

            # Check for new security threats
            threats = getattr(state, 'security_threats', [])
            if len(threats) > last_threat_count:
                last_threat_count = len(threats)
                yield f"data: {json.dumps({'type': 'security', 'data': threats[-1]})}\n\n"

            # Send heartbeat
            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now(CST).isoformat()})}\n\n"

            time.sleep(1)

    return Response(event_stream(), mimetype='text/event-stream')


@app.route('/api/simulate/start/<scenario>', methods=['POST'])
def simulate_start(scenario):
    """Start a controlled instability simulation."""
    try:
        data = request.get_json(silent=True) or {}
        duration = float(data.get('duration', 60))

        # Power sag is handled by the monitoring agent directly (no subprocess needed)
        if scenario == 'power_sag':
            monitoring_agent = external_agents.get('monitoring')
            if monitoring_agent and hasattr(monitoring_agent, 'trigger_power_event'):
                monitoring_agent.trigger_power_event(sag_volts=0.75, duration_seconds=duration)
                ts = now_cst()
                state.logs.append({
                    'timestamp': ts,
                    'level': 'WARNING',
                    'message': f"SIM START: Power sag simulation — voltage dropping ~0.75 V for {int(duration)}s"
                })
                return jsonify({'success': True, 'message': f'Power sag started for {int(duration)}s'})
            return jsonify({'success': False, 'error': 'Monitoring agent not available'})

        from simulation.instability_runner import InstabilityRunner
        runner = InstabilityRunner.get_instance()
        result = runner.start(scenario, duration=duration)

        if result.get('success'):
            ts = now_cst()
            state.logs.append({
                'timestamp': ts,
                'level': 'WARNING',
                'message': f"SIM START: {result.get('message', scenario)}"
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulate/stop', methods=['POST'])
def simulate_stop():
    """Stop a specific simulation or all simulations."""
    try:
        from simulation.instability_runner import InstabilityRunner
        data = request.get_json(silent=True) or {}
        scenario = data.get('scenario')
        runner = InstabilityRunner.get_instance()
        result = runner.stop(scenario) if scenario else runner.stop_all()

        ts = now_cst()
        state.logs.append({
            'timestamp': ts,
            'level': 'INFO',
            'message': f"SIM STOP: {result.get('message', str(result))}"
        })
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulate/status')
def simulate_status():
    """Get status of all active simulations."""
    try:
        from simulation.instability_runner import InstabilityRunner
        runner = InstabilityRunner.get_instance()
        return jsonify(runner.get_status())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Multi-Device API — remote client registration & metric ingestion
# ─────────────────────────────────────────────────────────────────────────────

# Global remote device manager (initialized by main.py or lazily here)
remote_device_manager = None


def _get_remote_manager():
    """Return (or lazily create) the RemoteDeviceManager."""
    global remote_device_manager
    if remote_device_manager is None:
        from agents.monitoring.remote_device_manager import RemoteDeviceManager
        from core.event_bus import get_event_bus
        from core.logging import get_logger
        eb = get_event_bus()
        remote_device_manager = RemoteDeviceManager(eb, get_logger('RemoteDeviceManager'))
        remote_device_manager.start()
    return remote_device_manager


@app.route('/api/devices/register', methods=['POST'])
def register_device():
    """Called by sentinel_client.py when a remote machine connects."""
    try:
        data      = request.get_json(silent=True) or {}
        device_id = data.get('device_id')
        if not device_id:
            return jsonify({'error': 'device_id required'}), 400
        mgr = _get_remote_manager()
        mgr.register(device_id, data)
        ts = now_cst()
        state.logs.append({
            'timestamp': ts,
            'level':     'INFO',
            'message':   f"Remote device connected: {device_id} "
                         f"({data.get('hostname', '?')} / {data.get('platform', '?')})",
        })
        return jsonify({'status': 'registered', 'device_id': device_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/metrics/push', methods=['POST'])
def push_metrics():
    """Accept a metric payload from a remote sentinel_client.py instance."""
    try:
        data      = request.get_json(silent=True) or {}
        device_id = data.get('device_id')
        timestamp = data.get('timestamp', datetime.utcnow().isoformat())
        metrics   = data.get('metrics', {})
        if not device_id or not metrics:
            return jsonify({'error': 'device_id and metrics required'}), 400
        mgr = _get_remote_manager()
        ok  = mgr.push_metrics(device_id, timestamp, metrics)
        return jsonify({'status': 'ok' if ok else 'error', 'device_id': device_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices')
def list_devices():
    """Return all connected (and recently seen) remote devices."""
    try:
        mgr = _get_remote_manager()
        return jsonify(mgr.get_all_devices())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>/commands')
def get_device_commands(device_id):
    """Remote client polls this to pick up queued recovery commands."""
    try:
        mgr   = _get_remote_manager()
        cmds  = mgr.pop_commands(device_id)
        return jsonify({'commands': cmds})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>/command_results', methods=['POST'])
def post_command_results(device_id):
    """Remote client posts execution results back to the hub."""
    try:
        data = request.get_json(force=True) or {}
        results = data.get('results', [])
        app.logger.info(f"Remote recovery results from {device_id}: {results}")
        return jsonify({'status': 'ok', 'received': len(results)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>/metrics')
def get_device_metrics(device_id):
    """Return the latest metrics snapshot for a specific remote device."""
    try:
        mgr = _get_remote_manager()
        m   = mgr.get_device_metrics(device_id)
        if m is None:
            return jsonify({'error': f'Device {device_id!r} not found'}), 404
        return jsonify(m)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def run_dashboard(host='0.0.0.0', port=5001, debug=False, run_agents=True):
    """
    Run the dashboard.

    Args:
        host: Host to bind to
        port: Port to listen on
        debug: Enable debug mode
        run_agents: If False, dashboard is display-only (agents run elsewhere)
    """
    global dashboard

    # Initialize dashboard (agents optional)
    dashboard = SentinelDashboard(run_agents=run_agents)

    if run_agents:
        # Start agents in background thread
        agent_thread = threading.Thread(target=dashboard.start, daemon=True)
        agent_thread.start()
    else:
        state.system_status = "running"

    # Wait for agents to start
    time.sleep(2)

    # Run Flask app
    print(f"\n{'='*80}")
    print(f"Sentinel AI Dashboard Running")
    print(f"{'='*80}")
    print(f"\nOpen your browser and navigate to:")
    print(f"\n  http://localhost:{port}")
    print(f"\nPress Ctrl+C to stop\n")

    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\nStopping dashboard...")
    finally:
        if dashboard:
            dashboard.stop()


if __name__ == '__main__':
    run_dashboard()
