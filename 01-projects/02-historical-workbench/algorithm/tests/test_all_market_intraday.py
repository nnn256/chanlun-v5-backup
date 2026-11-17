"""Durable batch accounting, source integrity, STOP/resume and validation gates."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chanmodel.model import Candle
from chanmodel.tdx_intraday import cache_intraday
from tools import run_all_market_intraday as batch


class AllMarketIntradayTests(unittest.TestCase):
    def fixture(self,root):
        universe=root/'universe.json'
        universe.write_text(json.dumps([{'symbol':'sh600000','name':'fixture'}]),encoding='utf-8')
        return universe

    def test_universe_rejects_duplicate_and_non_A_security(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'u.json'
            p.write_text('["sz000001","sz000001"]')
            with self.assertRaisesRegex(ValueError,'duplicate'):batch.load_universe(p)
            p.write_text('["sh510300"]')
            with self.assertRaisesRegex(ValueError,'A-share'):batch.load_universe(p)

    def test_stop_submits_nothing_and_resume_checks_frozen_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);u=self.fixture(root);out=root/'run';out.mkdir();(out/'STOP').touch()
            with patch.object(batch,'code_identity',return_value={'sha256':'frozen','files':{}}),\
                 patch.object(batch,'worker',side_effect=AssertionError('STOP must not dispatch')):
                result=batch.run(u,root/'cache',out,'2026-11-13T15:00:00+08:00',min_free_gb=0)
            self.assertEqual(result['state'],'stopped_by_file')
            self.assertEqual(result['verified'],0)
            self.assertFalse(result['processing_complete'])
            with patch.object(batch,'code_identity',return_value={'sha256':'changed','files':{}}):
                with self.assertRaisesRegex(ValueError,'frozen code'):
                    batch.run(u,root/'cache',out,'2026-11-13T15:00:00+08:00',resume=True,min_free_gb=0)

    def test_missing_source_is_not_success_and_failure_is_retryable(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);u=self.fixture(root)
            with patch.object(batch,'code_identity',return_value={'sha256':'frozen','files':{}}):
                result=batch.run(u,root/'cache',root/'run','2026-11-13T15:00:00+08:00',min_free_gb=0,min_free_memory_mb=0)
                self.assertEqual(result['source_unavailable'],2)
                self.assertTrue(result['processing_complete'])
                self.assertFalse(result['successful_coverage_complete'])
                second=batch.run(u,root/'cache',root/'run','2026-11-13T15:00:00+08:00',resume=True,retry_failed=True,min_free_gb=0,min_free_memory_mb=0)
                self.assertEqual(second['verified'],0)
                self.assertEqual(second['source_unavailable'],2)

    def test_disk_gate_stops_dispatch_without_losing_pending_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);u=self.fixture(root)
            with patch.object(batch,'code_identity',return_value={'sha256':'frozen','files':{}}),\
                 patch.object(batch.shutil,'disk_usage',return_value=type('D',(),{'free':1})()):
                result=batch.run(u,root/'cache',root/'run','2026-11-13T15:00:00+08:00',min_free_gb=1)
            self.assertEqual(result['state'],'stopped_low_disk')
            self.assertEqual(result['counts'],{'pending':2})

    def test_verification_failure_cannot_mark_worker_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'tasks.sqlite3';u=self.fixture(root)
            manifest={'output':str(root),'cache':str(root/'cache'),'cutoff':'2026-11-13T15:00:00+08:00',
                      'config':batch.asdict_config(),'code':{'sha256':'frozen','files':{}},
                      'universe':[{'symbol':'sh600000'}],'periods':['1m']}
            batch.initialize(db,manifest)
            with patch.object(batch,'code_identity',return_value=manifest['code']),\
                 patch.object(batch,'source_identity',return_value={'csv_sha256':'source'}),\
                 patch.object(batch,'run_one',return_value={'alerts':1,'artifact':'fixture'}),\
                 patch.object(batch,'audit_record',return_value={'state':'failed','errors':['deliberate mismatch']}):
                result=batch.worker('sh600000','1m',manifest,str(db),None)
            self.assertEqual(result['state'],'failed')
            with closing(batch.connect_db(db)) as connection:
                row=connection.execute('SELECT * FROM tasks').fetchone()
            self.assertEqual(row['state'],'failed')
            self.assertIn('independent replay failed',row['error'])

    def test_changed_frozen_source_cannot_be_retried_as_a_new_dataset(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'tasks.sqlite3';self.fixture(root)
            manifest={'output':str(root),'cache':str(root/'cache'),'cutoff':'2026-11-13T15:00:00+08:00',
                      'config':batch.asdict_config(),'code':{'sha256':'frozen','files':{}},
                      'universe':[{'symbol':'sh600000'}],'periods':['5m']}
            batch.initialize(db,manifest)
            with patch.object(batch,'code_identity',return_value=manifest['code']),\
                 patch.object(batch,'source_identity',return_value={'csv_sha256':'changed'}),\
                 patch.object(batch,'run_one',side_effect=AssertionError('changed input was replayed')):
                result=batch.worker('sh600000','5m',manifest,str(db),{'csv_sha256':'original'})
            self.assertEqual(result['state'],'failed')
            self.assertIn('source changed',result['error'])

    def test_verified_integrity_check_rejects_changed_artifact_or_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);csv,meta=batch.source_paths(root,'sh600000','5m')
            csv.parent.mkdir(parents=True);csv.write_bytes(b'csv');meta.parent.mkdir(parents=True);meta.write_bytes(b'meta')
            artifact=root/'artifact.gz';artifact.write_bytes(b'artifact')
            row={'symbol':'sh600000','period':'5m','source_identity':json.dumps({'storage_sha256':batch.file_hash(csv),'metadata_sha256':batch.file_hash(meta)}),
                 'record':json.dumps({'artifact':str(artifact),'artifact_sha256':batch.file_hash(artifact)}),
                 'verification':json.dumps({'state':'passed'})}
            self.assertTrue(batch.verified_still_intact(row,root))
            meta.write_bytes(b'changed')
            self.assertFalse(batch.verified_still_intact(row,root))

    def test_following_acquisition_ends_only_on_completed_source_status(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'status.json'
            self.assertFalse(batch.acquisition_finished(p))
            p.write_text('{"state":"running","processing_complete":false}')
            self.assertFalse(batch.acquisition_finished(p))
            p.write_text('{"state":"completed","processing_complete":true}')
            self.assertTrue(batch.acquisition_finished(p))

    def test_sql_aggregate_preserves_verified_totals_and_separates_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'tasks.sqlite3'
            manifest={'cutoff':'2026-11-13T15:00:00+08:00','periods':['1m','5m'],
                      'universe':[{'symbol':'sh600000'},{'symbol':'sz000001'}],
                      'code':{'sha256':'frozen'}}
            batch.initialize(db,manifest)
            with closing(batch.connect_db(db)) as connection:
                connection.execute("UPDATE tasks SET state='verified',record=? WHERE symbol='sh600000' AND period='1m'",(json.dumps({'input_bars':123,'alerts':4,'evaluation_sessions':['large field']*100}),))
                connection.execute("UPDATE tasks SET state='verified',record=? WHERE symbol='sh600000' AND period='5m'",(json.dumps({'input_bars':50,'alerts':0}),))
                connection.execute("UPDATE tasks SET state='failed',error='no source' WHERE symbol='sz000001' AND period='1m'")
                connection.commit()
            summary=batch.aggregate(db,manifest,'running')
            self.assertEqual(summary['requested'],4)
            self.assertEqual(summary['verified'],2)
            self.assertEqual(summary['bars_verified'],173)
            self.assertEqual(summary['alerts_verified'],4)
            self.assertEqual(summary['failed'],1)
            self.assertFalse(summary['processing_complete'])
            self.assertFalse(summary['successful_coverage_complete'])
            self.assertEqual(summary['failed_records'],[{'symbol':'sz000001','period':'1m','error':'no source'}])

    def test_stop_drains_active_security_without_dispatching_next_period(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);u=self.fixture(root);out=root/'run'
            for period in ('1m','5m'):
                csv,meta=batch.source_paths(root/'cache','sh600000',period)
                csv.parent.mkdir(parents=True,exist_ok=True);csv.write_bytes(b'present')
                meta.parent.mkdir(parents=True,exist_ok=True);meta.write_bytes(b'present')
            calls=[]
            def done_worker(code,period,manifest,db_path,expected):
                calls.append((code,period));(out/'STOP').touch()
                return {'state':'verified','record':{'input_bars':10,'alerts':0},
                        'verification':{'state':'passed'},'source_identity':{'csv_sha256':'fixture'}}
            def threads(**kwargs):return ThreadPoolExecutor(max_workers=kwargs['max_workers'])
            with patch.object(batch,'ProcessPoolExecutor',side_effect=threads),\
                 patch.object(batch,'code_identity',return_value={'sha256':'frozen','files':{}}),\
                 patch.object(batch,'worker',side_effect=done_worker):
                result=batch.run(u,root/'cache',out,'2026-11-13T15:00:00+08:00',workers=1,min_free_gb=0,min_free_memory_mb=0)
            self.assertEqual(result['state'],'stopped_by_file')
            self.assertEqual(result['verified'],1)
            self.assertEqual(result['counts'].get('pending'),1)
            self.assertEqual(len(calls),1)

    def test_low_ram_waits_and_does_not_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);u=self.fixture(root);out=root/'run'
            def stop_after_wait(_): (out/'STOP').touch()
            with patch.object(batch,'code_identity',return_value={'sha256':'frozen','files':{}}),\
                 patch.object(batch,'available_memory_bytes',return_value=1),\
                 patch.object(batch.time,'sleep',side_effect=stop_after_wait),\
                 patch.object(batch,'worker',side_effect=AssertionError('low RAM dispatched work')):
                result=batch.run(u,root/'cache',out,'2026-11-13T15:00:00+08:00',min_free_gb=0,min_free_memory_mb=512)
            self.assertEqual(result['verified'],0)
            self.assertEqual(result['counts'],{'pending':2})


if __name__=='__main__':unittest.main()
