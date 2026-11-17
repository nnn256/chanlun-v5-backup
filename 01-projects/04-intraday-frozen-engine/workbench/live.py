"""Incremental live candles; confirmed structures append closed bars only."""
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
import copy
import gzip
import hashlib
import json
import pickle
import threading
import time

from chanmodel.kline_audit import audit_panel, candles_from_panel
from chanmodel.model import Candle
from chanmodel.tdx_data import CN, TdxClient, atomic_bytes, normalize_daily, symbol
from chanmodel.tdx_intraday import normalize_intraday
from chanmodel.v2.series import Series, session_closes
from .compute import local, make_chart
from .incremental import LiveSession, append_journal, get as get_session, save as save_session, quarantine
from .store import STATE, connect

PERIODS={'day':'day','30m':'minute30','5m':'minute5','1m':'minute1'}
TAIL_LIMIT=64
AUDIT_INTERVAL=7*86400
CACHE=OrderedDict();CACHE_LOCK=threading.RLock();KEY_LOCKS={}
PERIOD_FLIGHTS={}
LIVE_REQUEST_TIMEOUT=12
LIVE_REQUEST_ATTEMPTS=2


def _key_lock(key):
    with CACHE_LOCK:return KEY_LOCKS.setdefault(key,threading.RLock())


def _normalize(data,observed,period):
    if period=='day':return normalize_daily(data,observed)
    return normalize_intraday(data,observed,PERIODS[period])


def acquire(code,period,*,full=False):
    params={'code':code,'type':PERIODS[period]}
    if not full:params['limit']=TAIL_LIMIT
    data,receipt,raw=TdxClient(timeout=LIVE_REQUEST_TIMEOUT).request_retry(
        '/api/kline-all/tdx',params,attempts=LIVE_REQUEST_ATTEMPTS)
    observed=datetime.fromisoformat(receipt['requested_at'])
    closed,rows,quality=_normalize(data,observed,period)
    if not rows or not closed:raise ValueError(f'{code} {period}: 行情接口没有返回可用的真实K线')
    if period!='day':
        upcoming=next((p for p in session_closes(observed.date(),period) if p>observed),None)
        if any(not r['is_closed'] and (upcoming is None or datetime.fromisoformat(r['closed_at'])!=upcoming) for r in rows):
            raise ValueError('行情接口返回了尚未开始的分钟区间')
    source=STATE/'live'/code/period/(receipt['response_sha256']+'.json.gz')
    if not source.exists():atomic_bytes(source,gzip.compress(raw,compresslevel=3,mtime=0))
    receipt={**receipt,'raw_path':str(source.relative_to(STATE)),'quality':quality,
             'observed_at':observed.isoformat(),'period':period,
             'response_kind':'tdx_raw_ohlcv_'+('full_bootstrap' if full else 'bounded_tail')}
    return closed,rows,receipt


def _bar_signature(bar):
    return (bar.closed_at,bar.open,bar.high,bar.low,bar.close,bar.volume)


def _new_bar(row,pos,closed=True):
    return Candle(pos,*(row[k] for k in ('open','high','low','close')),row['closed_at'],row['volume'],closed)


def reconcile_closed_tail(session,closed):
    """Check provider overlap, append only new bars, or demand a full rebuild."""
    if not session.bars:return {'appended':0,'new_bars':(),'rebuild':'bootstrap','revision':None}
    indexed={bar.closed_at:bar for bar in session.bars}
    overlapping=[bar for bar in closed if bar.closed_at in indexed]
    changes=[{'time':bar.closed_at,'cached':_bar_signature(indexed[bar.closed_at]),
              'provider':_bar_signature(bar)} for bar in overlapping
             if _bar_signature(indexed[bar.closed_at])!=_bar_signature(bar)]
    if changes:return {'appended':0,'new_bars':(),'rebuild':'source_revision','revision':changes[:16]}
    newest=closed[-1].closed_at
    if newest<session.last_closed_at:raise ValueError('行情源落后于已保存闭合K线；保留现有确认结构并报告行情源延迟')
    if not overlapping and newest>session.last_closed_at:return {'appended':0,'new_bars':(),'rebuild':'bounded_tail_no_overlap','revision':None}
    appended=[]
    for bar in closed:
        if bar.closed_at<=session.last_closed_at:continue
        new_bar=_new_bar({'open':bar.open,'high':bar.high,'low':bar.low,'close':bar.close,
                          'closed_at':bar.closed_at,'volume':bar.volume},session.closed_count)
        session.append(new_bar);appended.append(new_bar)
    return {'appended':len(appended),'new_bars':tuple(appended),'rebuild':None,'revision':None}


