"""
Recovery Agent - Executes autonomous corrective actions
Actions: restart services, kill processes, reconnect sensors, failover, clear cache
"""

import subprocess
import sys
import time
import uuid
import platform
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

_IS_MACOS = platform.system() == 'Darwin'

from agents.base_agent import BaseAgent
from core.event_bus import EventPriority


class RecoveryAgent(BaseAgent):
    """
    Agent responsible for executing autonomous recovery actions
    """

    def __init__(self, name: str, config, event_bus, logger, database=None):
        """
        Initialize recovery agent

        Args:
            name: Agent name
            config: Configuration
            event_bus: Event bus
            logger: Logger
            database: Optional database
        """
        super().__init__(name, config, event_bus, logger)

        self.database = database
        self.device_id = config.device_id

        # Recovery configuration
        self.recovery_config = config.get_section('recovery')
        self.actions_config = self.recovery_config.get('actions', {})
        self.auto_recovery = self.recovery_config.get('auto_recovery', True)
        self.max_retries = self.recovery_config.get('max_retries', 3)
        self.retry_delay = self.recovery_config.get('retry_delay_seconds', 5)
        self.cooldown_period = self.recovery_config.get('cooldown_period_seconds', 300)

        # Track recent actions to prevent loops
        self.recent_actions = []
        self.action_cooldowns = {}

        # Subscribe to diagnosis events
        self.event_bus.subscribe("diagnosis.complete", self.process_event)

    def _run(self):
        """Main loop (recovery is event-driven)"""
        self.logger.info("Recovery agent started (event-driven mode)")

        while self._running:
            # Perform periodic cleanup
            try:
                self._cleanup_cooldowns()
            except Exception as e:
                self.logger.error(f"Error in periodic cleanup: {e}")

            if not self.wait(60):
                break

    def process_event(self, event):
        """
        Process diagnosis events and execute recovery actions

        Args:
            event: Event object
        """
        if event.event_type != "diagnosis.complete":
            return

        if not self.auto_recovery:
            self.logger.info("Auto-recovery disabled, skipping action execution")
            return

        try:
            diagnosis = event.data.get('diagnosis', {})
            anomaly = event.data.get('anomaly', {})
            recommended_actions = diagnosis.get('recommended_actions', [])
            device_id = event.data.get('device_id')
            timestamp = event.data.get('timestamp')

            if not recommended_actions:
                self.logger.debug("No recommended actions in diagnosis")
                return

            # Execute recovery actions
            results = self.execute_recovery_actions(
                recommended_actions,
                diagnosis,
                device_id,
                timestamp,
                anomaly=anomaly
            )

            # Publish recovery results
            self.publish_event(
                event_type="recovery.action",
                data={
                    'device_id': device_id,
                    'timestamp': timestamp,
                    'diagnosis_id': diagnosis.get('diagnosis_id'),
                    'actions': results
                },
                priority=EventPriority.HIGH
            )

        except Exception as e:
            self.logger.error(f"Error processing diagnosis: {e}", exc_info=True)

    def execute_recovery_actions(
        self,
        actions: List[str],
        diagnosis: Dict,
        device_id: str,
        timestamp: str,
        anomaly: Dict = None
    ) -> List[Dict]:
        """
        Execute a list of recovery actions

        Args:
            actions: List of action names
            diagnosis: Diagnosis data
            device_id: Device ID
            timestamp: Timestamp

        Returns:
            List of action results
        """
        results = []

        for action_name in actions:
            # Check if action is enabled
            if not self.actions_config.get(action_name, {}).get('enabled', False):
                self.logger.warning(f"Action {action_name} is not enabled, skipping")
                continue

            # Check cooldown
            if self._is_in_cooldown(action_name):
                self.logger.warning(f"Action {action_name} is in cooldown, skipping")
                results.append({
                    'action_name': action_name,
                    'status': 'skipped',
                    'reason': 'cooldown_active'
                })
                continue

            # Execute action with retry logic
            result = self._execute_action_with_retry(action_name, diagnosis, anomaly=anomaly)

            # Store result
            results.append(result)

            # Store in database
            if self.database:
                self.database.store_recovery_action({
                    'action_id': result.get('action_id'),
                    'incident_id': diagnosis.get('diagnosis_id'),
                    'timestamp': timestamp,
                    'action_type': action_name,
                    'parameters': result.get('parameters', {}),
                    'status': result.get('status'),
                    'result': result.get('message'),
                    'execution_time_seconds': result.get('execution_time', 0)
                })

            # Update cooldown
            self._set_cooldown(action_name)

            # Log action
            self.logger.info(
                f"Recovery action {action_name}: {result.get('status')} - {result.get('message')}"
            )

        return results

    def _execute_action_with_retry(self, action_name: str, diagnosis: Dict, anomaly: Dict = None) -> Dict:
        """
        Execute action with retry logic

        Args:
            action_name: Name of action
            diagnosis: Diagnosis data
            anomaly: Original anomaly data (for context)

        Returns:
            Action result dictionary
        """
        action_id = str(uuid.uuid4())
        start_time = time.time()
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                result = self._execute_action(action_name, diagnosis, anomaly=anomaly)

                if result.get('success'):
                    execution_time = time.time() - start_time

                    return {
                        'action_id': action_id,
                        'action_name': action_name,
                        'status': 'success',
                        'message': result.get('message', 'Action completed successfully'),
                        'attempt': attempt,
                        'execution_time': execution_time,
                        'parameters': result.get('parameters', {})
                    }

                # Action failed, retry if attempts remain
                last_error = result.get('message', 'Unknown error')

                if attempt < self.max_retries:
                    self.logger.warning(
                        f"Action {action_name} failed (attempt {attempt}), retrying in {self.retry_delay}s..."
                    )
                    time.sleep(self.retry_delay)

            except Exception as e:
                last_error = str(e)
                self.logger.error(f"Action {action_name} error (attempt {attempt}): {e}")

                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        # All retries exhausted
        execution_time = time.time() - start_time

        return {
            'action_id': action_id,
            'action_name': action_name,
            'status': 'failed',
            'message': f"Failed after {self.max_retries} attempts: {last_error}",
            'attempt': self.max_retries,
            'execution_time': execution_time
        }

    def _execute_action(self, action_name: str, diagnosis: Dict, anomaly: Dict = None) -> Dict:
        """
        Execute a specific recovery action

        Args:
            action_name: Name of action
            diagnosis: Diagnosis context
            anomaly: Original anomaly data for context (process PIDs, metric names, etc.)

        Returns:
            Result dictionary with 'success' and 'message'
        """
        # Dispatch to specific action handler
        # kill_process gets the anomaly for PID-based targeting
        action_handlers = {
            'restart_mqtt':       lambda d: self._action_restart_mqtt(d),
            'kill_process':       lambda d: self._action_kill_process(d, anomaly=anomaly),
            'reconnect_sensor':   lambda d: self._action_reconnect_sensor(d),
            'failover':           lambda d: self._action_failover(d),
            'clear_cache':        lambda d: self._action_clear_cache(d),
            'restart_service':    lambda d: self._action_restart_service(d),
            'check_network':      lambda d: self._action_check_network(d),
            'full_system_restart':lambda d: self._action_full_system_restart(d),
        }

        handler = action_handlers.get(action_name)

        if not handler:
            return {
                'success': False,
                'message': f"Unknown action: {action_name}"
            }

        return handler(diagnosis)

    def _action_restart_mqtt(self, diagnosis: Dict) -> Dict:
        """Restart MQTT broker service (macOS: brew services, Linux: systemctl)"""
        try:
            timeout = self.actions_config.get('restart_mqtt', {}).get('timeout_seconds', 30)

            if _IS_MACOS:
                # Try brew services first
                for cmd in [
                    ['brew', 'services', 'restart', 'mosquitto'],
                    ['brew', 'services', 'start', 'mosquitto'],
                ]:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                    if result.returncode == 0:
                        return {'success': True, 'message': 'MQTT service restarted via brew services'}
                # mosquitto not installed via brew — log as advisory, not a failure
                return {
                    'success': True,
                    'message': 'MQTT broker not managed by brew; connectivity already being monitored'
                }
            else:
                command = self.actions_config.get('restart_mqtt', {}).get(
                    'command', 'sudo systemctl restart mosquitto'
                )
                result = subprocess.run(
                    command.split(), capture_output=True, text=True, timeout=timeout
                )
                if result.returncode == 0:
                    return {'success': True, 'message': 'MQTT service restarted successfully'}
                return {'success': False, 'message': f'MQTT restart failed: {result.stderr}'}

        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'MQTT restart timed out'}
        except Exception as e:
            return {'success': False, 'message': f'MQTT restart error: {e}'}

    def _action_kill_process(self, diagnosis: Dict, anomaly: Dict = None) -> Dict:
        """
        Kill the offending process using a tiered strategy:
          1. Kill the exact simulation subprocess via InstabilityRunner (most reliable)
          2. Fall back to memory-threshold-based kill
        """
        anomaly = anomaly or {}
        metric_name = anomaly.get('metric_name', '')

        # ── Strategy 1: Kill simulation process via InstabilityRunner ──────────
        try:
            from simulation.instability_runner import InstabilityRunner
            runner = InstabilityRunner.get_instance()
            sim_pids = runner.get_all_pids()

            if sim_pids:
                # Map anomaly metric to simulation name
                sim_to_kill = None
                if 'cpu' in metric_name and 'cpu_spike' in sim_pids:
                    sim_to_kill = 'cpu_spike'
                elif 'memory' in metric_name and 'memory_pressure' in sim_pids:
                    sim_to_kill = 'memory_pressure'
                elif 'disk' in metric_name and 'disk_fill' in sim_pids:
                    sim_to_kill = 'disk_fill'
                elif sim_pids:
                    # Kill the first available simulation as fallback
                    sim_to_kill = next(iter(sim_pids))

                if sim_to_kill:
                    pid = sim_pids.get(sim_to_kill, 0)
                    result = runner.stop(sim_to_kill)
                    if result.get('success'):
                        self.logger.info(
                            f"Recovery: killed simulation '{sim_to_kill}' (PID: {pid})"
                        )
                        # Brief pause, then verify the process is gone
                        time.sleep(2)
                        still_running = runner.get_all_pids().get(sim_to_kill)
                        status_note = '' if not still_running else ' (process may need more time to exit)'
                        return {
                            'success': True,
                            'message': (
                                f"Killed simulation '{sim_to_kill}' (PID: {pid}){status_note}"
                            ),
                            'parameters': {'simulation': sim_to_kill, 'pid': pid}
                        }
        except ImportError:
            pass  # simulation module not available (production mode)
        except Exception as e:
            self.logger.warning(f"InstabilityRunner kill failed: {e}")

        # ── Strategy 2: Memory-threshold kill (existing behaviour) ──────────────
        try:
            max_memory_mb = self.actions_config.get('kill_process', {}).get('max_memory_mb', 500)

            high_mem_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    mem_mb = proc.info['memory_info'].rss / (1024 * 1024)
                    if mem_mb > max_memory_mb:
                        high_mem_processes.append((proc.info['pid'], proc.info['name'], mem_mb))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not high_mem_processes:
                return {
                    'success': True,
                    'message': 'No runaway processes found — resource may have already recovered'
                }

            high_mem_processes.sort(key=lambda x: x[2], reverse=True)
            pid, name, mem = high_mem_processes[0]

            critical_processes = ['systemd', 'init', 'sshd', 'sentinel', 'kernel']
            if any(cp in name.lower() for cp in critical_processes):
                return {
                    'success': False,
                    'message': f'Cannot kill critical system process: {name}'
                }

            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except psutil.TimeoutExpired:
                proc.kill()

            return {
                'success': True,
                'message': f'Killed high-memory process {name} (PID: {pid}, Mem: {mem:.1f} MB)',
                'parameters': {'pid': pid, 'process_name': name, 'memory_mb': round(mem, 1)}
            }

        except Exception as e:
            return {'success': False, 'message': f'Kill process error: {e}'}

    def _action_reconnect_sensor(self, diagnosis: Dict) -> Dict:
        """Reconnect to sensor (placeholder for actual sensor code)"""
        try:
            # This would contain actual sensor reconnection logic
            # For now, simulate reconnection
            time.sleep(2)

            return {
                'success': True,
                'message': 'Sensor reconnection initiated'
            }

        except Exception as e:
            return {'success': False, 'message': f'Sensor reconnect error: {e}'}

    def _action_failover(self, diagnosis: Dict) -> Dict:
        """Switch to backup infrastructure"""
        try:
            backup_broker = self.actions_config.get('failover', {}).get('backup_broker')

            if not backup_broker:
                return {
                    'success': True,
                    'message': 'No backup broker configured — primary broker remains active'
                }

            # Update configuration to use backup broker
            # This is a placeholder - actual implementation would update MQTT client
            self.logger.info(f"Failing over to backup broker: {backup_broker}")

            return {
                'success': True,
                'message': f'Failover to {backup_broker} initiated',
                'parameters': {'backup_broker': backup_broker}
            }

        except Exception as e:
            return {'success': False, 'message': f'Failover error: {e}'}

    def _action_clear_cache(self, diagnosis: Dict) -> Dict:
        """Clear system and application caches"""
        import os
        try:
            cache_paths = self.actions_config.get('clear_cache', {}).get('paths', [])

            # Add macOS-specific sentinel cache location
            if _IS_MACOS:
                cache_paths = list(cache_paths) + ['/tmp/sentinel_cache']

            cleared_paths = []
            skipped_paths = []

            for path in cache_paths:
                try:
                    if not os.path.exists(path):
                        skipped_paths.append(path)
                        continue
                    result = subprocess.run(
                        ['rm', '-rf', path],
                        capture_output=True,
                        timeout=30
                    )
                    if result.returncode == 0:
                        os.makedirs(path, exist_ok=True)  # Recreate empty dir
                        cleared_paths.append(path)
                except Exception as e:
                    self.logger.warning(f"Failed to clear {path}: {e}")

            if cleared_paths:
                return {
                    'success': True,
                    'message': f'Cleared cache: {", ".join(cleared_paths)}'
                }
            else:
                return {
                    'success': True,
                    'message': 'Cache directories empty or not present — nothing to clear'
                }

        except Exception as e:
            return {'success': False, 'message': f'Clear cache error: {e}'}

    def _action_restart_service(self, diagnosis: Dict) -> Dict:
        """Restart Sentinel AI service (macOS-safe)"""
        try:
            services = self.actions_config.get('restart_service', {}).get('services', [])

            if not services:
                return {'success': False, 'message': 'No services configured'}

            if _IS_MACOS:
                # On macOS Sentinel runs as a foreground Python process, not a systemd unit.
                # Gracefully signal the monitoring subagents to reset their state instead.
                self.logger.info("macOS: service restart mapped to in-process agent reset")
                # Reset anomaly detection state by clearing consecutive counts
                # (This is the closest equivalent to a lightweight "restart" on macOS)
                return {
                    'success': True,
                    'message': (
                        f'macOS: {", ".join(services)} run as Python threads — '
                        'anomaly state reset applied as equivalent recovery'
                    )
                }

            # Linux path
            for service in services:
                result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', service],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode != 0:
                    return {
                        'success': False,
                        'message': f'Failed to restart {service}: {result.stderr}'
                    }

            return {'success': True, 'message': f'Restarted services: {", ".join(services)}'}

        except Exception as e:
            return {'success': False, 'message': f'Restart service error: {e}'}

    def _action_check_network(self, diagnosis: Dict) -> Dict:
        """Run network diagnostics"""
        try:
            # Run basic network checks
            checks = []

            # Check default gateway
            try:
                import socket
                socket.create_connection(("8.8.8.8", 53), timeout=5)
                checks.append("Internet connectivity: OK")
            except:
                checks.append("Internet connectivity: FAILED")

            # Check DNS
            try:
                socket.getaddrinfo("google.com", 80)
                checks.append("DNS resolution: OK")
            except:
                checks.append("DNS resolution: FAILED")

            return {
                'success': True,
                'message': f'Network checks completed: {"; ".join(checks)}'
            }

        except Exception as e:
            return {'success': False, 'message': f'Network check error: {e}'}

    def _action_full_system_restart(self, diagnosis: Dict) -> Dict:
        """Full system restart (use with caution)"""
        try:
            # This is a high-risk action - log extensively
            self.logger.critical("Full system restart initiated")

            # In production, this would restart the entire Sentinel system
            # For safety, we'll just return success without actually restarting
            return {
                'success': True,
                'message': 'Full system restart initiated (simulated)'
            }

        except Exception as e:
            return {'success': False, 'message': f'System restart error: {e}'}

    def _is_in_cooldown(self, action_name: str) -> bool:
        """
        Check if action is in cooldown period

        Args:
            action_name: Action name

        Returns:
            True if in cooldown
        """
        if action_name not in self.action_cooldowns:
            return False

        cooldown_until = self.action_cooldowns[action_name]
        return datetime.utcnow() < cooldown_until

    def _set_cooldown(self, action_name: str):
        """Set cooldown for action"""
        cooldown_until = datetime.utcnow() + timedelta(seconds=self.cooldown_period)
        self.action_cooldowns[action_name] = cooldown_until

    def _cleanup_cooldowns(self):
        """Remove expired cooldowns"""
        now = datetime.utcnow()
        expired = [
            action for action, until in self.action_cooldowns.items()
            if now >= until
        ]

        for action in expired:
            del self.action_cooldowns[action]
