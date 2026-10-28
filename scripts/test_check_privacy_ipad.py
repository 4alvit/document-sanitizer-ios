"""Offline control-flow tests: every process, signal and clock is injected.

Run with unittest discovery. The sibling driver is imported without __main__;
no Xcode, simulator, application, process group, or native test is executed.
"""
from contextlib import ExitStack
import ast
import errno
import importlib.util
import inspect
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import tempfile
import time
import traceback
from types import SimpleNamespace
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
        if self.step in ('set_ax5', 'readback', 'test'):
            duration = {'set_ax5': self.backend.set_ax5_seconds,
                        'readback': self.backend.readback_seconds,
                        'test': self.backend.test_seconds}[self.step]
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
        self.readback_seconds = 0.0
        self.test_seconds = 0.0
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
            if self.readback_elapsed is not None:
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
        self.stack.enter_context(mock.patch.object(time, 'monotonic', self.clock.monotonic))
        self.stack.enter_context(mock.patch.object(time, 'sleep', self.clock.sleep))
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
            'GITHUB_SHA': 'checkout', 'GITHUB_RUN_ID': '123456789'}))
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
        self.assertEqual(observation['stop_signals'], [{'signal': 'SIGTERM', 'result': 'SYSCALL_RETURNED'}])
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
                self.assert_failed(meta, 'TimeoutExpired' if fault == 'timeout' else 'synthetic diagnostic cancellation')
                proc = next(p for p in f.backend.processes if p.step == 'runtimes')
                command = next(c for c in meta['commands'] if c.get('owned_process_group') == proc.pid)
                self.assertFalse(proc.group_present)
                self.assertIsNotNone(proc.returncode)
                self.assertTrue(command['owned_group_absent'])
                if fault == 'timeout':
                    self.assertEqual(command['runtime_observation']['wait_error'], 'TimeoutExpired')
                    self.assertEqual(command['command_error_operation'], 'wait')
                    self.assertEqual(command['secondary_errors']['wait_observation']['exception_type'], 'InterruptedError')
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
                self.assert_failed(meta, 'TimeoutExpired' if fault == 'timeout' else 'synthetic stat cancellation')
                proc = next(p for p in f.backend.processes if p.step == 'runtimes')
                command = next(c for c in meta['commands'] if c.get('owned_process_group') == proc.pid)
                self.assertFalse(proc.group_present)
                self.assertTrue(command['owned_group_absent'])
                if fault == 'timeout':
                    self.assertEqual(command['runtime_observation']['wait_error'], 'TimeoutExpired')
                    self.assertEqual(command['command_error_operation'], 'wait')
                    self.assertEqual(command['secondary_errors']['wait_observation']['exception_type'], 'InterruptedError')
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

    def test_selected_ax5_config_240_preserves_original_and_excludes_other_cases(self):
        generated = self.f.dd / 'Build/Products/synthetic.xctestrun'
        data = plistlib.loads(generated.read_bytes())
        targets = data['TestConfigurations'][0]['TestTargets']
        targets[0].update(MaximumTestExecutionTimeAllowance=180,
                          OnlyTestIdentifiers=['OrdinaryTests/testUnrelated'])
        targets[1].update(TestTimeoutsEnabled=True, DefaultTestExecutionTimeAllowance=120,
                          MaximumTestExecutionTimeAllowance=180,
                          OnlyTestIdentifiers=[CASE, 'PrivacySupportUITests/testEnglishOfflineInformationFromWorkspaceAndProPreservesDocument'])
        original = plistlib.dumps(data)
        generated.write_bytes(original)
        rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        selected = plistlib.loads((self.f.out / 'selected.xctestrun').read_bytes())
        chosen = selected['TestConfigurations'][0]['TestTargets']
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0]['BlueprintName'], 'CleanSendUITests')
        self.assertEqual(chosen[0]['OnlyTestIdentifiers'], [CASE])
        self.assertEqual(chosen[0]['SkipTestIdentifiers'], [])
        self.assertTrue(chosen[0]['TestTimeoutsEnabled'])
        self.assertEqual(chosen[0]['DefaultTestExecutionTimeAllowance'], 120)
        self.assertEqual(chosen[0]['MaximumTestExecutionTimeAllowance'], 240)
        self.assertEqual(generated.read_bytes(), original)
        self.assertEqual((self.f.out / 'generated-original.xctestrun').read_bytes(), original)
        self.assertEqual(plistlib.loads(generated.read_bytes()), data)
        changes = json.loads((self.f.out / 'config-diff.json').read_text())['target_changes']
        self.assertEqual(changes['MaximumTestExecutionTimeAllowance'], {'before': 180, 'after': 240})
        self.assertEqual(len(self.f.test_processes()), 1)
        self.assertEqual(self.f.test_processes()[0].wait_calls, [211])
        self.assertFalse(meta['retry'])
        self.f.assert_cleanup(meta)

    def test_selected_ax5_config_rejects_ambiguous_ui_target_before_device_or_test(self):
        generated = self.f.dd / 'Build/Products/synthetic.xctestrun'
        data = plistlib.loads(generated.read_bytes())
        targets = data['TestConfigurations'][0]['TestTargets']
        targets.append(dict(targets[1]))
        original = plistlib.dumps(data)
        generated.write_bytes(original)
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'AssertionError')
        self.assertFalse(any(p.step in ('create', 'test') for p in self.f.backend.processes))
        self.assertFalse((self.f.out / 'selected.xctestrun').exists())
        self.assertEqual(generated.read_bytes(), original)

    def test_manual_attempt_identity_paths_and_worker_receipts(self):
        with mock.patch.dict(os.environ, {'GITHUB_RUN_ID': '40631521600', 'GITHUB_RUN_ATTEMPT': '2'}):
            self.assertEqual(self.f.module.hosted_only(), {'run_id': '40631521600', 'run_attempt': '2'})
            self.assertEqual(self.f.module.hosted_paths(), (
                self.f.root / '.qa/privacy-ipad/run-40631521600-attempt-2',
                self.f.root / '.qa/privacy-ipad-build/run-40631521600-attempt-2'))
            rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        self.assertEqual((meta['run_id'], meta['run_attempt']), ('40631521600', '2'))
        self.assertFalse(meta['retry'])
        self.assertEqual(json.loads((self.f.out / 'worker-started.json').read_text()),
                         {'run_id': '40631521600', 'run_attempt': '2'})
        provenance = json.loads((self.f.out / 'source-provenance.json').read_text())
        self.assertEqual((provenance['run_id'], provenance['run_attempt']), ('40631521600', '2'))
        self.assertEqual(len(self.f.test_processes()), 1)
        self.assertEqual(self.f.test_processes()[0].wait_calls, [211])
        self.f.assert_cleanup(meta)

    def test_noncanonical_run_or_attempt_rejected_before_any_process(self):
        for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
            for value in ('', '0', '01', '+2', '-2', ' 2', '2 ', '2\n', '٢'):
                with self.subTest(key=key, value=value), mock.patch.dict(os.environ, {key: value}):
                    with self.assertRaisesRegex(AssertionError, 'canonical positive decimals'):
                        self.f.module.hosted_paths()
        self.assertEqual(self.f.backend.calls, [])

    def test_second_worker_in_attempt_cannot_overwrite_receipts_or_spawn(self):
        rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        before = {p.name: p.read_bytes() for p in self.f.out.iterdir() if p.is_file()}
        calls = list(self.f.backend.calls)
        with self.assertRaises(FileExistsError):
            self.f.module.worker()
        self.assertEqual(self.f.backend.calls, calls)
        self.assertEqual({p.name: p.read_bytes() for p in self.f.out.iterdir() if p.is_file()}, before)
        self.f.assert_cleanup(meta)

    def test_supervisor_rejects_existing_attempt_output_before_spawn(self):
        with mock.patch.object(self.f.module, 'DD', self.f.root / 'unused-derived'):
            with self.assertRaises(FileExistsError):
                self.f.module.supervise()
        self.assertEqual(self.f.backend.calls, [])

    def test_supervisor_rejects_existing_attempt_build_or_inspection_before_spawn(self):
        self.f.module.OUT = self.f.root / 'fresh-attempt'
        with self.assertRaisesRegex(AssertionError, 'build directory already exists'):
            self.f.module.supervise()
        self.f.module.DD = self.f.root / 'unused-derived'
        inspection = self.f.module.OUT.with_name(self.f.module.OUT.name + '-inspection.xcresult')
        inspection.mkdir()
        with self.assertRaisesRegex(AssertionError, 'inspection evidence already exists'):
            self.f.module.supervise()
        self.assertFalse(self.f.module.OUT.exists())
        self.assertEqual(self.f.backend.calls, [])

    def test_import_is_inert(self):
        self.assertEqual(self.f.import_calls, [])
        self.assertEqual(self.f.backend.calls, [])
        self.assertEqual(self.f.backend.signals, [])

    def test_xctest_outer_cap_and_remaining_work_clipping(self):
        for elapsed, expected in ((246.0, 300.0), (256.0, 300.0), (256.001, 299.999)):
            with self.subTest(readback_elapsed=elapsed):
                f = Fixture(self)
                f.backend.readback_elapsed = elapsed
                rc, meta = f.run()
                self.assertEqual(rc, 0)
                tests = f.test_processes()
                self.assertEqual(len(tests), 1)
                self.assertAlmostEqual(tests[0].wait_calls[0], expected)
                command = next(c for c in meta['commands'] if 'test-without-building' in c['args'])
                self.assertAlmostEqual(command['timeout_seconds'], expected)
                self.assertLessEqual(elapsed + command['timeout_seconds'], 556)
                self.assertEqual(meta['phase_deadlines_seconds'],
                                 {'work': 560, 'recovery': 582, 'shutdown': 619,
                                  'delete': 638, 'absence': 660, 'evidence': 772})
                self.assertEqual(meta['total_seconds'], 780)
                self.assertFalse(meta['retry'])
                f.assert_cleanup(meta)

    def test_xctest_startup_plus_case_allowance_fits_available_work(self):
        # A scheduling relation only; synthetic completion does not prove real UI success.
        startup, testcase = 85.202, 180.0
        self.f.backend.readback_elapsed = 246.0
        self.f.backend.test_seconds = startup + testcase
        self.assertGreater(startup + testcase, 210)
        rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        self.assertEqual(self.f.test_processes()[0].wait_calls, [300])
        self.assertAlmostEqual(self.f.clock.value, 246.0 + startup + testcase)
        self.assertLess(self.f.clock.value, 560 - 4)
        self.assertEqual(meta['phase_deadlines_seconds']['absence'], 660)
        self.f.assert_cleanup(meta)

    def test_xctest_maximum_timeout_still_reaps_and_preserves_cleanup(self):
        self.f.backend.readback_elapsed = 246.0
        self.f.backend.test_seconds = 300.001
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        tests = self.f.test_processes()
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0].wait_calls, [300])
        self.assertIn((tests[0].pid, signal.SIGTERM), self.f.backend.signals)
        self.assertFalse(tests[0].group_present)
        command = next(c for c in meta['commands'] if 'test-without-building' in c['args'])
        self.assertTrue(command['owned_group_absent'])
        self.assertLess(self.f.clock.value, 560)
        self.assertEqual(meta['phase_deadlines_seconds']['absence'], 660)
        self.assertFalse(meta['retry'])
        self.f.assert_cleanup(meta)

    def test_exact_215_seconds_reaches_one_unchanged_ui_test_and_preserves_result(self):
        rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        self.assertEqual(meta['result'], 'passed_pending_independent_review')
        self.assertEqual(meta['counts'], {'passedTests': 1, 'failedTests': 0, 'skippedTests': 0, 'totalTestCount': 1})
        tests = self.f.test_processes()
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0].wait_calls, [211])
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
        self.assert_failed(meta, 'No minimum runtime/cleanup budget')
        self.assertEqual(self.f.test_processes(), [])
        self.f.assert_cleanup(meta)

    def test_exact_ax5_admission_allows_full_commands_and_test(self):
        self.f.backend.bootstatus_elapsed = 217.0  # 343s remain in unchanged WORK_END.
        self.f.backend.set_ax5_seconds = 60.0
        self.f.backend.readback_seconds = 60.0
        self.f.backend.readback_elapsed = None  # Advance the injected clock for both full allowances.
        rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        commands = [p for p in self.f.backend.processes if p.step in ('set_ax5', 'readback', 'test')]
        self.assertEqual([p.step for p in commands], ['set_ax5', 'readback', 'test'])
        self.assertEqual([p.wait_calls for p in commands], [[60], [60], [219]])
        self.assertIn('-only-testing:CleanSendUITests/' + CASE, commands[-1].args)
        self.assertEqual(meta['actual_system_content_size'], self.f.module.AX5)
        self.f.assert_cleanup(meta)

    def test_no_ax5_allowance_beyond_reserve_denies_both_commands_and_test(self):
        self.f.backend.bootstatus_elapsed = 341.0  # 215s test reserve plus4s stop; no positive command budget.
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'No phase budget before set-ax5.log')
        self.assertFalse(any(p.step in ('set_ax5', 'readback', 'test') for p in self.f.backend.processes))
        self.f.assert_cleanup(meta)

    def test_cold_startup_admits_short_commands_rejected_by_old_sum(self):
        self.f.backend.bootstatus_elapsed = 224.0
        self.assertLess(560 - 224, 60 + 60 + 8 + 215)
        self.f.backend.set_ax5_seconds = 5.0
        self.f.backend.readback_seconds = 5.0
        self.f.backend.readback_elapsed = None
        rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        commands = [p for p in self.f.backend.processes if p.step in ('set_ax5', 'readback', 'test')]
        self.assertEqual([p.wait_calls for p in commands], [[60], [60], [300]])
        self.assertEqual(meta['actual_system_content_size'], self.f.module.AX5)
        self.f.assert_cleanup(meta)

    def test_ax5_caps_clip_to_original_deadline_without_renewal(self):
        self.f.backend.bootstatus_elapsed = 300.0
        self.f.backend.set_ax5_seconds = 20.0
        self.f.backend.readback_seconds = 10.0
        self.f.backend.readback_elapsed = None
        rc, meta = self.f.run()
        self.assertEqual(rc, 0)
        commands = [p for p in self.f.backend.processes if p.step in ('set_ax5', 'readback', 'test')]
        self.assertEqual([p.wait_calls for p in commands], [[41], [21], [226]])
        self.assertEqual(meta['phase_deadlines_seconds']['work'], 560)
        self.assertEqual(meta['phase_deadlines_seconds']['absence'], 660)
        self.assertEqual(meta['total_seconds'], 780)
        self.f.assert_cleanup(meta)

    def test_clipped_ax5_timeout_preserves_stop_and_device_cleanup(self):
        self.f.backend.bootstatus_elapsed = 300.0
        self.f.backend.set_ax5_seconds = 42.0
        self.f.backend.readback_elapsed = None
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        setters = [p for p in self.f.backend.processes if p.step == 'set_ax5']
        self.assertEqual(len(setters), 1)
        self.assertEqual(setters[0].wait_calls, [41])
        record = next(c for c in meta['commands'] if c.get('owned_process_group') == setters[0].pid)
        self.assertTrue(record['owned_group_absent'])
        self.assertFalse(any(p.step in ('readback', 'test') for p in self.f.backend.processes))
        self.f.assert_cleanup(meta)

    def test_ax5_setter_over_60_seconds_stops_without_readback_or_retry(self):
        self.f.backend.set_ax5_seconds = 60.001
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        setters = [p for p in self.f.backend.processes if p.step == 'set_ax5']
        self.assertEqual(len(setters), 1)
        self.assertEqual(setters[0].wait_calls, [60])
        self.assertFalse(any(p.step in ('readback', 'test') for p in self.f.backend.processes))
        record = next(c for c in meta['commands'] if c.get('owned_process_group') == setters[0].pid)
        self.assertTrue(record['interrupted'])
        self.assertTrue(record['owned_group_absent'])
        self.f.assert_cleanup(meta)

    def test_ax5_readback_over_60_seconds_does_not_start_test_or_retry(self):
        self.f.backend.readback_seconds = 60.001
        self.f.backend.readback_elapsed = None
        rc, meta = self.f.run()
        self.assertEqual(rc, 1)
        self.assert_failed(meta, 'TimeoutExpired')
        readbacks = [p for p in self.f.backend.processes if p.step == 'readback']
        self.assertEqual(len(readbacks), 1)
        self.assertEqual(readbacks[0].wait_calls, [60])
        self.assertEqual(self.f.test_processes(), [])
        self.assertNotIn('actual_system_content_size', meta)
        record = next(c for c in meta['commands'] if c.get('owned_process_group') == readbacks[0].pid)
        self.assertTrue(record['interrupted'])
        self.assertTrue(record['owned_group_absent'])
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
        self.assertEqual(proc.wait_calls, [211])
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


