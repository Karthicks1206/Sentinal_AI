"""
Learning Agent - Manages persistence, learning, and adaptive threshold adjustment
Handles: Incident storage, AWS sync, threshold optimization, strategy refinement
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

from agents.base_agent import BaseAgent
from core.event_bus import EventPriority


class LearningAgent(BaseAgent):
    """
    Agent responsible for learning from incidents and adapting system behavior
    """

    def __init__(self, name: str, config, event_bus, logger, database=None):
        """
        Initialize learning agent

        Args:
            name: Agent name
            config: Configuration
            event_bus: Event bus
            logger: Logger
            database: Database instance
        """
        super().__init__(name, config, event_bus, logger)

        self.database = database
        self.device_id = config.device_id

        # Learning configuration
        self.learning_config = config.get_section('learning')
        self.aws_sync_config = self.learning_config.get('aws_sync', {})
        self.adaptation_config = self.learning_config.get('adaptation', {})

        # AWS clients
        self.dynamodb_client = None
        self.s3_client = None

        if self.aws_sync_config.get('enabled', False):
            self._init_aws_clients()

        # Learning state
        self.incident_history = []
        self.threshold_adjustments = {}
        self.recovery_success_rates = defaultdict(list)

        # Subscribe to events
        self.event_bus.subscribe("diagnosis.complete", self.process_event)
        self.event_bus.subscribe("recovery.action", self._on_recovery_action)

    def _init_aws_clients(self):
        """Initialize AWS clients for cloud sync"""
        if not BOTO3_AVAILABLE:
            self.logger.warning("boto3 not available, AWS sync disabled")
            return

        try:
            region = self.aws_sync_config.get('dynamodb', {}).get('region', 'us-east-1')

            # Initialize DynamoDB client
            if self.aws_sync_config.get('dynamodb', {}).get('table_name'):
                self.dynamodb_client = boto3.client('dynamodb', region_name=region)
                self.logger.info("Initialized DynamoDB client")

            # Initialize S3 client
            if self.aws_sync_config.get('s3', {}).get('bucket_name'):
                self.s3_client = boto3.client('s3', region_name=region)
                self.logger.info("Initialized S3 client")

        except Exception as e:
            self.logger.error(f"Failed to initialize AWS clients: {e}")

    def _run(self):
        """Main learning loop"""
        self.logger.info("Learning agent started")

        sync_interval = self.aws_sync_config.get('sync_interval_minutes', 15) * 60

        while self._running:
            try:
                # Sync to cloud
                if self.aws_sync_config.get('enabled', False):
                    self._sync_to_cloud()

                # Perform adaptive learning
                if self.adaptation_config.get('enabled', False):
                    self._perform_adaptation()

                # Cleanup old data
                self._cleanup_old_data()

            except Exception as e:
                self.logger.error(f"Error in learning loop: {e}", exc_info=True)

            # Wait for next iteration
            if not self.wait(sync_interval):
                break

    def process_event(self, event):
        """
        Process diagnosis events and store incidents

        Args:
            event: Event object
        """
        if event.event_type != "diagnosis.complete":
            return

        try:
            diagnosis = event.data.get('diagnosis', {})
            anomaly = event.data.get('anomaly', {})
            device_id = event.data.get('device_id')
            timestamp = event.data.get('timestamp')

            # Create incident record
            incident = {
                'incident_id': diagnosis.get('diagnosis_id'),
                'timestamp': timestamp,
                'device_id': device_id,
                'anomaly_type': anomaly.get('type'),
                'severity': diagnosis.get('severity'),
                'metrics': {
                    'metric_name': anomaly.get('metric_name'),
                    'value': anomaly.get('value'),
                    'expected_value': anomaly.get('expected_value'),
                    'deviation': anomaly.get('deviation')
                },
                'diagnosis': diagnosis.get('diagnosis'),
                'root_cause': diagnosis.get('root_cause'),
                'recovery_actions': diagnosis.get('recommended_actions', []),
                'recovery_status': 'pending'
            }

            # Store in database
            if self.database:
                self.database.store_incident(incident)

            # Add to history buffer
            self.incident_history.append(incident)

            self.logger.info(f"Stored incident: {incident['incident_id']}")

        except Exception as e:
            self.logger.error(f"Error processing diagnosis event: {e}", exc_info=True)

    def _on_recovery_action(self, event):
        """
        Track recovery action results for learning

        Args:
            event: Recovery action event
        """
        try:
            actions = event.data.get('actions', [])
            diagnosis_id = event.data.get('diagnosis_id')

            # Update incident with recovery status
            if self.database and diagnosis_id:
                # Calculate recovery status
                successful = sum(1 for a in actions if a.get('status') == 'success')
                executed = sum(1 for a in actions if a.get('status') in ('success', 'failed'))

                if successful > 0:
                    status = 'success' if successful == executed else 'partial'
                elif executed > 0:
                    status = 'failed'
                else:
                    status = 'attempted'  # all actions were skipped (cooldown)

                self.database.update_incident(
                    diagnosis_id,
                    {
                        'recovery_status': status,
                        'recovery_actions': json.dumps(actions)
                    }
                )

            # Track success rates for each action type
            for action in actions:
                action_name = action.get('action_name')
                success = action.get('status') == 'success'
                self.recovery_success_rates[action_name].append(success)

                # Keep only recent results
                if len(self.recovery_success_rates[action_name]) > 100:
                    self.recovery_success_rates[action_name].pop(0)

        except Exception as e:
            self.logger.error(f"Error tracking recovery action: {e}")

    def _sync_to_cloud(self):
        """Sync incidents to AWS (DynamoDB and S3)"""
        if not self.database:
            return

        try:
            # Get unsynced incidents
            unsynced = self.database.get_unsynced_incidents(limit=100)

            if not unsynced:
                self.logger.debug("No incidents to sync")
                return

            self.logger.info(f"Syncing {len(unsynced)} incidents to cloud...")

            synced_ids = []

            for incident in unsynced:
                try:
                    # Sync to DynamoDB
                    if self.dynamodb_client:
                        self._sync_to_dynamodb(incident)

                    # Sync to S3
                    if self.s3_client:
                        self._sync_to_s3(incident)

                    synced_ids.append(incident['incident_id'])

                except Exception as e:
                    self.logger.error(f"Failed to sync incident {incident['incident_id']}: {e}")

            # Mark as synced
            if synced_ids:
                self.database.mark_incidents_synced(synced_ids)
                self.logger.info(f"Successfully synced {len(synced_ids)} incidents")

        except Exception as e:
            self.logger.error(f"Cloud sync error: {e}")

    def _sync_to_dynamodb(self, incident: Dict):
        """
        Sync incident to DynamoDB

        Args:
            incident: Incident data
        """
        if not self.dynamodb_client:
            return

        table_name = self.aws_sync_config['dynamodb']['table_name']

        # Parse JSON strings
        metrics = incident.get('metrics')
        if isinstance(metrics, str):
            metrics = json.loads(metrics)

        recovery_actions = incident.get('recovery_actions')
        if isinstance(recovery_actions, str):
            recovery_actions = json.loads(recovery_actions)

        # Prepare item
        item = {
            'incident_id': {'S': incident['incident_id']},
            'timestamp': {'S': incident['timestamp']},
            'device_id': {'S': incident['device_id']},
            'anomaly_type': {'S': incident.get('anomaly_type', 'unknown')},
            'severity': {'S': incident.get('severity', 'unknown')},
            'diagnosis': {'S': incident.get('diagnosis') or 'N/A'},
            'root_cause': {'S': incident.get('root_cause') or 'N/A'},
            'recovery_status': {'S': incident.get('recovery_status', 'unknown')},
            'metrics': {'S': json.dumps(metrics)},
            'recovery_actions': {'S': json.dumps(recovery_actions or [])}
        }

        # Put item
        self.dynamodb_client.put_item(
            TableName=table_name,
            Item=item
        )

    def _sync_to_s3(self, incident: Dict):
        """
        Sync incident to S3

        Args:
            incident: Incident data
        """
        if not self.s3_client:
            return

        bucket = self.aws_sync_config['s3']['bucket_name']
        prefix = self.aws_sync_config['s3'].get('prefix', 'incidents/')

        # Parse JSON strings for complete object
        incident_copy = incident.copy()
        if isinstance(incident_copy.get('metrics'), str):
            incident_copy['metrics'] = json.loads(incident_copy['metrics'])
        if isinstance(incident_copy.get('recovery_actions'), str):
            incident_copy['recovery_actions'] = json.loads(incident_copy['recovery_actions'])

        # Create S3 key with timestamp for partitioning
        timestamp = datetime.fromisoformat(incident['timestamp'])
        key = f"{prefix}{timestamp.year}/{timestamp.month:02d}/{timestamp.day:02d}/{incident['incident_id']}.json"

        # Upload to S3
        self.s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(incident_copy, indent=2),
            ContentType='application/json'
        )

    def _perform_adaptation(self):
        """Perform adaptive learning: adjust thresholds and refine strategies"""
        if not self.database:
            return

        try:
            min_incidents = self.adaptation_config.get('min_incidents_for_learning', 10)

            # Get recent incidents
            recent_incidents = self.database.get_recent_incidents(limit=min_incidents)

            if len(recent_incidents) < min_incidents:
                self.logger.debug("Not enough incidents for adaptation")
                return

            # Adjust thresholds
            if self.adaptation_config.get('threshold_adjustment', True):
                self._adjust_thresholds(recent_incidents)

            # Refine recovery strategies
            if self.adaptation_config.get('strategy_refinement', True):
                self._refine_strategies()

        except Exception as e:
            self.logger.error(f"Adaptation error: {e}")

    def _adjust_thresholds(self, incidents: List[Dict]):
        """
        Adjust anomaly detection thresholds based on historical data

        Args:
            incidents: Recent incidents
        """
        # Analyze incident patterns
        metric_incidents = defaultdict(list)

        for incident in incidents:
            try:
                metrics = incident.get('metrics')
                if isinstance(metrics, str):
                    metrics = json.loads(metrics)

                metric_name = metrics.get('metric_name')
                value = metrics.get('value')
                expected = metrics.get('expected_value')

                if metric_name and value and expected:
                    metric_incidents[metric_name].append({
                        'value': value,
                        'expected': expected,
                        'severity': incident.get('severity')
                    })
            except Exception as e:
                self.logger.debug(f"Error parsing incident metrics: {e}")

        # Adjust thresholds for each metric
        for metric_name, data in metric_incidents.items():
            if len(data) < 5:
                continue

            # Calculate adjustment based on false positive rate
            # If many low-severity incidents, increase threshold
            low_severity_count = sum(1 for d in data if d['severity'] in ['low', 'medium'])
            high_severity_count = len(data) - low_severity_count

            if low_severity_count > high_severity_count * 2:
                # Too many low-severity alerts, increase threshold by 5%
                adjustment = 1.05
                self.threshold_adjustments[metric_name] = adjustment

                # Store in database for persistence
                if self.database:
                    self.database.store_learning_data(
                        data_type='threshold_adjustment',
                        key=metric_name,
                        value=adjustment,
                        metadata={'reason': 'reduce_false_positives', 'incidents': len(data)}
                    )

                self.logger.info(
                    f"Adjusted threshold for {metric_name} by {(adjustment-1)*100:.1f}% "
                    f"(reduce false positives)"
                )

            elif high_severity_count > low_severity_count * 2:
                # Too many critical incidents, decrease threshold by 5%
                adjustment = 0.95
                self.threshold_adjustments[metric_name] = adjustment

                if self.database:
                    self.database.store_learning_data(
                        data_type='threshold_adjustment',
                        key=metric_name,
                        value=adjustment,
                        metadata={'reason': 'increase_sensitivity', 'incidents': len(data)}
                    )

                self.logger.info(
                    f"Adjusted threshold for {metric_name} by {(adjustment-1)*100:.1f}% "
                    f"(increase sensitivity)"
                )

    def _refine_strategies(self):
        """Refine recovery strategies based on success rates"""
        for action_name, results in self.recovery_success_rates.items():
            if len(results) < 5:
                continue

            success_rate = sum(results) / len(results)

            # Store success rate
            if self.database:
                self.database.store_learning_data(
                    data_type='recovery_success_rate',
                    key=action_name,
                    value=success_rate,
                    metadata={'sample_size': len(results)}
                )

            # Log insights
            if success_rate < 0.5:
                self.logger.warning(
                    f"Recovery action '{action_name}' has low success rate: {success_rate:.1%}"
                )
            elif success_rate > 0.9:
                self.logger.info(
                    f"Recovery action '{action_name}' is highly effective: {success_rate:.1%}"
                )

    def _cleanup_old_data(self):
        """Clean up old data based on retention policy"""
        if not self.database:
            return

        try:
            retention_days = self.learning_config.get('local_db', {}).get('retention_days', 90)
            self.database.cleanup_old_data(retention_days)
            self.logger.debug(f"Cleaned up data older than {retention_days} days")

        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")

    def get_threshold_adjustment(self, metric_name: str) -> float:
        """
        Get learned threshold adjustment for a metric

        Args:
            metric_name: Metric name

        Returns:
            Adjustment multiplier (1.0 = no change)
        """
        # Check in-memory cache
        if metric_name in self.threshold_adjustments:
            return self.threshold_adjustments[metric_name]

        # Check database
        if self.database:
            adjustment = self.database.get_learning_data('threshold_adjustment', metric_name)
            if adjustment:
                self.threshold_adjustments[metric_name] = adjustment
                return adjustment

        return 1.0  # No adjustment

    def get_recovery_stats(self) -> Dict[str, float]:
        """Get recovery action success rates"""
        stats = {}

        for action_name, results in self.recovery_success_rates.items():
            if results:
                stats[action_name] = sum(results) / len(results)

        return stats
