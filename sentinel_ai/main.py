#!/usr/bin/env python3
"""
Sentinel AI - Autonomous Self-Healing Distributed IoT Infrastructure
Main orchestrator that coordinates all agents
"""

import sys
import signal
import time
import threading
import webbrowser
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.config import get_config
from core.logging import setup_logging, get_logger
from core.event_bus import get_event_bus
from core.database import get_database

from agents.monitoring import MonitoringAgent
from agents.anomaly import AnomalyDetectionAgent
from agents.diagnosis import DiagnosisAgent
from agents.recovery import RecoveryAgent
from agents.learning import LearningAgent

from cloud.aws_iot import AWSIoTClient, CloudWatchPublisher


class SentinelAI:
    """
    Main orchestrator for Sentinel AI system
    Manages lifecycle of all agents and components
    """

    def __init__(self, config_path: str = None):
        """
        Initialize Sentinel AI system

        Args:
            config_path: Optional path to config file
        """
        # Load configuration
        self.config = get_config(config_path)

        # Setup logging
        setup_logging(self.config)
        self.logger = get_logger('SentinelAI')

        self.logger.info("="*60)
        self.logger.info("Sentinel AI - Autonomous Self-Healing System")
        self.logger.info(f"Version: {self.config.get('system.version')}")
        self.logger.info(f"Device ID: {self.config.device_id}")
        self.logger.info(f"Environment: {self.config.environment}")
        self.logger.info("="*60)

        # Initialize core infrastructure
        self.event_bus = get_event_bus(self.config)
        self.database = get_database(self.config)

        # Initialize AWS integration
        self.aws_iot = None
        self.cloudwatch = None

        if self.config.get('aws.enabled', False):
            try:
                self.aws_iot = AWSIoTClient(self.config, get_logger('AWSIoT'))
                self.cloudwatch = CloudWatchPublisher(self.config, get_logger('CloudWatch'))
                self.logger.info("AWS integration initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize AWS integration: {e}")

        # Initialize agents
        self.agents = {}
        self._init_agents()

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.running = False

    def _init_agents(self):
        """Initialize all agents"""
        self.logger.info("Initializing agents...")

        try:
            # Monitoring Agent
            if self.config.is_enabled('monitoring'):
                self.agents['monitoring'] = MonitoringAgent(
                    name='MonitoringAgent',
                    config=self.config,
                    event_bus=self.event_bus,
                    logger=get_logger('MonitoringAgent'),
                    database=self.database
                )
                self.logger.info("✓ Monitoring Agent initialized")

            # Anomaly Detection Agent
            if self.config.is_enabled('anomaly_detection'):
                self.agents['anomaly'] = AnomalyDetectionAgent(
                    name='AnomalyDetectionAgent',
                    config=self.config,
                    event_bus=self.event_bus,
                    logger=get_logger('AnomalyDetectionAgent'),
                    database=self.database
                )
                self.logger.info("✓ Anomaly Detection Agent initialized")

            # Diagnosis Agent
            if self.config.is_enabled('diagnosis'):
                self.agents['diagnosis'] = DiagnosisAgent(
                    name='DiagnosisAgent',
                    config=self.config,
                    event_bus=self.event_bus,
                    logger=get_logger('DiagnosisAgent'),
                    database=self.database
                )
                self.logger.info("✓ Diagnosis Agent initialized")

            # Recovery Agent
            if self.config.is_enabled('recovery'):
                self.agents['recovery'] = RecoveryAgent(
                    name='RecoveryAgent',
                    config=self.config,
                    event_bus=self.event_bus,
                    logger=get_logger('RecoveryAgent'),
                    database=self.database
                )
                self.logger.info("✓ Recovery Agent initialized")

            # Learning Agent
            if self.config.is_enabled('learning'):
                self.agents['learning'] = LearningAgent(
                    name='LearningAgent',
                    config=self.config,
                    event_bus=self.event_bus,
                    logger=get_logger('LearningAgent'),
                    database=self.database
                )
                self.logger.info("✓ Learning Agent initialized")

            self.logger.info(f"Successfully initialized {len(self.agents)} agents")

        except Exception as e:
            self.logger.error(f"Failed to initialize agents: {e}", exc_info=True)
            raise

    def start(self):
        """Start all agents and the system"""
        self.logger.info("Starting Sentinel AI system...")

        try:
            # Start all agents
            for name, agent in self.agents.items():
                agent.start()
                self.logger.info(f"Started {name}")

            self.running = True
            self.logger.info("✓ All agents started successfully")

            # Subscribe to events for AWS publishing
            if self.aws_iot:
                self._setup_aws_subscriptions()

            self.logger.info("Sentinel AI is now operational")

            # Main monitoring loop
            self._run()

        except Exception as e:
            self.logger.error(f"Failed to start system: {e}", exc_info=True)
            self.stop()
            raise

    def _setup_aws_subscriptions(self):
        """Setup event subscriptions for AWS publishing"""
        # Publish health metrics to AWS IoT
        def publish_metrics(event):
            if self.aws_iot and self.aws_iot.connected:
                self.aws_iot.publish_telemetry(event.data)
            if self.cloudwatch:
                self.cloudwatch.publish_metrics(event.data.get('metrics', {}))

        # Publish anomalies
        def publish_anomalies(event):
            if self.aws_iot and self.aws_iot.connected:
                self.aws_iot.publish_anomaly(event.data)

        # Publish recovery actions
        def publish_recovery(event):
            if self.aws_iot and self.aws_iot.connected:
                self.aws_iot.publish_recovery(event.data)

        self.event_bus.subscribe("health.metric", publish_metrics)
        self.event_bus.subscribe("anomaly.detected", publish_anomalies)
        self.event_bus.subscribe("recovery.action", publish_recovery)

        self.logger.info("AWS event subscriptions configured")

    def _run(self):
        """Main system loop"""
        try:
            while self.running:
                # Monitor system health
                self._check_system_health()

                # Sleep
                time.sleep(10)

        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
        except Exception as e:
            self.logger.error(f"Error in main loop: {e}", exc_info=True)
        finally:
            self.stop()

    def _check_system_health(self):
        """Check health of all agents"""
        for name, agent in self.agents.items():
            if not agent.is_running():
                self.logger.warning(f"Agent {name} is not running!")

    def stop(self):
        """Stop all agents and shutdown system"""
        if not self.running:
            return

        self.logger.info("Stopping Sentinel AI system...")
        self.running = False

        # Stop all agents
        for name, agent in self.agents.items():
            try:
                agent.stop()
                self.logger.info(f"Stopped {name}")
            except Exception as e:
                self.logger.error(f"Error stopping {name}: {e}")

        # Stop event bus
        try:
            self.event_bus.stop()
            self.logger.info("Event bus stopped")
        except Exception as e:
            self.logger.error(f"Error stopping event bus: {e}")

        # Disconnect from AWS IoT
        if self.aws_iot:
            try:
                self.aws_iot.disconnect()
            except Exception as e:
                self.logger.error(f"Error disconnecting from AWS IoT: {e}")

        # Close database
        try:
            self.database.close()
            self.logger.info("Database closed")
        except Exception as e:
            self.logger.error(f"Error closing database: {e}")

        self.logger.info("Sentinel AI stopped")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}")
        self.running = False

    def get_status(self):
        """Get system status"""
        status = {
            'running': self.running,
            'device_id': self.config.device_id,
            'agents': {},
            'event_bus_stats': self.event_bus.get_stats()
        }

        for name, agent in self.agents.items():
            status['agents'][name] = {
                'running': agent.is_running()
            }

        return status


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Sentinel AI - Autonomous Self-Healing IoT Infrastructure'
    )
    parser.add_argument(
        '--config',
        type=str,
        help='Path to configuration file',
        default=None
    )
    parser.add_argument(
        '--simulate',
        action='store_true',
        help='Enable simulation mode',
        default=False
    )

    args = parser.parse_args()

    # Start dashboard in a background thread
    def start_dashboard():
        try:
            from dashboard.app import run_dashboard
            # run_agents=False: SentinelAI (main.py) owns the agents; dashboard is display-only
            run_dashboard(host='0.0.0.0', port=5001, debug=False, run_agents=False)
        except Exception as e:
            print(f"Dashboard error: {e}")

    dashboard_thread = threading.Thread(target=start_dashboard, daemon=True)
    dashboard_thread.start()

    # Give the dashboard a moment to start, then open browser
    def open_browser():
        time.sleep(3)
        webbrowser.open('http://localhost:5001')

    threading.Thread(target=open_browser, daemon=True).start()

    # Initialize and start system
    sentinel = SentinelAI(config_path=args.config)

    # Register SentinelAI's agents with the dashboard for status display
    try:
        import dashboard.app as _dash_app
        _dash_app.external_agents = sentinel.agents
    except Exception:
        pass

    try:
        sentinel.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
