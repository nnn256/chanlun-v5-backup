"""Persistent market scans, state transitions and local research alerts."""
from concurrent.futures import ThreadPoolExecutor,as_completed,wait,FIRST_COMPLETED
from datetime import datetime,time as day_time
import gzip
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import uuid

from chanmodel.tdx_data import TdxClient,normalized_quotes,normalize_universe,normalize_daily,cache_history,atomic_bytes,atomic_json,now_iso,CN
from chanmodel.v2.io import load_cache_series
from chanmodel.unified import analyze_all
from chanmodel.v2.divergence import invalidated_by
from .store import ROOT,STATE,connect

DEFAULT={'enabled':False,'scope':'all','symbols':[],'quote_interval':60,'structure_interval':300,
         'structure_mode':'day','refresh_history':False,'workers':4,'volume_tolerance':1,'desktop_notifications':False,
         'intraday_period':'5m','intraday_config':{}}
LOCK=threading.Lock();STOP=threading.Event();CANCEL=threading.Event();BUSY=False;THREAD=None


def _instant(value):
    """Require comparable observation instants; a receipt is not a trade time."""
    if not isinstance(value,str):return None
    try:point=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:return None
    return point if point.tzinfo is not None else None


def config():
    with connect() as db:row=db.execute("SELECT value FROM metadata WHERE key='monitor_config'").fetchone()
    return {**DEFAULT,**(json.loads(row[0]) if row else {})}


def configure(values):
    settings={**config(),**values}
    for key in ['enabled','refresh_history','desktop_notifications']:
        if type(settings[key]) is not bool:raise ValueError(key+' must be boolean')
    for key,minimum,maximum in [('quote_interval',15,3600),('structure_interval',60,86400),('workers',1,8)]:
        if type(settings[key]) is not int or not minimum<=settings[key]<=maximum:raise ValueError(key+' is outside allowed range')
    if settings['scope'] not in {'all','selected'} or settings['structure_mode'] not in {'day','multi','intraday'}:raise ValueError('unknown scope/mode')
    if settings['intraday_period'] not in ('1m','5m'):raise ValueError('intraday period must be 1m or 5m')
    if not isinstance(settings['intraday_config'],dict):raise ValueError('intraday_config must be a dictionary')
    from chanmodel.intraday_research import IntradayConfig
    IntradayConfig(**settings['intraday_config'])
    if settings['volume_tolerance'] not in {1,100,1000}:raise ValueError('volume tolerance must be explicit 1/100/1000')
    if not isinstance(settings['symbols'],list):raise ValueError('symbols must be a list')
    with connect() as db:
        known={r[0] for r in db.execute('SELECT symbol FROM universe WHERE active=1')}
        if any(s not in known for s in settings['symbols']):raise ValueError('unknown security in monitor selection')
        if settings['scope']=='selected' and not settings['symbols']:raise ValueError('select at least one security')
        db.execute("INSERT OR REPLACE INTO metadata VALUES('monitor_config',?)",(json.dumps(settings),))
    return settings


def session_state(now=None):
    now=(now or datetime.now(CN)).astimezone(CN);t=now.time().replace(tzinfo=None)
    trading=now.weekday()<5 and (day_time(9,30)<=t<=day_time(11,30) or day_time(13)<=t<=day_time(15))
    return {'state':'session_window' if trading else 'outside_session','at':now.isoformat(),
            'calendar_scope':'weekday and CN session windows; no exchange holiday calendar proof',
            'quote_freshness':'provider exchange timestamp not independently decoded'}


def records(settings):
    with connect() as db:rows=[dict(r) for r in db.execute('SELECT * FROM universe WHERE active=1 ORDER BY symbol')]
    return rows if settings['scope']=='all' else [r for r in rows if r['symbol'] in settings['symbols']]


