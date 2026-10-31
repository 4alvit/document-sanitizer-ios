"""Bounded, best-effort log delivery for one owned iPad XCTest attempt.

No native work occurs on import. NativeIO is used only by the proposed driver.
The JSON validator is conservative, not a claim about a stable Apple schema.
"""
from collections import deque
import codecs
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time


CHANNEL_CAP = 8 * 1024 * 1024
STAGING_CAP = 4 * 1024 * 1024
CHUNK = 64 * 1024
HOST_PROCESSES = ('CoreSimulatorService', 'SimulatorTrampoline', 'xcodebuild', 'debugserver')
DEVICE_PROCESSES = ('launchd', 'runningboardd', 'SpringBoard', 'testmanagerd',
                    'debugserver', 'CleanSendUITests-Runner')
RUNNER = 'CleanSendUITests-Runner'
BUNDLE = 'io.github.4alvit.cleansend.uitests.xctrunner'


class NativeIO:
    """Small injectable boundary; tests replace every process/clock operation."""
    clock = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)

    def start(self, argv, cwd, env):
        return subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)

    def prepare(self, proc):
        os.set_blocking(proc.stdout.fileno(), False)

    def read(self, proc):
        try:
            return os.read(proc.stdout.fileno(), CHUNK)
        except BlockingIOError:
            return None

    def signal_group(self, proc, sig):
        os.killpg(proc.pid, sig)

    def group_exists(self, proc):
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            return False
        return True  # PermissionError propagates: absence is not established.

    def close(self, proc):
        proc.stdout.close()


