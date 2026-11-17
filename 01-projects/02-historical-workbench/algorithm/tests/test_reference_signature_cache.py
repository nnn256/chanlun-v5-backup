import copy
import json
import unittest
from unittest.mock import patch

from chanmodel.reference_engine import ReferenceSession, _signature_identity, make_report
from chanmodel.model import Candle
from KLine.KLine_List import CKLine_List
from workbench import incremental
from pathlib import Path
import tempfile
from tests.test_recursive_v2 import daily_series


class ReferenceSignatureCacheTests(unittest.TestCase):
    def test_feature_identity_preserves_json_scalar_distinctions(self):
        base={'begin':1,'end':9,'sure':True,'first_context':None,'features':{}}
        values=[None,False,0,0.0,-0.0,1,1.0,'1']
        for left in values:
            for right in values:
                a={**base,'features':{'x':left}}
                b={**base,'features':{'x':right}}
                self.assertEqual(_signature_identity(a)==_signature_identity(b),
                                 json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True))
        for bad in (float('nan'),float('inf'),float('-inf')):
            with self.assertRaises(ValueError):_signature_identity({**base,'features':{'x':bad}})

    def test_old_session_without_comparison_cache_keeps_observed_event_history(self):
        bars=daily_series(420).bars
        original=ReferenceSession()
        for bar in bars[:300]:original.append(bar)
        restored=copy.deepcopy(original)
        del restored._signature_cache
        for bar in bars[300:]:
            self.assertEqual(restored.append(bar),original.append(bar))
        self.assertEqual(restored.registry,original.registry)
        self.assertEqual(restored.events,original.events)
        self.assertEqual(restored.snapshot('sh600000'),original.snapshot('sh600000'))

    def test_unchanged_point_signatures_are_not_reencoded_for_every_closed_bar(self):
        bars=daily_series(420).bars
        session=ReferenceSession()
        original_dumps=json.dumps
        calls=[]
        def encode(value,*args,**kwargs):
            if isinstance(value,dict) and set(value)=={'begin','end','sure','first_context','features'}:
                calls.append(value)
            return original_dumps(value,*args,**kwargs)
        with patch('chanmodel.reference_engine.json.dumps',side_effect=encode):
            for bar in bars:session.append(bar)
        # An actual event change may share one encoded point between its native
        # classes; unchanged historical points need no JSON work at all.
        self.assertTrue(session.events)
        self.assertLessEqual(len(calls),len(session.events))

    def test_indexed_invalidation_does_not_rescan_bar_suffix_when_no_crossing(self):
        bars=daily_series(420).bars
        session=ReferenceSession()
        for bar in bars:session.append(bar)
        expected=session.snapshot('sh600000')

        class IndexedBars(list):
            def __getitem__(self,index):
                if isinstance(index,slice):raise AssertionError('unexpected full-history suffix scan')
                return super().__getitem__(index)

        engine,_,registry,events,first=session.result_tuple()
        result=make_report(engine,IndexedBars(bars),registry,events,first,'sh600000','day',
                           bars[-1].closed_at,'tdx','unadjusted','',
                           first_crossing=session.extrema.first_crossing)
        self.assertEqual(result,expected)

    def test_unchanged_native_structure_still_admits_candle_to_extrema_index(self):
        initial=daily_series(1).bars[0]
        session=ReferenceSession()
        session.append(initial)
        from datetime import timedelta
        from chanmodel.model import time_value
        stamp=(time_value(initial.closed_at)+timedelta(days=1)).isoformat()
        inside=Candle(1,initial.open,initial.high,initial.low,initial.close,stamp,initial.volume)
        with patch('chanmodel.reference_engine.native_objects',side_effect=AssertionError('unchanged observer rescanned')):
            self.assertEqual(session.append(inside),[])
        self.assertEqual(session.closed_count,2)
        self.assertEqual(session.extrema.size,2)
        self.assertEqual(session.extrema.first_crossing(1,inside.low+.01,'buy'),1)
        self.assertEqual(session.extrema.first_crossing(1,inside.high-.01,'sell'),1)

    def test_old_plain_engine_checkpoint_restores_and_keeps_append_results(self):
        bars=daily_series(420).bars
        fresh=ReferenceSession()
        for bar in bars[:270]:fresh.append(bar)
        legacy=copy.deepcopy(fresh)
        # Pinned upstream deepcopy already returns its original CKLine_List;
        # this models a pre-optimization CHJ7 object with no revision marker.
        self.assertIs(type(legacy.engine),CKLine_List)
        # A stray marker on a plain upstream engine cannot prove that its
        # recalculation method increments it; only our exact adapter can.
        legacy.engine._observer_revision=123
        del legacy._signature_cache
        with tempfile.TemporaryDirectory() as tmp, patch.object(incremental,'ROOT',Path(tmp)):
            with patch.object(incremental,'MEMORY',incremental.OrderedDict()):
                incremental.save('sh600000','day',incremental.LiveSession(legacy,270))
                incremental.clear_memory()
                recovered,restored=incremental.get('sh600000','day')
                self.assertTrue(restored)
                self.assertIs(type(recovered.session.engine),CKLine_List)
                self.assertEqual(recovered.session.engine._observer_revision,123)
                for bar in bars[270:]:
                    self.assertEqual(recovered.session.append(bar),fresh.append(bar))
                self.assertEqual(recovered.session.snapshot('sh600000'),fresh.snapshot('sh600000'))

    def test_new_observed_engine_checkpoint_retains_native_revision_marker(self):
        session=ReferenceSession()
        for bar in daily_series(270).bars:session.append(bar)
        with tempfile.TemporaryDirectory() as tmp, patch.object(incremental,'ROOT',Path(tmp)):
            with patch.object(incremental,'MEMORY',incremental.OrderedDict()):
                incremental.save('sh600000','day',incremental.LiveSession(session,270))
                incremental.clear_memory()
                recovered,restored=incremental.get('sh600000','day')
                self.assertTrue(restored)
                self.assertIs(type(recovered.session.engine),type(session.engine))
                self.assertEqual(recovered.session.engine._observer_revision,session.engine._observer_revision)
                self.assertEqual(recovered.session.snapshot('sh600000'),session.snapshot('sh600000'))


if __name__=='__main__':unittest.main()
