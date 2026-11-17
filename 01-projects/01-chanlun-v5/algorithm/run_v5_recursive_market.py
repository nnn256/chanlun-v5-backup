#!/usr/bin/env python3
"""Run the declared V5 recursive profile across cached daily stock CSVs."""
from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import time

from chanmodel.model import Config
from chanmodel.v2.io import load_series
from chanmodel.unified import analyze_all
from chanmodel.resource_runtime import adaptive_results,plan_workers

CN = timezone(timedelta(hours=8))
HERE = Path(__file__).resolve().parent

def now(): return datetime.now(CN).isoformat(timespec='seconds')

def worker(task):
    symbol,csv_path,meta_path,cutoff,max_rank,out_dir = task
    started=time.monotonic()
    try:
        series,receipt=load_series(Path(csv_path),symbol,'day','unadjusted','tdx',Path(meta_path))
        report=analyze_all({'day':series},cutoff,Config(stroke_mode='strict',second_policy='conservative',third_boundary='strict_outside',max_depth=3),max_rank)
        period=report['reports']['day']
        compact={'symbol':symbol,'status':'success','source_receipt':receipt,'as_of':cutoff,
                 'bars':period['input_audit']['bars_used'],'max_rank':max_rank,
                 'levels':len(period['hierarchy']['levels']),
                 'fractals':len(period['base']['fractals']),'strokes':len(period['base']['strokes']),
                 'segments':len(period['base']['segments']),'centers':sum(len(x['centers']) for x in period['hierarchy']['levels']),
                 'completed_types':sum(len(x['completed_types']) for x in period['hierarchy']['levels']),
                 'signals':len(period['signals']),'certificate_state':period['certificate_audit']['state'],
                 'definition_mode':period['definition_mode'],'strict_original_equivalence_proven':False,
                 'execution_allowed':False,'elapsed_seconds':round(time.monotonic()-started,3)}
        detail=Path(out_dir)/'details'/f'{symbol}.json.gz';detail.parent.mkdir(parents=True,exist_ok=True)
        detail.write_bytes(gzip.compress(json.dumps(report,ensure_ascii=False,allow_nan=False).encode(),mtime=0));compact['detail_path']=str(detail)
        return compact
    except Exception as exc:
        return {'symbol':symbol,'status':'failed','error':f'{type(exc).__name__}: {exc}','execution_allowed':False,'elapsed_seconds':round(time.monotonic()-started,3)}


def resumable_success(item, symbol, csv_path, meta_path, detail_path, cutoff, max_rank):
    if item.get('symbol')!=symbol or item.get('status')!='success':
        return False
    if item.get('max_rank')!=max_rank or item.get('as_of')!=cutoff:
        return False
    if not detail_path.is_file():
        return False
    try:
        series,receipt=load_series(csv_path,symbol,'day','unadjusted','tdx',meta_path)
        saved=item.get('source_receipt') or {}
        if not receipt.get('provider_identity_receipt_checked') or receipt.get('csv_sha256')!=saved.get('csv_sha256'):
            return False
        report=json.loads(gzip.decompress(detail_path.read_bytes()))
        return (report.get('profile')=='source_declared_complete_study_layers_v1'
                and report.get('as_of')==cutoff
                and report.get('max_rank')==max_rank
                and report.get('input_sha256')==series.input_sha256
                and report.get('config',{}).get('stroke_mode')=='strict'
                and report.get('config',{}).get('second_policy')=='conservative'
                and report.get('config',{}).get('max_depth')==3
                and report.get('config',{}).get('third_boundary')=='strict_outside')
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        return False


