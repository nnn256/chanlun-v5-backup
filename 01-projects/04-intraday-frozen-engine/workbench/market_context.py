"""Normalized benchmark indices and independently sourced industry leaders."""
from collections import Counter,OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,time as day_time,timezone
import json
import hashlib
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

from chanmodel.model import Candle
from chanmodel.reference_engine import ReferenceSession,review_geometry,PROFILE,COMMIT
from chanmodel.signal_chart import build_annotations
from chanmodel.tdx_data import CN, TdxClient, now_iso, yuan
from chanmodel.v2.series import session_closes

INDEXES=OrderedDict([
    ('sh000001','上证指数'),('sz399001','深证成指'),('sz399006','创业板指'),
    ('sh000300','沪深300'),('sh000905','中证500'),('sh000852','中证1000')])
GLOBAL_INDEXES=OrderedDict([
    ('^DJI',('道琼斯工业指数','Dow Jones Industrial Average')),
    ('^GSPC',('标普500','S&P 500')),
    ('^IXIC',('纳斯达克综合指数','Nasdaq Composite')),
    ('^FTSE',('富时100','FTSE 100')),
    ('^NSEI',('印度Nifty 50','Nifty 50')),
    ('^NDX',('纳斯达克100','Nasdaq 100')),
    ('^BSESN',('印度Sensex','BSE Sensex')),
    ('^N225',('日经225','Nikkei 225')),
    ('^HSI',('恒生指数','Hang Seng Index')),
    ('^GDAXI',('德国DAX','DAX')),
    ('^FCHI',('法国CAC40','CAC 40')),
    ('^KS11',('韩国KOSPI','KOSPI')),
    ('^AXJO',('澳洲ASX200','S&P/ASX 200')),
])
GLOBAL_CHART_URL='https://query1.finance.yahoo.com/v8/finance/chart/'
INDUSTRY_URL='https://push2.eastmoney.com/api/qt/clist/get'
INDUSTRY_PAGE_SIZE=500
MAX_INDUSTRY_BOARDS=10000
INDUSTRY_PARAMS={'pn':1,'pz':INDUSTRY_PAGE_SIZE,'po':1,'np':1,'ut':'bd1d9ddb04089700cf9c27f6f7426281',
                 'fltt':2,'invt':2,'fid':'f3','fs':'m:90+t:2','fields':'f12,f14,f2,f3,f62,f184'}
LOCK=threading.RLock();CACHE={};SNAPSHOT_CACHE={};INDEX_CACHE={};INDEX_STRUCTURE_CACHE={}


