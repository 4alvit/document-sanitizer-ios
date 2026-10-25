"""Offline control-flow tests: every process, signal and clock is injected.

Run with unittest discovery. The sibling driver is imported without __main__;
no Xcode, simulator, application, process group, or native test is executed.
"""
from contextlib import ExitStack
import importlib.util
import inspect
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import tempfile
import unittest
from unittest import mock


DRIVER = Path(__file__).with_name('check-privacy-ipad.py')
CASE = 'PrivacySupportUITests/testRussianOfflineInformationAtSystemAX5OnLandscapeIPad'
UID = 'A09F18F8-31EF-432D-A426-0197E73D75E8'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-18-5'
DEVICE = 'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M4-16GB'


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError('negative synthetic sleep')
        self.value += seconds


class FakeProcess:
    def __init__(self, backend, args, output):
        self.backend, self.args, self.output = backend, args, output
        self.pid = 5000 + len(backend.processes)
        self.returncode = None
        self.group_present = True
        self.wait_calls = []
        self.step = backend.step(args)
        self.fault_used = False

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self.returncode is not None:
            return self.returncode
        if self.step == self.backend.fault_step and not self.fault_used:
            self.fault_used = True
            fault = self.backend.fault
            if fault == 'timeout':
                if self.step in ('test', 'runtimes'):
                    self.backend.fixture.clock.value += timeout
                raise subprocess.TimeoutExpired(self.args, timeout)
            if fault == 'signal':
                self.backend.handlers[signal.SIGTERM](signal.SIGTERM, None)
            if fault == 'nonzero':
                if self.step == 'test':
                    self.backend.complete(self)
                self.returncode, self.group_present = 7, False
                return self.returncode
        if self.step == 'set_ax5':
            duration = self.backend.set_ax5_seconds
            self.backend.fixture.clock.value += min(duration, timeout)
            if duration > timeout:
                raise subprocess.TimeoutExpired(self.args, timeout)
        self.backend.complete(self)
        self.returncode = 0
        self.group_present = self.step == 'test' and self.backend.test_group_permission_error
        return 0

    def poll(self):
        return self.returncode


