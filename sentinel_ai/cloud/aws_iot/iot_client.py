"""
AWS IoT Core Integration
Handles device connectivity, telemetry publishing, and policy management
"""

import json
import ssl
from typing import Dict, Optional, Callable
import threading

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


class AWSIoTClient:
    """
    AWS IoT Core MQTT client for device communication
    """

    def __init__(self, config, logger):
        """
        Initialize AWS IoT client

        Args:
            config: Configuration object
            logger: Logger instance
        """
        self.config = config
        self.logger = logger

        self.iot_config = config.get_section('aws.iot_core')
        self.device_id = config.device_id

        if not self.iot_config.get('enabled', False):
            self.logger.info("AWS IoT Core disabled")
            self.client = None
            return

        if not MQTT_AVAILABLE:
            self.logger.error("paho-mqtt not available, AWS IoT disabled")
            self.client = None
            return

        # MQTT client
        self.client = None
        self.connected = False
        self._message_handlers = {}

        # Topics
        self.topics = self._init_topics()

        # Initialize client
        self._init_client()

    def _init_topics(self) -> Dict[str, str]:
        """Initialize topic names with device ID substitution"""
        topic_templates = self.iot_config.get('topics', {})
        topics = {}

        for key, template in topic_templates.items():
            topics[key] = template.replace('{device_id}', self.device_id)

        return topics

    def _init_client(self):
        """Initialize MQTT client with TLS"""
        try:
            # Get certificate paths
            cert_path = self.iot_config.get('cert_path')
            key_path = self.iot_config.get('key_path')
            ca_path = self.iot_config.get('ca_path')
            endpoint = self.iot_config.get('endpoint')

            if not all([cert_path, key_path, ca_path, endpoint]):
                self.logger.error("AWS IoT certificates or endpoint not configured")
                return

            # Create MQTT client
            self.client = mqtt.Client(
                client_id=self.device_id,
                clean_session=True
            )

            # Set up TLS
            self.client.tls_set(
                ca_certs=ca_path,
                certfile=cert_path,
                keyfile=key_path,
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLSv1_2
            )

            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message

            # Connect
            self.logger.info(f"Connecting to AWS IoT endpoint: {endpoint}")
            self.client.connect(endpoint, 8883, 60)

            # Start network loop
            self.client.loop_start()

        except Exception as e:
            self.logger.error(f"Failed to initialize AWS IoT client: {e}")
            self.client = None

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            self.connected = True
            self.logger.info("Connected to AWS IoT Core")

            # Subscribe to policy topic
            policy_topic = self.topics.get('policy')
            if policy_topic:
                self.client.subscribe(policy_topic, qos=1)
                self.logger.info(f"Subscribed to policy topic: {policy_topic}")

        else:
            self.connected = False
            self.logger.error(f"AWS IoT connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback"""
        self.connected = False
        self.logger.warning(f"Disconnected from AWS IoT Core (rc={rc})")

    def _on_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())

            self.logger.debug(f"Received message on topic {topic}")

            # Call registered handlers
            for handler_topic, handler in self._message_handlers.items():
                if topic.startswith(handler_topic):
                    handler(topic, payload)

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    def publish_telemetry(self, metrics: Dict):
        """
        Publish telemetry data

        Args:
            metrics: Metrics dictionary
        """
        if not self.client or not self.connected:
            self.logger.debug("Not connected to AWS IoT, skipping telemetry publish")
            return

        try:
            topic = self.topics.get('telemetry')
            if not topic:
                return

            payload = {
                'device_id': self.device_id,
                'timestamp': metrics.get('timestamp'),
                'metrics': metrics
            }

            self.client.publish(
                topic,
                json.dumps(payload),
                qos=0
            )

            self.logger.debug(f"Published telemetry to {topic}")

        except Exception as e:
            self.logger.error(f"Failed to publish telemetry: {e}")

    def publish_anomaly(self, anomaly: Dict):
        """
        Publish anomaly event

        Args:
            anomaly: Anomaly data
        """
        if not self.client or not self.connected:
            return

        try:
            topic = self.topics.get('anomalies')
            if not topic:
                return

            payload = {
                'device_id': self.device_id,
                'anomaly': anomaly
            }

            self.client.publish(
                topic,
                json.dumps(payload),
                qos=1
            )

            self.logger.debug(f"Published anomaly to {topic}")

        except Exception as e:
            self.logger.error(f"Failed to publish anomaly: {e}")

    def publish_recovery(self, recovery_data: Dict):
        """
        Publish recovery action result

        Args:
            recovery_data: Recovery action data
        """
        if not self.client or not self.connected:
            return

        try:
            topic = self.topics.get('recovery')
            if not topic:
                return

            payload = {
                'device_id': self.device_id,
                'recovery': recovery_data
            }

            self.client.publish(
                topic,
                json.dumps(payload),
                qos=1
            )

            self.logger.debug(f"Published recovery to {topic}")

        except Exception as e:
            self.logger.error(f"Failed to publish recovery: {e}")

    def subscribe_topic(self, topic: str, handler: Callable, qos: int = 0):
        """
        Subscribe to a topic with handler

        Args:
            topic: MQTT topic
            handler: Message handler function
            qos: QoS level
        """
        if not self.client:
            return

        self._message_handlers[topic] = handler
        self.client.subscribe(topic, qos=qos)
        self.logger.info(f"Subscribed to topic: {topic}")

    def disconnect(self):
        """Disconnect from AWS IoT"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.logger.info("Disconnected from AWS IoT Core")


class CloudWatchPublisher:
    """
    Publishes metrics and logs to AWS CloudWatch
    """

    def __init__(self, config, logger):
        """
        Initialize CloudWatch publisher

        Args:
            config: Configuration object
            logger: Logger instance
        """
        self.config = config
        self.logger = logger

        self.cw_config = config.get_section('aws.cloudwatch')
        self.device_id = config.device_id

        if not self.cw_config.get('enabled', False):
            self.logger.info("AWS CloudWatch disabled")
            self.cloudwatch = None
            return

        if not BOTO3_AVAILABLE:
            self.logger.error("boto3 not available, CloudWatch disabled")
            self.cloudwatch = None
            return

        try:
            region = config.get('aws.region', 'us-east-1')
            self.cloudwatch = boto3.client('cloudwatch', region_name=region)
            self.namespace = self.cw_config.get('namespace', 'SentinelAI')

            self.logger.info("Initialized CloudWatch publisher")

        except Exception as e:
            self.logger.error(f"Failed to initialize CloudWatch: {e}")
            self.cloudwatch = None

    def publish_metrics(self, metrics: Dict):
        """
        Publish metrics to CloudWatch

        Args:
            metrics: Metrics dictionary
        """
        if not self.cloudwatch:
            return

        try:
            # Flatten metrics
            metric_data = []

            for category, values in metrics.items():
                if isinstance(values, dict):
                    for key, value in values.items():
                        if isinstance(value, (int, float)):
                            metric_data.append({
                                'MetricName': f"{category}_{key}",
                                'Value': float(value),
                                'Unit': 'None',
                                'Dimensions': [
                                    {'Name': 'DeviceId', 'Value': self.device_id}
                                ]
                            })

            if metric_data:
                # Send in batches of 20 (CloudWatch limit)
                for i in range(0, len(metric_data), 20):
                    batch = metric_data[i:i+20]
                    self.cloudwatch.put_metric_data(
                        Namespace=self.namespace,
                        MetricData=batch
                    )

                self.logger.debug(f"Published {len(metric_data)} metrics to CloudWatch")

        except Exception as e:
            self.logger.error(f"Failed to publish metrics to CloudWatch: {e}")
