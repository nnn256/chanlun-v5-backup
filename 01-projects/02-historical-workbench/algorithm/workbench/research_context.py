"""Archive public flow observations without inventing historical availability."""
from collections import OrderedDict
from concurrent.futures import Future
from datetime import date, datetime
import hashlib
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request

from chanmodel.tdx_data import CN, atomic_bytes, now_iso
from .store import STATE

FLOW_URL = 'https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get'
# These are verified routes for the same public vendor dataset. Archive the
# actual URL and earlier failures so one current record is never sold as history.
FLOW_ALTERNATE_URLS=('http://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get',
                     'https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get')
MARKET_ID={'sh':1,'sz':0,'bj':0}
EXCHANGE_NAMES={'sh':'沪市','sz':'深市','bj':'北交所'}
MAX_CACHE_BYTES=4*1024*1024
MAX_ENTRY_BYTES=256*1024
MAX_CACHE_ENTRIES=64
READY_TTL=300
ERROR_TTL=10
LOCK = threading.RLock()
CACHE = OrderedDict()
FLIGHTS = {}


class FlowDataError(ValueError):
    def __init__(self,status_code,message):
        super().__init__(message);self.status_code=status_code


def normalize_flow(payload, symbol, received_at):
    if not re.fullmatch(r'(sh|sz|bj)\d{6}', symbol):
        raise ValueError('股票代码格式错误')
    received = datetime.fromisoformat(received_at)
    if received.tzinfo is None:
        raise ValueError('资金流获取时间必须包含时区')
    if not isinstance(payload,dict):
        raise ValueError('资金流响应必须为对象')
    received = received.astimezone(CN)
    data = payload.get('data')
    if type(payload.get('rc')) is not int or payload['rc']!=0:
        raise FlowDataError('upstream_error','资金流供应商没有返回成功状态')
    if data is None:
        raise FlowDataError('no_records','资金流供应商本次未返回该证券记录')
    if not isinstance(data,dict):raise ValueError('资金流数据对象格式不正确')
    expected_market = MARKET_ID[symbol[:2]]
    if str(data.get('code')) != symbol[2:] or type(data.get('market')) is not int or data['market'] != expected_market:
        raise ValueError('资金流来源证券身份不一致')
    klines = data.get('klines')
    if not isinstance(klines,list):raise ValueError('资金流日记录不是列表')
    if not klines:raise FlowDataError('no_records','资金流供应商本次未返回该证券日历史记录')
    rows = []
    previous = None
    fields = ('net_flow', 'small_net_flow', 'medium_net_flow', 'large_net_flow',
              'super_large_net_flow', 'net_flow_pct', 'small_pct', 'medium_pct',
              'large_pct', 'super_large_pct', 'close', 'change_pct')
    for raw in klines:
        if not isinstance(raw,str):
            raise ValueError('资金流日记录必须为协议文本')
        parts = raw.split(',')
        if len(parts) != 13:
            raise ValueError('资金流字段数量与公开日线协议不一致')
        stamp = date.fromisoformat(parts[0])
        if stamp > received.date() or (previous is not None and stamp <= previous):
            raise ValueError('资金流日期重复、倒序或来自未来')
        values = [float(value) for value in parts[1:]]
        if not all(math.isfinite(value) for value in values) or values[-2] <= 0:
            raise ValueError('资金流字段存在无效数值')
        rows.append({'date': stamp.isoformat(), **dict(zip(fields, values)),
                     'main_net_flow':values[0],
                     'available_at': received_at,
                     'source': 'Eastmoney daily fund-flow estimate',
                     'availability_semantics': 'this response acquisition; historical publication time unverified'})
        previous = stamp
    return rows


