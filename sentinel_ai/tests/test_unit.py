#!/usr/bin/env python3
"""
Sentinel AI — Comprehensive Unit Test Suite
Covers: RemoteDeviceManager, GraduatedEscalationTracker,
        DashboardState, sentinel_client._exec_remote_command,
        and event bus publish/subscribe flow.

Run with:
    python -m pytest tests/test_unit.py -v
  or
    python tests/test_unit.py
"""

import sys
import os
import time
import threading
import unittest
from collections import deque
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

# ── Path setup ────────────────────────────────────────────────────────────────
# Make the project root importable regardless of where pytest is invoked from.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# =============================================================================
# 1. RemoteDeviceManager
# =============================================================================

class TestRemoteDeviceManager(unittest.TestCase):
    """Tests for agents/monitoring/remote_device_manager.py"""

    def _make_manager(self):
        """Return a RemoteDeviceManager wired to a real EventBus."""
        from core.event_bus import EventBus
        bus = EventBus()
        logger = MagicMock()
        from agents.monitoring.remote_device_manager import RemoteDeviceManager
        mgr = RemoteDeviceManager(event_bus=bus, logger=logger)
        return mgr, bus

    # ── register / get_all_devices ────────────────────────────────────────

    def test_register_device(self):
        """Registering a device should make it appear in get_all_devices()."""
        mgr, _ = self._make_manager()
        info = {'hostname': 'testbox', 'platform': 'linux'}
        mgr.register('device-001', info)
        devices = mgr.get_all_devices()
        device_ids = [d['device_id'] for d in devices]
        self.assertIn('device-001', device_ids)

    def test_register_device_stores_metadata(self):
        """Registered device metadata (hostname, platform) should be preserved."""
        mgr, _ = self._make_manager()
        mgr.register('device-002', {'hostname': 'myhost', 'platform': 'windows'})
        d = mgr.get_device('device-002')
        self.assertIsNotNone(d)
        self.assertEqual(d['hostname'], 'myhost')
        self.assertEqual(d['platform'], 'windows')

    # ── is_remote ─────────────────────────────────────────────────────────

    def test_is_remote_registered(self):
        """A registered device_id should return True from is_remote()."""
        mgr, _ = self._make_manager()
        mgr.register('device-abc', {})
        self.assertTrue(mgr.is_remote('device-abc'))

    def test_is_remote_unknown(self):
        """An unknown device_id should return False from is_remote()."""
        mgr, _ = self._make_manager()
        self.assertFalse(mgr.is_remote('no-such-device'))

    # ── queue_command / pop_commands ──────────────────────────────────────

    def test_queue_and_pop_commands(self):
        """Queue 2 commands; first pop returns both; second pop returns empty."""
        mgr, _ = self._make_manager()
        mgr.register('device-q', {})
        cmd1 = {'action': 'compact_memory', 'action_id': 'a1'}
        cmd2 = {'action': 'rotate_logs',    'action_id': 'a2'}
        mgr.queue_command('device-q', cmd1)
        mgr.queue_command('device-q', cmd2)

        popped = mgr.pop_commands('device-q')
        self.assertEqual(len(popped), 2)
        actions = [c['action'] for c in popped]
        self.assertIn('compact_memory', actions)
        self.assertIn('rotate_logs', actions)

        # Second pop must be empty (queue was cleared)
        empty = mgr.pop_commands('device-q')
        self.assertEqual(empty, [])

    def test_pop_commands_unknown_device_returns_empty(self):
        """pop_commands on an unregistered device must not raise and return []."""
        mgr, _ = self._make_manager()
        result = mgr.pop_commands('ghost-device')
        self.assertEqual(result, [])

    # ── push_metrics → event bus ──────────────────────────────────────────

    def test_push_metrics_injects_event(self):
        """push_metrics should publish a health.metric event to the event bus."""
        from core.event_bus import EventBus
        bus = EventBus()
        logger = MagicMock()
        from agents.monitoring.remote_device_manager import RemoteDeviceManager
        mgr = RemoteDeviceManager(event_bus=bus, logger=logger)
        mgr.register('device-push', {'hostname': 'host1', 'platform': 'linux'})

        received = []

        def handler(event):
            received.append(event)

        bus.subscribe('health.metric', handler)

        metrics = {'cpu': {'cpu_percent': 55.0}, 'memory': {'memory_percent': 40.0}}
        ts = datetime.now(timezone.utc).isoformat()
        mgr.push_metrics('device-push', ts, metrics)

        # Give the synchronous bus a moment (it's actually sync, but just in case)
        self.assertGreater(len(received), 0, "Expected at least one health.metric event")
        event = received[0]
        self.assertEqual(event.event_type, 'health.metric')
        self.assertEqual(event.data['device_id'], 'device-push')

    def test_push_metrics_auto_registers_unknown_device(self):
        """push_metrics for an unknown device should auto-register it."""
        mgr, bus = self._make_manager()
        ts = datetime.now(timezone.utc).isoformat()
        mgr.push_metrics('auto-reg-device', ts, {})
        self.assertTrue(mgr.is_remote('auto-reg-device'))

    # ── device age / status transitions ──────────────────────────────────

    def test_device_stale_offline(self):
        """
        Test age_seconds property and that refresh_status transitions
        a device from connected → stale when last_seen is backdated.
        """
        from agents.monitoring.remote_device_manager import RemoteDevice
        d = RemoteDevice('test-dev', {'hostname': 'h', 'platform': 'linux'})

        # Freshly registered → connected
        self.assertEqual(d.status, 'connected')
        self.assertAlmostEqual(d.age_seconds, 0, delta=1)

        # Backdate last_seen past the stale threshold
        stale_threshold = RemoteDevice.STALE_AFTER_S + 5
        d.last_seen = datetime.now(timezone.utc) - timedelta(seconds=stale_threshold)
        d.refresh_status()
        self.assertEqual(d.status, 'stale')

    def test_device_offline_after_60s(self):
        """Device should become offline after OFFLINE_AFTER_S seconds."""
        from agents.monitoring.remote_device_manager import RemoteDevice
        d = RemoteDevice('test-dev-2', {})
        offline_threshold = RemoteDevice.OFFLINE_AFTER_S + 5
        d.last_seen = datetime.now(timezone.utc) - timedelta(seconds=offline_threshold)
        d.refresh_status()
        self.assertEqual(d.status, 'offline')

    def test_device_count(self):
        """device_count() should reflect number of registered devices."""
        mgr, _ = self._make_manager()
        self.assertEqual(mgr.device_count(), 0)
        mgr.register('d1', {})
        mgr.register('d2', {})
        self.assertEqual(mgr.device_count(), 2)