class Window:
    """Fixed byte budget: early bytes plus a bounded tail, with explicit gaps."""
    def __init__(self, limit):
        self.limit = limit
        self.head_limit = min(128 * 1024, limit // 4)
        self.head = bytearray()
        self.tail = deque()
        self.tail_size = 0
        self.total = 0

    def add(self, data):
        self.total += len(data)
        n = min(len(data), self.head_limit - len(self.head))
        self.head.extend(data[:n])
        data = data[n:]
        if data:
            self.tail.append(data)
            self.tail_size += len(data)
        excess = self.tail_size - (self.limit - self.head_limit)
        while excess > 0:
            first = self.tail.popleft()
            drop = min(excess, len(first))
            if drop < len(first):
                self.tail.appendleft(first[drop:])
            self.tail_size -= drop
            excess -= drop

    @property
    def dropped(self):
        return self.total - len(self.head) - self.tail_size

    def segments(self):
        return [('head', 0, [bytes(self.head)]),
                ('tail', self.total - self.tail_size, list(self.tail))]


class JsonObjects:
    """Accept bounded JSON objects with optional array framing; never a banner."""
    def __init__(self):
        self.text = ''
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.unparsed_bytes = 0
        self.overflow = False
        self.array_depth = 0
        self.array_state = None
        self.invalid = False

    def feed(self, data):
        try:
            self.text += self.decoder.decode(data)
        except UnicodeDecodeError:
            self.unparsed_bytes += len(data)
            self.invalid = True
            self.text = ''
            self.decoder.reset()
            return []
        if len(self.text) > 256 * 1024:
            self.unparsed_bytes += len(self.text.encode('utf-8'))
            self.text = ''
            self.overflow = True
            return []
        result = []
        while self.text:
            self.text = self.text.lstrip()
            if not self.text:
                break
            if self.text[0] in '[,]':
                token, self.text = self.text[0], self.text[1:]
                if token == '[':
                    if self.array_depth:
                        self.invalid = True
                    self.array_depth += 1
                    self.array_state = 'value_or_end'
                elif token == ']':
                    if self.array_depth != 1 or self.array_state not in ('value_or_end', 'separator_or_end'):
                        self.invalid = True
                    if self.array_depth:
                        self.array_depth -= 1
                    self.array_state = None
                else:
                    if self.array_depth != 1 or self.array_state != 'separator_or_end':
                        self.invalid = True
                    self.array_state = 'value'
                continue
            if not self.text.startswith('{'):
                end = self.text.find('\n')
                if end < 0:
                    break
                self.unparsed_bytes += len(self.text[:end + 1].encode('utf-8'))
                self.text = self.text[end + 1:]
                continue
            try:
                value, end = json.JSONDecoder().raw_decode(self.text)
            except json.JSONDecodeError:
                break
            if self.array_depth:
                if self.array_state not in ('value_or_end', 'value'):
                    self.invalid = True
                self.array_state = 'separator_or_end'
            result.append(value)
            self.text = self.text[end:]
        return result


class Capture:
    def __init__(self, *, root, out, env, uid, metadata, remaining, io=None,
                 channel_cap=CHANNEL_CAP, staging_cap=STAGING_CAP, persist=lambda: None):
        # UUID validation also keeps values safe inside a predicate literal.
        import uuid
        self.uid = str(uuid.UUID(uid)).upper()
        self.root, self.out, self.env = Path(root), Path(out) / 'launch-capture', env
        self.remaining = remaining
        self.persist = persist
        self.io = io or NativeIO()
        self.channel_cap, self.staging_cap = channel_cap, staging_cap
        self.channels = []
        self.record = {'owned_uuid': self.uid, 'channels': [], 'test_pid': None,
                       'collector_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'coverage': 'best_effort_no_completeness_claim',
                       'issues': [], 'staging': [], 'staging_bytes': 0,
                       'simulator_logger_absence': 'not_independently_observed',
                       'limits': {'channel_bytes': channel_cap, 'staging_bytes': staging_cap,
                                  'readiness_seconds': 10, 'finish_seconds': 10}}
        metadata['launch_capture'] = self.record

    def issue(self, text):
        if text not in self.record['issues'] and len(self.record['issues']) < 64:
            self.record['issues'].append(text)
        self.record['coverage'] = 'incomplete'

    def start(self):
        if self.remaining() < 235:
            raise TimeoutError('Capture admission requires235s of work budget')
        self.out.mkdir(parents=True, exist_ok=False)
        deadline = self.io.clock() + 10
        for name, processes in (('host', HOST_PROCESSES), ('device', DEVICE_PROCESSES)):
            if self.io.clock() >= deadline:
                raise TimeoutError('Shared capture readiness deadline')
            predicate = ' OR '.join('process == "' + p + '"' for p in processes)
            argv = ['/usr/bin/log', 'stream', '--style', 'json', '--level', 'debug',
                    '--timeout', '230', '--predicate', predicate]
            if name == 'device':
                argv = ['xcrun', 'simctl', 'spawn', self.uid, 'log'] + argv[1:]
            record = {'name': name, 'argv': argv, 'observed_delivery': False,
                      'events': 0, 'rejected_schema_events': 0, 'target_markers': [],
                      'runner_emitter_pids': [], 'host_group_absent': False}
            proc = self.io.start(argv, self.root, self.env)
            # Own the handle before pipe setup, which can itself fail.
            channel = {'proc': proc, 'record': record, 'window': Window(self.channel_cap),
                       'parser': JsonObjects(), 'eof': False, 'read_error': False, 'prepared': False}
            self.channels.append(channel)
            self.record['channels'].append(record)
            record['owned_host_pgid'] = proc.pid
            self.persist()
            self.io.prepare(proc)
            channel['prepared'] = True
        while self.io.clock() < deadline:
            self.pump(deadline)
            if self.record['issues'] or any(c['window'].dropped or c['parser'].overflow or c['parser'].invalid
                                           or c['parser'].unparsed_bytes for c in self.channels):
                raise RuntimeError('Capture startup has incomplete or unsupported data')
            if all(c['record']['observed_delivery'] and c['proc'].poll() is None
                   and not c['eof'] and not c['read_error'] for c in self.channels):
                if self.remaining() < 225:
                    raise TimeoutError('After capture readiness require225s of work budget')
                return
            if any(c['proc'].poll() is not None or c['eof'] or c['read_error']
                   for c in self.channels):
                raise RuntimeError('Capture channel ended before observed delivery')
            self.io.sleep(min(.02, max(0, deadline - self.io.clock())))
        raise TimeoutError('No scoped log delivery on both channels within10s; do not run XCTest')

    def event(self, channel, value):
        rec = channel['record']
        if not isinstance(value, dict) or not isinstance(value.get('timestamp'), str) \
                or not isinstance(value.get('eventMessage'), str) \
                or not isinstance(value.get('processImagePath'), str) \
                or type(value.get('processID')) is not int or value['processID'] <= 0:
            rec['rejected_schema_events'] += 1
            self.issue(rec['name'] + ':unsupported_event_schema')
            return
        process = Path(value['processImagePath']).name
        allowed = HOST_PROCESSES if rec['name'] == 'host' else DEVICE_PROCESSES
        if process not in allowed:
            self.issue(rec['name'] + ':out_of_scope_emitter')
            return
        rec['events'] += 1
        rec['observed_delivery'] = True
        if 'first_delivery_monotonic' not in rec:
            rec['first_delivery_monotonic'] = self.io.clock()
            rec['first_event_timestamp'] = value['timestamp']
        msg = value['eventMessage']
        owned = self.uid.lower() in msg.lower()
        runner = rec['name'] == 'device' and process == RUNNER
        if runner and value['processID'] not in rec['runner_emitter_pids']:
            if len(rec['runner_emitter_pids']) < 16:
                rec['runner_emitter_pids'].append(value['processID'])
            else:
                self.issue('runner_pid_limit')
        # A service emitter PID is NEVER labeled the runner PID. Bundle-only host
        # messages may refer to another simulator, so they remain uncorrelated.
        target = owned or (rec['name'] == 'device' and (runner or BUNDLE in msg))
        if target and len(rec['target_markers']) < 64:
            rec['target_markers'].append({'timestamp': value['timestamp'],
                'emitter_pid': value['processID'], 'process': process,
                'attribution': 'owned_uuid' if owned else 'owned_device_channel',
                'event_message_sha256': hashlib.sha256(msg.encode()).hexdigest()})
        elif target:
            self.issue(rec['name'] + ':marker_limit')
        if 'loss' in str(value.get('messageType', '')).lower():
            self.issue(rec['name'] + ':reported_log_loss')

    def pump(self, deadline):
        for channel in self.channels:
            if not channel['prepared'] or channel['eof'] or channel['read_error']:
                continue
            for _ in range(4):
                if self.io.clock() >= deadline:
                    return
                try:
                    data = self.io.read(channel['proc'])
                except Exception as error:
                    channel['read_error'] = True
                    self.issue(channel['record']['name'] + ':read:' + type(error).__name__)
                    break
                if data is None:
                    break
                if not data:
                    channel['eof'] = True
                    break
                channel['window'].add(data)
                for value in channel['parser'].feed(data):
                    self.event(channel, value)

    def wait_for_test(self, proc, timeout):
        self.record['test_pid'] = proc.pid
        deadline = self.io.clock() + timeout
        while proc.poll() is None:
            if self.io.clock() >= deadline:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            self.pump(deadline)
            for c in self.channels:
                if c['eof'] or c['read_error'] or c['proc'].poll() is not None:
                    self.issue(c['record']['name'] + ':delivery_ended_during_test')
            self.io.sleep(min(.02, max(0, deadline - self.io.clock())))

    def group_absent(self, channel):
        try:
            return not self.io.group_exists(channel['proc']) and channel['proc'].poll() is not None
        except BaseException as error:
            self.issue(channel['record']['name'] + ':group_query:' + type(error).__name__)
            return False

    def stop_signal(self, channel, sig):
        try:
            self.io.signal_group(channel['proc'], sig)
        except ProcessLookupError:
            pass
        except BaseException as error:
            self.issue(channel['record']['name'] + ':signal:' + type(error).__name__)

    def write_streams(self, deadline):
        for c in self.channels:
            rec, window, parser = c['record'], c['window'], c['parser']
            rec.update(observed_bytes=window.total, dropped_bytes=window.dropped,
                       unparsed_bytes=parser.unparsed_bytes,
                       buffered_parser_characters=len(parser.text),
                       unclosed_array_depth=parser.array_depth, files=[])
            if window.dropped or parser.overflow or parser.invalid or parser.array_depth \
                    or parser.unparsed_bytes or parser.text.strip() or parser.decoder.getstate()[0]:
                self.issue(rec['name'] + ':truncated_or_unparsed')
            for label, offset, chunks in window.segments():
                path = self.out / (rec['name'] + '-' + label + '.raw')
                count = 0
                digest = hashlib.sha256()
                with path.open('wb') as stream:
                    for chunk in chunks:
                        if self.io.clock() >= deadline:
                            self.issue('capture_finish_deadline')
                            break
                        stream.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
                rec['files'].append({'path':path.name, 'stream_offset':offset, 'bytes':count,
                                     'sha256':digest.hexdigest()})

    def copy_staging(self, deadline):
        source = self.out.parent / 'result.xcresult' / 'Staging' / '1_Test' / 'Diagnostics'
        if not source.is_dir():
            self.issue('staging_absent')
            return
        budget = self.staging_cap
        for index, path in enumerate(source.rglob('*')):
            if self.io.clock() >= deadline or index >= 512 or budget <= 0:
                self.issue('staging_limit')
                break
            if path.is_symlink() or not path.is_file():
                continue
            if not (path.suffix == '.log' or path.name == 'StandardOutputAndStandardError.txt'):
                continue
            if not path.resolve().is_relative_to(source.resolve()):
                self.issue('staging_path_outside_root')
                continue
            destination = self.out / 'staging' / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            count, original_size = 0, path.stat().st_size
            digest = hashlib.sha256()
            with path.open('rb') as src, destination.open('wb') as dst:
                while budget > 0 and self.io.clock() < deadline:
                    data = src.read(min(CHUNK, budget))
                    if not data:
                        break
                    dst.write(data)
                    digest.update(data)
                    count += len(data)
                    budget -= len(data)
            self.record['staging'].append({'path':str(destination.relative_to(self.out)),
                                          'bytes':count, 'sha256':digest.hexdigest(),
                                          'source_size_before_copy':original_size})
            self.record['staging_bytes'] += count
            if count < original_size:
                self.issue('staging_truncated')

    def finish(self):
        """Never let capture stop/copy failure bypass the driver's device cleanup."""
        start = self.io.clock()
        deadline = start + 10
        try:
            for c in self.channels:
                self.stop_signal(c, signal.SIGTERM)
            for phase_end in (deadline - 8, deadline - 5):
                while self.io.clock() < phase_end:
                    try:
                        self.pump(phase_end)
                    except BaseException as error:
                        self.issue('capture_drain:' + type(error).__name__)
                        break
                    if all(self.group_absent(c) for c in self.channels):
                        break
                    try:
                        self.io.sleep(min(.02, max(0, phase_end - self.io.clock())))
                    except BaseException as error:
                        self.issue('capture_drain_wait:' + type(error).__name__)
                        break
                for c in self.channels:
                    if not self.group_absent(c):
                        self.stop_signal(c, signal.SIGKILL)
            try:
                self.pump(deadline - 5)
            except BaseException as error:
                self.issue('capture_drain:' + type(error).__name__)
            for c in self.channels:
                c['record']['host_group_absent'] = self.group_absent(c)
                if not c['record']['host_group_absent']:
                    self.issue(c['record']['name'] + ':host_group_absence_unconfirmed')
            if self.out.is_dir():
                self.write_streams(deadline)
                self.copy_staging(deadline)
        except BaseException as error:
            self.issue('capture_finish:' + type(error).__name__)
        finally:
            for c in self.channels:
                try:
                    self.io.close(c['proc'])
                except BaseException as error:
                    self.issue(c['record']['name'] + ':close:' + type(error).__name__)
        self.record['finished_monotonic'] = self.io.clock()
        self.record['finish_elapsed_seconds'] = self.io.clock() - start
        if self.io.clock() > deadline:
            self.issue('capture_finish_deadline_overrun')
        return list(self.record['issues'])
