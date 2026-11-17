import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from build_full_data import (CONFIG,HERE,adapted_center,adapted_fractal,adapted_movement,
                             adapted_signal,demo_series,make_payload,pack_payload,source_bytes)
from chanmodel.v2.engine import analyze
from chanmodel.v2.recursive import audit_hierarchy
from chanmodel.segments import build_segments,characteristic_candidate


def fixture_moves(vertices):
    return [{'id':f'p:{i}','direction':'up' if b>a else 'down','start':10*i,'end':10*(i+1),
             'start_price':a,'end_price':b,'low':min(a,b),'high':max(a,b),
             'actual_low':min(a,b),'actual_high':max(a,b),'state':'confirmed','basis_closed':True,
             'basis_at':10*(i+1)+3} for i,(a,b) in enumerate(zip(vertices,vertices[1:]))]


class FullDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.series=demo_series()
        cls.payload,cls.complete=make_payload(cls.series)

    def test_default_has_feature_segments_and_recursive_types(self):
        final=self.payload['snapshots'][-1]
        self.assertGreater(len(final['segments']),30)
        self.assertTrue(any(x['rank']==2 and x['certificate']['sublevel_types_verified'] for x in final['centers']))
        self.assertGreaterEqual(len(final['hierarchy']['levels']),3)
        self.assertTrue(all(x['completed_types'] for x in final['hierarchy']['levels']))
        paths={x['confirmation']['path'] for x in final['segments'] if x.get('confirmation')}
        self.assertTrue(any(path.startswith('feature') for path in paths))

    def test_no_gap_feature_path(self):
        first=build_segments(fixture_moves([10,20,12,25,15,22,13]))[0]
        self.assertEqual(first['confirmation']['path'],'feature_no_gap')
        self.assertEqual((first['end_price'],first['confirm_move'],first['state']),(25,5,'confirmed'))

    def test_gap_feature_waits_for_second_sequence(self):
        moves=fixture_moves([0,10,5,30,20,25,15,24,18,27])
        self.assertEqual(characteristic_candidate(moves[:6],0,2)['state'],'pending')
        result=characteristic_candidate(moves,0,2)
        self.assertEqual((result['state'],result['confirm_move']),('confirmed',8))
        self.assertEqual(result['second_sequence']['kind'],'bottom')

    def test_gap_new_extreme_does_not_confirm_old_endpoint(self):
        result=characteristic_candidate(fixture_moves([0,10,5,30,20,25,15,31,18,32]),0,2)
        self.assertNotEqual(result['state'],'confirmed')

    def test_first_reverse_pen_is_not_end_confirmation(self):
        self.assertEqual(build_segments(fixture_moves([10,20,14,25,18]))[0]['state'],'provisional')
        self.assertEqual(build_segments(fixture_moves([10,20,14,25,18,22,18]))[0]['state'],'provisional')
        self.assertEqual(build_segments(fixture_moves([10,20,14,25,18,22,16]))[0]['state'],'confirmed')

    def test_every_prefix_certificate_passes(self):
        for s in self.payload['snapshots']:
            self.assertEqual(s['certificate_audit']['state'],'passed')
            self.assertEqual(audit_hierarchy(s['hierarchy'],s['as_of'])['state'],'passed')

    def test_adapter_equals_native_prefix(self):
        for n in (20,100,250,450,len(self.series.bars)):
            report=analyze(self.series,self.series.bars[n-1].closed_at,CONFIG,3)
            snapshot=self.payload['snapshots'][n-1]
            self.assertEqual(snapshot['strokes'],[adapted_movement(x,'stroke') for x in report['base']['strokes']])
            self.assertEqual(snapshot['segments'],[adapted_movement(x,'segment') for x in report['base']['segments']])
            self.assertEqual(snapshot['centers'],[adapted_center(x) for l in report['hierarchy']['levels'] for x in l['centers']])

    def test_time_fields_never_reference_future(self):
        for s in self.payload['snapshots']:
            i=s['as_of']
            for key in ('fractals','strokes','segments','centers','signal_candidates'):
                for item in s[key]:
                    for field in ('confirmed_at','available_at'):
                        if item.get(field) is not None:self.assertLessEqual(item[field],i)
            self.assertFalse(s['execution_allowed'])

    def test_partition_type_never_claims_turn(self):
        for level in self.complete['hierarchy']['levels']:
            for unit in level['completed_types']:
                self.assertFalse(unit['completion']['is_turn_confirmation'])

    def test_full_study_layers_are_calculated(self):
        for key in ('feature_sequences','center_evolution','center_monitors','decompositions'):
            self.assertTrue(self.payload['full_layers'][key],key)
        self.assertIn('construction_phases',self.payload['full_layers'])
        self.assertFalse(self.complete['strict_original_equivalence_proven'])

    def test_interning_preserves_structure_records(self):
        packed=pack_payload(self.payload);arena=packed['arena']
        for n in (0,50,200,len(packed['frames'])-1):
            f=packed['frames'][n];s=self.payload['snapshots'][n]
            for key,ids in f['_lists'].items():self.assertEqual([arena[i] for i in ids],s[key])
            for key,i in f['_objects'].items():self.assertEqual(arena[i],s[key])

    def test_full_cli_writes_portable_report(self):
        with tempfile.TemporaryDirectory() as temp:
            csv=Path(temp)/'sample.csv';csv.write_bytes(source_bytes(self.series))
            output=Path(temp)/'out.json'
            result=subprocess.run([sys.executable,str(HERE/'run_analysis.py'),'--csv',str(csv),'--period','5m',
                                   '--symbol','sz000001','--output',str(output)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            value=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(value['schema'],'chanlun.complete.v3')
            self.assertFalse(value['execution_allowed'])

    def test_modified_future_does_not_change_past(self):
        n=200
        a=analyze(self.series,self.series.bars[n-1].closed_at,CONFIG,3)
        from dataclasses import replace
        mutated=replace(self.series,bars=self.series.bars[:n]+tuple(replace(b,open=b.open+1,close=b.close+1,high=b.high+1,low=b.low+1) for b in self.series.bars[n:]))
        b=analyze(mutated,self.series.bars[n-1].closed_at,CONFIG,3)
        self.assertEqual(a,b)


if __name__=='__main__':unittest.main()