def fund_flow(symbol, refresh=False):
    """Vendor flow is an estimate, and newly acquired vintage is not PIT data."""
    if not re.fullmatch(r'(sh|sz|bj)\d{6}', symbol):
        raise ValueError('股票代码格式错误')
    started=time.monotonic()
    with LOCK:
        prior = CACHE.get(symbol)
        if not refresh and prior and started-prior[0]<prior[1]:
            CACHE.move_to_end(symbol);cached=prior
        else:cached=None
        pending=FLIGHTS.get(symbol) if cached is None else None
        owner=cached is None and pending is None
        if owner:pending=Future();FLIGHTS[symbol]=pending
    if cached is not None:
        result=json.loads(cached[2]);result['cache_age_seconds']=round(started-cached[0],1)
        result['fresh_requested']=bool(refresh)
        return result
    if not owner:
        result=json.loads(pending.result());result['fresh_requested']=bool(refresh)
        result['shared_request']=True
        return result
    try:
        result=_capture_flow(symbol)
        raw=json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        with LOCK:
            CACHE.pop(symbol,None)
            if len(raw)<=min(MAX_ENTRY_BYTES,MAX_CACHE_BYTES):
                CACHE[symbol]=(time.monotonic(),READY_TTL if result['state']=='ready' else ERROR_TTL,raw)
                while len(CACHE)>MAX_CACHE_ENTRIES or sum(len(item[2]) for item in CACHE.values())>MAX_CACHE_BYTES:
                    CACHE.popitem(last=False)
        pending.set_result(raw)
        result['fresh_requested']=bool(refresh)
        return result
    except BaseException as exc:
        pending.set_exception(exc);raise
    finally:
        with LOCK:
            if FLIGHTS.get(symbol) is pending:FLIGHTS.pop(symbol,None)


def _capture_flow(symbol):
    exchange=symbol[:2]
    params = {'lmt': 100, 'klt': 101, 'secid': str(MARKET_ID[exchange])+'.'+symbol[2:],
              'ut':'b2884a393a59ad64002292a3e90d46a5',
              'fields1': 'f1,f2,f3,f7',
              'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63'}
    url = FLOW_URL + '?' + urllib.parse.urlencode(params)
    context={'symbol':symbol,'exchange':exchange,'exchange_name':EXCHANGE_NAMES[exchange],
        'source':'Eastmoney daily fund-flow estimate','provider_market':MARKET_ID[exchange],
        'source_url':url,'execution_allowed':False}
    attempts=[]
    try:
        last_error=None
        for origin in (FLOW_URL,*FLOW_ALTERNATE_URLS):
            url=origin+'?'+urllib.parse.urlencode(params)
            request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json',
                'Referer':'https://quote.eastmoney.com/'})
            started=time.monotonic()
            try:
                with urllib.request.urlopen(request,timeout=8) as response:
                    raw=response.read(4*1024*1024+1)
                if len(raw)>4*1024*1024:raise ValueError('资金流响应过大')
                received_at=now_iso()
                rows=normalize_flow(json.loads(raw),symbol,received_at)
                attempts.append({'url':url,'state':'ready','rows_count':len(rows),
                    'seconds':round(time.monotonic()-started,3)})
                context.update(source_url=url,source_transport=urllib.parse.urlsplit(url).scheme)
                break
            except (OSError,FlowDataError) as error:
                last_error=error
                attempts.append({'url':url,'state':'unavailable','error':f'{type(error).__name__}: {error}',
                    'seconds':round(time.monotonic()-started,3)})
        else:raise last_error
        digest = hashlib.sha256(raw).hexdigest()
        directory = STATE / 'research-context' / symbol
        if not (directory / (digest + '.json')).exists():
            atomic_bytes(directory / (digest + '.json'), raw)
        result = {**context,'state':'ready','status_code':'ready',
                  'received_at': received_at, 'source_response_sha256': digest, 'rows': rows,
                  'latest': rows[-1], 'first_date': rows[0]['date'], 'last_date': rows[-1]['date'],
                  'rows_count': len(rows), 'pit_history_proven': False,
                  'requested_rows':100,'history_coverage':('latest_daily_observation' if len(rows)==1 else 'available_daily_history'),
                  'acquisition_attempts':attempts,
                  'usage': '仅本次获取后的研究证据；不回填到过去信号、也不视为真实持仓成本或确定买卖依据',
                  'execution_allowed': False}
        stamp=received_at.replace(':','').replace('+','_')+'-'+str(time.time_ns())
        atomic_bytes(directory / (digest + '-' + stamp + '.receipt.json'),
                     json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8'))
        atomic_bytes(directory / 'latest.json', json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (OSError, ValueError, TypeError, KeyError) as error:
        status=error.status_code if isinstance(error,FlowDataError) else ('upstream_error' if isinstance(error,OSError) else 'validation_error')
        detail=f'{type(error).__name__}: {error}'
        reason=('资金流供应商连接失败，未取得本次数据；可重新获取' if status=='upstream_error'
                else str(error) if status=='no_records' else '资金流响应校验未通过，未采用该数据')
        result={**context,'state':'unavailable','status_code':status,'rows':[],'rows_count':0,
                'acquisition_attempts':attempts,
                'received_at':now_iso(),'reason':reason,'error_detail':detail,'retry_after_seconds':ERROR_TTL}
    return result
