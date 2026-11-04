"""One opt-in hosted Share phase capture; never a release package producer."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import selectors
import shutil
import stat
import sys
import time
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODE = 'share-phase-trace-v1'
FLAG = 'CLEANSEND_SHARE_TRACE'
BRANCH = 'refs/heads/diagnostics/sanitizer14-share-phase-settings'
WORKFLOW = '.github/workflows/share-phase-diagnostic.yml'
REPO = '4alvit/document-sanitizer-ios'
TRACE = 'cleansend-share-phase-trace-v1.jsonl'
CASE = 'CleanSendUITests/ShareExtensionEntryTests/testPDFReceivedByExtensionThenImported'
BUILD_SECONDS = 420
CAP = 2 * 2**30
FLOOR = 16 * 2**30


def load(name):
    spec = importlib.util.spec_from_file_location('trace_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(environment, event=None):
    assert environment.get('GITHUB_ACTIONS') == 'true'
    assert environment.get('RUNNER_OS') == 'macOS'
    assert environment.get('GITHUB_EVENT_NAME') == 'push'
    assert environment.get('GITHUB_REPOSITORY') == REPO
    assert environment.get('GITHUB_REF') == BRANCH
    assert environment.get('GITHUB_WORKFLOW_REF') == REPO + '/' + WORKFLOW + '@' + BRANCH
    assert environment.get('GITHUB_RUN_ATTEMPT') == '1', 'No diagnostic rerun'
    head = environment.get('EXPECTED_HEAD_SHA', '')
    assert re.fullmatch('[a-f0-9]{40}', head) and head == environment.get('GITHUB_SHA')
    run = environment.get('GITHUB_RUN_ID', '')
    assert re.fullmatch('[1-9][0-9]*', run)
    if event is None:
        event_path = Path(environment['GITHUB_EVENT_PATH'])
        assert event_path.stat().st_size <= 2 * 2**20
        event = json.loads(event_path.read_bytes())
    assert event['created'] is True and event['deleted'] is False and event['forced'] is False
    assert event['before'] == '0' * 40 and event['after'] == head and event['ref'] == BRANCH
    return {'head': head, 'run': run, 'attempt': '1'}


def validate(grant, environment):
    current = identity(environment)
    assert grant['mode'] == MODE and all(grant[k] == v for k, v in current.items())
    trace = grant['phase_trace']
    assert trace == {'condition': FLAG, 'runtime_value': '1', 'publishable': False,
                     'configuration': 'Release', 'optimization': '-O'}
    assert grant['checkout'] == grant['head']
    required = {WORKFLOW, 'App/SharePhaseTrace.swift', 'App/Workspace.swift',
                'App/ReviewView.swift', 'Tests/UITests/ShareExtensionEntryTests.swift',
                'scripts/release_smoke/diagnostic.py', 'scripts/release_smoke/run.py',
                'scripts/release_smoke/config.py', 'CleanSend.xcodeproj/project.pbxproj'}
    assert required <= set(grant['source_files'])


def build_arguments(derived):
    # The ordinary Release project owns optimization/coverage/stripping settings.
    # This single extra condition is the only diagnostic compiler setting.
    return ['xcodebuild', '-project', 'CleanSend.xcodeproj', '-scheme', 'CleanSendPrivacyRelease',
            '-testPlan', 'CleanSendPrivacyRelease', '-configuration', 'Release',
            'ENABLE_TESTABILITY=NO', '-destination', 'generic/platform=iOS Simulator',
            '-derivedDataPath', str(derived), '-jobs', '2', 'ARCHS=arm64', 'ONLY_ACTIVE_ARCH=YES',
            'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-',
            'SWIFT_ACTIVE_COMPILATION_CONDITIONS=$(inherited) ' + FLAG,
            'build-for-testing', '-only-testing:' + CASE]


def settings_arguments(derived, *, diagnostic):
    args = build_arguments(derived)[:-2]
    # Xcode rejects -testPlan unless the action is a test/build-for-testing.
    index = args.index('-testPlan')
    del args[index:index + 2]
    if not diagnostic:
        args = [a for a in args if not a.startswith('SWIFT_ACTIVE_COMPILATION_CONDITIONS=')]
    return [*args, '-showBuildSettings', '-json']


class StderrCapture:
    """Bounded independent metadata diagnostics; never append them to JSON stdout."""
    limit = 65536

    def __init__(self):
        self.stream = None
        self.process = None
        self.raw = bytearray()
        self.complete = False
        self.truncated = False

    def attach(self, process):
        self.process = process
        self.stream = process.stderr

    def drain(self):
        if self.stream is None or self.complete:
            return
        # A spawn/ownership failure can reach finalization before a selector
        # exists. Never assume it has already made this pipe nonblocking.
        os.set_blocking(self.stream.fileno(), False)
        assert not os.get_blocking(self.stream.fileno())
        while True:
            try:
                block = os.read(self.stream.fileno(), min(16384, self.limit - len(self.raw) + 1))
            except BlockingIOError:
                return
            if not block:
                self.complete = True
                return
            remaining = self.limit - len(self.raw)
            self.raw.extend(block[:remaining])
            if len(block) > remaining:
                self.truncated = True
                raise RuntimeError('Metadata stderr exceeded its fixed cap')

    def close(self):
        if self.stream is not None:
            self.stream.close()


def finish_stderr(capture, path, row, deadline, *, primary_failed):
    error = None
    try:
        if not capture.truncated:
            capture.drain()
    except BaseException as caught:
        error = caught
    finally:
        try:
            capture.close()
        except BaseException as caught:
            error = error or caught
    try:
        assert time.monotonic() < deadline
        with path.open('xb') as stream:
            assert stream.write(capture.raw) == len(capture.raw)
        row['stderr'] = {'bytes': len(capture.raw), 'complete': capture.complete,
                         'truncated': capture.truncated,
                         'process_returncode': capture.process.returncode if capture.process else None,
                         'sha256': hashlib.sha256(capture.raw).hexdigest()}
    except BaseException as caught:
        error = error or caught
    if error:
        row['stderr_error'] = type(error).__name__
        if not primary_failed:
            raise error


def metadata_ops(transport, capture, check):
    class CheckedSelector:
        def __init__(self):
            self.inner = selectors.DefaultSelector()
            self.error_fd = capture.stream.fileno()
            os.set_blocking(self.error_fd, False)
            self.inner.register(self.error_fd, selectors.EVENT_READ)

        def register(self, *args):
            return self.inner.register(*args)

        def select(self, timeout=None):
            check()
            events = self.inner.select(min(.05, timeout if timeout is not None else .05))
            if not capture.complete:
                capture.drain()
                if capture.complete:
                    self.inner.unregister(self.error_fd)
            return [(key, mask) for key, mask in events if key.fd != self.error_fd]

        def close(self):
            self.inner.close()

    class Ops(transport.Ops):
        selector = CheckedSelector

        @staticmethod
        def popen(*args, **kwargs):
            import subprocess
            kwargs['stderr'] = subprocess.PIPE
            process = subprocess.Popen(*args, **kwargs)
            capture.attach(process)
            return process

        @staticmethod
        def read(fd, size):
            raw = os.read(fd, size)
            if not raw and not capture.complete:
                # stdout may close first; continue draining stderr under the
                # existing transport deadline instead of accepting an incomplete log.
                capture.drain()
                if not capture.complete:
                    time.sleep(.005)
                    raise BlockingIOError()
            return raw

    return Ops()


def verify_settings(normal, diagnostic):
    """Read actual resolved Release settings before compiling, without overriding them."""
    def targets(rows):
        assert isinstance(rows, list) and rows
        result = {r['target']: r['buildSettings'] for r in rows}
        assert len(result) == len(rows) and 'CleanSend' in result
        return result
    before, after = targets(normal), targets(diagnostic)
    assert before.keys() == after.keys()
    for name in before:
        a, b = before[name], after[name]
        for key in ('CONFIGURATION', 'SWIFT_OPTIMIZATION_LEVEL', 'ENABLE_TESTABILITY',
                    'ENABLE_CODE_COVERAGE', 'CLANG_COVERAGE_MAPPING', 'SDK_NAME', 'ARCHS'):
            assert a.get(key) == b.get(key), 'Diagnostic changed resolved build settings'
        assert b['CONFIGURATION'] == 'Release' and b['SWIFT_OPTIMIZATION_LEVEL'] == '-O'
        assert b['ENABLE_TESTABILITY'] == 'NO' and b['ARCHS'] == 'arm64'
        assert b['SDK_NAME'] == 'iphonesimulator18.5'
        original = a.get('SWIFT_ACTIVE_COMPILATION_CONDITIONS', '').split()
        actual = b.get('SWIFT_ACTIVE_COMPILATION_CONDITIONS', '').split()
        assert FLAG not in original and 'DEBUG' not in original
        assert actual == [*original, FLAG]
    return sorted(before)


def entries(root, check):
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        check()
        before = path.lstat()
        assert stat.S_ISDIR(before.st_mode) or stat.S_ISREG(before.st_mode)
        row = {'mode': f'{stat.S_IMODE(before.st_mode):04o}', 'device': before.st_dev, 'inode': before.st_ino}
        if path.is_dir():
            row['directory'] = True
        else:
            assert before.st_size <= 32 * 2**20
            row.update(bytes=before.st_size, sha256=sha(path))
        after = path.lstat()
        assert (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)
        result[str(path.relative_to(root))] = row
        assert len(result) <= 4000
    return result


def trace_read(data, budget, check, *, absent=False):
    """Only the fixed numeric trace, through no-follow directory descriptors."""
    with budget.directory(data / 'Library/Caches') as directory:
        check()
        try:
            fd = os.open(TRACE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        try:
            assert not absent, 'Trace already existed before the test'
            before = os.fstat(fd)
            assert stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 16384
            raw = os.read(fd, 16385)
            check()
            after = os.fstat(fd)
            token = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
            assert token(before) == token(after) and len(raw) == before.st_size
            assert token(after) == token(os.stat(TRACE, dir_fd=directory, follow_symlinks=False))
            parse_trace(raw)
            return raw
        finally:
            os.close(fd)


def parse_trace(raw):
    assert 0 < len(raw) <= 16384 and raw.endswith(b'\n')
    rows = [json.loads(line) for line in raw.splitlines()]
    assert 1 <= len(rows) <= 128 and rows[0][1] == 1
    previous = 0
    for index, row in enumerate(rows):
        assert isinstance(row, list) and len(row) == 4
        assert all(type(value) is int and 0 <= value <= 2**64 - 1 for value in row)
        assert row[0] == 1 and 1 <= row[1] <= 14 and row[2] >= previous
        assert row[1] in (11, 14) or row[3] == 0
        assert index == 0 or row[1] != 1
        assert row[1] < 12 or index == len(rows) - 1
        previous = row[2]
    return {'events': len(rows), 'terminal_observed': rows[-1][1] in (12, 13, 14),
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def capture(data, destination, budget, check):
    raw = trace_read(data, budget, check)
    if raw is None:
        return {'status': 'unavailable'}
    receipt = parse_trace(raw)
    check()
    with destination.open('xb') as stream:
        assert stream.write(raw) == len(raw)
    receipt['status'] = 'captured' if receipt['terminal_observed'] else 'partial'
    return receipt


def prepare():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    ids = identity(os.environ)
    assert os.uname().machine == 'arm64'
    base = Path(os.environ['RUNNER_TEMP']) / f"redact-share-phase-{ids['run']}-attempt-1"
    assert base.is_absolute() and not base.exists() and not base.is_symlink()
    assert shutil.disk_usage(base.parent).free >= FLOOR + CAP
    base.mkdir(mode=0o700)
    metadata = base.stat()
    (base / 'ownership.json').write_text(json.dumps({'mode': MODE, **ids,
        'device': metadata.st_dev, 'inode': metadata.st_ino}) + '\n')
    start = time.monotonic()
    last = 0
    maximum = 0
    report = {'mode': MODE, **ids, 'publishable': False, 'commands': [], 'status': 'preparing'}
    def check():
        nonlocal last, maximum
        assert time.monotonic() - start < BUILD_SECONDS and shutil.disk_usage(base).free >= FLOOR
        if time.monotonic() - last < 1:
            return
        count = total = 0
        for directory, dirs, files in os.walk(base, followlinks=False):
            for name in ['.', *dirs, *files]:
                try:
                    info = (Path(directory) / name).lstat()
                except FileNotFoundError:
                    continue  # Compiler temporary files may be concurrently removed.
                count += 1
                total += info.st_blocks * 512
                assert count <= 100000 and total <= CAP
                assert time.monotonic() - start < BUILD_SECONDS
        maximum = max(maximum, total)
        last = time.monotonic()
    transport = load('transport')
    class CheckedSelector:
        def __init__(self): self.inner = selectors.DefaultSelector()
        def register(self, *args): return self.inner.register(*args)
        def select(self, timeout=None):
            check()
            return self.inner.select(min(.05, timeout if timeout is not None else .05))
        def close(self): self.inner.close()
    def command(args, name, limit=15, cap=1024 * 1024):
        check()
        class Ops(transport.Ops):
            selector = CheckedSelector
            @staticmethod
            def popen(*args, **kwargs):
                import subprocess
                if name == 'build.log':
                    kwargs['stderr'] = subprocess.STDOUT
                return subprocess.Popen(*args, **kwargs)
        capture = StderrCapture() if name != 'build.log' else None
        ops = metadata_ops(transport, capture, check) if capture else Ops()
        client = transport.Transport(start + BUILD_SECONDS, str(ROOT), ops)
        row = {'args': args, 'transport': client.report}
        report['commands'].append(row)
        environment = load('lifecycle').child_environment(os.environ)
        primary = None
        try:
            with (base / name).open('xb') as output:
                with client.command('build', limit, cap, lambda _: args, environment) as source:
                    while block := source.read(65536):
                        check()
                        assert output.write(block) == len(block)
        except BaseException as error:
            primary = error
            raise
        finally:
            if capture:
                finish_stderr(capture, base / (name + '.stderr.log'), row,
                              start + BUILD_SECONDS, primary_failed=primary is not None)
        check()
        return (base / name).read_bytes() if cap <= 2 * 2**20 else None
    def save(name, value):
        check()
        raw = (json.dumps(value, indent=2) + '\n').encode()
        assert len(raw) <= 2 * 2**20
        with (base / name).open('xb') as stream:
            assert stream.write(raw) == len(raw)
        return hashlib.sha256(raw).hexdigest()
    try:
        checkout = command(['git', 'rev-parse', 'HEAD'], 'checkout.txt').decode().strip()
        assert checkout == ids['head']
        tree = command(['git', 'rev-parse', 'HEAD^{tree}'], 'tree.txt').decode().strip()
        assert not command(['git', 'status', '--porcelain', '--untracked-files=no'], 'status.txt').strip()
        names = command(['git', 'ls-files', '-z'], 'files.txt').decode().split('\0')[:-1]
        assert names and all(not Path(n).is_absolute() and '..' not in Path(n).parts
                             and not (ROOT / n).is_symlink() for n in names)
        sources = {name: sha(ROOT / name) for name in names}
        assert sum((ROOT / name).stat().st_size for name in names) <= 16 * 2**20
        assert command(['xcodebuild', '-version'], 'xcode.txt').decode().strip() == 'Xcode 16.4\nBuild version 16F6'
        assert command(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], 'sdk.txt').strip() == b'18.5'
        args = build_arguments(base / 'build')
        settings_args = settings_arguments(base / 'build', diagnostic=True)
        normal_args = settings_arguments(base / 'build', diagnostic=False)
        normal = json.loads(command(normal_args, 'normal-settings.json', 30, 2 * 2**20))
        diagnostic = json.loads(command(settings_args, 'diagnostic-settings.json', 30, 2 * 2**20))
        report['resolved_settings_targets'] = verify_settings(normal, diagnostic)
        command(args, 'build.log', 300, 32 * 2**20)
        products = base / 'build/Build/Products'
        app = products / 'Release-iphonesimulator/CleanSend.app'
        runner = products / 'Release-iphonesimulator/CleanSendUITests-Runner.app'
        templates = list(products.glob('*.xctestrun'))
        assert len(templates) == 1 and app.is_dir() and runner.is_dir()
        original_runner = str(runner)
        original_app = str(app)
        for bundle in (app, app / 'PlugIns/CleanSendShare.appex', runner):
            command(['codesign', '--verify', '--strict', '--all-architectures', str(bundle)], 'signature-' + bundle.name + '.txt')
        for executable, marker in ((app / 'CleanSend', TRACE.encode()),
                                   (runner / 'PlugIns/CleanSendUITests.xctest/CleanSendUITests', b'REDACT_SHARE_TRACE_WAIT')):
            check()
            assert not executable.is_symlink() and executable.stat().st_size <= 16 * 2**20
            assert marker in executable.read_bytes(), 'Instrumented source was not present in the built product'
        (base / 'runner').mkdir()
        runner.rename(base / 'runner' / runner.name)
        runner = base / 'runner' / runner.name
        (base / 'privacy-inputs').mkdir()
        template = base / 'privacy-inputs/generated-original.xctestrun'
        template.write_bytes(templates[0].read_bytes())
        assets = base / 'release-assets'
        assets.mkdir()
        window, evidence = load('window'), load('evidence')
        inventory = evidence.payload_inventory(app, window, check)
        package = assets / 'RedactLeaf-adhoc-simulator.zip'
        with zipfile.ZipFile(package, 'x', zipfile.ZIP_DEFLATED) as archive:
            for name, row in inventory.items():
                check()
                path = app if name == '.' else app / name
                archive.write(path, 'CleanSend.app' if name == '.' else 'CleanSend.app/' + name)
        assert package.stat().st_size <= 32 * 2**20
        payload_sha = save('release-assets/payload-sha256.json', {package.name: inventory})
        producer = {'host_architecture': 'arm64', **ids, 'tree': tree, 'checkout': checkout,
                    'configuration': 'Release', 'xcode': 'Xcode 16.4\nBuild version 16F6', 'sdk': '18.5'}
        binding = {'producer': producer, 'runner': str(runner), 'runner_entries': entries(runner, check),
                   'runner_source_commit': checkout, 'selected_test_source_path': str(ROOT / 'Tests/UITests/ShareExtensionEntryTests.swift'),
                   'test_source_sha256': sources['Tests/UITests/ShareExtensionEntryTests.swift'],
                   'runner_Info': {k: plistlib.loads((runner / 'Info.plist').read_bytes()).get(k)
                                   for k in ('CFBundleIdentifier', 'MinimumOSVersion', 'DTXcodeBuild')},
                   'original_runner': original_runner, 'original_AUT': original_app, 'template_sha256': sha(template)}
        binding_sha = save('runner-binding.json', binding)
        assert {name: sha(ROOT / name) for name in names} == sources
        # Disposable diagnostic products are never published; retain only the
        # bound ZIP and runner needed by the next same-host native stage.
        shutil.rmtree(base / 'build')
        context = {'mode': MODE, 'host_architecture': 'arm64', 'repository': REPO, **ids,
                   'tree': tree, 'checkout': checkout, 'base': str(base), 'scope': str(base / 'native'),
                   'assets': str(assets), 'runner_binding': str(base / 'runner-binding.json'),
                   'runner_binding_sha256': binding_sha, 'runner_template': str(template),
                   'adhoc_zip_sha256': sha(package), 'adhoc_zip_bytes': package.stat().st_size,
                   'payload_manifest_sha256': payload_sha,
                   'runtime_id': 'com.apple.CoreSimulator.SimRuntime.iOS-18-5',
                   'device_type': 'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M4-16GB',
                   'runtime_version': '18.5', 'xcode_build': '16F6', 'seconds': 900,
                   'owned_cap_bytes': CAP, 'free_floor_bytes': FLOOR, 'get_count': 0,
                   'native_worker_count': 1, 'retry_authorized': False,
                   'pipeline_deadline': time.monotonic() + 1200, 'expires_unix': time.time() + 300,
                   'source_files': sources, 'phase_trace': {'condition': FLAG, 'runtime_value': '1',
                   'publishable': False, 'configuration': 'Release', 'optimization': '-O'}}
        validate(context, os.environ)
        digest = save('context.json', context)
        report.update(status='prepared', maximum_owned_allocation=maximum, context_sha256=digest)
        with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
            output.write(f'context={base / "context.json"}\ncontext_sha256={digest}\nscope={base}\n')
    finally:
        report['elapsed_seconds'] = time.monotonic() - start
        with (base / 'preparation.json').open('x') as stream:
            json.dump(report, stream, indent=2)


def cleanup():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    ids = identity(os.environ)
    base = Path(os.environ['RUNNER_TEMP']) / f"redact-share-phase-{ids['run']}-attempt-1"
    if not base.exists():
        return
    assert not base.is_symlink()
    metadata = base.stat()
    owner = json.loads((base / 'ownership.json').read_bytes())
    assert owner == {'mode': MODE, **ids, 'device': metadata.st_dev, 'inode': metadata.st_ino}
    report = json.loads((base / 'preparation.json').read_bytes())
    assert all(row['transport']['build']['cleanup_confirmed'] is True for row in report['commands'])
    native = base / 'native'
    if native.exists():
        terminal = json.loads((native / 'invocation-final.json').read_bytes())
        assert terminal['owned_group_absent'] is True
        assert terminal['owned_command_groups']['all_absent'] is True
        assert terminal['cleanup_obligation']['absence_verified'] is True
    removed = []
    for relative in ('build', 'runner', 'release-assets', 'native/extracted'):
        path = base / relative
        if path.exists():
            assert not path.is_symlink()
            shutil.rmtree(path)
            removed.append(relative)
    (base / 'payload-cleanup.json').write_text(json.dumps({'mode': MODE, 'removed': removed,
        'instrumented_payloads_published': False}) + '\n')


if __name__ == '__main__':
    assert sys.argv[1:] in ([], ['cleanup'])
    cleanup() if sys.argv[1:] else prepare()
