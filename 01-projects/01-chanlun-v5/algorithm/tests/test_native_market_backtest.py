import unittest

from chanmodel.model import Candle
from chanmodel.causal_portfolio import CostModel, simulate
from chanmodel.native_market_backtest import native_backtest_events
from chanmodel.reference_engine import ReferenceSession


class NativeMarketBacktestTests(unittest.TestCase):
    def bars(self):
        return [
            Candle(0, 10, 11, 8, 9, '2026-11-02T15:00:00+08:00', 100000),
            Candle(1, 9, 10, 7, 8, '2026-11-03T15:00:00+08:00', 100000),
            Candle(2, 8, 9, 7.5, 8.5, '2026-11-04T15:00:00+08:00', 100000),
            Candle(3, 8.5, 9, 7.5, 8.8, '2026-11-05T15:00:00+08:00', 100000),
        ]

    def test_candidate_is_not_backfilled_as_a_confirmation(self):
        events = [{'id': 'cp:2:3b:buy:0', 'event': 'appeared', 'state': 'candidate',
                   'observed_index': 1, 'observed_at': self.bars()[1].closed_at,
                   'anchor': 0, 'rank': 2, 'side': 'buy', 'native_type': '3b'}]
        result = native_backtest_events(events, self.bars())
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['confirmations'], [])

    def test_confirmation_uses_its_observed_index_and_native_level(self):
        bars = self.bars()
        events = [
            {'id': 'cp:2:3b:buy:0', 'event': 'appeared', 'state': 'candidate',
             'observed_index': 1, 'observed_at': bars[1].closed_at,
             'anchor': 0, 'rank': 2, 'side': 'buy', 'native_type': '3b'},
            {'id': 'cp:2:3b:buy:0', 'event': 'structure_completed', 'state': 'structure_complete',
             'observed_index': 2, 'observed_at': bars[2].closed_at,
             'anchor': 0, 'rank': 2, 'side': 'buy', 'native_type': '3b'},
            {'id': 'cp:2:3b:buy:0', 'event': 'withdrawn',
             'observed_index': 3, 'observed_at': bars[3].closed_at},
        ]
        result = native_backtest_events(events, bars)
        self.assertEqual(result['confirmations'][0]['observed_index'], 2)
        self.assertEqual(result['confirmations'][0]['rank'], 2)
        self.assertEqual(result['confirmations'][0]['class'], '3b_buy')
        self.assertEqual(result['confirmations'][0]['invalidation'], bars[0].low)
        withdrawal=next(e for e in result['events'] if e['event']=='withdrawn')
        self.assertEqual(withdrawal['side'], 'buy')

    def test_confirmation_withdrawal_revokes_signal_and_pivot_break_emits_invalidation(self):
        bars = self.bars()
        bars[3]=Candle(3,8.5,9,8.5,8.8,bars[3].closed_at,100000)
        events = [
            {'id': 'cp:1:1:buy:0', 'event': 'appeared', 'state': 'candidate',
             'observed_index': 1, 'observed_at': bars[1].closed_at,
             'anchor': 0, 'rank': 1, 'side': 'buy', 'native_type': '1'},
            {'id': 'cp:1:1:buy:0', 'event': 'structure_completed', 'state': 'structure_complete',
             'observed_index': 2, 'observed_at': bars[2].closed_at,
             'anchor': 0, 'rank': 1, 'side': 'buy', 'native_type': '1'},
            {'id': 'cp:1:1:buy:0', 'event': 'confirmation_withdrawn', 'state': 'candidate',
             'observed_index': 3, 'observed_at': bars[3].closed_at,
             'anchor': 0, 'rank': 1, 'side': 'buy', 'native_type': '1'},
        ]
        result = native_backtest_events(events, bars)
        lifecycle = [e['event'] for e in result['events']]
        self.assertIn('withdrawn', lifecycle)
        self.assertNotIn('invalidated',lifecycle)

    def test_first_pivot_break_is_retained_and_later_withdrawal_is_not_double_counted(self):
        bars=self.bars()
        bars.append(Candle(4,8.8,9,8.5,8.7,'2026-11-06T15:00:00+08:00',100000))
        events=[
            {'id':'cp:1:1:buy:0','event':'appeared','state':'candidate','observed_index':1,
             'observed_at':bars[1].closed_at,'anchor':0,'rank':1,'side':'buy','native_type':'1'},
            {'id':'cp:1:1:buy:0','event':'structure_completed','state':'structure_complete','observed_index':2,
             'observed_at':bars[2].closed_at,'anchor':0,'rank':1,'side':'buy','native_type':'1'},
            {'id':'cp:1:1:buy:0','event':'withdrawn','observed_index':4,
             'observed_at':bars[4].closed_at},
        ]
        result=native_backtest_events(events,bars)
        invalidation=next(e for e in result['events'] if e['event']=='invalidated')
        self.assertEqual(invalidation['observed_index'], 3)
        self.assertEqual(invalidation['invalidation_operator'], 'lt')
        self.assertNotIn('withdrawn',[event['event'] for event in result['events']])

    def test_extrema_index_matches_the_reference_first_strict_crossing(self):
        bars=self.bars();session=ReferenceSession('day',observe=True)
        for bar in bars:session.append(bar)
        events=[{'id':'s','event':'structure_completed','state':'structure_complete',
            'observed_index':0,'observed_at':bars[0].closed_at,'anchor':0,'rank':1,
            'side':'buy','native_type':'1'}]
        linear=native_backtest_events(events,bars)
        indexed=native_backtest_events(events,bars,session.extrema)
        self.assertEqual(indexed,linear)

    def test_missing_or_future_anchor_is_rejected(self):
        event = {'id': 'bad', 'event': 'structure_completed', 'state': 'structure_complete',
                 'observed_index': 2, 'observed_at': self.bars()[2].closed_at,
                 'anchor': 4, 'rank': 1, 'side': 'sell', 'native_type': '1'}
        with self.assertRaisesRegex(ValueError, 'anchor'):
            native_backtest_events([event], self.bars())

    def test_native_strict_pivot_can_be_touched_without_forcing_an_exit(self):
        bars=self.bars()
        bars[0]=Candle(0,10,11,10,10,'2026-11-02T15:00:00+08:00',100000)
        bars[1]=Candle(1,11,12,10,11,'2026-11-03T15:00:00+08:00',100000)
        event={'observed_index':0,'observed_at':bars[0].closed_at,'signal_id':'native','event':'confirmed',
               'side':'buy','rank':1,'class':'1_buy','invalidation':10,'invalidation_operator':'lt'}
        bars=bars[:2]
        result=simulate(bars,bars,[event],{bar.closed_at[:10]:bar.close for bar in bars},
                        cost=CostModel(slippage_bps=0),period='day',symbol='bj920002')
        self.assertTrue(any(order['state']=='filled' and order['side']=='buy' for order in result['orders']))
        self.assertFalse(any(order['side']=='sell' for order in result['orders']))
        self.assertIsNotNone(result['open_position'])


if __name__ == '__main__':
    unittest.main()