class FakeBackend:
    """Command responses only; unknown commands fail and are recorded."""
    def __init__(self, fixture):
        self.fixture = fixture
        self.processes, self.calls, self.signals, self.forbidden = [], [], [], []
        self.handlers = {}
        self.fault_step = self.fault = None
        self.readback_elapsed = 345.0
        self.bootstatus_elapsed = 0.0
        self.set_ax5_seconds = 0.0
        self.bad_ax5 = False
        self.omit_result = False
        self.summary = {'passedTests': 1, 'failedTests': 0, 'skippedTests': 0, 'totalTestCount': 1}
        self.nodes = [{'nodeType': 'Test Case', 'nodeIdentifier': CASE, 'result': 'Passed'}]
        self.mutate = None
        self.leave_device = False
        self.created = self.deleted = False
        self.device_name = None
        self.bad_tree = False
        self.test_group_permission_error = False

    def deny(self, *args, **kwargs):
        self.forbidden.append(repr(args))
        raise AssertionError('native boundary not injected: ' + repr(args))

    def step(self, args):
        if args[0] == 'git':
            return 'git'
        if args[0] == 'xcodebuild':
            if 'build-for-testing' in args:
                return 'build'
            if 'test-without-building' in args:
                return 'test'
            if args[1:] == ['-version']:
                return 'version'
        if args == ['xcode-select', '-p']:
            return 'developer'
        if args == ['sw_vers']:
            return 'macos'
        if args[0] == 'codesign' and args[1:4] == ['--verify', '--strict', '--all-architectures']:
            return 'signature'
        if args[:4] == ['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version']:
            return 'sdk'
        if args[:2] == ['xcrun', 'simctl']:
            if args[2] == 'ui':
                return 'readback' if len(args) == 5 else 'set_ax5'
            if args[2] in ('create', 'boot', 'bootstatus', 'shutdown', 'delete'):
                return args[2]
            if args[2:4] in (['list', 'runtimes'], ['list', 'devicetypes'], ['list', 'devices']):
                return args[3]
        if args[:2] == ['xcrun', 'xcresulttool']:
            if args[2:4] == ['export', 'attachments']:
                return 'attachments'
            if args[2:4] == ['get', 'test-results'] and args[4] in ('summary', 'tests'):
                return args[4]
        return self.deny(args)

    def popen(self, args, **kwargs):
        args = list(map(str, args))
        self.calls.append(args)
        if kwargs.get('start_new_session') is not True or kwargs.get('stdout') is None:
            return self.deny(args, kwargs)
        proc = FakeProcess(self, args, kwargs['stdout'])
        self.processes.append(proc)
        return proc

    def killpg(self, pid, sig):
        self.signals.append((pid, sig))
        proc = next((p for p in self.processes if p.pid == pid), None)
        if proc is None:
            return self.deny(pid, sig)
        if proc.step == 'test' and self.test_group_permission_error:
            raise PermissionError('synthetic test group remains; probe/signal denied')
        if not proc.group_present:
            raise ProcessLookupError('synthetic group absent')
        if sig:
            proc.group_present = False
            proc.returncode = -int(sig)

    def getpgid(self, pid):
        if not any(p.pid == pid for p in self.processes):
            return self.deny(pid)
        return pid

    def signal(self, sig, handler):
        previous = self.handlers.get(sig)
        self.handlers[sig] = handler
        return previous

    def complete(self, proc):
        f, a, step = self.fixture, proc.args, proc.step
        output = ''
        if step == 'git':
            if a[1:3] == ['rev-parse', 'HEAD']:
                output = 'checkout'
            elif a[1] == 'rev-parse':
                output = 'wrong-tree' if self.bad_tree and a[2] == 'HEAD^{tree}' else 'tree'
            elif a[1] == 'ls-files':
                output = 'source.txt\n'
            elif a[1] != 'status':
                return self.deny(a)
        elif step == 'version':
            output = 'Xcode 16.4\nBuild version 16F6'
        elif step == 'sdk':
            output = '18.5'
        elif step == 'macos':
            output = 'Synthetic macOS fixture'
        elif step == 'developer':
            output = str(f.developer)
        elif step == 'runtimes':
            output = {'runtimes': [{'identifier': RUNTIME, 'version': '18.5', 'isAvailable': True,
                       'supportedArchitectures': ['arm64', 'x86_64'],
                       'supportedDeviceTypes': [{'identifier': DEVICE}]}]}
        elif step == 'devicetypes':
            output = {'devicetypes': [{'identifier': DEVICE, 'name': 'iPad Pro 13-inch (M4) (16GB)',
                       'productFamily': 'iPad', 'minRuntimeVersionString': '17.5',
                       'maxRuntimeVersionString': '99.0'}]}
        elif step == 'create':
            self.created, self.device_name = True, a[3]
            output = UID
        elif step == 'bootstatus':
            f.clock.value = self.bootstatus_elapsed
        elif step == 'readback':
            f.clock.value = self.readback_elapsed
            output = 'large' if self.bad_ax5 else f.module.AX5
        elif step == 'delete':
            self.deleted = True
        elif step == 'devices':
            present = self.created and (not self.deleted or self.leave_device)
            output = {'devices': {RUNTIME: [{'udid': UID, 'name': self.device_name}] if present else []}}
        elif step == 'test':
            if not self.omit_result:
                result = f.out / 'result.xcresult'
                result.mkdir()
                (result / 'synthetic-result').write_bytes(b'unchanged original xcresult bytes')
                staging = result / 'Staging/1_Test/Diagnostics/startup.log'
                staging.parent.mkdir(parents=True)
                staging.write_bytes(b'unchanged existing staging diagnostics\n')
            if self.mutate == 'source':
                (f.root / 'source.txt').write_text('changed after test')
            elif self.mutate == 'payload':
                (f.app / 'CleanSend').write_bytes(b'changed built AUT bytes')
        elif step == 'summary':
            output = self.summary
        elif step == 'tests':
            output = {'testNodes': self.nodes}
        elif step == 'attachments':
            Path(a[a.index('--output-path') + 1]).mkdir()
        if isinstance(output, (dict, list)):
            output = json.dumps(output)
        proc.output.write(output.encode('utf-8'))
        proc.output.flush()


