"""Durable EXE-safe all-market backtest jobs and progress."""
from datetime import datetime
from collections import OrderedDict
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid
from chanmodel.tdx_data import atomic_json,now_iso
from chanmodel.market_backtest import run_market,PROFILE as BACKTEST_PROFILE
from chanmodel.native_market_backtest import run_market as run_native_market, BACKTEST_PROFILE as NATIVE_BACKTEST_PROFILE
from .store import ROOT,STATE,connect

SUMMARY_CACHE=OrderedDict()
SUMMARY_LOCK=threading.RLock()
LAUNCH_LOCK=threading.Lock()


def _check_idle():
    from .server import alive
    with connect() as db:
        for row in db.execute("SELECT value FROM metadata WHERE key LIKE 'backtest:%'"):
            value=json.loads(row[0])
            if value.get('state')=='running' and alive(value.get('pid')):
                raise ValueError('已有回测正在运行，请等待结束或先停止派发')


def _records(body):
    scope=body.get('scope','all')
    if scope not in {'all','selected'}:raise ValueError('backtest scope must be all or selected')
    with connect() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM universe WHERE active=1 ORDER BY symbol')]
    if scope=='selected':
        selected=body.get('symbols',[])
        if not isinstance(selected,list) or not selected or any(not isinstance(s,str) for s in selected):
            raise ValueError('selected backtest needs securities')
        rows=[r for r in rows if r['symbol'] in selected]
        if len(rows)!=len(set(selected)):raise ValueError('unknown backtest security')
    if not rows:raise ValueError('backtest universe is empty')
    return rows


def _coverage(body,rows):
    from .backtest_cache import resolve_sources
    cutoff=body.get('cutoff') or now_iso()
    point=datetime.fromisoformat(cutoff)
    if point.tzinfo is None:raise ValueError('backtest cutoff requires timezone')
    result=resolve_sources(ROOT,rows,cutoff,explicit_cache=body.get('cache') or None)
    result['source_pairs_available']=result['available']
    minimum=50 if body.get('engine','native')=='native' else 1
    insufficient=[symbol for symbol,detail in result['source_details'].items()
                  if detail.get('closed_rows') is not None and detail['closed_rows']<minimum]
    for symbol in insufficient:
        result['sources'].pop(symbol,None)
        result['source_details'].pop(symbol,None)
    result['insufficient_history_symbols']=insufficient
    result['minimum_closed_bars']=minimum
    result['missing_symbols']+=insufficient
    result['available']=len(result['sources'])
    result['missing']=len(result['missing_symbols'])
    result['coverage_complete']=result['missing']==0
    return result,cutoff


def coverage(body):
    result,cutoff=_coverage(body,_records(body))
    return {key:result.get(key) for key in ['total','available','coverage_complete','candidate_roots','preflight_semantics']}|{
        'cutoff':cutoff,'missing_count':len(result['missing_symbols']),
        'missing_symbols':result['missing_symbols'][:20],
        'sample_missing':result['missing_symbols'][:5],
        'source_pairs_available':result.get('source_pairs_available',result['available']),
        'insufficient_history_count':len(result.get('insufficient_history_symbols',[])),
        'minimum_closed_bars':result.get('minimum_closed_bars',50),
        'invalid_sources_count':len(result.get('invalid_sources',[])),
        'execution_allowed':False}


def _worker_env():
    return {**{k:v for k,v in os.environ.items() if k.upper() not in
        {'PYTHONHOME','PYTHONPATH','PYTHONEXECUTABLE'}},'PYTHONIOENCODING':'utf-8'}


def _output(value):
    folder=Path(value['output'])
    return folder if folder.is_absolute() else ROOT/folder


