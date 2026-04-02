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
        self.cpu_history = deque(maxlen=60)
        self.memory_history = deque(maxlen=60)
        self.disk_history = deque(maxlen=60)
        self.network_latency_history = deque(maxlen=60)
        self.power_voltage_history = deque(maxlen=60)
        self.power_quality_history = deque(maxlen=60)
        self.timestamps = deque(maxlen=60)
        self.device_anomalies: dict = {}
        self.device_diagnoses: dict = {}
        self.device_recoveries: dict = {}
        self.device_logs: dict = {}
        self.device_history: dict = {}

    def _device_history(self, device_id: str) -> dict:
        if device_id not in self.device_history:
            self.device_history[device_id] = {
                'cpu': deque(maxlen=60), 'memory': deque(maxlen=60),
                'disk': deque(maxlen=60), 'net': deque(maxlen=60),
                'timestamps': deque(maxlen=60),
            }
        return self.device_history[device_id]

    def _device_deque(self, store: dict, device_id: str, maxlen: int) -> deque:
        if device_id not in store:
            store[device_id] = deque(maxlen=maxlen)
        return store[device_id]


state = DashboardState()


class SentinelDashboard:
    """
    Dashboard backend that subscribes to Sentinel AI events for display.
    When run_agents=True it also starts its own agent set (standalone mode).
    When run_agents=False (embedded in main.py) it is display-only.
    """

    def __init__(self, run_agents: bool = True):
        """Initialize dashboard"""
        self.config = get_config()
        self.local_device_id = self.config.device_id
        self.config.set('aws.enabled', False)

        setup_logging(self.config)
        self.logger = get_logger('Dashboard')

        self.event_bus = get_event_bus(self.config)
        self.database = get_database(self.config)

        self._setup_event_subscriptions()

        self._run_agents = run_agents
        self.agents = self._init_agents() if run_agents else {}

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
        metrics = event.data.get('metrics', {})
        device_id = event.data.get('device_id') or self.local_device_id
        timestamp = now_cst()

        cpu = metrics.get('cpu', {}).get('cpu_percent', 0)
        mem = metrics.get('memory', {}).get('memory_percent', 0)
        disk = metrics.get('disk', {}).get('disk_percent', 0)
        net = metrics.get('network',{}).get('ping_latency_ms',0)

        dh = state._device_history(device_id)
        dh['cpu'].append(round(cpu, 1))
        dh['memory'].append(round(mem, 1))
        dh['disk'].append(round(disk, 1))
        dh['net'].append(round(net, 1))
        dh['timestamps'].append(timestamp)

        dl = state._device_deque(state.device_logs, device_id, 200)
        dl.append({'timestamp': timestamp, 'level': 'INFO',
                   'message': f'Metrics: CPU={cpu:.1f}% MEM={mem:.1f}% DISK={disk:.1f}%'})

        if device_id == self.local_device_id:
            state.latest_metrics = metrics
            power = metrics.get('power', {})
            pwr_voltage = power.get('power_voltage_v', 0)
            pwr_quality = power.get('power_quality', 100)
            state.cpu_history.append(round(cpu, 1))
            state.memory_history.append(round(mem, 1))
            state.disk_history.append(round(disk, 1))
            state.network_latency_history.append(round(net, 1))
            state.power_voltage_history.append(round(pwr_voltage, 3))
            state.power_quality_history.append(round(pwr_quality, 1))
            state.timestamps.append(timestamp)
            state.logs.append({'timestamp': timestamp, 'level': 'INFO',
                                'message': f'Metrics collected: CPU={cpu:.1f}%, Memory={mem:.1f}%'})

    def _on_anomaly(self, event):
        """Handle anomaly event"""
        anomaly = event.data.get('anomaly', {})
        device_id = event.data.get('device_id') or self.local_device_id
        ts_str = datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')
        entry = {'timestamp': ts_str, 'anomaly': anomaly, 'device_id': device_id}

        state.anomalies.append(entry)
        state._device_deque(state.device_anomalies, device_id, 50).append(entry)

        state.alert_active = True
        state.current_alert = {
            'type': 'anomaly',
            'severity': anomaly.get('severity', 'unknown'),
            'message': f"[{device_id}] Anomaly: {anomaly.get('metric_name')} - {anomaly.get('type')}",
            'details': anomaly,
        }

        timestamp = now_cst()
        msg = f"[{device_id}] ANOMALY: {anomaly.get('metric_name')} = {anomaly.get('value', 0):.2f} (severity: {anomaly.get('severity')})"
        state.logs.append({'timestamp': timestamp, 'level': 'WARNING', 'message': msg})
        state._device_deque(state.device_logs, device_id, 100).append(
            {'timestamp': timestamp, 'level': 'WARNING', 'message': msg})
        self.logger.warning(f"Anomaly detected: {anomaly}")

    def _on_diagnosis(self, event):
        """Handle diagnosis event"""
        diagnosis = event.data.get('diagnosis', {})
        device_id = event.data.get('device_id') or self.local_device_id
        ts_str = datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')
        entry = {'timestamp': ts_str, 'diagnosis': diagnosis, 'device_id': device_id}

        state.diagnoses.append(entry)
        state._device_deque(state.device_diagnoses, device_id, 50).append(entry)

        if state.alert_active:
            state.current_alert['diagnosis'] = diagnosis.get('diagnosis')
            state.current_alert['root_cause'] = diagnosis.get('root_cause')
            state.current_alert['actions'] = diagnosis.get('recommended_actions', [])

        timestamp = now_cst()
        for msg in [
            f"[{device_id}] DIAGNOSIS: {diagnosis.get('diagnosis', 'N/A')}",
            f"[{device_id}] Root Cause: {diagnosis.get('root_cause', 'Unknown')}",
            f"[{device_id}] Actions: {', '.join(diagnosis.get('recommended_actions', []))}",
        ]:
            state.logs.append({'timestamp': timestamp, 'level': 'WARNING', 'message': msg})
            state._device_deque(state.device_logs, device_id, 100).append(
                {'timestamp': timestamp, 'level': 'WARNING', 'message': msg})
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
        state.security_threats = getattr(state, 'security_threats', [])
        state.security_threats.append({
            'timestamp': timestamp,
            'threat': threat
        })
        if len(state.security_threats) > 50:
            state.security_threats = state.security_threats[-50:]

    def _on_recovery(self, event):
        """Handle recovery event"""
        actions = event.data.get('actions', [])
        device_id = event.data.get('device_id') or self.local_device_id
        ts_str = datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')
        entry = {'timestamp': ts_str, 'actions': actions, 'device_id': device_id}

        state.recoveries.append(entry)
        state._device_deque(state.device_recoveries, device_id, 50).append(entry)

        timestamp = now_cst()
        msgs = [f"[{device_id}] RECOVERY: Executing {len(actions)} action(s)"]
        for action in actions:
            status = 'OK' if action.get('status') == 'success' else action.get('status','?').upper()
            msgs.append(f"[{device_id}] [{status}] {action.get('action_name','?')}: {action.get('message','N/A')}")

        for msg in msgs:
            lvl = 'INFO'
            state.logs.append({'timestamp': timestamp, 'level': lvl, 'message': msg})
            state._device_deque(state.device_logs, device_id, 100).append(
                {'timestamp': timestamp, 'level': lvl, 'message': msg})

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