def _ingest_one(code,period,force_full_audit=False):
    rejected=None
    try:live,session_reused=get_session(code,period)
    except (ValueError,pickle.UnpicklingError,EOFError,RecursionError,OverflowError) as exc:
        rejected=quarantine(code,period,f'{type(exc).__name__}: {exc}')
        live,session_reused=get_session(code,period)
    restored=getattr(live,'last_load_source','checkpoint' if session_reused else 'new')=='checkpoint'
    session=live.session
    closed,rows,receipt=acquire(code,period,full=not session_reused or not session.bars)
    revision=rejected;appended=0;rebuilt=False;new_bars=();audit_checked=False
    if not session.bars:
        session=type(session)(period,observe=True);live=LiveSession(session)
        for position,bar in enumerate(closed):
            session.append(_new_bar({'open':bar.open,'high':bar.high,'low':bar.low,'close':bar.close,
                                     'closed_at':bar.closed_at,'volume':bar.volume},position))
        appended=len(closed);rebuilt=True
    else:
        reconciliation=reconcile_closed_tail(session,closed)
        appended=reconciliation['appended']
        new_bars=reconciliation['new_bars']
        if reconciliation['rebuild']=='source_revision':
            revision={**(revision or {}),'source_revision_detected':True,'bars':reconciliation['revision'],'checked_rows':len(closed)}
            all_closed,all_rows,receipt=acquire(code,period,full=True)
            revision_count=live.revisions+1
            session=type(session)(period,observe=True);live=LiveSession(session,revisions=revision_count)
            for position,bar in enumerate(all_closed):
                session.append(_new_bar({'open':bar.open,'high':bar.high,'low':bar.low,'close':bar.close,
                                         'closed_at':bar.closed_at,'volume':bar.volume},position))
            closed,rows=all_closed,all_rows;appended=len(all_closed);rebuilt=True
        elif reconciliation['rebuild']=='bounded_tail_no_overlap':
            all_closed,all_rows,receipt=acquire(code,period,full=True)
            revision_count=live.revisions+1
            session=type(session)(period,observe=True);live=LiveSession(session,revisions=revision_count)
            for position,bar in enumerate(all_closed):
                session.append(_new_bar({'open':bar.open,'high':bar.high,'low':bar.low,'close':bar.close,
                                         'closed_at':bar.closed_at,'volume':bar.volume},position))
            closed,rows=all_closed,all_rows;appended=len(all_closed);rebuilt=True
            revision={**(revision or {}),'bounded_tail_no_overlap_rebuilt':True,'checked_rows':len(all_closed)}
    due_audit=force_full_audit or (time.time()-live.last_full_audit>=AUDIT_INTERVAL)
    if session_reused and not rebuilt and due_audit:
        all_closed,all_rows,full_receipt=acquire(code,period,full=True)
        current={b.closed_at:b for b in session.bars};provider={b.closed_at:b for b in all_closed}
        removed=sorted(set(current)-set(provider));added=sorted(set(provider)-set(current))
        changed=[stamp for stamp in set(current)&set(provider)
                 if _bar_signature(current[stamp])!=_bar_signature(provider[stamp])]
        audit_changes=removed+added+sorted(changed)
        if audit_changes:
            revision={**(revision or {}),'deep_history_revision_detected':True,
                      'bars':audit_changes[:32],'checked_rows':len(all_closed)}
            revision_count=live.revisions+1
            session=type(session)(period,observe=True);live=LiveSession(session,revisions=revision_count)
            for position,bar in enumerate(all_closed):
                session.append(_new_bar({'open':bar.open,'high':bar.high,'low':bar.low,'close':bar.close,
                                         'closed_at':bar.closed_at,'volume':bar.volume},position))
            closed,rows,receipt=all_closed,all_rows,full_receipt;appended=len(all_closed);rebuilt=True
        else:
            receipt={**receipt,'deep_audit_at':full_receipt['received_at'],'deep_audit_rows':len(all_closed)}
            audit_checked=True
        live.last_full_audit=time.time()
    elif rebuilt:live.last_full_audit=time.time()
    session_bars=tuple(session.bars)
    forming_rows=[r for r in rows if not r['is_closed']]
    display=session_bars+tuple(_new_bar(r,len(session_bars)+i,False) for i,r in enumerate(forming_rows))
    if not display:raise ValueError('no validated provider or cached K-line')
    input_hash=hashlib.sha256(json.dumps([_bar_signature(b) for b in session_bars],separators=(',',':')).encode()).hexdigest()
    if rebuilt or not session_reused or live.needs_migration:
        save_session(code,period,live)
    elif new_bars:
        try:
            compact=append_journal(code,period,live,new_bars)
        except OSError:
            save_session(code,period,live)
        else:
            if compact:save_session(code,period,live)
    elif audit_checked:
        save_session(code,period,live)
    meta={'restored':restored,'session_reused':session_reused,'resident':True,'appended':appended,'rebuilt':rebuilt,'total_closed':len(session_bars),
          'revision':revision,'checkpoint_sha256':input_hash,'deep_audit_at':getattr(live,'last_full_audit',time.time()),
          'checkpoint_journal_bars':live.journal_count,'checkpoint_migrated':live.needs_migration}
    return live,display,receipt,meta


