"""Synthetic source/config/file controls only; no native build or simulator."""
import ast
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'scripts/release_smoke'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load('share_diagnostic_controls', HERE / 'diagnostic.py')
W = load('share_diagnostic_window', HERE / 'window.py')


class DiagnosticControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='share-phase-controls-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.event = {'created': True, 'deleted': False, 'forced': False,
                      'before': '0' * 40, 'after': 'a' * 40, 'ref': M.BRANCH}
        self.event_path = self.root / 'event.json'
        self.event_path.write_text(json.dumps(self.event))
        self.env = {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'macOS', 'GITHUB_EVENT_NAME': 'push',
                    'GITHUB_REPOSITORY': M.REPO, 'GITHUB_REF': M.BRANCH,
                    'GITHUB_WORKFLOW_REF': M.REPO + '/' + M.WORKFLOW + '@' + M.BRANCH,
                    'GITHUB_RUN_ATTEMPT': '1', 'EXPECTED_HEAD_SHA': 'a' * 40,
                    'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': str(self.root),
                    'GITHUB_EVENT_PATH': str(self.event_path)}

    def test_only_first_exact_branch_push(self):
        self.assertEqual(M.identity(self.env), {'head': 'a' * 40, 'run': '123', 'attempt': '1'})
        for field, value in (('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_EVENT_NAME', 'pull_request'),
                             ('GITHUB_EVENT_NAME', 'workflow_dispatch'), ('GITHUB_REF', 'refs/heads/main'),
                             ('GITHUB_REPOSITORY', 'other/repo'), ('EXPECTED_HEAD_SHA', 'b' * 40),
                             ('GITHUB_WORKFLOW_REF', 'wrong'), ('GITHUB_RUN_ID', '01')):
            with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                M.identity(self.env | {field: value})
        for field, value in (('created', False), ('deleted', True), ('forced', True),
                             ('before', 'b' * 40), ('after', 'b' * 40), ('ref', 'refs/heads/main')):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                M.identity(self.env, self.event | {field: value})

    def test_build_is_one_release_compile_not_a_publisher(self):
        args = M.build_arguments(self.root / 'build')
        self.assertEqual(args.count('build-for-testing'), 1)
        self.assertEqual(args[args.index('-configuration') + 1], 'Release')
        self.assertIn('ENABLE_TESTABILITY=NO', args)
        self.assertIn('SWIFT_ACTIVE_COMPILATION_CONDITIONS=$(inherited) CLEANSEND_SHARE_TRACE', args)
        self.assertEqual(args[-1], '-only-testing:' + M.CASE)
        self.assertFalse(any('SWIFT_OPTIMIZATION_LEVEL=' in v for v in args))
        self.assertNotIn('test', args)
        self.assertNotIn('archive', args)

    def test_settings_queries_remove_only_test_action_options(self):
        build = M.build_arguments(self.root / 'build')
        for enabled in (False, True):
            settings = M.settings_arguments(self.root / 'build', diagnostic=enabled)
            self.assertNotIn('-testPlan', settings)
            self.assertNotIn('build-for-testing', settings)
            self.assertFalse(any(a.startswith('-only-testing:') for a in settings))
            expected = build[:-2]
            index = expected.index('-testPlan')
            del expected[index:index + 2]
            if not enabled:
                expected = [a for a in expected if not a.startswith('SWIFT_ACTIVE_COMPILATION_CONDITIONS=')]
            self.assertEqual(settings, expected + ['-showBuildSettings', '-json'])
        self.assertEqual(build[build.index('-testPlan') + 1], 'CleanSendPrivacyRelease')

    def metadata_command(self, source, label):
        transport = M.load('transport')
        capture = M.StderrCapture()
        deadline = time.monotonic() + 8
        client = transport.Transport(deadline, str(self.root), M.metadata_ops(transport, capture, lambda: None))
        output = bytearray()
        error = None
        row = {}
        try:
            with client.command('probe', 6, 65536, lambda _: [sys.executable, '-c', source],
                                {'PATH': os.environ.get('PATH', ''), 'HOME': str(self.root)}) as stream:
                while block := stream.read(4096):
                    output.extend(block)
        except BaseException as caught:
            error = caught
        finally:
            M.finish_stderr(capture, self.root / (label + '.log'), row, deadline, primary_failed=error is not None)
        self.assertTrue(client.report['probe']['cleanup_confirmed'])
        return bytes(output), (self.root / (label + '.log')).read_bytes(), row, error

    def test_real_metadata_stderr_never_corrupts_json_or_loses_late_error(self):
        output, errorlog, row, error = self.metadata_command(
            'import os,time;os.write(1,b"{\\"ok\\":true}");os.close(1);time.sleep(.05);os.write(2,b"diagnostic only\\n")', 'success')
        self.assertIsNone(error)
        self.assertEqual(json.loads(output), {'ok': True})
        self.assertEqual(errorlog, b'diagnostic only\n')
        self.assertTrue(row['stderr']['complete'])

    def test_real_metadata_nonzero_retains_stderr_and_original_exit(self):
        output, errorlog, row, error = self.metadata_command(
            'import os;os.write(2,b"The flag -testPlan is only supported when testing.\\n");os._exit(64)', 'failure')
        self.assertIsNotNone(error)
        self.assertEqual(output, b'')
        self.assertIn(b'-testPlan', errorlog)
        self.assertEqual(row['stderr']['process_returncode'], 64)

    def test_real_metadata_stderr_is_capped_and_closed(self):
        _, errorlog, row, error = self.metadata_command(
            'import os,time;os.write(2,b"x"*100000);time.sleep(5)', 'oversize')
        self.assertIsNotNone(error)
        self.assertEqual(len(errorlog), 65536)
        self.assertTrue(row['stderr']['truncated'])

    def test_stderr_drain_without_selector_never_blocks_on_open_writer(self):
        code = '''import os,runpy
Capture=runpy.run_path("scripts/release_smoke/diagnostic.py")["StderrCapture"]
r,w=os.pipe();capture=Capture();capture.stream=os.fdopen(r,"rb",buffering=0)
assert os.get_blocking(r)
try:
 capture.drain()
 assert not os.get_blocking(r) and capture.raw==b"" and not capture.complete
 print("nonblocking")
finally:
 capture.close();os.close(w)
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                check=True, capture_output=True, text=True, timeout=2)
        self.assertEqual(result.stdout.strip(), 'nonblocking')

    def test_stderr_nonblocking_setup_failure_does_not_attempt_read(self):
        r, w = os.pipe()
        capture = M.StderrCapture()
        capture.stream = os.fdopen(r, 'rb', buffering=0)
        try:
            with mock.patch.object(M.os, 'set_blocking', side_effect=OSError('synthetic')), \
                 mock.patch.object(M.os, 'read') as read:
                with self.assertRaises(OSError): capture.drain()
                read.assert_not_called()
        finally:
            capture.close(); os.close(w)

    def test_stderr_recording_failure_cannot_mask_primary(self):
        capture = M.StderrCapture()
        row = {}
        with mock.patch.object(Path, 'open', side_effect=PermissionError('synthetic')):
            M.finish_stderr(capture, self.root / 'error', row, time.monotonic() + 1, primary_failed=True)
        self.assertEqual(row['stderr_error'], 'PermissionError')
        with mock.patch.object(Path, 'open', side_effect=PermissionError('synthetic')):
            with self.assertRaises(PermissionError):
                M.finish_stderr(capture, self.root / 'error', {}, time.monotonic() + 1, primary_failed=False)

    def settings(self):
        base = {'CONFIGURATION': 'Release', 'SWIFT_OPTIMIZATION_LEVEL': '-O', 'ENABLE_TESTABILITY': 'NO',
                'ENABLE_CODE_COVERAGE': 'NO', 'CLANG_COVERAGE_MAPPING': 'NO',
                'SDK_NAME': 'iphonesimulator18.5', 'ARCHS': 'arm64', 'SWIFT_ACTIVE_COMPILATION_CONDITIONS': ''}
        normal = [{'target': name, 'buildSettings': dict(base)} for name in ('CleanSend', 'CleanSendUITests')]
        instrumented = copy.deepcopy(normal)
        for row in instrumented:
            row['buildSettings']['SWIFT_ACTIVE_COMPILATION_CONDITIONS'] = M.FLAG
        return normal, instrumented

    def test_resolved_optimization_and_toolchain_are_unchanged(self):
        normal, instrumented = self.settings()
        self.assertEqual(M.verify_settings(normal, instrumented), ['CleanSend', 'CleanSendUITests'])
        for key, value in (('CONFIGURATION', 'Debug'), ('SWIFT_OPTIMIZATION_LEVEL', '-Onone'),
                           ('ENABLE_TESTABILITY', 'YES'), ('ENABLE_CODE_COVERAGE', 'YES'),
                           ('CLANG_COVERAGE_MAPPING', 'YES'), ('SDK_NAME', 'iphonesimulator19.0'),
                           ('ARCHS', 'x86_64'), ('SWIFT_ACTIVE_COMPILATION_CONDITIONS', M.FLAG + ' DEBUG')):
            changed = copy.deepcopy(instrumented)
            changed[0]['buildSettings'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                M.verify_settings(normal, changed)

    def test_numeric_trace_bounds_and_terminal_semantics(self):
        valid = b'[1,1,100,0]\n[1,2,110,0]\n[1,11,120,7]\n[1,14,130,9]\n'
        self.assertTrue(M.parse_trace(valid)['terminal_observed'])
        self.assertFalse(M.parse_trace(b'[1,1,100,0]\n[1,2,110,0]\n')['terminal_observed'])
        invalid = (b'', b'[1,1,100,0]', b'[1,1,100,"secret"]\n', b'[1,2,100,0]\n',
                   b'[1,1,100,0]\n[1,2,99,0]\n', b'[1,1,100,0]\n[1,1,101,0]\n',
                   b'[1,1,100,0]\n[1,12,110,0]\n[1,2,120,0]\n', b'[1,1,100,1]\n',
                   b'[1,1,true,0]\n', b'[1,1,18446744073709551616,0]\n',
                   b'[1,1,100,0]\n' + b'[1,11,101,0]\n' * 128)
        for raw in invalid:
            with self.subTest(raw=raw[:64]), self.assertRaises((AssertionError, ValueError)):
                M.parse_trace(raw)

    def data(self):
        data = self.root / 'data'
        (data / 'Library/Caches').mkdir(parents=True)
        return data

    def test_trace_capture_missing_partial_and_complete(self):
        data = self.data()
        self.assertIsNone(M.trace_read(data, W, lambda: None, absent=True))
        self.assertEqual(M.capture(data, self.root / 'out', W, lambda: None), {'status': 'unavailable'})
        path = data / 'Library/Caches' / M.TRACE
        raw = b'[1,1,10,0]\n[1,2,20,0]\n'
        path.write_bytes(raw)
        with self.assertRaises(AssertionError):
            M.trace_read(data, W, lambda: None, absent=True)
        receipt = M.capture(data, self.root / 'partial', W, lambda: None)
        self.assertEqual(receipt['status'], 'partial')
        self.assertEqual((self.root / 'partial').read_bytes(), raw)
        path.write_bytes(raw + b'[1,12,30,0]\n')
        self.assertEqual(M.capture(data, self.root / 'complete', W, lambda: None)['status'], 'captured')
        with self.assertRaises(FileExistsError):
            M.capture(data, self.root / 'complete', W, lambda: None)

    def test_trace_symlink_oversize_changed_and_nonregular_refused(self):
        data = self.data()
        path = data / 'Library/Caches' / M.TRACE
        outside = self.root / 'outside'
        outside.write_bytes(b'[1,1,10,0]\n')
        path.symlink_to(outside)
        with self.assertRaises(OSError): M.trace_read(data, W, lambda: None)
        path.unlink()
        path.write_bytes(b'x' * 16385)
        with self.assertRaises(AssertionError): M.trace_read(data, W, lambda: None)
        path.unlink(); path.mkdir()
        with self.assertRaises(AssertionError): M.trace_read(data, W, lambda: None)
        path.rmdir(); path.write_bytes(outside.read_bytes())
        count = [0]
        def mutate():
            count[0] += 1
            if count[0] == 2:
                path.write_bytes(b'[1,1,20,0]\n')
        with self.assertRaises(AssertionError): M.trace_read(data, W, mutate)

    def test_runtime_opt_in_changes_only_runner_environment(self):
        tests = load('phase_existing_smoke_fixtures', ROOT / 'scripts/test_release_smoke.py')
        fixture = tests.HostedPreparationTests('test_real_preparation_and_rebound_config')
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        app, dev = fixture.configured_fixture()
        values = []
        for flag in (False, True):
            out = fixture.root / ('trace' if flag else 'normal')
            fixture.config.prepare(app, dev, out, fixture.scope / 'runner-binding.json',
                                   fixture.scope / 'privacy-inputs/generated-original.xctestrun',
                                   fixture.head, fixture.tree, phase_trace=flag)
            values.append(plistlib.loads((out / 'exact-package-share.xctestrun').read_bytes()))
        target = values[1]['TestConfigurations'][0]['TestTargets'][0]
        self.assertEqual(target['EnvironmentVariables'].pop(M.FLAG), '1')
        # Output-local derived-data placeholders are the only expected path delta.
        normal = plistlib.dumps(values[0]).replace(str(fixture.root / 'normal').encode(), b'OUTPUT')
        trace = plistlib.dumps(values[1]).replace(str(fixture.root / 'trace').encode(), b'OUTPUT')
        self.assertEqual(normal, trace)

    def test_capture_failure_does_not_replace_original_verdict(self):
        tree = ast.parse((HERE / 'run.py').read_text())
        worker = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'worker')
        node = next(n for n in ast.walk(worker) if isinstance(n, ast.If)
                    and ast.unparse(n.test) == 'phase_trace and observation_roots is not None')
        code = compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(HERE / 'run.py'), 'exec')
        for enabled, result in ((True, {'status': 'captured'}), (True, {'status': 'unavailable'}),
                                (True, ValueError('synthetic invalid trace')), (False, None)):
            capture = mock.Mock(side_effect=result if isinstance(result, Exception) else None,
                                return_value=result)
            failures = ['original ten-second assertion']
            run = SimpleNamespace(meta={})
            state = {'phase_trace': enabled, 'observation_roots': {}, 'resources': SimpleNamespace(check=lambda *_: None, device=None),
                     'data': None, 'group': None, 'uid': None, 'b': None, 'l': SimpleNamespace(RECOVERY_END=702),
                     'run': run, 'SCOPE': self.root, 'load': lambda _: SimpleNamespace(capture=capture),
                     'verify_observation_roots': lambda *a, **kw: None, 'failures': failures}
            exec(code, state)
            self.assertEqual(failures[0], 'original ten-second assertion')
            self.assertEqual(capture.call_count, int(enabled))
            if enabled and (isinstance(result, Exception) or result['status'] == 'unavailable'):
                self.assertEqual(len(failures), 2)

    def test_diagnostic_failed_test_keeps_early_late_attachments_and_failure(self):
        tree = ast.parse((HERE / 'run.py').read_text())
        worker = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'worker')
        block = next(n for n in ast.walk(worker) if isinstance(n, ast.Try)
                     and any(isinstance(c, ast.ExceptHandler) and 'result evidence:' in ast.unparse(c) for c in n.handlers))
        code = compile(ast.fix_missing_locations(ast.Module(body=[block], type_ignores=[])), str(HERE / 'run.py'), 'exec')
        (self.root / 'summary.json').write_text(json.dumps({'passedTests': 0, 'failedTests': 1, 'skippedTests': 0, 'totalTestCount': 1}))
        calls = []
        run = SimpleNamespace(meta={'xcodebuild_returncode': 65}, command=lambda *args: calls.append(args))
        failures = ['original ten-second assertion']
        exec(code, {'phase_trace': True, 'run': run, 'SCOPE': self.root, 'json': json, 'failures': failures})
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[-1][0][:4], ['xcrun', 'xcresulttool', 'export', 'attachments'])
        self.assertEqual(failures[0], 'original ten-second assertion')
        self.assertEqual(len(failures), 2)

    def test_cleanup_requires_owned_scope_and_all_process_proofs(self):
        base = self.root / 'redact-share-phase-123-attempt-1'
        base.mkdir()
        for name in ('build', 'runner', 'release-assets'):
            (base / name).mkdir(); (base / name / 'inert').write_bytes(b'fixture')
        (self.root / 'foreign').mkdir()
        (base / 'context.json').write_text('{}')
        info = base.stat()
        owner = {'mode': M.MODE, 'head': 'a' * 40, 'run': '123', 'attempt': '1', 'device': info.st_dev, 'inode': info.st_ino}
        (base / 'ownership.json').write_text(json.dumps(owner))
        report = {'commands': [{'transport': {'build': {'cleanup_confirmed': False}}}]}
        (base / 'preparation.json').write_text(json.dumps(report))
        with mock.patch.dict(os.environ, self.env):
            with self.assertRaises(AssertionError): M.cleanup()
            self.assertTrue((base / 'build').exists())
            report['commands'][0]['transport']['build']['cleanup_confirmed'] = True
            (base / 'preparation.json').write_text(json.dumps(report))
            M.cleanup()
        self.assertFalse((base / 'build').exists())
        self.assertTrue((self.root / 'foreign').exists())
        self.assertTrue((base / 'context.json').exists())

    def test_workflow_is_isolated_and_upload_has_no_executables(self):
        value = json.loads((ROOT / M.WORKFLOW).read_bytes())
        self.assertEqual(value['on'], {'push': {'branches': [M.BRANCH.removeprefix('refs/heads/')]}})
        self.assertEqual(value['permissions'], {'contents': 'read'})
        job = value['jobs']['diagnostic']
        self.assertEqual(job['if'], 'github.event.created && !github.event.deleted && github.run_attempt == 1')
        self.assertNotIn('secrets', json.dumps(value))
        steps = job['steps']
        self.assertFalse(steps[0]['with']['persist-credentials'])
        self.assertEqual(steps[-2]['if'], 'always()')
        self.assertTrue(steps[-2]['run'].endswith('diagnostic.py cleanup'))
        paths = steps[-1]['with']['path'].splitlines()
        for path in paths:
            self.assertTrue(path.endswith(('.json', '.jsonl', '.txt', '.log', '.png')))
            self.assertNotIn('**', path)
            self.assertNotIn('build/', path)
            self.assertNotIn('extracted', path)
        self.assertEqual(steps[-1]['with']['retention-days'], 7)

    def test_original_ten_second_and_late_observers_remain(self):
        source = (ROOT / 'Tests/UITests/ShareExtensionEntryTests.swift').read_text()
        self.assertIn('app.buttons["Close"].waitForExistence(timeout: 10)', source)
        self.assertIn('share-system-sheet-missing-after-required-wait', source)
        self.assertIn('share-system-sheet-after-failure-observation', source)
        tree = ast.parse((HERE / 'run.py').read_text())
        worker = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'worker')
        text = ast.unparse(worker)
        self.assertIn('sampler.event', text)
        self.assertIn('sampler.assert_workflow()', text)
        self.assertIn("assert run.meta.get('xcodebuild_returncode') == 0", text)
        # Collection is inside the existing finally, before owned-device deletion.
        self.assertLess(text.index("load('diagnostic').capture"), text.index('cleanup_device_commands'))

    def test_real_preparation_and_native_binding_with_inert_compiler(self):
        repo = self.root / 'repo'
        repo.mkdir()
        names = (M.WORKFLOW, 'App/SharePhaseTrace.swift', 'App/Workspace.swift', 'App/ReviewView.swift',
                 'Tests/UITests/ShareExtensionEntryTests.swift', 'scripts/release_smoke/diagnostic.py',
                 'scripts/release_smoke/run.py', 'scripts/release_smoke/config.py', 'CleanSend.xcodeproj/project.pbxproj')
        for name in names:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
        calls = []
        owner = self
        class FakeTransport:
            def __init__(self, *_): self.report = {}
            @contextlib.contextmanager
            def command(self, kind, limit, cap, argv, env):
                args = argv(None)
                calls.append(args)
                self.report[kind] = {'cleanup_confirmed': True, 'exit_code': 0}
                if args[:3] == ['git', 'rev-parse', 'HEAD']:
                    raw = b'a' * 40 + b'\n'
                elif args[:3] == ['git', 'rev-parse', 'HEAD^{tree}']:
                    raw = b'b' * 40 + b'\n'
                elif args[:2] == ['git', 'status']:
                    raw = b''
                elif args[:2] == ['git', 'ls-files']:
                    raw = ('\0'.join(names) + '\0').encode()
                elif args == ['xcodebuild', '-version']:
                    raw = b'Xcode 16.4\nBuild version 16F6\n'
                elif args[0] == 'xcrun':
                    raw = b'18.5\n'
                elif '-showBuildSettings' in args:
                    normal, diagnostic = owner.settings()
                    rows = diagnostic if any(v.startswith('SWIFT_ACTIVE_COMPILATION_CONDITIONS=') for v in args) else normal
                    raw = json.dumps(rows).encode()
                elif 'build-for-testing' in args:
                    products = Path(args[args.index('-derivedDataPath') + 1]) / 'Build/Products'
                    product = products / 'Release-iphonesimulator'
                    app = product / 'CleanSend.app'
                    runner = product / 'CleanSendUITests-Runner.app'
                    (app / 'PlugIns/CleanSendShare.appex').mkdir(parents=True)
                    (runner / 'PlugIns/CleanSendUITests.xctest').mkdir(parents=True)
                    (app / 'CleanSend').write_bytes(M.TRACE.encode())
                    (runner / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'fixture.runner'}))
                    (runner / 'PlugIns/CleanSendUITests.xctest/CleanSendUITests').write_bytes(b'REDACT_SHARE_TRACE_WAIT')
                    (products / 'generated.xctestrun').write_bytes(plistlib.dumps({'fixture': True}))
                    raw = b'inert compiler completed\n'
                elif args[0] == 'codesign':
                    raw = b''
                else:
                    raise AssertionError(args)
                yield io.BytesIO(raw)
        original_load = M.load
        def fake_load(name):
            if name == 'transport':
                return SimpleNamespace(Transport=FakeTransport, Ops=type('Ops', (), {}))
            return original_load(name)
        outputs = self.root / 'outputs'
        with mock.patch.dict(os.environ, self.env | {'GITHUB_OUTPUT': str(outputs)}), \
             mock.patch.object(M, 'ROOT', repo), mock.patch.object(M, 'load', side_effect=fake_load), \
             mock.patch.object(os, 'uname', return_value=SimpleNamespace(machine='arm64')), \
             mock.patch.object(M.shutil, 'disk_usage', return_value=SimpleNamespace(free=64 * 2**30)):
            M.prepare()
        self.assertEqual(sum('build-for-testing' in args for args in calls), 1)
        base = self.root / 'redact-share-phase-123-attempt-1'
        context = base / 'context.json'
        grant = json.loads(context.read_bytes())
        self.assertFalse((base / 'build').exists())
        self.assertFalse(grant['phase_trace']['publishable'])
        self.assertEqual(grant['seconds'], 900)
        native = load('phase_bound_native', HERE / 'run.py')
        env = self.env | {'RELEASE_SMOKE_CONTEXT_SHA': hashlib.sha256(context.read_bytes()).hexdigest()}
        with mock.patch.dict(os.environ, env), mock.patch.object(native, 'ROOT', repo), \
             mock.patch.object(os, 'uname', return_value=SimpleNamespace(machine='arm64')):
            self.assertEqual(native.validate_grant(context), grant)
            # A diagnostic grant cannot be presented by the ordinary PR job.
            with mock.patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'pull_request'}), self.assertRaises(AssertionError):
                native.validate_grant(context)
        native.SCOPE.mkdir()
        expected = json.loads((base / 'release-assets/payload-sha256.json').read_bytes())[native.ZIP.name]
        native.extract_exact(W, original_load('evidence'), SimpleNamespace(check=lambda: None), expected)
        self.assertEqual((native.BUNDLE / 'CleanSend').read_bytes(), M.TRACE.encode())


if __name__ == '__main__':
    unittest.main()
