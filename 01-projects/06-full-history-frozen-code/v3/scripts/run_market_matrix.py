"""Durable local eleven-period stock snapshots over immutable source receipts.

The legacy F: intraday batch is read-only. This runner owns a different output,
lock, task ledger and STOP file. Snapshot mode computes the current closed-prefix
structure, not a first-available backtest. Replay is an explicit expensive mode.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import csv
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, ProxyHandler
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.model import Candle, time_value
from chanmodel.local_compute import OrderedLocalMap, memory_snapshot

CN=timezone(timedelta(hours=8))
PROFILE='liangce_v3_all_market_period_matrix_v1'
PERIODS=('1m','5m','15m','30m','60m','day','5d','week','month','quarter','year')
LEGACY=Path('F:/ChanlunAlgorithmTests/2026-11-15-all-market-intraday')
DEFAULT_OUTPUT=Path('F:/ChanlunAlgorithmTests/2026-11-17-liangce-v3-all-periods')
MAX_RESPONSE=32*1024**2
TERMINAL={'completed','insufficient'}


def now():return datetime.now(CN).isoformat(timespec='seconds')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def json_bytes(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def atomic(path,value,*,raw=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_bytes(value if raw else json_bytes(value));temporary.replace(path)
def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def pack(path,value):
    raw=gzip.compress(json_bytes(value),compresslevel=3,mtime=0);atomic(path,raw,raw=True)
    return sha(raw)
def normalized_digest(bars):return sha(json_bytes([[b.closed_at,b.open,b.high,b.low,b.close,b.volume,b.closed] for b in bars]))
def reindex(bars):return [replace(b,pos=i) for i,b in enumerate(bars)]


def source_manifest():
    paths=sorted(p for p in (ROOT/'chanmodel').rglob('*.py') if '__pycache__' not in p.parts)
    paths += [ROOT/'web/tdx_provider.py',ROOT/'web/precision_backtest.py',Path(__file__).resolve()]
    files={p.relative_to(ROOT).as_posix():file_sha(p) for p in paths}
    return {'sha256':sha(json_bytes(files)),'files':files}


def load_universe(path,limit=0):
    rows=read_json(path)
    if isinstance(rows,dict):rows=rows.get('symbols') or rows.get('universe')
    if not isinstance(rows,list) or not rows:raise ValueError('universe must contain stocks')
    found={}
    for item in rows:
        code=str(item.get('symbol','')).lower()
        if not re.fullmatch(r'(?:sh6\d{5}|sz(?:0\d{5}|30\d{4})|bj\d{6})',code):
            raise ValueError('explicit SH/SZ/BJ A-share code required: '+code)
        if code in found:raise ValueError('duplicate universe symbol '+code)
        found[code]={'symbol':code,'name':str(item.get('name',code)),'exchange':code[:2]}
    selected=[found[k] for k in sorted(found)]
    return selected[:limit] if limit else selected


def valid_minute(point,step):
    minute=point.hour*60+point.minute
    return point.weekday()<5 and not point.second and not point.microsecond and any(
        start<minute<=end and (minute-start)%step==0 for start,end in ((570,690),(780,900)))


def load_legacy_series(cache,symbol,period,cutoff):
    if period not in ('1m','5m'):raise ValueError('legacy cache only contains native 1m/5m')
    folder=Path(cache)/'tdx'/('minute1' if period=='1m' else 'minute5')
    meta_path=folder/'metadata'/(symbol+'.json');csv_path=folder/'ohlcv'/(symbol+'.csv.gz')
    if not meta_path.is_file() or not csv_path.is_file():raise FileNotFoundError('native cache missing '+symbol+'/'+period)
    metadata=read_json(meta_path);stored=csv_path.read_bytes()
    if metadata.get('csv_storage_sha256')!=sha(stored):raise ValueError('source compressed CSV hash mismatch')
    raw=gzip.decompress(stored)
    if metadata.get('csv_sha256')!=sha(raw):raise ValueError('source normalized CSV hash mismatch')
    if metadata.get('adjustment')!='unadjusted' or metadata.get('source')!='tdx':
        raise ValueError('native source units/adjustment not declared')
    result=[];seen={};step=1 if period=='1m' else 5
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
        point=datetime.fromisoformat(row['closed_at'].replace('Z','+00:00'))
        if point.tzinfo is None:raise ValueError('native cache timestamp has no timezone')
        point=point.astimezone(CN)
        if not valid_minute(point,step):raise ValueError('off-session native cached bar')
        bar=Candle(0,*[float(row[k]) for k in ('open','high','low','close')],point.isoformat(),float(row['volume']),
            row.get('is_closed','true').lower()=='true' and point<=cutoff)
        if min(bar.open,bar.high,bar.low,bar.close)<=0:raise ValueError('nonpositive cached OHLC')
        if point in seen and seen[point]!=replace(bar,pos=0):raise ValueError('conflicting duplicate native bar')
        seen[point]=bar
    for point,bar in sorted(seen.items()):
        if point<=cutoff:result.append(bar)
    result=reindex(result)
    receipt={'source':'read_only_legacy_tdx_native_cache','native_period':period,'adjustment':'unadjusted',
        'split_adjustment_verified':False,'listing_coverage_verified':False,'source_retention_unlimited':False,
        'source_files':{str(csv_path.resolve()):sha(stored),str(meta_path.resolve()):file_sha(meta_path)},
        'normalized_csv_sha256':sha(raw),'rows':len(result),'source_rows':metadata.get('raw_rows'),
        'coverage_claim':'all native rows actually retained at frozen cutoff; not listing-inception completeness',
        'first':result[0].closed_at if result else None,'last':result[-1].closed_at if result else None}
    return result,receipt


def aggregate_intraday(bars,period,cutoff):
    """Aggregate complete 5m groups on separate morning/afternoon close grids."""
    step=int(period[:-1])
    if step not in (15,30,60):raise ValueError('aggregation requires 15m/30m/60m')
    groups=defaultdict(list)
    for bar in bars:
        p=datetime.fromisoformat(bar.closed_at).astimezone(CN)
        if not valid_minute(p,5):raise ValueError('5m input has an invalid close grid')
        minute=p.hour*60+p.minute;start=570 if minute<=690 else 780
        end=start+((minute-start-1)//step+1)*step
        groups[(p.date(),start,end)].append(bar)
    result=[];incomplete=[]
    for (day,start,end),items in sorted(groups.items()):
        points={datetime.fromisoformat(b.closed_at).astimezone(CN).hour*60+datetime.fromisoformat(b.closed_at).astimezone(CN).minute for b in items}
        expected=set(range(end-step+5,end+1,5));stamp=datetime.combine(day,datetime.min.time(),CN)+timedelta(minutes=end)
        complete=points==expected and len(items)==len(expected) and all(b.closed for b in items) and stamp<=cutoff
        result.append(Candle(len(result),items[0].open,max(b.high for b in items),min(b.low for b in items),items[-1].close,
            stamp.isoformat(),sum(b.volume or 0 for b in items),complete))
        if not complete:incomplete.append({'close':stamp.isoformat(),'observed_components':len(items),'expected_components':len(expected)})
    return result,{'aggregation':'exchange_session_aligned_from_frozen_native_5m','component_period':'5m',
        'source_grid_minutes':5,'incomplete_groups':incomplete,'incomplete_group_count':len(incomplete),
        'missing_components_padded':False,'native_target_history_claim':False}


def validate_origin(origin):
    parsed=urlparse(origin)
    if parsed.scheme not in ('http','https') or parsed.hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('matrix acquisition requires the explicit local TDX interface')
    return origin.rstrip('/')


def daily_series(output,symbol,cutoff,origin,acquire):
    """Acquire once then replay the same immutable daily response for all derivatives."""
    from web import tdx_provider as tdx
    folder=Path(output)/'sources/day';reference=folder/(symbol+'.json')
    if reference.is_file():
        receipt=read_json(reference);raw_path=Path(receipt['raw_path'])
        raw=gzip.decompress(raw_path.read_bytes())
        if sha(raw)!=receipt['raw_sha256']:raise ValueError('daily raw source hash mismatch')
    else:
        if not acquire:raise FileNotFoundError('daily source not collected; use --acquire-daily')
        origin=validate_origin(origin);url=origin+'/api/kline-all/tdx?'+urlencode({'code':symbol,'type':'day'})
        requested=now();opener=build_opener(ProxyHandler({}))
        with opener.open(Request(url,headers={'Accept':'application/json','User-Agent':'LiangceMatrix/1'}),timeout=90) as response:
            raw=response.read(MAX_RESPONSE+1)
            if len(raw)>MAX_RESPONSE:raise ValueError('daily source exceeds response bound')
        envelope=json.loads(raw)
        if not isinstance(envelope,dict) or envelope.get('code')!=0:raise ValueError('daily source envelope rejected')
        raw_path=folder/'raw'/(sha(raw)+'.json.gz')
        atomic(raw_path,gzip.compress(raw,compresslevel=3,mtime=0),raw=True)
        receipt={'symbol':symbol,'url':url,'requested_at':requested,'received_at':now(),
            'raw_sha256':sha(raw),'raw_path':str(raw_path.resolve()),'response_bytes':len(raw)}
        atomic(reference,receipt)
    envelope=json.loads(raw)
    if envelope.get('code')!=0 or not isinstance(envelope.get('data'),dict):raise ValueError('daily source envelope invalid')
    candles,metadata=tdx.normalize_rest(envelope['data'],'day',datetime.now(CN))
    candles=[replace(b,closed=True) for b in candles if time_value(b.closed_at)<=cutoff]
    candles,metadata=tdx.split_adjust(symbol,reindex(candles),metadata)
    metadata.update(receipt,source_files={str(reference.resolve()):file_sha(reference),str(raw_path.resolve()):file_sha(raw_path)},
        listing_coverage_verified=False,source_retention_unlimited=False,
        adjustment_limitation='only explicitly cross-verified corporate actions are adjusted; others remain unadjusted',
        coverage_claim='all retained provider daily rows at cutoff; listing inception not certified')
    return candles,metadata


def aggregate_daily(bars,period,cutoff,metadata):
    from web import tdx_provider as tdx
    if period=='5d':
        values=tdx.five_day_bars(bars)
        return values,{'aggregation':'five_source_contiguous_trading_sessions',
            'five_day_anchor':'listing_start' if metadata.get('listing_coverage_verified') else 'first_retained_source_day',
            'listing_anchor_verified':metadata.get('listing_coverage_verified') is True,
            'source_anchored_5d':metadata.get('listing_coverage_verified') is not True,
            'incomplete_group_count':sum(not b.closed for b in values)}
    if period not in ('week','month','quarter','year'):raise ValueError('unknown daily aggregation')
    values=tdx.calendar_bars(bars,period,cutoff)
    # The first retained source day may be in the middle of its calendar bucket.
    # Its envelope is kept for coverage/preview but cannot confirm structure.
    if values and not metadata.get('listing_coverage_verified'):
        values[0]=replace(values[0],closed=False)
    return values,{'aggregation':'calendar_'+period+'_from_same_frozen_adjustment_daily',
        'initial_calendar_bucket_coverage_verified':False if values else None,
        'initial_partial_bucket_excluded':bool(values and not metadata.get('listing_coverage_verified')),
        'incomplete_group_count':sum(not b.closed for b in values),
        'calendar_endpoint_policy':'weekday calendar endpoint; no invented exchange holiday session'}


def terminal_extremes(bars):
    tail=bars[-20:]
    if not tail:return None
    low=min(tail,key=lambda b:(b.low,b.pos));high=max(tail,key=lambda b:(b.high,-b.pos))
    return {'scope':'current_closed_snapshot_only','window_bars':len(tail),'observed_low':low.low,
        'observed_low_index':low.pos,'observed_high':high.high,'observed_high_index':high.pos,
        'as_of':tail[-1].closed_at,'future_extreme_known':False,'prediction':False}


def compute_snapshot(symbol,period,bars,metadata,mode='snapshot',replay_periods=(),resolution='stroke'):
    from chanmodel.complete_study import analyze_complete
    from chanmodel.stroke_signals import snapshot as stroke_snapshot
    from chanmodel.market_phase import MarketPhaseSession
    closed=reindex([b for b in bars if b.closed]);digest=normalized_digest(closed)
    result={'symbol':symbol,'period':period,'mode':mode,'input_sha256':digest,
        'coverage':{**metadata,'source_rows':len(bars),'closed_rows':len(closed),
            'incomplete_or_forming_rows':sum(not b.closed for b in bars),
            'first':closed[0].closed_at if closed else None,'last':closed[-1].closed_at if closed else None},
        'forming_or_incomplete_tail':[asdict(b) for b in bars if not b.closed][-8:],
        'terminal_extremes':terminal_extremes(closed),'execution_allowed':False,
        'historical_first_confirmation_verified':False,'snapshot_is_prefix_backtest':False}
    if len(closed)<3:
        result.update(state='insufficient',reason='fewer_than_three_closed_bars',structure=None,stroke_model=None)
        return result
    result.update(state='completed',structure=analyze_complete(symbol,period,closed,closed[-1].closed_at,digest),
        stroke_model=stroke_snapshot(closed))
    if period=='day':
        phase=MarketPhaseSession(symbol)
        for bar in closed:phase.append(bar)
        result['market_phase']=phase.snapshot()
    if mode=='replay' and period in replay_periods:
        from web.precision_backtest import prefix_events
        result['replay']=prefix_events(closed,period,resolution)
        result['historical_first_confirmation_verified']=True
        result['replay_scope']='causal signal ledger only; no portfolio fills or guaranteed original equivalence'
    return result


def db_connect(output):
    db=sqlite3.connect(Path(output)/'tasks.sqlite3',timeout=30);db.row_factory=sqlite3.Row
    db.execute('PRAGMA busy_timeout=30000');return db


def set_task(output,symbol,period,state,**fields):
    allowed={'artifact','artifact_sha256','receipt','error','bars','updated_at','source_kind'}
    if set(fields)-allowed:raise ValueError('invalid task fields')
    fields.update(state=state,updated_at=now())
    with db_connect(output) as db:
        db.execute('UPDATE tasks SET '+','.join(k+'=?' for k in fields)+' WHERE symbol=? AND period=?',
            (*[json.dumps(v,ensure_ascii=False) if k=='receipt' else v for k,v in fields.items()],symbol,period))


def process_symbol(task):
    output=Path(task['output']);symbol=task['symbol'];cutoff=datetime.fromisoformat(task['cutoff']).astimezone(CN)
    results=[];sources={}
    for period in task['periods']:
        if (output/'STOP').exists():break
        if shutil.disk_usage(output).free<task['min_free_gb']*1024**3:
            set_task(output,symbol,period,'resource_wait',error='minimum free disk reserve reached');continue
        mem=memory_snapshot().get('available_bytes')
        if mem is not None and mem<task['min_free_memory_mib']*1024**2:
            set_task(output,symbol,period,'resource_wait',error='minimum desktop RAM reserve reached');continue
        set_task(output,symbol,period,'processing',error=None)
        try:
            native=period if period in ('1m','5m') else '5m' if period in ('15m','30m','60m') else 'day'
            if native not in sources:
                sources[native]=(daily_series(output,symbol,cutoff,task['origin'],task['acquire_daily']) if native=='day'
                    else load_legacy_series(task['source_cache'],symbol,native,cutoff))
            bars,receipt=sources[native];metadata=dict(receipt)
            if period in ('15m','30m','60m'):
                bars,aggregation=aggregate_intraday(bars,period,cutoff);metadata.update(aggregation)
            elif period in ('5d','week','month','quarter','year'):
                bars,aggregation=aggregate_daily(bars,period,cutoff,metadata);metadata.update(aggregation)
            report=compute_snapshot(symbol,period,bars,metadata,task['mode'],task['replay_periods'],task['resolution'])
            path=output/'snapshots'/symbol/(period+'.json.gz');artifact_sha=pack(path,report)
            summary={'symbol':symbol,'period':period,'state':report['state'],'bars':report['coverage']['closed_rows'],
                'input_sha256':report['input_sha256'],'source_files':metadata['source_files'],
                'source_kind':metadata.get('aggregation',metadata.get('source')),
                'incomplete_rows':report['coverage']['incomplete_or_forming_rows'],
                'artifact':str(path.resolve()),'artifact_sha256':artifact_sha,'snapshot_is_prefix_backtest':False,
                'execution_allowed':False}
            atomic(output/'receipts'/symbol/(period+'.json'),summary)
            set_task(output,symbol,period,summary['state'],artifact=summary['artifact'],artifact_sha256=artifact_sha,
                receipt=summary,bars=summary['bars'],source_kind=summary['source_kind'])
            results.append(summary)
        except FileNotFoundError as exc:
            set_task(output,symbol,period,'source_pending',error=str(exc)[:400]);results.append({'symbol':symbol,'period':period,'state':'source_pending'})
        except Exception as exc:
            set_task(output,symbol,period,'failed',error=type(exc).__name__+': '+str(exc)[:380]);results.append({'symbol':symbol,'period':period,'state':'failed'})
    return {'symbol':symbol,'period_results':results}


def initialize(output,universe,periods):
    with db_connect(output) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('''CREATE TABLE IF NOT EXISTS tasks(symbol TEXT,exchange TEXT,period TEXT,state TEXT,
            updated_at TEXT,error TEXT,bars INTEGER,source_kind TEXT,artifact TEXT,artifact_sha256 TEXT,receipt TEXT,
            PRIMARY KEY(symbol,period))''')
        db.executemany('INSERT OR IGNORE INTO tasks(symbol,exchange,period,state,updated_at) VALUES(?,?,?,?,?)',
            ((r['symbol'],r['exchange'],p,'source_pending',now()) for r in universe for p in periods))


def verify_completed(output):
    """A resume never treats stale/corrupt source or result bytes as completed."""
    checked={};invalid=[]
    with db_connect(output) as db:
        records=db.execute("SELECT * FROM tasks WHERE state IN ('completed','insufficient')").fetchall()
    for row in records:
        try:
            if file_sha(row['artifact'])!=row['artifact_sha256']:raise ValueError('artifact changed')
            receipt=json.loads(row['receipt'])
            for path,expected in receipt['source_files'].items():
                if path not in checked:checked[path]=file_sha(path)
                if checked[path]!=expected:raise ValueError('source changed: '+path)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            invalid.append((row['symbol'],row['period'],str(exc)))
    for symbol,period,error in invalid:set_task(output,symbol,period,'failed',error='resume integrity rejection: '+error)
    return {'checked_completed':len(records),'invalidated':len(invalid),'unique_source_files_hashed':len(checked)}


def status(output,run_state=None,resources=None):
    output=Path(output);manifest=read_json(output/'manifest.json')
    with db_connect(output) as db:
        counts=dict(db.execute('SELECT state,COUNT(*) FROM tasks GROUP BY state').fetchall())
        periods=[dict(r) for r in db.execute('SELECT period,state,COUNT(*) tasks,COALESCE(SUM(bars),0) bars FROM tasks GROUP BY period,state ORDER BY period,state')]
        markets=[dict(r) for r in db.execute('SELECT exchange,state,COUNT(*) tasks FROM tasks GROUP BY exchange,state ORDER BY exchange,state')]
        active=[dict(r) for r in db.execute("SELECT symbol,period,updated_at FROM tasks WHERE state='processing' LIMIT 20")]
        failures=[dict(r) for r in db.execute("SELECT symbol,period,error FROM tasks WHERE state='failed' LIMIT 20")]
        bars=db.execute('SELECT COALESCE(SUM(bars),0) FROM tasks').fetchone()[0]
    completed=counts.get('completed',0)+counts.get('insufficient',0);total=sum(counts.values())
    value={'profile':PROFILE,'updated_at':now(),'state':run_state or ('completed' if completed==total else 'pending'),
        'mode':manifest['mode'],'cutoff':manifest['cutoff'],'securities':len(manifest['universe']),
        'requested':total,'periods':manifest['periods'],'counts':counts,'by_period':periods,'by_market':markets,
        'completed_or_insufficient':completed,'successful_coverage_complete':counts.get('completed',0)==total,
        'processing_complete':completed==total,'closed_bars_across_periods':bars,'active':active,'failed_records':failures,
        'output':str(output.resolve()),'source_manifest_sha256':manifest['code']['sha256'],
        'resources':resources,'free_disk_bytes':shutil.disk_usage(output).free,'memory':memory_snapshot(),
        'scope':'current frozen SH/SZ/BJ A shares; finite retained sources; computed snapshots are not causal backtests',
        'execution_allowed':False,'uploaded':False}
    atomic(output/'summary.json',value);return value


def _alive(pid):
    if os.name=='nt':
        import ctypes
        api=ctypes.windll.kernel32;api.OpenProcess.restype=ctypes.c_void_p
        h=api.OpenProcess(0x1000,False,pid)
        if not h:return False
        try:
            code=ctypes.c_ulong();return bool(api.GetExitCodeProcess(ctypes.c_void_p(h),ctypes.byref(code))) and code.value==259
        finally:api.CloseHandle(ctypes.c_void_p(h))
    try:os.kill(pid,0);return True
    except OSError:return False


def run(args):
    output=args.output.resolve();cache=args.source_cache.resolve()
    # The foreign batch owns its manifest, database and STOP. Never nest here.
    foreign_root=cache.parent.parent
    if (foreign_root/'analysis/tasks.sqlite3').exists() and output.is_relative_to(foreign_root):
        raise ValueError('new matrix output must be outside the active legacy batch')
    output.mkdir(parents=True,exist_ok=True)
    if args.status:return status(output)
    cutoff=datetime.fromisoformat(args.cutoff.replace('Z','+00:00'))
    if cutoff.tzinfo is None:raise ValueError('cutoff requires timezone')
    universe=load_universe(args.universe,args.limit);periods=[p for p in PERIODS if p in args.periods]
    if len(periods)!=len(set(args.periods)):raise ValueError('unknown/duplicate periods')
    if args.mode=='replay' and any(p not in periods for p in args.replay_periods):raise ValueError('replay periods must be in matrix')
    origin=validate_origin(args.origin)
    code=source_manifest()
    manifest={'profile':PROFILE,'mode':args.mode,'universe':universe,'periods':periods,'cutoff':cutoff.astimezone(CN).isoformat(),
        'universe_file_sha256':file_sha(args.universe),'source_cache':str(cache),'code':code,
        'replay_periods':args.replay_periods if args.mode=='replay' else [],'replay_resolution':args.resolution,
        'source_policy':'legacy 1m/5m read-only; higher minutes aggregate5m; daily response frozen then consistent daily derivatives',
        'listing_coverage_verified':False,'origin':origin,'execution_allowed':False,'uploaded':False}
    manifest_path=output/'manifest.json';lock=output/'runner.lock'
    if lock.exists():
        try:owner=read_json(lock)
        except (OSError,ValueError):raise ValueError('matrix lock unreadable; inspect before resuming')
        if _alive(int(owner['pid'])):raise ValueError('matrix runner already active')
        lock.unlink()
    descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(descriptor,json_bytes({'pid':os.getpid(),'created_at':now()}));os.close(descriptor)
    try:
        if manifest_path.exists():
            if not args.resume:raise ValueError('existing matrix requires --resume')
            if read_json(manifest_path)!=manifest:raise ValueError('resume manifest/source code/universe/cutoff differs; use a new output')
        else:
            if args.resume:raise ValueError('--resume needs an existing manifest')
            atomic(manifest_path,manifest)
        initialize(output,universe,periods)
        verification=verify_completed(output) if args.resume else None
        with db_connect(output) as db:
            db.execute("UPDATE tasks SET state='source_pending',error='prior owner interrupted' WHERE state='processing'")
            states=('source_pending','resource_wait','failed') if args.retry_failed else ('source_pending','resource_wait')
            pending=db.execute('SELECT symbol,period FROM tasks WHERE state IN ('+','.join('?' for _ in states)+') ORDER BY symbol,period',states).fetchall()
        grouped=defaultdict(list)
        for row in pending:grouped[row['symbol']].append(row['period'])
        tasks=[{'symbol':symbol,'periods':[p for p in periods if p in wanted],'cutoff':manifest['cutoff'],
            'source_cache':str(cache),'output':str(output),'origin':origin,'acquire_daily':args.acquire_daily,
            'mode':args.mode,'replay_periods':manifest['replay_periods'],'resolution':args.resolution,
            'min_free_gb':args.min_free_gb,'min_free_memory_mib':args.min_free_memory_mib} for symbol,wanted in sorted(grouped.items())]
        mapper=OrderedLocalMap(process_symbol,tasks,workers=args.workers,worker_mib=args.worker_mib,reserve_mib=args.reserve_mib)
        resources={'plan':mapper.plan,'stats':mapper.stats,'resume_verification':verification}
        status(output,'running',resources);last=0
        for number,result in enumerate(mapper,1):
            if time.monotonic()-last>5 or number==len(tasks):
                current=status(output,'running',resources);print(json.dumps({k:current[k] for k in ('updated_at','state','requested','counts','closed_bars_across_periods')},ensure_ascii=False),flush=True);last=time.monotonic()
            if (output/'STOP').exists():break
        if source_manifest()!=code:raise ValueError('source code changed during batch; result summary rejected')
        current=status(output,'stopped' if (output/'STOP').exists() else 'pending',resources)
        if current['processing_complete']:current=status(output,'completed',resources)
        elif current['counts'].get('resource_wait'):current=status(output,'waiting_resources',resources)
        return current
    finally:
        if lock.exists():lock.unlink()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe',type=Path,default=LEGACY/'source-universe/universe.json')
    parser.add_argument('--source-cache',type=Path,default=LEGACY/'acquisition/market_data')
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--cutoff',default='2026-11-13T15:00:00+08:00')
    parser.add_argument('--periods',nargs='+',default=list(PERIODS))
    parser.add_argument('--mode',choices=('snapshot','replay'),default='snapshot')
    parser.add_argument('--replay-periods',nargs='+',default=['day'])
    parser.add_argument('--resolution',choices=('stroke','segment'),default='stroke')
    parser.add_argument('--origin',default=os.environ.get('LIANGCE_TDX_API','http://127.0.0.1:18080'))
    parser.add_argument('--acquire-daily',action='store_true')
    parser.add_argument('--workers',default='auto');parser.add_argument('--worker-mib',type=int,default=512)
    parser.add_argument('--reserve-mib',type=int,default=1024)
    parser.add_argument('--min-free-memory-mib',type=int,default=512)
    parser.add_argument('--min-free-gb',type=float,default=10)
    parser.add_argument('--resume',action='store_true');parser.add_argument('--retry-failed',action='store_true')
    parser.add_argument('--status',action='store_true');parser.add_argument('--limit',type=int,default=0)
    args=parser.parse_args(argv)
    if args.limit<0 or args.min_free_gb<1 or args.min_free_memory_mib<256:raise ValueError('invalid resource bounds')
    result=run(args);print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['processing_complete'] else 3


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);raise SystemExit(1)
