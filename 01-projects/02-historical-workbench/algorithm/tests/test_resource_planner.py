import unittest
from unittest.mock import patch

from workbench.resources import GIB, MIB, plan_resources, admission_limit, hardware_snapshot


def host(logical=20, total=16 * GIB, available=10 * GIB):
    return {'cpu': {'logical_processors': logical},
            'memory': {'total_bytes': total, 'available_bytes': available}}


class ResourcePlannerTests(unittest.TestCase):
    def test_auto_preserves_interactive_cpu_and_memory_headroom(self):
        p = plan_resources('day', snapshot=host())
        self.assertGreater(p['workers'], 1)
        self.assertLess(p['workers'], 20)
        self.assertLessEqual(p['workers'] * p['per_worker_memory_bytes'] + p['memory_reserve_bytes'], 10 * GIB)

    def test_memory_pressure_waits_without_invalid_zero_process_pool(self):
        p = plan_resources('native_backtest', snapshot=host(available=512 * MIB))
        self.assertFalse(p['can_start'])
        self.assertEqual(p['admission_workers'], 0)
        self.assertGreaterEqual(p['workers'], 1)
        self.assertGreater(p['capacity_workers'], 1)
        self.assertEqual(admission_limit(p, host(available=512 * MIB)), 0)

    def test_manual_request_remains_a_cap_and_cannot_override_ram(self):
        p = plan_resources('multi', workers=12, snapshot=host(available=4 * GIB))
        self.assertEqual(p['policy'], 'manual')
        self.assertLess(p['workers'], 12)
        self.assertLessEqual(p['capacity_workers'], 12)
        self.assertLessEqual(plan_resources('day', workers=2, snapshot=host())['workers'], 2)

    def test_full_download_respects_shared_upstream_concurrency(self):
        p = plan_resources('full', snapshot=host(logical=64, total=128 * GIB, available=100 * GIB))
        self.assertLessEqual(p['capacity_workers'], 3)
        self.assertFalse(p['gpu_enabled'])
        self.assertEqual(p['compute_backend'], 'cpu')

    def test_native_backtest_can_use_more_than_legacy_twelve_with_ram(self):
        p = plan_resources('native_backtest', snapshot=host(total=64 * GIB, available=50 * GIB))
        self.assertGreater(p['workers'], 12)
        self.assertLessEqual(p['workers'], p['cpu_limit'])

    def test_pressure_drains_existing_workers_and_recovers_admission(self):
        p = plan_resources('day', snapshot=host())
        low = admission_limit(p, host(available=200 * MIB), active_workers=3)
        self.assertEqual(low, 3)
        high = admission_limit(p, host(available=12 * GIB), active_workers=3)
        self.assertGreater(high, low)
        self.assertLessEqual(high, p['capacity_workers'])
        self.assertEqual(admission_limit(p,host(available=100*MIB),active_workers=p['capacity_workers']+2),p['capacity_workers']+2)

    def test_unknown_memory_and_single_cpu_are_conservative(self):
        p = plan_resources('day', snapshot=host(logical=1, total=None, available=None))
        self.assertEqual(p['workers'], 1)
        self.assertEqual(p['capacity_workers'], 1)
        self.assertIn('memory_probe_unavailable', p['bottlenecks'])

    def test_invalid_manual_values_do_not_become_auto(self):
        for value in (True, False, -1, 1.5, '12'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan_resources('day', workers=value, snapshot=host())

    def test_probe_reads_dynamic_memory_and_returns_independent_inventory(self):
        observed = {'total_bytes': 16 * GIB, 'available_bytes': 4 * GIB, 'state': 'observed'}
        with patch('workbench.resources._memory', return_value=observed):
            first = hardware_snapshot()
            first['cpu']['model'] = 'mutated by UI'
            second = hardware_snapshot()
        self.assertEqual(second['memory']['available_bytes'], 4 * GIB)
        self.assertNotEqual(second['cpu']['model'], 'mutated by UI')


if __name__ == '__main__':
    unittest.main()
