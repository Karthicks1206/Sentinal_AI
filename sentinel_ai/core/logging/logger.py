"""
Production-Grade Logging Infrastructure
Supports console, file, and CloudWatch logging with structured JSON output
"""

import logging
import logging.handlers
import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import traceback


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs logs in JSON format
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON

        Args:
            record: Log record

        Returns:
            JSON-formatted log string
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info)
            }

        # Add extra fields
        if hasattr(record, 'extra_fields'):
            log_data.update(record.extra_fields)

        # Add device_id and environment from record if available
        if hasattr(record, 'device_id'):
            log_data['device_id'] = record.device_id
        if hasattr(record, 'environment'):
            log_data['environment'] = record.environment

        return json.dumps(log_data)


class StructuredLogger:
    """
    Structured logger with support for extra fields and context
    """

    def __init__(self, name: str, device_id: str = "unknown", environment: str = "production"):
        """
        Initialize structured logger

        Args:
            name: Logger name
            device_id: Device identifier
            environment: Environment (production, staging, etc.)
        """
        self.logger = logging.getLogger(name)
        self.device_id = device_id
        self.environment = environment

    def _add_context(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Add device_id and environment to extra fields"""
        context = {
            'device_id': self.device_id,
            'environment': self.environment
        }
        if extra:
            context.update(extra)
        return context

    def debug(self, message: str, **kwargs):
        """Log debug message"""
        extra = self._add_context(kwargs)
        self.logger.debug(message, extra={'extra_fields': extra})

    def info(self, message: str, **kwargs):
        """Log info message"""
        extra = self._add_context(kwargs)
        self.logger.info(message, extra={'extra_fields': extra})

    def warning(self, message: str, **kwargs):
        """Log warning message"""
        extra = self._add_context(kwargs)
        self.logger.warning(message, extra={'extra_fields': extra})

    def error(self, message: str, **kwargs):
        """Log error message"""
        extra = self._add_context(kwargs)
        self.logger.error(message, extra={'extra_fields': extra})

    def critical(self, message: str, **kwargs):
        """Log critical message"""
        extra = self._add_context(kwargs)
        self.logger.critical(message, extra={'extra_fields': extra})

    def exception(self, message: str, **kwargs):
        """Log exception with traceback"""
        extra = self._add_context(kwargs)
        self.logger.exception(message, extra={'extra_fields': extra})


class LoggingManager:
    """
    Centralized logging manager that configures all logging handlers
    """

    def __init__(self, config):
        """
        Initialize logging manager

        Args:
            config: Configuration object
        """
        self.config = config
        self.handlers = []
        self._setup_logging()

    def _setup_logging(self):
        """Configure all logging handlers"""
        # Get root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        # Clear existing handlers
        root_logger.handlers = []

        # Setup console handler
        if self.config.get('logging.handlers.console.enabled', True):
            self._setup_console_handler()

        # Setup file handler
        if self.config.get('logging.handlers.file.enabled', True):
            self._setup_file_handler()

        # Setup CloudWatch handler (placeholder for now)
        if self.config.get('logging.handlers.cloudwatch.enabled', False):
            self._setup_cloudwatch_handler()

    def _setup_console_handler(self):
        """Setup console logging handler"""
        console_handler = logging.StreamHandler(sys.stdout)
        console_level = self.config.get('logging.handlers.console.level', 'INFO')
        console_handler.setLevel(getattr(logging, console_level))

        # Use JSON format if configured
        log_format = self.config.get('logging.format', 'json')
        if log_format == 'json':
            console_handler.setFormatter(JSONFormatter())
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(formatter)

        logging.getLogger().addHandler(console_handler)
        self.handlers.append(console_handler)

    def _setup_file_handler(self):
        """Setup file logging handler with rotation"""
        log_path = self.config.get('logging.handlers.file.path', 'logs/sentinel.log')
        log_dir = Path(log_path).parent

        # Create log directory if it doesn't exist
        log_dir.mkdir(parents=True, exist_ok=True)

        max_bytes = self.config.get('logging.handlers.file.max_bytes', 100 * 1024 * 1024)  # 100MB
        backup_count = self.config.get('logging.handlers.file.backup_count', 10)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count
        )

        file_level = self.config.get('logging.handlers.file.level', 'DEBUG')
        file_handler.setLevel(getattr(logging, file_level))

        # Always use JSON format for file logs
        file_handler.setFormatter(JSONFormatter())

        logging.getLogger().addHandler(file_handler)
        self.handlers.append(file_handler)

    def _setup_cloudwatch_handler(self):
        """Setup CloudWatch logging handler (AWS integration)"""
        # This will be implemented in the AWS integration layer
        # For now, just log that it's configured
        logging.info("CloudWatch logging configured (handler will be added by AWS module)")

    def get_logger(self, name: str) -> StructuredLogger:
        """
        Get a structured logger instance

        Args:
            name: Logger name

        Returns:
            StructuredLogger instance
        """
        device_id = self.config.device_id
        environment = self.config.environment
        return StructuredLogger(name, device_id, environment)


# Global logging manager
_logging_manager: Optional[LoggingManager] = None


def setup_logging(config) -> LoggingManager:
    """
    Initialize global logging manager

    Args:
        config: Configuration object

    Returns:
        LoggingManager instance
    """
    global _logging_manager
    _logging_manager = LoggingManager(config)
    return _logging_manager


def get_logger(name: str) -> StructuredLogger:
    """
    Get a logger instance

    Args:
        name: Logger name

    Returns:
        StructuredLogger instance
    """
    if _logging_manager is None:
        # Fallback: create basic logger
        return StructuredLogger(name)

    return _logging_manager.get_logger(name)
