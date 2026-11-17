"""Build a single stock chart from saved histories without contacting a provider."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import threading

from chanmodel.model import time_value
from chanmodel.reference_engine import PROFILE,COMMIT,SETTINGS
from chanmodel.tdx_data import atomic_bytes,now_iso
from chanmodel.v2.io import load_series
from chanmodel.v2.series import Series
from .store import ROOT,STATE,connect

PERIODS={'day':'day','30m':'minute30','5m':'minute5','1m':'minute1'}
LOCK=threading.RLock()
POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='local-history-chart')
TASKS=OrderedDict()


def _file_hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def _safe(path):
    path=Path(path).resolve()
    if not path.is_relative_to(Path(ROOT).resolve()):raise ValueError('本地历史路径超出数据目录')
    return path


def _roots():
    rows=[Path(ROOT)/'market_data'];jobs=Path(ROOT)/'runtime/workbench/jobs'
    if jobs.is_dir():rows.extend(folder/'cache' for folder in sorted(jobs.iterdir()) if folder.is_dir())
    return [root for root in rows if (root/'tdx').is_dir() and _safe(root)]


def _candidate(root,code,period):
    folder=root/'tdx'/PERIODS[period]
    meta_path=folder/'metadata'/(code+'.json')
    csv_path=folder/'ohlcv'/(code+('.csv' if period=='day' else '.csv.gz'))
    if not meta_path.is_file() or not csv_path.is_file():return None
    meta_path=_safe(meta_path);csv_path=_safe(csv_path)
    if not 0<meta_path.stat().st_size<=1024*1024:raise ValueError('历史元数据过大或为空')
    meta_raw=meta_path.read_bytes();meta=json.loads(meta_raw)
    declared=meta.get('period',(meta.get('provider_meta') or {}).get('type','day'))
    if (meta.get('symbol')!=code or declared!=PERIODS[period] or meta.get('source')!='tdx' or
            meta.get('adjustment')!='unadjusted' or not re.fullmatch('[0-9a-fA-F]{64}',str(meta.get('csv_sha256','')))):
        raise ValueError('本地历史证券、周期或哈希声明不一致')
    rank=(str(meta.get('last_close') or meta.get('last_date') or ''),int(meta.get('closed_rows') or 0),
          str(meta.get('received_at') or ''),csv_path.stat().st_mtime_ns)
    return {'csv':csv_path,'metadata':meta_path,'meta':meta,'metadata_sha256':hashlib.sha256(meta_raw).hexdigest(),
        'rank':rank,'declared_csv_sha256':meta['csv_sha256'].lower(),
        'source_relative':meta_path.relative_to(Path(ROOT).resolve()).as_posix()}


def _sources(code,period):
    wanted=('day','30m','5m') if period=='all' else tuple(dict.fromkeys(('day',period)))
    roots=_roots();choices={};errors={}
    for selected in wanted:
        available=[]
        for root in roots:
            try:item=_candidate(root,code,selected)
            except (OSError,ValueError,TypeError) as exc:
                errors.setdefault(selected,[]).append(str(exc));continue
            if item:available.append(item)
        choices[selected]=sorted(available,key=lambda x:x['rank'],reverse=True)
        checkpoint=_safe(Path(STATE)/'live-sessions'/code/selected/'session.bin')
        if not available and checkpoint.is_file():
            wal=checkpoint.with_suffix('.wal')
            files=[checkpoint]+([wal] if wal.is_file() else [])
            fingerprint=[(str(p.relative_to(Path(ROOT).resolve())),p.stat().st_size,p.stat().st_mtime_ns,
                hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]
            choices[selected]=[{'kind':'checkpoint','checkpoint':checkpoint,'fingerprint':fingerprint}]
    return choices,errors


def _identity(code,period,choices):
    from .reference_service import ADAPTER_VERSION
    from chanmodel.regime_research import VERSION,RegimeConfig
    from dataclasses import asdict
    raw=json.dumps({'adapter':'local-cache-chart-v1','symbol':code,'period':period,'engine':PROFILE,'commit':COMMIT,
        'settings':SETTINGS,'reference_adapter':ADAPTER_VERSION,'research':VERSION,'research_config':asdict(RegimeConfig()),
        'sources':{p:[x['fingerprint'] if x.get('kind')=='checkpoint' else
            (x['source_relative'],x['declared_csv_sha256'],x['metadata_sha256'],
             _file_hash(x['csv'])) for x in rows] for p,rows in choices.items()}},
        sort_keys=True,allow_nan=False,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()


def _path(ident):return Path(STATE)/'local-stock'/f'{ident}.json.gz'


def _load(ident,full=False):
    value=json.loads(gzip.decompress(_path(ident).read_bytes()))
    if not full:value.pop('evidence',None)
    return value


def request_local(code,period='all',full=False):
    if not re.fullmatch(r'(sh|sz|bj)\d{6}',code):raise ValueError('股票代码格式错误')
    if period not in {*PERIODS,'all'}:raise ValueError('本地历史支持日线、30分钟、5分钟和1分钟')
    choices,errors=_sources(code,period)
    if not choices.get('day'):
        return {'available':False,'state':'unavailable','symbol':code,'period':period,
            'reason':'该股票没有通过身份预检的本地日线历史；可导入历史包或稍后下载行情','period_errors':errors}
    ident=_identity(code,period,choices)
    if _path(ident).is_file():return _load(ident,full)
    with LOCK:
        task=TASKS.get(ident)
        if task is None:
            TASKS[ident]={'state':'building','symbol':code,'period':period,'started_at':now_iso(),
                         'stage':'正在读取并校验本地历史'}
            POOL.submit(_build,ident,code,period,choices,errors)
            while len(TASKS)>64:
                finished=next((key for key,v in TASKS.items() if v['state']!='building'),None)
                if finished is None:break
                TASKS.pop(finished)
    return local_status(ident,full)


def local_status(ident,full=False):
    if not re.fullmatch('[0-9a-f]{64}',ident):raise ValueError('本地历史任务标识无效')
    if _path(ident).is_file():return _load(ident,full)
    with LOCK:task=dict(TASKS.get(ident) or {})
    if not task:raise ValueError('本地历史任务不存在')
    return {'available':False,**task,'id':ident,'status_url':'/api/local-stock/status/'+ident}


def _build(ident,code,period,choices,initial_errors):
    try:
        from .reference_service import reference_report
        from .compute import make_chart
        from .research_service import attach_bundle
        from chanmodel.kline_audit import audit_panel
        inputs={};receipts={};errors={k:list(v) for k,v in initial_errors.items()};selected={}
        for selected_period,options in choices.items():
            for option in options:
                try:
                    if option.get('kind')=='checkpoint':
                        from .incremental import get as saved_session
                        resident,restored=saved_session(code,selected_period)
                        closed=tuple(resident.session.bars)
                        if not closed or not restored:raise ValueError('没有通过身份校验的已保存结构会话')
                        digest=hashlib.sha256(json.dumps([[b.closed_at,b.open,b.high,b.low,b.close,b.volume]
                            for b in closed],separators=(',',':')).encode()).hexdigest()
                        inputs[selected_period]=Series(code,selected_period,'unadjusted',closed,
                            'authenticated_saved_session',digest)
                        relative=option['checkpoint'].relative_to(Path(ROOT).resolve()).as_posix()
                        receipts[selected_period]={'source_kind':'authenticated_saved_session','source_relative':relative,
                            'checkpoint_files':option['fingerprint'],'listing_inception_proven':False}
                        selected[selected_period]={'source_kind':'authenticated_saved_session',
                            'input_sha256':digest,'source_relative':relative,'closed_bars':len(closed),
                            'last_closed_at':closed[-1].closed_at,'saved_forming_rows_excluded':0}
                        break
                    series,receipt=load_series(option['csv'],code,selected_period,'unadjusted','tdx',option['metadata'])
                    previous=None
                    for bar in series.bars:
                        moment=time_value(bar.closed_at)
                        if previous is not None and moment<=previous:raise ValueError('本地历史时间重复或倒序')
                        previous=moment
                    closed=tuple(bar for bar in series.bars if bar.closed)
                    if not closed:raise ValueError('本地历史没有闭合K线')
                    # A saved forming candle remains available in its raw CSV;
                    # it is not presented as a current live observation here.
                    if any(b.pos!=i for i,b in enumerate(closed)):raise ValueError('本地历史闭合序列位置不连续')
                    inputs[selected_period]=Series(code,selected_period,series.adjustment,closed,series.source,series.input_sha256)
                    receipts[selected_period]={**receipt,'cache_metadata':{key:option['meta'].get(key)
                        for key in ('received_at','requested_at','as_of','first_date','last_date','first_close','last_close')},
                        'source_relative':option['source_relative']}
                    selected[selected_period]={'csv_sha256':receipt['csv_sha256'],
                        'file_sha256':receipt['file_sha256'],'metadata_sha256':option['metadata_sha256'],
                        'source_relative':option['source_relative'],'closed_bars':len(closed),
                        'last_closed_at':closed[-1].closed_at,'saved_forming_rows_excluded':len(series.bars)-len(closed)}
                    break
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    errors.setdefault(selected_period,[]).append(f'{type(exc).__name__}: {exc}')
            if selected_period not in inputs:errors.setdefault(selected_period,[]).append('没有可用的完整本地来源')
        if 'day' not in inputs:raise ValueError('本地日线内容校验未通过：'+'；'.join(errors.get('day',[])[:3]))
        cutoff=max(s.bars[-1].closed_at for s in inputs.values())
        with LOCK:TASKS[ident].update(stage='正在从本地历史生成结构图',progress_periods=list(inputs))
        reports={p:reference_report(code,p,list(s.bars),s.bars[-1].closed_at,s.adjustment,'verified_local_saved_ohlcv')
                 for p,s in inputs.items()}
        with connect() as db:row=db.execute('SELECT * FROM universe WHERE symbol=?',(code,)).fetchone()
        record=dict(row) if row else {'symbol':code,'code':code[2:],'name':code,'exchange':code[:2]}
        chart,summary=make_chart(record,inputs,reports,cutoff,include_forming=False)
        observed=now_iso()
        local={'state':'saved_history','network_used':False,'calculated_at':observed,
            'as_of':inputs['day'].bars[-1].closed_at,'sources':selected,
            'period_errors':{p:v for p,v in errors.items() if p not in inputs},
            'coverage':'saved native OHLC only; no current quote, missing sessions or listing inception proof'}
        summary.update(mode='local_cache',local_cache=local,result_text='本地历史快照 · 未联网获取当前行情')
        chart.update(local_cache=local,result_text=summary['result_text'],
            snapshot_semantics='verified local closed history; capture date is not current market time')
        for panel in chart['panels']:
            panel['kline_audit']=audit_panel(panel)
            panel['note']='本地已保存历史 · 截至 '+selected[panel['period']]['last_closed_at']
        result={'available':True,'state':'ready','summary':summary,'chart':chart,
                'evidence':{'reference_reports':reports,'source_receipts':receipts}}
        attach_bundle(result)
        atomic_bytes(_path(ident),gzip.compress(json.dumps(result,ensure_ascii=False,allow_nan=False,
            separators=(',',':')).encode(),compresslevel=3,mtime=0))
        with LOCK:TASKS[ident].update(state='ready',finished_at=observed,stage='本地历史图已生成')
    except Exception as exc:
        with LOCK:TASKS[ident].update(state='failed',stage='本地历史生成失败',reason=f'{type(exc).__name__}: {exc}')
