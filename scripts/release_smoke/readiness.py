"""Bounded observations of one cold runtime discovery; never repair or retry it."""
import os
import resource
import signal
import subprocess
import sys
import time


OUTPUT_LIMIT = 1024 * 1024
SAMPLE_AFTER = 45
CLEANUP_RESERVE = 2


class OwnershipLost(RuntimeError):
    pass


class CleanupUnknown(RuntimeError):
    pass


def supported():
    return (signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL
            and all(hasattr(os, name) for name in ('waitid', 'WNOWAIT', 'WEXITED', 'WNOHANG', 'P_PID')))


def observe_owned(proc):
    """Do not reap: a waitable leader reserves the PID through the last attach/signal."""
    if proc.returncode is not None:
        raise OwnershipLost('Child was already reaped')
    try:
        result = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError as error:
        raise OwnershipLost('Child reservation unavailable') from error
    if result is not None and result.si_pid != proc.pid:
        raise OwnershipLost('Unexpected child observation')
    return result is not None


def output_limit():
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_LIMIT, OUTPUT_LIMIT))


def group_snapshot(pgid, deadline):
    """Read numeric identities, validating states only for the owned group."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Process cleanup observation deadline")
    raw = subprocess.check_output(
        ["/bin/ps", "-ax", "-o", "pid=,pgid=,stat="], timeout=min(1, remaining)
    )
    if not raw or len(raw) > 2 * 1024**2:
        raise RuntimeError("Invalid process registry snapshot")
    rows, seen = [], set()
    for line in raw.decode("ascii").splitlines():
        fields = line.split()
        if (len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit()
                or int(fields[0]) <= 0 or int(fields[1]) < 0):
            raise RuntimeError("Malformed process registry snapshot: " + repr(line[:128]))
        pid, group = int(fields[0]), int(fields[1])
        if pid in seen:
            raise RuntimeError("Duplicate process identity")
        seen.add(pid)
        if group == pgid:
            if not fields[2][0].isalpha() or len(fields[2]) > 16:
                raise RuntimeError("Owned process state is unknown: " + repr(line[:128]))
            rows.append({"pid": pid, "state": fields[2]})
    if os.getpid() not in seen:
        raise RuntimeError("Incomplete process registry snapshot")
    return rows

def group_members(pgid, deadline):
    """Retry transient unknown snapshots without extending cleanup time."""
    while True:
        try:
            return group_snapshot(pgid, deadline)
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Cannot confirm owned process state") from error
            time.sleep(min(.02, remaining))


def stop_observer(proc, deadline, row):
    """Preserve the leader through every signal, excluding its zombie from liveness."""
    observe_owned(proc)
    row['cleanup_confirmed'] = False
    start = time.monotonic()
    for index, sig in enumerate((signal.SIGTERM, signal.SIGKILL), start=1):
        members = group_members(proc.pid, deadline)
        live = any(member['state'][0] != 'Z' for member in members)
        if not live:
            break
        observe_owned(proc)
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass  # Only a fresh registry observation can confirm absence.
        row.setdefault('group_signals', []).append(sig.name)
        phase_end = min(deadline, start + index * max(0, deadline - start) / 3)
        while time.monotonic() < phase_end:
            members = group_members(proc.pid, deadline)
            live = any(member['state'][0] != 'Z' for member in members)
            if not live:
                break
            time.sleep(min(.02, max(0, phase_end - time.monotonic())))
        if not live:
            break
    if live or not observe_owned(proc):
        raise CleanupUnknown('Observer remains live at cleanup deadline')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CleanupUnknown('No observer reap budget')
    proc.wait(timeout=remaining)
    row['returncode'] = proc.returncode
    while group_members(proc.pid, deadline):
        if time.monotonic() >= deadline:
            raise CleanupUnknown('Observer group absence unconfirmed')
        time.sleep(min(.02, max(0, deadline - time.monotonic())))
    row['cleanup_confirmed'] = True


def command(args, name, deadline, out, env, cwd, rows, *, run=None):
    """Fixed callers only; output and all child work share the supplied deadline."""
    row = {'kind': 'diagnostic', 'args': args, 'output': name, 'output_limit_bytes': OUTPUT_LIMIT,
           'started_monotonic': time.monotonic(), 'deadline_monotonic': deadline}
    rows.append(row)
    if run is not None:
        run.meta['commands'].append(row)
    if not supported():
        row['status'] = 'UNAVAILABLE_WNOWAIT'
        return
    if deadline - time.monotonic() <= CLEANUP_RESERVE:
        row['status'] = 'NOT_STARTED_DEADLINE'
        return
    proc = None
    failure = None
    try:
        with (out / name).open('xb') as stream:
            proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT,
                                    start_new_session=True, preexec_fn=output_limit)
            row.update(pid=proc.pid, owned_process_group=proc.pid, owned_group_absent=False)
            if run is not None:
                run.meta['diagnostic_cleanup_unconfirmed'] = True
                run.persist()
            while not observe_owned(proc):
                if time.monotonic() >= deadline - CLEANUP_RESERVE:
                    row['status'] = 'TIMEOUT'
                    break
                time.sleep(min(.02, max(0, deadline - CLEANUP_RESERVE - time.monotonic())))
            else:
                row['status'] = 'RETURNED'
    except (OSError, OwnershipLost) as error:
        row.update(status='UNAVAILABLE', error=type(error).__name__)
        failure = error
    finally:
        try:
            if proc is not None:
                # Seed the obligation before even reading pid: a signal may have
                # interrupted the first registration immediately after Popen.
                row['owned_group_absent'] = False
                if run is not None:
                    run.meta['diagnostic_cleanup_unconfirmed'] = True
                try:
                    row.setdefault('owned_process_group', proc.pid)
                    stop_observer(proc, deadline, row)
                    row['owned_group_absent'] = row.get('cleanup_confirmed') is True
                except (OSError, subprocess.SubprocessError, OwnershipLost, CleanupUnknown) as error:
                    row.update(cleanup_error=type(error).__name__)
                    raise CleanupUnknown('Diagnostic child cleanup unconfirmed') from error
            path = out / name
            if path.is_file():
                row['output_bytes'] = path.stat().st_size
                row['possibly_truncated'] = row['output_bytes'] == OUTPUT_LIMIT
            row['finished_monotonic'] = time.monotonic()
        finally:
            if run is not None:
                run.meta['diagnostic_cleanup_unconfirmed'] = any(
                    value.get('kind') == 'diagnostic' and value.get('owned_group_absent') is False
                    for value in run.meta['commands'])
                active_error = sys.exc_info()[0] is not None
                try:
                    run.persist()
                except Exception as error:
                    run.meta['diagnostic_persist_error'] = type(error).__name__
                    if not active_error:
                        raise
    if isinstance(failure, (OwnershipLost, InterruptedError)):
        raise failure


def preflight(run, out, env, cwd):
    observation = run.meta['runtime_readiness_diagnostics'] = {
        'scope': 'component/path observations only; not proof of runtime readiness',
        'python_version': list(sys.version_info[:3]), 'commands': []}
    deadline = min(time.monotonic() + 8, run.start + run.end - 4)
    observation['deadline_monotonic'] = deadline
    for args, name in ((['/usr/bin/xcodebuild', '-checkFirstLaunchStatus'], 'runtime-first-launch.txt'),
                       (['/usr/bin/xcrun', '--find', 'simctl'], 'runtime-simctl-path.txt')):
        command(args, name, min(time.monotonic() + 4, deadline), out, env, cwd,
                observation['commands'], run=run)
    run.persist()


def wait_runtime(proc, deadline, item, out, env, cwd, *, run=None):
    observation = item['runtime_observation']
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(proc.args, 0)
    if remaining <= SAMPLE_AFTER or not supported():
        observation['sample_status'] = 'NOT_STARTED_BUDGET_OR_WNOWAIT'
        return proc.wait(timeout=remaining)
    try:
        return proc.wait(timeout=SAMPLE_AFTER)
    except subprocess.TimeoutExpired:
        # wait(timeout) did not reap. Confirm the reservation without poll/wait.
        try:
            exited = observe_owned(proc)
        except OwnershipLost:
            observation['ownership_lost'] = True
            raise
        if exited:
            observation['sample_status'] = 'NOT_STARTED_CHILD_EXITED'
        else:
            rows = observation['diagnostic_commands'] = []
            sample_end = min(time.monotonic() + 5, deadline)
            # Retain the original leader, including a possible zombie, until the
            # sampler ends. Never attach by name, follow a daemon, or dump env.
            if os.path.lexists(out / 'runtime-sample.txt'):
                raise CleanupUnknown('Unexpected existing sample output')
            command(['/usr/bin/sample', str(proc.pid), '1', '10', '-mayDie',
                     '-file', str(out / 'runtime-sample.txt')],
                    'runtime-sample-command.txt', sample_end, out, env, cwd, rows, run=run)
            observation['sample_status'] = rows[-1]['status']
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(proc.args, 0)
    return proc.wait(timeout=remaining)