def _ingest(code,period,force_full_audit=False):
    with _key_lock(('incremental-session',code,period)):
        live,display,receipt,meta=_ingest_one(code,period,force_full_audit)
        bars=live.session.bars
        if not bars:raise ValueError(f'{code} {period}: resident engine has no closed bars')
        input_hash=meta.get('checkpoint_sha256')
        if not input_hash:
            input_hash=hashlib.sha256(json.dumps([_bar_signature(bar) for bar in bars],
                separators=(',',':')).encode()).hexdigest()
        report=live.session.snapshot(code,bars[-1].closed_at,'tdx_live_ohlcv','unadjusted',input_hash)
        return live,display,receipt,{**meta,'report':report}


def _shared_ingest(code,period,endpoint):
    """Join overlapping day/all reads without retaining another engine cache."""
    key=(code,period,endpoint)
    with CACHE_LOCK:
        pending=PERIOD_FLIGHTS.get(key)
        owner=pending is None
        if owner:
            pending=Future();PERIOD_FLIGHTS[key]=pending
    if owner:
        try:
            pending.set_result(_ingest(code,period))
        except BaseException as exc:
            pending.set_exception(exc)
        finally:
            with CACHE_LOCK:
                if PERIOD_FLIGHTS.get(key) is pending:PERIOD_FLIGHTS.pop(key,None)
    resident,display,receipt,meta=pending.result()
    # Chart annotation mutates report dictionaries. Give each joined request
    # its own report while the immutable candles and resident engine stay shared.
    return resident,display,copy.deepcopy(receipt),copy.deepcopy(meta)


def _period_inputs(code,selected,endpoint,allow_partial):
    inputs={};receipts={};sessions={};errors={}
    with ThreadPoolExecutor(max_workers=len(selected),thread_name_prefix='live-period') as pool:
        pending={period:pool.submit(_shared_ingest,code,period,endpoint) for period in selected}
        for period in selected:
            try:session,display,receipt,meta=pending[period].result()
            except (ValueError,OSError,TimeoutError) as exc:
                if not allow_partial or period=='day':raise
                errors[period]=f'{type(exc).__name__}: {exc}'
                continue
            inputs[period]=Series(code,period,'unadjusted',tuple(display),
                'tdx_live_ohlcv',meta['checkpoint_sha256'])
            receipts[period]=receipt;sessions[period]={'session':session,**meta}
    return inputs,receipts,sessions,errors


