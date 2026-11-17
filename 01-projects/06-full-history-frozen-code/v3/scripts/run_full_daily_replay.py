"""Resumable, serial v3 causal replay of every selected cached daily candle.

Inputs are a current-universe JSON and a frozen V4 resolve_sources() result.
This runner never requests market data, truncates history, or changes engine
rules. It reuses v3's recursive prefix ledger and existing costed portfolio.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import gc
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROFILE = 'liangce_full_daily_recursive_causal_v1'
SYMBOL = re.compile(r'^(?:sh|sz|bj)\d{6}$')
SHA = re.compile(r'^[a-fA-F0-9]{64}$')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def atomic_bytes(path, raw):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(raw);temporary.replace(path)


def atomic_json(path, value):
    atomic_bytes(path, canonical(value))


@contextmanager
def run_lock(path):
    """An OS file lock is released even if a previous process was killed."""
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0);stream.write(b' ');stream.flush();stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('another daily replay runner holds the output lock') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


def code_identity():
    paths = [*sorted((ROOT/'chanmodel').rglob('*.py')),
             ROOT/'web/precision_backtest.py', Path(__file__).resolve()]
    files = {path.relative_to(ROOT).as_posix(): file_hash(path) for path in paths}
    return {'sha256': hashlib.sha256(canonical(files)).hexdigest(), 'files': files}


def inputs(universe_path, sources_path):
    universe = json.loads(Path(universe_path).read_text(encoding='utf-8-sig'))
    records = universe.get('records') if isinstance(universe, dict) else universe
    if not isinstance(records, list) or not records:
        raise ValueError('universe requires nonempty security records')
    seen = set()
    for record in records:
        symbol = record.get('symbol') if isinstance(record, dict) else None
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol) or symbol in seen:
            raise ValueError('universe has an invalid or duplicate security symbol')
        seen.add(symbol)
    selection = json.loads(Path(sources_path).read_text(encoding='utf-8-sig'))
    if not isinstance(selection, dict) or not isinstance(selection.get('sources'), dict) or not isinstance(selection.get('source_details'), dict):
        raise ValueError('source manifest requires resolve_sources sources and source_details')
    return records, selection


def read_daily(record, selection):
    from chanmodel.model import Candle, time_value
    symbol = record['symbol']
    cache = selection['sources'].get(symbol)
    detail = selection['source_details'].get(symbol)
    if cache is None or detail is None:
        return None, {'state': 'source_unavailable', 'symbol': symbol,
                      'error': 'no daily source selected in the frozen source manifest'}
    cache = Path(cache).resolve()
    path = cache/'tdx/day/ohlcv'/f'{symbol}.csv'
    metadata_path = cache/'tdx/day/metadata'/f'{symbol}.json'
    raw_metadata = metadata_path.read_bytes()
    if detail.get('metadata_sha256') and hashlib.sha256(raw_metadata).hexdigest() != detail['metadata_sha256']:
        raise ValueError('daily metadata changed after source selection')
    meta = json.loads(raw_metadata.decode('utf-8-sig'))
    if (meta.get('symbol') != symbol or meta.get('source') != 'tdx'
            or meta.get('adjustment') != 'unadjusted'
            or meta.get('period', meta.get('provider_meta', {}).get('type', 'day')) != 'day'):
        raise ValueError('daily metadata security, period, provider or adjustment mismatch')
    expected = meta.get('csv_sha256')
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError('daily metadata requires a CSV SHA-256')
    selected_hash = detail.get('declared_csv_sha256')
    if selected_hash and selected_hash.lower() != expected.lower():
        raise ValueError('daily CSV declaration changed after source selection')
    if file_hash(path) != expected.lower():
        raise ValueError('daily CSV SHA-256 mismatch')
    bars = [];previous = None;forming_seen = False;rows = 0
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not {'closed_at','open','high','low','close','is_closed'} <= set(headers):
            raise ValueError('daily CSV requires unique OHLC, close-time and is_closed headers')
        for row in reader:
            rows += 1
            stamp = row['closed_at'];moment = time_value(stamp)
            if previous is not None and moment <= previous:
                raise ValueError('daily CSV closing timestamps must strictly increase')
            previous = moment
            flag = str(row['is_closed']).lower()
            if flag not in {'true','false','1','0'}:
                raise ValueError('daily CSV is_closed must be true/false or 1/0')
            closed = flag in {'true','1'}
            if not closed:
                forming_seen = True;continue
            if forming_seen:
                raise ValueError('closed daily candle follows a forming candle')
            if moment > datetime.now(timezone.utc):
                raise ValueError('daily CSV contains a future closed candle')
            volume = float(row['volume']) if row.get('volume') else None
            bars.append(Candle(len(bars), *(float(row[key]) for key in ('open','high','low','close')),
                               stamp, volume, True))
    if type(meta.get('closed_rows')) is not int or meta['closed_rows'] != len(bars):
        raise ValueError('daily metadata closed_rows differs from full CSV history')
    if not bars:
        return None, {'state':'source_unavailable','symbol':symbol,'error':'daily source contains no closed candles'}
    if meta.get('first_date') != bars[0].closed_at[:10] or meta.get('last_date') != bars[-1].closed_at[:10]:
        raise ValueError('daily metadata coverage differs from CSV endpoints')
    receipt = {'symbol':symbol,'source':'tdx','adjustment':'unadjusted','csv_path':str(path),
               'metadata_path':str(metadata_path),'csv_sha256':expected.lower(),
               'metadata_sha256':hashlib.sha256(raw_metadata).hexdigest(),
               'bars':len(bars),'first':bars[0].closed_at,'last':bars[-1].closed_at,
               'forming_rows_excluded':rows-len(bars),'full_saved_history':True,
               'coverage_claim':'all closed daily candles in the selected cache; listing-inception coverage unverified',
               'corporate_actions':[],'split_adjustment_verified':False}
    return bars, receipt


class StopRequested(Exception):
    pass


def analyze(record, selection, progress=None):
    from web.precision_backtest import prefix_events, portfolio, definition_fields
    bars, receipt = read_daily(record, selection)
    if bars is None:
        return receipt, None
    symbol = record['symbol']
    if len(bars) < 3:
        return {**record, **receipt, 'state':'insufficient_history',
                'error':'fewer than 3 closed daily candles; no structure result asserted'}, None
    replay = prefix_events(bars, 'day', 'segment', progress)
    fills = portfolio(symbol, 'day', bars, replay['signal_events'], receipt, bars, receipt)
    fills['limitations'].append('Corporate action history is not independently certified; unadjusted distribution gaps are not corrected.')
    for event in replay['confirmations']:
        if not 0 <= event['anchor'] <= event['observed_index'] < len(bars):
            raise ValueError('causal replay references a future or out-of-range candle')
    for order in fills['orders']:
        if order['state']=='filled' and (order['time']<order['signal_time'] or order['bar_close_time']<=order['signal_time']):
            raise ValueError('portfolio fill precedes the visible signal or uses its own candle')
    result = {**record, **receipt, 'state':'complete', 'period':'day','resolution':'segment',
              **definition_fields('day','segment'),'definition_mode':replay['definition_mode'],
              'confirmation_count':len(replay['confirmations']),
              'signal_event_count':len(replay['signal_events']),
              'invalidation_count':sum(event['event']=='invalidated' for event in replay['signal_events']),
              'withdrawal_count':sum(event['event']=='withdrawn' for event in replay['signal_events']),
              'metrics':fills['metrics'],'strict_original_equivalence_proven':False,
              'original_data_certified':False,'execution_allowed':False}
    return result, {'summary':result,'source_receipt':receipt,'replay':replay,'simulation':fills}


def memory_available():
    from core.hardware_compute import hardware_status
    return hardware_status(include_gpu=False)['memory'].get('available_bytes')


def run(universe, source_manifest, output, *, resume=False, retry_failed=False,
        min_free_memory_mb=768, poll_seconds=1):
    if not math.isfinite(min_free_memory_mb) or min_free_memory_mb < 0:
        raise ValueError('min-free-memory-mb must be finite and nonnegative')
    records, selection = inputs(universe, source_manifest)
    out = Path(output).resolve();out.mkdir(parents=True, exist_ok=True)
    frozen_code = code_identity()
    manifest = {'profile':PROFILE,'universe_sha256':file_hash(universe),
                'source_manifest_sha256':file_hash(source_manifest),'symbols':[r['symbol'] for r in records],
                'algorithm_code':frozen_code,'period':'day','resolution':'segment',
                'history':'all selected saved closed candles, no rolling window or cutoff truncation',
                'workers':1,'backend':'serial_cpu','gpu_active':False,'network_used':False,
                'execution_allowed':False}
    with run_lock(out/'runner.lock'):
        manifest_path = out/'manifest.json'
        if manifest_path.exists():
            if not resume:
                raise ValueError('output already has a run; use --resume')
            if json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
                raise ValueError('resume input or algorithm identity differs from frozen manifest')
        elif resume:
            raise ValueError('--resume requires an existing run manifest')
        else:
            atomic_json(manifest_path, manifest)
        results = {}
        checkpoint = out/'checkpoint.jsonl'
        if checkpoint.exists():
            for line in checkpoint.read_text(encoding='utf-8').splitlines():
                try:
                    item = json.loads(line);symbol = item['symbol']
                    if item['state'] == 'complete':
                        artifact = Path(item['artifact'])
                        if not artifact.is_file() or file_hash(artifact) != item['artifact_sha256']:
                            continue
                    if retry_failed and item['state'] == 'failed':
                        continue
                    results[symbol] = item
                except (ValueError,KeyError,OSError):
                    continue
        started = time.monotonic();state = 'running';active = None
        def publish(stage='running', **extra):
            counts = Counter(item['state'] for item in results.values())
            summary = {'profile':PROFILE,'state':stage,'updated_at':now(),'requested':len(records),
                       'processed':len(results),'remaining':len(records)-len(results),'counts':dict(counts),
                       'bars':sum(item.get('bars',0) for item in results.values()),
                       'confirmations':sum(item.get('confirmation_count',0) for item in results.values()),
                       'processing_complete':len(results)==len(records),
                       'successful_coverage_complete':counts.get('complete',0)==len(records),
                       'active':active,'workers':1,'gpu_active':False,'network_used':False,
                       'execution_allowed':False,'elapsed_seconds':round(time.monotonic()-started,1),**extra}
            atomic_json(out/'summary.json',summary);return summary
        with checkpoint.open('a',encoding='utf-8') as log:
            for record in records:
                if record['symbol'] in results:
                    continue
                if (out/'STOP').exists():
                    state = 'stopped';break
                if code_identity()['sha256'] != frozen_code['sha256']:
                    state = 'stopped_code_changed';break
                while True:
                    available = memory_available()
                    if available is None or available >= min_free_memory_mb*1024**2:
                        break
                    publish('waiting_memory',available_memory_bytes=available)
                    if (out/'STOP').exists():
                        state = 'stopped';break
                    time.sleep(poll_seconds)
                if state != 'running':
                    break
                symbol = record['symbol'];active={'symbol':symbol,'bars_done':0,'bars_total':None}
                publish()
                def progress(done,total):
                    active.update(bars_done=done,bars_total=total)
                    publish()
                    if (out/'STOP').exists():
                        raise StopRequested()
                task_started = time.monotonic()
                detail = None
                try:
                    item, detail = analyze(record, selection, progress)
                    item['seconds'] = round(time.monotonic()-task_started,3)
                    if detail is not None:
                        path = out/'stocks'/f'{symbol}.json.gz'
                        atomic_bytes(path,gzip.compress(canonical(detail),mtime=0))
                        item.update(artifact=str(path),artifact_sha256=file_hash(path))
                except StopRequested:
                    state = 'stopped';break
                except Exception as error:
                    item = {**record,'state':'failed','error':f'{type(error).__name__}: {error}',
                            'seconds':round(time.monotonic()-task_started,3)}
                results[symbol] = item
                log.write(canonical(item).decode()+'\n');log.flush();os.fsync(log.fileno())
                active = None
                summary = publish()
                print(json.dumps({'symbol':symbol,'state':item['state'],'processed':len(results),
                                  'requested':len(records),'bars':item.get('bars',0)},ensure_ascii=False),flush=True)
                detail = None
                gc.collect()
        active = None
        final = publish('completed' if len(results)==len(records) else state)
        atomic_json(out/'results.json', {'records':list(results.values()),'summary':final})
        return final


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe',type=Path,required=True)
    parser.add_argument('--source-manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--retry-failed',action='store_true')
    parser.add_argument('--min-free-memory-mb',type=float,default=768)
    options=parser.parse_args(argv)
    result=run(options.universe,options.source_manifest,options.output,resume=options.resume,
               retry_failed=options.retry_failed,min_free_memory_mb=options.min_free_memory_mb)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['successful_coverage_complete'] else 2


if __name__=='__main__':
    raise SystemExit(main())
