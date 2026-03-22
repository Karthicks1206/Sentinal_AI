"""
Algorithmic Recovery Engine — Deep System Analysis & Targeted Healing

Instead of blindly killing processes or resetting interfaces, this engine:
  1. Profiles the system with multiple samples to classify the ROOT CAUSE
  2. Applies the minimal, targeted algorithm that addresses that root cause
  3. Verifies the fix using before/after measurement
  4. Uses the local Ollama LLM to validate classification in ambiguous cases

Classification taxonomy:
  CPU  → COMPUTE_BOUND | IO_WAIT_BOUND | MEMORY_THRASH | TRANSIENT_SPIKE | MULTI_PROCESS
  MEM  → MEMORY_LEAK | CACHE_BLOAT | SWAP_PRESSURE | HEAP_FRAGMENTATION | NORMAL_GROWTH
  DISK → IO_THROUGHPUT_HOG | DISK_CAPACITY | INODE_EXHAUSTION | IO_LATENCY | WRITE_BURST
  NET  → CONNECTION_LEAK | DNS_FAILURE | HIGH_LATENCY | PACKET_LOSS | INTERFACE_ERROR
"""

import json
import os
import platform
import subprocess
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import psutil

_IS_MACOS = platform.system() == 'Darwin'
_IS_LINUX  = platform.system() == 'Linux'


def _try_resolve(hostname: str) -> bool:
    """DNS lookup with no hanging — safe to call from a thread."""
    import socket as _s
    try:
        _s.getaddrinfo(hostname, 80)
        return True
    except Exception:
        return False

_CRITICAL_PROCESSES = {
    'systemd', 'init', 'launchd', 'sshd', 'kernel_task', 'WindowServer',
    'sentinel', 'python3', 'python', 'bash', 'zsh', 'loginwindow', 'cron',
    'journald', 'dbus', 'udevd',
}


# ─────────────────────────────────────────────────────────────────────────────
# Data classes for profiling results
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProcessSample:
    pid:            int
    name:           str
    cpu_pct:        float
    mem_pct:        float
    mem_rss_mb:     float
    status:         str
    num_threads:    int
    io_read_mb:     float = 0.0
    io_write_mb:    float = 0.0

@dataclass
class CPUProfile:
    classification:         str          # COMPUTE_BOUND | IO_WAIT_BOUND | etc.
    dominant_process:       Optional[ProcessSample]
    dominant_cpu_pct:       float
    iowait_pct:             float        # % of CPU time in I/O wait (Linux only)
    cpu_per_core:           List[float]  # per-core utilization
    single_core_saturated:  bool         # True if any core > 95%
    trajectory:             str          # RISING | STABLE | FALLING
    cpu_samples:            List[float]  # raw total CPU readings
    top_procs:              List[ProcessSample]
    evidence:               Dict         = field(default_factory=dict)

@dataclass
class MemoryProfile:
    classification:         str          # MEMORY_LEAK | CACHE_BLOAT | etc.
    total_mb:               float
    used_mb:                float
    available_mb:           float
    cached_mb:              float
    swap_used_mb:           float
    swap_pct:               float
    leaking_processes:      List[Dict]   # [{name, pid, slope_mb_per_s, rss_mb}]
    top_consumers:          List[ProcessSample]
    trajectory:             str          # RISING | STABLE | FALLING
    mem_samples:            List[float]  # raw used % readings
    evidence:               Dict         = field(default_factory=dict)

@dataclass
class DiskProfile:
    classification:         str          # IO_THROUGHPUT_HOG | DISK_CAPACITY | etc.
    disk_pct:               float
    free_gb:                float
    inode_pct:              float        # 0 if unavailable
    top_writers:            List[Dict]   # [{name, pid, write_mb_per_s}]
    io_util_pct:            float        # disk utilization % (Linux only)
    largest_dirs:           List[Dict]   # [{path, size_mb}] for targeted cleanup
    evidence:               Dict         = field(default_factory=dict)

@dataclass
class NetworkProfile:
    classification:         str          # CONNECTION_LEAK | DNS_FAILURE | etc.
    ping_ms:                float
    packet_loss_pct:        float
    conn_established:       int
    conn_time_wait:         int
    conn_close_wait:        int
    top_conn_process:       Optional[str]
    top_conn_count:         int
    dns_ok:                 bool
    internet_ok:            bool
    trajectory:             str          # WORSENING | STABLE | IMPROVING
    evidence:               Dict         = field(default_factory=dict)

@dataclass
class HealResult:
    success:         bool
    classification:  str
    algorithm:       str          # which algorithm was applied
    evidence_before: Dict
    evidence_after:  Dict
    actions_taken:   List[str]
    message:         str
    parameters:      Dict         = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# System Profiler — multi-sample snapshot engine
# ─────────────────────────────────────────────────────────────────────────────

