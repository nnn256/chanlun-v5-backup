"""Loopback-only HTTP workbench with a persistent subprocess queue."""
import argparse
from datetime import datetime
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import csv
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, parse_qs, unquote
import uuid

from chanmodel.tdx_data import CN, TdxClient, normalize_universe, normalized_quotes, now_iso, atomic_bytes
from chanmodel.release import APP_VERSION,APP_LABEL
from .store import ROOT, STATE, connect, initialize, decode, publish_result

WEB = ROOT / 'workbench' / 'web'
ASSETS = ROOT / 'runs' / 'aoya-v2-chart-20261107' / 'assets'
LOCK = threading.Lock()
STOP = threading.Event()
ACTIVE = {'starting','running','pausing','cancelling'}
MODE_NAMES = {'day':'日线扫描','multi':'三周期校验','replay':'日线逐日回放','full':'全周期历史与分时'}


def alive(pid):
    if not pid:
        return False
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            return False
        status = wintypes.DWORD()
        try:
            return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(status))) and status.value==259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid,0)
        return True
    except OSError:
        return False


def seed():
    initialize()
    source = ROOT / 'runs/tdx-all-a-20261106/universe.json'
    with connect() as db:
        if not db.execute('SELECT COUNT(*) FROM universe').fetchone()[0]:
            records = json.loads(source.read_text(encoding='utf-8'))['records']
            db.executemany('INSERT OR IGNORE INTO universe(symbol,code,name,exchange) VALUES(?,?,?,?)',
                [(r['symbol'],r['code'],r['name'],r['exchange']) for r in records])
    # Existing completed V2 single-stock runs are available immediately.
    for folder in sorted((ROOT/'runs').glob('*-v2-chart-*')):
        if not (folder/'summary.json').exists() or not (folder/'chart-data.json').exists():
            continue
        summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
        code = summary['symbol']
        with connect() as db:
            previous=db.execute("SELECT summary FROM results WHERE symbol=? AND mode='multi'",(code,)).fetchone()
            if previous and json.loads(previous[0]).get('last_date','')>=summary['last_close_time'][:10]:continue
        chart = json.loads((folder/'chart-data.json').read_text(encoding='utf-8'))
        if 'periods' not in summary:
            continue
        summary.update(code=code[2:],exchange=code[:2],mode='multi',algorithm='V2',
            last_date=summary['last_close_time'][:10],state=summary.get('multiframe_explicit_tolerance_state','calculated'),
            triggered=summary.get('triggered_count',0),volume_tolerance=summary.get('volume_tolerance_shares',100),
            active_candidates=len(summary['periods']['day'].get('active_candidates',[])))
        from .compute import contract_brief
        for filename,key in [('multiframe-default.json','default_contract'),('multiframe-explicit-volume-tolerance.json','comparison_contract')]:
            f=folder/filename
            summary[key]=contract_brief(json.loads(f.read_text(encoding='utf-8'))['data_contract']) if f.exists() else None
        chart['last_close_time']=chart.get('as_of_bar',summary['last_close_time'])
        chart['symbol']=code
        chart['execution_allowed']=False
        chart.setdefault('definition_mode','recursive_completed_types_under_same_level_decomposition')
        chart.setdefault('input_sha256',{})
        artifact = STATE / 'imports' / f'{code}.json.gz'
        atomic_bytes(artifact,gzip.compress(json.dumps({'summary':summary,'chart':chart,'imported_from':folder.name},ensure_ascii=False).encode(),mtime=0))
        with connect() as db:
            publish_result(db,code,'multi','imported',now_iso(),json.dumps(summary,ensure_ascii=False),str(artifact.relative_to(STATE)))


def engine_hash():
    if getattr(sys,'frozen',False):
        info=json.loads((Path(sys._MEIPASS)/'build-info.json').read_text(encoding='utf-8'))
        value=info.get('engine_source_sha256')
        if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):
            raise ValueError('内置算法源码校验标识无效，请重新安装完整程序')
        return value
    paths=sorted((ROOT/'chanmodel').glob('*.py'))+sorted((ROOT/'chanmodel/v2').glob('*.py'))
    return hashlib.sha256(b''.join(p.name.encode()+p.read_bytes() for p in paths)).hexdigest()


