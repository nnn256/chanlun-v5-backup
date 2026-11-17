"""Isolated, resumable acquisition of all daily history returned by TDX.

This downloads data only. It never substitutes older caches, truncates history,
or changes another run's stop marker. Each successful HTTP payload and receipt
is retained before normalization, including payloads rejected as malformed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chanmodel.tdx_data import (CN, TdxClient, atomic_bytes, atomic_json,
                                cache_history, normalize_daily, now_iso, symbol)
from workbench.resources import hardware_snapshot

PROFILE = 'tdx_full_daily_acquisition_v1'
MIB = 1024 ** 2
GIB = 1024 ** 3
TERMINAL = {'success', 'unavailable', 'failed'}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(MIB), b''):
            value.update(block)
    return value.hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def load_universe(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    rows = value if isinstance(value, list) else value.get('records', value.get('universe'))
    if not isinstance(rows, list) or not rows:
        raise ValueError('universe must contain a nonempty records list')
    selected = {}
    duplicates = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('normalized universe records must be objects')
        code = symbol(row.get('symbol'))
        record = {'symbol': code, 'exchange': code[:2], 'code': code[2:],
                  'name': str(row.get('name', code))}
        if code in selected:
            if selected[code] != record:
                raise ValueError('conflicting duplicate universe record: ' + code)
            duplicates += 1
        selected[code] = record
    records = [selected[key] for key in sorted(selected)]
    return records, duplicates


class RunLock:
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open('a+b')
        self.handle.seek(0)
        self.handle.write(b'1')
        self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            raise ValueError('another acquisition owns this output directory') from error
        return self

    def __exit__(self, *_):
        self.handle.close()


def checkpoint(path):
    db = sqlite3.connect(path, timeout=30)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE IF NOT EXISTS stocks(
        symbol TEXT PRIMARY KEY, state TEXT NOT NULL, result TEXT,
        updated_at TEXT NOT NULL)''')
    db.commit()
    return db


def resource_slots(output, maximum, active, min_free_gb, min_memory_mb):
    free_disk = shutil.disk_usage(output).free
    available = hardware_snapshot().get('memory', {}).get('available_bytes')
    report = {'free_disk_bytes': free_disk, 'available_memory_bytes': available,
              'max_workers': maximum, 'active_workers': active}
    if free_disk < min_free_gb * GIB:
        return active, {**report, 'reason': 'waiting_disk'}
    # Existing requests drain; admit only new 128 MiB response/decode budgets
    # above the requested desktop reserve. Unknown memory stays sequential.
    additional = (max(0, int(available) - int(min_memory_mb * MIB)) // (128 * MIB)
                  if available is not None else max(0, 1 - active))
    allowed = max(active, min(maximum, active + additional))
    return allowed, {**report, 'reason': 'ready' if allowed > active else 'waiting_memory'}


def acquire_one(record, settings):
    code = record['symbol']
    output = Path(settings['output'])
    client = TdxClient(settings['base_url'], settings['timeout'])
    as_of = datetime.fromisoformat(settings['as_of'])
    attempts = []
    started = time.monotonic()
    for attempt in range(1, settings['retries'] + 2):
        # Attempts use unique directories so retries/resume never overwrite
        # earlier provider evidence, including invalid payloads.
        folder = output / 'responses' / code / (now_iso().replace(':', '') + '-' + str(time.time_ns()))
        try:
            data, receipt, raw = client.history(code, 'tdx')
            atomic_bytes(folder / 'response.json.gz', gzip.compress(raw, mtime=0))
            atomic_json(folder / 'receipt.json', receipt)
            if hashlib.sha256(raw).hexdigest() != receipt['response_sha256']:
                raise ValueError('response bytes differ from request receipt hash')
            bars, rows, quality = normalize_daily(data, as_of, 'tdx')
            quality['cache_run_as_of'] = settings['as_of']
            metadata = cache_history(output / 'cache', code, 'tdx', rows, raw, receipt, quality)
            metadata_path = output / 'cache/tdx/day/metadata' / (code + '.json')
            result = {**record, 'state': 'success' if bars else 'unavailable',
                      'bars': len(bars), 'raw_rows': quality['raw_rows'],
                      'first_date': quality['first_date'], 'last_date': quality['last_date'],
                      'as_of': settings['as_of'], 'received_at': receipt['received_at'],
                      'source': 'tdx', 'adjustment': 'unadjusted',
                      'csv_path': metadata['csv_path'], 'csv_sha256': metadata['csv_sha256'],
                      'raw_path': metadata['raw_path'], 'raw_storage_sha256': metadata['raw_storage_sha256'],
                      'response_sha256': receipt['response_sha256'],
                      'metadata_path': str(metadata_path.resolve()),
                      'metadata_sha256': digest(metadata_path),
                      'attempts': attempts + [{'attempt': attempt, 'state': 'received',
                                              'evidence': str(folder.resolve())}],
                      'elapsed_seconds': round(time.monotonic() - started, 3),
                      'coverage_claim': quality['coverage_claim']}
            if not bars:
                result['error'] = 'provider returned no closed daily bars; no fallback or padding'
            atomic_json(output / 'stocks' / (code + '.json'), result)
            return result
        except Exception as error:
            failure = {'attempt': attempt, 'state': 'failed', 'at': now_iso(),
                       'error': f'{type(error).__name__}: {error}'}
            if folder.exists():
                failure['evidence'] = str(folder.resolve())
            attempts.append(failure)
            atomic_json(output / 'attempt-errors' / (code + '.json'), attempts)
            if attempt <= settings['retries']:
                time.sleep(min(.5 * 2 ** (attempt - 1), 3))
    result = {**record, 'state': 'failed', 'bars': 0, 'source': 'tdx',
              'as_of': settings['as_of'], 'attempts': attempts,
              'error': attempts[-1]['error'],
              'elapsed_seconds': round(time.monotonic() - started, 3)}
    atomic_json(output / 'stocks' / (code + '.json'), result)
    return result


def reusable(result, output):
    try:
        saved = json.loads((output / 'stocks' / (result['symbol'] + '.json')).read_text(encoding='utf-8'))
        if saved != result or result['state'] not in {'success', 'unavailable'}:
            return False
        for key, hash_key in [('csv_path', 'csv_sha256'), ('raw_path', 'raw_storage_sha256'),
                              ('metadata_path', 'metadata_sha256')]:
            path = Path(result[key]).resolve()
            path.relative_to(output.resolve())
            if digest(path) != result[hash_key]:
                return False
        raw = gzip.decompress(Path(result['raw_path']).read_bytes())
        return hashlib.sha256(raw).hexdigest() == result['response_sha256']
    except (OSError, ValueError, KeyError, TypeError):
        return False


def export(db, output, manifest, state, resource=None, final=False):
    rows = [json.loads(row[0]) for row in db.execute('SELECT result FROM stocks WHERE result IS NOT NULL ORDER BY symbol')]
    counts = Counter(row['state'] for row in rows)
    total = len(manifest['records'])
    success = [row for row in rows if row['state'] == 'success']
    done = sum(counts[k] for k in TERMINAL)
    summary = {'profile': PROFILE, 'state': state, 'started_at': manifest['started_at'],
               'updated_at': now_iso(), 'as_of': manifest['settings']['as_of'],
               'total': total, 'done': done, 'success': counts['success'],
               'unavailable': counts['unavailable'], 'failed': counts['failed'],
               'pending': total - done, 'processing_complete': done == total,
               'successful_coverage_complete': counts['success'] == total,
               'bars': sum(row['bars'] for row in success),
               'first_date': min((row['first_date'] for row in success), default=None),
               'last_date': max((row['last_date'] for row in success), default=None),
               'last_date_counts': dict(Counter(row['last_date'] for row in success)),
               'resources': resource, 'full_returned_history': True, 'warmup': 0,
               'history_inception_complete': False, 'historical_delisted_universe_complete': False,
               'execution_allowed': False, 'fallback_used': False}
    atomic_json(output / 'summary.json', summary)
    if final:
        atomic_json(output / 'results.json', {'profile': PROFILE, 'manifest_sha256': digest(output / 'manifest.json'),
                    'as_of': manifest['settings']['as_of'], 'records': rows,
                    'cache_root': str((output / 'cache').resolve()),
                    'source_semantics': 'whole provider response per stock; no splicing or silent fallback'})
    return summary


def run(universe, output, *, base_url=None, as_of=None, workers=1, timeout=45,
        retries=2, resume=False, retry_failed=False, min_free_gb=5,
        min_free_memory_mb=512, stop_file=None, progress=None):
    if type(workers) is not int or not 1 <= workers <= 2:
        raise ValueError('workers must be 1 or 2 network threads')
    if type(retries) is not int or not 0 <= retries <= 10:
        raise ValueError('retries must be 0..10')
    if timeout <= 0 or min_free_gb < 0 or min_free_memory_mb < 0:
        raise ValueError('timeout must be positive and resource thresholds nonnegative')
    universe, output = Path(universe).resolve(), Path(output).resolve()
    records, duplicates = load_universe(universe)
    client = TdxClient(base_url, timeout)
    old_path = output / 'manifest.json'
    old = json.loads(old_path.read_text(encoding='utf-8')) if old_path.is_file() else None
    if old and not resume:
        raise ValueError('output already has a manifest; use --resume')
    if not old and output.exists() and any(output.iterdir()):
        raise ValueError('new output must be empty; never reuse another run directory')
    point = datetime.fromisoformat(as_of or (old['settings']['as_of'] if old else now_iso()))
    if point.tzinfo is None or point > datetime.now(CN):
        raise ValueError('as-of must include timezone and cannot be in the future')
    settings = {'base_url': client.base_url, 'as_of': point.astimezone(CN).isoformat(timespec='seconds'),
                'source': 'tdx', 'period': 'day', 'output': str(output),
                'timeout': timeout, 'retries': retries,
                'adapter_sha256': digest(ROOT / 'chanmodel/tdx_data.py')}
    identity = {'profile': PROFILE, 'universe_sha256': digest(universe), 'records': records,
                'output': str(output),
                'base_url': settings['base_url'], 'as_of': settings['as_of'],
                'source': 'tdx', 'period': 'day', 'adapter_sha256': settings['adapter_sha256'],
                'runner_sha256': digest(Path(__file__))}
    fingerprint = hashlib.sha256(canonical(identity)).hexdigest()
    if old and old.get('fingerprint') != fingerprint:
        raise ValueError('resume manifest identity differs; use a new output directory')
    output.mkdir(parents=True, exist_ok=True)
    with RunLock(output / 'run.lock'):
        manifest = old or {**identity, 'fingerprint': fingerprint, 'settings': settings,
                           'started_at': now_iso(), 'universe_path': str(universe),
                           'identical_duplicates_removed': duplicates,
                           'history_semantics': 'all returned native daily history; no truncation',
                           'universe_semantics': 'fixed current A-share universe, not all delisted securities'}
        if not old:
            atomic_json(old_path, manifest)
        settings = {**manifest['settings'], 'timeout': timeout, 'retries': retries}
        stop = Path(stop_file).resolve() if stop_file else output / 'STOP'
        with closing(checkpoint(output / 'checkpoint.sqlite3')) as db:
            db.execute("UPDATE stocks SET state='pending',result=NULL WHERE state='running'")
            pending = []
            for record in records:
                row = db.execute('SELECT state,result FROM stocks WHERE symbol=?', (record['symbol'],)).fetchone()
                prior = json.loads(row[1]) if row and row[1] else None
                valid = prior is not None and reusable(prior, output)
                if valid or (prior and prior.get('symbol') == record['symbol'] and
                             row[0] == prior.get('state') == 'failed' and not retry_failed):
                    continue
                db.execute('INSERT OR REPLACE INTO stocks VALUES(?,?,NULL,?)',
                           (record['symbol'], 'pending', now_iso()))
                pending.append(record)
            db.commit()
            state = 'running'
            futures = {}
            next_index = 0
            resource = None
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='tdx-daily-acquire') as pool:
                while futures or next_index < len(pending):
                    stopped = stop.exists()
                    allowed, resource = resource_slots(output, workers, len(futures), min_free_gb, min_free_memory_mb)
                    while not stopped and next_index < len(pending) and len(futures) < allowed:
                        record = pending[next_index]
                        next_index += 1
                        db.execute('UPDATE stocks SET state=?,updated_at=? WHERE symbol=?',
                                   ('running', now_iso(), record['symbol']))
                        db.commit()
                        futures[pool.submit(acquire_one, record, settings)] = record
                    report_state = 'pausing' if stopped and futures else 'paused' if stopped else (
                        resource['reason'] if not futures and next_index < len(pending) else 'running')
                    value = export(db, output, manifest, report_state, resource)
                    if progress:
                        progress(value)
                    if not futures:
                        if stopped:
                            state = 'paused'
                            break
                        if next_index >= len(pending):
                            break
                        time.sleep(1)
                        continue
                    done, _ = wait(futures, timeout=1, return_when=FIRST_COMPLETED)
                    for future in done:
                        record = futures.pop(future)
                        try:
                            result = future.result()
                        except Exception as error:
                            result = {**record, 'state': 'failed', 'bars': 0,
                                      'error': f'{type(error).__name__}: {error}'}
                            atomic_json(output / 'stocks' / (record['symbol'] + '.json'), result)
                        db.execute('UPDATE stocks SET state=?,result=?,updated_at=? WHERE symbol=?',
                                   (result['state'], json.dumps(result, ensure_ascii=False), now_iso(), record['symbol']))
                        db.commit()
            if state != 'paused':
                state = 'completed'
            return export(db, output, manifest, state, resource, final=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--base-url')
    parser.add_argument('--as-of', help='timezone-aware cutoff; default now, retained on resume')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--timeout', type=float, default=45)
    parser.add_argument('--retries', type=int, default=2)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--min-free-gb', type=float, default=5)
    parser.add_argument('--min-free-memory-mb', type=float, default=512)
    parser.add_argument('--stop-file', type=Path)
    args = vars(parser.parse_args())
    def progress(value):
        print(json.dumps({key: value[key] for key in ('state', 'done', 'total', 'success',
                         'unavailable', 'failed', 'bars', 'updated_at')}, ensure_ascii=False), flush=True)
    result = run(**args, progress=progress)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 3 if result['state'] == 'paused' else 1 if result['failed'] or result['unavailable'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