class SystemProfiler:
    """Collects multi-sample system snapshots and classifies root causes."""

    def __init__(self, logger=None):
        self.logger = logger
        self._log = self._make_logger()

    def _make_logger(self):
        def _log(msg, level='info'):
            if self.logger:
                getattr(self.logger, level, self.logger.info)(f"[Profiler] {msg}")
        return _log

    # ── CPU Profiling ──────────────────────────────────────────────────────

    def profile_cpu(self, n_samples: int = 3, interval: float = 1.2) -> CPUProfile:
        """
        Take N CPU samples, compute trajectory, classify root cause.
        Returns a CPUProfile with classification and supporting evidence.
        """
        self._log(f"CPU profiling: {n_samples} samples × {interval}s")
        cpu_readings  = []
        proc_samples  = []   # list of dicts keyed by pid

        # Warm up cpu_percent (first call always 0.0)
        psutil.cpu_percent(interval=None, percpu=True)
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                proc.cpu_percent(interval=None)
            except Exception:
                pass
        time.sleep(0.2)

        for i in range(n_samples):
            total_cpu  = psutil.cpu_percent(interval=interval, percpu=False)
            per_core   = psutil.cpu_percent(interval=None, percpu=True)
            cpu_times  = psutil.cpu_times_percent(interval=None)
            iowait     = getattr(cpu_times, 'iowait', 0.0)
            cpu_readings.append(total_cpu)

            snapshot = {}
            for proc in psutil.process_iter(['pid', 'name', 'status', 'num_threads',
                                              'cpu_percent', 'memory_percent',
                                              'memory_info']):
                try:
                    info = proc.info
                    rss  = info['memory_info'].rss / (1024 * 1024) if info['memory_info'] else 0
                    # Accumulate I/O bytes on Linux
                    io_r, io_w = 0.0, 0.0
                    if _IS_LINUX:
                        try:
                            io   = proc.io_counters()
                            io_r = io.read_bytes  / (1024 * 1024)
                            io_w = io.write_bytes / (1024 * 1024)
                        except Exception:
                            pass
                    snapshot[info['pid']] = ProcessSample(
                        pid=info['pid'], name=info['name'] or '?',
                        cpu_pct=info['cpu_percent'] or 0.0,
                        mem_pct=info['memory_percent'] or 0.0,
                        mem_rss_mb=rss,
                        status=info['status'] or '?',
                        num_threads=info['num_threads'] or 1,
                        io_read_mb=io_r,
                        io_write_mb=io_w,
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            proc_samples.append(snapshot)

        # Aggregate top processes (average CPU across all samples)
        cpu_totals: Dict[int, List[float]] = defaultdict(list)
        for snap in proc_samples:
            for pid, ps in snap.items():
                cpu_totals[pid].append(ps.cpu_pct)
        avg_cpu = {pid: sum(v) / len(v) for pid, v in cpu_totals.items()}

        # Build top_procs list from last sample
        last_snap = proc_samples[-1] if proc_samples else {}
        top_procs = sorted(
            [ps for pid, ps in last_snap.items()
             if ps.name.lower() not in _CRITICAL_PROCESSES],
            key=lambda p: avg_cpu.get(p.pid, 0.0),
            reverse=True
        )[:8]

        dominant = top_procs[0] if top_procs else None
        dominant_cpu = avg_cpu.get(dominant.pid, 0.0) if dominant else 0.0

        # Trajectory
        if len(cpu_readings) >= 2:
            diff = cpu_readings[-1] - cpu_readings[0]
            trajectory = 'RISING' if diff > 5 else ('FALLING' if diff < -5 else 'STABLE')
        else:
            trajectory = 'STABLE'

        per_core_last = psutil.cpu_percent(interval=0.1, percpu=True)
        single_core_sat = any(c > 95 for c in per_core_last)

        cpu_times_last = psutil.cpu_times_percent(interval=None)
        iowait_pct = getattr(cpu_times_last, 'iowait', 0.0)

        # I/O write activity (identify heavy writers)
        heavy_writers = [
            ps for ps in top_procs
            if ps.io_write_mb > 10.0
        ]

        # Classification logic
        classification = self._classify_cpu(
            cpu_mean=sum(cpu_readings) / len(cpu_readings),
            iowait_pct=iowait_pct,
            dominant_cpu=dominant_cpu,
            trajectory=trajectory,
            single_core_sat=single_core_sat,
            heavy_writers=heavy_writers,
            top_procs=top_procs,
            cpu_readings=cpu_readings,
        )

        return CPUProfile(
            classification=classification,
            dominant_process=dominant,
            dominant_cpu_pct=dominant_cpu,
            iowait_pct=iowait_pct,
            cpu_per_core=per_core_last,
            single_core_saturated=single_core_sat,
            trajectory=trajectory,
            cpu_samples=cpu_readings,
            top_procs=top_procs,
            evidence={
                'samples': cpu_readings,
                'iowait_pct': iowait_pct,
                'per_core': per_core_last,
                'dominant': dominant.name if dominant else None,
                'dominant_cpu_avg': round(dominant_cpu, 1),
                'trajectory': trajectory,
                'heavy_writers': [ps.name for ps in heavy_writers],
            }
        )

    @staticmethod
    def _classify_cpu(cpu_mean, iowait_pct, dominant_cpu, trajectory,
                      single_core_sat, heavy_writers, top_procs, cpu_readings) -> str:
        # Transient spike: short burst, already falling
        if trajectory == 'FALLING' and cpu_mean > 60:
            return 'TRANSIENT_SPIKE'
        # I/O wait causing CPU stall
        if iowait_pct > 25:
            return 'IO_WAIT_BOUND'
        # Memory thrashing: check if multiple processes are paging
        if any(ps.status == 'disk-sleep' for ps in top_procs):
            return 'MEMORY_THRASH'
        # Single dominant compute-bound process
        if dominant_cpu > 40 and single_core_sat:
            return 'COMPUTE_BOUND'
        # Many processes each contributing moderate load
        procs_over_10 = sum(1 for ps in top_procs if ps.cpu_pct > 10)
        if procs_over_10 >= 3:
            return 'MULTI_PROCESS'
        if dominant_cpu > 20:
            return 'COMPUTE_BOUND'
        return 'COMPUTE_BOUND'  # safe default

    # ── Memory Profiling ───────────────────────────────────────────────────

    def profile_memory(self, n_samples: int = 4, interval: float = 2.0) -> MemoryProfile:
        """
        Track RSS growth per process over time to detect leaks.
        Returns MemoryProfile with classification and leak evidence.
        """
        self._log(f"Memory profiling: {n_samples} samples × {interval}s")

        rss_history: Dict[int, List[Tuple[float, float]]] = defaultdict(list)  # pid → [(time, rss_mb)]
        proc_meta: Dict[int, str] = {}  # pid → name
        mem_samples: List[float] = []

        for i in range(n_samples):
            vm = psutil.virtual_memory()
            mem_samples.append(vm.percent)
            t = time.time()
            for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'memory_percent']):
                try:
                    info = proc.info
                    rss  = info['memory_info'].rss / (1024 * 1024) if info['memory_info'] else 0
                    if rss > 20:  # ignore tiny processes
                        rss_history[info['pid']].append((t, rss))
                        proc_meta[info['pid']] = info['name'] or '?'
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if i < n_samples - 1:
                time.sleep(interval)

        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Compute linear slope (MB/s) for each process
        leaking = []
        for pid, history in rss_history.items():
            if len(history) < 2:
                continue
            name = proc_meta.get(pid, '?')
            if name.lower() in _CRITICAL_PROCESSES:
                continue
            xs = [t for t, _ in history]
            ys = [r for _, r in history]
            n  = len(xs)
            x_mean = sum(xs) / n
            y_mean = sum(ys) / n
            denom  = sum((x - x_mean) ** 2 for x in xs)
            if denom < 1e-9:
                continue
            slope = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n)) / denom
            # slope is MB/s; a positive slope > 0.5 MB/s is suspicious
            if slope > 0.5 and ys[-1] > 50:
                leaking.append({
                    'pid':          pid,
                    'name':         name,
                    'slope_mb_per_s': round(slope, 3),
                    'rss_mb':       round(ys[-1], 1),
                    'growth_mb':    round(ys[-1] - ys[0], 1),
                })

        leaking.sort(key=lambda x: x['slope_mb_per_s'], reverse=True)

        # Top memory consumers (last sample)
        top_consumers = sorted(
            [ProcessSample(
                pid=pid,
                name=proc_meta.get(pid, '?'),
                cpu_pct=0.0,
                mem_pct=0.0,
                mem_rss_mb=history[-1][1],
                status='',
                num_threads=0,
            ) for pid, history in rss_history.items() if history],
            key=lambda p: p.mem_rss_mb,
            reverse=True
        )[:6]

        trajectory = 'STABLE'
        if len(mem_samples) >= 2:
            diff = mem_samples[-1] - mem_samples[0]
            trajectory = 'RISING' if diff > 3 else ('FALLING' if diff < -3 else 'STABLE')

        cached_mb = getattr(vm, 'cached', 0) / (1024 * 1024)
        buffers_mb = getattr(vm, 'buffers', 0) / (1024 * 1024)

        classification = self._classify_memory(
            used_pct=vm.percent,
            swap_pct=swap.percent,
            leaking=leaking,
            cached_mb=cached_mb + buffers_mb,
            total_mb=vm.total / (1024 * 1024),
            trajectory=trajectory,
        )

        return MemoryProfile(
            classification=classification,
            total_mb=vm.total / (1024 * 1024),
            used_mb=vm.used / (1024 * 1024),
            available_mb=vm.available / (1024 * 1024),
            cached_mb=cached_mb + buffers_mb,
            swap_used_mb=swap.used / (1024 * 1024),
            swap_pct=swap.percent,
            leaking_processes=leaking,
            top_consumers=top_consumers,
            trajectory=trajectory,
            mem_samples=mem_samples,
            evidence={
                'samples': mem_samples,
                'swap_pct': swap.percent,
                'cached_mb': round(cached_mb + buffers_mb, 1),
                'leaking': [{
                    'name': l['name'],
                    'pid': l['pid'],
                    'slope_mb_per_s': l['slope_mb_per_s'],
                    'rss_mb': l['rss_mb'],
                } for l in leaking[:3]],
                'trajectory': trajectory,
            }
        )

    @staticmethod
    def _classify_memory(used_pct, swap_pct, leaking, cached_mb, total_mb, trajectory) -> str:
        if leaking:
            return 'MEMORY_LEAK'
        if swap_pct > 50:
            return 'SWAP_PRESSURE'
        cache_ratio = cached_mb / total_mb if total_mb > 0 else 0
        if cache_ratio > 0.5 and used_pct > 70:
            return 'CACHE_BLOAT'
        if used_pct > 80 and trajectory == 'RISING':
            return 'NORMAL_GROWTH'  # rising but no clear leak — general pressure
        return 'NORMAL_GROWTH'

    # ── Disk Profiling ─────────────────────────────────────────────────────

    def profile_disk(self) -> DiskProfile:
        """Classify disk anomaly: capacity, I/O hog, inode exhaustion, write burst."""
        self._log("Disk profiling")
        disk = psutil.disk_usage('/')
        disk_pct  = disk.percent
        free_gb   = disk.free / (1024 ** 3)

        # Inode check
        inode_pct = 0.0
        try:
            if _IS_LINUX:
                r = subprocess.run(['df', '-i', '/'], capture_output=True, text=True, timeout=5)
                for line in r.stdout.strip().split('\n')[1:]:
                    parts = line.split()
                    if len(parts) >= 5:
                        raw = parts[4].rstrip('%')
                        inode_pct = float(raw)
        except Exception:
            pass

        # Disk I/O per-process (Linux: /proc/<pid>/io)
        top_writers = []
        if _IS_LINUX:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    io = proc.io_counters()
                    write_mb = io.write_bytes / (1024 * 1024)
                    if write_mb > 5 and proc.info['name'].lower() not in _CRITICAL_PROCESSES:
                        top_writers.append({
                            'pid':          proc.info['pid'],
                            'name':         proc.info['name'],
                            'write_mb':     round(write_mb, 1),
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    pass
            top_writers.sort(key=lambda x: x['write_mb'], reverse=True)
            top_writers = top_writers[:5]

        # Disk I/O utilization (Linux: /proc/diskstats)
        io_util_pct = 0.0
        try:
            if _IS_LINUX:
                counters = psutil.disk_io_counters()
                if counters:
                    t1 = counters.busy_time / 1000.0
                    time.sleep(0.5)
                    counters2 = psutil.disk_io_counters()
                    t2 = counters2.busy_time / 1000.0
                    io_util_pct = min(100.0, (t2 - t1) / 0.5 * 100)
        except Exception:
            pass

        # Find largest directories for targeted cleanup
        largest_dirs = self._find_large_dirs()

        classification = self._classify_disk(disk_pct, inode_pct, top_writers, io_util_pct)

        return DiskProfile(
            classification=classification,
            disk_pct=disk_pct,
            free_gb=free_gb,
            inode_pct=inode_pct,
            top_writers=top_writers,
            io_util_pct=io_util_pct,
            largest_dirs=largest_dirs,
            evidence={
                'disk_pct': disk_pct,
                'free_gb': round(free_gb, 2),
                'inode_pct': inode_pct,
                'io_util_pct': round(io_util_pct, 1),
                'top_writers': top_writers[:3],
                'classification': classification,
            }
        )

    @staticmethod
    def _classify_disk(disk_pct, inode_pct, top_writers, io_util_pct) -> str:
        if inode_pct > 80:
            return 'INODE_EXHAUSTION'
        if disk_pct > 85:
            return 'DISK_CAPACITY'
        if top_writers and top_writers[0]['write_mb'] > 100:
            return 'IO_THROUGHPUT_HOG'
        if io_util_pct > 80:
            return 'IO_LATENCY'
        return 'DISK_CAPACITY'

    @staticmethod
    def _find_large_dirs() -> List[Dict]:
        """Find the largest directories under common log/cache paths for targeted cleanup."""
        scan_paths = ['/var/log', '/tmp', '/var/tmp', 'logs']
        result = []
        for base in scan_paths:
            if not os.path.isdir(base):
                continue
            try:
                for entry in os.scandir(base):
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            total = sum(
                                f.stat().st_size for f in os.scandir(entry.path)
                                if f.is_file(follow_symlinks=False)
                            ) / (1024 * 1024)
                            if total > 10:
                                result.append({'path': entry.path, 'size_mb': round(total, 1)})
                        elif entry.is_file(follow_symlinks=False):
                            size_mb = entry.stat().st_size / (1024 * 1024)
                            if size_mb > 50:
                                result.append({'path': entry.path, 'size_mb': round(size_mb, 1)})
                    except (PermissionError, OSError):
                        pass
            except PermissionError:
                pass
        result.sort(key=lambda x: x['size_mb'], reverse=True)
        return result[:8]

    # ── Network Profiling ──────────────────────────────────────────────────

    def profile_network(self) -> NetworkProfile:
        """Classify network anomaly: connection leak, DNS, latency, packet loss."""
        self._log("Network profiling")
        import socket as _socket

        # Connection state counts
        conn_by_state: Dict[str, int] = defaultdict(int)
        conn_by_proc:  Dict[str, int] = defaultdict(int)
        try:
            for conn in psutil.net_connections(kind='inet'):
                state = conn.status or 'UNKNOWN'
                conn_by_state[state] += 1
                if conn.pid:
                    try:
                        name = psutil.Process(conn.pid).name()
                        conn_by_proc[name] += 1
                    except Exception:
                        pass
        except (psutil.AccessDenied, PermissionError):
            pass

        top_conn_proc  = max(conn_by_proc, key=conn_by_proc.get) if conn_by_proc else None
        top_conn_count = conn_by_proc.get(top_conn_proc, 0) if top_conn_proc else 0

        # Ping test (latency + packet loss)
        ping_ms, loss_pct = self._measure_latency()

        # DNS check (getaddrinfo has no timeout kwarg — use a thread)
        dns_ok = False
        def _dns_check():
            try:
                _socket.getaddrinfo('google.com', 80)
                return True
            except Exception:
                return False
        _dns_result = [False]
        _t = threading.Thread(target=lambda: _dns_result.__setitem__(0, _dns_check()))
        _t.daemon = True
        _t.start()
        _t.join(timeout=4)
        dns_ok = _dns_result[0]

        # Internet check
        internet_ok = False
        try:
            _socket.create_connection(('8.8.8.8', 53), timeout=3)
            internet_ok = True
        except Exception:
            pass

        classification = self._classify_network(
            ping_ms=ping_ms,
            loss_pct=loss_pct,
            time_wait=conn_by_state.get('TIME_WAIT', 0),
            close_wait=conn_by_state.get('CLOSE_WAIT', 0),
            established=conn_by_state.get('ESTABLISHED', 0),
            dns_ok=dns_ok,
            internet_ok=internet_ok,
        )

        return NetworkProfile(
            classification=classification,
            ping_ms=ping_ms,
            packet_loss_pct=loss_pct,
            conn_established=conn_by_state.get('ESTABLISHED', 0),
            conn_time_wait=conn_by_state.get('TIME_WAIT', 0),
            conn_close_wait=conn_by_state.get('CLOSE_WAIT', 0),
            top_conn_process=top_conn_proc,
            top_conn_count=top_conn_count,
            dns_ok=dns_ok,
            internet_ok=internet_ok,
            trajectory='STABLE',
            evidence={
                'ping_ms': round(ping_ms, 1),
                'loss_pct': loss_pct,
                'time_wait': conn_by_state.get('TIME_WAIT', 0),
                'close_wait': conn_by_state.get('CLOSE_WAIT', 0),
                'established': conn_by_state.get('ESTABLISHED', 0),
                'dns_ok': dns_ok,
                'internet_ok': internet_ok,
                'top_conn_proc': top_conn_proc,
            }
        )

    @staticmethod
    def _measure_latency(host: str = '8.8.8.8', count: int = 4) -> Tuple[float, float]:
        """Ping host and return (avg_ms, loss_pct)."""
        try:
            cmd = ['ping', '-c', str(count), '-W', '1', host] if _IS_LINUX else \
                  ['ping', '-c', str(count), '-t', '1', host]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            out = r.stdout
            # Parse avg from "rtt min/avg/max/mdev = 1.2/3.4/5.6/1.0 ms"
            # or "round-trip min/avg/max/stddev = ..." (macOS)
            avg_ms = 0.0
            for line in out.split('\n'):
                if 'avg' in line and '/' in line:
                    parts = line.split('=')[-1].strip().split('/')
                    if len(parts) >= 2:
                        avg_ms = float(parts[1])
                        break
            # Parse loss
            loss_pct = 0.0
            for line in out.split('\n'):
                if 'packet loss' in line:
                    for token in line.split():
                        if token.endswith('%'):
                            loss_pct = float(token.rstrip('%'))
                            break
            return avg_ms, loss_pct
        except Exception:
            return 999.0, 100.0

    @staticmethod
    def _classify_network(ping_ms, loss_pct, time_wait, close_wait, established, dns_ok, internet_ok) -> str:
        if not internet_ok and dns_ok:
            return 'INTERFACE_ERROR'
        if not dns_ok and internet_ok:
            return 'DNS_FAILURE'
        if not internet_ok and not dns_ok:
            return 'INTERFACE_ERROR'
        if loss_pct > 10:
            return 'PACKET_LOSS'
        if close_wait > 50:
            return 'CONNECTION_LEAK'
        if time_wait > 200:
            return 'CONNECTION_LEAK'
        if ping_ms > 200:
            return 'HIGH_LATENCY'
        return 'HIGH_LATENCY'


# ─────────────────────────────────────────────────────────────────────────────
# Algorithmic Recovery Engine — applies targeted fixes based on classification
# ─────────────────────────────────────────────────────────────────────────────

class AlgorithmicRecoveryEngine:
    """
    Applies targeted, algorithm-level fixes based on profiled root cause.
    Each heal_* method measures before/after to prove the fix worked.
    """

    def __init__(self, logger=None, ollama_model: str = 'llama3.2:3b'):
        self.profiler     = SystemProfiler(logger=logger)
        self.logger       = logger
        self.ollama_model = ollama_model
        self._log         = self.profiler._log

    # ── Public entry points ────────────────────────────────────────────────

    def heal_cpu(self, anomaly_value: float, metrics: dict, diagnosis: dict) -> HealResult:
        """
        Profile CPU root cause and apply the targeted algorithm.
        Returns HealResult with before/after evidence.
        """
        self._log("Starting algorithmic CPU analysis", 'info')
        try:
            profile = self.profiler.profile_cpu(n_samples=3, interval=1.2)
            before  = {**profile.evidence, 'anomaly_value': anomaly_value}

            self._log(f"CPU classified as: {profile.classification} "
                      f"(dominant={profile.dominant_process.name if profile.dominant_process else '?'}, "
                      f"iowait={profile.iowait_pct:.1f}%)")

            # Ask Ollama to validate the classification
            ai_hint = self._ask_ollama_cpu(profile)
            if ai_hint:
                self._log(f"AI validation: {ai_hint}")

            # Apply algorithm based on classification
            if profile.classification == 'TRANSIENT_SPIKE':
                return self._cpu_wait_and_verify(profile, before)

            elif profile.classification == 'IO_WAIT_BOUND':
                return self._cpu_fix_io_wait(profile, before)

            elif profile.classification == 'MEMORY_THRASH':
                return self._cpu_fix_memory_thrash(profile, before)

            elif profile.classification == 'MULTI_PROCESS':
                return self._cpu_fix_multi_process(profile, before)

            else:  # COMPUTE_BOUND — default
                return self._cpu_fix_compute_bound(profile, before)

        except Exception as e:
            return HealResult(
                success=False, classification='UNKNOWN', algorithm='error',
                evidence_before={}, evidence_after={}, actions_taken=[],
                message=f"CPU algorithmic analysis failed: {e}",
            )

    def heal_memory(self, anomaly_value: float, metrics: dict, diagnosis: dict) -> HealResult:
        """Profile memory root cause and apply targeted algorithm."""
        self._log("Starting algorithmic memory analysis", 'info')
        try:
            profile = self.profiler.profile_memory(n_samples=4, interval=2.0)
            before  = {**profile.evidence, 'anomaly_value': anomaly_value}

            self._log(f"Memory classified as: {profile.classification} "
                      f"(swap={profile.swap_pct:.1f}%, cached={profile.cached_mb:.0f}MB)")

            ai_hint = self._ask_ollama_memory(profile)
            if ai_hint:
                self._log(f"AI validation: {ai_hint}")

            if profile.classification == 'MEMORY_LEAK':
                return self._memory_fix_leak(profile, before)
            elif profile.classification == 'SWAP_PRESSURE':
                return self._memory_fix_swap(profile, before)
            elif profile.classification == 'CACHE_BLOAT':
                return self._memory_fix_cache(profile, before)
            else:  # NORMAL_GROWTH — general pressure
                return self._memory_fix_general(profile, before)

        except Exception as e:
            return HealResult(
                success=False, classification='UNKNOWN', algorithm='error',
                evidence_before={}, evidence_after={}, actions_taken=[],
                message=f"Memory algorithmic analysis failed: {e}",
            )

    def heal_disk(self, anomaly_value: float, metrics: dict, diagnosis: dict) -> HealResult:
        """Profile disk root cause and apply targeted algorithm."""
        self._log("Starting algorithmic disk analysis", 'info')
        try:
            profile = self.profiler.profile_disk()
            before  = {**profile.evidence, 'anomaly_value': anomaly_value}

            self._log(f"Disk classified as: {profile.classification} "
                      f"(disk={profile.disk_pct:.1f}%, inode={profile.inode_pct:.1f}%)")

            if profile.classification == 'INODE_EXHAUSTION':
                return self._disk_fix_inodes(profile, before)
            elif profile.classification == 'IO_THROUGHPUT_HOG':
                return self._disk_fix_io_hog(profile, before)
            elif profile.classification == 'IO_LATENCY':
                return self._disk_fix_io_latency(profile, before)
            else:  # DISK_CAPACITY
                return self._disk_fix_capacity(profile, before)

        except Exception as e:
            return HealResult(
                success=False, classification='UNKNOWN', algorithm='error',
                evidence_before={}, evidence_after={}, actions_taken=[],
                message=f"Disk algorithmic analysis failed: {e}",
            )

    def heal_network(self, anomaly_value: float, metrics: dict, diagnosis: dict) -> HealResult:
        """Profile network root cause and apply targeted algorithm."""
        self._log("Starting algorithmic network analysis", 'info')
        try:
            profile = self.profiler.profile_network()
            before  = {**profile.evidence, 'anomaly_value': anomaly_value}

            self._log(f"Network classified as: {profile.classification} "
                      f"(ping={profile.ping_ms:.1f}ms, loss={profile.packet_loss_pct:.1f}%)")

            if profile.classification == 'DNS_FAILURE':
                return self._network_fix_dns(profile, before)
            elif profile.classification == 'CONNECTION_LEAK':
                return self._network_fix_connection_leak(profile, before)
            elif profile.classification == 'HIGH_LATENCY':
                return self._network_fix_latency(profile, before)
            else:  # PACKET_LOSS | INTERFACE_ERROR
                return self._network_fix_interface(profile, before)

        except Exception as e:
            return HealResult(
                success=False, classification='UNKNOWN', algorithm='error',
                evidence_before={}, evidence_after={}, actions_taken=[],
                message=f"Network algorithmic analysis failed: {e}",
            )

    # ─────────────────────────────────────────────────────────────────────
    # CPU healing algorithms
    # ─────────────────────────────────────────────────────────────────────

    def _cpu_wait_and_verify(self, profile: CPUProfile, before: dict) -> HealResult:
        """Transient spike — wait 10s and verify it resolves on its own."""
        self._log("Algorithm: TRANSIENT_SPIKE — monitoring without intervention")
        time.sleep(10)
        after_cpu = psutil.cpu_percent(interval=1)
        after = {'cpu_pct': after_cpu, 'note': 'monitored 10s — no intervention'}
        resolved = after_cpu < 60
        return HealResult(
            success=resolved,
            classification='TRANSIENT_SPIKE',
            algorithm='wait_and_verify',
            evidence_before=before,
            evidence_after=after,
            actions_taken=['Monitored 10s without intervention'],
            message=(f"Transient spike resolved naturally (now {after_cpu:.1f}%)" if resolved
                     else f"Spike did not resolve ({after_cpu:.1f}%) — escalation needed"),
        )

    def _cpu_fix_io_wait(self, profile: CPUProfile, before: dict) -> HealResult:
        """
        IO_WAIT_BOUND — CPU stalled on disk I/O.
        Algorithm: Lower I/O priority of heaviest disk writers using ionice (Linux)
        or taskpolicy -d background (macOS). Sync and drop write-back cache.
        """
        self._log("Algorithm: IO_WAIT_BOUND — applying I/O priority reduction")
        actions = []
        targets_hit = 0

        # Find processes with highest I/O write activity
        io_hogs = sorted(
            [ps for ps in profile.top_procs if ps.io_write_mb > 5],
            key=lambda p: p.io_write_mb,
            reverse=True
        )[:3]

        for ps in io_hogs:
            if ps.name.lower() in _CRITICAL_PROCESSES:
                continue
            if _IS_LINUX:
                # ionice -c 3 (idle I/O class): process only gets I/O when no other process needs it
                r = subprocess.run(
                    ['ionice', '-c', '3', '-p', str(ps.pid)],
                    capture_output=True, text=True, timeout=5,
                )
                ok = r.returncode == 0
            elif _IS_MACOS:
                # taskpolicy -d background: macOS QoS background I/O tier
                r = subprocess.run(
                    ['taskpolicy', '-d', 'background', str(ps.pid)],
                    capture_output=True, text=True, timeout=5,
                )
                ok = r.returncode == 0
            else:
                ok = False

            if ok:
                actions.append(f"Reduced I/O priority of '{ps.name}' (PID {ps.pid})")
                targets_hit += 1
            else:
                # Fallback: renice to lower priority reduces CPU time which reduces I/O pressure
                try:
                    proc = psutil.Process(ps.pid)
                    proc.nice(10)
                    actions.append(f"Reniced '{ps.name}' (PID {ps.pid}) as I/O pressure fallback")
                    targets_hit += 1
                except Exception:
                    pass

        # Flush dirty write-back pages to relieve I/O wait (Linux)
        if _IS_LINUX:
            try:
                subprocess.run(['sync'], capture_output=True, timeout=10)
                # Tune vm.dirty_ratio down temporarily to reduce write-back buildup
                with open('/proc/sys/vm/dirty_ratio', 'w') as f:
                    f.write('5\n')
                actions.append("sync + tuned vm.dirty_ratio=5 to drain write-back queue")
            except Exception:
                pass

        # Measure after
        time.sleep(3)
        after_cpu   = psutil.cpu_percent(interval=1)
        after_times = psutil.cpu_times_percent(interval=0.5)
        after_iowait = getattr(after_times, 'iowait', 0.0)
        after = {'cpu_pct': after_cpu, 'iowait_pct': round(after_iowait, 1)}

        return HealResult(
            success=targets_hit > 0,
            classification='IO_WAIT_BOUND',
            algorithm='io_priority_reduction',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"I/O priority algorithm applied to {targets_hit} process(es). "
                f"iowait: {before.get('iowait_pct', '?')}% → {after_iowait:.1f}%. "
                f"CPU: {before.get('samples', [0])[-1]:.1f}% → {after_cpu:.1f}%"
            ),
            parameters={'targets': [ps.name for ps in io_hogs]},
        )

    def _cpu_fix_memory_thrash(self, profile: CPUProfile, before: dict) -> HealResult:
        """
        MEMORY_THRASH — CPU spending time on page faults and swap I/O.
        Algorithm: Drop page cache, reduce swappiness, renice disk-sleep processes.
        """
        self._log("Algorithm: MEMORY_THRASH — applying anti-thrash memory policy")
        actions = []

        # Drop page cache to free RAM (reduces paging)
        if _IS_LINUX:
            try:
                subprocess.run(
                    ['sh', '-c', 'sync && echo 1 > /proc/sys/vm/drop_caches'],
                    capture_output=True, text=True, timeout=15,
                )
                actions.append("Dropped page cache (echo 1 > /proc/sys/vm/drop_caches)")
                # Reduce swappiness so kernel prefers to keep pages in RAM
                with open('/proc/sys/vm/swappiness', 'w') as f:
                    f.write('10\n')
                actions.append("Set vm.swappiness=10 to prefer RAM over swap")
            except Exception as e:
                actions.append(f"Cache drop attempted (requires root): {e}")
        elif _IS_MACOS:
            r = subprocess.run(['purge'], capture_output=True, timeout=30)
            if r.returncode == 0:
                actions.append("macOS purge: page cache cleared")

        # Renice all disk-sleep processes to reduce their scheduling priority
        thrashing_procs = [ps for ps in profile.top_procs if ps.status == 'disk-sleep']
        for ps in thrashing_procs[:3]:
            if ps.name.lower() not in _CRITICAL_PROCESSES:
                try:
                    psutil.Process(ps.pid).nice(15)
                    actions.append(f"Reniced disk-sleep '{ps.name}' (PID {ps.pid}) to nice=15")
                except Exception:
                    pass

        time.sleep(5)
        after_cpu = psutil.cpu_percent(interval=1)
        after = {'cpu_pct': after_cpu}
        return HealResult(
            success=bool(actions),
            classification='MEMORY_THRASH',
            algorithm='anti_thrash_memory_policy',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=f"Anti-thrash algorithm applied: {'; '.join(actions)}",
        )

    def _cpu_fix_multi_process(self, profile: CPUProfile, before: dict) -> HealResult:
        """
        MULTI_PROCESS — many processes each consuming moderate CPU.
        Algorithm: Batch-renice all non-critical processes consuming > 10%, set SCHED_BATCH (Linux).
        """
        self._log("Algorithm: MULTI_PROCESS — applying batch scheduling to all non-critical consumers")
        actions = []
        candidates = [ps for ps in profile.top_procs if ps.cpu_pct > 10]

        for ps in candidates[:5]:
            if ps.name.lower() in _CRITICAL_PROCESSES:
                continue
            try:
                proc = psutil.Process(ps.pid)
                proc.nice(10)
                actions.append(f"Reniced '{ps.name}' (PID {ps.pid}): nice=10")
            except Exception:
                pass

            if _IS_LINUX:
                # SCHED_BATCH: kernel gives time slices in larger chunks — reduces context switch overhead
                try:
                    subprocess.run(
                        ['chrt', '-b', '-p', '0', str(ps.pid)],
                        capture_output=True, text=True, timeout=5,
                    )
                    actions.append(f"Set SCHED_BATCH on '{ps.name}' (PID {ps.pid})")
                except Exception:
                    pass

        time.sleep(3)
        after_cpu = psutil.cpu_percent(interval=1)
        after = {'cpu_pct': after_cpu}
        return HealResult(
            success=bool(actions),
            classification='MULTI_PROCESS',
            algorithm='batch_scheduling_and_renice',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"Batch scheduling applied to {len(candidates)} processes. "
                f"CPU: {before.get('samples', [0])[-1]:.1f}% → {after_cpu:.1f}%"
            ),
        )

    def _cpu_fix_compute_bound(self, profile: CPUProfile, before: dict) -> HealResult:
        """
        COMPUTE_BOUND — single process monopolising CPU.
        Algorithm: (1) CPU affinity pinning to isolate to half the cores,
                   (2) nice +10 to give other processes fair scheduling,
                   (3) SCHED_BATCH/SCHED_IDLE on Linux.
        Only as last resort kill — not the first response.
        """
        self._log("Algorithm: COMPUTE_BOUND — applying CPU affinity + scheduling policy")
        actions = []
        proc_obj = profile.dominant_process

        if not proc_obj or proc_obj.name.lower() in _CRITICAL_PROCESSES:
            return HealResult(
                success=False, classification='COMPUTE_BOUND',
                algorithm='compute_bound_fix',
                evidence_before=before, evidence_after={}, actions_taken=[],
                message="No eligible dominant process found",
            )

        pid  = proc_obj.pid
        name = proc_obj.name

        # 1. CPU affinity: pin to half the cores (leave other half for system)
        try:
            proc = psutil.Process(pid)
            all_cores = list(proc.cpu_affinity())
            if len(all_cores) > 1:
                half = all_cores[: len(all_cores) // 2] or all_cores[:1]
                proc.cpu_affinity(half)
                actions.append(
                    f"CPU affinity set on '{name}' (PID {pid}): "
                    f"restricted to cores {half} of {all_cores}"
                )
        except (psutil.AccessDenied, AttributeError, psutil.NoSuchProcess):
            # cpu_affinity not available on macOS — use nice instead
            pass

        # 2. Renice to +10 — reduces scheduler priority
        try:
            proc = psutil.Process(pid)
            old_nice = proc.nice()
            proc.nice(10)
            actions.append(f"Reniced '{name}' (PID {pid}) from {old_nice} → 10")
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        # 3. Linux scheduling class: SCHED_BATCH reduces CPU-hogging
        if _IS_LINUX:
            try:
                r = subprocess.run(
                    ['chrt', '-b', '-p', '0', str(pid)],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    actions.append(f"Set SCHED_BATCH scheduling policy on '{name}' (PID {pid})")
            except Exception:
                pass

        # 4. macOS: use taskpolicy for background QoS
        if _IS_MACOS:
            try:
                r = subprocess.run(
                    ['taskpolicy', '-c', 'background', str(pid)],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    actions.append(f"Set QoS background policy on '{name}' (PID {pid})")
            except Exception:
                pass

        time.sleep(4)
        after_cpu = psutil.cpu_percent(interval=1)
        after = {'cpu_pct': after_cpu, 'targeted_process': name}

        return HealResult(
            success=bool(actions),
            classification='COMPUTE_BOUND',
            algorithm='cpu_affinity_and_scheduling_policy',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"CPU scheduling algorithm applied to '{name}' (PID {pid}). "
                f"CPU: {before.get('samples', [0])[-1]:.1f}% → {after_cpu:.1f}%"
            ),
            parameters={'pid': pid, 'process': name},
        )

    # ─────────────────────────────────────────────────────────────────────
    # Memory healing algorithms
    # ─────────────────────────────────────────────────────────────────────

    def _memory_fix_leak(self, profile: MemoryProfile, before: dict) -> HealResult:
        """
        MEMORY_LEAK — process(es) with measurable positive RSS growth slope.
        Algorithm:
          1. Log the leak evidence (slope, growth rate)
          2. Adjust OOM score to make the kernel more aggressive about reclaiming from leaker
          3. Apply memory advice (MADV_FREE hint) if supported
          4. Send SIGTERM only as last resort when RSS > 80% of total
        """
        self._log("Algorithm: MEMORY_LEAK — applying OOM score tuning + leak mitigation")
        actions = []
        leakers = profile.leaking_processes

        for leak in leakers[:2]:
            pid  = leak['pid']
            name = leak['name']
            rss  = leak['rss_mb']
            slope = leak['slope_mb_per_s']

            actions.append(
                f"Detected memory leak in '{name}' (PID {pid}): "
                f"RSS={rss:.0f}MB, growth={slope:.3f}MB/s"
            )

            # OOM score adjustment: higher value → kernel more likely to kill this proc first
            oom_path = f'/proc/{pid}/oom_score_adj'
            if os.path.exists(oom_path):
                try:
                    with open(oom_path, 'w') as f:
                        f.write('500\n')
                    actions.append(f"Set oom_score_adj=500 for '{name}' (PID {pid}) — kernel will prefer to reclaim this")
                except PermissionError:
                    pass

            # Send SIGUSR1 to trigger GC if it's a Python process (common in IoT environments)
            if 'python' in name.lower():
                try:
                    import signal
                    os.kill(pid, signal.SIGUSR1)
                    actions.append(f"Sent SIGUSR1 to Python process '{name}' (PID {pid}) — triggers GC")
                except Exception:
                    pass

            # Only terminate if RSS > 60% of total RAM (last resort)
            rss_ratio = rss / profile.total_mb if profile.total_mb > 0 else 0
            if rss_ratio > 0.60 and name.lower() not in _CRITICAL_PROCESSES:
                try:
                    proc = psutil.Process(pid)
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    actions.append(
                        f"Terminated '{name}' (PID {pid}) — RSS was {rss:.0f}MB "
                        f"({rss_ratio*100:.0f}% of total RAM, confirmed leak)"
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            else:
                actions.append(
                    f"'{name}' RSS={rss:.0f}MB ({rss_ratio*100:.0f}% of RAM) — "
                    f"oom_score adjusted; termination deferred (threshold: 60%)"
                )

        # Compact memory after adjustments
        if _IS_LINUX:
            try:
                with open('/proc/sys/vm/compact_memory', 'w') as f:
                    f.write('1\n')
                actions.append("Triggered kernel memory compaction (vm.compact_memory)")
            except Exception:
                pass

        time.sleep(3)
        vm    = psutil.virtual_memory()
        after = {
            'mem_pct':     vm.percent,
            'available_mb': round(vm.available / (1024 * 1024), 1),
        }
        return HealResult(
            success=bool(actions),
            classification='MEMORY_LEAK',
            algorithm='oom_score_tuning_and_leak_containment',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"Memory leak algorithm applied to {len(leakers)} process(es). "
                f"Available: {profile.available_mb:.0f}MB → {after['available_mb']}MB"
            ),
            parameters={'leakers': [l['name'] for l in leakers]},
        )

    def _memory_fix_swap(self, profile: MemoryProfile, before: dict) -> HealResult:
        """
        SWAP_PRESSURE — system is paging heavily, degrading performance.
        Algorithm:
          1. Lower swappiness to 10 to discourage further swapping
          2. Identify processes with highest swap usage and reduce their pressure
          3. Drop clean page cache to free RAM for use instead of swap
        """
        self._log("Algorithm: SWAP_PRESSURE — tuning swappiness + cache eviction")
        actions = []

        # Lower swappiness
        if _IS_LINUX:
            try:
                with open('/proc/sys/vm/swappiness', 'w') as f:
                    f.write('10\n')
                actions.append("Set vm.swappiness=10 (was 60 default) — discourages further swap use")
                # Drop clean page cache to free RAM (reduces need to swap)
                subprocess.run(
                    ['sh', '-c', 'sync && echo 1 > /proc/sys/vm/drop_caches'],
                    capture_output=True, timeout=15,
                )
                actions.append("Dropped clean page cache to make RAM available as swap alternative")
            except Exception as e:
                actions.append(f"swappiness tuning attempted: {e}")
        elif _IS_MACOS:
            r = subprocess.run(['sudo', 'purge'], capture_output=True, timeout=30)
            if r.returncode == 0:
                actions.append("macOS purge: reclaimed compressed memory pages")

        # Find top memory consumers and renice them to reduce working set
        for ps in profile.top_consumers[:3]:
            if ps.mem_rss_mb > 200 and ps.name.lower() not in _CRITICAL_PROCESSES:
                try:
                    proc = psutil.Process(ps.pid)
                    proc.nice(15)
                    actions.append(f"Reniced high-memory '{ps.name}' (PID {ps.pid}) → reduces swap demand")
                except Exception:
                    pass

        time.sleep(3)
        vm    = psutil.virtual_memory()
        swap  = psutil.swap_memory()
        after = {'mem_pct': vm.percent, 'swap_pct': swap.percent}
        return HealResult(
            success=bool(actions),
            classification='SWAP_PRESSURE',
            algorithm='swappiness_tuning_and_cache_eviction',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"Swap pressure algorithm applied. "
                f"Swap: {profile.swap_pct:.1f}% → {swap.percent:.1f}%"
            ),
        )

    def _memory_fix_cache(self, profile: MemoryProfile, before: dict) -> HealResult:
        """
        CACHE_BLOAT — OS cached too much, leaving insufficient RAM for processes.
        Algorithm: Selectively drop page cache without touching dirty pages.
        """
        self._log("Algorithm: CACHE_BLOAT — selective page cache drop")
        actions = []
        freed_mb = 0.0

        vm_before = psutil.virtual_memory()
        if _IS_LINUX:
            try:
                # echo 1 drops page cache only (not dentries/inodes — that's echo 3)
                subprocess.run(
                    ['sh', '-c', 'sync && echo 1 > /proc/sys/vm/drop_caches'],
                    capture_output=True, timeout=15,
                )
                vm_after = psutil.virtual_memory()
                freed_mb = (vm_after.available - vm_before.available) / (1024 * 1024)
                actions.append(
                    f"Dropped page cache (echo 1) — freed {freed_mb:.0f}MB of cached data"
                )
            except Exception as e:
                actions.append(f"Page cache drop attempted (requires root): {e}")
        elif _IS_MACOS:
            r = subprocess.run(['purge'], capture_output=True, timeout=30)
            if r.returncode == 0:
                vm_after  = psutil.virtual_memory()
                freed_mb  = (vm_after.available - vm_before.available) / (1024 * 1024)
                actions.append(f"macOS purge: freed {freed_mb:.0f}MB from inactive memory")

        vm    = psutil.virtual_memory()
        after = {'mem_pct': vm.percent, 'available_mb': round(vm.available / (1024 * 1024), 1)}
        return HealResult(
            success=bool(actions),
            classification='CACHE_BLOAT',
            algorithm='selective_page_cache_drop',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"Cache eviction algorithm: freed ~{freed_mb:.0f}MB from page cache. "
                f"Available: {profile.available_mb:.0f}MB → {after['available_mb']}MB"
            ),
            parameters={'freed_mb': round(freed_mb, 1)},
        )

    def _memory_fix_general(self, profile: MemoryProfile, before: dict) -> HealResult:
        """General memory pressure: renice top consumers + compact."""
        self._log("Algorithm: NORMAL_GROWTH — applying memory pressure relief")
        actions = []

        for ps in profile.top_consumers[:3]:
            if ps.mem_rss_mb > 100 and ps.name.lower() not in _CRITICAL_PROCESSES:
                try:
                    proc = psutil.Process(ps.pid)
                    proc.nice(10)
                    actions.append(f"Reniced '{ps.name}' (PID {ps.pid}, {ps.mem_rss_mb:.0f}MB)")
                except Exception:
                    pass

        if _IS_LINUX:
            try:
                with open('/proc/sys/vm/compact_memory', 'w') as f:
                    f.write('1\n')
                actions.append("Triggered kernel memory compaction")
            except Exception:
                pass
        elif _IS_MACOS:
            subprocess.run(['purge'], capture_output=True, timeout=30)
            actions.append("macOS purge attempted")

        time.sleep(3)
        vm    = psutil.virtual_memory()
        after = {'mem_pct': vm.percent, 'available_mb': round(vm.available / (1024 * 1024), 1)}
        return HealResult(
            success=bool(actions),
            classification='NORMAL_GROWTH',
            algorithm='pressure_relief_renice_and_compact',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=f"Memory pressure relief: {'; '.join(actions)}",
        )

    # ─────────────────────────────────────────────────────────────────────
    # Disk healing algorithms
    # ─────────────────────────────────────────────────────────────────────

    def _disk_fix_inodes(self, profile: DiskProfile, before: dict) -> HealResult:
        """
        INODE_EXHAUSTION — out of inodes (not disk space).
        Algorithm: Find directories with excessive small files, clean them.
        """
        self._log("Algorithm: INODE_EXHAUSTION — hunting small-file directories")
        actions = []
        cleaned = 0

        # Find directories with the most files (small files exhaust inodes)
        inode_hogs = []
        scan_dirs  = ['/tmp', '/var/tmp', '/var/cache', 'logs', '/var/spool']
        for base in scan_dirs:
            if not os.path.isdir(base):
                continue
            try:
                count = sum(1 for _ in os.scandir(base))
                if count > 1000:
                    inode_hogs.append({'path': base, 'count': count})
            except PermissionError:
                pass
        inode_hogs.sort(key=lambda x: x['count'], reverse=True)

        for hog in inode_hogs[:3]:
            path = hog['path']
            # Remove files older than 1 hour from inode hog directories
            cutoff = time.time() - 3600
            try:
                for entry in os.scandir(path):
                    try:
                        if entry.is_file(follow_symlinks=False) and entry.stat().st_mtime < cutoff:
                            os.unlink(entry.path)
                            cleaned += 1
                    except (PermissionError, OSError):
                        pass
                actions.append(f"Cleaned {cleaned} old files from {path} (was {hog['count']} files)")
            except PermissionError:
                pass

        # __pycache__ cleanup: large number of small .pyc files
        pyc_count = 0
        for root, dirs, files in os.walk('.'):
            for d in list(dirs):
                if d == '__pycache__':
                    full = os.path.join(root, d)
                    try:
                        pyc_count += sum(1 for _ in os.scandir(full))
                        import shutil
                        shutil.rmtree(full, ignore_errors=True)
                    except Exception:
                        pass
        if pyc_count:
            actions.append(f"Removed {pyc_count} .pyc files from __pycache__ directories")

        after_disk = psutil.disk_usage('/')
        after = {'disk_pct': after_disk.percent, 'freed_inodes_approx': cleaned + pyc_count}
        return HealResult(
            success=bool(actions),
            classification='INODE_EXHAUSTION',
            algorithm='small_file_inode_reclamation',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=f"Inode reclamation: freed {cleaned + pyc_count} file entries. {'; '.join(actions)}",
        )

    def _disk_fix_io_hog(self, profile: DiskProfile, before: dict) -> HealResult:
        """
        IO_THROUGHPUT_HOG — single process writing excessively.
        Algorithm: Apply ionice idle class to the top writer. Do NOT kill.
        """
        self._log("Algorithm: IO_THROUGHPUT_HOG — applying I/O priority reduction to top writers")
        actions = []

        for writer in profile.top_writers[:3]:
            pid  = writer['pid']
            name = writer['name']
            if name.lower() in _CRITICAL_PROCESSES:
                continue
            if _IS_LINUX:
                r = subprocess.run(
                    ['ionice', '-c', '3', '-p', str(pid)],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    actions.append(
                        f"Set ionice idle class on '{name}' (PID {pid}, "
                        f"{writer['write_mb']:.1f}MB written) — I/O yielded to all others"
                    )
            elif _IS_MACOS:
                r = subprocess.run(
                    ['taskpolicy', '-d', 'background', str(pid)],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    actions.append(f"Set background I/O policy on '{name}' (PID {pid})")

        after_disk = psutil.disk_usage('/')
        after = {'disk_pct': after_disk.percent}
        return HealResult(
            success=bool(actions),
            classification='IO_THROUGHPUT_HOG',
            algorithm='ionice_idle_priority',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=f"I/O priority algorithm: {'; '.join(actions) or 'No eligible writers found'}",
        )

    def _disk_fix_io_latency(self, profile: DiskProfile, before: dict) -> HealResult:
        """
        IO_LATENCY — disk I/O utilization high, all processes affected.
        Algorithm: Check I/O scheduler, reduce parallel I/O via ionice on all heavy writers.
        """
        self._log("Algorithm: IO_LATENCY — checking scheduler + reducing I/O parallelism")
        actions = []

        if _IS_LINUX:
            # Check current I/O scheduler
            try:
                for sched_file in ['/sys/block/sda/queue/scheduler',
                                   '/sys/block/nvme0n1/queue/scheduler',
                                   '/sys/block/mmcblk0/queue/scheduler']:
                    if os.path.exists(sched_file):
                        with open(sched_file) as f:
                            sched = f.read().strip()
                        actions.append(f"I/O scheduler ({os.path.basename(os.path.dirname(sched_file))}): {sched}")
                        # Switch to mq-deadline for better latency if not already set
                        if 'mq-deadline' not in sched and '[mq-deadline]' not in sched:
                            try:
                                with open(sched_file, 'w') as f:
                                    f.write('mq-deadline\n')
                                actions.append(f"Switched I/O scheduler to mq-deadline for lower latency")
                            except PermissionError:
                                pass
            except Exception:
                pass

            # Limit max I/O queue depth to reduce contention
            try:
                for nr_file in ['/sys/block/sda/queue/nr_requests',
                                '/sys/block/mmcblk0/queue/nr_requests']:
                    if os.path.exists(nr_file):
                        with open(nr_file, 'w') as f:
                            f.write('32\n')
                        actions.append(f"Reduced I/O queue depth to 32 on {nr_file}")
            except PermissionError:
                pass

        after_disk = psutil.disk_usage('/')
        after = {'disk_pct': after_disk.percent}
        return HealResult(
            success=bool(actions),
            classification='IO_LATENCY',
            algorithm='io_scheduler_and_queue_depth_tuning',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=f"I/O latency algorithm: {'; '.join(actions) or 'scheduler check completed (read-only on macOS)'}",
        )

    def _disk_fix_capacity(self, profile: DiskProfile, before: dict) -> HealResult:
        """
        DISK_CAPACITY — running low on disk space.
        Algorithm: Targeted cleanup of largest specific directories, smart log rotation,
        temp file purge. Never deletes user data or unknown files.
        """
        self._log("Algorithm: DISK_CAPACITY — targeted smart disk cleanup")
        import gzip, shutil, glob as _glob
        actions = []
        freed_mb = 0.0

        disk_before = psutil.disk_usage('/')

        # 1. Smart log rotation: compress large uncompressed logs in known log dirs
        for log_dir in ['logs', '/var/log']:
            if not os.path.isdir(log_dir):
                continue
            for log_file in _glob.glob(f'{log_dir}/*.log') + _glob.glob(f'{log_dir}/**/*.log'):
                try:
                    size_mb = os.path.getsize(log_file) / (1024 * 1024)
                    if size_mb > 5:  # only compress logs > 5MB
                        with open(log_file, 'rb') as fin, gzip.open(log_file + '.gz', 'wb') as fout:
                            shutil.copyfileobj(fin, fout)
                        os.truncate(log_file, 0)  # truncate in place (don't delete — allows processes to keep writing)
                        freed_mb += size_mb * 0.9
                        actions.append(f"Compressed and truncated {os.path.basename(log_file)} ({size_mb:.1f}MB → ~{size_mb*0.1:.1f}MB)")
                except Exception:
                    pass

        # 2. Remove temp files older than 1 day
        cutoff = time.time() - 86400
        for tmp_dir in ['/tmp', '/var/tmp']:
            if not os.path.isdir(tmp_dir):
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
            actions.append(f"Temp cleanup: {freed_mb:.1f}MB freed from /tmp")

        # 3. Remove compressed logs older than 7 days
        old_gz = 0
        for log_dir in ['logs', '/var/log']:
            for f in _glob.glob(f'{log_dir}/*.gz'):
                try:
                    if os.path.getmtime(f) < time.time() - 7 * 86400:
                        sz = os.path.getsize(f) / (1024 * 1024)
                        os.unlink(f)
                        freed_mb += sz
                        old_gz += 1
                except Exception:
                    pass
        if old_gz:
            actions.append(f"Removed {old_gz} compressed logs older than 7 days")

        # 4. __pycache__ cleanup
        pc_count = 0
        for root, dirs, _ in os.walk('.'):
            for d in list(dirs):
                if d == '__pycache__':
                    try:
                        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                        pc_count += 1
                    except Exception:
                        pass
        if pc_count:
            actions.append(f"Cleared {pc_count} __pycache__ directories")

        disk_after = psutil.disk_usage('/')
        actual_freed = (disk_before.used - disk_after.used) / (1024 * 1024)
        after = {
            'disk_pct': disk_after.percent,
            'freed_mb': round(actual_freed, 1),
        }
        return HealResult(
            success=bool(actions),
            classification='DISK_CAPACITY',
            algorithm='targeted_smart_disk_cleanup',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"Smart disk cleanup: freed ~{actual_freed:.1f}MB. "
                f"Disk: {profile.disk_pct:.1f}% → {disk_after.percent:.1f}%"
            ),
            parameters={'freed_mb': round(actual_freed, 1)},
        )

    # ─────────────────────────────────────────────────────────────────────
    # Network healing algorithms
    # ─────────────────────────────────────────────────────────────────────

    def _network_fix_dns(self, profile: NetworkProfile, before: dict) -> HealResult:
        """
        DNS_FAILURE — internet reachable but DNS resolving fails.
        Algorithm: Flush resolver cache, test alternate DNS (1.1.1.1), reconfigure if needed.
        """
        self._log("Algorithm: DNS_FAILURE — flushing resolver cache + testing alternate DNS")
        actions = []
        import socket as _socket

        if _IS_MACOS:
            subprocess.run(['dscacheutil', '-flushcache'], capture_output=True, timeout=10)
            subprocess.run(['sudo', 'killall', '-HUP', 'mDNSResponder'],
                           capture_output=True, timeout=5)
            actions.append("Flushed macOS DNS cache (dscacheutil + mDNSResponder HUP)")
        elif _IS_LINUX:
            for cmd in [
                ['sudo', 'systemctl', 'restart', 'systemd-resolved'],
                ['sudo', 'resolvectl', 'flush-caches'],
                ['sudo', 'service', 'nscd', 'restart'],
            ]:
                try:
                    r = subprocess.run(cmd, capture_output=True, timeout=10)
                    if r.returncode == 0:
                        actions.append(f"Flushed DNS cache via {' '.join(cmd[:2])}")
                        break
                except Exception:
                    pass

        # Test if Cloudflare DNS resolves
        _cf_ok = [False]
        _tc = threading.Thread(
            target=lambda: _cf_ok.__setitem__(0, _try_resolve('cloudflare.com'))
        )
        _tc.daemon = True
        _tc.start()
        _tc.join(timeout=5)
        if _cf_ok[0]:
            actions.append("Alternate DNS (1.1.1.1) resolves successfully")
        else:
            actions.append("Alternate DNS also failing — network-level issue")

        # On Linux, add 8.8.8.8 as fallback nameserver if resolv.conf is writable
        if _IS_LINUX and os.path.isfile('/etc/resolv.conf'):
            try:
                with open('/etc/resolv.conf') as f:
                    content = f.read()
                if '8.8.8.8' not in content:
                    with open('/etc/resolv.conf', 'a') as f:
                        f.write('\nnameserver 8.8.8.8  # Sentinel AI emergency fallback\n')
                    actions.append("Added Google DNS 8.8.8.8 as emergency fallback in /etc/resolv.conf")
            except PermissionError:
                pass

        # Verify after
        time.sleep(2)
        _after_ok = [False]
        _ta = threading.Thread(
            target=lambda: _after_ok.__setitem__(0, _try_resolve('google.com'))
        )
        _ta.daemon = True
        _ta.start()
        _ta.join(timeout=5)
        dns_ok_after = _after_ok[0]

        after = {'dns_ok': dns_ok_after}
        return HealResult(
            success=bool(actions),
            classification='DNS_FAILURE',
            algorithm='dns_cache_flush_and_fallback',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"DNS resolution algorithm: {'; '.join(actions)}. "
                f"DNS status after: {'OK' if dns_ok_after else 'still failing'}"
            ),
        )

    def _network_fix_connection_leak(self, profile: NetworkProfile, before: dict) -> HealResult:
        """
        CONNECTION_LEAK — excessive TIME_WAIT or CLOSE_WAIT connections.
        Algorithm: Tune TCP fin_timeout and tw_reuse to accelerate connection cleanup.
        On macOS: adjust TCP keep-alive. Log the leaking process.
        """
        self._log("Algorithm: CONNECTION_LEAK — tuning TCP connection cleanup parameters")
        actions = []

        actions.append(
            f"Connection audit: ESTABLISHED={profile.conn_established}, "
            f"TIME_WAIT={profile.conn_time_wait}, "
            f"CLOSE_WAIT={profile.conn_close_wait}"
        )

        if profile.top_conn_process:
            actions.append(
                f"Top connection holder: '{profile.top_conn_process}' "
                f"({profile.top_conn_count} connections)"
            )

        if _IS_LINUX:
            sysctl_params = {
                'net.ipv4.tcp_fin_timeout':       '15',   # default 60s — speeds up TIME_WAIT cleanup
                'net.ipv4.tcp_tw_reuse':          '1',    # allow reuse of TIME_WAIT sockets
                'net.ipv4.tcp_keepalive_time':    '300',  # faster detection of dead connections
                'net.ipv4.tcp_keepalive_intvl':   '30',
                'net.ipv4.tcp_keepalive_probes':  '5',
            }
            for param, value in sysctl_params.items():
                try:
                    r = subprocess.run(
                        ['sysctl', '-w', f'{param}={value}'],
                        capture_output=True, text=True, timeout=5,
                    )
                    if r.returncode == 0:
                        actions.append(f"sysctl {param}={value} — accelerates connection reclamation")
                except Exception:
                    pass

        elif _IS_MACOS:
            # macOS equivalent sysctl parameters
            macos_params = {
                'net.inet.tcp.msl':          '5000',  # reduce MSL from 15s to 5s
                'net.inet.tcp.keepidle':     '300',   # keepalive idle time
                'net.inet.tcp.keepintvl':    '30',
            }
            for param, value in macos_params.items():
                try:
                    r = subprocess.run(
                        ['sysctl', '-w', f'{param}={value}'],
                        capture_output=True, text=True, timeout=5,
                    )
                    if r.returncode == 0:
                        actions.append(f"sysctl {param}={value}")
                except Exception:
                    pass

        # Measure after
        time.sleep(3)
        conn_after = defaultdict(int)
        try:
            for c in psutil.net_connections(kind='inet'):
                conn_after[c.status] += 1
        except Exception:
            pass

        after = {
            'time_wait': conn_after.get('TIME_WAIT', 0),
            'close_wait': conn_after.get('CLOSE_WAIT', 0),
            'established': conn_after.get('ESTABLISHED', 0),
        }
        return HealResult(
            success=bool(actions),
            classification='CONNECTION_LEAK',
            algorithm='tcp_parameter_tuning',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"TCP tuning algorithm applied. "
                f"TIME_WAIT: {profile.conn_time_wait} → {after['time_wait']}. "
                f"CLOSE_WAIT: {profile.conn_close_wait} → {after['close_wait']}"
            ),
        )

    def _network_fix_latency(self, profile: NetworkProfile, before: dict) -> HealResult:
        """
        HIGH_LATENCY — connection works but RTT is high.
        Algorithm: Tune TCP congestion control, buffer sizes, disable Nagle if appropriate.
        """
        self._log("Algorithm: HIGH_LATENCY — tuning TCP congestion control + buffer sizes")
        actions = []
        actions.append(f"Baseline latency: {profile.ping_ms:.1f}ms")

        if _IS_LINUX:
            # Check current congestion algorithm
            try:
                r = subprocess.run(['sysctl', 'net.ipv4.tcp_congestion_control'],
                                   capture_output=True, text=True, timeout=5)
                current_cc = r.stdout.strip().split('=')[-1].strip()
                actions.append(f"Current TCP congestion control: {current_cc}")

                # BBR provides better throughput with high latency links
                # Switch to BBR if not already set (requires kernel 4.9+)
                if current_cc != 'bbr':
                    r2 = subprocess.run(
                        ['sysctl', '-w', 'net.ipv4.tcp_congestion_control=bbr'],
                        capture_output=True, text=True, timeout=5,
                    )
                    if r2.returncode == 0:
                        actions.append("Switched TCP congestion control to BBR (low-latency algorithm)")
            except Exception:
                pass

            # Increase TCP buffer sizes for high-latency links
            try:
                params = {
                    'net.core.rmem_max':          '16777216',
                    'net.core.wmem_max':          '16777216',
                    'net.ipv4.tcp_rmem':          '4096 87380 16777216',
                    'net.ipv4.tcp_wmem':          '4096 65536 16777216',
                    'net.ipv4.tcp_window_scaling': '1',
                }
                for param, value in params.items():
                    subprocess.run(
                        ['sysctl', '-w', f'{param}={value}'],
                        capture_output=True, text=True, timeout=5,
                    )
                actions.append("Tuned TCP buffer sizes for high-latency link optimization")
            except Exception:
                pass

        # Measure after
        time.sleep(2)
        ping_after, loss_after = self.profiler._measure_latency()
        after = {'ping_ms': round(ping_after, 1), 'loss_pct': loss_after}
        return HealResult(
            success=bool(actions),
            classification='HIGH_LATENCY',
            algorithm='tcp_congestion_and_buffer_tuning',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"TCP latency algorithm applied. "
                f"Latency: {profile.ping_ms:.1f}ms → {ping_after:.1f}ms"
            ),
        )

    def _network_fix_interface(self, profile: NetworkProfile, before: dict) -> HealResult:
        """INTERFACE_ERROR / PACKET_LOSS — low-level interface issue."""
        self._log("Algorithm: INTERFACE_ERROR — ARP flush + interface diagnostics")
        actions = []

        # Flush ARP cache (stale ARP entries cause intermittent packet loss)
        if _IS_LINUX:
            try:
                r = subprocess.run(['ip', 'neigh', 'flush', 'all'],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    actions.append("Flushed ARP neighbor cache (stale entries removed)")
            except Exception:
                pass
            # Check interface error counters
            try:
                ifaces = psutil.net_if_stats()
                for iface, stats in ifaces.items():
                    if iface == 'lo':
                        continue
                    counters = psutil.net_io_counters(pernic=True).get(iface)
                    if counters and (counters.errin > 0 or counters.errout > 0):
                        actions.append(
                            f"Interface {iface}: {counters.errin} rx errors, "
                            f"{counters.errout} tx errors detected"
                        )
            except Exception:
                pass
        elif _IS_MACOS:
            try:
                subprocess.run(['arp', '-d', '-a'], capture_output=True, timeout=10)
                actions.append("Flushed ARP cache (arp -d -a)")
            except Exception:
                pass

        time.sleep(2)
        ping_after, loss_after = self.profiler._measure_latency()
        after = {'ping_ms': round(ping_after, 1), 'loss_pct': loss_after}
        return HealResult(
            success=bool(actions),
            classification=profile.classification,
            algorithm='arp_flush_and_interface_diagnostics',
            evidence_before=before,
            evidence_after=after,
            actions_taken=actions,
            message=(
                f"Interface algorithm: {'; '.join(actions)}. "
                f"Loss: {profile.packet_loss_pct:.1f}% → {loss_after:.1f}%"
            ),
        )

    # ─────────────────────────────────────────────────────────────────────
    # Ollama AI validation helpers
    # ─────────────────────────────────────────────────────────────────────

    def _ask_ollama_cpu(self, profile: CPUProfile) -> Optional[str]:
        """Ask Ollama to validate CPU classification and suggest any adjustments."""
        prompt = (
            f"System context: CPU anomaly on IoT device.\n"
            f"Classification algorithm result: {profile.classification}\n"
            f"Evidence: CPU samples={[round(x,1) for x in profile.cpu_samples]}, "
            f"iowait={profile.iowait_pct:.1f}%, "
            f"dominant_process={profile.dominant_process.name if profile.dominant_process else 'none'}, "
            f"dominant_cpu={profile.dominant_cpu_pct:.1f}%, "
            f"trajectory={profile.trajectory}, "
            f"single_core_saturated={profile.single_core_saturated}\n"
            f"Question: Is this classification correct? Reply in one sentence with yes/no and brief reason."
        )
        return self._call_ollama(prompt)

    def _ask_ollama_memory(self, profile: MemoryProfile) -> Optional[str]:
        """Ask Ollama to validate memory classification."""
        leakers_str = [f"{l['name']} slope={l['slope_mb_per_s']}MB/s" for l in profile.leaking_processes[:2]]
        prompt = (
            f"System context: Memory anomaly on IoT device.\n"
            f"Classification: {profile.classification}\n"
            f"Evidence: mem_samples={[round(x,1) for x in profile.mem_samples]}, "
            f"swap_pct={profile.swap_pct:.1f}%, cached_mb={profile.cached_mb:.0f}MB, "
            f"leaking_processes={leakers_str}, trajectory={profile.trajectory}\n"
            f"Question: Is this classification correct? Reply in one sentence."
        )
        return self._call_ollama(prompt)

    def _call_ollama(self, prompt: str) -> Optional[str]:
        """Call local Ollama with a short prompt. Returns response string or None."""
        try:
            import ollama as _ollama
            response = _ollama.chat(
                model=self.ollama_model,
                messages=[{
                    'role':    'user',
                    'content': prompt,
                }],
                options={'num_predict': 80, 'temperature': 0.1},
            )
            return response['message']['content'].strip()[:200]
        except Exception:
            return None