# Frozen pre-Q24 stop policy, AST-extracted only for fully injected call-trace comparison.
BASE_STOP_GROUP_SOURCE = 'def stop_group(proc, record=None):\n    """Require both leader reap and owned-group absence within the 3s reserve."""\n    record = record if record is not None else {}\n    record[\'owned_group_absent\'] = False\n    start = time.monotonic()\n    interrupted = None\n    observation = record.get(\'runtime_observation\')\n    if observation is not None:\n        observation.update(stop_probe_count=0, stop_signals=[])\n\n    def note(error):\n        nonlocal interrupted\n        errors = record.setdefault(\'cleanup_errors\', [])\n        if repr(error) not in errors:\n            errors.append(repr(error))\n        if isinstance(error, InterruptedError) or not isinstance(error, OSError):\n            interrupted = interrupted or error\n\n    def stopped():\n        try:\n            if observation is not None:\n                observation[\'stop_probe_count\'] += 1\n                observation[\'last_stop_probe\'] = {}\n            reaped = proc.poll() is not None\n            if observation is not None:\n                observation[\'last_stop_probe\'][\'leader_reaped\'] = reaped\n            try:\n                os.killpg(proc.pid, 0)\n                if observation is not None:\n                    observation[\'last_stop_probe\'][\'group\'] = \'PRESENT\'\n            except ProcessLookupError:\n                if observation is not None:\n                    observation[\'last_stop_probe\'][\'group\'] = \'ABSENT\'\n                record[\'owned_group_absent\'] = reaped\n                return reaped\n        except BaseException as error:\n            if observation is not None:\n                observation[\'last_stop_probe\'][\'error\'] = type(error).__name__\n            note(error)\n        return False\n\n    def completed():\n        if interrupted is not None:\n            raise interrupted\n\n    if stopped():\n        return completed()\n    for sig, offset in ((signal.SIGTERM, 2), (signal.SIGKILL, 3)):\n        if time.monotonic() >= start + 3:\n            break\n        event = None\n        try:\n            if observation is not None:\n                event = {\'signal\': sig.name}\n                observation[\'stop_signals\'].append(event)  # At most the existing TERM and KILL.\n            os.killpg(proc.pid, sig)\n            if event is not None:\n                event[\'result\'] = \'SENT\'\n        except ProcessLookupError:\n            if event is not None:\n                event[\'result\'] = \'ALREADY_ABSENT\'\n        except BaseException as error:\n            if event is not None:\n                event[\'result\'] = type(error).__name__\n            note(error)\n        deadline = start + offset\n        while True:\n            if stopped():\n                return completed()\n            remaining = deadline - time.monotonic()\n            if remaining <= 0:\n                break\n            try:\n                time.sleep(min(.02, remaining))\n            except BaseException as error:\n                note(error)\n    raise RuntimeError(\'Owned process/group cleanup unconfirmed: \' + repr(record.get(\'cleanup_errors\', [])))'


