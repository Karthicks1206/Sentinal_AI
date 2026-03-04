"""
Base Agent - Abstract base class for all agents
"""

import threading
import time
from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime


class BaseAgent(ABC):
    """
    Base class for all agents in the system
    Provides common functionality for lifecycle management
    """

    def __init__(self, name: str, config, event_bus, logger):
        """
        Initialize base agent

        Args:
            name: Agent name
            config: Configuration object
            event_bus: Event bus for communication
            logger: Logger instance
        """
        self.name = name
        self.config = config
        self.event_bus = event_bus
        self.logger = logger

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.logger.info(f"Initialized {self.name}")

    @abstractmethod
    def _run(self):
        """
        Main agent logic (to be implemented by subclasses)
        This method runs in a separate thread
        """
        pass

    @abstractmethod
    def process_event(self, event):
        """
        Process an event from the event bus

        Args:
            event: Event object
        """
        pass

    def start(self):
        """Start the agent"""
        if self._running:
            self.logger.warning(f"{self.name} is already running")
            return

        self._running = True
        self._stop_event.clear()

        # Start agent thread
        self._thread = threading.Thread(target=self._run_wrapper, daemon=True)
        self._thread.start()

        self.logger.info(f"Started {self.name}")

    def stop(self):
        """Stop the agent"""
        if not self._running:
            return

        self.logger.info(f"Stopping {self.name}...")
        self._running = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=10)

        self.logger.info(f"Stopped {self.name}")

    def _run_wrapper(self):
        """Wrapper for run method with error handling"""
        try:
            self._run()
        except Exception as e:
            self.logger.exception(f"Error in {self.name}: {e}")
            self._running = False

    def is_running(self) -> bool:
        """Check if agent is running"""
        return self._running

    def wait(self, seconds: float) -> bool:
        """
        Wait for specified seconds or until stop is requested

        Args:
            seconds: Time to wait

        Returns:
            True if wait completed, False if interrupted by stop
        """
        return not self._stop_event.wait(seconds)

    def publish_event(self, event_type: str, data: dict, priority=None):
        """
        Publish an event to the event bus

        Args:
            event_type: Type of event
            data: Event data
            priority: Optional event priority
        """
        from core.event_bus import EventPriority

        if priority is None:
            priority = EventPriority.NORMAL

        self.event_bus.create_event(
            event_type=event_type,
            data=data,
            source=self.name,
            priority=priority
        )
