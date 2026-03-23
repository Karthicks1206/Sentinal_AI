"""
Configuration Management System
Handles loading, validation, and access to system configuration
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from string import Template


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing"""
    pass


class Config:
    """
    Configuration manager with environment variable substitution
    and validation support
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration manager

        Args:
            config_path: Path to config file, defaults to config/config.yaml
        """
        if config_path is None:
            base_dir = Path(__file__).parent.parent
            config_path = base_dir / "config" / "config.yaml"

        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self):
        """Load and parse configuration file with env var substitution"""
        if not self.config_path.exists():
            raise ConfigurationError(f"Config file not found: {self.config_path}")

        try:
            with open(self.config_path, 'r') as f:
                raw_content = f.read()

            content = self._substitute_env_vars(raw_content)

            self._config = yaml.safe_load(content)

            if not self._config:
                raise ConfigurationError("Configuration file is empty")

        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in config file: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load config: {e}")

    def _substitute_env_vars(self, content: str) -> str:
        """
        Substitute environment variables in format ${VAR:-default}

        Args:
            content: Raw configuration content

        Returns:
            Content with environment variables substituted
        """
        import re

        pattern = r'\$\{([^}:]+)(?::-(.[^}]*))?\}'

        def replacer(match):
            var_name = match.group(1)
            default_value = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default_value)

        return re.sub(pattern, replacer, content)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation

        Args:
            key: Configuration key (e.g., 'monitoring.collection_interval')
            default: Default value if key not found

        Returns:
            Configuration value

        Example:
            >>> config.get('monitoring.collection_interval')
            5
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value

    def set(self, key: str, value: Any):
        """
        Set configuration value using dot notation

        Args:
            key: Configuration key
            value: Value to set
        """
        keys = key.split('.')
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def get_section(self, section: str) -> Dict[str, Any]:
        """
        Get entire configuration section

        Args:
            section: Section name

        Returns:
            Section dictionary
        """
        return self.get(section, {})

    def reload(self):
        """Reload configuration from file"""
        self._load_config()

    @property
    def device_id(self) -> str:
        """Get device ID"""
        return self.get('system.device_id', 'unknown-device')

    @property
    def environment(self) -> str:
        """Get environment (production, staging, development)"""
        return self.get('system.environment', 'production')

    @property
    def log_level(self) -> str:
        """Get log level"""
        return self.get('system.log_level', 'INFO')

    def is_enabled(self, feature: str) -> bool:
        """
        Check if a feature is enabled

        Args:
            feature: Feature path (e.g., 'monitoring.enabled')

        Returns:
            True if enabled
        """
        return bool(self.get(f'{feature}.enabled', False))

    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary"""
        return self._config.copy()


_global_config: Optional[Config] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """
    Get global configuration instance (singleton pattern)

    Args:
        config_path: Optional path to config file

    Returns:
        Configuration instance
    """
    global _global_config

    if _global_config is None:
        _global_config = Config(config_path)

    return _global_config


def load_yaml_file(file_path: str) -> Dict[str, Any]:
    """
    Load a YAML file

    Args:
        file_path: Path to YAML file

    Returns:
        Parsed YAML content
    """
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        raise ConfigurationError(f"Failed to load YAML file {file_path}: {e}")