def refresh_universe(client=None):
    data,receipt,raw=(client or TdxClient(timeout=30)).universe();rows,coverage,exclusions=normalize_universe(data)
    if not coverage['complete_exchange_presence'] or not coverage.get('upstream_coverage',{}).get('complete'):
        raise ValueError('provider universe coverage incomplete; previous universe retained')
    atomic_bytes(STATE/'monitor/universe-response.json.gz',gzip.compress(raw,mtime=0))
    with connect() as db:
        db.execute('UPDATE universe SET active=0')
        db.executemany('INSERT INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,1) ON CONFLICT(symbol) DO UPDATE SET code=excluded.code,name=excluded.name,exchange=excluded.exchange,active=1',
                       [(r['symbol'],r['code'],r['name'],r['exchange']) for r in rows])
        db.execute("INSERT OR REPLACE INTO metadata VALUES('universe',?)",(json.dumps({'coverage':coverage,'receipt':receipt}),))
    return {'total':len(rows),'coverage':coverage,'received_at':receipt['received_at']}


def collect_quotes(rows,client=None,workers=4):
    client=client or TdxClient(timeout=15);batches=[rows[i:i+50] for i in range(0,len(rows),50)];points=[];failures=[];missing=[];extras=[];receipts=[]
    def fetch(batch):
        symbols=[r['symbol'] for r in batch];data,receipt,raw=client.quotes(symbols)
        normalized,absent,extra=normalized_quotes(data,symbols,receipt)
        return normalized,absent,extra,receipt
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(fetch,b):b for b in batches}
        for future in as_completed(futures):
            try:
                values,absent,extra,receipt=future.result();points+=values;missing+=absent;extras+=extra;receipts.append(receipt)
            except Exception as exc:failures.append({'symbols':[r['symbol'] for r in futures[future]],'error':f'{type(exc).__name__}: {exc}'})
    with connect() as db:
        db.executemany('INSERT OR REPLACE INTO monitor_quotes VALUES(?,?,?)',[(p['symbol'],p['received_at'],json.dumps(p,ensure_ascii=False)) for p in points])
    return {'requested':len(rows),'observed':len(points),'missing':missing,'extras':extras,'failed_batches':failures,
            'batch_receipts':receipts,'complete':len(points)==len(rows) and not missing and not failures,
            'quotes':points,'session':session_state()}


def structure_one(record,settings,cutoff):
    symbol=record['symbol'];inputs={};receipts={};session_meta={}
    try:
        if settings['structure_mode']=='intraday':
            from .intraday_monitor import structure_one as intraday_structure
            return intraday_structure(record,settings,cutoff)
        from chanmodel.v2.series import Series
        from .live import _ingest
        for period in ['day','30m','5m'] if settings['structure_mode']=='multi' else ['day']:
            session,display,receipt,meta=_ingest(symbol,period,force_full_audit=settings['refresh_history'])
            inputs[period]=Series(symbol,period,'unadjusted',tuple(display),
                'tdx_live_ohlcv',meta['checkpoint_sha256'])
            session_meta[period]=meta
            receipts[period]={**receipt,'incremental_session':{k:meta.get(k) for k in
                ('restored','session_reused','resident','appended','rebuilt','total_closed','revision','checkpoint_sha256',
                 'checkpoint_journal_bars','checkpoint_migrated')}}
        reports={p:session_meta[p]['report'] for p in inputs}
        result={'reports':reports,'links':{'selected_signals':[],'pairs':{}}}
        signals=[]
        for period,report in result['reports'].items():
            # The scan start can be older than the bars returned by a slow
            # fetch. Anchor every index and age to the report's own cutoff.
            bars=inputs[period].prefix(report['as_of']).bars
            for point in report['signals']:
                if not 0<=point['anchor']<len(bars) or not 0<=point['available_at']<len(bars):continue
                age_bars=len(bars)-1-point['available_at']
                if age_bars<0:continue
                signals.append({**point,'signal_id':period+':'+point['id'],'period':period,
                                'anchor_time':bars[point['anchor']].closed_at,'available_time':bars[point['available_at']].closed_at,
                                'age_bars':age_bars,'trade_level':period,
                                'confirm_level':'missing','trigger_level':'missing','definition_mode':report['definition_mode'],
                                'structure_completeness':'recursive_single_timeframe_candidate','approximation_loss':report['approximation_loss'],
                                'execution_allowed':False})
        for link in result['links']['selected_signals']:
            if link['state']!='structurally_triggered_under_profile':continue
            parent=next((s for s in signals if s['id']==link['parent_signal'] and s['period']==link['trade_period']),None)
            if parent:parent.update(state=link['state'],confirm_level=link['confirm_period'],trigger_level=link['trigger_period'],
                                   trigger_evidence=link['trigger'],confirmation_evidence=link['confirmation'])
        observed=max(datetime.fromisoformat(r['received_at']) for r in receipts.values()).isoformat()
        data_as_of={p:report['as_of'] for p,report in reports.items()}
        last_bar_at={p:report['last_bar_at'] for p,report in reports.items()}
        return {**record,'state':'calculated','as_of':observed,'scan_started_at':cutoff,
                'data_as_of':data_as_of,'last_bar_at':last_bar_at,
                'signals':signals,'data_pairs':{k:{f:v.get(f) for f in ['state','matched_parent_bars','mismatched_parent_bars']} for k,v in result['links']['pairs'].items()},
                'source_receipts':receipts,'execution_allowed':False}
    except Exception as exc:return {**record,'state':'failed','as_of':cutoff,'signals':[],'error':f'{type(exc).__name__}: {exc}'}


