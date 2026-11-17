"""Archive public flow observations without inventing historical availability."""
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
LOCK = threading.RLock()
CACHE = {}


def normalize_flow(payload, symbol, received_at):
    if not re.fullmatch(r'(sh|sz)\d{6}', symbol):
        raise ValueError('资金流接口当前只验证沪深股票')
    received = datetime.fromisoformat(received_at)
    if received.tzinfo is None:
        raise ValueError('资金流获取时间必须包含时区')
    if not isinstance(payload,dict):
        raise ValueError('资金流响应必须为对象')
    received = received.astimezone(CN)
    data = payload.get('data')
    if payload.get('rc') != 0 or not isinstance(data, dict):
        raise ValueError('资金流来源没有返回成功数据')
    expected_market = 1 if symbol.startswith('sh') else 0
    if str(data.get('code')) != symbol[2:] or data.get('market') != expected_market:
        raise ValueError('资金流来源证券身份不一致')
    klines = data.get('klines')
    if not isinstance(klines, list) or not klines:
        raise ValueError('资金流来源没有日历史记录')
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
    if symbol.startswith('bj'):
        return {'state': 'unavailable', 'symbol': symbol, 'rows': [],
                'reason': '未验证北交所个股资金流接口', 'execution_allowed': False}
    with LOCK:
        prior = CACHE.get(symbol)
        if not refresh and prior and time.monotonic() - prior[0] < 300:
            return {**prior[1], 'cache_age_seconds': round(time.monotonic() - prior[0], 1)}
    params = {'lmt': 100, 'klt': 101, 'secid': ('1.' if symbol.startswith('sh') else '0.') + symbol[2:],
              'fields1': 'f1,f2,f3,f7',
              'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63'}
    url = FLOW_URL + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('资金流响应过大')
        received_at = now_iso()
        digest = hashlib.sha256(raw).hexdigest()
        rows = normalize_flow(json.loads(raw), symbol, received_at)
        directory = STATE / 'research-context' / symbol
        if not (directory / (digest + '.json')).exists():
            atomic_bytes(directory / (digest + '.json'), raw)
        result = {'state': 'ready', 'symbol': symbol, 'source': 'Eastmoney daily fund-flow estimate',
                  'received_at': received_at, 'source_response_sha256': digest, 'rows': rows,
                  'latest': rows[-1], 'first_date': rows[0]['date'], 'last_date': rows[-1]['date'],
                  'rows_count': len(rows), 'pit_history_proven': False,
                  'usage': '仅本次获取后的研究证据；不回填到过去信号、也不视为真实持仓成本或确定买卖依据',
                  'execution_allowed': False}
        stamp=received_at.replace(':','').replace('+','_')
        atomic_bytes(directory / (digest + '-' + stamp + '.receipt.json'),
                     json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8'))
        atomic_bytes(directory / 'latest.json', json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (OSError, ValueError, TypeError, KeyError) as error:
        result = {'state': 'unavailable', 'symbol': symbol, 'rows': [],
                  'source': 'Eastmoney daily fund-flow estimate', 'received_at': now_iso(),
                  'reason': f'{type(error).__name__}: {error}', 'execution_allowed': False}
    with LOCK:
        CACHE[symbol] = (time.monotonic(), result)
    return result
