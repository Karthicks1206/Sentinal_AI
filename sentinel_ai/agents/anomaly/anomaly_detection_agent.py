"""
Anomaly Detection Agent — fully adaptive, threshold-free detection.

All bounds are LEARNED from the live data stream — no hardcoded numbers.

Detection methods (all adaptive):
  1. IQR outlier — Tukey-fence spike (Q3 + k*IQR); k learned from variance
  2. Adaptive z-score — statistical deviation from rolling mean/std
  3. Trend elevation — sustained high readings (time-series pattern)
  4. Rate-of-change — acceleration spike vs. learned change rate
  5. Isolation Forest — multivariate ML (sklearn)
  6. Keras LSTM AE — time-series sequence ML

Anomaly fires only when:
  a) Metric is anomalous for `min_consecutive` readings in a row (persistence gate)
  b) Per-metric cooldown has elapsed (dedup gate)

Confirmed anomalies flow to the Diagnosis Agent, which must confirm a real
error before the Recovery Agent acts. No false alarm → no recovery.
"""

import json
import threading
import uuid
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import numpy as np

try:
    from groq import Groq as _GroqClient
    _GROQ_AVAIL = True
except ImportError:
    _GroqClient = None
    _GROQ_AVAIL = False

try:
    from sklearn.ensemble import IsolationForest
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    from agents.anomaly.keras_lstm_detector import KerasLSTMDetector, KERAS_AVAILABLE
except Exception:
    KerasLSTMDetector = None
    KERAS_AVAILABLE = False

from agents.base_agent import BaseAgent
from core.event_bus import EventPriority


class AdaptiveMetricBaseline:
    """
    Maintains a rolling statistical baseline for a single metric.

    The baseline is built purely from observed values — no seed values,
    no hardcoded thresholds. All anomaly bounds are derived at runtime
    from the IQR / mean / std of the rolling window.

    Improvements over the original implementation:
      • Baseline freeze — while an anomaly is active the rolling window
        is frozen so spike values cannot inflate the baseline and mask
        themselves. The window resumes updating once the metric recovers.
      • Hysteresis — the consecutive-anomaly counter is not reset until
        the metric falls back below (mean + 0.5σ), preventing flapping at
        the detection boundary.
      • EMA shadow — a fast exponential moving average runs in parallel to
        detect sustained drift that the slower rolling window might lag on.
    """

    WARMUP_SAMPLES: int = 30

    EMA_ALPHA: float = 0.15

    def __init__(self, window_size: int = 300):
        self.window: deque = deque(maxlen=window_size)
        self.short_window: deque = deque(maxlen=20)

        self.frozen: bool = False

        self._ema: Optional[float] = None


    @property
    def ready(self) -> bool:
        return len(self.window) >= self.WARMUP_SAMPLES

    def push(self, value: float) -> None:
        self.short_window.append(value)
        if self._ema is None:
            self._ema = value
        else:
            self._ema = self.EMA_ALPHA * value + (1 - self.EMA_ALPHA) * self._ema
        if not self.frozen:
            self.window.append(value)

    def freeze(self):
        """Freeze baseline updates — called when an anomaly is confirmed active."""
        self.frozen = True

    def unfreeze(self):
        """Resume baseline updates — called when the metric has recovered."""
        self.frozen = False

    @property
    def ema(self) -> Optional[float]:
        return self._ema

    def stats(self) -> Optional[Dict[str, float]]:
        """
        Compute and return baseline statistics.
        Returns None during warm-up.
        """
        if not self.ready:
            return None

        arr = np.array(self.window)

        q1, q3 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
        median = float(np.median(arr))
        iqr = q3 - q1

        upper_mild = q3 + 1.5 * iqr
        upper_extreme = q3 + 3.0 * iqr

        clean = arr[arr <= upper_mild] if np.sum(arr <= upper_mild) >= 10 else arr
        mean = float(np.mean(clean))
        std = float(np.std(clean)) or 1e-6

        recent = np.array(self.short_window) if len(self.short_window) >= 5 else arr[-10:]
        diffs = np.diff(recent)
        roc_std = float(np.std(diffs)) if len(diffs) > 1 else 1e-6
        roc_mean = float(np.mean(np.abs(diffs))) if len(diffs) > 1 else 0.0

        return {
            'mean': mean,
            'std': std,
            'median': median,
            'q1': q1,
            'q3': q3,
            'iqr': iqr,
            'upper_mild': upper_mild,
            'upper_extreme': upper_extreme,
            'lower_fence': q1 - 1.5 * iqr,
            'roc_std': roc_std,
            'roc_mean': roc_mean,
        }

    def recent_values(self, n: int = 5) -> List[float]:
        """Return the last n values from the short window."""
        w = list(self.short_window)
        return w[-n:] if len(w) >= n else w


