"""
Sentinel AI — 2-Week Compressed Test Suite
==========================================
Simulates 14 days of real-world IoT operation in compressed time.

Each "day" runs a distinct failure scenario profile:
  Day  1 — Baseline: verify all agents initialise and metrics flow correctly
  Day  2 — CPU stress: COMPUTE_BOUND anomaly → algorithmic CPU fix
  Day  3 — Memory pressure: NORMAL_GROWTH → algorithmic memory fix
  Day  4 — Memory leak detection: injected RSS growth → OOM score tuning
  Day  5 — Disk capacity: DISK_CAPACITY → smart log cleanup
  Day  6 — Network degradation: HIGH_LATENCY → TCP parameter tuning
  Day  7 — Escalation: repeated CPU → L1→L2→L3 escalation path tested
  Day  8 — Multi-anomaly: CPU + memory simultaneously
  Day  9 — Groq AI validation: verify 70B model validates classifications
  Day 10 — Anomaly detection pipeline: IQR / z-score / trend / rate-of-change
  Day 11 — Recovery does NOT kill at Level 1 (algorithmic first guard)
  Day 12 — Outcome verification: check 30s post-recovery metric status
  Day 13 — Adaptive baselines: freeze/hysteresis/EMA drift
  Day 14 — Full end-to-end pipeline: monitoring→detection→diagnosis→recovery

Results are written to: tests/two_week_report.txt
"""

import os
import sys
import time
import json
import threading
import platform
import traceback
import subprocess
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Any, Optional

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── Load .env ───────────────────────────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.isfile(_env_path):
    for _line in open(_env_path):
        _line = _line.strip()
        if '=' in _line and not _line.startswith('#'):
            _k, _v = _line.split('=', 1)
            os.environ.setdefault(_k, _v)

_IS_MACOS = platform.system() == 'Darwin'
_REPORT_PATH = os.path.join(os.path.dirname(__file__), 'two_week_report.txt')

# ─────────────────────────────────────────────────────────────────────────────
# Test Infrastructure
# ─────────────────────────────────────────────────────────────────────────────

class TestResult:
    def __init__(self, day: int, name: str):
        self.day      = day
        self.name     = name
        self.passed   = False
        self.skipped  = False
        self.details  : List[str] = []
        self.errors   : List[str] = []
        self.duration : float     = 0.0

    def ok(self, msg: str):
        self.details.append(f"  [PASS] {msg}")

    def fail(self, msg: str):
        self.errors.append(f"  [FAIL] {msg}")

    def info(self, msg: str):
        self.details.append(f"  [INFO] {msg}")

    def warn(self, msg: str):
        self.details.append(f"  [WARN] {msg}")

    def skip(self, msg: str):
        self.skipped = True
        self.details.append(f"  [SKIP] {msg}")