def record_structure(value):
    symbol=value['symbol'];at=value['as_of'];created=[]
    with connect() as db:
        prior=db.execute('SELECT payload FROM monitor_structures WHERE symbol=?',(symbol,)).fetchone()
        # A failed refresh does not erase the last good structure or imply
        # withdrawal of every signal. Its failure is recorded in the run.
        if value['state']!='calculated':return []
        moment=_instant(at)
        if moment is None:raise ValueError('monitor structure observation requires a timezone')
        if prior:
            previous=_instant(json.loads(prior['payload']).get('as_of'))
            # Slow overlapping requests can complete in reverse order. Their
            # old snapshot must not withdraw a newer signal or replace state.
            if previous is not None and moment<previous:return []
        present=set()
        for point in value['signals']:
            ident=point['signal_id'];present.add(ident)
            old=db.execute('SELECT * FROM monitor_signals WHERE symbol=? AND signal_id=?',(symbol,ident)).fetchone()
            signature=hashlib.sha256(json.dumps({k:point.get(k) for k in ['state','anchor','price','invalidation','available_time',
                'confirmed_at','confirmed_time','invalidated_at','invalidated_time']},sort_keys=True).encode()).hexdigest()
            state=point['state'];first=old['first_seen'] if old else at
            db.execute('INSERT OR REPLACE INTO monitor_signals VALUES(?,?,?,?,?,?,?)',(symbol,ident,state,signature,first,at,json.dumps(point,ensure_ascii=False)))
            old_value=json.loads(old['payload']) if old else {}
            old_state=old_value.get('source_state',old['state']) if old else None
            lifecycle=old is not None and state!=old_state and state in {
                'structure_complete','structurally_triggered_under_profile','invalidated','withdrawn'}
            recent=0<=point.get('age_bars',-1)<=2
            # Confirmation or invalidation may occur many bars after its
            # price pivot; the age of the pivot is not the observation age.
            if prior and not value.get('suppress_notifications') and (old is None or old['signature']!=signature) and (recent or lifecycle):
                key='structure:'+symbol+':'+ident+':'+signature
                payload={**point,'observed_at':at,'lifecycle_transition':lifecycle,
                         'execution_allowed':False}
                cursor=db.execute('INSERT OR IGNORE INTO monitor_alerts(event_key,symbol,created,kind,payload) VALUES(?,?,?,?,?)',
                                  (key,symbol,at,'structure_transition',json.dumps(payload,ensure_ascii=False)))
                if cursor.rowcount:created.append({'symbol':symbol,'kind':'structure_transition','point':point})
        for old in db.execute('SELECT * FROM monitor_signals WHERE symbol=?',(symbol,)).fetchall():
            if old['signal_id'] not in present and old['state'] not in {'withdrawn','invalidated','session_expired'}:
                if old['signal_id'] in value.get('expired_signal_ids',[]):
                    payload=json.loads(old['payload']);payload.update(state='session_expired',
                        expired_observed_at=at,expiry_reason='pivot belongs to an earlier native trading session')
                    db.execute("UPDATE monitor_signals SET state='session_expired',last_seen=?,payload=? WHERE symbol=? AND signal_id=?",
                               (at,json.dumps(payload,ensure_ascii=False),symbol,old['signal_id']))
                    continue
                db.execute("UPDATE monitor_signals SET state='withdrawn',last_seen=? WHERE symbol=? AND signal_id=?",(at,symbol,old['signal_id']))
                payload=json.loads(old['payload']);payload['state']='withdrawn'
                key='withdrawn:'+symbol+':'+old['signal_id']+':'+old['signature']
                if not value.get('suppress_notifications'):
                    cursor=db.execute('INSERT OR IGNORE INTO monitor_alerts(event_key,symbol,created,kind,payload) VALUES(?,?,?,?,?)',
                                      (key,symbol,at,'signal_withdrawn',json.dumps(payload,ensure_ascii=False)))
                    if cursor.rowcount:created.append({'symbol':symbol,'kind':'signal_withdrawn','point':payload})
        db.execute('INSERT OR REPLACE INTO monitor_structures VALUES(?,?,?)',(symbol,at,json.dumps(value,ensure_ascii=False)))
    return created