# =============================================================================
# 2. GraduatedEscalationTracker
# =============================================================================

class TestGraduatedEscalationTracker(unittest.TestCase):
    """Tests for GraduatedEscalationTracker in agents/recovery/recovery_agent.py"""

    def _make_tracker(self):
        from agents.recovery.recovery_agent import GraduatedEscalationTracker
        return GraduatedEscalationTracker(window_minutes=30)

    # ── level increases ───────────────────────────────────────────────────

    def test_level_increases_with_incidents(self):
        """
        1st incident → L1, 2nd → L2, 3rd → L3, 4th+ → L4.
        """
        tracker = self._make_tracker()
        self.assertEqual(tracker.record('cpu.cpu_percent'), 1)
        self.assertEqual(tracker.record('cpu.cpu_percent'), 2)
        self.assertEqual(tracker.record('cpu.cpu_percent'), 3)
        self.assertEqual(tracker.record('cpu.cpu_percent'), 4)
        # Extra incidents still cap at 4
        self.assertEqual(tracker.record('cpu.cpu_percent'), 4)

    # ── extra_actions for level 1 CPU ─────────────────────────────────────

    def test_extra_actions_level1_cpu(self):
        """Level 1 extra actions for CPU should include algorithmic_cpu_fix."""
        tracker = self._make_tracker()
        actions = tracker.extra_actions('cpu.cpu_percent', 1)
        self.assertIn('algorithmic_cpu_fix', actions)

    def test_extra_actions_level2_cpu_includes_level1(self):
        """Level 2 extra actions should include both L1 and L2 actions."""
        tracker = self._make_tracker()
        actions = tracker.extra_actions('cpu.cpu_percent', 2)
        self.assertIn('algorithmic_cpu_fix', actions)   # level 1 action
        self.assertIn('throttle_cpu_process', actions)  # level 2 action

    def test_extra_actions_level3_cpu(self):
        """Level 3 should accumulate all actions up to L3."""
        tracker = self._make_tracker()
        actions = tracker.extra_actions('cpu.cpu_percent', 3)
        self.assertIn('kill_top_cpu_process', actions)

    # ── reset ─────────────────────────────────────────────────────────────

    def test_reset_clears_counter(self):
        """record twice, reset, then record once again → back to L1."""
        tracker = self._make_tracker()
        tracker.record('cpu.cpu_percent')
        tracker.record('cpu.cpu_percent')
        tracker.reset('cpu.cpu_percent')
        level = tracker.record('cpu.cpu_percent')
        self.assertEqual(level, 1)

    # ── category mapping ──────────────────────────────────────────────────

    def test_category_mapping_cpu(self):
        """'cpu.cpu_percent' should map to the 'cpu' category."""
        from agents.recovery.recovery_agent import GraduatedEscalationTracker
        cat = GraduatedEscalationTracker._category('cpu.cpu_percent')
        self.assertEqual(cat, 'cpu')

    def test_category_mapping_memory(self):
        """'memory.memory_percent' should map to 'memory'."""
        from agents.recovery.recovery_agent import GraduatedEscalationTracker
        cat = GraduatedEscalationTracker._category('memory.memory_percent')
        self.assertEqual(cat, 'memory')

    def test_category_mapping_disk(self):
        from agents.recovery.recovery_agent import GraduatedEscalationTracker
        self.assertEqual(GraduatedEscalationTracker._category('disk.disk_percent'), 'disk')

    def test_category_mapping_unknown_falls_to_general(self):
        from agents.recovery.recovery_agent import GraduatedEscalationTracker
        self.assertEqual(GraduatedEscalationTracker._category('sensors.temperature'), 'general')

    # ── independent categories ────────────────────────────────────────────

    def test_categories_are_independent(self):
        """CPU and memory escalation counters must not affect each other."""
        tracker = self._make_tracker()
        tracker.record('cpu.cpu_percent')
        tracker.record('cpu.cpu_percent')
        # Memory should start fresh at level 1
        mem_level = tracker.record('memory.memory_percent')
        self.assertEqual(mem_level, 1)

    def test_current_level_starts_at_1(self):
        """current_level on a fresh tracker should return 1."""
        tracker = self._make_tracker()
        self.assertEqual(tracker.current_level('cpu.cpu_percent'), 1)


