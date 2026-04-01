#!/usr/bin/env python3
"""
Sentinel AI — Comprehensive Unit Test Suite
Covers: RemoteDeviceManager, GraduatedEscalationTracker,
        DashboardState, sentinel_client._exec_remote_command,
        event bus publish/subscribe flow, per-device big-3 pipeline,
        min_consecutive_readings gate, Groq anomaly validation gate,
        and Groq kill guard.

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

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


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


    def test_is_remote_registered(self):
        """A registered device_id should return True from is_remote()."""
        mgr, _ = self._make_manager()
        mgr.register('device-abc', {})
        self.assertTrue(mgr.is_remote('device-abc'))

    def test_is_remote_unknown(self):
        """An unknown device_id should return False from is_remote()."""
        mgr, _ = self._make_manager()
        self.assertFalse(mgr.is_remote('no-such-device'))


    def test_queue_and_pop_commands(self):
        """Queue 2 commands; first pop returns both; second pop returns empty."""
        mgr, _ = self._make_manager()
        mgr.register('device-q', {})
        cmd1 = {'action': 'compact_memory', 'action_id': 'a1'}
        cmd2 = {'action': 'rotate_logs', 'action_id': 'a2'}
        mgr.queue_command('device-q', cmd1)
        mgr.queue_command('device-q', cmd2)

        popped = mgr.pop_commands('device-q')
        self.assertEqual(len(popped), 2)
        actions = [c['action'] for c in popped]
        self.assertIn('compact_memory', actions)
        self.assertIn('rotate_logs', actions)

        empty = mgr.pop_commands('device-q')
        self.assertEqual(empty, [])

    def test_pop_commands_unknown_device_returns_empty(self):
        """pop_commands on an unregistered device must not raise and return []."""
        mgr, _ = self._make_manager()
        result = mgr.pop_commands('ghost-device')
        self.assertEqual(result, [])


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


    def test_device_stale_offline(self):
        """
        Test age_seconds property and that refresh_status transitions
        a device from connected → stale when last_seen is backdated.
        """
        from agents.monitoring.remote_device_manager import RemoteDevice
        d = RemoteDevice('test-dev', {'hostname': 'h', 'platform': 'linux'})

        self.assertEqual(d.status, 'connected')
        self.assertAlmostEqual(d.age_seconds, 0, delta=1)

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


class TestGraduatedEscalationTracker(unittest.TestCase):
    """Tests for GraduatedEscalationTracker in agents/recovery/recovery_agent.py"""

    def _make_tracker(self):
        from agents.recovery.recovery_agent import GraduatedEscalationTracker
        return GraduatedEscalationTracker(window_minutes=30)


    def test_level_increases_with_incidents(self):
        """
        1st incident → L1, 2nd → L2, 3rd → L3, 4th+ → L4.
        """
        tracker = self._make_tracker()
        self.assertEqual(tracker.record('cpu.cpu_percent'), 1)
        self.assertEqual(tracker.record('cpu.cpu_percent'), 2)
        self.assertEqual(tracker.record('cpu.cpu_percent'), 3)
        self.assertEqual(tracker.record('cpu.cpu_percent'), 4)
        self.assertEqual(tracker.record('cpu.cpu_percent'), 4)


    def test_extra_actions_level1_cpu(self):
        """Level 1 extra actions for CPU should include algorithmic_cpu_fix."""
        tracker = self._make_tracker()
        actions = tracker.extra_actions('cpu.cpu_percent', 1)
        self.assertIn('algorithmic_cpu_fix', actions)

    def test_extra_actions_level2_cpu_includes_level1(self):
        """Level 2 extra actions should include both L1 and L2 actions."""
        tracker = self._make_tracker()
        actions = tracker.extra_actions('cpu.cpu_percent', 2)
        self.assertIn('algorithmic_cpu_fix', actions)
        self.assertIn('throttle_cpu_process', actions)

    def test_extra_actions_level3_cpu(self):
        """Level 3 should accumulate all actions up to L3."""
        tracker = self._make_tracker()
        actions = tracker.extra_actions('cpu.cpu_percent', 3)
        self.assertIn('kill_top_cpu_process', actions)


    def test_reset_clears_counter(self):
        """record twice, reset, then record once again → back to L1."""
        tracker = self._make_tracker()
        tracker.record('cpu.cpu_percent')
        tracker.record('cpu.cpu_percent')
        tracker.reset('cpu.cpu_percent')
        level = tracker.record('cpu.cpu_percent')
        self.assertEqual(level, 1)


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


    def test_categories_are_independent(self):
        """CPU and memory escalation counters must not affect each other."""
        tracker = self._make_tracker()
        tracker.record('cpu.cpu_percent')
        tracker.record('cpu.cpu_percent')
        mem_level = tracker.record('memory.memory_percent')
        self.assertEqual(mem_level, 1)

    def test_current_level_starts_at_1(self):
        """current_level on a fresh tracker should return 1."""
        tracker = self._make_tracker()
        self.assertEqual(tracker.current_level('cpu.cpu_percent'), 1)


class TestDashboardState(unittest.TestCase):
    """Tests for DashboardState in dashboard/app.py"""

    def _make_state(self):
        """Import and instantiate DashboardState without launching Flask."""
        import importlib, types

        from dashboard.app import DashboardState
        return DashboardState()


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
        first = state._device_history('machine-2')
        second = state._device_history('machine-2')
        self.assertIs(first, second)

    def test_device_history_deques_have_maxlen_60(self):
        """All rolling deques in _device_history should have maxlen=60."""
        state = self._make_state()
        dh = state._device_history('machine-3')
        for key in ('cpu', 'memory', 'disk', 'net', 'timestamps'):
            self.assertEqual(dh[key].maxlen, 60,
                             f"Expected maxlen=60 for key '{key}'")


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
        first = state._device_deque(store, 'dev-y', maxlen=50)
        second = state._device_deque(store, 'dev-y', maxlen=50)
        self.assertIs(first, second)


    def test_device_history_rolling(self):
        """Appending 65 items to a maxlen=60 deque must keep only the last 60."""
        state = self._make_state()
        dh = state._device_history('machine-roll')
        cpu_dq = dh['cpu']
        self.assertEqual(cpu_dq.maxlen, 60)

        for i in range(65):
            cpu_dq.append(float(i))

        self.assertEqual(len(cpu_dq), 60)
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


class TestExecRemoteCommand(unittest.TestCase):
    """Tests for the _exec_remote_command() function in sentinel_client.py"""

    @classmethod
    def setUpClass(cls):
        """Import sentinel_client once; it doesn't start anything on import."""
        import importlib.util
        client_path = os.path.join(_PROJECT_ROOT, 'sentinel_client.py')
        spec = importlib.util.spec_from_file_location('sentinel_client', client_path)
        cls.sc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.sc)


    def test_unknown_action_returns_skipped(self):
        """An unrecognised action should return status='skipped'."""
        result = self.sc._exec_remote_command('foobar_action_xyz')
        self.assertEqual(result['status'], 'skipped')


    def test_kill_protected_process_skipped(self):
        """
        When psutil only returns processes named 'python' (in _CRITICAL_PROCS),
        kill_top_cpu_process should return 'skipped'.
        """
        mock_proc = MagicMock()
        mock_proc.name.return_value = 'python'
        mock_proc.info = {'pid': 999, 'name': 'python', 'cpu_percent': 99.0}
        mock_proc.pid = 999

        with patch.object(self.sc.psutil, 'process_iter', return_value=[mock_proc]):
            result = self.sc._exec_remote_command('kill_top_cpu_process')
        self.assertEqual(result['status'], 'skipped')


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


