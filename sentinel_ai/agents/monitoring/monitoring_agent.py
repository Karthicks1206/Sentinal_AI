"""
Monitoring Agent - Collects real-time health metrics from the system
Monitors: CPU, Memory, Disk, Network, MQTT connectivity, Sensor latency
"""

import psutil
import subprocess
import time
import socket
from datetime import datetime
from typing import Dict, List, Optional, Any
import threading

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from agents.base_agent import BaseAgent
from core.event_bus import EventPriority


class MonitoringAgent(BaseAgent):
    """
    Agent responsible for collecting system health metrics
    """

    def __init__(self, name: str, config, event_bus, logger, database=None):
        """
        Initialize monitoring agent

        Args:
            name: Agent name
            config: Configuration
            event_bus: Event bus
            logger: Logger
            database: Optional database instance
        """
        super().__init__(name, config, event_bus, logger)

        self.database = database
        self.collection_interval = config.get('monitoring.collection_interval', 5)
        self.device_id = config.device_id

        self.metrics_config = config.get_section('monitoring.metrics')

        self.mqtt_client = None
        self.mqtt_connected = False
        self.mqtt_last_latency = 0

        self.sensor_latency = 0
        self.sensor_success_rate = 1.0

        self._power_sim_sag = 0.0

        self._init_mqtt()

    def _init_mqtt(self):
        """Initialize MQTT client for connectivity monitoring"""
        if not self.metrics_config.get('mqtt', {}).get('enabled', False):
            return

        if mqtt is None:
            self.logger.warning("paho-mqtt not installed, MQTT monitoring disabled")
            return

        try:
            broker_host = self.metrics_config['mqtt'].get('broker_host', 'localhost')
            broker_port = self.metrics_config['mqtt'].get('broker_port', 1883)

            try:
                self.mqtt_client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                    client_id=f"{self.device_id}_monitor"
                )
            except AttributeError:
                self.mqtt_client = mqtt.Client(client_id=f"{self.device_id}_monitor")

            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect

            def connect():
                try:
                    self.mqtt_client.connect(broker_host, broker_port, keepalive=60)
                    self.mqtt_client.loop_start()
                except Exception as e:
                    self.logger.warning(f"MQTT broker not reachable ({broker_host}:{broker_port}): {e}")
                    self.mqtt_client = None

            threading.Thread(target=connect, daemon=True).start()

        except Exception as e:
            self.logger.error(f"MQTT initialization failed: {e}")

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            self.mqtt_connected = True
            self.logger.info("Connected to MQTT broker")
        else:
            self.mqtt_connected = False
            self.logger.error(f"MQTT connection failed with code {rc}")

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback"""
        self.mqtt_connected = False
        if rc != 0:
            self.logger.warning(f"MQTT broker disconnected (rc={rc}) — will not auto-reconnect")

    def _run(self):
        """Main monitoring loop"""
        self.logger.info("Monitoring agent started")

        while self._running:
            try:
                metrics = self.collect_metrics()

                self.publish_event(
                    event_type="health.metric",
                    data={
                        "device_id": self.device_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "metrics": metrics
                    },
                    priority=EventPriority.NORMAL
                )

                if self.database:
                    for metric_type, metric_data in metrics.items():
                        if isinstance(metric_data, dict):
                            for metric_name, value in metric_data.items():
                                if isinstance(value, (int, float)):
                                    self.database.store_metric(
                                        device_id=self.device_id,
                                        metric_type=metric_type,
                                        metric_name=metric_name,
                                        value=float(value)
                                    )

            except Exception as e:
                self.logger.error(f"Error collecting metrics: {e}", exc_info=True)

            if not self.wait(self.collection_interval):
                break

        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

    def collect_metrics(self) -> Dict[str, Any]:
        """
        Collect all enabled metrics

        Returns:
            Dictionary of metrics
        """
        metrics = {}

        if self.metrics_config.get('cpu', {}).get('enabled', True):
            metrics['cpu'] = self.collect_cpu_metrics()

        if self.metrics_config.get('memory', {}).get('enabled', True):
            metrics['memory'] = self.collect_memory_metrics()

        if self.metrics_config.get('disk', {}).get('enabled', True):
            metrics['disk'] = self.collect_disk_metrics()

        if self.metrics_config.get('network', {}).get('enabled', True):
            metrics['network'] = self.collect_network_metrics()

        if self.metrics_config.get('mqtt', {}).get('enabled', False):
            metrics['mqtt'] = self.collect_mqtt_metrics()

        if self.metrics_config.get('sensors', {}).get('enabled', False):
            metrics['sensors'] = self.collect_sensor_metrics()

        if self.metrics_config.get('power', {}).get('enabled', True):
            metrics['power'] = self.collect_power_metrics()

        return metrics

    def collect_cpu_metrics(self) -> Dict[str, float]:
        """Collect CPU metrics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)

            cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)

            cpu_freq = psutil.cpu_freq()

            try:
                load_avg = psutil.getloadavg()
            except AttributeError:
                load_avg = (0, 0, 0)

            processes = sorted(
                [(p.info['pid'], p.info['name'], p.info['cpu_percent'])
                 for p in psutil.process_iter(['pid', 'name', 'cpu_percent'])
                 if p.info['cpu_percent']],
                key=lambda x: x[2],
                reverse=True
            )

            top_process_pid = processes[0][0] if processes else 0
            top_process_name = processes[0][1] if processes else "none"
            top_process_cpu = processes[0][2] if processes else 0

            return {
                'cpu_percent': cpu_percent,
                'cpu_count': psutil.cpu_count(),
                'cpu_freq_current': cpu_freq.current if cpu_freq else 0,
                'load_avg_1min': load_avg[0],
                'load_avg_5min': load_avg[1],
                'load_avg_15min': load_avg[2],
                'top_process_name': top_process_name,
                'top_process_cpu': top_process_cpu,
                'top_process_pid': top_process_pid,
            }
        except Exception as e:
            self.logger.error(f"Error collecting CPU metrics: {e}")
            return {}

    def collect_memory_metrics(self) -> Dict[str, float]:
        """Collect memory metrics"""
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()

            processes = sorted(
                [(p.info['name'], p.info['memory_percent'])
                 for p in psutil.process_iter(['name', 'memory_percent'])
                 if p.info['memory_percent']],
                key=lambda x: x[1],
                reverse=True
            )

            top_process_name = processes[0][0] if processes else "none"
            top_process_mem = processes[0][1] if processes else 0

            return {
                'memory_percent': mem.percent,
                'memory_total_mb': mem.total / (1024 * 1024),
                'memory_available_mb': mem.available / (1024 * 1024),
                'memory_used_mb': mem.used / (1024 * 1024),
                'swap_percent': swap.percent,
                'swap_used_mb': swap.used / (1024 * 1024),
                'top_process_name': top_process_name,
                'top_process_memory': top_process_mem
            }
        except Exception as e:
            self.logger.error(f"Error collecting memory metrics: {e}")
            return {}

    def collect_disk_metrics(self) -> Dict[str, float]:
        """Collect disk metrics"""
        try:
            disk = psutil.disk_usage('/')
            disk_io = psutil.disk_io_counters()

            return {
                'disk_percent': disk.percent,
                'disk_total_gb': disk.total / (1024 ** 3),
                'disk_used_gb': disk.used / (1024 ** 3),
                'disk_free_gb': disk.free / (1024 ** 3),
                'disk_read_mb': disk_io.read_bytes / (1024 * 1024) if disk_io else 0,
                'disk_write_mb': disk_io.write_bytes / (1024 * 1024) if disk_io else 0,
            }
        except Exception as e:
            self.logger.error(f"Error collecting disk metrics: {e}")
            return {}

    def collect_network_metrics(self) -> Dict[str, Any]:
        """Collect network metrics including ping tests"""
        try:
            net_io = psutil.net_io_counters()

            ping_hosts = self.metrics_config.get('network', {}).get('ping_hosts', ['8.8.8.8'])
            ping_results = {}
            packet_loss_total = 0
            latency_total = 0
            latency_count = 0

            for host in ping_hosts[:2]:
                ping_success, latency, loss = self._ping(host)
                ping_results[host] = {
                    'success': ping_success,
                    'latency_ms': latency,
                    'packet_loss': loss
                }
                packet_loss_total += loss
                if ping_success and latency > 0:
                    latency_total += latency
                    latency_count += 1

            avg_packet_loss = packet_loss_total / len(ping_hosts) if ping_hosts else 0
            avg_latency = latency_total / latency_count if latency_count > 0 else 0

            return {
                'bytes_sent_mb': net_io.bytes_sent / (1024 * 1024),
                'bytes_recv_mb': net_io.bytes_recv / (1024 * 1024),
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv,
                'errors_in': net_io.errin,
                'errors_out': net_io.errout,
                'ping_success': any(r['success'] for r in ping_results.values()),
                'ping_latency_ms': round(avg_latency, 1),
                'packet_loss_percent': avg_packet_loss,
                'ping_results': ping_results
            }
        except Exception as e:
            self.logger.error(f"Error collecting network metrics: {e}")
            return {}

    def _ping(self, host: str, count: int = 2) -> tuple:
        """
        Ping a host and return results

        Args:
            host: Host to ping
            count: Number of ping attempts

        Returns:
            Tuple of (success: bool, latency_ms: float, packet_loss: float)
        """
        try:
            import platform
            param = '-n' if platform.system().lower() == 'windows' else '-c'

            command = ['ping', param, str(count), host]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                output = result.stdout

                if 'packet loss' in output.lower():
                    import re
                    match = re.search(r'(\d+)%.*loss', output, re.IGNORECASE)
                    packet_loss = float(match.group(1)) if match else 0
                else:
                    packet_loss = 0

                import re
                latency = 0
                match = re.search(r'=\s*[\d.]+/([\d.]+)/', output)
                if match:
                    latency = float(match.group(1))
                else:
                    match = re.search(r'average\s*=\s*([\d.]+)', output, re.IGNORECASE)
                    if match:
                        latency = float(match.group(1))

                return True, latency, packet_loss
            else:
                return False, 0, 100

        except Exception as e:
            self.logger.debug(f"Ping error for {host}: {e}")
            return False, 0, 100

    def collect_mqtt_metrics(self) -> Dict[str, Any]:
        """Collect MQTT connectivity metrics"""
        try:
            latency = 0
            if self.mqtt_client and self.mqtt_connected:
                start_time = time.time()
                try:
                    self.mqtt_client.publish("sentinel/health/ping", "ping", qos=0)
                    latency = (time.time() - start_time) * 1000
                    self.mqtt_last_latency = latency
                except:
                    latency = self.mqtt_last_latency

            return {
                'mqtt_connected': self.mqtt_connected,
                'mqtt_latency_ms': latency,
            }
        except Exception as e:
            self.logger.error(f"Error collecting MQTT metrics: {e}")
            return {
                'mqtt_connected': False,
                'mqtt_latency_ms': 0
            }

    def collect_sensor_metrics(self) -> Dict[str, Any]:
        """
        Collect sensor metrics (placeholder for actual sensor integration)
        In production, this would interface with actual IoT sensors
        """
        try:
            import random

            return {
                'sensor_latency_ms': random.randint(50, 200),
                'sensor_success_rate': random.uniform(0.95, 1.0),
                'sensor_count': 5,
                'sensors_online': 5
            }
        except Exception as e:
            self.logger.error(f"Error collecting sensor metrics: {e}")
            return {}

    def collect_power_metrics(self) -> Dict[str, float]:
        """
        Collect power supply metrics.
        On macOS dev: simulated with realistic IoT power patterns.
        On real IoT hardware: replace body with INA219/INA3221 sensor reads.

        Metrics:
          power_voltage_v — input voltage (V)
          power_current_a — current draw (A)
          power_watts — power consumption (W)
          power_quality — quality score 0-100 (100 = clean supply)
          power_voltage_deviation_pct — % deviation from nominal (for anomaly threshold)
        """
        import random

        nominal_v = float(
            self.metrics_config.get('power', {}).get('nominal_voltage_v', 5.0)
        )

        try:
            cpu_pct = psutil.cpu_percent(interval=0) / 100.0
        except Exception:
            cpu_pct = 0.3

        load_sag = cpu_pct * 0.08
        noise = random.gauss(0, 0.025)
        voltage = nominal_v - load_sag + noise - self._power_sim_sag
        voltage = round(max(2.5, min(7.0, voltage)), 3)

        current = 0.5 + cpu_pct * 2.0 + random.gauss(0, 0.04)
        current = round(max(0.05, current), 3)

        watts = round(voltage * current, 2)

        voltage_dev_pct = round(abs(voltage - nominal_v) / nominal_v * 100.0, 2)

        quality = round(max(0.0, 100.0 - voltage_dev_pct * 8.0), 1)

        return {
            'power_voltage_v': voltage,
            'power_current_a': current,
            'power_watts': watts,
            'power_quality': quality,
            'power_voltage_deviation_pct': voltage_dev_pct,
        }

    def trigger_power_event(self, sag_volts: float = 0.8, duration_seconds: float = 60):
        """
        Inject a simulated power sag for testing purposes.
        The sag is removed automatically after duration_seconds.
        """
        import threading

        self._power_sim_sag = sag_volts
        self.logger.warning(
            f"Power sag simulation started: -{sag_volts:.2f}V for {duration_seconds}s"
        )

        def _reset():
            time.sleep(duration_seconds)
            self._power_sim_sag = 0.0
            self.logger.info("Power sag simulation ended — voltage restored")

        threading.Thread(target=_reset, daemon=True).start()

    def process_event(self, event):
        """
        Process events (monitoring agent mainly publishes, doesn't consume much)

        Args:
            event: Event object
        """
        if event.event_type == "config.updated":
            self.logger.info("Configuration updated, reloading...")
            self.metrics_config = self.config.get_section('monitoring.metrics')
