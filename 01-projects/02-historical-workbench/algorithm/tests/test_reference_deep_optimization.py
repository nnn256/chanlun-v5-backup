import copy
import json
import random
from types import SimpleNamespace
import unittest

from chanmodel.reference_engine import (
    ReferenceSession,_line_indices,_point_signature_parts,_signature_identity,review_geometry)
from tests.fixtures.reference_geometry_443 import review_geometry as previous_review
from tests.test_recursive_v2 import daily_series


class ReferenceDeepOptimizationTests(unittest.TestCase):
    def test_lean_point_comparison_equals_legacy_payload_identity(self):
        cases=[None,False,0,0.0,-0.0,1,1.0,'1',{},[],{'nested':[1,2]}]
        for feature in cases:
            point=SimpleNamespace(bi=SimpleNamespace(is_sure=True,
                get_begin_klu=lambda:SimpleNamespace(idx=3)),klu=SimpleNamespace(idx=8),
                relate_bsp1=SimpleNamespace(klu=SimpleNamespace(idx=1)),
                features={'z':feature,'a':1.25})
            identity,parts=_point_signature_parts(point)
            expected={'begin':3,'end':8,'sure':True,'first_context':1,
                      'features':dict(point.features.items())}
            self.assertEqual(identity,_signature_identity(expected))
            if not isinstance(parts,dict):
                begin,end,sure,first,items=parts
                parts={'begin':begin,'end':end,'sure':sure,'first_context':first,'features':dict(items)}
            self.assertEqual(json.dumps(parts,sort_keys=True),json.dumps(expected,sort_keys=True))
        for bad in (float('nan'),float('inf'),float('-inf')):
            point.features={'a':bad}
            with self.assertRaises(ValueError):_point_signature_parts(point)

    def test_endpoint_memo_agrees_before_and_after_native_tail_revisions(self):
        session=ReferenceSession()
        for bar in daily_series(700).bars:
            session.append(bar)
            if len(session.engine.bi_list):
                line=session.engine.bi_list[-1]
                expected=(line.get_begin_klu().idx,line.get_end_klu().idx)
                self.assertEqual(_line_indices(line),expected)
                line.clean_cache()
                self.assertEqual(_line_indices(line),expected)

    def test_geometry_matches_preserved_reviewer_for_random_signal_ranges_and_disputes(self):
        session=ReferenceSession()
        for bar in daily_series(1600).bars:session.append(bar)
        report=session.snapshot('sz000001');rng=random.Random(443)
        self.assertTrue(report['base']['segments'])
        for seed in range(20):
            sample=copy.deepcopy(report)
            for stroke in sample['base']['strokes']:
                if rng.random()<.13:stroke['end_price']+=.01
            for segment in sample['base']['segments']:
                if rng.random()<.13:segment['start_price']-=.02
            for signal in sample['signals']:
                a=rng.randrange(1000);signal['terminal_range']=[a,a+rng.randrange(400)]
            if seed%3==0:rng.shuffle(sample['base']['strokes'])
            self.assertEqual(review_geometry(copy.deepcopy(sample)),previous_review(copy.deepcopy(sample)))

    def test_geometry_selection_preserves_boundary_touch_and_duplicate_endpoints(self):
        strokes=[{'id':'a','start':0,'end':2,'start_price':10,'end_price':11,'direction':'up','state':'confirmed'},
                 {'id':'b','start':2,'end':4,'start_price':11,'end_price':9,'direction':'down','state':'confirmed'},
                 {'id':'c','start':4,'end':6,'start_price':9,'end_price':12,'direction':'up','state':'confirmed'}]
        for start,end in [(0,6),(2,4),(1,5),(4,4),(7,8)]:
            sample={'base':{'merged':[],'fractals':[],'strokes':copy.deepcopy(strokes),
                'segments':[{'id':'s','start':start,'end':end,'start_price':10,'end_price':12,
                             'direction':'up','state':'confirmed'}]},'signals':[],'hierarchy':{'levels':[]}}
            self.assertEqual(review_geometry(copy.deepcopy(sample)),previous_review(copy.deepcopy(sample)))


if __name__=='__main__':unittest.main()
