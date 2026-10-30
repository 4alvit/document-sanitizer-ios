#!/usr/bin/env python3
"""Bounded native child lifecycle shared by this one exact-package smoke."""
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
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.qa/privacy-ipad'
DD = ROOT / '.qa/privacy-ipad-build'
CONFIGURATION = 'Release'
assert CONFIGURATION in ('Debug', 'Release'), 'Unsupported privacy build configuration'
SCHEME = 'CleanSendPrivacyRelease' if CONFIGURATION == 'Release' else 'CleanSend'
TEST_PLAN = SCHEME
TARGET = 'CleanSendUITests'
CASE = 'PrivacySupportUITests/testRussianOfflineInformationAtSystemAX5OnLandscapeIPad'
AX5 = 'accessibility-extra-extra-extra-large'
# Cold hosted AX5 requests can exhaust 30s after bootstatus succeeds.
# Both finite 60s caps must fit before the unchanged runtime/cleanup reservation.
AX5_SET_LIMIT, AX5_READ_LIMIT = 60, 60
# Runner startup and selected-case execution share this finite outer cap.
# Run.command still clips this maximum to remaining work minus its 4s reserve.
XCTEST_COMMAND_LIMIT = 300
TOTAL = 780
WORK_END = 560
RECOVERY_END, SHUTDOWN_END, DELETE_END, CLEANUP_END = 582, 619, 638, 660
NATIVE_CONTEXT_KEYS = ('XPC_SERVICE_NAME', 'XPC_FLAGS', '__CF_USER_TEXT_ENCODING')


def child_environment(parent):
    # Preserve only these parent-provided system values; never synthesize them.
    keys = ('HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'DEVELOPER_DIR') + NATIVE_CONTEXT_KEYS
    return {**{key: parent[key] for key in keys if key in parent}, 'LANG': 'en_US.UTF-8'}


ENV = child_environment(os.environ)


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
                     'phase_deadlines_seconds': {'work': WORK_END, 'recovery': RECOVERY_END,
                         'shutdown': SHUTDOWN_END, 'delete': DELETE_END, 'absence': CLEANUP_END,
                         'evidence': TOTAL - 8},
                     'binary_kind': 'same-run packaged Release AUT and Release UI runner',
                     'build_configuration': CONFIGURATION, 'build_scheme': SCHEME, 'test_plan': TEST_PLAN,
                     'launch_capture': {'enabled': False, 'coverage': 'NOT_COLLECTED',
                         'reason': 'Primary UI acceptance uses test.log and the original result.xcresult, including any Staging files; no log streams are started.'}}

    def remaining(self):
        return self.end - (time.monotonic() - self.start)

    def persist(self):
        assert time.monotonic() < self.start + TOTAL, 'whole deadline before worker metadata write'
        save(OUT / 'metadata.json', self.meta)
        assert time.monotonic() < self.start + TOTAL, 'whole deadline after worker metadata write'

    def command(self, args, name, limit=15, required=True, *, bootstrap_observer=None):
        assert not any(c.get('owned_group_absent') is False for c in self.meta['commands']), 'Prior owned child group unresolved; no additional native child work'
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
                cleanup_required = True  # Exact-package adapter requires every owned group absent, including successful metadata commands.
                try:
                    try:
                        if observe:
                            item['runtime_observation']['spawn_started_monotonic'] = time.monotonic()
                        spawn_time = time.monotonic()
                        allowance = min(limit, self.start + self.end - spawn_time - 4)
                        if allowance <= 0:
                            raise TimeoutError('No phase budget before ' + name)
                        command_end = spawn_time + allowance
                        item.update(timeout_seconds=allowance, command_deadline_monotonic=command_end)
                        child_env = ENV
                        if bootstrap_observer is not None:
                            bootstrap_observer.begin(command_end)
                            child_env = bootstrap_observer.environment(ENV)
                            if time.monotonic() >= command_end:
                                raise TimeoutError('No launch budget after diagnostic setup')
                        proc = subprocess.Popen(item['args'], cwd=ROOT, env=child_env, stdout=log,
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
                                if bootstrap_observer is None:
                                    proc.wait(timeout=allowance)
                                else:
                                    bootstrap_observer.wait(proc, command_end)
                                assert self.remaining() > 0, 'Original phase deadline after command'
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
        return (OUT / name).read_text().strip()


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
