from dataclasses import replace
import hashlib
import json
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

from chanmodel.model import Candle
from chanmodel.reference_engine import ReferenceSession
from tests.test_recursive_v2 import daily_series
from workbench import live
from workbench.incremental import LiveSession


def original_hash(bars):
    return hashlib.sha256(json.dumps([live._bar_signature(bar) for bar in bars],
        separators=(',',':')).encode()).hexdigest()


class ClosedInputHashTests(unittest.TestCase):
    def resident(self,count):
        engine=ReferenceSession('day')
        for bar in daily_series(count).bars:engine.append(bar)
        return LiveSession(engine,count)

    def test_unchanged_history_reuses_hash_without_encoding_old_bars(self):
        value=self.resident(100)
        expected=original_hash(value.session.bars)
        self.assertEqual(live._closed_input_hash(value),expected)
        with patch.object(live,'_bar_signature',side_effect=AssertionError('old history was encoded')):
            self.assertEqual(live._closed_input_hash(value),expected)

    def test_appending_extends_exact_original_json_hash_only_for_new_bars(self):
        value=self.resident(96);bars=daily_series(100).bars
        self.assertEqual(live._closed_input_hash(value),original_hash(bars[:96]))
        for bar in bars[96:]:
            value.session.append(bar)
            original=live._bar_signature
            seen=[]
            def signature(candidate):seen.append(candidate.pos);return original(candidate)
            with patch.object(live,'_bar_signature',side_effect=signature):
                actual=live._closed_input_hash(value)
            self.assertEqual(actual,original_hash(value.session.bars))
            self.assertEqual(seen,[bar.pos])

    def test_rebuilt_or_replaced_session_invalidates_transient_prefix(self):
        value=self.resident(100);first=live._closed_input_hash(value)
        other=ReferenceSession('day')
        for index,bar in enumerate(daily_series(100).bars):
            other.append(replace(bar,volume=(bar.volume or 0)+1) if index==0 else bar)
        value.session=other
        actual=live._closed_input_hash(value)
        self.assertEqual(actual,original_hash(other.bars))
        self.assertNotEqual(actual,first)

    def test_replaced_last_bar_or_shorter_prefix_forces_rehash(self):
        value=self.resident(100);live._closed_input_hash(value)
        value.session.bars[-1]=replace(value.session.bars[-1],volume=0)
        self.assertEqual(live._closed_input_hash(value),original_hash(value.session.bars))
        value.session.bars=value.session.bars[:90]
        self.assertEqual(live._closed_input_hash(value),original_hash(value.session.bars))

    def test_json_scalar_values_and_empty_prefix_keep_legacy_identity(self):
        value=self.resident(1);value.session.bars=[]
        self.assertEqual(live._closed_input_hash(value),original_hash([]))
        bars=[Candle(0,1.,1.,1.,1.,'2026-11-13T15:00:00+08:00',None),
              Candle(1,1.,1.,1.,1.,'2026-11-16T15:00:00+08:00',-0.)]
        value.session.bars=bars
        self.assertEqual(live._closed_input_hash(value),original_hash(bars))

    def test_provider_revision_rebuilds_and_replaces_cached_history_identity(self):
        value=self.resident(100);value.last_full_audit=time.time()
        before=live._closed_input_hash(value)
        revised=[replace(bar,volume=(bar.volume or 0)+5) for bar in value.session.bars]
        tail=revised[-64:]
        def rows(bars):
            return [dict(open=b.open,high=b.high,low=b.low,close=b.close,volume=b.volume,
                         closed_at=b.closed_at,is_closed=True) for b in bars]
        receipt={'observed_at':'2026-11-15T15:00:00+08:00','received_at':'2026-11-15T15:00:00+08:00'}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(live,'get_session',return_value=(value,True)), \
             patch.object(live,'save_session'), \
             patch.object(live,'acquire',side_effect=[(tail,rows(tail),receipt),(revised,rows(revised),receipt)]):
            rebuilt,_,_,meta=live._ingest_one('sz000001','day')
        self.assertIsNot(rebuilt,value)
        self.assertTrue(meta['rebuilt'])
        self.assertEqual(meta['checkpoint_sha256'],original_hash(rebuilt.session.bars))
        self.assertNotEqual(meta['checkpoint_sha256'],before)

    def test_transient_hash_state_is_not_checkpointed(self):
        from workbench import incremental
        value=self.resident(100);expected=live._closed_input_hash(value)
        self.assertTrue(hasattr(value,'_closed_hash_state'))
        with tempfile.TemporaryDirectory() as tmp,patch.object(incremental,'ROOT',Path(tmp)), \
             patch.object(incremental,'MEMORY',incremental.OrderedDict()):
            incremental.save('sz000001','day',value)
            incremental.clear_memory()
            restored,reused=incremental.get('sz000001','day')
            self.assertTrue(reused)
            self.assertFalse(hasattr(restored,'_closed_hash_state'))
            self.assertEqual(live._closed_input_hash(restored),expected)


class TailLookupTests(unittest.TestCase):
    def test_bounded_provider_tail_does_not_walk_full_resident_history(self):
        bars=daily_series(1000).bars
        class CountedBars(list):
            walked=0
            def __iter__(self):
                self.walked+=len(self);return super().__iter__()
        class Session:
            def __init__(self):self.bars=CountedBars(bars);self.last_closed_at=bars[-1].closed_at
        session=Session()
        result=live.reconcile_closed_tail(session,bars[-64:])
        self.assertEqual(result['appended'],0)
        self.assertEqual(result['rebuild'],None)
        self.assertEqual(session.bars.walked,0)

    def test_source_revision_and_lag_detection_still_inspect_provider_window(self):
        engine=ReferenceSession('day')
        bars=daily_series(100).bars
        for bar in bars:engine.append(bar)
        tail=list(bars[-64:]);tail[0]=replace(tail[0],volume=(tail[0].volume or 0)+1)
        result=live.reconcile_closed_tail(engine,tail)
        self.assertEqual(result['rebuild'],'source_revision')
        self.assertEqual(result['revision'][0]['time'],tail[0].closed_at)
        with self.assertRaisesRegex(ValueError,'行情源落后'):
            live.reconcile_closed_tail(engine,bars[-65:-1])


if __name__=='__main__':unittest.main()