class TestEventBusFlow(unittest.TestCase):
    """Integration-style tests using the real EventBus."""

    def _make_bus(self):
        from core.event_bus import EventBus
        return EventBus()


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
        bus.create_event(event_type='health.metric', data={}, source='test')
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
        self.assertEqual(len(received), 1)

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



class TestRemoteStressCommands(unittest.TestCase):
    """
    Contract-driven tests for sentinel_client._exec_remote_command.

    Every action the recovery agent can dispatch must be handled on the client.
    No action should return "not supported on remote client".
    Tests are written from REQUIREMENTS (what the hub sends) not from the
    current implementation, so they catch gaps when new hub actions are added.
    """

    ALL_HUB_RECOVERY_ACTIONS = [
        'kill_process', 'kill_top_cpu_process', 'kill_top_memory_process',
        'throttle_cpu_process', 'algorithmic_cpu_fix',
        'compact_memory', 'clear_cache', 'algorithmic_memory_fix',
        'emergency_disk_cleanup', 'rotate_logs', 'algorithmic_disk_fix',
        'flush_dns', 'check_network', 'reset_network_interface',
        'algorithmic_network_fix', 'restart_mqtt',
        'restart_service', 'reconnect_sensor', 'restart_process_by_name',
        'failover', 'full_system_restart',
    ]

    @classmethod
    def setUpClass(cls):
        import importlib.util
        client_path = os.path.join(_PROJECT_ROOT, 'sentinel_client.py')
        spec = importlib.util.spec_from_file_location('sentinel_client_stress', client_path)
        cls.sc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.sc)
        cls.sc._stress_stop.clear()
        cls.sc._stress_threads.clear()

    def setUp(self):
        self.sc._stress_stop.set()
        time.sleep(0.05)
        self.sc._stress_stop.clear()
        self.sc._stress_threads[:] = [t for t in self.sc._stress_threads if t.is_alive()]

    def tearDown(self):
        """Stop all stress threads after every test — no leaked threads between tests."""
        self.sc._stress_stop.set()
        alive = [t for t in self.sc._stress_threads if t.is_alive()]
        for t in alive:
            t.join(timeout=3.0)
        self.sc._stress_threads[:] = [t for t in self.sc._stress_threads if t.is_alive()]

    @classmethod
    def tearDownClass(cls):
        """Final safety net: ensure all stress threads are dead after the class."""
        cls.sc._stress_stop.set()
        for t in cls.sc._stress_threads:
            t.join(timeout=5.0)
        cls.sc._stress_threads.clear()

    def _run(self, action):
        return self.sc._exec_remote_command(action)

    def _assert_handled(self, action, result):
        self.assertNotEqual(
            result.get('message', ''),
            "action '{}' not supported on remote client".format(action),
            msg="Action '{}' fell through to unsupported fallback — add it to _exec_remote_command".format(action)
        )
        self.assertIn(result.get('status'), ('success', 'skipped'),
                      msg="Action '{}' returned unexpected status: {}".format(action, result))

    def test_contract_no_recovery_action_falls_through_to_unsupported(self):
        """Contract: every hub recovery action must be handled — no 'not supported' allowed."""
        self.sc._stress_stop.set()
        time.sleep(0.1)
        for action in self.ALL_HUB_RECOVERY_ACTIONS:
            with self.subTest(action=action):
                result = self._run(action)
                self._assert_handled(action, result)

    def test_stress_cpu_returns_success_and_spawns_double_core_threads(self):
        import os
        result = self._run('stress_cpu')
        self.assertEqual(result['status'], 'success')
        cpu_threads = [t for t in self.sc._stress_threads
                       if 'sentinel_stress_cpu' in t.name and t.is_alive()]
        expected = max(2, (os.cpu_count() or 2) * 2)
        self.assertEqual(len(cpu_threads), expected,
                         msg='Expected {}x cpu_count threads to fight GIL, got {}'.format(2, len(cpu_threads)))
        self.sc._stress_stop.set()

    def test_stress_memory_allocates_30_pct_of_total_ram(self):
        import psutil
        total_mb = psutil.virtual_memory().total // (1024 * 1024)
        expected_mb = max(512, int(total_mb * 0.30))
        result = self._run('stress_memory')
        self.assertEqual(result['status'], 'success')
        self.assertIn(str(expected_mb), result['message'],
                      msg='Memory stress must allocate 30% of RAM ({} MB), not a fixed size'.format(expected_mb))
        self.sc._stress_stop.set()

    def test_stress_disk_runs_and_cleans_up_temp_file(self):
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), 'sentinel_disk_stress.tmp')
        if os.path.exists(tmp):
            os.remove(tmp)
        result = self._run('stress_disk')
        self.assertEqual(result['status'], 'success')
        disk_threads = [t for t in self.sc._stress_threads
                        if t.name == 'sentinel_stress_disk' and t.is_alive()]
        self.sc._stress_stop.set()
        for t in disk_threads:
            t.join(timeout=3.0)
        self.assertFalse(os.path.exists(tmp), msg='Disk stress must clean up temp file on stop')

    def test_stop_stress_terminates_all_running_threads(self):
        self._run('stress_cpu')
        running = [t for t in self.sc._stress_threads if t.is_alive()]
        self.assertGreater(len(running), 0)
        self._run('stop_stress')
        for t in running:
            t.join(timeout=2.0)
            self.assertFalse(t.is_alive(), msg='Thread {} must stop after stop_stress'.format(t.name))

    def test_kill_process_is_handled_not_skipped_as_unsupported(self):
        result = self._run('kill_process')
        self._assert_handled('kill_process', result)

    def test_flush_dns_runs_on_current_platform(self):
        result = self._run('flush_dns')
        self.assertEqual(result['status'], 'success')
        self.assertIn('DNS', result['message'])

    def test_check_network_reports_probe_results(self):
        result = self._run('check_network')
        self.assertEqual(result['status'], 'success')
        self.assertIn('network check', result['message'])
        self.assertTrue(any(h in result['message'] for h in ['8.8.8.8', '1.1.1.1']))

    def test_algorithmic_cpu_fix_handled(self):
        self._assert_handled('algorithmic_cpu_fix', self._run('algorithmic_cpu_fix'))

    def test_algorithmic_memory_fix_handled(self):
        self._assert_handled('algorithmic_memory_fix', self._run('algorithmic_memory_fix'))

    def test_algorithmic_disk_fix_handled(self):
        self._assert_handled('algorithmic_disk_fix', self._run('algorithmic_disk_fix'))

    def test_algorithmic_network_fix_handled(self):
        self._assert_handled('algorithmic_network_fix', self._run('algorithmic_network_fix'))

    def test_service_stubs_return_success_not_error(self):
        for action in ('restart_service', 'restart_mqtt', 'reconnect_sensor'):
            with self.subTest(action=action):
                result = self._run(action)
                self.assertEqual(result['status'], 'success',
                                 msg="'{}' must return success (stub), not error or not-supported".format(action))

    def test_restart_process_by_name_handled(self):
        self._assert_handled('restart_process_by_name', self._run('restart_process_by_name'))

    def test_failover_handled(self):
        self._assert_handled('failover', self._run('failover'))

    def test_full_system_restart_blocked_for_safety_not_unsupported(self):
        result = self._run('full_system_restart')
        self.assertEqual(result['status'], 'skipped',
                         msg='full_system_restart must be explicitly blocked, not silently unsupported')
        self.assertNotIn('not supported', result['message'])
        self.assertIn('blocked', result['message'])

    def test_demo_cpu_saturates_double_core_count_threads(self):
        import os
        result = self._run('demo_cpu')
        self.assertEqual(result['status'], 'success')
        demo_threads = [t for t in self.sc._stress_threads
                        if 'sentinel_demo_cpu' in t.name and t.is_alive()]
        expected = max(2, (os.cpu_count() or 2) * 2)
        self.assertEqual(len(demo_threads), expected)
        self.sc._stress_stop.set()

    def test_demo_memory_allocates_40_pct_of_total_ram(self):
        import psutil
        total_mb = psutil.virtual_memory().total // (1024 * 1024)
        expected_mb = max(1024, int(total_mb * 0.40))
        result = self._run('demo_memory')
        self.assertEqual(result['status'], 'success')
        self.assertIn(str(expected_mb), result['message'])
        self.sc._stress_stop.set()

    def test_demo_full_spawns_both_cpu_and_memory_threads(self):
        result = self._run('demo_full')
        self.assertEqual(result['status'], 'success')
        cpu_threads = [t for t in self.sc._stress_threads
                       if 'sentinel_demo_full_cpu' in t.name and t.is_alive()]
        mem_threads = [t for t in self.sc._stress_threads
                       if t.name == 'sentinel_demo_full_mem' and t.is_alive()]
        self.assertGreater(len(cpu_threads), 0, msg='demo_full must spawn CPU threads')
        self.assertGreaterEqual(len(mem_threads), 1, msg='demo_full must spawn a memory thread')
        self.sc._stress_stop.set()

    def test_stop_stress_terminates_demo_threads(self):
        self._run('demo_full')
        running = [t for t in self.sc._stress_threads if t.is_alive()]
        self.assertGreater(len(running), 0)
        self._run('stop_stress')
        for t in running:
            t.join(timeout=2.0)
            self.assertFalse(t.is_alive())


