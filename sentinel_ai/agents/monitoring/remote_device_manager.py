"""
Remote Device Manager — manages machines that push metrics to the Sentinel AI hub.

Each registered device's metrics are injected into the shared event bus so they
flow through the full anomaly → diagnosis → recovery pipeline just like local metrics.
The device_id field in every event identifies which machine the metric came from.
"""

import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional


class RemoteDevice:
    """State record for one connected remote machine."""

    STALE_AFTER_S = 30
    OFFLINE_AFTER_S = 60

    def __init__(self, device_id: str, info: dict):
        self.device_id = device_id
        self.hostname = info.get('hostname', device_id)
        self.platform = info.get('platform', 'unknown')
        self.version = info.get('version', '')
        self.python = info.get('python', '')
        self.registered_at = datetime.now(timezone.utc)
        self.last_seen = self.registered_at
        self.last_metrics: dict = {}
        self.metric_count = 0
        self.status = 'connected'


    def record_push(self, metrics: dict):
        self.last_seen = datetime.now(timezone.utc)
        self.last_metrics = metrics
        self.metric_count += 1
        self.status = 'connected'

    def refresh_status(self):
        age = self.age_seconds
        if age > self.OFFLINE_AFTER_S:
            self.status = 'offline'
        elif age > self.STALE_AFTER_S:
            self.status = 'stale'


    @property
    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.last_seen).total_seconds()

    def to_dict(self) -> dict:
        return {
            'device_id': self.device_id,
            'hostname': self.hostname,
            'platform': self.platform,
            'registered_at': self.registered_at.isoformat(),
            'last_seen': self.last_seen.isoformat(),
            'metric_count': self.metric_count,
            'status': self.status,
            'age_seconds': round(self.age_seconds, 1),
        }


class RemoteDeviceManager:
    """
    Accepts metric pushes from remote sentinel_client.py instances and
    injects them into the hub's event bus for full pipeline processing.

    Thread-safe; designed to be started once and left running.
    """

    def __init__(self, event_bus, logger):
        self.event_bus = event_bus
        self.logger = logger
        self._devices: Dict[str, RemoteDevice] = {}
        self._lock = threading.RLock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._command_queues: Dict[str, list] = {}


    def start(self):
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._staleness_monitor,
            daemon=True,
            name='RemoteDeviceMonitor',
        )
        self._monitor_thread.start()
        self.logger.info("Remote Device Manager started — waiting for client connections")

    def stop(self):
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)


    def register(self, device_id: str, info: dict) -> bool:
        """Register or re-register a remote device."""
        with self._lock:
            is_new = device_id not in self._devices
            self._devices[device_id] = RemoteDevice(device_id, info)
            verb = 'registered' if is_new else 're-registered'
            self.logger.info(
                f"Remote device {verb}: {device_id} "
                f"({info.get('hostname', '?')} / {info.get('platform', '?')})"
            )
        return True

    def push_metrics(self, device_id: str, timestamp: str, metrics: dict) -> bool:
        """
        Accept a metric payload from a remote device and publish it to the
        event bus so the anomaly, diagnosis, and recovery agents process it.
        """
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                self.register(device_id, {'hostname': device_id, 'platform': 'unknown'})
                device = self._devices[device_id]
            device.record_push(metrics)

        try:
            from core.event_bus import EventPriority
            self.event_bus.create_event(
                event_type='health.metric',
                data={
                    'device_id': device_id,
                    'timestamp': timestamp,
                    'metrics': metrics,
                    'source': 'remote',
                },
                source='RemoteDeviceManager',
                priority=EventPriority.NORMAL,
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to inject remote metrics for {device_id}: {e}")
            return False

    def get_all_devices(self) -> list:
        with self._lock:
            return [d.to_dict() for d in self._devices.values()]

    def get_device(self, device_id: str) -> Optional[dict]:
        with self._lock:
            d = self._devices.get(device_id)
            return d.to_dict() if d else None

    def get_device_metrics(self, device_id: str) -> Optional[dict]:
        with self._lock:
            d = self._devices.get(device_id)
            return d.last_metrics if d else None

    def device_count(self) -> int:
        with self._lock:
            return len(self._devices)

    def is_remote(self, device_id: str) -> bool:
        """Return True if this device_id belongs to a registered remote device."""
        with self._lock:
            return device_id in self._devices

    def queue_command(self, device_id: str, command: dict) -> bool:
        """Queue a recovery command to be picked up by the remote client."""
        with self._lock:
            if device_id not in self._command_queues:
                self._command_queues[device_id] = []
            self._command_queues[device_id].append(command)
            self.logger.info(f"Queued remote command '{command.get('action')}' for {device_id}")
            return True

    def pop_commands(self, device_id: str) -> list:
        """Return and clear all pending commands for a device."""
        with self._lock:
            return self._command_queues.pop(device_id, [])


    def _staleness_monitor(self):
        """Periodically refresh device status and log transitions."""
        while self._running:
            with self._lock:
                for device in self._devices.values():
                    old_status = device.status
                    device.refresh_status()
                    if device.status != old_status:
                        level = 'warning'
                        if device.status == 'offline':
                            self.logger.warning(
                                f"Remote device OFFLINE: {device.device_id} "
                                f"(no data for {device.age_seconds:.0f}s)"
                            )
                        elif device.status == 'stale':
                            self.logger.warning(
                                f"Remote device STALE: {device.device_id} "
                                f"(no data for {device.age_seconds:.0f}s)"
                            )
                        elif device.status == 'connected' and old_status in ('stale', 'offline'):
                            self.logger.info(
                                f"Remote device RECONNECTED: {device.device_id}"
                            )
            time.sleep(10)