def index_snapshot(code,name,period='day',limit=64,full_history=False):
    if period not in {'day','30m','5m'}:raise ValueError('index period must be day, 30m, or 5m')
    if code not in INDEXES and not re.fullmatch(r'(sh|sz)\d{6}',code):raise ValueError('unsupported benchmark index: '+code)
    if limit is not None and (type(limit) is not int or not 1<=limit<=800):raise ValueError('index history limit must be 1..800')
    params={'code':code,'type':{'day':'day','30m':'minute30','5m':'minute5'}[period]}
    if limit is not None:params['limit']=limit
    endpoint='/api/index/all' if full_history else '/api/index'
    timeout=90 if full_history else 8 if limit==64 else 45
    data,receipt,_=TdxClient(timeout=timeout).request_retry(endpoint,params,attempts=2)
    rows=data.get('list',data.get('List'))
    count=data.get('count',data.get('Count'))
    if not isinstance(rows,list) or not rows:raise ValueError(f'{code}: index API returned no rows')
    if count is not None and int(count)!=len(rows):raise ValueError(f'{code}: index count mismatch')
    observed=datetime.fromisoformat(receipt['requested_at'])
    if observed.tzinfo is None:raise ValueError(f'{code}: request timestamp has no timezone')
    observed=observed.astimezone(CN)
    ordered=[];rejected_rows=[]
    for row_number,row in enumerate(rows):
        if not isinstance(row,dict):
            if full_history:rejected_rows.append({'row':row_number,'reason':'row_not_object'});continue
            raise ValueError(f'{code}: invalid index row')
        stamp=str(row.get('Time',''))
        try:point=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        except ValueError:
            try:point=datetime.strptime(stamp,'%Y/%m/%d %H:%M:%S').replace(tzinfo=CN)
            except ValueError:
                if full_history:rejected_rows.append({'row':row_number,'time_raw':stamp,'reason':'invalid_timestamp'});continue
                raise ValueError(f'{code}: invalid index timestamp')
        if point.tzinfo is None:
            if full_history:rejected_rows.append({'row':row_number,'time_raw':stamp,'reason':'timestamp_without_timezone'});continue
            raise ValueError(f'{code}: index timestamp has no timezone')
        ordered.append((point.astimezone(CN),row))
    ordered.sort(key=lambda item:item[0])
    if len({point for point,_ in ordered})!=len(ordered):raise ValueError(f'{code}: duplicate index timestamps')
    parsed=[]
    for point,row in ordered:
        if point.date()>observed.date():raise ValueError(f'{code}: index response contains a future session')
        is_closed=point<=observed
        if not is_closed:
            if period=='day':expected=datetime.combine(observed.date(),day_time(15),CN)
            else:expected=next((close for close in session_closes(observed.date(),period) if close>observed),None)
            if expected is None or point!=expected:
                raise ValueError(f'{code}: provider returned a future interval that has not started')
        try:values={key:yuan(row.get(field),field) for key,field in [('open','Open'),('high','High'),('low','Low'),('close','Close')]}
        except (ValueError,TypeError,OverflowError):
            if full_history:rejected_rows.append({'time':point.isoformat(),'reason':'invalid_ohlc_value'});continue
            raise ValueError(f'{code}: invalid index OHLC value')
        if min(values.values())<=0:
            if full_history:rejected_rows.append({'time':point.isoformat(),'reason':'nonpositive_ohlc'});continue
            raise ValueError(f'{code}: invalid index OHLC')
        if values['high']<max(values['open'],values['close'],values['low']) or values['low']>min(values['open'],values['close'],values['high']):
            if full_history:rejected_rows.append({'time':point.isoformat(),'reason':'invalid_ohlc_envelope','ohlc':values});continue
            raise ValueError(f'{code}: index OHLC envelope is invalid')
        parsed.append({'time':point.isoformat(),'date':point.date().isoformat(),'is_closed':is_closed,**values,
                       'volume_protocol_raw':row.get('Volume'),'volume_unit':'provider_native_unspecified',
                       'amount_protocol_raw':row.get('Amount'),'amount_unit':'provider_native_unscaled',
                       'up_count':row.get('UpCount'),'down_count':row.get('DownCount')})
    if not parsed:raise ValueError(f'{code}: no valid index OHLC rows remain after validation')
    latest=parsed[-1];previous=parsed[-2]['close'] if len(parsed)>1 else None
    last_closed=next((row for row in reversed(parsed) if row['is_closed']),None)
    result={'code':code,'name':name,'period':period,'price':latest['close'],'previous_close':previous,
            'change_pct':(latest['close']/previous-1)*100 if previous else None,
            'latest_bar_at':latest['time'],'latest_bar_is_closed':latest['is_closed'],
            'latest_closed_bar_at':last_closed['time'] if last_closed else None,
            'observed_at':receipt['requested_at'],'received_at':receipt['received_at'],'bars':parsed,
            'source':'TDX index all-history API · raw unadjusted' if full_history else 'TDX index API · raw unadjusted',
            'coverage_claim':'provider all-history response' if full_history else 'latest provider window',
            'provider_rows_received':len(rows),'rows_excluded':len(rejected_rows),'excluded_rows':rejected_rows,
            'source_response_sha256':receipt['response_sha256'],
            'market_group':'A股指数',
            'up_count':latest['up_count'],'down_count':latest['down_count'],
            'freshness_semantics':'request time is acquisition time; bar Time is the scheduled close label'}
    with LOCK:INDEX_CACHE[(code,period)]=(time.monotonic(),result)
    return result


