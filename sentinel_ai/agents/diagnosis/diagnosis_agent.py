"""
Diagnosis Agent - Performs root cause analysis using rule-based and LLM-powered methods
Integrates with AWS Bedrock for advanced LLM-based diagnostics
"""

import json
import uuid
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import ollama as _ollama_lib
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

try:
    from groq import Groq as _GroqClient
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

from agents.base_agent import BaseAgent
from core.event_bus import EventPriority
from core.config import load_yaml_file


class DiagnosisAgent(BaseAgent):
    """
    Agent responsible for diagnosing root causes of anomalies
    Uses both rule-based reasoning and LLM-powered analysis
    """

    def __init__(self, name: str, config, event_bus, logger, database=None):
        """
        Initialize diagnosis agent

        Args:
            name: Agent name
            config: Configuration
            event_bus: Event bus
            logger: Logger
            database: Optional database
        """
        super().__init__(name, config, event_bus, logger)

        self.database = database
        self.device_id = config.device_id

        # Diagnosis configuration
        self.diagnosis_config = config.get_section('diagnosis')
        self.rules_config = self.diagnosis_config.get('rules', {})
        self.llm_config = self.diagnosis_config.get('llm', {})

        # Load diagnosis rules
        self.rules = []
        if self.rules_config.get('enabled', True):
            self._load_rules()

        # Initialize LLM client (Bedrock)
        self.bedrock_client = None
        if self.llm_config.get('enabled', False):
            self._init_bedrock_client()

        # Initialize OpenAI client (used only if API key is available)
        self.openai_client = None
        self.openai_config = config.get_section('openai') or {}
        if self.openai_config.get('enabled', False):
            self._init_openai_client()

        # Initialize Groq client (fast cloud inference — preferred over Ollama when available)
        self.groq_client = None
        self.groq_config = config.get_section('groq') or {}
        if self.groq_config.get('enabled', True):
            self._init_groq_client()

        # Initialize Ollama AI agent (free, local — fallback when Groq unavailable)
        self.ollama_config = config.get_section('ollama') or {}
        self.ollama_model = self.ollama_config.get('model', 'llama3.2:3b')
        self.ollama_available = self._check_ollama()

        # Buffer for context gathering
        self.recent_metrics = []
        self.recent_anomalies = []

        # Subscribe to anomaly events
        self.event_bus.subscribe("anomaly.detected", self.process_event)

    def _load_rules(self):
        """Load diagnosis rules from configuration"""
        try:
            rules_path = self.rules_config.get('config_path', 'config/diagnosis_rules.yaml')
            rules_data = load_yaml_file(rules_path)
            self.rules = rules_data.get('rules', [])
            self.logger.info(f"Loaded {len(self.rules)} diagnosis rules")
        except Exception as e:
            self.logger.error(f"Failed to load diagnosis rules: {e}")
            self.rules = []

    def _init_bedrock_client(self):
        """Initialize AWS Bedrock client for LLM inference"""
        if not BOTO3_AVAILABLE:
            self.logger.warning("boto3 not available, LLM diagnosis disabled")
            return

        try:
            region = self.llm_config.get('region', 'us-east-1')
            self.bedrock_client = boto3.client(
                service_name='bedrock-runtime',
                region_name=region
            )
            self.logger.info("Initialized AWS Bedrock client")
        except Exception as e:
            self.logger.error(f"Failed to initialize Bedrock client: {e}")
            self.bedrock_client = None

    def _init_openai_client(self):
        """Initialize OpenAI client — reads key from env var or .env file"""
        if not OPENAI_AVAILABLE:
            self.logger.warning("openai package not installed - run: pip install openai")
            return

        import os
        from pathlib import Path

        api_key = os.environ.get('OPENAI_API_KEY', '')

        # If not set in environment, try to load from .env file in project root
        if not api_key:
            env_path = Path(__file__).parent.parent.parent / '.env'
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    line = line.strip()
                    if line.startswith('OPENAI_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
                        os.environ['OPENAI_API_KEY'] = api_key
                        break

        if not api_key:
            self.logger.warning("OpenAI enabled but OPENAI_API_KEY not found in env or .env file")
            return

        try:
            self.openai_client = OpenAI(api_key=api_key)
            model = self.openai_config.get('model', 'gpt-4o')
            self.logger.info(f"OpenAI client initialized (model: {model})")
        except Exception as e:
            self.logger.error(f"Failed to initialize OpenAI client: {e}")
            self.openai_client = None

    def _init_groq_client(self):
        """Initialize Groq client — reads key from env or .env file."""
        if not GROQ_AVAILABLE:
            self.logger.warning("groq package not installed — run: pip install groq")
            return

        import os
        from pathlib import Path

        api_key = os.environ.get('GROQ_API_KEY', '')

        if not api_key:
            env_path = Path(__file__).parent.parent.parent / '.env'
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    line = line.strip()
                    if line.startswith('GROQ_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
                        os.environ['GROQ_API_KEY'] = api_key
                        break

        if not api_key:
            self.logger.info("Groq: GROQ_API_KEY not set — Groq disabled")
            return

        try:
            self.groq_client = _GroqClient(api_key=api_key)
            model = self.groq_config.get('model', 'llama-3.1-8b-instant')
            self.logger.info(f"Groq client initialized (model: {model}) — fast cloud inference active")
        except Exception as e:
            self.logger.error(f"Failed to initialize Groq client: {e}")
            self.groq_client = None

    def _check_ollama(self) -> bool:
        """Check if Ollama is running and the model is available"""
        if not OLLAMA_AVAILABLE:
            self.logger.warning("ollama package not installed - run: pip install ollama")
            return False
        try:
            models = _ollama_lib.list()
            model_names = [m.model for m in models.models]
            # Accept model with or without tag
            base = self.ollama_model.split(':')[0]
            available = any(
                m == self.ollama_model or m.startswith(base + ':')
                for m in model_names
            )
            if available:
                self.logger.info(
                    f"[AI Engine] Ollama ({self.ollama_model}) is online — "
                    f"used for autonomous root-cause analysis when Groq is unavailable. "
                    f"Sentinel AI will run LLM inference locally on this device to diagnose anomalies "
                    f"without sending data to any external cloud service."
                )
            else:
                self.logger.warning(
                    f"Ollama model '{self.ollama_model}' not found. "
                    f"Run: ollama pull {self.ollama_model}"
                )
            return available
        except Exception as e:
            self.logger.warning(
                f"[AI Engine] Ollama not reachable ({e}). "
                f"Sentinel AI will fall back to rule-based diagnosis. "
                f"To enable local LLM diagnosis: brew services start ollama && ollama pull {self.ollama_model}"
            )
            return False

    def _run(self):
        """Main loop (diagnosis is event-driven)"""
        self.logger.info("Diagnosis agent started (event-driven mode)")

        while self._running:
            # Perform periodic cleanup
            try:
                self._cleanup_buffers()
            except Exception as e:
                self.logger.error(f"Error in periodic cleanup: {e}")

            if not self.wait(300):  # 5 minutes
                break

    def process_event(self, event):
        """
        Process anomaly detection events and diagnose root cause.
        Runs in a background thread so Ollama inference doesn't block the event bus.
        """
        if event.event_type != "anomaly.detected":
            return

        # Snapshot data immediately (before handing off to thread)
        anomaly = event.data.get('anomaly', {})
        device_id = event.data.get('device_id')
        timestamp = event.data.get('timestamp')

        self.recent_anomalies.append({'timestamp': timestamp, 'anomaly': anomaly})

        # Run the (potentially slow) Ollama inference off the event bus thread
        threading.Thread(
            target=self._diagnose_and_publish,
            args=(anomaly, device_id, timestamp),
            daemon=True
        ).start()

    def _diagnose_and_publish(self, anomaly: Dict, device_id: str, timestamp: str):
        """Run diagnosis (including Ollama call) and publish result — called from background thread."""
        try:
            diagnosis_result = self.diagnose(anomaly, device_id, timestamp)

            if diagnosis_result:
                self.publish_event(
                    event_type="diagnosis.complete",
                    data={
                        'device_id': device_id,
                        'timestamp': timestamp,
                        'anomaly': anomaly,
                        'diagnosis': diagnosis_result
                    },
                    priority=EventPriority.HIGH
                )
                self.logger.info(
                    f"Diagnosis complete: {diagnosis_result.get('diagnosis', 'Unknown')}"
                )
        except Exception as e:
            self.logger.error(f"Error in diagnosis thread: {e}", exc_info=True)

    def diagnose(self, anomaly: Dict, device_id: str, timestamp: str) -> Optional[Dict]:
        """
        Perform diagnosis using rule-based and LLM methods

        Args:
            anomaly: Anomaly data
            device_id: Device ID
            timestamp: Timestamp

        Returns:
            Diagnosis result dictionary
        """
        diagnosis_result = {
            'diagnosis_id': str(uuid.uuid4()),
            'timestamp': timestamp,
            'anomaly_id': anomaly.get('anomaly_id'),
            'methods_used': [],
            'diagnosis': None,
            'root_cause': None,
            'confidence': 0.0,
            'recommended_actions': [],
            'severity': anomaly.get('severity', 'medium')
        }

        # Method 1: Rule-based diagnosis
        if self.rules_config.get('enabled', True):
            rule_diagnosis = self._diagnose_with_rules(anomaly)
            if rule_diagnosis:
                diagnosis_result.update(rule_diagnosis)
                diagnosis_result['methods_used'].append('rule_based')
                self.logger.debug(f"Rule-based diagnosis: {rule_diagnosis.get('diagnosis')}")

        # Method 2: AI agent diagnosis
        # Priority: Groq (fast, free tier) > Ollama (local) > OpenAI > AWS Bedrock
        llm_diagnosis = None
        context = self._gather_context(device_id, timestamp)

        if self.groq_client:
            llm_diagnosis = self._diagnose_with_groq(anomaly, context)
            if llm_diagnosis:
                diagnosis_result['methods_used'].append('groq_ai')
                self.logger.debug(f"Groq diagnosis: {llm_diagnosis.get('diagnosis')}")

        if not llm_diagnosis and self.ollama_available:
            llm_diagnosis = self._diagnose_with_ollama(anomaly, context)
            if llm_diagnosis:
                diagnosis_result['methods_used'].append('ollama_ai_agent')
                self.logger.debug(f"Ollama diagnosis: {llm_diagnosis.get('diagnosis')}")

        if not llm_diagnosis and self.openai_client:
            llm_diagnosis = self._diagnose_with_openai(anomaly, context)
            if llm_diagnosis:
                diagnosis_result['methods_used'].append('openai')

        if not llm_diagnosis and self.llm_config.get('enabled', False) and self.bedrock_client:
            llm_diagnosis = self._diagnose_with_llm(anomaly, context)
            if llm_diagnosis:
                diagnosis_result['methods_used'].append('llm_powered')

        if llm_diagnosis:
            if not diagnosis_result['diagnosis']:
                diagnosis_result.update(llm_diagnosis)
            else:
                # AI enhances rule-based diagnosis
                diagnosis_result['root_cause'] = llm_diagnosis.get('root_cause', diagnosis_result['root_cause'])
                diagnosis_result['llm_insights'] = llm_diagnosis.get('diagnosis')
                existing = set(diagnosis_result.get('recommended_actions', []))
                for action in llm_diagnosis.get('recommended_actions', []):
                    if action not in existing:
                        diagnosis_result['recommended_actions'].append(action)

        return diagnosis_result if diagnosis_result['diagnosis'] else None

    def _diagnose_with_rules(self, anomaly: Dict) -> Optional[Dict]:
        """
        Diagnose using rule-based reasoning

        Args:
            anomaly: Anomaly data

        Returns:
            Diagnosis result or None
        """
        metric_name = anomaly.get('metric_name', '')
        value = anomaly.get('value', 0)

        # Get recent metrics for context
        recent_data = self._get_recent_metrics()

        # Enrich context with anomaly's own values and string context (e.g. process names)
        bare = metric_name.split('.')[-1]
        recent_data.setdefault(metric_name, value)
        recent_data.setdefault(bare, value)
        for k, v in anomaly.get('context', {}).items():
            recent_data.setdefault(k, v)

        for rule in self.rules:
            if self._match_rule(rule, metric_name, value, recent_data):
                # Format diagnosis with actual values
                diagnosis = rule.get('diagnosis', 'Unknown issue')
                diagnosis = self._format_diagnosis(diagnosis, recent_data)

                return {
                    'diagnosis': diagnosis,
                    'root_cause': rule.get('name'),
                    'confidence': 0.8,
                    'recommended_actions': rule.get('recommended_actions', []),
                    'severity': rule.get('severity', 'medium'),
                    'rule_id': rule.get('id')
                }

        return None

    def _match_rule(self, rule: Dict, metric_name: str, value: float, context: Dict) -> bool:
        """
        Check if a rule matches the current anomaly

        Args:
            rule: Rule definition
            metric_name: Metric name
            value: Metric value
            context: Additional context data

        Returns:
            True if rule matches
        """
        conditions = rule.get('conditions', [])

        for condition in conditions:
            condition_metric = condition.get('metric')
            operator = condition.get('operator')
            threshold = condition.get('value')

            # Get the metric value
            if condition_metric == metric_name:
                metric_value = value
            else:
                metric_value = context.get(condition_metric)

            if metric_value is None:
                continue

            # Check condition
            if operator == '>':
                if not (metric_value > threshold):
                    return False
            elif operator == '<':
                if not (metric_value < threshold):
                    return False
            elif operator == '==':
                if not (metric_value == threshold):
                    return False
            elif operator == 'increasing':
                # Check if trend is increasing
                if not self._check_trend(condition_metric, 'increasing'):
                    return False

        return True

    def _format_diagnosis(self, diagnosis: str, context: Dict) -> str:
        """
        Format diagnosis string with actual values

        Args:
            diagnosis: Diagnosis template
            context: Context data

        Returns:
            Formatted diagnosis
        """
        # Build replacement map with both full keys (cpu.top_process_name)
        # and bare keys (top_process_name) so templates match either form
        replacements = {}
        for key, value in context.items():
            replacements[key] = value
            # Also add the part after the last dot as a bare key
            bare = key.split('.')[-1]
            if bare not in replacements:
                replacements[bare] = value

        for key, value in replacements.items():
            placeholder = f"{{{key}}}"
            if placeholder in diagnosis:
                if isinstance(value, float):
                    diagnosis = diagnosis.replace(placeholder, f"{value:.1f}")
                else:
                    diagnosis = diagnosis.replace(placeholder, str(value))

        return diagnosis

    def _check_trend(self, metric_name: str, trend_type: str) -> bool:
        """
        Check if metric shows a specific trend

        Args:
            metric_name: Metric name
            trend_type: Type of trend (increasing, decreasing)

        Returns:
            True if trend matches
        """
        # Get historical data from database if available
        if not self.database:
            return False

        try:
            history = self.database.get_metrics_history(
                device_id=self.device_id,
                metric_type=metric_name.split('.')[0],
                hours=1
            )

            if len(history) < 5:
                return False

            values = [h.get('value', 0) for h in history[-10:]]

            if trend_type == 'increasing':
                # Check if values are generally increasing
                return values[-1] > values[0] and sum(1 for i in range(len(values)-1) if values[i+1] > values[i]) > len(values) * 0.6
            elif trend_type == 'decreasing':
                return values[-1] < values[0] and sum(1 for i in range(len(values)-1) if values[i+1] < values[i]) > len(values) * 0.6

        except Exception as e:
            self.logger.error(f"Error checking trend: {e}")

        return False

    def _diagnose_with_groq(self, anomaly: Dict, context: Dict) -> Optional[Dict]:
        """
        Diagnose using Groq cloud inference (llama-3.1-8b-instant).
        Groq is ~10x faster than local Ollama and has a generous free tier.
        Falls back to Ollama automatically on any error.
        """
        if not self.groq_client:
            return None

        try:
            metric   = anomaly.get('metric_name', 'unknown')
            value    = anomaly.get('value', 0)
            expected = anomaly.get('expected_value', 0)
            severity = anomaly.get('severity', 'medium')
            atype    = anomaly.get('type', 'unknown')

            recent = context.get('recent_metrics_summary', {})
            context_lines = []
            for mtype, stats in recent.items():
                if isinstance(stats, dict):
                    context_lines.append(
                        f"  {mtype}: mean={stats.get('mean', 0):.1f}, "
                        f"max={stats.get('max', 0):.1f}, min={stats.get('min', 0):.1f}"
                    )
            context_str = '\n'.join(context_lines) or '  No history available'

            model       = self.groq_config.get('model', 'llama-3.1-8b-instant')
            max_tokens  = self.groq_config.get('max_tokens', 512)
            temperature = self.groq_config.get('temperature', 0.2)

            response = self.groq_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert IoT infrastructure AI agent for Sentinel AI, "
                            "a self-healing distributed monitoring system. "
                            "Analyze anomalies, identify root causes, and recommend precise "
                            "recovery actions. Respond ONLY with valid JSON — no markdown."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"""ANOMALY on IoT device:
- Metric: {metric}
- Detection: {atype}
- Value: {value:.3f}  Expected: {expected:.3f}
- Severity: {severity}

System context (1-hour averages):
{context_str}

Available recovery actions (use exact names only):
  restart_mqtt, kill_process, reconnect_sensor, failover, clear_cache, restart_service

Respond with this JSON only:
{{
  "root_cause": "one concise sentence",
  "diagnosis": "clear explanation for an operator",
  "recommended_actions": ["action1"],
  "confidence": 0.85,
  "reasoning": "brief step-by-step reasoning"
}}"""
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"}
            )

            response_text = response.choices[0].message.content
            parsed = self._parse_llm_response(response_text)

            reasoning = parsed.pop('reasoning', None)
            if reasoning:
                self.logger.info(f"Groq reasoning for {metric}: {reasoning[:200]}")

            self.logger.info(
                f"Groq diagnosed {metric}: {parsed.get('root_cause', '?')} "
                f"(confidence: {parsed.get('confidence', 0):.2f})"
            )
            return parsed

        except Exception as e:
            self.logger.warning(f"Groq diagnosis failed (falling back to Ollama): {e}")
            return None

    def _diagnose_with_ollama(self, anomaly: Dict, context: Dict) -> Optional[Dict]:
        """
        Diagnose using a local Ollama AI agent.

        The agent reasons step-by-step about the anomaly, system state,
        and historical context before producing a structured action plan.
        """
        if not self.ollama_available:
            return None

        try:
            metric = anomaly.get('metric_name', 'unknown')
            value = anomaly.get('value', 0)
            expected = anomaly.get('expected_value', 0)
            severity = anomaly.get('severity', 'medium')
            atype = anomaly.get('type', 'unknown')

            # Build rich system context summary
            recent = context.get('recent_metrics_summary', {})
            context_lines = []
            for mtype, stats in recent.items():
                if isinstance(stats, dict):
                    context_lines.append(
                        f"  {mtype}: mean={stats.get('mean', 0):.1f}, "
                        f"max={stats.get('max', 0):.1f}, min={stats.get('min', 0):.1f}"
                    )
            context_str = '\n'.join(context_lines) if context_lines else '  No history available'

            recent_incidents = context.get('recent_incidents_count', 0)

            system_prompt = (
                "You are an expert IoT infrastructure AI agent for Sentinel AI, "
                "a self-healing distributed monitoring system. "
                "Your job is to analyze anomalies, identify root causes, and "
                "recommend precise recovery actions from the available action set. "
                "Always respond with valid JSON only — no markdown, no explanation outside the JSON."
            )

            user_prompt = f"""ANOMALY DETECTED on IoT device:
- Metric: {metric}
- Detection type: {atype}
- Current value: {value:.2f}
- Expected/baseline value: {expected:.2f}
- Severity: {severity}
- Recent incidents in last hour: {recent_incidents}

System state (last 1 hour averages):
{context_str}

Available recovery actions (use exact names):
  restart_mqtt      - Restart the MQTT broker service
  kill_process      - Kill the highest CPU-consuming process
  reconnect_sensor  - Reconnect disconnected sensors
  failover          - Switch to backup MQTT broker
  clear_cache       - Clear application cache directories
  restart_service   - Restart the sentinel-agent service

Task: Analyze this anomaly using step-by-step reasoning, then output a JSON response.

Respond with this exact JSON structure:
{{
  "reasoning": "Step-by-step analysis of what is happening and why",
  "root_cause": "One concise sentence describing the root cause",
  "diagnosis": "Clear explanation of the problem for an operator",
  "recommended_actions": ["action1", "action2"],
  "confidence": 0.85,
  "severity_assessment": "low|medium|high|critical"
}}"""

            response = _ollama_lib.chat(
                model=self.ollama_model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                format='json',
                options={'temperature': 0.2, 'num_predict': 512}
            )

            response_text = response.message.content
            parsed = self._parse_llm_response(response_text)

            reasoning = parsed.pop('reasoning', None)
            if reasoning:
                self.logger.info(f"Ollama reasoning for {metric}: {reasoning[:200]}...")

            self.logger.info(
                f"Ollama AI agent diagnosed {metric}: "
                f"{parsed.get('root_cause', 'unknown')} "
                f"(confidence: {parsed.get('confidence', 0):.2f})"
            )
            return parsed

        except Exception as e:
            self.logger.error(f"Ollama AI agent failed: {e}")
            return None

    def _diagnose_with_openai(self, anomaly: Dict, context: Dict) -> Optional[Dict]:
        """
        Diagnose using OpenAI GPT-4o

        Args:
            anomaly: Anomaly data
            context: Additional context

        Returns:
            OpenAI diagnosis result or None
        """
        if not self.openai_client:
            return None

        try:
            prompt = self._build_llm_prompt(anomaly, context)
            model = self.openai_config.get('model', 'gpt-4o')
            max_tokens = self.openai_config.get('max_tokens', 2048)
            temperature = self.openai_config.get('temperature', 0.3)
            timeout = self.openai_config.get('timeout_seconds', 30)

            response = self.openai_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert IoT infrastructure diagnostician. "
                            "Analyze system anomalies and respond with structured JSON containing "
                            "root cause, diagnosis, recommended_actions, and confidence."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                response_format={"type": "json_object"}
            )

            response_text = response.choices[0].message.content
            parsed = self._parse_llm_response(response_text)
            self.logger.info(
                f"OpenAI diagnosis for {anomaly.get('metric_name')}: "
                f"{parsed.get('root_cause', 'unknown')} (confidence: {parsed.get('confidence', 0):.2f})"
            )
            return parsed

        except Exception as e:
            self.logger.error(f"OpenAI diagnosis failed: {e}")
            return None

    def _diagnose_with_llm(self, anomaly: Dict, context: Dict) -> Optional[Dict]:
        """
        Diagnose using LLM (AWS Bedrock)

        Args:
            anomaly: Anomaly data
            context: Additional context

        Returns:
            LLM diagnosis result or None
        """
        if not self.bedrock_client:
            return None

        try:
            # Prepare prompt for LLM
            prompt = self._build_llm_prompt(anomaly, context)

            # Call Bedrock API
            model_id = self.llm_config.get('model_id', 'anthropic.claude-3-sonnet-20240229-v1:0')
            max_tokens = self.llm_config.get('max_tokens', 2048)
            temperature = self.llm_config.get('temperature', 0.3)

            # Prepare request body (format depends on model)
            if 'anthropic' in model_id:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                })
            else:
                # Generic format
                body = json.dumps({
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature
                })

            # Invoke model
            response = self.bedrock_client.invoke_model(
                modelId=model_id,
                body=body
            )

            # Parse response
            response_body = json.loads(response['body'].read())

            # Extract diagnosis from response
            if 'anthropic' in model_id:
                diagnosis_text = response_body.get('content', [{}])[0].get('text', '')
            else:
                diagnosis_text = response_body.get('completion', response_body.get('generated_text', ''))

            # Parse structured response
            parsed_diagnosis = self._parse_llm_response(diagnosis_text)

            return parsed_diagnosis

        except Exception as e:
            self.logger.error(f"LLM diagnosis failed: {e}")
            return None

    def _build_llm_prompt(self, anomaly: Dict, context: Dict) -> str:
        """
        Build prompt for LLM diagnosis

        Args:
            anomaly: Anomaly data
            context: Context data

        Returns:
            Prompt string
        """
        prompt = f"""You are an expert system diagnostician analyzing IoT infrastructure health issues.

Anomaly Detected:
- Metric: {anomaly.get('metric_name')}
- Type: {anomaly.get('type')}
- Current Value: {anomaly.get('value')}
- Expected Value: {anomaly.get('expected_value')}
- Deviation: {anomaly.get('deviation')}
- Severity: {anomaly.get('severity')}

Recent System Context:
{json.dumps(context, indent=2)}

Please analyze this anomaly and provide:
1. Root Cause Analysis: What is the most likely root cause?
2. Diagnosis: Detailed explanation of what's happening
3. Recommended Actions: List of corrective actions (as action names: restart_mqtt, kill_process, etc.)
4. Confidence: Your confidence level (0.0 to 1.0)

Format your response as JSON:
{{
    "root_cause": "...",
    "diagnosis": "...",
    "recommended_actions": ["action1", "action2"],
    "confidence": 0.85
}}
"""
        return prompt

    def _parse_llm_response(self, response_text: str) -> Dict:
        """
        Parse LLM response into structured format

        Args:
            response_text: LLM response

        Returns:
            Parsed diagnosis dictionary
        """
        try:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)

            if json_match:
                parsed = json.loads(json_match.group())
                return {
                    'root_cause': parsed.get('root_cause', 'Unknown'),
                    'diagnosis': parsed.get('diagnosis', response_text),
                    'recommended_actions': parsed.get('recommended_actions', []),
                    'confidence': float(parsed.get('confidence', 0.7))
                }
            else:
                # Fallback: use raw text
                return {
                    'root_cause': 'LLM Analysis',
                    'diagnosis': response_text,
                    'recommended_actions': [],
                    'confidence': 0.6
                }

        except Exception as e:
            self.logger.error(f"Failed to parse LLM response: {e}")
            return {
                'diagnosis': response_text,
                'confidence': 0.5
            }

    def _gather_context(self, device_id: str, timestamp: str) -> Dict:
        """
        Gather additional context for diagnosis

        Args:
            device_id: Device ID
            timestamp: Current timestamp

        Returns:
            Context dictionary
        """
        context = {
            'device_id': device_id,
            'timestamp': timestamp
        }

        # Get recent metrics from database
        if self.database:
            try:
                recent_metrics = self.database.get_metrics_history(
                    device_id=device_id,
                    hours=1
                )

                # Summarize recent metrics
                if recent_metrics:
                    context['recent_metrics_summary'] = self._summarize_metrics(recent_metrics)

                # Get recent anomalies
                recent_anomalies = self.database.get_recent_incidents(limit=5, device_id=device_id)
                if recent_anomalies:
                    context['recent_incidents_count'] = len(recent_anomalies)

            except Exception as e:
                self.logger.error(f"Error gathering context: {e}")

        # Add buffered anomalies
        context['recent_anomalies'] = self.recent_anomalies[-5:]

        return context

    def _summarize_metrics(self, metrics: List[Dict]) -> Dict:
        """Summarize metrics for context"""
        import pandas as pd

        try:
            df = pd.DataFrame(metrics)
            summary = {}

            for metric_type in df['metric_type'].unique():
                type_metrics = df[df['metric_type'] == metric_type]
                summary[metric_type] = {
                    'mean': type_metrics['value'].mean(),
                    'max': type_metrics['value'].max(),
                    'min': type_metrics['value'].min()
                }

            return summary
        except:
            return {}

    def _get_recent_metrics(self) -> Dict:
        """Get recent metrics from database or buffer"""
        if not self.database:
            return {}

        try:
            metrics = self.database.get_metrics_history(
                device_id=self.device_id,
                hours=1
            )

            if not metrics:
                return {}

            # Get most recent value for each metric
            recent = {}
            for m in metrics:
                key = f"{m['metric_type']}.{m['metric_name']}"
                recent[key] = m['value']

            return recent

        except Exception as e:
            self.logger.error(f"Error getting recent metrics: {e}")
            return {}

    def _cleanup_buffers(self):
        """Cleanup old data from buffers"""
        # Keep only last 100 anomalies
        if len(self.recent_anomalies) > 100:
            self.recent_anomalies = self.recent_anomalies[-100:]
