"""Benchmark-index structures and complete industry-board snapshots."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from chanmodel.model import Candle
from web.compute_budget import ByteCache
from web import market_gateway as mg

CN = timezone(timedelta(hours=8))
INDEXES = OrderedDict([
    ('sh000001', ('上证指数', '000001.SH')),
    ('sz399001', ('深证成指', '399001.SZ')),
    ('sz399006', ('创业板指', '399006.SZ')),
    ('sh000688', ('科创50', '000688.SH')),
    ('sh000300', ('沪深300', '000300.SH')),
    ('sh000905', ('中证500', '000905.SH')),
    ('sh000852', ('中证1000', '000852.SH')),
])
GLOBAL_INDEXES = OrderedDict([
    ('^DJI', '道琼斯工业指数'), ('^GSPC', '标普500'), ('^IXIC', '纳斯达克综合指数'),
    ('^FTSE', '富时100'), ('^NSEI', '印度Nifty 50'), ('^NDX', '纳斯达克100'),
    ('^BSESN', '印度Sensex'), ('^N225', '日经225'), ('^HSI', '恒生指数'),
    ('^GDAXI', '德国DAX'), ('^FCHI', '法国CAC40'), ('^KS11', '韩国KOSPI'),
    ('^AXJO', '澳洲ASX200'),
])
YAHOO_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/'
INDUSTRY_URL = 'https://push2.eastmoney.com/api/qt/clist/get'
INDUSTRY_HOSTS = ('https://push2.eastmoney.com', 'https://push2delay.eastmoney.com',
                  'https://48.push2.eastmoney.com')
INDUSTRY_PAGE_SIZE = 500
MAX_INDUSTRY_BOARDS = 10000
MAX_INDEX_BARS = 30000
INDUSTRY_PARAMS = {'po': 1, 'np': 1, 'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                   'fltt': 2, 'invt': 2, 'fid': 'f3', 'fs': 'm:90+t:2',
                   'fields': 'f12,f14,f2,f3'}
_lock = threading.RLock()
_market_cache = None
_industry_cache = None
_panel_cache = ByteCache(max_bytes=8 * 1024 * 1024, max_entries=1)
_panel_cached_at = 0.0
_panel_cache_key = None


def normalize_index_code(value):
    code = str(value).strip()
    if re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)', code, re.I):
        digits, market = code.split('.')
        code = market.lower() + digits
    elif re.fullmatch(r'\d{6}', code):
        code = ('sz' if code.startswith('399') else 'sh') + code
    elif code.startswith('^'):
        code = code.upper()
    else:
        code = code.lower()
    if code in GLOBAL_INDEXES or re.fullmatch(r'(?:sh|sz|bj)\d{6}', code):
        return code
    raise ValueError('指数代码请输入 sh000001、000001.SH 或已配置的全球代码（例如 ^GSPC）')


def _index_name(code):
    if code in GLOBAL_INDEXES:
        return GLOBAL_INDEXES[code]
    if code in INDEXES:
        return INDEXES[code][0]
    return code.upper()


def _number(value):
    if value in (None, '', '-', '--'):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _yahoo_payload(code, range_, interval, timeout=12, *, period1=None, period2=None):
    params={'interval':interval,'includePrePost':'false','events':'div,splits'}
    if period1 is not None and period2 is not None:
        params.update(period1=int(period1),period2=int(period2))
    else:
        params['range']=range_
    url = YAHOO_URL + urllib.parse.quote(code, safe='') + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (compatible; LiangceResearch/3.0)',
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    payload = json.loads(raw)
    chart = payload.get('chart') or {}
    if chart.get('error'):
        raise ValueError(str(chart['error'])[:180])
    result = (chart.get('result') or [None])[0]
    if not isinstance(result, dict):
        raise ValueError('Yahoo指数接口没有返回数据')
    return result, raw


def global_index_quote(code):
    result, _ = _yahoo_payload(code, '5d', '1d')
    meta = result.get('meta') or {}
    quote = ((result.get('indicators') or {}).get('quote') or [{}])[0]
    closes = quote.get('close') or []
    valid = [_number(value) for value in closes]
    valid = [value for value in valid if value is not None and value > 0]
    if not valid:
        raise ValueError('全球指数接口未返回有效收盘价')
    price = valid[-1]
    previous = valid[-2] if len(valid) > 1 else _number(meta.get('chartPreviousClose'))
    timestamp = (result.get('timestamp') or [])[-1:]
    zone_name = meta.get('exchangeTimezoneName') or 'UTC'
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, TypeError):
        zone = timezone.utc
    bar_at = datetime.fromtimestamp(timestamp[0], zone).isoformat() if timestamp else None
    return {'code': code, 'name': _index_name(code), 'market_group': '全球指数', 'period': 'day',
            'state': 'ready', 'price': price, 'previous_close': previous,
            'change_pct': (price / previous - 1) * 100 if previous else None,
            'latest_bar_at': bar_at, 'received_at': datetime.now(CN).isoformat(timespec='seconds'),
            'source': 'Yahoo Finance public chart', 'source_as_of': meta.get('regularMarketTime'),
            'coverage_claim': 'latest provider daily quote'}


def _local_index_quotes():
    symbols = [value[1] for value in INDEXES.values()]
    try:
        result = mg.fetch_level1_indices(symbols)
    except Exception as error:
        result = {}
        failure = type(error).__name__ + ': ' + str(error)[:160]
    else:
        failure = '行情源没有返回该指数快照'
    received = datetime.now(CN).isoformat(timespec='seconds')
    rows = []
    for code, (name, symbol) in INDEXES.items():
        quote = result.get(symbol)
        if quote:
            rows.append({'code': code, 'name': name, 'symbol': symbol, 'market_group': 'A股指数',
                         'period': 'day', 'state': 'ready', 'price': _number(quote.get('price')),
                         'previous_close': _number(quote.get('prevClose')),
                         'change_pct': _number(quote.get('changePercent')),
                         'latest_bar_at': quote.get('updated_at') or None, 'received_at': received,
                         'source': quote.get('source') or 'stock-dashboard market gateway',
                         'coverage_claim': 'latest provider quote'})
        else:
            rows.append({'code': code, 'name': name, 'symbol': symbol, 'market_group': 'A股指数',
                         'period': 'day', 'state': 'unavailable', 'source': 'stock-dashboard market gateway',
                         'received_at': received, 'error_detail': failure,
                         'coverage_claim': 'latest provider quote'})
    return rows


def _eastmoney_page(page):
    params = {**INDUSTRY_PARAMS, 'pn': page, 'pz': INDUSTRY_PAGE_SIZE}
    query = urllib.parse.urlencode(params)
    urls = [host + '/api/qt/clist/get?' + query for host in INDUSTRY_HOSTS]
    body = mg.sd._get_first_ok(urls, timeout=8, retries=1,
        referer='https://quote.eastmoney.com/',
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
                 'Accept': 'application/json'})
    response = json.loads(body)
    data = response.get('data')
    if response.get('rc') != 0 or not isinstance(data, dict):
        raise ValueError('Eastmoney行业接口响应不完整')
    return data


def _eastmoney_industries():
    records = []
    digests = []
    expected = None
    page = 1
    while True:
        data = _eastmoney_page(page)
        rows = data.get('diff') or []
        if not isinstance(rows, list):
            raise ValueError('Eastmoney行业分页不是数组')
        try:
            total = int(data['total'])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('Eastmoney未声明行业总数，无法验证全量') from error
        if expected is None:
            expected = total
        elif total != expected:
            raise ValueError('Eastmoney分页期间行业总数发生变化')
        if expected < 0 or expected > MAX_INDUSTRY_BOARDS:
            raise ValueError('行业总数超过配置上限')
        records.extend(rows)
        digests.append(hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
        if len(records) >= expected:
            break
        if not rows:
            raise ValueError('行业分页提前结束')
        page += 1
    codes = [str(row.get('f12', '')).strip() for row in records if isinstance(row, dict)]
    if len(records) != expected or len(codes) != len(records) or not all(codes) or len(set(codes)) != expected:
        raise ValueError('行业分页缺行或代码重复，拒绝标记全量')
    boards = []
    for row in records:
        price = _number(row.get('f2'))
        change = _number(row.get('f3'))
        boards.append({'code': str(row['f12']), 'name': str(row['f14']), 'price': price,
                       'change_pct': change, 'source': 'Eastmoney industry board'})
    boards.sort(key=lambda item: item['change_pct'] if item['change_pct'] is not None else -math.inf,
                reverse=True)
    return {'state': 'ready', 'source': 'Eastmoney industry board', 'received_at': datetime.now(CN).isoformat(timespec='seconds'),
            'count': len(boards), 'provider_total': expected, 'pages_fetched': page, 'complete': True,
            'boards': boards, 'source_response_sha256': hashlib.sha256(''.join(digests).encode()).hexdigest(),
            'completeness_semantics': 'all pages matched the provider-declared total; all board codes are unique',
            'timestamp_semantics': '本地获取时间；上游不提供可核验的逐行业快照时间'}


def _sina_industry_directory(error):
    raw = mg.sd.http('http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php',
                     gbk=True, timeout=8, retries=1, referer='https://finance.sina.com.cn/')
    body = raw.split('=', 1)[1].strip().rstrip(';') if '=' in raw else raw.strip()
    data = json.loads(body)
    if not isinstance(data, dict) or not data:
        raise ValueError('新浪行业目录为空')
    boards = []
    for key, value in data.items():
        fields = str(value).split(',')
        if len(fields) < 2 or not fields[1].strip():
            continue
        try:
            change = _number(fields[5]) if len(fields) > 5 else None
        except (ValueError, TypeError):
            change = None
        boards.append({'code': str(fields[0] or key), 'name': fields[1].strip(), 'price': None,
                       'change_pct': change, 'source': '新浪行业涨跌快照' if change is not None else '新浪行业目录'})
    if not boards:
        raise ValueError('新浪行业目录没有可识别的板块')
    boards.sort(key=lambda item: item['name'])
    quoted=sum(row['change_pct'] is not None for row in boards)
    return {'state': 'ready' if quoted else 'directory_only',
            'source': '新浪行业涨跌快照' if quoted else '新浪行业目录',
            'received_at': datetime.now(CN).isoformat(timespec='seconds'), 'count': len(boards),
            'provider_total': None, 'pages_fetched': 1, 'complete': False, 'boards': boards,
            'quote_rows': quoted, 'quote_completeness': 'change_pct_only' if quoted else 'directory_only',
            'price_semantics': '新浪接口返回行业涨跌幅和成分领涨信息，不提供行业指数点位',
            'error_detail': '东方财富行业行情暂不可用（' + str(error)[:100] + '）；' + ('使用新浪行业涨跌快照' if quoted else '显示新浪目录，报价留空'),
            'completeness_semantics': f'显示新浪响应返回的{len(boards)}条行业记录；新浪未提供声明总数，无法确认分类目录是否完整',
            'timestamp_semantics': '仅记录本地接收时间；新浪未提供上游快照时刻'}


def industry_boards(force=False):
    global _industry_cache
    now = time.monotonic()
    with _lock:
        if not force and _industry_cache and now - _industry_cache[0] < 60:
            return {**_industry_cache[1], 'cache_age_seconds': round(now - _industry_cache[0], 1)}
    try:
        value = _eastmoney_industries()
    except Exception as east_error:
        try:
            value = _sina_industry_directory(east_error)
        except Exception as sina_error:
            value = {'state': 'unavailable', 'source': 'Eastmoney / Sina',
                     'received_at': datetime.now(CN).isoformat(timespec='seconds'), 'count': 0,
                     'provider_total': None, 'pages_fetched': 0, 'complete': False, 'boards': [],
                     'error_detail': f'Eastmoney: {type(east_error).__name__}; Sina: {type(sina_error).__name__}',
                     'timestamp_semantics': '没有行情数据时不生成占位值'}
    with _lock:
        _industry_cache = (time.monotonic(), value)
    return value


def _global_index_candles(code, period, now):
    if period == 'day':
        range_, interval, duration = 'max', '1d', None
    elif period == '30m':
        range_, interval, duration = '1mo', '30m', 1800
    elif period == '5m':
        range_, interval, duration = '5d', '5m', 300
    else:
        raise ValueError('全球指数结构支持日线、30分钟和5分钟')
    if period=='day':
        reference,_=_yahoo_payload(code,'5d','1d')
        reference_meta=reference.get('meta') or {}
        first_trade=reference_meta.get('firstTradeDate')
        if not isinstance(first_trade,(int,float)) or not math.isfinite(first_trade):
            raise ValueError('Yahoo未声明指数最早历史日期，无法请求全历史')
        result,raw=_yahoo_payload(code,None,interval,45,period1=int(first_trade),
                                  period2=int(now.timestamp())+86400)
        range_='max'
    else:
        result, raw = _yahoo_payload(code, range_, interval, timeout=12)
    meta = result.get('meta') or {}
    quote = ((result.get('indicators') or {}).get('quote') or [{}])[0]
    fields = {key: quote.get(key) or [] for key in ('open', 'high', 'low', 'close', 'volume')}
    stamps = result.get('timestamp') or []
    try:
        zone = ZoneInfo(meta.get('exchangeTimezoneName') or 'UTC')
    except (ZoneInfoNotFoundError, TypeError):
        zone = timezone.utc
    regular_end = ((meta.get('currentTradingPeriod') or {}).get('regular') or {}).get('end')
    candles = []
    for index, stamp in enumerate(stamps):
        values = {key: (items[index] if index < len(items) else None) for key, items in fields.items()}
        try:
            o, h, l, c = (float(values[key]) for key in ('open', 'high', 'low', 'close'))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) and value > 0 for value in (o, h, l, c)):
            continue
        if h < max(o, c, l) or l > min(o, c, h):
            continue
        local = (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=stamp)).astimezone(zone)
        if duration is None:
            if local.weekday()>=5:continue
            closed = (regular_end is not None and now.timestamp() >= regular_end) or local.date() < now.astimezone(zone).date()
            close_at = local.replace(hour=16, minute=0, second=0, microsecond=0)
        else:
            closed = stamp + duration <= now.timestamp()
            close_at = local + timedelta(seconds=duration)
        volume = _number(values['volume'])
        candles.append(Candle(len(candles), o, h, l, c, close_at.isoformat(), volume, closed))
    if len(candles) < 10:
        raise ValueError('全球指数结构至少需要10根有效K线')
    if len(candles) > MAX_INDEX_BARS:
        candles = [Candle(i, bar.open, bar.high, bar.low, bar.close, bar.closed_at, bar.volume, bar.closed)
                   for i, bar in enumerate(candles[-MAX_INDEX_BARS:])]
    return candles, {'source': 'Yahoo Finance public chart endpoint', 'adjustment': 'provider_index_native',
                     'price_unit': meta.get('currency') or 'provider_native', 'volume_unit': 'provider_native_unspecified',
                     'scope': 'provider_max_daily_history' if range_ == 'max' else f'provider_{range_}_window',
                     'source_response_sha256': hashlib.sha256(raw).hexdigest(),
                     'source_retention_unlimited': False, 'exchange': meta.get('fullExchangeName')}


def _local_index_candles(code, period, now):
    from web import tdx_provider
    if tdx_provider.enabled():
        candles, metadata = tdx_provider.fetch_index(code, period, now)
    else:
        name = _index_name(code)
        tdx_code = INDEXES.get(code, (name, code[2:] + '.' + code[:2].upper()))[1]
        import market_gateway as gateway
        period_name = {'day': '1D', '5m': '5m', '30m': '30m'}[period]
        payload = gateway.fetch_symbol_klines(tdx_code, period_name)
        rows = payload.get('klines') or []
        if not rows:
            raise ValueError('没有可用的真实指数K线；请配置TDX /api/index/all数据源')
        from web.realtime_panel import provider_bars
        candles = provider_bars(rows, period, now)
        metadata = {'source': 'stock-dashboard market gateway', 'adjustment': 'provider_index_native',
                    'price_unit': 'CNY', 'volume_unit': 'provider_native_unspecified',
                    'scope': 'provider_recent_window', 'source_retention_unlimited': False,
                    'quality_note': '当前数据源只提供近期K线，不能标成上市以来全历史'}
    if len(candles) < 10:
        raise ValueError('指数行情少于10根有效K线，无法可靠构造结构')
    if len(candles) > MAX_INDEX_BARS:
        candles = [Candle(i, bar.open, bar.high, bar.low, bar.close, bar.closed_at, bar.volume, bar.closed)
                   for i, bar in enumerate(candles[-MAX_INDEX_BARS:])]
        metadata = {**metadata, 'scope': 'provider_latest_30000_bars', 'truncated': True}
    return candles, metadata


def index_panel(raw_code, period='day', refresh=False):
    global _panel_cached_at, _panel_cache_key
    code = normalize_index_code(raw_code)
    if period not in {'day', '30m', '5m'}:
        raise ValueError('指数结构目前支持日线、30分钟和5分钟')
    key = (code, period)
    now_monotonic = time.monotonic()
    ttl = 10 if _is_trading_hours(datetime.now(CN)) else 60
    with _lock:
        compressed = _panel_cache.get(key) if not refresh and _panel_cache_key == key and now_monotonic - _panel_cached_at < ttl else None
    if compressed:
        return json.loads(__import__('gzip').decompress(compressed))
    now = datetime.now(CN)
    candles, metadata = _global_index_candles(code, period, now) if code in GLOBAL_INDEXES else _local_index_candles(code, period, now)
    from web.realtime_panel import make_panel
    # The Chan engine accepts exchange-prefixed symbol identities. A global
    # ticker is mapped only for internal structure IDs; the public panel keeps
    # the actual ticker and its Yahoo provenance.
    engine_code = 'sh000001' if code in GLOBAL_INDEXES else code
    engine_period = 'global_day' if code in GLOBAL_INDEXES and period == 'day' else period
    panel = make_panel(engine_code, engine_period, candles, now, metadata, reuse_structure=True, record_observations=False)
    panel.update(name=_index_name(code), symbol=code, period=period, label=period,
                 market_group='全球指数' if code in GLOBAL_INDEXES else 'A股指数',
                 source_kind='live_index_panel', execution_allowed=False)
    panel['coverage']['claim'] = metadata.get('scope', 'provider_recent_window')
    panel['coverage']['first_bar_at'] = panel['bars'][0]['date_cn'] if panel.get('bars') else None
    panel['coverage']['returned_bars'] = len(candles)
    panel['coverage']['source_retention_unlimited'] = False
    packed = __import__('gzip').compress(json.dumps(panel, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode(), compresslevel=1)
    with _lock:
        _panel_cache.clear()
        _panel_cache.put(key, packed)
        _panel_cache_key = key
        _panel_cached_at = time.monotonic()
    return panel


def _is_trading_hours(now):
    minute = now.hour * 60 + now.minute
    return now.weekday() < 5 and (555 <= minute <= 690 or 780 <= minute <= 900)


def market_context(force=False):
    global _market_cache
    now = time.monotonic()
    with _lock:
        if not force and _market_cache and now - _market_cache[0] < 15:
            return {**_market_cache[1], 'cache_age_seconds': round(now - _market_cache[0], 1)}
    rows = []
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix='market-context') as pool:
        futures = {pool.submit(global_index_quote, code): code for code in GLOBAL_INDEXES}
        try:
            rows.extend(_local_index_quotes())
        except Exception as error:
            for code, (name, symbol) in INDEXES.items():
                rows.append({'code': code, 'name': name, 'symbol': symbol, 'market_group': 'A股指数',
                             'period': 'day', 'state': 'unavailable', 'source': 'stock-dashboard market gateway',
                             'error_detail': type(error).__name__})
        for future, code in futures.items():
            try:
                rows.append(future.result())
            except Exception as error:
                rows.append({'code': code, 'name': _index_name(code), 'market_group': '全球指数',
                             'period': 'day', 'state': 'unavailable', 'source': 'Yahoo Finance public chart',
                             'received_at': datetime.now(CN).isoformat(timespec='seconds'),
                             'error_detail': type(error).__name__ + ': ' + str(error)[:120]})
    industries = industry_boards(force=force)
    value = {'received_at': datetime.now(CN).isoformat(timespec='seconds'), 'indices': rows,
             'index_catalog': {'a_share': len(INDEXES), 'global': len(GLOBAL_INDEXES), 'configured_total': len(rows),
                               'semantics': '常用指数目录；A股可输入其他交易所指数代码；不是全球交易所全集'},
             'industries': industries, 'execution_allowed': False}
    with _lock:
        _market_cache = (time.monotonic(), value)
    return value
