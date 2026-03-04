"""
Instability Runner — Sentinel AI Simulation Controller
Manages controlled instabilities as separate, killable subprocesses.

Each simulation runs in its OWN process so:
  - The recovery agent can kill it by PID without affecting Sentinel itself
  - Metrics genuinely spike (real CPU/memory usage, not fake events)
  - The full self-healing pipeline is exercised end-to-end

Usage (from dashboard API):
    runner = InstabilityRunner.get_instance()
    runner.start('cpu_spike', duration=60)
    runner.stop('cpu_spike')
    runner.stop_all()
"""

import os
import sys
import time
import threading
import subprocess
import multiprocessing
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

_SCRIPT_DIR = Path(__file__).parent


class SimulationProcess:
    """Tracks a single running simulation subprocess."""

    def __init__(self, name: str, proc: subprocess.Popen, scenario_type: str, duration: float):
        self.name = name
        self.proc = proc
        self.pid = proc.pid
        self.scenario_type = scenario_type
        self.started_at = datetime.now()
        self.duration = duration
        self._timer: Optional[threading.Timer] = None

    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def terminate(self):
        if self.is_alive():
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        if self._timer:
            self._timer.cancel()

    def set_auto_stop(self, callback):
        """Auto-stop after duration."""
        self._timer = threading.Timer(self.duration, callback)
        self._timer.daemon = True
        self._timer.start()