# =============================================================================
# 3. DashboardState
# =============================================================================

class TestDashboardState(unittest.TestCase):
    """Tests for DashboardState in dashboard/app.py"""

    def _make_state(self):
        """Import and instantiate DashboardState without launching Flask."""
        # We need to import carefully to avoid triggering Flask route setup
        # or agent initialization.  We only need the DashboardState class.
        import importlib, types

        # Build a minimal stub for modules that DashboardState depends on
        # (avoids needing a running Ollama / DB / etc. during unit tests).
        # We rely on the fact that DashboardState.__init__ is simple and only
        # initialises deque/dict attributes — no I/O.
        from dashboard.app import DashboardState
        return DashboardState()

    # ── _device_history ───────────────────────────────────────────────────

    def test_device_history_creates_on_first_access(self):
        """_device_history for a new device_id must create all expected keys."""
        state = self._make_state()
        dh = state._device_history('machine-1')
        self.assertIsNotNone(dh)
        for key in ('cpu', 'memory', 'disk', 'net', 'timestamps'):
            self.assertIn(key, dh, f"Key '{key}' missing from device_history")

    def test_device_history_same_object_on_second_call(self):
        """Calling _device_history twice for the same device should return the same dict."""
        state = self._make_state()
        first  = state._device_history('machine-2')
        second = state._device_history('machine-2')
        self.assertIs(first, second)

    def test_device_history_deques_have_maxlen_60(self):
        """All rolling deques in _device_history should have maxlen=60."""
        state = self._make_state()
        dh = state._device_history('machine-3')
        for key in ('cpu', 'memory', 'disk', 'net', 'timestamps'):
            self.assertEqual(dh[key].maxlen, 60,
                             f"Expected maxlen=60 for key '{key}'")

    # ── _device_deque ─────────────────────────────────────────────────────

    def test_device_deque_creates_on_first_access(self):
        """_device_deque should create a deque with the requested maxlen."""
        state = self._make_state()
        store = {}
        dq = state._device_deque(store, 'dev-x', maxlen=50)
        self.assertIsInstance(dq, deque)
        self.assertEqual(dq.maxlen, 50)

    def test_device_deque_same_object_on_second_call(self):
        """_device_deque with same store+device_id should return same deque."""
        state = self._make_state()
        store = {}
        first  = state._device_deque(store, 'dev-y', maxlen=50)
        second = state._device_deque(store, 'dev-y', maxlen=50)
        self.assertIs(first, second)

    # ── rolling window (maxlen enforcement) ───────────────────────────────

    def test_device_history_rolling(self):
        """Appending 65 items to a maxlen=60 deque must keep only the last 60."""
        state = self._make_state()
        dh = state._device_history('machine-roll')
        cpu_dq = dh['cpu']
        self.assertEqual(cpu_dq.maxlen, 60)

        for i in range(65):
            cpu_dq.append(float(i))

        self.assertEqual(len(cpu_dq), 60)
        # The oldest 5 values (0-4) should have been dropped
        self.assertEqual(cpu_dq[0], 5.0)
        self.assertEqual(cpu_dq[-1], 64.0)

    def test_main_history_deques_have_maxlen_60(self):
        """The top-level rolling history deques must also have maxlen=60."""
        state = self._make_state()
        for attr in ('cpu_history', 'memory_history', 'disk_history',
                     'network_latency_history', 'power_voltage_history',
                     'power_quality_history', 'timestamps'):
            dq = getattr(state, attr)
            self.assertEqual(dq.maxlen, 60,
                             f"Expected maxlen=60 for state.{attr}")