class TestRemoteBig3Pipeline(unittest.TestCase):
    """
    End-to-end tests for the Anomaly → Diagnosis → Recovery pipeline
    for REMOTE devices.  Verifies that:

    1. health.metric events from remote devices produce per-device baselines
       (not a shared global baseline that would pollute cross-device detection).
    2. anomaly.detected events carry the correct remote device_id.
    3. The diagnosis agent passes device_id through to its context helpers.
    4. The recovery agent routes actions to the remote command queue rather
       than executing them locally.
    """

    # ------------------------------------------------------------------ helpers

    def _make_anomaly_agent(self):
        from core.event_bus import EventBus
        from agents.anomaly.anomaly_detection_agent import AnomalyDetectionAgent

        bus = EventBus()
        logger = MagicMock()

        cfg = MagicMock()
        cfg.device_id = 'hub-local'
        cfg.get_section.return_value = {
            'methods': {'z_score': {'threshold': 2.5}},
            'ml': {'enabled': False},
            'baseline': {'window_size': 30, 'update_interval_minutes': 15},
        }
        cfg.get.side_effect = lambda key, default=None: {
            'anomaly_detection.min_consecutive_readings': 2,
            'anomaly_detection.cooldown_minutes': 5,
        }.get(key, default)

        agent = AnomalyDetectionAgent(
            name='anomaly_agent', config=cfg,
            event_bus=bus, logger=logger, database=None
        )
        return agent, bus

    def _make_diagnosis_agent(self):
        from core.event_bus import EventBus
        from agents.diagnosis.diagnosis_agent import DiagnosisAgent

        bus = EventBus()
        logger = MagicMock()

        cfg = MagicMock()
        cfg.device_id = 'hub-local'
        cfg.get_section.return_value = {}
        cfg.get.return_value = None

        agent = DiagnosisAgent(
            name='diagnosis_agent', config=cfg,
            event_bus=bus, logger=logger, database=None
        )
        return agent, bus

    # ------------------------------------------- anomaly baseline isolation

    def test_remote_device_gets_independent_baseline(self):
        """
        Metrics from device-A and device-B must maintain completely separate
        baselines so that one device's normal range cannot inflate the other's.
        """
        agent, _ = self._make_anomaly_agent()

        # Warm up device-A at a low CPU level (20-30%)
        for v in ([25.0] * 35):
            agent.detect_anomalies({'cpu.cpu_percent': v}, 'ts', 'device-A')

        # Warm up device-B at a high CPU level (70-80%)
        for v in ([75.0] * 35):
            agent.detect_anomalies({'cpu.cpu_percent': v}, 'ts', 'device-B')

        key_a = ('device-A', 'cpu.cpu_percent')
        key_b = ('device-B', 'cpu.cpu_percent')

        self.assertIn(key_a, agent._baselines, "device-A baseline not created")
        self.assertIn(key_b, agent._baselines, "device-B baseline not created")

        stats_a = agent._baselines[key_a].stats()
        stats_b = agent._baselines[key_b].stats()

        self.assertIsNotNone(stats_a)
        self.assertIsNotNone(stats_b)

        # device-A's mean must be near 25, device-B's near 75 — not merged
        self.assertLess(stats_a['mean'], 40,
            "device-A baseline contaminated by device-B high-CPU data")
        self.assertGreater(stats_b['mean'], 60,
            "device-B baseline contaminated by device-A low-CPU data")

    def test_local_device_has_own_baseline_separate_from_remote(self):
        """Local hub baseline must not be shared with any remote device."""
        agent, _ = self._make_anomaly_agent()

        for v in [10.0] * 35:
            agent.detect_anomalies({'cpu.cpu_percent': v}, 'ts', 'hub-local')
        for v in [90.0] * 35:
            agent.detect_anomalies({'cpu.cpu_percent': v}, 'ts', 'remote-pi')

        local_key  = ('hub-local', 'cpu.cpu_percent')
        remote_key = ('remote-pi', 'cpu.cpu_percent')

        self.assertIn(local_key, agent._baselines)
        self.assertIn(remote_key, agent._baselines)
        self.assertIsNot(
            agent._baselines[local_key],
            agent._baselines[remote_key],
            "hub-local and remote-pi share the same baseline object — isolation broken"
        )

    def test_cooldown_is_per_device_not_global(self):
        """
        Firing an anomaly on device-A must not suppress anomaly detection
        on device-B (they have independent cooldown timers).
        """
        agent, _ = self._make_anomaly_agent()
        agent.cooldown_minutes = 999  # very long cooldown

        # Warm up both devices then inject identical anomalies
        for _ in range(35):
            agent.detect_anomalies({'cpu.cpu_percent': 20.0}, 'ts', 'dev-alpha')
            agent.detect_anomalies({'cpu.cpu_percent': 20.0}, 'ts', 'dev-beta')

        # Fire anomaly on dev-alpha (sets last_fired for that device only)
        for _ in range(3):
            agent.detect_anomalies({'cpu.cpu_percent': 95.0}, 'ts', 'dev-alpha')

        alpha_key = ('dev-alpha', 'cpu.cpu_percent')
        beta_key  = ('dev-beta',  'cpu.cpu_percent')

        alpha_fired = agent.last_fired.get(alpha_key) is not None
        beta_fired  = agent.last_fired.get(beta_key)  is not None

        if alpha_fired:
            # dev-beta cooldown must not be set just because dev-alpha fired
            self.assertFalse(beta_fired,
                "dev-beta cooldown was set after dev-alpha anomaly — cooldowns are not per-device")

    # ------------------------------------------- event carries device_id

    def test_anomaly_event_carries_remote_device_id(self):
        """
        When a health.metric event arrives tagged with a remote device_id,
        the resulting anomaly.detected event must carry that same device_id.
        """
        agent, bus = self._make_anomaly_agent()

        received = []
        bus.subscribe('anomaly.detected', lambda e: received.append(e))

        # Warm-up: establish a low-CPU baseline for the remote device
        for _ in range(35):
            bus.create_event(
                event_type='health.metric',
                data={
                    'device_id': 'raspberry-pi-01',
                    'timestamp': 'ts',
                    'metrics': {'cpu': {'cpu_percent': 15.0}},
                },
                source='test',
            )

        # Inject a spike on the same remote device (2+ consecutive readings)
        for _ in range(3):
            bus.create_event(
                event_type='health.metric',
                data={
                    'device_id': 'raspberry-pi-01',
                    'timestamp': 'ts',
                    'metrics': {'cpu': {'cpu_percent': 95.0}},
                },
                source='test',
            )

        if received:
            for ev in received:
                self.assertEqual(ev.data.get('device_id'), 'raspberry-pi-01',
                    "anomaly.detected event has wrong device_id")

    # ------------------------------------------- diagnosis passes device_id

    def test_get_recent_metrics_uses_passed_device_id(self):
        """
        _get_recent_metrics(device_id) must query the database with the
        supplied device_id, not always self.device_id.
        """
        agent, _ = self._make_diagnosis_agent()
        mock_db = MagicMock()
        mock_db.get_metrics_history.return_value = []
        agent.database = mock_db

        agent._get_recent_metrics('remote-node-7')

        mock_db.get_metrics_history.assert_called_once()
        call_kwargs = mock_db.get_metrics_history.call_args
        used_device_id = (
            call_kwargs.kwargs.get('device_id')
            if call_kwargs.kwargs
            else call_kwargs.args[0] if call_kwargs.args else None
        )
        self.assertEqual(used_device_id, 'remote-node-7',
            "_get_recent_metrics used self.device_id instead of the passed remote device_id")

    def test_check_trend_uses_passed_device_id(self):
        """
        _check_trend(..., device_id='remote') must query the database with
        the remote device_id, not the hub's self.device_id.
        """
        agent, _ = self._make_diagnosis_agent()
        mock_db = MagicMock()
        mock_db.get_metrics_history.return_value = []
        agent.database = mock_db

        agent._check_trend('cpu.cpu_percent', 'increasing', 'remote-node-7')

        mock_db.get_metrics_history.assert_called_once()
        call_kwargs = mock_db.get_metrics_history.call_args
        used_device_id = (
            call_kwargs.kwargs.get('device_id')
            if call_kwargs.kwargs
            else call_kwargs.args[0] if call_kwargs.args else None
        )
        self.assertEqual(used_device_id, 'remote-node-7',
            "_check_trend used self.device_id instead of the passed remote device_id")

    def test_check_trend_falls_back_to_local_device_id(self):
        """_check_trend with no device_id must fall back to self.device_id."""
        agent, _ = self._make_diagnosis_agent()
        mock_db = MagicMock()
        mock_db.get_metrics_history.return_value = []
        agent.database = mock_db

        agent._check_trend('cpu.cpu_percent', 'increasing')

        mock_db.get_metrics_history.assert_called_once()
        call_kwargs = mock_db.get_metrics_history.call_args
        used_device_id = (
            call_kwargs.kwargs.get('device_id')
            if call_kwargs.kwargs
            else call_kwargs.args[0] if call_kwargs.args else None
        )
        self.assertEqual(used_device_id, agent.device_id,
            "_check_trend must use self.device_id when no device_id is supplied")

    # ------------------------------------------- recovery routes to remote

    def test_recovery_queues_command_for_remote_device(self):
        """
        When recovery fires for a remote device_id, the action must be
        queued via remote_device_manager.queue_command — not executed locally.
        """
        from agents.recovery.recovery_agent import RecoveryAgent
        from core.event_bus import EventBus

        bus = EventBus()
        logger = MagicMock()
        cfg = MagicMock()
        cfg.device_id = 'hub-local'
        cfg.get_section.return_value = {}
        cfg.get.return_value = None

        mock_rdm = MagicMock()
        mock_rdm.is_remote.return_value = True  # device IS remote

        agent = RecoveryAgent(
            name='recovery_agent', config=cfg,
            event_bus=bus, logger=logger, database=None
        )
        agent.remote_device_manager = mock_rdm
        agent.auto_recovery = True

        agent.execute_recovery_actions(
            actions=['compact_memory'],
            diagnosis={'diagnosis': 'high memory', 'recommended_actions': []},
            device_id='remote-pi',
            timestamp='ts',
        )

        mock_rdm.queue_command.assert_called_once()
        call_args = mock_rdm.queue_command.call_args
        queued_device = call_args.args[0] if call_args.args else call_args.kwargs.get('device_id')
        queued_cmd    = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get('command')
        self.assertEqual(queued_device, 'remote-pi',
            "command was not queued to the correct remote device")
        self.assertEqual(queued_cmd.get('action'), 'compact_memory',
            "wrong action queued to remote device")

    def test_recovery_does_not_queue_for_local_device(self):
        """Recovery for the local hub must NOT call queue_command."""
        from agents.recovery.recovery_agent import RecoveryAgent
        from core.event_bus import EventBus

        bus = EventBus()
        logger = MagicMock()
        cfg = MagicMock()
        cfg.device_id = 'hub-local'
        cfg.get_section.return_value = {}
        cfg.get.return_value = None

        mock_rdm = MagicMock()
        mock_rdm.is_remote.return_value = False  # device is LOCAL

        agent = RecoveryAgent(
            name='recovery_agent', config=cfg,
            event_bus=bus, logger=logger, database=None
        )
        agent.remote_device_manager = mock_rdm
        agent.auto_recovery = True

        agent.execute_recovery_actions(
            actions=['compact_memory'],
            diagnosis={'diagnosis': 'high memory', 'recommended_actions': []},
            device_id='hub-local',
            timestamp='ts',
        )

        mock_rdm.queue_command.assert_not_called()


