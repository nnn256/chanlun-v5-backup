"""Inventory and export existing, verified TDX history without live requests.

Only a narrow cache layout is admitted. Exports contain selected price files,
sanitized provider metadata and a manifest; application settings, databases,
process state and arbitrary paths are never included.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from datetime import date, datetime, timezone
import csv
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

from .store import ROOT, STATE

PERIODS = {'day': 'day', '1m': 'minute1', '5m': 'minute5', '15m': 'minute15',
           '30m': 'minute30', '60m': 'hour', 'week': 'week', 'month': 'month',
           'quarter': 'quarter', 'year': 'year'}
ALIASES = {folder: period for period, folder in PERIODS.items()}
ALIASES.update({period: period for period in PERIODS})
SYMBOL = re.compile(r'(?:sh|sz|bj)\d{6}')
SHA = re.compile(r'[a-fA-F0-9]{64}')
MAX_METADATA_BYTES = 1024 * 1024
MAX_EXPANDED_FILE_BYTES = 512 * 1024 * 1024
MAX_EXPORT_SOURCE_BYTES = 8 * 1024**3
DISK_RESERVE_BYTES = 2 * 1024**3
INVENTORY_TTL = 15
MAX_INVENTORY_CACHE_BYTES = 8 * 1024 * 1024
LOCK = threading.RLock()
FLIGHTS = {}
INVENTORY_CACHE = OrderedDict()


def _period(value):
    if value == 'all': return 'all'
    if not isinstance(value, str) or value not in ALIASES:
        raise ValueError('unsupported history period')
    return ALIASES[value]


def _symbol(value):
    if value is not None and (not isinstance(value, str) or not SYMBOL.fullmatch(value)):
        raise ValueError('history symbol must be a canonical sh/sz/bj security code')
    return value


def _safe(path, root=None):
    root = Path(ROOT if root is None else root).resolve()
    path = Path(path)
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('history path leaves the project data directory')
    current = path.absolute()
    while current != root and current.is_relative_to(root):
        if current.is_symlink(): raise ValueError('linked history files are not exported')
        current = current.parent
    return resolved


def _cache_roots():
    root = Path(ROOT).resolve()
    candidates = [root / 'market_data']
    jobs = root / 'runtime/workbench/jobs'
    if jobs.is_dir():
        for folder in sorted(jobs.iterdir()):
            try:
                if folder.is_dir() and not folder.is_symlink(): candidates.append(_safe(folder / 'cache'))
            except (OSError, ValueError): continue
    result = []
    for path in candidates:
        try:
            if (path / 'tdx').is_dir(): result.append(_safe(path))
        except (OSError, ValueError): continue
    return result


def _time(value):
    if not isinstance(value, str): return None
    try:
        point = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if point.tzinfo is None: return None
        return point.astimezone(timezone.utc)
    except (ValueError, OverflowError): return None


def _date(value):
    if not isinstance(value, str): return None
    try: return date.fromisoformat(value)
    except ValueError: return None


def _candidate(cache, period, metadata_path, directories=None, project_root=None):
    def cache_file(path, kind):
        # The three parent directories were boundary-checked once by _scan.
        # Repeating Windows junction resolution on every ancestor of every
        # small file dominates a full-market metadata inventory. Reject leaf
        # links here; export repeats the complete boundary check before reads.
        if directories is None:return _safe(path)
        if path.parent != directories[kind] or path.is_symlink():
            raise ValueError('linked or misplaced history files are not exported')
        return path
    metadata_path = cache_file(metadata_path, 'metadata')
    if not 0 < metadata_path.stat().st_size <= MAX_METADATA_BYTES:
        raise ValueError('metadata size is invalid')
    raw = metadata_path.read_bytes();meta = json.loads(raw.decode('utf-8-sig'))
    code = metadata_path.stem
    if not SYMBOL.fullmatch(code) or not isinstance(meta, dict) or meta.get('symbol') != code:
        raise ValueError('metadata security identity is invalid')
    declared = meta.get('period', (meta.get('provider_meta') or {}).get('type', 'day'))
    if _period(declared) != period or meta.get('source') != 'tdx' or meta.get('adjustment') != 'unadjusted':
        raise ValueError('metadata period, provider or adjustment is invalid')
    checksum = meta.get('csv_sha256')
    if not isinstance(checksum, str) or not SHA.fullmatch(checksum):
        raise ValueError('metadata has no CSV checksum')
    folder = cache / 'tdx' / PERIODS[period]
    paths = [folder / 'ohlcv' / (code + suffix) for suffix in ('.csv', '.csv.gz')]
    paths = [p for p in paths if p.is_file()]
    if len(paths) != 1: raise ValueError('expected one CSV file for metadata')
    csv_path = cache_file(paths[0], 'ohlcv');size = csv_path.stat().st_size
    if not size: raise ValueError('CSV file is empty')
    if csv_path.suffix == '.gz' and not SHA.fullmatch(str(meta.get('csv_storage_sha256', ''))):
        raise ValueError('compressed CSV has no storage checksum')
    first = _time(meta.get('first_close'));last = _time(meta.get('last_close'))
    first_date = _date(meta.get('first_date'));last_date = _date(meta.get('last_date'))
    if first is None and first_date is None or last is None and last_date is None:
        raise ValueError('metadata has no valid coverage dates')
    first_label = first.isoformat() if first else first_date.isoformat()
    last_label = last.isoformat() if last else last_date.isoformat()
    if first_label[:10] > last_label[:10]: raise ValueError('metadata coverage is reversed')
    closed = meta.get('closed_rows')
    if type(closed) is not int or closed <= 0: raise ValueError('metadata closed row count is invalid')
    raw_path = folder / 'raw' / (code + '.json.gz')
    raw_available = raw_path.is_file()
    if raw_available: raw_path = cache_file(raw_path, 'raw')
    raw_verified_possible = raw_available and SHA.fullmatch(str(meta.get('raw_storage_sha256', ''))) is not None
    capture = _time(meta.get('received_at')) or _time(meta.get('requested_at'))
    return {'symbol': code, 'period': period, 'csv_path': csv_path, 'metadata_path': metadata_path,
        'raw_path': raw_path if raw_verified_possible else None, 'metadata': meta,
        'metadata_sha256': hashlib.sha256(raw).hexdigest(), 'csv_sha256': checksum.lower(),
        'stored_bytes': size + len(raw) + (raw_path.stat().st_size if raw_verified_possible else 0),
        'first': first_label, 'last': last_label, 'closed_rows': closed,
        'rank': (int(raw_verified_possible), last_label[:10], closed,
                 capture.timestamp() if capture else 0., csv_path.stat().st_mtime_ns),
        'source_relative': metadata_path.relative_to(project_root or Path(ROOT).resolve()).as_posix()}


def _scan(period, symbol):
    chosen = {} ; invalid = []
    project_root=Path(ROOT).resolve()
    requested = list(PERIODS) if period == 'all' else [period]
    for cache in _cache_roots():
        for item_period in requested:
            folder = cache / 'tdx' / PERIODS[item_period] / 'metadata'
            if not folder.is_dir(): continue
            try:
                parent=folder.parent
                directories={kind:_safe(parent/kind) for kind in ('metadata','ohlcv','raw')}
                folder=directories['metadata']
            except (OSError,ValueError) as error:
                invalid.append({'symbol':symbol,'period':item_period,'error':type(error).__name__+': '+str(error)})
                continue
            paths = [folder / (symbol + '.json')] if symbol else sorted(folder.glob('*.json'))
            for path in paths:
                if not path.is_file(): continue
                try:
                    item = _candidate(cache, item_period, path, directories, project_root)
                    chosen.setdefault((item['symbol'], item['period']), []).append(item)
                except (OSError, ValueError, TypeError, AttributeError) as error:
                    invalid.append({'symbol': path.stem, 'period': item_period,
                                    'error': type(error).__name__ + ': ' + str(error)})
    for items in chosen.values(): items.sort(key=lambda item: item['rank'], reverse=True)
    return chosen, invalid


def _public(item, alternatives):
    return {'symbol': item['symbol'], 'period': item['period'], 'source': 'tdx', 'adjustment': 'unadjusted',
        'first': item['first'], 'last': item['last'], 'closed_rows': item['closed_rows'],
        'csv_sha256': item['csv_sha256'], 'stored_bytes': item['stored_bytes'],
        'raw_available': item['raw_path'] is not None, 'alternative_sources': alternatives,
        'source_relative': item['source_relative'], 'content_hash_verified': False}


def history_inventory(period='day', symbol=None, *, offset=0, limit=200, refresh=False):
    period = _period(period);symbol = _symbol(symbol)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('history inventory pagination is invalid')
    key = (str(Path(ROOT).resolve()), period, symbol)
    with LOCK: cached = INVENTORY_CACHE.get(key)
    if refresh or cached is None or time.monotonic() - cached[0] >= INVENTORY_TTL:
        sources, invalid = _scan(period, symbol)
        rows = [_public(items[0], len(items)-1) for _, items in sorted(sources.items())]
        data = {'schema': 'local_history_inventory_v1', 'period': period, 'symbol': symbol,
            'total': len(rows), 'securities': len({row['symbol'] for row in rows}),
            'estimated_source_bytes': sum(row['stored_bytes'] for row in rows),
            'raw_available': sum(row['raw_available'] for row in rows), 'rows': rows,
            'invalid_sources_count': len(invalid), 'invalid_sources_preview': invalid[:10],
            'network_used': False, 'algorithm_calculated': False,
            'semantics': 'metadata and file-pair inventory; export verifies source content hashes and CSV rows',
            'coverage_claim': 'available saved histories only; not complete historical exchange membership or listing-inception coverage'}
        raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()
        with LOCK:
            INVENTORY_CACHE.pop(key,None)
            if len(raw)<=MAX_INVENTORY_CACHE_BYTES:
                INVENTORY_CACHE[key] = (time.monotonic(), raw);INVENTORY_CACHE.move_to_end(key)
                while len(INVENTORY_CACHE)>8 or sum(len(item[1]) for item in INVENTORY_CACHE.values())>MAX_INVENTORY_CACHE_BYTES:
                    INVENTORY_CACHE.popitem(last=False)
        cached = (time.monotonic(), raw)
    data = json.loads(cached[1]);all_rows = data.pop('rows')
    data.update(offset=offset, limit=limit, rows=all_rows[offset:offset+limit],
                remaining=max(0, len(all_rows)-offset-limit), cache_age_seconds=round(time.monotonic()-cached[0], 2))
    return data


def _hash(path, *, decompressed=False, maximum=MAX_EXPANDED_FILE_BYTES):
    digest = hashlib.sha256();count = 0
    opener = gzip.open if decompressed and path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            count += len(block)
            if maximum is not None and count > maximum: raise ValueError('history file exceeds expanded size limit')
            digest.update(block)
    return digest.hexdigest(), count


def _verify_csv(item):
    path = _safe(item['csv_path']);meta = item['metadata']
    stored, _ = _hash(path)
    if path.suffix == '.gz' and stored != meta['csv_storage_sha256'].lower():
        raise ValueError('compressed CSV storage checksum mismatch')
    plain, _ = _hash(path, decompressed=True)
    if plain != item['csv_sha256']: raise ValueError('CSV content checksum mismatch')
    opener = gzip.open if path.suffix == '.gz' else open
    rows = closed = 0;previous = None;first = last = None
    first_closed = last_closed = None
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream);headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not {'closed_at','open','high','low','close'} <= set(headers):
            raise ValueError('history CSV headers are invalid')
        for row in reader:
            if None in row: raise ValueError('history CSV contains extra fields')
            moment = _time(row['closed_at'])
            if moment is None or previous is not None and moment <= previous:
                raise ValueError('history CSV timestamps are not strictly increasing with timezone')
            previous = moment
            values = [float(row[name]) for name in ('open','high','low','close')]
            if not all(math.isfinite(v) and v > 0 for v in values): raise ValueError('history CSV has invalid OHLC')
            op, high, low, close = values
            if high < max(op, low, close) or low > min(op, close): raise ValueError('history CSV OHLC range is invalid')
            if row.get('volume'):
                volume = float(row['volume'])
                if not math.isfinite(volume) or volume < 0: raise ValueError('history CSV volume is invalid')
            flag = (row.get('is_closed') or 'true').lower()
            if flag not in {'true','false','1','0'}: raise ValueError('history CSV closed flag is invalid')
            if row.get('symbol') and row['symbol'] != item['symbol']: raise ValueError('history CSV security differs')
            if row.get('period') and _period(row['period']) != item['period']: raise ValueError('history CSV period differs')
            stamp = moment.isoformat();first = first or stamp;last = stamp;rows += 1
            if flag in {'true','1'}:
                closed += 1;first_closed = first_closed or stamp;last_closed = stamp
    if not rows or closed != item['closed_rows']: raise ValueError('history CSV closed rows differ from metadata')
    # Daily metadata names the closed-date prefix; minute metadata names its
    # observed boundaries. Preserve open suffix rows while verifying receipts.
    if item['period'] == 'day':
        if first_closed[:10] != item['first'][:10] or last_closed[:10] != item['last'][:10]:
            raise ValueError('daily CSV coverage differs from metadata')
    elif first[:10] != item['first'][:10] or last[:10] != item['last'][:10]:
        raise ValueError('intraday CSV coverage differs from metadata')
    return {'stored_sha256': stored, 'csv_sha256': plain, 'rows': rows, 'closed_rows': closed,
            'forming_rows': rows-closed, 'first_close': first, 'last_close': last,
            'first_closed': first_closed, 'last_closed': last_closed}


def _verify(item):
    coverage = _verify_csv(item);raw_info = None
    if item['raw_path'] is not None:
        path = _safe(item['raw_path']);stored, _ = _hash(path)
        if stored != item['metadata']['raw_storage_sha256'].lower(): raise ValueError('raw response storage checksum mismatch')
        raw_hash, expanded = _hash(path, decompressed=True)
        expected = item['metadata'].get('response_sha256')
        if expected and (not SHA.fullmatch(str(expected)) or raw_hash != expected.lower()):
            raise ValueError('raw provider response checksum mismatch')
        raw_info = {'stored_sha256': stored, 'response_sha256': raw_hash, 'expanded_bytes': expanded}
    return coverage, raw_info


def _metadata(item, coverage, csv_entry, raw_entry, raw_info):
    meta = item['metadata']
    # Whitelist scalar measurement fields; never copy request URL, arbitrary
    # notes or absolute file paths from the provider metadata into a ZIP.
    result = {'symbol': item['symbol'], 'period': PERIODS[item['period']], 'source': 'tdx',
        'adjustment': 'unadjusted', 'csv_path': csv_entry, 'csv_sha256': coverage['csv_sha256'],
        'closed_rows': coverage['closed_rows'], 'rows': coverage['rows'],
        'first_close': coverage['first_close'], 'last_close': coverage['last_close'],
        'first_date': coverage['first_closed'][:10], 'last_date': coverage['last_closed'][:10],
        'coverage_claim': 'complete selected saved file; listing-inception and missing-session absence unproved',
        'identity_provenance': 'saved local metadata and content hashes; upstream authenticity not independently certified',
        'original_metadata_sha256': item['metadata_sha256'],
        'history_export_schema': 'verified_local_history_zip_v1'}
    for name in ('price_unit','volume_unit','original_volume_unit','amount_unit','session_timezone','normalization_schema'):
        value = meta.get(name)
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_+. /:-]{1,100}', value): result[name] = value
    for name in ('requested_at','received_at','as_of','cache_run_as_of'):
        if _time(meta.get(name)) is not None: result[name] = meta[name]
    if item['csv_path'].suffix == '.gz': result.update(csv_compression='gzip', csv_storage_sha256=coverage['stored_sha256'])
    if raw_entry:
        result.update(raw_path=raw_entry, raw_storage_sha256=raw_info['stored_sha256'],
                      response_sha256=raw_info['response_sha256'])
    return result


def create_export(scope='all', period='day', symbol=None, *, progress=None):
    period = _period(period);symbol = _symbol(symbol)
    if scope == 'selected': raise ValueError('selected multi-security export is not supported; use stock with one symbol or all')
    if scope not in {'all','stock'}: raise ValueError('history export scope is invalid')
    if scope == 'stock' and symbol is None: raise ValueError('stock history export needs a symbol')
    if scope == 'all' and symbol is not None: raise ValueError('all history export cannot also select a symbol')
    identity = (str(Path(ROOT).resolve()), scope, period, symbol)
    with LOCK:
        pending = FLIGHTS.get(identity);owner = pending is None
        if owner: pending = Future();FLIGHTS[identity] = pending
    if not owner: return json.loads(pending.result())
    try:
        result = _create(scope, period, symbol, progress)
        pending.set_result(json.dumps(result, ensure_ascii=False).encode())
        return result
    except BaseException as error:
        pending.set_exception(error);raise
    finally:
        with LOCK:
            if FLIGHTS.get(identity) is pending: FLIGHTS.pop(identity, None)


def _create(scope, period, symbol, progress):
    choices, invalid = _scan(period, symbol)
    if not choices: raise ValueError('no saved history sources are available for this export')
    estimated = sum(max(item['stored_bytes'] for item in items) for items in choices.values())
    if estimated > MAX_EXPORT_SOURCE_BYTES: raise ValueError('history export exceeds the configured 8GiB source budget; select a period or security')
    directory = _safe(Path(STATE) / 'history-exports')
    directory.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(directory).free < estimated + DISK_RESERVE_BYTES:
        raise ValueError('not enough free disk space for history ZIP and the 2GiB reserve')
    ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-') + uuid.uuid4().hex[:12]
    name = f'history-{period}-{symbol or "all"}-{ident}.zip'
    final = directory / name;temporary = directory / (name + '.partial')
    sources = [];entries = [];known = {};errors = [];attempted = 0
    complete=False
    try:
        with ZipFile(temporary, 'x', compression=ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
            for _, items in sorted(choices.items()):
                selected = None
                for item in items:
                    try:
                        coverage, raw_info = _verify(item);selected = item;break
                    except (OSError, ValueError, TypeError, KeyError, EOFError, csv.Error) as error:
                        errors.append({'symbol': item['symbol'], 'period': item['period'],
                                       'error': type(error).__name__ + ': ' + str(error)})
                attempted += 1
                if selected is None:
                    if progress: progress({'processed': attempted, 'total': len(choices), 'exported': len(sources), 'failed': attempted-len(sources)})
                    continue
                if shutil.disk_usage(directory).free < DISK_RESERVE_BYTES:
                    raise ValueError('free disk space fell below the history export reserve')
                folder = 'tdx/' + PERIODS[item['period']]
                def add_file(path, target, checksum):
                    if checksum in known: return known[checksum]
                    path = _safe(path)
                    with path.open('rb') as stream, archive.open(target, 'w', force_zip64=True) as dest:
                        digest = hashlib.sha256();count = 0
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            dest.write(block);digest.update(block);count += len(block)
                    if digest.hexdigest() != checksum: raise ValueError('history source changed while writing ZIP')
                    known[checksum] = target;entries.append({'path': target, 'sha256': checksum, 'bytes': count})
                    return target
                csv_name = add_file(item['csv_path'], folder + '/ohlcv/' + item['csv_path'].name, coverage['stored_sha256'])
                raw_name = add_file(item['raw_path'], folder + '/raw/' + item['raw_path'].name, raw_info['stored_sha256']) if raw_info else None
                sanitized = _metadata(item, coverage, csv_name, raw_name, raw_info)
                meta_name = folder + '/metadata/' + item['symbol'] + '.json'
                meta_raw = json.dumps(sanitized, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
                archive.writestr(meta_name, meta_raw)
                entries.append({'path': meta_name, 'sha256': hashlib.sha256(meta_raw).hexdigest(), 'bytes': len(meta_raw)})
                sources.append({'symbol': item['symbol'], 'period': item['period'], 'csv_path': csv_name,
                    'metadata_path': meta_name, 'raw_path': raw_name, 'coverage': coverage,
                    'content_hash_verified': True, 'alternative_sources': len(items)-1,
                    'source_relative': item['source_relative'], 'original_metadata_sha256': item['metadata_sha256']})
                if progress: progress({'processed': attempted, 'total': len(choices), 'exported': len(sources), 'failed': attempted-len(sources)})
            if not sources: raise ValueError('no history sources passed content verification')
            manifest = {'schema': 'verified_local_history_zip_v1', 'created_at': datetime.now(timezone.utc).isoformat(),
                'scope': scope, 'period': period, 'symbol': symbol, 'requested_pairs': len(choices),
                'exported_pairs': len(sources), 'failed_pairs': len(choices)-len(sources),
                'sources': sources, 'files': entries, 'invalid_metadata_count': len(invalid),
                'rejected_source_count': len(errors), 'rejected_source_preview': errors[:20],
                'network_used': False, 'algorithm_calculated': False,
                'deduplication': 'one validated whole source per security/period; identical stored content written once and referenced by manifest',
                'coverage_claim': 'available saved files only; no listing-inception or missing-session absence proof',
                'paths': 'relative ZIP member references; application settings, databases and request URLs excluded'}
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2).encode())
        # CRC checks read the completed ZIP without holding full histories in RAM.
        with ZipFile(temporary) as archive:
            if archive.testzip() is not None: raise ValueError('history ZIP integrity check failed')
        temporary.replace(final)
        checksum, _ = _hash(final, maximum=None)
        receipt = {'id': ident, 'name': name, 'path': str(final), 'bytes': final.stat().st_size,
            'sha256': checksum, 'files': len(entries)+1, 'scope': scope, 'period': period, 'symbol': symbol,
            'coverage': {'requested_pairs': len(choices), 'exported_pairs': len(sources),
                'failed_pairs': len(choices)-len(sources), 'securities': len({x['symbol'] for x in sources}),
                'closed_rows': sum(x['coverage']['closed_rows'] for x in sources)},
            'state': 'ready' if len(sources) == len(choices) else 'partial',
            'network_used': False, 'algorithm_calculated': False}
        final.with_suffix('.receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        complete=True
        return receipt
    except BaseException:
        temporary.unlink(missing_ok=True)
        if not complete:
            final.unlink(missing_ok=True)
            final.with_suffix('.receipt.json').unlink(missing_ok=True)
        raise


def export_download_path(name):
    """Resolve only a completed ZIP created by this exporter, never a raw path."""
    if not isinstance(name, str) or not re.fullmatch(
            r'history-(?:all|day|1m|5m|15m|30m|60m|week|month|quarter|year)-(?:all|(?:sh|sz|bj)\d{6})-\d{8}T\d{6}-[a-f0-9]{12}\.zip', name):
        raise ValueError('invalid history export name')
    path = _safe(Path(STATE) / 'history-exports' / name)
    receipt_path = path.with_suffix('.receipt.json')
    if not path.is_file() or not receipt_path.is_file(): raise ValueError('completed history export does not exist')
    receipt = json.loads(_safe(receipt_path).read_text(encoding='utf-8'))
    if receipt.get('name') != name or receipt.get('bytes') != path.stat().st_size:
        raise ValueError('history export receipt identity differs')
    return path
