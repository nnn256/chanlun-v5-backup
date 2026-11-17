"""Nonempty causal replay, extrema-oracle isolation and T+1 study semantics."""
from dataclasses import replace
from datetime import date, timedelta
import math
import unittest
from unittest.mock import patch

from chanmodel.model import Candle
from chanmodel.intraday_research import IntradayConfig, IntradayResearchSession, evaluate_intraday
from chanmodel.v2.series import session_closes


def fixture_bars(count=48):
    result=[];day=date(2026,11,2)
    while len(result)<count:
        if day.weekday()<5:
            for stamp in session_closes(day,'5m'):
                i=len(result);c=100+5*math.sin(i/12)+2*math.sin(i/3)
                result.append(Candle(i,c,c+.2,c-.2,c,stamp.isoformat(),100000))
                if len(result)>=count:break
        day+=timedelta(days=1)
    return result


class ScriptedReference:
    def __init__(self, scripts, reviewed=True):self.scripts=scripts;self.bars=[];self.reviewed=reviewed
    def append(self,bar):
        self.bars.append(bar)
        return self.scripts.get(bar.pos,[])
    def snapshot(self,*args):
        signals=[]
        for events in self.scripts.values():
            for e in events:
                if e.get('state')=='structure_complete':
                    signals.append({'id':e['id'],'state':'structure_complete' if self.reviewed else 'needs_review',
                                    'rule_audit':{'passed':self.reviewed}})
        return {'signals':signals}


def completion(index=2,side='buy',anchor=1):
    return {'id':'native:'+side,'event':'structure_completed','state':'structure_complete',
            'anchor':anchor,'rank':1,'native_type':'1','side':side,'observed_index':index}


class IntradayRules(unittest.TestCase):
    def session(self, scripts, config=None, reviewed=True):
        with patch('chanmodel.intraday_research.ReferenceSession',return_value=ScriptedReference(scripts,reviewed)):
            return IntradayResearchSession('sh600000','5m',config or IntradayConfig(max_pivot_distance_pct=20))

    def test_only_completed_reviewed_structure_generates_alert(self):
        bars=fixture_bars(5)
        scripts={1:[{**completion(1), 'event':'appeared','state':'candidate'}],2:[completion()]}
        session=self.session(scripts)
        session.append(bars[0]);self.assertEqual(session.append(bars[1]),[])
        added=session.append(bars[2])
        self.assertEqual([e['event'] for e in added],['research_alert'])
        self.assertEqual(added[0]['available_time'],bars[2].closed_at)
        self.assertEqual(added[0]['pivot_time'],bars[1].closed_at)
        self.assertFalse(added[0]['execution_allowed'])
        rejected=self.session(scripts,reviewed=False)
        for bar in bars[:3]:rejected.append(bar)
        self.assertEqual(rejected.events[-1]['event'],'rejected')
        self.assertIn('local_geometry_not_reviewed_complete',rejected.events[-1]['rejection_reasons'])

    def test_invalidation_does_not_rewrite_or_repeat_prior_alert(self):
        bars=fixture_bars(5);session=self.session({2:[completion()]})
        for bar in bars[:3]:session.append(bar)
        original=session.snapshot()['events']
        boundary=bars[1].low
        broken=replace(bars[3],open=boundary,high=boundary+.1,low=boundary-1,close=boundary-.5)
        events=session.append(broken)
        self.assertEqual(events[-1]['event'],'invalidated')
        self.assertEqual(events[-1]['available_at'],3)
        self.assertEqual(session.events[:len(original)],original)
        self.assertEqual(session.snapshot()['active_signals'],[])
        self.assertEqual(session.append(replace(bars[4],open=boundary,high=boundary+.1,low=boundary-1,close=boundary-.5)),[])

    def test_earlier_session_and_delayed_confirmations_are_rejected(self):
        bars=fixture_bars(50)
        session=self.session({48:[completion(48,anchor=1)]})
        for bar in bars[:49]:session.append(bar)
        self.assertIn('pivot_from_an_earlier_session',session.events[-1]['rejection_reasons'])
        session=self.session({15:[completion(15,anchor=1)]})
        for bar in bars[:16]:session.append(bar)
        self.assertIn('confirmation_delay_exceeds_profile',session.events[-1]['rejection_reasons'])

    def test_forming_and_off_session_candles_never_advance_engine(self):
        s=self.session({});bar=fixture_bars(1)[0]
        with self.assertRaisesRegex(ValueError,'forming'):s.append(replace(bar,closed=False))
        with self.assertRaisesRegex(ValueError,'session grid'):s.append(replace(bar,closed_at='2026-11-02T12:00:00+08:00'))
        self.assertEqual(s.snapshot()['processed_bars'],0)

    def test_missing_native_rows_do_not_understate_confirmation_delay(self):
        full=fixture_bars(20)
        bars=[replace(full[0],pos=0),replace(full[1],pos=1),replace(full[15],pos=2)]
        session=self.session({2:[completion()]})
        for bar in bars:session.append(bar)
        self.assertEqual(session.events[-1]['confirmation_delay_trading_minutes'],70)
        self.assertIn('confirmation_delay_exceeds_profile',session.events[-1]['rejection_reasons'])

    def test_later_geometry_disagreement_withdraws_active_alert(self):
        bars=fixture_bars(5)
        scripts={2:[completion()],3:[{**completion(3),'event':'revised'}]}
        session=self.session(scripts)
        for bar in bars[:3]:session.append(bar)
        session.reference.reviewed=False
        added=session.append(bars[3])
        self.assertEqual(added[0]['event'],'withdrawn')
        self.assertEqual(added[0]['withdrawal_reason'],'local_geometry_review_no_longer_complete')
        self.assertFalse(session.snapshot()['active_signals'])

    def test_real_native_nonempty_alert_prefix_is_immutable_under_future_append(self):
        # A fixed synthetic teaching path is visibly identified as synthetic.
        bars=fixture_bars(650)
        config=IntradayConfig(max_confirmation_delay_minutes=240,max_pivot_distance_pct=10,same_session_pivot=False)
        session=IntradayResearchSession('sh600000','5m',config,'synthetic_teaching')
        for bar in bars[:450]:session.append(bar)
        earlier=session.snapshot()['events']
        self.assertTrue(any(e['event']=='research_alert' for e in earlier),'causality test must not compare empty event lists')
        for bar in bars[450:]:session.append(bar)
        self.assertEqual(earlier,[e for e in session.events if e['available_at']<450])
        snapshot=session.snapshot();snapshot['events'].clear()
        self.assertTrue(session.events)


