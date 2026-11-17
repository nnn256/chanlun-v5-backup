from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chanmodel.model import Candle
from chanmodel.tdx_data import CN
from workbench import intraday_monitor as bridge,monitor,store


class FixtureStudy:
    """Control only the research event source while testing live wiring."""
    def __init__(self,symbol,period,config,source):
        self.symbol=symbol;self.period=period;self.bars=[];self.events=[];self.active={}

    def append(self,bar):
        self.bars.append(bar)
        if bar.pos!=3:return []
        event={'id':self.period+':point','signal_id':'point','event':'research_alert','state':'local_structure_complete',
               'side':'sell','rank':1,'native_type':'1p','anchor':2,'pivot_price':11.0,
               'pivot_time':self.bars[2].closed_at,'available_at':3,'available_time':bar.closed_at,
               'invalidation':11,'invalidation_operator':'gt','execution_allowed':False}
        self.events.append(event);self.active['point']=event;return [event]

    def snapshot(self):return {'events':self.events,'active_signals':list(self.active.values())}


class IntradayMonitorBridgeTests(unittest.TestCase):
    def setUp(self):
        bridge.CACHE.clear()
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'monitor.sqlite3';store.initialize(self.db)
        self.patches=[patch.object(bridge,'IntradayResearchSession',FixtureStudy),
                      patch.object(monitor,'connect',lambda:store.connect(self.db))]
        for item in self.patches:item.start()
        self.record={'symbol':'sz000001','name':'fixture','code':'000001','exchange':'sz'}
        self.settings={'structure_mode':'intraday','intraday_period':'1m','refresh_history':False,'intraday_config':{}}

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        bridge.CACHE.clear();self.tmp.cleanup()

    def bars(self,n):
        start=datetime(2026,11,13,9,31,tzinfo=CN)
        return [Candle(i,10,11,9,10,(start+timedelta(minutes=i)).isoformat(),10000) for i in range(n)]

    def ingest(self,bars,received=None):
        receipt={'received_at':received or bars[-1].closed_at,'requested_at':received or bars[-1].closed_at}
        return object(),bars,receipt,{'rebuilt':False}

    def observe(self,bars,received=None):
        with patch('workbench.live._ingest',return_value=self.ingest(bars,received)):
            return monitor.structure_one(self.record,self.settings,bars[-1].closed_at)

    def test_warmup_silent_new_closed_bar_alerts_once_and_repeats_stay_silent(self):
        first=self.observe(self.bars(3));self.assertEqual(first['state'],'calculated')
        self.assertTrue(first['research_warmup']);self.assertTrue(first['suppress_notifications'])
        self.assertEqual(monitor.record_structure(first),[])
        bars=self.bars(4);bars.append(Candle(4,10,11,9,10,'2026-11-13T09:35:00+08:00',10000,False))
        second=self.observe(bars,'2026-11-13T09:34:30+08:00')
        self.assertEqual(second['latest_closed_bar_at'],'2026-11-13T09:34:00+08:00')
        self.assertFalse(second['suppress_notifications']);self.assertEqual(len(second['research_events']),1)
        self.assertEqual(len(monitor.record_structure(second)),1)
        again=self.observe(bars,'2026-11-13T09:34:40+08:00')
        self.assertEqual(again['research_events'],[])
        self.assertEqual(monitor.record_structure(again),[])
        with store.connect(self.db) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_alerts').fetchone()[0],1)

    def test_weekend_acquisition_does_not_publish_friday_event_as_live(self):
        first=self.observe(self.bars(3),'2026-11-15T12:00:00+08:00');monitor.record_structure(first)
        latest=self.observe(self.bars(4),'2026-11-15T12:01:00+08:00')
        self.assertFalse(latest['research_warmup']);self.assertTrue(latest['suppress_notifications'])
        self.assertEqual(monitor.record_structure(latest),[])
        with store.connect(self.db) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_alerts').fetchone()[0],0)

    def test_source_revision_rewarms_silently_instead_of_reissuing_history(self):
        baseline=self.observe(self.bars(4));monitor.record_structure(baseline)
        revised=self.bars(4);revised[0]=Candle(0,9.5,11,9,10,revised[0].closed_at,10000)
        result=self.observe(revised,'2026-11-13T09:35:00+08:00')
        self.assertTrue(result['research_warmup']);self.assertTrue(result['suppress_notifications'])
        self.assertEqual(monitor.record_structure(result),[])

    def test_native_session_rollover_expires_prior_day_points_without_deleting_ledger(self):
        for period,delta in [('1m',1),('5m',5)]:
            with self.subTest(period=period):
                bridge.CACHE.clear()
                with store.connect(self.db) as db:
                    db.execute('DELETE FROM monitor_structures');db.execute('DELETE FROM monitor_signals');db.execute('DELETE FROM monitor_alerts')
                self.settings['intraday_period']=period
                start=datetime(2026,11,13,9,30,tzinfo=CN)
                bars=[Candle(i,10,11,9,10,(start+timedelta(minutes=(i+1)*delta)).isoformat(),10000) for i in range(4)]
                first=self.observe(bars);monitor.record_structure(first)
                self.assertEqual(len(first['signals']),1)
                self.assertEqual(first['native_session'],'2026-11-13')
                monday=datetime(2026,11,16,9,30,tzinfo=CN)+timedelta(minutes=delta)
                bars.append(Candle(4,10,11,9,10,monday.isoformat(),10000))
                next_day=self.observe(bars,monday.isoformat())
                self.assertEqual(next_day['signals'],[])
                self.assertEqual(next_day['historical_active_count'],1)
                self.assertEqual(next_day['expired_signal_ids'],['intraday:'+period+':point'])
                self.assertEqual(monitor.record_structure(next_day),[])
                with store.connect(self.db) as db:
                    row=db.execute('SELECT state,payload FROM monitor_signals WHERE signal_id=?',('intraday:'+period+':point',)).fetchone()
                self.assertEqual(row['state'],'session_expired')
                self.assertIn('pivot_time',row['payload'])
                unchanged=self.observe(bars,(monday+timedelta(seconds=10)).isoformat())
                self.assertEqual(unchanged['signals'],[])
                self.assertEqual(unchanged['research_events'],[])
                self.assertEqual(monitor.record_structure(unchanged),[])


if __name__=='__main__':unittest.main()