def build_live(record,inputs,receipts,session_meta=None):
    session_meta=session_meta or {}
    if not session_meta:
        for period,series in inputs.items():
            session=LiveSession(__import__('chanmodel.reference_engine',fromlist=['ReferenceSession']).ReferenceSession(period))
            for bar in series.bars:
                if bar.closed:session.session.append(bar)
            session.saved_count=session.session.closed_count
            closed_hash=hashlib.sha256(json.dumps([_bar_signature(bar) for bar in session.session.bars],
                separators=(',',':')).encode()).hexdigest()
            report=session.session.snapshot(series.symbol,session.session.bars[-1].closed_at,
                series.source,series.adjustment,closed_hash)
            session_meta[period]={'session':session,'restored':False,'session_reused':False,'resident':True,'appended':session.saved_count,
                'rebuilt':True,'total_closed':session.saved_count,'revision':None,
                'checkpoint_sha256':closed_hash,'deep_audit_at':time.time(),'report':report}
    reports={}
    for period,series in inputs.items():
        live=session_meta[period]['session']
        report=session_meta[period].get('report')
        if report is None:
            closed=live.session.bars
            report=live.session.snapshot(series.symbol,closed[-1].closed_at,series.source,series.adjustment,
                                         session_meta[period]['checkpoint_sha256'])
        report['observation_mode']='incremental_fixed_engine_append'
        report['snapshot_semantics']='resident fixed engine; each new closed candle admitted once'
        reports[period]=report
    cutoff=max(r['observed_at'] for r in receipts.values())
    chart,summary=make_chart(record,inputs,reports,cutoff,include_forming=True)
    coverage=[]
    for panel in chart['panels']:
        period=panel['period'];receipt=receipts[period];meta=session_meta[period]
        bars=panel['bars'];closed=[bar for bar in bars if bar['is_closed']]
        forming=sum(not bar['is_closed'] for bar in bars);latest=bars[-1]['closed_at']
        panel.update(kline_audit=audit_panel(panel),observed_at=receipt['observed_at'],
            received_at=receipt['received_at'],confirmed_through=closed[-1]['closed_at'],latest_bar_at=latest,
            forming_count=forming,source_receipt=receipt,
            coverage={'source':'TDX实时原始OHLCV · 不复权','forming_count':forming},
            live_session={k:meta.get(k) for k in ('restored','session_reused','resident','appended','rebuilt','total_closed','revision',
                                                    'checkpoint_sha256','checkpoint_journal_bars','checkpoint_migrated')},
            note=('最新K线形成中 · 确认结构截止 ' if forming else '已收盘结构截止 ')+local(closed[-1]['closed_at']))
        coverage.append({'period':period,'count':len(bars),'first':bars[0]['date_cn'],'last':bars[-1]['date_cn'],
                         'source':'TDX实时原始OHLCV','forming_count':forming})
        summary['periods'][period].update(confirmed_through=local(closed[-1]['closed_at']),forming_count=forming)
    daily=next(panel for panel in chart['panels'] if panel['period']=='day');daily_meta=session_meta['day']
    meta={'mode':'live_incremental','received_at':receipts['day']['received_at'],'observed_at':receipts['day']['observed_at'],
          'latest_bar_at':daily['latest_bar_at'],'confirmed_through':daily['confirmed_through'],
          'forming':bool(daily['forming_count']),'latest_session_is_today':daily['latest_bar_at'][:10]==receipts['day']['observed_at'][:10],
          'freshness':'provider raw OHLCV; last-trade timestamp not exposed','source':'TDX原始OHLCV · 不复权',
          'refresh_seconds':15,'session_restored':daily_meta.get('restored',False),
          'session_reused':daily_meta.get('session_reused',False),'session_resident':daily_meta.get('resident',True),
          'new_closed_bars':daily_meta['appended'],
          'confirmed_history_bars':daily_meta['total_closed'],'engine_rebuilt':daily_meta['rebuilt'],
          'source_revision':daily_meta['revision'],'engine_profile':'pinned_native_incremental'}
    summary.update(live=meta,history_coverage=coverage,mode='live_incremental',
                   result_text='结构引擎已按闭合K线增量推进；形成中的K线仅用于图表展示')
    chart.update(live=meta,result_text=summary['result_text'],
                 snapshot_semantics='incremental pinned engine; forming OHLC excluded from confirmed signals')
    from .research_service import attach_research
    attach_research(daily,record['symbol'])
    return {'available':True,'summary':summary,'chart':chart,'evidence':{
        'source_receipts':receipts,'reference_reports':reports,
        'session':{p:{k:v for k,v in session_meta[p].items() if k not in {'session','report'}} for p in session_meta}}}


