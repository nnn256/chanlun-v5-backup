from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tests.test_recursive_v2 import daily_series
from workbench import reference_service as service


class ReferenceReportCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        context=patch.object(service,'STATE',self.root)
        context.start();self.addCleanup(context.stop)
        with service.LOCK:
            service.CACHE.clear();service.FLIGHTS.clear()

    def fake(self,symbol,period,bars,cutoff,key,source,adjustment):
        return {'engine_commit':service.COMMIT,'input_sha256':key,'signals':[{'state':'needs_review'}],
                'geometry_review':{'state':'reviewed'},'base':{'bars':len(bars)}}

    def request(self):
        bars=daily_series(40).bars
        return service.reference_report('sz000001','day',bars,bars[-1].closed_at)

    def test_memory_and_disk_return_independent_reviewed_results_without_recalculation(self):
        with patch.object(service,'analyze_reference',side_effect=self.fake) as compute:
            first=self.request();first['signals'][0]['state']='caller-only'
            second=self.request()
            service.CACHE.clear()
            third=self.request()
        self.assertEqual(compute.call_count,1)
        self.assertEqual(second,third)
        self.assertEqual(second['signals'][0]['state'],'needs_review')
        self.assertIsNot(second['signals'],third['signals'])
        self.assertTrue(all(isinstance(raw,bytes) for raw in service.CACHE.values()))

    def test_parallel_identical_requests_compute_once(self):
        started=threading.Event();release=threading.Event()
        def build(*args):
            started.set();self.assertTrue(release.wait(3));return self.fake(*args)
        with patch.object(service,'analyze_reference',side_effect=build) as compute:
            with ThreadPoolExecutor(max_workers=4) as pool:
                first=pool.submit(self.request);self.assertTrue(started.wait(2))
                rest=[pool.submit(self.request) for _ in range(3)]
                release.set();values=[first.result(3)]+[f.result(3) for f in rest]
        self.assertEqual(compute.call_count,1)
        self.assertTrue(all(v==values[0] for v in values))
        self.assertEqual(len({id(v['signals']) for v in values}),4)

    def test_failed_owner_cleans_flight_and_can_retry(self):
        with patch.object(service,'analyze_reference',side_effect=ValueError('invalid history')):
            with self.assertRaisesRegex(ValueError,'invalid history'):self.request()
        self.assertFalse(service.FLIGHTS)
        with patch.object(service,'analyze_reference',side_effect=self.fake):
            self.assertEqual(self.request()['base']['bars'],40)

    def test_byte_budget_evicts_or_bypasses_without_dropping_results(self):
        with patch.object(service,'analyze_reference',side_effect=self.fake), \
             patch.object(service,'MAX_CACHE_BYTES',1):
            value=self.request()
        self.assertEqual(value['base']['bars'],40)
        self.assertFalse(service.CACHE)
        self.assertTrue(list(self.root.rglob('*.json.gz')))

    def test_adapter_revision_invalidates_disk_and_memory(self):
        with patch.object(service,'analyze_reference',side_effect=self.fake) as compute:
            first=self.request()
            with patch.object(service,'ADAPTER_VERSION','next-reviewed-adapter'):
                second=self.request()
        self.assertEqual(compute.call_count,2)
        self.assertNotEqual(first['input_sha256'],second['input_sha256'])

    def test_mismatched_disk_input_is_rejected(self):
        with patch.object(service,'analyze_reference',side_effect=self.fake):self.request()
        path=next(self.root.rglob('*.json.gz'))
        value=json.loads(gzip.decompress(path.read_bytes()));value['input_sha256']='changed'
        path.write_bytes(gzip.compress(json.dumps(value).encode()))
        service.CACHE.clear()
        with self.assertRaisesRegex(ValueError,'identity mismatch'):self.request()


if __name__=='__main__':unittest.main()
