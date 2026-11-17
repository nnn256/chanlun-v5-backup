"""Exact provider industry membership and native board-index Chan context.

Membership is a current provider classification, never inferred from a stock
name. Relative returns and quote ranking remain separate from closed-bar
structure evidence. Neither current membership nor snapshots backfill history.
"""
from __future__ import annotations

from collections import OrderedDict
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request

from chanmodel.model import Candle

VERSION='industry_chan_context_v1.0.0'
CN=timezone(timedelta(hours=8))
MAX_RESPONSE_BYTES=8*1024*1024
MEMBERSHIP_TTL=3600
STRENGTH_TTL=30
PERIODS={'day':101,'30m':30,'5m':5}
_guard=threading.RLock()
_memberships=OrderedDict()
_strengths=OrderedDict()
_benchmarks=OrderedDict()


def now():return datetime.now(CN).isoformat(timespec='seconds')


def normalize_symbol(value):
    raw=str(value).strip().lower()
    if re.fullmatch(r'\d{6}\.(sh|sz|bj)',raw):
        digits,market=raw.split('.');raw=market+digits
    elif re.fullmatch(r'\d{6}',raw):
        raw=('bj' if raw.startswith(('4','8','92')) else 'sh' if raw.startswith('6') else 'sz')+raw
    if not re.fullmatch(r'(sh6\d{5}|sz(?:0\d{5}|30\d{4})|bj\d{6})',raw):
        raise ValueError('请输入有效的沪深京A股代码')
    return raw


def _number(value):
    if value in (None,'','-','--') or isinstance(value,bool):return None
    try:result=float(value)
    except (TypeError,ValueError):return None
    return result if math.isfinite(result) else None


def _request_json(url):
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (Liangce local research)',
        'Accept':'application/json','Referer':'https://quote.eastmoney.com/'})
    with urllib.request.urlopen(request,timeout=8) as response:
        raw=response.read(MAX_RESPONSE_BYTES+1)
        if len(raw)>MAX_RESPONSE_BYTES:raise ValueError('板块数据响应超出8MiB上限')
    return json.loads(raw),{'url':url,'received_at':now(),
        'response_sha256':hashlib.sha256(raw).hexdigest(),'response_bytes':len(raw)}


def _url(host,path,params):return host+path+'?'+urllib.parse.urlencode(params)


def _cache_get(cache,key,ttl,refresh=False):
    with _guard:
        item=cache.get(key)
        if item and not refresh and 0<=time.monotonic()-item[0]<ttl:
            cache.move_to_end(key);value=copy.deepcopy(item[1]);value['cache_age_seconds']=round(time.monotonic()-item[0],3)
            return value
    return None


def _cache_put(cache,key,value,limit=32):
    with _guard:
        cache[key]=(time.monotonic(),copy.deepcopy(value));cache.move_to_end(key)
        while len(cache)>limit:cache.popitem(last=False)


def _resolve_industry(name):
    url=_url('https://searchapi.eastmoney.com','/api/suggest/get',{
        'input':name,'type':14,'token':'D43BF722C8E33BDC906FB84D85E326E8','count':10})
    payload,receipt=_request_json(url)
    table=payload.get('QuotationCodeTable') or {}
    if table.get('Status') not in (None,0):raise ValueError('板块代码查询响应失败')
    rows=table.get('Data') or []
    if not isinstance(rows,list) or len(rows)>100:raise ValueError('板块搜索响应格式无效')
    matches=[row for row in rows if isinstance(row,dict) and row.get('Name')==name
        and row.get('Classify')=='BK' and str(row.get('MktNum'))=='90'
        and str(row.get('TypeUS'))=='2' and re.fullmatch(r'BK\d{4,6}',str(row.get('Code','')))
        and row.get('QuoteID')=='90.'+row['Code']]
    codes={row['Code'] for row in matches}
    if len(codes)!=1:
        return None,receipt
    row=matches[0]
    return {'code':row['Code'],'quote_id':row['QuoteID'],'board_category':'industry',
        'match_semantics':'exact_name_and_provider_industry_type'},receipt


