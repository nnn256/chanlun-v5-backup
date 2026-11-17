"""Offline, memory-budgeted CPU research across independent securities.

Each security's periods are processed in order inside one process. The declared
algorithm still sees every admitted candle in its original order; the runner
only distributes separate securities. Existing live services are never changed.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PERIODS = {'day', '5d', '1m', '5m', '15m', '30m', '60m', 'week', 'month', 'quarter', 'year'}
PANEL_NAME = re.compile(r'((?:sh|sz|bj)\d{6})__([a-z0-9_]+)\.json\.gz')
MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 128 * 1024 * 1024


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_identity():
    paths = [*sorted((ROOT / 'chanmodel').rglob('*.py')), Path(__file__).resolve()]
    hardware = ROOT / 'core/hardware_compute.py'
    if hardware.is_file():
        paths.append(hardware)
    files = {path.relative_to(ROOT).as_posix(): file_hash(path) for path in paths}
    return {'files': files, 'sha256': hashlib.sha256(canonical(files)).hexdigest()}


def archive_tasks(archive_dir, periods=('day',), symbols=None, limit=3):
    """Bind an explicit, hash-verified input set without loading candle graphs."""
    root = Path(archive_dir).resolve()
    if not root.is_dir():
        raise ValueError('archive directory does not exist')
    manifest_path = root / 'manifest.json'
    if not manifest_path.is_file():
        raise ValueError('archive manifest.json is required; unverified files are not scheduled')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    entries = manifest.get('files')
    if not isinstance(entries, list):
        raise ValueError('archive manifest files must be a list')
    periods = tuple(dict.fromkeys(periods))
    if not periods or any(period not in PERIODS for period in periods):
        raise ValueError('choose supported OHLC periods; line/auction snapshots are not candles')
    if type(limit) is not int or not 1 <= limit <= 240:
        raise ValueError('limit must be 1..240 distinct securities')
    selected_symbols = None if symbols is None else tuple(dict.fromkeys(symbols))
    if selected_symbols is not None and (not selected_symbols or any(
            not re.fullmatch(r'(?:sh|sz|bj)\d{6}', code) for code in selected_symbols)):
        raise ValueError('symbols must use normalized exchange codes such as sz300949')
    index = {}
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get('file'), str):
            raise ValueError('invalid archive manifest entry')
        match = PANEL_NAME.fullmatch(item['file'])
        if match is None:
            raise ValueError('archive manifest contains an unsafe or unsupported panel filename')
        name = item['file']
        if name in index:
            raise ValueError('duplicate archive manifest filename')
        digest = item.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('archive manifest requires a lowercase SHA-256 for every panel')
        index[name] = {'symbol': match[1], 'period': match[2], 'file': name, 'sha256': digest}
    available = sorted({item['symbol'] for item in index.values()
                        if item['period'] in periods})
    chosen = (list(selected_symbols) if selected_symbols is not None else available)[:limit]
    if selected_symbols is not None and len(selected_symbols) > limit:
        raise ValueError('explicit symbols exceed --limit; no requested security was silently omitted')
    if not chosen:
        raise ValueError('no requested OHLC archive inputs are available')
    tasks = []
    for code in chosen:
        for period in periods:
            name = f'{code}__{period}.json.gz'
            if name not in index:
                raise ValueError(f'missing verified archive input: {name}')
            task = {**index[name], 'path': str(root / name)}
            path = Path(task['path'])
            if not path.is_file():
                raise ValueError(f'missing archive file: {name}')
            if path.stat().st_size > MAX_COMPRESSED_BYTES:
                raise ValueError(f'compressed archive exceeds memory bound: {name}')
            if file_hash(path) != task['sha256']:
                raise ValueError(f'archive SHA-256 mismatch: {name}')
            task['compressed_bytes'] = path.stat().st_size
            tasks.append(task)
    return tasks, {'path': str(manifest_path), 'sha256': file_hash(manifest_path),
                   'available_securities': len(available), 'selected_securities': len(chosen),
                   'selected_symbols': chosen, 'periods': list(periods),
                   'as_of': manifest.get('as_of'),
                   'scope': 'selected locally archived OHLC inputs; no new acquisition'}


def read_bars(task, max_bars, cutoff=None):
    from chanmodel.model import Candle, time_value
    path = Path(task['path'])
    if file_hash(path) != task['sha256']:
        raise ValueError('input archive changed after preflight: ' + task['file'])
    with gzip.open(path, 'rb') as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('expanded archive exceeds memory bound: ' + task['file'])
    panel = json.loads(raw)
    if panel.get('symbol') != task['symbol'] or panel.get('period') != task['period']:
        raise ValueError('archive panel identity differs from its manifest filename')
    if panel.get('kind') != 'candles' or not isinstance(panel.get('bars'), list):
        raise ValueError('archive is not an OHLC candle panel')
    rows = panel['bars']
    if len(rows) > max_bars:
        raise ValueError(f'archive has {len(rows)} rows, exceeding max-bars={max_bars}; history was not truncated')
    declared = panel.get('coverage', {}).get('count')
    if declared is not None and (type(declared) is not int or declared != len(rows)):
        raise ValueError('archive candle count differs from its declared coverage')
    stop = time_value(cutoff) if cutoff else None
    bars = []
    previous = None
    forming_seen = False
    for index, row in enumerate(rows):
        if row.get('source_index', index) != index:
            raise ValueError('archive candle indices must start at zero and be contiguous')
        closed = row.get('is_closed', True)
        if type(closed) is not bool:
            raise ValueError('archive is_closed must be a boolean')
        text = row.get('closed_at')
        if text is None:
            text = str(row['date_cn']).replace(' ', 'T')
            point = datetime.fromisoformat(text)
            text = point.isoformat() + ('+08:00' if point.tzinfo is None else '')
        moment = time_value(text)
        if previous is not None and moment <= previous:
            raise ValueError('archive candles must have strictly increasing close times')
        previous = moment
        if not closed:
            forming_seen = True
            continue
        if forming_seen:
            raise ValueError('a closed candle follows a forming archive candle')
        if stop is not None and moment > stop:
            continue
        bars.append(Candle(len(bars), *(row[field] for field in ('open', 'high', 'low', 'close')),
                           text, row.get('volume'), True))
    if len(bars) < 3:
        raise ValueError('fewer than three closed archive candles exist before cutoff')
    digest = hashlib.sha256(canonical([[bar.closed_at, bar.open, bar.high, bar.low,
                                       bar.close, bar.volume] for bar in bars])).hexdigest()
    return bars, digest, {'rows_in_archive': len(rows), 'closed_rows_admitted': len(bars),
                          'forming_rows_excluded': sum(not row.get('is_closed', True) for row in rows),
                          'first_close': bars[0].closed_at, 'last_close': bars[-1].closed_at,
                          'source_kind': panel.get('source_kind'), 'name': panel.get('name')}


def analyze_task(task, max_bars=30000, cutoff=None):
    from chanmodel.complete_study import analyze_complete
    bars, digest, evidence = read_bars(task, max_bars, cutoff)
    moment = cutoff or bars[-1].closed_at
    report = analyze_complete(task['symbol'], task['period'], bars, moment, digest)
    return report, {'symbol': task['symbol'], 'period': task['period'], 'archive_sha256': task['sha256'],
                    'input_sha256': digest, 'bars': len(bars), 'cutoff': moment, **evidence}


def _worker_group(tasks, output_dir, max_bars, cutoff, expected_code):
    """A small path-only IPC message admits one security and its ordered periods."""
    if source_identity()['sha256'] != expected_code:
        raise ValueError('research source changed before worker start')
    results = []
    for task in tasks:
        started = time.perf_counter()
        try:
            report, evidence = analyze_task(task, max_bars, cutoff)
            encoded = canonical(report)
            digest = hashlib.sha256(encoded).hexdigest()
            path = Path(output_dir) / 'reports' / task['file']
            path.parent.mkdir(parents=True, exist_ok=True)
            # A fresh output root and exclusive file creation prevent accidental
            # replacement of a historical result from another run.
            with path.open('xb') as stream:
                stream.write(gzip.compress(encoded, compresslevel=3, mtime=0))
            results.append({**evidence, 'state': 'completed', 'report': str(path),
                            'report_sha256': digest, 'report_file_sha256': file_hash(path),
                            'signals': len(report.get('signals', [])), 'worker_pid': os.getpid(),
                            'seconds': round(time.perf_counter() - started, 6)})
        except Exception as error:
            results.append({'symbol': task['symbol'], 'period': task['period'], 'state': 'failed',
                            'error': type(error).__name__ + ': ' + str(error),
                            'worker_pid': os.getpid(), 'seconds': round(time.perf_counter() - started, 6)})
    if source_identity()['sha256'] != expected_code:
        raise ValueError('research source changed during worker execution')
    return results


def run_batch(archive_dir, output_dir, *, workers='auto', mode='auto', symbols=None,
              periods=('day',), limit=3, max_bars=30000, cutoff=None, verify_serial=False):
    from core.hardware_compute import resource_plan
    if type(max_bars) is not int or not 3 <= max_bars <= 30000:
        raise ValueError('max-bars must be 3..30000')
    if cutoff is not None:
        from chanmodel.model import time_value
        time_value(cutoff)
    if workers != 'auto':
        if isinstance(workers, bool):
            raise ValueError('workers must be auto or a positive integer')
        if not isinstance(workers, int) and (not isinstance(workers, str) or not workers.isdecimal()):
            raise ValueError('workers must be auto or a positive integer')
        try:
            workers = int(workers)
        except (TypeError, ValueError) as error:
            raise ValueError('workers must be auto or a positive integer') from error
        if workers < 1:
            raise ValueError('workers must be auto or a positive integer')
    target = Path(output_dir).resolve()
    if target.exists():
        raise ValueError('output directory already exists; use a fresh directory')
    tasks, archive = archive_tasks(archive_dir, periods, symbols, limit)
    groups = OrderedDict()
    for task in tasks:
        groups.setdefault(task['symbol'], []).append(task)
    plan = resource_plan(task_count=len(groups), requested=workers,
                         per_worker_bytes=768 * 1024 * 1024, mode=mode)
    actual_workers = max(1, min(int(plan['workers']), len(groups)))
    source = source_identity()
    target.mkdir(parents=True, exist_ok=False)
    manifest = {'schema': 'hardware-research-batch.v1', 'started_at': datetime.now(timezone.utc).isoformat(),
                'backend': 'cpu_processes' if actual_workers > 1 else 'cpu_serial',
                'gpu_active': False, 'gpu_scope': 'causal object-graph research remains on CPU',
                'workers': actual_workers, 'resource_plan': plan, 'source': source, 'archive': archive,
                'inputs': tasks, 'max_bars': max_bars, 'cutoff': cutoff,
                'verify_serial': bool(verify_serial), 'execution_allowed': False, 'uploaded': False}
    (target / 'manifest.json').write_bytes(canonical(manifest))
    started = time.perf_counter()
    results = []
    if actual_workers == 1:
        for group in groups.values():
            results.extend(_worker_group(group, str(target), max_bars, cutoff, source['sha256']))
    else:
        # The same spawn path is exercised on Windows and other platforms;
        # workers do not inherit the live web server's mutable session graphs.
        with ProcessPoolExecutor(max_workers=actual_workers,
                                 mp_context=multiprocessing.get_context('spawn')) as pool:
            pending = [(group, pool.submit(_worker_group, group, str(target), max_bars,
                                          cutoff, source['sha256'])) for group in groups.values()]
            for group, future in pending:
                try:
                    results.extend(future.result())
                except Exception as error:
                    # A broken worker is a failed security, not lost coverage.
                    results.extend({'symbol': task['symbol'], 'period': task['period'], 'state': 'failed',
                                    'error': type(error).__name__ + ': ' + str(error)} for task in group)
    compute_seconds = time.perf_counter() - started
    serial_started = time.perf_counter()
    serial_checks = []
    if verify_serial:
        lookup = {(task['symbol'], task['period']): task for task in tasks}
        for result in results:
            if result['state'] != 'completed':
                continue
            try:
                report, _ = analyze_task(lookup[(result['symbol'], result['period'])], max_bars, cutoff)
                current = hashlib.sha256(canonical(report)).hexdigest()
                serial_checks.append({'symbol': result['symbol'], 'period': result['period'],
                                      'report_sha256': current, 'equal': current == result['report_sha256']})
            except Exception as error:
                serial_checks.append({'symbol': result['symbol'], 'period': result['period'],
                                      'equal': False, 'error': type(error).__name__ + ': ' + str(error)})
    source_stable = source_identity()['sha256'] == source['sha256']
    successful = sum(row['state'] == 'completed' for row in results)
    passed = successful == len(tasks) and source_stable and all(row['equal'] for row in serial_checks)
    summary = {'schema': manifest['schema'], 'state': 'completed' if passed else 'failed',
               'backend': manifest['backend'], 'gpu_active': False, 'workers': actual_workers,
               'securities': len(groups), 'requested': len(tasks), 'completed': successful,
               'failed': len(tasks) - successful, 'bars': sum(row.get('bars', 0) for row in results),
               'compute_seconds': round(compute_seconds, 6),
               'serial_verification_seconds': round(time.perf_counter() - serial_started, 6) if verify_serial else None,
               'serial_verification': serial_checks, 'source_stable': source_stable,
               'results': results, 'execution_allowed': False, 'uploaded': False,
               'limits': ['Local selected archive, not an all-market replay.',
                          'Exact serial parity verifies execution equivalence, not predictive accuracy.',
                          'All original admitted closed candles are retained; oversized input is rejected.']}
    (target / 'summary.json').write_bytes(canonical(summary))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-dir', type=Path, default=ROOT / 'data/research')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--workers', default='auto', help='auto or requested CPU process count; memory limits still apply')
    parser.add_argument('--mode', choices=('auto', 'eco', 'performance', 'mem'), default='auto')
    parser.add_argument('--symbols', nargs='+', help='normalized exchange codes, e.g. sz300949 sh600000')
    parser.add_argument('--periods', nargs='+', choices=sorted(PERIODS), default=['day'])
    parser.add_argument('--limit', type=int, default=3, help='maximum distinct securities, default 3')
    parser.add_argument('--max-bars', type=int, default=30000, help='reject larger panels; never silently truncate')
    parser.add_argument('--cutoff', help='timezone-aware ISO closing timestamp')
    parser.add_argument('--verify-serial', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = run_batch(args.archive_dir, args.output_dir, workers=args.workers, mode=args.mode,
                           symbols=args.symbols, periods=args.periods, limit=args.limit,
                           max_bars=args.max_bars, cutoff=args.cutoff, verify_serial=args.verify_serial)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps({key: result[key] for key in ('state', 'backend', 'gpu_active', 'workers',
                                                 'securities', 'requested', 'completed', 'failed', 'bars', 'compute_seconds')},
                     ensure_ascii=False))
    return 0 if result['state'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
