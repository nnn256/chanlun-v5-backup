"""Calendar reuse and label preparation must preserve causal research rules."""
from datetime import date,datetime,timedelta,timezone
import unittest
from unittest.mock import patch

import chanmodel.intraday_research as study
from chanmodel.model import Candle
from chanmodel.v2.series import CN,PERIODS,session_closes
from tests.test_intraday_research import ScriptedReference
from tools.verify_intraday_research import raw_session_evidence


class CalendarReuseTests(unittest.TestCase):
    def setUp(self):study._session_calendar.cache_clear()

    def test_cached_delay_equals_grid_count_across_lunch_weekend_and_timezone(self):
        cases=[('2026-11-05T11:25:00+08:00','2026-11-05T13:15:00+08:00'),
               ('2026-11-06T14:55:00+08:00','2026-11-09T09:45:00+08:00'),
               ('2026-11-06T02:25:00Z','2026-11-09T02:45:00Z'),
               ('2026-11-06T14:55:00+08:00','2026-11-06T14:00:00+08:00')]
        for period in ('1m','5m','15m','30m','60m'):
            for first,last in cases:
                start,end=(datetime.fromisoformat(x).astimezone(CN) for x in (first,last))
                day=start.date();expected=0
                while day<=end.date():
                    if day.weekday()<5:expected+=sum(start<s<=end for s in session_closes(day,period))
                    day+=timedelta(days=1)
                with self.subTest(period=period,first=first,last=last):
                    self.assertEqual(study._trading_minutes_between(first,last,period),expected*PERIODS[period])

    def test_one_session_grid_is_built_once_for_every_minute_append(self):
        grid=session_closes(date(2026,11,2),'1m')
        bars=[Candle(i,10,11,9,10,s.isoformat(),100) for i,s in enumerate(grid)]
        with patch.object(study,'ReferenceSession',return_value=ScriptedReference({})), \
             patch.object(study,'session_closes',wraps=session_closes) as calendar:
            session=study.IntradayResearchSession('sz300949','1m')
            for bar in bars:session.append(bar)
            self.assertEqual(calendar.call_count,1)
        self.assertEqual(session.snapshot()['processed_bars'],240)

    def test_calendar_cache_is_immutable_and_has_no_security_specific_data(self):
        sequence,lookup=study._session_calendar(date(2026,11,2),'1m')
        self.assertIsInstance(sequence,tuple)
        self.assertIsInstance(lookup,frozenset)
        self.assertEqual(sequence,tuple(session_closes(date(2026,11,2),'1m')))
        self.assertEqual(study._session_calendar.cache_info().maxsize,512)

    def test_multiple_alerts_share_complete_session_grid_and_keep_exact_fill_values(self):
        grid=session_closes(date(2026,11,2),'1m')
        bars=[Candle(i,10+i/100,11+i/100,9+i/100,10+i/100,s.isoformat(),100)
              for i,s in enumerate(grid)]
        events=[{'signal_id':str(i),'event':'research_alert','side':'buy' if i%2 else 'sell',
                 'anchor':i-1,'available_at':i,'available_time':bars[i].closed_at,
                 'invalidation':1 if i%2 else 100} for i in range(2,100)]
        with patch.object(study,'session_closes',wraps=session_closes) as calendar:
            result=study.evaluate_intraday(bars,events,'1m')
            self.assertEqual(calendar.call_count,1)
        self.assertEqual(result['summary']['alerts'],98)
        for event,row in zip(events,result['rows']):
            sign=1 if event['side']=='buy' else -1
            self.assertEqual(row['fill_price'],bars[event['available_at']+1].open*(1+sign*5/10000))
            self.assertEqual(row['daily_extreme'],min(b.low for b in bars) if sign==1 else max(b.high for b in bars))
            self.assertEqual(row['session_extreme_state'],'complete_native_session')

    def test_independent_raw_audit_groups_each_session_without_hiding_missing_bars(self):
        from dataclasses import replace
        full=[]
        for day in (date(2026,11,2),date(2026,11,3)):
            for stamp in session_closes(day,'5m'):
                full.append(Candle(len(full),10,11+len(full)/100,9,10,stamp.isoformat(),100))
        result=raw_session_evidence(full,'5m')
        self.assertEqual(len(result),2)
        self.assertTrue(all(x['complete'] for x in result.values()))
        self.assertEqual(result[date(2026,11,2)]['high'],max(b.high for b in full[:48]))
        missing=[replace(b,pos=i) for i,b in enumerate(full[:30]+full[31:])]
        result=raw_session_evidence(missing,'5m')
        self.assertFalse(result[date(2026,11,2)]['complete'])
        self.assertTrue(result[date(2026,11,3)]['complete'])


if __name__=='__main__':unittest.main()
