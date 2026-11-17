from datetime import datetime, timedelta, timezone
import unittest

from chanmodel.regime_research import RegimeConfig, RegimeSession, analyze_regimes


CN = timezone(timedelta(hours=8))
FAST_CONFIG = RegimeConfig(
    ma_fast=3, ma_slow=5, slope_window=2, range_window=4,
    pressure_window=2, volume_window=2, cost_window=4,
    base_min_bars=2, watch_max_bars=20, drawdown_threshold=.10,
    runup_threshold=.10, near_extreme_pct=.03, base_range_pct=.20,
    weakening_ratio=.95,
)


def bars(closes, volumes=None, *, start=None, lows=None, highs=None):
    start = start or datetime(2026, 1, 5, 15, tzinfo=CN)
    volumes = volumes if volumes is not None else [100.] * len(closes)
    lows = lows if lows is not None else [value - .2 for value in closes]
    highs = highs if highs is not None else [value + .15 for value in closes]
    rows = []
    for index, (close, volume, low, high) in enumerate(zip(closes, volumes, lows, highs)):
        rows.append({'source_index': index, 'closed_at': (start + timedelta(days=index)).isoformat(),
                     'open': close - .1, 'high': high, 'low': low, 'close': close,
                     'volume': volume, 'is_closed': True})
    return rows


def declining_then_rising():
    return bars([100, 96, 92, 88, 84, 80, 76, 72, 70, 69, 69.2, 69.4, 69.5, 72])


