"""Resource-aware scheduling for the unchanged frozen replay and independent audit.

This changes task admission only. The manifest, per-security native worker, cached
sources, event definitions and independent verification remain the frozen ones.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures.process import BrokenProcessPool
from contextlib import closing
import ctypes
from datetime import datetime
import gc
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

BATCH_ROOT = Path(__file__).resolve().parent.parent
FROZEN = BATCH_ROOT / 'frozen-code'
sys.path.insert(0, str(FROZEN))
from tools import run_all_market_intraday as native

MIB = 1024 ** 2
SCHEDULER_PROFILE = 'resource_adaptive_cpu_v1'


def initialize_worker(gc_mode='default'):
    if gc_mode == 'disabled':
        gc.disable()


def build_manifest(universe, cache, output, cutoff, periods=('1m', '5m'), limit=0):
    """Intentionally identical to the frozen runner's manifest construction."""
    return {'profile': native.RUNNER_PROFILE, 'output': str(Path(output).resolve()),
            'cache': str(Path(cache).resolve()), 'cutoff': cutoff,
            'periods': sorted(set(periods)), 'universe': native.load_universe(universe, limit),
            'universe_file_sha256': native.file_hash(universe), 'config': native.asdict_config(),
            'sessions': 0, 'warmup': 0, 'code': native.code_identity(),
            'execution_allowed': False, 'uploaded': False}


class CpuSampler:
    def __init__(self):
        self.previous = None

    def sample(self):
        if os.name != 'nt':
            try:
                return min(100., os.getloadavg()[0] * 100 / max(1, os.cpu_count() or 1))
            except (AttributeError, OSError):
                return None
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        api = ctypes.windll.kernel32
        if not api.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        current = (idle.value, kernel.value + user.value)
        previous, self.previous = self.previous, current
        if previous is None or current[1] <= previous[1]:
            return None
        return max(0., min(100., 100 * (1 - (current[0] - previous[0]) / (current[1] - previous[1]))))