def create_job(body):
    mode=body.get('mode','multi')
    if mode not in MODE_NAMES:
        raise ValueError('未知任务类型')
    requested_workers=body.get('workers','auto')
    from .resources import plan_resources
    resource_plan=plan_resources(mode,requested_workers,max_workers=32)
    workers=resource_plan['workers']
    tolerance=body.get('volume_tolerance',100)
    if type(tolerance) not in (int,float) or tolerance not in (1,100,1000):
        raise ValueError('成交量容差只接受1、100、1000股')
    refresh=body.get('refresh',False)
    if not isinstance(refresh,bool):
        raise ValueError('refresh必须是布尔值')
    cutoff=body.get('cutoff') or now_iso()
    at=datetime.fromisoformat(cutoff)
    if at.tzinfo is None or at>datetime.now(CN):
        raise ValueError('截止时点须带时区且不晚于当前时间')
    cutoff=at.astimezone(CN).isoformat(timespec='seconds')
    with LOCK, connect() as db:
        if body.get('scope')=='all':
            symbols=[r[0] for r in db.execute('SELECT symbol FROM universe WHERE active=1 ORDER BY symbol')]
        else:
            values=body.get('symbols',[])
            if not isinstance(values,list) or not values:
                raise ValueError('请选择股票或全市场范围')
            symbols=[]
            for value in values:
                if not isinstance(value,str) or not re.fullmatch(r'(?:(?:sh|sz|bj))?\d{6}',value):
                    raise ValueError('股票代码格式错误')
                row=db.execute('SELECT symbol FROM universe WHERE symbol=? OR code=?',(value,value)).fetchone()
                if not row:
                    raise ValueError(f'股票不在当前股票池：{value}')
                if row[0] not in symbols:
                    symbols.append(row[0])
        settings={'mode':mode,'cutoff':cutoff,'workers':workers,'refresh':refresh,
                  'requested_workers':requested_workers,'resource_plan':resource_plan,
                  'volume_tolerance':tolerance,'engine_sha256':engine_hash(),
                  'universe_semantics':'current provider-listed A shares; excludes historical delisted membership',
                  'execution_allowed':False}
        settings['interactive']=body.get('scope')!='all' and len(symbols)<=5
        if mode=='full':
            settings['refresh']=True
            settings['workers']=min(workers,3)
        signature=hashlib.sha256(json.dumps([sorted(symbols),mode,refresh,tolerance,cutoff[:10]],sort_keys=True).encode()).hexdigest()
        for row in db.execute("SELECT settings FROM jobs WHERE state IN ('queued','starting','running','pausing')"):
            if json.loads(row[0]).get('selection_hash')==signature:
                raise ValueError('相同范围和参数的任务已经在队列中')
        settings['selection_hash']=signature
        ident=datetime.now(CN).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
        title=('全市场' if body.get('scope')=='all' else f'{len(symbols)}只股票')+' · '+MODE_NAMES[mode]
        db.execute('INSERT INTO jobs(id,title,mode,state,created,updated,settings,total) VALUES(?,?,?,?,?,?,?,?)',
                   (ident,title,mode,'queued',now_iso(),now_iso(),json.dumps(settings,ensure_ascii=False),len(symbols)))
        db.executemany('INSERT INTO items(job_id,symbol) VALUES(?,?)',[(ident,s) for s in symbols])
    return {'id':ident,'state':'queued','total':len(symbols),'resource_plan':resource_plan}


