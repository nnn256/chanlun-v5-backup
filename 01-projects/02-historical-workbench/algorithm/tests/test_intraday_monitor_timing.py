from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workbench import monitor,store
from workbench import live
from chanmodel.tdx_intraday import normalize_intraday,fetch_intraday
from chanmodel.tdx_data import CN
from unittest.mock import Mock


class ObservationTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'monitor.sqlite3';store.initialize(self.db)
        self.patcher=patch.object(monitor,'connect',lambda:store.connect(self.db));self.patcher.start()

    def tearDown(self):
        self.patcher.stop();self.temp.cleanup()

    def sample(self,at='2026-11-13T10:10:00+08:00',state='awaiting_lower_confirmation',age=50):
        point={'id':'p','signal_id':'5m:p','state':state,'period':'5m','side':'sell','class':'first_sell',
               'price':12.0,'anchor':10,'available_time':'2026-11-13T10:00:00+08:00',
               'invalidation':12.0,'invalidation_operator':'gt','age_bars':age}
        return {'symbol':'sz000001','state':'calculated','as_of':at,'signals':[point]}

    def test_late_confirmation_of_old_pivot_alerts_once(self):
        baseline=self.sample();monitor.record_structure(baseline)
        confirmed=self.sample('2026-11-13T10:15:00+08:00','structure_complete')
        confirmed['signals'][0]['confirmed_at']=60
        confirmed['signals'][0]['confirmed_time']='2026-11-13T10:15:00+08:00'
        self.assertEqual(len(monitor.record_structure(confirmed)),1)
        self.assertEqual(monitor.record_structure(confirmed),[])
        with store.connect(self.db) as db:
            alert=json.loads(db.execute('SELECT payload FROM monitor_alerts').fetchone()[0])
        self.assertTrue(alert['lifecycle_transition'])
        self.assertEqual(alert['observed_at'],confirmed['as_of'])
        self.assertFalse(alert['execution_allowed'])

    def test_old_pivot_boundary_invalidation_is_not_silenced_by_age(self):
        monitor.record_structure(self.sample())
        invalid=self.sample('2026-11-13T10:20:00+08:00','invalidated',100)
        self.assertEqual(len(monitor.record_structure(invalid)),1)
        self.assertEqual(monitor.record_structure(invalid),[])

    def test_slow_old_snapshot_cannot_withdraw_newer_structure(self):
        newer=self.sample();monitor.record_structure(newer)
        old=self.sample('2026-11-13T10:05:00+08:00');old['signals']=[]
        self.assertEqual(monitor.record_structure(old),[])
        with store.connect(self.db) as db:
            state=db.execute('SELECT state FROM monitor_signals').fetchone()[0]
            saved=json.loads(db.execute('SELECT payload FROM monitor_structures').fetchone()[0])
        self.assertEqual(state,'awaiting_lower_confirmation')
        self.assertEqual(saved['as_of'],newer['as_of'])

    def test_unknown_historical_signal_does_not_alert_on_refresh(self):
        empty=self.sample();empty['signals']=[];monitor.record_structure(empty)
        self.assertEqual(monitor.record_structure(self.sample('2026-11-13T10:15:00+08:00')),[])

    def test_stale_or_invalid_quote_cannot_cross_new_structure_boundary(self):
        monitor.record_structure(self.sample())
        for time,price in [('2026-11-13T09:59:00+08:00',13),
                           ('2026-11-13T10:06:00+08:00',13),
                           ('2026-11-13T10:20:00',13),
                           ('2026-11-13T10:20:00+08:00',float('nan'))]:
            quote={'symbol':'sz000001','quote_status':'observed','price':price,'received_at':time}
            self.assertEqual(monitor.quote_invalidations([quote]),[])
        quote={'symbol':'sz000001','quote_status':'observed','price':13,'received_at':'2026-11-13T10:20:00+08:00'}
        crossing=monitor.quote_invalidations([quote])
        self.assertEqual(len(crossing),1)
        self.assertFalse(crossing[0]['quote_trade_freshness_proven'])
        self.assertEqual(crossing[0]['source_state'],'awaiting_lower_confirmation')
        self.assertTrue(crossing[0]['closed_bar_confirmation_required'])
        self.assertEqual(monitor.quote_invalidations([quote]),[])

    def test_receipt_after_structure_cannot_make_old_exchange_trade_current(self):
        monitor.record_structure(self.sample())
        quote={'symbol':'sz000001','quote_status':'observed','price':13,
               'received_at':'2026-11-13T10:20:00+08:00',
               'exchange_trade_timestamp':'2026-11-13T09:55:00+08:00'}
        self.assertEqual(monitor.quote_invalidations([quote]),[])

    def test_withdrawal_count_matches_durable_alert_and_reset_is_silent(self):
        monitor.record_structure(self.sample())
        absent=self.sample('2026-11-13T10:20:00+08:00');absent['signals']=[]
        self.assertEqual(len(monitor.record_structure(absent)),1)
        self.assertEqual(monitor.record_structure(absent),[])
        with store.connect(self.db) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_alerts').fetchone()[0],1)
        current=self.sample('2026-11-13T10:25:00+08:00');current['signals'][0]['signal_id']='5m:p2'
        current['suppress_notifications']=True;monitor.record_structure(current)
        absent['as_of']='2026-11-13T10:30:00+08:00';absent['suppress_notifications']=True
        self.assertEqual(monitor.record_structure(absent),[])
        with store.connect(self.db) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_alerts').fetchone()[0],1)

    def test_next_session_quote_does_not_invalidate_previous_intraday_alert_before_scan(self):
        value=self.sample();point=value['signals'][0]
        point.update(signal_id='intraday:1m:p',pivot_time='2026-11-13T09:55:00+08:00')
        monitor.record_structure(value)
        quote={'symbol':'sz000001','quote_status':'observed','price':13,
               'received_at':'2026-11-16T09:35:00+08:00'}
        self.assertEqual(monitor.quote_invalidations([quote]),[])


class NativeMinuteDataTests(unittest.TestCase):
    def test_one_minute_data_uses_native_ohlc_and_close_grid(self):
        client=Mock();fetch_intraday(client,'sz000001','minute1')
        client.request.assert_called_once_with('/api/kline-all/tdx',{'code':'sz000001','type':'minute1'})
        rows=[{'Time':'2026-11-13T09:31:00+08:00','Open':10000,'High':10100,
               'Low':9900,'Close':10050,'Volume':100},
              {'Time':'2026-11-13T09:32:00+08:00','Open':10050,'High':10200,
               'Low':10000,'Close':10100,'Volume':200}]
        data={'count':2,'list':rows,'meta':{'source':'tdx','type':'minute1'}}
        bars,display,quality=normalize_intraday(data,datetime(2026,11,13,9,31,30,tzinfo=CN),'minute1')
        self.assertEqual(len(bars),1)
        self.assertEqual((bars[0].open,bars[0].high,bars[0].low,bars[0].close),(10,10.1,9.9,10.05))
        self.assertFalse(display[-1]['is_closed'])
        self.assertEqual(quality['open_rows_excluded'],1)
        self.assertFalse(quality['session_gaps_padded'])
        self.assertEqual(live.PERIODS['1m'],'minute1')

if __name__=='__main__':unittest.main()
