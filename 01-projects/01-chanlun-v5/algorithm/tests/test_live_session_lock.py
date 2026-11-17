import threading
import unittest
from unittest.mock import patch

from tests.test_recursive_v2 import daily_series
from chanmodel.reference_engine import ReferenceSession
from workbench import live
from workbench.incremental import LiveSession


class LiveSessionLockTests(unittest.TestCase):
    def test_ingestion_is_serialized_without_emitting_a_reference_snapshot(self):
        code = 'sh600000'
        period = 'day'
        bars = daily_series(96).bars
        session = ReferenceSession(period, observe=True)
        for bar in bars:
            session.append(bar)
        resident = LiveSession(session, len(bars))
        receipt = {'received_at': bars[-1].closed_at, 'observed_at': bars[-1].closed_at}
        meta = {'checkpoint_sha256': 'snapshot-test-hash'}
        lock = live._key_lock(('incremental-session', code, period))
        lock_attempts = []

        def guarded_ingest(*args, **kwargs):
            def try_lock():
                acquired = lock.acquire(blocking=False)
                lock_attempts.append(acquired)
                if acquired:
                    lock.release()

            worker = threading.Thread(target=try_lock)
            worker.start()
            worker.join(timeout=2)
            if worker.is_alive():
                raise AssertionError('lock probe did not finish')
            return resident, tuple(bars), receipt, meta

        with patch.object(live, '_ingest_one', side_effect=guarded_ingest), \
             patch.object(ReferenceSession, 'snapshot', side_effect=AssertionError('legacy snapshot was called')):
            _, _, _, result = live._ingest(code, period)

        self.assertEqual(lock_attempts, [False])
        self.assertNotIn('report', result)
        self.assertEqual(result['checkpoint_sha256'], 'snapshot-test-hash')


if __name__ == '__main__':
    unittest.main()
