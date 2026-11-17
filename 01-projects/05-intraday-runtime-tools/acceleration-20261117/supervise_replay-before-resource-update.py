"""Resume the frozen replay with bounded crash recovery; never alter its code or DB."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import ctypes
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

CN = timezone(timedelta(hours=8))
OPERATIONS = 'operations-20261117'


def now():
    return datetime.now(CN).isoformat(timespec='seconds')


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + f'.tmp-{os.getpid()}')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(.025 * (attempt + 1))


def event(ops, name, **fields):
    with (ops / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'at': now(), 'event': name, **fields}, ensure_ascii=False) + '\n')


class LockBusy(RuntimeError):
    pass


@contextmanager
def exclusive_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'1')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LockBusy(str(path)) from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


def check_frozen_code(root):
    manifest = read_json(root / 'analysis/manifest.json')
    expected = manifest.get('code', {})
    files = expected.get('files')
    if not isinstance(files, dict) or not files or not expected.get('sha256'):
        raise ValueError('manifest has no frozen code identity')
    frozen = (root / 'frozen-code').resolve()
    actual = {}
    for name, expected_hash in files.items():
        path = (frozen / name).resolve()
        if not path.is_relative_to(frozen):
            raise ValueError('manifest path leaves frozen-code')
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual[name] != expected_hash:
            raise ValueError('frozen code differs: ' + name)
    digest = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != expected['sha256']:
        raise ValueError('manifest aggregate frozen code identity differs')
    return digest


def verified_count(root):
    database = root / 'analysis/tasks.sqlite3'
    if not database.is_file():
        return 0
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        return db.execute("SELECT COUNT(*) FROM tasks WHERE state='verified'").fetchone()[0]


def memory_available():
    if os.name == 'nt':
        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ('total_phys', 'available_phys', 'total_page',
                'available_page', 'total_virtual', 'available_virtual', 'extended')]
        value = Status()
        value.length = ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            return value.available_phys
        return None
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, AttributeError):
        return None


def resource_gate(free_disk, free_memory, min_disk, min_memory):
    if free_disk < min_disk:
        return 'stopped_low_disk'
    if free_memory is None:
        return 'stopped_memory_unknown'
    return 'waiting_memory' if free_memory < min_memory else 'ready'


class RetryBudget:
    def __init__(self, verified, max_without_progress=3, max_restarts=8):
        self.verified = verified
        self.without_progress = 0
        self.restarts = 0
        self.max_without_progress = max_without_progress
        self.max_restarts = max_restarts

    def crash(self, verified):
        self.without_progress = 0 if verified > self.verified else self.without_progress + 1
        self.verified = max(self.verified, verified)
        if self.without_progress >= self.max_without_progress or self.restarts >= self.max_restarts:
            return False
        self.restarts += 1
        return True


def child_command(root, ops):
    return [sys.executable, '-X', 'faulthandler', str(root / 'acceleration-20261117/adaptive_replay.py'),
            '--universe', str(root / 'source-universe/universe.json'),
            '--cache', str(root / 'acquisition/market_data'), '--output', str(root / 'analysis'),
            '--cutoff', '2026-11-13T15:00:00+08:00', '--workers', '4', '--periods', '1m', '5m',
            '--min-free-gb', '10', '--min-free-memory-mb', '512', '--follow-cache',
            '--guard-mb', '768', '--reserve-mb', '768', '--gc-mode', 'disabled',
            '--source-status', str(root / 'acquisition/summary.json'), '--resume', '--retry-failed',
            '--stop-file', str(ops / 'STOP')]


def stop_requested(root, ops):
    return (root / 'analysis/STOP').exists() or (ops / 'STOP').exists()


def fatal_output(text):
    return any(marker in text for marker in (
        'resume configuration, universe, paths, cutoff or frozen code SHA256 differs',
        'frozen source code changed', 'another batch orchestrator already owns',
        '--resume requires an existing manifest'))


def supervise(root, poll_seconds=10, retry_seconds=30, max_restarts=8):
    root = Path(root).resolve()
    ops = root / OPERATIONS
    ops.mkdir(parents=True, exist_ok=True)
    budget = RetryBudget(verified_count(root), max_restarts=max_restarts)
    base = {'supervisor_pid': os.getpid(), 'root': str(root), 'runner_pid': None,
            'execution_allowed': False, 'uploaded': False}

    def status(state, **fields):
        try:
            verified = verified_count(root)
        except sqlite3.Error:
            verified = None
        write_json(ops / 'status.json', {**base, 'state': state, 'heartbeat': now(),
                   'verified': verified, 'restarts': budget.restarts, **fields})

    with exclusive_lock(ops / 'supervisor.lock'):
        event(ops, 'supervisor_started', pid=os.getpid())
        attempt = 0
        waiting_existing = False
        while True:
            if stop_requested(root, ops):
                status('stopped_by_request')
                event(ops, 'stopped_by_request')
                return 0
            try:
                digest = check_frozen_code(root)
            except (OSError, ValueError) as exc:
                status('stopped_integrity_error', error=str(exc))
                event(ops, 'integrity_error', error=str(exc))
                return 2
            try:
                with exclusive_lock(root / 'analysis/runner.lock'):
                    pass
            except LockBusy:
                status('waiting_existing_runner')
                if not waiting_existing:
                    event(ops, 'waiting_existing_runner')
                waiting_existing = True
                time.sleep(poll_seconds)
                continue
            if waiting_existing:
                event(ops, 'existing_runner_exited')
                previous = read_json(root / 'analysis/summary.json')
                if previous.get('processing_complete') or str(previous.get('state', '')).startswith('stopped_'):
                    status('completed' if previous.get('processing_complete') else previous['state'])
                    return 0
                waiting_existing = False
            gate = resource_gate(shutil.disk_usage(root).free, memory_available(), 10 * 1024**3, 1024**3)
            if gate != 'ready':
                status(gate)
                if gate.startswith('stopped_'):
                    event(ops, gate)
                    return 0
                time.sleep(poll_seconds)
                continue
            attempt += 1
            prefix = f'run-{datetime.now(CN):%Y%m%d-%H%M%S}-{os.getpid()}-{attempt:02d}'
            stdout_path, stderr_path = ops / (prefix + '.stdout.log'), ops / (prefix + '.stderr.log')
            with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
                child = subprocess.Popen(child_command(root, ops), cwd=root / 'frozen-code',
                                         stdout=stdout, stderr=stderr)
                event(ops, 'runner_started', runner_pid=child.pid, code_sha256=digest,
                      stdout=str(stdout_path), stderr=str(stderr_path))
                while child.poll() is None:
                    if (root / 'analysis/STOP').exists():
                        # The child watches our own STOP path; keep the caller's STOP untouched.
                        (ops / 'STOP').touch(exist_ok=True)
                    status('stopping' if stop_requested(root, ops) else 'running',
                           runner_pid=child.pid, stdout=str(stdout_path), stderr=str(stderr_path))
                    time.sleep(poll_seconds)
                code = child.returncode
            current = verified_count(root)
            summary = read_json(root / 'analysis/summary.json')
            state = summary.get('state', '')
            event(ops, 'runner_exited', exit_code=code, verified=current,
                  reported_state=state, stdout=str(stdout_path), stderr=str(stderr_path))
            if stop_requested(root, ops) or state.startswith('stopped_') or state.startswith('paused_'):
                status('stopped_by_request' if stop_requested(root, ops) else state, exit_code=code)
                return 0
            if code == 0:
                terminal = 'completed' if summary.get('processing_complete') else 'runner_returned_incomplete'
                status(terminal, exit_code=code, failed=summary.get('failed', 0),
                       source_unavailable=summary.get('source_unavailable', 0))
                return 0
            error_tail = stderr_path.read_text(encoding='utf-8', errors='replace')[-16000:]
            if fatal_output(error_tail):
                status('stopped_runner_configuration_error', exit_code=code, error=error_tail)
                return 2
            if not budget.crash(current):
                status('stopped_retry_limit', exit_code=code, no_progress_failures=budget.without_progress)
                event(ops, 'retry_limit', exit_code=code, verified=current)
                return 1
            status('restart_backoff', exit_code=code, no_progress_failures=budget.without_progress)
            event(ops, 'restart_scheduled', delay_seconds=retry_seconds, restarts=budget.restarts)
            # Split the backoff so both stop files remain responsive.
            deadline = time.monotonic() + retry_seconds
            while time.monotonic() < deadline and not stop_requested(root, ops):
                time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    try:
        return supervise(args.root)
    except LockBusy as exc:
        print('Another supervisor owns this batch:', exc, file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
