#!/usr/bin/env python3
"""One hosted-only Russian iPad AX5 SDK/runtime baseline, with cleanup and evidence.

This creates a new Debug simulator AUT by default, or Release when explicitly
selected by REDACTLEAF_PRIVACY_CONFIGURATION. It does not use a local frozen binary,
change product behavior, select native StoreKit tests, or retry a failed run.
"""
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.qa/privacy-ipad'
DD = ROOT / '.qa/privacy-ipad-build'
CONFIGURATION = os.environ.get('REDACTLEAF_PRIVACY_CONFIGURATION', 'Debug')
assert CONFIGURATION in ('Debug', 'Release'), 'Unsupported privacy build configuration'
SCHEME = 'CleanSendPrivacyRelease' if CONFIGURATION == 'Release' else 'CleanSend'
TEST_PLAN = SCHEME
TARGET = 'CleanSendUITests'
CASE = 'PrivacySupportUITests/testRussianOfflineInformationAtSystemAX5OnLandscapeIPad'
AX5 = 'accessibility-extra-extra-extra-large'
# Cold hosted AX5 requests can exhaust 30s after bootstatus succeeds.
# Each finite 60s cap is clipped to the original work deadline while preserving
# the full 360s XCTest command plus 4s stop reservation.
AX5_SET_LIMIT, AX5_READ_LIMIT = 60, 60
# Reserve launch and result completion around the unchanged240s selected case.
# Planning allowances90+240+30 share one finite command cap, not renewed phases.
# This transfers60s from startup; original work/cleanup/evidence endpoints remain.
# Run.command rechecks the full360+4 admission immediately before spawning.
XCTEST_COMMAND_LIMIT = 360
TOTAL = 960
WORK_END = 740
TEST_ADMISSION = XCTEST_COMMAND_LIMIT + 4
STARTUP_END = WORK_END - TEST_ADMISSION
READINESS_LIMIT = 300
RECOVERY_END, SHUTDOWN_END, DELETE_END, CLEANUP_END = 762, 799, 818, 840
NATIVE_CONTEXT_KEYS = ('XPC_SERVICE_NAME', 'XPC_FLAGS', '__CF_USER_TEXT_ENCODING')


def child_environment(parent):
    # Preserve only these parent-provided system values; never synthesize them.
    keys = ('HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'DEVELOPER_DIR') + NATIVE_CONTEXT_KEYS
    return {**{key: parent[key] for key in keys if key in parent}, 'LANG': 'en_US.UTF-8'}


ENV = child_environment(os.environ)



def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def checked_write(path, raw, check=lambda: None):
    check()
    with Path(path).open('wb') as stream:
        check()
        stream.write(raw)
        check()
        stream.flush()
        check()
    check()


def save(path, value, check=lambda: None):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    check()
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    check()
    checked_write(temp, raw, check)
    check()
    temp.replace(path)
    check()


def sha(path, check=lambda: None):
    digest = hashlib.sha256()
    check()
    with path.open('rb') as stream:
        check()
        while True:
            check()
            block = stream.read(1024 * 1024)
            check()
            if not block:
                break
            digest.update(block)
            check()
    check()
    return digest.hexdigest()


def paths(path, check):
    nodes = []
    check()
    for node in path.rglob('*'):
        check()
        nodes.append(node)
    check()
    result = sorted(nodes)
    check()
    return result


def inventory(path, check=lambda: None):
    result = {}
    for node in paths(path, check):
        check()
        regular = node.is_file()
        check()
        if regular:
            result[str(node.relative_to(path))] = sha(node, check)
    check()
    return result


def payload_modes(path, check=lambda: None):
    result = {}
    for node in [path, *paths(path, check)]:
        check()
        mode = node.lstat().st_mode
        check()
        assert not stat.S_ISLNK(mode) and (stat.S_ISREG(mode) or stat.S_ISDIR(mode))
        result[str(node.relative_to(path))] = {'mode': f'{stat.S_IMODE(mode):04o}',
                                               'directory': stat.S_ISDIR(mode)}
    check()
    return result


def hosted_only():
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'This driver must not run locally'
    assert os.environ.get('RUNNER_OS') == 'macOS'
    assert os.uname().machine == 'arm64', 'reviewed ARM host profile required'
    assert os.environ.get('GITHUB_EVENT_NAME') == 'pull_request'
    identity = {'run_id': os.environ.get('GITHUB_RUN_ID', ''),
                'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT', '')}
    assert all(re.fullmatch(r'[1-9][0-9]*', value) for value in identity.values()), \
        'Run ID and attempt must be canonical positive decimals'
    return identity


