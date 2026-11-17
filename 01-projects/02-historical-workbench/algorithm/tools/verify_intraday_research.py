"""Repeat local replay, check source/artifact hashes and independently verify fills."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.intraday_research import IntradayConfig, IntradayResearchSession, evaluate_intraday
from chanmodel.tdx_data import atomic_json
from chanmodel.v2.io import load_cache_series
from chanmodel.v2.series import CN,PERIODS,session_closes


def raw_session_evidence(bars,period):
    """Independent raw-candle oracle labels, prepared once per audit input."""
    grouped={}
    for bar in bars:
        stamp=datetime.fromisoformat(bar.closed_at).astimezone(CN)
        grouped.setdefault(stamp.date(),[]).append((bar,stamp))
    return {day:{'complete':[stamp for _,stamp in rows]==session_closes(day,period),
                 'low':min(bar.low for bar,_ in rows),
                 'high':max(bar.high for bar,_ in rows)}
            for day,rows in grouped.items()}


def audit_record(record,cache):
    path=Path(record['artifact']);errors=[]
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=record['artifact_sha256']:raise ValueError('saved artifact SHA256 differs')
    payload=json.loads(gzip.decompress(path.read_bytes()))
    source,receipt=load_cache_series(cache,payload['symbol'],payload['period'])
    if receipt.get('csv_sha256')!=payload['source_receipt'].get('csv_sha256'):
        raise ValueError('source CSV changed since initial replay')
    source=source.prefix(payload['as_of'])
    bars=tuple(replace(b,pos=i) for i,b in enumerate(source.bars[payload['replay_start_original_index']:]))
    data_digest=hashlib.sha256(json.dumps([[b.pos,b.closed_at,b.open,b.high,b.low,b.close,b.volume] for b in bars],separators=(',',':')).encode()).hexdigest()
    if data_digest!=payload['input_data_sha256']:raise ValueError('replay data SHA256 differs')
    config=IntradayConfig(**payload['config'])
    session=IntradayResearchSession(payload['symbol'],payload['period'],config,source.source,source.adjustment)
    for bar in bars:session.append(bar)
    evaluation_dates=payload['evaluation_sessions']
    events=[e for e in session.events if datetime.fromisoformat(e['available_time']).astimezone(CN).date().isoformat() in evaluation_dates]
    if events!=payload['events']:errors.append('repeated replay events differ')
    settings=payload['evaluation']['settings']
    evaluation=evaluate_intraday(bars,events,payload['period'],tuple(settings['horizons']),settings['slippage_bps'])
    if evaluation!=payload['evaluation']:errors.append('repeated event evaluation differs')
    independent=0
    raw_days=raw_session_evidence(bars,payload['period'])
    for row in payload['evaluation']['rows']:
        i=row['available_at'];anchor=row['anchor'];side=row['side']
        if not anchor<=i:errors.append('future anchor in stored event')
        if row['available_time']!=bars[i].closed_at:errors.append('stored event time mismatch')
        if row['fill_price'] is None:continue
        j=i+1;fill_bar=bars[j]
        moment=datetime.fromisoformat(fill_bar.closed_at).astimezone(CN)
        expected_price=fill_bar.open*(1+settings['slippage_bps']/10000*(1 if side=='buy' else -1))
        if not math.isclose(row['fill_price'],expected_price,rel_tol=1e-12,abs_tol=1e-12):errors.append('fill is not next raw open with declared slippage')
        expected_time=(moment-timedelta(minutes=PERIODS[payload['period']])).isoformat()
        if row['fill_time']!=expected_time:errors.append('fill timestamp differs from next native bar opening')
        day=raw_days[moment.date()]
        complete=day['complete']
        if complete:
            extreme=day['low'] if side=='buy' else day['high']
            if row['daily_extreme']!=extreme:errors.append('session extreme differs from all raw native bars')
        elif row['daily_extreme'] is not None:errors.append('incomplete session claimed complete-session extreme')
        independent+=1
    return {'symbol':payload['symbol'],'period':payload['period'],'state':'passed' if not errors else 'failed',
            'events':len(events),'alerts':evaluation['summary']['alerts'],'independently_checked_next_opens':independent,
            'input_data_sha256':data_digest,'source_csv_sha256':receipt.get('csv_sha256'),
            'artifact_sha256':digest,'errors':errors,'execution_allowed':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',type=Path,required=True,help='directory containing study-summary.json')
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--output',type=Path)
    p.add_argument('--workers',type=int,default=1,help='independent per-security replay processes, 1..4')
    a=p.parse_args()
    if not 1<=a.workers<=4:p.error('workers must be 1..4')
    records=json.loads((a.study/'study-summary.json').read_text(encoding='utf-8'))['records']
    checks=[]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(audit_record,r,a.cache) if r.get('state')=='complete' else None for r in records]
        for r,future in zip(records,futures):
            if future is None:
                checks.append({'symbol':r.get('symbol'),'state':'failed','errors':['initial replay did not complete']});continue
            try:checks.append(future.result())
            except Exception as exc:checks.append({'symbol':r.get('symbol'),'state':'failed','errors':[f'{type(exc).__name__}: {exc}']})
    result={'state':'passed' if checks and all(c['state']=='passed' for c in checks) else 'failed',
            'created_at':datetime.now(CN).isoformat(),'checks':checks,'uploaded':False,'execution_allowed':False}
    atomic_json(a.output or a.study/'verification.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['state']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
