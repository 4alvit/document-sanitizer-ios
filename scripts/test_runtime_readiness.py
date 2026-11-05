"""Inert runtime-diagnostic tests: no Xcode, CoreSimulator, sample or device calls."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest import TestCase, main, mock, skipUnless


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('runtime_readiness', HERE / 'release_smoke/readiness.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class RuntimeWaitTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.clock = [100.0]
        self.item = {'runtime_observation': {}}
        self.proc = SimpleNamespace(pid=123, args=['inert-simctl'], returncode=None)
        self.waits = []
        self.commands = []
        self.patch = mock.patch.object(m.time, 'monotonic', side_effect=lambda: self.clock[0])
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def wait(self, timeout):
        self.waits.append(timeout)
        self.clock[0] += timeout
        raise subprocess.TimeoutExpired(self.proc.args, timeout)

    def command(self, args, name, deadline, out, env, cwd, rows, **kwargs):
        self.commands.append((args, deadline))
        self.clock[0] += 2
        rows.append({'status': 'RETURNED'})

    def invoke(self, exited=False):
        self.proc.wait = self.wait
        with mock.patch.object(m, 'supported', return_value=True), \
                mock.patch.object(m, 'observe_owned', return_value=exited), \
                mock.patch.object(m, 'command', side_effect=self.command):
            return m.wait_runtime(self.proc, 160, self.item, self.out, {}, self.out)

    def test_sample_consumes_original_deadline_without_second_simctl(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.invoke()
        self.assertEqual(self.waits, [45, 13])
        self.assertEqual(self.clock[0], 160)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.commands[0][0], ['/usr/bin/sample', '123', '1', '10', '-mayDie',
                                             '-file', str(self.out / 'runtime-sample.txt')])
        self.assertEqual(self.commands[0][1], 150)

    def test_exited_unreaped_child_is_not_sampled(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.invoke(exited=True)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.waits, [45, 15])

    def test_fast_return_never_observes_or_samples(self):
        self.proc.wait = mock.Mock(return_value=0)
        with mock.patch.object(m, 'supported', return_value=True), \
                mock.patch.object(m, 'observe_owned') as observe, \
                mock.patch.object(m, 'command') as command:
            self.assertEqual(m.wait_runtime(self.proc, 160, self.item, self.out, {}, self.out), 0)
        observe.assert_not_called()
        command.assert_not_called()

    def test_lost_reservation_stops_before_attach_and_marks_no_signal(self):
        self.proc.wait = self.wait
        with mock.patch.object(m, 'supported', return_value=True), \
                mock.patch.object(m, 'observe_owned', side_effect=m.OwnershipLost('gone')), \
                mock.patch.object(m, 'command') as command:
            with self.assertRaises(m.OwnershipLost):
                m.wait_runtime(self.proc, 160, self.item, self.out, {}, self.out)
        command.assert_not_called()
        self.assertTrue(self.item['runtime_observation']['ownership_lost'])

    def test_unsupported_platform_retains_original_wait_without_attach(self):
        self.proc.wait = self.wait
        with mock.patch.object(m, 'supported', return_value=False), mock.patch.object(m, 'command') as command:
            with self.assertRaises(subprocess.TimeoutExpired):
                m.wait_runtime(self.proc, 160, self.item, self.out, {}, self.out)
        self.assertEqual(self.waits, [60])
        command.assert_not_called()

    def test_existing_sample_path_is_never_followed_or_overwritten(self):
        (self.out / 'runtime-sample.txt').symlink_to(self.out / 'unrelated')
        with self.assertRaises(m.CleanupUnknown):
            self.invoke()
        self.assertEqual(self.commands, [])

    def test_diagnostic_overrun_never_renews_main_wait(self):
        def overrun(*args, **kwargs):
            self.clock[0] = 161
            args[-1].append({'status': 'TIMEOUT'})
        self.command = overrun
        with self.assertRaises(subprocess.TimeoutExpired):
            self.invoke()
        self.assertEqual(self.waits, [45])


class ChildOwnershipTests(TestCase):
    def load_smoke(self, name):
        spec = importlib.util.spec_from_file_location('diagnostic_' + name, HERE / ('release_smoke/' + name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_persistence_cancellation_is_not_masked_by_cleanup_failure(self):
        for interruption in (KeyboardInterrupt, SystemExit, InterruptedError):
            with self.subTest(interruption=interruption), tempfile.TemporaryDirectory() as directory:
                run = SimpleNamespace(meta={'commands': []},
                                      persist=mock.Mock(side_effect=[None, interruption('cancel')]))
                proc = SimpleNamespace(pid=123, returncode=None)
                with mock.patch.object(m, 'supported', return_value=True), \
                        mock.patch.object(m.subprocess, 'Popen', return_value=proc), \
                        mock.patch.object(m, 'observe_owned', return_value=True), \
                        mock.patch.object(m, 'stop_observer', side_effect=m.CleanupUnknown('fixture')):
                    with self.assertRaisesRegex(interruption, 'cancel'):
                        m.command(['inert'], 'out.txt', time.monotonic() + 4,
                                  Path(directory), {}, Path(directory), [], run=run)
                self.assertTrue(run.meta['diagnostic_cleanup_unconfirmed'])

    def test_persistence_failure_preserves_original_cleanup_error(self):
        with tempfile.TemporaryDirectory() as directory:
            run = SimpleNamespace(meta={'commands': []},
                                  persist=mock.Mock(side_effect=[None, OSError('disk full')]))
            proc = SimpleNamespace(pid=123, returncode=None)
            with mock.patch.object(m, 'supported', return_value=True), \
                    mock.patch.object(m.subprocess, 'Popen', return_value=proc), \
                    mock.patch.object(m, 'observe_owned', return_value=True), \
                    mock.patch.object(m, 'stop_observer', side_effect=m.CleanupUnknown('fixture')):
                with self.assertRaises(m.CleanupUnknown):
                    m.command(['inert'], 'out.txt', time.monotonic() + 4,
                              Path(directory), {}, Path(directory), [], run=run)
            self.assertEqual(run.meta['diagnostic_persist_error'], 'OSError')

    def test_interruption_before_pid_registration_preserves_cleanup_obligation(self):
        class InterruptedPid:
            returncode = None
            reads = 0
            @property
            def pid(self):
                self.reads += 1
                if self.reads == 1:
                    raise InterruptedError('first pid read')
                return 123
        lifecycle = self.load_smoke('lifecycle')
        driver = self.load_smoke('run')
        with tempfile.TemporaryDirectory() as directory:
            lifecycle.OUT = Path(directory)
            run = lifecycle.Run()
            with mock.patch.object(m, 'supported', return_value=True), \
                    mock.patch.object(m.subprocess, 'Popen', return_value=InterruptedPid()), \
                    mock.patch.object(m, 'stop_observer', side_effect=m.CleanupUnknown('fixture')):
                with self.assertRaises(m.CleanupUnknown):
                    m.command(['inert'], 'out.txt', time.monotonic() + 4,
                              Path(directory), {}, Path(directory), [], run=run)
            self.assertTrue(run.meta['diagnostic_cleanup_unconfirmed'])
            self.assertFalse(run.meta['commands'][0]['owned_group_absent'])
            self.assertEqual(run.meta['commands'][0]['owned_process_group'], 123)
            self.assertFalse(driver.aggregate_command_groups(run.meta, run.start)['all_absent'])
            with mock.patch.object(lifecycle.subprocess, 'Popen') as spawn:
                with self.assertRaises(AssertionError):
                    run.command(['never'], 'never.txt')
            spawn.assert_not_called()

    def test_preflight_unknown_cleanup_blocks_next_native_and_terminal_pass(self):
        lifecycle = self.load_smoke('lifecycle')
        driver = self.load_smoke('run')
        with tempfile.TemporaryDirectory() as directory:
            lifecycle.OUT = Path(directory)
            lifecycle.RUNTIME_DIAGNOSTICS = m
            run = lifecycle.Run()
            diagnostic = SimpleNamespace(pid=123, returncode=None)
            with mock.patch.object(m, 'supported', return_value=True), \
                    mock.patch.object(m.subprocess, 'Popen', return_value=diagnostic) as spawn, \
                    mock.patch.object(m, 'observe_owned', return_value=True), \
                    mock.patch.object(m, 'stop_observer', side_effect=m.CleanupUnknown('fixture')):
                with self.assertRaises(m.CleanupUnknown):
                    run.command(['xcrun', 'simctl', 'list', 'runtimes', '--json'], 'runtimes.json', 60)
                with self.assertRaises(AssertionError):
                    run.command(['xcrun', 'simctl', 'create'], 'never.txt')
            self.assertEqual(spawn.call_count, 1)
            self.assertTrue(run.meta['diagnostic_cleanup_unconfirmed'])
            self.assertIn('"diagnostic_cleanup_unconfirmed": true', (Path(directory) / 'metadata.json').read_text())
            with mock.patch.object(driver.os, 'killpg', side_effect=ProcessLookupError) as probe:
                proof = driver.aggregate_command_groups(run.meta, run.start, probe=probe)
            self.assertFalse(proof['all_absent'])
            self.assertEqual(proof['unresolved_group_ids'], [123])
            probe.assert_not_called()
            with mock.patch.object(lifecycle.os, 'killpg') as signal_child:
                self.assertEqual(lifecycle.stop_recorded_children(999, run.meta, time.monotonic() + 1), [])
            signal_child.assert_not_called()

    def test_sample_unknown_cleanup_survives_successful_main_cleanup(self):
        lifecycle = self.load_smoke('lifecycle')
        driver = self.load_smoke('run')
        with tempfile.TemporaryDirectory() as directory:
            lifecycle.OUT = Path(directory)
            lifecycle.RUNTIME_DIAGNOSTICS = m
            run = lifecycle.Run()
            main = SimpleNamespace(pid=111, args=['inert-simctl'], returncode=None,
                                   wait=mock.Mock(side_effect=subprocess.TimeoutExpired('inert', 45)))
            diagnostic = SimpleNamespace(pid=222, returncode=None)
            def clean_main(proc, row):
                self.assertIs(proc, main)
                proc.returncode = -15
                row['owned_group_absent'] = True
            with mock.patch.object(m, 'preflight'), \
                    mock.patch.object(m, 'supported', return_value=True), \
                    mock.patch.object(m, 'observe_owned', side_effect=lambda p: p is diagnostic), \
                    mock.patch.object(m.subprocess, 'Popen', side_effect=[main, diagnostic]) as spawn, \
                    mock.patch.object(m, 'stop_observer', side_effect=m.CleanupUnknown('fixture')), \
                    mock.patch.object(lifecycle, 'stop_group', side_effect=clean_main) as stop:
                with self.assertRaises(m.CleanupUnknown):
                    run.command(['xcrun', 'simctl', 'list', 'runtimes', '--json'], 'runtimes.json', 60)
                with self.assertRaises(AssertionError):
                    run.command(['xcrun', 'simctl', 'create'], 'never.txt')
            self.assertEqual(spawn.call_count, 2)
            stop.assert_called_once()
            self.assertTrue(run.meta['commands'][0]['owned_group_absent'])
            self.assertTrue(run.meta['diagnostic_cleanup_unconfirmed'])
            proof = driver.aggregate_command_groups(run.meta, run.start, probe=mock.Mock())
            self.assertFalse(proof['all_absent'])
            self.assertEqual(proof['unresolved_group_ids'], [222])

    def test_original_lifecycle_never_signals_after_reservation_loss(self):
        lifecycle_spec = importlib.util.spec_from_file_location('readiness_lifecycle', HERE / 'release_smoke/lifecycle.py')
        lifecycle = importlib.util.module_from_spec(lifecycle_spec)
        lifecycle_spec.loader.exec_module(lifecycle)
        with tempfile.TemporaryDirectory() as directory:
            lifecycle.OUT = Path(directory)
            lifecycle.RUNTIME_DIAGNOSTICS = SimpleNamespace(preflight=lambda *a: None)
            def lost(proc, deadline, item, *args, **kwargs):
                item['runtime_observation']['ownership_lost'] = True
                raise m.OwnershipLost('gone')
            lifecycle.RUNTIME_DIAGNOSTICS.wait_runtime = lost
            run = lifecycle.Run()
            proc = SimpleNamespace(pid=123, returncode=None)
            with mock.patch.object(lifecycle.subprocess, 'Popen', return_value=proc), \
                    mock.patch.object(lifecycle, 'stop_group') as stop:
                with self.assertRaises(m.OwnershipLost):
                    run.command(['xcrun', 'simctl', 'list', 'runtimes', '--json'], 'runtime.json', 60)
            stop.assert_not_called()
            self.assertFalse(run.meta['commands'][0]['owned_group_absent'])

    def test_cancellation_survives_observer_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = SimpleNamespace(pid=123, returncode=None)
            with mock.patch.object(m, 'supported', return_value=True), \
                    mock.patch.object(m.subprocess, 'Popen', return_value=proc), \
                    mock.patch.object(m, 'observe_owned', side_effect=InterruptedError('cancel')), \
                    mock.patch.object(m, 'stop_observer') as stop:
                with self.assertRaises(InterruptedError):
                    m.command(['inert'], 'out.txt', time.monotonic() + 4,
                              Path(directory), {}, Path(directory), [])
            stop.assert_called_once()

    def test_waitid_is_nonreaping_and_mismatch_rejected(self):
        proc = SimpleNamespace(pid=123, returncode=None)
        with mock.patch.object(m.os, 'waitid', return_value=None) as waitid:
            self.assertFalse(m.observe_owned(proc))
            self.assertTrue(waitid.call_args.args[2] & os.WNOWAIT)
        with mock.patch.object(m.os, 'waitid', return_value=SimpleNamespace(si_pid=321)):
            with self.assertRaises(m.OwnershipLost):
                m.observe_owned(proc)

    def test_all_nonzero_group_signals_precede_final_reap(self):
        events = []
        proc = SimpleNamespace(pid=123, returncode=None)
        def wait(timeout):
            events.append('reap')
            proc.returncode = 0
        proc.wait = wait
        def kill(pid, sig):
            events.append(sig)
            if sig == 0:
                raise ProcessLookupError()
        with mock.patch.object(m, 'observe_owned', return_value=True), \
                mock.patch.object(m.os, 'killpg', side_effect=kill), \
                mock.patch.object(m, 'group_members', side_effect=[[{'state': 'S'}], [{'state': 'S'}], [{'state': 'S'}], [], []]), \
                mock.patch.object(m.time, 'sleep'):
            row = {}
            m.stop_observer(proc, time.monotonic() + 1, row)
        self.assertEqual(events, [signal.SIGTERM, 'reap'])
        self.assertTrue(row['cleanup_confirmed'])

    def test_lost_reservation_never_signals(self):
        proc = SimpleNamespace(pid=123, returncode=None, wait=mock.Mock())
        with mock.patch.object(m, 'observe_owned', side_effect=m.OwnershipLost('gone')), \
                mock.patch.object(m.os, 'killpg') as kill:
            with self.assertRaises(m.OwnershipLost):
                m.stop_observer(proc, time.monotonic() + 1, {})
        kill.assert_not_called()
        proc.wait.assert_not_called()

    def test_reaped_child_cannot_be_attached_by_reused_pid(self):
        with self.assertRaises(m.OwnershipLost), mock.patch.object(m.os, 'waitid') as waitid:
            m.observe_owned(SimpleNamespace(pid=123, returncode=0))
        waitid.assert_not_called()

    def test_preflight_only_reads_status_and_path_with_one_budget(self):
        clock = [100.0]
        calls = []
        def command(args, name, deadline, *rest, **kwargs):
            calls.append((args, deadline))
            clock[0] += 4
        run = SimpleNamespace(meta={}, start=0, end=680, persist=mock.Mock())
        with mock.patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]), \
                mock.patch.object(m, 'command', side_effect=command):
            m.preflight(run, Path('/unused'), {}, Path('/unused'))
        self.assertEqual(calls, [(['/usr/bin/xcodebuild', '-checkFirstLaunchStatus'], 104),
                                 (['/usr/bin/xcrun', '--find', 'simctl'], 108)])
        self.assertEqual(run.meta['runtime_readiness_diagnostics']['deadline_monotonic'], 108)
        self.assertEqual((run.start, run.end), (0, 680))


@skipUnless(os.name == 'posix' and m.supported(), 'POSIX WNOWAIT required')
class InertChildTests(TestCase):
    def test_output_cap_and_owned_descendant_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            rows = []
            m.command([sys.executable, '-c', 'import os; os.write(1, b"x" * (2*1024*1024))'],
                      'bounded.txt', time.monotonic() + 4, out, dict(os.environ), out, rows)
            self.assertLessEqual((out / 'bounded.txt').stat().st_size, m.OUTPUT_LIMIT)
            self.assertTrue(rows[0]['cleanup_confirmed'])
            child = 'import signal,time; signal.alarm(5); time.sleep(30)'
            code = ('import subprocess,sys,time,signal; signal.alarm(5); '
                    'p=subprocess.Popen([sys.executable,"-c",sys.argv[1]]); '
                    'print(p.pid,flush=True); time.sleep(30)')
            rows = []
            m.command([sys.executable, '-c', code, child], 'child.txt',
                      time.monotonic() + 4, out, dict(os.environ), out, rows)
            self.assertEqual(rows[0]['status'], 'TIMEOUT')
            self.assertTrue(rows[0]['cleanup_confirmed'])


if __name__ == '__main__':
    main()
