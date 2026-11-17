"""Durable EXE-safe all-market backtest jobs and progress."""
from datetime import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import uuid
from chanmodel.tdx_data import atomic_json,now_iso
from chanmodel.market_backtest import run_market,PROFILE as BACKTEST_PROFILE
from chanmodel.native_market_backtest import run_market as run_native_market, BACKTEST_PROFILE as NATIVE_BACKTEST_PROFILE
from .store import ROOT,STATE,connect


def default_cache_dir():
    configured=os.environ.get('CHANLUN_MARKET_DATA_DIR')
    return Path(configured or ROOT.parent/'data'/'market_data').resolve()


def normalize_workers(value):
    if value=='auto':return 'auto'
    if isinstance(value,bool):
        raise ValueError('并行股票数必须为1到16之间的整数')
    if isinstance(value,int):
        workers=value
    elif isinstance(value,float) and math.isfinite(value) and value.is_integer():
        workers=int(value)
    elif isinstance(value,str):
        text=value.strip()
        if not text.isascii() or not text.isdecimal():
            raise ValueError('并行股票数必须为1到16之间的整数')
        workers=int(text)
    else:
        raise ValueError('并行股票数必须为1到16之间的整数')
    if not 1<=workers<=16:
        raise ValueError('并行股票数必须为1到16之间的整数')
    return workers


def launch(body):
    workers=normalize_workers(body.get('workers','auto'))
    cutoff=body.get('cutoff') or now_iso();point=datetime.fromisoformat(cutoff)
    if point.tzinfo is None:raise ValueError('backtest cutoff requires timezone')
    engine=body.get('engine','native')
    if engine not in {'native','proxy'}:raise ValueError('backtest engine must be native or proxy')
    profile=NATIVE_BACKTEST_PROFILE if engine=='native' else BACKTEST_PROFILE
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        from .server import alive
        if any(alive(row['pid']) for row in db.execute("SELECT pid FROM jobs WHERE state IN ('starting','running','pausing','cancelling')")):
            raise ValueError('分析任务正在计算，请待其完成后启动回测，以免争抢内存')
        for row in db.execute("SELECT value FROM metadata WHERE key LIKE 'backtest:%'"):
            value=json.loads(row[0])
            from .server import alive
            if value['state'] in {'starting','running','pausing','cancelling'} and (
                    value['state']!='running' or alive(value.get('pid'))):
                raise ValueError('a backtest is already starting or running')
        rows=[dict(r) for r in db.execute('SELECT * FROM universe WHERE active=1 ORDER BY symbol')]
        if body.get('scope','all')=='selected':
            selected=body.get('symbols',[])
            if not isinstance(selected,list) or not selected:raise ValueError('selected backtest needs securities')
            rows=[r for r in rows if r['symbol'] in selected]
            if len(rows)!=len(set(selected)):raise ValueError('unknown backtest security')
        ident='backtest-'+uuid.uuid4().hex[:12];folder=STATE/'backtests'/ident;folder.mkdir(parents=True)
        cache=Path(body['cache']).resolve() if body.get('cache') else default_cache_dir()
        if not (cache/'tdx/day/ohlcv').is_dir():raise ValueError('history cache must contain tdx/day/ohlcv')
        spec={'id':ident,'created':now_iso(),'cutoff':cutoff,'workers':workers,'cache':str(cache),
              'records':rows,'output':str(folder),'engine':engine,
              'resource_policy':'cpu_memory_adaptive_v1','execution_backend':'cpu_multiprocess'}
        atomic_json(folder/'request.json',spec)
        command=[sys.executable,'--backtest-worker',str(folder/'request.json')] if getattr(sys,'frozen',False) else [sys.executable,'-m','workbench.backtests',str(folder/'request.json')]
        with (folder/'worker.stdout.txt').open('ab') as stdout,(folder/'worker.stderr.txt').open('ab') as stderr:
            p=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                               env={**os.environ,'PYTHONIOENCODING':'utf-8'},creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        value={**{k:spec[k] for k in ['id','created','cutoff','workers','output','engine']},
               'state':'running','pid':p.pid,'total':len(rows),'algorithm_scope':profile,
               'resource_policy':spec['resource_policy'],'execution_backend':spec['execution_backend'],
               'reference_engine_performance':engine=='native'}
        db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('backtest:'+ident,json.dumps(value)))
    return value


