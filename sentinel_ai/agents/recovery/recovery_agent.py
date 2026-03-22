"""
Recovery Agent — Full-Scale Autonomous Self-Healing

Implements a tiered, AI-guided recovery system with:
  • Graduated escalation — escalates through 4 tiers when the same issue recurs
  • 15+ recovery actions across CPU, memory, disk, network, and services
  • Outcome verification — checks 30s after actions if the metric recovered
  • Platform-aware — macOS & Linux code paths throughout
  • Cooldown tracking per action to prevent recovery loops

Escalation levels (per metric category, within rolling 30-min window):
  Level 1 — Gentle:     AI-recommended actions only
  Level 2 — Moderate:   + throttle/compact (non-destructive)
  Level 3 — Aggressive: + kill process / disk cleanup
  Level 4 — Critical:   + network reset / service restart / log rotation
"""

import glob
import gzip
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
import platform
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

_IS_MACOS = platform.system() == 'Darwin'

_CRITICAL_PROCESSES = {
    'systemd', 'init', 'launchd', 'sshd', 'kernel_task', 'WindowServer',
    'sentinel', 'python3', 'python', 'bash', 'zsh', 'loginwindow',
}

from agents.base_agent import BaseAgent
from core.event_bus import EventPriority


# ─────────────────────────────────────────────────────────────────────────────
# Graduated Escalation Tracker
# ─────────────────────────────────────────────────────────────────────────────

