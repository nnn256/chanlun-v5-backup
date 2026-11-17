from pathlib import Path
import json
import tempfile
import unittest

from tools.serve_full_history_progress import snapshot


class FullHistoryProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'daily';self.root.mkdir()
        self.minute=Path(self.temp.name)/'minute'

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')

    def test_missing_summaries_show_pending_without_inventing_zero_success(self):
        value=snapshot(self.root,self.minute)
        self.assertEqual(value['pipeline']['state'],'pending')
        self.assertTrue(value['read_only'])
        for stage in value['stages'].values():
            self.assertEqual(stage['state'],'pending')
            self.assertIsNone(stage['successful'])
            self.assertIsNone(stage['processing_complete'])

    def test_prepared_pipeline_shows_planned_count_and_ignores_smoke_results(self):
        self.write(self.root/'pipeline.json',{'securities':5580})
        self.write(self.root/'status.json',{'state':'prepared','securities':5580})
        self.write(self.root/'smoke/v4/summary.json',{'completed':3,'total':3,'failed':0,'processing_complete':True})
        value=snapshot(self.root,self.minute)
        self.assertEqual(value['pipeline']['state'],'prepared')
        self.assertEqual(value['stages']['v3']['planned_total'],5580)
        self.assertFalse(value['stages']['v4']['available'])

    def test_actual_success_failures_and_exclusions_stay_separate(self):
        self.write(self.root/'inputs/coverage.json',{'requested':4,'source_pairs':3,'v4_eligible':2,
                   'v4_excluded':[{'symbol':'sz000001'},{'symbol':'sz000002'}]})
        self.write(self.root/'acquisition/summary.json',{'state':'completed','requested':4,'done':4,'complete':3,'failed':1,'unavailable':0,'bars':100})
        self.write(self.root/'v4-daily/summary.json',{'total':2,'completed':1,'failed':1,'bars':70,'processing_complete':True,'successful_coverage_complete':False})
        self.write(self.root/'v3-daily/summary.json',{'state':'completed','requested':4,'processed':4,
                   'counts':{'complete':2,'failed':1,'insufficient_history':1},'processing_complete':True,
                   'successful_coverage_complete':False,'bars':90})
        self.write(self.minute/'analysis/summary.json',{'state':'running','requested':8,'verified':3,'failed':1,'source_unavailable':1,'bars_verified':500})
        value=snapshot(self.root,self.minute)
        self.assertEqual(value['stages']['acquisition']['successful'],3)
        self.assertEqual(value['stages']['v4']['processed'],2)
        self.assertEqual(value['stages']['v4']['excluded'],2)
        self.assertFalse(value['stages']['v4']['successful_coverage_complete'])
        self.assertEqual(value['stages']['v3']['successful'],2)
        self.assertEqual(value['stages']['v3']['excluded'],1)
        self.assertEqual(value['stages']['intraday']['processed'],5)
        self.assertEqual(value['stages']['intraday']['bars'],500)

    def test_malformed_status_does_not_hide_other_stages(self):
        (self.root/'status.json').write_text('{unfinished',encoding='utf-8')
        self.write(self.root/'v3-daily/summary.json',{'state':'running','requested':4,'processed':1,'counts':{'complete':1}})
        value=snapshot(self.root,self.minute)
        self.assertIn('status',value['read_errors'])
        self.assertEqual(value['stages']['v3']['successful'],1)


if __name__=='__main__':unittest.main()
