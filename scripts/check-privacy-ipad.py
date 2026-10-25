#!/usr/bin/env python3
"""One hosted-only Russian iPad AX5 SDK/runtime baseline, with cleanup and evidence.

This creates a new Debug simulator AUT. It does not use a local frozen binary,
change product behavior, select native StoreKit tests, or retry a failed run.
"""
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import time
import uuid
import zipfile

from privacy_capture import Capture

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.qa/privacy-ipad'
DD = ROOT / '.qa/privacy-ipad-build'
TARGET = 'CleanSendUITests'
CASE = 'PrivacySupportUITests/testRussianOfflineInformationAtSystemAX5OnLandscapeIPad'
AX5 = 'accessibility-extra-extra-extra-large'
TOTAL = 780
WORK_END = 560
RECOVERY_END, SHUTDOWN_END, DELETE_END, CLEANUP_END = 582, 619, 638, 660
ENV = {k: os.environ[k] for k in ('HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'DEVELOPER_DIR') if k in os.environ}
ENV['LANG'] = 'en_US.UTF-8'


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory(path):
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*')) if p.is_file()}


def hosted_only():
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'This driver must not run locally'
    assert os.environ.get('RUNNER_OS') == 'macOS'
    assert os.environ.get('GITHUB_EVENT_NAME') == 'pull_request'
    assert os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'No replay of this run'


class Run:
    def __init__(self):
        self.start = time.monotonic()
        self.capture = None
        self.end = WORK_END
        self.meta = {'started_at': now(), 'total_seconds': TOTAL, 'commands': [],
                     'native_storekit_tests': 0, 'retry': False, 'result': 'running',
                     'phase_deadlines_seconds': {'work': WORK_END, 'recovery': RECOVERY_END,
                         'shutdown': SHUTDOWN_END, 'delete': DELETE_END, 'absence': CLEANUP_END,
                         'evidence': TOTAL - 8},
                     'binary_kind': 'new hosted Debug simulator build, not local frozen AUT or Release ZIP'}

    def remaining(self):
        return self.end - (time.monotonic() - self.start)

    def persist(self):
        save(OUT / 'metadata.json', self.meta)

    def command(self, args, name, limit=15, required=True):
        allowance = min(limit, self.remaining() - 4)
        if allowance <= 0:
            raise TimeoutError('No phase budget before ' + name)
        item = {'args': list(map(str, args)), 'started_at': now(), 'timeout_seconds': allowance}
        self.meta['commands'].append(item)
        self.persist()
        with (OUT / name).open('wb') as log:
            proc = subprocess.Popen(item['args'], cwd=ROOT, env=ENV, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            item['owned_process_group'] = proc.pid
            self.persist()
            try:
                if self.capture is not None and name == 'test.log':
                    self.capture.wait_for_test(proc, allowance)
                else:
                    proc.wait(timeout=allowance)
            except BaseException:
                item['interrupted'] = True
                stop_group(proc)
                raise
            finally:
                item.update(returncode=proc.returncode, finished_at=now())
                self.persist()
        if required and proc.returncode:
            raise RuntimeError(name + ' exited ' + str(proc.returncode))
        return proc.returncode

    def output(self, args, name, limit=15):
        self.command(args, name, limit)
        return (OUT / name).read_text().strip()


def stop_group(proc):
    for sig, wait in ((signal.SIGTERM, 2), (signal.SIGKILL, 1)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass
    if proc.poll() is None:
        raise RuntimeError('Owned process did not reap')


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
    sources = {name: sha(ROOT / name) for name in files}
    info = {'published_head': head, 'actual_checkout': checkout, 'actual_tree': tree,
            'head_tree': head_tree, 'equal_trees': True, 'source_files': sources,
            'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
            'xcode': run.output(['xcodebuild', '-version'], 'xcode-version.txt'),
            'sdk': run.output(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], 'sdk-version.txt'),
            'macos': run.output(['sw_vers'], 'macos.txt')}
    save(OUT / 'source-provenance.json', info)
    run.meta['simulator_sdk_version'] = info['sdk']
    return sources


def prepare_config(run):
    products = DD / 'Build/Products'
    generated = list(products.glob('*.xctestrun'))
    assert len(generated) == 1
    raw = generated[0].read_bytes()
    (OUT / 'generated-original.xctestrun').write_bytes(raw)
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
                  MaximumTestExecutionTimeAllowance=180, UserAttachmentLifetime='keepAlways',
                  SystemAttachmentLifetime='keepAlways')
    app, runner = Path(target['UITargetAppPath']), Path(target['TestHostPath'])
    assert app.is_dir() and runner.is_dir() and Path(target['TestBundlePath']).is_dir()
    assert app.is_relative_to(products) and runner.is_relative_to(products)
    built_sdk = plistlib.loads((app / 'Info.plist').read_bytes())['DTSDKName']
    assert built_sdk == 'iphonesimulator' + run.meta['simulator_sdk_version'], 'Built AUT SDK must match selected runtime'
    run.meta['built_AUT_sdk'] = built_sdk
    assert target['TestingEnvironmentVariables'] == original['TestingEnvironmentVariables']
    assert any((Path(p) / 'XCTest.framework/XCTest').is_file()
               for p in target['TestingEnvironmentVariables']['DYLD_FRAMEWORK_PATH'].split(':'))
    prepared = resolve(copy.deepcopy(data))
    prepared['TestConfigurations'][0]['TestTargets'] = [target]
    config = OUT / 'selected.xctestrun'
    config.write_bytes(plistlib.dumps(prepared))
    save(OUT / 'config-diff.json', {'original_sha256': sha(OUT / 'generated-original.xctestrun'),
         'selected_sha256': sha(config), 'placeholder_resolution': replacements,
         'selected_target_count': 1, 'selected_identifiers': [CASE],
         'target_changes': {key: {'before': original.get(key), 'after': target.get(key)}
                            for key in set(original) | set(target) if original.get(key) != target.get(key)}})
    payloads = {'AUT': {'path': str(app), 'files': inventory(app)},
                'runner': {'path': str(runner), 'files': inventory(runner)}}
    save(OUT / 'payload-before.json', payloads)
    run.command(['codesign', '--verify', '--strict', '--all-architectures', app], 'aut-signature.log')
    run.command(['codesign', '--verify', '--strict', '--all-architectures', runner], 'runner-signature.log')
    # Preserve the actual new binaries, not just their paths in an ephemeral runner.
    with zipfile.ZipFile(OUT / 'tested-payloads.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for label, value in payloads.items():
            for relative in value['files']:
                assert run.remaining() > 4
                archive.write(Path(value['path']) / relative, label + '/' + relative)
    return config, payloads


def collect(run):
    result = OUT / 'result.xcresult'
    if not result.exists():
        raise RuntimeError('No xcresult produced')
    before = inventory(result)
    inspection = ROOT / '.qa/privacy-ipad-inspection.xcresult'
    shutil.copytree(result, inspection)
    # Decode only a copy; preserve the original complete result in the artifact.
    summary = json.loads(run.output(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary',
                                    '--path', inspection, '--format', 'json'], 'summary.json', 20))
    tests = json.loads(run.output(['xcrun', 'xcresulttool', 'get', 'test-results', 'tests',
                                  '--path', inspection, '--format', 'json'], 'tests.json', 20))
    run.command(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', inspection,
                 '--output-path', OUT / 'attachments'], 'attachments.log', 35)
    assert inventory(result) == before
    save(OUT / 'original-xcresult-files.json', before)

    def cases(value):
        if isinstance(value, dict):
            return ([value] if value.get('nodeType') == 'Test Case' else []) + [n for v in value.values() for n in cases(v)]
        if isinstance(value, list):
            return [n for v in value for n in cases(v)]
        return []

    nodes = cases(tests)
    counts = {k: summary.get(k) for k in ('passedTests', 'failedTests', 'skippedTests', 'totalTestCount')}
    run.meta['counts'] = counts
    save(OUT / 'selected-cases.json', {'expected': CASE, 'observed': nodes})
    assert list(counts.values()) == [1, 0, 0, 1], counts
    assert len(nodes) == 1 and nodes[0]['nodeIdentifier'].removesuffix('()') == CASE
    assert nodes[0]['result'] == 'Passed'


def worker():
    run = Run()
    payloads = sources = None
    failed = []
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError('SIGTERM')))
    try:
        hosted_only()
        sources = provenance(run)
        runtime, device_type = select_device(run)
        run.command(['xcodebuild', '-project', 'CleanSend.xcodeproj', '-scheme', 'CleanSend', '-testPlan', 'CleanSend',
                     '-destination', 'generic/platform=iOS Simulator', '-derivedDataPath', DD, '-jobs', '2',
                     'ARCHS=arm64' if os.uname().machine == 'arm64' else 'ARCHS=x86_64', 'ONLY_ACTIVE_ARCH=YES',
                     'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-', 'build-for-testing',
                     '-only-testing:' + TARGET + '/' + CASE], 'build.log', 300)
        config, payloads = prepare_config(run)
        name = 'RedactLeaf-Privacy-' + str(uuid.uuid4())
        run.meta['owned_device_name'] = name
        run.persist()
        uid = run.output(['xcrun', 'simctl', 'create', name, device_type, runtime], 'create.txt')
        uuid.UUID(uid)
        run.meta['owned_uuid'] = uid
        run.persist()
        run.command(['xcrun', 'simctl', 'boot', uid], 'boot.log', 20)
        run.command(['xcrun', 'simctl', 'bootstatus', uid, '-b'], 'bootstatus.log', 90)
        run.command(['xcrun', 'simctl', 'ui', uid, 'content_size', AX5], 'set-ax5.log')
        readback = run.output(['xcrun', 'simctl', 'ui', uid, 'content_size'], 'ax5-readback.txt')
        assert readback == AX5
        run.meta['actual_system_content_size'] = readback
        run.capture = Capture(root=ROOT, out=OUT, env=ENV, uid=uid,
                              metadata=run.meta, remaining=run.remaining, persist=run.persist)
        run.capture.start()
        run.persist()
        assert run.remaining() >= 225, 'No full capture/test/drain budget left; do not start XCTest'
        run.meta['xcodebuild_returncode'] = run.command(
            ['xcodebuild', 'test-without-building', '-xctestrun', config,
             '-destination', 'platform=iOS Simulator,id=' + uid, '-parallel-testing-enabled', 'NO',
             '-maximum-concurrent-test-simulator-destinations', '1', '-collect-test-diagnostics', 'never',
             '-resultBundlePath', OUT / 'result.xcresult', '-only-testing:' + TARGET + '/' + CASE],
            'test.log', 210, required=False)
    except BaseException as error:
        failed.append(repr(error))
    finally:
        if run.capture is not None:
            try:
                issues = run.capture.finish()
                failed.extend('Capture: ' + item for item in issues)
                run.persist()
            except BaseException as error:
                failed.append('Capture finalization: ' + repr(error))
        # Capture failure must never bypass owned-device cleanup.
        # Separate deadlines preserve deletion/absence time after one 30s shutdown.
        # Cleanup ends by 660s, leaving 112s for evidence (75s commands plus I/O).
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
                if run.capture is not None:
                    run.capture.record['owned_device_cleanup'] = {
                        'commands': cleanup.copy(), 'device_removed': run.meta['device_removed'],
                        'limit': 'Device absence does not independently attest the simulator logger PID.'}
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
                assert {name: sha(ROOT / name) for name in sources} == sources
            if payloads is not None:
                after = {label: {'path': value['path'], 'files': inventory(Path(value['path']))}
                         for label, value in payloads.items()}
                save(OUT / 'payload-after.json', after)
                assert after == payloads
            run.meta['source_and_built_payloads_unchanged'] = sources is not None and payloads is not None
        except BaseException as error:
            failed.append('Integrity: ' + repr(error))
        run.meta.update(result='failed' if failed else 'passed_pending_independent_review', failures=failed,
                        finished_at=now(), elapsed_seconds=time.monotonic() - run.start)
        run.persist()
    return 1 if failed else 0


def stop_recorded_children(worker_pid, metadata, deadline):
    """Last-resort host-group signals; simulator child absence is not implied."""
    active = [c['owned_process_group'] for c in metadata.get('commands', [])
              if 'owned_process_group' in c and 'finished_at' not in c]
    channels = metadata.get('launch_capture', {}).get('channels', [])
    candidates = active[-1:] + [c.get('owned_host_pgid') for c in channels
                               if not c.get('host_group_absent')]
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
    hosted_only()
    OUT.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    record = {'started_at': now(), 'total_budget_seconds': TOTAL, 'result': 'running'}
    save(OUT / 'invocation.json', record)
    proc = None
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError('SIGTERM')))
    try:
        with (OUT / 'driver.log').open('wb') as log:
            proc = subprocess.Popen([sys.executable, __file__, '--worker'], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            record['owned_worker'] = proc.pid
            proc.wait(timeout=TOTAL - 8)
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
        save(OUT / 'invocation.json', record)
    return 0 if record['result'] == 'passed_pending_independent_review' else 1


if __name__ == '__main__':
    raise SystemExit(worker() if sys.argv[1:] == ['--worker'] else supervise())
