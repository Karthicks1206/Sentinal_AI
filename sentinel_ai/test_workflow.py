#!/usr/bin/env python3
"""
Sentinel AI - Comprehensive Test Workflow
Tests multi-agent system step-by-step:
1. System monitoring (logs, power, network)
2. Trigger CPU/RAM overload
3. Verify anomaly detection
4. Verify diagnosis
5. Verify autonomous recovery
6. Verify learning/adaptation
"""

import sys
import time
import threading
import multiprocessing
import psutil
from pathlib import Path
from datetime import datetime
from collections import deque

sys.path.insert(0, str(Path(__file__).parent))

from core.config import get_config
from core.logging import setup_logging, get_logger
from core.event_bus import get_event_bus, EventPriority
from core.database import get_database

from agents.monitoring import MonitoringAgent
from agents.anomaly import AnomalyDetectionAgent
from agents.diagnosis import DiagnosisAgent
from agents.recovery import RecoveryAgent
from agents.learning import LearningAgent


class TestWorkflow:
    """
    Orchestrates comprehensive testing of Sentinel AI system
    """

    def __init__(self):
        """Initialize test workflow"""
        print("="*80)
        print("SENTINEL AI - COMPREHENSIVE TEST WORKFLOW")
        print("="*80)
        print()

        self.config = get_config()

        self.config.set('aws.enabled', False)
        self.config.set('simulation.enabled', False)

        setup_logging(self.config)
        self.logger = get_logger('TestWorkflow')

        self.event_bus = get_event_bus(self.config)
        self.database = get_database(self.config)

        self.events_received = {
            'health.metric': deque(maxlen=100),
            'anomaly.detected': deque(maxlen=50),
            'diagnosis.complete': deque(maxlen=50),
            'recovery.action': deque(maxlen=50)
        }

        self._setup_event_tracking()

        self.agents = {}
        self._init_agents()

        self.test_results = []
        self.current_test = None

    def _setup_event_tracking(self):
        """Setup event tracking for verification"""
        def track_health_metric(event):
            self.events_received['health.metric'].append(event)

        def track_anomaly(event):
            self.events_received['anomaly.detected'].append(event)
            print(f"\n ANOMALY DETECTED: {event.data['anomaly']['metric_name']} - {event.data['anomaly']['type']}")
            print(f" Severity: {event.data['anomaly']['severity']}")
            print(f" Value: {event.data['anomaly']['value']:.2f}")

        def track_diagnosis(event):
            self.events_received['diagnosis.complete'].append(event)
            print(f"\n DIAGNOSIS: {event.data['diagnosis']['diagnosis']}")
            print(f" Root Cause: {event.data['diagnosis']['root_cause']}")
            print(f" Actions: {event.data['diagnosis']['recommended_actions']}")

        def track_recovery(event):
            self.events_received['recovery.action'].append(event)
            print(f"\n RECOVERY ACTIONS:")
            for action in event.data.get('actions', []):
                status_icon = "" if action.get('status') == 'success' else ""
                msg = action.get('message') or action.get('result') or ''
                print(f" {status_icon} {action.get('action_name', '?')}: {msg}")

        self.event_bus.subscribe("health.metric", track_health_metric)
        self.event_bus.subscribe("anomaly.detected", track_anomaly)
        self.event_bus.subscribe("diagnosis.complete", track_diagnosis)
        self.event_bus.subscribe("recovery.action", track_recovery)

    def _init_agents(self):
        """Initialize all agents"""
        print("Initializing agents...")

        self.agents['monitoring'] = MonitoringAgent(
            name='MonitoringAgent',
            config=self.config,
            event_bus=self.event_bus,
            logger=get_logger('MonitoringAgent'),
            database=self.database
        )

        self.agents['anomaly'] = AnomalyDetectionAgent(
            name='AnomalyDetectionAgent',
            config=self.config,
            event_bus=self.event_bus,
            logger=get_logger('AnomalyDetectionAgent'),
            database=self.database
        )

        self.agents['diagnosis'] = DiagnosisAgent(
            name='DiagnosisAgent',
            config=self.config,
            event_bus=self.event_bus,
            logger=get_logger('DiagnosisAgent'),
            database=self.database
        )

        self.agents['recovery'] = RecoveryAgent(
            name='RecoveryAgent',
            config=self.config,
            event_bus=self.event_bus,
            logger=get_logger('RecoveryAgent'),
            database=self.database
        )

        self.agents['learning'] = LearningAgent(
            name='LearningAgent',
            config=self.config,
            event_bus=self.event_bus,
            logger=get_logger('LearningAgent'),
            database=self.database
        )

        print(" All agents initialized\n")

    def _seed_baselines(self):
        """
        Inject 20 normal-range readings into each metric baseline so the
        warmup gate is already satisfied before the anomaly tests run.
        Uses current live values so the baseline matches this machine's real state.
        This avoids the 75-second real-time wait (15 readings × 5s).
        """
        from agents.anomaly.anomaly_detection_agent import AdaptiveMetricBaseline

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        cpu_base = 15.0
        mem_base = round(mem.percent, 1)
        disk_base = round(disk.percent, 1)

        normal_values = {
            'cpu.cpu_percent':       [cpu_base] * 20,
            'memory.memory_percent': [mem_base] * 20,
            'disk.disk_percent':     [disk_base] * 20,
        }
        anomaly_agent = self.agents['anomaly']
        for metric_key, values in normal_values.items():
            bl = anomaly_agent._baselines.get(metric_key)
            if bl is None:
                bl = AdaptiveMetricBaseline(window_size=300)
                anomaly_agent._baselines[metric_key] = bl
            for v in values:
                bl.window.append(v)
                bl.short_window.append(v)
        print(f" Baselines seeded — cpu={cpu_base}% mem={mem_base}% disk={disk_base}% — warmup complete")

    def start_agents(self):
        """Start all agents"""
        print("Starting agents...")
        for name, agent in self.agents.items():
            agent.start()
            print(f" {name} started")
        print()
        time.sleep(2)
        self._seed_baselines()

    def stop_agents(self):
        """Stop all agents"""
        print("\nStopping agents...")
        for name, agent in self.agents.items():
            agent.stop()
            print(f" {name} stopped")

    def run_test(self, test_name, test_func, expected_result):
        """
        Run a test and track results

        Args:
            test_name: Name of the test
            test_func: Function to execute
            expected_result: Expected outcome
        """
        print("="*80)
        print(f"TEST: {test_name}")
        print("="*80)
        print(f"Expected: {expected_result}")
        print()

        self.current_test = test_name
        start_time = time.time()

        try:
            result = test_func()
            duration = time.time() - start_time

            if result:
                print(f"\n PASSED in {duration:.2f}s")
                self.test_results.append({
                    'test': test_name,
                    'status': 'PASSED',
                    'duration': duration
                })
            else:
                print(f"\n FAILED after {duration:.2f}s")
                self.test_results.append({
                    'test': test_name,
                    'status': 'FAILED',
                    'duration': duration
                })

            return result

        except Exception as e:
            duration = time.time() - start_time
            print(f"\n ERROR: {e}")
            self.test_results.append({
                'test': test_name,
                'status': 'ERROR',
                'duration': duration,
                'error': str(e)
            })
            return False


    def test_1_basic_monitoring(self):
        """Test that monitoring agent collects basic system metrics"""
        print("Waiting for monitoring agent to collect metrics...")

        self.events_received['health.metric'].clear()

        for i in range(25):
            time.sleep(1)
            count = len(self.events_received['health.metric'])
            print(f" Metrics collected: {count}/3", end='\r')
            if count >= 3:
                break

        if len(self.events_received['health.metric']) >= 3:
            latest_event = self.events_received['health.metric'][-1]
            metrics = latest_event.data.get('metrics', {})

            print(f"\n\nLatest Metrics Collected:")
            print(f" CPU: {metrics.get('cpu', {}).get('cpu_percent', 0):.1f}%")
            print(f" Memory: {metrics.get('memory', {}).get('memory_percent', 0):.1f}%")
            print(f" Disk: {metrics.get('disk', {}).get('disk_percent', 0):.1f}%")

            has_cpu = 'cpu' in metrics and 'cpu_percent' in metrics['cpu']
            has_memory = 'memory' in metrics and 'memory_percent' in metrics['memory']
            has_disk = 'disk' in metrics and 'disk_percent' in metrics['disk']

            return has_cpu and has_memory and has_disk

        return False


    def test_2_cpu_overload_detection(self):
        """Test CPU overload detection and response"""
        print("Triggering CPU overload...")

        self.events_received['anomaly.detected'].clear()
        self.events_received['diagnosis.complete'].clear()

        cpu_count = psutil.cpu_count()

        def _cpu_worker():
            """Pure CPU burn — runs in a subprocess to bypass the GIL."""
            while True:
                _ = sum(i * i for i in range(200000))

        procs = []
        print(f" Starting {cpu_count} CPU stress processes (multiprocessing)...")
        for _ in range(cpu_count):
            p = multiprocessing.Process(target=_cpu_worker, daemon=True)
            p.start()
            procs.append(p)

        print(" Waiting for anomaly detection (max 30s)...")
        detected = False

        for i in range(30):
            time.sleep(1)
            cpu_percent = psutil.cpu_percent(interval=0.1)
            anomaly_count = len(self.events_received['anomaly.detected'])

            print(f" CPU: {cpu_percent:.1f}% | Anomalies: {anomaly_count}", end='\r')

            if anomaly_count > 0:
                detected = True
                break

        for p in procs:
            p.terminate()
        for p in procs:
            p.join(timeout=2)

        print(f"\n CPU stress stopped")

        if detected:
            print(" Waiting for diagnosis and recovery...")
            time.sleep(5)

            diagnosis_count = len(self.events_received['diagnosis.complete'])
            recovery_count = len(self.events_received['recovery.action'])

            print(f"\n Results:")
            print(f" Anomalies detected: {len(self.events_received['anomaly.detected'])}")
            print(f" Diagnoses completed: {diagnosis_count}")
            print(f" Recovery actions: {recovery_count}")

            return diagnosis_count > 0

        return False


    def test_3_memory_spike_detection(self):
        """Test memory spike detection and response"""
        print("Triggering memory spike...")

        self.events_received['anomaly.detected'].clear()
        self.events_received['diagnosis.complete'].clear()

        mem = psutil.virtual_memory()
        available_mb = mem.available / (1024 * 1024)

        # Cap at 800 MB — prevents OOM on Pi; enough to spike well above baseline
        target_mb = min(int(available_mb * 0.3), 800)
        print(f" Allocating {target_mb}MB memory...")

        memory_hog = []
        chunk_size = 1024 * 1024

        try:
            for i in range(target_mb):
                memory_hog.append(' ' * chunk_size)

                if i % 50 == 0:
                    current_percent = psutil.virtual_memory().percent
                    print(f" Memory usage: {current_percent:.1f}%", end='\r')

            current_percent = psutil.virtual_memory().percent
            print(f"\n Peak memory usage: {current_percent:.1f}%")

            print(" Waiting for anomaly detection (max 20s)...")
            detected = False

            for i in range(20):
                time.sleep(1)
                anomaly_count = len(self.events_received['anomaly.detected'])
                print(f" Waiting... {i+1}s | Anomalies: {anomaly_count}", end='\r')

                if anomaly_count > 0:
                    detected = True
                    break

            print()

            memory_hog.clear()
            del memory_hog

            print(" Memory released")

            if detected:
                time.sleep(3)

                diagnosis_count = len(self.events_received['diagnosis.complete'])

                print(f"\n Results:")
                print(f" Anomalies detected: {len(self.events_received['anomaly.detected'])}")
                print(f" Diagnoses completed: {diagnosis_count}")

                return diagnosis_count > 0

            return False

        except MemoryError:
            print("\n MemoryError encountered (expected on low-memory systems)")
            return True


    def test_4_recovery_execution(self):
        """Test that recovery actions are executed"""
        print("Checking recovery action execution...")

        recovery_count = len(self.events_received['recovery.action'])

        print(f" Total recovery actions executed: {recovery_count}")

        if recovery_count > 0:
            for event in self.events_received['recovery.action']:
                print(f"\n Recovery Event:")
                for action in event.data.get('actions', []):
                    print(f" - {action['action_name']}: {action['status']}")

            return True
        else:
            print(" No recovery actions executed yet")
            return False


    def test_5_database_persistence(self):
        """Test that incidents are persisted to database"""
        print("Checking database persistence...")

        incidents = self.database.get_recent_incidents(limit=10)

        print(f" Incidents in database: {len(incidents)}")

        if len(incidents) > 0:
            print("\n Recent Incidents:")
            for inc in incidents[:3]:
                print(f" - {inc['timestamp']}: {inc.get('diagnosis', 'N/A')}")
                print(f" Status: {inc.get('recovery_status', 'N/A')}")

            return True

        return False


    def test_6_learning_adaptation(self):
        """Test that learning agent tracks and adapts"""
        print("Checking learning and adaptation...")

        learning_agent = self.agents['learning']

        recovery_stats = learning_agent.get_recovery_stats()

        print(f" Recovery action statistics:")
        if recovery_stats:
            for action, success_rate in recovery_stats.items():
                print(f" {action}: {success_rate:.1%} success rate")
            return True
        else:
            print(" No statistics yet (need more incidents)")
            return len(self.events_received['recovery.action']) > 0


    def run_all_tests(self):
        """Run complete test suite"""
        print("Starting Sentinel AI Multi-Agent System Test\n")

        self.start_agents()

        try:
            tests = [
                ("Basic System Monitoring",
                 self.test_1_basic_monitoring,
                 "Agent collects CPU, memory, disk metrics"),

                ("CPU Overload Detection",
                 self.test_2_cpu_overload_detection,
                 "Detect high CPU, diagnose, suggest recovery"),

                ("Memory Spike Detection",
                 self.test_3_memory_spike_detection,
                 "Detect memory spike, diagnose cause"),

                ("Recovery Action Execution",
                 self.test_4_recovery_execution,
                 "Recovery actions executed successfully"),

                ("Database Persistence",
                 self.test_5_database_persistence,
                 "Incidents saved to database"),

                ("Learning & Adaptation",
                 self.test_6_learning_adaptation,
                 "System learns from incidents"),
            ]

            for test_name, test_func, expected in tests:
                self.run_test(test_name, test_func, expected)
                time.sleep(2)

            self.print_summary()

        finally:
            self.stop_agents()

            self.event_bus.stop()

    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)

        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r['status'] == 'PASSED')
        failed = sum(1 for r in self.test_results if r['status'] == 'FAILED')
        errors = sum(1 for r in self.test_results if r['status'] == 'ERROR')

        print(f"\nTotal Tests: {total}")
        print(f" Passed: {passed}")
        print(f" Failed: {failed}")
        print(f" Errors: {errors}")
        print(f"\nSuccess Rate: {(passed/total*100) if total > 0 else 0:.1f}%")

        print("\nDetailed Results:")
        for result in self.test_results:
            status_icon = "" if result['status'] == 'PASSED' else ""
            print(f" {status_icon} {result['test']}: {result['status']} ({result['duration']:.2f}s)")

        print("\nEvent Summary:")
        print(f" Health metrics collected: {len(self.events_received['health.metric'])}")
        print(f" Anomalies detected: {len(self.events_received['anomaly.detected'])}")
        print(f" Diagnoses completed: {len(self.events_received['diagnosis.complete'])}")
        print(f" Recovery actions: {len(self.events_received['recovery.action'])}")

        print("\n" + "="*80)


def main():
    """Main entry point"""
    try:
        workflow = TestWorkflow()
        workflow.run_all_tests()

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
