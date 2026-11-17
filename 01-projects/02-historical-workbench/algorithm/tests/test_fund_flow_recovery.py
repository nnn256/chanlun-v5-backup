from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from workbench import research_context as flow


def payload(code='920000',market=0):
    return {'rc':0,'data':{'code':code,'market':market,'klines':[
        '2026-11-13,-218076,-189522,-521867,-218076,0,-7.45,-6.47,-17.83,-7.45,0,10.90,-1.80']}}


class Response:
    def __init__(self,value):self.raw=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,limit):return self.raw[:limit]


class FundFlowRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        context=patch.object(flow,'STATE',Path(self.temp.name));context.start();self.addCleanup(context.stop)
        with flow.LOCK:flow.CACHE.clear();flow.FLIGHTS.clear()
        context=patch.object(flow,'now_iso',return_value='2026-11-15T20:00:00+08:00')
        context.start();self.addCleanup(context.stop)

    def test_bj_market_mapping_validates_success_and_stores_actual_count(self):
        with patch.object(flow.urllib.request,'urlopen',return_value=Response(payload())) as request:
            value=flow.fund_flow('bj920000')
        self.assertEqual(value['state'],'ready')
        self.assertEqual(value['exchange_name'],'北交所')
        self.assertEqual(value['latest']['main_net_flow'],-218076)
        self.assertIn('secid=0.920000',request.call_args.args[0].full_url)
        self.assertEqual(value['rows_count'],1)
        self.assertEqual(value['history_coverage'],'latest_daily_observation')
        self.assertFalse(value['pit_history_proven'])
        self.assertEqual(value['rows'][0]['available_at'],value['received_at'])

    def test_network_failure_does_not_blacklist_exchange_and_manual_refresh_bypasses_error_cache(self):
        with patch.object(flow.urllib.request,'urlopen',side_effect=OSError('remote disconnected')) as request:
            first=flow.fund_flow('bj920000')
        self.assertEqual(first['status_code'],'upstream_error')
        self.assertEqual(request.call_count,3)
        self.assertNotIn('不支持',first['reason'])
        with patch.object(flow.urllib.request,'urlopen',return_value=Response(payload())) as request:
            cached=flow.fund_flow('bj920000')
            self.assertEqual(request.call_count,0)
            recovered=flow.fund_flow('bj920000',refresh=True)
        self.assertEqual(cached['state'],'unavailable')
        self.assertTrue(recovered['fresh_requested'])
        self.assertEqual(recovered['state'],'ready')

    def test_error_cache_expires_after_short_cooldown(self):
        with patch.object(flow,'_capture_flow',return_value={'state':'unavailable','rows':[]}), \
             patch.object(flow.time,'monotonic',return_value=100):
            flow.fund_flow('bj920000')
        with patch.object(flow,'_capture_flow',return_value={'state':'ready','rows':[]}) as request, \
             patch.object(flow.time,'monotonic',return_value=111):
            value=flow.fund_flow('bj920000')
        request.assert_called_once()
        self.assertEqual(value['state'],'ready')

    def test_verified_alternate_route_is_archived_with_prior_failure(self):
        with patch.object(flow.urllib.request,'urlopen',side_effect=[OSError('TLS remote closed'),Response(payload())]):
            value=flow.fund_flow('bj920000')
        self.assertEqual(value['source_transport'],'http')
        self.assertEqual(len(value['acquisition_attempts']),2)
        self.assertIn('TLS remote closed',value['acquisition_attempts'][0]['error'])
        saved=json.loads((Path(self.temp.name)/'research-context/bj920000/latest.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['source_url'],value['source_url'])

    def test_fresh_captures_in_same_second_have_distinct_receipts_and_immutable_cache(self):
        with patch.object(flow.urllib.request,'urlopen',side_effect=lambda *a,**k:Response(payload())):
            first=flow.fund_flow('bj920000',True);second=flow.fund_flow('bj920000',True)
            first['rows'].clear();second['latest']['main_net_flow']=999
            third=flow.fund_flow('bj920000')
        self.assertEqual(third['rows_count'],1)
        self.assertEqual(len(third['rows']),1)
        self.assertEqual(third['latest']['main_net_flow'],-218076)
        self.assertEqual(len(list((Path(self.temp.name)/'research-context/bj920000').glob('*.receipt.json'))),2)

    def test_concurrent_same_symbol_has_one_acquisition_and_isolated_results(self):
        started=threading.Event();release=threading.Event();joined=threading.Event()
        from concurrent.futures import Future
        class TrackingFuture(Future):
            def result(self,*args,**kwargs):
                if not self.done():joined.set()
                return super().result(*args,**kwargs)
        def capture(code):
            started.set();self.assertTrue(release.wait(3))
            return {'state':'ready','symbol':code,'rows':[{'net_flow':0}]}
        with patch.object(flow,'Future',TrackingFuture),patch.object(flow,'_capture_flow',side_effect=capture) as acquire:
            with ThreadPoolExecutor(max_workers=2) as pool:
                a=pool.submit(flow.fund_flow,'bj920000',True);self.assertTrue(started.wait(2))
                b=pool.submit(flow.fund_flow,'bj920000',True)
                try:self.assertTrue(joined.wait(2))
                finally:release.set()
                one,two=a.result(3),b.result(3)
        acquire.assert_called_once_with('bj920000')
        one['rows'].clear();self.assertEqual(two['rows'],[{'net_flow':0}])

    def test_no_records_validation_and_network_failure_have_different_codes(self):
        cases=[({'rc':0,'data':None},'no_records'),
               ({'rc':0,'data':{'code':'920000','market':0,'klines':[]}},'no_records'),
               (payload('920010'),'validation_error')]
        for value,expected in cases:
            with patch.object(flow.urllib.request,'urlopen',side_effect=lambda *a,**k:Response(value)):
                self.assertEqual(flow.fund_flow('bj920000',True)['status_code'],expected)
        for field,value in [('rc',False),('market',False)]:
            data=payload()
            if field=='rc':data['rc']=value
            else:data['data']['market']=value
            with self.assertRaises(ValueError):flow.normalize_flow(data,'bj920000','2026-11-15T20:00:00+08:00')

    def test_cache_obeys_bytes_and_entry_limits(self):
        with patch.object(flow,'MAX_CACHE_ENTRIES',1), \
             patch.object(flow,'_capture_flow',side_effect=lambda code:{'state':'ready','symbol':code,'rows':[]}):
            flow.fund_flow('bj920000');flow.fund_flow('sh600000')
        self.assertEqual(list(flow.CACHE),['sh600000'])
        with patch.object(flow,'MAX_ENTRY_BYTES',1),patch.object(flow,'_capture_flow',return_value={'state':'ready','rows':[]}):
            flow.fund_flow('bj920000',True)
        self.assertNotIn('bj920000',flow.CACHE)


if __name__=='__main__':unittest.main()