def hosted_paths():
    identity = hosted_only()
    key = 'run-' + identity['run_id'] + '-attempt-' + identity['run_attempt']
    return ROOT / '.qa/privacy-ipad' / key, ROOT / '.qa/privacy-ipad-build' / key


def runtime_context():
    """Fixed read-only context; PATH lookups are prospective, not process-image proof."""
    def displayed(value):
        return None if value is None else {'value': value[:4096], 'characters': len(value),
                                          'truncated': len(value) > 4096}

    context = {'started_monotonic': time.monotonic(),
               'child_env': {key: displayed(ENV.get(key)) for key in
                             ('HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'DEVELOPER_DIR', 'LANG')},
               'parent_presence_only': {key: key in os.environ for key in
                                       ('SDKROOT', 'TOOLCHAINS', 'xcrun_log', 'xcrun_verbose',
                                        'xcrun_nocache', 'XPC_SERVICE_NAME', 'XPC_FLAGS',
                                        '__CF_USER_TEXT_ENCODING', 'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH')},
               'native_context': {key: {'parent_present': key in os.environ,
                                        'child_present': key in ENV,
                                        'equal_to_parent': key in ENV and key in os.environ
                                            and ENV[key] == os.environ[key]} for key in NATIVE_CONTEXT_KEYS},
               'lookup_basis': 'child PATH; os.defpath only if PATH is absent', 'tools': {}}
    path = ENV.get('PATH', os.defpath)
    for tool in ('xcrun', 'xcodebuild'):
        if len(path) > 8192 or len(path.split(os.pathsep)) > 64:
            context['tools'][tool] = {'status': 'NOT_READ_PATH_LIMIT'}
            continue
        if any(not os.path.isabs(part) for part in path.split(os.pathsep)):
            context['tools'][tool] = {'status': 'NOT_READ_RELATIVE_OR_EMPTY_PATH'}
            continue
        try:
            found = shutil.which(tool, path=path)
            context['tools'][tool] = {'status': 'FOUND' if found else 'NOT_FOUND',
                                      'path': displayed(found),
                                      'realpath': displayed(os.path.realpath(found)) if found else None}
        except InterruptedError:
            raise
        except OSError as error:
            context['tools'][tool] = {'status': 'UNKNOWN_LOOKUP_ERROR',
                                      'error': type(error).__name__}
    context['finished_monotonic'] = time.monotonic()
    return context


class Run:
    def __init__(self):
        self.start = time.monotonic()
        self.end = WORK_END
        self.meta = {'started_at': now(), 'total_seconds': TOTAL, 'commands': [],
                     'run_id': os.environ.get('GITHUB_RUN_ID'),
                     'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
                     'native_storekit_tests': 0, 'retry': False, 'result': 'running',
                     'phase_deadlines_seconds': {'startup': STARTUP_END, 'work': WORK_END, 'recovery': RECOVERY_END,
                         'shutdown': SHUTDOWN_END, 'delete': DELETE_END, 'absence': CLEANUP_END,
                         'evidence': TOTAL - 8},
                     'binary_kind': f'new hosted {CONFIGURATION} simulator build, not local frozen AUT or Release ZIP',
                     'build_configuration': CONFIGURATION, 'build_scheme': SCHEME, 'test_plan': TEST_PLAN,
                     'launch_capture': {'enabled': False, 'coverage': 'NOT_COLLECTED',
                         'reason': 'Primary UI acceptance uses test.log and the original result.xcresult, including any Staging files; no log streams are started.'}}

    def remaining(self):
        return self.end - (time.monotonic() - self.start)

    def check(self, end=None):
        if time.monotonic() >= self.start + (self.end if end is None else end):
            raise TimeoutError('Original phase deadline')

    def persist(self):
        save(OUT / 'metadata.json', self.meta, lambda: self.check(TOTAL))

    def command(self, args, name, limit=15, required=True):
        command_args = list(map(str, args))
        observe = command_args == ['xcrun', 'simctl', 'list', 'runtimes', '--json']
        if observe and self.remaining() > 4:
            self.meta['runtime_discovery_context'] = runtime_context()
        # Context work consumes the existing phase budget; it never extends the allowance.
        allowance = min(limit, self.remaining() - 4)
        if allowance <= 0:
            raise TimeoutError('No phase budget before ' + name)
        item = {'args': command_args, 'started_at': now(), 'timeout_seconds': allowance}
        if observe:
            item['runtime_observation'] = {'prepared_monotonic': time.monotonic(),
                                           'stdout_stderr': 'same regular file',
                                           'cwd': str(ROOT), 'new_session': True}
        self.meta['commands'].append(item)
        self.persist()
        failure = None

        def secondary(error, operation):
            # Fixed call sites, at most one retained error per stage; no retry or I/O.
            item.setdefault('secondary_errors', {}).setdefault(operation, {
                'operation': operation, 'exception_type': type(error).__name__,
                'errno': getattr(error, 'errno', None), 'error': repr(error)})

        def failed(error, operation):
            nonlocal failure
            if failure is None:
                failure = (error, error.__traceback__)
                item.update(command_error=repr(error), command_error_operation=operation)
            else:
                secondary(error, operation)

        proc = None
        try:
            with (OUT / name).open('wb') as log:
                cleanup_required = item['args'][0] == 'xcodebuild'
                try:
                    try:
                        if observe:
                            item['runtime_observation']['spawn_started_monotonic'] = time.monotonic()
                        spawn_time = time.monotonic()
                        phase_remaining = self.start + self.end - spawn_time
                        allowance = min(limit, phase_remaining - 4)
                        if allowance <= 0:
                            raise TimeoutError('No phase budget before ' + name)
                        if command_args[:2] == ['xcodebuild', 'test-without-building']:
                            assert phase_remaining >= TEST_ADMISSION, 'No full XCTest/stop budget before spawn'
                        command_end = spawn_time + allowance
                        item.update(timeout_seconds=allowance, command_deadline_monotonic=command_end)
                        proc = subprocess.Popen(item['args'], cwd=ROOT, env=ENV, stdout=log,
                                                stderr=subprocess.STDOUT, start_new_session=True)
                    except BaseException as error:
                        failed(error, 'spawn')
                        if observe:
                            item['runtime_observation']['spawn_error'] = type(error).__name__
                            try:
                                item['runtime_observation']['spawn_failed_monotonic'] = time.monotonic()
                            except BaseException as observation_error:
                                failed(observation_error, 'spawn_observation')
                    else:
                        item['owned_process_group'] = proc.pid
                        try:
                            if observe:
                                item['runtime_observation']['spawn_returned_monotonic'] = time.monotonic()
                            self.persist()
                            if observe:
                                item['runtime_observation']['wait_started_monotonic'] = time.monotonic()
                            try:
                                allowance = command_end - time.monotonic()
                                if allowance <= 0:
                                    raise TimeoutError('No phase budget before wait ' + name)
                                item['wait_timeout_seconds'] = allowance
                                proc.wait(timeout=allowance)
                                self.check()
                            except BaseException as error:
                                # Capture before sampling: a later diagnostic cannot replace wait().
                                failed(error, 'wait')
                                cleanup_required = True
                                if observe:
                                    item['runtime_observation']['wait_error'] = type(error).__name__
                            finally:
                                try:
                                    if observe:
                                        item['runtime_observation']['wait_finished_monotonic'] = time.monotonic()
                                        try:
                                            item['runtime_observation']['output_bytes_at_wait_end'] = os.fstat(log.fileno()).st_size
                                        except InterruptedError:
                                            raise
                                        except OSError as error:
                                            item['runtime_observation']['output_size_error'] = type(error).__name__
                                            secondary(error, 'output_size')
                                except BaseException as error:
                                    failed(error, 'wait_observation')
                                    cleanup_required = True
                        except BaseException as error:
                            failed(error, 'body')
                            cleanup_required = True
                        if failure is not None:
                            item['interrupted'] = True
                            if observe:
                                item['runtime_observation']['wait_or_persist_error'] = type(failure[0]).__name__
                        if failure is None and required and proc.returncode:
                            # A known command failure precedes finalization errors. This does not
                            # change the existing cleanup policy for a returned nonzero status.
                            failed(RuntimeError(name + ' exited ' + str(proc.returncode)), 'exit_status')
                except BaseException as error:
                    failed(error, 'body')
                    cleanup_required = True
                finally:
                    try:
                        if proc is not None and cleanup_required:
                            item['owned_group_absent'] = False
                            try:
                                stop_group(proc, item)
                            except BaseException as error:
                                item['cleanup_error'] = repr(error)
                                failed(error, 'cleanup')
                    finally:
                        try:
                            if proc is not None:
                                item['returncode'] = proc.returncode
                            item['finished_at'] = now()
                        except BaseException as error:
                            failed(error, 'final_observation')
                        try:
                            self.persist()
                        except BaseException as error:
                            failed(error, 'final_persist')
        except BaseException as error:
            # Includes log open/close; close must not replace an earlier command failure.
            failed(error, 'log_io')
        if failure is not None:
            error, traceback = failure
            raise error.with_traceback(traceback)
        return proc.returncode

    def output(self, args, name, limit=15):
        self.command(args, name, limit)
        self.check()
        value = (OUT / name).read_text().strip()
        self.check()
        return value


def stop_group(proc, record=None):
    """Require both leader reap and owned-group absence within the 3s reserve."""
    record = record if record is not None else {}
    record['owned_group_absent'] = False
    start = time.monotonic()
    interrupted = None
    observation = record.get('runtime_observation')
    if observation is not None:
        observation.update(stop_probe_count=0, stop_signals=[])
    operations = ('leader_poll', 'group_probe', 'SIGTERM', 'SIGKILL', 'sleep')
    counter_limit = 65535
    cleanup = record['cleanup_observation'] = {
        'counter_limit': counter_limit, 'probe_count': 0,
        'error_counts': dict.fromkeys(operations, 0),
        'first_errors': dict.fromkeys(operations), 'last_probe': {}}

    def note(error, operation):
        nonlocal interrupted
        errors = record.setdefault('cleanup_errors', [])
        if repr(error) not in errors:
            errors.append(repr(error))
        cleanup['error_counts'][operation] = min(counter_limit, cleanup['error_counts'][operation] + 1)
        if isinstance(error, InterruptedError) or not isinstance(error, OSError):
            interrupted = interrupted or error
        if cleanup['first_errors'][operation] is None:
            # Preserve the failure before reading diagnostic time. A clock error must
            # neither skip required cleanup nor replace its original exception.
            slot = {'operation': operation, 'exception_type': type(error).__name__,
                    'errno': getattr(error, 'errno', None), 'monotonic': None}
            cleanup['first_errors'][operation] = slot
            try:
                slot['monotonic'] = time.monotonic()
            except BaseException as clock_error:
                slot['timestamp_error'] = {'exception_type': type(clock_error).__name__,
                    'errno': getattr(clock_error, 'errno', None), 'error': repr(clock_error)}
                if repr(clock_error) not in errors:
                    errors.append(repr(clock_error))
                interrupted = interrupted or clock_error

    def stopped():
        operation = 'leader_poll'
        cleanup['probe_count'] = min(counter_limit, cleanup['probe_count'] + 1)
        last = cleanup['last_probe'] = {}
        if observation is not None:
            observation['stop_probe_count'] = cleanup['probe_count']
            observation['last_stop_probe'] = last
        try:
            reaped = proc.poll() is not None
            last['leader_reaped'] = reaped
            operation = 'group_probe'
            try:
                os.killpg(proc.pid, 0)
                last['group'] = 'PRESENT'
            except ProcessLookupError:
                last['group'] = 'ABSENT'
                record['owned_group_absent'] = reaped
                return reaped
        except BaseException as error:
            last.update(error=type(error).__name__, operation=operation)
            note(error, operation)
        return False

    def completed():
        if interrupted is not None:
            raise interrupted

    if stopped():
        return completed()
    for sig, offset in ((signal.SIGTERM, 2), (signal.SIGKILL, 3)):
        if time.monotonic() >= start + 3:
            break
        event = None
        try:
            if observation is not None:
                event = {'signal': sig.name}
                observation['stop_signals'].append(event)  # At most the existing TERM and KILL.
            os.killpg(proc.pid, sig)
            if event is not None:
                event['result'] = 'SYSCALL_RETURNED'
        except ProcessLookupError:
            if event is not None:
                event['result'] = 'ALREADY_ABSENT'
        except BaseException as error:
            if event is not None:
                event['result'] = type(error).__name__
            note(error, sig.name)
        deadline = start + offset
        while True:
            if stopped():
                return completed()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                time.sleep(min(.02, remaining))
            except BaseException as error:
                note(error, 'sleep')
    raise RuntimeError('Owned process/group cleanup unconfirmed: ' + repr(record.get('cleanup_errors', [])))


def version(text):
    parts = [int(p) for p in text.split('.')]
    assert 1 <= len(parts) <= 3, 'Unsupported version format'
    return tuple((parts + [0, 0, 0])[:3])


def select_device(run):
    runtimes = json.loads(run.output(['xcrun', 'simctl', 'list', 'runtimes', '--json'], 'runtimes.json', 60))['runtimes']
    types = json.loads(run.output(['xcrun', 'simctl', 'list', 'devicetypes', '--json'], 'device-types.json'))['devicetypes']
    sdk = run.meta['simulator_sdk_version']
    matches = [r for r in runtimes if r.get('isAvailable') and '.iOS-' in r['identifier']
               and version(r['version']) == version(sdk)]
    if len(matches) != 1:
        raise RuntimeError('Exactly one installed iOS runtime matching SDK ' + sdk + ' is required; no fallback or download')
    runtime = matches[0]
    assert os.uname().machine in runtime['supportedArchitectures']
    supported = {d['identifier'] for d in runtime['supportedDeviceTypes']}
    for device in sorted(types, key=lambda x: (x['name'].startswith('iPad Pro '),
                         version(x['minRuntimeVersionString']), '(16GB)' in x['name'],
                         x['identifier']), reverse=True):
        if (device.get('productFamily') == 'iPad' and '13-inch' in device['name']
                and device['identifier'] in supported
                and version(device['minRuntimeVersionString']) <= version(runtime['version'])
                <= version(device['maxRuntimeVersionString'])):
            run.meta.update(runtime=runtime, device_type=device,
                            runtime_selection='exact simulator SDK version; installed compatible 13-inch iPad')
            return runtime['identifier'], device['identifier']
    raise RuntimeError('No compatible 13-inch iPad for SDK-matched runtime; no substitute or download')


def provenance(run):
    head = os.environ['EXPECTED_HEAD_SHA']
    checkout = run.output(['git', 'rev-parse', 'HEAD'], 'checkout.txt')
    tree = run.output(['git', 'rev-parse', 'HEAD^{tree}'], 'checkout-tree.txt')
    head_tree = run.output(['git', 'rev-parse', head + '^{tree}'], 'head-tree.txt')
    assert checkout == os.environ['GITHUB_SHA'] and tree == head_tree
    assert not run.output(['git', 'status', '--porcelain', '--untracked-files=no'], 'source-status.txt')
    files = run.output(['git', 'ls-files'], 'source-files.txt').splitlines()
    sources = {name: sha(ROOT / name, run.check) for name in files}
    info = {'published_head': head, 'actual_checkout': checkout, 'actual_tree': tree,
            'head_tree': head_tree, 'equal_trees': True, 'source_files': sources,
            'build_configuration': CONFIGURATION, 'build_scheme': SCHEME, 'test_plan': TEST_PLAN,
            'host_architecture': os.uname().machine,
            'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
            'xcode': run.output(['xcodebuild', '-version'], 'xcode-version.txt'),
            'sdk': run.output(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], 'sdk-version.txt'),
            'macos': run.output(['sw_vers'], 'macos.txt')}
    save(OUT / 'source-provenance.json', info, run.check)
    run.meta['simulator_sdk_version'] = info['sdk']
    run.meta['source_binding'] = {key: info[key] for key in
                                  ('published_head', 'actual_checkout', 'actual_tree', 'head_tree', 'equal_trees')}
    run.meta['source_binding']['driver_sha256'] = sources['scripts/check-privacy-ipad.py']
    return sources


def prepare_config(run):
    run.check()
    products = DD / 'Build/Products'
    generated = list(products.glob('*.xctestrun'))
    run.check()
    assert len(generated) == 1
    raw = generated[0].read_bytes()
    run.check()
    checked_write(OUT / 'generated-original.xctestrun', raw, run.check)
    data = plistlib.loads(raw)
    assert data['__xctestrun_metadata__']['FormatVersion'] == 2
    configs = data['TestConfigurations']
    assert len(configs) == 1 and configs[0].get('IsEnabled', True)
    targets = [t for t in configs[0]['TestTargets'] if t['BlueprintName'] == TARGET]
    assert len(targets) == 1
    target = copy.deepcopy(targets[0])
    assert target['IsUITestBundle'] and target['IsXCTRunnerHostedTestBundle']
    host = target['TestHostPath'].replace('__TESTROOT__', str(products))
    platforms = run.output(['xcode-select', '-p'], 'developer-directory.txt') + '/Platforms'
    replacements = {'__TESTROOT__': str(products), '__TESTHOST__': host,
                    '__PLATFORMS__': platforms, '__DERIVEDDATA__': str(DD)}

    def resolve(value):
        if isinstance(value, str):
            for old, new in replacements.items():
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value

    target = resolve(target)
    original = copy.deepcopy(target)
    target.update(OnlyTestIdentifiers=[CASE], SkipTestIdentifiers=[], TestLanguage='ru', TestRegion='RU',
                  TestTimeoutsEnabled=True, DefaultTestExecutionTimeAllowance=120,
                  MaximumTestExecutionTimeAllowance=240, UserAttachmentLifetime='keepAlways',
                  SystemAttachmentLifetime='keepAlways')
    app, runner = Path(target['UITargetAppPath']), Path(target['TestHostPath'])
    assert app.is_dir() and runner.is_dir() and Path(target['TestBundlePath']).is_dir()
    run.check()
    assert app.is_relative_to(products) and runner.is_relative_to(products)
    if CONFIGURATION == 'Release':
        assert app.parent.name == 'Release-iphonesimulator' and runner.parent == app.parent, \
            'Release AUT and UI runner must come from the selected Release products'
        run.check()
        assert not [node for node in paths(app, run.check) if node.match('*.storekit')], 'Local StoreKit configuration in Release AUT'
        assert not [node for node in paths(app, run.check) if node.match('*.xctest')], 'Hosted unit-test bundle in Release AUT'
        assert not [node for node in paths(app, run.check) if node.match('*.debug.dylib')], 'Debug executable in Release AUT'
        run.meta['release_AUT_path_and_payload_checks'] = 'passed'
    built_sdk = plistlib.loads((app / 'Info.plist').read_bytes())['DTSDKName']
    run.check()
    assert built_sdk == 'iphonesimulator' + run.meta['simulator_sdk_version'], 'Built AUT SDK must match selected runtime'
    run.meta['built_AUT_sdk'] = built_sdk
    assert target['TestingEnvironmentVariables'] == original['TestingEnvironmentVariables']
    assert any((Path(p) / 'XCTest.framework/XCTest').is_file()
               for p in target['TestingEnvironmentVariables']['DYLD_FRAMEWORK_PATH'].split(':'))
    prepared = resolve(copy.deepcopy(data))
    prepared['TestConfigurations'][0]['TestTargets'] = [target]
    config = OUT / 'selected.xctestrun'
    checked_write(config, plistlib.dumps(prepared), run.check)
    save(OUT / 'config-diff.json', {'original_sha256': sha(OUT / 'generated-original.xctestrun', run.check),
         'selected_sha256': sha(config, run.check), 'placeholder_resolution': replacements,
         'selected_target_count': 1, 'selected_identifiers': [CASE],
         'target_changes': {key: {'before': original.get(key), 'after': target.get(key)}
                            for key in set(original) | set(target) if original.get(key) != target.get(key)}}, run.check)
    payloads = {'AUT': {'path': str(app), 'files': inventory(app, run.check)},
                'runner': {'path': str(runner), 'files': inventory(runner, run.check)}}
    save(OUT / 'payload-before.json', payloads, run.check)
    save(OUT / 'payload-node-modes-before.json', {label: payload_modes(Path(value['path']), run.check)
                                               for label, value in payloads.items()}, run.check)
    run.command(['codesign', '--verify', '--strict', '--all-architectures', app], 'aut-signature.log')
    run.command(['codesign', '--verify', '--strict', '--all-architectures', runner], 'runner-signature.log')
    # Preserve the actual new binaries, not just their paths in an ephemeral runner.
    run.check()
    with zipfile.ZipFile(OUT / 'tested-payloads.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        run.check()
        for label, value in payloads.items():
            for relative in value['files']:
                assert run.remaining() > 4
                archive.write(Path(value['path']) / relative, label + '/' + relative)
                run.check()
    run.check()
    return config, payloads


def collect(run):
    # The original bundle, including existing Staging files, remains in OUT
    # and is uploaded even if it is unfinished or cannot be decoded.
    result = OUT / 'result.xcresult'
    if not result.exists():
        raise RuntimeError('No xcresult produced')
    run.check()
    before = inventory(result, run.check)
    inspection = OUT.with_name(OUT.name + '-inspection.xcresult')
    run.check()
    shutil.copytree(result, inspection)
    run.check()
    # Decode only a copy; preserve the original complete result in the artifact.
    summary = json.loads(run.output(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary',
                                    '--path', inspection, '--format', 'json'], 'summary.json', 20))
    tests = json.loads(run.output(['xcrun', 'xcresulttool', 'get', 'test-results', 'tests',
                                  '--path', inspection, '--format', 'json'], 'tests.json', 20))
    run.command(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', inspection,
                 '--output-path', OUT / 'attachments'], 'attachments.log', 35)
    assert inventory(result, run.check) == before
    save(OUT / 'original-xcresult-files.json', before, run.check)

    def cases(value):
        if isinstance(value, dict):
            return ([value] if value.get('nodeType') == 'Test Case' else []) + [n for v in value.values() for n in cases(v)]
        if isinstance(value, list):
            return [n for v in value for n in cases(v)]
        return []

    nodes = cases(tests)
    counts = {k: summary.get(k) for k in ('passedTests', 'failedTests', 'skippedTests', 'totalTestCount')}
    run.meta['counts'] = counts
    save(OUT / 'selected-cases.json', {'expected': CASE, 'observed': nodes}, run.check)
    assert list(counts.values()) == [1, 0, 0, 1], counts
    assert len(nodes) == 1 and nodes[0]['nodeIdentifier'].removesuffix('()') == CASE
    assert nodes[0]['result'] == 'Passed'