def index_structure(code,period='day'):
    """Calculate native Chan structures over the provider's available index history."""
    code=str(code).strip()
    if code not in GLOBAL_INDEXES and code not in INDEXES and not re.fullmatch(r'(sh|sz)\d{6}',code):
        raise ValueError('unsupported benchmark index: '+str(code))
    if period not in {'day','30m','5m'}:raise ValueError('index period must be day, 30m, or 5m')
    cache_key=(code,period);now=time.monotonic()
    with LOCK:
        cached=INDEX_STRUCTURE_CACHE.get(cache_key)
        if cached and now-cached[0]<60:return {**cached[1],'cache_age_seconds':round(now-cached[0],1)}
    if code in GLOBAL_INDEXES:index=global_index_snapshot(code,period,full_history=period=='day')
    else:index=index_snapshot(code,INDEXES.get(code,code.upper()),period,
                              limit=None if period=='day' else 800,full_history=period=='day')
    closed_rows=[row for row in index['bars'] if row['is_closed']]
    if len(closed_rows)<10:raise ValueError(f"{code} {period}: 结构分析至少需要10根已收盘指数K线")
    native_bars=[];source_positions=[]
    for row in index['bars']:
        if not row['is_closed']:continue
        position=len(native_bars);source_positions.append(position)
        native_bars.append(Candle(position,row['open'],row['high'],row['low'],row['close'],row['time'],None,True))
    digest=hashlib.sha256(json.dumps([[bar.closed_at,bar.open,bar.high,bar.low,bar.close] for bar in native_bars],
        separators=(',',':'),allow_nan=False).encode()).hexdigest()
    session=ReferenceSession(period,observe=True)
    for bar in native_bars:session.append(bar)
    cutoff=native_bars[-1].closed_at
    report=review_geometry(session.snapshot(code,cutoff,index['source'],'unadjusted',digest))
    bars=[];closed_position=0
    for row in index['bars']:
        closed=row['is_closed']
        pos=closed_position if closed else len(native_bars)
        if closed:closed_position+=1
        stamp=datetime.fromisoformat(row['time'])
        bars.append({'time':int(stamp.timestamp())+8*3600,'source_index':pos,'closed_at':row['time'],
            'date_cn':stamp.strftime('%Y-%m-%d %H:%M'),'is_closed':closed,
            'open':row['open'],'high':row['high'],'low':row['low'],'close':row['close'],'volume':None})
    layer=report['hierarchy']['levels'][0]
    panel={'kind':'candlestick','period':period,'visible_start':0,'visible_bars':len(bars),
        'input_bars':len(bars),'default_visible':min(300,len(bars)),'history_complete_in_chart':True,
        'bars':bars,'strokes':report['base']['strokes'],'segments':report['base']['segments'],
        'higher_segments':report['base'].get('higher_segments',[]),'centers':layer['centers'],
        'signals':[signal for signal in report['signals'] if signal['rank']==1],
        'all_signals':report['signals'],'structure_layers':report['hierarchy']['levels'],
        'merged':report['base']['merged'],'fractals':report['base']['fractals'],
        'geometry_review':report['geometry_review'],'complete_evidence':{
            key:report.get(key,[]) for key in ('feature_sequences','center_evolution','center_monitors',
                'construction_phases','divergence_comparisons')},
        'engine_provenance':report.get('engine_provenance'),'kline_audit':{'state':'valid','errors':[]},
        'coverage':{'source':index['source'],'returned_bars':len(index['bars']),
                    'first_bar_at':index['bars'][0]['time'],
                    'closed_bars':len(native_bars),'claim':index.get('coverage_claim',
                        'latest provider window'),'provider_rows_received':index.get('provider_rows_received',len(index['bars'])),
                    'rows_excluded':index.get('rows_excluded',0),
                    'exclusion_reasons':dict(Counter(row['reason'] for row in index.get('excluded_rows',[])))}}
    panel['signal_chart']=build_annotations(panel,cutoff=cutoff)
    from .research_service import attach_research
    attach_research(panel,code)
    up=index.get('up_count');down=index.get('down_count')
    if ('regime_research' in panel and isinstance(up,(int,float)) and isinstance(down,(int,float)) and
            math.isfinite(up) and math.isfinite(down) and min(up,down)>=0 and up+down>0):
        panel['regime_research']['market_observation']={
            'up_count':up,'down_count':down,'advance_share':up/(up+down),
            'received_at':index['received_at'],'scope':'当前指数成分的涨跌家数；不是全A股或投资者心理指标',
            'pit_history_proven':False}
    value={'index':index,'panel':panel,'structure':{
        'profile':PROFILE,'commit':COMMIT,'closed_bars':len(native_bars),
        'stroke_count':len(report['base']['strokes']),'segment_count':len(report['base']['segments']),
        'center_count':len(layer['centers']),'signal_count':len(report['signals']),
        'signals_by_rank':{str(rank):sum(point['rank']==rank for point in report['signals'])
                           for rank in sorted({point['rank'] for point in report['signals']})},
        'approximation_loss':report['approximation_loss'],
        'coverage_semantics':index.get('coverage_claim','latest provider window'),
        'provider_rows_received':index.get('provider_rows_received',len(index['bars'])),'rows_excluded':index.get('rows_excluded',0),
        'exclusion_reasons':dict(Counter(row['reason'] for row in index.get('excluded_rows',[]))),
        'execution_allowed':False}}
    with LOCK:INDEX_STRUCTURE_CACHE[cache_key]=(time.monotonic(),value)
    return value


