"""Local, point-in-time regime event study over immutable cached daily OHLCV.

This evaluates conditional price movement. It does not simulate an executable
strategy, sell short, tune source code, or promote new model parameters.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CN = timezone(timedelta(hours=8))
STUDY_VERSION = 'causal_regime_event_study_v1.1'
DEFAULT_HORIZONS = (5, 20, 60)
SYMBOL_RE = re.compile(r'^(sh|sz|bj)\d{6}$')
EVENT_FAMILIES = {
    'bottom_candidate': ('precursor', 1),
    'basing': ('base', 1),
    'breakout_confirmation': ('breakout', 1),
    'uptrend': ('uptrend', 1),
    'downtrend': ('downtrend', -1),
    'breakdown': ('breakdown', -1),
    'bottom_invalidated': ('invalidation', -1),
    'top_candidate': ('precursor', -1),
    'topping': ('base', -1),
    'top_invalidated': ('invalidation', 1),
}
_WORKER_CONTEXT = None


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json(value).encode('utf-8')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(raw)
    temporary.replace(path)


def normalize_cutoff(value):
    if not value:
        return datetime.now(CN).isoformat(timespec='seconds')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        value += 'T15:00:00+08:00'
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('cutoff must include a timezone or be YYYY-MM-DD')
    return moment.astimezone(CN).isoformat(timespec='seconds')


def read_daily_rows(path, cutoff=None):
    """Keep one source intact; never splice conflicting history across roots."""
    source = Path(path)
    raw = source.read_bytes()
    source_hash = digest_bytes(raw)
    point = datetime.fromisoformat(normalize_cutoff(cutoff)) if cutoff else None
    rows = []
    excluded = Counter()
    prior = None
    source_dates = set()
    source_closed_count = 0
    source_last_closed = None
    with io.StringIO(raw.decode('utf-8-sig'), newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'closed_at', 'open', 'high', 'low', 'close', 'volume'}.issubset(reader.fieldnames or []):
            raise ValueError('daily CSV lacks closed_at/open/high/low/close/volume')
        for line, item in enumerate(reader, 2):
            stamp = datetime.fromisoformat(item['closed_at'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError(f'row {line}: daily timestamp has no timezone')
            stamp = stamp.astimezone(CN)
            session_date = stamp.date().isoformat()
            if session_date in source_dates:
                raise ValueError(f'row {line}: duplicate daily session date')
            source_dates.add(session_date)
            if (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) != (15, 0, 0, 0):
                raise ValueError(f'row {line}: daily bar must be scheduled at 15:00:00 China time')
            if prior is not None and stamp <= prior:
                raise ValueError(f'row {line}: duplicate or descending timestamp')
            prior = stamp
            closed = (item.get('is_closed') or 'true').strip().lower()
            if closed not in {'true', '1', 'false', '0'}:
                raise ValueError(f'row {line}: invalid is_closed')
            if closed in {'false', '0'}:
                excluded['forming'] += 1
                continue
            # Metadata describes the complete immutable source, not the earlier
            # historical prefix selected for this evaluation.
            source_closed_count += 1
            source_last_closed = stamp
            if point and stamp > point:
                excluded['after_cutoff'] += 1
                continue
            values = {key: float(item[key]) for key in ('open', 'high', 'low', 'close', 'volume')}
            if any(not math.isfinite(value) for value in values.values()):
                raise ValueError(f'row {line}: nonfinite OHLCV')
            if min(values[key] for key in ('open', 'high', 'low', 'close')) <= 0 or values['volume'] < 0:
                raise ValueError(f'row {line}: nonpositive prices or negative volume')
            if values['high'] < max(values['open'], values['close'], values['low']) or values['low'] > min(values['open'], values['close'], values['high']):
                raise ValueError(f'row {line}: invalid OHLC envelope')
            amount = item.get('amount_yuan')
            if amount not in (None, ''):
                amount = float(amount)
                if not math.isfinite(amount) or amount < 0:
                    raise ValueError(f'row {line}: invalid amount')
            else:
                amount = None
            rows.append({'closed_at': stamp.isoformat(timespec='seconds'),
                         'date': session_date, 'is_closed': True,
                         **values, 'amount_yuan': amount})
    if not rows:
        raise ValueError('no closed daily bars at the requested cutoff')
    metadata_path = source.parent.parent / 'metadata' / f'{source.stem}.json'
    metadata_verified = False
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        expected_hash = metadata.get('csv_sha256')
        if expected_hash and expected_hash != source_hash:
            raise ValueError('cache metadata CSV SHA-256 does not match selected source')
        if metadata.get('symbol') not in (None, source.stem.lower()):
            raise ValueError('cache metadata symbol does not match selected source')
        if metadata.get('csv_sha256'):
            metadata_verified = True
        if metadata.get('last_date'):
            if metadata['last_date'] != source_last_closed.date().isoformat():
                raise ValueError('cache metadata last_date differs from selected closed CSV')
    return rows, {'path': str(source.resolve()), 'bytes': len(raw),
                  'source_sha256': source_hash, 'closed_rows': len(rows),
                  'first_close': rows[0]['closed_at'], 'last_close': rows[-1]['closed_at'],
                  'source_closed_rows': source_closed_count,
                  'source_last_close': source_last_closed.isoformat(timespec='seconds'),
                  'excluded': dict(excluded), 'source_adjustment': 'cached_unadjusted',
                  'metadata_verified': metadata_verified,
                  'point_in_time_revision_history': False}


def candidate_folders(root):
    root = Path(root).expanduser().resolve()
    folders = [root, root / 'tdx/day/ohlcv', root / 'market_data/tdx/day/ohlcv']
    jobs = root / 'runtime/workbench/jobs'
    if jobs.is_dir():
        folders.extend(jobs.glob('*/cache/tdx/day/ohlcv'))
    if root.name == 'jobs' and root.is_dir():
        folders.extend(root.glob('*/cache/tdx/day/ohlcv'))
    seen = set()
    for folder in folders:
        if folder.is_dir() and str(folder).lower() not in seen:
            seen.add(str(folder).lower())
            yield folder


def last_closed_hint(path):
    """Choose a whole CSV by latest closed label; mtime only breaks ties."""
    path = Path(path)
    metadata_path = path.parent.parent / 'metadata' / f'{path.stem}.json'
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            if (metadata.get('symbol') in (None, path.stem.lower())
                    and metadata.get('csv_sha256') and metadata.get('last_date')
                    and metadata.get('open_rows_excluded', 0) == 0):
                datetime.strptime(metadata['last_date'], '%Y-%m-%d')
                return metadata['last_date'] + 'T15:00:00+08:00'
        except (OSError, ValueError, TypeError, UnicodeError):
            pass
    with path.open('rb') as stream:
        header = stream.readline().decode('utf-8-sig').strip()
        stream.seek(max(0, path.stat().st_size - 65536))
        tail = stream.read().decode('utf-8', errors='strict').splitlines()
    fields = next(csv.reader([header]))
    date_index = fields.index('closed_at')
    closed_index = fields.index('is_closed') if 'is_closed' in fields else None
    for line in reversed(tail):
        values = next(csv.reader([line]))
        if len(values) != len(fields):
            continue
        if closed_index is not None and values[closed_index].strip().lower() in {'false', '0'}:
            continue
        try:
            stamp = datetime.fromisoformat(values[date_index].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                continue
            return stamp.astimezone(CN).isoformat(timespec='seconds')
        except ValueError:
            continue
    raise ValueError('cannot find a closed timestamp in CSV tail')


def discover_sources(roots, workers=8):
    candidates = defaultdict(list)
    failures = []
    seen_paths = set()
    paths = []
    for root_rank, root in enumerate(roots):
        for folder in candidate_folders(root):
            for path in sorted(folder.glob('*.csv')):
                symbol = path.stem.lower()
                identity = str(path.resolve()).lower()
                if not SYMBOL_RE.fullmatch(symbol) or identity in seen_paths:
                    continue
                seen_paths.add(identity)
                paths.append((symbol, path, root_rank))

    def inspect(item):
        symbol, path, root_rank = item
        try:
            last = last_closed_hint(path)
            stat = path.stat()
            return {**{'symbol': symbol, 'path': str(path.resolve()),
                       'last_closed_hint': last, 'mtime_ns': stat.st_mtime_ns,
                       'bytes': stat.st_size, 'root_rank': root_rank}}
        except (OSError, ValueError, UnicodeError, csv.Error) as exc:
            return {'symbol': symbol, 'path': str(path),
                    'error': f'{type(exc).__name__}: {exc}'}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(inspect, paths):
            if 'error' in result:
                failures.append({key: result[key] for key in ('symbol', 'path', 'error')})
            else:
                candidates[result['symbol']].append(result)
    selected = []
    for symbol, versions in sorted(candidates.items()):
        versions.sort(key=lambda row: (row['last_closed_hint'], row['mtime_ns'], -row['root_rank']), reverse=True)
        selected.append({**versions[0], 'alternative_sources': len(versions) - 1})
    return selected, failures


def select_sources(sources, limit=0, symbols=None):
    if symbols:
        by_symbol = {source['symbol']: source for source in sources}
        requested = list(dict.fromkeys(str(symbol).strip().lower() for symbol in symbols))
        unknown = [symbol for symbol in requested if not SYMBOL_RE.fullmatch(symbol) or symbol not in by_symbol]
        if unknown:
            raise ValueError('requested symbols have no cached daily source: ' + ','.join(unknown))
        return [by_symbol[symbol] for symbol in requested]
    return sources[:limit] if limit else list(sources)


def build_breadth(sources, cutoff):
    """Historical same-close advance/decline proxy from the discovered cache pool."""
    totals = defaultdict(lambda: [0, 0, 0, 0])
    failures = []
    source_receipts = []
    for source in sources:
        try:
            rows, receipt = read_daily_rows(source['path'], cutoff)
            source_receipts.append({'symbol': source['symbol'], 'sha256': receipt['source_sha256']})
            for previous, row in zip(rows, rows[1:]):
                values = totals[row['date']]
                values[0] += row['close'] > previous['close']
                values[1] += row['close'] < previous['close']
                values[2] += row['close'] == previous['close']
                values[3] += row['volume'] > 0
        except (OSError, ValueError, UnicodeError, csv.Error) as exc:
            failures.append({'symbol': source['symbol'], 'path': source['path'],
                             'error': f'{type(exc).__name__}: {exc}'})
        if (len(source_receipts) + len(failures)) % 500 == 0:
            print(f'Breadth scanned {len(source_receipts) + len(failures)}/{len(sources)} sources', flush=True)
    result = {}
    for date, (advance, decline, unchanged, positive_volume) in sorted(totals.items()):
        comparable = advance + decline
        result[date] = {'date': date, 'advance': advance, 'decline': decline,
                       'unchanged': unchanged, 'observed_securities': advance + decline + unchanged,
                       'positive_volume_securities': positive_volume,
                       'advance_ratio': advance / comparable if comparable else None,
                       'available_at': date + 'T15:00:00+08:00'}
    return result, {'source': 'cached_close_advance_decline_proxy',
        'pool_size': len(sources), 'successful_sources': len(source_receipts),
        'failed_sources': failures, 'source_pool_sha256': digest_bytes(canonical_json(source_receipts).encode()),
        'historical_membership_verified': False,
        'scope': 'currently cached selected securities; current-universe/survivorship and suspension coverage bias',
        'future_prices_used': False}


def chronological_splits(dates):
    dates = sorted(set(dates))
    if len(dates) < 5:
        raise ValueError('at least five market dates required for chronological splits')
    train_end = max(1, int(len(dates) * .6))
    validation_end = max(train_end + 1, int(len(dates) * .8))
    validation_end = min(validation_end, len(dates) - 1)
    return {'train': (dates[0], dates[train_end - 1]),
            'validation': (dates[train_end], dates[validation_end - 1]),
            'test': (dates[validation_end], dates[-1])}


def split_for(date, splits):
    return next((name for name, (start, end) in splits.items() if start <= date <= end), None)


def _empty_stats():
    return {'count': 0, 'positive_gross': 0, 'positive_after_cost': 0,
            'sum_underlying_return': 0.0, 'sum_directional_move': 0.0,
            'sum_net_directional_move': 0.0, 'sum_mfe': 0.0, 'sum_mae': 0.0}


def _add_stats(stats, label):
    stats['count'] += 1
    stats['positive_gross'] += label['directional_move'] > 0
    stats['positive_after_cost'] += label['net_directional_move'] > 0
    stats['sum_underlying_return'] += label['underlying_return']
    stats['sum_directional_move'] += label['directional_move']
    stats['sum_net_directional_move'] += label['net_directional_move']
    stats['sum_mfe'] += label['mfe']
    stats['sum_mae'] += label['mae']


def _finish_stats(stats):
    n = stats['count']
    return {**stats, 'gross_direction_hit_rate': stats['positive_gross'] / n if n else None,
            'after_cost_direction_hit_rate': stats['positive_after_cost'] / n if n else None,
            'mean_underlying_return': stats['sum_underlying_return'] / n if n else None,
            'mean_directional_move': stats['sum_directional_move'] / n if n else None,
            'mean_net_directional_move': stats['sum_net_directional_move'] / n if n else None,
            'mean_mfe': stats['sum_mfe'] / n if n else None,
            'mean_mae': stats['sum_mae'] / n if n else None,
            'sample_state': 'descriptive_only' if n >= 30 else 'too_few_observations'}


def horizon_labels(rows, horizon):
    """Future outcomes are evaluation-only; never passed into feature generation."""
    result = [None] * len(rows)
    highs, lows = deque(), deque()
    tradable = [index for index, row in enumerate(rows) if row['volume'] > 0]
    for ordinal, right in enumerate(tradable):
        row = rows[right]
        while highs and rows[highs[-1]]['high'] <= row['high']:
            highs.pop()
        while lows and rows[lows[-1]]['low'] >= row['low']:
            lows.pop()
        highs.append(right)
        lows.append(right)
        left_ordinal = ordinal - horizon + 1
        left = tradable[left_ordinal] if left_ordinal >= 0 else -1
        if left_ordinal < 0:
            continue
        while highs[0] < left:
            highs.popleft()
        while lows[0] < left:
            lows.popleft()
        result[left] = {'entry_index': left, 'entry_time': rows[left]['date'] + 'T09:30:00+08:00',
                        'entry_bar_closed_at': rows[left]['closed_at'],
                        'entry_date': rows[left]['date'], 'entry_open': rows[left]['open'],
                        'exit_index': right, 'exit_time': row['closed_at'],
                        'exit_date': row['date'], 'exit_close': row['close'],
                        'window_high': rows[highs[0]]['high'], 'window_low': rows[lows[0]]['low']}
    return result


def evaluate_label(rows, observed_index, horizon, direction, splits, cost_bps=20,
                   labels=None, next_entries=None):
    if type(observed_index) is not int or not 0 <= observed_index < len(rows):
        raise ValueError('event observed_index outside closed input')
    if direction not in {-1, 1}:
        raise ValueError('direction must be -1 or 1')
    if rows[observed_index]['volume'] <= 0:
        return None, 'observation_bar_no_positive_volume'
    entry = (next_entries[observed_index] if next_entries is not None else
             next((i for i in range(observed_index + 1, len(rows)) if rows[i]['volume'] > 0), None))
    if entry is None:
        return None, 'no_next_positive_volume_bar'
    label = (labels if labels is not None else horizon_labels(rows, horizon))[entry]
    if label is None:
        return None, 'insufficient_forward_horizon'
    split = split_for(rows[observed_index]['date'], splits)
    if not split or split_for(label['entry_date'], splits) != split or split_for(label['exit_date'], splits) != split:
        return None, 'purged_at_chronological_boundary'
    opening = label['entry_open']
    raw_return = label['exit_close'] / opening - 1
    signed = direction * raw_return
    if direction == 1:
        mfe = label['window_high'] / opening - 1
        mae = label['window_low'] / opening - 1
    else:
        mfe = 1 - label['window_low'] / opening
        mae = 1 - label['window_high'] / opening
    return {**label, 'split': split, 'horizon': horizon, 'direction': direction,
            'observed_index': observed_index, 'observed_at': rows[observed_index]['closed_at'],
            'underlying_return': raw_return, 'directional_move': signed,
            'net_directional_move': signed - cost_bps / 10000,
            'cost_bps_assumption': cost_bps, 'mfe': mfe, 'mae': mae,
            'entry_kind': 'next_positive_volume_observed_bar_open',
            'executable_strategy': False}, None


def breadth_pass(date, direction, breadth, minimum_securities=20):
    value = breadth.get(date)
    if not value or value.get('advance_ratio') is None or value.get('observed_securities', 0) < minimum_securities:
        return None
    ratio = value['advance_ratio']
    return ratio >= .5 if direction == 1 else ratio <= .5


def evaluate_symbol(rows, analysis, splits, breadth=None, horizons=DEFAULT_HORIZONS,
                    cost_bps=20, minimum_securities=20):
    breadth = breadth or {}
    stats = defaultdict(_empty_stats)
    excluded = Counter()
    event_rows = []
    following = [None] * len(rows)
    upcoming = None
    for index in range(len(rows) - 1, -1, -1):
        following[index] = upcoming
        if rows[index]['volume'] > 0:
            upcoming = index
    label_windows = {h: horizon_labels(rows, h) for h in horizons}
    eligible_indices = {record['index'] for record in analysis.get('series', [])
                        if record.get('state') != 'warmup'}
    for horizon in horizons:
        for observed_index in range(len(rows)):
            if rows[observed_index]['volume'] <= 0:
                continue
            if analysis.get('series') and observed_index not in eligible_indices:
                continue
            for direction in (1, -1):
                label, reason = evaluate_label(rows, observed_index, horizon, direction, splits,
                    cost_bps, label_windows[horizon], following)
                if label is None:
                    excluded['baseline:' + reason] += 1
                    continue
                key = f"{label['split']}|{horizon}|{'up' if direction == 1 else 'down'}|all_days"
                _add_stats(stats[key], label)
                condition = breadth_pass(rows[observed_index]['date'], direction, breadth, minimum_securities)
                if condition:
                    _add_stats(stats[key.replace('|all_days', '|all_days_breadth_filter')], label)
    seen = set()
    for event in analysis.get('events', []):
        event_name = event.get('event')
        if event_name not in EVENT_FAMILIES:
            continue
        family, direction = EVENT_FAMILIES[event_name]
        observed_index = event.get('observed_index')
        if (event_name, observed_index) in seen:
            continue
        seen.add((event_name, observed_index))
        if type(observed_index) is not int or not 0 <= observed_index < len(rows):
            raise ValueError('analysis event has invalid observed_index')
        if rows[observed_index]['volume'] <= 0:
            excluded[family + ':observation_bar_no_positive_volume'] += 1
            event_rows.append({'event_id': event.get('id'), 'event': event_name,
                'family': family, 'observed_index': observed_index,
                'observed_at': rows[observed_index]['closed_at'], 'state': 'excluded',
                'reason': 'observation_bar_no_positive_volume'})
            continue
        supplied_time = event.get('observed_at')
        if supplied_time and datetime.fromisoformat(supplied_time) != datetime.fromisoformat(rows[observed_index]['closed_at']):
            raise ValueError('analysis event observed_at differs from its closed bar')
        for horizon in horizons:
            label, reason = evaluate_label(rows, observed_index, horizon, direction, splits,
                cost_bps, label_windows[horizon], following)
            condition = breadth_pass(rows[observed_index]['date'], direction, breadth, minimum_securities)
            if label is None:
                excluded[family + ':' + reason] += 1
                event_rows.append({'event_id': event.get('id'), 'event': event_name,
                    'family': family, 'observed_index': observed_index,
                    'observed_at': rows[observed_index]['closed_at'], 'horizon': horizon,
                    'state': 'excluded', 'reason': reason, 'breadth_filter': condition})
                continue
            side = 'up' if direction == 1 else 'down'
            key = f"{label['split']}|{horizon}|{side}|{family}"
            _add_stats(stats[key], label)
            if condition:
                _add_stats(stats[key + '_breadth_filter'], label)
            event_rows.append({'event_id': event.get('id'), 'event': event_name,
                'family': family, 'state': 'evaluated', 'breadth_filter': condition,
                'breadth': breadth.get(rows[observed_index]['date']), **label})
    return {'stats': dict(stats), 'event_outcomes': event_rows, 'excluded': dict(excluded)}


def research_one(source, cutoff, splits, breadth, horizons, cost_bps, minimum_securities, output):
    started = time.perf_counter()
    try:
        from chanmodel.regime_research import analyze_regimes
        rows, receipt = read_daily_rows(source['path'], cutoff)
        analysis = analyze_regimes(rows, symbol=source['symbol'])
        # Evaluation labels are built only after the full causal feature/event pass.
        evaluation = evaluate_symbol(rows, analysis, splits, breadth, horizons, cost_bps, minimum_securities)
        destination = Path(output) / 'stocks' / (source['symbol'] + '.json.gz')
        payload = {'version': STUDY_VERSION, 'symbol': source['symbol'], 'source': receipt,
                   'research_version': analysis.get('version'), 'latest': analysis.get('latest'),
                   'event_count': len(analysis.get('events', [])), **evaluation,
                   'flow_history_coverage': {'observations_used': 0, 'state': 'unavailable_point_in_time'},
                   'chip_history_coverage': {'observations_used': 0, 'state': 'price_volume_proxy_only'},
                   'execution_allowed': False}
        raw = canonical_json(payload).encode('utf-8')
        destination.parent.mkdir(parents=True, exist_ok=True)
        packed = gzip.compress(raw, compresslevel=3, mtime=0)
        destination.write_bytes(packed)
        return {'symbol': source['symbol'], 'state': 'complete', 'bars': len(rows),
                'first_close': rows[0]['closed_at'], 'last_close': rows[-1]['closed_at'],
                'source_path': source['path'], 'source_sha256': receipt['source_sha256'],
                'event_count': len(analysis.get('events', [])),
                'evaluated_event_horizons': sum(row['state'] == 'evaluated' for row in evaluation['event_outcomes']),
                'stats': evaluation['stats'], 'excluded': evaluation['excluded'],
                'artifact': str(destination.resolve()), 'artifact_sha256': digest_bytes(packed),
                'seconds': round(time.perf_counter() - started, 3)}
    except Exception as exc:
        return {'symbol': source['symbol'], 'state': 'failed', 'source_path': source['path'],
                'error': f'{type(exc).__name__}: {exc}',
                'seconds': round(time.perf_counter() - started, 3)}


def _initialize_worker(cutoff, splits, breadth, horizons, cost_bps, minimum_securities, output):
    global _WORKER_CONTEXT
    _WORKER_CONTEXT = (cutoff, splits, breadth, horizons, cost_bps, minimum_securities, output)


def _research_source(source):
    if _WORKER_CONTEXT is None:
        raise RuntimeError('research worker has no immutable run context')
    return research_one(source, *_WORKER_CONTEXT)


def aggregate(rows):
    stats = defaultdict(_empty_stats)
    complete = [row for row in rows if row['state'] == 'complete']
    failed = [row for row in rows if row['state'] != 'complete']
    symbol_means = defaultdict(list)
    exclusions = Counter()
    for row in complete:
        exclusions.update(row['excluded'])
        for key, value in row['stats'].items():
            for field in _empty_stats():
                stats[key][field] += value[field]
            if value['count']:
                symbol_means[key].append(value['sum_net_directional_move'] / value['count'])
    finished = {}
    for key, value in sorted(stats.items()):
        finished[key] = {**_finish_stats(value), 'symbols_with_observations': len(symbol_means[key]),
                         'mean_equal_symbol_net_move': statistics.fmean(symbol_means[key]) if symbol_means[key] else None}
    comparisons = []
    for key, value in finished.items():
        split, horizon, direction, family = key.split('|', 3)
        if family.startswith('all_days'):
            continue
        baseline_key = f'{split}|{horizon}|{direction}|all_days'
        base = finished.get(baseline_key)
        if base and base['count']:
            comparisons.append({'group': key, 'baseline': baseline_key,
                'event_count': value['count'], 'baseline_count': base['count'],
                'mean_directional_difference': value['mean_directional_move'] - base['mean_directional_move'],
                'direction_hit_difference': value['gross_direction_hit_rate'] - base['gross_direction_hit_rate']})
    return {'total': len(rows), 'completed': len(complete), 'failed': len(failed),
            'bars': sum(row['bars'] for row in complete),
            'events': sum(row['event_count'] for row in complete),
            'event_horizon_observations': sum(row['evaluated_event_horizons'] for row in complete),
            'metrics': finished, 'comparisons': comparisons, 'excluded': dict(exclusions),
            'failures': [{key: row.get(key) for key in ('symbol', 'source_path', 'error')} for row in failed]}


def run(roots, output, limit=0, workers=4, cutoff=None, horizons=DEFAULT_HORIZONS, cost_bps=20,
        minimum_securities=20, symbols=None):
    cutoff = normalize_cutoff(cutoff)
    output = Path(output).resolve()
    if (output / 'manifest.json').exists():
        raise ValueError('output already has a manifest; use a new directory to preserve the prior study')
    sources, discovery_failures = discover_sources(roots, workers=min(16, max(4, workers * 2)))
    if not sources:
        raise ValueError('no symbol daily CSV caches found under requested data roots')
    selected = select_sources(sources, limit, symbols)
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    print(f'Building same-close breadth for {len(sources)} immutable cache sources', flush=True)
    breadth, breadth_receipt = build_breadth(sources, cutoff)
    splits = chronological_splits(breadth)
    regime_file = ROOT / 'chanmodel/regime_research.py'
    code = {path.relative_to(ROOT).as_posix(): digest_bytes(path.read_bytes())
            for path in (Path(__file__).resolve(), regime_file)}
    config = {'version': STUDY_VERSION, 'cutoff': cutoff, 'horizons': list(horizons),
              'cost_bps_round_trip_assumption': cost_bps, 'minimum_breadth_securities': minimum_securities,
              'breadth_threshold': .5, 'split_rule': 'global chronological dates 60/20/20, horizon-purged',
              'splits': splits, 'selected_symbols': [source['symbol'] for source in selected]}
    config_hash = digest_bytes(canonical_json(config).encode())
    manifest = {'config': config, 'config_sha256': config_hash, 'code_sha256': code,
                'roots': [str(Path(root).resolve()) for root in roots],
                'sources': sources, 'discovery_failures': discovery_failures,
                'source_selection': 'one whole CSV per symbol; latest closed date then mtime, never splice',
                'breadth_receipt': breadth_receipt, 'execution_allowed': False,
                'auto_source_updates': False, 'external_publish': False}
    write_json(output / 'manifest.json', manifest)
    write_json(output / 'breadth.json', breadth)
    rows = []
    with ProcessPoolExecutor(max_workers=workers, initializer=_initialize_worker,
            initargs=(cutoff, splits, breadth, tuple(horizons), cost_bps, minimum_securities, str(output))) as pool:
        jobs = {pool.submit(_research_source, source): source for source in selected}
        for future in as_completed(jobs):
            source = jobs[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {'symbol': source['symbol'], 'state': 'failed', 'source_path': source['path'],
                       'error': f'{type(exc).__name__}: {exc}'}
            rows.append(row)
            if len(rows) == 1 or len(rows) % 100 == 0 or len(rows) == len(selected):
                print(f"Evaluated {len(rows)}/{len(selected)} securities; failed {sum(r['state'] != 'complete' for r in rows)}", flush=True)
    summary = {**aggregate(rows), 'version': STUDY_VERSION, 'as_of': cutoff,
        'configuration_sha256': config_hash, 'code_sha256': code, 'splits': splits,
        'breadth_receipt': breadth_receipt, 'discovery_failures': discovery_failures,
        'elapsed_seconds': round(time.perf_counter() - started, 3),
        'performance_scope': 'overlapping observational event outcomes, not executable strategy returns or short-sale P&L',
        'flow_history_coverage': {'observations_used': 0, 'point_in_time_history_verified': False},
        'chip_history_coverage': {'true_holder_cost_observations': 0, 'price_volume_proxy_only': True},
        'limitations': ['Unadjusted cached OHLCV and latest-vintage history; corporate actions and historical revisions are not reconstructed point in time.',
                        'Current cached symbol pool, not historical membership; includes survivorship and coverage bias.',
                        'Overlapping horizons and repeated states make observations dependent; hit rates are descriptive, not confidence in future trades.',
                        'Next available positive-volume observed bar open is a reference price; queue, suspension, ST, limit prices, capacity and short-sale feasibility are not simulated.',
                        'No point-in-time individual fund flow or genuine shareholder cost/chip distribution is used.',
                        'Rules are frozen; study does not edit sources, tune on the test block, or automatically deploy a winner.'],
        'execution_allowed': False, 'external_publish': False}
    write_json(output / 'summary.json', summary)
    fields = ('symbol', 'state', 'bars', 'first_close', 'last_close', 'event_count',
              'evaluated_event_horizons', 'source_sha256', 'seconds', 'error')
    with (output / 'stocks.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row['symbol']))
    write_json(output / 'stock-receipts.json', sorted(rows, key=lambda row: row['symbol']))
    print(canonical_json({'output': str(output), 'completed': summary['completed'],
        'failed': summary['failed'], 'bars': summary['bars'], 'events': summary['events'],
        'seconds': summary['elapsed_seconds'], 'summary_sha256': digest_bytes((output / 'summary.json').read_bytes())}), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, action='append', required=True,
                        help='Repeat cache/project/jobs roots; each source remains intact.')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=0, help='Evaluate first N sorted symbols; 0 means every discovered symbol.')
    parser.add_argument('--symbols', help='Comma-separated explicit sample; cannot be combined with a nonzero --limit.')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--cutoff')
    parser.add_argument('--horizons', default='5,20,60')
    parser.add_argument('--cost-bps', type=float, default=20)
    parser.add_argument('--minimum-breadth-securities', type=int, default=20)
    args = parser.parse_args()
    horizons = tuple(sorted({int(value) for value in args.horizons.split(',')}))
    if not 1 <= args.workers <= 16 or args.limit < 0 or (args.symbols and args.limit) or not horizons or min(horizons) < 1 or max(horizons) > 252:
        parser.error('workers 1..16, nonnegative limit, horizons 1..252 required')
    if not math.isfinite(args.cost_bps) or args.cost_bps < 0 or args.minimum_breadth_securities < 1:
        parser.error('cost must be finite/nonnegative and minimum breadth at least 1')
    run(args.data_root, args.output_dir, args.limit, args.workers, args.cutoff, horizons,
        args.cost_bps, args.minimum_breadth_securities,
        [symbol for symbol in args.symbols.split(',') if symbol.strip()] if args.symbols else None)


if __name__ == '__main__':
    main()