class Fixture:
    def __init__(self, test):
        self.test = test
        self.stack = ExitStack()
        test.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.clock = FakeClock()
        self.backend = FakeBackend(self)
        # Guards are already active during dynamic import; __main__ never runs.
        for name in ('Popen', 'check_output', 'run', 'call', 'check_call'):
            self.stack.enter_context(mock.patch.object(subprocess, name, self.backend.deny))
        for name in ('killpg', 'getpgid', 'kill', 'system'):
            self.stack.enter_context(mock.patch.object(os, name, self.backend.deny))
        self.stack.enter_context(mock.patch.object(signal, 'signal', self.backend.deny))
        spec = importlib.util.spec_from_file_location('privacy_ipad_driver_offline_test', DRIVER)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.import_calls = list(self.backend.forbidden)
        self.stack.enter_context(mock.patch.object(self.module, 'ENV',
            {'PATH': '/synthetic/bin', 'HOME': str(self.root), 'LANG': 'en_US.UTF-8'}))
        self.stack.enter_context(mock.patch.object(self.module.shutil, 'which', return_value=None))
        self.stack.enter_context(mock.patch.object(subprocess, 'Popen', self.backend.popen))
        self.stack.enter_context(mock.patch.object(os, 'killpg', self.backend.killpg))
        self.stack.enter_context(mock.patch.object(os, 'getpgid', self.backend.getpgid))
        self.stack.enter_context(mock.patch.object(signal, 'signal', self.backend.signal))
        self.stack.enter_context(mock.patch.object(self.module.time, 'monotonic', self.clock.monotonic))
        self.stack.enter_context(mock.patch.object(self.module.time, 'sleep', self.clock.sleep))
        self.stack.enter_context(mock.patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'macOS',
            'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_RUN_ATTEMPT': '1', 'EXPECTED_HEAD_SHA': 'head',
            'GITHUB_SHA': 'checkout', 'GITHUB_RUN_ID': 'offline-fixture'}))
        self.out = self.root / '.qa/privacy-ipad'
        self.out.mkdir(parents=True)
        self.dd = self.root / '.qa/privacy-ipad-build'
        self.module.ROOT, self.module.OUT, self.module.DD = self.root, self.out, self.dd
        self.developer = self.root / 'synthetic-xcode/Contents/Developer'
        framework = self.developer / 'Platforms/iPhoneSimulator.platform/Developer/Library/Frameworks/XCTest.framework/XCTest'
        framework.parent.mkdir(parents=True)
        framework.write_bytes(b'synthetic framework, never executable')
        self.app = self.dd / 'Build/Products/Debug-iphonesimulator/CleanSend.app'
        runner = self.app.parent / 'CleanSendUITests-Runner.app'
        bundle = runner / 'PlugIns/CleanSendUITests.xctest'
        self.app.mkdir(parents=True)
        bundle.mkdir(parents=True)
        (self.app / 'Info.plist').write_bytes(plistlib.dumps({'DTSDKName': 'iphonesimulator18.5'}))
        (self.app / 'CleanSend').write_bytes(b'synthetic AUT, never executable')
        (runner / 'Runner').write_bytes(b'synthetic runner, never executable')
        (bundle / 'Tests').write_bytes(b'synthetic test bundle, never executable')
        (self.root / 'source.txt').write_text('frozen synthetic source')
        target = {'BlueprintName': 'CleanSendUITests', 'IsUITestBundle': True,
                  'IsXCTRunnerHostedTestBundle': True,
                  'TestHostPath': '__TESTROOT__/Debug-iphonesimulator/CleanSendUITests-Runner.app',
                  'TestBundlePath': '__TESTHOST__/PlugIns/CleanSendUITests.xctest',
                  'UITargetAppPath': '__TESTROOT__/Debug-iphonesimulator/CleanSend.app',
                  'TestingEnvironmentVariables': {'DYLD_FRAMEWORK_PATH': '__PLATFORMS__/iPhoneSimulator.platform/Developer/Library/Frameworks'}}
        plan = {'__xctestrun_metadata__': {'FormatVersion': 2},
                'TestConfigurations': [{'Name': 'Local Testing', 'TestTargets': [
                    {'BlueprintName': 'CleanSendTests'}, target]}]}
        (self.dd / 'Build/Products/synthetic.xctestrun').write_bytes(plistlib.dumps(plan))
        test.addCleanup(self.assert_injected_only)

    def assert_injected_only(self):
        self.test.assertEqual(self.backend.forbidden, [], 'an uninjected native boundary was attempted')
        self.test.assertFalse(any('stream' in a or 'log' in a for a in self.backend.calls),
                              'baseline must not start log streams')

    def run(self):
        rc = self.module.worker()
        return rc, json.loads((self.out / 'metadata.json').read_text())

    def assert_cleanup(self, meta):
        actions = [(p.step, p.args) for p in self.backend.processes if p.step in ('shutdown', 'delete')]
        self.test.assertEqual([a[0] for a in actions], ['shutdown', 'delete'])
        self.test.assertTrue(all(a[1][-1] == UID for a in actions))
        self.test.assertEqual(meta['cleanup'], {'shutdown': 0, 'delete': 0})
        self.test.assertTrue(meta['device_removed'])

    def test_processes(self):
        return [p for p in self.backend.processes if p.step == 'test']


class BaselineWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def assert_failed(self, meta, text=None):
        self.assertEqual(meta['result'], 'failed')
        self.assertTrue(meta['failures'])
        if text:
            self.assertIn(text, '\n'.join(meta['failures']))

    def test_runtime_timeout_records_wait_stop_and_context_without_retry(self):
        self.f.backend.fault_step, self.f.backend.fault = 'runtimes', 'timeout'
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        processes = [p for p in self.f.backend.processes if p.step == 'runtimes']
        self.assertEqual(len(processes), 1)
        self.assertEqual(processes[0].wait_calls, [60])
        command = next(c for c in meta['commands'] if c['args'][2:4] == ['list', 'runtimes'])
        observation = command['runtime_observation']
        self.assertTrue(command['owned_group_absent'])
        self.assertEqual(observation['wait_or_persist_error'], 'TimeoutExpired')
        self.assertEqual(observation['output_bytes_at_wait_end'], 0)
        self.assertEqual(observation['stop_signals'], [{'signal': 'SIGTERM', 'result': 'SENT'}])
        self.assertEqual(observation['stop_probe_count'], 2)
        self.assertEqual(observation['last_stop_probe']['group'], 'ABSENT')
        self.assertTrue(observation['last_stop_probe']['leader_reaped'])
        self.assertEqual(meta['runtime_discovery_context']['child_env']['DEVELOPER_DIR'], None)
        self.assertEqual(meta['runtime_discovery_context']['child_env']['PATH']['value'], '/synthetic/bin')
        self.assertFalse(any(p.step in ('build', 'create', 'test') for p in self.f.backend.processes))
        self.assertNotIn('owned_uuid', meta)

    def test_runtime_output_stat_error_does_not_mask_timeout_or_skip_cleanup(self):
        self.f.backend.fault_step, self.f.backend.fault = 'runtimes', 'timeout'
        with mock.patch.object(self.f.module.os, 'fstat', side_effect=OSError('synthetic stat failure')):
            rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        command = next(c for c in meta['commands'] if c['args'][2:4] == ['list', 'runtimes'])
        self.assertTrue(command['owned_group_absent'])
        self.assertEqual(command['runtime_observation']['output_size_error'], 'OSError')
        self.assertNotIn('output_bytes_at_wait_end', command['runtime_observation'])

    def test_runtime_spawn_failure_is_recorded_without_wait_or_owned_cleanup(self):
        original = self.f.backend.popen
        def spawn(args, **kwargs):
            if args[2:4] == ['list', 'runtimes']:
                raise FileNotFoundError('synthetic missing xcrun')
            return original(args, **kwargs)
        with mock.patch.object(self.f.module.subprocess, 'Popen', spawn):
            rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'synthetic missing xcrun')
        command = next(c for c in meta['commands'] if c['args'][2:4] == ['list', 'runtimes'])
        self.assertEqual(command['runtime_observation']['spawn_error'], 'FileNotFoundError')
        self.assertNotIn('owned_process_group', command)
        self.assertNotIn('wait_started_monotonic', command['runtime_observation'])
        self.assertFalse(any(p.step in ('runtimes', 'build', 'create') for p in self.f.backend.processes))

    def test_runtime_context_preserves_empty_path_and_limits_display_without_secrets(self):
        env = {'PATH': '', 'DEVELOPER_DIR': 'x' * 4100, 'LANG': 'C'}
        with mock.patch.object(self.f.module, 'ENV', env), \
             mock.patch.dict(os.environ, {'SDKROOT': 'private-value', 'TOKEN_SECRET': 'do-not-capture'}), \
             mock.patch.object(self.f.module.shutil, 'which', return_value=None) as lookup:
            context = self.f.module.runtime_context()
        lookup.assert_not_called()
        self.assertEqual(context['tools']['xcrun']['status'], 'NOT_READ_RELATIVE_OR_EMPTY_PATH')
        self.assertEqual(context['child_env']['PATH']['value'], '')
        self.assertTrue(context['child_env']['DEVELOPER_DIR']['truncated'])
        self.assertEqual(len(context['child_env']['DEVELOPER_DIR']['value']), 4096)
        self.assertTrue(context['parent_presence_only']['SDKROOT'])
        self.assertNotIn('private-value', json.dumps(context))
        self.assertNotIn('TOKEN_SECRET', json.dumps(context))
        with mock.patch.object(self.f.module, 'ENV', {'PATH': 'x' * 8193}), \
             mock.patch.object(self.f.module.shutil, 'which') as lookup:
            context = self.f.module.runtime_context()
        lookup.assert_not_called()
        self.assertEqual(context['tools']['xcrun']['status'], 'NOT_READ_PATH_LIMIT')

    def test_runtime_lookup_error_and_absent_path_do_not_replace_timeout(self):
        self.f.backend.fault_step, self.f.backend.fault = 'runtimes', 'timeout'
        with mock.patch.object(self.f.module, 'ENV', {'LANG': 'C'}), \
             mock.patch.object(self.f.module.shutil, 'which', side_effect=OSError('synthetic lookup failure')) as lookup:
            rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        self.assertNotIn('synthetic lookup failure', str(meta['failures']))
        self.assertEqual(lookup.call_args_list, [mock.call('xcrun', path=os.defpath), mock.call('xcodebuild', path=os.defpath)])
        self.assertIsNone(meta['runtime_discovery_context']['child_env']['PATH'])
        self.assertEqual(meta['runtime_discovery_context']['tools']['xcrun']['status'], 'UNKNOWN_LOOKUP_ERROR')

    def test_runtime_context_cost_reduces_allowance_and_can_deny_launch(self):
        for elapsed, expected_wait in ((499.0, 57.0), (557.0, None)):
            with self.subTest(elapsed=elapsed):
                f = Fixture(self)
                f.backend.fault_step, f.backend.fault = 'runtimes', 'timeout'
                def context():
                    f.clock.value = elapsed
                    return {'synthetic_context': True}
                with mock.patch.object(f.module, 'runtime_context', side_effect=context):
                    rc, meta = f.run()
                self.assertEqual(rc, 1)
                runtimes = [p for p in f.backend.processes if p.step == 'runtimes']
                self.assertEqual([p.wait_calls for p in runtimes], [] if expected_wait is None else [[expected_wait]])
                self.assertFalse(any(p.step in ('build', 'create', 'test') for p in f.backend.processes))
                self.assertEqual(meta['runtime_discovery_context'], {'synthetic_context': True})

    def test_runtime_cleanup_failure_records_bounded_existing_probes(self):
        self.f.backend.fault_step, self.f.backend.fault = 'runtimes', 'timeout'
        original = self.f.backend.killpg
        def signal_or_probe(pid, sig):
            proc = next(p for p in self.f.backend.processes if p.pid == pid)
            if proc.step == 'runtimes':
                raise PermissionError('synthetic group access denied')
            return original(pid, sig)
        with mock.patch.object(self.f.module.os, 'killpg', signal_or_probe):
            rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        command = next(c for c in meta['commands'] if c['args'][2:4] == ['list', 'runtimes'])
        observation = command['runtime_observation']
        self.assertFalse(command['owned_group_absent'])
        self.assertIn('TimeoutExpired', command['command_error'])
        self.assertIn('cleanup', command['cleanup_error'])
        self.assertEqual([s['signal'] for s in observation['stop_signals']], ['SIGTERM', 'SIGKILL'])
        self.assertGreater(observation['stop_probe_count'], 2)
        self.assertEqual(observation['last_stop_probe']['error'], 'PermissionError')
        self.assertLess(len(json.dumps(observation)), 1500)
        self.assertFalse(any(p.step in ('build', 'create', 'test') for p in self.f.backend.processes))

    def test_runtime_diagnostic_clock_interruption_still_stops_owned_child(self):
        for field, fault in (('spawn_returned_monotonic', None),
                             ('wait_started_monotonic', None),
                             ('wait_finished_monotonic', None),
                             ('wait_finished_monotonic', 'timeout')):
            with self.subTest(field=field, fault=fault):
                f = Fixture(self)
                f.backend.fault_step, f.backend.fault = 'runtimes', fault
                injected = []
                def clock():
                    frame = inspect.currentframe().f_back
                    line = inspect.getframeinfo(frame).code_context or []
                    if not injected and field in ''.join(line):
                        injected.append(field)
                        raise InterruptedError('synthetic diagnostic cancellation')
                    return f.clock.value
                with mock.patch.object(f.module.time, 'monotonic', new=clock):
                    rc, meta = f.run()
                self.assertEqual(injected, [field])
                self.assertEqual(rc, 1)
                self.assert_failed(meta, 'synthetic diagnostic cancellation')
                proc = next(p for p in f.backend.processes if p.step == 'runtimes')
                command = next(c for c in meta['commands'] if c.get('owned_process_group') == proc.pid)
                self.assertFalse(proc.group_present)
                self.assertIsNotNone(proc.returncode)
                self.assertTrue(command['owned_group_absent'])
                if fault == 'timeout':
                    self.assertEqual(command['runtime_observation']['wait_error'], 'TimeoutExpired')
                self.assertFalse(any(p.step in ('build', 'create', 'test') for p in f.backend.processes))

    def test_runtime_lookup_cancellation_fails_before_child_launch(self):
        with mock.patch.object(self.f.module.shutil, 'which',
                               side_effect=InterruptedError('synthetic lookup cancellation')):
            rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'synthetic lookup cancellation')
        self.assertFalse(any(p.step in ('runtimes', 'build', 'create', 'test') for p in self.f.backend.processes))

    def test_runtime_stat_cancellation_fails_and_confirms_owned_cleanup(self):
        for fault in (None, 'timeout'):
            with self.subTest(fault=fault):
                f = Fixture(self)
                f.backend.fault_step, f.backend.fault = 'runtimes', fault
                with mock.patch.object(f.module.os, 'fstat',
                                       side_effect=InterruptedError('synthetic stat cancellation')):
                    rc, meta = f.run()
                self.assertEqual(rc, 1)
                self.assert_failed(meta, 'synthetic stat cancellation')
                proc = next(p for p in f.backend.processes if p.step == 'runtimes')
                command = next(c for c in meta['commands'] if c.get('owned_process_group') == proc.pid)
                self.assertFalse(proc.group_present)
                self.assertTrue(command['owned_group_absent'])
                if fault == 'timeout':
                    self.assertEqual(command['runtime_observation']['wait_error'], 'TimeoutExpired')
                self.assertFalse(any(p.step in ('build', 'create', 'test') for p in f.backend.processes))

    def test_runtime_relative_or_empty_path_is_explicitly_not_resolved(self):
        for path in ('bin:/usr/bin', '/usr/bin:', ':/usr/bin'):
            with self.subTest(path=path), mock.patch.object(self.f.module, 'ENV', {'PATH': path}), \
                 mock.patch.object(self.f.module.shutil, 'which') as lookup:
                context = self.f.module.runtime_context()
                lookup.assert_not_called()
                self.assertEqual(context['child_env']['PATH']['value'], path)
                self.assertTrue(all(t['status'] == 'NOT_READ_RELATIVE_OR_EMPTY_PATH'
                                    for t in context['tools'].values()))

    def test_import_is_inert(self):
        self.assertEqual(self.f.import_calls, [])
        self.assertEqual(self.f.backend.calls, [])
        self.assertEqual(self.f.backend.signals, [])

    def test_exact_215_seconds_reaches_one_unchanged_ui_test_and_preserves_result(self):
        rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        self.assertEqual(meta['result'], 'passed_pending_independent_review')
        self.assertEqual(meta['counts'], {'passedTests': 1, 'failedTests': 0, 'skippedTests': 0, 'totalTestCount': 1})
        tests = self.f.test_processes()
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0].wait_calls, [210])
        self.assertEqual(tests[0].args, ['xcodebuild', 'test-without-building', '-xctestrun',
            str(self.f.out / 'selected.xctestrun'), '-destination', 'platform=iOS Simulator,id=' + UID,
            '-parallel-testing-enabled', 'NO', '-maximum-concurrent-test-simulator-destinations', '1',
            '-collect-test-diagnostics', 'never', '-resultBundlePath', str(self.f.out / 'result.xcresult'),
            '-only-testing:CleanSendUITests/' + CASE])
        self.assertEqual(sum(p.step == 'build' for p in self.f.backend.processes), 1)
        self.assertFalse(meta['launch_capture']['enabled'])
        self.assertEqual(meta['launch_capture']['coverage'], 'NOT_COLLECTED')
        self.assertEqual(meta['native_storekit_tests'], 0)
        self.assertFalse(meta['retry'])
        self.assertTrue(all(c['owned_group_absent'] for c in meta['commands'] if c['args'][0] == 'xcodebuild'))
        self.assertEqual((self.f.out / 'result.xcresult/synthetic-result').read_bytes(), b'unchanged original xcresult bytes')
        self.assertEqual((self.f.out / 'result.xcresult/Staging/1_Test/Diagnostics/startup.log').read_bytes(),
                         b'unchanged existing staging diagnostics\n')
        self.f.assert_cleanup(meta)

    def test_less_than_215_seconds_denies_test_and_cleans_owned_device(self):
        self.f.backend.readback_elapsed = 345.001
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'No full runtime/cleanup budget')
        self.assertEqual(self.f.test_processes(), [])
        self.f.assert_cleanup(meta)

    def test_exact_ax5_admission_allows_full_commands_and_test(self):
        self.f.backend.bootstatus_elapsed = 292.0  # 268s remain in WORK_END.
        self.f.backend.set_ax5_seconds = 30.0
        self.f.backend.readback_elapsed = 337.0  # Setter30 + readback15.
        rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        commands = [p for p in self.f.backend.processes if p.step in ('set_ax5', 'readback', 'test')]
        self.assertEqual([p.step for p in commands], ['set_ax5', 'readback', 'test'])
        self.assertEqual([p.wait_calls for p in commands], [[30], [15], [210]])
        self.assertEqual(meta['actual_system_content_size'], self.f.module.AX5)
        self.f.assert_cleanup(meta)

    def test_less_than_ax5_admission_denies_both_commands_and_test(self):
        self.f.backend.bootstatus_elapsed = 292.001
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'No full AX5 setup and runtime/cleanup budget')
        self.assertFalse(any(p.step in ('set_ax5', 'readback', 'test') for p in self.f.backend.processes))
        self.f.assert_cleanup(meta)

    def test_ax5_setter_over_30_seconds_stops_without_readback_or_retry(self):
        self.f.backend.set_ax5_seconds = 30.001
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        setters = [p for p in self.f.backend.processes if p.step == 'set_ax5']
        self.assertEqual(len(setters), 1)
        self.assertEqual(setters[0].wait_calls, [30])
        self.assertFalse(any(p.step in ('readback', 'test') for p in self.f.backend.processes))
        record = next(c for c in meta['commands'] if c.get('owned_process_group') == setters[0].pid)
        self.assertTrue(record['interrupted'])
        self.assertTrue(record['owned_group_absent'])
        self.f.assert_cleanup(meta)

    def test_ax5_readback_timeout_does_not_start_test_or_retry(self):
        self.f.backend.fault_step, self.f.backend.fault = 'readback', 'timeout'
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        readbacks = [p for p in self.f.backend.processes if p.step == 'readback']
        self.assertEqual(len(readbacks), 1)
        self.assertEqual(readbacks[0].wait_calls, [15])
        self.assertEqual(self.f.test_processes(), [])
        self.assertNotIn('actual_system_content_size', meta)
        self.f.assert_cleanup(meta)

    def test_wrong_system_ax5_denies_test_and_cleans(self):
        self.f.backend.bad_ax5 = True
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assertEqual(self.f.test_processes(), [])
        self.f.assert_cleanup(meta)

    def test_nonzero_setup_command_still_cleans(self):
        self.f.backend.fault_step, self.f.backend.fault = 'bootstatus', 'nonzero'
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'bootstatus.log exited 7')
        self.f.assert_cleanup(meta)

    def test_timed_out_setup_command_stops_only_owned_group_and_cleans(self):
        self.f.backend.fault_step, self.f.backend.fault = 'bootstatus', 'timeout'
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        proc = next(p for p in self.f.backend.processes if p.step == 'bootstatus')
        self.assertIn((proc.pid, signal.SIGTERM), self.f.backend.signals)
        self.assertFalse(proc.group_present)
        self.f.assert_cleanup(meta)

    def test_injected_sigterm_still_cleans(self):
        self.f.backend.fault_step, self.f.backend.fault = 'bootstatus', 'signal'
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'SIGTERM')
        self.f.assert_cleanup(meta)

    def test_post_spawn_persistence_failure_stops_group_and_still_cleans(self):
        original_save = self.f.module.save
        failed = []
        def save(path, value):
            commands = value.get('commands', []) if isinstance(value, dict) else []
            if commands and not failed:
                last = commands[-1]
                if last['args'][:3] == ['xcrun', 'simctl', 'boot'] and 'owned_process_group' in last:
                    failed.append(True)
                    raise OSError('injected post-spawn metadata write failure')
            return original_save(path, value)
        with mock.patch.object(self.f.module, 'save', save):
            rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assertEqual(failed, [True])
        self.assert_failed(meta, 'post-spawn metadata')
        proc = next(p for p in self.f.backend.processes if p.step == 'boot')
        self.assertEqual(proc.wait_calls, [])
        self.assertFalse(proc.group_present)
        command = next(c for c in meta['commands'] if c['args'][:3] == ['xcrun', 'simctl', 'boot'])
        self.assertTrue(command['owned_group_absent'])
        self.f.assert_cleanup(meta)

    def test_no_result_bundle_cannot_pass(self):
        self.f.backend.omit_result = True
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'No xcresult')
        self.f.assert_cleanup(meta)

    def test_nonzero_xcodebuild_cannot_pass_even_with_valid_result(self):
        self.f.backend.fault_step, self.f.backend.fault = 'test', 'nonzero'
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assertEqual(meta['xcodebuild_returncode'], 7)
        self.assertEqual(meta['counts']['passedTests'], 1)
        self.assertEqual(len(self.f.test_processes()), 1)
        self.assert_failed(meta, 'Result acceptance:')
        self.f.assert_cleanup(meta)

    def test_timed_out_xctest_stops_owned_group_and_cleans_without_result(self):
        self.f.backend.fault_step, self.f.backend.fault = 'test', 'timeout'
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        self.assert_failed(meta, 'No xcresult')
        tests = self.f.test_processes()
        self.assertEqual(len(tests), 1)
        proc = tests[0]
        self.assertEqual(proc.wait_calls, [210])
        self.assertIn((proc.pid, signal.SIGTERM), self.f.backend.signals)
        self.assertFalse(proc.group_present)
        command = next(c for c in meta['commands'] if 'test-without-building' in c['args'])
        self.assertTrue(command['interrupted'])
        self.assertTrue(command['owned_group_absent'])
        self.assertNotIn('cleanup_error', command)
        self.assertFalse((self.f.out / 'result.xcresult').exists())
        self.assertNotIn('counts', meta)
        self.assertNotIn('xcodebuild_returncode', meta)
        self.f.assert_cleanup(meta)

    def test_successful_xctest_with_unconfirmed_group_cannot_pass_and_cleans_device(self):
        self.f.backend.test_group_permission_error = True
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'Owned process/group cleanup unconfirmed')
        tests = self.f.test_processes()
        self.assertEqual(len(tests), 1)
        proc = tests[0]
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.group_present)
        self.assertEqual(meta['counts'], {'passedTests': 1, 'failedTests': 0,
                                         'skippedTests': 0, 'totalTestCount': 1})
        command = next(c for c in meta['commands'] if 'test-without-building' in c['args'])
        self.assertEqual(command['returncode'], 0)
        self.assertFalse(command['owned_group_absent'])
        self.assertIn('PermissionError', command['cleanup_error'])
        self.assertTrue(command['cleanup_errors'])
        for sig in (0, signal.SIGTERM, signal.SIGKILL):
            self.assertIn((proc.pid, sig), self.f.backend.signals)
        self.assertNotIn('xcodebuild_returncode', meta)
        self.assertTrue((self.f.out / 'result.xcresult').is_dir())
        self.f.assert_cleanup(meta)

    def test_skipped_case_cannot_pass(self):
        self.f.backend.summary.update(passedTests=0, skippedTests=1)
        self.f.backend.nodes[0]['result'] = 'Skipped'
        self.assertEqual(self.f.run()[0], 1)

    def test_failed_case_cannot_pass(self):
        self.f.backend.summary.update(passedTests=0, failedTests=1)
        self.f.backend.nodes[0]['result'] = 'Failed'
        self.assertEqual(self.f.run()[0], 1)

    def test_wrong_case_cannot_pass_even_with_success_counts(self):
        self.f.backend.nodes[0]['nodeIdentifier'] = 'OtherTests/testWrongCase'
        self.assertEqual(self.f.run()[0], 1)

    def test_missing_case_cannot_pass_even_with_success_counts(self):
        self.f.backend.nodes = []
        self.assertEqual(self.f.run()[0], 1)

    def test_wrong_case_result_cannot_pass_even_with_success_counts(self):
        self.f.backend.nodes[0]['result'] = 'Failed'
        self.assertEqual(self.f.run()[0], 1)

    def test_missing_summary_count_cannot_pass(self):
        del self.f.backend.summary['skippedTests']
        self.assertEqual(self.f.run()[0], 1)

    def test_source_changed_after_test_cannot_pass(self):
        self.f.backend.mutate = 'source'
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'Integrity:')
        self.f.assert_cleanup(meta)

    def test_built_payload_changed_after_test_cannot_pass(self):
        self.f.backend.mutate = 'payload'
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'Integrity:')
        self.f.assert_cleanup(meta)

    def test_inconsistent_source_tree_denies_before_build_or_create(self):
        self.f.backend.bad_tree = True
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assertFalse(self.f.backend.created)
        self.assertFalse(any(p.step == 'build' for p in self.f.backend.processes))
        self.assert_failed(meta)

    def test_device_still_present_cannot_pass_successful_test(self):
        self.f.backend.leave_device = True
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assertFalse(meta['device_removed'])
        self.assert_failed(meta, 'Cleanup:')


if __name__ == '__main__':
    unittest.main()