def global_index_snapshot(code,period='day',full_history=False):
    if code not in GLOBAL_INDEXES:raise ValueError('unsupported global index ticker: '+code)
    if period not in {'day','30m','5m'}:raise ValueError('index period must be day, 30m, or 5m')
    range_,interval={'day':('max' if full_history else '1mo','1d'),
                     '30m':('1mo','30m'),'5m':('5d','5m')}[period]
    url=GLOBAL_CHART_URL+urllib.parse.quote(code,safe='')+'?'+urllib.parse.urlencode(
        {'range':range_,'interval':interval,'includePrePost':'false','events':'div,splits'})
    request=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'Mozilla/5.0 (compatible; ChanlunResearch/4.3)'})
    with urllib.request.urlopen(request,timeout=45 if full_history else 10) as response:raw=response.read()
    payload=json.loads(raw);chart=payload.get('chart') or {}
    if chart.get('error'):raise ValueError(f'{code}: Yahoo chart error: {chart["error"]}')
    results=chart.get('result')
    if not isinstance(results,list) or not results or not isinstance(results[0],dict):raise ValueError(f'{code}: Yahoo chart returned no index')
    result=results[0];meta=result.get('meta') or {};timestamps=result.get('timestamp') or []
    quote=((result.get('indicators') or {}).get('quote') or [{}])[0]
    try:zone=ZoneInfo(meta.get('exchangeTimezoneName','UTC'))
    except (ZoneInfoNotFoundError,TypeError):zone=timezone.utc
    now=datetime.now(timezone.utc).timestamp();regular=(meta.get('currentTradingPeriod') or {}).get('regular') or {}
    regular_end=regular.get('end');rows=[]
    fields={key:quote.get(key) or [] for key in ('open','high','low','close','volume')}
    for i,stamp in enumerate(timestamps):
        values={key:(array[i] if i<len(array) else None) for key,array in fields.items()}
        if any(value is None for key,value in values.items() if key!='volume'):continue
        try:ohlc={key:float(values[key]) for key in ('open','high','low','close')}
        except (TypeError,ValueError):continue
        if not all(math.isfinite(value) and value>0 for value in ohlc.values()):continue
        if ohlc['high']<max(ohlc['open'],ohlc['close'],ohlc['low']) or ohlc['low']>min(ohlc['open'],ohlc['close'],ohlc['high']):
            continue
        if period=='day':closed=(stamp<now and (regular_end is None or now>=regular_end or
            datetime.fromtimestamp(stamp,zone).date()<datetime.fromtimestamp(now,zone).date()))
        else:closed=stamp+({'5m':300,'30m':1800}[period])<=now
        local=datetime.fromtimestamp(stamp,zone)
        rows.append({'time':local.isoformat(),'date':local.date().isoformat(),'is_closed':closed,**ohlc,
                     'volume':values['volume'],'volume_unit':meta.get('instrumentType','provider_native'),
                     'currency':meta.get('currency')})
    if not rows:raise ValueError(f'{code}: Yahoo response has no valid OHLC bars')
    latest=rows[-1];last_closed=next((row for row in reversed(rows) if row['is_closed']),None)
    prior=next((row for row in reversed(rows[:-1]) if row['is_closed']),None)
    previous=prior['close'] if prior else meta.get('chartPreviousClose') or meta.get('previousClose')
    result={'code':code,'ticker':code,'name':GLOBAL_INDEXES[code][0],'english_name':GLOBAL_INDEXES[code][1],
            'provider':'Yahoo Finance chart','source':'Yahoo Finance public chart endpoint',
            'period':period,'currency':meta.get('currency'),'exchange':meta.get('fullExchangeName') or meta.get('exchangeName'),
            'price':latest['close'],'previous_close':previous,
            'change_pct':(latest['close']/previous-1)*100 if previous else None,
            'latest_bar_at':latest['time'],'latest_bar_is_closed':latest['is_closed'],
            'latest_closed_bar_at':last_closed['time'] if last_closed else None,'bars':rows,
            'received_at':now_iso(),'source_as_of':datetime.fromtimestamp(meta['regularMarketTime'],timezone.utc).isoformat() if meta.get('regularMarketTime') else None,
            'source_response_sha256':hashlib.sha256(raw).hexdigest(),
            'coverage_claim':('provider maximum daily history response' if full_history and period=='day' else
                {'day':'provider 1mo range','30m':'provider 1mo range','5m':'provider 5d range'}[period]),
            'execution_allowed':False,'freshness_semantics':'public third-party index chart; source time and local receive time are separate'}
    with LOCK:INDEX_CACHE[(code,period)]=(time.monotonic(),result)
    return result


