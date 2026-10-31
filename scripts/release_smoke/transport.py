"""Fixed local credential read + one HTTPS ZIP request; no work on import."""
from contextlib import contextmanager
import math
import os
import re
import selectors
import signal
import shutil
import subprocess
import time

GH = shutil.which("gh")
CURL = "/usr/bin/curl"
URL = None
HOST_HOME = os.environ.get("HOME", "")
CHUNK, TOKEN_CAP, CLEANUP_RESERVE = 65536, 4096, 2.0


class TransportFailure(Exception):
    """Fixed reason codes only; never a token, URL response, or stderr."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code):
    if not value:
        raise TransportFailure(code)


class Ops:
    clock = staticmethod(time.monotonic)
    popen = staticmethod(subprocess.Popen)
    selector = staticmethod(selectors.DefaultSelector)
    read = staticmethod(os.read)
    write = staticmethod(os.write)
    set_blocking = staticmethod(os.set_blocking)
    getpgid = staticmethod(os.getpgid)
    getsid = staticmethod(os.getsid)
    killpg = staticmethod(os.killpg)
    sleep = staticmethod(time.sleep)


def environment(auth=False):
    result = {"PATH": "/usr/bin:/bin", "HOME": HOST_HOME, "LANG": "C", "LC_ALL": "C"}
    if auth:
        result.update(GH_HOST="github.com", GH_CONFIG_DIR=HOST_HOME + "/.config/gh",
            GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", GH_NO_EXTENSION_UPDATE_NOTIFIER="1")
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            if name in os.environ:
                result[name] = os.environ[name]
    # Curl receives no credential, proxy, debug, TLS-key-log, DYLD or config env.
    return result


class OwnedPipe:
    def __init__(self, ops, outer_end, limit, cwd, cap):
        self.ops, self.cwd, self.cap = ops, cwd, cap
        self.started = ops.clock()
        self.end = min(self.started + limit, outer_end)
        self.work_end = self.end - CLEANUP_RESERVE
        self.process = self.selector = None
        self.owned = self.attempted = self.eof = False
        self.reaped = False
        self.count = 0
        self.report = {"attempted": False, "cleanup_confirmed": False,
            "exit_code": None, "deadline_exceeded": False}
        self.check(self.work_end)

    def check(self, end):
        now = self.ops.clock()
        if not math.isfinite(now) or now < self.started or now >= end:
            self.report["deadline_exceeded"] = True
            raise TransportFailure("DEADLINE")
        return now

    def observe_reaping(self, code=None):
        # Reading returncode does not poll/reap. Once reaping is observed,
        # the numeric PID/PGID can no longer authorize destructive signals.
        if code is not None or getattr(self.process, "returncode", None) is not None:
            self.reaped = True
            self.owned = False

    def poll(self):
        code = self.process.poll()
        self.observe_reaping(code)
        return code

    def wait(self, timeout):
        code = self.process.wait(timeout=timeout)
        self.observe_reaping(code)
        return code

    def require_signal_rights(self):
        self.observe_reaping()  # Never poll merely to authorize a signal.
        require(self.owned and not self.reaped, "OWNERSHIP_AFTER_REAP_OR_UNKNOWN")

    def start(self, argv, env, config=None):
        self.check(self.work_end)
        self.attempted = self.report["attempted"] = True
        self.process = self.ops.popen(argv, stdin=subprocess.PIPE if config is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            start_new_session=True, close_fds=True, cwd=self.cwd, env=env)
        pid = self.process.pid
        require(type(pid) is int and pid > 1, "OWNERSHIP")
        try:
            require(self.ops.getpgid(pid) == pid and self.ops.getsid(pid) == pid, "OWNERSHIP")
            self.owned = True
        except ProcessLookupError:
            # A fast local auth process may already be gone. Accept only
            # reaped-child + read-only group absence; never gain signal rights.
            require(self.poll() is not None and self.absent(), "OWNERSHIP")
        self.check(self.work_end)
        self.ops.set_blocking(self.process.stdout.fileno(), False)
        self.selector = self.ops.selector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        if config is not None:
            self.send_config(config)
        self.check(self.work_end)

    def send_config(self, config):
        # Secret stays in parent memory and the child's stdin, never argv/env/file.
        stream = self.process.stdin
        self.ops.set_blocking(stream.fileno(), False)
        selector = self.ops.selector()
        primary = None
        try:
            selector.register(stream, selectors.EVENT_WRITE)
            offset = 0
            while offset < len(config):
                now = self.check(self.work_end)
                events = selector.select(min(0.05, self.work_end - now))
                self.check(self.work_end)
                if not events:
                    continue
                try:
                    written = self.ops.write(stream.fileno(), config[offset:])
                except BlockingIOError:
                    continue
                self.check(self.work_end)
                require(type(written) is int and 0 < written <= len(config) - offset, "STDIN_WRITE")
                offset += written
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                selector.close()
            except BaseException:
                if primary is None:
                    raise
        stream.close()
        self.check(self.work_end)

    def read(self, size):
        require(type(size) is int and 0 < size <= 131072, "READ_BOUND")
        self.check(self.work_end)
        if self.eof:
            return b""
        while True:
            now = self.check(self.work_end)
            events = self.selector.select(min(0.05, self.work_end - now))
            self.check(self.work_end)
            if not events:
                code = self.poll()
                self.check(self.work_end)
                require(code in (None, 0), "EXIT")
                continue  # Exit0 is not EOF; descendants can still hold the pipe.
            try:
                data = self.ops.read(self.process.stdout.fileno(), min(size, CHUNK))
            except BlockingIOError:
                continue
            self.check(self.work_end)
            if data:
                self.count += len(data)
                require(self.count <= self.cap, "STDOUT_CAP")
                return data
            self.eof = True
            now = self.check(self.work_end)
            code = self.wait(timeout=self.work_end - now)
            self.check(self.work_end)
            self.report["exit_code"] = code
            require(code == 0, "EXIT")
            return b""

    def absent(self):
        try:
            self.ops.killpg(self.process.pid, 0)
        except ProcessLookupError:
            self.check(self.end)
            return True
        self.check(self.end)
        return False

    def close(self):
        first = None
        for value in (self.selector, getattr(self.process, "stdin", None), getattr(self.process, "stdout", None)):
            if value is not None:
                try:
                    value.close()
                except BaseException as error:
                    if first is None: first = error
        absent = reaped = False
        try:
            if self.process is not None:
                # No signal to a guessed/unconfirmed group. EPERM stops this
                # sequence; it is never reinterpreted as absence or retried.
                if not self.absent():
                    self.require_signal_rights()
                    self.ops.killpg(self.process.pid, signal.SIGTERM)
                    self.check(self.end)
                    try:
                        self.wait(timeout=min(0.1, self.end - self.check(self.end)))
                    except subprocess.TimeoutExpired:
                        pass
                    self.check(self.end)
                    if not self.absent():
                        self.require_signal_rights()
                        self.ops.killpg(self.process.pid, signal.SIGKILL)
                        self.check(self.end)
                self.wait(timeout=self.end - self.check(self.end))
                self.check(self.end)
                reaped = self.poll() is not None
                self.check(self.end)
                while not self.absent():
                    self.observe_reaping()
                    require(not self.reaped, "GROUP_PRESENT_AFTER_REAP")
                    now = self.check(self.end)
                    self.ops.sleep(min(0.01, self.end - now))
                absent = True
            elif not self.attempted:
                absent = reaped = True
        except BaseException as error:
            if first is None: first = error
        self.report["cleanup_confirmed"] = absent and reaped and first is None
        if first is not None:
            raise first
        require(self.report["cleanup_confirmed"], "CLEANUP_UNKNOWN")


class Transport:
    def __init__(self, outer_end, cwd, ops=None):
        self.outer_end, self.cwd, self.ops = outer_end, cwd, ops or Ops()
        self.auth_used = self.zip_used = False
        self.report = {"auth": None, "zip": None, "top_level_get_count": 0}

    @contextmanager
    def command(self, kind, limit, cap, argv, env, config=None):
        pipe = OwnedPipe(self.ops, self.outer_end, limit, self.cwd, cap)
        self.report[kind] = pipe.report
        primary = None
        try:
            pipe.start(argv(pipe), env, config)
            yield pipe
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                pipe.close()
            except BaseException:
                if primary is None:
                    raise

    def token(self):
        require(not self.auth_used, "AUTH_RETRY")
        self.auth_used = True
        with self.command("auth", 8.0, TOKEN_CAP + 1,
                lambda _: [GH, "auth", "token", "--hostname", "github.com"], environment(True)) as source:
            parts, total = [], 0
            while True:
                block = source.read(TOKEN_CAP + 2 - total)
                if not block: break
                total += len(block)
                require(total <= TOKEN_CAP + 1, "TOKEN_BOUND")
                parts.append(block)
        token = b"".join(parts)
        if token.endswith(b"\n"): token = token[:-1]
        require(re.fullmatch(rb"[A-Za-z0-9_.-]{1,4096}", token) is not None, "TOKEN_FORMAT")
        return token

    @contextmanager
    def zip(self, token, expected_bytes):
        require(not self.zip_used, "GET_RETRY")
        self.zip_used = True
        require(re.fullmatch(rb"[A-Za-z0-9_.-]{1,4096}", token) is not None, "TOKEN_FORMAT")
        config = b'header = "Authorization: Bearer ' + token + b'"\n'
        def argv(pipe):
            remaining = pipe.work_end - pipe.check(pipe.work_end)
            timeout = math.floor(remaining * 1000000) / 1000000
            require(timeout > 0, "DEADLINE")
            self.report["top_level_get_count"] += 1
            return [CURL, "--disable", "--silent", "--fail", "--location",
                "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "1",
                "--retry", "0", "--proxy", "", "--noproxy", "*", "--request", "GET",
                "--connect-timeout", str(timeout), "--max-time", str(timeout),
                "--config", "-", "--output", "-", "--url", URL]
        with self.command("zip", 90.0, expected_bytes + 1, argv, environment(), config) as source:
            yield source
