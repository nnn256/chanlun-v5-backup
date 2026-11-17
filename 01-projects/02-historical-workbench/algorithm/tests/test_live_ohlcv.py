from datetime import datetime, timedelta
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from chanmodel.tdx_data import CN
from chanmodel.model import Candle
from chanmodel.v2.series import Series
from workbench import live, reference_service
from workbench import incremental


def response(today=True):
    dates=[]; date=datetime(2026,11,9,tzinfo=CN)
    while len(dates)<80:
        if date.weekday()<5:dates.append(date)
        date-=timedelta(days=1)
    rows=[]
    for i,date in enumerate(reversed(dates)):
        price=10000+int(1000*math.sin(i/6))
        rows.append(dict(Time=date.replace(hour=15).isoformat(),Open=price,High=price+150,
                         Low=price-100,Close=price+50,Volume=1234))
    if today:rows.append(dict(Time='2026-11-10T15:00:00+08:00',Open=11000,High=11200,Low=10900,Close=11100,Volume=900))
    return {'count':len(rows),'list':rows,'meta':{'source':'tdx','type':'day'}}


class LiveOHLCV(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        incremental.clear_memory();live.CACHE.clear()
        self.incremental_root=patch.object(incremental,'ROOT',Path(self.tmp.name)/'live-sessions')
        self.incremental_root.start();self.addCleanup(self.incremental_root.stop)
        self.scope=patch.multiple(live,STATE=Path(self.tmp.name));self.scope.start();self.addCleanup(self.scope.stop)
        self.ref=patch.object(reference_service,'STATE',Path(self.tmp.name));self.ref.start();self.addCleanup(self.ref.stop)

    def acquire(self, data=None, observed='2026-11-10T11:20:00+08:00', received=None, period='day'):
        data=copy.deepcopy(data if data is not None else response())
        raw=json.dumps({'code':0,'data':data}).encode()
        receipt={'requested_at':observed,'received_at':received or observed,
                 'response_sha256':hashlib.sha256(raw).hexdigest()}
        with patch.object(live,'TdxClient') as client:
            client.return_value.request_retry.return_value=(data,receipt,raw)
            closed,rows,receipt=live.acquire('bj920010',period)
            client.return_value.request_retry.assert_called_once_with('/api/kline-all/tdx',
                {'code':'bj920010','type':live.PERIODS[period],'limit':live.TAIL_LIMIT},attempts=live.LIVE_REQUEST_ATTEMPTS)
            client.return_value.quotes.assert_not_called()
        bars=list(closed)
        for row in rows:
            if not row['is_closed']:bars.append(Candle(len(bars),row['open'],row['high'],row['low'],row['close'],row['closed_at'],row['volume'],False))
        return Series('bj920010',period,'unadjusted',tuple(bars),'tdx_live_ohlcv',receipt['response_sha256']),receipt,raw

    def bundle(self, acquired):
        series,receipt,_=acquired
        return live.build_live({'symbol':'bj920010','code':'920010','name':'测试','exchange':'bj'},
                               {'day':series},{'day':receipt})

    def test_november_10_forming_candle_is_visible_with_actual_ohlcv(self):
        bundle=self.bundle(self.acquire()); panel=bundle['chart']['panels'][0]
        self.assertEqual(bundle['summary']['last_date'],'2026-11-10')
        self.assertEqual([panel['bars'][-1][k] for k in ['open','high','low','close','volume']], [11,11.2,10.9,11.1,90000])
        self.assertFalse(panel['bars'][-1]['is_closed'])
        self.assertTrue(bundle['summary']['live']['forming'])
        self.assertEqual(panel['confirmed_through'],'2026-11-09T15:00:00+08:00')
        self.assertEqual(live.audit_live_panel(panel)['compared_rows'],81)

    def test_intrabar_price_change_cannot_change_confirmed_engine_or_cache_identity(self):
        before=self.bundle(self.acquire())
        data=response();data['list'][-1].update(High=1000000,Close=900000)
        after=self.bundle(self.acquire(data,observed='2026-11-10T11:25:00+08:00'))
        a=before['evidence']['reference_reports']['day'];b=after['evidence']['reference_reports']['day']
        self.assertEqual(a['input_sha256'],b['input_sha256'])
        self.assertEqual(a['base'],b['base']);self.assertEqual(a['signals'],b['signals'])
        self.assertNotEqual(before['summary']['price'],after['summary']['price'])
        self.assertEqual(a['input_audit']['bars_used'],80)
        self.assertTrue(all(s['available_at']<80 for s in b['signals']))

    def test_closed_bar_enters_engine_only_after_a_post_close_request(self):
        lag=self.bundle(self.acquire(observed='2026-11-10T14:59:59+08:00',received='2026-11-10T15:00:02+08:00'))
        self.assertTrue(lag['summary']['live']['forming'])
        closed=self.bundle(self.acquire(observed='2026-11-10T15:00:02+08:00'))
        self.assertFalse(closed['summary']['live']['forming'])
        self.assertEqual(closed['evidence']['reference_reports']['day']['input_audit']['bars_used'],81)

    def test_missing_today_or_weekend_never_creates_a_synthetic_bar(self):
        for observed in ['2026-11-10T11:20:00+08:00','2026-11-14T10:00:00+08:00','2026-11-10T00:01:00+08:00']:
            bundle=self.bundle(self.acquire(response(False),observed))
            self.assertEqual(bundle['summary']['last_date'],'2026-11-09')
            self.assertFalse(bundle['summary']['live']['latest_session_is_today'])
            self.assertEqual(len(bundle['chart']['panels'][0]['bars']),80)

    def test_future_session_is_rejected(self):
        data=response();data['list'][-1]['Time']='2026-11-11T15:00:00+08:00'
        with self.assertRaisesRegex(ValueError,'future session'):self.acquire(data)

    def test_forming_minute_bar_preserves_ohlc_but_future_interval_is_rejected(self):
        data=response(False);data['meta']['type']='minute30'
        data['list']=[dict(data['list'][-1],Time='2026-11-10T10:00:00+08:00'),
                      dict(data['list'][-1],Time='2026-11-10T10:30:00+08:00')];data['count']=2
        series,_,_=self.acquire(data,observed='2026-11-10T10:21:00+08:00',period='30m')
        self.assertEqual([b.closed for b in series.bars],[True,False])
        data['list'][-1]['Time']='2026-11-10T11:00:00+08:00'
        with self.assertRaisesRegex(ValueError,'尚未开始'):self.acquire(data,observed='2026-11-10T10:21:00+08:00',period='30m')

    def test_raw_receipt_corruption_fails_audit(self):
        bundle=self.bundle(self.acquire());panel=bundle['chart']['panels'][0]
        panel['bars'][-1]['close']=11.15
        with self.assertRaisesRegex(ValueError,'不一致'):live.audit_live_panel(panel)

    def test_first_bootstrap_persists_then_warm_live_refresh_does_not_replay_history(self):
        with patch.multiple(live,STATE=Path(self.tmp.name)/'state'), patch('workbench.incremental.ROOT',Path(self.tmp.name)/'state/live-sessions'):
            data=response();raw=json.dumps({'code':0,'data':data}).encode()
            receipt={'requested_at':'2026-11-10T11:20:00+08:00','received_at':'2026-11-10T11:20:00+08:00',
                     'response_sha256':hashlib.sha256(raw).hexdigest()}
            with patch.object(live,'TdxClient') as client:
                client.return_value.request_retry.return_value=(data,receipt,raw)
                first=live.live_stock('bj920010','day',full=True,fresh=True)
            self.assertTrue(first['summary']['live']['engine_rebuilt'])
            self.assertEqual(first['summary']['live']['confirmed_history_bars'],80)
            live.CACHE.clear();incremental.clear_memory()
            tail_data={**response(),'list':response()['list'][-live.TAIL_LIMIT:]}
            tail_data['count']=len(tail_data['list'])
            raw2=json.dumps({'code':0,'data':tail_data}).encode()
            receipt2={'requested_at':'2026-11-10T11:21:00+08:00','received_at':'2026-11-10T11:21:00+08:00',
                      'response_sha256':hashlib.sha256(raw2).hexdigest()}
            with patch.object(live,'TdxClient') as client:
                client.return_value.request_retry.return_value=(tail_data,receipt2,raw2)
                second=live.live_stock('bj920010','day',full=True,fresh=True)
                client.return_value.request_retry.assert_called_once_with('/api/kline-all/tdx',
                    {'code':'bj920010','type':'day','limit':live.TAIL_LIMIT},attempts=live.LIVE_REQUEST_ATTEMPTS)
            self.assertTrue(second['summary']['live']['session_resident'])
            self.assertTrue(second['summary']['live']['session_restored'])
            self.assertFalse(second['summary']['live']['engine_rebuilt'])
            self.assertEqual(second['summary']['live']['new_closed_bars'],0)
            self.assertEqual(second['evidence']['reference_reports']['day']['input_audit']['bars_used'],80)
            encoded=json.dumps(second,ensure_ascii=False,allow_nan=False)
            self.assertIn('checkpoint_sha256',encoded)
            self.assertNotIn('ReferenceSession',encoded)

    def test_corrupt_snapshot_is_quarantined_and_full_raw_history_rebuilt(self):
        with patch.multiple(live,STATE=Path(self.tmp.name)/'state'),patch('workbench.incremental.ROOT',Path(self.tmp.name)/'state/live-sessions'),patch('workbench.incremental.STATE',Path(self.tmp.name)/'state'):
            data=response();raw=json.dumps({'code':0,'data':data}).encode()
            receipt={'requested_at':'2026-11-10T11:20:00+08:00','received_at':'2026-11-10T11:20:00+08:00',
                     'response_sha256':hashlib.sha256(raw).hexdigest()}
            with patch.object(live,'TdxClient') as client:
                client.return_value.request_retry.return_value=(data,receipt,raw)
                first=live.live_stock('bj920010','day',full=True,fresh=True)
            live.CACHE.clear();incremental.clear_memory()
            path=incremental._checkpoint_path('bj920010','day')
            original=path.read_bytes();path.write_bytes(original[:-1]+bytes([original[-1]^1]))
            later={'requested_at':'2026-11-10T11:22:00+08:00','received_at':'2026-11-10T11:22:00+08:00',
                   'response_sha256':hashlib.sha256(raw).hexdigest()}
            with patch.object(live,'TdxClient') as client:
                client.return_value.request_retry.return_value=(data,later,raw)
                rebuilt=live.live_stock('bj920010','day',full=True,fresh=True)
                calls=[call.args[1] for call in client.return_value.request_retry.call_args_list]
            self.assertEqual(calls,[{'code':'bj920010','type':'day'}])
            self.assertTrue(rebuilt['summary']['live']['engine_rebuilt'])
            self.assertEqual(rebuilt['evidence']['reference_reports']['day']['signals'],
                             first['evidence']['reference_reports']['day']['signals'])
            self.assertEqual(len(list(path.parent.glob('session.bin.quarantined-*'))),1)

    def test_all_period_live_view_keeps_available_periods_when_one_intraday_source_fails(self):
        live.CACHE.clear()
        bar=Candle(0,10,11,9,10,'2026-11-10T15:00:00+08:00',100000)
        receipt={'requested_at':bar.closed_at,'received_at':bar.closed_at,'observed_at':bar.closed_at,'response_sha256':'hash'}
        meta={'checkpoint_sha256':'checkpoint'}
        def ingest(code,period,force_full_audit=False):
            if period=='30m':raise ValueError('minute history absent')
            return object(),[bar],receipt,meta
        connection=MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.return_value=None
        bundle={'available':True,'summary':{'live':{},'result_text':'daily'},'chart':{},'evidence':{}}
        with patch.object(live,'connect',return_value=connection), \
             patch.object(live,'_ingest',side_effect=[(object(),[bar],receipt,meta),ValueError('minute history absent'),(object(),[bar],receipt,meta)]), \
             patch.object(live,'build_live',return_value=bundle) as build:
            result=live.live_stock('sh600000','all',fresh=True)
        self.assertEqual(set(build.call_args.args[1]),{'day','5m'})
        self.assertEqual(result['summary']['live']['period_errors'],{'30m':'ValueError: minute history absent'})
        self.assertEqual(result['chart']['period_errors'],result['summary']['live']['period_errors'])

    def test_explicit_unavailable_intraday_request_is_not_silently_downgraded(self):
        live.CACHE.clear()
        connection=MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.return_value=None
        with patch.object(live,'connect',return_value=connection), \
             patch.object(live,'_ingest',side_effect=[(object(),[Candle(0,10,11,9,10,'2026-11-10T15:00:00+08:00',100000)],
                 {'requested_at':'2026-11-10T15:00:00+08:00','received_at':'2026-11-10T15:00:00+08:00','observed_at':'2026-11-10T15:00:00+08:00','response_sha256':'hash'},
                 {'checkpoint_sha256':'checkpoint'}),ValueError('minute history absent')]):
            with self.assertRaisesRegex(ValueError,'minute history absent'):
                live.live_stock('sh600000','30m',fresh=True)


if __name__=='__main__':unittest.main()