class AnomalyDetectionAgent(BaseAgent):
    """
    Detects anomalies using fully adaptive, learned baselines.
    No static thresholds — all bounds derive from the data stream.
    """

    def __init__(self, name: str, config, event_bus, logger, database=None):
        super().__init__(name, config, event_bus, logger)

        self.database = database
        self.device_id = config.device_id

        self.ad_config = config.get_section('anomaly_detection')
        self.methods_config = self.ad_config.get('methods', {})
        self.ml_config = self.ad_config.get('ml', {})
        self.baseline_config = self.ad_config.get('baseline', {})

        baseline_window = self.baseline_config.get('window_size', 300)
        self._baselines: Dict[str, AdaptiveMetricBaseline] = {}
        self._baseline_window_size: int = baseline_window

        self.metric_windows: Dict[str, deque] = {}

        self.min_consecutive = config.get('anomaly_detection.min_consecutive_readings', 2)
        self.cooldown_minutes = config.get('anomaly_detection.cooldown_minutes', 5)
        self.consecutive_counts: Dict[str, int] = {}
        self.last_fired: Dict[str, datetime] = {}

        self._metric_anomaly_active: Dict[str, bool] = {}

        self.isolation_forest = None
        self.ml_training_data: List[List[float]] = []

        if self.ml_config.get('enabled', False) and SKLEARN_AVAILABLE:
            self._init_isolation_forest()
        elif self.ml_config.get('enabled', False):
            self.logger.warning("scikit-learn not available — Isolation Forest disabled")

        self.lstm_detector = None
        if self.ml_config.get('enabled', False):
            if KERAS_AVAILABLE and KerasLSTMDetector is not None:
                self.lstm_detector = KerasLSTMDetector(logger=self.logger)
            else:
                self.logger.warning("Keras not available — LSTM detector disabled")

        self.excluded_metrics = {
            'disk.disk_read_mb', 'disk.disk_write_mb',
            'network.bytes_sent_mb', 'network.bytes_recv_mb',
            'network.packets_sent', 'network.packets_recv',
            'network.errors_in', 'network.errors_out',
            'network.packet_loss_percent',
            'mqtt.mqtt_latency_ms',
            'cpu.cpu_count', 'cpu.cpu_freq_current',
            'cpu.top_process_cpu',
            'cpu.top_process_pid',
            'cpu.load_avg_1min', 'cpu.load_avg_5min', 'cpu.load_avg_15min',
            'memory.top_process_memory',
            'memory.memory_total_mb',
            'memory.memory_available_mb',
            'memory.memory_used_mb',
            'memory.swap_used_mb',
            'disk.disk_total_gb', 'disk.disk_used_gb', 'disk.disk_free_gb',
            'sensors.sensor_count', 'sensors.sensors_online',
            'power.power_quality',
            'power.power_watts',
            'power.power_voltage_deviation_pct',
        }
        self.excluded_prefixes = ('network.ping_results.',)

        self._groq_client = None
        self._groq_config: Dict = {}
        self._init_anomaly_groq(config)

        self.event_bus.subscribe("health.metric", self.process_event)

        self.logger.info(
            "Anomaly Detection Agent ready — fully adaptive mode "
            f"(warmup: {AdaptiveMetricBaseline.WARMUP_SAMPLES} readings per metric, "
            f"consecutive: {self.min_consecutive}, cooldown: {self.cooldown_minutes} min)"
        )


    def _init_anomaly_groq(self, config):
        """Initialize Groq client for the pre-publish validation gate."""
        if not _GROQ_AVAIL:
            return
        groq_cfg = config.get_section('groq') or {}
        if not groq_cfg.get('enabled', True):
            return
        import os
        from pathlib import Path
        api_key = os.environ.get('GROQ_API_KEY')
        if not api_key:
            try:
                env_path = Path(__file__).parent.parent.parent / '.env'
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        if line.startswith('GROQ_API_KEY='):
                            api_key = line.split('=', 1)[1].strip().strip('"').strip("'")
                            break
            except Exception:
                pass
        if not api_key:
            return
        try:
            self._groq_client = _GroqClient(api_key=api_key)
            self._groq_config = groq_cfg
            self.logger.info(
                "Anomaly gate: Groq validation enabled — "
                "false positives filtered before pipeline entry"
            )
        except Exception as e:
            self.logger.warning(f"Anomaly Groq init failed: {e}")

    def _groq_validate_anomaly(
        self,
        anomaly: Dict,
        top_proc_name: Optional[str],
        top_proc_pct: float,
        kind: str,
    ) -> bool:
        """
        Ask Groq whether this anomaly is a genuine system problem or normal
        user behavior.  Returns True to publish, False to suppress.
        Fail-open: if Groq is unavailable or times out, the anomaly is published.
        """
        if not self._groq_client:
            return True

        try:
            metric = anomaly.get('metric_name', 'unknown')
            value = anomaly.get('value', 0)
            expected = anomaly.get('expected_value', 0)
            severity = anomaly.get('severity', 'medium')

            proc_ctx = (
                f"\nTop process: '{top_proc_name}' using {top_proc_pct:.1f}% {kind.upper()}"
                if top_proc_name
                else ""
            )

            model = self._groq_config.get('model', 'llama-3.3-70b-versatile')

            response = self._groq_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a smart false-positive filter for Sentinel AI. "
                            "Decide if a detected anomaly is a GENUINE system problem "
                            "that needs recovery action, or just normal user activity. "
                            "Browsers (Safari, Chrome), video players, IDEs, Slack, "
                            "and other user-facing apps using high resources while the "
                            "user is actively working is NORMAL and should NOT be flagged. "
                            "Respond ONLY with valid JSON — no markdown."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Anomaly detected:\n"
                            f"- Metric: {metric}\n"
                            f"- Value: {value:.1f} (expected ≈ {expected:.1f})\n"
                            f"- Severity: {severity}"
                            f"{proc_ctx}\n\n"
                            f'Is this a genuine system problem?\n'
                            f'{{"is_genuine": true, "reason": "one sentence"}}'
                        ),
                    },
                ],
                max_tokens=100,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            is_genuine = result.get('is_genuine', True)
            reason = result.get('reason', '')

            if not is_genuine:
                self.logger.info(
                    f"[GROQ GATE] Suppressed {metric}={value:.1f} — {reason}"
                )
            else:
                self.logger.debug(f"[GROQ GATE] Confirmed anomaly {metric}: {reason}")

            return bool(is_genuine)

        except Exception as e:
            self.logger.debug(f"Groq anomaly gate error (publishing anomaly): {e}")
            return True  # fail-open

    def _init_isolation_forest(self):
        try:
            contamination = self.ml_config.get('contamination', 0.1)
            self.isolation_forest = IsolationForest(
                contamination=contamination,
                random_state=42,
                n_estimators=100
            )
            self.logger.info("Isolation Forest initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize Isolation Forest: {e}")

    def _run(self):
        """Periodic baseline maintenance loop (detection is event-driven)."""
        self.logger.info("Anomaly Detection Agent started — adaptive baselines learning...")

        while self._running:
            try:
                self._log_baseline_status()

                min_samples = self.ml_config.get('min_samples_for_training', 50)
                if (self.isolation_forest is not None
                        and len(self.ml_training_data) >= min_samples):
                    self._retrain_model()

            except Exception as e:
                self.logger.error(f"Error in periodic baseline update: {e}")

            update_interval = self.baseline_config.get('update_interval_minutes', 15) * 60
            if not self.wait(update_interval):
                break

    def _log_baseline_status(self):
        """Log how many metrics have completed warm-up."""
        ready = sum(1 for b in self._baselines.values() if b.ready)
        warming = sum(1 for b in self._baselines.values() if not b.ready)
        if self._baselines:
            self.logger.info(
                f"Adaptive baselines: {ready} metrics learned, "
                f"{warming} still warming up"
            )


    def process_event(self, event):
        if event.event_type != "health.metric":
            return

        try:
            metrics = event.data.get('metrics', {})
            device_id = event.data.get('device_id') or self.device_id
            timestamp = event.data.get('timestamp')

            flat_metrics = self._flatten_metrics(metrics)

            if self.lstm_detector is not None:
                self.lstm_detector.add_reading(flat_metrics)

            anomalies = self.detect_anomalies(flat_metrics, timestamp, device_id)

            string_context = {}
            for section, section_data in metrics.items():
                if isinstance(section_data, dict):
                    for k, v in section_data.items():
                        if isinstance(v, str):
                            string_context[f"{section}.{k}"] = v
                            string_context[k] = v

            # Top process context for Groq validation
            top_proc_name = (
                string_context.get('cpu.top_process_name')
                or string_context.get('top_process_name')
            )
            top_proc_cpu = flat_metrics.get('cpu.top_process_cpu', 0.0)
            top_proc_mem = flat_metrics.get('memory.top_process_memory', 0.0)

            for anomaly in anomalies:
                anomaly['context'] = string_context

                if not self._groq_client:
                    # No Groq — publish immediately (guarded by consecutive/cooldown gates)
                    self._publish_anomaly(anomaly, device_id, timestamp)
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
                            'confidence': anomaly.get('confidence', 0.8),
                        })
                else:
                    # Groq gate: validate in background thread, publish only if confirmed
                    # Bypass Groq for hard threshold breaches — they are self-evidently genuine
                    if anomaly.get('type') == 'threshold_breach':
                        self._publish_anomaly(anomaly, device_id, timestamp)
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
                                'confidence': anomaly.get('confidence', 0.95),
                            })
                        continue
                    def _gate(
                        _a=anomaly, _d=device_id, _t=timestamp,
                        _name=top_proc_name, _cpu=top_proc_cpu, _mem=top_proc_mem,
                    ):
                        metric = _a.get('metric_name', '')
                        if 'memory' in metric or 'mem' in metric:
                            ok = self._groq_validate_anomaly(_a, _name, _mem, 'memory')
                        elif 'cpu' in metric:
                            ok = self._groq_validate_anomaly(_a, _name, _cpu, 'cpu')
                        else:
                            ok = self._groq_validate_anomaly(
                                _a, None, 0.0, metric.split('.')[0] if '.' in metric else 'system'
                            )
                        if not ok:
                            return
                        self._publish_anomaly(_a, _d, _t)
                        if self.database:
                            self.database.store_anomaly({
                                'anomaly_id': _a['anomaly_id'],
                                'timestamp': _t,
                                'device_id': _d,
                                'metric_name': _a['metric_name'],
                                'anomaly_type': _a['type'],
                                'severity': _a['severity'],
                                'value': _a['value'],
                                'expected_value': _a.get('expected_value'),
                                'deviation': _a.get('deviation'),
                                'confidence': _a.get('confidence', 0.8),
                            })
                    threading.Thread(target=_gate, daemon=True).start()

        except Exception as e:
            self.logger.error(f"Error processing health metric: {e}", exc_info=True)


    def detect_anomalies(
        self,
        metrics: Dict[str, float],
        timestamp: str,
        device_id: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Run all adaptive detection methods on the current metric snapshot.

        Returns only sustained, non-duplicate anomalies ready to publish
        to the diagnosis pipeline.
        """
        now = datetime.now()
        sustained_anomalies = []
        dev = device_id or self.device_id

        for metric_name, value in metrics.items():
            if not isinstance(value, (int, float)):
                continue
            if metric_name in self.excluded_metrics:
                continue
            if any(metric_name.startswith(p) for p in self.excluded_prefixes):
                continue

            bkey = (dev, metric_name)
            if bkey not in self._baselines:
                self._baselines[bkey] = AdaptiveMetricBaseline(
                    window_size=self._baseline_window_size
                )
                self.metric_windows[bkey] = self._baselines[bkey].window

            baseline = self._baselines[bkey]
            baseline.push(value)

            if not baseline.ready:
                continue

            stats = baseline.stats()
            if stats is None:
                continue

            if self._metric_anomaly_active.get(bkey, False):
                hysteresis_band = stats['mean'] + 0.5 * stats['std']
                if value <= hysteresis_band:
                    self.consecutive_counts[bkey] = 0
                    self._metric_anomaly_active[bkey] = False
                    baseline.unfreeze()

            candidates = []

            # Hard threshold floor — fires even when baseline is contaminated
            hit = self._detect_hard_threshold(metric_name, value)
            if hit:
                candidates.append(hit)

            hit = self._detect_iqr_outlier(metric_name, value, stats)
            if hit:
                candidates.append(hit)

            hit = self._detect_zscore_adaptive(metric_name, value, stats)
            if hit:
                candidates.append(hit)

            hit = self._detect_trend_elevation(metric_name, value, stats, baseline)
            if hit:
                candidates.append(hit)

            hit = self._detect_roc_spike(metric_name, value, stats, baseline)
            if hit:
                candidates.append(hit)

            if baseline.ema is not None:
                ema_drift = baseline.ema - stats['mean']
                if ema_drift > 2.0 * stats['std'] and not candidates:
                    candidates.append({
                        'anomaly_id': str(uuid.uuid4()),
                        'metric_name': metric_name,
                        'type': 'ema_drift',
                        'value': value,
                        'expected_value': stats['mean'],
                        'deviation': ema_drift / max(stats['std'], 1e-6),
                        'severity': 'low',
                        'confidence': 0.65,
                        'baseline': {
                            'mean': round(stats['mean'], 3),
                            'ema': round(baseline.ema, 3),
                            'drift': round(ema_drift, 3),
                        },
                    })

            if candidates:
                self.consecutive_counts[bkey] = (
                    self.consecutive_counts.get(bkey, 0) + 1
                )
            else:
                if not self._metric_anomaly_active.get(bkey, False):
                    self.consecutive_counts[bkey] = 0
                continue

            if self.consecutive_counts[bkey] < self.min_consecutive:
                continue

            last = self.last_fired.get(bkey)
            if last is not None:
                if (now - last).total_seconds() / 60 < self.cooldown_minutes:
                    continue

            sev_rank = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
            best = max(candidates,
                       key=lambda a: sev_rank.get(a.get('severity', 'low'), 0))
            self.last_fired[bkey] = now

            self._metric_anomaly_active[bkey] = True
            baseline.freeze()

            sustained_anomalies.append(best)

        if self.ml_config.get('enabled', False) and self.isolation_forest is not None:
            for ml_a in self._detect_ml_anomalies(metrics):
                key = (dev, 'multivariate_isolation_forest')
                last = self.last_fired.get(key)
                if last is None or (now - last).total_seconds() / 60 >= self.cooldown_minutes:
                    self.last_fired[key] = now
                    sustained_anomalies.append(ml_a)

        if self.lstm_detector is not None and self.lstm_detector.is_trained:
            lstm_a = self.lstm_detector.predict(metrics)
            if lstm_a is not None:
                key = (dev, 'multivariate_lstm')
                last = self.last_fired.get(key)
                if last is None or (now - last).total_seconds() / 60 >= self.cooldown_minutes:
                    self.last_fired[key] = now
                    sustained_anomalies.append(lstm_a)

        return sustained_anomalies

    def _detect_hard_threshold(self, metric_name: str, value: float):
        """Hard threshold floor — guaranteed trigger regardless of baseline state.
        Fires when a metric exceeds its configured absolute limit.
        Prevents contaminated baselines from masking obvious anomalies.
        """
        thresh_cfg = self.methods_config.get('threshold', {})
        if not thresh_cfg.get('enabled', False):
            return None

        # Map bare key and prefixed key to threshold config
        bare = metric_name.split('.')[-1]
        limit = thresh_cfg.get(metric_name) or thresh_cfg.get(bare)
        if limit is None:
            return None
        if value <= limit:
            return None

        excess = (value - limit) / max(limit, 1.0)
        severity = 'critical' if excess > 0.25 else 'high' if excess > 0.10 else 'medium'
        return {
            'anomaly_id': str(__import__('uuid').uuid4()),
            'metric_name': metric_name,
            'type': 'threshold_breach',
            'value': value,
            'expected_value': limit,
            'deviation': round(excess, 3),
            'severity': severity,
            'confidence': 0.95,
            'threshold': limit,
        }

    def _detect_iqr_outlier(
        self,
        metric_name: str,
        value: float,
        stats: Dict
    ) -> Optional[Dict]:
        """
        Tukey-fence IQR outlier detection.

        Mild fence (Q3 + 1.5 * IQR) → medium anomaly
        Extreme fence (Q3 + 3.0 * IQR) → high / critical anomaly

        Both bounds are computed from the learned data distribution —
        there are no hardcoded numbers anywhere in this method.
        """
        upper_mild = stats['upper_mild']
        upper_extreme = stats['upper_extreme']

        if value <= upper_mild:
            return None

        if value >= upper_extreme:
            excess = (value - upper_extreme) / max(stats['iqr'], 1e-6)
            severity = 'critical' if excess > 2.0 else 'high'
            confidence = min(0.97, 0.80 + excess * 0.05)
        else:
            excess = (value - upper_mild) / max(stats['iqr'], 1e-6)
            severity = 'medium'
            confidence = min(0.85, 0.65 + excess * 0.10)

        return {
            'anomaly_id': str(uuid.uuid4()),
            'metric_name': metric_name,
            'type': 'iqr_outlier',
            'value': value,
            'expected_value': stats['q3'],
            'deviation': value - stats['upper_mild'],
            'severity': severity,
            'confidence': confidence,
            'baseline': {
                'upper_mild': round(upper_mild, 3),
                'upper_extreme': round(upper_extreme, 3),
                'iqr': round(stats['iqr'], 3),
            },
        }

    def _detect_zscore_adaptive(
        self,
        metric_name: str,
        value: float,
        stats: Dict
    ) -> Optional[Dict]:
        """
        Adaptive z-score detection using the learned mean and std.

        The z-score threshold is 2.5 σ by default but scales with
        the coefficient of variation (CV): metrics that are naturally
        more volatile get a higher tolerance so they don't flood alerts.
        """
        mean = stats['mean']
        std = stats['std']

        z = abs((value - mean) / std)

        cv = std / max(abs(mean), 1e-6)
        z_threshold = self.methods_config.get('z_score', {}).get('threshold', 2.5)
        if cv > 0.30:
            z_threshold += 0.5

        if z < z_threshold:
            return None

        severity = self._severity_from_z(z, z_threshold)
        confidence = min(0.95, 0.50 + (z / z_threshold) * 0.40)

        return {
            'anomaly_id': str(uuid.uuid4()),
            'metric_name': metric_name,
            'type': 'statistical_zscore',
            'value': value,
            'expected_value': mean,
            'deviation': z,
            'severity': severity,
            'confidence': confidence,
            'baseline': {
                'mean': round(mean, 3),
                'std': round(std, 3),
                'z': round(z, 2),
            },
        }

    def _detect_trend_elevation(
        self,
        metric_name: str,
        value: float,
        stats: Dict,
        baseline: AdaptiveMetricBaseline,
    ) -> Optional[Dict]:
        """
        Time-series trend detection: fires when the last N readings are
        all consistently above the learned normal band.

        This catches gradual increases that no single-point method would
        flag (e.g. memory creeping up over 10 minutes).
        """
        recent = baseline.recent_values(n=5)
        if len(recent) < 5:
            return None

        elev_threshold = stats['mean'] + 1.5 * stats['std']

        sustained = all(v > elev_threshold for v in recent)
        if not sustained:
            return None

        avg_recent = float(np.mean(recent))
        z = (avg_recent - stats['mean']) / stats['std']
        severity = self._severity_from_z(z, 1.5)

        return {
            'anomaly_id': str(uuid.uuid4()),
            'metric_name': metric_name,
            'type': 'trend_elevation',
            'value': value,
            'expected_value': stats['mean'],
            'deviation': z,
            'severity': severity,
            'confidence': min(0.92, 0.70 + z * 0.05),
            'baseline': {
                'mean': round(stats['mean'], 3),
                'elev_threshold': round(elev_threshold, 3),
                'recent_avg': round(avg_recent, 3),
            },
        }

    def _detect_roc_spike(
        self,
        metric_name: str,
        value: float,
        stats: Dict,
        baseline: AdaptiveMetricBaseline,
    ) -> Optional[Dict]:
        """
        Rate-of-change spike detection.

        Fires when the step-to-step jump is abnormally large compared to
        the learned typical rate of change. Catches sudden vertical spikes
        (e.g. CPU: 20% → 90% in one reading) even if the absolute value
        is not yet above the IQR fence.
        """
        recent = baseline.recent_values(n=2)
        if len(recent) < 2:
            return None

        change = abs(recent[-1] - recent[-2])
        roc_std = stats['roc_std']
        roc_mean = stats['roc_mean']

        spike_limit = roc_mean + 4.0 * roc_std
        if spike_limit < 1e-4 or change <= spike_limit:
            return None

        excess = change / max(spike_limit, 1e-6)
        severity = 'high' if excess > 3.0 else 'medium'
        confidence = min(0.90, 0.65 + (excess - 1.0) * 0.08)

        return {
            'anomaly_id': str(uuid.uuid4()),
            'metric_name': metric_name,
            'type': 'roc_spike',
            'value': value,
            'expected_value': recent[-2],
            'deviation': change,
            'severity': severity,
            'confidence': confidence,
            'baseline': {
                'typical_change': round(roc_mean, 4),
                'spike_limit': round(spike_limit, 4),
                'actual_change': round(change, 4),
            },
        }


    def _detect_ml_anomalies(self, metrics: Dict[str, float]) -> List[Dict]:
        """Isolation Forest multivariate detection."""
        if self.isolation_forest is None or not hasattr(self.isolation_forest, 'estimators_'):
            return []

        try:
            feature_names = sorted(k for k, v in metrics.items()
                                   if isinstance(v, (int, float)))
            features = [metrics[n] for n in feature_names]
            if len(features) < 3:
                return []

            self.ml_training_data.append(features)
            if len(self.ml_training_data) > 10000:
                self.ml_training_data.pop(0)

            min_samples = self.ml_config.get('min_samples_for_training', 50)
            if len(self.ml_training_data) < min_samples:
                return []

            prediction = self.isolation_forest.predict([features])[0]
            score = self.isolation_forest.score_samples([features])[0]

            if prediction == -1:
                return [{
                    'anomaly_id': str(uuid.uuid4()),
                    'metric_name': 'multivariate',
                    'type': 'ml_isolation_forest',
                    'value': 0,
                    'expected_value': 0,
                    'deviation': abs(score),
                    'severity': self._severity_from_z(abs(score), 0.5),
                    'confidence': min(0.95, abs(score)),
                }]
        except Exception as e:
            self.logger.error(f"Isolation Forest error: {e}")

        return []

    def _retrain_model(self):
        """Retrain Isolation Forest on accumulated training data."""
        try:
            min_samples = self.ml_config.get('min_samples_for_training', 50)
            if len(self.ml_training_data) < min_samples:
                return
            self.logger.info(
                f"Retraining Isolation Forest on {len(self.ml_training_data)} samples..."
            )
            self.isolation_forest.fit(self.ml_training_data)
            self.logger.info("Isolation Forest retrained")
        except Exception as e:
            self.logger.error(f"Model retraining failed: {e}")


    def _severity_from_z(self, z: float, base_threshold: float) -> str:
        """Map a z-score (or ratio) to a severity label."""
        ratio = z / max(base_threshold, 1e-6)
        if ratio >= 3.0:
            return 'critical'
        elif ratio >= 2.0:
            return 'high'
        elif ratio >= 1.0:
            return 'medium'
        return 'low'

    _SKIP_FLATTEN_KEYS = {'ping_results'}

    def _flatten_metrics(self, metrics: Dict) -> Dict[str, float]:
        """Flatten nested metrics dict into dot-separated float keys."""
        flat = {}

        def flatten(d, prefix=''):
            for key, value in d.items():
                if key in self._SKIP_FLATTEN_KEYS:
                    continue
                new_key = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    flatten(value, new_key)
                elif isinstance(value, bool):
                    flat[new_key] = float(value)
                elif isinstance(value, (int, float)):
                    flat[new_key] = value
                elif isinstance(value, str):
                    try:
                        flat[new_key] = float(value)
                    except ValueError:
                        pass

        flatten(metrics)
        return flat

    def _publish_anomaly(self, anomaly: Dict, device_id: str, timestamp: str):
        """Publish anomaly event to the bus → triggers Diagnosis Agent."""
        priority = (EventPriority.CRITICAL
                    if anomaly['severity'] == 'critical'
                    else EventPriority.HIGH)

        self.publish_event(
            event_type="anomaly.detected",
            data={
                'device_id': device_id,
                'timestamp': timestamp,
                'anomaly': anomaly,
            },
            priority=priority,
        )

        self.logger.warning(
            f"[ANOMALY] {anomaly['metric_name']} — {anomaly['type']} "
            f"| severity={anomaly['severity']} "
            f"| value={anomaly['value']:.3f} "
            f"| expected≈{anomaly.get('expected_value', 0):.3f} "
            f"| confidence={anomaly.get('confidence', 0):.2f}"
        )
