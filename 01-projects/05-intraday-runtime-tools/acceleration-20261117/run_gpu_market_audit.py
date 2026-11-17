"""Resumable CUDA audit of cached native intraday OHLCV, separate from Chan replay."""
from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cuda_audit import CudaAuditor, PTX

CN = timezone(timedelta(hours=8))
PERIOD_DIR = {'1m': 'minute1', '5m': 'minute5'}
PROFILE = 'cuda_native_ohlcv_integrity_extrema_v1'
MIB = 1024 * 1024
GIB = 1024 ** 3


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(path)


@contextmanager
def exclusive_lock(path: Path):
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
            raise RuntimeError(f'GPU audit already owns lock {path}') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


def available_memory_bytes():
    if os.name == 'nt':
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ('total_phys', 'available_phys', 'total_page',
                'available_page', 'total_virtual', 'available_virtual', 'extended')]

        value = Status()
        value.length = ctypes.sizeof(value)
        return value.available_phys if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)) else None
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, OSError, ValueError):
        return None


def load_universe(path: Path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, list):
        raise ValueError('frozen universe must be a list')
    symbols = []
    seen = set()
    for row in value:
        code = row if isinstance(row, str) else row.get('symbol')
        if not isinstance(code, str) or code in seen:
            raise ValueError(f'invalid or duplicate universe symbol: {code!r}')
        seen.add(code)
        symbols.append(code)
    return sorted(symbols)


def source_files(cache: Path, symbol: str, period: str):
    part = PERIOD_DIR[period]
    folder = cache / 'tdx' / part
    return folder / 'ohlcv' / f'{symbol}.csv.gz', folder / 'metadata' / f'{symbol}.json'


