"""
Security Agent — Sentinel AI Cybersecurity Monitor
Detects suspicious activity patterns on IoT devices.

Current implementation: rule-based detection (demo/stub).
Production integration: plug in Suricata, Zeek, or AWS GuardDuty alerts here.

Threat categories monitored:
  - Port scan / brute-force (rapid failed connection bursts)
  - Unusual outbound connections (unexpected IPs or ports)
  - Process anomalies (unexpected privileged processes)
  - Payload size anomalies (data exfiltration indicators)
  - Authentication failures (repeated login attempts)
"""

import time
import random
import socket
from datetime import datetime
from typing import Dict, List, Any, Optional

import psutil

from agents.base_agent import BaseAgent
from core.event_bus import EventPriority


SEVERITY_INFO = 'info'
SEVERITY_LOW = 'low'
SEVERITY_MEDIUM = 'medium'
SEVERITY_HIGH = 'high'
SEVERITY_CRITICAL = 'critical'


class SecurityAgent(BaseAgent):
    """
    Monitors the device for cybersecurity threats and publishes
    `security.threat` events to the event bus.

    In demo mode the agent emits realistic-looking simulated threat
    observations so the dashboard can show something meaningful without
    needing a real IDS/IPS backend.
    """

    def __init__(self, name: str, config, event_bus, logger, database=None):
        super().__init__(name, config, event_bus, logger)

        self.database = database
        self.device_id = config.device_id
        self.scan_interval = config.get('security.scan_interval_seconds', 30)

        self._failed_conns: Dict[str, int] = {}
        self._prev_net_stats = None

        self._expected_ports = {22, 80, 443, 1883, 5001, 8883}

        self.threat_history: List[Dict] = []

        self.logger.info("Security Agent initialized (demo/stub mode)")


    def _run(self):
        self.logger.info("Security Agent started")

        while self._running:
            try:
                threats = self._scan()
                for threat in threats:
                    self._publish_threat(threat)
            except Exception as e:
                self.logger.error(f"Security scan error: {e}", exc_info=True)

            if not self.wait(self.scan_interval):
                break


    def _scan(self) -> List[Dict]:
        """Run all detection checks and return a list of threat dicts."""
        threats: List[Dict] = []

        t = self._check_open_ports()
        if t:
            threats.append(t)

        t = self._check_connection_anomaly()
        if t:
            threats.append(t)

        t = self._check_privileged_processes()
        if t:
            threats.append(t)

        if random.random() < 0.04:
            threats.append(self._synthetic_threat())

        return threats

    def _check_open_ports(self) -> Optional[Dict]:
        """Detect unexpected listening ports (possible backdoor or rogue service)."""
        try:
            listening = {
                conn.laddr.port
                for conn in psutil.net_connections(kind='inet')
                if conn.status == 'LISTEN'
            }
            unexpected = listening - self._expected_ports
            if unexpected:
                return self._make_threat(
                    category = 'unexpected_port',
                    severity = SEVERITY_MEDIUM,
                    title = 'Unexpected listening port',
                    detail = f"Ports not in allowlist: {sorted(unexpected)}",
                    indicators = {'ports': sorted(unexpected)},
                )
        except Exception as e:
            self.logger.debug(f"Port check error: {e}")
        return None

    def _check_connection_anomaly(self) -> Optional[Dict]:
        """Detect abnormally high number of concurrent connections (scan/flood)."""
        try:
            conns = psutil.net_connections(kind='inet')
            total = len(conns)
            if total > 200:
                return self._make_threat(
                    category = 'connection_flood',
                    severity = SEVERITY_HIGH if total > 500 else SEVERITY_MEDIUM,
                    title = 'High connection count',
                    detail = f"{total} concurrent connections detected",
                    indicators = {'connection_count': total},
                )
        except Exception as e:
            self.logger.debug(f"Connection check error: {e}")
        return None

    def _check_privileged_processes(self) -> Optional[Dict]:
        """Detect processes running as root/SYSTEM that are not expected."""
        _safe_root_names = {
            'kernel_task', 'launchd', 'systemd', 'init', 'kthreadd',
            'python', 'python3', 'sshd', 'sentinel', 'sentinel_ai',
        }
        try:
            suspicious = []
            for proc in psutil.process_iter(['pid', 'name', 'username']):
                try:
                    if proc.info['username'] in ('root', 'SYSTEM'):
                        name = (proc.info['name'] or '').lower()
                        if not any(s in name for s in _safe_root_names):
                            suspicious.append(proc.info['name'])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if suspicious:
                return self._make_threat(
                    category = 'privileged_process',
                    severity = SEVERITY_LOW,
                    title = 'Privileged process observed',
                    detail = f"Root process(es): {', '.join(suspicious[:5])}",
                    indicators = {'processes': suspicious[:5]},
                )
        except Exception as e:
            self.logger.debug(f"Privilege check error: {e}")
        return None

    def _synthetic_threat(self) -> Dict:
        """Generate a realistic-looking synthetic threat for demo purposes."""
        templates = [
            dict(category='brute_force', severity=SEVERITY_HIGH,
                 title='SSH brute-force attempt',
                 detail='24 failed login attempts from 203.0.113.42 in 60s'),
            dict(category='data_exfiltration', severity=SEVERITY_CRITICAL,
                 title='Unusual data egress',
                 detail='Outbound transfer spike: 48 MB to unknown IP'),
            dict(category='port_scan', severity=SEVERITY_MEDIUM,
                 title='Port scan detected',
                 detail='192.168.1.77 probed 312 ports in 5s'),
            dict(category='malware_signature', severity=SEVERITY_CRITICAL,
                 title='Suspicious payload pattern',
                 detail='Network packet matched known C2 beacon signature'),
            dict(category='auth_anomaly', severity=SEVERITY_HIGH,
                 title='Auth anomaly',
                 detail='Login from new geographic location'),
        ]
        t = random.choice(templates)
        return self._make_threat(**t, indicators={'synthetic': True, 'demo': True})


    def _make_threat(self, category: str, severity: str, title: str,
                     detail: str, indicators: Dict = None) -> Dict:
        return {
            'threat_id': f"sec-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            'timestamp': datetime.utcnow().isoformat(),
            'device_id': self.device_id,
            'category': category,
            'severity': severity,
            'title': title,
            'detail': detail,
            'indicators': indicators or {},
        }

    def _publish_threat(self, threat: Dict):
        """Publish a security threat event to the bus and log it."""
        self.threat_history.append(threat)
        if len(self.threat_history) > 50:
            self.threat_history.pop(0)

        self.publish_event(
            event_type = 'security.threat',
            data = {'threat': threat, 'device_id': self.device_id},
            priority = EventPriority.HIGH,
        )
        self.logger.warning(
            f"[SECURITY] {threat['severity'].upper()} — {threat['title']}: {threat['detail']}"
        )

    def process_event(self, event):
        """Security agent is primarily a producer; no events to consume."""
        pass
