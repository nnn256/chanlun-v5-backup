"""Causal period catalog checks: real aggregation, time, and source identity."""
from __future__ import annotations

import math
import unittest
from dataclasses import replace
from datetime import datetime

from build_period_catalog import (ORDER, aggregate_calendar, analyze_sequence,
                                  long_daily_bars, make_catalog, schedule)


class PeriodCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=make_catalog(snapshot_limit=6)

    def test_all_ten_actual_sampling_labels_are_present(self):
        self.assertEqual(tuple(self.catalog['periods']),ORDER)
        for key,item in self.catalog['periods'].items():
            self.assertTrue(item['bars'])
            self.assertEqual(item['period'],key)
            self.assertEqual(item['snapshots'][-1]['report']['period'],key)
            self.assertEqual(item['snapshots'][-1]['report']['sampling_period'],key)

    def test_minutes_and_long_source_are_not_pretended_as_one_security_path(self):
        periods=self.catalog['periods']
        self.assertEqual({periods[k]['source_group'] for k in ('1m','5m','15m','30m','60m')},{'minute_source'})
        self.assertEqual({periods[k]['source_group'] for k in ('day','week','month','quarter','year')},{'daily_source'})
        self.assertTrue(all(not item['cross_group_link_allowed'] for item in periods.values()))
        self.assertIn('forbidden',self.catalog['meta']['cross_group_evidence'])

    def test_minute_aggregates_match_complete_underlying_ohlcv(self):
        fine=self.catalog['periods']['1m']['bars']
        by_time={datetime.fromisoformat(b['time']):b for b in fine}
        from datetime import timedelta
        for period in ('5m','15m','30m','60m'):
            width=int(period[:-1])
            for parent in self.catalog['periods'][period]['bars']:
                end=datetime.fromisoformat(parent['time'])
                children=[by_time[end-timedelta(minutes=offset)] for offset in reversed(range(width))]
                self.assertEqual(parent['open'],children[0]['open'])
                self.assertEqual(parent['high'],max(b['high'] for b in children))
                self.assertEqual(parent['low'],min(b['low'] for b in children))
                self.assertEqual(parent['close'],children[-1]['close'])
                self.assertEqual(parent['volume'],math.fsum(b['volume'] for b in children))

    def test_calendar_aggregates_are_exact_and_have_complete_lineage(self):
        source=long_daily_bars()
        for period in ('week','month','quarter','year'):
            bars,audit=aggregate_calendar(source,period)
            self.assertFalse(audit['missing_children_filled'])
            self.assertTrue(audit['lineage'])
            for parent,proof in zip(bars,audit['lineage']):
                parts=source[proof['source_start']:proof['source_end']+1]
                self.assertTrue(proof['complete'])
                self.assertEqual(proof['source_count'],len(parts))
                self.assertEqual(parent.open,parts[0].open)
                self.assertEqual(parent.close,parts[-1].close)
                self.assertEqual(parent.high,max(b.high for b in parts))
                self.assertEqual(parent.low,min(b.low for b in parts))
                self.assertEqual(parent.volume,math.fsum(b.volume for b in parts))
                self.assertEqual(parent.closed_at,parts[-1].closed_at)

    def test_partial_calendar_buckets_remain_excluded(self):
        source=long_daily_bars(27)
        monthly,audit=aggregate_calendar(source,'month')
        self.assertEqual(monthly,())
        self.assertEqual(len(audit['excluded_partial_buckets']),2)
        self.assertTrue(all(e['observed_daily_bars']<e['expected_daily_bars'] for e in audit['excluded_partial_buckets']))

    def test_snapshot_times_never_use_future_evidence(self):
        for period,item in self.catalog['periods'].items():
            for snapshot in item['snapshots']:
                asof=snapshot['as_of'];report=snapshot['report']
                self.assertEqual(snapshot['input_count'],asof+1)
                self.assertEqual(report['as_of_time'],item['bars'][asof]['time'])
                for kind in ('merged','fractals','strokes','segments'):
                    for obj in report['base'][kind]:
                        for field in ('basis_at','available_at'):
                            if obj.get(field) is not None:self.assertLessEqual(obj[field],asof,(period,kind,field))
                for layer in report['hierarchy']['levels']:
                    for center in layer['centers']:
                        self.assertLessEqual(center['formed_at'],asof)
                        self.assertLessEqual(center['available_at'],asof)
                    for unit in layer['completed_types']:
                        self.assertLessEqual(unit['completed_at'],asof)
                        self.assertFalse(unit['completion']['is_turn_confirmation'])
                for point in report['signals']:
                    self.assertLessEqual(point['available_at'],asof)

    def test_direct_recompute_matches_selected_literal_prefixes(self):
        from chanmodel.model import Candle
        for period in ('1m','15m','day','week','year'):
            item=self.catalog['periods'][period]
            sample=item['snapshots'][len(item['snapshots'])//2]
            bars=[Candle(b['index'],b['open'],b['high'],b['low'],b['close'],b['time'],b['volume'],True)
                  for b in item['bars'][:sample['input_count']]]
            self.assertEqual(analyze_sequence(bars,period),sample['report'])

    def test_future_changes_do_not_modify_prefix(self):
        source=long_daily_bars(100)
        before=analyze_sequence(source[:50],'day')
        changed=source[:50]+tuple(replace(b,open=b.open+100,high=b.high+100,low=b.low+100,close=b.close+100) for b in source[50:])
        self.assertEqual(before,analyze_sequence(changed[:50],'day'))

    def test_insufficient_year_history_does_not_invent_full_structures(self):
        year=self.catalog['periods']['year']
        final=year['snapshots'][-1]['report']
        self.assertEqual(len(year['bars']),5)
        self.assertEqual(final['history_state'],'insufficient_history')
        self.assertEqual(final['base']['segments'],[])
        self.assertEqual(final['signals'],[])
        self.assertFalse(final['execution_allowed'])

    def test_scheduled_replay_is_described_honestly(self):
        for item in self.catalog['periods'].values():
            replay=item['replay_schedule']
            self.assertEqual(replay['observations'],len(item['snapshots']))
            self.assertEqual(replay['indices'],[s['as_of'] for s in item['snapshots']])
            self.assertIn('not every source bar',replay['semantics'])
            self.assertEqual(replay['indices'][-1],len(item['bars'])-1)


if __name__=='__main__':unittest.main()
