import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from tools import full_history_pipeline as pipeline


class FullHistoryPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_fixed_universe_and_code_reject_changes(self):
        universe=self.root/'inputs/universe.json';pipeline.atomic(universe,{'records':[{'symbol':'sh600000'}]})
        source=self.root/'code/v4/example.py';source.parent.mkdir(parents=True);source.write_text('x=1')
        config={'universe_sha256':pipeline.digest(universe),'frozen_files':{'v4/example.py':pipeline.digest(source)}}
        pipeline.verify_code(self.root,config)
        source.write_text('x=2')
        with self.assertRaisesRegex(ValueError,'code changed'):pipeline.verify_code(self.root,config)
        source.write_text('x=1');pipeline.atomic(universe,{'records':[]})
        with self.assertRaisesRegex(ValueError,'universe changed'):pipeline.verify_code(self.root,config)

    def test_selection_binds_acquisition_and_eligible_sources(self):
        paths={'sources_sha256':'inputs/daily-sources.json',
               'eligible_universe_sha256':'inputs/v4-eligible-universe.json',
               'acquisition_manifest_sha256':'acquisition/manifest.json',
               'acquisition_results_sha256':'acquisition/results.json'}
        for path in paths.values():pipeline.atomic(self.root/path,{'frozen':True})
        pipeline.atomic(self.root/'inputs/selection-identity.json',
                        {key:pipeline.digest(self.root/path) for key,path in paths.items()})
        pipeline.verify_selection(self.root)
        pipeline.atomic(self.root/'acquisition/results.json',{'changed':True})
        with self.assertRaisesRegex(ValueError,'selection changed'):pipeline.verify_selection(self.root)

    def test_stop_before_child_created_directory_is_forwarded_without_killing_work(self):
        (self.root/'STOP').write_text('user stop')
        process=Mock(pid=123,returncode=3);process.poll.side_effect=[None,3]
        with patch.object(pipeline.subprocess,'Popen',return_value=process),patch.object(pipeline.time,'sleep'):
            complete=pipeline.run_child(self.root,{'securities':2},'acquisition',['ignored'],self.root/'acquisition/summary.json')
        self.assertFalse(complete)
        self.assertTrue((self.root/'acquisition/STOP').is_file())
        process.kill.assert_not_called();process.terminate.assert_not_called()

    def test_acquisition_terminal_failures_are_reviewable_and_do_not_claim_success(self):
        summary=self.root/'acquisition/summary.json'
        pipeline.atomic(summary,{'state':'completed','processing_complete':True,'failed':1,'success':1})
        process=Mock(pid=123,returncode=1);process.poll.return_value=1
        with patch.object(pipeline.subprocess,'Popen',return_value=process):
            self.assertTrue(pipeline.run_child(self.root,{'securities':2},'acquisition',['ignored'],summary))
        value=json.loads(summary.read_text());self.assertEqual(value['failed'],1)

    def test_incomplete_child_is_an_error_instead_of_launching_next_stage(self):
        summary=self.root/'v4-daily/summary.json'
        pipeline.atomic(summary,{'processing_complete':False,'completed':1,'total':2})
        process=Mock(pid=123,returncode=0);process.poll.return_value=0
        with patch.object(pipeline.subprocess,'Popen',return_value=process):
            with self.assertRaisesRegex(RuntimeError,'entire schedule'):
                pipeline.run_child(self.root,{'securities':2},'v4-daily',['ignored'],summary)


if __name__=='__main__':unittest.main()