def _sector_request(params):
    request=urllib.request.Request(INDUSTRY_URL+'?'+urllib.parse.urlencode(params),
        headers={'Accept':'application/json','Referer':'https://quote.eastmoney.com/',
                 'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'})
    with urllib.request.urlopen(request,timeout=12) as response:raw=response.read()
    data=json.loads(raw)
    if data.get('rc')!=0 or not isinstance(data.get('data'),dict):raise ValueError('Eastmoney industry response is incomplete')
    return data['data'],raw


def _industry_pages():
    records=[];digests=[];declared=None;page=1
    while True:
        params={**INDUSTRY_PARAMS,'pn':page,'pz':INDUSTRY_PAGE_SIZE}
        data,raw=_sector_request(params);difference=data.get('diff') or []
        if not isinstance(difference,list):raise ValueError('Eastmoney industry page is not a list')
        try:reported=int(data['total'])
        except (KeyError,TypeError,ValueError):reported=None
        if declared is None:declared=reported
        elif reported is not None and reported!=declared:raise ValueError('Eastmoney industry total changed during paging')
        records.extend(difference);digests.append(hashlib.sha256(raw).hexdigest())
        if declared is not None:
            if declared<0 or declared>MAX_INDUSTRY_BOARDS:raise ValueError('Eastmoney industry count exceeds configured bound')
            if len(records)>=declared:break
            if not difference:raise ValueError('Eastmoney industry pages ended before declared total')
            page+=1
        else:
            if len(difference)<INDUSTRY_PAGE_SIZE:declared=len(records);break
            raise ValueError('Eastmoney industry page omitted total; completeness cannot be proven')
    codes=[str(row.get('f12','')) for row in records if isinstance(row,dict)]
    if len(records)!=declared or len(codes)!=len(records) or len(set(codes))!=len(codes):
        raise ValueError('Eastmoney industry pages are incomplete or duplicated')
    return records,declared,page,hashlib.sha256(''.join(digests).encode()).hexdigest()


