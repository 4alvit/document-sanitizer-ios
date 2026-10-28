"""One nonrenewable retrieval window; no network or archive execution.

Every writer must reserve first and use copy(). Reservations are never refunded.
Actual allocation remains sampled; a returning write that exceeds its reserved
allocation aborts. This is not an instantaneous filesystem quota.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import time
import unicodedata

CAP = 32 * 2**20
FLOOR, OTHER = 8 * 2**30, 4 * 2**30
SECONDS, ENTRIES, CHUNK = 180, 30000, 128 * 1024
SLACK = 65536
IDENTITY = {}


class Rejected(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Rejected(reason)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def safe(name):
    require(type(name) is str and 0 < len(name.encode("utf-8")) <= 4096, "path length/type")
    path = PurePosixPath(name)
    require(path.as_posix() == name and not path.is_absolute() and not any(p in (".", "..") for p in path.parts), "noncanonical path")
    require("\\" not in name and all(unicodedata.category(c) not in ("Cc", "Cf", "Cs") for c in name), "control/backslash path")
    return name


def alias(name):
    return unicodedata.normalize("NFC", name).casefold()


def integer(value):
    return type(value) is int and value >= 0


def allocation(info):
    require(integer(getattr(info, "st_blocks", None)), "allocation unknown")
    return info.st_blocks * 512


@contextmanager
def directory(path):
    """Open every absolute ancestor without following links; pin via dirfd."""
    path = Path(path)
    require(path.is_absolute() and str(path) == os.path.normpath(str(path)), "absolute canonical directory required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


class Window:
    def __init__(self, scope, started, entries, *, clock=time.monotonic, disk_usage=shutil.disk_usage):
        self.scope, self.started = Path(scope), started
        self.clock, self.disk_usage, self.entries = clock, disk_usage, entries
        self.check()
        self.validate_entries()

    def check(self):
        now = self.clock()
        require(type(self.started) in (int, float) and math.isfinite(self.started)
                and self.started <= now < self.started + SECONDS, "original window expired/invalid")

    def validate_entries(self):
        require(type(self.entries) is dict and len(self.entries) <= ENTRIES, "ledger entry bound")
        for name, row in self.entries.items():
            if name:
                safe(name)
            require(set(row) == {"kind", "dev", "ino", "logical", "allocated", "logical_charge", "allocated_charge", "materialization_started"}, "ledger shape")
            require(row["kind"] in ("file", "directory"), "ledger kind")
            require(type(row["materialization_started"]) is bool
                    and (row["dev"] is None or row["materialization_started"]), "ledger materialization state")
            require(all(integer(row[k]) for k in ("logical", "allocated", "logical_charge", "allocated_charge")), "ledger counters")
            require(row["logical"] <= row["logical_charge"] and row["allocated"] <= row["allocated_charge"], "undercharged ledger")
            require((row["dev"] is None and row["ino"] is None) or (integer(row["dev"]) and integer(row["ino"])), "ledger identity")
        require(self.total("logical_charge") <= CAP and self.total("allocated_charge") <= CAP, "cumulative32MiB cap")

    def total(self, key):
        return sum(row[key] for row in self.entries.values())

    def capacity(self):
        self.check()
        self.validate_entries()
        free = self.disk_usage(self.scope).free
        self.check()
        # Includes unspent reservations, not only unreserved allowance.
        remaining = CAP - self.total("allocated")
        require(free >= FLOOR + OTHER + remaining, "free floor plus reserve plus remaining allowance")

    def observe(self, name, info):
        self.check()
        kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else None
        require(kind is not None, "symlink/special owned entry")
        logical, allocated = info.st_size if kind == "file" else 0, allocation(info)
        require(integer(logical), "invalid logical length")
        require(name in self.entries, "unaccounted owned entry")
        row = self.entries[name]
        require(kind == row["kind"] and (row["dev"] is None or (row["dev"], row["ino"]) == (info.st_dev, info.st_ino)), "owned identity replaced")
        row["materialization_started"] = True
        row["dev"], row["ino"] = info.st_dev, info.st_ino
        row["logical"], row["allocated"] = max(row["logical"], logical), max(row["allocated"], allocated)
        self.validate_entries()

    def inventory(self, *, admit=False):
        """Bounded scope-only no-follow walk. Deletions never remove ledger rows."""
        self.check()
        seen_aliases, seen_count = set(), 0
        def visit(fd, prefix):
            nonlocal seen_count
            info = os.fstat(fd)
            accept(prefix, info)
            with os.scandir(fd) as scan:
                for item in scan:
                    self.check()
                    name = safe(prefix + "/" + item.name if prefix else item.name)
                    info = item.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        child = os.open(item.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        try:
                            require((info.st_dev, info.st_ino) == (os.fstat(child).st_dev, os.fstat(child).st_ino), "directory changed")
                            visit(child, name)
                        finally:
                            os.close(child)
                    else:
                        accept(name, info)
        def accept(name, info):
            nonlocal seen_count
            seen_count += 1
            require(seen_count <= ENTRIES and alias(name) not in seen_aliases, "owned count/alias")
            seen_aliases.add(alias(name))
            if admit:
                require(name not in self.entries, "admission collision")
                kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else None
                require(kind is not None, "symlink/special owned entry")
                logical, allocated = info.st_size if kind == "file" else 0, allocation(info)
                self.entries[name] = {"kind": kind, "dev": info.st_dev, "ino": info.st_ino,
                    "logical": logical, "allocated": allocated, "logical_charge": logical,
                    "allocated_charge": allocated + (SLACK if kind == "directory" else 0),
                    "materialization_started": True}
            self.observe(name, info)
        with directory(self.scope) as fd:
            visit(fd, "")
        self.capacity()

    @classmethod
    def admit(cls, scope, *, started, clock=time.monotonic, disk_usage=shutil.disk_usage):
        # Original acquirer start is mandatory; admission cannot reset time.
        window = cls(scope, started, {}, clock=clock, disk_usage=disk_usage)
        window.inventory(admit=True)
        return window

    def reserve(self, plans):
        self.capacity()
        proposed = dict(self.entries)
        aliases = {alias(name) for name in proposed}
        for name, kind, size in plans:
            safe(name)
            require(name not in proposed and alias(name) not in aliases and kind in ("file", "directory") and integer(size), "reservation collision/shape")
            require(kind == "file" or size == 0, "directory size")
            aliases.add(alias(name))
            proposed[name] = {"kind": kind, "dev": None, "ino": None, "logical": 0, "allocated": 0,
                "logical_charge": size, "allocated_charge": ((size + 4095) // 4096) * 4096 + SLACK,
                "materialization_started": False}
        for name in proposed:
            for parent in PurePosixPath(name).parents:
                key = "" if str(parent) == "." else str(parent)
                require(key in proposed and proposed[key]["kind"] == "directory", "missing/file reservation ancestor")
        original = self.entries
        self.entries = proposed
        try:
            self.validate_entries()
            self.capacity()
        except BaseException:
            self.entries = original  # No reservation or write occurred.
            raise

    @contextmanager
    def parent(self, name):
        safe(name)
        relative = PurePosixPath(name)
        with directory(self.scope / str(relative.parent)) as fd:
            yield fd, relative.name

    def mkdir(self, name):
        require(self.entries[name]["kind"] == "directory", "directory not reserved")
        require(not self.entries[name]["materialization_started"], "reservation already consumed")
        self.capacity()
        self.entries[name]["materialization_started"] = True
        with self.parent(name) as (fd, leaf):
            os.mkdir(leaf, 0o700, dir_fd=fd)
            self.check()
            self.observe(name, os.stat(leaf, dir_fd=fd, follow_symlinks=False))
            parent_name = str(PurePosixPath(name).parent)
            self.observe("" if parent_name == "." else parent_name, os.fstat(fd))

    @contextmanager
    def reader(self, name):
        self.check()
        with self.parent(name) as (parent, leaf):
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                info = os.fstat(fd)
                require(stat.S_ISREG(info.st_mode), "regular input required")
                identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                self.observe(name, info)
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    yield stream
                final = os.fstat(fd)
                require(identity == (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns, final.st_ctime_ns),
                        "input descriptor changed during reading")
                self.observe(name, final)
            finally:
                os.close(fd)

    def copy(self, source, name, expected=None, expected_sha=None):
        exact = expected is not None
        expected = self.entries[name]["logical_charge"] if expected is None else expected
        require(self.entries[name]["kind"] == "file" and integer(expected)
                and expected <= self.entries[name]["logical_charge"], "write not reserved")
        require(not self.entries[name]["materialization_started"], "reservation already consumed")
        self.capacity()
        self.entries[name]["materialization_started"] = True
        digest, count = hashlib.sha256(), 0
        with self.parent(name) as (parent, leaf):
            fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            try:
                self.observe(name, os.fstat(fd))
                while True:
                    self.check()
                    chunk = source.read(min(CHUNK, expected - count + 1))
                    self.check()
                    if not chunk:
                        break
                    count += len(chunk)
                    require(count <= expected, "stream exceeds declared length")
                    self.capacity()
                    written = os.write(fd, chunk)
                    self.check()
                    self.observe(name, os.fstat(fd))
                    require(written == len(chunk), "partial write")
                    digest.update(chunk)
                require((not exact or count == expected) and (expected_sha is None or digest.hexdigest() == expected_sha), "stream hash/length")
                self.capacity()
                os.fsync(fd)
                self.check()
                self.observe(name, os.fstat(fd))
                parent_name = str(PurePosixPath(name).parent)
                self.observe("" if parent_name == "." else parent_name, os.fstat(parent))
            finally:
                os.close(fd)
        return {"bytes": count, "sha256": digest.hexdigest()}

    def state(self):
        self.check()
        self.validate_entries()
        return {"schema_version": 1, "identity": IDENTITY, "scope": str(self.scope),
                "started": self.started, "deadline": self.started + SECONDS,
                "entries": {name: dict(row) for name, row in self.entries.items()}}

    @classmethod
    def resume(cls, scope, admission, handoff, started, *, clock=time.monotonic, disk_usage=shutil.disk_usage):
        for state in (admission, handoff):
            require(set(state) == {"schema_version", "identity", "scope", "started", "deadline", "entries"}
                    and type(state["schema_version"]) is int and state["schema_version"] == 1 and state["identity"] == IDENTITY
                    and state["scope"] == str(scope) and state["started"] == started
                    and state["deadline"] == started + SECONDS, "ledger window/identity mismatch")
        initial = cls(scope, started, admission["entries"], clock=clock, disk_usage=disk_usage)
        window = cls(scope, started, handoff["entries"], clock=clock, disk_usage=disk_usage)
        require("" in initial.entries and initial.entries[""]["kind"] == "directory"
                and initial.entries[""]["dev"] is not None, "missing original scope inventory")
        for name, old in initial.entries.items():
            require(name in window.entries, "lost cumulative entry")
            row = window.entries[name]
            require(row["kind"] == old["kind"] and (old["dev"] is None or
                    (row["dev"], row["ino"]) == (old["dev"], old["ino"])), "baseline identity changed")
            require(not old["materialization_started"] or row["materialization_started"], "consumed reservation reset")
            require(all(row[k] >= old[k] for k in ("logical", "allocated", "logical_charge", "allocated_charge")), "reduced baseline charge")
        window.inventory()
        return window