def quote_invalidations(points):
    changed=[]
    with connect() as db:
        for quote in points:
            if quote['quote_status']!='observed':continue
            quote_at=_instant(quote.get('received_at'))
            price=quote.get('price')
            if quote_at is None or isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:continue
            structure=db.execute('SELECT payload FROM monitor_structures WHERE symbol=?',(quote['symbol'],)).fetchone()
            structure_at=_instant(json.loads(structure['payload']).get('as_of')) if structure else None
            for row in db.execute("SELECT * FROM monitor_signals WHERE symbol=? AND state NOT IN ('invalidated','withdrawn','session_expired')",(quote['symbol'],)).fetchall():
                point=json.loads(row['payload']);limit=point['invalidation']
                available=_instant(point.get('available_time'))
                if row['signal_id'].startswith('intraday:'):
                    pivot=_instant(point.get('pivot_time',point.get('anchor_time')))
                    if pivot is None or pivot.astimezone(CN).date()!=quote_at.astimezone(CN).date():continue
                barriers=[value for value in (available,structure_at,_instant(row['last_seen'])) if value is not None]
                if barriers and quote_at<max(barriers):continue
                trade_at=_instant(quote.get('exchange_trade_timestamp'))
                if trade_at is not None and (trade_at>quote_at or available is not None and trade_at<available):continue
                operator=point.get('invalidation_operator','le' if point['side']=='buy' else 'ge')
                broken={'le':price<=limit,'lt':price<limit,'ge':price>=limit,'gt':price>limit}[operator]
                if not broken:continue
                payload={**point,'source_state':point.get('source_state',point['state']),
                         'state':'quote_boundary_crossed','quote':quote,'closed_bar_confirmation_required':True,
                         'quote_trade_freshness_proven':trade_at is not None,'execution_allowed':False}
                key='quote-boundary:'+quote['symbol']+':'+row['signal_id']+':'+row['signature']
                cursor=db.execute('INSERT OR IGNORE INTO monitor_alerts(event_key,symbol,created,kind,payload) VALUES(?,?,?,?,?)',
                                  (key,quote['symbol'],quote['received_at'],'quote_boundary_crossed',json.dumps(payload,ensure_ascii=False)))
                if cursor.rowcount:
                    db.execute("UPDATE monitor_signals SET state='quote_boundary_crossed',last_seen=?,payload=? WHERE symbol=? AND signal_id=?",
                               (quote['received_at'],json.dumps(payload,ensure_ascii=False),quote['symbol'],row['signal_id']))
                    changed.append(payload)
    return changed


def update_run(ident,state,payload):
    with connect() as db:
        db.execute('INSERT INTO monitor_runs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,updated=excluded.updated,payload=excluded.payload',
                   (ident,state,payload['started'],now_iso(),json.dumps(payload,ensure_ascii=False)))


