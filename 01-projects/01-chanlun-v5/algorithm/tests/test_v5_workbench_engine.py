import unittest

from tests.test_recursive_v2 import daily_series
from workbench.v5_engine import CONFIG, MAX_RANK, PROFILE, analyze_inputs


class V5WorkbenchEngineTests(unittest.TestCase):
    def test_daily_report_uses_declared_recursive_profile(self):
        series = daily_series(140)
        result = analyze_inputs({'day': series}, series.bars[-1].closed_at)
        report = result['reports']['day']

        self.assertEqual(result['workbench_profile'], PROFILE)
        self.assertEqual(report['workbench_profile'], PROFILE)
        self.assertEqual(result['config']['stroke_mode'], 'strict')
        self.assertEqual(result['config']['second_policy'], 'conservative')
        self.assertEqual(result['config']['third_boundary'], 'strict_outside')
        self.assertEqual(result['max_rank'], MAX_RANK)
        self.assertEqual(MAX_RANK, 8)
        self.assertFalse(report['strict_original_equivalence_proven'])
        self.assertFalse(result['execution_allowed'])

    def test_config_cannot_fall_back_to_legacy_v2_defaults(self):
        self.assertEqual(CONFIG.stroke_mode, 'strict')
        self.assertEqual(CONFIG.second_policy, 'conservative')
        self.assertEqual(CONFIG.third_boundary, 'strict_outside')
        self.assertEqual(CONFIG.max_depth, 3)


if __name__ == '__main__':
    unittest.main()