def load_source(path: Path, metadata_path: Path, symbol: str, period: str, cutoff: datetime,
                max_batch_rows: int = 200000, auditor=None):
    stored = path.read_bytes()
    meta_raw = metadata_path.read_bytes()
    metadata = json.loads(meta_raw.decode('utf-8-sig'))
    raw = gzip.decompress(stored)
    storage_hash, raw_hash = sha256(stored), sha256(raw)
    if metadata.get('symbol') != symbol or metadata.get('period') != PERIOD_DIR[period]:
        raise ValueError('provider metadata symbol/period mismatch')
    if metadata.get('source') != 'tdx' or metadata.get('adjustment') != 'unadjusted':
        raise ValueError('GPU audit requires original TDX unadjusted native OHLCV')
    if metadata.get('csv_storage_sha256') != storage_hash or metadata.get('csv_sha256') != raw_hash:
        raise ValueError('compressed or uncompressed cached CSV hash mismatch')
    if metadata.get('csv_compression') != 'gzip':
        raise ValueError('source metadata does not declare gzip CSV')
    close_cutoff = cutoff.astimezone(CN)
    rows, batch_dates = [], []
    sessions = []
    session_totals = {}
    bars = 0
    batch_reports = []

    def flush(auditor):
        nonlocal rows, batch_dates
        if not rows:
            return
        groups = []
        group_start = 0
        day = batch_dates[0]
        for index, current in enumerate(batch_dates[1:], 1):
            if current != day:
                groups.append((group_start, index))
                group_start, day = index, current
        groups.append((group_start, len(batch_dates)))
        report = auditor.audit(rows, groups, verify_cpu=True)
        flags = report['flags']
        invalid = sum(bool(value) for value in flags)
        if invalid:
            raise ValueError(f'GPU OHLCV validation rejected {invalid} row(s); first flags={flags[:12]}')
        for item in report['sessions']:
            key = batch_dates[item['start']]
            old = session_totals.get(key)
            if old is None:
                session_totals[key] = {'count': item['count'], 'finite_extrema_rows': item['finite_extrema_rows'],
                                       'low': item['low'], 'high': item['high']}
            else:
                old['count'] += item['count']
                old['finite_extrema_rows'] += item['finite_extrema_rows']
                if item['finite_extrema_rows']:
                    old['low'] = item['low'] if old['low'] is None else min(old['low'], item['low'])
                    old['high'] = item['high'] if old['high'] is None else max(old['high'], item['high'])
        batch_reports.append({'rows': len(rows), **report['timings_ms']})
        rows, batch_dates = [], []

    context = CudaAuditor() if auditor is None else nullcontext(auditor)
    with context as auditor:
        reader = csv.DictReader(io.TextIOWrapper(io.BytesIO(raw), encoding='utf-8-sig', newline=''))
        required = {'closed_at', 'open', 'high', 'low', 'close', 'volume', 'is_closed', 'trade_date'}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError('cached OHLCV CSV is missing required columns')
        previous = None
        for line_number, item in enumerate(reader, 2):
            if None in item:
                raise ValueError(f'extra CSV fields at line {line_number}')
            if item.get('symbol') and item['symbol'] != symbol:
                raise ValueError(f'CSV symbol mismatch at line {line_number}')
            if item.get('period') and item['period'] != period:
                raise ValueError(f'CSV period mismatch at line {line_number}')
            if str(item['is_closed']).lower() not in ('true', '1'):
                raise ValueError(f'open/forming bar in frozen source at line {line_number}')
            timestamp = datetime.fromisoformat(item['closed_at'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError(f'timestamp has no timezone at line {line_number}')
            timestamp = timestamp.astimezone(CN)
            if timestamp > close_cutoff:
                raise ValueError(f'bar exceeds frozen cutoff at line {line_number}')
            if previous is not None and timestamp <= previous:
                raise ValueError(f'non-monotonic timestamp at line {line_number}')
            previous = timestamp
            day = timestamp.date().isoformat()
            if item['trade_date'] != day:
                raise ValueError(f'trade_date differs from timestamp at line {line_number}')
            try:
                row = tuple(float(item[key]) for key in ('open', 'high', 'low', 'close', 'volume'))
            except (ValueError, TypeError) as exc:
                raise ValueError(f'non-numeric OHLCV at line {line_number}') from exc
            rows.append(row)
            batch_dates.append(day)
            if day not in sessions:
                sessions.append(day)
            bars += 1
            if len(rows) >= max_batch_rows:
                flush(auditor)
        flush(auditor)
        if bars == 0:
            raise ValueError('source CSV contains no closed bars')
        # Metadata is the source-side row-count assertion; rows are parsed from the hash-checked payload.
        if metadata.get('closed_rows') != bars or metadata.get('unique_rows') != bars:
            raise ValueError('metadata closed/unique row count differs from parsed CSV')
        return {
            'symbol': symbol, 'period': period, 'state': 'passed', 'bars': bars,
            'first_session': sessions[0], 'last_session': sessions[-1],
            'sessions': [{'date': day, **session_totals[day]} for day in sessions],
            'invalid_rows': 0, 'source_csv_sha256': raw_hash, 'source_storage_sha256': storage_hash,
            'source_metadata_sha256': sha256(meta_raw), 'gpu_backend_sha256': sha256(PTX.encode('ascii')),
            'cuda_device': auditor.device, 'batch_count': len(batch_reports), 'batch_rows_limit': max_batch_rows,
            'batches': batch_reports, 'timings_ms': {
                'cuda_context_and_ptx_startup': auditor.startup_ms,
                'gpu_h2d': sum(row['h2d'] for row in batch_reports),
                'gpu_kernels': sum(row['gpu_kernels'] for row in batch_reports),
                'gpu_d2h': sum(row['d2h'] for row in batch_reports),
            },
            'audit_scope': 'GPU OHLCV integrity and per-session extrema only; no Chan structure or buy/sell-point computation',
            'verified_against_cpu_oracle': True,
            'execution_allowed': False,
        }


def _read_cached_result(path: Path, csv_hash: str, storage_hash: str, backend_hash: str):
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
        return (result.get('source_csv_sha256') == csv_hash and
                result.get('source_storage_sha256') == storage_hash and
                result.get('gpu_backend_sha256') == backend_hash)
    except (OSError, ValueError):
        return False


def run(root: Path, limit=0, max_batch_rows=200000):
    if not isinstance(limit, int) or limit < 0:
        raise ValueError('limit must be a nonnegative integer')
    if not isinstance(max_batch_rows, int) or not 1 <= max_batch_rows <= 200000:
        raise ValueError('max_batch_rows must be in 1..200000')
    root = Path(root).resolve()
    output = root / 'acceleration-20261117' / 'gpu-audit'
    result_dir = output / 'results'
    cache, universe_path = root / 'acquisition/market_data', root / 'source-universe/universe.json'
    cutoff = datetime.fromisoformat('2026-11-13T15:00:00+08:00')
    universe = load_universe(universe_path)
    if limit:
        universe = universe[:limit]
    tasks = [(symbol, period) for symbol in universe for period in ('1m', '5m')]
    output.mkdir(parents=True, exist_ok=True)
    backend_hash = sha256(PTX.encode('ascii'))
    stop_paths = [root / 'analysis/STOP', root / 'operations-20261117/STOP', output / 'STOP']
    summary_path = output / 'summary.json'
    journal = output / 'events.jsonl'
    lock_path = root / 'operations-20261117' / 'gpu-audit.lock'
    events = []
    counts = {'passed': 0, 'failed': 0}
    done, bars, current = 0, 0, None

    def state_for(code, period):
        return result_dir / period / f'{code}.json'

    def save(state):
        value = {'profile': PROFILE, 'state': state, 'updated_at': datetime.now(CN).isoformat(),
                 'requested': len(tasks), 'done': done, **counts, 'bars': bars,
                 'gpu_enabled': True, 'gpu_device': current.device if current else None,
                 'role': 'data_integrity_session_extrema_only', 'cpu_structure_replay_on_gpu': False,
                 'source_cutoff': cutoff.isoformat(), 'source_universe_sha256': sha256(universe_path.read_bytes()),
                 'gpu_backend_sha256': backend_hash, 'max_batch_rows': max_batch_rows,
                 'min_free_memory_mb': 512, 'min_free_disk_gb': 10,
                 'execution_allowed': False, 'uploaded': False,
                 'detail_results': str((result_dir / '<period>/<symbol>.json').resolve()),
                 'event_journal': str(journal.resolve())}
        atomic_json(summary_path, value)
        return value

    with exclusive_lock(lock_path):
        summary = save('starting')
        while done < len(tasks):
            if any(path.exists() for path in stop_paths):
                return save('stopped_by_file')
            free_disk = shutil.disk_usage(output).free
            if free_disk < 10 * GIB:
                return save('stopped_low_disk')
            memory = available_memory_bytes()
            if memory is None:
                return save('waiting_memory_unknown')
            if memory < 512 * MIB:
                save('waiting_memory')
                time.sleep(10)
                continue
            break
        if done >= len(tasks):
            return save('completed')

        with CudaAuditor() as auditor:
            current = auditor
            for symbol, period in tasks:
                if any(path.exists() for path in stop_paths):
                    return save('stopped_by_file')
                path, metadata_path = source_files(cache, symbol, period)
                target = state_for(symbol, period)
                try:
                    stored_hash = sha256(path.read_bytes())
                    meta_raw = metadata_path.read_bytes()
                    metadata = json.loads(meta_raw.decode('utf-8-sig'))
                    raw_hash = metadata.get('csv_sha256')
                    if _read_cached_result(target, raw_hash, stored_hash, backend_hash):
                        saved = json.loads(target.read_text(encoding='utf-8'))
                    else:
                        while True:
                            if any(p.exists() for p in stop_paths):
                                return save('stopped_by_file')
                            memory = available_memory_bytes()
                            if memory is None:
                                return save('waiting_memory_unknown')
                            if memory >= 512 * MIB:
                                break
                            save('waiting_memory')
                            time.sleep(10)
                        saved = load_source(path, metadata_path, symbol, period, cutoff,
                                            max_batch_rows, auditor=auditor)
                        saved['gpu_backend_sha256'] = backend_hash
                        atomic_json(target, saved)
                    counts[saved['state']] += 1
                    bars += saved.get('bars', 0)
                    done += 1
                    with journal.open('a', encoding='utf-8', newline='\n') as stream:
                        stream.write(json.dumps({'observed_at': datetime.now(CN).isoformat(),
                                                 'symbol': symbol, 'period': period,
                                                 'state': saved['state'], 'bars': saved.get('bars', 0),
                                                 'source_csv_sha256': saved.get('source_csv_sha256'),
                                                 'cuda_device': auditor.device}, ensure_ascii=False,
                                                separators=(',', ':')) + '\n')
                except Exception as exc:
                    failure = {'symbol': symbol, 'period': period, 'state': 'failed',
                               'error': f'{type(exc).__name__}: {exc}',
                               'source_metadata_sha256': sha256(metadata_path.read_bytes()) if metadata_path.exists() else None,
                               'gpu_backend_sha256': backend_hash, 'execution_allowed': False}
                    atomic_json(target, failure)
                    counts['failed'] += 1
                    done += 1
                    with journal.open('a', encoding='utf-8', newline='\n') as stream:
                        stream.write(json.dumps({'observed_at': datetime.now(CN).isoformat(), **failure}, ensure_ascii=False,
                                                separators=(',', ':')) + '\n')
                save('running')
                if done % 10 == 0 or done == len(tasks):
                    print(json.dumps({'done': done, 'requested': len(tasks), **counts, 'bars': bars,
                                      'gpu': auditor.device['name']}, ensure_ascii=False), flush=True)
        return save('completed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--max-batch-rows', type=int, default=200000)
    args = parser.parse_args()
    result = run(args.root, args.limit, args.max_batch_rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
