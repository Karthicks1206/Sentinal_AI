"""
Anomaly Detection Agent - Detects anomalies using statistical methods and ML
Methods: Z-score, spike detection, threshold logic, rolling baselines,
         Isolation Forest (multivariate), Keras LSTM Autoencoder (time-series)
"""

import uuid
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import numpy as np

try:
    from sklearn.ensemble import IsolationForest
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    from agents.anomaly.keras_lstm_detector import KerasLSTMDetector, KERAS_AVAILABLE
except Exception:
    KerasLSTMDetector = None
    KERAS_AVAILABLE   = False

from agents.base_agent import BaseAgent
from core.event_bus import EventPriority


class AnomalyDetectionAgent(BaseAgent):
    """
    Agent responsible for detecting anomalies in system metrics
    """

    def __init__(self, name: str, config, event_bus, logger, database=None):
        """
        Initialize anomaly detection agent

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

        # Anomaly detection configuration
        self.ad_config = config.get_section('anomaly_detection')
        self.methods_config = self.ad_config.get('methods', {})
        self.ml_config = self.ad_config.get('ml', {})
        self.baseline_config = self.ad_config.get('baseline', {})

        # Metric thresholds from monitoring config
        self.thresholds = {
            'cpu_percent': config.get('monitoring.metrics.cpu.threshold_percent', 80),
            'memory_percent': config.get('monitoring.metrics.memory.threshold_percent', 85),
            'disk_percent': config.get('monitoring.metrics.disk.threshold_percent', 90),
            'packet_loss_percent': config.get('monitoring.metrics.network.max_packet_loss_percent', 5)
        }

        # Rolling windows for each metric
        self.window_size = self.methods_config.get('z_score', {}).get('window_size', 100)
        self.metric_windows: Dict[str, deque] = {}

        # Baselines for each metric
        self.baselines: Dict[str, Dict[str, float]] = {}

        # Isolation Forest model
        self.isolation_forest = None
        self.ml_training_data = []

        if self.ml_config.get('enabled', False) and SKLEARN_AVAILABLE:
            self._init_isolation_forest()
        elif self.ml_config.get('enabled', False):
            self.logger.warning("scikit-learn not available, ML-based detection disabled")

        # Keras LSTM Autoencoder (time-series, runs alongside Isolation Forest)
        self.lstm_detector = None
        if self.ml_config.get('enabled', False):
            if KERAS_AVAILABLE and KerasLSTMDetector is not None:
                self.lstm_detector = KerasLSTMDetector(logger=self.logger)
            else:
                self.logger.warning("Keras not available — LSTM detector disabled")

        # Persistence tracking: only fire after N consecutive anomalous readings
        # This prevents one-off spikes (normal process activity) from triggering alerts
        self.min_consecutive = config.get('anomaly_detection.min_consecutive_readings', 3)
        self.cooldown_minutes = config.get('anomaly_detection.cooldown_minutes', 20)
        self.consecutive_counts: Dict[str, int] = {}   # metric -> consecutive anomaly count
        self.last_fired: Dict[str, datetime] = {}      # metric -> last anomaly fire time

        # Cumulative counters, absolute-value metrics, and noisy derived values
        # that should NOT trigger anomaly alerts.
        self.excluded_metrics = {
            # Cumulative I/O counters — always increasing, not meaningful as anomalies
            'disk.disk_read_mb', 'disk.disk_write_mb',
            'network.bytes_sent_mb', 'network.bytes_recv_mb',
            'network.packets_sent', 'network.packets_recv',
            'network.errors_in', 'network.errors_out',
            # Packet loss — highly volatile on macOS (ping blocked by CPU-heavy inference)
            # Use ping_latency_ms instead for network health
            'network.packet_loss_percent',
            # MQTT sub-ms values — too sensitive, normally near 0
            'mqtt.mqtt_latency_ms',
            # CPU static/noisy derived values
            'cpu.cpu_count', 'cpu.cpu_freq_current',
            'cpu.top_process_cpu',        # noisy; top process changes every reading
            'cpu.top_process_pid',        # PID is not a meaningful numeric metric
            'cpu.load_avg_1min',          # correlated with cpu_percent — duplicate signal
            'cpu.load_avg_5min',
            'cpu.load_avg_15min',
            # Memory — track only memory_percent; absolute MB values spike with AI model loads
            'memory.top_process_memory',  # noisy; top process changes every reading
            'memory.memory_total_mb',     # static — never anomalous
            'memory.memory_available_mb', # inverse of memory_used — duplicate signal
            'memory.memory_used_mb',      # absolute MB — spikes when Ollama model loads
            'memory.swap_used_mb',        # spikes on normal paging
            # Disk absolute sizes — not meaningful as anomalies (only % matters)
            'disk.disk_total_gb', 'disk.disk_used_gb', 'disk.disk_free_gb',
            # Sensor count — static
            'sensors.sensor_count', 'sensors.sensors_online',
        }
        # Also exclude any metric whose name contains these substrings
        self.excluded_prefixes = (
            'network.ping_results.',  # deeply nested per-host ping data
        )

        # Subscribe to health metrics
        self.event_bus.subscribe("health.metric", self.process_event)

    def _init_isolation_forest(self):
        """Initialize Isolation Forest model"""
        try:
            contamination = self.ml_config.get('contamination', 0.1)
            self.isolation_forest = IsolationForest(
                contamination=contamination,
                random_state=42,
                n_estimators=100
            )
            self.logger.info("Initialized Isolation Forest model")
        except Exception as e:
            self.logger.error(f"Failed to initialize Isolation Forest: {e}")

    def _run(self):
        """Main loop (anomaly detection is event-driven)"""
        self.logger.info("Anomaly detection agent started (event-driven mode)")

        while self._running:
            # Perform periodic tasks
            try:
                # Update baselines periodically
                self._update_baselines()

                # Retrain ML model if needed
                if self.isolation_forest is not None and len(self.ml_training_data) > self.ml_config.get('min_samples_for_training', 1000):
                    self._retrain_model()

            except Exception as e:
                self.logger.error(f"Error in periodic tasks: {e}")

            # Wait before next iteration
            update_interval = self.baseline_config.get('update_interval_minutes', 15) * 60
            if not self.wait(update_interval):
                break

    def process_event(self, event):
        """
        Process health metric events and detect anomalies

        Args:
            event: Event object
        """
        if event.event_type != "health.metric":
            return

        try:
            metrics = event.data.get('metrics', {})
            device_id = event.data.get('device_id')
            timestamp = event.data.get('timestamp')

            # Flatten metrics for analysis
            flat_metrics = self._flatten_metrics(metrics)

            # Feed LSTM buffer (time-series learning — non-blocking)
            if self.lstm_detector is not None:
                self.lstm_detector.add_reading(flat_metrics)

            # Detect anomalies using various methods
            anomalies = self.detect_anomalies(flat_metrics, timestamp)

            # Build string context (process names etc.) for diagnosis templates
            string_context = {}
            for section, section_data in metrics.items():
                if isinstance(section_data, dict):
                    for k, v in section_data.items():
                        if isinstance(v, str):
                            string_context[f"{section}.{k}"] = v
                            string_context[k] = v

            # Publish anomalies
            for anomaly in anomalies:
                anomaly['context'] = string_context
                self._publish_anomaly(anomaly, device_id, timestamp)

                # Store in database
                if self.database:
                    self.database.store_anomaly({
                        'anomaly_id': anomaly['anomaly_id'],
                        'timestamp': timestamp,
                        'device_id': device_id,
                        'metric_name': anomaly['metric_name'],
                        'anomaly_type': anomaly['type'],
                        'severity': anomaly['severity'],
                        'value': anomaly['value'],
                        'expected_value': anomaly.get('expected_value'),
                        'deviation': anomaly.get('deviation'),
                        'confidence': anomaly.get('confidence', 0.8)
                    })

        except Exception as e:
            self.logger.error(f"Error processing health metric: {e}", exc_info=True)

    def detect_anomalies(self, metrics: Dict[str, float], timestamp: str) -> List[Dict[str, Any]]:
        """
        Detect anomalies using all enabled methods.

        Only fires an anomaly when:
          1. The metric has been anomalous for min_consecutive readings in a row
             (prevents normal process spikes from triggering alerts).
          2. The per-metric cooldown period has elapsed since the last alert.

        Args:
            metrics: Flattened metrics dictionary
            timestamp: Timestamp string

        Returns:
            List of sustained, non-duplicate anomalies ready to publish
        """
        now = datetime.now()
        sustained_anomalies = []

        for metric_name, value in metrics.items():
            # Skip non-numeric values
            if not isinstance(value, (int, float)):
                continue

            # Skip cumulative counters and irrelevant metrics
            if metric_name in self.excluded_metrics:
                continue
            if any(metric_name.startswith(p) for p in self.excluded_prefixes):
                continue

            # Update metric window
            if metric_name not in self.metric_windows:
                self.metric_windows[metric_name] = deque(maxlen=self.window_size)
            self.metric_windows[metric_name].append(value)

            # Run detection methods; collect the best (highest severity) hit per metric
            candidates = []

            if self.methods_config.get('threshold', {}).get('enabled', True):
                a = self._detect_threshold_anomaly(metric_name, value)
                if a:
                    candidates.append(a)

            if self.methods_config.get('z_score', {}).get('enabled', True):
                a = self._detect_zscore_anomaly(metric_name, value)
                if a:
                    candidates.append(a)

            if self.methods_config.get('spike_detection', {}).get('enabled', True):
                a = self._detect_spike_anomaly(metric_name, value)
                if a:
                    candidates.append(a)

            # ── Persistence gate ──────────────────────────────────────────
            if candidates:
                # Metric is anomalous this reading — increment streak
                self.consecutive_counts[metric_name] = (
                    self.consecutive_counts.get(metric_name, 0) + 1
                )
            else:
                # Metric is normal — reset streak
                self.consecutive_counts[metric_name] = 0
                continue  # Nothing to report

            streak = self.consecutive_counts[metric_name]
            if streak < self.min_consecutive:
                # Not sustained long enough — likely a transient spike
                continue

            # ── Cooldown gate ─────────────────────────────────────────────
            last = self.last_fired.get(metric_name)
            if last is not None:
                elapsed_min = (now - last).total_seconds() / 60
                if elapsed_min < self.cooldown_minutes:
                    continue  # Already reported this recently

            # Pick the highest-severity candidate
            sev_rank = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
            best = max(candidates, key=lambda a: sev_rank.get(a.get('severity', 'low'), 0))
            self.last_fired[metric_name] = now
            sustained_anomalies.append(best)

        # ── ML Layer 1: Isolation Forest (multivariate, point-in-time) ──────────
        if self.ml_config.get('enabled', False) and self.isolation_forest is not None:
            ml_anomalies = self._detect_ml_anomalies(metrics)
            for ml_a in ml_anomalies:
                key = 'multivariate_isolation_forest'
                last = self.last_fired.get(key)
                if last is None or (now - last).total_seconds() / 60 >= self.cooldown_minutes:
                    self.last_fired[key] = now
                    sustained_anomalies.append(ml_a)

        # ── ML Layer 2: Keras LSTM Autoencoder (time-series, sequence-level) ──
        if self.lstm_detector is not None and self.lstm_detector.is_trained:
            lstm_a = self.lstm_detector.predict(metrics)
            if lstm_a is not None:
                key = 'multivariate_lstm'
                last = self.last_fired.get(key)
                if last is None or (now - last).total_seconds() / 60 >= self.cooldown_minutes:
                    self.last_fired[key] = now
                    sustained_anomalies.append(lstm_a)

        return sustained_anomalies

    def _detect_threshold_anomaly(self, metric_name: str, value: float) -> Optional[Dict]:
        """Detect anomaly using static thresholds.
        Supports both fully-qualified keys (cpu.cpu_percent) and bare keys (cpu_percent).
        """
        # Try full key first, then the last component (e.g. 'cpu.cpu_percent' -> 'cpu_percent')
        threshold = self.thresholds.get(metric_name) or self.thresholds.get(metric_name.split('.')[-1])
        if threshold is None:
            return None

        if value > threshold:
            severity = self._calculate_severity(value, threshold, threshold * 1.2)

            return {
                'anomaly_id': str(uuid.uuid4()),
                'metric_name': metric_name,
                'type': 'threshold',
                'value': value,
                'expected_value': threshold,
                'deviation': value - threshold,
                'severity': severity,
                'confidence': 0.9
            }

        return None

    def _detect_zscore_anomaly(self, metric_name: str, value: float) -> Optional[Dict]:
        """Detect anomaly using Z-score method"""
        window = self.metric_windows.get(metric_name)

        if not window or len(window) < 10:
            return None

        values = list(window)
        mean = np.mean(values)
        std = np.std(values)

        if std == 0:
            return None

        z_score = abs((value - mean) / std)
        threshold = self.methods_config.get('z_score', {}).get('threshold', 3.0)

        if z_score > threshold:
            severity = self._calculate_severity(z_score, threshold, threshold * 1.5)

            return {
                'anomaly_id': str(uuid.uuid4()),
                'metric_name': metric_name,
                'type': 'statistical_zscore',
                'value': value,
                'expected_value': mean,
                'deviation': z_score,
                'severity': severity,
                'confidence': min(0.95, 0.5 + (z_score / threshold) * 0.4)
            }

        return None

    def _detect_spike_anomaly(self, metric_name: str, value: float) -> Optional[Dict]:
        """Detect sudden spikes in metric values"""
        window = self.metric_windows.get(metric_name)

        if not window or len(window) < 5:
            return None

        # Get recent average (excluding current value)
        recent_values = list(window)[:-1]
        recent_avg = np.mean(recent_values)

        if recent_avg == 0:
            return None

        # Calculate spike ratio
        spike_ratio = value / recent_avg
        multiplier = self.methods_config.get('spike_detection', {}).get('multiplier', 4.0)

        if spike_ratio > multiplier:
            severity = self._calculate_severity(spike_ratio, multiplier, multiplier * 1.5)

            return {
                'anomaly_id': str(uuid.uuid4()),
                'metric_name': metric_name,
                'type': 'spike',
                'value': value,
                'expected_value': recent_avg,
                'deviation': spike_ratio,
                'severity': severity,
                'confidence': 0.85
            }

        return None

    def _detect_ml_anomalies(self, metrics: Dict[str, float]) -> List[Dict]:
        """Detect anomalies using Isolation Forest"""
        if self.isolation_forest is None or not hasattr(self.isolation_forest, 'estimators_'):
            return []

        try:
            # Prepare feature vector
            feature_names = sorted([k for k, v in metrics.items() if isinstance(v, (int, float))])
            features = [metrics[name] for name in feature_names]

            if len(features) < 3:
                return []

            # Add to training data
            self.ml_training_data.append(features)
            if len(self.ml_training_data) > 10000:
                self.ml_training_data.pop(0)

            # Predict if model is trained
            min_samples = self.ml_config.get('min_samples_for_training', 1000)
            if len(self.ml_training_data) >= min_samples:
                prediction = self.isolation_forest.predict([features])[0]
                score = self.isolation_forest.score_samples([features])[0]

                # -1 indicates anomaly
                if prediction == -1:
                    return [{
                        'anomaly_id': str(uuid.uuid4()),
                        'metric_name': 'multivariate',
                        'type': 'ml_isolation_forest',
                        'value': 0,  # Multivariate, no single value
                        'expected_value': 0,
                        'deviation': abs(score),
                        'severity': self._calculate_severity(abs(score), 0.5, 0.7),
                        'confidence': min(0.95, abs(score))
                    }]

        except Exception as e:
            self.logger.error(f"ML anomaly detection error: {e}")

        return []

    def _retrain_model(self):
        """Retrain Isolation Forest model"""
        try:
            min_samples = self.ml_config.get('min_samples_for_training', 1000)
            if len(self.ml_training_data) < min_samples:
                return

            self.logger.info("Retraining Isolation Forest model...")
            self.isolation_forest.fit(self.ml_training_data)
            self.logger.info(f"Model retrained with {len(self.ml_training_data)} samples")

        except Exception as e:
            self.logger.error(f"Model retraining failed: {e}")

    def _update_baselines(self):
        """Update rolling baselines for metrics"""
        for metric_name, window in self.metric_windows.items():
            if len(window) < 10:
                continue

            values = list(window)
            self.baselines[metric_name] = {
                'mean': np.mean(values),
                'std': np.std(values),
                'min': np.min(values),
                'max': np.max(values),
                'median': np.median(values)
            }

    def _calculate_severity(self, value: float, threshold: float, critical_threshold: float) -> str:
        """
        Calculate severity level

        Args:
            value: Current value
            threshold: Warning threshold
            critical_threshold: Critical threshold

        Returns:
            Severity string (low, medium, high, critical)
        """
        if value >= critical_threshold:
            return "critical"
        elif value >= threshold * 1.1:
            return "high"
        elif value >= threshold:
            return "medium"
        else:
            return "low"

    # Keys at any level that should not be recursively flattened
    _SKIP_FLATTEN_KEYS = {'ping_results'}

    def _flatten_metrics(self, metrics: Dict) -> Dict[str, float]:
        """
        Flatten nested metrics dictionary.
        Skips sub-dicts that are purely informational (e.g. ping_results).

        Args:
            metrics: Nested metrics dictionary

        Returns:
            Flattened dictionary
        """
        flat = {}

        def flatten(d, prefix=''):
            for key, value in d.items():
                if key in self._SKIP_FLATTEN_KEYS:
                    continue  # skip deeply nested per-host detail dicts
                new_key = f"{prefix}.{key}" if prefix else key

                if isinstance(value, dict):
                    flatten(value, new_key)
                elif isinstance(value, (int, float, bool)):
                    flat[new_key] = float(value) if isinstance(value, bool) else value
                elif isinstance(value, str):
                    # Try to convert string numbers
                    try:
                        flat[new_key] = float(value)
                    except ValueError:
                        pass

        flatten(metrics)
        return flat

    def _publish_anomaly(self, anomaly: Dict, device_id: str, timestamp: str):
        """
        Publish anomaly event

        Args:
            anomaly: Anomaly dictionary
            device_id: Device ID
            timestamp: Timestamp
        """
        priority = EventPriority.CRITICAL if anomaly['severity'] == 'critical' else EventPriority.HIGH

        self.publish_event(
            event_type="anomaly.detected",
            data={
                'device_id': device_id,
                'timestamp': timestamp,
                'anomaly': anomaly
            },
            priority=priority
        )

        self.logger.warning(
            f"Anomaly detected: {anomaly['metric_name']} - {anomaly['type']} "
            f"(severity: {anomaly['severity']}, value: {anomaly['value']:.2f})"
        )