def _industries():
    now=time.monotonic()
    with LOCK:
        prior=CACHE.get('industries')
        if prior and now-prior[0]<120:return {**prior[1],'cache_age_seconds':round(now-prior[0],1)}
    try:
        difference,total,pages,combined_hash=_industry_pages()
        if not difference:raise ValueError('industry API returned no rows')
        rows=[]
        for row in difference:
            try:
                code=str(row['f12']);name=str(row['f14'])
                price=None if row.get('f2') in (None,'-') else float(row['f2'])
                change=None if row.get('f3') in (None,'-') else float(row['f3'])
                if price is not None and (not math.isfinite(price) or price<=0):continue
                if change is not None and not math.isfinite(change):continue
                flow=None if row.get('f62') in (None,'-') else float(row['f62'])
                if flow is not None and not math.isfinite(flow):flow=None
                if not code or not name:continue
                rows.append({'code':code,'name':name,'price':price,'change_pct':change,
                             'net_flow':flow,'source':'Eastmoney industry board'})
            except (KeyError,TypeError,ValueError):continue
        if not rows:raise ValueError('industry API has no normalized rows')
        value={'state':'ready','source':'Eastmoney industry board','received_at':now_iso(),
               'source_as_of':None,
               'timestamp_semantics':'provider timestamp is not exposed; received_at is local acquisition time',
               'source_response_sha256':combined_hash,'count':len(rows),'provider_total':total,
               'pages_fetched':pages,'complete':len(rows)==total,'boards':sorted(rows,key=lambda x:x['change_pct'] if x['change_pct'] is not None else -float('inf'),reverse=True),
               'leaders':sorted(rows,key=lambda x:x['change_pct'] if x['change_pct'] is not None else -float('inf'),reverse=True)[:20],
               'laggards':sorted(rows,key=lambda x:x['change_pct'] if x['change_pct'] is not None else float('inf'))[:10],
               'semantics':'provider industry-board snapshot; not cross-market security breadth'}
        with LOCK:CACHE['industries']=(time.monotonic(),value)
        return value
    except Exception as exc:
        with LOCK:prior=CACHE.get('industries')
        detail=f'HTTP {exc.code}' if isinstance(exc,urllib.error.HTTPError) else f'{type(exc).__name__}: {exc}'
        if prior:return {**prior[1],'state':'stale','error':type(exc).__name__,'error_detail':detail,
                         'cache_age_seconds':round(now-prior[0],1)}
        return {'state':'unavailable','source':'Eastmoney industry board','received_at':now_iso(),
                'error':type(exc).__name__,'error_detail':detail,'count':0,'leaders':[],'laggards':[],
                'semantics':'行业数据源不可用；未生成占位行情'}


def market_context(period='day',include_industries=True):
    if period not in {'day','30m','5m'}:raise ValueError('market context period must be day/30m/5m')
    key=(period,bool(include_industries));now=time.monotonic()
    with LOCK:
        cached=SNAPSHOT_CACHE.get(key)
        if cached and now-cached[0]<20:
            return {**cached[1],'cache_age_seconds':round(now-cached[0],1)}
    tasks=[('tdx',code,name,lambda code=code,name=name:index_snapshot(code,name,period)) for code,name in INDEXES.items()]
    tasks += [('global',ticker,names[0],lambda ticker=ticker:global_index_snapshot(ticker,period))
              for ticker,names in GLOBAL_INDEXES.items()]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(fetch) for _,_,_,fetch in tasks]
        industry_future=pool.submit(_industries) if include_industries else None
        indices=[]
        for (provider,code,name,_),future in zip(tasks,futures):
            try:indices.append(future.result())
            except Exception as exc:
                with LOCK:old_entry=INDEX_CACHE.get((code,period))
                old=old_entry[1] if old_entry else None
                if old:
                    indices.append({**old,'state':'stale','error':type(exc).__name__,
                                    'error_detail':str(exc)[:160],
                                    'cache_age_seconds':round(now-old_entry[0],1)})
                else:
                    indices.append({'code':code,'name':name,'period':period,'market_group':'A股指数' if provider=='tdx' else '全球指数',
                        'state':'unavailable','error':type(exc).__name__,'error_detail':str(exc)[:160],
                        'source':'TDX index API' if provider=='tdx' else 'Yahoo Finance chart'})
        industry_value=industry_future.result() if industry_future else {'state':'not_requested'}
    breadth=next(({'index':'sh000001','latest_bar_at':x['latest_bar_at'],
                   'up_count':x['up_count'],'down_count':x['down_count'],
                   'state':x.get('state','ready'),
                   'scope':'上证指数成分统计；不是全A股涨跌家数'}
                  for x in indices if x['code']=='sh000001' and x.get('state')!='unavailable'),None)
    result={'received_at':now_iso(),'period':period,'indices':indices,
            'index_catalog':{'tdx':len(INDEXES),'global':len(GLOBAL_INDEXES),'total':len(indices),
                             'semantics':'configured benchmark catalog; not every exchange-listed index worldwide'},
            'industries':industry_value,
            'breadth':breadth,'execution_allowed':False}
    with LOCK:SNAPSHOT_CACHE[key]=(time.monotonic(),result)
    return result