def _summary(folder):
    path=folder/'summary.json'
    if not path.is_file():return None
    stat=path.stat();key=(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
    with SUMMARY_LOCK:
        prior=SUMMARY_CACHE.get(key)
        if prior is not None:SUMMARY_CACHE.move_to_end(key);return prior
    value=json.loads(path.read_text(encoding='utf-8'))
    with SUMMARY_LOCK:
        SUMMARY_CACHE[key]=value;SUMMARY_CACHE.move_to_end(key)
        while len(SUMMARY_CACHE)>16:SUMMARY_CACHE.popitem(last=False)
    return value


def launch(body):
    requested=body.get('workers','auto')
    from .resources import plan_resources
    engine=body.get('engine','native')
    if engine not in {'native','proxy'}:raise ValueError('backtest engine must be native or proxy')
    plan=plan_resources('native_backtest' if engine=='native' else 'backtest',requested,max_workers=32)
    workers=plan['workers']
    _check_idle()
    rows=_records(body)
    preflight,cutoff=_coverage(body,rows)
    policy=body.get('cache_policy','complete')
    if policy not in {'available','complete'}:raise ValueError('cache_policy must be available or complete')
    if preflight['available']!=len(rows) and policy=='complete':
        missing=len(rows)-preflight['available']
        raise ValueError(f"本地日线缓存覆盖 {preflight['available']}/{len(rows)} 只，缺少或历史不足 {missing} 只，未启动回测。请先补齐历史或选择仅回测可用证券；示例："+','.join(preflight['missing_symbols'][:5]))
    requested_total=len(rows)
    if policy=='available':
        rows=[row for row in rows if row['symbol'] in preflight['sources']]
    if not rows:raise ValueError('没有可运行的本地日线缓存；未启动回测')
    cache=Path(body.get('cache') or ROOT/'market_data').resolve()
    profile=NATIVE_BACKTEST_PROFILE if engine=='native' else BACKTEST_PROFILE
    source_details=preflight['source_details']
    hashes={row['symbol']:source_details[row['symbol']]['declared_csv_sha256'] for row in rows}
    cache_sources={row['symbol']:preflight['sources'][row['symbol']] for row in rows}
    compact_coverage={key:preflight[key] for key in ('schema','total','available','missing','missing_symbols','coverage_complete','explicit_cache','candidate_roots','preflight_semantics','source_selection','network_used')}
    compact_coverage['invalid_sources_count']=len(preflight['invalid_sources'])
    compact_coverage['minimum_closed_bars']=preflight.get('minimum_closed_bars',50)
    compact_coverage['insufficient_history_count']=len(preflight.get('insufficient_history_symbols',[]))
    compact_coverage['resource_request']=requested
    compact_coverage['resource_plan']=plan
    return _launch_prepared(rows,cutoff,workers,cache,engine,profile,cache_sources,hashes,
                            policy,requested_total,compact_coverage)


def _launch_prepared(rows,cutoff,workers,cache,engine,profile,cache_sources,hashes,policy,requested_total,compact_coverage):
    with LAUNCH_LOCK:
        _check_idle()
        return _spawn_prepared(rows,cutoff,workers,cache,engine,profile,cache_sources,hashes,
                                policy,requested_total,compact_coverage)


def _spawn_prepared(rows,cutoff,workers,cache,engine,profile,cache_sources,hashes,policy,requested_total,compact_coverage):
    ident='backtest-'+uuid.uuid4().hex[:12];folder=STATE/'backtests'/ident;folder.mkdir(parents=True)
    spec={'id':ident,'created':now_iso(),'cutoff':cutoff,'workers':workers,'cache':str(cache),
          'records':rows,'output':str(folder),'engine':engine,
          'cache_sources':cache_sources,'source_hashes':hashes,
          'cache_policy':policy,'requested_total':requested_total,
          'skipped_missing_count':requested_total-len(rows),'cache_coverage':compact_coverage}
    spec['requested_workers']=compact_coverage.get('resource_request',workers)
    spec['resource_plan']=compact_coverage.get('resource_plan')
    atomic_json(folder/'request.json',spec)
    command=[sys.executable,'--backtest-worker',str(folder/'request.json')] if getattr(sys,'frozen',False) else [sys.executable,'-m','workbench.backtests',str(folder/'request.json')]
    with (folder/'worker.stdout.txt').open('ab') as stdout,(folder/'worker.stderr.txt').open('ab') as stderr:
        p=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                           env=_worker_env(),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    value={**{k:spec[k] for k in ['id','created','cutoff','workers','output','engine']},
           'state':'running','pid':p.pid,'total':len(rows),'algorithm_scope':profile,
           'reference_engine_performance':engine=='native',
           'cache_available':len(rows),'requested_total':requested_total,
           'skipped_missing_count':requested_total-len(rows),'cache_policy':policy,
           'requested_workers':spec['requested_workers'],'resource_plan':spec['resource_plan'],
           'cache_selection':'frozen_per_symbol_whole_sources'}
    with connect() as db:db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('backtest:'+ident,json.dumps(value)))
    return value


def worker(path):
    spec=json.loads(Path(path).read_text(encoding='utf-8'))
    def progress(summary):print(json.dumps(summary,ensure_ascii=False),flush=True)
    sources={key:spec[key] for key in ('cache_sources','source_hashes') if key in spec}
    if spec.get('resource_plan') is not None:sources['resource_plan']=spec['resource_plan']
    if spec.get('engine','proxy')=='native':
        return run_native_market(spec['records'],spec['cache'],spec['cutoff'],spec['output'],
                                 spec['workers'],progress,Path(spec['output'])/'STOP',**sources)
    return run_market(spec['records'],spec['cache'],spec['cutoff'],spec['output'],spec['workers'],progress,Path(spec['output'])/'STOP',**sources)


