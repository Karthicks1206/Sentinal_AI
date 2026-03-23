"""
Simulation Environment - Emulates system failures for testing
Scenarios: memory spikes, MQTT drops, latency increases, sensor failures, CPU overload
"""

import random
import time
import threading
import psutil
from typing import Dict, Optional
from datetime import datetime


class FailureSimulator:
    """
    Simulates various system failures for testing recovery mechanisms
    """

    def __init__(self, config, logger, event_bus=None):
        """
        Initialize failure simulator

        Args:
            config: Configuration object
            logger: Logger instance
            event_bus: Optional event bus
        """
        self.config = config
        self.logger = logger
        self.event_bus = event_bus

        self.sim_config = config.get_section('simulation')
        self.scenarios = self.sim_config.get('scenarios', {})

        self.running = False
        self._thread = None

    def start(self):
        """Start simulation"""
        if not self.sim_config.get('enabled', False):
            self.logger.info("Simulation disabled")
            return

        self.logger.info("Starting failure simulator...")
        self.running = True

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop simulation"""
        self.logger.info("Stopping failure simulator...")
        self.running = False

        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        """Main simulation loop"""
        while self.running:
            try:
                self._trigger_random_scenario()

                time.sleep(random.randint(30, 120))

            except Exception as e:
                self.logger.error(f"Simulation error: {e}")

    def _trigger_random_scenario(self):
        """Randomly select and trigger a scenario"""
        enabled_scenarios = [
            name for name, cfg in self.scenarios.items()
            if cfg.get('enabled', False)
        ]

        if not enabled_scenarios:
            return

        scenario = random.choice(enabled_scenarios)
        self.logger.info(f"Triggering simulation scenario: {scenario}")

        scenario_methods = {
            'memory_spike': self.simulate_memory_spike,
            'mqtt_drop': self.simulate_mqtt_drop,
            'latency_increase': self.simulate_latency_increase,
            'sensor_failure': self.simulate_sensor_failure,
            'cpu_overload': self.simulate_cpu_overload
        }

        method = scenario_methods.get(scenario)
        if method:
            try:
                method()
            except Exception as e:
                self.logger.error(f"Error in scenario {scenario}: {e}")

    def simulate_memory_spike(self):
        """Simulate a sudden memory spike"""
        config = self.scenarios.get('memory_spike', {})
        duration = config.get('duration_seconds', 60)
        target_percent = config.get('trigger_percent', 90)

        self.logger.warning(f"Simulating memory spike for {duration}s...")

        try:
            mem = psutil.virtual_memory()
            available_mb = mem.available / (1024 * 1024)

            target_mb = int(available_mb * 0.5)

            memory_hog = []
            chunk_size = 1024 * 1024

            for _ in range(target_mb):
                memory_hog.append(' ' * chunk_size)

                current_percent = psutil.virtual_memory().percent
                if current_percent >= target_percent:
                    break

            self.logger.info(f"Memory allocated, current usage: {psutil.virtual_memory().percent}%")

            time.sleep(duration)

            memory_hog.clear()
            del memory_hog

            self.logger.info("Memory spike simulation completed")

        except Exception as e:
            self.logger.error(f"Memory spike simulation failed: {e}")

    def simulate_mqtt_drop(self):
        """Simulate MQTT connection drop"""
        config = self.scenarios.get('mqtt_drop', {})
        duration = config.get('duration_seconds', 30)

        self.logger.warning(f"Simulating MQTT drop for {duration}s...")

        if self.event_bus:
            self.event_bus.create_event(
                event_type="simulation.mqtt_drop",
                data={'duration': duration},
                source='Simulator'
            )

        time.sleep(duration)

        self.logger.info("MQTT drop simulation completed")

    def simulate_latency_increase(self):
        """Simulate network latency increase"""
        config = self.scenarios.get('latency_increase', {})
        duration = config.get('duration_seconds', 45)
        multiplier = config.get('multiplier', 5)

        self.logger.warning(
            f"Simulating latency increase ({multiplier}x) for {duration}s..."
        )

        if self.event_bus:
            self.event_bus.create_event(
                event_type="simulation.latency_increase",
                data={'duration': duration, 'multiplier': multiplier},
                source='Simulator'
            )

        time.sleep(duration)

        self.logger.info("Latency increase simulation completed")

    def simulate_sensor_failure(self):
        """Simulate sensor communication failure"""
        config = self.scenarios.get('sensor_failure', {})
        failure_rate = config.get('failure_rate', 0.1)

        self.logger.warning(f"Simulating sensor failure (rate: {failure_rate})...")

        if self.event_bus:
            self.event_bus.create_event(
                event_type="simulation.sensor_failure",
                data={'failure_rate': failure_rate},
                source='Simulator'
            )

        time.sleep(60)

        self.logger.info("Sensor failure simulation completed")

    def simulate_cpu_overload(self):
        """Simulate CPU overload"""
        config = self.scenarios.get('cpu_overload', {})
        duration = config.get('duration_seconds', 120)
        target_percent = config.get('target_percent', 95)

        self.logger.warning(f"Simulating CPU overload for {duration}s...")

        def cpu_burner(stop_event):
            """Burn CPU cycles"""
            while not stop_event.is_set():
                _ = sum(i * i for i in range(10000))

        cpu_count = psutil.cpu_count()
        num_threads = int(cpu_count * (target_percent / 100))

        stop_event = threading.Event()
        threads = []

        try:
            for _ in range(num_threads):
                t = threading.Thread(target=cpu_burner, args=(stop_event,), daemon=True)
                t.start()
                threads.append(t)

            self.logger.info(f"Started {num_threads} CPU burner threads")

            time.sleep(duration)

        finally:
            stop_event.set()

            for t in threads:
                t.join(timeout=1)

            self.logger.info("CPU overload simulation completed")

    def trigger_specific_scenario(self, scenario_name: str):
        """
        Manually trigger a specific scenario

        Args:
            scenario_name: Name of scenario to trigger
        """
        if scenario_name not in self.scenarios:
            self.logger.error(f"Unknown scenario: {scenario_name}")
            return

        if not self.scenarios[scenario_name].get('enabled', False):
            self.logger.warning(f"Scenario {scenario_name} is disabled")
            return

        self.logger.info(f"Manually triggering scenario: {scenario_name}")

        scenario_methods = {
            'memory_spike': self.simulate_memory_spike,
            'mqtt_drop': self.simulate_mqtt_drop,
            'latency_increase': self.simulate_latency_increase,
            'sensor_failure': self.simulate_sensor_failure,
            'cpu_overload': self.simulate_cpu_overload
        }

        method = scenario_methods.get(scenario_name)
        if method:
            thread = threading.Thread(target=method, daemon=True)
            thread.start()
