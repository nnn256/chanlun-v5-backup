from datetime import datetime,timedelta,timezone
import json
import math
import unittest
from unittest.mock import patch

from workbench import market_context as market


def index_data(code,rows):
    return {'Count':len(rows),'List':rows}


class MarketContextTests(unittest.TestCase):
    def setUp(self):
        market.CACHE.clear();market.SNAPSHOT_CACHE.clear();market.INDEX_CACHE.clear();market.INDEX_STRUCTURE_CACHE.clear()

    def test_provider_local_index_time_without_timezone_is_explicitly_china_time(self):
        rows=[{'Time':'2026/11/11 15:00:00','Open':3600000,'High':3700000,'Low':3500000,'Close':3600000,'Volume':1200},
              {'Time':'2026/11/12 15:00:00','Open':3600000,'High':3800000,'Low':3500000,'Close':3780000,'Volume':1300}]
        with patch.object(market.TdxClient,'request_retry',return_value=(index_data('sh000001',rows),
            {'requested_at':'2026-11-13T09:00:00+08:00','received_at':'2026-11-13T09:00:00+08:00','response_sha256':'local-time'},b'{}')):
            result=market.index_snapshot('sh000001','上证指数')
        self.assertEqual(result['latest_bar_at'],'2026-11-12T15:00:00+08:00')
        self.assertEqual(result['bars'][-2]['time'],'2026-11-11T15:00:00+08:00')
    def test_tdx_index_snapshot_normalizes_protocol_units_and_computes_change(self):
        rows=[{'Time':'2026-11-11T15:00:00+08:00','Open':3600000,'High':3700000,'Low':3500000,'Close':3600000,'Volume':1200,'UpCount':100,'DownCount':90},
              {'Time':'2026-11-12T15:00:00+08:00','Open':3600000,'High':3800000,'Low':3500000,'Close':3780000,'Volume':1300,'UpCount':140,'DownCount':60}]
        receipt={'requested_at':'2026-11-13T09:00:00+08:00','received_at':'2026-11-13T09:00:00+08:00','response_sha256':'abc'}
        with patch.object(market.TdxClient,'request_retry',return_value=(index_data('sh000001',rows),receipt,b'{}')):
            result=market.index_snapshot('sh000001','上证指数')
        self.assertEqual(result['price'],3780);self.assertAlmostEqual(result['change_pct'],5)
        self.assertEqual((result['up_count'],result['down_count']),(140,60))
        self.assertEqual(result['latest_bar_at'],'2026-11-12T15:00:00+08:00')
        self.assertTrue(result['latest_bar_is_closed'])

    def test_full_history_snapshot_uses_index_all_and_keeps_unconfigured_index_codes(self):
        rows=[{'Time':f'2026-11-{day:02d}T15:00:00+08:00','Open':3600000,'High':3700000,
               'Low':3500000,'Close':3600000+day*100,'Volume':1200} for day in range(1,13)]
        receipt={'requested_at':'2026-11-13T09:00:00+08:00','received_at':'2026-11-13T09:00:01+08:00',
                 'response_sha256':'all-history'}
        with patch.object(market.TdxClient,'request_retry',return_value=({'count':len(rows),'list':rows},receipt,b'{}')) as request:
            result=market.index_snapshot('sh000688','科创50','day',limit=None,full_history=True)
        request.assert_called_once_with('/api/index/all',{'code':'sh000688','type':'day'},attempts=2)
        self.assertEqual(result['coverage_claim'],'provider all-history response')
        self.assertEqual(len(result['bars']),12)

    def test_index_structure_uses_closed_original_index_bars_and_returns_native_layers(self):
        origin=datetime.fromisoformat('2026-01-01T15:00:00+08:00');rows=[]
        for i in range(160):
            close=3600+math.sin(i/4)*45+math.sin(i/13)*80+i*.35
            rows.append({'time':(origin+timedelta(days=i)).isoformat(),'date':(origin+timedelta(days=i)).date().isoformat(),
                'is_closed':True,'open':close-5,'high':close+12,'low':close-13,'close':close,
                'volume_protocol_raw':None,'volume_unit':'provider_native_unspecified','amount_protocol_raw':None,
                'amount_unit':'provider_native_unscaled','up_count':None,'down_count':None})
        snapshot={'code':'sh000001','name':'上证指数','period':'day','price':rows[-1]['close'],
            'previous_close':rows[-2]['close'],'change_pct':0.2,'latest_bar_at':rows[-1]['time'],
            'latest_bar_is_closed':True,'latest_closed_bar_at':rows[-1]['time'],
            'observed_at':rows[-1]['time'],'received_at':rows[-1]['time'],'bars':rows,
            'source':'TDX index all-history API · raw unadjusted','coverage_claim':'provider all-history response',
            'source_response_sha256':'source-hash'}
        with patch.object(market,'index_snapshot',return_value=snapshot) as load:
            value=market.index_structure('sh000001','day')
        load.assert_called_once_with('sh000001','上证指数','day',limit=None,full_history=True)
        self.assertEqual(value['structure']['closed_bars'],160)
        self.assertEqual(value['panel']['bars'][-1]['source_index'],159)
        self.assertTrue(value['panel']['engine_provenance'])
        self.assertEqual(value['panel']['coverage']['claim'],'provider all-history response')
        self.assertIn('objects',value['panel']['signal_chart'])
        self.assertEqual(value['panel']['regime_research']['latest']['index'],159)
        self.assertEqual(value['panel']['regime_research']['as_of'],rows[-1]['time'])
        self.assertEqual(value['panel']['regime_research']['provenance']['closed_bars'],160)

    def test_global_index_structure_uses_yahoo_window_without_tdx_alias(self):
        stamp='2026-11-12T16:00:00-05:00'
        rows=[{'time':(datetime.fromisoformat(stamp)+timedelta(days=i)).isoformat(),'date':'2026-11-12',
            'is_closed':True,'open':4000+i,'high':4010+i,'low':3990+i,'close':4001+i,
            'volume':1000,'currency':'USD'} for i in range(40)]
        snapshot={'code':'^GSPC','name':'标普500','period':'day','price':rows[-1]['close'],
            'previous_close':rows[-2]['close'],'change_pct':0.1,'latest_bar_at':rows[-1]['time'],
            'latest_bar_is_closed':True,'latest_closed_bar_at':rows[-1]['time'],
            'received_at':'2026-11-13T09:00:00+08:00','bars':rows,
            'source':'Yahoo Finance public chart endpoint','coverage_claim':'provider 1mo range'}
        with patch.object(market,'global_index_snapshot',return_value=snapshot) as load:
            value=market.index_structure('^GSPC','day')
        load.assert_called_once_with('^GSPC','day',full_history=True)
        self.assertEqual(value['index']['source'],'Yahoo Finance public chart endpoint')
        self.assertEqual(value['structure']['closed_bars'],40)
        self.assertEqual(value['panel']['coverage']['claim'],'provider 1mo range')

    def test_intraday_index_breadth_does_not_require_a_daily_research_panel(self):
        for period in ['30m','5m']:
            with self.subTest(period=period):
                origin=datetime.fromisoformat('2026-11-02T10:00:00+08:00')
                rows=[]
                for i in range(40):
                    price=3600+math.sin(i/3)*20
                    rows.append({'time':(origin+timedelta(minutes=30*i)).isoformat(),
                        'date':'2026-11-02','is_closed':True,'open':price,'high':price+2,
                        'low':price-2,'close':price+1})
                snapshot={'code':'sh000001','name':'上证指数','period':period,'bars':rows,
                    'source':'TDX fixture index','received_at':rows[-1]['time'],'up_count':50,'down_count':20}
                with patch.object(market,'index_snapshot',return_value=snapshot):
                    value=market.index_structure('sh000001',period)
                self.assertEqual(value['panel']['period'],period)
                self.assertNotIn('regime_research',value['panel'])
                self.assertEqual(value['structure']['closed_bars'],40)

    def test_global_daily_full_history_requests_provider_max_range(self):
        stamp=1735689600
        payload={'chart':{'result':[{'meta':{'exchangeTimezoneName':'America/New_York','currency':'USD',
            'fullExchangeName':'SNP','regularMarketTime':stamp,'currentTradingPeriod':{'regular':{'end':stamp+86400}}},
            'timestamp':[stamp],'indicators':{'quote':[{'open':[100.0],'high':[102.0],'low':[99.0],
                'close':[101.0],'volume':[1000]}]}}],'error':None}}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self):return json.dumps(payload).encode()
        with patch.object(market.urllib.request,'urlopen',return_value=Response()) as request:
            result=market.global_index_snapshot('^GSPC','day',full_history=True)
        query=market.urllib.parse.parse_qs(market.urllib.parse.urlsplit(request.call_args.args[0].full_url).query)
        self.assertEqual((query['range'],query['interval']),(['max'],['1d']))
        self.assertEqual(result['coverage_claim'],'provider maximum daily history response')

    def test_current_daily_index_bar_is_marked_forming_until_scheduled_close(self):
        rows=[{'Time':'2026-11-12T15:00:00+08:00','Open':3600000,'High':3700000,'Low':3500000,'Close':3600000,'Volume':1200},
              {'Time':'2026-11-13T15:00:00+08:00','Open':3600000,'High':3750000,'Low':3550000,'Close':3720000,'Volume':500}]
        receipt={'requested_at':'2026-11-13T11:30:00+08:00','received_at':'2026-11-13T11:30:00+08:00','response_sha256':'abc'}
        with patch.object(market.TdxClient,'request_retry',return_value=(index_data('sh000001',rows),receipt,b'{}')):
            result=market.index_snapshot('sh000001','上证指数')
        self.assertEqual(result['price'],3720)
        self.assertFalse(result['latest_bar_is_closed'])
        self.assertEqual(result['latest_closed_bar_at'],'2026-11-12T15:00:00+08:00')
        self.assertFalse(result['bars'][-1]['is_closed'])

    def test_market_snapshot_reports_each_index_failure_without_fabricating_values(self):
        def request(path,params,attempts):
            if params['code']=='sz399001':raise OSError('index source down')
            rows=[{'Time':'2026-11-12T15:00:00+08:00','Open':3600000,'High':3700000,'Low':3500000,'Close':3600000,'Volume':1200,'UpCount':100,'DownCount':90}]
            receipt={'requested_at':'2026-11-13T09:00:00+08:00','received_at':'2026-11-13T09:00:00+08:00'}
            return index_data(params['code'],rows),receipt,b'{}'
        with patch.object(market.TdxClient,'request_retry',side_effect=request),patch.object(market,'GLOBAL_INDEXES',{}),patch.object(market,'_industries',return_value={'state':'unavailable','leaders':[]}):
            result=market.market_context(include_industries=False)
        failed=next(x for x in result['indices'] if x['code']=='sz399001')
        self.assertEqual(failed['state'],'unavailable');self.assertNotIn('price',failed)
        self.assertEqual(len(result['indices']),len(market.INDEXES))

    def test_sector_api_normalizes_only_returned_provider_rows(self):
        raw=json.dumps({'rc':0,'data':{'diff':[{'f12':'BK001','f14':'行业甲','f2':12.5,'f3':3.2,'f62':9000}]}}).encode()
        with patch.object(market,'_sector_request',return_value=({'diff':[{'f12':'BK001','f14':'行业甲','f2':12.5,'f3':3.2,'f62':9000}]},raw)):
            market.CACHE.clear();result=market._industries()
        self.assertEqual(result['state'],'ready');self.assertEqual(result['leaders'][0]['name'],'行业甲')
        self.assertEqual(result['leaders'][0]['change_pct'],3.2);self.assertEqual(result['count'],1)

    def test_sector_source_failure_without_cache_is_explicit(self):
        market.CACHE.clear()
        with patch.object(market,'_sector_request',side_effect=OSError('source blocked')):
            result=market._industries()
        self.assertEqual(result['state'],'unavailable');self.assertEqual(result['leaders'],[])

    def test_market_context_snapshot_uses_short_cache_and_period_is_validated(self):
        index={'code':'sh000001','name':'上证指数','state':'ready','latest_bar_at':'2026-11-12T15:00:00+08:00','up_count':10,'down_count':4}
        with patch.object(market,'_industries',return_value={'state':'unavailable'}),\
             patch.object(market,'index_snapshot',return_value=index),patch.object(market,'INDEXES',{'sh000001':'上证指数'}):
            market.SNAPSHOT_CACHE.clear()
            value=market.market_context('day',True);again=market.market_context('day',True)
            self.assertEqual(value['period'],'day');self.assertIn('cache_age_seconds',again)
            with self.assertRaisesRegex(ValueError,'period'):market.market_context('hour',True)

    def test_failed_index_refresh_uses_explicit_stale_last_good_value(self):
        old={'code':'sh000001','name':'上证指数','period':'day','state':'ready','price':3600,
             'latest_bar_at':'2026-11-12T15:00:00+08:00','up_count':12,'down_count':8}
        market.INDEX_CACHE[('sh000001','day')]=(market.time.monotonic()-60,old)
        with patch.object(market,'INDEXES',{'sh000001':'上证指数'}),\
             patch.object(market,'index_snapshot',side_effect=OSError('index source down')):
            first=market.market_context('day',False)
            first_age=first['indices'][0]['cache_age_seconds']
            market.SNAPSHOT_CACHE[('day',False)]=(market.time.monotonic()-21,first)
            result=market.market_context('day',False)
        self.assertEqual(result['indices'][0]['state'],'stale')
        self.assertEqual(result['indices'][0]['price'],3600)
        self.assertGreaterEqual(first_age,59)
        self.assertGreaterEqual(result['indices'][0]['cache_age_seconds'],first_age)


if __name__=='__main__':unittest.main()
