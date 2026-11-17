import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import patch

from chanmodel.model import Candle
from workbench import live


class LiveLoadingParallelTests(unittest.TestCase):
    def setUp(self):
        self.bar = Candle(0, 10, 11, 9, 10, '2026-11-13T15:00:00+08:00', 100)

    def result(self):
        return object(), (self.bar,), {'observed_at': self.bar.closed_at}, {
            'checkpoint_sha256': 'unchanged-closed-history', 'report': {'signals': []}}

    def test_all_periods_acquire_concurrently_and_keep_period_identity(self):
        barrier = threading.Barrier(3, timeout=3)
        calls = []

        def acquire(code, period):
            calls.append((code, period))
            # This cannot complete if the implementation silently becomes serial.
            barrier.wait()
            return self.result()

        with patch.object(live, '_shared_ingest', side_effect=lambda c, p, e: acquire(c, p)):
            inputs, receipts, sessions, errors = live._period_inputs(
                'bj920000', ('day', '30m', '5m'), 'http://one', True)
        self.assertCountEqual(calls, [('bj920000', p) for p in ('day', '30m', '5m')])
        self.assertEqual(list(inputs), ['day', '30m', '5m'])
        self.assertEqual([value.period for value in inputs.values()], ['day', '30m', '5m'])
        self.assertFalse(errors)

    def test_overlapping_day_and_all_share_acquisition_but_isolate_annotations(self):
        started = threading.Event()
        joined = threading.Event()
        release = threading.Event()

        class ObservedFuture(Future):
            def result(self, *args, **kwargs):
                if not self.done():
                    joined.set()
                return super().result(*args, **kwargs)

        def acquire(code, period):
            started.set()
            if not release.wait(3):
                raise AssertionError('test did not release acquisition')
            return self.result()

        with patch.object(live, 'Future', ObservedFuture), patch.object(live, '_ingest', side_effect=acquire) as ingest:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(live._shared_ingest, 'bj920000', 'day', 'http://one')
                self.assertTrue(started.wait(2))
                second = pool.submit(live._shared_ingest, 'bj920000', 'day', 'http://one')
                try:
                    self.assertTrue(joined.wait(2))
                finally:
                    release.set()
                a, b = first.result(), second.result()
        ingest.assert_called_once_with('bj920000', 'day')
        a[3]['report']['signals'].append('caller-specific-annotation')
        self.assertEqual(b[3]['report']['signals'], [])
        self.assertIs(a[0], b[0])

    def test_different_sources_do_not_share_period_acquisition(self):
        barrier = threading.Barrier(2, timeout=3)

        def acquire(code, period):
            barrier.wait()
            return self.result()

        with patch.object(live, '_ingest', side_effect=acquire) as ingest:
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(live._shared_ingest, 'bj920000', 'day', 'http://one')
                b = pool.submit(live._shared_ingest, 'bj920000', 'day', 'http://two')
                a.result(); b.result()
        self.assertEqual(ingest.call_count, 2)

    def test_failed_acquisition_is_removed_and_a_retry_can_succeed(self):
        with patch.object(live, '_ingest', side_effect=[TimeoutError('upstream wait'), self.result()]) as ingest:
            with self.assertRaisesRegex(TimeoutError, 'upstream wait'):
                live._shared_ingest('bj920000', 'day', 'http://one')
            result = live._shared_ingest('bj920000', 'day', 'http://one')
        self.assertEqual(ingest.call_count, 2)
        self.assertEqual(result[3]['checkpoint_sha256'], 'unchanged-closed-history')


if __name__ == '__main__':
    unittest.main()