class TestMinConsecutiveReadings(unittest.TestCase):
    """
    The system now requires 4 consecutive anomalous readings before an anomaly
    fires (up from 2).  At a 5-second collection interval that means 20 seconds
    of sustained anomaly is needed — transient spikes are silently dropped.

    These tests call detect_anomalies() directly (bypassing the Groq gate)
    so that consecutive-readings logic can be verified in isolation.
    """

    def _make_agent(self, min_consecutive=4):
        from core.event_bus import EventBus
        from agents.anomaly.anomaly_detection_agent import AnomalyDetectionAgent
        bus = EventBus()
        logger = MagicMock()
        cfg = MagicMock()
        cfg.device_id = 'hub-local'
        cfg.get_section.side_effect = lambda s: (
            {
                'methods': {'z_score': {'threshold': 2.5}},
                'ml': {'enabled': False},
                'baseline': {'window_size': 30, 'update_interval_minutes': 15},
            } if s == 'anomaly_detection' else {}
        )
        cfg.get.side_effect = lambda key, default=None: {
            'anomaly_detection.min_consecutive_readings': min_consecutive,
            'anomaly_detection.cooldown_minutes': 60,
        }.get(key, default)
        return AnomalyDetectionAgent(
            name='anomaly', config=cfg, event_bus=bus,
            logger=logger, database=None,
        )

    def _warmup(self, agent, value=15.0, n=35, device='local'):
        """Push n normal readings to complete baseline warmup."""
        for _ in range(n):
            agent.detect_anomalies({'cpu.cpu_percent': value}, 'ts', device)

    # ── Consecutive-readings gate ─────────────────────────────────────────

    def test_fewer_than_4_consecutive_readings_does_not_fire(self):
        """
        3 consecutive anomalous readings must NOT trigger an anomaly
        when min_consecutive=4.  A single 15-second burst is noise.
        """
        agent = self._make_agent(min_consecutive=4)
        self._warmup(agent)

        results = []
        for _ in range(3):
            results = agent.detect_anomalies({'cpu.cpu_percent': 95.0}, 'ts', 'local')

        self.assertEqual(results, [],
            "Anomaly fired after only 3 readings — min_consecutive=4 not respected")

    def test_exactly_4_consecutive_readings_fires_anomaly(self):
        """The 4th consecutive anomalous reading must trigger the anomaly."""
        agent = self._make_agent(min_consecutive=4)
        self._warmup(agent)

        for _ in range(3):
            agent.detect_anomalies({'cpu.cpu_percent': 95.0}, 'ts', 'local')
        results = agent.detect_anomalies({'cpu.cpu_percent': 95.0}, 'ts', 'local')

        self.assertGreater(len(results), 0,
            "Anomaly did NOT fire after 4 consecutive anomalous readings")

    def test_transient_spike_broken_by_normal_reading_does_not_fire(self):
        """
        3 high readings → 1 normal reading (counter resets) → 3 more high readings
        must still not fire because the streak was interrupted.
        This is the Safari/Chrome transient-spike scenario.
        """
        agent = self._make_agent(min_consecutive=4)
        self._warmup(agent)

        for _ in range(3):
            agent.detect_anomalies({'cpu.cpu_percent': 95.0}, 'ts', 'local')
        # Normal reading resets the counter
        agent.detect_anomalies({'cpu.cpu_percent': 15.0}, 'ts', 'local')
        # Only 3 more high readings — consecutive count is back at 3, below threshold
        results = []
        for _ in range(3):
            results = agent.detect_anomalies({'cpu.cpu_percent': 95.0}, 'ts', 'local')

        self.assertEqual(results, [],
            "Anomaly fired even though consecutive streak was reset by a normal reading")

    def test_5_consecutive_readings_fires_exactly_once(self):
        """
        After the anomaly fires at reading 4, the 5-minute cooldown must
        prevent a second fire at reading 5 within the same window.
        """
        agent = self._make_agent(min_consecutive=4)
        self._warmup(agent)

        fired_count = 0
        for _ in range(5):
            r = agent.detect_anomalies({'cpu.cpu_percent': 95.0}, 'ts', 'local')
            fired_count += len(r)

        self.assertEqual(fired_count, 1,
            f"Expected exactly 1 fire for 5 consecutive anomalous readings, got {fired_count}")

    def test_consecutive_counter_is_per_metric_not_global(self):
        """
        3 CPU anomalous readings must not advance the memory counter.
        Each metric has its own independent consecutive counter.
        """
        agent = self._make_agent(min_consecutive=4)
        self._warmup(agent, value=15.0)
        # Warm up memory baseline too
        for _ in range(35):
            agent.detect_anomalies({'memory.memory_percent': 30.0}, 'ts', 'local')

        for _ in range(3):
            agent.detect_anomalies({'cpu.cpu_percent': 95.0}, 'ts', 'local')
        # Only 1 anomalous memory reading — must not fire (only 1 consecutive)
        mem_results = agent.detect_anomalies({'memory.memory_percent': 95.0}, 'ts', 'local')

        self.assertEqual(mem_results, [],
            "Memory anomaly fired after only 1 consecutive reading — "
            "CPU counter bled into memory counter")

    def test_warmup_period_prevents_early_detection(self):
        """
        No anomaly should fire before the baseline has seen 30+ samples
        (AdaptiveMetricBaseline.WARMUP_SAMPLES).  Even extreme values must
        be silently ignored during warm-up.
        """
        agent = self._make_agent(min_consecutive=4)

        results = []
        for _ in range(25):   # below 30-sample warmup threshold
            results = agent.detect_anomalies({'cpu.cpu_percent': 99.0}, 'ts', 'local')

        self.assertEqual(results, [],
            "Anomaly fired during warmup period (< 30 samples) — baseline not ready yet")