def run_scan(kind='quotes',settings=None):
    global BUSY
    if kind not in {'quotes','structures','both'}:raise ValueError('unknown scan kind')
    settings=settings or config();rows=records(settings);ident='scan-'+uuid.uuid4().hex[:12]
    payload={'id':ident,'kind':kind,'started':now_iso(),'total':len(rows),'done':0,'failed':0,'alerts':0}
    update_run(ident,'running',payload)
    try:
        if kind in {'quotes','both'}:
            quotes=collect_quotes(rows,workers=settings['workers']);crossings=quote_invalidations(quotes['quotes'])
            payload['quotes']={k:v for k,v in quotes.items() if k!='quotes'};payload['alerts']+=len(crossings)
        if kind in {'structures','both'}:
            with ThreadPoolExecutor(max_workers=settings['workers']) as pool:
                pending=iter(rows);futures={};exhausted=False
                while futures or not exhausted:
                    while len(futures)<settings['workers']*2 and not exhausted and not STOP.is_set() and not CANCEL.is_set():
                        try:record=next(pending)
                        except StopIteration:exhausted=True;break
                        futures[pool.submit(structure_one,record,settings,payload['started'])]=record
                    if not futures:break
                    done,_=wait(futures,timeout=1,return_when=FIRST_COMPLETED)
                    for future in done:
                        futures.pop(future);value=future.result();created=record_structure(value)
                        payload['done']+=1;payload['failed']+=value['state']=='failed';payload['alerts']+=len(created)
                        if value['state']=='failed':payload.setdefault('failures',[]).append({'symbol':value['symbol'],'error':value['error']})
                        if payload['done']%20==0:update_run(ident,'running',payload)
                    if STOP.is_set() or CANCEL.is_set():exhausted=True
        else:payload['done']=len(rows)
        update_run(ident,'stopped' if STOP.is_set() or CANCEL.is_set() else 'complete',payload)
    except Exception as exc:
        payload['error']=f'{type(exc).__name__}: {exc}';update_run(ident,'failed',payload)
    finally:
        with LOCK:BUSY=False
    return payload


def start_scan(kind='quotes'):
    global BUSY
    with LOCK:
        if BUSY:raise ValueError('a scan is already running')
        BUSY=True
        CANCEL.clear()
    threading.Thread(target=run_scan,args=(kind,),daemon=True).start()
    return {'state':'started','kind':kind}


def overview(limit=100):
    with connect() as db:
        runs=[{**dict(r),'payload':json.loads(r['payload'])} for r in db.execute('SELECT * FROM monitor_runs ORDER BY started DESC LIMIT 8')]
        alerts=[{**dict(r),'payload':json.loads(r['payload'])} for r in db.execute('SELECT * FROM monitor_alerts ORDER BY id DESC LIMIT ?',(limit,))]
        signals=[{**dict(r),'payload':json.loads(r['payload'])} for r in db.execute("SELECT * FROM monitor_signals WHERE state NOT IN ('withdrawn','invalidated','session_expired') ORDER BY last_seen DESC LIMIT ?",(limit,))]
        counts={'quotes':db.execute('SELECT COUNT(*) FROM monitor_quotes').fetchone()[0],
                'structures':db.execute('SELECT COUNT(*) FROM monitor_structures').fetchone()[0],
                'unread':db.execute('SELECT COUNT(*) FROM monitor_alerts WHERE acknowledged=0').fetchone()[0]}
    return {'config':config(),'session':session_state(),'busy':BUSY,'counts':counts,'runs':runs,'alerts':alerts,'signals':signals,
            'notification_scope':'application and optional browser desktop; application must remain running'}


def acknowledge():
    with connect() as db:db.execute('UPDATE monitor_alerts SET acknowledged=1')
    return {'state':'acknowledged'}


def stop_scan():
    CANCEL.set()
    return {'state':'stopping_after_inflight_requests'}


def supervisor():
    last_quotes=last_structures=0.
    while not STOP.wait(2):
        try:
            settings=config()
            if not settings['enabled'] or BUSY or session_state()['state']!='session_window':continue
            now=time.monotonic()
            if now-last_structures>=settings['structure_interval']:
                start_scan('both');last_quotes=last_structures=now
            elif now-last_quotes>=settings['quote_interval']:
                start_scan('quotes');last_quotes=now
        except (ValueError,OSError):continue


def launch():
    global THREAD
    if THREAD is None or not THREAD.is_alive():
        STOP.clear();THREAD=threading.Thread(target=supervisor,daemon=True);THREAD.start()
