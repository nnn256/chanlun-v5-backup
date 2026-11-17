from datetime import datetime,timedelta
import copy
import gzip
import hashlib
import hmac
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chanmodel.model import Candle
from chanmodel.reference_engine import ReferenceSession,run_reference,make_report,SETTINGS,_ExtremaIndex
from tests.test_recursive_v2 import daily_series
from workbench import incremental,live
LiveSession=incremental.LiveSession


def report_from_session(session,symbol):
    return session.snapshot(symbol,session.bars[-1].closed_at,'random_test','unadjusted','sample')


class IncrementalReferenceTests(unittest.TestCase):
    def compare(self,series,positions):
        session=ReferenceSession('day',observe=True)
        selected=set(positions)|{len(series.bars)-1}
        for index,bar in enumerate(series.bars):
            session.append(bar)
            if index not in selected:continue
            whole,closed,registry,events,first=run_reference(series.bars[:index+1],'day',True)
            expected=make_report(whole,closed,registry,events,first,series.symbol,'day',
                                 closed[-1].closed_at,'random_test','unadjusted','sample',
                                 first_crossing=None)
            actual=report_from_session(session,series.symbol)
            for field in ('base','hierarchy','signals','observed_signal_events','geometry_review'):
                self.assertEqual(actual[field],expected[field],f'{series.symbol} prefix={index} field={field}')

    def test_fixed_seed_randomized_two_security_incremental_outputs_match_full_prefix(self):
        rng=random.Random(20261113);count=rng.randint(180,260)
        for symbol in ['sh600000','sz000001']:
            series=daily_series(count);series=type(series)(symbol,series.period,series.adjustment,series.bars,series.source)
            sample=sorted(set(rng.randrange(40,count) for _ in range(4)))
            self.compare(series,sample)

    def test_segment_tree_invalidation_matches_linear_scan_for_randomized_boundaries(self):
        rng=random.Random(42013);index=_ExtremaIndex();lows=[];highs=[]
        for _ in range(513):
            low=rng.uniform(5,40);high=low+rng.uniform(.01,4);lows.append(low);highs.append(high);index.append(low,high)
        for _ in range(400):
            start=rng.randrange(514);boundary=rng.uniform(5,44);side=rng.choice(['buy','sell'])
            expected=next((i for i in range(start,len(lows)) if (lows[i]<boundary if side=='buy' else highs[i]>boundary)),None)
            self.assertEqual(index.first_crossing(start,boundary,side),expected)

    def test_authenticated_checkpoint_survives_restart_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(incremental,'ROOT',Path(tmp)),patch.object(incremental,'MEMORY',incremental.OrderedDict()):
                initial,restored=incremental.get('bj920010','day');self.assertFalse(restored)
                series=daily_series(2208)
                initial.session=ReferenceSession('day',True)
                for bar in series.bars:initial.session.append(bar)
                digest=incremental.save('bj920010','day',initial)
                self.assertEqual(len(digest),64)
                incremental.clear_memory()
                recovered,restored=incremental.get('bj920010','day')
                self.assertTrue(restored);self.assertEqual(recovered.session.closed_count,2208)
                self.assertEqual(report_from_session(recovered.session,'bj920010')['signals'],
                                 report_from_session(initial.session,'bj920010')['signals'])
                path=incremental._checkpoint_path('bj920010','day')
                raw=path.read_bytes();path.write_bytes(raw[:-1]+bytes([raw[-1]^1]));incremental.clear_memory()
                with self.assertRaisesRegex(ValueError,'authentication'):incremental.get('bj920010','day')

    def test_engine_snapshot_restores_without_replaying_historical_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(incremental,'ROOT',Path(tmp)),patch.object(incremental,'MEMORY',incremental.OrderedDict()):
                session=ReferenceSession('day',True);series=daily_series(256)
                for bar in series.bars:session.append(bar)
                value=incremental.LiveSession(session,saved_count=session.closed_count)
                incremental.save('sz000001','day',value);incremental.clear_memory()
                with patch.object(ReferenceSession,'append',side_effect=AssertionError('snapshot replayed OHLC')):
                    restored,loaded=incremental.get('sz000001','day')
                self.assertTrue(loaded);self.assertIs(type(restored.session),ReferenceSession)
                self.assertEqual(restored.session.closed_count,256)

    def test_engine_snapshot_restores_without_replaying_historical_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(incremental,'ROOT',Path(tmp)),patch.object(incremental,'MEMORY',incremental.OrderedDict()):
                session=ReferenceSession('day',True);series=daily_series(256)
                for bar in series.bars:session.append(bar)
                value=LiveSession(session,256);incremental.save('bj920010','day',value)
                incremental.clear_memory()
                original=ReferenceSession.append
                with patch.object(ReferenceSession,'append',autospec=True,side_effect=original) as append:
                    recovered,restored=incremental.get('bj920010','day')
                self.assertTrue(restored);self.assertEqual(append.call_count,0)
                self.assertEqual(report_from_session(recovered.session,'bj920010')['signals'],
                                 report_from_session(session,'bj920010')['signals'])

    def test_append_journal_restores_only_new_bars_then_compacts_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(incremental,'ROOT',Path(tmp)),patch.object(incremental,'MEMORY',incremental.OrderedDict()):
                series=daily_series(135);session=ReferenceSession('day',True)
                for bar in series.bars[:128]:session.append(bar)
                value=LiveSession(session,128);incremental.save('bj920010','day',value)
                tail=series.bars[128:135]
                for bar in tail:session.append(bar)
                self.assertFalse(incremental.append_journal('bj920010','day',value,tail))
                self.assertEqual(value.saved_count,135);self.assertEqual(value.journal_count,7)
                incremental.clear_memory();original=ReferenceSession.append
                with patch.object(ReferenceSession,'append',autospec=True,side_effect=original) as append:
                    recovered,restored=incremental.get('bj920010','day')
                self.assertTrue(restored);self.assertEqual(append.call_count,7)
                expected=run_reference(series.bars[:135],'day',True)
                report=make_report(*expected,'bj920010','day',series.bars[134].closed_at,
                                   series.source,series.adjustment,'sample')
                self.assertEqual(report_from_session(recovered.session,'bj920010')['signals'],report['signals'])
                incremental.save('bj920010','day',recovered)
                self.assertEqual(recovered.journal_count,0)
                self.assertEqual(incremental._journal_path('bj920010','day').read_bytes(),b'')

    def test_torn_journal_tail_is_dropped_before_next_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(incremental,'ROOT',Path(tmp)),patch.object(incremental,'MEMORY',incremental.OrderedDict()):
                series=daily_series(82);session=ReferenceSession('day',True)
                for bar in series.bars[:80]:session.append(bar)
                value=LiveSession(session,80);incremental.save('bj920010','day',value)
                session.append(series.bars[80]);incremental.append_journal('bj920010','day',value,[series.bars[80]])
                wal=incremental._journal_path('bj920010','day');wal.write_bytes(wal.read_bytes()+b'{partial')
                incremental.clear_memory();recovered,restored=incremental.get('bj920010','day')
                self.assertTrue(restored);self.assertEqual(recovered.session.closed_count,81)
                self.assertTrue(wal.read_bytes().endswith(b'\n'))
                recovered.session.append(series.bars[81])
                incremental.append_journal('bj920010','day',recovered,[series.bars[81]])
                incremental.clear_memory();again,_=incremental.get('bj920010','day')
                self.assertEqual(again.session.closed_count,82)

    def test_legacy_json_checkpoint_is_loaded_and_upgraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(incremental,'ROOT',Path(tmp)),patch.object(incremental,'MEMORY',incremental.OrderedDict()):
                session=ReferenceSession('day',True);series=daily_series(90)
                for bar in series.bars:session.append(bar)
                metadata={'schema':1,'symbol':'bj920010','period':'day','profile':incremental.PROFILE,
                          'commit':incremental.COMMIT,'settings_fingerprint':incremental.settings_fingerprint('day')}
                state={'metadata':metadata,'saved_count':90,'revisions':0,'last_full_audit':0.0,
                       **incremental._public_state(session)}
                packed=gzip.compress(json.dumps(state,separators=(',',':')).encode(),mtime=0)
                signature=hmac.new(incremental._key(),packed,hashlib.sha256).digest()
                path=incremental._checkpoint_path('bj920010','day');path.parent.mkdir(parents=True)
                path.write_bytes(incremental.LEGACY_MAGIC+signature+packed)
                recovered,restored=incremental.get('bj920010','day')
                self.assertTrue(restored);self.assertTrue(recovered.needs_migration)
                incremental.save('bj920010','day',recovered)
                self.assertEqual(path.read_bytes()[:4],incremental.MAGIC)
                self.assertFalse(recovered.needs_migration)

    def test_resident_session_lru_is_bounded_and_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(incremental,'ROOT',Path(tmp)),\
                 patch.object(incremental,'MEMORY',incremental.OrderedDict()),\
                 patch.object(incremental,'SESSION_CACHE_LIMIT',2):
                incremental.get('sz000001','day')
                incremental.get('sh600000','day')
                incremental.get('bj920010','day')
                self.assertEqual(list(incremental.MEMORY),[('sh600000','day'),('bj920010','day')])
                session,reused=incremental.get('sz000001','day')
                self.assertFalse(reused)
                self.assertEqual(session.last_load_source,'new')

    def test_intraday_forming_bar_is_rejected_by_confirmed_engine(self):
        session=ReferenceSession('day')
        bar=daily_series(10).bars[-1]
        with self.assertRaisesRegex(ValueError,'forming candles'):session.append(Candle(0,bar.open,bar.high,bar.low,bar.close,bar.closed_at,bar.volume,False))

    def test_live_rolling_tail_appends_new_bars_without_replaying_and_detects_provider_revision(self):
        series=daily_series(120);session=ReferenceSession('day')
        for bar in series.bars[:110]:session.append(bar)
        engine_identity=id(session.engine)
        result=live.reconcile_closed_tail(session,series.bars[90:114])
        self.assertEqual(result['appended'],4);self.assertEqual(id(session.engine),engine_identity)
        self.assertEqual(session.closed_count,114)
        revised=list(series.bars[90:120]);changed=revised[4]
        revised[4]=Candle(changed.pos,changed.open,changed.high+1,changed.low,changed.close,changed.closed_at,changed.volume)
        result=live.reconcile_closed_tail(session,revised)
        self.assertEqual(result['rebuild'],'source_revision');self.assertEqual(result['revision'][0]['time'],changed.closed_at)

    def test_live_rolling_tail_requires_rebuild_after_gap_and_rejects_stale_data(self):
        series=daily_series(150);session=ReferenceSession('day')
        for bar in series.bars[:75]:session.append(bar)
        self.assertEqual(live.reconcile_closed_tail(session,series.bars[80:])['rebuild'],'bounded_tail_no_overlap')
        with self.assertRaisesRegex(ValueError,'落后'):live.reconcile_closed_tail(session,series.bars[:50])


if __name__=='__main__':unittest.main()
