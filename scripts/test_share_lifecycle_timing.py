"""Pure causal lifecycle controls; no native commands or simulator."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent / 'release_smoke'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LifecycleTimingTests(unittest.TestCase):
    def setUp(self):
        self.m = load('timing_lifecycle', HERE / 'lifecycle.py')
        self.r = load('timing_runner', HERE / 'run.py')

    def stop(self, *, enabled=False, delay=0, kill_only=False):
        clock = [100.0]
        events = []
        state = {'gone': False}
        record = {'bootstatus_timing': {'schema': 1}} if enabled else {}
        def tick():
            events.append('clock')
            return clock[0]
        def poll():
            events.append('poll')
            clock[0] += delay
            return 0 if state['gone'] else None
        def killpg(pid, sig):
            events.append(('signal', sig))
            if state['gone']:
                raise ProcessLookupError()
            if sig == signal.SIGKILL or sig == signal.SIGTERM and not kill_only:
                state['gone'] = True
        def sleep(seconds):
            events.append('sleep')
            clock[0] += seconds
        proc = SimpleNamespace(pid=123, poll=poll)
        error = None
        with mock.patch.object(self.m.time, 'monotonic', tick), \
             mock.patch.object(self.m.time, 'sleep', sleep), \
             mock.patch.object(self.m.os, 'killpg', killpg):
            try:
                self.m.stop_group(proc, record)
            except RuntimeError as caught:
                error = caught
        return record, events, error

    def test_default_stamp_does_not_read_clock(self):
        with mock.patch.object(self.m.time, 'monotonic', side_effect=AssertionError('clock')):
            self.m.diagnostic_stamp(None, 'unused')

    def test_default_cleanup_has_exact_original_probe_and_clock_order(self):
        record, events, error = self.stop()
        self.assertIsNone(error)
        self.assertEqual(events, ['clock', 'poll', ('signal', 0), 'clock',
                                  ('signal', signal.SIGTERM), 'poll', ('signal', 0)])
        self.assertTrue(record['owned_group_absent'])
        self.assertNotIn('bootstatus_timing', record)

    def test_expired_first_probe_reports_delay_without_signaling(self):
        record, events, error = self.stop(enabled=True, delay=4)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual([e for e in events if isinstance(e, tuple)], [('signal', 0)])
        timing = record['bootstatus_timing']['cleanup']
        self.assertEqual(timing['deadline'], 103)
        self.assertEqual(timing['first_probe'], {'poll_before': 100, 'poll_after': 104,
                                               'group_before': 104, 'group_after': 104})
        self.assertEqual(timing['signal_decisions'], [{'signal': int(signal.SIGTERM),
                            'checked_at': 104, 'reserve_exhausted': True}])
        self.assertFalse(record['owned_group_absent'])

    def test_many_probes_keep_only_first_last_and_two_decisions(self):
        record, _, error = self.stop(enabled=True, kill_only=True)
        self.assertIsNone(error)
        self.assertGreater(record['cleanup_observation']['probe_count'], 50)
        timing = record['bootstatus_timing']['cleanup']
        self.assertEqual(set(timing), {'started', 'deadline', 'first_probe', 'last_probe', 'signal_decisions'})
        self.assertEqual(len(timing['signal_decisions']), 2)
        self.assertLess(len(json.dumps(timing)), 1200)
        self.assertNotEqual(timing['first_probe'], timing['last_probe'])

    def command(self, enabled, args, *, clock_fault=False):
        error = subprocess.TimeoutExpired(args, 120)
        events = []
        def clock():
            caller = sys._getframe(1).f_code.co_name
            if clock_fault and caller == 'diagnostic_stamp':
                raise RuntimeError('sensitive clock exception text')
            events.append('clock')
            return 100.0
        def absent(*_):
            events.append('group_probe')
            raise ProcessLookupError()
        def wait(timeout):
            events.append(('wait', timeout))
            raise error
        def poll():
            events.append('poll')
            return 0
        proc = SimpleNamespace(pid=123, returncode=None, poll=poll, wait=wait)
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch.object(self.m.time, 'monotonic', clock), \
             mock.patch.object(self.m.subprocess, 'Popen', return_value=proc), \
             mock.patch.object(self.m.os, 'killpg', absent):
            run = self.m.Run()
            run.meta['diagnostic_lifecycle_timing'] = enabled
            run.persist = lambda: None
            self.m.OUT = Path(temporary)
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                run.command(args, 'fixture.log', 120)
            self.assertIs(caught.exception, error)
        return run.meta['commands'][0], events

    def test_default_command_no_extra_clock_or_process_operations(self):
        args = ['xcrun', 'simctl', 'bootstatus', 'fixture', '-b']
        record, events = self.command(False, args)
        self.assertNotIn('bootstatus_timing', record)
        self.assertEqual(events, ['clock', 'clock', 'clock', 'clock', ('wait', 120.0),
                                  'clock', 'poll', 'group_probe'])
        self.assertEqual(record['timeout_seconds'], 120)

    def test_enabled_command_records_fixed_numeric_boundaries(self):
        record, _ = self.command(True, ['xcrun', 'simctl', 'bootstatus', 'fixture', '-b'])
        t = record['bootstatus_timing']
        self.assertEqual(set(t), {'schema', 'python_version', 'prepared', 'spawn_before',
                                 'spawn_after', 'wait_before', 'wait_after', 'cleanup'})
        self.assertEqual(t['python_version'], list(sys.version_info[:3]))
        self.assertEqual(record['command_error_operation'], 'wait')
        self.assertTrue(record['owned_group_absent'])
        self.assertEqual(record['timeout_seconds'], 120)

    def test_timing_clock_fault_cannot_replace_timeout_or_skip_cleanup(self):
        record, events = self.command(True, ['xcrun', 'simctl', 'bootstatus', 'fixture', '-b'], clock_fault=True)
        self.assertTrue(record['bootstatus_timing']['clock_failed'])
        self.assertTrue(record['bootstatus_timing']['cleanup']['first_probe']['clock_failed'])
        self.assertIn('group_probe', events)
        self.assertTrue(record['owned_group_absent'])
        self.assertEqual(record['command_error_operation'], 'wait')
        self.assertNotIn('sensitive', json.dumps(record))

    def test_other_commands_do_not_enable_new_observation(self):
        for args in (['xcrun', 'simctl', 'boot', 'fixture'], ['echo', 'bootstatus'],
                     ['xcrun', 'simctl', 'bootstatus', 'fixture'],
                     ['xcrun', 'simctl', 'bootstatus', 'fixture', '-b', 'extra']):
            with self.subTest(args=args):
                record, events = self.command(True, args)
                self.assertNotIn('bootstatus_timing', record)
                self.assertEqual(events.count('clock'), 5)

    def test_worker_summary_preserves_own_exit_error_status_and_deep_copies_frames(self):
        original = {'status': 'failed', 'error': 'AssertionError()', 'returncode': 1}
        intent = dict(original)
        detail = {'type': 'TimeoutExpired', 'frames': [
            {'file': 'subprocess.py', 'function': '_wait_kqueue', 'line': 2286}]}
        self.r.retain_worker_failure(intent, {'primary_error': detail})
        self.assertEqual({k: intent[k] for k in original}, original)
        self.assertEqual(intent['worker_primary_error'], detail)
        detail['frames'][0]['line'] = 1
        self.assertEqual(intent['worker_primary_error']['frames'][0]['line'], 2286)

    def test_malformed_worker_error_is_bounded_and_cannot_affect_verdict(self):
        for detail in (None, {}, 'x', {'type': 'x'*129, 'frames': []},
                       {'type': 'Error', 'frames': [{'file': '/private/path', 'function': 'f', 'line': 1}]},
                       {'type': 'Error', 'frames': [{}]*5}):
            intent = {'status': 'failed', 'error': 'original'}
            self.r.retain_worker_failure(intent, {'primary_error': detail})
            self.assertNotIn('worker_primary_error', intent)
            self.assertEqual(intent['status'], 'failed')
            self.assertEqual(intent['error'], 'original')

    def test_enabling_and_summary_calls_are_diagnostic_grant_only(self):
        tree = ast.parse((HERE / 'run.py').read_text())
        enable = [n for n in ast.walk(tree) if isinstance(n, ast.If)
                  and any(isinstance(c, ast.keyword) and c.arg == 'diagnostic_lifecycle_timing'
                          for c in ast.walk(n))]
        self.assertEqual(len(enable), 1)
        self.assertEqual(ast.unparse(enable[0].test), 'phase_trace')
        summary = [n for n in ast.walk(tree) if isinstance(n, ast.If)
                   and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                           and c.func.id == 'retain_worker_failure' for c in ast.walk(n))]
        self.assertEqual(len(summary), 1)
        self.assertEqual(ast.unparse(summary[0].test), "grant.get('mode') == 'share-phase-trace-v1'")

    def test_one_shot_preflight_runs_all_controls_before_native_build(self):
        root = HERE.parents[1]
        workflow = json.loads((root / '.github/workflows/share-phase-diagnostic.yml').read_text())
        self.assertEqual(workflow['on'], {'push': {'branches': ['diagnostics/sanitizer14-share-phase-timing']}})
        job = workflow['jobs']['diagnostic']
        self.assertEqual(job['timeout-minutes'], 30)
        self.assertEqual(job['if'], 'github.event.created && !github.event.deleted && github.run_attempt == 1')
        preflight = job['steps'][1]
        self.assertEqual(preflight['timeout-minutes'], 2)
        self.assertNotIn('if', preflight)
        self.assertNotIn('continue-on-error', preflight)
        self.assertEqual(preflight['run'], 'python3 -B -m unittest scripts/test_release_smoke.py '
                         'scripts/test_share_phase_diagnostic.py scripts/test_share_lifecycle_timing.py '
                         'scripts/test_share_phase_trace.py')
        self.assertEqual(job['steps'][2]['id'], 'prepare')
        self.assertEqual(job['steps'][2]['run'], 'python3 -B scripts/release_smoke/diagnostic.py')


if __name__ == '__main__':
    unittest.main()