# =============================================================================
# 4. sentinel_client._exec_remote_command
# =============================================================================

class TestExecRemoteCommand(unittest.TestCase):
    """Tests for the _exec_remote_command() function in sentinel_client.py"""

    @classmethod
    def setUpClass(cls):
        """Import sentinel_client once; it doesn't start anything on import."""
        # sentinel_client.py lives at the project root, not inside a package,
        # so we use importlib to load it by file path.
        import importlib.util
        client_path = os.path.join(_PROJECT_ROOT, 'sentinel_client.py')
        spec = importlib.util.spec_from_file_location('sentinel_client', client_path)
        cls.sc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.sc)

    # ── unknown action ────────────────────────────────────────────────────

    def test_unknown_action_returns_skipped(self):
        """An unrecognised action should return status='skipped'."""
        result = self.sc._exec_remote_command('foobar_action_xyz')
        self.assertEqual(result['status'], 'skipped')

    # ── protected process ─────────────────────────────────────────────────

    def test_kill_protected_process_skipped(self):
        """
        When psutil only returns processes named 'python' (in _CRITICAL_PROCS),
        kill_top_cpu_process should return 'skipped'.
        """
        # Build a fake proc with high CPU but a protected name
        mock_proc = MagicMock()
        mock_proc.name.return_value = 'python'
        mock_proc.info = {'pid': 999, 'name': 'python', 'cpu_percent': 99.0}
        mock_proc.pid = 999

        with patch.object(self.sc.psutil, 'process_iter', return_value=[mock_proc]):
            result = self.sc._exec_remote_command('kill_top_cpu_process')
        self.assertEqual(result['status'], 'skipped')

    # ── disk cleanup ──────────────────────────────────────────────────────

    def test_disk_cleanup_runs(self):
        """
        emergency_disk_cleanup should complete without raising and return a
        status of 'success', 'skipped', or 'error'.
        """
        result = self.sc._exec_remote_command('emergency_disk_cleanup')
        self.assertIn(result['status'], ('success', 'skipped', 'error'))

    def test_rotate_logs_runs(self):
        """rotate_logs is handled by the same branch as emergency_disk_cleanup."""
        result = self.sc._exec_remote_command('rotate_logs')
        self.assertIn(result['status'], ('success', 'skipped', 'error'))

    def test_compact_memory_runs(self):
        """compact_memory should not raise and should return a known status."""
        result = self.sc._exec_remote_command('compact_memory')
        self.assertIn(result['status'], ('success', 'skipped', 'error'))


