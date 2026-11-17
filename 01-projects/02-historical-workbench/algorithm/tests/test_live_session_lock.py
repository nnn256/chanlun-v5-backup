import threading
import unittest
from unittest.mock import patch

from tests.test_recursive_v2 import daily_series
from chanmodel.reference_engine import ReferenceSession
from workbench import live
from workbench.incremental import LiveSession


class LiveSessionLockTests(unittest.TestCase):
    def test_snapshot_is_built_while_shared_session_lock_is_held(self):
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
        original_snapshot = ReferenceSession.snapshot
        lock_attempts = []

        def guarded_snapshot(instance, *args, **kwargs):
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
            return original_snapshot(instance, *args, **kwargs)

        with patch.object(live, '_ingest_one', return_value=(resident, tuple(bars), receipt, meta)), \
             patch.object(ReferenceSession, 'snapshot', new=guarded_snapshot):
            _, _, _, result = live._ingest(code, period)

        self.assertEqual(lock_attempts, [False])
        self.assertEqual(result['report']['as_of'], bars[-1].closed_at)
        self.assertEqual(result['report']['input_sha256'], 'snapshot-test-hash')


if __name__ == '__main__':
    unittest.main()
