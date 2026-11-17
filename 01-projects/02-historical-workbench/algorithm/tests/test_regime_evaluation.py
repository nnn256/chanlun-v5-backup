from datetime import datetime, timedelta, timezone
import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.run_regime_research import (
    aggregate, breadth_pass, build_breadth, chronological_splits, discover_sources, select_sources,
    evaluate_label, evaluate_symbol, horizon_labels, read_daily_rows, research_one,
)

CN = timezone(timedelta(hours=8))


def bars(count=30):
    first = datetime(2025, 1, 1, 15, tzinfo=CN)
    values = []
    for index in range(count):
        date = (first + timedelta(days=index)).date().isoformat()
        price = 10 + index
        values.append({'date': date, 'closed_at': date + 'T15:00:00+08:00',
                       'open': price, 'high': price + 2, 'low': price - 1,
                       'close': price + 1, 'volume': 1000, 'is_closed': True})
    return values


def source(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ('closed_at', 'open', 'high', 'low', 'close', 'volume', 'is_closed')
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, 'is_closed': str(row['is_closed']).lower()})


class RegimeEvaluationTests(unittest.TestCase):
    def test_reference_entry_is_next_positive_volume_open_after_observation(self):
        rows = bars()
        rows[2]['volume'] = 0
        splits = {'test': (rows[0]['date'], rows[-1]['date'])}
        outcome, reason = evaluate_label(rows, 1, 5, 1, splits, cost_bps=20)
        self.assertIsNone(reason)
        self.assertEqual(outcome['entry_index'], 3)
        self.assertEqual(outcome['entry_open'], rows[3]['open'])
        self.assertEqual(outcome['exit_index'], 7)
        self.assertEqual(outcome['entry_time'], rows[3]['date'] + 'T09:30:00+08:00')
        self.assertGreater(outcome['entry_time'], outcome['observed_at'])
        expected = rows[7]['close'] / rows[3]['open'] - 1
        self.assertAlmostEqual(outcome['underlying_return'], expected)
        self.assertAlmostEqual(outcome['net_directional_move'], expected - .002)
        self.assertFalse(outcome['executable_strategy'])

    def test_horizons_crossing_split_are_purged_for_signal_and_baseline(self):
        rows = bars()
        splits = chronological_splits(row['date'] for row in rows)
        outcome, reason = evaluate_label(rows, 16, 5, 1, splits)
        self.assertIsNone(outcome)
        self.assertEqual(reason, 'purged_at_chronological_boundary')
        outcome, reason = evaluate_label(rows, 10, 5, 1, splits)
        self.assertIsNone(reason)
        self.assertEqual(outcome['split'], 'train')
        analysis = {'series': [{'index': i, 'state': 'neutral'} for i in range(len(rows))],
                    'events': [{'id': 'boundary', 'event': 'bottom_candidate',
                                'observed_index': 16, 'observed_at': rows[16]['closed_at']}]}
        result = evaluate_symbol(rows, analysis, splits, horizons=(5,))
        self.assertEqual(result['event_outcomes'][0]['reason'], 'purged_at_chronological_boundary')
        self.assertNotIn('train|5|up|precursor', result['stats'])
        self.assertGreater(result['excluded']['baseline:purged_at_chronological_boundary'], 0)

    def test_downside_outcome_is_a_directional_observation_not_short_return(self):
        rows = bars()
        splits = {'test': (rows[0]['date'], rows[-1]['date'])}
        upward, _ = evaluate_label(rows, 1, 5, 1, splits)
        downward, _ = evaluate_label(rows, 1, 5, -1, splits)
        self.assertEqual(upward['underlying_return'], downward['underlying_return'])
        self.assertEqual(upward['directional_move'], -downward['directional_move'])
        self.assertLess(downward['directional_move'], 0)
        self.assertFalse(downward['executable_strategy'])

    def test_evaluator_does_not_modify_events_or_feed_future_labels_into_features(self):
        rows = bars()
        splits = {'test': (rows[0]['date'], rows[-1]['date'])}
        analysis = {'series': [{'index': i, 'state': 'warmup' if i < 5 else 'neutral'} for i in range(len(rows))],
                    'events': [{'id': 'one', 'event': 'breakout_confirmation',
                                'observed_index': 8, 'observed_at': rows[8]['closed_at']}]}
        before = copy.deepcopy(analysis)
        result = evaluate_symbol(rows, analysis, splits, horizons=(5,))
        self.assertEqual(analysis, before)
        altered = copy.deepcopy(rows)
        altered[13].update(high=1000, close=999)
        second = evaluate_symbol(altered, analysis, splits, horizons=(5,))
        self.assertEqual(analysis, before)
        self.assertNotEqual(result['event_outcomes'][0]['underlying_return'], second['event_outcomes'][0]['underlying_return'])
        self.assertEqual(result['stats']['test|5|up|all_days']['count'], 20)

    def test_research_pipeline_passes_only_closed_inputs_to_feature_generator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'tdx/day/ohlcv/sh600000.csv'
            rows = bars()
            source(path, rows)
            observed = []

            def features(inputs, *, symbol):
                observed.append(copy.deepcopy(inputs))
                self.assertEqual(symbol, 'sh600000')
                forbidden = {'entry_index', 'exit_index', 'underlying_return', 'window_high', 'window_low'}
                self.assertTrue(all(not (forbidden & set(row)) for row in inputs))
                return {'version': 'fixture', 'series': [{'index': i, 'state': 'neutral'} for i in range(len(inputs))],
                        'events': [{'id': 'one', 'event': 'bottom_candidate', 'observed_index': 8,
                                    'observed_at': inputs[8]['closed_at']}], 'latest': None}

            split = {'test': (rows[0]['date'], rows[-1]['date'])}
            with patch('chanmodel.regime_research.analyze_regimes', side_effect=features):
                receipt = research_one({'symbol': 'sh600000', 'path': str(path)}, rows[-1]['closed_at'],
                                       split, {}, (5,), 20, 20, root / 'out')
            self.assertEqual(receipt['state'], 'complete')
            self.assertEqual(len(observed), 1)
            self.assertEqual(len(observed[0]), len(rows))
            self.assertTrue(all(row['is_closed'] is True for row in observed[0]))

    def test_rolling_label_extrema_match_simple_window(self):
        rows = bars(50)
        rows[15]['high'] = 80
        rows[19]['low'] = 2
        for horizon in (1, 5, 20):
            labels = horizon_labels(rows, horizon)
            for start in range(len(rows) - horizon + 1):
                window = rows[start:start + horizon]
                self.assertEqual(labels[start]['window_high'], max(row['high'] for row in window))
                self.assertEqual(labels[start]['window_low'], min(row['low'] for row in window))
                self.assertEqual(labels[start]['exit_index'], start + horizon - 1)
            self.assertTrue(all(value is None for value in labels[len(rows) - horizon + 1:]))

    def test_horizon_counts_positive_volume_bars_and_skips_suspension_rows(self):
        rows = bars(12)
        rows[4]['volume'] = 0
        rows[4]['high'] = 1000
        rows[4]['low'] = .01
        labels = horizon_labels(rows, 5)
        self.assertEqual(labels[0]['entry_index'], 0)
        self.assertEqual(labels[0]['exit_index'], 5)
        self.assertEqual(labels[0]['window_high'], max(rows[i]['high'] for i in [0, 1, 2, 3, 5]))
        splits = {'test': (rows[0]['date'], rows[-1]['date'])}
        excluded, reason = evaluate_label(rows, 4, 5, 1, splits, labels=labels)
        self.assertIsNone(excluded)
        self.assertEqual(reason, 'observation_bar_no_positive_volume')

    def test_top_and_invalidation_events_map_to_downside_observation_families(self):
        rows = bars()
        splits = {'test': (rows[0]['date'], rows[-1]['date'])}
        analysis = {'series': [{'index': i, 'state': 'neutral'} for i in range(len(rows))],
                    'events': [{'id': 'top', 'event': 'top_candidate', 'observed_index': 2,
                                'observed_at': rows[2]['closed_at']},
                               {'id': 'invalid', 'event': 'top_invalidated', 'observed_index': 3,
                                'observed_at': rows[3]['closed_at']}]}
        result = evaluate_symbol(rows, analysis, splits, horizons=(5,))
        self.assertEqual([item['family'] for item in result['event_outcomes']], ['precursor', 'invalidation'])
        self.assertEqual([item['direction'] for item in result['event_outcomes']], [-1, 1])

    def test_flow_and_true_chip_coverage_are_not_invented_by_breadth(self):
        value = {'2025-01-02': {'advance_ratio': .8, 'observed_securities': 100}}
        self.assertTrue(breadth_pass('2025-01-02', 1, value))
        self.assertFalse(breadth_pass('2025-01-02', -1, value))
        self.assertIsNone(breadth_pass('2025-01-01', 1, value))
        self.assertIsNone(breadth_pass('2025-01-02', 1, value, minimum_securities=200))

    def test_cache_discovery_prefers_latest_whole_csv_without_splicing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / 'old/tdx/day/ohlcv/sh600000.csv'
            newer = root / 'new/tdx/day/ohlcv/sh600000.csv'
            source(original, bars(15))
            changed = bars(20)
            changed[0].update(open=5, low=4, high=7, close=6)
            source(newer, changed)
            selected, failures = discover_sources([root / 'old', root / 'new'])
            self.assertEqual(failures, [])
            self.assertEqual(len(selected), 1)
            self.assertEqual(Path(selected[0]['path']), newer.resolve())
            loaded, receipt = read_daily_rows(selected[0]['path'])
            self.assertEqual(loaded[0]['close'], 6)
            self.assertEqual(len(loaded), 20)
            self.assertEqual(selected[0]['alternative_sources'], 1)
            self.assertFalse(receipt['point_in_time_revision_history'])

    def test_explicit_symbol_sample_is_ordered_deduplicated_and_fail_closed(self):
        source_rows = [{'symbol': code, 'path': code + '.csv'} for code in ('sh600000', 'sz000001', 'bj920010')]
        selected = select_sources(source_rows, symbols=['SZ000001', 'sh600000', 'sz000001'])
        self.assertEqual([row['symbol'] for row in selected], ['sz000001', 'sh600000'])
        with self.assertRaisesRegex(ValueError, 'unknown|cached'):
            select_sources(source_rows, symbols=['xx000000'])

    def test_breadth_uses_only_same_day_or_earlier_price_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'tdx/day/ohlcv/sh600000.csv'
            rows = bars(10)
            source(path, rows)
            sources = [{'symbol': path.stem, 'path': str(path)}]
            first, receipt = build_breadth(sources, rows[4]['closed_at'])
            rows[7].update(open=3, high=4, low=1, close=2)
            source(path, rows)
            changed, _ = build_breadth(sources, rows[4]['closed_at'])
            self.assertEqual(first, changed)
            self.assertEqual(first[rows[4]['date']]['advance'], 1)
            self.assertFalse(receipt['historical_membership_verified'])

    def test_historical_cutoff_checks_metadata_against_complete_source_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'tdx/day/ohlcv/sh600000.csv'
            rows = bars(10)
            source(path, rows)
            metadata = path.parent.parent / 'metadata' / 'sh600000.json'
            metadata.parent.mkdir()
            metadata.write_text(json.dumps({'symbol': 'sh600000',
                'csv_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'last_date': rows[-1]['date'], 'open_rows_excluded': 0}), encoding='utf-8')
            loaded, receipt = read_daily_rows(path, rows[4]['closed_at'])
            self.assertEqual(len(loaded), 5)
            self.assertEqual(receipt['last_close'], rows[4]['closed_at'])
            self.assertEqual(receipt['source_last_close'], rows[-1]['closed_at'])
            self.assertEqual(receipt['source_closed_rows'], 10)
            self.assertEqual(receipt['excluded']['after_cutoff'], 5)
            self.assertTrue(receipt['metadata_verified'])
            wrong = json.loads(metadata.read_text(encoding='utf-8'))
            wrong['last_date'] = rows[4]['date']
            metadata.write_text(json.dumps(wrong), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'metadata last_date'):
                read_daily_rows(path, rows[4]['closed_at'])

    def test_daily_schedule_accepts_equivalent_utc_and_rejects_intraday_or_duplicate_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'tdx/day/ohlcv/sz000001.csv'
            rows = bars(4)
            rows[0]['closed_at'] = rows[0]['date'] + 'T07:00:00Z'
            source(path, rows)
            loaded, _ = read_daily_rows(path)
            self.assertEqual(loaded[0]['closed_at'], rows[0]['date'] + 'T15:00:00+08:00')

            wrong_time = bars(4)
            wrong_time[1]['closed_at'] = wrong_time[1]['date'] + 'T14:59:00+08:00'
            source(path, wrong_time)
            with self.assertRaisesRegex(ValueError, '15:00:00 China time'):
                read_daily_rows(path)
            # A post-cutoff record is still part of the declared daily source.
            with self.assertRaisesRegex(ValueError, '15:00:00 China time'):
                read_daily_rows(path, wrong_time[0]['closed_at'])

            duplicates = bars(4)
            duplicates[1]['closed_at'] = duplicates[0]['date'] + 'T16:00:00+08:00'
            source(path, duplicates)
            with self.assertRaisesRegex(ValueError, 'duplicate daily session date'):
                read_daily_rows(path)

    def test_bad_source_does_not_silently_reorder_or_accept_false_prices(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'sh600000.csv'
            rows = bars(4)
            rows[2], rows[1] = rows[1], rows[2]
            source(path, rows)
            with self.assertRaisesRegex(ValueError, 'descending'):
                read_daily_rows(path)
            rows = bars(4)
            rows[1]['close'] = float('nan')
            source(path, rows)
            with self.assertRaisesRegex(ValueError, 'nonfinite'):
                read_daily_rows(path)


if __name__ == '__main__':
    unittest.main()