class TestGroqAnomalyGate(unittest.TestCase):
    """
    Tests for the Groq pre-publish validation gate in AnomalyDetectionAgent.

    Before an anomaly enters the pipeline, Groq is asked:
      "Is this a genuine system problem or normal user behavior?"

    Design contract:
      • Fail-OPEN — if Groq is unavailable or errors, the anomaly IS published.
        (Under-alerting during a real incident is worse than a false positive.)
      • Suppression — if Groq says is_genuine=false, the anomaly is silently
        dropped and anomaly.detected is NOT published.
      • No Groq key — gate bypassed, anomaly published directly (identical to
        pre-Groq behavior; no regression).
    """

    def _make_agent(self):
        from core.event_bus import EventBus
        from agents.anomaly.anomaly_detection_agent import AnomalyDetectionAgent
        bus = EventBus()
        logger = MagicMock()
        cfg = MagicMock()
        cfg.device_id = 'hub-local'
        cfg.get_section.side_effect = lambda s: (
            {
                'methods': {'z_score': {'threshold': 2.5}},
                'ml': {'enabled': False},
                'baseline': {'window_size': 30, 'update_interval_minutes': 15},
            } if s == 'anomaly_detection' else {}
        )
        cfg.get.side_effect = lambda key, default=None: {
            'anomaly_detection.min_consecutive_readings': 4,
            'anomaly_detection.cooldown_minutes': 60,
        }.get(key, default)
        agent = AnomalyDetectionAgent(
            name='anomaly', config=cfg, event_bus=bus,
            logger=logger, database=None,
        )
        return agent, bus

    def _mock_groq(self, is_genuine: bool):
        """Build a Groq client mock that responds with the given is_genuine value."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            f'{{"is_genuine": {str(is_genuine).lower()}, "reason": "test reason"}}'
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    def _warmup_via_bus(self, agent, bus, value=15.0, n=35, device='hub-local'):
        for _ in range(n):
            bus.create_event(
                event_type='health.metric',
                data={'device_id': device, 'timestamp': 'ts',
                      'metrics': {'cpu': {'cpu_percent': value}}},
                source='test',
            )

    # ── Unit tests on _groq_validate_anomaly directly ────────────────────

    def test_genuine_anomaly_gate_returns_true(self):
        """Groq responding is_genuine=true → gate allows the anomaly through."""
        agent, _ = self._make_agent()
        agent._groq_client = self._mock_groq(True)
        agent._groq_config = {'model': 'test-model'}

        anomaly = {'metric_name': 'cpu.cpu_percent', 'value': 95.0,
                   'expected_value': 20.0, 'severity': 'high'}
        result = agent._groq_validate_anomaly(anomaly, 'stress-ng', 95.0, 'cpu')

        self.assertTrue(result,
            "Gate blocked a genuine anomaly — real incidents will be silently missed")

    def test_false_positive_browser_gate_returns_false(self):
        """
        Groq responding is_genuine=false → gate suppresses the anomaly.
        This is the core Safari/browser high-memory false-positive scenario.
        """
        agent, _ = self._make_agent()
        agent._groq_client = self._mock_groq(False)
        agent._groq_config = {'model': 'test-model'}

        anomaly = {'metric_name': 'memory.memory_percent', 'value': 85.0,
                   'expected_value': 40.0, 'severity': 'high'}
        result = agent._groq_validate_anomaly(anomaly, 'Safari', 85.0, 'memory')

        self.assertFalse(result,
            "Gate passed a browser false-positive — Safari high-memory would "
            "trigger unnecessary recovery actions")

    def test_groq_exception_fails_open_returns_true(self):
        """
        If Groq raises an exception (network down, quota exceeded),
        the gate must return True (fail-open) so no real anomaly is silently dropped.
        """
        agent, _ = self._make_agent()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Groq API timeout")
        agent._groq_client = mock_client
        agent._groq_config = {'model': 'test-model'}

        anomaly = {'metric_name': 'cpu.cpu_percent', 'value': 90.0,
                   'expected_value': 20.0, 'severity': 'high'}
        result = agent._groq_validate_anomaly(anomaly, None, 0.0, 'cpu')

        self.assertTrue(result,
            "Gate returned False on Groq exception — fail-OPEN violated: "
            "real anomalies can now be silently dropped when Groq is down")

    def test_no_groq_client_gate_returns_true(self):
        """
        When _groq_client is explicitly None (no key or key invalid),
        _groq_validate_anomaly must return True immediately — identical
        to the pre-Groq behavior.  No regression for users without a key.
        """
        agent, _ = self._make_agent()
        agent._groq_client = None  # force no-Groq code path regardless of env

        anomaly = {'metric_name': 'cpu.cpu_percent', 'value': 90.0,
                   'expected_value': 20.0, 'severity': 'high'}
        result = agent._groq_validate_anomaly(anomaly, 'python', 90.0, 'cpu')

        self.assertTrue(result)

    def test_groq_prompt_includes_top_process_name(self):
        """
        The Groq prompt must include the top process name so the AI can
        distinguish 'Safari using 2GB RAM' from 'unknown daemon using 2GB RAM'.
        Without process context, Groq cannot make an informed decision.
        """
        agent, _ = self._make_agent()
        mock_client = self._mock_groq(True)
        agent._groq_client = mock_client
        agent._groq_config = {'model': 'test-model'}

        anomaly = {'metric_name': 'memory.memory_percent', 'value': 88.0,
                   'expected_value': 45.0, 'severity': 'high'}
        agent._groq_validate_anomaly(anomaly, 'com.apple.WebKit.WebContent', 88.0, 'memory')

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs.get('messages', [])
        user_content = next((m['content'] for m in messages if m['role'] == 'user'), '')
        self.assertIn('com.apple.WebKit.WebContent', user_content,
            "Top process name missing from Groq prompt — AI cannot distinguish "
            "normal browser activity from a genuine memory leak")

    def test_groq_prompt_includes_metric_name_and_value(self):
        """The Groq prompt must contain the metric name and observed value."""
        agent, _ = self._make_agent()
        mock_client = self._mock_groq(True)
        agent._groq_client = mock_client
        agent._groq_config = {'model': 'test-model'}

        anomaly = {'metric_name': 'cpu.cpu_percent', 'value': 93.5,
                   'expected_value': 18.2, 'severity': 'critical'}
        agent._groq_validate_anomaly(anomaly, None, 0.0, 'cpu')

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs.get('messages', [])
        user_content = next((m['content'] for m in messages if m['role'] == 'user'), '')
        self.assertIn('cpu.cpu_percent', user_content,
            "Metric name not in Groq prompt")
        self.assertIn('93.5', user_content,
            "Anomaly value not in Groq prompt")

    # ── Integration: gate wired into process_event ────────────────────────

    def test_process_event_publishes_anomaly_when_groq_confirms(self):
        """
        End-to-end: after 4 consecutive high-CPU readings, when Groq
        responds is_genuine=true, anomaly.detected must be published.
        """
        agent, bus = self._make_agent()
        agent._groq_client = self._mock_groq(True)
        agent._groq_config = {'model': 'test-model'}

        received = []
        bus.subscribe('anomaly.detected', lambda e: received.append(e))

        self._warmup_via_bus(agent, bus)

        for _ in range(4):
            bus.create_event(
                event_type='health.metric',
                data={'device_id': 'hub-local', 'timestamp': 'ts',
                      'metrics': {'cpu': {'cpu_percent': 97.0}}},
                source='test',
            )

        time.sleep(0.5)  # let background validation thread complete

        self.assertGreater(len(received), 0,
            "anomaly.detected was not published even though Groq confirmed is_genuine=true")

    def test_process_event_suppresses_anomaly_when_groq_denies(self):
        """
        End-to-end: when Groq responds is_genuine=false, anomaly.detected
        must NOT be published — the false positive is silently swallowed.
        This is the main user requirement: Safari-level activity must not
        trigger recovery actions.
        """
        agent, bus = self._make_agent()
        agent._groq_client = self._mock_groq(False)
        agent._groq_config = {'model': 'test-model'}

        received = []
        bus.subscribe('anomaly.detected', lambda e: received.append(e))

        self._warmup_via_bus(agent, bus)

        for _ in range(4):
            bus.create_event(
                event_type='health.metric',
                data={'device_id': 'hub-local', 'timestamp': 'ts',
                      'metrics': {'cpu': {'cpu_percent': 97.0}}},
                source='test',
            )

        time.sleep(0.5)

        self.assertEqual(len(received), 0,
            "anomaly.detected was published despite Groq returning is_genuine=false — "
            "false positive suppression is broken")

    def test_process_event_publishes_when_groq_errors_fail_open(self):
        """
        End-to-end: if the Groq call raises during validation, the anomaly
        must still be published (fail-open).  Groq downtime must never silence
        real incident alerts.
        """
        agent, bus = self._make_agent()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API unreachable")
        agent._groq_client = mock_client
        agent._groq_config = {'model': 'test-model'}

        received = []
        bus.subscribe('anomaly.detected', lambda e: received.append(e))

        self._warmup_via_bus(agent, bus)

        for _ in range(4):
            bus.create_event(
                event_type='health.metric',
                data={'device_id': 'hub-local', 'timestamp': 'ts',
                      'metrics': {'cpu': {'cpu_percent': 97.0}}},
                source='test',
            )

        time.sleep(0.5)

        self.assertGreater(len(received), 0,
            "anomaly.detected was suppressed when Groq was down — "
            "fail-open violated: real incidents can now be silently missed")


class TestGroqKillGuard(unittest.TestCase):
    """
    Tests for the Groq sanity check that gates kill recovery actions.

    Before terminating any process, the recovery agent asks Groq:
      "Is it safe to kill '[process_name]'?"

    Design contract — opposite of the anomaly gate:
      • Fail-SAFE — if Groq errors or is unavailable, the kill is BLOCKED.
        (Killing a user process is irreversible; err on the side of caution.)
      • No Groq key — kill is ALLOWED but still gated by _CRITICAL_PROCESSES.
      • Approved — Groq says safe_to_kill=true → terminate() is called.
      • Denied — Groq says safe_to_kill=false → blocked, success=True returned.
    """

    def _make_agent(self):
        from agents.recovery.recovery_agent import RecoveryAgent
        from core.event_bus import EventBus
        bus = EventBus()
        logger = MagicMock()
        cfg = MagicMock()
        cfg.device_id = 'hub-local'
        cfg.get_section.side_effect = lambda s: (
            {
                'auto_recovery': True,
                'max_retries': 3,
                'retry_delay_seconds': 5,
                'cooldown_period_seconds': 300,
                'escalation_window_minutes': 30,
                'actions': {},
            } if s == 'recovery' else {}
        )
        cfg.get.return_value = None
        return RecoveryAgent(
            name='recovery', config=cfg, event_bus=bus,
            logger=logger, database=None,
        )

    def _mock_groq(self, safe_to_kill: bool):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            f'{{"safe_to_kill": {str(safe_to_kill).lower()}, "reason": "test reason"}}'
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    def _proc(self, name, cpu_pct=0.0, mem_pct=0.0):
        p = MagicMock()
        p.info = {'pid': 9999, 'name': name,
                  'cpu_percent': cpu_pct, 'memory_percent': mem_pct}
        return p

    # ── Unit tests on _groq_ok_to_kill directly ───────────────────────────

    def test_no_groq_client_allows_kill(self):
        """
        When _groq_client is None (no key or key invalid), _groq_ok_to_kill
        must return True so the static _CRITICAL_PROCESSES list remains the
        only guard — Groq is a second layer, not the only layer.
        """
        agent = self._make_agent()
        agent._groq_client = None  # force no-Groq code path regardless of env
        result = agent._groq_ok_to_kill('some_process', 85.0, 'cpu')
        self.assertTrue(result)

    def test_groq_approves_kill_returns_true(self):
        """Groq returning safe_to_kill=true → guard allows the kill."""
        agent = self._make_agent()
        agent._groq_client = self._mock_groq(True)
        agent._groq_config = {'model': 'test-model'}
        result = agent._groq_ok_to_kill('stress_worker', 95.0, 'cpu')
        self.assertTrue(result)

    def test_groq_denies_kill_returns_false(self):
        """
        Groq returning safe_to_kill=false → guard blocks the kill.
        This is the Safari/Chrome memory scenario: user is browsing,
        high memory is expected, do not terminate.
        """
        agent = self._make_agent()
        agent._groq_client = self._mock_groq(False)
        agent._groq_config = {'model': 'test-model'}
        result = agent._groq_ok_to_kill('Safari', 72.0, 'memory')
        self.assertFalse(result,
            "Kill guard returned True for Safari — browser should be protected by Groq")

    def test_groq_exception_fails_safe_returns_false(self):
        """
        If Groq raises an exception, _groq_ok_to_kill must return False.
        Fail-SAFE: we never kill when uncertain — a living process is
        always recoverable; a dead user process is not.
        """
        agent = self._make_agent()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Groq timeout")
        agent._groq_client = mock_client
        agent._groq_config = {'model': 'test-model'}
        result = agent._groq_ok_to_kill('unknown_process', 80.0, 'memory')
        self.assertFalse(result,
            "_groq_ok_to_kill returned True on Groq exception — must fail-safe "
            "(fail-safe = block the kill when uncertain)")

    def test_groq_prompt_includes_process_name_and_usage(self):
        """
        The kill guard prompt must include the process name and usage percentage
        so Groq can distinguish 'Safari 72% MEM' from 'stress-ng 72% MEM'.
        """
        agent = self._make_agent()
        mock_client = self._mock_groq(True)
        agent._groq_client = mock_client
        agent._groq_config = {'model': 'test-model'}

        agent._groq_ok_to_kill('com.apple.WebKit.WebContent', 1400.0, 'memory')

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs.get('messages', [])
        user_content = next((m['content'] for m in messages if m['role'] == 'user'), '')
        self.assertIn('com.apple.WebKit.WebContent', user_content,
            "Process name missing from kill guard Groq prompt")
        self.assertIn('1400.0', user_content,
            "Memory usage missing from kill guard Groq prompt")

    # ── Integration: kill actions obey the guard ──────────────────────────

    def test_kill_top_cpu_blocked_when_groq_denies(self):
        """
        _action_kill_top_cpu_process must return a 'blocked' success result
        when Groq denies the kill — proc.terminate() must never be called.
        """
        agent = self._make_agent()
        agent._groq_client = self._mock_groq(False)
        agent._groq_config = {'model': 'test-model'}

        with patch('agents.recovery.recovery_agent.psutil.process_iter',
                   return_value=[self._proc('my_app', cpu_pct=85.0)]):
            result = agent._action_kill_top_cpu_process({})

        self.assertTrue(result['success'],
            "Blocked kill should still return success=True (not an error)")
        self.assertIn('blocked', result['message'].lower(),
            "Result message must indicate the kill was blocked by the AI guard")

    def test_kill_top_memory_blocked_when_groq_denies(self):
        """
        _action_kill_top_memory_process must be blocked when Groq says no.
        Key scenario: Safari / WebKit process using high memory while user
        is actively browsing.
        """
        agent = self._make_agent()
        agent._groq_client = self._mock_groq(False)
        agent._groq_config = {'model': 'test-model'}

        with patch('agents.recovery.recovery_agent.psutil.process_iter',
                   return_value=[self._proc('my_app', mem_pct=75.0)]):
            result = agent._action_kill_top_memory_process({})

        self.assertTrue(result['success'])
        self.assertIn('blocked', result['message'].lower())

    def test_kill_top_cpu_proceeds_when_groq_approves(self):
        """
        When Groq says safe_to_kill=true, _action_kill_top_cpu_process
        must call proc.terminate() — the runaway process is actually killed.
        """
        agent = self._make_agent()
        agent._groq_client = self._mock_groq(True)
        agent._groq_config = {'model': 'test-model'}

        mock_ps = MagicMock()

        with patch('agents.recovery.recovery_agent.psutil.process_iter',
                   return_value=[self._proc('runaway_worker', cpu_pct=90.0)]), \
             patch('agents.recovery.recovery_agent.psutil.Process', return_value=mock_ps):
            result = agent._action_kill_top_cpu_process({})

        self.assertTrue(result['success'])
        self.assertIn('runaway_worker', result['message'])
        mock_ps.terminate.assert_called_once()

    def test_kill_top_memory_proceeds_when_groq_approves(self):
        """
        When Groq approves, _action_kill_top_memory_process must call
        proc.terminate() and return a success message with the process name.
        """
        agent = self._make_agent()
        agent._groq_client = self._mock_groq(True)
        agent._groq_config = {'model': 'test-model'}

        mock_ps = MagicMock()

        with patch('agents.recovery.recovery_agent.psutil.process_iter',
                   return_value=[self._proc('data_pipeline', mem_pct=60.0)]), \
             patch('agents.recovery.recovery_agent.psutil.Process', return_value=mock_ps):
            result = agent._action_kill_top_memory_process({})

        self.assertTrue(result['success'])
        self.assertIn('data_pipeline', result['message'])
        mock_ps.terminate.assert_called_once()

    def test_critical_processes_list_filters_before_groq_is_consulted(self):
        """
        A process in _CRITICAL_PROCESSES ('python') must be filtered out
        by the static list before Groq is ever contacted.
        Groq.chat.completions.create must not be called.
        """
        agent = self._make_agent()
        mock_client = self._mock_groq(True)
        agent._groq_client = mock_client
        agent._groq_config = {'model': 'test-model'}

        # 'python' is in _CRITICAL_PROCESSES — must be excluded at the static-list level
        with patch('agents.recovery.recovery_agent.psutil.process_iter',
                   return_value=[self._proc('python', cpu_pct=99.0)]):
            result = agent._action_kill_top_cpu_process({})

        mock_client.chat.completions.create.assert_not_called()
        self.assertIn('No runaway', result['message'],
            "Expected 'No runaway CPU process found' when only protected processes exist")

    def test_groq_kill_guard_is_fail_safe_not_fail_open(self):
        """
        CRITICAL: kill guard failure mode must be fail-SAFE, not fail-open.
        The anomaly gate is fail-open (anomaly published when Groq down).
        The kill guard is the opposite — when Groq down, kill is BLOCKED.
        Killing a user process is irreversible; anomalies can be re-detected.
        """
        agent = self._make_agent()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("network error")
        agent._groq_client = mock_client
        agent._groq_config = {'model': 'test-model'}

        with patch('agents.recovery.recovery_agent.psutil.process_iter',
                   return_value=[self._proc('unknown_service', cpu_pct=85.0)]):
            result = agent._action_kill_top_cpu_process({})

        self.assertTrue(result['success'])
        self.assertIn('blocked', result['message'].lower(),
            "Kill was not blocked when Groq was down — "
            "fail-SAFE violated (should block kill when uncertain)")

    def test_anomaly_gate_fail_open_vs_kill_guard_fail_safe_are_asymmetric(self):
        """
        Contract test: the two Groq components have OPPOSITE failure modes.

        Anomaly gate → fail-OPEN  (return True when Groq errors)
        Kill guard   → fail-SAFE  (return False when Groq errors)

        This asymmetry is intentional: missing an anomaly alert is recoverable
        (anomaly will fire again next cycle); killing the wrong process is not.
        """
        from agents.anomaly.anomaly_detection_agent import AnomalyDetectionAgent
        from agents.recovery.recovery_agent import RecoveryAgent
        from core.event_bus import EventBus

        failing_groq = MagicMock()
        failing_groq.chat.completions.create.side_effect = Exception("down")

        # Build anomaly agent with failing Groq
        bus = EventBus()
        a_cfg = MagicMock()
        a_cfg.device_id = 'hub'
        a_cfg.get_section.side_effect = lambda s: (
            {'methods': {}, 'ml': {'enabled': False}, 'baseline': {'window_size': 30}}
            if s == 'anomaly_detection' else {}
        )
        a_cfg.get.side_effect = lambda k, d=None: {
            'anomaly_detection.min_consecutive_readings': 4,
            'anomaly_detection.cooldown_minutes': 60,
        }.get(k, d)
        anomaly_agent = AnomalyDetectionAgent('a', a_cfg, bus, MagicMock(), None)
        anomaly_agent._groq_client = failing_groq
        anomaly_agent._groq_config = {}

        anomaly = {'metric_name': 'cpu.cpu_percent', 'value': 90.0,
                   'expected_value': 20.0, 'severity': 'high'}
        gate_result = anomaly_agent._groq_validate_anomaly(anomaly, None, 0.0, 'cpu')

        # Build recovery agent with same failing Groq
        r_cfg = MagicMock()
        r_cfg.device_id = 'hub'
        r_cfg.get_section.side_effect = lambda s: (
            {'auto_recovery': True, 'max_retries': 1, 'retry_delay_seconds': 1,
             'cooldown_period_seconds': 60, 'escalation_window_minutes': 30, 'actions': {}}
            if s == 'recovery' else {}
        )
        r_cfg.get.return_value = None
        recovery_agent = RecoveryAgent('r', r_cfg, bus, MagicMock(), None)
        recovery_agent._groq_client = failing_groq
        recovery_agent._groq_config = {}

        guard_result = recovery_agent._groq_ok_to_kill('some_process', 80.0, 'cpu')

        self.assertTrue(gate_result,
            "Anomaly gate must be fail-OPEN (True) when Groq is down")
        self.assertFalse(guard_result,
            "Kill guard must be fail-SAFE (False) when Groq is down")
        self.assertNotEqual(gate_result, guard_result,
            "Gate and guard must have opposite failure modes")


if __name__ == '__main__':
    unittest.main(verbosity=2)