class IntradayEvaluation(unittest.TestCase):
    def test_next_open_and_session_extreme_are_distinct(self):
        bars=fixture_bars()
        bars[1]=replace(bars[1],open=98,high=99,low=97,close=98)
        bars[2]=replace(bars[2],open=99,high=100,low=98,close=99)
        bars[3]=replace(bars[3],open=100,high=101,low=99,close=100)
        events=[{'id':'5m:buy','signal_id':'buy','event':'research_alert','side':'buy',
                 'anchor':1,'available_at':2,'available_time':bars[2].closed_at,'invalidation':97}]
        result=evaluate_intraday(bars,events,slippage_bps=0)
        row=result['rows'][0]
        self.assertEqual(row['fill_price'],100)
        self.assertEqual(row['daily_extreme'],min(b.low for b in bars))
        self.assertNotEqual(row['fill_price'],row['daily_extreme'])
        self.assertEqual(row['fill_time'],'2026-11-02T09:45:00+08:00')
        self.assertFalse(row['buy_same_day_resale_allowed'])

    def test_future_high_low_changes_labels_but_never_alert_or_fill(self):
        bars=fixture_bars();event={'signal_id':'sell','event':'research_alert','side':'sell',
            'anchor':0,'available_at':2,'available_time':bars[2].closed_at,'invalidation':bars[0].high}
        first=evaluate_intraday(bars,[event],slippage_bps=0)['rows'][0]
        changed=bars.copy();changed[30]=replace(changed[30],high=150,low=50)
        later=evaluate_intraday(changed,[event],slippage_bps=0)['rows'][0]
        self.assertEqual(first['fill_price'],later['fill_price'])
        self.assertNotEqual(first['daily_extreme'],later['daily_extreme'])
        self.assertEqual(event['available_at'],2)
        self.assertEqual(later['sell_inventory_assumption'],'preexisting_T1_eligible_holdings')

    def test_last_bar_or_missing_next_bar_is_never_backfilled(self):
        bars=fixture_bars();event={'signal_id':'buy','event':'research_alert','side':'buy',
            'anchor':46,'available_at':47,'available_time':bars[47].closed_at,'invalidation':bars[46].low}
        row=evaluate_intraday(bars,[event])['rows'][0]
        self.assertEqual(row['evaluation_state'],'no_same_session_next_bar')
        missing=bars[:4]+[replace(b,pos=i) for i,b in enumerate(bars[5:],4)]
        event.update(anchor=1,available_at=3,available_time=bars[3].closed_at)
        row=evaluate_intraday(missing,[event])['rows'][0]
        self.assertEqual(row['evaluation_state'],'missing_next_native_bar')

    def test_lunch_gap_uses_first_afternoon_bar_open_not_1230(self):
        bars=fixture_bars();event={'signal_id':'buy','event':'research_alert','side':'buy',
            'anchor':20,'available_at':23,'available_time':bars[23].closed_at,'invalidation':1}
        row=evaluate_intraday(bars,[event],slippage_bps=0)['rows'][0]
        self.assertEqual(row['fill_time'],'2026-11-02T13:00:00+08:00')

    def test_incomplete_session_does_not_claim_exact_daily_low_or_high(self):
        full=fixture_bars();bars=[replace(b,pos=i) for i,b in enumerate(full[1:])]
        event={'signal_id':'buy','event':'research_alert','side':'buy',
            'anchor':1,'available_at':2,'available_time':bars[2].closed_at,'invalidation':1}
        row=evaluate_intraday(bars,[event],slippage_bps=0)['rows'][0]
        self.assertIsNotNone(row['fill_price'])
        self.assertEqual(row['session_extreme_state'],'incomplete_native_session')
        self.assertIsNone(row['daily_extreme'])

    def test_future_window_with_missing_native_bar_is_not_a_complete_horizon(self):
        full=fixture_bars();bars=full[:5]+[replace(b,pos=i) for i,b in enumerate(full[6:],5)]
        event={'signal_id':'sell','event':'research_alert','side':'sell',
            'anchor':1,'available_at':2,'available_time':bars[2].closed_at,'invalidation':200}
        row=evaluate_intraday(bars,[event],slippage_bps=0)['rows'][0]
        self.assertEqual(row['future_labels']['3']['state'],'missing_native_bar_in_forward_window')


if __name__=='__main__':unittest.main()