class InstabilityRunner:
    """
    Singleton controller for controlled instability scenarios.
    Runs each scenario as a separate subprocess with a tracked PID.
    """

    _instance: Optional['InstabilityRunner'] = None
    _lock = threading.Lock()

    def __init__(self):
        self._simulations: Dict[str, SimulationProcess] = {}
        self._sim_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'InstabilityRunner':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = InstabilityRunner()
        return cls._instance

    # ── Public API ─────────────────────────────────────────────────────────

    def start(self, scenario: str, duration: float = 60.0, **kwargs) -> Dict:
        """
        Start a named simulation scenario.

        Scenarios:
          cpu_spike      — Burns CPU across multiple cores
          memory_pressure — Allocates a large chunk of RAM
          disk_fill      — Writes temp files to disk

        Returns dict with pid and status.
        """
        handlers = {
            'cpu_spike':        self._start_cpu_spike,
            'memory_pressure':  self._start_memory_pressure,
            'disk_fill':        self._start_disk_fill,
        }
        handler = handlers.get(scenario)
        if not handler:
            return {'success': False, 'error': f'Unknown scenario: {scenario}'}

        with self._sim_lock:
            if scenario in self._simulations and self._simulations[scenario].is_alive():
                return {'success': False, 'error': f'{scenario} is already running'}

        return handler(duration=duration, **kwargs)

    def stop(self, scenario: str) -> Dict:
        """Stop a specific scenario by name."""
        with self._sim_lock:
            sim = self._simulations.pop(scenario, None)
        if sim:
            sim.terminate()
            return {'success': True, 'message': f'Stopped {scenario} (PID: {sim.pid})'}
        return {'success': False, 'error': f'{scenario} is not running'}

    def stop_all(self) -> Dict:
        """Stop all active simulations."""
        with self._sim_lock:
            sims = dict(self._simulations)
            self._simulations.clear()
        stopped = []
        for name, sim in sims.items():
            sim.terminate()
            stopped.append(f'{name}(PID:{sim.pid})')
        return {'success': True, 'stopped': stopped}

    def get_status(self) -> Dict:
        """Return all active simulation details."""
        with self._sim_lock:
            result = {}
            dead = []
            for name, sim in self._simulations.items():
                if sim.is_alive():
                    elapsed = (datetime.now() - sim.started_at).total_seconds()
                    result[name] = {
                        'pid': sim.pid,
                        'type': sim.scenario_type,
                        'elapsed_seconds': round(elapsed, 1),
                        'duration': sim.duration,
                        'remaining_seconds': max(0, round(sim.duration - elapsed, 1))
                    }
                else:
                    dead.append(name)
            for name in dead:
                del self._simulations[name]
        return result

    def get_all_pids(self) -> Dict[str, int]:
        """Return {scenario_name: pid} for all active simulations."""
        with self._sim_lock:
            return {
                name: sim.pid
                for name, sim in self._simulations.items()
                if sim.is_alive()
            }

    def kill_by_pid(self, pid: int) -> bool:
        """Kill a simulation process by PID and remove it from tracking."""
        with self._sim_lock:
            for name, sim in list(self._simulations.items()):
                if sim.pid == pid:
                    sim.terminate()
                    del self._simulations[name]
                    return True
        return False

    # ── Scenario Implementations ───────────────────────────────────────────

    def _start_cpu_spike(self, duration: float = 60.0, **kwargs) -> Dict:
        """Spawn cpu_stress.py as a separate process."""
        cores = max(1, multiprocessing.cpu_count() - 2)
        script = str(_SCRIPT_DIR / 'cpu_stress.py')
        proc = subprocess.Popen(
            [sys.executable, script, str(duration), str(cores)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        sim = SimulationProcess('cpu_spike', proc, 'cpu', duration)
        sim.set_auto_stop(lambda: self._auto_stop('cpu_spike'))
        with self._sim_lock:
            self._simulations['cpu_spike'] = sim
        return {
            'success': True,
            'scenario': 'cpu_spike',
            'pid': proc.pid,
            'duration': duration,
            'cores': cores,
            'message': f'CPU spike started: {cores} cores for {duration}s (PID: {proc.pid})'
        }

    def _start_memory_pressure(self, duration: float = 60.0, mb: int = None, **kwargs) -> Dict:
        """Spawn memory_stress.py as a separate process."""
        import psutil
        available_mb = psutil.virtual_memory().available // (1024 * 1024)
        # Allocate enough to push memory_percent by ~15-20 percentage points
        total_mb = psutil.virtual_memory().total // (1024 * 1024)
        if mb is None:
            mb = min(int(total_mb * 0.20), available_mb - 512)  # 20% of total, leave 512MB free
        mb = max(512, mb)

        script = str(_SCRIPT_DIR / 'memory_stress.py')
        proc = subprocess.Popen(
            [sys.executable, script, str(mb), str(duration)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        sim = SimulationProcess('memory_pressure', proc, 'memory', duration)
        sim.set_auto_stop(lambda: self._auto_stop('memory_pressure'))
        with self._sim_lock:
            self._simulations['memory_pressure'] = sim
        return {
            'success': True,
            'scenario': 'memory_pressure',
            'pid': proc.pid,
            'duration': duration,
            'mb': mb,
            'message': f'Memory pressure started: {mb}MB for {duration}s (PID: {proc.pid})'
        }

    def _start_disk_fill(self, duration: float = 60.0, mb: int = 200, **kwargs) -> Dict:
        """Spawn disk_stress.py as a separate process."""
        script = str(_SCRIPT_DIR / 'disk_stress.py')
        proc = subprocess.Popen(
            [sys.executable, script, str(mb), str(duration)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        sim = SimulationProcess('disk_fill', proc, 'disk', duration)
        sim.set_auto_stop(lambda: self._auto_stop('disk_fill'))
        with self._sim_lock:
            self._simulations['disk_fill'] = sim
        return {
            'success': True,
            'scenario': 'disk_fill',
            'pid': proc.pid,
            'duration': duration,
            'mb': mb,
            'message': f'Disk fill started: {mb}MB for {duration}s (PID: {proc.pid})'
        }

    def _auto_stop(self, scenario: str):
        """Called automatically after duration expires."""
        with self._sim_lock:
            sim = self._simulations.pop(scenario, None)
        if sim and sim.is_alive():
            sim.terminate()
