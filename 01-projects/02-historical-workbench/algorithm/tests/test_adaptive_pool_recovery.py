"""Resizing a process pool must drain work without killing or refilling it."""
from unittest.mock import Mock, patch
import unittest

from workbench.parallel import AdaptiveProcessPool


class AdaptivePoolRecoveryTests(unittest.TestCase):
    def test_recovered_memory_drains_two_worker_queue_then_grows(self):
        with patch('workbench.parallel.admission_limit', side_effect=[2, 8, 8, 8]), \
             patch('workbench.parallel.ProcessPoolExecutor') as factory:
            with AdaptiveProcessPool({'workers': 2, 'capacity_workers': 8}) as pool:
                self.assertEqual(pool.admission(0), 2)
                self.assertEqual(pool.admission(2), 2)
                self.assertTrue(pool.drain_pending)
                # One result completed. Returning two here would refill the
                # old pool forever, preventing a resize to eight processes.
                self.assertEqual(pool.admission(1), 1)
                factory.return_value.shutdown.assert_not_called()
                self.assertEqual(pool.admission(0), 8)
                self.assertFalse(pool.drain_pending)
                self.assertEqual(factory.call_count, 2)
                self.assertEqual(factory.call_args.kwargs['max_workers'], 8)

    def test_memory_pressure_drains_then_waits_without_starting_zero_workers(self):
        first, recovered = Mock(), Mock()
        with patch('workbench.parallel.admission_limit', side_effect=[4, 2, 1, 0, 0, 2]), \
             patch('workbench.parallel.ProcessPoolExecutor', side_effect=[first, recovered]) as factory:
            with AdaptiveProcessPool({'workers': 4, 'capacity_workers': 8}) as pool:
                self.assertEqual(pool.admission(0), 4)
                self.assertEqual(pool.admission(2), 2)
                self.assertEqual(pool.admission(1), 1)
                first.shutdown.assert_not_called()
                self.assertEqual(pool.admission(0), 0)
                first.shutdown.assert_called_once_with(wait=True)
                self.assertIsNone(pool.pool)
                self.assertEqual(pool.workers, 0)
                self.assertEqual(pool.admission(0), 0)
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(pool.admission(0), 2)
                self.assertEqual(factory.call_count, 2)
                self.assertIs(pool.pool, recovered)

    def test_transient_growth_request_cannot_resume_refilling_before_drain(self):
        with patch('workbench.parallel.admission_limit', side_effect=[3, 7, 3, 2, 3]), \
             patch('workbench.parallel.ProcessPoolExecutor') as factory:
            with AdaptiveProcessPool({'workers': 3, 'capacity_workers': 8}) as pool:
                self.assertEqual(pool.admission(0), 3)
                self.assertEqual(pool.admission(3), 3)
                self.assertTrue(pool.drain_pending)
                self.assertEqual(pool.admission(2), 2)
                self.assertEqual(pool.admission(1), 1)
                self.assertEqual(pool.admission(0), 3)
                self.assertFalse(pool.drain_pending)
                # Same final target can safely reuse the now-idle pool.
                self.assertEqual(factory.call_count, 1)

    def test_active_tasks_are_not_cancelled_or_shut_down_during_resize(self):
        executor = Mock()
        with patch('workbench.parallel.admission_limit', side_effect=[2, 6, 6]), \
             patch('workbench.parallel.ProcessPoolExecutor', return_value=executor):
            pool = AdaptiveProcessPool({'workers': 2, 'capacity_workers': 8})
            pool.admission(0)
            self.assertEqual(pool.admission(2), 2)
            self.assertEqual(pool.admission(1), 1)
            executor.shutdown.assert_not_called()
            executor.terminate.assert_not_called()
            self.assertTrue(pool.drain_pending)


if __name__ == '__main__': unittest.main()