def control_job(ident, action):
    with LOCK,connect() as db:
        job=decode(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        if not job:
            raise ValueError('任务不存在')
        state=job['state']
        if action=='pause' and state in ('queued','starting','running'):
            target='paused' if state=='queued' else 'pausing'
        elif action=='cancel' and state in ('queued','paused','interrupted','starting','running','pausing'):
            target='cancelling' if state in ('starting','running','pausing') else 'cancelled'
        elif action in ('resume','retry') and state in ('paused','interrupted','completed','cancelled'):
            if action=='retry':
                db.execute("UPDATE items SET state='pending',error=NULL WHERE job_id=? AND state='failed'",(ident,))
            db.execute("UPDATE items SET state='pending' WHERE job_id=? AND state='running'",(ident,))
            if not db.execute("SELECT 1 FROM items WHERE job_id=? AND state='pending'",(ident,)).fetchone():
                raise ValueError('没有可继续的股票；失败项请使用重试')
            if job['settings']['engine_sha256']!=engine_hash():
                raise ValueError('算法代码已变化，请创建新任务以保持版本一致')
            target='queued'
        else:
            raise ValueError('当前任务状态不支持该操作')
        db.execute('UPDATE jobs SET state=?,updated=?,finished=NULL WHERE id=?',(target,now_iso(),ident))
        from .jobs import update_counts
        update_counts(db,ident)
    return {'id':ident,'state':target}


def scheduler():
    while not STOP.wait(1):
        try:
            with LOCK,connect() as db:
                active=db.execute("SELECT * FROM jobs WHERE state IN ('starting','running','pausing','cancelling')").fetchall()
                for row in active:
                    if not alive(row['pid']):
                        db.execute("UPDATE jobs SET state='interrupted',message='运行进程已退出，可从断点继续',pid=NULL,updated=? WHERE id=?",(now_iso(),row['id']))
                live=[r for r in active if alive(r['pid'])]
                if live:
                    if any(json.loads(r['settings']).get('interactive',False) for r in live):continue
                    row=db.execute("SELECT id FROM jobs WHERE state='queued' AND json_extract(settings,'$.interactive')=1 ORDER BY created LIMIT 1").fetchone()
                else:
                    row=db.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
                if not row:
                    continue
                ident=row[0]; folder=STATE/'jobs'/ident;folder.mkdir(parents=True,exist_ok=True)
                db.execute("UPDATE jobs SET state='starting',updated=? WHERE id=?",(now_iso(),ident))
                db.commit()
                with (folder/'worker.log').open('ab') as log:
                    from .services import worker_command
                    # A PyInstaller parent can export its temporary PYTHONHOME/
                    # PYTHONPATH into a worker process. The embedded runtime
                    # then looks for encodings in a deleted extraction path and
                    # exits before the job starts. Workers must inherit locale
                    # and API settings, never the parent's interpreter paths.
                    worker_env={k:v for k,v in os.environ.items()
                                if k.upper() not in {'PYTHONHOME','PYTHONPATH','PYTHONEXECUTABLE'}}
                    worker_env['PYTHONIOENCODING']='utf-8'
                    proc=subprocess.Popen(worker_command(ident),cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                        env=worker_env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                db.execute('UPDATE jobs SET pid=? WHERE id=?',(proc.pid,ident))
        except Exception as exc:
            print(f'scheduler: {exc}',flush=True)


PICK = '''WITH ranked AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY
    json_extract(summary,'$.last_date') DESC,(mode='full') DESC,(mode='multi') DESC,updated DESC) rn FROM results),
    chosen AS (SELECT * FROM ranked WHERE rn=1),
    attempts AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY updated DESC) attempt_rank FROM items),
    latest_attempt AS (SELECT * FROM attempts WHERE attempt_rank=1) '''


def market(query):
    q=query.get('q',[''])[0][:80]; exchange=query.get('exchange',[''])[0]
    status=query.get('filter',[''])[0]; job=query.get('job',[''])[0]
    limit=max(1,min(100,int(query.get('limit',['40'])[0])));offset=max(0,int(query.get('offset',['0'])[0]))
    if not job and not status:
        where=['active=1'];params=[]
        if q:
            where.append('(code LIKE ? OR name LIKE ?)');params.extend(['%'+q+'%']*2)
        if exchange:
            where.append('exchange=?');params.append(exchange)
        clause=' AND '.join(where)
        with connect() as db:
            total=db.execute('SELECT COUNT(*) FROM universe WHERE '+clause,params).fetchone()[0]
            rows=[dict(row) for row in db.execute('SELECT * FROM universe WHERE '+clause+' ORDER BY symbol LIMIT ? OFFSET ?',params+[limit,offset])]
            codes=[row['symbol'] for row in rows]
            results={};attempts={}
            if codes:
                marks=','.join('?' for _ in codes)
                for value in db.execute(f'SELECT symbol,mode,job_id,updated,summary,artifact FROM results WHERE symbol IN ({marks})',codes):
                    item=dict(value);summary=json.loads(item['summary']) if item.get('summary') else {}
                    item['decoded_summary']=summary
                    previous=results.get(item['symbol'])
                    def result_rank(candidate):
                        value=candidate['decoded_summary']
                        return (value.get('last_date',''),candidate['mode']=='full',candidate['mode']=='multi',candidate['updated'])
                    if previous is None or result_rank(item)>result_rank(previous):results[item['symbol']]=item
                for value in db.execute(f'SELECT symbol,state,job_id,updated FROM items WHERE symbol IN ({marks}) ORDER BY symbol,updated DESC',codes):
                    item=dict(value);attempts.setdefault(item['symbol'],item)
        for row in rows:
            result=results.get(row['symbol']);summary=result['decoded_summary'] if result else {}
            attempt=attempts.get(row['symbol'])
            day=(summary.get('periods') or {}).get('day') or {}
            segment=day.get('last_segment') or {};center=day.get('latest_center') or {}
            row.update(item_state='success' if result else attempt['state'] if attempt else 'pending',
                job_id=result['job_id'] if result else attempt['job_id'] if attempt else None,
                price=summary.get('price'),change_pct=summary.get('change_pct'),last_date=summary.get('last_date'),
                mode=summary.get('mode'),algorithm=summary.get('algorithm'),analysis_state=summary.get('state'),
                triggered=summary.get('triggered'),active_candidates=summary.get('active_candidates'),
                direction=segment.get('direction'),segment_state=segment.get('state'),
                zd=center.get('zd'),zg=center.get('zg'),artifact=result['artifact'] if result else None)
        return {'rows':rows,'total':total,'offset':offset,'limit':limit}
    params=[];where=['1=1' if job else 'u.active=1']
    if q:
        where.append('(u.code LIKE ? OR u.name LIKE ?)');params.extend(['%'+q+'%']*2)
    if exchange:
        where.append('u.exchange=?');params.append(exchange)
    if job:
        prefix='';join='JOIN items r ON r.symbol=u.symbol AND r.job_id=?';params.insert(0,job)
        state='r.state';artifact='r.artifact';jobcol='r.job_id'
    else:
        prefix=PICK;join='LEFT JOIN chosen r ON r.symbol=u.symbol LEFT JOIN latest_attempt a ON a.symbol=u.symbol';state="CASE WHEN r.symbol IS NULL THEN COALESCE(a.state,'pending') ELSE 'success' END";artifact='r.artifact';jobcol='COALESCE(r.job_id,a.job_id)'
    if status=='candidate':where.append("COALESCE(json_extract(r.summary,'$.active_candidates'),0)>0")
    if status=='triggered':where.append("COALESCE(json_extract(r.summary,'$.triggered'),0)>0")
    if status=='blocked':where.append("json_extract(r.summary,'$.state')='blocked_data_contract'")
    if status=='pending':where.append(f"{state} IN ('pending','running')")
    if status=='failed':where.append(f"{state}='failed'")
    suffix=f" FROM universe u {join} WHERE "+' AND '.join(where)
    fields=f'''u.*, {state} item_state,{jobcol} job_id,
      json_extract(r.summary,'$.price') price,json_extract(r.summary,'$.change_pct') change_pct,
      json_extract(r.summary,'$.last_date') last_date,json_extract(r.summary,'$.mode') mode,
      json_extract(r.summary,'$.algorithm') algorithm,
      json_extract(r.summary,'$.state') analysis_state,json_extract(r.summary,'$.triggered') triggered,
      json_extract(r.summary,'$.active_candidates') active_candidates,
      json_extract(r.summary,'$.periods.day.last_segment.direction') direction,
      json_extract(r.summary,'$.periods.day.last_segment.state') segment_state,
      json_extract(r.summary,'$.periods.day.latest_center.zd') zd,
      json_extract(r.summary,'$.periods.day.latest_center.zg') zg'''
    with connect() as db:
        total=db.execute(prefix+'SELECT COUNT(*)'+suffix,params).fetchone()[0]
        rows=[dict(r) for r in db.execute(prefix+'SELECT '+fields+suffix+' ORDER BY u.symbol LIMIT ? OFFSET ?',params+[limit,offset])]
    return {'rows':rows,'total':total,'offset':offset,'limit':limit}


def overview():
    with connect() as db:
        total=db.execute('SELECT COUNT(*) FROM universe WHERE active=1').fetchone()[0]
        exchanges=dict(db.execute('SELECT exchange,COUNT(*) FROM universe WHERE active=1 GROUP BY exchange').fetchall())
        stats=dict(db.execute(PICK+'''SELECT COUNT(*) computed,
            SUM(CASE WHEN mode IN ('multi','full') THEN 1 ELSE 0 END) multi,
            SUM(CASE WHEN COALESCE(json_extract(summary,'$.triggered'),0)>0 THEN 1 ELSE 0 END) triggered,
            MIN(json_extract(summary,'$.last_date')) oldest_date,
            MAX(json_extract(summary,'$.last_date')) newest_date FROM chosen''').fetchone())
        jobs=[decode(r) for r in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 40')]
        active_symbols=[dict(r) for r in db.execute("SELECT job_id,symbol FROM items WHERE state='running' LIMIT 12")]
        from .progress import read_progress
        for job in jobs:
            first=db.execute("SELECT symbol,state FROM items WHERE job_id=? ORDER BY (state='success') DESC,symbol LIMIT 1",(job['id'],)).fetchone()
            job['result_symbol']=first['symbol'] if first else None
            job['progress']=[p for r in active_symbols if r['job_id']==job['id'] for p in [read_progress(job['id'],r['symbol'])] if p]
    return {'total':total,'exchanges':exchanges,'stats':stats,'jobs':jobs,'active_symbols':active_symbols,
            'now':now_iso(),'algorithm':APP_LABEL,'version':APP_VERSION,'execution_allowed':False,'service':'chanlun-workbench-v1',
            'universe_semantics':'当前股票池；不是包含全部退市股票的历史成分股库'}


def load_import_evidence(bundle):
    if bundle.get('imported_from') and 'evidence' not in bundle:
        original=(ROOT/'runs'/bundle['imported_from']).resolve()
        if not original.is_relative_to((ROOT/'runs').resolve()):raise ValueError('导入路径无效')
        reports={p:json.loads((original/'analysis'/f'{p}.json').read_text(encoding='utf-8')) for p in ('day','30m','5m') if (original/'analysis'/f'{p}.json').exists()}
        bundle['evidence']={'reports':reports,'imported_from':original.name}
        for filename,key in [('multiframe-default.json','default_contract'),('multiframe-explicit-volume-tolerance.json','multiframe'),('acquisition.json','source_receipts')]:
            if (original/filename).exists():
                value=json.loads((original/filename).read_text(encoding='utf-8'))
                bundle['evidence'][key]={k:v for k,v in value.items() if k!='levels'}
    return bundle


def saved_stock_bundle(path):
    from .saved_result_cache import get_or_build
    from .reference_service import rebuild_bundle,ADAPTER_VERSION
    from chanmodel.reference_engine import PROFILE,COMMIT,SETTINGS
    from chanmodel.regime_research import VERSION as RESEARCH_VERSION,RegimeConfig
    from dataclasses import asdict
    # The compressed content identity also detects repairs that preserve size
    # and file timestamps. Never key only by a symbol or the user's job name.
    contents=path.read_bytes()
    identity=json.dumps({'presentation':'saved-stock-snapshot-v2','adapter':ADAPTER_VERSION,'engine':PROFILE,
                         'commit':COMMIT,'settings':SETTINGS,'research':RESEARCH_VERSION,
                         'research_config':asdict(RegimeConfig())},
                        sort_keys=True,allow_nan=False,separators=(',',':'))
    key=(str(path),hashlib.sha256(contents).hexdigest(),identity)
    reusable=[True]
    built=[False]
    def build():
        built[0]=True
        from .full_compute import expand_legacy
        from .research_service import attach_bundle
        from chanmodel.signal_chart import attach_chart_annotations
        source_bundle=json.loads(gzip.decompress(contents))
        reusable[0]=not source_bundle.get('imported_from') and all(
            len(panel.get('bars',[]))==panel.get('input_bars',len(panel.get('bars',[])))
            for panel in source_bundle.get('chart',{}).get('panels',[]))
        bundle=expand_legacy(source_bundle)
        rebuild_bundle(bundle)
        attach_bundle(bundle)
        attach_chart_annotations(bundle['chart'],bundle.get('evidence',{}).get('multiframe'))
        return bundle
    # A legacy migration verifies external CSV/metadata or import receipts.
    # Keep that validation live rather than letting an unchanged artifact hide
    # a changed dependency. Fully saved candle bundles have no such dependency.
    bundle=get_or_build(key,build,retain=lambda:reusable[0])
    for panel in bundle.get('chart',{}).get('panels',[]):
        runtime=panel.get('regime_research',{}).get('runtime')
        if runtime is not None:
            runtime['snapshot_reused']=not built[0]
            if not built[0]:
                runtime['snapshot_built_new_closed_bars']=runtime.get('new_closed_bars',0)
                runtime.update(new_closed_bars=0,session_reused=False,history_rebuild_reason=None)
    return bundle


def stock(code, query):
    if not re.fullmatch(r'(sh|sz|bj)\d{6}',code):
        raise ValueError('股票代码格式错误')
    if query.get('local')==['1']:
        from .local_stock import request_local
        period=query.get('period',query.get('audit_period',['all']))[0]
        value=request_local(code,period,query.get('full')==['1'])
        if value.get('available') and query.get('period'):
            panel=next((p for p in value['chart']['panels'] if p['period']==period),None)
            if panel is None:raise ValueError('没有可用的所选周期本地历史')
            return {'available':True,'panel':panel,'summary':value['summary'],'chart':value['chart']}
        return value
    if query.get('live')==['1']:
        from .services import ensure_tdx
        from .live import live_stock
        ensure_tdx(timeout=8)
        return live_stock(code,query.get('period',query.get('audit_period',['day']))[0],query.get('full')==['1'])
    job=query.get('job',[''])[0]
    with connect() as db:
        if job:
            row=db.execute("SELECT artifact FROM items WHERE job_id=? AND symbol=? AND state='success'",(job,code)).fetchone()
        else:
            row=db.execute(PICK+'SELECT artifact FROM chosen WHERE symbol=?',(code,)).fetchone()
        record=db.execute('SELECT * FROM universe WHERE symbol=?',(code,)).fetchone()
    if not row or not row[0]:
        return {'available':False,'record':dict(record) if record else None}
    path=(STATE/row[0]).resolve()
    if not path.is_relative_to(STATE.resolve()):
        raise ValueError('无效结果路径')
    bundle=saved_stock_bundle(path)
    from .full_compute import history_view
    if query.get('period'):
        date=query.get('date',[None])[0]
        if date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):raise ValueError('日期必须为YYYY-MM-DD')
        return history_view(bundle,query['period'][0],date)
    if query.get('full')==['1']:
        load_import_evidence(bundle)
        return {'available':True,**bundle}
    bundle['chart']['panels']=[p for p in bundle['chart']['panels'] if p['period'] in ('day','30m','5m')]
    return {'available':True,'summary':bundle['summary'],'chart':bundle['chart']}


def accepts_gzip(value):
    choices={}
    for entry in value.lower().split(','):
        parts=[part.strip() for part in entry.split(';')]
        quality=1.0
        for parameter in parts[1:]:
            if parameter.startswith('q='):
                try:quality=float(parameter[2:])
                except ValueError:quality=0
        choices[parts[0]]=quality if 0<=quality<=1 else 0
    return choices.get('gzip',choices.get('*',0))>0


class Handler(BaseHTTPRequestHandler):
    server_version='ChanlunWorkbench/1.0'

    def log_message(self, format, *args):
        if len(args)>1 and str(args[1]) not in ('200','304'):
            super().log_message(format,*args)

    def send(self,value,status=200,content_type='application/json; charset=utf-8'):
        raw=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        varying=content_type.split(';',1)[0].strip().lower()=='application/json' and len(raw)>=65536
        compressed=False
        if varying and accepts_gzip(self.headers.get('Accept-Encoding','')):
            encoded=gzip.compress(raw,compresslevel=1,mtime=0)
            if len(encoded)<len(raw):raw=encoded;compressed=True
        try:
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if varying:self.send_header('Vary','Accept-Encoding')
            if compressed:self.send_header('Content-Encoding','gzip')
            self.end_headers()
            self.wfile.write(raw)
        except OSError:
            # Navigation can close the socket while a large chart is sent.
            # Sending a second HTTP 500 on that socket only causes another error.
            pass

    def local_request(self, mutation=False):
        host=self.headers.get('Host','')
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if host not in allowed:
            raise ValueError('只允许本机地址访问')
        if mutation and self.headers.get('Origin') not in (None,*['http://'+h for h in allowed]):
            raise ValueError('不接受跨站操作')

    def send_file(self,path):
        try:
            size=path.stat().st_size
            self.send_response(200);self.send_header('Content-Type','application/zip')
            self.send_header('Content-Length',str(size))
            self.send_header('Content-Disposition','attachment; filename="'+path.name+'"')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            with path.open('rb') as stream:
                while True:
                    block=stream.read(1024*1024)
                    if not block:break
                    self.wfile.write(block)
        except OSError:pass

    def do_GET(self):
        try:
            self.local_request()
            parsed=urlsplit(self.path);path=unquote(parsed.path);query=parse_qs(parsed.query)
            if path.startswith('/api/local-stock/status/'):
                from .local_stock import local_status
                value=local_status(path.rsplit('/',1)[1],query.get('full')==['1'])
                return self.send(value,202 if value.get('state')=='building' else 200)
            if path.startswith('/api/local-stock/'):
                from .local_stock import request_local
                value=request_local(path.rsplit('/',1)[1],query.get('period',['all'])[0],query.get('full')==['1'])
                return self.send(value,202 if value.get('state')=='building' else 200)
            if path=='/api/history/inventory':
                from .history_inventory_jobs import request_inventory
                value=request_inventory(query.get('period',['day'])[0],query.get('symbol',[None])[0],
                    int(query.get('offset',['0'])[0]),int(query.get('limit',['200'])[0]))
                return self.send(value,202 if value.get('state')=='building' else 200)
            if path.startswith('/api/history/inventory/status/'):
                from .history_inventory_jobs import status
                value=status(path.rsplit('/',1)[1])
                return self.send(value,202 if value.get('state')=='building' else 200)
            if path.startswith('/api/history/exports/'):
                from .history_export_jobs import status,download_path
                parts=path.split('/')
                if path.endswith('/download'):return self.send_file(download_path(parts[-2]))
                value=status(parts[-1]);return self.send(value,202 if value['state']=='building' else 200)
            if path=='/api/market-context':
                from .services import ensure_tdx
                from .market_context import market_context
                ensure_tdx()
                period=query.get('period',['day'])[0]
                if period not in {'day','30m','5m'}:raise ValueError('market context period must be day/30m/5m')
                return self.send(market_context(period,query.get('industries',['1'])!=['0']))
            if path=='/api/overview':return self.send(overview())
            if path=='/api/resources':
                from .resources import hardware_snapshot,plan_resources
                snapshot=hardware_snapshot(include_gpu=True)
                return self.send({'hardware':snapshot,'plans':{mode:plan_resources(mode,'auto',snapshot=snapshot,max_workers=32) for mode in ('day','multi','full','replay','native_backtest')},'gpu_compute_enabled':False,
                    'batch_indicator_adapter':{'backend':'cuda_driver_float64_macd_v1','endpoint':'/api/indicators/macd-batch',
                        'policy':'auto for compatible batches; CPU for small batches or unavailable CUDA',
                        'scope':'MACD indicators only; recursive structure rules remain CPU'}})
            if path=='/api/monitor':
                from .monitor import overview as monitor_overview
                return self.send(monitor_overview())
            if path=='/api/backtests':
                from .backtests import results
                return self.send(results())
            if path=='/api/backtests/coverage':
                from .backtests import coverage
                body={key:query[key][0] for key in ('cache','cutoff') if query.get(key)}
                return self.send(coverage(body))
            if path=='/api/backtests/errors':
                from .backtests import errors
                return self.send(errors(query.get('id',[''])[0],int(query.get('offset',['0'])[0]),int(query.get('limit',['20'])[0])))
            if path.startswith('/api/quote/'):
                code=path.rsplit('/',1)[1]
                if not re.fullmatch(r'(sh|sz|bj)\d{6}',code):raise ValueError('股票代码格式错误')
                from .services import ensure_tdx
                ensure_tdx()
                data,receipt,raw=TdxClient(timeout=15).quotes([code]);quotes,missing,extra=normalized_quotes(data,[code],receipt)
                if missing:raise ValueError('报价接口未返回指定股票')
                return self.send({'quote':quotes[0],'received_at':receipt['received_at'],'freshness':'获取时间不等于成交时间，休市时可能为最后交易日报价'})
            if path=='/api/stocks':return self.send(market(query))
            if path.startswith('/api/live-stock/'):
                from .services import ensure_tdx
                from .live import live_stock
                from .live_delivery import snapshot_response
                code=path.rsplit('/',1)[1]
                if not re.fullmatch(r'(sh|sz|bj)\d{6}',code):raise ValueError('股票代码格式错误')
                ensure_tdx(timeout=8)
                full=query.get('full')==['1']
                value=live_stock(code,query.get('period',['day'])[0],full,query.get('fresh')==['1'])
                return self.send(snapshot_response(value,query.get('known_snapshot',[None])[0],full=full))
            if path.startswith('/api/research-context/'):
                from .research_context import fund_flow
                return self.send(fund_flow(path.rsplit('/',1)[1],query.get('fresh')==['1']))
            if path.startswith('/api/stock/'):return self.send(stock(path.rsplit('/',1)[1],query))
            if path.startswith('/api/kline-csv/'):
                code=path.rsplit('/',1)[1];data=stock(code,query)
                if not data.get('available'):return self.send({'error':'当前股票没有可导出的K线'},404)
                panel=data.get('panel') or next((p for p in data['chart']['panels'] if p['period']==query.get('period',['day'])[0]),None)
                if not panel or panel.get('kind')=='line':raise ValueError('所选数据不是OHLC K线')
                stream=io.StringIO(newline='');fields=['closed_at','open','high','low','close','volume','is_closed','source_index']
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                for bar in panel['bars']:
                    row={key:bar.get(key) for key in fields};row['closed_at']=bar.get('closed_at') or datetime.fromisoformat(bar['date_cn']).replace(tzinfo=CN).isoformat()
                    row['is_closed']=str(bar.get('is_closed',True)).lower();writer.writerow(row)
                return self.send(stream.getvalue().encode('utf-8-sig'),content_type='text/csv; charset=utf-8')
            if path.startswith('/api/kline-audit/'):
                code=path.rsplit('/',1)[1];parameters={**query,'full':['1']};data=stock(code,parameters)
                if not data.get('available'):return self.send(data)
                from chanmodel.kline_audit import verify_source
                period=query.get('audit_period',['day'])[0]
                panel=next((p for p in data['chart']['panels'] if p['period']==period),None)
                if panel is None:raise ValueError('没有保存所选周期的K线')
                if query.get('live')==['1']:
                    from .live import audit_live_panel
                    return self.send(audit_live_panel(panel))
                receipt=data.get('evidence',{}).get('source_receipts',{}).get(period)
                result=verify_source(panel,receipt,code,ROOT,data['chart'].get('as_of',data['summary']['as_of']))
                result['anchor_corrections']=panel.get('anchor_corrections',[])
                return self.send(result)
            if path=='/api/health':
                from .store import DB
                from chanmodel.regime_research import VERSION as RESEARCH_VERSION
                return self.send({'service':'chanlun-workbench-v1','status':'ok','instance':hashlib.sha256(str(ROOT).encode()).hexdigest()[:16],'desktop':bool(getattr(sys,'frozen',False)),'version':APP_VERSION,'release':APP_LABEL,'research_version':RESEARCH_VERSION,'offline_start':os.environ.get('CHANLUN_START_OFFLINE')=='1','features':['signal_chart_v1','signal_all_levels_v1','marker_visibility_v2','pinned_reference_engine_review_v1','live_ohlcv_v1','incremental_reference_v1','market_context_v1','market_index_detail_v1','native_chan_backtest_v1','causal_regime_research_v1.1','tdx_content_addressed_binary_v1'],'pid':os.getpid(),'database':str(DB)})
            if path.startswith('/api/index-structure/'):
                from .market_context import index_structure
                code=unquote(path.rsplit('/',1)[1])
                return self.send(index_structure(code,query.get('period',['day'])[0]))
            if path=='/api/errors':
                with connect() as db:
                    rows=[dict(r) for r in db.execute("SELECT i.symbol,u.name,i.error FROM items i JOIN universe u USING(symbol) WHERE job_id=? AND i.state='failed' LIMIT 100",(query.get('job',[''])[0],))]
                return self.send({'rows':rows})
            static={'/':'index.html','/app.js':'app.js','/signal-chart.js':'signal-chart.js','/style.css':'style.css','/market-context.css':'market-context.css','/terminal-layout.css':'terminal-layout.css','/regime-research.js':'regime-research.js','/regime-research.css':'regime-research.css'}
            if path in static:
                f=WEB/static[path]
            elif path.startswith('/assets/') and path.split('/')[-1] in ('lightweight-charts.standalone.production.js','LICENSE','NOTICE','library-source.json') and path.count('/')==2:
                f=ASSETS/path.split('/')[-1]
            else:return self.send({'error':'页面不存在'},404)
            return self.send(f.read_bytes(),content_type=mimetypes.guess_type(str(f))[0] or 'application/octet-stream')
        except (ValueError,TypeError,KeyError) as exc:self.send({'error':str(exc)},400)
        except Exception as exc:self.send({'error':f'{type(exc).__name__}: {exc}'},500)

    def do_POST(self):
        try:
            self.local_request(True)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                raise ValueError('请求必须为JSON')
            size=int(self.headers.get('Content-Length','0'))
            max_size=4*1024*1024 if urlsplit(self.path).path=='/api/indicators/macd-batch' else 65536
            if not 0<size<=max_size:raise ValueError('请求大小无效')
            body=json.loads(self.rfile.read(size))
            if not isinstance(body,dict):raise ValueError('JSON必须是对象')
            path=urlsplit(self.path).path
            if path=='/api/history/exports':
                from .history_export_jobs import start
                return self.send(start(body),202)
            if path=='/api/indicators/macd-batch':
                from .hardware_indicators import compute,CudaUnavailable
                try:return self.send(compute(body))
                except CudaUnavailable as error:return self.send({'error':str(error)},503)
            if path=='/api/monitor/config':
                from .monitor import configure
                return self.send(configure(body))
            if path=='/api/monitor/scan':
                from .monitor import start_scan
                if body.get('kind','quotes') in {'quotes','both'}:
                    from .services import ensure_tdx
                    ensure_tdx()
                return self.send(start_scan(body.get('kind','quotes')),202)
            if path=='/api/monitor/acknowledge':
                from .monitor import acknowledge
                return self.send(acknowledge())
            if path=='/api/monitor/stop':
                from .monitor import stop_scan
                return self.send(stop_scan())
            if path=='/api/backtests/start':
                from .backtests import launch
                return self.send(launch(body),202)
            if path=='/api/backtests/stop':
                from .backtests import stop
                return self.send(stop(body.get('id','')))
            if path=='/api/backtests/resume':
                from .backtests import resume
                return self.send(resume(body.get('id','')))
            if path=='/api/jobs':
                if body.get('refresh') is True or body.get('mode')=='full':
                    from .services import ensure_tdx
                    ensure_tdx()
                return self.send(create_job(body),201)
            match=re.fullmatch(r'/api/jobs/([a-zA-Z0-9-]+)/(pause|resume|retry|cancel)',path)
            if match:return self.send(control_job(*match.groups()))
            if path=='/api/data-service':
                from .services import ensure_tdx
                return self.send(ensure_tdx(force=True))
            if path=='/api/universe/refresh':
                from .services import ensure_tdx
                ensure_tdx()
                data,receipt,raw=TdxClient(timeout=30).universe();records,coverage,exclusions=normalize_universe(data)
                if not coverage['complete_exchange_presence'] or not coverage.get('upstream_coverage',{}).get('complete',False):
                    raise ValueError('股票池覆盖未通过，保留之前的股票池')
                atomic_bytes(STATE/'universe-response.json.gz',gzip.compress(raw,mtime=0))
                with connect() as db:
                    # Keep earlier symbols so historical job references remain usable.
                    db.execute('UPDATE universe SET active=0')
                    db.executemany('INSERT INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,1) ON CONFLICT(symbol) DO UPDATE SET code=excluded.code,name=excluded.name,exchange=excluded.exchange,active=1',[(r['symbol'],r['code'],r['name'],r['exchange']) for r in records])
                    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('universe',json.dumps({'coverage':coverage,'receipt':receipt},ensure_ascii=False)))
                return self.send({'count':len(records),'coverage':coverage,'received_at':receipt['received_at']})
            return self.send({'error':'接口不存在'},404)
        except (ValueError,TypeError,KeyError) as exc:self.send({'error':str(exc)},400)
        except Exception as exc:self.send({'error':f'{type(exc).__name__}: {exc}'},500)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8791);args=parser.parse_args()
    seed()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    threading.Thread(target=scheduler,daemon=True).start()
    from .monitor import launch as launch_monitor
    launch_monitor()
    print(f'Chanlun workbench http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:STOP.set();server.server_close()


if __name__=='__main__':main()
