"""
Keras LSTM Autoencoder — Multivariate Time-Series Anomaly Detector
Runs alongside Isolation Forest as a second ML layer.

Architecture:
  Input  →  LSTM Encoder (32 units)  →  RepeatVector
         →  LSTM Decoder (32 units)  →  TimeDistributed Dense
         →  Reconstruction MSE  →  anomaly if error > threshold

Metrics tracked: [cpu_percent, memory_percent, disk_percent]
"""

import os
import time
import threading
import numpy as np
from collections import deque
from typing import Optional, Tuple, List

# Force PyTorch backend and allow MPS fallback for Apple Silicon
os.environ.setdefault('KERAS_BACKEND', 'torch')
os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')

# Silence TF/Keras noise
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')

KERAS_AVAILABLE = False
try:
    import keras
    KERAS_AVAILABLE = True
except ImportError:
    pass


# ── Feature set: the three primary percentage metrics ──────────────────────────
LSTM_FEATURES = ['cpu.cpu_percent', 'memory.memory_percent', 'disk.disk_percent']
N_FEATURES = len(LSTM_FEATURES)
WINDOW = 20          # number of readings per sequence
LATENT  = 32         # LSTM hidden units
MIN_TRAIN_SEQS = 60  # minimum complete sequences before first training


class KerasLSTMDetector:
    """
    LSTM Autoencoder for multivariate anomaly detection on system metrics.
    Thread-safe: model is trained in a background thread, prediction is read-only.
    """

    def __init__(self, logger=None):
        self.logger = logger
        self._lock = threading.Lock()

        # Sliding buffer — appended every 5 s (one reading)
        self._buffer: deque = deque(maxlen=5000)

        # Trained model and error statistics
        self._model = None
        self._err_mean: float = 0.0
        self._err_std:  float = 1.0
        self._trained:  bool  = False
        self._training: bool  = False

        # Anomaly threshold = mean + k * std of training reconstruction errors
        self._k: float = 3.0

        # Track last anomaly to avoid duplicate fires
        self._last_score: float = 0.0

        if KERAS_AVAILABLE:
            self._log("Keras LSTM detector initialised (backend: "
                      f"{keras.backend.backend()}, window={WINDOW}, features={N_FEATURES})")
        else:
            self._log("Keras not available — LSTM detector disabled", level='warning')

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_reading(self, flat_metrics: dict):
        """
        Feed one timestep of metrics into the buffer.
        Call this every time a health.metric event arrives.

        Args:
            flat_metrics: Flattened metric dict (e.g. {'cpu.cpu_percent': 34.2, ...})
        """
        if not KERAS_AVAILABLE:
            return

        row = []
        for feat in LSTM_FEATURES:
            val = flat_metrics.get(feat, 0.0)
            row.append(float(val) if isinstance(val, (int, float)) else 0.0)
        self._buffer.append(row)

        # Trigger background training when enough data accumulated
        n_seqs = max(0, len(self._buffer) - WINDOW + 1)
        if n_seqs >= MIN_TRAIN_SEQS and not self._trained and not self._training:
            threading.Thread(target=self._train, daemon=True).start()

        # Periodic retraining every 500 readings after first training
        if self._trained and len(self._buffer) % 500 == 0 and not self._training:
            threading.Thread(target=self._train, daemon=True).start()

    def predict(self, flat_metrics: dict) -> Optional[dict]:
        """
        Run anomaly detection on the current window.

        Returns an anomaly dict if reconstruction error exceeds the threshold,
        or None if everything is normal / model not yet trained.

        Args:
            flat_metrics: Flattened metric dict for the current reading

        Returns:
            Anomaly dict or None
        """
        if not KERAS_AVAILABLE or not self._trained:
            return None

        with self._lock:
            model     = self._model
            err_mean  = self._err_mean
            err_std   = self._err_std

        if model is None or len(self._buffer) < WINDOW:
            return None

        try:
            seq = np.array(list(self._buffer)[-WINDOW:], dtype='float32')   # (WINDOW, N_FEATURES)
            seq_norm = self._normalise(seq)                                   # scale to [0,1]
            seq_in = seq_norm[np.newaxis, ...]                                # (1, WINDOW, N_FEATURES)

            recon = model.predict(seq_in, verbose=0)                         # (1, WINDOW, N_FEATURES)
            mse   = float(np.mean((seq_in - recon) ** 2))

            self._last_score = mse
            threshold = err_mean + self._k * err_std

            if mse > threshold and threshold > 0:
                import uuid
                excess = (mse - err_mean) / max(err_std, 1e-9)   # how many σ above mean
                severity = self._score_to_severity(excess)
                confidence = min(0.95, 0.6 + (excess / 10))

                return {
                    'anomaly_id':     str(uuid.uuid4()),
                    'metric_name':    'multivariate_lstm',
                    'type':           'ml_lstm_autoencoder',
                    'value':          round(mse, 6),
                    'expected_value': round(err_mean, 6),
                    'deviation':      round(excess, 2),
                    'severity':       severity,
                    'confidence':     round(confidence, 2),
                    'detail':         f"Reconstruction MSE {mse:.4f} > threshold {threshold:.4f} ({excess:.1f}σ)"
                }

        except Exception as e:
            self._log(f"LSTM predict error: {e}", level='error')

        return None

    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def status(self) -> dict:
        return {
            'available':  KERAS_AVAILABLE,
            'trained':    self._trained,
            'training':   self._training,
            'buffer_len': len(self._buffer),
            'err_mean':   round(self._err_mean, 6),
            'err_std':    round(self._err_std,  6),
            'last_score': round(self._last_score, 6),
        }

    # ── Model construction ─────────────────────────────────────────────────────

    def _build_model(self) -> 'keras.Model':
        """Build LSTM Autoencoder"""
        inp = keras.Input(shape=(WINDOW, N_FEATURES), name='input')

        # Encoder
        enc = keras.layers.LSTM(LATENT, activation='tanh', name='encoder')(inp)

        # Bottleneck → repeat for decoder
        rep = keras.layers.RepeatVector(WINDOW, name='repeat')(enc)

        # Decoder
        dec = keras.layers.LSTM(LATENT, activation='tanh',
                                return_sequences=True, name='decoder')(rep)

        # Output reconstruction
        out = keras.layers.TimeDistributed(
            keras.layers.Dense(N_FEATURES), name='reconstruction'
        )(dec)

        model = keras.Model(inp, out, name='lstm_autoencoder')
        model.compile(optimizer=keras.optimizers.Adam(learning_rate=1e-3), loss='mse')
        return model

    # ── Training ───────────────────────────────────────────────────────────────

    def _train(self):
        """Background training thread"""
        self._training = True
        t0 = time.time()
        try:
            buf_snapshot = list(self._buffer)
            sequences = self._make_sequences(buf_snapshot)

            if len(sequences) < MIN_TRAIN_SEQS:
                return

            # Normalise
            sequences_norm = np.array([self._normalise(s) for s in sequences], dtype='float32')

            # Build fresh model (or reuse)
            model = self._build_model()

            # Train — suppress all output
            model.fit(
                sequences_norm, sequences_norm,
                epochs=15,
                batch_size=32,
                validation_split=0.1,
                shuffle=True,
                verbose=0,
                callbacks=[
                    keras.callbacks.EarlyStopping(monitor='val_loss', patience=3,
                                                   restore_best_weights=True)
                ]
            )

            # Compute reconstruction error statistics on training data
            recon  = model.predict(sequences_norm, verbose=0)
            errors = np.mean((sequences_norm - recon) ** 2, axis=(1, 2))
            mean_e = float(np.mean(errors))
            std_e  = float(np.std(errors))

            # Commit atomically
            with self._lock:
                self._model    = model
                self._err_mean = mean_e
                self._err_std  = max(std_e, 1e-9)
                self._trained  = True

            elapsed = time.time() - t0
            self._log(
                f"LSTM trained: {len(sequences_norm)} seqs, "
                f"err_mean={mean_e:.4f} ± {std_e:.4f}, elapsed={elapsed:.1f}s"
            )

        except Exception as e:
            self._log(f"LSTM training failed: {e}", level='error')
        finally:
            self._training = False

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _make_sequences(self, buf: list) -> List[np.ndarray]:
        """Slide a window over the buffer to create training sequences"""
        seqs = []
        for i in range(len(buf) - WINDOW + 1):
            seqs.append(np.array(buf[i: i + WINDOW], dtype='float32'))
        return seqs

    def _normalise(self, seq: np.ndarray) -> np.ndarray:
        """Min-max normalise each feature independently to [0,1]"""
        out = seq.copy()
        for j in range(N_FEATURES):
            col = seq[:, j]
            lo, hi = col.min(), col.max()
            if hi > lo:
                out[:, j] = (col - lo) / (hi - lo)
            else:
                out[:, j] = 0.0
        return out

    @staticmethod
    def _score_to_severity(excess_sigma: float) -> str:
        if excess_sigma >= 8:   return 'critical'
        if excess_sigma >= 5:   return 'high'
        if excess_sigma >= 3:   return 'medium'
        return 'low'

    def _log(self, msg: str, level: str = 'info'):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(f"[KerasLSTM] {msg}")
        else:
            print(f"[KerasLSTM:{level}] {msg}")