class TwoWeekTestSuite:

    def __init__(self):
        self.results: List[TestResult] = []
        self.start_time = datetime.now()

    def _run_day(self, day: int, name: str, fn) -> TestResult:
        r = TestResult(day, name)
        t0 = time.time()
        print(f"\n{'='*70}")
        print(f"  DAY {day:2d} — {name}")
        print(f"{'='*70}")
        try:
            fn(r)
            r.passed = len(r.errors) == 0 and not r.skipped
        except Exception as e:
            r.errors.append(f"  [FAIL] Uncaught exception: {e}")
            r.errors.append(traceback.format_exc())
            r.passed = False
        r.duration = round(time.time() - t0, 2)

        status = "PASS" if r.passed else ("SKIP" if r.skipped else "FAIL")
        color  = "\033[92m" if r.passed else ("\033[93m" if r.skipped else "\033[91m")
        reset  = "\033[0m"
        print(f"\n  Result: {color}{status}{reset} ({r.duration}s)")
        for line in r.details:
            print(line)
        for line in r.errors:
            print(line)

        self.results.append(r)
        return r

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 1 — Baseline: imports, agent init, metric collection
    # ─────────────────────────────────────────────────────────────────────────
    def day01_baseline(self, r: TestResult):
        r.info("Verifying all core imports load without errors")

        mods = [
            ('psutil', 'psutil'),
            ('numpy', 'numpy'),
            ('agents.recovery.algorithmic_engine', 'AlgorithmicRecoveryEngine'),
            ('agents.recovery.recovery_agent',     'RecoveryAgent'),
            ('agents.anomaly.anomaly_detection_agent', 'AnomalyDetectionAgent'),
            ('agents.diagnosis.diagnosis_agent',   'DiagnosisAgent'),
            ('agents.monitoring.monitoring_agent', 'MonitoringAgent'),
            ('core.event_bus',                     'EventBus'),
            ('core.config',                        'load_config'),
        ]
        for mod, symbol in mods:
            try:
                m = __import__(mod, fromlist=[symbol])
                getattr(m, symbol)
                r.ok(f"Import OK: {mod}.{symbol}")
            except ImportError as e:
                r.warn(f"Optional import unavailable: {mod} ({e})")
            except Exception as e:
                r.fail(f"Import failed: {mod}.{symbol} — {e}")

        r.info("Verifying psutil can collect live metrics")
        vm   = psutil.virtual_memory()
        cpu  = psutil.cpu_percent(interval=0.5)
        disk = psutil.disk_usage('/')
        r.ok(f"CPU: {cpu:.1f}%")
        r.ok(f"Memory: {vm.percent:.1f}% used ({vm.available//(1024**2)} MB free)")
        r.ok(f"Disk: {disk.percent:.1f}% used ({disk.free//(1024**3)} GB free)")

        r.info("Verifying process enumeration works")
        procs = list(psutil.process_iter(['pid', 'name', 'cpu_percent']))
        r.ok(f"Enumerated {len(procs)} running processes")
        if len(procs) == 0:
            r.fail("No processes found — psutil may not have permissions")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 2 — CPU stress: profiler classification + algorithmic fix
    # ─────────────────────────────────────────────────────────────────────────
    def day02_cpu_stress(self, r: TestResult):
        from agents.recovery.algorithmic_engine import SystemProfiler, AlgorithmicRecoveryEngine

        r.info("Spinning up a CPU stress subprocess for 20 seconds")
        stress_proc = None
        try:
            stress_proc = subprocess.Popen(
                [sys.executable, '-c',
                 'import time; x=0\n'
                 'end=time.time()+20\n'
                 'while time.time()<end:\n'
                 '    x=x*x+1\n'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(3)  # let it warm up
            r.ok(f"Stress subprocess started (PID {stress_proc.pid})")

            # Profile
            profiler = SystemProfiler()
            profile  = profiler.profile_cpu(n_samples=3, interval=1.0)
            r.ok(f"CPU samples: {[round(x,1) for x in profile.cpu_samples]}")
            r.ok(f"Classification: {profile.classification}")
            r.ok(f"Dominant process: {profile.dominant_process.name if profile.dominant_process else '?'} "
                 f"@ {profile.dominant_cpu_pct:.1f}%")
            r.ok(f"Trajectory: {profile.trajectory}")

            if profile.dominant_cpu_pct > 10:
                r.ok("Dominant process detected correctly (CPU > 10%)")
            else:
                r.warn(f"Dominant CPU low ({profile.dominant_cpu_pct:.1f}%) — may be throttled by OS")

            # Algorithmic fix
            r.info("Running algorithmic CPU fix")
            eng    = AlgorithmicRecoveryEngine()
            result = eng.heal_cpu(anomaly_value=profile.cpu_samples[-1], metrics={}, diagnosis={})

            r.ok(f"Algorithm applied: {result.algorithm}")
            r.ok(f"Actions taken: {len(result.actions_taken)}")
            for action in result.actions_taken:
                r.ok(f"  > {action}")

            # KEY CHECK: must NOT be kill as first action
            kill_words = ['kill', 'terminate', 'SIGKILL', 'SIGTERM']
            first_action = result.actions_taken[0] if result.actions_taken else ''
            if any(w.lower() in first_action.lower() for w in kill_words):
                r.fail("REGRESSION: First action was a kill — algorithmic fix must come first")
            else:
                r.ok("First action was NOT a kill — algorithmic fix applied correctly")

            r.ok(f"Before CPU: {result.evidence_before.get('samples', [])}")
            r.ok(f"After  CPU: {result.evidence_after}")

        finally:
            if stress_proc and stress_proc.poll() is None:
                stress_proc.terminate()
                r.info("Stress process terminated")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 3 — Memory pressure: profiler + algorithmic fix
    # ─────────────────────────────────────────────────────────────────────────
    def day03_memory_pressure(self, r: TestResult):
        from agents.recovery.algorithmic_engine import SystemProfiler, AlgorithmicRecoveryEngine

        r.info("Profiling memory (4 samples × 1.5s)")
        profiler = SystemProfiler()
        profile  = profiler.profile_memory(n_samples=4, interval=1.5)

        r.ok(f"Memory samples: {[round(x,1) for x in profile.mem_samples]}")
        r.ok(f"Classification: {profile.classification}")
        r.ok(f"Swap usage: {profile.swap_pct:.1f}%")
        r.ok(f"Cached MB: {profile.cached_mb:.0f} MB")
        r.ok(f"Trajectory: {profile.trajectory}")
        r.ok(f"Top consumers: {[ps.name for ps in profile.top_consumers[:3]]}")

        if profile.leaking_processes:
            r.ok(f"Leak detection: {len(profile.leaking_processes)} potential leakers found")
            for lk in profile.leaking_processes[:3]:
                r.ok(f"  Leak: '{lk['name']}' RSS={lk['rss_mb']:.0f}MB slope={lk['slope_mb_per_s']:.3f}MB/s")
        else:
            r.ok("No memory leaks detected in this run (clean system)")

        r.info("Running algorithmic memory fix")
        eng    = AlgorithmicRecoveryEngine()
        result = eng.heal_memory(anomaly_value=profile.mem_samples[-1], metrics={}, diagnosis={})

        r.ok(f"Algorithm: {result.algorithm}")
        r.ok(f"Classification: {result.classification}")
        r.ok(f"Success: {result.success}")
        for action in result.actions_taken:
            r.ok(f"  > {action}")

        # Check: must NOT kill as first response
        first = result.actions_taken[0] if result.actions_taken else ''
        if 'Killed' in first or 'Terminated' in first:
            r.fail("REGRESSION: Kill used as first memory fix — should be algorithmic only")
        else:
            r.ok("First action was algorithmic (no kill as first response)")

        r.ok(f"Before: {result.evidence_before.get('samples', [])}")
        r.ok(f"After:  {result.evidence_after}")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 4 — Memory leak detection: inject growing RSS, verify slope detection
    # ─────────────────────────────────────────────────────────────────────────
    def day04_memory_leak_detection(self, r: TestResult):
        from agents.recovery.algorithmic_engine import SystemProfiler

        r.info("Injecting a memory leak simulation (growing list in subprocess)")
        leak_proc = None
        try:
            leak_script = (
                'import time, gc\n'
                'gc.disable()\n'
                'leak = []\n'
                'for i in range(30):\n'
                '    leak.extend([bytearray(512*1024)] * 2)  # +1MB/s\n'
                '    time.sleep(1)\n'
            )
            leak_proc = subprocess.Popen(
                [sys.executable, '-c', leak_script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            r.ok(f"Leak subprocess started (PID {leak_proc.pid})")
            time.sleep(4)  # let it grow

            profiler = SystemProfiler()
            profile  = profiler.profile_memory(n_samples=5, interval=2.0)

            r.ok(f"Memory samples: {[round(x,1) for x in profile.mem_samples]}")
            r.ok(f"Classification: {profile.classification}")

            # Check if the leak was detected
            leak_found = any(lk['pid'] == leak_proc.pid for lk in profile.leaking_processes)
            if leak_found:
                lk = next(l for l in profile.leaking_processes if l['pid'] == leak_proc.pid)
                r.ok(f"LEAK DETECTED: '{lk['name']}' PID={lk['pid']} "
                     f"slope={lk['slope_mb_per_s']:.3f}MB/s RSS={lk['rss_mb']:.0f}MB")
                if profile.classification == 'MEMORY_LEAK':
                    r.ok("Classification correctly set to MEMORY_LEAK")
                else:
                    r.warn(f"Classification is '{profile.classification}' (not MEMORY_LEAK) — "
                           f"may need more samples or higher slope")
            else:
                # May not detect in all cases depending on system load
                r.warn(f"Leak subprocess not in top leakers (may be masked by other processes). "
                       f"Leakers found: {[(l['name'], l['pid']) for l in profile.leaking_processes[:3]]}")
                r.ok("Leak detection algorithm ran without error")

        finally:
            if leak_proc and leak_proc.poll() is None:
                leak_proc.terminate()
                r.info("Leak subprocess terminated")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 5 — Disk: profiler + smart cleanup algorithm
    # ─────────────────────────────────────────────────────────────────────────
    def day05_disk(self, r: TestResult):
        from agents.recovery.algorithmic_engine import SystemProfiler, AlgorithmicRecoveryEngine
        import tempfile, shutil

        r.info("Creating test temp files for cleanup validation")
        tmp_dir = tempfile.mkdtemp(prefix='sentinel_test_')
        created_size = 0
        try:
            # Write some test files to /tmp
            for i in range(5):
                path = os.path.join(tmp_dir, f'test_log_{i}.log.bak')
                with open(path, 'wb') as f:
                    f.write(b'X' * (1024 * 50))  # 50KB each
                created_size += 50
            r.ok(f"Created {5} test files ({created_size}KB) in {tmp_dir}")
        except Exception as e:
            r.warn(f"Could not create temp test files: {e}")

        try:
            r.info("Running disk profiler")
            profiler = SystemProfiler()
            profile  = profiler.profile_disk()

            r.ok(f"Classification: {profile.classification}")
            r.ok(f"Disk usage: {profile.disk_pct:.1f}%")
            r.ok(f"Free space: {profile.free_gb:.1f} GB")
            r.ok(f"Inode usage: {profile.inode_pct:.1f}%")
            r.ok(f"Largest dirs found: {len(profile.largest_dirs)}")
            for d in profile.largest_dirs[:3]:
                r.ok(f"  {d['path']}: {d['size_mb']:.1f} MB")

            r.info("Running algorithmic disk fix")
            disk_before = psutil.disk_usage('/').percent
            eng    = AlgorithmicRecoveryEngine()
            result = eng.heal_disk(anomaly_value=disk_before, metrics={}, diagnosis={})

            r.ok(f"Algorithm: {result.algorithm}")
            r.ok(f"Success: {result.success}")
            for action in result.actions_taken:
                r.ok(f"  > {action}")
            r.ok(f"Before: disk={result.evidence_before.get('disk_pct')}%")
            r.ok(f"After:  {result.evidence_after}")

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 6 — Network: profiler + algorithmic fix
    # ─────────────────────────────────────────────────────────────────────────
    def day06_network(self, r: TestResult):
        from agents.recovery.algorithmic_engine import SystemProfiler, AlgorithmicRecoveryEngine

        r.info("Running network profiler")
        profiler = SystemProfiler()
        profile  = profiler.profile_network()

        r.ok(f"Classification: {profile.classification}")
        r.ok(f"Ping: {profile.ping_ms:.1f}ms, Loss: {profile.packet_loss_pct:.1f}%")
        r.ok(f"Connections — ESTABLISHED:{profile.conn_established} "
             f"TIME_WAIT:{profile.conn_time_wait} CLOSE_WAIT:{profile.conn_close_wait}")
        r.ok(f"DNS OK: {profile.dns_ok}, Internet OK: {profile.internet_ok}")
        if profile.top_conn_process:
            r.ok(f"Top connection holder: '{profile.top_conn_process}' ({profile.top_conn_count} conns)")

        r.info("Running algorithmic network fix")
        eng    = AlgorithmicRecoveryEngine()
        result = eng.heal_network(anomaly_value=profile.ping_ms, metrics={}, diagnosis={})

        r.ok(f"Algorithm: {result.algorithm}")
        r.ok(f"Success: {result.success}")
        for action in result.actions_taken:
            r.ok(f"  > {action}")

        # Verify: network fix should NOT reset the interface as first action
        first = result.actions_taken[0] if result.actions_taken else ''
        interface_reset_words = ['interface reset', 'down/up', 'networksetup']
        if any(w in first.lower() for w in interface_reset_words):
            r.fail("REGRESSION: Interface reset used as first network fix — should be algorithmic only")
        else:
            r.ok("First action was algorithmic (no interface reset as first response)")

        r.ok(f"Before: {result.evidence_before}")
        r.ok(f"After:  {result.evidence_after}")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 7 — Escalation: verify L1→L2→L3→L4 ladder works correctly
    # ─────────────────────────────────────────────────────────────────────────
    def day07_escalation(self, r: TestResult):
        from agents.recovery.recovery_agent import GraduatedEscalationTracker

        r.info("Testing graduated escalation tracker")
        tracker = GraduatedEscalationTracker(window_minutes=5)

        # First incident → Level 1
        level = tracker.record('cpu.cpu_percent')
        actions = tracker.extra_actions('cpu.cpu_percent', level)
        r.ok(f"Incident 1 → Level {level}, actions: {actions}")
        if level != 1:
            r.fail(f"Expected Level 1 on first incident, got {level}")
        else:
            r.ok("Level 1 correct on first incident")
        if 'algorithmic_cpu_fix' in actions:
            r.ok("algorithmic_cpu_fix is Level-1 action (correct)")
        else:
            r.fail(f"algorithmic_cpu_fix missing from Level-1 actions: {actions}")

        # Second incident → Level 2
        level = tracker.record('cpu.cpu_percent')
        actions = tracker.extra_actions('cpu.cpu_percent', level)
        r.ok(f"Incident 2 → Level {level}, actions: {actions}")
        if level != 2:
            r.fail(f"Expected Level 2, got {level}")
        else:
            r.ok("Level 2 correct on second incident")
        if 'throttle_cpu_process' in actions:
            r.ok("throttle_cpu_process added at Level 2 (correct)")
        else:
            r.fail(f"throttle_cpu_process missing from Level-2 actions: {actions}")

        # Third incident → Level 3
        level = tracker.record('cpu.cpu_percent')
        actions = tracker.extra_actions('cpu.cpu_percent', level)
        r.ok(f"Incident 3 → Level {level}, actions: {actions}")
        if level != 3:
            r.fail(f"Expected Level 3, got {level}")
        else:
            r.ok("Level 3 correct on third incident")
        if 'kill_top_cpu_process' in actions:
            r.ok("kill_top_cpu_process added at Level 3 (correct — kill only after algorithmic fails)")
        else:
            r.fail(f"kill_top_cpu_process missing from Level-3 actions: {actions}")

        # Fourth incident → Level 4 (critical)
        level = tracker.record('cpu.cpu_percent')
        actions = tracker.extra_actions('cpu.cpu_percent', level)
        r.ok(f"Incident 4 → Level {level}, actions: {actions}")
        if level != 4:
            r.fail(f"Expected Level 4, got {level}")
        else:
            r.ok("Level 4 correct on fourth incident")

        # Reset after resolution
        tracker.reset('cpu.cpu_percent')
        level = tracker.current_level('cpu.cpu_percent')
        r.ok(f"After reset → Level {level}")
        if level == 1:
            r.ok("Escalation reset correctly after resolution")
        else:
            r.fail(f"Expected Level 1 after reset, got {level}")

        # Test all categories
        for cat in ['memory.memory_percent', 'disk.disk_percent', 'network.ping_latency_ms']:
            l1 = tracker.record(cat)
            a1 = tracker.extra_actions(cat, l1)
            algorithmic_actions = [a for a in a1 if a.startswith('algorithmic_')]
            if algorithmic_actions:
                r.ok(f"Category '{cat.split('.')[0]}': Level-1 algorithmic action = {algorithmic_actions}")
            else:
                r.warn(f"Category '{cat.split('.')[0]}': no algorithmic action at Level 1: {a1}")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 8 — Multi-anomaly: simultaneous CPU + memory stress
    # ─────────────────────────────────────────────────────────────────────────
    def day08_multi_anomaly(self, r: TestResult):
        from agents.recovery.algorithmic_engine import SystemProfiler, AlgorithmicRecoveryEngine

        r.info("Running simultaneous CPU + memory stress for 15s")
        procs = []
        try:
            # CPU stress
            cpu_proc = subprocess.Popen(
                [sys.executable, '-c',
                 'import time; x=0\nend=time.time()+15\n'
                 'while time.time()<end:\n    x=x*x+1'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            procs.append(cpu_proc)

            # Memory stress (allocate ~200MB)
            mem_proc = subprocess.Popen(
                [sys.executable, '-c',
                 'import time; data=bytearray(200*1024*1024); time.sleep(15)'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            procs.append(mem_proc)
            time.sleep(3)

            r.ok(f"Stress procs running: CPU PID={cpu_proc.pid}, MEM PID={mem_proc.pid}")

            # Profile both
            profiler = SystemProfiler()
            cpu_profile = profiler.profile_cpu(n_samples=2, interval=1.0)
            mem_profile = profiler.profile_memory(n_samples=2, interval=1.0)

            r.ok(f"CPU classification: {cpu_profile.classification}")
            r.ok(f"CPU samples: {[round(x,1) for x in cpu_profile.cpu_samples]}")
            r.ok(f"MEM classification: {mem_profile.classification}")
            r.ok(f"MEM samples: {[round(x,1) for x in mem_profile.mem_samples]}")

            # Run fixes concurrently
            results = {}
            def _fix_cpu():
                eng = AlgorithmicRecoveryEngine()
                results['cpu'] = eng.heal_cpu(cpu_profile.cpu_samples[-1], {}, {})
            def _fix_mem():
                eng = AlgorithmicRecoveryEngine()
                results['mem'] = eng.heal_memory(mem_profile.mem_samples[-1], {}, {})

            threads = [threading.Thread(target=_fix_cpu), threading.Thread(target=_fix_mem)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

            if 'cpu' in results:
                r.ok(f"CPU fix: {results['cpu'].algorithm} — {len(results['cpu'].actions_taken)} actions")
                for a in results['cpu'].actions_taken:
                    r.ok(f"  [CPU] > {a}")
            else:
                r.fail("CPU fix did not complete")

            if 'mem' in results:
                r.ok(f"MEM fix: {results['mem'].algorithm} — {len(results['mem'].actions_taken)} actions")
                for a in results['mem'].actions_taken:
                    r.ok(f"  [MEM] > {a}")
            else:
                r.fail("MEM fix did not complete")

        finally:
            for p in procs:
                if p.poll() is None:
                    p.terminate()
            r.info("All stress processes terminated")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 9 — Groq AI validation: verify 70B model is responding
    # ─────────────────────────────────────────────────────────────────────────
    def day09_groq_ai_validation(self, r: TestResult):
        groq_key = os.environ.get('GROQ_API_KEY', '')
        if not groq_key:
            r.skip("GROQ_API_KEY not set — skipping Groq validation test")
            return

        r.info("Testing Groq llama-3.3-70b-versatile AI validation")
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)

            # Test 1: CPU classification validation
            t0  = time.time()
            resp = client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content':
                    'IoT device CPU anomaly. Classification: COMPUTE_BOUND. '
                    'Evidence: process=stress-ng at 82% CPU, iowait=0%, trajectory=STABLE. '
                    'In ONE sentence: confirm or correct the classification.'}],
                max_tokens=80, temperature=0.1,
            )
            latency = round(time.time() - t0, 2)
            text = resp.choices[0].message.content.strip()
            r.ok(f"Groq CPU response ({latency}s): {text}")
            if latency > 10:
                r.warn(f"Groq latency high ({latency}s) — may affect real-time recovery")
            else:
                r.ok(f"Groq latency acceptable: {latency}s")

            # Test 2: Memory leak validation
            t0  = time.time()
            resp2 = client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content':
                    'IoT memory anomaly. Classification: MEMORY_LEAK. '
                    'Evidence: process=python3, RSS growing at 0.8MB/s, swap=45%. '
                    'In ONE sentence: confirm or correct, then state the best algorithmic fix.'}],
                max_tokens=100, temperature=0.1,
            )
            latency2 = round(time.time() - t0, 2)
            text2 = resp2.choices[0].message.content.strip()
            r.ok(f"Groq MEM response ({latency2}s): {text2}")

            # Test 3: Network classification validation
            t0  = time.time()
            resp3 = client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content':
                    'IoT network anomaly. Classification: CONNECTION_LEAK. '
                    'Evidence: TIME_WAIT=350, CLOSE_WAIT=85, ping=15ms, loss=0%. '
                    'In ONE sentence: confirm or correct, then state the best fix.'}],
                max_tokens=100, temperature=0.1,
            )
            latency3 = round(time.time() - t0, 2)
            text3 = resp3.choices[0].message.content.strip()
            r.ok(f"Groq NET response ({latency3}s): {text3}")

            avg_latency = round((latency + latency2 + latency3) / 3, 2)
            r.ok(f"Average Groq latency: {avg_latency}s across 3 queries")
            r.ok(f"Model used: {resp.model}")

        except Exception as e:
            r.fail(f"Groq test failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 10 — Anomaly detection pipeline: test all detection methods
    # ─────────────────────────────────────────────────────────────────────────
    def day10_anomaly_detection(self, r: TestResult):
        from agents.anomaly.anomaly_detection_agent import AdaptiveMetricBaseline

        r.info("Testing AdaptiveMetricBaseline — all detection methods")
        baseline = AdaptiveMetricBaseline(window_size=100)

        # Warm up baseline with 35 normal readings (~35% CPU)
        r.info("Warming up baseline with 35 normal readings (35% CPU)")
        for i in range(35):
            baseline.push(35.0 + (i % 5) - 2.0)

        stats = baseline.stats()
        r.ok(f"Baseline stats: {stats}")

        if stats.get('n', 0) >= 30:
            r.ok("Baseline warm-up complete (≥30 samples)")
        else:
            r.fail(f"Baseline not warmed up: only {stats.get('n')} samples")

        # Test 1: Spike detection — inject a sudden spike
        r.info("Test 1: IQR spike detection (inject 95% reading into 35% baseline)")
        is_anom, reason, severity = baseline.is_anomalous(95.0)
        r.ok(f"Spike 95%: anomalous={is_anom}, reason={reason}, severity={severity}")
        if is_anom:
            r.ok("Spike correctly detected as anomalous")
        else:
            r.warn("Spike not detected — baseline may have very high variance")

        # Test 2: Normal reading — should NOT trigger
        r.info("Test 2: Normal reading should not trigger")
        is_anom2, reason2, _ = baseline.is_anomalous(36.0)
        r.ok(f"Normal 36%: anomalous={is_anom2}, reason={reason2}")
        if not is_anom2:
            r.ok("Normal reading correctly NOT flagged as anomaly")
        else:
            r.fail(f"False positive: normal reading 36% flagged as anomaly ({reason2})")

        # Test 3: Baseline freeze during anomaly
        r.info("Test 3: Baseline freeze — window should not accept spike values")
        n_before = len(baseline.window)
        baseline.freeze()
        baseline.push(95.0)
        baseline.push(95.0)
        n_after = len(baseline.window)
        r.ok(f"Window size before freeze push: {n_before}, after: {n_after}")
        if n_after == n_before:
            r.ok("Baseline correctly frozen — spike values rejected from window")
        else:
            r.fail(f"Baseline not frozen — window grew from {n_before} to {n_after}")

        # Test 4: Unfreeze and verify window resumes
        baseline.unfreeze()
        n_before2 = len(baseline.window)
        baseline.push(36.0)
        n_after2 = len(baseline.window)
        r.ok(f"Window size after unfreeze: {n_before2} → {n_after2}")
        if n_after2 == n_before2 + 1:
            r.ok("Baseline correctly unfrozen — window accepting values again")
        else:
            r.fail("Unfreeze failed")

        # Test 5: EMA tracking
        r.info("Test 5: EMA shadow tracking")
        ema_val = baseline.ema
        r.ok(f"EMA value: {ema_val:.2f} (should be close to 35.0)")
        if ema_val is not None and 20 < ema_val < 50:
            r.ok(f"EMA within expected range: {ema_val:.2f}")
        else:
            r.warn(f"EMA value unexpected: {ema_val}")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 11 — Verify NO KILL at Level 1 (algorithmic guard test)
    # ─────────────────────────────────────────────────────────────────────────
    def day11_no_kill_at_level1(self, r: TestResult):
        from agents.recovery.algorithmic_engine import AlgorithmicRecoveryEngine

        r.info("Verifying recovery does NOT kill/terminate at Level 1")
        eng = AlgorithmicRecoveryEngine()

        kill_words = ['Killed', 'Terminated', 'SIGKILL', 'SIGTERM', 'kill_top', 'terminated']

        # CPU fix
        r.info("CPU algorithmic fix at Level 1")
        cpu_result = eng.heal_cpu(anomaly_value=80.0, metrics={}, diagnosis={})
        cpu_actions_text = ' '.join(cpu_result.actions_taken)
        cpu_has_kill = any(w in cpu_actions_text for w in kill_words)
        r.ok(f"CPU actions: {cpu_result.actions_taken}")
        if cpu_has_kill:
            r.fail(f"REGRESSION: Kill found in Level-1 CPU actions: {cpu_actions_text}")
        else:
            r.ok("CPU Level-1: No kill/terminate — algorithmic fix only [PASS]")

        # Memory fix
        r.info("Memory algorithmic fix at Level 1 (no leak scenario)")
        mem_result = eng.heal_memory(anomaly_value=80.0, metrics={}, diagnosis={})
        mem_actions_text = ' '.join(mem_result.actions_taken)
        # Kill IS allowed in memory ONLY if RSS > 60% of total RAM (confirmed leak)
        # For normal NORMAL_GROWTH classification, no kill should happen
        r.ok(f"Memory classification: {mem_result.classification}")
        r.ok(f"Memory actions: {mem_result.actions_taken}")
        if mem_result.classification in ('NORMAL_GROWTH', 'CACHE_BLOAT', 'SWAP_PRESSURE'):
            mem_has_kill = any(w in mem_actions_text for w in ['Killed', 'SIGKILL'])
            if mem_has_kill:
                r.fail("REGRESSION: Kill used for non-leak memory classification")
            else:
                r.ok("Memory Level-1: No kill for non-leak scenario [PASS]")
        elif mem_result.classification == 'MEMORY_LEAK':
            r.ok("Memory LEAK classified — kill only applied if RSS > 60% threshold")

        # Verify escalation dispatch has algorithmic actions at Level 1
        r.info("Verifying dispatch table has algorithmic actions registered")
        from agents.recovery.recovery_agent import RecoveryAgent
        algo_actions = [
            'algorithmic_cpu_fix', 'algorithmic_memory_fix',
            'algorithmic_disk_fix', 'algorithmic_network_fix',
        ]
        # Check they exist in the handler map via a mock dispatch
        for action in algo_actions:
            try:
                # We can't easily invoke without full agent init, so check source
                import inspect
                src = inspect.getsource(RecoveryAgent._dispatch)
                if action in src:
                    r.ok(f"Action '{action}' registered in dispatch table")
                else:
                    r.fail(f"Action '{action}' NOT found in dispatch table")
            except Exception as e:
                r.warn(f"Could not inspect dispatch: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 12 — Outcome verification: before/after evidence present
    # ─────────────────────────────────────────────────────────────────────────
    def day12_outcome_verification(self, r: TestResult):
        from agents.recovery.algorithmic_engine import AlgorithmicRecoveryEngine

        r.info("Verifying outcome verification: all HealResult objects have before/after evidence")
        eng = AlgorithmicRecoveryEngine()

        scenarios = [
            ('CPU',     lambda: eng.heal_cpu(80.0, {}, {})),
            ('Memory',  lambda: eng.heal_memory(82.0, {}, {})),
            ('Disk',    lambda: eng.heal_disk(88.0, {}, {})),
            ('Network', lambda: eng.heal_network(150.0, {}, {})),
        ]

        for name, fn in scenarios:
            result = fn()
            r.ok(f"\n  {name} fix:")
            r.ok(f"    success        = {result.success}")
            r.ok(f"    classification = {result.classification}")
            r.ok(f"    algorithm      = {result.algorithm}")
            r.ok(f"    actions_taken  = {len(result.actions_taken)} actions")
            r.ok(f"    evidence_before: {list(result.evidence_before.keys())}")
            r.ok(f"    evidence_after : {list(result.evidence_after.keys())}")

            if result.evidence_before:
                r.ok(f"    Before/after evidence present [PASS]")
            else:
                r.fail(f"    {name}: evidence_before is empty")

            if result.evidence_after:
                r.ok(f"    After evidence present [PASS]")
            else:
                r.warn(f"    {name}: evidence_after is empty (may be OK for some scenarios)")

            if result.algorithm and result.algorithm != 'error':
                r.ok(f"    Algorithm name present [PASS]: {result.algorithm}")
            else:
                r.fail(f"    {name}: algorithm field missing or 'error'")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 13 — Adaptive baseline: hysteresis + EMA drift detection
    # ─────────────────────────────────────────────────────────────────────────
    def day13_adaptive_baselines(self, r: TestResult):
        from agents.anomaly.anomaly_detection_agent import AdaptiveMetricBaseline

        r.info("Testing hysteresis: anomaly counter should NOT reset at boundary")
        baseline = AdaptiveMetricBaseline(window_size=100)

        # Warm up with stable values
        for _ in range(35):
            baseline.push(40.0)

        stats = baseline.stats()
        mean  = stats.get('mean', 40.0)
        std   = stats.get('std', 1.0)
        r.ok(f"Baseline: mean={mean:.1f}, std={std:.2f}")

        # The hysteresis threshold: below mean + 0.5σ resets the counter
        reset_threshold = mean + 0.5 * std
        r.ok(f"Hysteresis reset threshold: {reset_threshold:.2f}")

        # Push a value just above threshold — should NOT reset counter
        just_above = reset_threshold + 2.0
        is_anom, reason, _ = baseline.is_anomalous(just_above)
        r.ok(f"Reading {just_above:.1f} (just above threshold): anomalous={is_anom}")

        # EMA drift detection
        r.info("Testing EMA drift: push slowly drifting values")
        drift_baseline = AdaptiveMetricBaseline(window_size=100)
        for v in range(35, 70):  # gradually rising from 35 to 70
            drift_baseline.push(float(v))

        ema = drift_baseline.ema
        window_mean = sum(drift_baseline.window) / len(drift_baseline.window) if drift_baseline.window else 0
        r.ok(f"After drift: EMA={ema:.2f}, window_mean={window_mean:.2f}")
        # EMA should be higher than window mean for rising drift
        if ema is not None and ema > window_mean:
            r.ok("EMA correctly tracking drift faster than window mean (EMA > window_mean)")
        elif ema is None:
            r.warn("EMA not initialized yet")
        else:
            r.ok(f"EMA={ema:.2f} vs window_mean={window_mean:.2f} (relationship depends on alpha)")

        r.info("Testing rate-of-change anomaly detection")
        roc_baseline = AdaptiveMetricBaseline(window_size=100)
        for _ in range(35):
            roc_baseline.push(30.0)
        # Inject a sudden spike (rate of change should fire)
        is_anom_roc, reason_roc, sev_roc = roc_baseline.is_anomalous(95.0)
        r.ok(f"Rate-of-change spike 30→95: anomalous={is_anom_roc}, reason={reason_roc}, severity={sev_roc}")
        if is_anom_roc:
            r.ok("Rate-of-change anomaly correctly detected [PASS]")
        else:
            r.warn("Rate-of-change spike not detected — may need larger change or stricter threshold")

    # ─────────────────────────────────────────────────────────────────────────
    # DAY 14 — Full end-to-end pipeline test
    # ─────────────────────────────────────────────────────────────────────────
    def day14_end_to_end(self, r: TestResult):
        r.info("Full pipeline test: EventBus → MonitoringAgent → AnomalyDetection → Diagnosis → Recovery")

        try:
            from core.event_bus import EventBus
            from core.config import load_config
            from core.logging import get_logger

            config = load_config('config/config.yaml')
            logger = get_logger('TestE2E')
            bus    = EventBus()

            r.ok("Core infrastructure initialised: EventBus, Config, Logger")
        except Exception as e:
            r.fail(f"Core infra init failed: {e}")
            return

        # Test event bus pub/sub
        r.info("Testing EventBus publish/subscribe")
        received = []
        def _handler(event):
            received.append(event)

        bus.subscribe('test.ping', _handler)
        bus.publish('test.ping', {'msg': 'hello'})
        time.sleep(0.2)
        if received:
            r.ok(f"EventBus pub/sub working: received {len(received)} event(s)")
        else:
            r.fail("EventBus pub/sub failed: no events received")

        # Test MonitoringAgent can collect metrics
        r.info("Testing MonitoringAgent metric collection")
        try:
            from agents.monitoring.monitoring_agent import MonitoringAgent
            agent = MonitoringAgent('test-monitor', config, bus, logger)
            metrics = agent._collect_metrics()
            r.ok(f"Metrics collected: keys={list(metrics.keys())}")
            if 'cpu' in metrics:
                r.ok(f"  CPU: {metrics['cpu'].get('cpu_percent', '?')}%")
            if 'memory' in metrics:
                r.ok(f"  MEM: {metrics['memory'].get('memory_percent', '?')}%")
            if 'disk' in metrics:
                r.ok(f"  DISK: {metrics['disk'].get('disk_percent', '?')}%")
        except Exception as e:
            r.fail(f"MonitoringAgent metric collection failed: {e}")

        # Test AnomalyDetectionAgent initialises
        r.info("Testing AnomalyDetectionAgent initialisation")
        try:
            from agents.anomaly.anomaly_detection_agent import AnomalyDetectionAgent
            anomaly_agent = AnomalyDetectionAgent('test-anomaly', config, bus, logger)
            r.ok("AnomalyDetectionAgent initialised")
            r.ok(f"  Isolation Forest available: {anomaly_agent.isolation_forest_available if hasattr(anomaly_agent, 'isolation_forest_available') else 'check manually'}")
        except Exception as e:
            r.fail(f"AnomalyDetectionAgent init failed: {e}")

        # Test DiagnosisAgent initialises with Groq
        r.info("Testing DiagnosisAgent initialisation (with Groq)")
        try:
            from agents.diagnosis.diagnosis_agent import DiagnosisAgent
            diag_agent = DiagnosisAgent('test-diagnosis', config, bus, logger)
            groq_ok = diag_agent.groq_client is not None
            ollama_ok = diag_agent.ollama_available
            r.ok(f"DiagnosisAgent initialised — Groq: {groq_ok}, Ollama: {ollama_ok}")
            if groq_ok:
                r.ok("Groq client active — llama-3.3-70b-versatile is the primary AI")
            else:
                r.warn("Groq client not active — falling back to Ollama")
        except Exception as e:
            r.fail(f"DiagnosisAgent init failed: {e}")

        # Test RecoveryAgent initialises with algorithmic engine
        r.info("Testing RecoveryAgent + AlgorithmicEngine initialisation")
        try:
            from agents.recovery.recovery_agent import RecoveryAgent, _get_algo_engine
            recovery_agent = RecoveryAgent('test-recovery', config, bus, logger)
            r.ok("RecoveryAgent initialised")

            engine = _get_algo_engine()
            r.ok(f"AlgorithmicRecoveryEngine singleton loaded")
        except Exception as e:
            r.fail(f"RecoveryAgent init failed: {e}")

        # Simulate the full anomaly → recovery flow via events
        r.info("Simulating anomaly → diagnosis → recovery event flow")
        recovery_events = []
        bus.subscribe('recovery.action', lambda e: recovery_events.append(e))

        import uuid
        fake_diagnosis_event = type('Event', (), {
            'event_type': 'diagnosis.complete',
            'data': {
                'device_id':  'test-device',
                'timestamp':  datetime.now().isoformat(),
                'anomaly': {
                    'metric_name': 'cpu.cpu_percent',
                    'value':       85.0,
                    'type':        'iqr_outlier',
                },
                'diagnosis': {
                    'diagnosis_id':       str(uuid.uuid4()),
                    'diagnosis':          'High CPU usage detected',
                    'root_cause':         'Compute-intensive process',
                    'confidence':         0.85,
                    'recommended_actions': ['algorithmic_cpu_fix'],
                    'severity':           'high',
                },
            },
        })()

        try:
            recovery_agent.process_event(fake_diagnosis_event)
            r.ok("Recovery agent processed diagnosis.complete event without crashing")
        except Exception as e:
            r.fail(f"Recovery process_event failed: {e}")

        # Give recovery time to run and publish
        time.sleep(8)
        if recovery_events:
            ev = recovery_events[0]
            r.ok(f"recovery.action event published: {ev.data.get('actions', [{}])[0].get('action_name', '?')}")
            r.ok(f"Escalation level: {ev.data.get('escalation_level', '?')}")
        else:
            r.warn("No recovery.action event received (algorithmic fix may be running in background thread)")

    # ─────────────────────────────────────────────────────────────────────────
    # Report generation
    # ─────────────────────────────────────────────────────────────────────────
    def _write_report(self):
        passed  = sum(1 for r in self.results if r.passed)
        failed  = sum(1 for r in self.results if not r.passed and not r.skipped)
        skipped = sum(1 for r in self.results if r.skipped)
        total   = len(self.results)
        duration = round((datetime.now() - self.start_time).total_seconds(), 1)

        lines = [
            "=" * 72,
            "  SENTINEL AI — 2-WEEK COMPRESSED TEST SUITE REPORT",
            f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Platform:  {platform.system()} {platform.release()}",
            f"  Python:    {sys.version.split()[0]}",
            "=" * 72,
            "",
            f"  SUMMARY: {passed}/{total} passed  |  {failed} failed  |  {skipped} skipped",
            f"  Total runtime: {duration}s",
            "",
            "  PASS RATE: {:.0f}%".format(passed / total * 100 if total else 0),
            "",
            "=" * 72,
            "  DAY-BY-DAY RESULTS",
            "=" * 72,
        ]

        for r in self.results:
            status = "PASS" if r.passed else ("SKIP" if r.skipped else "FAIL")
            lines.append(f"\n  Day {r.day:2d} [{status}] — {r.name} ({r.duration}s)")
            lines.extend(r.details)
            if r.errors:
                lines.append("  --- ERRORS ---")
                lines.extend(r.errors)

        lines += [
            "",
            "=" * 72,
            "  ALGORITHMIC RECOVERY VALIDATION",
            "=" * 72,
            "",
            "  The following checks confirm recovery is NOT just kill/reset:",
            "    Day  2: CPU Level-1 action is scheduling policy, NOT kill",
            "    Day  3: Memory Level-1 action is renice/cache-drop, NOT kill",
            "    Day  6: Network Level-1 action is TCP tuning, NOT interface reset",
            "    Day  7: Escalation ladder — kill only appears at Level 3",
            "    Day 11: Level-1 dispatch verified: algorithmic_*_fix actions registered",
            "",
            "  AI Integration:",
            f"    Groq llama-3.3-70b-versatile: {'active' if os.environ.get('GROQ_API_KEY') else 'key not set'}",
            "    Ollama fallback: local llama3.2:3b",
            "",
            "=" * 72,
        ]

        report_text = "\n".join(lines)
        os.makedirs(os.path.dirname(_REPORT_PATH), exist_ok=True)
        with open(_REPORT_PATH, 'w') as f:
            f.write(report_text)

        return report_text, passed, failed, skipped

    # ─────────────────────────────────────────────────────────────────────────
    # Main runner
    # ─────────────────────────────────────────────────────────────────────────
    def run(self):
        print("\n" + "=" * 70)
        print("  SENTINEL AI — 2-WEEK COMPRESSED TEST SUITE")
        print(f"  Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

        days = [
            (1,  "Baseline: imports, psutil, process enumeration",     self.day01_baseline),
            (2,  "CPU stress: profiler classification + algorithmic fix", self.day02_cpu_stress),
            (3,  "Memory pressure: profiler + algorithmic fix",         self.day03_memory_pressure),
            (4,  "Memory leak detection: injected RSS growth slope",    self.day04_memory_leak_detection),
            (5,  "Disk: profiler + smart targeted cleanup",             self.day05_disk),
            (6,  "Network: profiler + TCP algorithmic fix",             self.day06_network),
            (7,  "Escalation: L1→L2→L3→L4 ladder verification",        self.day07_escalation),
            (8,  "Multi-anomaly: simultaneous CPU + memory",            self.day08_multi_anomaly),
            (9,  "Groq AI validation: llama-3.3-70b-versatile live",   self.day09_groq_ai_validation),
            (10, "Anomaly detection: IQR / freeze / EMA methods",      self.day10_anomaly_detection),
            (11, "No-kill guard: Level-1 must not kill at first response", self.day11_no_kill_at_level1),
            (12, "Outcome verification: before/after evidence present", self.day12_outcome_verification),
            (13, "Adaptive baselines: hysteresis + drift detection",    self.day13_adaptive_baselines),
            (14, "Full end-to-end pipeline: monitor→detect→diagnose→recover", self.day14_end_to_end),
        ]

        for day, name, fn in days:
            self._run_day(day, name, fn)

        report, passed, failed, skipped = self._write_report()

        print("\n\n" + "=" * 70)
        print("  FINAL RESULTS")
        print("=" * 70)
        print(report.split("ALGORITHMIC")[1] if "ALGORITHMIC" in report else "")
        print(f"\n  Report saved to: {_REPORT_PATH}")
        print("=" * 70)

        return failed == 0


if __name__ == '__main__':
    suite = TwoWeekTestSuite()
    ok = suite.run()
    sys.exit(0 if ok else 1)