dashboard = None

external_agents = {}


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
    statistics. This endpoint reads those learned values directly from the
    agent's AdaptiveMetricBaseline instances so the dashboard always shows
    what the detector is actually using.

    Falls back to config reference values during warm-up (first ~2.5 minutes).
    """
    config = get_config()
    ref = {
        'cpu': config.get('monitoring.metrics.cpu.threshold_percent', 80),
        'memory': config.get('monitoring.metrics.memory.threshold_percent', 85),
        'disk': config.get('monitoring.metrics.disk.threshold_percent', 90),
        'network': config.get('monitoring.metrics.network.max_packet_loss_percent', 5),
    }

    metric_map = {
        'cpu': 'cpu.cpu_percent',
        'memory': 'memory.memory_percent',
        'disk': 'disk.disk_percent',
    }

    # Support ?device_id= for remote devices; default to local device
    device_id = request.args.get('device_id') or get_config().device_id

    try:
        anomaly_agent = (
            external_agents.get('anomaly')
            or (dashboard.agents.get('anomaly') if dashboard and hasattr(dashboard, 'agents') else None)
        )

        if anomaly_agent and hasattr(anomaly_agent, '_baselines'):
            result = {}
            baseline_info = {}

            for key, flat_name in metric_map.items():
                # Baselines are keyed by (device_id, metric_name) tuple
                baseline = anomaly_agent._baselines.get((device_id, flat_name))
                if baseline and baseline.ready:
                    stats = baseline.stats()
                    if stats:
                        result[key] = round(stats['upper_mild'], 1)
                        baseline_info[key] = {
                            'mean': round(stats['mean'], 1),
                            'std': round(stats['std'], 2),
                            'upper_mild': round(stats['upper_mild'], 1),
                            'upper_extreme': round(stats['upper_extreme'], 1),
                            'iqr': round(stats['iqr'], 2),
                            'warmup_done': True,
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
        pass

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

            if any(a.get('status') == 'success' for a in actions):
                status = 'resolved'
            elif any(a.get('status') == 'failed' for a in actions):
                status = 'failed'
            elif all(a.get('status') == 'skipped' for a in actions) and actions:
                status = 'attempted'
            elif actions:
                status = 'attempted'
            else:
                status = 'detected'

            metrics_raw = row.get('metrics') or '{}'
            try:
                metrics = _json.loads(metrics_raw) if isinstance(metrics_raw, str) else (metrics_raw or {})
            except Exception:
                metrics = {}

            result.append({
                'incident_id': row['incident_id'][:8],
                'timestamp': row['timestamp'],
                'anomaly_type': row['anomaly_type'],
                'severity': row['severity'],
                'diagnosis': row.get('diagnosis') or 'Pending diagnosis',
                'root_cause': row.get('root_cause') or 'Unknown',
                'actions': actions,
                'status': status,
                'metrics': metrics,
                'resolution_time': row.get('resolution_time_seconds'),
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/history')
def get_history():
    """Get rolling metric history for live graphs"""
    return jsonify({
        'timestamps': list(state.timestamps),
        'cpu': list(state.cpu_history),
        'memory': list(state.memory_history),
        'disk': list(state.disk_history),
        'network': list(state.network_latency_history),
        'power_voltage': list(state.power_voltage_history),
        'power_quality': list(state.power_quality_history),
    })


@app.route('/api/stream')
def stream():
    """Server-sent events for real-time updates"""
    def event_stream():
        last_log_count = 0
        last_anomaly_count = 0
        last_threat_count = 0

        while True:
            if len(state.logs) > last_log_count:
                last_log_count = len(state.logs)
                yield f"data: {json.dumps({'type': 'log', 'data': list(state.logs)[-1]})}\n\n"

            if len(state.anomalies) > last_anomaly_count:
                last_anomaly_count = len(state.anomalies)
                yield f"data: {json.dumps({'type': 'anomaly', 'data': list(state.anomalies)[-1]})}\n\n"

            threats = getattr(state, 'security_threats', [])
            if len(threats) > last_threat_count:
                last_threat_count = len(threats)
                yield f"data: {json.dumps({'type': 'security', 'data': threats[-1]})}\n\n"

            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now(CST).isoformat()})}\n\n"

            time.sleep(1)

    return Response(event_stream(), mimetype='text/event-stream')


@app.route('/api/simulate/start/<scenario>', methods=['POST'])
def simulate_start(scenario):
    """Start a controlled instability simulation."""
    try:
        data = request.get_json(silent=True) or {}
        duration = float(data.get('duration', 60))

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


remote_device_manager = None


def _get_remote_manager():
    """Return (or lazily create) the RemoteDeviceManager.
    When launched from main.py, app.remote_device_manager is injected — use that
    so the RecoveryAgent and the Flask endpoints share the same instance.
    """
    global remote_device_manager
    if remote_device_manager is None:
        # main.py injects its instance via _dash_app.remote_device_manager
        injected = getattr(app, 'remote_device_manager', None)
        if injected is not None:
            remote_device_manager = injected
        else:
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
        data = request.get_json(silent=True) or {}
        device_id = data.get('device_id')
        if not device_id:
            return jsonify({'error': 'device_id required'}), 400
        mgr = _get_remote_manager()
        data['_remote_addr'] = request.remote_addr
        mgr.register(device_id, data)
        ts = now_cst()
        state.logs.append({
            'timestamp': ts,
            'level': 'INFO',
            'message': f"Remote device connected: {device_id} "
                         f"({data.get('hostname', '?')} / {data.get('platform', '?')})",
        })
        return jsonify({'status': 'registered', 'device_id': device_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/metrics/push', methods=['POST'])
def push_metrics():
    """Accept a metric payload from a remote sentinel_client.py instance."""
    try:
        data = request.get_json(silent=True) or {}
        device_id = data.get('device_id')
        timestamp = data.get('timestamp', datetime.utcnow().isoformat())
        metrics = data.get('metrics', {})
        if not device_id or not metrics:
            return jsonify({'error': 'device_id and metrics required'}), 400
        mgr = _get_remote_manager()
        ok = mgr.push_metrics(device_id, timestamp, metrics)
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


@app.route('/device/<device_id>')
def device_dashboard(device_id):
    """Per-device full dashboard page."""
    return render_template('device_dashboard.html', device_id=device_id)


@app.route('/api/devices/<device_id>/history')
def get_device_history(device_id):
    """Return rolling chart history for a specific device."""
    dh = state.device_history.get(device_id)
    if not dh:
        return jsonify({'cpu': [], 'memory': [], 'disk': [], 'net': [], 'timestamps': []})
    return jsonify({k: list(v) for k, v in dh.items()})


@app.route('/api/devices/<device_id>/anomalies')
def get_device_anomalies(device_id):
    return jsonify(list(state.device_anomalies.get(device_id, [])))


@app.route('/api/devices/<device_id>/diagnoses')
def get_device_diagnoses(device_id):
    return jsonify(list(state.device_diagnoses.get(device_id, [])))


@app.route('/api/devices/<device_id>/recoveries')
def get_device_recoveries(device_id):
    return jsonify(list(state.device_recoveries.get(device_id, [])))


@app.route('/api/devices/<device_id>/logs')
def get_device_logs(device_id):
    return jsonify(list(state.device_logs.get(device_id, [])))


@app.route('/api/devices/<device_id>/incidents')
def get_device_incidents(device_id):
    """Return incident timeline for a specific device from DB."""
    if not dashboard and not external_agents:
        return jsonify([])
    try:
        import json as _json
        db = (dashboard.database if dashboard else
              next(iter(external_agents.values())).database if external_agents else None)
        if not db:
            return jsonify([])
        rows = db.get_recent_incidents(limit=20, device_id=device_id)
        result = []
        for row in rows:
            try:
                actions = _json.loads(row.get('recovery_actions') or '[]')
            except Exception:
                actions = []
            if any(a.get('status') == 'success' for a in actions):
                status = 'resolved'
            elif any(a.get('status') == 'failed' for a in actions):
                status = 'failed'
            elif actions:
                status = 'attempted'
            else:
                status = 'detected'
            result.append({
                'incident_id': row['incident_id'][:8],
                'timestamp': row['timestamp'],
                'anomaly_type': row['anomaly_type'],
                'severity': row['severity'],
                'diagnosis': row.get('diagnosis') or 'Pending',
                'root_cause': row.get('root_cause') or 'Unknown',
                'actions': actions,
                'status': status,
            })
        return jsonify(result)
    except Exception as e:
        return jsonify([])


@app.route('/api/devices/<device_id>/queue_command', methods=['POST'])
def queue_device_command(device_id):
    """Send a command to a remote device — direct push first, queue fallback."""
    import uuid as _uuid
    import urllib.request as _ur
    import urllib.error as _ue
    try:
        mgr = _get_remote_manager()
        data = request.get_json(force=True) or {}
        action = data.get('action')
        if not action:
            return jsonify({'error': 'action required'}), 400
        cmd = {'action_id': str(_uuid.uuid4()), 'action': action,
               'issued_at': datetime.now().isoformat()}

        device = mgr.get_device(device_id)
        cmd_port = (device or {}).get('cmd_port', 5002)
        client_ip = (device or {}).get('_remote_addr')

        if client_ip and cmd_port:
            try:
                payload = json.dumps(cmd).encode()
                req = _ur.Request(
                    'http://{}:{}/command'.format(client_ip, cmd_port),
                    data=payload,
                    headers={'Content-Type': 'application/json'},
                )
                with _ur.urlopen(req, timeout=1) as resp:
                    resp.read()
                return jsonify({'status': 'sent', 'action': action, 'method': 'direct'})
            except Exception:
                pass

        mgr.queue_command(device_id, cmd)
        return jsonify({'status': 'queued', 'action': action, 'method': 'queue'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>/commands')
def get_device_commands(device_id):
    """Remote client polls this to pick up queued recovery commands."""
    try:
        mgr = _get_remote_manager()
        cmds = mgr.pop_commands(device_id)
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
        ts = now_cst()
        for r in results:
            action  = r.get('action', r.get('action_name', '?'))
            status  = r.get('status', '?')
            message = r.get('message', '')
            level   = 'INFO' if status in ('success', 'queued_remote') else 'WARNING'
            msg     = f"[REMOTE ACTION] {action} → {status}: {message}"
            state._device_deque(state.device_logs, device_id, 200).append(
                {'timestamp': ts, 'level': level, 'message': msg})
            state.logs.append({'timestamp': ts, 'level': level,
                                'message': f"[{device_id}] {msg}"})
        return jsonify({'status': 'ok', 'received': len(results)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>/metrics')
def get_device_metrics(device_id):
    """Return the latest metrics snapshot for a specific remote device."""
    try:
        mgr = _get_remote_manager()
        m = mgr.get_device_metrics(device_id)
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

    dashboard = SentinelDashboard(run_agents=run_agents)

    if run_agents:
        agent_thread = threading.Thread(target=dashboard.start, daemon=True)
        agent_thread.start()
    else:
        state.system_status = "running"

    time.sleep(2)

    print(f"\n{'='*80}")
    print(f"Sentinel AI Dashboard Running")
    print(f"{'='*80}")
    print(f"\nOpen your browser and navigate to:")
    print(f"\n http://localhost:{port}")
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