def audit_live_panel(panel):
    result=audit_panel(panel);receipt=panel['source_receipt'];path=(STATE/receipt['raw_path']).resolve()
    if not path.is_relative_to((STATE/'live').resolve()):raise ValueError('实时原始数据路径无效')
    raw=gzip.decompress(path.read_bytes())
    if hashlib.sha256(raw).hexdigest()!=receipt['response_sha256']:raise ValueError('实时原始响应SHA256不匹配')
    data=json.loads(raw)['data'];observed=datetime.fromisoformat(receipt['observed_at'])
    _,rows,_=_normalize(data,observed,panel['period']);expected={row['closed_at']:row for row in rows}
    displayed={bar.closed_at:bar for bar in candles_from_panel(panel)};overlaps=0
    for timestamp,row in expected.items():
        actual=displayed.get(timestamp)
        if actual is None:continue
        wanted=_new_bar(row,actual.pos,row['is_closed'])
        if _bar_signature(actual)!=_bar_signature(wanted) or actual.closed!=wanted.closed:
            raise ValueError('图表K线与保存的原始行情尾部不一致: '+timestamp)
        overlaps+=1
    if overlaps!=len(expected):raise ValueError('图表未完整包含校验所需的原始行情窗口')
    return {**result,'source_state':'matched','compared_rows':overlaps,'source_kind':'provider_raw_response',
            'source_csv_sha256':receipt['response_sha256'],'provider_response_state':'hash_verified_and_renormalized',
            'received_at':receipt['received_at'],'incremental_engine_bars':panel['live_session']['total_closed']}


def live_stock(code,period='day',full=False,fresh=False):
    code=symbol(code)
    if period not in {*PERIODS,'all'}:raise ValueError('实时结构支持日线、30分钟、5分钟、1分钟')
    selected=('day','30m','5m') if period=='all' else tuple(dict.fromkeys(('day',period)))
    endpoint=TdxClient().base_url;identity=(code,selected,endpoint);lock=_key_lock(identity)
    with lock:
        cached=CACHE.get(identity)
        if not fresh and cached and time.monotonic()-cached[0]<2:
            value=copy.deepcopy(cached[1])
        else:
            with connect() as db:row=db.execute('SELECT * FROM universe WHERE symbol=?',(code,)).fetchone()
            record=dict(row) if row else {'symbol':code,'code':code[2:],'name':code,'exchange':code[:2]}
            inputs,receipts,sessions,period_errors=_period_inputs(code,selected,endpoint,period=='all')
            if 'day' not in inputs:raise ValueError(f'{code}: 无可用日线结构')
            value=build_live(record,inputs,receipts,sessions)
            if period_errors:
                value['summary']['live']['period_errors']=period_errors
                value['summary']['result_text']+='；部分分钟周期不可用，已保留其他周期'
                value['chart']['live']=value['summary']['live']
                value['chart']['result_text']=value['summary']['result_text']
                value['chart']['period_errors']=period_errors
                value['evidence']['period_errors']=period_errors
            CACHE[identity]=(time.monotonic(),copy.deepcopy(value));CACHE.move_to_end(identity)
            while len(CACHE)>8:CACHE.popitem(last=False)
        if not full:value.pop('evidence',None)
        return value
