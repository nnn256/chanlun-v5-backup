"""Interactive quote requests must not queue behind the desktop's 90s startup."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from workbench import services


class ServiceStartupBudgetTests(unittest.TestCase):
    def test_waiting_for_another_initializer_respects_the_callers_budget(self):
        mutex = threading.Lock()
        mutex.acquire()
        try:
            with patch.object(services, 'LOCK', mutex), patch.object(services, 'LAST_RESULT', None), \
                 patch.object(services, 'OWNED_PROCESS', None), patch.object(services, 'probe') as probe:
                started = time.monotonic()
                with self.assertRaisesRegex(ValueError, '其他请求初始化'):
                    services.ensure_tdx(timeout=.05)
                elapsed = time.monotonic() - started
                probe.assert_not_called()
                self.assertGreaterEqual(elapsed, .035)
                self.assertLess(elapsed, .5)
        finally:
            mutex.release()

    def test_reusable_ready_result_returns_without_waiting_for_an_unrelated_lock(self):
        mutex = threading.Lock()
        mutex.acquire()
        try:
            observed = {'ready': True, 'received_at': 'known receipt'}
            with patch.object(services, 'LOCK', mutex), patch.object(services, 'LAST_RESULT', observed), \
                 patch.object(services, 'LAST_READY', time.monotonic()), patch.object(services, 'OWNED_PROCESS', None), \
                 patch.object(services, 'probe') as probe:
                self.assertIs(services.ensure_tdx(timeout=.05), observed)
                probe.assert_not_called()
        finally:
            mutex.release()

    def test_probe_and_retries_share_one_deadline_including_initial_probe(self):
        clock = [100.0]
        calls = []
        def probe(timeout):
            calls.append(timeout)
            clock[0] += timeout
            raise ConnectionRefusedError('no quote')
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / 'tdx.exe'
            binary.write_bytes(b'fixture')
            with patch.object(services, 'ROOT', root), patch.object(services, 'STATE', root / 'state'), \
                 patch.object(services, 'LOCK', threading.Lock()), patch.object(services, 'LAST_RESULT', None), \
                 patch.object(services, 'OWNED_PROCESS', process), patch.object(services, 'tdx_binary', return_value=binary), \
                 patch.object(services, 'endpoint', return_value='http://127.0.0.1:18080'), \
                 patch.object(services.time, 'monotonic', side_effect=lambda: clock[0]), \
                 patch.object(services.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
                 patch.object(services, 'probe', side_effect=probe), patch.object(services.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(ValueError, '尚未连接到上游|等待超过'):
                    services.ensure_tdx(timeout=8)
                self.assertAlmostEqual(clock[0], 108.0)
                self.assertEqual(calls[0], 3)
                self.assertTrue(all(0 < seconds <= 2 for seconds in calls[1:]))
                self.assertLess(calls[-1], 1)
                spawn.assert_not_called()
                process.terminate.assert_not_called()

    def test_short_budget_is_passed_to_the_first_probe_and_lock_is_released_after_failure(self):
        clock = [100.0]
        def probe(timeout):
            self.assertLessEqual(timeout, .2 + 1e-9)
            clock[0] += timeout
            raise TimeoutError('timed out')
        mutex = threading.Lock()
        with patch.object(services, 'LOCK', mutex), patch.object(services, 'LAST_RESULT', None), \
             patch.object(services, 'OWNED_PROCESS', None), \
             patch.object(services.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(services, 'probe', side_effect=probe), patch.object(services, 'tdx_binary') as binary:
            with self.assertRaisesRegex(ValueError, '等待超过'):
                services.ensure_tdx(timeout=.2)
            binary.assert_not_called()
        self.assertTrue(mutex.acquire(blocking=False))
        mutex.release()

    def test_second_request_reuses_the_first_initializers_success_instead_of_probing_again(self):
        entered = threading.Event()
        release = threading.Event()
        receipt = {'ready': True, 'received_at': 'first initializer'}
        def probe(timeout):
            entered.set()
            self.assertTrue(release.wait(2))
            return receipt
        with patch.object(services, 'LOCK', threading.Lock()), patch.object(services, 'LAST_RESULT', None), \
             patch.object(services, 'LAST_READY', 0), patch.object(services, 'OWNED_PROCESS', None), \
             patch.object(services, 'probe', side_effect=probe) as observed:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(services.ensure_tdx, 2)
                self.assertTrue(entered.wait(2))
                second = pool.submit(services.ensure_tdx, 2)
                release.set()
                self.assertEqual(first.result(2), receipt)
                self.assertEqual(second.result(2), receipt)
            observed.assert_called_once()


if __name__ == '__main__':
    unittest.main()
