#!/usr/bin/env python3
"""Import D-drive V5 recursive daily summaries/charts into the V5 workbench."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from chanmodel.v2.io import load_series
from workbench.compute import make_chart
from workbench.store import connect,initialize,STATE,publish_result

CN=timezone(timedelta(hours=8))

def process_one(task):
    symbol,csv_path,meta_path,detail_path,record,out_dir,max_rank=task
    try:
        item=json.loads(gzip.decompress(Path(detail_path).read_bytes()))
        report=item['reports']['day']
        series,source_receipt=load_series(Path(csv_path),symbol,'day','unadjusted','tdx',Path(meta_path) if Path(meta_path).exists() else None)
        source_receipt.update(file=os.path.relpath(Path(csv_path).resolve(), HERE),
                              metadata_file=os.path.relpath(Path(meta_path).resolve(), HERE) if Path(meta_path).is_file() else None,
                              source='tdx',adjustment='unadjusted')
        cutoff=report['as_of']
        chart,summary=make_chart(record,{'day':series},{'day':report},cutoff,None,None)
        last_close=report['input_audit']['last_close']
        summary.update(algorithm='V5',profile='course_feature_sequence_recursive_v2',workbench_profile='course_feature_sequence_recursive_v2',algorithm_profile=report.get('profile'),engine_profile=report.get('profile'),max_rank=max_rank,levels_observed=len(report['hierarchy']['levels']),source_csv_sha256=series.input_sha256,as_of=cutoff,mode='v5_recursive',state='calculated',last_date=last_close[:10],last_close_time=last_close,active_candidates=sum(s.get('state') not in {'invalidated','withdrawn'} for s in report['signals']),triggered=0,execution_allowed=False,definition_mode=report['definition_mode'],strict_original_equivalence_proven=False,periods={'day':summary.get('periods',{}).get('day',{})})
        chart.update(algorithm='V5',workbench_profile='course_feature_sequence_recursive_v2',engine_profile=report.get('profile'))
        bundle={'summary':summary,'chart':chart,'evidence':{'reports':{'day':report},'source_receipts':{'day':source_receipt},'profile':'course_feature_sequence_recursive_v2','workbench_profile':'course_feature_sequence_recursive_v2','execution_allowed':False}}
        artifact=Path(out_dir)/'imports-v5'/f'{symbol}.json.gz';artifact.parent.mkdir(parents=True,exist_ok=True);artifact.write_bytes(gzip.compress(json.dumps(bundle,ensure_ascii=False,allow_nan=False).encode(),mtime=0))
        return {'symbol':symbol,'status':'success','summary':summary,'artifact':str(artifact.relative_to(Path(out_dir)))}
    except Exception as exc:
        return {'symbol':symbol,'status':'failed','error':f'{type(exc).__name__}: {exc}'}


def reusable_result(row, symbol, detail_path, csv_path, meta_path, state_root,
                    cutoff, max_rank):
    if not row:
        return False
    try:
        saved=json.loads(row['summary'])
        if saved.get('workbench_profile')!='course_feature_sequence_recursive_v2':return False
        if saved.get('as_of')!=cutoff or saved.get('max_rank')!=max_rank:return False
        source,receipt=load_series(csv_path,symbol,'day','unadjusted','tdx',meta_path if meta_path.is_file() else None)
        if (not receipt.get('provider_identity_receipt_checked')
                or saved.get('source_csv_sha256')!=source.input_sha256):return False
        artifact=(state_root/row['artifact']).resolve()
        if not artifact.is_relative_to(state_root.resolve()) or not artifact.is_file() or not detail_path.is_file():return False
        bundle=json.loads(gzip.decompress(artifact.read_bytes()))
        detail=json.loads(gzip.decompress(detail_path.read_bytes()))
        report=detail['reports']['day']
        run_summary=json.loads((detail_path.parent.parent/'summary.json').read_text(encoding='utf-8'))
        return (bundle.get('summary',{}).get('source_csv_sha256')==source.input_sha256
                and run_summary.get('profile')=='course_feature_sequence_recursive_v2'
                and run_summary.get('cutoff')==cutoff and run_summary.get('max_rank')==max_rank
                and report.get('as_of')==cutoff and report.get('max_rank')==max_rank
                and report.get('input_sha256')==source.input_sha256
                and report.get('certificate_audit',{}).get('state')=='passed'
                and bundle.get('evidence',{}).get('reports',{}).get('day',{}).get('input_sha256')==source.input_sha256)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        return False

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recursive-run',type=Path,default=HERE.parent/'runs'/'v5-recursive-l8-20261115')
    p.add_argument('--cache-dir',type=Path,default=HERE.parent/'data'/'market_data')
    p.add_argument('--universe',type=Path)
    p.add_argument('--limit',type=int)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--workers',type=int,default=4)
    args=p.parse_args()
    if not 1<=args.workers<=8:raise SystemExit('--workers must be 1..8')
    run=args.recursive_run.resolve();cache=args.cache_dir.resolve();details=run/'details'
    if not details.is_dir():raise SystemExit(f'missing details directory: {details}')
    rank_cap=json.loads((run/'summary.json').read_text(encoding='utf-8')).get('max_rank',8)
    if not 1<=rank_cap<=8:raise SystemExit(f'invalid recursive max_rank: {rank_cap}')
    cutoff=json.loads((run/'summary.json').read_text(encoding='utf-8')).get('cutoff')
    if not cutoff:raise SystemExit('recursive run summary has no cutoff')
    universe_path=(args.universe or run.parent/'full-market-20261114-tdx-partial'/'universe.json').resolve()
    universe=json.loads(universe_path.read_text(encoding='utf-8-sig'))
    records={x['symbol']:x for x in universe['records']}
    initialize()
    with connect() as db:
        existing={row['symbol']:dict(row) for row in db.execute("SELECT symbol,summary,artifact FROM results WHERE mode='v5_recursive'")}
    symbols=sorted(p.name[:-8] for p in details.glob('*.json.gz'))
    if args.limit:symbols=symbols[:args.limit]
    if any(symbol not in records for symbol in symbols):
        raise SystemExit('recursive report symbol is missing from the supplied provider universe')
    pending=[]
    if args.resume:
        for symbol in symbols:
            csv=cache/'tdx'/'day'/'ohlcv'/f'{symbol}.csv'
            meta=cache/'tdx'/'day'/'metadata'/f'{symbol}.json'
            if not reusable_result(existing.get(symbol),symbol,details/f'{symbol}.json.gz',
                                   csv,meta,STATE,cutoff=cutoff,max_rank=rank_cap):
                pending.append(symbol)
    else:
        pending=list(symbols)
    tasks=[]
    for symbol in pending:
        detail=details/f'{symbol}.json.gz';csv=cache/'tdx'/'day'/'ohlcv'/f'{symbol}.csv';meta=cache/'tdx'/'day'/'metadata'/f'{symbol}.json';tasks.append((symbol,str(csv),str(meta),str(detail),records.get(symbol,{'symbol':symbol,'name':symbol,'exchange':symbol[:2],'code':symbol[2:]}),str(STATE),rank_cap))
    done=failed=0
    with ProcessPoolExecutor(max_workers=args.workers) as pool, connect() as db:
        futures=[pool.submit(process_one,t) for t in tasks]
        for future in as_completed(futures):
            item=future.result()
            if item['status']=='success':
                publish_result(db,item['symbol'],'v5_recursive',run.name,datetime.now(CN).isoformat(timespec='seconds'),json.dumps(item['summary'],ensure_ascii=False),item['artifact']);done+=1
            else:
                failed+=1
                if failed<=5:print(json.dumps(item,ensure_ascii=False),flush=True)
            if (done+failed)%25==0:print(json.dumps({'processed':done+failed,'total':len(pending),'success':done,'failed':failed},ensure_ascii=False),flush=True)
    print(json.dumps({'algorithm':'V5','profile':'course_feature_sequence_recursive_v2','max_rank':rank_cap,'processed':done,'failed':failed,'total':len(symbols),'execution_allowed':False},ensure_ascii=False))
    return 0 if failed==0 else 1

if __name__=='__main__':raise SystemExit(main())
