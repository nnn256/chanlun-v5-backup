"""Durable local full-history 1m/5m replay; a row is successful only after recheck.

Acquisition is deliberately separate: point --cache at capture_market_intraday's
market_data directory, and use --follow-cache to consume completed source files.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing, redirect_stdout, redirect_stderr
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.intraday_research import PROFILE, IntradayConfig
from chanmodel.model import time_value
from chanmodel.tdx_data import atomic_json, symbol
from chanmodel.v2.io import load_cache_series
from chanmodel.v2.series import CN
from tools.run_intraday_research import run_one
from tools.verify_intraday_research import audit_record

RUNNER_PROFILE='all_market_native_intraday_verified_v1'
TERMINAL={'verified','failed','source_unavailable'}
_CODE_CHECK_CACHE=None


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def code_identity(root=ROOT):
    paths=list((root/'chanmodel').rglob('*.py'))+list((root/'third_party/chanpy').rglob('*.py'))
    paths += [root/'third_party/chanpy/provenance.json']
    paths += [root/'tools'/name for name in ('run_all_market_intraday.py','run_intraday_research.py','verify_intraday_research.py')]
    values={p.relative_to(root).as_posix():file_hash(p) for p in paths if '__pycache__' not in p.parts}
    digest=hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'sha256':digest,'files':values}


def code_matches(expected):
    # Poll cheap source metadata; rehash only after a file/mtime/size change.
    # Full content identity is always checked at worker start and finish.
    global _CODE_CHECK_CACHE
    try:stamp=tuple((name,(ROOT/name).stat().st_mtime_ns,(ROOT/name).stat().st_size)
                    for name in sorted(expected['files']))
    except OSError:return False
    key=(expected['sha256'],stamp)
    if _CODE_CHECK_CACHE and _CODE_CHECK_CACHE[0]==key:return _CODE_CHECK_CACHE[1]
    result=code_identity()['sha256']==expected['sha256'];_CODE_CHECK_CACHE=(key,result)
    return result


def load_universe(path,limit=0):
    value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    rows=value if isinstance(value,list) else next((value[k] for k in ('records','rows','symbols') if isinstance(value.get(k),list)),None)
    if rows is None:raise ValueError('universe must be a normalized records/rows/symbols list')
    selected={}
    for row in rows:
        code=symbol(row if isinstance(row,str) else row.get('symbol'))
        if code in selected:raise ValueError('duplicate security in frozen universe: '+code)
        selected[code]={'symbol':code,'name':row.get('name',code) if isinstance(row,dict) else code}
    records=[selected[key] for key in sorted(selected)]
    if not records:raise ValueError('frozen universe has no securities')
    return records[:limit] if limit else records


def connect_db(path):
    db=sqlite3.connect(path,timeout=30)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA busy_timeout=30000')
    return db


class RunLock:
    def __init__(self,path):self.path=Path(path);self.handle=None
    def __enter__(self):
        self.handle=self.path.open('a+b');self.handle.seek(0);self.handle.write(b'1');self.handle.flush();self.handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.handle.close();raise ValueError('another batch orchestrator already owns this output directory')
        return self
    def __exit__(self,*_):self.handle.close()


def initialize(db_path,manifest):
    with closing(connect_db(db_path)) as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS tasks(
          symbol TEXT,period TEXT,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
          stage TEXT,started_at TEXT,finished_at TEXT,updated_at TEXT,error TEXT,
          source_identity TEXT,record TEXT,verification TEXT,
          worker_pid INTEGER,
          PRIMARY KEY(symbol,period));''')
        for row in manifest['universe']:
            for period in manifest['periods']:
                db.execute('INSERT OR IGNORE INTO tasks(symbol,period) VALUES(?,?)',(row['symbol'],period))
        db.commit()


def write_stage(db_path,code,period,stage,**values):
    fields={'stage':stage,'updated_at':datetime.now(CN).isoformat(),**values}
    with closing(connect_db(db_path)) as db:
        db.execute('UPDATE tasks SET '+','.join(k+'=?' for k in fields)+' WHERE symbol=? AND period=?',
                   (*fields.values(),code,period));db.commit()


def available_memory_bytes():
    if os.name=='nt':
        import ctypes
        class Status(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in
                ('total_phys','available_phys','total_page','available_page','total_virtual','available_virtual','extended')]
        value=Status();value.length=ctypes.sizeof(value)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):return None
        return value.available_phys
    try:return os.sysconf('SC_AVPHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
    except (AttributeError,OSError,ValueError):return None


def process_alive(pid):
    if type(pid) is not int or pid<=0:return False
    if os.name=='nt':
        import ctypes
        api=ctypes.windll.kernel32;api.OpenProcess.restype=ctypes.c_void_p
        handle=api.OpenProcess(0x1000,False,pid)
        if not handle:return False
        try:
            code=ctypes.c_ulong();return bool(api.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code))) and code.value==259
        finally:api.CloseHandle(ctypes.c_void_p(handle))
    try:os.kill(pid,0);return True
    except OSError:return False


def source_paths(cache,code,period):
    folder=Path(cache)/'tdx'/('minute1' if period=='1m' else 'minute5')
    return folder/'ohlcv'/(code+'.csv.gz'),folder/'metadata'/(code+'.json')


def source_identity(cache,code,period):
    csv_path,meta_path=source_paths(cache,code,period)
    series,receipt=load_cache_series(Path(cache),code,period)
    return {'csv_sha256':receipt['csv_sha256'],'storage_sha256':file_hash(csv_path),
            'metadata_sha256':file_hash(meta_path),'rows':len(series.bars),
            'first_close':series.bars[0].closed_at,'last_close':series.bars[-1].closed_at}


def verified_still_intact(row,cache):
    try:
        identity=json.loads(row['source_identity']);record=json.loads(row['record'])
        verification=json.loads(row['verification'])
        csv_path,meta_path=source_paths(cache,row['symbol'],row['period'])
        return (verification.get('state')=='passed' and
                file_hash(csv_path)==identity['storage_sha256'] and
                file_hash(meta_path)==identity['metadata_sha256'] and
                file_hash(record['artifact'])==record['artifact_sha256'])
    except (OSError,ValueError,KeyError,TypeError):return False


def worker(code,period,manifest,db_path,expected_source):
    out=Path(manifest['output']);folder=out/'stocks'/code/period;folder.mkdir(parents=True,exist_ok=True)
    with (folder/'worker.log').open('a',encoding='utf-8',buffering=1) as log,redirect_stdout(log),redirect_stderr(log):
        try:
            print(datetime.now(CN).isoformat(),'START',code,period,flush=True)
            write_stage(db_path,code,period,'checking_source',worker_pid=os.getpid())
            if code_identity()['sha256']!=manifest['code']['sha256']:raise ValueError('frozen source code changed before replay')
            current=source_identity(manifest['cache'],code,period)
            if expected_source and current!=expected_source:raise ValueError('frozen cached source changed since prior attempt')
            write_stage(db_path,code,period,'replay',source_identity=json.dumps(current))
            record=run_one(code,manifest['cache'],out/'stocks',period,manifest['cutoff'],0,0,IntradayConfig(**manifest['config']))
            record['state']='complete'
            if source_identity(manifest['cache'],code,period)!=current:raise ValueError('cached source changed during replay')
            write_stage(db_path,code,period,'independent_verification',record=json.dumps(record,ensure_ascii=False))
            verification=audit_record(record,manifest['cache'])
            atomic_json(folder/'verification.json',verification)
            if verification['state']!='passed':raise ValueError('independent replay failed: '+str(verification['errors']))
            if code_identity()['sha256']!=manifest['code']['sha256']:raise ValueError('frozen source code changed during independent replay')
            print(datetime.now(CN).isoformat(),'VERIFIED',code,period,flush=True)
            write_stage(db_path,code,period,'verified',state='verified',record=json.dumps(record,ensure_ascii=False),
                        verification=json.dumps(verification,ensure_ascii=False),finished_at=datetime.now(CN).isoformat())
            return {'state':'verified','record':record,'verification':verification,'source_identity':current}
        except Exception as exc:
            traceback.print_exc()
            write_stage(db_path,code,period,'failed',state='failed',error=f'{type(exc).__name__}: {exc}',finished_at=datetime.now(CN).isoformat())
            return {'state':'failed','error':f'{type(exc).__name__}: {exc}'}


def aggregate(db_path,manifest,state):
    with closing(connect_db(db_path)) as db:
        counts=dict(db.execute('SELECT state,COUNT(*) FROM tasks GROUP BY state').fetchall())
        requested=sum(counts.values());verified=counts.get('verified',0)
        totals=db.execute("SELECT COALESCE(SUM(json_extract(record,'$.input_bars')),0),COALESCE(SUM(json_extract(record,'$.alerts')),0) FROM tasks WHERE state='verified'").fetchone()
        active=[dict(r) for r in db.execute("SELECT symbol,period,stage,started_at,worker_pid FROM tasks WHERE state='running' ORDER BY symbol,period LIMIT 20")]
        failures=[dict(r) for r in db.execute("SELECT symbol,period,error FROM tasks WHERE state='failed' ORDER BY symbol,period LIMIT 20")]
    return {'profile':RUNNER_PROFILE,'algorithm_profile':PROFILE,'state':state,
            'updated_at':datetime.now(CN).isoformat(),'cutoff':manifest['cutoff'],
            'securities':len(manifest['universe']),'periods':manifest['periods'],'requested':requested,
            'counts':counts,'verified':verified,'failed':counts.get('failed',0),
            'source_unavailable':counts.get('source_unavailable',0),
            'processing_complete':all(key in TERMINAL for key in counts),
            'successful_coverage_complete':bool(requested) and verified==requested,
            'bars_verified':totals[0],'alerts_verified':totals[1],
            'code_sha256':manifest['code']['sha256'],'full_history':True,'sessions':0,'warmup':0,
            'universe_scope':'frozen current listed A shares; no claim of historical delisted membership',
            'history_scope':'all native observations actually returned per security/period; not unlimited listing-inception history',
            'execution_allowed':False,'uploaded':False,
            'active_tasks':active,'failed_records':failures,
            'detail_scope':'first 20 active/failed rows; SQLite retains all security-period records'}


def acquisition_finished(path):
    if not path:return False
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        return value.get('processing_complete') is True or value.get('state')=='completed'
    except (OSError,ValueError):return False


def acquisition_stopped(path):
    if not path:return False
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        return str(value.get('state','')).startswith('stopped_')
    except (OSError,ValueError):return False


def source_failure(cache,code,period):
    path=Path(cache)/'capture-status'/period/(code+'.json')
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('state') in ('failed','unavailable'):
            return str(value.get('error') or value.get('reason') or value['state'])
    except (OSError,ValueError):pass
    return None


def run(universe,cache,output,cutoff,*,workers=2,periods=('1m','5m'),limit=0,
        resume=False,retry_failed=False,min_free_gb=10,min_free_memory_mb=512,stop_file=None,follow_cache=False,source_status=None):
    if not 1<=workers<=8:raise ValueError('workers must be 1..8')
    if not periods or any(p not in ('1m','5m') for p in periods):raise ValueError('periods must be 1m and/or 5m')
    if limit<0 or not math.isfinite(min_free_gb) or min_free_gb<0 or not math.isfinite(min_free_memory_mb) or min_free_memory_mb<0:
        raise ValueError('limit and free-resource gates must be finite nonnegative values')
    moment=time_value(cutoff)
    if moment>datetime.now(CN):raise ValueError('cutoff must not be in the future')
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True)
    stop=Path(stop_file) if stop_file else out/'STOP'
    records=load_universe(universe,limit)
    manifest={'profile':RUNNER_PROFILE,'output':str(out),'cache':str(Path(cache).resolve()),
              'cutoff':cutoff,'periods':sorted(set(periods)),'universe':records,
              'universe_file_sha256':file_hash(universe),'config':asdict_config(),
              'sessions':0,'warmup':0,'code':code_identity(),'execution_allowed':False,'uploaded':False}
    manifest_path=out/'manifest.json';db_path=out/'tasks.sqlite3';summary_path=out/'summary.json'
    with RunLock(out/'runner.lock'):
        if manifest_path.exists():
            if not resume:raise ValueError('output already has a manifest; use --resume or choose a new output')
            previous=json.loads(manifest_path.read_text(encoding='utf-8'))
            if previous!=manifest:raise ValueError('resume configuration, universe, paths, cutoff or frozen code SHA256 differs')
        else:
            if resume:raise ValueError('--resume requires an existing manifest')
            atomic_json(manifest_path,manifest)
        initialize(db_path,manifest)
        with closing(connect_db(db_path)) as db:
            for row in db.execute("SELECT * FROM tasks WHERE state='running'").fetchall():
                if not process_alive(row['worker_pid']):
                    db.execute("UPDATE tasks SET state='pending',stage='recovered_after_interruption',worker_pid=NULL WHERE symbol=? AND period=?",(row['symbol'],row['period']))
            for row in db.execute("SELECT symbol,period,source_identity,record,verification FROM tasks WHERE state='verified'"):
                if not verified_still_intact(row,cache):
                    db.execute("UPDATE tasks SET state='failed',error='verified artifact or frozen source integrity changed' WHERE symbol=? AND period=?",(row['symbol'],row['period']))
            if retry_failed:db.execute("UPDATE tasks SET state='pending',error=NULL WHERE state IN ('failed','source_unavailable')")
            db.commit()
        status='running'
        # Release each native engine's retained graph after its security/period
        # finishes; the viewing application must not compete with accumulated
        # worker heaps over an all-market run.
        with ProcessPoolExecutor(max_workers=workers,max_tasks_per_child=1) as pool:
            futures={}
            while True:
                stopped=stop.exists();free=shutil.disk_usage(out).free
                memory=available_memory_bytes();memory_low=memory is not None and memory<min_free_memory_mb*1024**2
                disk_low=free<min_free_gb*1024**3
                changed=not code_matches(manifest['code'])
                if stopped:status='stopped_by_file'
                elif disk_low:status='stopped_low_disk'
                elif changed:status='stopped_code_changed'
                if status=='running' and not memory_low:
                    with closing(connect_db(db_path)) as db:
                        pending=db.execute("SELECT symbol,period,source_identity FROM tasks WHERE state IN ('pending','waiting_source') ORDER BY attempts,symbol,period")
                        for row in pending:
                            if len(futures)>=workers:break
                            csv_path,meta_path=source_paths(cache,row['symbol'],row['period'])
                            if not csv_path.is_file() or not meta_path.is_file():
                                failure=source_failure(cache,row['symbol'],row['period'])
                                terminal=bool(failure) or not follow_cache or acquisition_finished(source_status)
                                db.execute('UPDATE tasks SET state=?,error=?,updated_at=? WHERE symbol=? AND period=?',
                                           ('source_unavailable' if terminal else 'waiting_source',failure or 'native cached source not available',datetime.now(CN).isoformat(),row['symbol'],row['period']))
                                continue
                            expected=json.loads(row['source_identity']) if row['source_identity'] else None
                            db.execute("UPDATE tasks SET state='running',stage='starting',attempts=attempts+1,started_at=?,updated_at=?,error=NULL WHERE symbol=? AND period=?",(datetime.now(CN).isoformat(),datetime.now(CN).isoformat(),row['symbol'],row['period']))
                            job_manifest={key:manifest[key] for key in ('output','cache','cutoff','config','code')}
                            futures[pool.submit(worker,row['symbol'],row['period'],job_manifest,str(db_path),expected)]=(row['symbol'],row['period'])
                        db.commit()
                done,_=wait(futures,timeout=1,return_when=FIRST_COMPLETED) if futures else (set(),set())
                for future in done:
                    code,period=futures.pop(future)
                    try:value=future.result()
                    except Exception as exc:value={'state':'failed','error':f'worker process: {type(exc).__name__}: {exc}'}
                    fields={'state':value['state'],'stage':value['state'],'error':value.get('error'),
                            'finished_at':datetime.now(CN).isoformat(),'updated_at':datetime.now(CN).isoformat()}
                    for key in ('record','verification','source_identity'):
                        if key in value:fields[key]=json.dumps(value[key],ensure_ascii=False)
                    with closing(connect_db(db_path)) as db:
                        db.execute('UPDATE tasks SET '+','.join(k+'=?' for k in fields)+' WHERE symbol=? AND period=?',(*fields.values(),code,period));db.commit()
                    with (out/'progress.jsonl').open('a',encoding='utf-8') as log:
                        log.write(json.dumps({'symbol':code,'period':period,**fields},ensure_ascii=False)+'\n')
                    print(code,period,value['state'],value.get('error',''),flush=True)
                summary=aggregate(db_path,manifest,'waiting_memory' if memory_low and status=='running' else status)
                if status=='running' and not memory_low and not futures and summary['counts'].get('waiting_source'):
                    summary['state']='waiting_source'
                    if acquisition_stopped(source_status):status='paused_waiting_source';summary['state']=status
                summary.update(free_disk_bytes=free,available_memory_bytes=memory,
                               min_free_memory_mb=min_free_memory_mb,min_free_disk_gb=min_free_gb,
                               workers=workers,source_status=str(source_status) if source_status else None)
                atomic_json(summary_path,summary)
                if not futures and (status!='running' or summary['processing_complete']):break
                if not futures:
                    # Bounded idle polling consumes acquisition output without
                    # declaring missing inputs successful or occupying workers.
                    time.sleep(2)
            if status=='running':status='completed'
        summary=aggregate(db_path,manifest,status)
        summary.update(free_disk_bytes=shutil.disk_usage(out).free,available_memory_bytes=available_memory_bytes(),
                       min_free_memory_mb=min_free_memory_mb,min_free_disk_gb=min_free_gb,workers=workers,
                       source_status=str(source_status) if source_status else None)
        atomic_json(summary_path,summary)
        return summary


def asdict_config():
    from dataclasses import asdict
    return json.loads(json.dumps(asdict(IntradayConfig())))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--universe',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--cutoff',required=True)
    p.add_argument('--workers',type=int,default=2);p.add_argument('--periods',nargs='+',default=['1m','5m'])
    p.add_argument('--limit',type=int,default=0);p.add_argument('--resume',action='store_true')
    p.add_argument('--retry-failed',action='store_true');p.add_argument('--min-free-gb',type=float,default=10)
    p.add_argument('--min-free-memory-mb',type=float,default=512)
    p.add_argument('--stop-file',type=Path);p.add_argument('--follow-cache',action='store_true')
    p.add_argument('--source-status',type=Path)
    a=p.parse_args()
    result=run(a.universe,a.cache,a.output,a.cutoff,workers=a.workers,periods=tuple(a.periods),limit=a.limit,
               resume=a.resume,retry_failed=a.retry_failed,min_free_gb=a.min_free_gb,min_free_memory_mb=a.min_free_memory_mb,stop_file=a.stop_file,
               follow_cache=a.follow_cache,source_status=a.source_status)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['failed'] or result['source_unavailable']:raise SystemExit(2)


if __name__=='__main__':main()
