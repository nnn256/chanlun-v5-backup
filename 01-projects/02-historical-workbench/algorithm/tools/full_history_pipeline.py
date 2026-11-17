"""Freeze inputs/code, refresh all daily histories, then replay V4 and v3.

The existing F-drive intraday batch is observed only and never controlled here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

CN = timezone(timedelta(hours=8))
WORKSPACE = Path(__file__).resolve().parents[2]
V4 = WORKSPACE/'缠论算法'
V3 = WORKSPACE/'liangce-v3'


class AlreadyRunning(RuntimeError):pass


def clock():
    return datetime.now(CN).isoformat(timespec='seconds')


def atomic(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for attempt in range(8):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==7:raise
            time.sleep(.05*(attempt+1))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy_code(source, target, folders):
    for name in folders:
        for path in (source/name).rglob('*'):
            if not path.is_file() or any(part in {'__pycache__','node_modules','dist','.git'} for part in path.parts):
                continue
            if path.suffix not in {'.py','.json','.md'} and path.name not in {'LICENSE'}:
                continue
            destination=target/path.relative_to(source)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,destination)


@contextmanager
def lock(path):
    with Path(path).open('a+b') as stream:
        stream.seek(0);stream.write(b' ');stream.flush();stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:raise AlreadyRunning('another pipeline process owns this run') from error
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)


def prepare(root, base_url, python):
    root=Path(root).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('preparation requires a new output directory')
    root.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect('file:'+str(V4/'runtime/workbench/workbench.sqlite3').replace('\\','/')+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        records=[dict(row) for row in db.execute('SELECT * FROM universe WHERE active=1 ORDER BY symbol')]
    atomic(root/'inputs/universe.json',{'records':records,'frozen_at':clock(),
        'scope':'current listed A shares; historical delisted membership is not reconstructed'})
    copy_code(V4,root/'code/v4',['chanmodel','workbench','tools','third_party/chanpy'])
    copy_code(V3,root/'code/v3',['chanmodel','core','web','scripts'])
    files={p.relative_to(root/'code').as_posix():digest(p) for p in (root/'code').rglob('*') if p.is_file()}
    config={'schema':'both_systems_full_daily_pipeline_v1','root':str(root),'created_at':clock(),
        'cutoff':clock(),'base_url':base_url,'python':str(Path(python).resolve()),'securities':len(records),
        'v4_max_workers':2,'v3_workers':1,'network_workers':2,'frozen_files':files,
        'universe_sha256':digest(root/'inputs/universe.json'),
        'minute_run':'F:/ChanlunAlgorithmTests/2026-11-15-all-market-intraday',
        'history':'all returned closed daily bars from the earliest actual source date',
        'scheduling':'acquire, V4, then v3; minute run remains independently supervised',
        'execution_allowed':False,'uploaded':False}
    atomic(root/'pipeline.json',config)
    atomic(root/'status.json',{'state':'prepared','updated_at':clock(),'securities':len(records)})
    return config


def verify_code(root, config):
    if digest(root/'inputs/universe.json')!=config['universe_sha256']:
        raise ValueError('frozen universe changed')
    for relative, checksum in config['frozen_files'].items():
        if digest(root/'code'/relative)!=checksum:
            raise ValueError('frozen code changed: '+relative)


def run_child(root, config, stage, command, summary_path):
    log=root/'logs';log.mkdir(exist_ok=True)
    with (log/(stage+'.stdout.log')).open('ab') as stdout, (log/(stage+'.stderr.log')).open('ab') as stderr:
        env={k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONHOME','PYTHONPATH','PYTHONEXECUTABLE'}}
        env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',LIANGCE_HOSTING='offline-full-history')
        process=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atomic(root/'status.json',{'state':'running','stage':stage,'pid':os.getpid(),'child_pid':process.pid,
            'summary':str(summary_path),'updated_at':clock(),'securities':config['securities']})
        stop_sent=False
        while process.poll() is None:
            if (root/'STOP').exists() and not stop_sent:
                target=summary_path.parent/'STOP'
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text('pipeline STOP requested at '+clock(),encoding='utf-8');stop_sent=True
            time.sleep(1)
        if stop_sent:return False
        if (summary_path.parent/'STOP').exists():return False
        accepted={0,1} if stage=='acquisition' else {0,2}
        if process.returncode not in accepted:
            raise RuntimeError(stage+' exited '+str(process.returncode)+'; see '+str(log/(stage+'.stderr.log')))
        if not summary_path.is_file():raise RuntimeError(stage+' wrote no summary')
        summary=json.loads(summary_path.read_text(encoding='utf-8-sig'))
        if summary.get('state') in {'stopped','paused'}:return False
        if summary.get('state')=='stopped_code_changed' or summary.get('processing_complete') is False:
            raise RuntimeError(stage+' did not process its entire schedule')
        return True


def select_sources(root):
    sys.path.insert(0,str(root/'code/v4'))
    from workbench.backtest_cache import resolve_sources
    records=json.loads((root/'inputs/universe.json').read_text(encoding='utf-8'))['records']
    selected=resolve_sources(root/'code/v4',records,explicit_cache=root/'acquisition/cache')
    atomic(root/'inputs/daily-sources.json',selected)
    eligible=[r for r in records if r['symbol'] in selected['source_details'] and
              selected['source_details'][r['symbol']].get('closed_rows',0)>=50]
    atomic(root/'inputs/v4-eligible-universe.json',{'records':eligible})
    eligible_symbols={item['symbol'] for item in eligible}
    short=[{'symbol':r['symbol'],'bars':selected['source_details'].get(r['symbol'],{}).get('closed_rows'),
            'reason':'no_valid_source' if r['symbol'] not in selected['sources'] else 'fewer_than_50_daily_bars'}
           for r in records if r['symbol'] not in eligible_symbols]
    atomic(root/'inputs/coverage.json',{'requested':len(records),'source_pairs':selected['available'],
        'v4_eligible':len(eligible),'v4_excluded':short,'history_truncated':False,
        'declared_bars':sum(d.get('closed_rows',0) for d in selected['source_details'].values()),
        'last_dates':dict(Counter(d['last_date'] for d in selected['source_details'].values())),
        'source_manifest_sha256':digest(root/'inputs/daily-sources.json')})
    atomic(root/'inputs/selection-identity.json',{
        'sources_sha256':digest(root/'inputs/daily-sources.json'),
        'eligible_universe_sha256':digest(root/'inputs/v4-eligible-universe.json'),
        'acquisition_manifest_sha256':digest(root/'acquisition/manifest.json'),
        'acquisition_results_sha256':digest(root/'acquisition/results.json')})
    return selected


def verify_selection(root):
    identity=json.loads((root/'inputs/selection-identity.json').read_text(encoding='utf-8'))
    for key,path in [('sources_sha256','inputs/daily-sources.json'),
                     ('eligible_universe_sha256','inputs/v4-eligible-universe.json'),
                     ('acquisition_manifest_sha256','acquisition/manifest.json'),
                     ('acquisition_results_sha256','acquisition/results.json')]:
        if digest(root/path)!=identity[key]:raise ValueError('fixed acquisition selection changed: '+path)


def v4_phase(root):
    config=json.loads((root/'pipeline.json').read_text(encoding='utf-8'));verify_code(root,config);verify_selection(root)
    sys.path.insert(0,str(root/'code/v4'))
    from chanmodel.native_market_backtest import run_market
    selected=json.loads((root/'inputs/daily-sources.json').read_text(encoding='utf-8'))
    records=json.loads((root/'inputs/v4-eligible-universe.json').read_text(encoding='utf-8'))['records']
    if not records:raise ValueError('no native daily source with 50 closed bars')
    return run_market(records,root/'acquisition/cache',None,root/'v4-daily',workers=config['v4_max_workers'],
        stop_file=root/'v4-daily/STOP',cache_sources=selected['sources'],
        source_hashes={symbol:detail['declared_csv_sha256'] for symbol,detail in selected['source_details'].items()},
        progress=lambda s:print(json.dumps({k:s[k] for k in ('completed','failed','total','bars')},ensure_ascii=False),flush=True))


def run(root):
    root=Path(root).resolve();config=json.loads((root/'pipeline.json').read_text(encoding='utf-8'))
    verify_code(root,config)
    with lock(root/'pipeline.lock'):
        python=config['python']
        acquire=[python,str(root/'code/v4/tools/acquire_full_daily.py'),'--universe',str(root/'inputs/universe.json'),
            '--output',str(root/'acquisition'),'--base-url',config['base_url'],'--as-of',config['cutoff'],
            '--workers',str(config['network_workers'])]
        if (root/'acquisition/manifest.json').exists():acquire+=['--resume']
        stages=[('acquisition',acquire,root/'acquisition/summary.json')]
        for name,command,summary in stages:
            if (root/'STOP').exists():
                atomic(root/'status.json',{'state':'paused','stage':name,'updated_at':clock()});return
            if not run_child(root,config,name,command,summary):
                atomic(root/'status.json',{'state':'paused','stage':name,'updated_at':clock()});return
        if not (root/'inputs/daily-sources.json').exists():select_sources(root)
        verify_selection(root)
        command=[python,str(root/'code/v4/tools/full_history_pipeline.py'),'v4','--root',str(root)]
        if (root/'STOP').exists():
            atomic(root/'status.json',{'state':'paused','stage':'v4-daily','updated_at':clock()});return
        if not run_child(root,config,'v4-daily',command,root/'v4-daily/summary.json'):
            atomic(root/'status.json',{'state':'paused','stage':'v4-daily','updated_at':clock()});return
        command=[python,str(root/'code/v3/scripts/run_full_daily_replay.py'),
            '--universe',str(root/'inputs/universe.json'),'--source-manifest',str(root/'inputs/daily-sources.json'),
            '--output',str(root/'v3-daily'),'--min-free-memory-mb','1024']
        if (root/'v3-daily/manifest.json').exists():command+=['--resume']
        if (root/'STOP').exists():
            atomic(root/'status.json',{'state':'paused','stage':'v3-daily','updated_at':clock()});return
        if not run_child(root,config,'v3-daily',command,root/'v3-daily/summary.json'):
            atomic(root/'status.json',{'state':'paused','stage':'v3-daily','updated_at':clock()});return
        atomic(root/'status.json',{'state':'completed','updated_at':clock(),
            'daily_processing_finished':True,'minute_processing_finished':False,
            'coverage':json.loads((root/'inputs/coverage.json').read_text(encoding='utf-8')),
            'note':'Inspect failures, insufficient history and separate intraday progress before claiming all coverage.',
            'execution_allowed':False})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','run','v4'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--base-url',default='http://127.0.0.1:65004')
    parser.add_argument('--python',default=str(V3/'.venv/Scripts/python.exe'))
    options=parser.parse_args()
    if options.action=='prepare':prepare(options.root,options.base_url,options.python)
    elif options.action=='v4':v4_phase(options.root)
    else:
        try:run(options.root)
        except AlreadyRunning:raise
        except Exception as error:
            atomic(options.root/'status.json',{'state':'failed','updated_at':clock(),'error':f'{type(error).__name__}: {error}'})
            raise


if __name__=='__main__':
    main()