def results():
    with connect() as db:rows=[json.loads(row[0]) for row in db.execute("SELECT value FROM metadata WHERE key LIKE 'backtest:%'")]
    from .server import alive
    for item in rows:
        folder=_output(item)
        full=_summary(folder)
        if full is not None:
            item['summary']={k:v for k,v in full.items() if k not in ('failed_records','failed_symbols')}
            value=item['summary'];processed=value.get('completed',0)+value.get('failed',0)
            value['processing_complete']=value.get('processing_complete',processed==item['total'])
            value['scheduled_success_complete']=(value.get('completed',0)==item['total'] and
                value.get('failed',0)==0 and value['processing_complete'])
            value['failure_count']=value.get('failed',0)
            value['failure_preview']=(full.get('failed_records') or [])[:3]
            requested=item.get('requested_total',item.get('total',value.get('total')))
            value['requested_total']=requested
            value['scheduled_total']=item.get('total',value.get('total'))
            value['skipped_missing_count']=item.get('skipped_missing_count',max(0,requested-value['scheduled_total']))
            value['cache_policy']=item.get('cache_policy','legacy_unspecified')
            value['cache_preflight_verified']=item.get('cache_selection')=='frozen_per_symbol_whole_sources'
            value['universe_coverage_rate']=(value.get('completed',0)/requested) if requested else None
            value['successful_coverage_complete']=(value.get('completed',0)==requested and
                value.get('failed',0)==0 and value['skipped_missing_count']==0 and value['processing_complete'])
        if item.get('state')=='running' and not alive(item.get('pid')):
            summary=item.get('summary',{})
            item['state']=('completed_with_errors' if summary.get('failed',0)>0 or summary.get('skipped_missing_count',0)>0 else 'complete') if summary.get('processing_complete') else 'interrupted'
        elif item.get('state')=='complete' and item.get('summary',{}).get('failed',0)>0:
            item['state']='completed_with_errors'
        error=folder/'worker.stderr.txt'
        if item['state']=='interrupted' and error.exists():item['error']=error.read_text(encoding='utf-8',errors='replace')[-1500:]
    return {'runs':sorted(rows,key=lambda x:x['created'],reverse=True),'execution_allowed':False}


def errors(ident,offset=0,limit=20):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise ValueError('invalid failure pagination')
    with connect() as db:row=db.execute('SELECT value FROM metadata WHERE key=?',('backtest:'+ident,)).fetchone()
    if row is None:raise ValueError('backtest not found')
    value=json.loads(row[0]);summary=_summary(_output(value)) or {};records=summary.get('failed_records')
    if records is None:
        import csv
        path=_output(value)/'stocks.csv'
        if path.is_file():
            with path.open(encoding='utf-8-sig',newline='') as stream:
                records=[{'symbol':r['symbol'],'error':r.get('error','unknown failure')} for r in csv.DictReader(stream) if r.get('state')=='failed']
        else:records=[]
    return {'id':ident,'total':len(records),'offset':offset,'limit':limit,'rows':records[offset:offset+limit],
            'execution_allowed':False}


def stop(ident):
    with connect() as db:row=db.execute('SELECT value FROM metadata WHERE key=?',('backtest:'+ident,)).fetchone()
    if row is None:raise ValueError('backtest not found')
    value=json.loads(row[0]);(Path(value['output'])/'STOP').write_text('stop requested',encoding='utf-8')
    return {'state':'stopping','id':ident}


def resume(ident):
    with LAUNCH_LOCK:
        _check_idle()
        return _resume_locked(ident)


def _resume_locked(ident):
    with connect() as db:row=db.execute('SELECT value FROM metadata WHERE key=?',('backtest:'+ident,)).fetchone()
    if row is None:raise ValueError('backtest not found')
    value=json.loads(row[0]);folder=_output(value);request=folder/'request.json'
    from .server import alive
    if alive(value.get('pid')):raise ValueError('backtest process is still running')
    if not request.exists():raise ValueError('this imported report has no resumable source request')
    spec=json.loads(request.read_text(encoding='utf-8'))
    symbols={record['symbol'] for record in spec['records']}
    if 'cache_sources' in spec:
        if symbols!=set(spec['cache_sources']) or symbols!=set(spec.get('source_hashes',{})):
            raise ValueError('回测来源清单不完整，请新建回测；原结果保留')
    else:
        from .backtest_cache import resolve_sources
        preflight=resolve_sources(ROOT,spec['records'],spec.get('cutoff'),explicit_cache=spec.get('cache'))
        if preflight['available']!=len(spec['records']):
            raise ValueError(f"旧回测指定缓存仅覆盖 {preflight['available']}/{len(spec['records'])} 只，继续会重复缺文件错误；请新建回测自动选择任务缓存，旧结果保留")
    stop_file=folder/'STOP'
    if stop_file.exists():stop_file.unlink()
    command=[sys.executable,'--backtest-worker',str(request)] if getattr(sys,'frozen',False) else [sys.executable,'-m','workbench.backtests',str(request)]
    with (folder/'worker.stdout.txt').open('ab') as stdout,(folder/'worker.stderr.txt').open('ab') as stderr:
        p=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                           env=_worker_env(),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    value.update(state='running',pid=p.pid)
    with connect() as db:db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('backtest:'+ident,json.dumps(value)))
    return value


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support();worker(sys.argv[1])