def worker(path):
    spec=json.loads(Path(path).read_text(encoding='utf-8'))
    def progress(summary):print(json.dumps(summary,ensure_ascii=False),flush=True)
    if spec.get('engine','proxy')=='native':
        return run_native_market(spec['records'],spec['cache'],spec['cutoff'],spec['output'],
                                 spec['workers'],progress,Path(spec['output'])/'STOP')
    return run_market(spec['records'],spec['cache'],spec['cutoff'],spec['output'],spec['workers'],progress,Path(spec['output'])/'STOP')


def results():
    with connect() as db:rows=[json.loads(row[0]) for row in db.execute("SELECT value FROM metadata WHERE key LIKE 'backtest:%'")]
    from .server import alive
    for item in rows:
        folder=Path(item['output']);folder=folder if folder.is_absolute() else ROOT/folder
        summary=folder/'summary.json'
        if summary.exists():item['summary']=json.loads(summary.read_text(encoding='utf-8'))
        resources=folder/'resource-status.json'
        if resources.exists():
            try:item['resources']=json.loads(resources.read_text(encoding='utf-8'))
            except (OSError,ValueError):pass
        if item.get('state')=='running' and not alive(item.get('pid')):
            summary=item.get('summary',{})
            item['state']='complete' if summary.get('coverage_complete') else 'interrupted'
        error=folder/'worker.stderr.txt'
        if item['state']=='interrupted' and error.exists():item['error']=error.read_text(encoding='utf-8',errors='replace')[-1500:]
    return {'runs':sorted(rows,key=lambda x:x['created'],reverse=True),'execution_allowed':False}


def stop(ident):
    with connect() as db:row=db.execute('SELECT value FROM metadata WHERE key=?',('backtest:'+ident,)).fetchone()
    if row is None:raise ValueError('backtest not found')
    value=json.loads(row[0]);(Path(value['output'])/'STOP').write_text('stop requested',encoding='utf-8')
    return {'state':'stopping','id':ident}


def resume(ident):
    from .server import alive
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT value FROM metadata WHERE key=?',('backtest:'+ident,)).fetchone()
        if row is None:raise ValueError('backtest not found')
        value=json.loads(row[0]);folder=Path(value['output']);request=folder/'request.json'
        if alive(value.get('pid')):raise ValueError('backtest process is still running')
        for other in db.execute("SELECT value FROM metadata WHERE key LIKE 'backtest:%'"):
            item=json.loads(other[0])
            if item.get('state')=='running' and alive(item.get('pid')):raise ValueError('a backtest is already starting or running')
        if any(alive(row['pid']) for row in db.execute("SELECT pid FROM jobs WHERE state IN ('starting','running','pausing','cancelling')")):
            raise ValueError('分析任务正在计算，请待其完成后继续回测')
        if not request.exists():raise ValueError('this imported report has no resumable source request')
        stop_file=folder/'STOP'
        if stop_file.exists():stop_file.unlink()
        command=[sys.executable,'--backtest-worker',str(request)] if getattr(sys,'frozen',False) else [sys.executable,'-m','workbench.backtests',str(request)]
        with (folder/'worker.stdout.txt').open('ab') as stdout,(folder/'worker.stderr.txt').open('ab') as stderr:
            p=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                               env={**os.environ,'PYTHONIOENCODING':'utf-8'},creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        value.update(state='running',pid=p.pid)
        db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('backtest:'+ident,json.dumps(value)))
    return value


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support();worker(sys.argv[1])
