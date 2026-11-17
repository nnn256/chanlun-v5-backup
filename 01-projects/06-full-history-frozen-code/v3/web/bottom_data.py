"""Auditable raw inputs for local bottom-exit research.

The dataset is a current-list sample, not a historical constituent universe.
Retrospectively fetched fund-flow dates do not prove original publication time.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import threading
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
CN = timezone(timedelta(hours=8))
DEFAULT_SEED = 20261113
FORCED_SYMBOLS = ('sz300949', 'sz000823')
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_DAILY_ROWS = 30000
_write_lock = threading.RLock()


def runtime_root():
    return Path(os.environ.get('LIANGCE_BOTTOM_RUNTIME', str(ROOT / '.runtime' / 'bottom-research')))


def now_iso():
    return datetime.now(CN).isoformat(timespec='seconds')


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_bytes(_json_bytes(value))
    temporary.replace(path)


def _object(raw):
    """Content-addressed raw bytes remain unchanged across refreshes."""
    digest = hashlib.sha256(raw).hexdigest()
    target = runtime_root() / 'raw' / (digest + '.json.gz')
    target.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        if target.exists():
            if hashlib.sha256(gzip.decompress(target.read_bytes())).hexdigest() != digest:
                raise ValueError('cached raw object hash mismatch')
        else:
            target.write_bytes(gzip.compress(raw, compresslevel=5, mtime=0))
    return digest, str(target.resolve())


def _read_object(receipt):
    path = Path(receipt['raw_path'])
    raw = gzip.decompress(path.read_bytes())
    if hashlib.sha256(raw).hexdigest() != receipt['raw_sha256']:
        raise ValueError('cached raw response integrity check failed')
    return json.loads(raw)


def _origin():
    origin = os.environ.get('LIANGCE_TDX_API') or os.environ.get('CHANLUN_TDX_BASE_URL')
    if not origin:
        # This is an explicit local bridge address, never an external secret.
        origin = 'http://127.0.0.1:18080'
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('TDX origin must be an HTTP(S) origin without query/fragment')
    return origin.rstrip('/')


def _request(url, timeout=45):
    parsed = urllib.parse.urlsplit(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if parsed.hostname in {'127.0.0.1', 'localhost', '::1'} else urllib.request.build_opener()
    requested = now_iso()
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'LiangceBottomResearch/1'})
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('provider response exceeds 32 MiB acquisition limit')
        receipt = {'url': url, 'requested_at': requested, 'received_at': now_iso(),
                   'http_status': response.status, 'content_type': response.headers.get('Content-Type'),
                   'response_bytes': len(raw)}
    receipt['raw_sha256'], receipt['raw_path'] = _object(raw)
    return json.loads(raw), receipt


def _code(value, benchmark=False):
    code = str(value).strip().lower()
    if not re.fullmatch(r'(sh|sz)\d{6}', code):
        raise ValueError('explicit sh/sz-prefixed six-digit code required')
    if not benchmark and not ((code.startswith('sh6')) or code.startswith(('sz0', 'sz30'))):
        raise ValueError('sample universe contains SH/SZ A-shares only')
    return code


def _price(value):
    try:
        number = float(Decimal(str(value)) / Decimal(1000))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError('invalid TDX protocol price') from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError('TDX protocol price must be positive and finite')
    return number


def normalize_daily(data, code, received_at, *, benchmark=False):
    rows = data.get('list', data.get('List'))
    declared = data.get('count', data.get('Count'))
    if not isinstance(rows, list) or not rows:
        raise ValueError('TDX daily endpoint returned no rows')
    if len(rows) > MAX_DAILY_ROWS:
        raise ValueError('TDX daily response exceeds 30000-row limit')
    if declared is None or int(declared) != len(rows):
        raise ValueError('TDX daily row count does not match declared total')
    observed = datetime.fromisoformat(received_at)
    if observed.tzinfo is None:
        raise ValueError('acquisition timestamp must include timezone')
    observed = observed.astimezone(CN)
    unique = {}
    rejected = []
    for source_position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('TDX daily row is not an object')
        label = str(row.get('Time', ''))
        try:
            point = datetime.fromisoformat(label.replace('Z', '+00:00'))
        except ValueError as error:
            raise ValueError('invalid TDX close timestamp: ' + label) from error
        if point.tzinfo is None:
            point = point.replace(tzinfo=CN)
        point = point.astimezone(CN)
        if point.date() > observed.date():
            raise ValueError('TDX response contains future session')
        point = point.replace(hour=15, minute=0, second=0, microsecond=0)
        try:
            o, h, l, c = [_price(row.get(field)) for field in ('Open', 'High', 'Low', 'Close')]
            volume = float(row.get('Volume') or 0) * (1 if benchmark else 100)
            if not math.isfinite(volume) or volume < 0:
                raise ValueError('invalid volume')
            if h < max(o, c, l) or l > min(o, c, h):
                raise ValueError('invalid OHLC envelope')
        except (ValueError, TypeError) as error:
            rejected.append({'source_position': source_position, 'date': point.date().isoformat(), 'reason': str(error)})
            continue
        item = {'closed_at': point.isoformat(), 'date': point.date().isoformat(),
                'date_cn': point.strftime('%Y-%m-%d %H:%M'), 'time': int(point.timestamp()) + 8 * 3600,
                'open': o, 'high': h, 'low': l, 'close': c, 'volume': volume,
                'amount_protocol_raw': row.get('Amount'), 'is_closed': point <= observed}
        key = point.isoformat()
        if key in unique and unique[key] != item:
            raise ValueError('conflicting duplicate TDX daily candle')
        unique[key] = item
    bars = [{**row, 'pos': i, 'source_index': i} for i, (_, row) in enumerate(sorted(unique.items()))]
    if not bars or not any(row['is_closed'] for row in bars):
        raise ValueError('no valid closed TDX daily candles')
    canonical = [[row[field] for field in ('closed_at', 'open', 'high', 'low', 'close', 'volume', 'is_closed')] for row in bars]
    metadata = {'source': 'oficcejo/tdx-api /api/index/all' if benchmark else 'oficcejo/tdx-api /api/kline-all/tdx',
                'adjustment': 'unadjusted', 'split_adjustment_verified': False,
                'price_unit': 'index_points' if benchmark else 'CNY',
                'volume_unit': 'provider_native_unspecified' if benchmark else 'shares',
                'source_price_unit': 'milli_index_points' if benchmark else 'milli_CNY',
                'source_volume_unit': 'provider_native_unspecified' if benchmark else 'lots',
                'amount_unit': 'provider_native_unspecified', 'scope': 'all_provider_native_pages',
                'source_rows': len(rows), 'count': len(bars), 'closed_count': sum(row['is_closed'] for row in bars),
                'forming_count': sum(not row['is_closed'] for row in bars), 'first': bars[0]['closed_at'],
                'last': bars[-1]['closed_at'], 'quarantined_rows': rejected, 'quarantined_count': len(rejected),
                'coverage_complete': not rejected, 'input_sha256': hashlib.sha256(_json_bytes(canonical)).hexdigest(),
                'historical_revision_audit': 'acquired_snapshot_only', 'execution_allowed': False,
                'limitations': ['current listed-symbol sample has survivorship bias',
                                'unadjusted OHLC can contain corporate-action discontinuities',
                                'provider all-history response does not prove listing-inception completeness']}
    return bars, metadata


@lru_cache(maxsize=1)
def _symbol_records():
    path = ROOT / 'data' / 'research' / 'symbols.json'
    raw = path.read_bytes()
    records = json.loads(raw)
    return records, hashlib.sha256(raw).hexdigest()


def _name(code):
    if code == 'sh000001':
        return '上证指数'
    return next((row['name'] for row in _symbol_records()[0] if row['symbol'] == code), code)


def _fetch(code, benchmark=False, refresh=False):
    code = _code(code, benchmark=benchmark)
    reference = runtime_root() / 'datasets' / (code + ('__index_day.json' if benchmark else '__day.json'))
    cached = json.loads(reference.read_text(encoding='utf-8')) if reference.is_file() else None
    if cached and not refresh:
        envelope = _read_object(cached)
        receipt = {key: cached[key] for key in ('url', 'requested_at', 'received_at', 'raw_sha256', 'raw_path')}
    else:
        endpoint = '/api/index/all' if benchmark else '/api/kline-all/tdx'
        url = _origin() + endpoint + '?' + urllib.parse.urlencode({'code': code, 'type': 'day'})
        envelope, receipt = _request(url, timeout=90)
    if not isinstance(envelope, dict) or envelope.get('code') != 0 or not isinstance(envelope.get('data'), dict):
        raise ValueError('TDX response envelope rejected: ' + str(envelope.get('message', 'malformed response'))[:160])
    bars, metadata = normalize_daily(envelope['data'], code, receipt['received_at'], benchmark=benchmark)
    metadata.update(receipt)
    metadata['dataset_ref'] = str(reference.resolve())
    result = {'symbol': code, 'name': _name(code), 'bars': bars, 'metadata': metadata}
    if refresh or cached is None:
        _atomic_json(reference, {**receipt, 'symbol': code, 'name': result['name'],
                                'benchmark': benchmark, 'input_sha256': metadata['input_sha256'],
                                'count': len(bars), 'closed_count': metadata['closed_count'],
                                'quarantined_count': metadata['quarantined_count']})
    return result


def fetch_daily(code, refresh=False):
    return _fetch(code, benchmark=False, refresh=refresh)


def fetch_tail(code, limit=10):
    """Acquire a bounded live tail without replacing its complete-history ref."""
    code = _code(code)
    if type(limit) is not int or not 1 <= limit <= 800:
        raise ValueError('TDX tail limit must be an integer in 1..800')
    url = _origin() + '/api/kline-history?' + urllib.parse.urlencode(
        {'code': code, 'type': 'day', 'limit': limit})
    envelope, receipt = _request(url, timeout=15)
    if not isinstance(envelope, dict) or envelope.get('code') != 0 or not isinstance(envelope.get('data'), dict):
        message = envelope.get('message', 'malformed response') if isinstance(envelope, dict) else 'malformed response'
        raise ValueError('TDX tail response envelope rejected: ' + str(message)[:160])
    returned_rows = envelope['data'].get('list', envelope['data'].get('List'))
    if isinstance(returned_rows, list) and len(returned_rows) > limit:
        raise ValueError('TDX tail returned more rows than the requested limit')
    bars, metadata = normalize_daily(envelope['data'], code, receipt['received_at'], benchmark=False)
    metadata.update(receipt)
    metadata.update(source='oficcejo/tdx-api /api/kline-history', scope='provider_recent_tail',
                    requested_limit=limit, full_history_reference_replaced=False)
    reference = runtime_root() / 'tails' / f'{code}__day_{receipt["raw_sha256"]}.json'
    metadata['tail_ref'] = str(reference.resolve())
    if not reference.exists():
        _atomic_json(reference, {**receipt, 'symbol': code, 'count': len(bars),
                                'input_sha256': metadata['input_sha256'], 'requested_limit': limit,
                                'closed_count': metadata['closed_count'],
                                'quarantined_count': metadata['quarantined_count']})
    return {'symbol': code, 'name': _name(code), 'bars': bars, 'metadata': metadata}


def fetch_benchmark(code='sh000001', refresh=False):
    return _fetch(code, benchmark=True, refresh=refresh)


def sample_symbols(count=120, seed=DEFAULT_SEED):
    if not 4 <= int(count) <= 1000:
        raise ValueError('sample size must be 4..1000')
    records, source_hash = _symbol_records()
    groups = defaultdict(list)
    for row in records:
        code, name = row.get('symbol', ''), str(row.get('name', ''))
        if 'ST' in name.upper() or '退' in name:
            continue
        group = 'STAR' if code.startswith('sh688') else 'SH_MAIN' if code.startswith('sh6') else 'CHINEXT' if code.startswith('sz30') else 'SZ_MAIN' if code.startswith('sz0') else None
        if group:
            groups[group].append({'symbol': code, 'code': code[2:], 'name': name, 'stratum': group})
    rng = random.Random(int(seed))
    order = ('SH_MAIN', 'STAR', 'SZ_MAIN', 'CHINEXT')
    selected = []
    for index, group in enumerate(order):
        candidates = sorted(groups[group], key=lambda row: row['symbol'])
        forced = [row for row in candidates if row['symbol'] in FORCED_SYMBOLS]
        remaining = [row for row in candidates if row['symbol'] not in FORCED_SYMBOLS]
        quota = int(count) // 4 + (index < int(count) % 4)
        selected.extend(forced + rng.sample(remaining, min(len(remaining), max(0, quota - len(forced)))))
    selected.sort(key=lambda row: row['symbol'])
    return {'seed': int(seed), 'requested_count': int(count), 'count': len(selected),
            'strata': dict(Counter(row['stratum'] for row in selected)), 'symbols': selected,
            'symbol_dictionary_sha256': source_hash, 'selection_time': now_iso(),
            'universe_semantics': 'fixed-seed stratified current dictionary; historical listing/ST/sector membership not verified',
            'forced_symbols': list(FORCED_SYMBOLS), 'execution_allowed': False}


def collect_sample(count=120, seed=DEFAULT_SEED, refresh=False, workers=4, on_progress=None):
    selected = sample_symbols(count, seed)
    ident = datetime.now(CN).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    path = runtime_root() / 'collections' / (ident + '.json')
    manifest = {'id': ident, 'state': 'running', 'started_at': now_iso(), 'selection': selected,
                'total': selected['count'], 'completed': 0, 'failed': 0, 'rows': [],
                'manifest_path': str(path.resolve()), 'refresh': bool(refresh), 'execution_allowed': False}
    _atomic_json(path, manifest)
    def fetch(row):
        result = fetch_daily(row['symbol'], refresh=refresh)
        return {'symbol': row['symbol'], 'name': row['name'], 'stratum': row['stratum'],
                'state': 'completed', **{key: result['metadata'].get(key) for key in
                    ('count', 'closed_count', 'forming_count', 'first', 'last', 'input_sha256',
                     'raw_sha256', 'raw_path', 'dataset_ref', 'received_at', 'quarantined_count')}}
    with ThreadPoolExecutor(max_workers=max(1, min(8, int(workers))), thread_name_prefix='bottom-data') as pool:
        futures = {pool.submit(fetch, row): row for row in selected['symbols']}
        for future in as_completed(futures):
            row = futures[future]
            try:
                receipt = future.result()
            except Exception as error:
                receipt = {'symbol': row['symbol'], 'name': row['name'], 'stratum': row['stratum'],
                           'state': 'failed', 'error': type(error).__name__ + ': ' + str(error)[:240]}
                manifest['failed'] += 1
            manifest['rows'].append(receipt)
            manifest['completed'] += 1
            manifest['updated_at'] = now_iso()
            _atomic_json(path, manifest)
            if on_progress:
                on_progress({'completed': manifest['completed'], 'total': manifest['total'],
                             'failed': manifest['failed'], 'last': receipt})
    manifest.update(state='completed', finished_at=now_iso(), successful=manifest['completed'] - manifest['failed'])
    manifest['rows'].sort(key=lambda row: row['symbol'])
    manifest['dataset_manifest_sha256'] = hashlib.sha256(_json_bytes(manifest['rows'])).hexdigest()
    _atomic_json(path, manifest)
    _atomic_json(runtime_root() / 'collections' / 'latest.json', {'id': ident, 'manifest_path': str(path.resolve())})
    return manifest


def _context_url(code, kind):
    secid = ('1.' if code.startswith('sh') else '0.') + code[2:]
    if kind == 'money_flow':
        params = {'lmt': 0, 'klt': 101, 'secid': secid, 'fields1': 'f1,f2,f3,f7',
                  'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65',
                  'ut': 'b2884a393a59ad64002292a3e90d46a5'}
        path = '/api/qt/stock/fflow/daykline/get'
    else:
        params = {'secid': secid, 'fields1': 'f1,f2,f3,f4,f5,f6',
                  'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
                  'klt': 101, 'fqt': 0, 'end': '20500101', 'lmt': 210}
        path = '/api/qt/stock/kline/get'
    return 'https://push2his.eastmoney.com' + path + '?' + urllib.parse.urlencode(params)


def _context_cache_fresh(cached, now):
    """A future or timezone-free receipt cannot establish cache freshness."""
    try:
        received = datetime.fromisoformat(cached['received_at'])
        if received.tzinfo is None:
            return False
        age = (now - received.astimezone(CN)).total_seconds()
        if age < 0:
            return False
        for source in cached.get('sources', {}).values():
            point = datetime.fromisoformat(source['received_at'])
            if point.tzinfo is None or point.astimezone(CN) > now:
                return False
    except (KeyError, TypeError, ValueError):
        return False
    local = now.astimezone(CN)
    minute = local.hour * 60 + local.minute
    active = local.weekday() < 5 and (555 <= minute <= 690 or 780 <= minute <= 900)
    return age < (60 if active else 300)


def probe_context(code, refresh=False):
    code = _code(code)
    path = runtime_root() / 'context' / (code + '.json')
    if path.is_file() and not refresh:
        cached = json.loads(path.read_text(encoding='utf-8'))
        now = datetime.fromisoformat(now_iso())
        if _context_cache_fresh(cached, now):
            for value in cached['sources'].values():
                if value.get('raw_path'):
                    _read_object(value)
            return cached
    result = {'symbol': code, 'received_at': now_iso(), 'sources': {}, 'execution_allowed': False,
              'historical_join_policy': 'known_at must not exceed observation cutoff; retrospectively fetched history is excluded until publication timing is independently verified'}
    for kind in ('money_flow', 'turnover_history'):
        try:
            envelope, receipt = _request(_context_url(code, kind), timeout=8)
            content = (envelope.get('data') or {}).get('klines')
            if not isinstance(content, list) or not content:
                raise ValueError('context endpoint returned no dated rows')
            rows = []
            for line in content:
                parts = line.split(',')
                date = datetime.strptime(parts[0], '%Y-%m-%d').date().isoformat()
                values = [None if value in ('', '-', '--') else float(value) for value in parts[1:]]
                if any(value is not None and not math.isfinite(value) for value in values):
                    raise ValueError('nonfinite context value')
                row = {'date': date, 'data_date': date, 'known_at': receipt['received_at'],
                       'publication_time_verified': False, 'historical_usable': False}
                if kind == 'money_flow':
                    if len(values) < 12:
                        raise ValueError('money-flow field count mismatch')
                    row.update(main_net_amount=values[0], small_net_amount=values[1], mid_net_amount=values[2],
                               large_net_amount=values[3], extra_large_net_amount=values[4],
                               main_net_pct=values[5], close=values[10], change_pct=values[11])
                else:
                    if len(values) < 10:
                        raise ValueError('turnover-history field count mismatch')
                    row.update(open=values[0], close=values[1], high=values[2], low=values[3],
                               volume=values[4], amount=values[5], turnover_pct=values[9])
                rows.append(row)
            rows.sort(key=lambda row: row['date'])
            result['sources'][kind] = {'state': 'ready', 'source': 'Eastmoney dated fund-flow statistics' if kind == 'money_flow' else 'Eastmoney OHLC + turnover inputs',
                **receipt, 'count': len(rows), 'first_date': rows[0]['date'], 'last_date': rows[-1]['date'], 'rows': rows,
                'historical_usable': False, 'publication_time_verified': False,
                'semantics': 'provider classified-order flow; not a record of shareholder identity' if kind == 'money_flow' else 'turnover history can feed an explicitly estimated chip-distribution model; not observed holdings'}
        except Exception as error:
            result['sources'][kind] = {'state': 'unavailable', 'source': 'Eastmoney public endpoint',
                'received_at': now_iso(), 'count': 0, 'rows': [], 'historical_usable': False,
                'error': type(error).__name__ + ': ' + str(error)[:200]}
    result['chip_structure'] = {'definition_mode': 'volume_distribution_proxy', 'observed_holdings': False,
        'available_inputs': result['sources']['turnover_history']['state'],
        'note': 'AkShare stock_cyq_em itself estimates chips from latest 210 OHLC/turnover rows and returns 90 days; no true historical shareholder chip registry is exposed'}
    _atomic_json(path, result)
    return result