# =============================================================================
# 5. Event flow integration (real EventBus)
# =============================================================================

class TestEventBusFlow(unittest.TestCase):
    """Integration-style tests using the real EventBus."""

    def _make_bus(self):
        from core.event_bus import EventBus
        return EventBus()

    # ── basic pub/sub ─────────────────────────────────────────────────────

    def test_event_publish_subscribe(self):
        """publish health.metric → subscribed handler is called with correct event_type."""
        bus = self._make_bus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe('health.metric', handler)
        bus.create_event(
            event_type='health.metric',
            data={'device_id': 'local', 'metrics': {}},
            source='test',
        )

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].event_type, 'health.metric')

    def test_event_data_preserved(self):
        """Published event data should arrive intact at the subscriber."""
        bus = self._make_bus()
        received = []

        bus.subscribe('health.metric', lambda e: received.append(e))
        bus.create_event(
            event_type='health.metric',
            data={'device_id': 'dev-99', 'metrics': {'cpu': {'cpu_percent': 77.0}}},
            source='test_suite',
        )

        self.assertEqual(received[0].data['device_id'], 'dev-99')
        self.assertEqual(
            received[0].data['metrics']['cpu']['cpu_percent'], 77.0
        )

    # ── multiple subscribers ──────────────────────────────────────────────

    def test_multiple_subscribers_both_called(self):
        """Two handlers subscribed to the same event type must both be called."""
        bus = self._make_bus()
        calls_a = []
        calls_b = []

        bus.subscribe('health.metric', lambda e: calls_a.append(e))
        bus.subscribe('health.metric', lambda e: calls_b.append(e))

        bus.create_event(
            event_type='health.metric',
            data={'device_id': 'multi-test'},
            source='test',
        )

        self.assertEqual(len(calls_a), 1, "Handler A was not called")
        self.assertEqual(len(calls_b), 1, "Handler B was not called")

    def test_handler_not_called_for_different_event(self):
        """A handler subscribed to event A must not be called for event B."""
        bus = self._make_bus()
        received = []

        bus.subscribe('anomaly.detected', lambda e: received.append(e))
        bus.create_event(
            event_type='health.metric',
            data={'device_id': 'noise'},
            source='test',
        )

        self.assertEqual(len(received), 0)

    def test_wildcard_subscriber_receives_all(self):
        """subscribe_all() handler should receive events of any type."""
        bus = self._make_bus()
        received = []

        bus.subscribe_all(lambda e: received.append(e))
        bus.create_event(event_type='health.metric',    data={}, source='test')
        bus.create_event(event_type='anomaly.detected', data={}, source='test')

        self.assertEqual(len(received), 2)

    def test_unsubscribe_stops_delivery(self):
        """After unsubscribe, the handler must no longer receive events."""
        bus = self._make_bus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe('health.metric', handler)
        bus.create_event(event_type='health.metric', data={}, source='test')
        self.assertEqual(len(received), 1)

        bus.unsubscribe('health.metric', handler)
        bus.create_event(event_type='health.metric', data={}, source='test')
        self.assertEqual(len(received), 1)  # still 1, no new delivery

    def test_event_source_field(self):
        """Event source should match what was passed to create_event()."""
        bus = self._make_bus()
        received = []

        bus.subscribe('health.metric', lambda e: received.append(e))
        bus.create_event(
            event_type='health.metric',
            data={},
            source='MonitoringAgent',
        )

        self.assertEqual(received[0].source, 'MonitoringAgent')

    def test_multiple_events_delivered_in_order(self):
        """Events should be delivered to subscribers in publication order."""
        bus = self._make_bus()
        order = []

        bus.subscribe('health.metric', lambda e: order.append(e.data['seq']))
        for i in range(5):
            bus.create_event(
                event_type='health.metric',
                data={'seq': i},
                source='test',
            )

        self.assertEqual(order, [0, 1, 2, 3, 4])


# =============================================================================
# Entry point for `python tests/test_unit.py`
# =============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