def identify_sector(code,refresh=False):
    code=normalize_symbol(code)
    cached=_cache_get(_memberships,code,MEMBERSHIP_TTL,refresh)
    if cached and (cached.get('state')=='ready' or cached.get('cache_age_seconds',0)<60):return cached
    result={'symbol':code,'version':VERSION,'state':'unavailable','name':code,'memberships':[],
        'received_at':now(),'source':'Eastmoney stock industry classification',
        'membership_scope':'current_industry_only','historical_membership_verified':False,
        'concept_membership_complete':False,'execution_allowed':False,'receipts':[]}
    try:
        secid=('1.' if code.startswith('sh') else '0.' if code.startswith('sz') else '0.')+code[2:]
        payload,receipt=_request_json(_url('https://push2.eastmoney.com','/api/qt/stock/get',
            {'secid':secid,'fields':'f57,f58,f127'}))
        result['receipts'].append(receipt)
        row=payload.get('data')
        if payload.get('rc')!=0 or not isinstance(row,dict):raise ValueError('上游没有返回行业归属')
        if str(row.get('f57'))!=code[2:]:raise ValueError('行业归属返回股票代码不匹配')
        result['name']=str(row.get('f58') or code)
        industry=row.get('f127')
        if not isinstance(industry,str) or not industry.strip() or industry.strip() in {'-','--'}:
            raise ValueError('上游行业字段为空；不按股票名称推测板块')
        industry=industry.strip()
        if len(industry)>100:raise ValueError('行业名称长度异常')
        board,search_receipt=_resolve_industry(industry);result['receipts'].append(search_receipt)
        membership={'category':'industry','name':industry,'code':None,'quote_id':None,
            'membership_source':'Eastmoney stock/get f127','received_at':receipt['received_at'],
            'historical_membership_verified':False}
        if board:membership.update(board)
        else:membership['code_resolution_note']='没有唯一的精确同名行业板块代码；不使用相似名称替代'
        result.update(state='ready',memberships=[membership],received_at=now(),
            note='现行行业分类；概念、地域等归属未在此请求中验证，不回填过去的行业成员')
    except Exception as error:
        result['error_detail']=type(error).__name__+': '+str(error)[:220]
    _cache_put(_memberships,code,result)
    return result