def latest_for_symbols(ledger, selected):
    latest={}
    selected=set(selected)
    if not ledger.is_file():return latest
    for line in ledger.read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        item=json.loads(line)
        if item.get('symbol') in selected:latest[item['symbol']]=item
    return latest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir',type=Path,default=HERE.parent/'data'/'market_data')
    parser.add_argument('--run-dir',type=Path,default=HERE.parent/'runs'/'v5-recursive-l8-20261115')
    parser.add_argument('--cutoff');parser.add_argument('--workers',default='auto');parser.add_argument('--max-rank',type=int,default=8)
    parser.add_argument('--symbols');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    try:
        request=plan_workers(args.workers,memory_per_worker_mb=256)
    except ValueError as exc:parser.error(str(exc))
    args.workers='auto' if args.workers=='auto' else int(args.workers)
    if not 1<=args.max_rank<=8:parser.error('max-rank must be 1..8')
    csv_dir=args.cache_dir.resolve()/'tdx'/'day'/'ohlcv';meta_dir=args.cache_dir.resolve()/'tdx'/'day'/'metadata'
    if not csv_dir.is_dir() or not meta_dir.is_dir():raise SystemExit(f'missing cached daily data: {csv_dir}')
    records=[]
    for path in sorted(csv_dir.glob('*.csv')):
        meta=meta_dir/f'{path.stem}.json'
        if meta.is_file():records.append((path.stem,str(path),str(meta),'',args.max_rank,str(args.run_dir.resolve())))
    if args.symbols:
        wanted={x.strip() for x in args.symbols.split(',') if x.strip()};records=[x for x in records if x[0] in wanted]
        if {x[0] for x in records}!=wanted:raise SystemExit('requested symbol absent from cached daily CSV')
    if not records:raise SystemExit('no cached daily CSVs')
    args.run_dir.mkdir(parents=True,exist_ok=True);ledger=args.run_dir/'status.jsonl';existing={}
    cutoff=args.cutoff
    if not cutoff:
        metas=list(meta_dir.glob('*.json'));cutoff=max(json.loads(x.read_text(encoding='utf-8'))['cache_run_as_of'] for x in metas)
    selected={row[0] for row in records}
    if args.resume:existing=latest_for_symbols(ledger,selected)
    reusable={}
    if args.resume:
        for symbol,csv_path,meta_path,*_ in records:
            previous=existing.get(symbol)
            if previous and resumable_success(previous,symbol,Path(csv_path),Path(meta_path),
                                              args.run_dir/'details'/f'{symbol}.json.gz',cutoff,args.max_rank):
                reusable[symbol]=previous
    tasks=[(s,c,m,cutoff,args.max_rank,str(args.run_dir.resolve())) for s,c,m,_,_,_ in records if s not in reusable]
    print(json.dumps({'event':'start','algorithm':'缠论V5','profile':'course_feature_sequence_recursive_v2','max_rank':args.max_rank,'universe':len(records),'remaining':len(tasks),'cutoff':cutoff},ensure_ascii=False),flush=True)
    def on_resource(value):
        from chanmodel.tdx_data import atomic_json
        atomic_json(args.run_dir/'resource-status.json',value)
    with ledger.open('a',encoding='utf-8') as stream:
        for index,(_,future) in enumerate(adaptive_results(worker,tasks,workers=args.workers,
                memory_per_worker_mb=256,stop_file=args.run_dir/'STOP',on_resource=on_resource),1):
            item=future.result();stream.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n');stream.flush()
            if index%25==0 or index==len(tasks):print(json.dumps({'event':'progress','processed':index,'total':len(tasks),'symbol':item['symbol'],'status':item['status']},ensure_ascii=False),flush=True)
    latest=dict(reusable)
    for line in ledger.read_text(encoding='utf-8').splitlines():
        if line.strip():
            item=json.loads(line)
            if item.get('symbol') in selected:latest[item['symbol']]=item
    values=list(latest.values());summary={'algorithm':'缠论V5','profile':'course_feature_sequence_recursive_v2','max_rank':args.max_rank,'cutoff':cutoff,'run_dir':str(args.run_dir.resolve()),'cached_daily_csv_count':len(records),'processed':len(values),'success':sum(x.get('status')=='success' for x in values),'failed':sum(x.get('status')!='success' for x in values),'pending':len(records)-len(values),'certificate_passed':sum(x.get('certificate_state')=='passed' for x in values),'signals':sum(x.get('signals',0) for x in values),'execution_allowed':False,'strict_original_equivalence_proven':False,'updated_at':now(),'source':'D cache from TDX normalized daily'}
    summary.update(workers=args.workers,resource_policy='cpu_memory_adaptive_v1',execution_backend='cpu_multiprocess')
    (args.run_dir/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'event':'finished',**summary},ensure_ascii=False));return 3 if summary['pending'] else 0 if summary['failed']==0 else 1

if __name__=='__main__':raise SystemExit(main())