def configure_system_ax5(run, uid):
    # The phase end is absolute relative to the existing run.start. The second
    # command recalculates remaining time after the first; no budget is renewed.
    previous_end = run.end
    assert previous_end == STARTUP_END
    run.end = min(previous_end, STARTUP_END)
    try:
        run.command(['xcrun', 'simctl', 'ui', uid, 'content_size', AX5], 'set-ax5.log', AX5_SET_LIMIT)
        return run.output(['xcrun', 'simctl', 'ui', uid, 'content_size'], 'ax5-readback.txt', AX5_READ_LIMIT)
    finally:
        run.end = previous_end


def worker():
    identity = hosted_only()
    # The supervisor creates a fresh attempt scope. Never run a second worker in it.
    with (OUT / 'worker-started.json').open('x') as claim:
        json.dump(identity, claim)
        claim.write('\n')
    run = Run()
    run.end = STARTUP_END
    payloads = sources = None
    failed = []
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError('SIGTERM')))
    try:
        hosted_only()
        sources = provenance(run)
        run.command(['xcodebuild', '-project', 'CleanSend.xcodeproj', '-scheme', SCHEME, '-testPlan', TEST_PLAN,
                     *(['-configuration', 'Release', 'ENABLE_TESTABILITY=NO'] if CONFIGURATION == 'Release' else []),
                     '-destination', 'generic/platform=iOS Simulator', '-derivedDataPath', DD, '-jobs', '2',
                     'ARCHS=arm64', 'ONLY_ACTIVE_ARCH=YES',
                     'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-', 'build-for-testing',
                     '-only-testing:' + TARGET + '/' + CASE], 'build.log', 300)
        runtime, device_type = select_device(run)
        # Generic build precedes the one runtime query. Owned boot can progress
        # during configuration, signatures and payload binding; no second child.
        name = 'RedactLeaf-Privacy-' + str(uuid.uuid4())
        run.meta['owned_device_name'] = name
        run.persist()
        uid = run.output(['xcrun', 'simctl', 'create', name, device_type, runtime], 'create.txt')
        uuid.UUID(uid)
        run.meta['owned_uuid'] = uid
        run.persist()
        run.command(['xcrun', 'simctl', 'boot', uid], 'boot.log', 20)
        config, payloads = prepare_config(run)
        run.check()
        run.command(['xcrun', 'simctl', 'bootstatus', uid, '-b'], 'bootstatus.log', READINESS_LIMIT)
        readback = configure_system_ax5(run, uid)
        assert readback == AX5
        run.meta['actual_system_content_size'] = readback
        run.persist()
        run.check()
        run.end = WORK_END
        assert run.remaining() >= TEST_ADMISSION, 'No full XCTest/stop budget left; do not start XCTest'
        run.meta['xcodebuild_returncode'] = run.command(
            ['xcodebuild', 'test-without-building', '-xctestrun', config,
             '-destination', 'platform=iOS Simulator,id=' + uid, '-parallel-testing-enabled', 'NO',
             '-maximum-concurrent-test-simulator-destinations', '1', '-collect-test-diagnostics', 'never',
             '-resultBundlePath', OUT / 'result.xcresult', '-only-testing:' + TARGET + '/' + CASE],
            'test.log', XCTEST_COMMAND_LIMIT, required=False)
    except BaseException as error:
        failed.append(repr(error))
    finally:
        # Separate deadlines preserve deletion/absence time after one 30s shutdown.
        # Cleanup ends by 840s, leaving 112s for evidence (75s commands plus I/O).
        run.end = RECOVERY_END
        uid = run.meta.get('owned_uuid')
        if not uid and run.meta.get('owned_device_name'):
            try:
                devices = json.loads(run.output(['xcrun', 'simctl', 'list', 'devices', '--json'], 'create-recovery.json'))['devices']
                matches = [d['udid'] for group in devices.values() for d in group if d['name'] == run.meta['owned_device_name']]
                assert len(matches) <= 1
                uid = matches[0] if matches else None
                run.meta['owned_uuid'] = uid
            except BaseException as error:
                failed.append('Device recovery: ' + repr(error))
        if uid:
            cleanup = {}
            for action, limit, deadline in (('shutdown', 30, SHUTDOWN_END), ('delete', 12, DELETE_END)):
                run.end = deadline
                try:
                    cleanup[action] = run.command(['xcrun', 'simctl', action, uid], 'cleanup-' + action + '.log', limit, required=False)
                except BaseException as error:
                    cleanup[action] = repr(error)
            run.meta['cleanup'] = cleanup
            run.end = CLEANUP_END
            try:
                devices = json.loads(run.output(['xcrun', 'simctl', 'list', 'devices', '--json'], 'devices-after.json'))['devices']
                run.meta['device_removed'] = not any(d['udid'] == uid for group in devices.values() for d in group)
                assert cleanup == {'shutdown': 0, 'delete': 0} and run.meta['device_removed']
            except BaseException as error:
                failed.append('Cleanup: ' + repr(error))
        run.end = TOTAL - 8
        try:
            collect(run)
            assert run.meta.get('xcodebuild_returncode') == 0
            assert run.meta.get('device_removed') is True
        except BaseException as error:
            failed.append('Result acceptance: ' + repr(error))
        try:
            if sources is not None:
                assert {name: sha(ROOT / name, run.check) for name in sources} == sources
            if payloads is not None:
                after = {label: {'path': value['path'], 'files': inventory(Path(value['path']), run.check)}
                         for label, value in payloads.items()}
                save(OUT / 'payload-after.json', after, run.check)
                assert after == payloads
                modes = {label: payload_modes(Path(value['path']), run.check) for label, value in payloads.items()}
                save(OUT / 'payload-node-modes-after.json', modes, run.check)
                run.check()
                before_modes = json.loads((OUT / 'payload-node-modes-before.json').read_text())
                run.check()
                assert modes == before_modes
            run.meta['source_and_built_payloads_unchanged'] = sources is not None and payloads is not None
        except BaseException as error:
            failed.append('Integrity: ' + repr(error))
        run.meta.update(result='failed' if failed else 'passed_pending_independent_review', failures=failed,
                        finished_at=now(), elapsed_seconds=time.monotonic() - run.start)
        run.persist()
    return 1 if failed else 0


