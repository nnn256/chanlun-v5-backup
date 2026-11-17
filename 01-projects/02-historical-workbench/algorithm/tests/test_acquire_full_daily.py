from concurrent.futures import Future
from datetime import datetime
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import acquire_full_daily as module
from chanmodel.tdx_data import sha256


RECORD = {'symbol':'sz300949', 'name':'奥雅股份', 'exchange':'sz', 'code':'300949'}
AS_OF = '2026-11-17T15:00:00+08:00'


def response(empty=False):
    rows = [] if empty else [dict(Time='2021-02-26T00:00:00+08:00',Open=10000,High=12000,
                                Low=9000,Close=11000,Volume=2,Amount=22000),
                            dict(Time='2026-11-17T00:00:00+08:00',Open=12000,High=14000,
                                 Low=11000,Close=13000,Volume=3,Amount=39000)]
    data = {'list':rows, 'count':len(rows), 'meta':{'source':'tdx','type':'day'}}
    raw = json.dumps({'code':0,'data':data}).encode()
    return data, {'url':'http://offline/api/kline-all/tdx?code=sz300949&type=day',
                  'requested_at':AS_OF,'received_at':AS_OF,'http_status':200,
                  'content_type':'application/json','response_bytes':len(raw),'response_sha256':sha256(raw)}, raw


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.universe=self.root/'universe.json'
        self.universe.write_text(json.dumps({'records':[RECORD]}),encoding='utf-8')
        self.output=self.root/'acquisition'

    def run_batch(self,**kwargs):
        with patch.object(module,'resource_slots',return_value=(2,{'reason':'ready'})):
            return module.run(self.universe,self.output,base_url='http://offline',as_of=AS_OF,
                              workers=2,min_free_gb=0,min_free_memory_mb=0,**kwargs)

    def test_acquires_complete_returned_history_and_retains_raw_and_manifest(self):
        expected=response()
        with patch.object(module.TdxClient,'history',return_value=expected) as history:
            result=self.run_batch()
        self.assertTrue(result['processing_complete']);self.assertEqual(result['bars'],2)
        self.assertEqual(result['first_date'],'2021-02-26')
        history.assert_called_once_with('sz300949','tdx')
        cache=self.output/'cache/tdx/day'
        self.assertEqual(gzip.decompress((cache/'raw/sz300949.json.gz').read_bytes()),expected[2])
        manifest=json.loads((self.output/'results.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['records'][0]['csv_sha256'],sha256((cache/'ohlcv/sz300949.csv').read_bytes()))

    def test_resume_reuses_verified_artifacts_but_reacquires_corrupted_csv(self):
        with patch.object(module.TdxClient,'history',return_value=response()):self.run_batch()
        with patch.object(module.TdxClient,'history') as history:
            self.run_batch(resume=True);history.assert_not_called()
        (self.output/'cache/tdx/day/ohlcv/sz300949.csv').write_text('broken',encoding='utf-8')
        with patch.object(module.TdxClient,'history',return_value=response()) as history:
            result=self.run_batch(resume=True)
        history.assert_called_once();self.assertEqual(result['success'],1)

    def test_resume_rejects_changed_fixed_cutoff_and_output_cannot_be_reused_implicitly(self):
        with patch.object(module.TdxClient,'history',return_value=response()):self.run_batch()
        with self.assertRaisesRegex(ValueError,'--resume'):self.run_batch()
        with self.assertRaisesRegex(ValueError,'identity differs'):
            module.run(self.universe,self.output,base_url='http://other',as_of=AS_OF,resume=True)

    def test_empty_history_is_explicit_unavailable_with_evidence(self):
        with patch.object(module.TdxClient,'history',return_value=response(empty=True)):
            result=self.run_batch()
        self.assertEqual(result['unavailable'],1);self.assertEqual(result['success'],0)
        self.assertTrue(result['processing_complete']);self.assertFalse(result['successful_coverage_complete'])
        self.assertTrue((self.output/'cache/tdx/day/raw/sz300949.json.gz').is_file())

    def test_timeout_retries_then_success_without_old_source_fallback(self):
        with patch.object(module.TdxClient,'history',side_effect=[TimeoutError('upstream'),response()]) as history, \
             patch.object(module.time,'sleep'):
            result=self.run_batch(retries=1)
        self.assertEqual(history.call_count,2);self.assertEqual(result['success'],1)
        self.assertFalse(result['fallback_used'])

    def test_malformed_payload_keeps_raw_and_fails_without_padding(self):
        data,receipt,raw=response();data['count']=200
        with patch.object(module.TdxClient,'history',return_value=(data,receipt,raw)):
            result=self.run_batch(retries=0)
        self.assertEqual(result['failed'],1)
        self.assertEqual(len(list((self.output/'responses/sz300949').glob('*/response.json.gz'))),1)
        self.assertFalse((self.output/'cache/tdx/day/ohlcv/sz300949.csv').exists())

    def test_existing_stop_preserves_pending_and_starts_no_request(self):
        with patch.object(module.TdxClient,'history',return_value=response()):self.run_batch()
        # Delete an artifact to require acquisition on resume.
        (self.output/'cache/tdx/day/ohlcv/sz300949.csv').unlink()
        (self.output/'STOP').write_text('user pause')
        with patch.object(module.TdxClient,'history') as history:
            result=self.run_batch(resume=True)
        history.assert_not_called();self.assertEqual(result['state'],'paused');self.assertEqual(result['pending'],1)

    def test_identical_universe_duplicates_are_removed_but_conflicts_rejected(self):
        self.universe.write_text(json.dumps([RECORD,RECORD]),encoding='utf-8')
        rows,duplicates=module.load_universe(self.universe)
        self.assertEqual((len(rows),duplicates),(1,1))
        self.universe.write_text(json.dumps([RECORD,{**RECORD,'name':'conflict'}]),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'conflicting'):module.load_universe(self.universe)

    def test_low_disk_or_memory_stops_admission_but_drains_active_requests(self):
        disk=type('Usage',(),{'free':0})()
        with patch.object(module.shutil,'disk_usage',return_value=disk), \
             patch.object(module,'hardware_snapshot',return_value={'memory':{'available_bytes':100*module.MIB}}):
            allowed,resource=module.resource_slots(self.root,2,1,5,512)
            self.assertEqual(allowed,1);self.assertEqual(resource['reason'],'waiting_disk')
        disk.free=10*module.GIB
        with patch.object(module.shutil,'disk_usage',return_value=disk), \
             patch.object(module,'hardware_snapshot',return_value={'memory':{'available_bytes':100*module.MIB}}):
            allowed,resource=module.resource_slots(self.root,2,0,5,512)
            self.assertEqual(allowed,0);self.assertEqual(resource['reason'],'waiting_memory')


if __name__=='__main__':unittest.main()
