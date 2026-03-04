#!/usr/bin/env python3
"""
Sentinel AI - Real-Time Visual Monitor
Shows live system status, metrics, and agent activity
"""

import sys
import time
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from core.config import get_config
from core.logging import setup_logging, get_logger
from core.event_bus import get_event_bus
from core.database import get_database

from agents.monitoring import MonitoringAgent
from agents.anomaly import AnomalyDetectionAgent
from agents.diagnosis import DiagnosisAgent
from agents.recovery import RecoveryAgent


class RealtimeMonitor:
    """
    Real-time visual monitor for Sentinel AI
    """

    def __init__(self):
        """Initialize monitor"""
        # Configuration
        self.config = get_config()
        self.config.set('aws.enabled', False)

        setup_logging(self.config)
        self.event_bus = get_event_bus(self.config)
        self.database = get_database(self.config)

        # State tracking
        self.latest_metrics = {}
        self.anomalies = []
        self.diagnoses = []
        self.recoveries = []

        # Subscribe to events
        self.event_bus.subscribe("health.metric", self._on_metric)
        self.event_bus.subscribe("anomaly.detected", self._on_anomaly)
        self.event_bus.subscribe("diagnosis.complete", self._on_diagnosis)
        self.event_bus.subscribe("recovery.action", self._on_recovery)

        # Initialize agents
        self.agents = {
            'monitoring': MonitoringAgent(
                'MonitoringAgent', self.config, self.event_bus,
                get_logger('MonitoringAgent'), self.database
            ),
            'anomaly': AnomalyDetectionAgent(
                'AnomalyDetectionAgent', self.config, self.event_bus,
                get_logger('AnomalyDetectionAgent'), self.database
            ),
            'diagnosis': DiagnosisAgent(
                'DiagnosisAgent', self.config, self.event_bus,
                get_logger('DiagnosisAgent'), self.database
            ),
            'recovery': RecoveryAgent(
                'RecoveryAgent', self.config, self.event_bus,
                get_logger('RecoveryAgent'), self.database
            ),
        }

    def _on_metric(self, event):
        """Handle metric event"""
        self.latest_metrics = event.data.get('metrics', {})

    def _on_anomaly(self, event):
        """Handle anomaly event"""
        self.anomalies.append(event)
        if len(self.anomalies) > 10:
            self.anomalies.pop(0)

    def _on_diagnosis(self, event):
        """Handle diagnosis event"""
        self.diagnoses.append(event)
        if len(self.diagnoses) > 10:
            self.diagnoses.pop(0)

    def _on_recovery(self, event):
        """Handle recovery event"""
        self.recoveries.append(event)
        if len(self.recoveries) > 10:
            self.recoveries.pop(0)

    def clear_screen(self):
        """Clear terminal screen"""
        os.system('clear' if os.name == 'posix' else 'cls')

    def get_status_icon(self, running):
        """Get status icon"""
        return "🟢" if running else "🔴"

    def render_dashboard(self):
        """Render the monitoring dashboard"""
        self.clear_screen()

        print("=" * 80)
        print("SENTINEL AI - REAL-TIME MONITORING DASHBOARD")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        print()

        # Agent Status
        print("AGENT STATUS:")
        print("-" * 80)
        for name, agent in self.agents.items():
            status = self.get_status_icon(agent.is_running())
            print(f"  {status} {name.capitalize()}: {'RUNNING' if agent.is_running() else 'STOPPED'}")
        print()

        # Current Metrics
        print("CURRENT METRICS:")
        print("-" * 80)
        if self.latest_metrics:
            cpu = self.latest_metrics.get('cpu', {})
            memory = self.latest_metrics.get('memory', {})
            disk = self.latest_metrics.get('disk', {})
            network = self.latest_metrics.get('network', {})

            # CPU
            cpu_pct = cpu.get('cpu_percent', 0)
            cpu_bar = self._make_bar(cpu_pct, 100)
            cpu_color = self._get_color(cpu_pct, 80, 90)
            print(f"  CPU:    {cpu_bar} {cpu_color}{cpu_pct:5.1f}%\033[0m")

            # Memory
            mem_pct = memory.get('memory_percent', 0)
            mem_bar = self._make_bar(mem_pct, 100)
            mem_color = self._get_color(mem_pct, 85, 90)
            print(f"  Memory: {mem_bar} {mem_color}{mem_pct:5.1f}%\033[0m")

            # Disk
            disk_pct = disk.get('disk_percent', 0)
            disk_bar = self._make_bar(disk_pct, 100)
            disk_color = self._get_color(disk_pct, 90, 95)
            print(f"  Disk:   {disk_bar} {disk_color}{disk_pct:5.1f}%\033[0m")

            # Network
            pkt_loss = network.get('packet_loss_percent', 0)
            net_color = self._get_color(pkt_loss, 5, 10)
            print(f"  Network: {net_color}Packet Loss: {pkt_loss:.1f}%\033[0m")
        else:
            print("  Waiting for metrics...")
        print()

        # Recent Anomalies
        print("RECENT ANOMALIES:")
        print("-" * 80)
        if self.anomalies:
            for i, event in enumerate(self.anomalies[-5:], 1):
                anomaly = event.data.get('anomaly', {})
                severity = anomaly.get('severity', 'unknown')
                severity_icon = self._get_severity_icon(severity)
                print(f"  {severity_icon} {anomaly.get('metric_name', 'unknown')}: "
                      f"{anomaly.get('type', 'unknown')} "
                      f"(value: {anomaly.get('value', 0):.1f})")
        else:
            print("  No anomalies detected (system healthy)")
        print()

        # Recent Diagnoses
        print("RECENT DIAGNOSES:")
        print("-" * 80)
        if self.diagnoses:
            latest = self.diagnoses[-1].data.get('diagnosis', {})
            print(f"  Latest: {latest.get('diagnosis', 'N/A')}")
            print(f"  Root Cause: {latest.get('root_cause', 'N/A')}")
            print(f"  Actions: {', '.join(latest.get('recommended_actions', []))}")
        else:
            print("  No diagnoses yet")
        print()

        # Recent Recoveries
        print("RECENT RECOVERY ACTIONS:")
        print("-" * 80)
        if self.recoveries:
            for event in self.recoveries[-3:]:
                for action in event.data.get('actions', []):
                    status_icon = "✅" if action['status'] == 'success' else "❌"
                    print(f"  {status_icon} {action['action_name']}: {action['status']}")
        else:
            print("  No recovery actions executed")
        print()

        # Statistics
        print("STATISTICS:")
        print("-" * 80)
        print(f"  Total Anomalies: {len(self.anomalies)}")
        print(f"  Total Diagnoses: {len(self.diagnoses)}")
        print(f"  Total Recoveries: {len(self.recoveries)}")
        print()

        print("=" * 80)
        print("Press Ctrl+C to stop monitoring")
        print("=" * 80)

    def _make_bar(self, value, max_value, width=30):
        """Create a progress bar"""
        filled = int((value / max_value) * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}]"

    def _get_color(self, value, warning, critical):
        """Get ANSI color code based on value"""
        if value >= critical:
            return "\033[91m"  # Red
        elif value >= warning:
            return "\033[93m"  # Yellow
        else:
            return "\033[92m"  # Green

    def _get_severity_icon(self, severity):
        """Get icon for severity level"""
        icons = {
            'low': '🟢',
            'medium': '🟡',
            'high': '🟠',
            'critical': '🔴'
        }
        return icons.get(severity, '⚪')

    def start(self):
        """Start monitoring"""
        print("Starting Sentinel AI agents...")

        # Start all agents
        for name, agent in self.agents.items():
            agent.start()
            print(f"  ✅ {name} started")

        print("\nWaiting for metrics collection...\n")
        time.sleep(3)

        try:
            # Main monitoring loop
            while True:
                self.render_dashboard()
                time.sleep(2)  # Refresh every 2 seconds

        except KeyboardInterrupt:
            print("\n\nStopping monitor...")

        finally:
            # Stop agents
            for name, agent in self.agents.items():
                agent.stop()
            self.event_bus.stop()

            print("Monitor stopped.")


def main():
    """Main entry point"""
    monitor = RealtimeMonitor()
    monitor.start()


if __name__ == '__main__':
    main()
