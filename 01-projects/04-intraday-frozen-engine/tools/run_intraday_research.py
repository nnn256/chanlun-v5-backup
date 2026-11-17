"""Local native-Chan intraday replay; archive alerts and ex-post extreme gaps."""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chanmodel.intraday_research import IntradayConfig, IntradayResearchSession, evaluate_intraday
from chanmodel.tdx_data import atomic_bytes, atomic_json
from chanmodel.v2.io import load_cache_series
from chanmodel.v2.series import CN, validate_series


def run_one(symbol, cache, output, period='5m', cutoff=None, sessions=20, warmup=1000, config=None):
    started = time.perf_counter()
    source, receipt = load_cache_series(Path(cache), symbol, period)
    cutoff = cutoff or source.bars[-1].closed_at
    source = source.prefix(cutoff)
    audit = validate_series(source, cutoff)
    dates = sorted({datetime.fromisoformat(b.closed_at).astimezone(CN).date().isoformat() for b in source.bars})
    evaluation_dates = dates[-sessions:] if sessions else dates
    if not evaluation_dates: raise ValueError('no evaluation dates')
    first = next(i for i,b in enumerate(source.bars) if datetime.fromisoformat(b.closed_at).astimezone(CN).date().isoformat() >= evaluation_dates[0])
    # Zero means replay the full available prefix; never reset the structural
    # engine at the beginning of the evaluation/holdout window.
    begin = max(0, first-warmup) if warmup else 0
    bars = tuple(replace(b, pos=i) for i,b in enumerate(source.bars[begin:]))
    session = IntradayResearchSession(symbol, period, config, source.source, source.adjustment)
    for i,bar in enumerate(bars):
        session.append(bar)
        if (i+1)%1000==0:
            print(f'{symbol} {period} {i+1}/{len(bars)} bars',flush=True)
    snapshot = session.snapshot()
    selected = [e for e in snapshot['events'] if datetime.fromisoformat(e['available_time']).astimezone(CN).date().isoformat() in evaluation_dates]
    evaluation = evaluate_intraday(bars, selected, period)
    output = Path(output)/symbol/period
    output.mkdir(parents=True,exist_ok=True)
    payload = {'symbol':symbol,'period':period,'as_of':cutoff,'created_at':datetime.now(CN).isoformat(),
               'input_audit':audit,'source_receipt':receipt,'replay_start_original_index':begin,
               'warmup_requested_bars':warmup,'warmup_actual_bars':first-begin,
               'evaluation_sessions':evaluation_dates,'input_bars':len(bars),
               'input_data_sha256':hashlib.sha256(json.dumps([[b.pos,b.closed_at,b.open,b.high,b.low,b.close,b.volume] for b in bars],separators=(',',':')).encode()).hexdigest(),
               'profile':snapshot['profile'],'algorithm_profile':snapshot['algorithm_profile'],'engine_commit':snapshot['engine_commit'],
               'config':snapshot['config'],'events':selected,'active_signals':snapshot['active_signals'],
               'evaluation':evaluation,'seconds':round(time.perf_counter()-started,3),'execution_allowed':False,
               'limitations':['Native OHLC source history is finite and may have subsequent provider corrections.',
                              'Local native structure completion is not independently proven multi-timeframe trading confirmation.',
                              'Session low/high is only an ex-post comparator; it never supplies an execution fill.',
                              'Sell event study assumes previously held T+1-eligible stock; buying does not permit same-day A-share resale.',
                              'This event study does not replay exchange queues, ticks, order-book limits or full transaction costs.']}
    raw=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    artifact=output/'intraday-research.json.gz'
    atomic_bytes(artifact,gzip.compress(raw,mtime=0))
    summary={k:payload[k] for k in ('symbol','period','as_of','created_at','input_bars','warmup_actual_bars','evaluation_sessions','input_data_sha256','profile','config','seconds','limitations','execution_allowed')}
    summary.update(evaluation['summary'],artifact=str(artifact.resolve()),artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                   rejections=sum(e['event']=='rejected' for e in selected),
                   rejected_by_reason={reason:sum(reason in e.get('rejection_reasons',[]) for e in selected) for reason in sorted({r for e in selected for r in e.get('rejection_reasons',[])})})
    atomic_json(output/'summary.json',summary)
    fields=['symbol','period','side','native_type','rank','pivot_time','pivot_price','available_time','confirmation_price',
            'confirmation_delay_bars','pivot_distance_pct','evaluation_state','fill_time','fill_price','daily_extreme','daily_extreme_gap_bps']
    with (output/'alerts.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(evaluation['rows'])
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--symbol',action='append',required=True)
    p.add_argument('--period',choices=('1m','5m','30m'),default='5m')
    p.add_argument('--cache',type=Path,default=ROOT/'market_data')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cutoff')
    p.add_argument('--sessions',type=int,default=20)
    p.add_argument('--warmup',type=int,default=0,help='0: all prior history; positive: explicitly truncated warm-up bars')
    p.add_argument('--max-delay-minutes',type=int,default=60)
    p.add_argument('--max-distance-pct',type=float,default=2.0)
    a=p.parse_args()
    if a.sessions<0 or a.warmup<0:p.error('sessions/warmup must be nonnegative')
    config=IntradayConfig(max_confirmation_delay_minutes=a.max_delay_minutes,max_pivot_distance_pct=a.max_distance_pct)
    a.output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for symbol in a.symbol:
        try:rows.append({'state':'complete',**run_one(symbol,a.cache,a.output,a.period,a.cutoff,a.sessions,a.warmup,config)})
        except Exception as exc:rows.append({'symbol':symbol,'state':'failed','error':f'{type(exc).__name__}: {exc}'})
    atomic_json(a.output/'study-summary.json',{'profile':'native_chan_intraday_reversal_causal_v1','records':rows,
                                            'execution_allowed':False,'uploaded':False})
    print(json.dumps(rows,ensure_ascii=False,indent=2))
    if any(r['state']=='failed' for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