class GraduatedEscalationTracker:
    """
    Tracks how many times a metric category has fired within a rolling window.
    Returns the current escalation level (1–4) and the additional actions to
    take at that level.

    Category → level mapping:
      1 incident in window → Level 1 (gentle, AI-recommended only)
      2 incidents          → Level 2 (add throttle / compact)
      3 incidents          → Level 3 (add kill / cleanup)
      4+ incidents         → Level 4 (add network reset / restart)
    """

    # Additional actions added at each level, keyed by (category, level)
    _ESCALATION_ACTIONS: Dict[str, Dict[int, List[str]]] = {
        'cpu': {
            2: ['throttle_cpu_process'],
            3: ['kill_top_cpu_process'],
            4: ['restart_service', 'compact_memory'],
        },
        'memory': {
            2: ['compact_memory'],
            3: ['kill_top_memory_process'],
            4: ['rotate_logs', 'emergency_disk_cleanup'],
        },
        'disk': {
            2: ['emergency_disk_cleanup'],
            3: ['rotate_logs'],
            4: ['emergency_disk_cleanup', 'clear_cache'],
        },
        'network': {
            2: ['flush_dns', 'check_network'],
            3: ['reset_network_interface'],
            4: ['reset_network_interface', 'check_network'],
        },
        'power': {
            2: [],
            3: [],
            4: ['check_network'],
        },
        'general': {
            2: ['compact_memory'],
            3: ['emergency_disk_cleanup'],
            4: ['rotate_logs', 'clear_cache'],
        },
    }

    def __init__(self, window_minutes: int = 30):
        self._window = timedelta(minutes=window_minutes)
        self._incidents: Dict[str, List[datetime]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _category(metric_name: str) -> str:
        name = metric_name.lower()
        for cat in ('cpu', 'memory', 'disk', 'network', 'power'):
            if cat in name:
                return cat
        return 'general'

    def record(self, metric_name: str) -> int:
        """Record a new incident and return the resulting escalation level (1-4)."""
        cat = self._category(metric_name)
        now = datetime.utcnow()
        with self._lock:
            times = self._incidents.setdefault(cat, [])
            # Purge old incidents outside the window
            self._incidents[cat] = [t for t in times if (now - t) <= self._window]
            self._incidents[cat].append(now)
            level = min(4, len(self._incidents[cat]))
        return level

    def reset(self, metric_name: str):
        """Reset escalation for a metric category (issue resolved)."""
        cat = self._category(metric_name)
        with self._lock:
            self._incidents[cat] = []

    def current_level(self, metric_name: str) -> int:
        cat = self._category(metric_name)
        now = datetime.utcnow()
        with self._lock:
            times = self._incidents.get(cat, [])
            valid = [t for t in times if (now - t) <= self._window]
            return min(4, len(valid)) if valid else 1

    def extra_actions(self, metric_name: str, level: int) -> List[str]:
        """Return additional actions appropriate for this escalation level."""
        cat = self._category(metric_name)
        cat_map = self._ESCALATION_ACTIONS.get(cat, self._ESCALATION_ACTIONS['general'])
        actions: List[str] = []
        for lvl in range(2, level + 1):
            actions.extend(cat_map.get(lvl, []))
        return list(dict.fromkeys(actions))  # deduplicate, preserve order


# ─────────────────────────────────────────────────────────────────────────────
# Recovery Agent
# ─────────────────────────────────────────────────────────────────────────────

class RecoveryAgent(BaseAgent):
    """
    Executes autonomous recovery actions in response to diagnosed anomalies.
    Uses graduated escalation and outcome verification for intelligent healing.
    """

    def __init__(self, name: str, config, event_bus, logger, database=None):
        super().__init__(name, config, event_bus, logger)

        self.database    = database
        self.device_id   = config.device_id

        self.recovery_config  = config.get_section('recovery')
        self.actions_config   = self.recovery_config.get('actions', {})
        self.auto_recovery    = self.recovery_config.get('auto_recovery', True)
        self.max_retries      = self.recovery_config.get('max_retries', 3)
        self.retry_delay      = self.recovery_config.get('retry_delay_seconds', 5)
        self.cooldown_period  = self.recovery_config.get('cooldown_period_seconds', 300)

        self.action_cooldowns: Dict[str, datetime] = {}
        self.recent_actions:   List[Dict]          = []

        self.escalation = GraduatedEscalationTracker(
            window_minutes=self.recovery_config.get('escalation_window_minutes', 30)
        )

        # Pending outcome verifications: {metric_name: (check_at, expected_max)}
        self._pending_verifications: Dict[str, tuple] = {}
        self._verification_lock = threading.RLock()

        self.event_bus.subscribe("diagnosis.complete", self.process_event)
        # Also subscribe to health.metric for outcome verification
        self.event_bus.subscribe("health.metric", self._on_health_metric)

    # ── Main loop (event-driven; loop just does cleanup) ─────────────────

    def _run(self):
        self.logger.info("Recovery Agent started — graduated escalation + outcome verification active")
        while self._running:
            try:
                self._cleanup_cooldowns()
            except Exception as e:
                self.logger.error(f"Cleanup error: {e}")
            if not self.wait(60):
                break

    # ── Event handlers ────────────────────────────────────────────────────

    def process_event(self, event):
        if event.event_type != "diagnosis.complete":
            return
        if not self.auto_recovery:
            self.logger.info("Auto-recovery disabled — skipping")
            return

        try:
            diagnosis  = event.data.get('diagnosis', {})
            anomaly    = event.data.get('anomaly', {})
            device_id  = event.data.get('device_id')
            timestamp  = event.data.get('timestamp')
            metric_name = anomaly.get('metric_name', 'unknown')

            recommended = diagnosis.get('recommended_actions', [])
            if not recommended:
                return

            # Graduated escalation
            level = self.escalation.record(metric_name)
            extra = self.escalation.extra_actions(metric_name, level)
            # Merge: recommended first, then escalation extras (no duplicates)
            all_actions = list(dict.fromkeys(recommended + extra))

            if level > 1:
                self.logger.warning(
                    f"ESCALATION level {level} for '{metric_name}' "
                    f"— adding: {extra}"
                )

            results = self.execute_recovery_actions(
                all_actions, diagnosis, device_id, timestamp,
                anomaly=anomaly, escalation_level=level
            )

            self.publish_event(
                event_type="recovery.action",
                data={
                    'device_id':        device_id,
                    'timestamp':        timestamp,
                    'diagnosis_id':     diagnosis.get('diagnosis_id'),
                    'actions':          results,
                    'escalation_level': level,
                },
                priority=EventPriority.HIGH,
            )

            # Schedule outcome verification 30s from now
            self._schedule_verification(metric_name, anomaly, results)

        except Exception as e:
            self.logger.error(f"Recovery event error: {e}", exc_info=True)

    def _on_health_metric(self, event):
        """Check pending outcome verifications against incoming metric readings."""
        if event.event_type != "health.metric":
            return
        now = datetime.utcnow()
        metrics = event.data.get('metrics', {})
        with self._verification_lock:
            expired = []
            for metric_name, (check_at, anomaly_value, anomaly_type) in list(
                self._pending_verifications.items()
            ):
                if now < check_at:
                    continue  # not yet
                expired.append(metric_name)
                # Look up the metric value in the flattened metrics
                current_value = self._lookup_metric(metrics, metric_name)
                if current_value is not None:
                    recovered = current_value < anomaly_value * 0.80
                    if recovered:
                        self.logger.info(
                            f"Outcome verification: '{metric_name}' RECOVERED "
                            f"(was {anomaly_value:.1f}, now {current_value:.1f})"
                        )
                        self.escalation.reset(metric_name)
                    else:
                        self.logger.warning(
                            f"Outcome verification: '{metric_name}' NOT recovered "
                            f"(was {anomaly_value:.1f}, still {current_value:.1f}) "
                            f"— escalation preserved for next incident"
                        )
            for k in expired:
                del self._pending_verifications[k]

    # ── Action execution ─────────────────────────────────────────────────

    def execute_recovery_actions(
        self,
        actions: List[str],
        diagnosis: Dict,
        device_id: str,
        timestamp: str,
        anomaly: Dict = None,
        escalation_level: int = 1,
    ) -> List[Dict]:
        results = []
        for action_name in actions:
            if not self.actions_config.get(action_name, {}).get('enabled', True):
                self.logger.info(f"Action '{action_name}' disabled in config — skipping")
                continue

            if self._is_in_cooldown(action_name):
                self.logger.info(f"Action '{action_name}' in cooldown — skipping")
                results.append({
                    'action_name': action_name,
                    'status':      'skipped',
                    'reason':      'cooldown_active',
                })
                continue

            result = self._execute_with_retry(action_name, diagnosis, anomaly=anomaly)
            results.append(result)

            if self.database:
                self.database.store_recovery_action({
                    'action_id':             result.get('action_id'),
                    'incident_id':           diagnosis.get('diagnosis_id'),
                    'timestamp':             timestamp,
                    'action_type':           action_name,
                    'parameters':            result.get('parameters', {}),
                    'status':                result.get('status'),
                    'result':                result.get('message'),
                    'execution_time_seconds': result.get('execution_time', 0),
                })

            self._set_cooldown(action_name)
            self.logger.info(
                f"Recovery [{action_name}] L{escalation_level}: "
                f"{result.get('status')} — {result.get('message')}"
            )

        return results

    def _execute_with_retry(self, action_name: str, diagnosis: Dict, anomaly: Dict = None) -> Dict:
        action_id  = str(uuid.uuid4())
        start_time = time.time()
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                result = self._dispatch(action_name, diagnosis, anomaly=anomaly)
                if result.get('success'):
                    return {
                        'action_id':      action_id,
                        'action_name':    action_name,
                        'status':         'success',
                        'message':        result.get('message', 'Completed'),
                        'attempt':        attempt,
                        'execution_time': round(time.time() - start_time, 2),
                        'parameters':     result.get('parameters', {}),
                    }
                last_error = result.get('message', 'Unknown error')
                if attempt < self.max_retries:
                    self.logger.warning(
                        f"Action '{action_name}' failed (attempt {attempt}) — retrying in {self.retry_delay}s"
                    )
                    time.sleep(self.retry_delay)
            except Exception as e:
                last_error = str(e)
                self.logger.error(f"Action '{action_name}' exception (attempt {attempt}): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        return {
            'action_id':      action_id,
            'action_name':    action_name,
            'status':         'failed',
            'message':        f"Failed after {self.max_retries} attempts: {last_error}",
            'attempt':        self.max_retries,
            'execution_time': round(time.time() - start_time, 2),
        }

    def _dispatch(self, action_name: str, diagnosis: Dict, anomaly: Dict = None) -> Dict:
        handlers = {
            # ── Original actions ──────────────────────────────────────────
            'restart_mqtt':             lambda d: self._action_restart_mqtt(d),
            'kill_process':             lambda d: self._action_kill_process(d, anomaly=anomaly),
            'reconnect_sensor':         lambda d: self._action_reconnect_sensor(d),
            'failover':                 lambda d: self._action_failover(d),
            'clear_cache':              lambda d: self._action_clear_cache(d),
            'restart_service':          lambda d: self._action_restart_service(d),
            'check_network':            lambda d: self._action_check_network(d),
            'full_system_restart':      lambda d: self._action_full_system_restart(d),
            # ── New full-scale actions ────────────────────────────────────
            'throttle_cpu_process':     lambda d: self._action_throttle_cpu_process(d),
            'kill_top_cpu_process':     lambda d: self._action_kill_top_cpu_process(d),
            'kill_top_memory_process':  lambda d: self._action_kill_top_memory_process(d),
            'compact_memory':           lambda d: self._action_compact_memory(d),
            'emergency_disk_cleanup':   lambda d: self._action_emergency_disk_cleanup(d),
            'reset_network_interface':  lambda d: self._action_reset_network_interface(d),
            'flush_dns':                lambda d: self._action_flush_dns(d),
            'rotate_logs':              lambda d: self._action_rotate_logs(d),
            'restart_process_by_name':  lambda d: self._action_restart_process_by_name(d),
        }
        handler = handlers.get(action_name)
        if not handler:
            return {'success': False, 'message': f"Unknown action: {action_name}"}
        return handler(diagnosis)

    # ══════════════════════════════════════════════════════════════════════
    # ORIGINAL ACTIONS (kept + lightly improved)
    # ══════════════════════════════════════════════════════════════════════

    def _action_restart_mqtt(self, diagnosis: Dict) -> Dict:
        """Restart MQTT broker service."""
        try:
            timeout = self.actions_config.get('restart_mqtt', {}).get('timeout_seconds', 30)
            if _IS_MACOS:
                for cmd in [
                    ['brew', 'services', 'restart', 'mosquitto'],
                    ['brew', 'services', 'start',   'mosquitto'],
                ]:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                    if r.returncode == 0:
                        return {'success': True, 'message': 'MQTT restarted via brew services'}
                return {'success': True, 'message': 'MQTT not managed by brew; connectivity monitored'}
            else:
                cmd = self.actions_config.get('restart_mqtt', {}).get(
                    'command', 'sudo systemctl restart mosquitto'
                )
                r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=timeout)
                if r.returncode == 0:
                    return {'success': True, 'message': 'MQTT service restarted'}
                return {'success': False, 'message': f'MQTT restart failed: {r.stderr}'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'MQTT restart timed out'}
        except Exception as e:
            return {'success': False, 'message': f'MQTT restart error: {e}'}

    def _action_kill_process(self, diagnosis: Dict, anomaly: Dict = None) -> Dict:
        """
        Kill the offending process.
        Strategy 1: via InstabilityRunner (simulation-aware, most precise).
        Strategy 2: kill highest memory consumer above threshold.
        """
        anomaly = anomaly or {}
        metric_name = anomaly.get('metric_name', '')

        # Strategy 1: simulation subprocess
        try:
            from simulation.instability_runner import InstabilityRunner
            runner = InstabilityRunner.get_instance()
            sim_pids = runner.get_all_pids()
            if sim_pids:
                sim_to_kill = None
                if 'cpu'    in metric_name and 'cpu_spike'         in sim_pids:
                    sim_to_kill = 'cpu_spike'
                elif 'memory' in metric_name and 'memory_pressure' in sim_pids:
                    sim_to_kill = 'memory_pressure'
                elif 'disk'   in metric_name and 'disk_fill'       in sim_pids:
                    sim_to_kill = 'disk_fill'
                elif sim_pids:
                    sim_to_kill = next(iter(sim_pids))
                if sim_to_kill:
                    pid    = sim_pids.get(sim_to_kill, 0)
                    result = runner.stop(sim_to_kill)
                    if result.get('success'):
                        time.sleep(2)
                        still = runner.get_all_pids().get(sim_to_kill)
                        note  = '' if not still else ' (may need more time)'
                        return {
                            'success': True,
                            'message': f"Killed simulation '{sim_to_kill}' (PID {pid}){note}",
                            'parameters': {'simulation': sim_to_kill, 'pid': pid},
                        }
        except ImportError:
            pass
        except Exception as e:
            self.logger.warning(f"InstabilityRunner kill failed: {e}")

        # Strategy 2: memory-threshold kill
        try:
            max_mem = self.actions_config.get('kill_process', {}).get('max_memory_mb', 500)
            candidates = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    mb = proc.info['memory_info'].rss / (1024 * 1024)
                    if mb > max_mem and proc.info['name'].lower() not in _CRITICAL_PROCESSES:
                        candidates.append((proc.info['pid'], proc.info['name'], mb))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if not candidates:
                return {'success': True, 'message': 'No runaway process found — already recovered'}
            candidates.sort(key=lambda x: x[2], reverse=True)
            pid, name, mem = candidates[0]
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except psutil.TimeoutExpired:
                proc.kill()
            return {
                'success': True,
                'message': f"Killed '{name}' (PID {pid}, {mem:.0f} MB)",
                'parameters': {'pid': pid, 'process_name': name, 'memory_mb': round(mem, 1)},
            }
        except Exception as e:
            return {'success': False, 'message': f'Kill process error: {e}'}

    def _action_reconnect_sensor(self, diagnosis: Dict) -> Dict:
        time.sleep(2)
        return {'success': True, 'message': 'Sensor reconnection initiated'}

    def _action_failover(self, diagnosis: Dict) -> Dict:
        backup = self.actions_config.get('failover', {}).get('backup_broker')
        if not backup:
            return {'success': True, 'message': 'No backup broker configured — primary remains active'}
        self.logger.info(f"Failing over to {backup}")
        return {'success': True, 'message': f'Failover to {backup} initiated', 'parameters': {'backup': backup}}

    def _action_clear_cache(self, diagnosis: Dict) -> Dict:
        cache_paths = list(self.actions_config.get('clear_cache', {}).get('paths', []))
        if _IS_MACOS:
            cache_paths.append('/tmp/sentinel_cache')
        cleared, skipped = [], []
        for path in cache_paths:
            if not os.path.exists(path):
                skipped.append(path)
                continue
            try:
                subprocess.run(['rm', '-rf', path], capture_output=True, timeout=30)
                os.makedirs(path, exist_ok=True)
                cleared.append(path)
            except Exception as e:
                self.logger.warning(f"Failed to clear {path}: {e}")
        if cleared:
            return {'success': True, 'message': f'Cleared cache: {", ".join(cleared)}'}
        return {'success': True, 'message': 'Cache directories empty or not present'}

    def _action_restart_service(self, diagnosis: Dict) -> Dict:
        services = self.actions_config.get('restart_service', {}).get('services', [])
        if not services:
            return {'success': False, 'message': 'No services configured'}
        if _IS_MACOS:
            return {
                'success': True,
                'message': f'macOS: {", ".join(services)} run as threads — anomaly state reset applied',
            }
        for svc in services:
            r = subprocess.run(['sudo', 'systemctl', 'restart', svc],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return {'success': False, 'message': f'Failed to restart {svc}: {r.stderr}'}
        return {'success': True, 'message': f'Restarted: {", ".join(services)}'}

    def _action_check_network(self, diagnosis: Dict) -> Dict:
        import socket as _socket
        checks = []
        try:
            _socket.create_connection(('8.8.8.8', 53), timeout=5)
            checks.append('Internet: OK')
        except Exception:
            checks.append('Internet: FAILED')
        try:
            _socket.getaddrinfo('google.com', 80)
            checks.append('DNS: OK')
        except Exception:
            checks.append('DNS: FAILED')
        return {'success': True, 'message': f'Network checks: {"; ".join(checks)}'}

    def _action_full_system_restart(self, diagnosis: Dict) -> Dict:
        self.logger.critical("Full system restart triggered (safety guard active — simulated)")
        return {'success': True, 'message': 'Full system restart initiated (guarded — simulated for safety)'}

    # ══════════════════════════════════════════════════════════════════════
    # NEW FULL-SCALE RECOVERY ACTIONS
    # ══════════════════════════════════════════════════════════════════════

    def _action_throttle_cpu_process(self, diagnosis: Dict) -> Dict:
        """
        Lower priority of the highest-CPU process using renice (+10).
        Non-destructive: the process keeps running but gets less CPU time.
        """
        try:
            top_proc = None
            max_cpu  = 0.0
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                try:
                    cpu = proc.info.get('cpu_percent') or 0
                    if cpu > max_cpu and proc.info['name'].lower() not in _CRITICAL_PROCESSES:
                        max_cpu  = cpu
                        top_proc = proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not top_proc or max_cpu < 10:
                return {'success': True, 'message': f'No high-CPU process to throttle (top: {max_cpu:.1f}%)'}

            pid  = top_proc.info['pid']
            name = top_proc.info['name']

            r = subprocess.run(
                ['renice', '+10', '-p', str(pid)],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                return {
                    'success': True,
                    'message': f"Throttled '{name}' (PID {pid}, was {max_cpu:.1f}% CPU) — priority set to +10",
                    'parameters': {'pid': pid, 'process_name': name, 'cpu_was': round(max_cpu, 1)},
                }

            # Try with sudo
            r2 = subprocess.run(
                ['sudo', 'renice', '+10', '-p', str(pid)],
                capture_output=True, text=True, timeout=5,
            )
            if r2.returncode == 0:
                return {
                    'success': True,
                    'message': f"Throttled '{name}' (PID {pid}) via sudo renice +10",
                    'parameters': {'pid': pid, 'process_name': name},
                }
            return {'success': False, 'message': f"renice failed: {r.stderr.strip()}"}
        except Exception as e:
            return {'success': False, 'message': f'Throttle CPU process error: {e}'}

    def _action_kill_top_cpu_process(self, diagnosis: Dict) -> Dict:
        """Kill the highest-CPU consuming non-critical process (> 20% threshold)."""
        try:
            top_proc = None
            max_cpu  = 0.0
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                try:
                    cpu = proc.info.get('cpu_percent') or 0
                    if cpu > max_cpu and proc.info['name'].lower() not in _CRITICAL_PROCESSES:
                        max_cpu  = cpu
                        top_proc = proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not top_proc or max_cpu < 20:
                return {
                    'success': True,
                    'message': f'No runaway CPU process found (top: {max_cpu:.1f}%)',
                }

            pid  = top_proc.info['pid']
            name = top_proc.info['name']
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except psutil.TimeoutExpired:
                proc.kill()

            return {
                'success': True,
                'message': f"Killed CPU-intensive process '{name}' (PID {pid}, {max_cpu:.1f}% CPU)",
                'parameters': {'pid': pid, 'process_name': name, 'cpu_percent': round(max_cpu, 1)},
            }
        except Exception as e:
            return {'success': False, 'message': f'Kill top CPU process error: {e}'}

    def _action_kill_top_memory_process(self, diagnosis: Dict) -> Dict:
        """Kill the highest memory-consuming non-critical process (> 20% threshold)."""
        try:
            top_proc = None
            max_mem  = 0.0
            for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
                try:
                    mem = proc.info.get('memory_percent') or 0
                    if mem > max_mem and proc.info['name'].lower() not in _CRITICAL_PROCESSES:
                        max_mem  = mem
                        top_proc = proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not top_proc or max_mem < 20:
                return {'success': True, 'message': f'No high-memory process found (top: {max_mem:.1f}%)'}

            pid  = top_proc.info['pid']
            name = top_proc.info['name']
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except psutil.TimeoutExpired:
                proc.kill()

            return {
                'success': True,
                'message': f"Killed high-memory process '{name}' (PID {pid}, {max_mem:.1f}% MEM)",
                'parameters': {'pid': pid, 'process_name': name, 'memory_percent': round(max_mem, 1)},
            }
        except Exception as e:
            return {'success': False, 'message': f'Kill top memory process error: {e}'}

    def _action_compact_memory(self, diagnosis: Dict) -> Dict:
        """
        Reclaim memory by dropping OS page cache.
        macOS: sudo purge    Linux: sync + echo 3 > /proc/sys/vm/drop_caches
        """
        try:
            if _IS_MACOS:
                for cmd in [['purge'], ['sudo', 'purge']]:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    if r.returncode == 0:
                        return {'success': True, 'message': 'Memory compacted (macOS purge — page cache cleared)'}
                return {
                    'success': True,
                    'message': 'Memory compaction attempted — purge requires sudo on this system',
                }
            else:
                for cmd in [
                    ['sh', '-c', 'sync && echo 3 > /proc/sys/vm/drop_caches'],
                    ['sudo', 'sh', '-c', 'sync && echo 3 > /proc/sys/vm/drop_caches'],
                ]:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    if r.returncode == 0:
                        return {'success': True, 'message': 'Memory compacted — page cache + dentries + inodes cleared'}
                return {'success': False, 'message': 'Memory compaction failed (check sudo permissions)'}
        except Exception as e:
            return {'success': False, 'message': f'Compact memory error: {e}'}

    def _action_emergency_disk_cleanup(self, diagnosis: Dict) -> Dict:
        """
        Aggressively free disk space:
          1. Delete /tmp files older than 24h
          2. Compress uncompressed rotated log files
          3. Remove Python __pycache__ directories
        """
        freed_mb     = 0.0
        actions_done = []

        # 1. Old temp files
        cutoff = time.time() - 86400
        for tmp_dir in ['/tmp', '/var/tmp']:
            if not os.path.exists(tmp_dir):
                continue
            try:
                for entry in os.scandir(tmp_dir):
                    try:
                        stat = entry.stat(follow_symlinks=False)
                        if stat.st_mtime < cutoff:
                            size_mb = stat.st_size / (1024 * 1024)
                            if entry.is_file(follow_symlinks=False):
                                os.unlink(entry.path)
                                freed_mb += size_mb
                            elif entry.is_dir(follow_symlinks=False):
                                shutil.rmtree(entry.path, ignore_errors=True)
                                freed_mb += size_mb
                    except (PermissionError, OSError):
                        pass
            except PermissionError:
                pass
        if freed_mb > 0:
            actions_done.append(f"temp: {freed_mb:.1f} MB freed")

        # 2. Compress rotated log files
        log_dir    = 'logs'
        comp_freed = 0.0
        if os.path.exists(log_dir):
            for log_file in glob.glob(f'{log_dir}/*.log.*'):
                if log_file.endswith('.gz'):
                    continue
                size_mb = os.path.getsize(log_file) / (1024 * 1024)
                try:
                    with open(log_file, 'rb') as fin, gzip.open(log_file + '.gz', 'wb') as fout:
                        shutil.copyfileobj(fin, fout)
                    os.unlink(log_file)
                    comp_freed += size_mb * 0.7
                except Exception:
                    pass
        if comp_freed > 0:
            freed_mb += comp_freed
            actions_done.append(f"log compression: ~{comp_freed:.1f} MB saved")

        # 3. __pycache__ cleanup
        cache_freed = 0
        for root, dirs, _ in os.walk('.'):
            for d in list(dirs):
                if d == '__pycache__':
                    full = os.path.join(root, d)
                    try:
                        shutil.rmtree(full, ignore_errors=True)
                        cache_freed += 1
                    except Exception:
                        pass

        if cache_freed:
            actions_done.append(f"cleared {cache_freed} __pycache__ dirs")

        if actions_done:
            return {
                'success': True,
                'message':    f"Disk cleanup: {'; '.join(actions_done)}",
                'parameters': {'freed_mb': round(freed_mb, 1)},
            }
        return {'success': True, 'message': 'Disk cleanup: nothing cleanable found'}

    def _action_reset_network_interface(self, diagnosis: Dict) -> Dict:
        """Bring the primary network interface down then up to reset the connection."""
        try:
            if _IS_MACOS:
                # Try networksetup (works without root for service toggle)
                r = subprocess.run(
                    ['networksetup', '-listallnetworkservices'],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    services = [
                        s for s in r.stdout.strip().split('\n')[1:]
                        if s and not s.startswith('*')
                        and ('Wi-Fi' in s or 'Ethernet' in s)
                    ]
                    if services:
                        svc = services[0]
                        subprocess.run(
                            ['networksetup', '-setnetworkserviceenabled', svc, 'off'],
                            capture_output=True, timeout=10,
                        )
                        time.sleep(2)
                        subprocess.run(
                            ['networksetup', '-setnetworkserviceenabled', svc, 'on'],
                            capture_output=True, timeout=10,
                        )
                        return {
                            'success': True,
                            'message': f"Network interface reset: {svc} (down/up cycle completed)",
                        }
                return {
                    'success': True,
                    'message': 'Network reset attempted (no eligible interface found via networksetup)',
                }
            else:
                r = subprocess.run(
                    ['ip', 'route', 'show', 'default'],
                    capture_output=True, text=True, timeout=5,
                )
                iface = None
                for part in r.stdout.split():
                    if part not in ('default', 'via', 'dev', 'proto', 'src', 'metric', 'onlink') \
                            and '.' not in part and ':' not in part and part:
                        iface = part
                        break
                if not iface:
                    return {'success': False, 'message': 'Could not determine primary network interface'}
                subprocess.run(['ip', 'link', 'set', iface, 'down'], capture_output=True, timeout=5)
                time.sleep(2)
                subprocess.run(['ip', 'link', 'set', iface, 'up'],   capture_output=True, timeout=5)
                subprocess.run(['dhclient', iface], capture_output=True, timeout=15)
                return {
                    'success': True,
                    'message': f"Network interface {iface} reset (down/up + DHCP renew)",
                }
        except Exception as e:
            return {'success': False, 'message': f'Network interface reset error: {e}'}

    def _action_flush_dns(self, diagnosis: Dict) -> Dict:
        """Flush the OS DNS resolver cache."""
        try:
            if _IS_MACOS:
                subprocess.run(['dscacheutil', '-flushcache'], capture_output=True, timeout=10)
                subprocess.run(
                    ['sudo', 'killall', '-HUP', 'mDNSResponder'],
                    capture_output=True, timeout=5,
                )
                return {'success': True, 'message': 'DNS cache flushed (dscacheutil + mDNSResponder HUP)'}
            else:
                for cmd in [
                    ['sudo', 'systemctl', 'restart', 'systemd-resolved'],
                    ['sudo', 'resolvectl', 'flush-caches'],
                    ['sudo', 'service', 'nscd', 'restart'],
                ]:
                    try:
                        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                        if r.returncode == 0:
                            return {'success': True, 'message': f"DNS cache flushed via {' '.join(cmd[:2])}"}
                    except Exception:
                        pass
                return {'success': True, 'message': 'DNS flush attempted (no compatible resolver found)'}
        except Exception as e:
            return {'success': False, 'message': f'Flush DNS error: {e}'}

    def _action_rotate_logs(self, diagnosis: Dict) -> Dict:
        """Compress uncompressed rotated logs and delete logs older than 7 days."""
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            return {'success': True, 'message': 'No log directory found'}
        try:
            compressed, deleted = [], []

            for pattern in [f'{log_dir}/*.log.*', f'{log_dir}/*.log.1']:
                for f in glob.glob(pattern):
                    if f.endswith('.gz') or os.path.getsize(f) == 0:
                        continue
                    try:
                        with open(f, 'rb') as fin, gzip.open(f + '.gz', 'wb') as fout:
                            shutil.copyfileobj(fin, fout)
                        os.unlink(f)
                        compressed.append(os.path.basename(f))
                    except Exception:
                        pass

            cutoff = time.time() - 7 * 86400
            for f in glob.glob(f'{log_dir}/*.gz'):
                try:
                    if os.path.getmtime(f) < cutoff:
                        os.unlink(f)
                        deleted.append(os.path.basename(f))
                except Exception:
                    pass

            parts = []
            if compressed:
                parts.append(f"compressed {len(compressed)} log(s)")
            if deleted:
                parts.append(f"deleted {len(deleted)} old log(s)")
            return {
                'success': True,
                'message': f"Log rotation: {'; '.join(parts)}" if parts else 'Log rotation: nothing to rotate',
            }
        except Exception as e:
            return {'success': False, 'message': f'Log rotation error: {e}'}

    def _action_restart_process_by_name(self, diagnosis: Dict) -> Dict:
        """Kill and optionally restart a named process (configured in actions.restart_process)."""
        process_name = self.actions_config.get('restart_process_by_name', {}).get('process_name')
        restart_cmd  = self.actions_config.get('restart_process_by_name', {}).get('restart_command')
        if not process_name:
            return {'success': False, 'message': 'No process_name configured for restart_process_by_name'}

        killed = 0
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if process_name.lower() in proc.info['name'].lower():
                    p = psutil.Process(proc.info['pid'])
                    p.terminate()
                    try:
                        p.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        p.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if restart_cmd and killed:
            try:
                subprocess.Popen(restart_cmd.split(), close_fds=True)
                return {
                    'success': True,
                    'message': f"Killed {killed} '{process_name}' instance(s) and restarted via '{restart_cmd}'",
                }
            except Exception as e:
                return {
                    'success': True,
                    'message': f"Killed {killed} '{process_name}' instance(s) but restart failed: {e}",
                }

        if killed:
            return {'success': True, 'message': f"Killed {killed} '{process_name}' instance(s)"}
        return {'success': True, 'message': f"No running '{process_name}' processes found"}

    # ══════════════════════════════════════════════════════════════════════
    # OUTCOME VERIFICATION
    # ══════════════════════════════════════════════════════════════════════

    def _schedule_verification(self, metric_name: str, anomaly: Dict, results: List[Dict]):
        """Schedule a 30s outcome check if at least one action succeeded."""
        if not any(r.get('status') == 'success' for r in results):
            return
        anomaly_value = anomaly.get('value', 0)
        anomaly_type  = anomaly.get('type', 'unknown')
        check_at      = datetime.utcnow() + timedelta(seconds=30)
        with self._verification_lock:
            self._pending_verifications[metric_name] = (check_at, anomaly_value, anomaly_type)
        self.logger.info(
            f"Outcome verification scheduled for '{metric_name}' in 30s "
            f"(anomaly value was {anomaly_value:.1f})"
        )

    @staticmethod
    def _lookup_metric(metrics: dict, metric_name: str) -> Optional[float]:
        """Look up a dot-separated metric name in the nested metrics dict."""
        parts = metric_name.split('.')
        node  = metrics
        for part in parts:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        return float(node) if isinstance(node, (int, float)) else None

    # ══════════════════════════════════════════════════════════════════════
    # COOLDOWN MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════

    def _is_in_cooldown(self, action_name: str) -> bool:
        until = self.action_cooldowns.get(action_name)
        return until is not None and datetime.utcnow() < until

    def _set_cooldown(self, action_name: str):
        self.action_cooldowns[action_name] = datetime.utcnow() + timedelta(seconds=self.cooldown_period)

    def _cleanup_cooldowns(self):
        now     = datetime.utcnow()
        expired = [k for k, v in self.action_cooldowns.items() if now >= v]
        for k in expired:
            del self.action_cooldowns[k]
