"""Checkpointed, all-security causal signal replay and explicit cash simulations."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
from dataclasses import asdict
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import statistics
import time

from .causal_replay import StreamingStructure,SignalLedger,CONFIG
from .causal_portfolio import simulate,CostModel
from .v2.io import load_cache_series
from .tdx_data import atomic_json,atomic_bytes

PROFILE='v4_all_market_daily_causal_next_open_v1'


def backtest_one(record,cache,cutoff,output,expected_csv_sha256=None):
    started=time.perf_counter();symbol=record['symbol'];destination=Path(output)/'stocks'/(symbol+'.json.gz')
    try:
        series,receipt=load_cache_series(Path(cache),symbol,'day');series=series.prefix(cutoff)
        if expected_csv_sha256 and receipt.get('csv_sha256')!=expected_csv_sha256:
            raise ValueError('daily source changed after backtest coverage check; create a new run')
        if not series.bars:raise ValueError('no completed history at cutoff')
        stream=StreamingStructure(CONFIG);ledger=SignalLedger('day')
        for bar in series.bars:
            changed=stream.append(bar);ledger.invalidate(bar)
            if changed:ledger.observe(stream.snapshot(),bar,stream.bars)
        daily={b.closed_at[:10]:b.close for b in series.bars}
        result=simulate(series.bars,series.bars,ledger.events,daily,cost=CostModel(),period='day',symbol=symbol)
        discontinuities=[{'index':i,'date':b.closed_at,'previous_close':a.close,'open':b.open}
                         for i,(a,b) in enumerate(zip(series.bars,series.bars[1:]),1) if abs(b.open/a.close-1)>.35]
        # The conservative clause audit cannot confirm a rank-one proxy. Retain
        # all candidate counts, including zero-trade cases, rather than relax it.
        summary={**record,'state':'complete','profile':PROFILE,'bars':len(series.bars),
                 'first_close':series.bars[0].closed_at,'last_close':series.bars[-1].closed_at,
                 'input_sha256':receipt['csv_sha256'],'effective_sha256':series.digest(),
                 'events':len(ledger.events),'confirmations':len(ledger.confirmations),
                 'metrics':result['metrics'],'candidate_count':len(ledger.records),
                 'price_discontinuities':len(discontinuities),'seconds':round(time.perf_counter()-started,3),
                 'corporate_actions_accounted':False,'historical_st_status_known':False,
                 'definition_mode':'source_clause_confirmed_under_declared_base','trade_level':'day',
                 'confirm_level':'recursive_child_types','trigger_level':'next_daily_open',
                 'structure_completeness':'single_period_recursive_audit','execution_allowed':False}
        detail={'summary':summary,'receipt':receipt,'events':ledger.events,'confirmations':ledger.confirmations,
                'simulation':result,'price_discontinuities':discontinuities,
                'limitations':['current membership has survivorship bias; historical delisted universe is not available',
                   'unadjusted daily observations; dividends/splits are not universally supplied and affect cash returns',
                   'board standard limits; historical ST status, IPO exceptions and exchange queue priorities are unavailable',
                   'each security starts with separate 100000 CNY; average returns are not a shared-capital market portfolio',
                   'daily recursive confirmation is distinct from live day/30m/5m confirmation']}
        atomic_bytes(destination,gzip.compress(json.dumps(detail,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode(),compresslevel=3,mtime=0))
        summary['artifact']=str(destination.resolve());summary['artifact_sha256']=hashlib.sha256(destination.read_bytes()).hexdigest()
        return summary
    except Exception as exc:
        return {**record,'state':'failed','error':f'{type(exc).__name__}: {exc}','seconds':round(time.perf_counter()-started,3)}


def aggregate(rows,total):
    good=[r for r in rows if r['state']=='complete'];failed=[r for r in rows if r['state']=='failed']
    metrics=[r['metrics'] for r in good];returns=[m['total_return'] for m in metrics]
    return {'profile':PROFILE,'total':total,'completed':len(good),'failed':len(failed),'remaining':total-len(rows),
            'coverage_complete':len(rows)==total,'all_securities_successful':len(good)==total,
            'processing_complete':len(rows)==total,'successful_coverage_complete':len(good)==total,
            'bars':sum(r['bars'] for r in good),'signals':sum(r['confirmations'] for r in good),
            'oldest_last_bar':min((r['last_close'] for r in good if r.get('last_close')),default=None),
            'newest_last_bar':max((r['last_close'] for r in good if r.get('last_close')),default=None),
            'completed_trades':sum(m['completed_trades'] for m in metrics),'zero_trade_securities':sum(m['completed_trades']==0 for m in metrics),
            'mean_independent_account_return':statistics.fmean(returns) if returns else None,
            'median_independent_account_return':statistics.median(returns) if returns else None,
            'total_fees':sum(m['total_fees'] for m in metrics),'worst_account_drawdown':min((m['max_drawdown'] for m in metrics),default=None),
            'failed_symbols':[r['symbol'] for r in failed],'no_universal_corporate_action_adjustment':True,
            'performance_scope':'separate cash accounts on unadjusted histories; not a certified corporate-action-adjusted strategy return',
            'execution_allowed':False}


def run_market(records,cache,cutoff,output,workers='auto',progress=None,stop_file=None,*,cache_sources=None,source_hashes=None,resource_plan=None):
    from workbench.resources import plan_resources
    from workbench.parallel import AdaptiveProcessPool
    plan=resource_plan or plan_resources('native_backtest',workers,max_workers=32)
    workers=plan.get('capacity_workers',plan['workers'])
    out=Path(output);out.mkdir(parents=True,exist_ok=True);checkpoint=out/'checkpoint.jsonl'
    manifest={'profile':PROFILE,'cutoff':cutoff,'cache':str(Path(cache).resolve()),'symbols':[r['symbol'] for r in records],
              'configuration':asdict(CONFIG),'historical_membership':'current listing snapshot','workers':workers,'resource_plan':plan}
    if cache_sources is not None:
        missing=[r['symbol'] for r in records if r['symbol'] not in cache_sources]
        if missing:raise ValueError('backtest source manifest is missing securities: '+','.join(missing[:5]))
        manifest['cache_sources']={r['symbol']:str(Path(cache_sources[r['symbol']]).resolve()) for r in records}
        manifest['source_hashes']=source_hashes or {}
    manifest_path=out/'manifest.json'
    if manifest_path.exists():
        old=json.loads(manifest_path.read_text(encoding='utf-8'))
        if any(old.get(k)!=manifest.get(k) for k in ['profile','cutoff','cache','symbols','configuration','cache_sources','source_hashes']):raise ValueError('resume manifest differs')
    atomic_json(manifest_path,manifest);existing={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            try:row=json.loads(line)
            except ValueError:continue
            if row['state']=='complete' and Path(row.get('artifact','')).is_file():
                if hashlib.sha256(Path(row['artifact']).read_bytes()).hexdigest()==row.get('artifact_sha256'):existing[row['symbol']]=row
    pending_records=[r for r in records if r['symbol'] not in existing];pending=iter(pending_records);rows=dict(existing);started=time.monotonic()
    runtime_state={'plan':plan,'active_workers':0,'admission_workers':0,'waiting_for_memory':False}
    with AdaptiveProcessPool(plan) as pool,checkpoint.open('a',encoding='utf-8') as log:
        futures={};exhausted=not pending_records
        while futures or not exhausted:
            stopped=stop_file is not None and Path(stop_file).exists()
            allowed=len(futures) if stopped else pool.admission(len(futures))
            runtime_state.update(active_workers=len(futures),admission_workers=allowed,waiting_for_memory=allowed==0 and not exhausted and not stopped)
            while len(futures)<allowed and not exhausted and not stopped:
                try:record=next(pending)
                except StopIteration:exhausted=True;break
                selected_cache=manifest.get('cache_sources',{}).get(record['symbol'],str(cache))
                expected_hash=manifest.get('source_hashes',{}).get(record['symbol'])
                futures[pool.submit(backtest_one,record,selected_cache,cutoff,str(out),expected_hash)]=record
            if not futures:
                if not exhausted and not stopped:
                    summary=aggregate(list(rows.values()),len(records));summary['resources']=runtime_state.copy()
                    atomic_json(out/'summary.json',summary)
                    if progress:progress(summary)
                    time.sleep(1);continue
                break
            done,_=wait(futures,timeout=1,return_when=FIRST_COMPLETED)
            for future in done:
                record=futures.pop(future)
                try:row=future.result()
                except Exception as exc:row={**record,'state':'failed','error':f'{type(exc).__name__}: {exc}'}
                rows[record['symbol']]=row;log.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');log.flush()
            if len(rows)==len(records):exhausted=True
            if done:
                summary=aggregate(list(rows.values()),len(records));summary['seconds']=round(time.monotonic()-started,1)
                summary['resources']=runtime_state.copy()
                atomic_json(out/'summary.json',summary)
                if progress:progress(summary)
            if stopped:exhausted=True
    runtime_state.update(active_workers=0,admission_workers=0,waiting_for_memory=False)
    summary=aggregate(list(rows.values()),len(records));summary['resources']=runtime_state.copy();atomic_json(out/'summary.json',summary)
    with (out/'stocks.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields=['symbol','name','state','bars','confirmations','completed_trades','total_return','max_drawdown','total_fees','error']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in sorted(rows.values(),key=lambda r:r['symbol']):writer.writerow({k:row.get(k,row.get('metrics',{}).get(k)) for k in fields})
    return summary
