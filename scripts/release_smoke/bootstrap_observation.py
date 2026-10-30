"""One diagnostic launch observation. No background thread, child or extra launch."""
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid

APP = 'io.github.4alvit.cleansend'
CAP = 1024


def validate_binding(binding):
    assert set(binding) == {'nonce', 'installation', 'source', 'run', 'attempt'}
    assert str(uuid.UUID(binding['nonce'])) == binding['nonce']
    assert str(uuid.UUID(binding['installation'])).upper() == binding['installation']
    assert re.fullmatch(r'[0-9a-f]{40}', binding['source'])
    assert re.fullmatch(r'[1-9][0-9]{0,19}', binding['run'])
    assert re.fullmatch(r'[1-9][0-9]{0,5}', binding['attempt'])


class Observation:
    def __init__(self, data, device, binding, *, clock=time.monotonic, raw_clock=None):
        validate_binding(binding)
        self.clock = clock
        self.raw_clock = raw_clock or (lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW))
        self.binding = dict(binding)
        self.data, self.device = Path(data), Path(device)
        assert self.device.is_absolute() and self.device == self.device.resolve()
        relative = self.data.relative_to(self.device).parts
        assert len(relative) == 5 and relative[:4] == ('data', 'Containers', 'Data', 'Application')
        assert str(uuid.UUID(relative[4])).upper() == relative[4]
        assert self.data == self.data.resolve()
        self.tmp = self.data/'tmp'
        assert self.tmp == self.tmp.resolve()
        self.filename = 'bootstrap-'+binding['nonce']+'.json'
        self.fds = []
        try:
            for path in (self.data, self.tmp):
                fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                self.fds.append(fd)
            self.identities = [self.identity(os.fstat(fd)) for fd in self.fds]
            assert not os.path.lexists(self.tmp/self.filename), 'fresh marker path already exists'
            assert not os.path.lexists(self.tmp/('bootstrap-'+binding['nonce']+'.writing')), 'fresh staging path already exists'
        except BaseException:
            self.close()
            raise
        self.end = None
        self.done = False
        self.polls = 0
        self.result = {'status': 'UNKNOWN', 'reason': 'NO_TIMELY_VALID_MARKER',
                       'diagnostic_only': True, 'exact_release_acceptance': False,
                       'binding': self.binding}

    @staticmethod
    def identity(info):
        return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))

    def environment(self, base):
        result = dict(base)
        result['SIMCTL_CHILD_REDACT_BOOTSTRAP_OBSERVATION'] = '1'
        for key, value in self.binding.items():
            result['SIMCTL_CHILD_REDACT_BOOTSTRAP_'+key.upper()] = value
        return result

    def begin(self, end):
        assert self.end is None
        now = self.clock()
        assert math.isfinite(now) and math.isfinite(end) and now < end <= now+20
        self.end = end
        self.allowance = end-now
        self.raw_start = self.raw_clock()
        self.result.update(launch_deadline_monotonic=end, launch_ready_monotonic=now,
                           launch_ready_raw_nanoseconds=self.raw_start)

    def poll(self):
        if self.done or self.end is None or self.clock() >= self.end:
            return
        self.polls += 1
        if self.polls > 256:
            self.result['reason'] = 'OBSERVATION_READ_LIMIT'
            self.done = True
            return
        fd = None
        try:
            observed_identities = []
            for path in (self.data, self.tmp):
                if self.clock() >= self.end: return
                observed_identities.append(self.identity(os.lstat(path)))
            assert observed_identities == self.identities
            if self.clock() >= self.end: return
            fd = os.open(self.filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fds[1])
            if self.clock() >= self.end: return
            before = os.fstat(fd)
            assert stat.S_ISREG(before.st_mode) and 0 < before.st_size <= CAP
            if self.clock() >= self.end: return
            raw = os.read(fd, CAP+1)
            if self.clock() >= self.end: return
            after = os.fstat(fd)
            identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            assert identity(before) == identity(after) and len(raw) == before.st_size
            observed_identities = []
            for path in (self.data, self.tmp):
                if self.clock() >= self.end: return
                observed_identities.append(self.identity(os.lstat(path)))
            assert observed_identities == self.identities
            observed_raw = self.raw_clock()
            observed = self.clock()
            if observed >= self.end: return
            value = json.loads(raw)
            assert set(value) == set(self.binding) | {'schema', 'event', 'bundle', 'raw_nanoseconds', 'processIdentifier'}
            assert type(value['schema']) is int and value['schema'] == 1
            assert value['event'] == 'root.onAppear' and value['bundle'] == APP
            assert all(value[key] == expected for key, expected in self.binding.items())
            assert type(value['raw_nanoseconds']) is int and self.raw_start <= value['raw_nanoseconds'] <= observed_raw
            assert type(value['processIdentifier']) is int and 1 < value['processIdentifier'] < 2**31
            if self.clock() >= self.end: return
            self.result.update(status='ROOT_ON_APPEAR_OBSERVED_BEFORE_LAUNCH_DEADLINE', reason=None,
                               marker=value, observed_monotonic=observed, observed_raw_nanoseconds=observed_raw)
            self.done = True
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AssertionError, TypeError, KeyError):
            self.result['reason'] = 'INVALID_OR_UNREADABLE_MARKER_OR_CONTAINER'
            self.done = True
        finally:
            if fd is not None:
                try: os.close(fd)
                except OSError:
                    self.result.update(status='UNKNOWN', reason='MARKER_FD_CLOSE_ERROR')
                    self.done = True

    def wait(self, proc, end):
        assert end == self.end
        try:
            while True:
                self.poll()
                remaining = end-self.clock()
                if remaining <= 0: raise subprocess.TimeoutExpired(proc.args, self.allowance)
                try:
                    code = proc.wait(timeout=min(.1, remaining))
                except subprocess.TimeoutExpired:
                    if self.clock() >= end: raise subprocess.TimeoutExpired(proc.args, self.allowance)
                    continue
                if self.clock() >= end:
                    raise subprocess.TimeoutExpired(proc.args, self.allowance)
                self.poll()
                if self.clock() >= end:
                    raise subprocess.TimeoutExpired(proc.args, self.allowance)
                return code
        finally:
            self.done = True  # No post-return/timeout observation or app wait.

    def close(self):
        first = None
        for fd in self.fds:
            try: os.close(fd)
            except OSError as error:
                if first is None: first = error
        self.fds = []
        if first is not None: raise first
