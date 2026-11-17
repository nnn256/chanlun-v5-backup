"""Offline paired comparison of bottom engines at their first knowable signal.

No network fetches, parameter search, promotion, source edits or snapshot hierarchy
construction occur here. The old test period is retrospective regression, not a
newly untouched holdout. A disjoint symbols manifest can supply a new symbol
holdout while retaining the same frozen time boundaries and evaluation rules.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import random
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chanmodel import bottom_research as current
from web import bottom_data as data

RUNTIME = ROOT / '.runtime/bottom-research'
BASELINE_FILE = RUNTIME / 'accuracy-v11/baseline/chanmodel/bottom_research.py'
STATES = ('base_formed', 'departure', 'retest_held')
SPLITS = ('train', 'validation', 'test', 'all')
CN = timezone(timedelta(hours=8))
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261116


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def load_baseline():
    if not BASELINE_FILE.is_file():
        raise ValueError('frozen baseline module missing: ' + str(BASELINE_FILE))
    name = 'chanmodel._bottom_accuracy_frozen_baseline'
    spec = importlib.util.spec_from_file_location(name, BASELINE_FILE)
    if spec is None or spec.loader is None:
        raise ValueError('could not load baseline module')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def choose_run(ident):
    if ident:
        if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{6}', ident):
            raise ValueError('invalid --baseline-run identifier')
        path = RUNTIME / 'runs' / ident / 'status.json'
        run = read_json(path)
        if run.get('state') not in {'completed', 'partial'}:
            raise ValueError('baseline run must be completed or partial')
        return run, path.parent
    for folder in sorted((RUNTIME / 'runs').iterdir(), reverse=True):
        if not folder.is_dir() or not (folder / 'status.json').is_file():
            continue
        run = read_json(folder / 'status.json')
        if run.get('state') == 'completed' and run.get('total') == 240:
            return run, folder
    raise ValueError('no completed 240-symbol baseline run; pass --baseline-run')


def receipt_records(manifest, baseline_run):
    if manifest is None:
        return list(baseline_run['data_receipts'])
    value = read_json(manifest)
    if isinstance(value, list):
        records = value
    elif isinstance(value, dict):
        records = (value.get('data_receipts') or value.get('rows') or
                   value.get('symbols') or (value.get('selection') or {}).get('symbols'))
    else:
        records = None
    if not isinstance(records, list) or not records:
        raise ValueError('symbols manifest needs a nonempty list, rows, symbols or data_receipts')
    normalized = []
    seen = set()
    for record in records:
        row = {'symbol': record} if isinstance(record, str) else dict(record)
        if row.get('state') in {'failed', 'error'}:
            raise ValueError('symbols manifest contains failed collection: ' + str(row.get('symbol')))
        code = data._code(row.get('symbol') or row.get('code'))
        if code in seen:
            raise ValueError('duplicate symbol in manifest: ' + code)
        seen.add(code)
        metadata = row.get('metadata') or row
        if not metadata.get('raw_sha256'):
            reference = RUNTIME / 'datasets' / (code + '__day.json')
            if not reference.is_file():
                raise ValueError('offline data receipt missing for ' + code)
            metadata = read_json(reference)
        normalized.append({'symbol': code, 'name': row.get('name', code), 'metadata': metadata})
    return normalized


def load_dataset(receipt, *, benchmark=False):
    """Use immutable raw objects, never a subsequently replaced dataset ref."""
    metadata = dict(receipt.get('metadata') or receipt)
    code = data._code(receipt.get('symbol', 'sh000001'), benchmark=benchmark)
    raw_sha = metadata.get('raw_sha256')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', str(raw_sha)):
        raise ValueError('raw SHA256 receipt missing for ' + code)
    path = Path(metadata.get('raw_path') or RUNTIME / 'raw' / (raw_sha + '.json.gz'))
    if not path.is_file():
        path = RUNTIME / 'raw' / (raw_sha + '.json.gz')
    raw = gzip.decompress(path.read_bytes())
    if digest(raw) != raw_sha:
        raise ValueError('raw response hash mismatch: ' + code)
    envelope = json.loads(raw)
    if envelope.get('code') != 0 or not isinstance(envelope.get('data'), dict):
        raise ValueError('cached envelope invalid: ' + code)
    bars, normalized = data.normalize_daily(envelope['data'], code, metadata['received_at'], benchmark=benchmark)
    expected = metadata.get('input_sha256')
    if expected and expected != normalized['input_sha256']:
        raise ValueError('normalized input hash mismatch: ' + code)
    closed = [row for row in bars if row['is_closed']]
    ledger_digest = hashlib.sha256()
    for row in closed:
        ledger_digest.update(json.dumps([row[key] for key in
            ('closed_at', 'open', 'high', 'low', 'close', 'volume')], separators=(',', ':')).encode() + b'\n')
    return closed, {**metadata, **normalized, 'raw_path': str(path.resolve()),
                    'raw_sha256': raw_sha, 'closed_prefix_sha256': ledger_digest.hexdigest()}


def source_hashes():
    paths = ['chanmodel/bottom_research.py', 'chanmodel/causal_replay.py', 'chanmodel/model.py',
             'chanmodel/structure.py', 'chanmodel/segments.py', 'chanmodel/signals.py',
             'chanmodel/v2/recursive.py', 'chanmodel/v2/series.py', 'web/bottom_data.py',
             'scripts/validate_bottom_accuracy.py']
    result = {path: digest((ROOT / path).read_bytes()) for path in paths}
    result['frozen_baseline_module'] = digest(BASELINE_FILE.read_bytes())
    return result


class PivotObserver:
    """Record first-seen daily fractals and every later withdrawal/revision."""
    GEOMETRY = ('kind', 'source', 'price', 'center_high', 'center_low',
                'group_start', 'group_end', 'basis_at', 'components')

    def __init__(self, symbol):
        self.symbol = symbol
        self.active = {}
        self.generations = Counter()
        self.records = []
        self.events = []
        self.last_fractals = None

    def _signature(self, fractal):
        return tuple(json.dumps(fractal.get(key), sort_keys=True, separators=(',', ':'))
                     for key in self.GEOMETRY)

    def _withdraw(self, record, index, timestamp, reason):
        record['status'] = 'withdrawn'
        record['withdrawn_at_index'] = index
        record['withdrawn_at'] = timestamp
        record['withdrawal_reason'] = reason
        self.events.append({'event': 'withdrawn', 'symbol': self.symbol,
                            'candidate_id': record['candidate_id'],
                            'fractal_id': record['fractal_id'], 'kind': record['kind'],
                            'anchor_index': record['source'], 'anchor_time': record['anchor_time'],
                            'price': record['price'], 'first_available_index': record['first_available_index'],
                            'first_available_time': record['first_available_time'],
                            'observed_index': index, 'observed_time': timestamp,
                            'basis_at': record['basis_at'], 'reason': reason})

    def observe(self, fractals, bars):
        if fractals is self.last_fractals:
            return
        self.last_fractals = fractals
        index = len(bars) - 1
        timestamp = bars[index].closed_at
        present = {row['id']: row for row in fractals}
        # Withdraw an earlier observation before accepting any revised geometry.
        for fractal_id, record in list(self.active.items()):
            fractal = present.get(fractal_id)
            if fractal is None:
                self._withdraw(record, index, timestamp, 'fractal_absent_from_current_prefix')
                del self.active[fractal_id]
            elif fractal is not record.get('_fractal') and self._signature(fractal) != record['_signature']:
                self._withdraw(record, index, timestamp, 'fractal_geometry_revised')
                del self.active[fractal_id]
        for fractal_id, fractal in present.items():
            if fractal_id in self.active:
                self.active[fractal_id]['last_present_index'] = index
                continue
            source = fractal.get('source')
            basis = fractal.get('basis_at')
            if type(source) is not int or not 0 <= source <= index or type(basis) is not int or basis > index:
                raise ValueError('fractal source/basis is not available in the current closed prefix')
            self.generations[fractal_id] += 1
            generation = self.generations[fractal_id]
            record = {'candidate_id': f'{self.symbol}:{fractal_id}:observation:{generation}',
                      'fractal_id': fractal_id, 'symbol': self.symbol,
                      'kind': fractal['kind'], 'source': source, 'anchor_index': source,
                      'anchor_time': bars[source].closed_at, 'price': fractal['price'],
                      'center_high': fractal.get('center_high'), 'center_low': fractal.get('center_low'),
                      'group_start': fractal.get('group_start'), 'group_end': fractal.get('group_end'),
                      'basis_at': basis, 'first_available_index': index,
                      'first_available_time': timestamp, 'confirmation_delay_sessions': index - source,
                      'status': 'observed', 'last_present_index': index,
                      '_signature': self._signature(fractal), '_fractal': fractal}
            self.records.append(record)
            self.active[fractal_id] = record
            self.events.append({key: value for key, value in record.items() if not key.startswith('_')}
                               | {'event': 'candidate_observed', 'observed_index': index,
                                  'observed_time': timestamp,
                                  'observation_semantics': 'first closed prefix where fractal object is present'})


def replay(module, code, rows, benchmark):
    session = module.BottomSession(code, benchmark_by_date=benchmark)
    pivots = PivotObserver(code)
    for row in rows:
        session.append(row)
        pivots.observe(session.stream.fractals, session.bars)
    # Snapshot builds the recursive chart hierarchy; evaluation needs only events.
    return session.events, session.bars, pivots.records, pivots.events


def replay_pivots(module, code, rows):
    """Fast pivot-only replay when an old bottom-event ledger is cached."""
    stream = module.StreamingStructure(module.CONFIG, segments=False)
    pivots = PivotObserver(code)
    bars = []
    for row in rows:
        bar = module._bar(row, len(bars))
        stream.append(bar)
        bars.append(bar)
        pivots.observe(stream.fractals, bars)
    return pivots.records, pivots.events, bars


def cached_baseline_events(run, folder, code, metadata, baseline_hash, dependencies_match):
    path = folder / 'events' / (code + '.json.gz')
    manifest_hash = run.get('source_manifest', {}).get('files', {}).get('chanmodel/bottom_research.py')
    if not path.is_file() or manifest_hash != baseline_hash or not dependencies_match:
        return None
    payload = read_json(path)
    if payload.get('symbol') != code or payload.get('input_sha256') != metadata['closed_prefix_sha256']:
        return None
    return payload['events']


def unique_signals(events, state, bars):
    selected = {}
    for event in sorted(events, key=lambda row: (row.get('available_at_index', -1), row.get('sequence', -1))):
        if event.get('state') != state:
            continue
        episode = event.get('episode_id')
        if not episode:
            raise ValueError('signal event is missing episode_id')
        index = event.get('available_at_index')
        if type(index) is not int or not 0 <= index < len(bars):
            raise ValueError('signal first-available index outside closed prefix')
        if event.get('available_time') != bars[index].closed_at:
            raise ValueError('signal first-available time does not match source candle')
        if event.get('anchor_index', index) > index:
            raise ValueError('signal anchor occurs after evidence')
        selected.setdefault(episode, event)
    return list(selected.values())


def evaluate_signals(code, bars, events, state, benchmark, splits):
    signals = unique_signals(events, state, bars)
    # evaluate_events is unchanged and accepts base_formed. This temporary alias
    # selects an evaluation entry time; actual signal states remain explicit.
    aliases = [{**event, 'state': 'base_formed'} for event in signals]
    evaluated = current.evaluate_events(code, bars, aliases, benchmark_by_date=benchmark)
    by_id = {event['id']: event for event in signals}
    by_episode = defaultdict(dict)
    for event in events:
        if event.get('episode_id') and event.get('state') in ('bottom_watch', *STATES):
            by_episode[event['episode_id']].setdefault(event['state'], event)
    result = []
    for label in evaluated:
        event = by_id[label['event_id']]
        episode = by_episode[event['episode_id']]
        available = event['available_at_index']
        end = label.get('max_observed_index', available)
        gap = [index for index in range(max(1, available - 60), min(len(bars), end + 1))
               if abs(bars[index].open / bars[index - 1].close - 1) > .25]
        label.update(actual_signal_state=state, episode_id=event['episode_id'],
                     first_available_time=event['available_time'],
                     first_available_index=available,
                     anchor_time=event.get('anchor_time'),
                     evidence_anchor_delay_sessions=available - event.get('anchor_index', available),
                     delay_from_base_sessions=available - episode.get('base_formed', event)['available_at_index'],
                     delay_from_watch_sessions=available - episode.get('bottom_watch', event)['available_at_index'])
        if gap:
            label['exclusion'] = 'unverified_large_price_discontinuity'
            label['excluded_gap_indices'] = gap
        result.append(label)
    # This is the identical evaluator and purge convention for both engines.
    current.split_outcomes(result, splits)
    evaluated_ids = {label['event_id'] for label in result}
    for event in signals:
        if event['id'] not in evaluated_ids:
            result.append({'symbol': code, 'event_id': event['id'], 'episode_id': event['episode_id'],
                           'actual_signal_state': state, 'state': 'pending_next_session', 'split': 'censored',
                           'first_available_time': event['available_time'],
                           'first_available_index': event['available_at_index'],
                           'outcome_complete': False, 'return': None})
    return result


def false_breakouts(events, bars, splits):
    """Forward outcome diagnostics; never used as a signal-generation feature."""
    result = []
    for event in unique_signals(events, 'departure', bars):
        index = event['available_at_index']
        resistance = event.get('resistance')
        if not resistance or resistance <= 0:
            raise ValueError('departure resistance missing')
        horizon_end = index + current.HORIZON
        end = min(len(bars) - 1, horizon_end)
        subsequent = [row for row in events if row.get('episode_id') == event['episode_id']
                      and index < row.get('available_at_index', -1) <= end]
        first_ledger_retest = next((row for row in subsequent
                                   if row.get('state') in {'retest_failed', 'retest_held'}), None)
        first_touch = next((i for i in range(index + 1, end + 1)
                            if bars[i].low <= resistance * (1 + current.RETEST_BAND)), None)
        touch_failed = (bars[first_touch].low < resistance * (1 - current.RETEST_BAND)
                        or bars[first_touch].close <= resistance) if first_touch is not None else None
        label_end = first_touch if first_touch is not None else end
        pseudo_label = {'entry_time': bars[min(index + 1, len(bars) - 1)].closed_at,
                        'label_end_time': bars[label_end].closed_at,
                        'outcome_complete': first_touch is not None or end == horizon_end,
                        'horizon_complete': end == horizon_end}
        current.split_outcomes([pseudo_label], splits)
        result.append({'symbol': event['symbol'], 'episode_id': event['episode_id'],
                       'departure_index': index, 'departure_time': event['available_time'],
                       'max_observed_index': end, 'horizon_complete': end == horizon_end,
                       'split': pseudo_label['split'],
                       'explicit_first_retest_failed': first_ledger_retest is not None and first_ledger_retest['state'] == 'retest_failed',
                       'explicit_retest_state': first_ledger_retest['state'] if first_ledger_retest else None,
                       'first_touch_index': first_touch, 'uniform_first_touch_failed': touch_failed,
                       'uniform_first_touch_delay': first_touch - index if first_touch is not None else None,
                       'diagnostic_uses_future_outcome_only': True})
    return result


def evaluate_pivots(code, bars, pivots, kind, splits):
    """Evaluate first-seen pivots with symmetric bottom/avoidance barriers."""
    output = []
    for pivot in pivots:
        if pivot['kind'] != kind:
            continue
        available = pivot['first_available_index']
        item = {key: value for key, value in pivot.items() if not key.startswith('_')}
        item.update(actual_signal_state='candidate_observed', pivot_kind=kind,
                    _total_bars=len(bars),
                    state='pending_next_session', outcome_complete=False,
                    execution_allowed=False, target=current.TARGET_RETURN,
                    invalidation_buffer=current.STOP_BUFFER, horizon=current.HORIZON,
                    entry_time=None, exit_time=None, directional_proxy_return=None, **{'return':None},
                    outcome_semantics=('long-directional bottom reversal proxy' if kind == 'bottom'
                                       else 'top avoidance/downside mirror proxy; not a short fill'))
        if available + 1 >= len(bars):
            item.update(split='censored', max_observed_index=available,
                        label_end_time=bars[available].closed_at)
            output.append(item)
            continue
        entry_index = available + 1
        entry = bars[entry_index].open
        anchor_price = pivot['price']
        stop = anchor_price * (1 - current.STOP_BUFFER if kind == 'bottom'
                               else 1 + current.STOP_BUFFER)
        target = entry * (1 + current.TARGET_RETURN if kind == 'bottom'
                          else 1 - current.TARGET_RETURN)
        is_gap_invalid = entry <= stop if kind == 'bottom' else entry >= stop
        if is_gap_invalid:
            outcome = 'invalidated_before_entry'
            end = entry_index
            exit_price = entry
            directional_return = None
            complete = False
        else:
            end = min(len(bars) - 1, entry_index + current.HORIZON - 1)
            outcome = 'right_censored'
            exit_price = bars[end].close
            exit_index = end
            for index in range(entry_index + 1, end + 1):
                bar = bars[index]
                stop_hit = bar.low <= stop if kind == 'bottom' else bar.high >= stop
                target_hit = bar.high >= target if kind == 'bottom' else bar.low <= target
                # Resolve same-bar ambiguity against the candidate.
                if stop_hit:
                    outcome = 'stop'
                    exit_price = (min(bar.open, stop) if kind == 'bottom' and bar.open < stop
                                  else max(bar.open, stop) if kind == 'top' and bar.open > stop
                                  else stop)
                    exit_index = index
                    break
                if target_hit:
                    outcome = 'target'
                    exit_price = (max(bar.open, target) if kind == 'bottom' and bar.open > target
                                  else min(bar.open, target) if kind == 'top' and bar.open < target
                                  else target)
                    exit_index = index
                    break
            horizon_complete = end == entry_index + current.HORIZON - 1
            complete = outcome in {'target', 'stop'} or horizon_complete
            if not complete:
                exit_index = end
            directional_return = ((exit_price / entry - 1) if kind == 'bottom'
                                  else ((entry - exit_price) / entry)) - current.ROUND_TRIP_COST
        if is_gap_invalid:
            horizon_complete = False
            exit_index = entry_index
        item.update(state=outcome, available_at_index=available,
                    first_available_index=available, first_available_time=pivot['first_available_time'],
                    entry_index=entry_index, entry_price=entry, entry_time=bars[entry_index].closed_at,
                    stop_price=stop, target_price=target, exit_index=exit_index,
                    exit_time=bars[exit_index].closed_at, exit_price=exit_price,
                    gross_directional_return=(0.0 if is_gap_invalid else
                        ((exit_price / entry - 1) if kind == 'bottom' else ((entry - exit_price) / entry))),
                    directional_proxy_return=directional_return,
                    outcome_complete=complete, horizon_complete=horizon_complete,
                    max_observed_index=end, label_end_time=bars[end].closed_at,
                    signal_time=pivot['first_available_time'],
                    signal_to_exit_sessions=exit_index - available)
        item['return']=directional_return
        start = max(1, available - 60)
        gaps = [index for index in range(start, min(len(bars), end + 1))
                if abs(bars[index].open / bars[index - 1].close - 1) > .25]
        if gaps:
            item['exclusion'] = 'unverified_large_price_discontinuity'
            item['excluded_gap_indices'] = gaps
        output.append(item)
    current.split_outcomes(output, splits)
    return output


def pivot_metrics(rows, kind, symbols, total_bars):
    eligible = [row for row in rows if not row.get('exclusion')]
    complete = [row for row in eligible
                if row.get('outcome_complete') and isinstance(row.get('return'), (float, int))]
    targets = sum(row['state'] == 'target' for row in complete)
    returns = [row['return'] for row in complete]
    mature = [row for row in rows
              if row['first_available_index'] + current.HORIZON < row.get('_total_bars', 0)]
    withdrawn = [row for row in mature
                 if row.get('withdrawn_at_index') is not None and
                 row['withdrawn_at_index'] <= row['first_available_index'] + current.HORIZON]
    return {'pivot_kind': kind, 'candidate_observations': len(rows),
            'events_after_gap_exclusion': len(eligible), 'gap_exclusions': len(rows) - len(eligible),
            'evaluated_outcomes': len(complete), 'right_censored_or_purged': len(eligible) - len(complete),
            'target_hits': targets, 'target_precision': targets / len(complete) if complete else None,
            'positive_directional_return_rate': sum(value > 0 for value in returns) / len(returns) if returns else None,
            'mean_directional_proxy_return': mean(returns), 'median_directional_proxy_return': median(returns),
            'median_confirmation_delay_sessions': median([r['confirmation_delay_sessions'] for r in rows]),
            'median_signal_to_target_sessions': median([r['signal_to_exit_sessions'] for r in complete if r['state'] == 'target']),
            'symbol_coverage': len({r['symbol'] for r in rows}) / len(symbols) if symbols else None,
            'candidates_per_1000_closed_bars': len(rows) * 1000 / total_bars if total_bars else None,
            'withdrawal_window_sessions': current.HORIZON,
            'withdrawal_observable_candidates': len(mature),
            'withdrawn_within_window': len(withdrawn),
            'withdrawal_rate_within_window': len(withdrawn) / len(mature) if mature else None,
            'withdrawal_window_right_censored': len(rows) - len(mature),
            'withdrawal_state_at_data_end': sum(r.get('status') == 'withdrawn' for r in rows),
            'outcomes': dict(Counter(row['state'] for row in eligible))}


def pivot_bootstrap(rows, symbols, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    counts={symbol:[0,0,0,0,0] for symbol in symbols}
    for row in rows:
        c=counts[row['symbol']]
        complete=(not row.get('exclusion') and row.get('outcome_complete') and isinstance(row.get('return'),(float,int)))
        if complete:
            c[0]+=1;c[1]+=row['state']=='target';c[2]+=row['return']>0
        mature=row['first_available_index']+current.HORIZON<row.get('_total_bars',0)
        if mature:
            c[3]+=1;c[4]+=row.get('withdrawn_at_index') is not None and row['withdrawn_at_index']<=row['first_available_index']+current.HORIZON
    rng=random.Random(seed);trials=[[],[],[]]
    for _ in range(draws):
        picked=[counts[rng.choice(symbols)] for _ in symbols]
        totals=[sum(c[i] for c in picked) for i in range(5)]
        for i,v in enumerate((totals[1]/totals[0] if totals[0] else None,totals[2]/totals[0] if totals[0] else None,totals[4]/totals[3] if totals[3] else None)):
            if v is not None:trials[i].append(v)
    def interval(values):
        values.sort()
        return [values[int(.025*len(values))],values[min(len(values)-1,int(.975*len(values)))]] if values else None
    return {'method':'symbol-cluster bootstrap with replacement; lifecycle events stay within symbol',
            'resamples':draws,'seed':seed,'target_precision_95pct_ci':interval(trials[0]),
            'positive_directional_return_95pct_ci':interval(trials[1]),'withdrawal_rate_within_window_95pct_ci':interval(trials[2])}


def mean(values):
    return statistics.fmean(values) if values else None


def median(values):
    return statistics.median(values) if values else None


def metrics(rows, total_symbols, base_count):
    eligible = [row for row in rows if not row.get('exclusion')]
    complete = [row for row in eligible if row.get('outcome_complete', row.get('horizon_complete'))
                and isinstance(row.get('return'), (float, int))]
    returns = [row['return'] for row in complete]
    targets = sum(row['state'] == 'target' for row in complete)
    return {'signals': len(rows), 'excluded': len(rows) - len(eligible), 'evaluated': len(complete),
            'unevaluated_or_purged': len(eligible) - len(complete), 'symbols_with_signals': len({row['symbol'] for row in eligible}),
            'symbol_coverage': len({row['symbol'] for row in eligible}) / total_symbols if total_symbols else None,
            'relative_signal_count_to_same_engine_base': len(rows) / base_count if base_count else None,
            'target_hits': targets, 'target_precision': targets / len(complete) if complete else None,
            'positive_return_rate': sum(value > 0 for value in returns) / len(returns) if returns else None,
            'stops': sum(row['state'] == 'stop' for row in complete),
            'mean_return': mean(returns), 'median_return': median(returns),
            'mean_excess_return': mean([row['excess_return'] for row in complete if row.get('excess_return') is not None]),
            'median_evidence_anchor_delay_sessions': median([row['evidence_anchor_delay_sessions'] for row in eligible if 'evidence_anchor_delay_sessions' in row]),
            'median_delay_from_base_sessions': median([row['delay_from_base_sessions'] for row in eligible if 'delay_from_base_sessions' in row]),
            'median_delay_from_watch_sessions': median([row['delay_from_watch_sessions'] for row in eligible if 'delay_from_watch_sessions' in row]),
            'median_signal_to_target_sessions': median([row['exit_index'] - row['first_available_index'] for row in complete if row['state'] == 'target']),
            'outcomes': dict(Counter(row['state'] for row in eligible))}


def bootstrap(models, symbols, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    aggregate = {}
    for model, rows in models.items():
        by_symbol = {symbol: [0, 0, 0] for symbol in symbols}
        for row in rows:
            if row.get('exclusion') or not row.get('outcome_complete', row.get('horizon_complete')) or row.get('return') is None:
                continue
            value = by_symbol[row['symbol']]
            value[0] += 1
            value[1] += row['state'] == 'target'
            value[2] += row['return'] > 0
        aggregate[model] = by_symbol
    rng = random.Random(seed)
    samples = {model: {'target_precision': [], 'positive_return_rate': []} for model in models}
    differences = {'target_precision': [], 'positive_return_rate': []}
    for _ in range(draws):
        selection = [rng.choice(symbols) for _ in symbols]
        rates = {}
        for model, by_symbol in aggregate.items():
            count = sum(by_symbol[symbol][0] for symbol in selection)
            rates[model] = [sum(by_symbol[symbol][index] for symbol in selection) / count if count else None for index in (1, 2)]
            for index, key in enumerate(('target_precision', 'positive_return_rate')):
                if rates[model][index] is not None:
                    samples[model][key].append(rates[model][index])
        for index, key in enumerate(('target_precision', 'positive_return_rate')):
            if rates['baseline'][index] is not None and rates['current'][index] is not None:
                differences[key].append(rates['current'][index] - rates['baseline'][index])
    def interval(values):
        values.sort()
        return [values[int(.025 * len(values))], values[min(len(values)-1, int(.975 * len(values)))]] if values else None
    return {'method': 'paired bootstrap resampling symbols with replacement; events stay clustered',
            'resamples': draws, 'seed': seed, 'symbols': len(symbols),
            'model_95pct_intervals': {model: {key: interval(value) for key, value in result.items()} for model, result in samples.items()},
            'current_minus_baseline_95pct_intervals': {key: interval(value) for key, value in differences.items()}}


def breakout_bootstrap(models, symbols, split, draws=BOOTSTRAP_DRAWS):
    rng = random.Random(BOOTSTRAP_SEED + sum(ord(char) for char in split))
    clustered = {model: defaultdict(list) for model in models}
    for model, rows in models.items():
        for row in rows:
            if split == 'all' or row.get('split') == split:
                clustered[model][row['symbol']].append(row)
    rates = {'baseline': [], 'current': []}
    differences = []
    for _ in range(draws):
        chosen = [rng.choice(symbols) for _ in symbols]
        trial = {}
        for model in ('baseline', 'current'):
            touched = [row for symbol in chosen for row in clustered[model][symbol]
                       if row['first_touch_index'] is not None]
            trial[model] = (sum(row['uniform_first_touch_failed'] is True for row in touched) / len(touched)
                            if touched else None)
            if trial[model] is not None:
                rates[model].append(trial[model])
        if trial['baseline'] is not None and trial['current'] is not None:
            differences.append(trial['current'] - trial['baseline'])
    def interval(values):
        values.sort()
        return [values[int(.025 * len(values))], values[min(len(values)-1, int(.975 * len(values)))]] if values else None
    return {'method': 'paired bootstrap resampling symbols with replacement', 'resamples': draws,
            'seed': BOOTSTRAP_SEED + sum(ord(char) for char in split),
            'per_model_failure_rate_95pct_ci': {model: interval(values) for model, values in rates.items()},
            'current_minus_baseline_failure_rate_95pct_ci': interval(differences)}


def summarize_breakouts(rows):
    touched = [row for row in rows if row['first_touch_index'] is not None]
    failures = sum(row['uniform_first_touch_failed'] is True for row in touched)
    return {'departures': len(rows), 'explicit_first_retest_failed': sum(row['explicit_first_retest_failed'] for row in rows),
            'uniform_first_touch_observed': len(touched), 'uniform_first_touch_failed': failures,
            'uniform_first_touch_failure_rate_among_touched': failures / len(touched) if touched else None,
            'without_touch_and_right_censored': sum(row['first_touch_index'] is None and not row['horizon_complete'] for row in rows),
            'median_first_touch_delay_sessions': median([row['uniform_first_touch_delay'] for row in touched]),
            'symbols_with_departure': len({row['symbol'] for row in rows})}


def report_markdown(report):
    def percent(value):
        return '—' if value is None else f'{value:.2%}'
    lines = ['# Bottom accuracy paired comparison', '',
             f'- Baseline: `{report["models"]["baseline"]["version"]}`; current: `{report["models"]["current"]["version"]}`.',
             f'- Scope: `{report["dataset_scope"]}`; {report["successful_symbols"]}/{report["requested_symbols"]} symbols; {report["closed_bars"]:,} closed daily bars.',
             '- Every state is evaluated at its first available event per episode, followed by next-session-open entry.',
             '- Shared rule: +10% target/support stop, 20 sessions, T+1 exits, same-bar stop first, estimated 0.2% round-trip cost.',
             '- No strategy selection or automatic promotion is performed.', '',
             '|Period|Model|Actual signal|Evaluated|Target precision|Positive return|Signal count/base|Median delay from base|',
             '|---|---|---|---:|---:|---:|---:|---:|']
    for split, states in report['metrics'].items():
        for state, values in states.items():
            for model in ('baseline', 'current'):
                m = values[model]
                lines.append(f'|{split}|{model}|{state}|{m["evaluated"]}|{percent(m["target_precision"])}|{percent(m["positive_return_rate"])}|{percent(m["relative_signal_count_to_same_engine_base"])}|{m["median_delay_from_base_sessions"]}|')
    lines += ['', '## False breakouts after departure', '',
              '|Period|Model|Departures|First retest observed|First retest failed|Failure rate among touched|Median touch delay|',
              '|---|---|---:|---:|---:|---:|---:|']
    for split in SPLITS:
        for model in ('baseline', 'current'):
            m = report['false_breakouts'][split][model]
            lines.append(f'|{split}|{model}|{m["departures"]}|{m["uniform_first_touch_observed"]}|{m["uniform_first_touch_failed"]}|{percent(m["uniform_first_touch_failure_rate_among_touched"])}|{m["median_first_touch_delay_sessions"]}|')
    lines += ['', '## Limits', ''] + ['- ' + line for line in report['limitations']]
    lines += ['', '## First retest diagnostics', '',
              '- Explicit `retest_failed` counts depend on the ledger vocabulary. The old engine did not emit that event.',
              '- `uniform_first_touch_failed` uses the identical first-touch OHLC test in both models and is only a forward outcome, never a decision input.',
              '- Exact raw/input/source hashes and symbol-cluster 95% intervals are retained in report.json.',
              '- Full labels and immutable input receipts are in outcomes.json.gz and input-manifest.json.']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols-manifest', type=Path, help='offline collection manifest or symbols list')
    parser.add_argument('--baseline-run', help='defaults to newest completed 240-symbol run')
    parser.add_argument('--output', type=Path, default=RUNTIME / 'accuracy-v11/comparison')
    args = parser.parse_args(argv)
    output = args.output if args.output.suffix.lower() not in {'.json', '.md'} else args.output.parent
    if (output / 'report.json').exists():
        raise ValueError('output already contains report.json; choose a fresh directory')
    baseline = load_baseline()
    run, folder = choose_run(args.baseline_run)
    records = receipt_records(args.symbols_manifest, run)
    benchmark_rows, benchmark_receipt = load_dataset({'symbol': 'sh000001', 'metadata': run['benchmark_receipt']}, benchmark=True)
    benchmark = {row['closed_at'][:10]: row['close'] for row in benchmark_rows}
    splits = run.get('split_dates') or run.get('validation_protocol', {}).get('split')
    if not splits or not splits.get('trading_dates'):
        raise ValueError('baseline time boundaries and session map unavailable')
    source_start = source_hashes()
    baseline_symbols = {row['symbol'] for row in run['data_receipts']}
    selected_symbols = [row['symbol'] for row in records]
    overlap = sorted(set(selected_symbols) & baseline_symbols)
    scope = 'new_symbol_holdout_with_frozen_date_boundaries' if args.symbols_manifest and not overlap else 'retrospective_regression'
    old_dependencies = run.get('source_manifest', {}).get('files', {})
    dependency_paths = ('chanmodel/structure.py', 'chanmodel/segments.py', 'chanmodel/causal_replay.py')
    deps_match = all(old_dependencies.get(path) == source_start.get(path) for path in dependency_paths)
    labels = {model: {state: [] for state in STATES} for model in ('baseline', 'current')}
    breakouts = {model: [] for model in labels}
    pivot_labels={kind:[] for kind in ('top','bottom')};pivot_ledger=[]
    receipts = []
    failures = []
    started = time.perf_counter()
    reused = 0
    for number, record in enumerate(records, 1):
        code = record['symbol']
        try:
            rows, metadata = load_dataset(record)
            old_events = cached_baseline_events(run, folder, code, metadata,
                                               source_start['frozen_baseline_module'], deps_match)
            old_cached = old_events is not None
            if not old_cached:
                old_events, bars, old_pivots, old_pivot_events = replay(baseline, code, rows, benchmark)
            else:
                bars = [current._bar(row, index) for index, row in enumerate(rows)]
                reused += 1
            new_events, new_bars, new_pivots, new_pivot_events = replay(current, code, rows, benchmark)
            if len(new_bars) != len(bars):
                raise ValueError('engines did not retain the same closed input count')
            for model, events in (('baseline', old_events), ('current', new_events)):
                for state in STATES:
                    labels[model][state].extend(evaluate_signals(code, bars, events, state, benchmark, splits))
                breakouts[model].extend(false_breakouts(events, bars, splits))
            for kind in ('top','bottom'):
                pivot_labels[kind].extend(evaluate_pivots(code,bars,new_pivots,kind,splits))
            pivot_ledger.extend(new_pivot_events)
            receipts.append({'symbol': code, 'name': record.get('name', code), 'metadata': metadata,
                             'baseline_events_reused': old_cached,
                             'bars': len(rows)})
        except Exception as error:
            failures.append({'symbol': code, 'error': type(error).__name__ + ': ' + str(error)[:400]})
        progress = {'completed': number, 'total': len(records), 'last_symbol': code,
                    'successful': len(receipts), 'failed': len(failures), 'seconds': round(time.perf_counter() - started, 2)}
        write_json(output / 'progress.json', progress)
        print(json.dumps(progress, ensure_ascii=False), flush=True)
    if source_hashes() != source_start:
        raise ValueError('source changed during replay; results rejected')
    symbols = [record['symbol'] for record in receipts]
    if not symbols:
        raise ValueError('no usable paired offline samples')
    comparison = {}
    for split in SPLITS:
        comparison[split] = {}
        for state in STATES:
            chosen = {model: [row for row in labels[model][state] if split == 'all' or row.get('split') == split]
                      for model in labels}
            base_counts = {model: sum(split == 'all' or row.get('split') == split for row in labels[model]['base_formed']) for model in labels}
            comparison[split][state] = {
                **{model: metrics(rows, len(symbols), base_counts[model]) for model, rows in chosen.items()},
                'cluster_bootstrap': bootstrap(chosen, symbols)}
    false_summary = {}
    for split in SPLITS:
        false_summary[split] = {model: summarize_breakouts(
            [row for row in records_ if split == 'all' or row.get('split') == split])
                                for model, records_ in breakouts.items()}
        false_summary[split]['cluster_bootstrap'] = breakout_bootstrap(breakouts, symbols, split)
    pivot_summary={}
    for split in SPLITS:
        pivot_summary[split]={}
        for kind in ('top','bottom'):
            chosen=[r for r in pivot_labels[kind] if split=='all' or r.get('split')==split]
            pivot_summary[split][kind]={**pivot_metrics(chosen,kind,symbols,sum(r['bars'] for r in receipts)),'cluster_bootstrap':pivot_bootstrap(chosen,symbols)}
    report = {'report_version': 'bottom_accuracy_paired_v1', 'created_at': datetime.now(CN).isoformat(timespec='seconds'),
              'state': 'completed' if not failures else 'partial', 'dataset_scope': scope,
              'baseline_run': run['id'], 'symbols_manifest': str(args.symbols_manifest.resolve()) if args.symbols_manifest else None,
              'baseline_symbol_overlap': overlap, 'requested_symbols': len(records), 'successful_symbols': len(receipts),
              'closed_bars': sum(row['bars'] for row in receipts), 'baseline_cached_event_symbols': reused,
              'source_hashes': source_start, 'source_unchanged_through_replay': True,
              'models': {'baseline': {'version': baseline.BOTTOM_VERSION, 'module': str(BASELINE_FILE)},
                         'current': {'version': current.BOTTOM_VERSION, 'module': str(ROOT / 'chanmodel/bottom_research.py')}},
              'evaluation': {'entry': 'next_session_open', 'exit_earliest': 'session_after_entry_T_plus_1',
                             'states': STATES, 'event_counting': 'first_available_per_model_per_state_per_episode',
                             'temporary_state_alias_for_evaluator_only': 'base_formed',
                             'horizon': current.HORIZON, 'target': current.TARGET_RETURN,
                             'round_trip_cost': current.ROUND_TRIP_COST, 'same_bar_order': 'stop_first',
                             'evaluator_sha256': digest(inspect.getsource(current.evaluate_events).encode()),
                             'same_input_benchmark_split': True, 'source_selection_or_promotion': False,
                             'test_period_interpretation': 'unseen_symbols_with_preexisting_dates' if scope.startswith('new_symbol') else 'retrospective_regression_already_examined'},
              'splits': {key: value for key, value in splits.items() if key != 'trading_dates'},
              'metrics': comparison, 'false_breakouts': false_summary, 'pivot_observations':pivot_summary,
              'pivot_semantics':'first closed-prefix fractal observation; later withdrawal retained; shared base fractal rules unchanged between versions', 'failures': failures,
              'limitations': ['Bottom structure proxies are not proven equivalent to original Chan buy/sell classes.',
                              'The old test period was already inspected; its results are retrospective regression.',
                              'Current listed-symbol universe has survivorship bias; unadjusted OHLC corporate actions are incompletely certified.',
                              'Large-gap windows are excluded under the same frozen rule in both models.',
                              'Statistics are independent event outcomes, not a shared-capital portfolio; within-symbol events may overlap.',
                              'Fund-flow publication history is unavailable and excluded; chips and emotion remain explicit proxies.',
                              'No rule tuning, best-state selection, promotion, Git operation or order execution occurs in this script.'],
              'execution_allowed': False}
    write_json(output / 'input-manifest.json', {'benchmark': benchmark_receipt, 'symbols': receipts,
                                             'same_input_hashes': True, 'source_hashes': source_start})
    compressed = gzip.compress(json.dumps({'labels': labels, 'false_breakout_outcomes': breakouts,'pivot_labels':pivot_labels,'pivot_ledger':pivot_ledger},
                                          ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode(), mtime=0)
    (output / 'outcomes.json.gz').write_bytes(compressed)
    report['outcomes_file_sha256'] = digest(compressed)
    write_json(output / 'report.json', report)
    (output / 'report.md').write_text(report_markdown(report), encoding='utf-8')
    print(json.dumps({'state': report['state'], 'report': str((output / 'report.json').resolve()),
                      'successful': len(receipts), 'failed': len(failures)}, ensure_ascii=False), flush=True)
    return 0 if not failures else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        raise SystemExit(1)