def _native_candles(quote_id,period):
    if period not in PERIODS:raise ValueError('板块结构支持日线、30分钟和5分钟')
    if not re.fullmatch(r'(90\.BK\d{4,6}|1\.000001)',quote_id):raise ValueError('无效板块/基准代码')
    limit=1200 if period=='day' else 480
    url=_url('https://push2his.eastmoney.com','/api/qt/stock/kline/get',{
        'secid':quote_id,'fields1':'f1,f2,f3,f4,f5,f6',
        'fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt':PERIODS[period],'fqt':0,'end':'20500101','lmt':limit})
    payload,receipt=_request_json(url);data=payload.get('data')
    if payload.get('rc')!=0 or not isinstance(data,dict):raise ValueError('板块原生K线暂不可用')
    if str(data.get('code'))!=quote_id.split('.')[1]:raise ValueError('板块K线返回代码不匹配')
    rows=data.get('klines')
    if not isinstance(rows,list) or len(rows)>limit:raise ValueError('板块K线条数无效')
    if len(rows)<10:raise ValueError('板块有效K线少于10根，不能构造结构')
    point_now=datetime.now(CN);candles=[];last=None
    for raw in rows:
        fields=str(raw).split(',')
        if len(fields)<6:raise ValueError('板块K线字段缺失')
        stamp=datetime.fromisoformat(fields[0].replace(' ','T'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=CN)
        else:stamp=stamp.astimezone(CN)
        if period=='day':stamp=stamp.replace(hour=15,minute=0,second=0,microsecond=0)
        else:
            minute=stamp.hour*60+stamp.minute;step=PERIODS[period]
            if not any(start<minute<=end and (minute-start)%step==0 for start,end in ((570,690),(780,900))):
                raise ValueError('板块分钟K线不在对应周期的闭合时间网格')
        if stamp.date()>point_now.date():raise ValueError('板块返回未来日期K线')
        if period!='day' and stamp>point_now+timedelta(minutes=PERIODS[period]):raise ValueError('板块返回未来分钟K线')
        if last and stamp<=last:raise ValueError('板块K线时间重复或乱序')
        o,c,h,l,v=(_number(value) for value in fields[1:6])
        if any(value is None for value in (o,c,h,l,v)) or min(o,c,h,l)<=0 or v<0:
            raise ValueError('板块K线价格或成交量无效')
        if h<max(o,c,l) or l>min(o,c,h):raise ValueError('板块K线OHLC包络无效')
        candles.append(Candle(len(candles),o,h,l,c,stamp.isoformat(),v,stamp<=point_now));last=stamp
    metadata={**receipt,'source':'Eastmoney native industry index OHLC','adjustment':'provider_board_native',
        'volume_unit':'provider_native_unspecified','price_unit':'index_points',
        'source_rows':len(rows),'scope':f'provider_recent_{len(rows)}_native_{period}_bars',
        'source_retention_unlimited':False,'provider_total':data.get('dktotal'),
        'complete_history_verified':False,'split_adjustment_verified':False}
    return candles,metadata


def summarize_structure(panel):
    bars=[bar for bar in panel.get('bars',[]) if bar.get('is_closed') is not False]
    if len(bars)<10:raise ValueError('板块闭合K线不足')
    close=bars[-1]['close'];now_index=bars[-1].get('source_index',len(bars)-1)
    confirmed_segments=[s for s in panel.get('segments',[]) if s.get('state')=='confirmed' and s.get('basis_at',0)<=now_index]
    completed_strokes=[s for s in panel.get('strokes',[]) if s.get('state')=='confirmed' and s.get('basis_at',0)<=now_index]
    segment=confirmed_segments[-1] if confirmed_segments else None
    stroke=completed_strokes[-1] if completed_strokes else None
    centers=[c for c in panel.get('all_centers',[]) if c.get('end',0)<=now_index and
        c.get('available_at',c.get('basis_at',0))<=now_index and _number(c.get('zg')) is not None and _number(c.get('zd')) is not None]
    center=max(centers,key=lambda c:(c.get('end',0),c.get('rank',0))) if centers else None
    score=0;basis=[]
    for unit,label in ((segment,'最近确认线段'),(stroke,'最近完成笔')):
        if unit and unit.get('direction') in {'up','down'}:
            score+=1 if unit['direction']=='up' else -1
            basis.append(label+('向上' if unit['direction']=='up' else '向下'))
    position='missing_center'
    if center:
        position='above' if close>center['zg'] else 'below' if close<center['zd'] else 'inside'
        score+=1 if position=='above' else -1 if position=='below' else 0
        basis.append({'above':'收盘位于最近中枢核心上方','below':'收盘位于最近中枢核心下方','inside':'收盘仍在最近中枢核心内'}[position])
    evidence_count=sum(item is not None for item in (segment,stroke,center))
    label='偏强' if evidence_count>=2 and score>=2 else '偏弱' if evidence_count>=2 and score<=-2 else '震荡' if center and position=='inside' else '不明'
    def unit_summary(unit):
        return {key:unit.get(key) for key in ('id','direction','state','start','end','start_price','end_price','basis_at')} if unit else None
    return {'label':label,'score':score,'score_range':[-3,3],'score_semantics':'方向与中枢位置的证据计数，不是上涨概率',
        'basis':basis,'evidence_count':evidence_count,'price_position':position,
        'latest_segment':unit_summary(segment),'latest_stroke':unit_summary(stroke),
        'center':{key:center.get(key) for key in ('id','rank','start','end','zd','zg','available_at')} if center else None,
        'evidence_age_bars':{'segment':now_index-segment['basis_at'] if segment and isinstance(segment.get('basis_at'),int) else None,
            'stroke':now_index-stroke['basis_at'] if stroke and isinstance(stroke.get('basis_at'),int) else None,
            'center':now_index-center['available_at'] if center and isinstance(center.get('available_at'),int) else None},
        'evidence_note':'使用最近已完成结构；确认线段可能滞后，形成中端点不升级为方向确认',
        'closed_count':len(bars),'price':close,'data_as_of':bars[-1].get('date_cn'),
        'definition_mode':'declared_structure_proxy','strict_original_equivalence_proven':False,
        'confirm_level':'closed_native_board_candles','trigger_level':'lower_timeframe_trigger_not_verified',
        'signal_confirmation_claim':'not inferred from quote changes or ranking'}


def _return_comparison(board,bmark,period):
    left={b.closed_at:b.close for b in board if b.closed};right={b.closed_at:b.close for b in bmark if b.closed}
    common=sorted(set(left)&set(right))
    if len(common)<21:return {'state':'insufficient','matched_closed_bars':len(common),'lookback_bars':20}
    end=common[-1];start=common[-21];a=left[end]/left[start]-1;b=right[end]/right[start]-1
    return {'state':'ready','board_return_20':a,'benchmark_return_20':b,'excess_return_20':a-b,
        'matched_closed_bars':len(common),'lookback_bars':20,'period':period,'start':start,'end':end,
        'benchmark':'sh000001','meaning':'同时间原生收盘价的20根收益对照；独立于缠论强弱证据'}


def sector_strength(code,period='day',refresh=False):
    code=normalize_symbol(code)
    if period not in PERIODS:raise ValueError('板块结构支持日线、30分钟和5分钟')
    key=(code,period);cached=_cache_get(_strengths,key,STRENGTH_TTL,refresh)
    if cached:return cached
    membership=identify_sector(code,refresh=refresh)
    result={'symbol':code,'name':membership['name'],'period':period,'version':VERSION,
        'state':'unavailable','membership':membership,'boards':[],'received_at':now(),
        'definition_mode':'declared_structure_proxy','execution_allowed':False,
        'historical_membership_verified':False,'ranking_only_is_not_chan_strength':True}
    if membership['state']!='ready':
        result['error_detail']=membership.get('error_detail','股票行业归属暂不可用');return result
    for member in membership['memberships'][:2]:
        board={'code':member.get('code'),'name':member['name'],'category':member['category'],
            'state':'unavailable','quote':None,'structure':None,'relative_performance':None}
        if not member.get('quote_id'):
            board['error_detail']=member.get('code_resolution_note','行业板块代码未核实')
            result['boards'].append(board);continue
        try:
            candles,metadata=_native_candles(member['quote_id'],period)
            closed=[bar for bar in candles if bar.closed]
            if len(closed)<10:raise ValueError('板块闭合K线不足10根')
            from web.realtime_panel import make_panel
            # The generic engine accepts exchange-prefixed identities. The
            # input is the board's own OHLC; this identity is used only for IDs,
            # exactly as global-index panels do, never for fetching stock data.
            metadata.update(board_code=member['code'],board_quote_id=member['quote_id'],
                internal_engine_identity='sh000001_for_structure_ids_only')
            panel=make_panel('sh000001',period,closed,datetime.now(CN),metadata,
                reuse_structure=False,record_observations=False)
            structure=summarize_structure(panel)
            board.update(state='ready',structure=structure,source=metadata['source'],provenance=metadata,
                data_as_of=structure['data_as_of'],quote={'price':candles[-1].close,'is_closed':candles[-1].closed,
                    'change_pct':(candles[-1].close/candles[-2].close-1)*100 if len(candles)>1 else None,
                    'received_at':metadata['received_at'],'meaning':'板块K线收盘/形成中价格，不是逐笔报价'})
            benchmark=_cache_get(_benchmarks,period,STRENGTH_TTL,refresh)
            if benchmark is None:
                bmarks,bmeta=_native_candles('1.000001',period)
                benchmark={'candles':bmarks,'metadata':bmeta};_cache_put(_benchmarks,period,benchmark,3)
            board['relative_performance']=_return_comparison(candles,benchmark['candles'],period)
        except Exception as error:
            board['error_detail']=type(error).__name__+': '+str(error)[:220]
        result['boards'].append(board)
    result['state']='ready' if any(board['state']=='ready' for board in result['boards']) else 'membership_only'
    result['note']='当前行业归属和板块自身闭合K线结构；没有跨周期确认时不升级大级别买点'
    _cache_put(_strengths,key,result)
    return result
