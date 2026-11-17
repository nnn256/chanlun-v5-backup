"""Causal all-market backtest for the pinned native Chan structure engine."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
from dataclasses import asdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import time

from .causal_portfolio import CostModel, simulate
from .reference_engine import PROFILE, COMMIT, ReferenceSession
from .model import time_value
from .tdx_data import atomic_bytes, atomic_json
from .v2.io import load_cache_series


BACKTEST_PROFILE = 'v4_native_chan_next_open_t1_v3'


def _candidate_event(event):
    return event.get('event') in {'appeared', 'reappeared'} and event.get('state') == 'candidate'


def native_backtest_events(engine_events, bars, extrema=None):
    """Translate append-time engine events without consulting final signal states."""
    identities = {}
    candidates = []
    confirmations = []
    history = []
    for event in engine_events:
        ident = event.get('id')
        if not ident:
            continue
        if event.get('rank') is not None:
            metadata = {key: event.get(key) for key in ('id', 'rank', 'side', 'native_type', 'anchor')}
            identities[ident] = metadata
        else:
            metadata = identities.get(ident)
        if _candidate_event(event):
            candidates.append({'signal_id': ident, 'observed_index': event['observed_index'],
                               'observed_at': event['observed_at'], **metadata})
            continue
        if event.get('event') in {'withdrawn', 'confirmation_withdrawn'} and metadata:
            history.append({'signal_id': ident, 'event': 'withdrawn',
                            'withdrawal_reason': event.get('event'),
                            'observed_index': event['observed_index'],
                            'observed_at': event['observed_at'], **metadata})
            continue
        if event.get('event') not in {'appeared', 'reappeared', 'structure_completed'}:
            continue
        if event.get('state') != 'structure_complete' or not metadata:
            continue
        index = event['observed_index']
        anchor = metadata['anchor']
        side = metadata['side']
        if type(index) is not int or not 0 <= index < len(bars):
            raise ValueError('native confirmation event index is outside the input bars')
        if type(anchor) is not int or not 0 <= anchor <= index:
            raise ValueError('native confirmation anchor is outside its observed prefix')
        if time_value(event['observed_at']) != time_value(bars[index].closed_at):
            raise ValueError('native confirmation time differs from its observed bar close')
        if side not in {'buy', 'sell'}:
            raise ValueError('native confirmation has an unknown side')
        boundary = bars[anchor].low if side == 'buy' else bars[anchor].high
        confirmations.append({'signal_id': ident, 'event': 'confirmed', 'side': side,
            'rank': metadata['rank'], 'class': f"{metadata['native_type']}_{side}",
            'observed_index': index, 'observed_at': event['observed_at'],
            'invalidation': boundary, 'invalidation_operator':'lt' if side=='buy' else 'gt', 'anchor': anchor,
            'native_type': metadata['native_type']})
        history.append(confirmations[-1])
    for confirmation in confirmations:
        anchor=confirmation['anchor'];available=confirmation['observed_index'];side=confirmation['side']
        boundary=confirmation['invalidation']
        if extrema is not None:
            crossing_index=extrema.first_crossing(available+1,boundary,side)
            crossing=bars[crossing_index] if crossing_index is not None else None
        else:
            crossing=next((bar for bar in bars[available+1:]
                if (bar.low<boundary if side=='buy' else bar.high>boundary)),None)
        if crossing is not None:
            history.append({'signal_id':confirmation['signal_id'],'event':'invalidated',
                'side':side,'rank':confirmation['rank'],'class':confirmation['class'],
                'observed_index':crossing.pos,'observed_at':crossing.closed_at,
                'invalidation':boundary,'invalidation_operator':'lt' if side=='buy' else 'gt',
                'invalidation_price':crossing.low if side=='buy' else crossing.high,
                'anchor':anchor,'native_type':confirmation['native_type']})
    history.sort(key=lambda event:(event['observed_index'],0 if event['event']=='confirmed' else 1,event['signal_id']))
    active={};causal_history=[]
    for event in history:
        ident=event['signal_id']
        if event['event']=='confirmed':
            active[ident]=True;causal_history.append(event);continue
        if event['event'] in {'invalidated','withdrawn'} and active.get(ident,False):
            causal_history.append(event);active[ident]=False
    return {'candidates': candidates, 'confirmations': confirmations, 'events': causal_history}


def backtest_one(record, cache, cutoff, output, cost_values, expected_csv_sha256=None):
    started = time.perf_counter()
    symbol = record['symbol']
    destination = Path(output) / 'stocks' / (symbol + '.json.gz')
    try:
        series, receipt = load_cache_series(Path(cache), symbol, 'day')
        if expected_csv_sha256 and receipt.get('csv_sha256') != expected_csv_sha256:
            raise ValueError('daily source changed after backtest coverage check; create a new run')
        if cutoff:
            series = series.prefix(cutoff)
        bars = series.bars
        if len(bars) < 50:
            raise ValueError(f'insufficient closed daily history: {len(bars)} bars')
        session = ReferenceSession('day', observe=True)
        for bar in bars:
            session.append(bar)
        ledger = native_backtest_events(session.events, bars, session.extrema)
        daily_closes = {bar.closed_at[:10]: bar.close for bar in bars}
        cost = CostModel(**cost_values)
        portfolio = simulate(bars, bars, ledger['events'], daily_closes,
                             cost=cost, period='day', symbol=symbol)
        signal_counts = {}
        for event in ledger['confirmations']:
            key = f"rank_{event['rank']}:{event['native_type']}:{event['side']}"
            signal_counts[key] = signal_counts.get(key, 0) + 1
        summary = {**record, 'state': 'complete', 'profile': BACKTEST_PROFILE,
            'algorithm_profile': PROFILE, 'engine_commit': COMMIT, 'bars': len(bars),
            'first_close': bars[0].closed_at, 'last_close': bars[-1].closed_at,
            'input_sha256': receipt.get('csv_sha256') or series.digest(),
            'candidate_count': len(ledger['candidates']),
            'confirmation_count': len(ledger['confirmations']),
            'withdrawal_count': sum(e['event'] == 'withdrawn' for e in ledger['events']),
            'invalidation_count': sum(e['event'] == 'invalidated' for e in ledger['events']),
            'signal_counts': signal_counts, 'metrics': portfolio['metrics'],
            'seconds': round(time.perf_counter() - started, 3),
            'execution_allowed': False,
            'limitations': ['Unadjusted cached OHLCV; historical dividends, splits, ST and listing status are not universally available.',
                            'Historical source corrections after cache capture are not reconstructed point in time.',
                            'Next-open OHLC fills with declared slippage are a research simulation, not exchange queue replay.']}
        detail = {'summary': summary, 'source_receipt': receipt,
                  'candidate_events': ledger['candidates'], 'confirmation_events': ledger['confirmations'],
                  'lifecycle_events': ledger['events'], 'simulation': portfolio}
        payload = json.dumps(detail, ensure_ascii=False, allow_nan=False,
                             separators=(',', ':')).encode('utf-8')
        atomic_bytes(destination, gzip.compress(payload, compresslevel=3, mtime=0))
        summary['artifact'] = str(destination.resolve())
        summary['artifact_sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
        return summary
    except Exception as exc:
        return {**record, 'state': 'failed',
                'error': f'{type(exc).__name__}: {exc}',
                'seconds': round(time.perf_counter() - started, 3)}


def aggregate(rows, total):
    good = [row for row in rows if row.get('state') == 'complete']
    failed = [row for row in rows if row.get('state') == 'failed']
    metrics = [row['metrics'] for row in good]
    returns = [value['total_return'] for value in metrics]
    by_signal = {}
    for row in good:
        for key, count in row['signal_counts'].items():
            by_signal[key] = by_signal.get(key, 0) + count
    return {'profile': BACKTEST_PROFILE, 'algorithm_profile': PROFILE,
        'engine_commit': COMMIT, 'total': total, 'completed': len(good),
        'failed': len(failed), 'remaining': max(0, total - len(rows)),
        'coverage_complete': len(rows) == total,
        'processing_complete': len(rows) == total,
        'successful_coverage_complete': len(good) == total,
        'all_securities_successful': len(good) == total,
        'bars': sum(row['bars'] for row in good),
        'candidates': sum(row['candidate_count'] for row in good),
        'confirmations': sum(row['confirmation_count'] for row in good),
        'withdrawals': sum(row['withdrawal_count'] for row in good),
        'invalidations': sum(row['invalidation_count'] for row in good),
        'confirmed_signals_by_rank_type_side': dict(sorted(by_signal.items())),
        'completed_trades': sum(value['completed_trades'] for value in metrics),
        'zero_trade_securities': sum(value['completed_trades'] == 0 for value in metrics),
        'mean_independent_account_return': statistics.fmean(returns) if returns else None,
        'median_independent_account_return': statistics.median(returns) if returns else None,
        'total_fees': sum(value['total_fees'] for value in metrics),
        'worst_account_drawdown': min((value['max_drawdown'] for value in metrics), default=None),
        'failed_symbols': [row['symbol'] for row in failed],
        'failed_records': [{'symbol':row['symbol'],'error':row.get('error','unknown failure')} for row in failed],
        'performance_scope': 'separate 100000 CNY accounts; unadjusted current cached history; research simulation',
        'execution_allowed': False}


def run_market(records, cache, cutoff, output, workers='auto', progress=None, stop_file=None,
               *, cache_sources=None, source_hashes=None,resource_plan=None):
    from workbench.resources import plan_resources
    from workbench.parallel import AdaptiveProcessPool
    plan=resource_plan or plan_resources('native_backtest',workers,max_workers=32)
    workers=plan.get('capacity_workers',plan['workers'])
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    checkpoint = out / 'checkpoint.jsonl'
    cost_values = asdict(CostModel())
    manifest = {'profile': BACKTEST_PROFILE, 'algorithm_profile': PROFILE,
        'engine_commit': COMMIT, 'cutoff': cutoff,
        'cache': str(Path(cache).resolve()), 'symbols': [row['symbol'] for row in records],
        'cost_model': cost_values, 'workers': workers,'resource_plan':plan}
    if cache_sources is not None:
        missing=[row['symbol'] for row in records if row['symbol'] not in cache_sources]
        if missing:raise ValueError('backtest source manifest is missing securities: '+','.join(missing[:5]))
        manifest['cache_sources']={row['symbol']:str(Path(cache_sources[row['symbol']]).resolve()) for row in records}
        manifest['source_hashes']=source_hashes or {}
    manifest_path = out / 'manifest.json'
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding='utf-8'))
        identity_keys=('profile','algorithm_profile','engine_commit','cutoff','cache','symbols','cost_model','cache_sources','source_hashes')
        if any(old.get(key) != manifest.get(key) for key in identity_keys):
            raise ValueError('resume manifest differs from this native-engine run')
    else:
        atomic_json(manifest_path, manifest)

    rows = {}
    if checkpoint.is_file():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
                artifact = Path(row.get('artifact', ''))
                if row.get('state') == 'complete' and artifact.is_file() and hashlib.sha256(artifact.read_bytes()).hexdigest() == row.get('artifact_sha256'):
                    rows[row['symbol']] = row
            except (ValueError, OSError, KeyError):
                continue
    pending = [record for record in records if record['symbol'] not in rows]
    started = time.monotonic()
    runtime_state={'plan':plan,'active_workers':0,'admission_workers':0,'waiting_for_memory':False}
    def report_resources():
        summary=aggregate(list(rows.values()),len(records));summary['resources']=runtime_state.copy()
        summary['elapsed_seconds']=round(time.monotonic()-started,1)
        atomic_json(out/'summary.json',summary)
        if progress:progress(summary)
        return summary
    with AdaptiveProcessPool(plan) as pool, checkpoint.open('a', encoding='utf-8') as log:
        iterator = iter(pending)
        futures = {}
        exhausted = not pending
        while futures or not exhausted:
            stopped = stop_file is not None and Path(stop_file).exists()
            allowed=len(futures) if stopped else pool.admission(len(futures))
            runtime_state.update(active_workers=len(futures),admission_workers=allowed,waiting_for_memory=allowed==0 and not exhausted and not stopped)
            while len(futures) < allowed and not exhausted and not stopped:
                try:
                    record = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                selected_cache=manifest.get('cache_sources',{}).get(record['symbol'],str(cache))
                expected_hash=manifest.get('source_hashes',{}).get(record['symbol'])
                future = pool.submit(backtest_one, record, selected_cache, cutoff, str(out), cost_values, expected_hash)
                futures[future] = record
            if not futures:
                if not exhausted and not stopped:
                    report_resources();time.sleep(1);continue
                break
            done, _ = wait(futures, timeout=1, return_when=FIRST_COMPLETED)
            for future in done:
                record = futures.pop(future)
                try:
                    row = future.result()
                except Exception as exc:
                    row = {**record, 'state': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
                rows[record['symbol']] = row
                log.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                log.flush()
            if len(rows)==len(records):exhausted=True
            runtime_state['active_workers']=len(futures)
            if done:report_resources()
            if stopped:
                exhausted = True

    summary = aggregate(list(rows.values()), len(records))
    runtime_state.update(active_workers=0,admission_workers=0,waiting_for_memory=False)
    summary['resources']=runtime_state.copy()
    summary['elapsed_seconds'] = round(time.monotonic() - started, 1)
    atomic_json(out / 'summary.json', summary)
    fields = ['symbol', 'name', 'exchange', 'state', 'bars', 'candidate_count',
              'confirmation_count', 'withdrawal_count', 'completed_trades',
              'total_return', 'win_rate', 'max_drawdown', 'total_fees', 'invalidation_count', 'error']
    with (out / 'stocks.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows.values(), key=lambda item: item['symbol']):
            metrics = row.get('metrics') or {}
            writer.writerow({**{key: row.get(key) for key in fields},
                             'completed_trades': metrics.get('completed_trades'),
                             'total_return': metrics.get('total_return'),
                             'win_rate': metrics.get('win_rate'),
                             'max_drawdown': metrics.get('max_drawdown'),
                             'total_fees': metrics.get('total_fees'),
                             'invalidation_count': row.get('invalidation_count')})
    return summary
