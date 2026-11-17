from concurrent.futures import ThreadPoolExecutor
import json
import threading
import unittest
from unittest.mock import patch

from workbench import saved_result_cache as cache


class CacheDecodeConcurrencyTests(unittest.TestCase):
    def test_decoding_one_hit_does_not_block_another_stock_build(self):
        with cache.LOCK:
            cache.CACHE.clear();cache.CACHE_BYTES=0
        cache.get_or_build('slow',lambda:{'stock':'slow'})
        decode_entered=threading.Event();release=threading.Event();other_built=threading.Event()
        decode=json.loads
        def slow_decode(raw):
            if b'"slow"' in raw:
                decode_entered.set()
                if not release.wait(3):raise AssertionError('decode was not released')
            return decode(raw)
        def build_other():
            other_built.set();return {'stock':'fast'}
        with patch.object(cache.json,'loads',side_effect=slow_decode):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first=pool.submit(cache.get_or_build,'slow',lambda:None)
                self.assertTrue(decode_entered.wait(2))
                second=pool.submit(cache.get_or_build,'other',build_other)
                try:self.assertTrue(other_built.wait(2),'unrelated build blocked behind decoding')
                finally:release.set()
                self.assertEqual(first.result(3),{'stock':'slow'})
                self.assertEqual(second.result(3),{'stock':'fast'})


if __name__=='__main__':unittest.main()
