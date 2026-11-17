"""Local-only bridge from native minute candles to causal research alerts.

Historical warm-up is silent. Only new closed-bar evidence can enter monitor
notifications; per-session extrema are evaluation labels, never live inputs.
"""
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime
import copy
import hashlib
import json
import threading
import time

from chanmodel.intraday_research import IntradayConfig, IntradayResearchSession, PROFILE
from chanmodel.model import Candle
from chanmodel.tdx_data import CN,TdxClient


CACHE=OrderedDict()
LOCK=threading.RLock()
CACHE_LIMIT=16


def _signature(bar):
    return (bar.closed_at,bar.open,bar.high,bar.low,bar.close,bar.volume)


def _point(event,bars):
    signal={**event,'id':event['signal_id'],'signal_id':'intraday:'+event['id'],
            'native_signal_id':event['signal_id'],'source_signal_id':event['id'],
            'class':({'buy':'bottom_reversal','sell':'top_reversal'}[event['side']]),
            'label':'底部反转研究' if event['side']=='buy' else '顶部反转研究',
            'state':'structure_complete' if event['event']=='research_alert' else event['event'],
            'price':event['pivot_price'],'anchor_time':event['pivot_time'],
            'confirmed_time':event['available_time'],
            'age_bars':len(bars)-1-event['available_at'],'execution_allowed':False}
    return signal


def warm_from_cache(symbol,period,cache_root,config=None):
    """Seed both engines from a hash-checked native cache, without alerts."""
    from chanmodel.v2.io import load_cache_series
    from chanmodel.reference_engine import ReferenceSession
    from .incremental import LiveSession,save as save_session
    series,receipt=load_cache_series(cache_root,symbol,period)
    config=config or IntradayConfig()
    native=ReferenceSession(period,observe=True)
    study=IntradayResearchSession(symbol,period,config,source='tdx_native_live_ohlcv')
    closed=[b for b in series.bars if b.closed]
    for i,b in enumerate(closed):
        bar=Candle(i,b.open,b.high,b.low,b.close,b.closed_at,b.volume,True)
        native.append(bar);study.append(bar)
    resident=LiveSession(native,saved_count=len(closed),last_full_audit=time.time())
    save_session(symbol,period,resident)
    identity=(symbol,period,TdxClient().base_url,
              hashlib.sha256(json.dumps(asdict(config),sort_keys=True).encode()).hexdigest())
    with LOCK:
        CACHE[identity]={'signatures':[_signature(b) for b in closed],'study':study};CACHE.move_to_end(identity)
        while len(CACHE)>CACHE_LIMIT:CACHE.popitem(last=False)
    return {'symbol':symbol,'period':period,'bars':len(closed),'latest_closed_bar_at':closed[-1].closed_at if closed else None,
            'receipt':receipt,'native_warmup':True,'research_warmup':True,'notifications_sent':0,
            'execution_allowed':False}


def structure_one(record,settings,scan_started_at):
    from .live import _ingest
    from .monitor import session_state
    period=settings.get('intraday_period','5m')
    if period not in ('1m','5m'):raise ValueError('盘中研究周期只支持真实1分钟或5分钟K线')
    config=IntradayConfig(**settings.get('intraday_config',{}))
    session,display,receipt,meta=_ingest(record['symbol'],period,
                                       force_full_audit=settings.get('refresh_history',False))
    bars=tuple(b for b in display if b.closed)
    if not bars:raise ValueError('分时提醒没有可用的已闭合原生K线')
    identity=(record['symbol'],period,TdxClient().base_url,
              hashlib.sha256(json.dumps(asdict(config),sort_keys=True).encode()).hexdigest())
    signatures=[_signature(b) for b in bars]
    with LOCK:
        cached=CACHE.get(identity)
        prefix_ok=cached is not None and len(cached['signatures'])<=len(signatures) and cached['signatures']==signatures[:len(cached['signatures'])]
        initialized=not prefix_ok
        if initialized:
            study=IntradayResearchSession(record['symbol'],period,config,source='tdx_native_live_ohlcv')
            start=0
        else:
            study=cached['study'];start=len(cached['signatures'])
        added=[]
        for index in range(start,len(bars)):
            b=bars[index]
            added.extend(study.append(Candle(index,b.open,b.high,b.low,b.close,b.closed_at,b.volume,True)))
        snapshot=study.snapshot()
        CACHE[identity]={'signatures':signatures,'study':study};CACHE.move_to_end(identity)
        while len(CACHE)>CACHE_LIMIT:CACHE.popitem(last=False)
    # Receipt time is not an independently decoded exchange quote timestamp.
    # Check both calendar/session context and last closed-bar date before a
    # historical Friday event can be offered as Sunday's live alert.
    observed=datetime.fromisoformat(receipt['received_at']).astimezone(CN)
    last_closed=datetime.fromisoformat(bars[-1].closed_at).astimezone(CN)
    live_window=session_state(observed)['state']=='session_window' and observed.date()==last_closed.date()
    session_day=last_closed.date()
    def pivot_day(event):
        return datetime.fromisoformat(event['pivot_time']).astimezone(CN).date()
    session_active=[e for e in snapshot['active_signals'] if pivot_day(e)==session_day]
    historic_active=[e for e in snapshot['active_signals'] if pivot_day(e)!=session_day]
    points=[_point(e,bars) for e in session_active]
    for point in points:
        point['native_session']=session_day.isoformat()
        point['current_notification_evidence']=point['age_bars']<=2 and live_window and not initialized
        point['not_a_current_order']=True
    terminal=[_point(e,bars) for e in added if e['event'] in ('invalidated','withdrawn') and pivot_day(e)==session_day]
    current={p['signal_id']:p for p in points+terminal}
    return {**record,'state':'calculated','as_of':receipt['received_at'],'scan_started_at':scan_started_at,
            'data_as_of':{period:bars[-1].closed_at},'last_bar_at':{period:bars[-1].closed_at},
            'signals':list(current.values()),'data_pairs':{},
            'source_receipts':{period:receipt},'research_profile':PROFILE,'research_config':asdict(config),
            'research_events':copy.deepcopy(added),'research_warmup':initialized,
            'native_session':session_day.isoformat(),
            'historical_active_count':len(historic_active),
            'expired_signal_ids':['intraday:'+e['id'] for e in historic_active],
            'suppress_notifications':initialized or not live_window,
            'notification_suppression_reason':'historical_warmup_or_source_rebuild' if initialized else
                'outside_current_exchange_session_or_historical_source' if not live_window else None,
            'source_rebuilt':bool(meta.get('rebuilt')),'native_period':period,
            'latest_closed_bar_at':bars[-1].closed_at,
            'research_semantics':'local native structure reversal; not a guaranteed session high/low or multi-timeframe order',
            'execution_allowed':False}
