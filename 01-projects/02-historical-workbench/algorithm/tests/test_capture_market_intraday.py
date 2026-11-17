from datetime import datetime
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from tools import capture_market_intraday as capture
from chanmodel.tdx_data import sha256
from chanmodel.v2.io import load_cache_series


class NativeMarketCaptureTests(unittest.TestCase):
    def response(self,empty=False):
        rows=[] if empty else [{'Time':'2026-11-13T09:31:00+08:00','Open':10000,'High':11000,
                              'Low':9000,'Close':10500,'Volume':100,'Amount':1000000}]
        data={'count':len(rows),'list':rows,'meta':{'source':'tdx','type':'minute1'}}
        raw=json.dumps({'code':0,'data':data}).encode()
        receipt={'response_sha256':sha256(raw),'requested_at':'2026-11-15T12:00:00+08:00','received_at':'2026-11-15T12:00:00+08:00'}
        return data,receipt,raw

    def test_capture_roundtrip_and_resume_independently_rechecks_raw_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=self.response();cut='2026-11-13T15:00:00+08:00'
            with patch.object(capture,'TdxClient') as client:
                client.return_value.request_retry.return_value=data
                first=capture.capture_one('sz000001','1m',root,cut)
                self.assertEqual(first['state'],'complete');self.assertFalse(first['resumed'])
                series,receipt=load_cache_series(root,'sz000001','1m')
                self.assertEqual(len(series.bars),1)
                again=capture.capture_one('sz000001','1m',root,cut)
                self.assertTrue(again['resumed']);self.assertEqual(client.return_value.request_retry.call_count,1)
                raw=Path(json.loads((root/'tdx/minute1/metadata/sz000001.json').read_text())['raw_path'])
                raw.write_bytes(b'broken')
                rebuilt=capture.capture_one('sz000001','1m',root,cut)
                self.assertFalse(rebuilt['resumed']);self.assertEqual(client.return_value.request_retry.call_count,2)

    def test_empty_source_is_unavailable_not_successful_empty_ohlc(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(capture,'TdxClient') as client:
            client.return_value.request_retry.return_value=self.response(empty=True)
            result=capture.capture_one('sz000001','1m',Path(tmp),'2026-11-13T15:00:00+08:00')
            self.assertEqual(result['state'],'unavailable');self.assertEqual(result['bars'],0)
            self.assertTrue(Path(result['raw_path']).is_file())
            self.assertFalse((Path(tmp)/'tdx/minute1/ohlcv/sz000001.csv.gz').exists())

    def test_cutoff_price_policy_change_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(capture,'TdxClient') as client:
            client.return_value.request_retry.return_value=self.response()
            capture.capture_one('sz000001','1m',tmp,'2026-11-13T15:00:00+08:00')
            result=capture.capture_one('sz000001','1m',tmp,'2026-11-13T14:00:00+08:00')
            self.assertFalse(result['resumed']);self.assertEqual(client.return_value.request_retry.call_count,2)

    def test_progress_completed_means_attempted_all_and_retains_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);universe=root/'universe.json'
            universe.write_text(json.dumps([{'symbol':'sz000001'},{'symbol':'sh600000'}]))
            def one(code,period,cache,*args,**kwargs):
                value={'symbol':code,'period':period,'state':'complete' if code=='sz000001' else 'failed','bars':10 if code=='sz000001' else 0}
                capture.atomic_json(Path(cache)/'capture-status'/period/(code+'.json'),value)
                return value
            with patch.object(capture,'capture_one',side_effect=one):
                result=capture.run_capture(universe,root/'output','2026-11-13T15:00:00+08:00','http://127.0.0.1:65004',periods=('1m',),min_free_gb=0)
            self.assertTrue(result['processing_complete']);self.assertEqual(result['done'],2)
            self.assertEqual(result['failed'],1);self.assertEqual(result['complete'],1)
            self.assertEqual(len(result['entries']),2)
            saved=json.loads((root/'output/summary.json').read_text())
            self.assertNotIn('entries',saved)
            self.assertTrue(saved['status_final_count_verified'])
            self.assertEqual(len((root/'output/acquisition-events.jsonl').read_text().splitlines()),2)
            self.assertEqual(len(json.loads((root/'output/acquisition-results.json').read_text())['entries']),2)
            with self.assertRaisesRegex(ValueError,'different frozen universe'):
                capture.run_capture(universe,root/'output','2026-11-12T15:00:00+08:00','http://127.0.0.1:65004')

    def test_stop_file_submits_no_requests_and_retains_explicit_incomplete_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);universe=root/'universe.json';universe.write_text(json.dumps(['sz000001']))
            out=root/'output';out.mkdir();(out/'STOP').write_text('stop')
            with patch.object(capture,'capture_one') as request:
                result=capture.run_capture(universe,out,'2026-11-13T15:00:00+08:00','http://127.0.0.1:65004',min_free_gb=0)
            request.assert_not_called();self.assertEqual(result['state'],'stopped_by_request')
            self.assertFalse(result['processing_complete']);self.assertEqual(result['done'],0)
            self.assertTrue((out/'acquisition.lock').exists())

    def test_low_disk_stops_cleanly_before_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);universe=root/'universe.json';universe.write_text(json.dumps(['sz000001']))
            with patch.object(capture.shutil,'disk_usage',return_value=Mock(free=1)),patch.object(capture,'capture_one') as request:
                result=capture.run_capture(universe,root/'output','2026-11-13T15:00:00+08:00','http://127.0.0.1:65004',min_free_gb=10)
            request.assert_not_called();self.assertEqual(result['state'],'stopped_low_disk')
            self.assertFalse(result['processing_complete'])

    def test_concurrent_capture_output_is_rejected_without_deleting_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            with capture.capture_output_lock(tmp):
                with self.assertRaisesRegex(ValueError,'already writing'):
                    with capture.capture_output_lock(tmp):pass
            self.assertTrue((Path(tmp)/'acquisition.lock').exists())


if __name__=='__main__':unittest.main()
