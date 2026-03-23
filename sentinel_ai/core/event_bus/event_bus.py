"""
Event Bus - Internal messaging system for agent communication
Implements publish-subscribe pattern for loose coupling
"""

import asyncio
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum
import json
import uuid


class EventPriority(Enum):
    """Event priority levels"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Event:
    """
    Event data structure
    """
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "unknown"
    priority: EventPriority = EventPriority.NORMAL
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary"""
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['priority'] = self.priority.value
        return result

    def to_json(self) -> str:
        """Convert event to JSON string"""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """Create event from dictionary"""
        if isinstance(data.get('timestamp'), str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        if isinstance(data.get('priority'), int):
            data['priority'] = EventPriority(data['priority'])
        return cls(**data)


EventHandler = Callable[[Event], None]
AsyncEventHandler = Callable[[Event], "Coroutine"]


class EventBus:
    """
    In-memory event bus with support for synchronous and asynchronous handlers
    Thread-safe implementation
    """

    def __init__(self, max_buffer_size: int = 10000, max_retries: int = 3):
        """
        Initialize event bus

        Args:
            max_buffer_size: Maximum number of events to buffer
            max_retries: Maximum number of retries for failed handlers
        """
        self.max_buffer_size = max_buffer_size
        self.max_retries = max_retries

        self._subscribers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._async_subscribers: Dict[str, List[AsyncEventHandler]] = defaultdict(list)

        self._wildcard_subscribers: List[EventHandler] = []
        self._async_wildcard_subscribers: List[AsyncEventHandler] = []

        self._event_buffer: deque = deque(maxlen=max_buffer_size)

        self._lock = threading.RLock()

        self._stats = {
            'events_published': 0,
            'events_delivered': 0,
            'events_failed': 0,
            'subscribers_count': 0
        }

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start the event bus (creates event loop for async handlers)"""
        if self._running:
            return

        self._running = True

        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

        while self._loop is None:
            threading.Event().wait(0.01)

    def stop(self):
        """Stop the event bus"""
        if not self._running:
            return

        self._running = False

        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._loop_thread:
            self._loop_thread.join(timeout=5)

    def subscribe(self, event_type: str, handler: EventHandler):
        """
        Subscribe to an event type

        Args:
            event_type: Event type to subscribe to
            handler: Handler function
        """
        with self._lock:
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)
                self._stats['subscribers_count'] += 1

    def subscribe_async(self, event_type: str, handler: AsyncEventHandler):
        """
        Subscribe to an event type with async handler

        Args:
            event_type: Event type to subscribe to
            handler: Async handler function
        """
        with self._lock:
            if handler not in self._async_subscribers[event_type]:
                self._async_subscribers[event_type].append(handler)
                self._stats['subscribers_count'] += 1

    def subscribe_all(self, handler: EventHandler):
        """
        Subscribe to all events (wildcard subscription)

        Args:
            handler: Handler function
        """
        with self._lock:
            if handler not in self._wildcard_subscribers:
                self._wildcard_subscribers.append(handler)
                self._stats['subscribers_count'] += 1

    def unsubscribe(self, event_type: str, handler: EventHandler):
        """
        Unsubscribe from an event type

        Args:
            event_type: Event type
            handler: Handler to remove
        """
        with self._lock:
            if handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)
                self._stats['subscribers_count'] -= 1

    def publish(self, event: Event):
        """
        Publish an event to all subscribers

        Args:
            event: Event to publish
        """
        with self._lock:
            self._event_buffer.append(event)
            self._stats['events_published'] += 1

            handlers = self._subscribers.get(event.event_type, []).copy()
            handlers.extend(self._wildcard_subscribers)

            async_handlers = self._async_subscribers.get(event.event_type, []).copy()
            async_handlers.extend(self._async_wildcard_subscribers)

        for handler in handlers:
            self._execute_handler(handler, event)

        for handler in async_handlers:
            self._execute_async_handler(handler, event)

    def _execute_handler(self, handler: EventHandler, event: Event):
        """Execute a synchronous handler with retry logic"""
        for attempt in range(self.max_retries):
            try:
                handler(event)
                self._stats['events_delivered'] += 1
                return
            except Exception as e:
                if attempt == self.max_retries - 1:
                    self._stats['events_failed'] += 1
                    print(f"Handler {handler.__name__} failed after {self.max_retries} attempts: {e}")

    def _execute_async_handler(self, handler: AsyncEventHandler, event: Event):
        """Execute an asynchronous handler"""
        if not self._loop:
            return

        async def run_handler():
            for attempt in range(self.max_retries):
                try:
                    await handler(event)
                    self._stats['events_delivered'] += 1
                    return
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        self._stats['events_failed'] += 1
                        print(f"Async handler {handler.__name__} failed: {e}")

        asyncio.run_coroutine_threadsafe(run_handler(), self._loop)

    def create_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        source: str = "unknown",
        priority: EventPriority = EventPriority.NORMAL,
        correlation_id: Optional[str] = None
    ) -> Event:
        """
        Create and publish an event

        Args:
            event_type: Type of event
            data: Event data
            source: Event source (agent name, component, etc.)
            priority: Event priority
            correlation_id: Optional correlation ID for tracing

        Returns:
            Created event
        """
        event = Event(
            event_type=event_type,
            data=data,
            source=source,
            priority=priority,
            correlation_id=correlation_id
        )
        self.publish(event)
        return event

    def get_recent_events(self, count: int = 100, event_type: Optional[str] = None) -> List[Event]:
        """
        Get recent events from buffer

        Args:
            count: Number of events to retrieve
            event_type: Optional filter by event type

        Returns:
            List of recent events
        """
        with self._lock:
            events = list(self._event_buffer)

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        return events[-count:]

    def get_stats(self) -> Dict[str, int]:
        """Get event bus statistics"""
        with self._lock:
            return self._stats.copy()

    def clear_buffer(self):
        """Clear event buffer"""
        with self._lock:
            self._event_buffer.clear()


_global_event_bus: Optional[EventBus] = None


def get_event_bus(config=None) -> EventBus:
    """
    Get global event bus instance (singleton)

    Args:
        config: Optional configuration

    Returns:
        EventBus instance
    """
    global _global_event_bus

    if _global_event_bus is None:
        if config:
            max_buffer = config.get('event_bus.buffer_size', 10000)
            max_retries = config.get('event_bus.max_retries', 3)
            _global_event_bus = EventBus(max_buffer, max_retries)
        else:
            _global_event_bus = EventBus()

        _global_event_bus.start()

    return _global_event_bus