def worker_memory(pid):
    """Return observed working set and peak; unknown workers retain full reserves."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name != 'nt':
        try:
            fields = {}
            for line in Path(f'/proc/{pid}/status').read_text().splitlines():
                if line.startswith(('VmRSS:', 'VmHWM:')):
                    name, value, _ = line.split()
                    fields[name[:-1]] = int(value) * 1024
            return fields['VmRSS'], max(fields.get('VmHWM', 0), fields['VmRSS'])
        except (OSError, ValueError, KeyError):
            return None

    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
            'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]

    api, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    api.OpenProcess.restype = ctypes.c_void_p
    handle = api.OpenProcess(0x0410, False, pid)
    if not handle:
        return None
    try:
        value = Counters()
        value.cb = ctypes.sizeof(value)
        if not psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle), ctypes.byref(value), value.cb):
            return None
        return value.WorkingSetSize, value.PeakWorkingSetSize
    finally:
        api.CloseHandle(ctypes.c_void_p(handle))


class AdmissionPolicy:
    def __init__(self, max_workers=4, reserve_mb=768, guard_mb=768, min_memory_mb=512,
                 logical_cpus=None):
        cpus = (os.cpu_count() or 1) if logical_cpus is None else logical_cpus
        self.max_workers = max(1, min(4, max_workers, max(1, cpus - 2)))
        self.reservation = int(reserve_mb * MIB)
        self.guard = int(guard_mb * MIB)
        self.minimum = int(min_memory_mb * MIB)

    def observe(self, observations):
        peaks = [memory[1] for memory in observations if memory is not None]
        if peaks:
            # Leave growth headroom when observed graphs exceed the initial estimate.
            self.reservation = max(self.reservation, math.ceil(max(peaks) * 1.25 / MIB) * MIB)

    def decide(self, available, active_memory, cpu_percent):
        active = len(active_memory)
        if active >= self.max_workers:
            return False, 'worker_limit', None
        if available is None:
            return False, 'memory_unknown', None
        if active == 0:
            needed = max(self.minimum, self.guard + self.reservation)
            return available >= needed, ('ready_single' if available >= needed else 'waiting_memory'), needed
        if cpu_percent is None or cpu_percent >= 85:
            return False, 'cpu_busy_or_unknown', None
        growth = sum(max(0, self.reservation - (m[0] if m is not None else 0)) for m in active_memory)
        needed = self.guard + self.reservation + growth
        return available >= needed, ('ready_parallel' if available >= needed else 'reserving_memory'), needed


def active_memory(db_path, futures):
    observations = []
    with closing(native.connect_db(db_path)) as db:
        for code, period in futures.values():
            row = db.execute('SELECT worker_pid FROM tasks WHERE symbol=? AND period=?', (code, period)).fetchone()
            observations.append(worker_memory(row['worker_pid']) if row else None)
    return observations


def recover_database(db_path, manifest, cache, retry_failed):
    native.initialize(db_path, manifest)
    with closing(native.connect_db(db_path)) as db:
        for row in db.execute("SELECT * FROM tasks WHERE state='running'").fetchall():
            if not isinstance(row['worker_pid'], int) or row['worker_pid'] <= 0:
                raise ValueError('running task has no registered worker PID; refusing automatic replay to avoid duplicate work')
            if native.process_alive(row['worker_pid']):
                raise ValueError('a live worker still owns unfinished task; wait before resume')
            db.execute("UPDATE tasks SET state='pending',stage='recovered_after_interruption',worker_pid=NULL WHERE symbol=? AND period=?", (row['symbol'], row['period']))
        for row in db.execute("SELECT symbol,period,source_identity,record,verification FROM tasks WHERE state='verified'"):
            if not native.verified_still_intact(row, cache):
                db.execute("UPDATE tasks SET state='failed',error='verified artifact or frozen source integrity changed' WHERE symbol=? AND period=?", (row['symbol'], row['period']))
        if retry_failed:
            db.execute("UPDATE tasks SET state='pending',error=NULL WHERE state IN ('failed','source_unavailable')")
        db.commit()


def submit_one(pool, futures, db_path, manifest, follow_cache, source_status):
    """No deferred queue: submit at most one admitted task, then commit immediately."""
    cache = manifest['cache']
    with closing(native.connect_db(db_path)) as db:
        rows = db.execute("SELECT symbol,period,source_identity FROM tasks WHERE state IN ('pending','waiting_source') ORDER BY attempts,symbol,period")
        for row in rows:
            code, period = row['symbol'], row['period']
            csv_path, meta_path = native.source_paths(cache, code, period)
            if not csv_path.is_file() or not meta_path.is_file():
                failure = native.source_failure(cache, code, period)
                terminal = bool(failure) or not follow_cache or native.acquisition_finished(source_status)
                db.execute('UPDATE tasks SET state=?,error=?,updated_at=? WHERE symbol=? AND period=?',
                           ('source_unavailable' if terminal else 'waiting_source', failure or 'native cached source not available',
                            datetime.now(native.CN).isoformat(), code, period))
                continue
            expected = json.loads(row['source_identity']) if row['source_identity'] else None
            stamp = datetime.now(native.CN).isoformat()
            db.execute("UPDATE tasks SET state='running',stage='starting',attempts=attempts+1,started_at=?,updated_at=?,error=NULL,worker_pid=NULL WHERE symbol=? AND period=?", (stamp, stamp, code, period))
            job_manifest = {key: manifest[key] for key in ('output', 'cache', 'cutoff', 'config', 'code')}
            try:
                future = pool.submit(native.worker, code, period, job_manifest, str(db_path), expected)
            except BaseException:
                db.rollback()
                raise
            futures[future] = (code, period)
            db.commit()
            return True
        db.commit()
    return False


def finish_future(future, pair, db_path, output):
    code, period = pair
    broken = False
    try:
        value = future.result()
    except Exception as exc:
        broken = isinstance(exc, BrokenProcessPool)
        value = {'state': 'failed', 'error': f'worker process: {type(exc).__name__}: {exc}'}
    stamp = datetime.now(native.CN).isoformat()
    fields = {'state': value['state'], 'stage': value['state'], 'error': value.get('error'),
              'finished_at': stamp, 'updated_at': stamp}
    for key in ('record', 'verification', 'source_identity'):
        if key in value:
            fields[key] = json.dumps(value[key], ensure_ascii=False)
    with closing(native.connect_db(db_path)) as db:
        db.execute('UPDATE tasks SET ' + ','.join(k + '=?' for k in fields) + ' WHERE symbol=? AND period=?',
                   (*fields.values(), code, period))
        db.commit()
    with (output / 'progress.jsonl').open('a', encoding='utf-8') as log:
        log.write(json.dumps({'symbol': code, 'period': period, **fields}, ensure_ascii=False) + '\n')
    print(code, period, value['state'], value.get('error', ''), flush=True)
    return broken


def run(universe, cache, output, cutoff, *, workers=4, periods=('1m', '5m'), limit=0,
        resume=False, retry_failed=False, min_free_gb=10, min_free_memory_mb=512,
        stop_file=None, follow_cache=False, source_status=None, guard_mb=768, reserve_mb=768,
        gc_mode='default'):
    if not 1 <= workers <= 8 or not periods or any(p not in ('1m', '5m') for p in periods):
        raise ValueError('require workers 1..8 and native 1m/5m periods')
    if limit < 0 or any(not math.isfinite(v) or v < 0 for v in (min_free_gb, min_free_memory_mb, guard_mb, reserve_mb)):
        raise ValueError('resource gates and limit must be finite nonnegative values')
    if native.time_value(cutoff) > datetime.now(native.CN):
        raise ValueError('cutoff must not be in the future')
    if gc_mode not in ('default', 'disabled'):
        raise ValueError('gc_mode must be default or disabled')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    batch = output.parent
    runtime_dir = batch / 'acceleration-20261117'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(universe, cache, output, cutoff, periods, limit)
    db_path, manifest_path = output / 'tasks.sqlite3', output / 'manifest.json'
    stop_paths = [output / 'STOP', batch / 'operations-20261117/STOP']
    if stop_file:
        stop_paths.append(Path(stop_file))
    policy = AdmissionPolicy(workers, reserve_mb, guard_mb, min_free_memory_mb)
    sampler = CpuSampler()
    scheduler_identity = {'profile': SCHEDULER_PROFILE, 'path': str(Path(__file__).resolve()),
                          'sha256': native.file_hash(Path(__file__)), 'max_workers': policy.max_workers,
                          'gpu_enabled': False, 'algorithm_code_sha256': manifest['code']['sha256'],
                          'uses_unchanged_native_worker': True, 'independent_verification': True,
                          'gc_mode': gc_mode}
    with native.RunLock(output / 'runner.lock'):
        if manifest_path.exists():
            if not resume:
                raise ValueError('output already has a manifest; use --resume or choose a new output')
            if json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
                raise ValueError('resume configuration, universe, paths, cutoff or frozen code SHA256 differs')
        elif resume:
            raise ValueError('--resume requires an existing manifest')
        else:
            native.atomic_json(manifest_path, manifest)
        recover_database(db_path, manifest, cache, retry_failed)
        native.atomic_json(runtime_dir / 'scheduler-provenance.json', scheduler_identity)
        state, futures, last_admission, reason, needed = 'running', {}, 0., 'initializing', None
        with ProcessPoolExecutor(max_workers=policy.max_workers, max_tasks_per_child=1,
                                 initializer=initialize_worker, initargs=(gc_mode,)) as pool:
            while True:
                free, memory = shutil.disk_usage(output).free, native.available_memory_bytes()
                cpu = sampler.sample()
                if any(path.exists() for path in stop_paths):
                    state = 'stopped_by_file'
                elif free < min_free_gb * 1024 ** 3:
                    state = 'stopped_low_disk'
                elif not native.code_matches(manifest['code']):
                    state = 'stopped_code_changed'
                observations = active_memory(db_path, futures)
                policy.observe(observations)
                admitted, reason, needed = policy.decide(memory, observations, cpu)
                if state == 'running' and admitted and time.monotonic() - last_admission >= 1:
                    try:
                        if submit_one(pool, futures, db_path, manifest, follow_cache, source_status):
                            last_admission = time.monotonic()
                    except BrokenProcessPool:
                        state = 'interrupted'
                done, _ = wait(futures, timeout=1, return_when=FIRST_COMPLETED) if futures else (set(), set())
                for future in done:
                    if finish_future(future, futures.pop(future), db_path, output):
                        state = 'interrupted'
                report_state = state
                if state == 'running' and not futures and not admitted:
                    report_state = 'waiting_memory' if 'memory' in reason else 'waiting_resources'
                summary = native.aggregate(db_path, manifest, report_state)
                if state == 'running' and not futures and admitted and summary['counts'].get('waiting_source'):
                    summary['state'] = 'waiting_source'
                    if native.acquisition_stopped(source_status):
                        state = summary['state'] = 'paused_waiting_source'
                scheduler = {**scheduler_identity, 'active_workers': len(futures),
                             'admission_reason': reason, 'next_admission_required_bytes': needed,
                             'worker_reservation_bytes': policy.reservation, 'guard_bytes': policy.guard,
                             'cpu_percent': cpu, 'available_memory_bytes': memory,
                             'heartbeat': datetime.now(native.CN).isoformat(), 'pid': os.getpid()}
                summary.update(free_disk_bytes=free, available_memory_bytes=memory,
                               min_free_memory_mb=min_free_memory_mb, min_free_disk_gb=min_free_gb,
                               workers=policy.max_workers, source_status=str(source_status) if source_status else None,
                               scheduler=scheduler)
                native.atomic_json(output / 'summary.json', summary)
                native.atomic_json(runtime_dir / 'runtime.json', {**scheduler, 'state': summary['state'],
                                   'verified': summary['verified'], 'requested': summary['requested']})
                if not futures and (state != 'running' or summary['processing_complete']):
                    break
                if not futures:
                    time.sleep(1)
            if state == 'running':
                state = 'completed'
        summary = native.aggregate(db_path, manifest, state)
        summary.update(free_disk_bytes=shutil.disk_usage(output).free,
                       available_memory_bytes=native.available_memory_bytes(),
                       min_free_memory_mb=min_free_memory_mb, min_free_disk_gb=min_free_gb,
                       workers=policy.max_workers, source_status=str(source_status) if source_status else None,
                       scheduler=scheduler)
        native.atomic_json(output / 'summary.json', summary)
        native.atomic_json(runtime_dir / 'runtime.json', {**scheduler, 'state': state,
                           'verified': summary['verified'], 'requested': summary['requested']})
        return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--universe', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cutoff', required=True)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--periods', nargs='+', default=['1m', '5m'])
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--retry-failed', action='store_true')
    p.add_argument('--min-free-gb', type=float, default=10)
    p.add_argument('--min-free-memory-mb', type=float, default=512)
    p.add_argument('--guard-mb', type=float, default=768)
    p.add_argument('--reserve-mb', type=float, default=768)
    p.add_argument('--gc-mode', choices=('default', 'disabled'), default='default')
    p.add_argument('--stop-file', type=Path)
    p.add_argument('--follow-cache', action='store_true')
    p.add_argument('--source-status', type=Path)
    args = vars(p.parse_args())
    result = run(**args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['state'] == 'interrupted' else 2 if result['failed'] or result['source_unavailable'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