STOP_OPERATIONS = ('leader_poll', 'group_probe', 'SIGTERM', 'SIGKILL', 'sleep')


class ScriptedStop:
    """A deterministic group model; diagnostic clock reads never advance time."""
    def __init__(self, operation=None, error=None, policy='term'):
        self.operation, self.error, self.policy = operation, error, policy
        self.trace, self.injected = [], False
        self.clock = FakeClock()
        self.absent = policy == 'absent'
        self.proc = SimpleNamespace(pid=7171, poll=self.poll)

    def fault(self, operation):
        if operation == self.operation and not self.injected:
            self.injected = True
            if operation in ('SIGTERM', 'SIGKILL', 'sleep'):
                self.absent = True
            raise self.error

    def poll(self):
        self.trace.append(('poll',))
        self.fault('leader_poll')
        return 0 if self.absent else None

    def killpg(self, pid, sig):
        assert pid == self.proc.pid
        self.trace.append(('killpg', int(sig)))
        if sig == 0:
            self.fault('group_probe')
            if self.absent:
                raise ProcessLookupError(errno.ESRCH, 'injected group absent')
            return
        self.fault(sig.name)
        if (sig == signal.SIGTERM and self.policy == 'term') or (sig == signal.SIGKILL and self.policy == 'kill'):
            self.absent = True

    def sleep(self, seconds):
        self.trace.append(('sleep', seconds))
        self.fault('sleep')
        self.clock.sleep(seconds)


class CleanupObservationTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def stop(self, scenario, record=None, reference=False, clock=None):
        record = {'runtime_observation': {}} if record is None else record
        if reference:
            parsed = ast.parse(BASE_STOP_GROUP_SOURCE)
            self.assertEqual(len(parsed.body), 1)
            self.assertIsInstance(parsed.body[0], ast.FunctionDef)
            namespace = {'time': SimpleNamespace(monotonic=scenario.clock.monotonic, sleep=scenario.sleep),
                         'os': SimpleNamespace(killpg=scenario.killpg), 'signal': signal}
            exec(compile(parsed, '<frozen-base-stop-policy>', 'exec'), namespace)
            target = namespace['stop_group']
        else:
            target = self.f.module.stop_group
        error = None
        with mock.patch.object(self.f.module.os, 'killpg', scenario.killpg), \
             mock.patch.object(self.f.module.time, 'sleep', scenario.sleep), \
             mock.patch.object(self.f.module.time, 'monotonic', clock or scenario.clock.monotonic):
            try:
                target(scenario.proc, record)
            except BaseException as caught:
                error = caught
        return record, error

    def assert_fixed_observation(self, record):
        observation = record['cleanup_observation']
        self.assertEqual(observation['counter_limit'], 65535)
        self.assertEqual(set(observation['error_counts']), set(STOP_OPERATIONS))
        self.assertEqual(set(observation['first_errors']), set(STOP_OPERATIONS))
        self.assertEqual(record['runtime_observation']['stop_probe_count'], observation['probe_count'])
        self.assertEqual(record['runtime_observation']['last_stop_probe'], observation['last_probe'])
        self.assertLessEqual(len(record['runtime_observation']['stop_signals']), 2)
        return observation

    def test_each_operation_retains_first_EPERM_after_final_reaped_absence(self):
        for operation in STOP_OPERATIONS:
            with self.subTest(operation=operation):
                fault = PermissionError(errno.EPERM, 'injected early permission error')
                policy = 'kill' if operation in ('SIGKILL', 'sleep') else 'term'
                scenario = ScriptedStop(operation, fault, policy)
                record, error = self.stop(scenario)
                self.assertIsNone(error)
                self.assertTrue(scenario.injected)
                self.assertTrue(record['owned_group_absent'])
                obs = self.assert_fixed_observation(record)
                self.assertEqual(obs['last_probe'], {'leader_reaped': True, 'group': 'ABSENT'})
                self.assertEqual(obs['error_counts'][operation], 1)
                self.assertEqual(obs['first_errors'][operation], {
                    'operation': operation, 'exception_type': 'PermissionError',
                    'errno': errno.EPERM, 'monotonic': 2.0 if operation == 'SIGKILL' else 0.0})
                self.assertIn(repr(fault), record['cleanup_errors'])
                self.assertEqual(sum(obs['error_counts'].values()), 1)
                self.assertTrue(all(value is None for key, value in obs['first_errors'].items() if key != operation))

    def test_interruption_and_non_os_error_rethrow_original_after_confirmed_absence(self):
        for operation in STOP_OPERATIONS:
            for kind in (InterruptedError, RuntimeError):
                with self.subTest(operation=operation, kind=kind.__name__):
                    fault = kind('injected cancellation')
                    scenario = ScriptedStop(operation, fault, 'kill' if operation in ('SIGKILL', 'sleep') else 'term')
                    record, caught = self.stop(scenario)
                    self.assertIs(caught, fault)
                    self.assertTrue(record['owned_group_absent'])
                    self.assertEqual(record['cleanup_observation']['first_errors'][operation]['exception_type'], kind.__name__)

    def test_diagnostic_clock_failure_does_not_skip_cleanup_or_erase_operation_error(self):
        fault = PermissionError(errno.EPERM, 'group denied before absence')
        clock_fault = InterruptedError('diagnostic timestamp cancelled')
        scenario = ScriptedStop('group_probe', fault)
        triggered = []
        def clock():
            if inspect.currentframe().f_back.f_code.co_name == 'note' and not triggered:
                triggered.append(True)
                raise clock_fault
            return scenario.clock.value
        record, caught = self.stop(scenario, clock=clock)
        self.assertEqual(triggered, [True])
        self.assertIs(caught, clock_fault)
        self.assertTrue(record['owned_group_absent'])
        slot = record['cleanup_observation']['first_errors']['group_probe']
        self.assertIsNone(slot['monotonic'])
        self.assertEqual(slot['exception_type'], 'PermissionError')
        self.assertEqual(slot['errno'], errno.EPERM)
        self.assertEqual(slot['timestamp_error']['exception_type'], 'InterruptedError')
        self.assertIn(repr(fault), record['cleanup_errors'])
        self.assertIn(repr(clock_fault), record['cleanup_errors'])

    def test_later_different_error_does_not_replace_first_operation_slot(self):
        first = PermissionError(errno.EPERM, 'first')
        later = OSError(errno.EIO, 'later')
        scenario = ScriptedStop(policy='persistent')
        count = []
        def group(pid, sig):
            scenario.trace.append(('killpg', int(sig)))
            if sig:
                return
            count.append(True)
            if len(count) == 3:
                scenario.absent = True
                raise ProcessLookupError(errno.ESRCH, 'gone')
            if len(count) > 3:
                raise ProcessLookupError(errno.ESRCH, 'gone')
            raise first if len(count) == 1 else later
        scenario.killpg = group
        record, caught = self.stop(scenario)
        self.assertIsNone(caught)
        self.assertTrue(record['owned_group_absent'])
        self.assertEqual(record['cleanup_observation']['error_counts']['group_probe'], 2)
        self.assertEqual(record['cleanup_observation']['first_errors']['group_probe']['errno'], errno.EPERM)
        self.assertEqual(record['cleanup_errors'], [repr(first), repr(later)])

    def test_new_counters_saturate_and_fixed_storage_remains_bounded(self):
        scenario = ScriptedStop(policy='persistent')
        calls = []
        fault = PermissionError(errno.EPERM, 'same injected group failure')
        def group(pid, sig):
            if sig == 0:
                calls.append(1)
                raise fault
        scenario.killpg = group
        # More than 65,535 synthetic probes within the unchanged 3s deadline.
        scenario.sleep = lambda seconds: setattr(scenario.clock, 'value', scenario.clock.value + 1 / 30000)
        record, caught = self.stop(scenario)
        self.assertIsInstance(caught, RuntimeError)
        self.assertGreater(len(calls), 65535)
        obs = self.assert_fixed_observation(record)
        self.assertEqual(obs['probe_count'], 65535)
        self.assertEqual(obs['error_counts']['group_probe'], 65535)
        self.assertEqual(record['runtime_observation']['stop_probe_count'], 65535)
        self.assertEqual(record['cleanup_errors'], [repr(fault)])
        self.assertLess(len(json.dumps(obs)), 1500)
        self.assertEqual(obs['first_errors']['group_probe']['monotonic'], 0.0)

    def test_new_telemetry_never_adds_poll_signal_or_sleep_against_frozen_base(self):
        scenarios = [(None, 'absent'), (None, 'term'), (None, 'kill'), (None, 'persistent')]
        scenarios += [(operation, 'kill' if operation in ('SIGKILL', 'sleep') else 'term') for operation in STOP_OPERATIONS]
        for operation, policy in scenarios:
            with self.subTest(operation=operation, policy=policy):
                a = ScriptedStop(operation, PermissionError(errno.EPERM, 'fixed'), policy)
                b = ScriptedStop(operation, PermissionError(errno.EPERM, 'fixed'), policy)
                current, current_error = self.stop(a)
                base, base_error = self.stop(b, reference=True)
                self.assertEqual(a.trace, b.trace)
                self.assertEqual(a.clock.value, b.clock.value)
                self.assertEqual(current['owned_group_absent'], base['owned_group_absent'])
                self.assertEqual(type(current_error), type(base_error))
                if current_error:
                    self.assertEqual(str(current_error), str(base_error))
                self.assertTrue(all(e['result'] != 'SENT' for e in current['runtime_observation']['stop_signals']))


class CommandErrorPrecedenceTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def caught(self, fn):
        try:
            fn()
        except BaseException as error:
            return error, traceback.extract_tb(error.__traceback__)
        self.fail('injected command failure must propagate')

    def test_primary_exception_identity_and_traceback_survive_cleanup_and_persist(self):
        for stage in ('timeout', 'cancel', 'spawn', 'body'):
            with self.subTest(stage=stage):
                f = Fixture(self)
                run = f.module.Run()
                primary = subprocess.TimeoutExpired(['synthetic'], 15) if stage == 'timeout' else (
                    InterruptedError('primary cancellation') if stage == 'cancel' else RuntimeError('primary ' + stage))
                cleanup_error, persist_error = RuntimeError('secondary cleanup'), OSError(errno.EIO, 'secondary persist')
                persist_calls, cleanup_calls, primary_tracebacks = [], [], []
                real_popen, real_stop = f.backend.popen, f.module.stop_group
                def raise_primary():
                    try:
                        raise primary
                    except BaseException as error:
                        primary_tracebacks.append(error.__traceback__)
                        raise
                def popen(args, **kwargs):
                    if stage == 'spawn':
                        raise_primary()
                    proc = real_popen(args, **kwargs)
                    if stage in ('timeout', 'cancel'):
                        proc.wait = lambda timeout=None: raise_primary()
                    return proc
                def persist():
                    persist_calls.append(True)
                    if stage == 'body' and len(persist_calls) == 2:
                        raise_primary()
                    if len(persist_calls) == (2 if stage == 'spawn' else 3):
                        raise persist_error
                def cleanup(proc, record):
                    cleanup_calls.append(proc.pid)
                    real_stop(proc, record)
                    raise cleanup_error
                with mock.patch.object(f.module.subprocess, 'Popen', popen), \
                     mock.patch.object(run, 'persist', persist), \
                     mock.patch.object(f.module, 'stop_group', cleanup):
                    caught, frames = self.caught(lambda: run.command(['xcodebuild', '-version'], 'command.log'))
                self.assertIs(caught, primary)
                self.assertIn('raise_primary', [frame.name for frame in frames])
                chain = []
                current = caught.__traceback__
                while current is not None:
                    chain.append(current)
                    current = current.tb_next
                self.assertTrue(any(node is primary_tracebacks[0] for node in chain))
                item = run.meta['commands'][0]
                self.assertEqual(item['command_error_operation'], 'wait' if stage in ('timeout', 'cancel') else stage)
                self.assertEqual(item['secondary_errors']['final_persist']['error'], repr(persist_error))
                if stage == 'spawn':
                    self.assertEqual(cleanup_calls, [])
                    self.assertEqual(f.backend.processes, [])
                else:
                    self.assertEqual(len(cleanup_calls), 1)
                    self.assertTrue(item['owned_group_absent'])
                    self.assertEqual(item['secondary_errors']['cleanup']['error'], repr(cleanup_error))

    def test_timeout_stays_primary_through_wait_and_final_observation_failures(self):
        f = self.f
        run = f.module.Run()
        primary = subprocess.TimeoutExpired(['synthetic'], 60)
        wait_error = InterruptedError('secondary stat cancellation')
        final_error = RuntimeError('secondary final clock')
        original = f.backend.popen
        def popen(args, **kwargs):
            proc = original(args, **kwargs)
            def wait(timeout=None):
                raise primary
            proc.wait = wait
            return proc
        now_calls = []
        def now():
            now_calls.append(True)
            if len(now_calls) > 1:
                raise final_error
            return 'synthetic start'
        with mock.patch.object(f.module.subprocess, 'Popen', popen), \
             mock.patch.object(f.module.os, 'fstat', side_effect=wait_error), \
             mock.patch.object(f.module, 'now', now):
            caught, frames = self.caught(lambda: run.command(['xcrun', 'simctl', 'list', 'runtimes', '--json'], 'runtimes.json', 60))
        self.assertIs(caught, primary)
        self.assertIn('wait', [frame.name for frame in frames])
        item = run.meta['commands'][0]
        self.assertTrue(item['owned_group_absent'])
        self.assertEqual(item['secondary_errors']['wait_observation']['error'], repr(wait_error))
        self.assertEqual(item['secondary_errors']['final_observation']['error'], repr(final_error))

    def test_successful_command_secondary_cleanup_or_persist_still_fails(self):
        for operation in ('cleanup', 'final_persist'):
            with self.subTest(operation=operation):
                f = Fixture(self)
                run = f.module.Run()
                error = OSError(errno.EIO, 'injected ' + operation)
                real_stop = f.module.stop_group
                calls = []
                def stop(proc, item):
                    real_stop(proc, item)
                    if operation == 'cleanup':
                        raise error
                def persist():
                    calls.append(True)
                    if operation == 'final_persist' and len(calls) == 3:
                        raise error
                with mock.patch.object(run, 'persist', persist), mock.patch.object(f.module, 'stop_group', stop):
                    caught, frames = self.caught(lambda: run.command(['xcodebuild', '-version'], 'version.log'))
                self.assertIs(caught, error)
                self.assertEqual(run.meta['commands'][0]['returncode'], 0)
                self.assertEqual(run.meta['commands'][0]['command_error_operation'], operation)
                self.assertTrue(run.meta['commands'][0]['owned_group_absent'])

    def test_nonzero_required_precedes_persist_without_adding_non_xcode_cleanup(self):
        f = self.f
        run = f.module.Run()
        f.backend.fault_step, f.backend.fault = 'macos', 'nonzero'
        calls = []
        def persist():
            calls.append(True)
            if len(calls) == 3:
                raise OSError(errno.EIO, 'late persist')
        with mock.patch.object(run, 'persist', persist), mock.patch.object(f.module, 'stop_group') as cleanup:
            caught, _ = self.caught(lambda: run.command(['sw_vers'], 'macos.log', required=True))
        self.assertIsInstance(caught, RuntimeError)
        self.assertEqual(str(caught), 'macos.log exited 7')
        item = run.meta['commands'][0]
        self.assertEqual(item['command_error_operation'], 'exit_status')
        self.assertEqual(item['secondary_errors']['final_persist']['exception_type'], 'OSError')
        cleanup.assert_not_called()
        self.assertEqual(f.backend.signals, [])

    def test_nonzero_optional_retains_return_value_and_no_extra_cleanup(self):
        self.f.backend.fault_step, self.f.backend.fault = 'macos', 'nonzero'
        run = self.f.module.Run()
        with mock.patch.object(self.f.module, 'stop_group') as cleanup:
            self.assertEqual(run.command(['sw_vers'], 'macos.log', required=False), 7)
        cleanup.assert_not_called()
        self.assertNotIn('command_error', run.meta['commands'][0])
        self.assertEqual(self.f.backend.signals, [])


    def test_returncode_property_failure_still_attempts_owned_cleanup_once(self):
        f = self.f
        run = f.module.Run()
        primary = InterruptedError('returncode observation cancelled')
        real_popen, real_stop = f.backend.popen, f.module.stop_group
        cleanup_calls = []
        class StatusFault:
            def __init__(self, process):
                self.process, self.armed = process, False
                self.pid = process.pid
            def wait(self, timeout=None):
                result = self.process.wait(timeout=timeout)
                self.armed = True
                return result
            @property
            def returncode(self):
                if self.armed:
                    self.armed = False
                    raise primary
                return self.process.returncode
            def poll(self):
                return self.process.poll()
        def popen(args, **kwargs):
            return StatusFault(real_popen(args, **kwargs))
        def stop(proc, item):
            cleanup_calls.append(proc.pid)
            return real_stop(proc, item)
        with mock.patch.object(f.module.subprocess, 'Popen', popen), mock.patch.object(f.module, 'stop_group', stop):
            caught, frames = self.caught(lambda: run.command(['xcodebuild', '-version'], 'version.log'))
        self.assertIs(caught, primary)
        self.assertIn('returncode', [frame.name for frame in frames])
        self.assertEqual(len(cleanup_calls), 1)
        self.assertEqual(len(f.backend.processes), 1)
        self.assertEqual(f.backend.processes[0].wait_calls, [15])
        self.assertTrue(run.meta['commands'][0]['owned_group_absent'])

    def test_post_timeout_metadata_failure_is_secondary_and_does_not_skip_cleanup(self):
        f = self.f
        run = f.module.Run()
        primary = subprocess.TimeoutExpired(['synthetic'], 60)
        metadata_error = RuntimeError('wait-error metadata failed')
        real_popen, real_stop = f.backend.popen, f.module.stop_group
        cleanup_calls, persist_calls, injected = [], [], []
        class Observation(dict):
            def __setitem__(self, key, value):
                if key == 'wait_error' and not injected:
                    injected.append(key)
                    raise metadata_error
                super().__setitem__(key, value)
        def persist():
            persist_calls.append(True)
            if len(persist_calls) == 2:
                item = run.meta['commands'][-1]
                item['runtime_observation'] = Observation(item['runtime_observation'])
        def popen(args, **kwargs):
            proc = real_popen(args, **kwargs)
            def wait(timeout=None):
                raise primary
            proc.wait = wait
            return proc
        def stop(proc, item):
            cleanup_calls.append(proc.pid)
            return real_stop(proc, item)
        with mock.patch.object(f.module.subprocess, 'Popen', popen), \
             mock.patch.object(f.module, 'stop_group', stop), mock.patch.object(run, 'persist', persist):
            caught, frames = self.caught(lambda: run.command(['xcrun', 'simctl', 'list', 'runtimes', '--json'], 'runtimes.json', 60))
        self.assertIs(caught, primary)
        self.assertIn('wait', [frame.name for frame in frames])
        self.assertEqual(injected, ['wait_error'])
        self.assertEqual(len(cleanup_calls), 1)
        item = run.meta['commands'][0]
        self.assertTrue(item['owned_group_absent'])
        self.assertEqual(item['command_error_operation'], 'wait')
        self.assertIn(repr(metadata_error), [e['error'] for e in item['secondary_errors'].values()])


if __name__ == '__main__':
    unittest.main()