def stop_recorded_children(worker_pid, metadata, deadline):
    """Last-resort active command signal; group absence is not implied."""
    active = [c['owned_process_group'] for c in metadata.get('commands', [])
              if 'owned_process_group' in c and
              ('finished_at' not in c or c.get('owned_group_absent') is False)]
    candidates = active[-1:]
    outcomes = []
    for pid in dict.fromkeys(p for p in candidates if type(p) is int and p > 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            outcomes.append({'pid': pid, 'status': 'deadline_no_signal'})
            break
        try:
            parent = subprocess.check_output(['ps', '-p', str(pid), '-o', 'ppid='],
                                             text=True, timeout=min(1, remaining)).strip()
            if time.monotonic() >= deadline:
                status = 'deadline_no_signal'
            elif parent == str(worker_pid) and os.getpgid(pid) == pid:
                if time.monotonic() >= deadline:
                    status = 'deadline_no_signal'
                else:
                    os.killpg(pid, signal.SIGKILL)
                    status = 'signal_sent_absence_not_established'
            else:
                status = 'identity_mismatch_no_signal'
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            status = 'identity_or_signal_unavailable:' + type(error).__name__
        outcomes.append({'pid': pid, 'status': status})
    return outcomes


def supervise():
    identity = hosted_only()
    assert not os.path.lexists(DD), 'Attempt build directory already exists; no reuse'
    assert not os.path.lexists(OUT.with_name(OUT.name + '-inspection.xcresult')), \
        'Attempt inspection evidence already exists; no reuse'
    OUT.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    record = {'started_at': now(), 'total_budget_seconds': TOTAL, 'result': 'running', **identity}
    def remaining(end=TOTAL - 8):
        value = start + end - time.monotonic()
        if value <= 0:
            raise TimeoutError('Original supervisor deadline')
        return value
    save(OUT / 'invocation.json', record, remaining)
    proc = None
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError('SIGTERM')))
    try:
        with (OUT / 'driver.log').open('wb') as log:
            remaining()
            proc = subprocess.Popen([sys.executable, __file__, '--worker'], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            record['owned_worker'] = proc.pid
            proc.wait(timeout=remaining())
            assert proc.returncode == 0, 'Worker failed; no retry'
        record['result'] = 'passed_pending_independent_review'
    except BaseException as error:
        record.update(result='failed', error=repr(error))
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    meta = json.loads((OUT / 'metadata.json').read_text())
                    record['recorded_child_termination'] = stop_recorded_children(
                        proc.pid, meta, min(start + TOTAL - 2, time.monotonic() + 3))
                except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                    record['active_command_identity_unavailable'] = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=1)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    record['worker_reap_unconfirmed'] = True
        record.update(finished_at=now(), elapsed_seconds=time.monotonic() - start,
                      worker_returncode=proc.returncode if proc else None)
        if record['elapsed_seconds'] >= TOTAL:
            record['result'] = 'failed'
        if time.monotonic() < start + TOTAL:
            try:
                save(OUT / 'invocation.json', record, lambda: remaining(TOTAL))
            except TimeoutError:
                record['result'] = 'failed'
    return 0 if record['result'] == 'passed_pending_independent_review' else 1


if __name__ == '__main__':
    OUT, DD = hosted_paths()
    raise SystemExit(worker() if sys.argv[1:] == ['--worker'] else supervise())