class RegimeResearchTests(unittest.TestCase):
    def test_candidate_basing_breakout_and_invalidation_are_observed_causally(self):
        rows = declining_then_rising()
        result = analyze_regimes(rows, symbol='sh600000', config=FAST_CONFIG)
        names = [event['event'] for event in result['events']]
        self.assertIn('downtrend', names)
        self.assertIn('bottom_candidate', names)
        self.assertIn('bottom_invalidated', names)
        self.assertIn('basing', names)
        self.assertIn('breakout_confirmation', names)
        breakout = next(event for event in result['events'] if event['event'] == 'breakout_confirmation')
        self.assertEqual(breakout['observed_index'], 13)
        self.assertEqual(breakout['observed_at'], rows[13]['closed_at'])
        self.assertLessEqual(breakout['anchor_index'], breakout['observed_index'])
        self.assertEqual(breakout['side'], 'buy')
        self.assertEqual(result['latest']['state'], 'breakout_confirmation')
        self.assertEqual(result['latest']['invalidation']['operator'], '<')
        self.assertFalse(result['execution_allowed'])

    def test_downtrend_breakdown_and_top_invalidation_are_mirrored(self):
        source = bars([60, 64, 68, 72, 76, 80, 84, 88, 90, 91, 90.8, 90.6, 90.5, 88,
                       92, 87, 82, 77, 72, 67, 62, 57, 52])
        result = analyze_regimes(source, symbol='sz000001', config=FAST_CONFIG)
        events = result['events']
        names = [event['event'] for event in events]
        self.assertIn('uptrend', names)
        self.assertIn('top_candidate', names)
        self.assertIn('top_invalidated', names)
        self.assertIn('topping', names)
        self.assertIn('breakdown', names)
        self.assertIn('downtrend', names)
        top = next(event for event in events if event['event'] == 'top_candidate')
        self.assertEqual(top['side'], 'sell')
        self.assertEqual(top['invalidation']['operator'], '>')
        invalidated = next(event for event in events if event['event'] == 'top_invalidated')
        self.assertLessEqual(invalidated['anchor_index'], invalidated['observed_index'])

    def test_batch_and_single_append_snapshots_match_at_every_prefix(self):
        source = declining_then_rising()
        session = RegimeSession(symbol='sh600000', config=FAST_CONFIG)
        for end, row in enumerate(source, 1):
            appended = session.append(row)
            expected = analyze_regimes(source[:end], symbol='sh600000', config=FAST_CONFIG)
            self.assertEqual(session.snapshot(), expected)
            self.assertEqual(appended, expected['latest'])

    def test_future_rows_never_change_prior_prefix(self):
        source = declining_then_rising()
        prefix = analyze_regimes(source[:10], symbol='sh600000', config=FAST_CONFIG)
        full = analyze_regimes(source, symbol='sh600000', config=FAST_CONFIG)
        self.assertEqual(full['series'][:10], prefix['series'])
        self.assertEqual([event for event in full['events'] if event['observed_index'] < 10], prefix['events'])
        self.assertEqual(prefix['as_of'], source[9]['closed_at'])

    def test_open_bar_is_excluded_and_same_timestamp_can_close(self):
        source = bars([100, 96, 92])
        session = RegimeSession(config=FAST_CONFIG)
        for row in source[:2]:
            session.append(row)
        opened = {**source[2], 'is_closed': 'false'}
        self.assertIsNone(session.append(opened))
        self.assertEqual(len(session.snapshot()['series']), 2)
        closed = {**source[2], 'is_closed': 'true'}
        result = session.append(closed)
        self.assertEqual(result['index'], 2)
        self.assertEqual(session.snapshot()['as_of'], source[2]['closed_at'])

    def test_as_of_safe_actual_context_is_attached_but_disclosed_as_not_signal_input(self):
        source = bars([100, 96, 92, 88, 84, 80, 76, 72, 70, 69])
        context = {'rows': [
            {'date': source[8]['closed_at'][:10], 'available_at': source[8]['closed_at'],
             'source': 'documented-provider', 'unit': 'CNY', 'net_flow': -1200,
             'up_count': 100, 'down_count': 300, 'scope': 'index constituent'},
            {'date': source[9]['closed_at'][:10], 'available_at': '2026-01-15T15:00:00+08:00',
             'source': 'late-provider', 'unit': 'CNY', 'net_flow': 99999,
             'up_count': 400, 'down_count': 0},
        ]}
        result = analyze_regimes(source, config=FAST_CONFIG, context=context)
        available = result['series'][8]['features']
        future = result['series'][9]['features']
        self.assertEqual(available['actual_fund_flow']['net_flow'], -1200)
        self.assertEqual(available['breadth']['up_ratio'], .25)
        self.assertFalse(available['actual_fund_flow']['used_by_state_rules'])
        self.assertEqual(future['actual_fund_flow']['state'], 'unavailable')
        self.assertEqual(future['actual_fund_flow']['reason'], 'not_available_at_bar_close')
        self.assertEqual(future['clv_pressure_proxy']['kind'], 'price_volume_pressure_proxy')
        self.assertTrue(future['clv_pressure_proxy']['not_main_fund_flow'])
        self.assertEqual(future['cost_distribution_proxy']['kind'], 'rolling_traded_volume_cost_proxy')
        self.assertTrue(future['cost_distribution_proxy']['not_actual_chips'])
        self.assertIn('central_80_price_band_width_pct', future['cost_distribution_proxy'])
        self.assertNotIn('concentration_80_pct', future['cost_distribution_proxy'])

    def test_invalid_time_ohlc_volume_and_index_gaps_fail_closed(self):
        source = bars([100, 101, 102])
        with self.assertRaisesRegex(ValueError, 'timezone'):
            analyze_regimes([{**source[0], 'closed_at': '2026-01-05T15:00:00'}])
        with self.assertRaisesRegex(ValueError, 'strictly increase'):
            analyze_regimes([source[0], {**source[1], 'closed_at': source[0]['closed_at']}])
        with self.assertRaisesRegex(ValueError, 'OHLC'):
            analyze_regimes([{**source[0], 'high': 90}])
        with self.assertRaisesRegex(ValueError, 'negative'):
            analyze_regimes([{**source[0], 'volume': -1}])
        with self.assertRaisesRegex(ValueError, 'contiguous'):
            analyze_regimes([source[0], {**source[1], 'source_index': 2}])

    def test_context_without_timestamp_or_source_is_unavailable(self):
        source = bars([100, 96, 92, 88, 84, 80])
        row = source[-1]
        result = analyze_regimes(source, config=FAST_CONFIG, context={'rows': [
            {'date': row['closed_at'][:10], 'net_flow': 1, 'up_count': 2, 'down_count': 1}
        ]})
        features = result['latest']['features']
        self.assertEqual(features['actual_fund_flow']['state'], 'unavailable')
        self.assertEqual(features['actual_fund_flow']['reason'], 'missing_or_invalid_availability_time')
        self.assertEqual(features['breadth']['state'], 'unavailable')

    def test_snapshot_contains_versioned_rules_config_and_proxy_disclosures(self):
        result = analyze_regimes(declining_then_rising(), config=FAST_CONFIG)
        self.assertEqual(result['version'], 'causal_regime_research_v1.1')
        self.assertEqual(len(result['config_sha256']), 64)
        self.assertIn('breakout_confirmation', result['rule_definitions'])
        self.assertFalse(result['provenance']['probability_calibrated'])
        self.assertTrue(any('not held-share' in item for item in result['approximation_loss']))

    def test_invalidations_are_risk_events_and_compact_snapshot_keeps_same_evidence(self):
        session=RegimeSession(config=FAST_CONFIG)
        for row in declining_then_rising():session.append(row)
        full=session.snapshot();compact=session.snapshot(include_series=False)
        self.assertNotIn('series',compact)
        self.assertEqual(compact,{key:value for key,value in full.items() if key!='series'})
        invalid=next(event for event in full['events'] if event['event']=='bottom_invalidated')
        self.assertEqual(invalid['side'],'risk')


if __name__ == '__main__':
    unittest.main()
